# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
OpenAI-compatible chat-completions front end for the agent (modeled on
Foyer Studio's ``openai_proxy``): lets any OpenAI client chat with the
Blender agent — including media in both directions — with the agent's
tool calls surfaced as non-standard response properties and optionally
rendered inline in the message text.

Enabled and configured entirely by environment variables:

- ``BLENDER_AGENT_CHAT_API=1`` — expose ``POST /v1/chat/completions`` and
  ``GET /v1/models`` on the agent's HTTP port. Launching in this mode
  REQUIRES a remote LLM: ``BLENDER_AGENT_ENDPOINT`` and
  ``BLENDER_AGENT_MODEL`` (``BLENDER_AGENT_API_KEY`` optional) — the
  in-browser local model cannot serve headless API traffic.
- ``BLENDER_AGENT_CHAT_API_KEY`` — when set, requests must carry
  ``Authorization: Bearer <key>``.
- ``BLENDER_AGENT_CHAT_API_INLINE_TOOLS=1`` — additionally render tool
  calls as markdown blockquotes inside the assistant text, for plain
  OpenAI clients that ignore unknown fields.

Wire shape:

- Sessions are per client and persistent: the OpenAI ``user`` field (or
  an ``X-Client-Id`` header) maps deterministically to one agent session,
  so the agent-side transcript, media library and compaction all apply.
  Each request contributes its LAST user message as the new turn input;
  history lives server-side (clients may still send full history — prior
  messages are ignored).
- Tool calls appear as ``blender_tool_calls`` entries (``call_id``,
  ``name``, ``args_json``, ``status``: running/done/error, ``summary``)
  on streaming deltas and on the final message. Strict OpenAI clients
  ignore them.
- Media: clients send images as standard ``image_url`` data-URL content
  parts; tool-produced images come back as ``blender_media`` entries
  (id, mime, data_url) plus a markdown image in the text so plain-text
  clients see them too.
- Tool confirmation is impossible over a fire-and-forget API, so turns
  run with autonomy forced to ``auto``.
"""

__all__ = (
    "configure",
    "enabled",
    "routes",
)

import asyncio
import base64
import binascii
import hashlib
import json
import logging
import os
import re
import time
import uuid

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

_log = logging.getLogger("blagent.chat_api")

_TRUTHY = ("1", "true", "yes", "on")

# Per-event wait while a turn runs; a turn with no events for this long
# is presumed wedged and the response is closed with an error note.
_EVENT_TIMEOUT = 300.0

_MAX_ATTACHMENT = 8 * 1024 * 1024

_DATA_URL_RE = re.compile(r"^data:(?P<mime>[\w.+-]+/[\w.+-]+);base64,(?P<b64>.*)$", re.DOTALL)
_CLIENT_SLUG_RE = re.compile(r"[^A-Za-z0-9_-]+")


def enabled() -> bool:
    return os.environ.get("BLENDER_AGENT_CHAT_API", "").lower() in _TRUTHY


def _inline_tools() -> bool:
    return os.environ.get("BLENDER_AGENT_CHAT_API_INLINE_TOOLS", "").lower() in _TRUTHY


def _required_key() -> str:
    return os.environ.get("BLENDER_AGENT_CHAT_API_KEY", "")


def configure(runtime) -> None:
    """
    Validate and pin the runtime for API mode. Raises ``RuntimeError``
    when the required remote-LLM settings are missing.
    """
    config = runtime.store.config
    missing = [
        name for name, value in (
            ("BLENDER_AGENT_ENDPOINT", config.endpoint),
            ("BLENDER_AGENT_MODEL", config.model),
        ) if not value
    ]
    if missing:
        raise RuntimeError(
            "chat API mode (BLENDER_AGENT_CHAT_API=1) requires a remote LLM: "
            "set {:s} (BLENDER_AGENT_API_KEY optional)".format(", ".join(missing)))
    # The in-browser local model can't serve API traffic with no browser
    # attached; pin this process to the remote endpoint (not persisted).
    config.use_local_llm = False
    _log.info("chat API enabled: model=%s endpoint=%s inline_tools=%s auth=%s",
              config.model, config.endpoint, _inline_tools(), bool(_required_key()))


# -----------------------------------------------------------------------------
# Request parsing


def _auth_error() -> JSONResponse:
    return JSONResponse(
        {"error": {
            "message": "missing or invalid Authorization: Bearer <key>",
            "type": "invalid_request_error",
            "code": "invalid_api_key",
        }},
        status_code=401,
    )


def _request_error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse(
        {"error": {"message": message, "type": "invalid_request_error"}},
        status_code=status,
    )


def _check_auth(request: Request) -> bool:
    key = _required_key()
    if not key:
        return True
    header = request.headers.get("authorization", "")
    return header == "Bearer {:s}".format(key)


def client_session_id(body: dict[str, Any], request: Request) -> str:
    """
    Deterministic per-client session id: same client -> same persistent
    agent session across requests and restarts. Identity comes from the
    OpenAI ``user`` field, else an ``X-Client-Id`` header, else a shared
    anonymous bucket.
    """
    client = str(body.get("user") or request.headers.get("x-client-id") or "anonymous")
    slug = _CLIENT_SLUG_RE.sub("-", client).strip("-")[:32] or "client"
    digest = hashlib.sha1(client.encode("utf-8")).hexdigest()[:8]
    return "api-{:s}-{:s}".format(slug, digest)


def extract_user_input(messages: list) -> tuple[str, list[tuple[bytes, str, str | None]]]:
    """
    The newest user message becomes the turn input: joined text parts
    plus decoded attachments as ``(bytes, mime, filename|None)``.
    ``image_url`` data URLs carry images; ``file`` parts
    (``{"type": "file", "file": {"name", "b64"|"data", "mime"?}}``)
    carry anything else — meshes, audio, documents — destined for the
    session media folder where the ``media_io`` tool can import them.
    """
    last_user = None
    for message in messages or ():
        if isinstance(message, dict) and message.get("role") == "user":
            last_user = message
    if last_user is None:
        return "", []

    content = last_user.get("content")
    if isinstance(content, str):
        return content, []

    texts: list[str] = []
    attachments: list[tuple[bytes, str, str | None]] = []
    for part in content or ():
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text":
            texts.append(str(part.get("text", "")))
        elif part.get("type") == "image_url":
            url = str((part.get("image_url") or {}).get("url", ""))
            match = _DATA_URL_RE.match(url)
            if match is None:
                texts.append("[image attachment skipped: only data: URLs are fetched]")
                continue
            try:
                data = base64.b64decode(match.group("b64"), validate=True)
            except (binascii.Error, ValueError):
                continue
            if len(data) <= _MAX_ATTACHMENT:
                attachments.append((data, match.group("mime"), None))
        elif part.get("type") == "file":
            spec = part.get("file") or {}
            b64 = str(spec.get("b64") or spec.get("data") or "")
            try:
                data = base64.b64decode(b64, validate=True)
            except (binascii.Error, ValueError):
                continue
            if data and len(data) <= _MAX_ATTACHMENT:
                name = str(spec.get("name") or "attachment.bin")
                attachments.append((data, str(spec.get("mime") or ""), name))
    return "\n".join(t for t in texts if t), attachments


# -----------------------------------------------------------------------------
# Event translation

_TOOL_GLYPHS = {"running": "🔧", "done": "✅"}


class EventTranslator:
    """
    Folds runtime broadcast events for one session into OpenAI-delta
    fragments: ``{"content": str, "blender_tool_calls": [...],
    "blender_media": [...]}`` per event (empty dict = nothing to send).
    Pure apart from reading media bytes, so it is unit-testable.
    """

    def __init__(self, media_library, inline_tools: bool) -> None:
        self._media = media_library
        self._inline = inline_tools
        self.tool_calls: dict[str, dict[str, Any]] = {}
        self.media: list[dict[str, str]] = []
        self.text_parts: list[str] = []
        self.done = False

    def feed(self, event: dict[str, Any]) -> dict[str, Any]:
        kind = event.get("type")
        if kind == "token":
            self._note_text(event.get("text", ""))
            return {"content": event.get("text", "")}
        if kind == "tool_status":
            return self._feed_tool(event)
        if kind == "error":
            note = "\n\n> ⚠️ {:s}\n".format(str(event.get("message", "agent error")))
            self._note_text(note)
            return {"content": note}
        if kind == "turn_done":
            self.done = True
        return {}

    def _note_text(self, text: str) -> None:
        if text:
            self.text_parts.append(text)

    def _feed_tool(self, event: dict[str, Any]) -> dict[str, Any]:
        status = {
            "running": "running",
            "done": "done",
            "pending_confirm": "running",
        }.get(str(event.get("state")), "error")
        entry: dict[str, Any] = {
            "call_id": event.get("call_id", ""),
            "name": event.get("name", ""),
            "args_json": event.get("arguments", ""),
            "status": status,
        }
        if event.get("summary") is not None:
            entry["summary"] = event.get("summary")
        self.tool_calls[str(entry["call_id"]) + ":" + status] = entry

        delta: dict[str, Any] = {"blender_tool_calls": [entry]}
        content = ""
        if self._inline:
            glyph = _TOOL_GLYPHS.get(status, "❌")
            args_preview = str(entry["args_json"] or "")[:120]
            if status == "running":
                content += "\n> {:s} `{:s}({:s})`\n".format(glyph, entry["name"], args_preview)
            else:
                content += "\n> {:s} `{:s}` — {:s}\n".format(
                    glyph, entry["name"], str(entry.get("summary", ""))[:200])

        for media_id in event.get("media_ids") or ():
            data_url = self._data_url(str(media_id))
            if data_url is None:
                continue
            item = {"id": str(media_id), "data_url": data_url}
            self.media.append(item)
            delta.setdefault("blender_media", []).append(item)
            # Markdown image so text-only clients receive the bytes too.
            content += "\n![{:s}]({:s})\n".format(media_id, data_url)

        if content:
            self._note_text(content)
            delta["content"] = content
        return delta

    def _data_url(self, media_id: str) -> str | None:
        if self._media is None:
            return None
        item = self._media.get(media_id)
        data = self._media.read_base64(media_id)
        if item is None or data is None:
            return None
        return "data:{:s};base64,{:s}".format(item.mime, data)

    def merged_tool_calls(self) -> list[dict[str, Any]]:
        """
        One entry per call id, terminal status winning over "running".
        """
        merged: dict[str, dict[str, Any]] = {}
        for entry in self.tool_calls.values():
            call_id = str(entry["call_id"])
            existing = merged.get(call_id)
            if existing is None or existing["status"] == "running":
                merged[call_id] = entry
        return list(merged.values())


# -----------------------------------------------------------------------------
# Response assembly


def _chunk(completion_id: str, created: int, model: str,
           delta: dict[str, Any], finish: str | None = None) -> str:
    payload = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return "data: {:s}\n\n".format(json.dumps(payload))


def routes(runtime) -> list[Route]:
    """
    The ``/v1`` routes, bound to *runtime*.
    """

    async def models(request: Request) -> Response:
        if not _check_auth(request):
            return _auth_error()
        return JSONResponse({
            "object": "list",
            "data": [{
                "id": "blender-agent",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "blender-mcp-agent",
            }],
        })

    async def chat_completions(request: Request) -> Response:
        if not _check_auth(request):
            return _auth_error()
        try:
            body = await request.json()
        except ValueError:
            return _request_error("invalid JSON body")

        text, attachments = extract_user_input(body.get("messages") or [])
        if not text and not attachments:
            return _request_error("no user message found in 'messages'")

        session_id = client_session_id(body, request)
        session = runtime._get_or_load_session(session_id)  # pylint: disable=protected-access
        if session.busy:
            return _request_error(
                "a turn is already running for this client", status=409)

        media_ids = [
            (session.media.register_named_bytes(data, name, mime=mime or None)
             if name else
             session.media.register_bytes(data, mime=mime, label="api attachment"))
            for data, mime, name in attachments
        ]

        queue = runtime.subscribe()
        try:
            await runtime.send_user_message(
                session_id, text or "(see attached media)",
                media_ids=media_ids, autonomy="auto")
        except RuntimeError as ex:
            runtime.unsubscribe(queue)
            return _request_error(str(ex), status=409)
        except Exception:
            runtime.unsubscribe(queue)
            raise

        completion_id = "chatcmpl-{:s}".format(uuid.uuid4().hex)
        created = int(time.time())
        model = str(body.get("model") or runtime.store.config.model or "blender-agent")
        translator = EventTranslator(session.media, _inline_tools())

        async def events():
            while not translator.done:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=_EVENT_TIMEOUT)
                except asyncio.TimeoutError:
                    yield translator.feed({
                        "type": "error",
                        "session_id": session_id,
                        "message": "turn timed out (no agent events for {:.0f}s)".format(
                            _EVENT_TIMEOUT),
                    })
                    break
                if event.get("session_id") != session_id:
                    continue
                delta = translator.feed(event)
                if delta:
                    yield delta

        if body.get("stream"):
            async def sse():
                try:
                    yield _chunk(completion_id, created, model, {"role": "assistant"})
                    async for delta in events():
                        yield _chunk(completion_id, created, model, delta)
                    yield _chunk(completion_id, created, model, {}, finish="stop")
                    yield "data: [DONE]\n\n"
                finally:
                    runtime.unsubscribe(queue)

            return StreamingResponse(sse(), media_type="text/event-stream")

        try:
            async for _delta in events():
                pass
        finally:
            runtime.unsubscribe(queue)

        full_text = "".join(translator.text_parts)
        content: Any = full_text
        if translator.media:
            content = [{"type": "text", "text": full_text}] + [
                {"type": "image_url", "image_url": {"url": m["data_url"]}}
                for m in translator.media
            ]
        message: dict[str, Any] = {"role": "assistant", "content": content}
        tool_calls = translator.merged_tool_calls()
        if tool_calls:
            message["blender_tool_calls"] = tool_calls

        return JSONResponse({
            "id": completion_id,
            "object": "chat.completion",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        })

    return [
        Route("/v1/models", models),
        Route("/v1/chat/completions", chat_completions, methods=["POST"]),
    ]
