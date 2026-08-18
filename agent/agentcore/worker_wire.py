# SPDX-FileCopyrightText: 2026 agentcore contributors
#
# SPDX-License-Identifier: MIT OR Apache-2.0

"""
The wire between an orchestrator and one worker agent.

``RemoteWorkerStrategy`` owns a worker's whole lifecycle -- ports, subprocess,
artifact collection, prompts, gather -- but only ONE part of that is protocol:
sending the task and streaming back what the worker did. This module is that
part, factored out so the protocol can be swapped without touching the
lifecycle.

Three implementations, deliberately:

- ``ChatCompletionsWire`` -- the original: the worker's OpenAI-compatible
  ``/v1/chat/completions`` plus SSE, with non-standard ``tool_calls`` / ``media``
  delta fields. Works, but it is a chat API pressed into service as an agent
  control protocol: there is no cancel, no steer, and tool calls ride in
  vendor extensions.
- ``AcpWire`` (see ``agentcore.acp.worker``) -- the same conversation over the
  Agent Client Protocol, where cancellation, steering and tool-call reporting
  are first-class.
- ``LocalWire`` -- the in-process case. A worker running in this process needs
  no wire at all, so this exists to keep the seam honest rather than
  theoretical: it names the third case and fails loudly if something routes
  through it by mistake.

Every wire reports activity by emitting the harness's own event vocabulary
(``token``, ``tool_status``, ``worker_media``), so the UI cannot tell which one
produced a run. That is the property the parity check depends on.
"""

__all__ = (
    "ChatCompletionsWire",
    "EventSink",
    "LocalWire",
    "WORKER_TOOL_STATES",
    "WorkerWire",
    "normalize_tool_state",
    "strip_data_urls",
)

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable

_log = logging.getLogger("agentcore.worker_wire")

# Emits one harness event for a worker's card.
EventSink = Callable[["dict[str, Any]"], Awaitable[None]]

# Markdown image with an inlined data: URL -- chat_api adds these to the
# assistant text so plain clients still receive tool media. Media is surfaced
# as its own event, so these (often huge) blobs are stripped from the prose.
_DATA_URL_MD_RE = re.compile(r"!\[[^\]]*\]\(data:[^)]*\)")


def strip_data_urls(text: str) -> str:
    """Drop inlined data-URL images from prose (they are emitted separately)."""
    return _DATA_URL_MD_RE.sub("", text)


# The tool states a worker card renders (see web/components/chat-stage.js).
# Every wire normalizes onto these, so a run looks the same whichever produced
# it -- that sameness is the whole basis of the parity check.
WORKER_TOOL_STATES = ("running", "ok", "error", "rejected", "pending_confirm")

# Success is spelled differently at each source: the engine emits "done", the
# chat API reports "done" too, and ACP calls it "completed". A worker card has
# always been shown "ok", so that is the canonical word.
_SUCCESS_WORDS = frozenset({"done", "ok", "completed"})


def normalize_tool_state(state: str) -> str:
    """Fold a producer's own state word onto the worker-card vocabulary."""
    if state in _SUCCESS_WORDS:
        return "ok"
    return state if state in WORKER_TOOL_STATES else "error"


class WorkerWire(ABC):
    """
    How to reach one worker and hold one conversation with it.

    Stateless with respect to a given worker: the endpoint is passed in, so a
    single wire instance serves every worker in a run.
    """

    # Extra environment a worker subprocess needs in order to serve this wire.
    launch_env: "dict[str, str]" = {}

    # Path on the worker's HTTP port that answers once it is ready to work.
    ready_path = "/v1/models"

    @abstractmethod
    def endpoint(self, host: str, port: int) -> str:
        """The address this wire talks to for a worker on *host*:*port*."""

    @abstractmethod
    async def converse(
        self,
        endpoint: str,
        prompt: str,
        *,
        user: str,
        emit: "EventSink | None" = None,
        cancel: "Any | None" = None,
        seed_messages: "list[dict[str, Any]] | None" = None,
        timeout: float = 900.0,
        api_key: str = "",
    ) -> str:
        """
        Give the worker its task and return its final report.

        *emit* receives harness events as the worker works; when it is None the
        wire may skip streaming entirely. *cancel* is an ``asyncio.Event`` that
        breaks the exchange early. *seed_messages* forks the parent
        conversation into the worker's session.
        """

    async def steer(self, endpoint: str, user: str, message: str, api_key: str = "") -> bool:
        """
        Inject guidance into a worker that is already working.

        False when the wire cannot do it, which the caller should treat as "the
        message will have to wait for a round boundary" rather than an error.
        """
        del endpoint, user, message, api_key
        return False

    @property
    def supports_steering(self) -> bool:
        return type(self).steer is not WorkerWire.steer


class ChatCompletionsWire(WorkerWire):
    """
    The original wire: the worker's OpenAI-compatible chat API over SSE.

    Tool calls and media arrive in non-standard delta fields whose names differ
    per build (``blagent.chat_api`` brands them ``blender_tool_calls`` /
    ``blender_media``), so the field names are constructor arguments rather
    than hardcoded.
    """

    def __init__(
            self,
            *,
            model: str = "agent",
            tool_calls_key: str = "tool_calls",
            media_key: str = "media",
    ) -> None:
        self._model = model
        self._tool_calls_key = tool_calls_key
        self._media_key = media_key

    def endpoint(self, host: str, port: int) -> str:
        return "http://{:s}:{:d}/v1".format(host, port)

    async def converse(
            self,
            endpoint: str,
            prompt: str,
            *,
            user: str,
            emit: "EventSink | None" = None,
            cancel: "Any | None" = None,
            seed_messages: "list[dict[str, Any]] | None" = None,
            timeout: float = 900.0,
            api_key: str = "",
    ) -> str:
        import httpx  # pylint: disable=import-error

        headers = {"Authorization": "Bearer " + api_key} if api_key else {}
        stream = emit is not None
        body: "dict[str, Any]" = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "user": user,
            "stream": stream,
        }
        if seed_messages:
            # Fork extension (see blagent.chat_api): the worker seeds its
            # session with this conversation and pins the mission message.
            body["seed_messages"] = seed_messages
            body["pin_user"] = True

        if not stream:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    endpoint + "/chat/completions", json=body, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            message = (data.get("choices") or [{}])[0].get("message") or {}
            return str(message.get("content") or "")

        text_parts: "list[str]" = []
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                    "POST", endpoint + "/chat/completions",
                    json=body, headers=headers) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if cancel is not None and cancel.is_set():
                        break
                    if not line.startswith("data: "):
                        continue
                    payload = line[len("data: "):].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except ValueError:
                        continue
                    delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                    await self._stream_delta(delta, text_parts, emit)
        # Strip inlined data-URL images from the proof; media is surfaced
        # separately and the raw blobs would bloat the report.
        return strip_data_urls("".join(text_parts)).strip()

    async def _stream_delta(
            self,
            delta: "dict[str, Any]",
            text_parts: "list[str]",
            emit: "EventSink | None",
    ) -> None:
        """Translate one OpenAI delta into worker-card events."""
        if emit is None:
            return
        content = delta.get("content")
        if content:
            text_parts.append(str(content))
            shown = strip_data_urls(str(content))
            if shown:
                await emit({"type": "token", "text": shown})
        for call in delta.get(self._tool_calls_key) or ():
            state = normalize_tool_state(str(call.get("status")))
            await emit({
                "type": "tool_status",
                "call_id": str(call.get("call_id", "")),
                "name": str(call.get("name", "")),
                "arguments": call.get("args_json", ""),
                "state": state,
                "summary": call.get("summary", ""),
            })
        for media in delta.get(self._media_key) or ():
            data_url = media.get("data_url")
            if data_url:
                await emit({
                    "type": "worker_media",
                    "media_id": str(media.get("id", "")),
                    "data_url": str(data_url),
                })


class LocalWire(WorkerWire):
    """
    Placeholder for an in-process worker, which has no wire.

    In-process workers are driven by calling ``AgentEngine`` directly, with no
    serialization in the path. This class exists so the third isolation mode is
    named at the seam instead of being an unstated assumption -- and so that if
    the orchestrator ever routes an in-process worker through a wire by
    mistake, it fails here with an explanation rather than silently paying for
    a loopback.
    """

    def endpoint(self, host: str, port: int) -> str:
        del host, port
        return "local://in-process"

    async def converse(self, endpoint: str, prompt: str, **_kwargs: Any) -> str:
        del endpoint, prompt
        raise NotImplementedError(
            "in-process workers are driven through AgentEngine directly, not over a "
            "wire; see AgentRuntime._make_worker_runner. Reaching this means an "
            "in-process worker was routed through the remote strategy.")
