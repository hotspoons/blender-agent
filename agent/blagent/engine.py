# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Single-turn agent loop, ported from Foyer Studio's
``foyer-agent/src/engine.rs``.

One turn = the user speaks once, then the loop alternates LLM rounds
and tool dispatch until the model stops calling tools or the round
budget runs out (extendable mid-turn via ``continue_working``).

Destructive tool calls pause for confirmation when autonomy is
``ask`` - the gate awaits a decision delivered by the runtime.

Tool-produced images are registered in the media library and fed back
into the next round's context as a synthetic user message so
vision-capable models can see what they just did.
"""

__all__ = (
    "AgentEngine",
    "EngineEvents",
)

import asyncio
import json
import logging
import time

from typing import Any, Awaitable, Callable

from .llm import LlmClient, LlmError
from .media import MediaLibrary
from .tools import ToolContext, ToolError, ToolRegistry, TurnBudget

_log = logging.getLogger("blagent.engine")

# Records the model sees, counted from the end of the transcript.
_CONTEXT_RECORD_LIMIT = 80
# Cap on tool result JSON fed back to the model, per call.
_TOOL_RESULT_CHAR_LIMIT = 24_000
# Seconds to wait on the ask-mode confirmation gate before giving up.
_CONFIRM_TIMEOUT = 600.0

EngineEvents = Callable[[dict[str, Any]], Awaitable[None]]


def _now() -> float:
    return time.time()


def _messages_have_images(messages: list[dict[str, Any]]) -> bool:
    """
    True when any message carries image content parts.
    """
    for message in messages:
        content = message.get("content")
        if isinstance(content, list) and any(
                isinstance(p, dict) and p.get("type") == "image_url" for p in content):
            return True
    return False


def _clip_result_data(data: object, limit: int = 20_000) -> object:
    """
    Result payload for tool-status UI events, size-capped so a huge
    tool result never bloats the socket (the full payload still goes
    to the model via the transcript, separately truncated).
    """
    try:
        text = json.dumps(data)
    except (TypeError, ValueError):
        return {"repr": repr(data)[:limit]}
    if len(text) <= limit:
        return data
    return {"truncated_preview": text[:limit]}


class AgentEngine:
    """
    Runs turns for one session. The runtime owns instances of this and
    serializes turns per session.
    """

    def __init__(
            self,
            registry: ToolRegistry,
            media: MediaLibrary,
            system_prompt: str,
            emit: EngineEvents,
            append_record: Callable[[dict[str, Any]], None],
    ) -> None:
        self._registry = registry
        self._media = media
        self._system_prompt = system_prompt
        self._emit = emit
        self._append_record = append_record
        self.records: list[dict[str, Any]] = []
        # call_id -> Future resolved by the runtime on user confirm/deny.
        self.pending_confirms: dict[str, asyncio.Future[bool]] = {}
        # Cleared when the endpoint rejects image content (text-only
        # model, e.g. vLLM without an image encoder) - the transcript
        # then renders media as text placeholders instead.
        self.vision_ok = True

    # ------------------------------------------------------------------
    # Transcript helpers.

    def push_record(self, record: dict[str, Any]) -> None:
        record.setdefault("ts", _now())
        self.records.append(record)
        self._append_record(record)

    def _llm_messages(self) -> list[dict[str, Any]]:
        """
        Project the transcript into OpenAI chat messages.
        """
        messages: list[dict[str, Any]] = [{"role": "system", "content": self._system_prompt}]
        for record in self.records[-_CONTEXT_RECORD_LIMIT:]:
            role = record.get("role")
            if role == "user":
                media_ids = record.get("media_ids") or []
                text = str(record.get("content", ""))
                if media_ids and not self.vision_ok:
                    # Tell a blind model the truth - a bare "[Attached:
                    # media i4]" placeholder reads like an image it
                    # should describe, and text-only models will
                    # confidently confabulate a description.
                    text += (
                        "\n(note: media {:s} exists but you are connected as a TEXT-ONLY "
                        "model and cannot see images. Never describe or pretend to see "
                        "them - inspect the scene with tools, or ask the user to look.)"
                    ).format(", ".join(media_ids))
                    media_ids = []
                content = self._content_with_images(text, media_ids)
                messages.append({"role": "user", "content": content})
            elif role == "assistant":
                message: dict[str, Any] = {"role": "assistant", "content": record.get("content", "")}
                tool_calls = record.get("tool_calls") or []
                if tool_calls:
                    message["tool_calls"] = [
                        {
                            "id": call["id"],
                            "type": "function",
                            "function": {"name": call["name"], "arguments": call["arguments"]},
                        }
                        for call in tool_calls
                    ]
                messages.append(message)
            elif role == "tool":
                messages.append({
                    "role": "tool",
                    "tool_call_id": record.get("tool_call_id", ""),
                    "content": str(record.get("content", "")),
                })
        return messages

    def _content_with_images(self, text: str, media_ids: list[str]) -> object:
        if not media_ids:
            return text
        parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
        for media_id in media_ids:
            payload = self._media.read_base64(media_id)
            item = self._media.get(media_id)
            if payload is None or item is None:
                continue
            parts.append({
                "type": "image_url",
                "image_url": {"url": "data:{:s};base64,{:s}".format(item.mime, payload)},
            })
        return parts

    # ------------------------------------------------------------------
    # The turn loop.

    async def run_turn(
            self,
            session_id: str,
            user_text: str,
            llm: LlmClient,
            model: str,
            autonomy: str,
            max_rounds: int,
            media_ids: list[str] | None = None,
    ) -> None:
        """
        Run one full turn. Events are emitted through the runtime's
        broadcast callback; records are appended to the transcript.
        *media_ids* are user-attached images (pasted/dropped in the UI).
        """
        _log.info("turn start session=%s model=%s attachments=%s", session_id, model, media_ids or [])
        user_record: dict[str, Any] = {"role": "user", "content": user_text}
        if media_ids:
            user_record["media_ids"] = media_ids
        self.push_record(user_record)
        await self._emit({
            "type": "user_record",
            "session_id": session_id,
            "content": user_text,
            "media_ids": media_ids or [],
        })

        budget = TurnBudget(rounds_left=max_rounds, rounds_max=max_rounds * 2)
        ctx = ToolContext(media=self._media, turn_budget=budget, session_id=session_id)
        # Media produced by tools in the previous round, fed to the
        # model as a synthetic user record on the next one.
        feedback_media: list[str] = []
        # Some models go silent after tool results (no text, no calls).
        # Nudge them to wrap up for the user - a bounded number of times.
        nudges_left = 2
        turn_had_tool_calls = False

        while True:
            if feedback_media:
                self.push_record({
                    "role": "user",
                    "content": "[Attached: tool-produced media {:s} from the previous step]".format(
                        ", ".join(feedback_media)),
                    "media_ids": feedback_media,
                    "synthetic": True,
                })
                feedback_media = []

            request: dict[str, Any] = {
                "model": model,
                "messages": self._llm_messages(),
                "tools": self._registry.specs(),
            }

            try:
                content, tool_calls = await self._stream_round(session_id, request, llm)
            except LlmError as ex:
                if self.vision_ok and _messages_have_images(request["messages"]):
                    # Endpoint rejected image content (text-only model,
                    # e.g. vLLM without an image encoder). Degrade to
                    # text placeholders for the rest of this session
                    # and retry the round once.
                    self.vision_ok = False
                    _log.warning("endpoint rejected image content; retrying text-only: %s", ex)
                    await self._emit({
                        "type": "error",
                        "session_id": session_id,
                        "message": "Model rejected image input (text-only model?) - "
                                   "continuing with text placeholders for media.",
                    })
                    request["messages"] = self._llm_messages()
                    content, tool_calls = await self._stream_round(session_id, request, llm)
                else:
                    _log.error("LLM round failed: %s", ex)
                    raise

            record: dict[str, Any] = {"role": "assistant", "content": content}
            if tool_calls:
                record["tool_calls"] = tool_calls
            self.push_record(record)
            await self._emit({
                "type": "assistant_done",
                "session_id": session_id,
                "content": content,
                "tool_calls": [
                    {"id": c["id"], "name": c["name"], "arguments": c["arguments"]}
                    for c in tool_calls
                ],
            })

            if not tool_calls:
                if not content.strip() and turn_had_tool_calls and nudges_left > 0:
                    # Empty close-out after tool work: nudge for a
                    # user-facing summary instead of ending in silence.
                    nudges_left -= 1
                    self.push_record({
                        "role": "user",
                        "content": (
                            "(Your last message was empty. Briefly tell the user what was "
                            "done and what the outcome was, or continue with tool calls "
                            "if the work is unfinished.)"
                        ),
                        "synthetic": True,
                    })
                    continue
                break
            turn_had_tool_calls = True
            if budget.rounds_left <= 0:
                await self._emit({
                    "type": "error",
                    "session_id": session_id,
                    "message": "Turn round budget exhausted; stopping. Send a follow-up to continue.",
                })
                break
            budget.rounds_left -= 1

            declined = False
            for index, call in enumerate(tool_calls):
                if declined:
                    # A declined call ends the batch: record the rest as
                    # skipped so the model sees an honest transcript.
                    message = "skipped: an earlier tool call in this batch was declined by the user"
                    self._push_tool_record(call["id"], {"status": "skipped", "message": message})
                    await self._emit({
                        "type": "tool_status",
                        "session_id": session_id,
                        "call_id": call["id"],
                        "name": call["name"],
                        "arguments": call["arguments"],
                        "state": "rejected",
                        "summary": message,
                    })
                    continue
                media_ids, was_declined = await self._dispatch_tool(session_id, ctx, call, autonomy)
                feedback_media.extend(media_ids)
                declined = declined or was_declined
                del index

            if declined:
                # Pause the whole turn instead of letting the model retry
                # into more declines - the user steers with their next
                # message (the rejected results are in the transcript).
                await self._emit({
                    "type": "error",
                    "session_id": session_id,
                    "message": "Tool call declined - turn paused. Send a message to tell the agent how to proceed.",
                })
                break

        await self._emit({"type": "turn_done", "session_id": session_id})

    async def _stream_round(
            self,
            session_id: str,
            request: dict[str, Any],
            llm: LlmClient,
    ) -> tuple[str, list[dict[str, Any]]]:
        """
        Stream one LLM round, emitting token events; reassemble content
        and tool calls from the deltas.
        """
        content_parts: list[str] = []
        # index -> {id, name, arguments}
        calls: dict[int, dict[str, Any]] = {}

        async for chunk in llm.stream(request):
            if chunk.content:
                content_parts.append(chunk.content)
                await self._emit({"type": "token", "session_id": session_id, "text": chunk.content})
            for delta in chunk.tool_calls:
                index = int(delta.get("index", 0))
                slot = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                if delta.get("id"):
                    slot["id"] = delta["id"]
                function = delta.get("function") or {}
                if function.get("name"):
                    slot["name"] += function["name"]
                if function.get("arguments"):
                    slot["arguments"] += function["arguments"]

        tool_calls = []
        for index in sorted(calls):
            slot = calls[index]
            if not slot["id"]:
                slot["id"] = "call_{:d}_{:d}".format(int(_now() * 1000), index)
            if slot["name"]:
                tool_calls.append(slot)
        return "".join(content_parts), tool_calls

    async def _dispatch_tool(
            self,
            session_id: str,
            ctx: ToolContext,
            call: dict[str, Any],
            autonomy: str,
    ) -> tuple[list[str], bool]:
        """
        Run one tool call through the autonomy gate and dispatch.
        Returns ``(media_ids, declined)`` - media for the vision
        feedback loop, and whether the user declined the call.
        """
        name = call["name"]
        call_id = call["id"]
        tool = self._registry.get(name)

        async def status(state: str, **extra: object) -> None:
            await self._emit({
                "type": "tool_status",
                "session_id": session_id,
                "call_id": call_id,
                "name": name,
                "arguments": call["arguments"],
                "state": state,
                **extra,
            })

        if tool is None:
            message = "unknown tool: {:s}".format(name)
            await status("error", summary=message)
            self._push_tool_record(call_id, {"status": "error", "message": message})
            return [], False

        try:
            args = json.loads(call["arguments"]) if call["arguments"].strip() else {}
        except ValueError as ex:
            message = "tool arguments are not valid JSON: {:s}".format(str(ex))
            await status("error", summary=message)
            self._push_tool_record(call_id, {"status": "error", "message": message})
            return [], False

        # Autonomy gate: destructive tools pause in ask mode.
        if tool.destructive and autonomy == "ask":
            future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
            self.pending_confirms[call_id] = future
            await status("pending_confirm")
            try:
                approved = await asyncio.wait_for(future, timeout=_CONFIRM_TIMEOUT)
            except asyncio.TimeoutError:
                approved = False
            finally:
                self.pending_confirms.pop(call_id, None)
            if not approved:
                message = "user declined this tool call"
                await status("rejected", summary=message)
                self._push_tool_record(call_id, {"status": "rejected", "message": message})
                return [], True

        await status("running")
        _log.info("tool call %s %s", name, call["arguments"][:200])
        try:
            result = await tool.call(ctx, args)
        except ToolError as ex:
            await status("error", summary=str(ex))
            self._push_tool_record(call_id, {"status": "error", "message": str(ex)})
            return [], False
        except Exception as ex:  # pylint: disable=broad-exception-caught
            message = "{:s}: {:s}".format(type(ex).__name__, str(ex))
            await status("error", summary=message)
            self._push_tool_record(call_id, {"status": "error", "message": message})
            return [], False

        payload: dict[str, Any] = {"status": "ok", "result": result.data}
        if result.media_ids:
            payload["media_ids"] = result.media_ids
        self._push_tool_record(call_id, payload)
        await status(
            "done",
            summary=result.summary,
            media_ids=result.media_ids,
            data=_clip_result_data(result.data),
        )
        return result.media_ids, False

    def _push_tool_record(self, call_id: str, payload: dict[str, Any]) -> None:
        text = json.dumps(payload)
        if len(text) > _TOOL_RESULT_CHAR_LIMIT:
            text = text[:_TOOL_RESULT_CHAR_LIMIT] + "... [truncated]"
        self.push_record({"role": "tool", "tool_call_id": call_id, "content": text})

    # ------------------------------------------------------------------
    # Confirm gate plumbing (called by the runtime).

    def resolve_confirm(self, call_id: str, approve: bool) -> bool:
        future = self.pending_confirms.get(call_id)
        if future is None or future.done():
            return False
        future.set_result(approve)
        return True
