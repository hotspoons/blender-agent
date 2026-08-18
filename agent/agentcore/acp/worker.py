# SPDX-FileCopyrightText: 2026 agentcore contributors
#
# SPDX-License-Identifier: MIT OR Apache-2.0

"""
Driving worker sub-agents over ACP.

The ACP counterpart to ``worker_wire.ChatCompletionsWire``: same conversation,
same emitted events, real protocol underneath. The orchestrator is an ACP
client; each worker subprocess is an ACP agent.

What this buys over the chat-completions wire:

- **Cancellation is in-protocol.** ``session/cancel`` asks the worker to wind
  its turn down and report; the old wire could only drop the HTTP stream and
  kill the process, losing whatever the worker had done.
- **Steering is in-protocol.** A second ``session/prompt`` on a live session
  reaches a working agent -- legal in v2, which dropped turn-based semantics.
  The chat API had no way to say anything to a worker mid-turn.
- **Tool calls are first-class**, not vendor extension fields whose names each
  build has to agree on out of band.

Workers need no launch changes: ``agentcore.app.create_app`` mounts ACP at
``/acp`` on the agent's own port, so any worker this repo spawns already serves
it. Readiness is probed on ``/healthz`` rather than ``/v1/models`` so a worker
can eventually stop enabling the chat API at all.
"""

__all__ = (
    "AcpWire",
)

import logging
from typing import Any

from agentcore.acp.client import AcpClient
from agentcore.acp.updates import META_NAMESPACE
from agentcore.worker_wire import (
    EventSink,
    WorkerWire,
    normalize_tool_state,
    strip_data_urls,
)

_log = logging.getLogger("agentcore.acp.worker")

# ACP ToolCallStatus -> the harness tool_status states the UI renders. The
# inverse of updates._TOOL_STATUS, and lossy in the same place: ACP `failed`
# covers both a tool error and a declined call, so the harness's own state is
# read back out of _meta when the peer put it there.
_STATE_FROM_STATUS = {
    "pending": "running",
    "in_progress": "running",
    "completed": "ok",
    "failed": "error",
}


class AcpWire(WorkerWire):
    """
    Worker wire over ACP.

    One client connection per conversation. Sessions are not reused across
    tasks: a worker subprocess is created per task and torn down after, so
    there is nothing to reuse, and a fresh session keeps each task's transcript
    its own.
    """

    ready_path = "/healthz"

    def __init__(self, *, client_name: str = "agentcore-orchestrator") -> None:
        self._client_name = client_name
        # Live sessions by worker key, so steer/cancel can find them.
        self._live: "dict[str, tuple[AcpClient, str]]" = {}

    def endpoint(self, host: str, port: int) -> str:
        return "ws://{:s}:{:d}/acp".format(host, port)

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
        collected: "list[str]" = []

        async def on_update(_session_id: str, update: "dict[str, Any]") -> None:
            await self._translate(update, collected, emit)

        client = AcpClient(
            endpoint, api_key=api_key, client_name=self._client_name, on_update=on_update)
        await client.connect()
        session_id = ""
        try:
            meta: "dict[str, Any] | None" = None
            if seed_messages:
                # The parent conversation is forked in by seeding the worker's
                # session. ACP has no seed field, so it goes under the _meta
                # extension v2 reserves for exactly this; the receiving side
                # reads it in bridge._apply_seed.
                meta = {META_NAMESPACE: {"seedMessages": seed_messages, "pinUser": True}}
            session_id = await client.new_session(cwd="/", meta=meta)
            self._live[user] = (client, session_id)
            if cancel is not None:
                self._watch_cancel(cancel, client, session_id)
            stop_reason = await client.prompt(session_id, prompt)
            if stop_reason not in ("end_turn", "cancelled"):
                _log.info("acp/worker: %s stopped with %r", user, stop_reason)
        finally:
            self._live.pop(user, None)
            if session_id:
                await client.close_session(session_id)
            await client.aclose()
        return strip_data_urls("".join(collected)).strip()

    async def steer(self, endpoint: str, user: str, message: str, api_key: str = "") -> bool:
        """
        Land a message in a running worker's session.

        Uses the connection the conversation is already on: a second connection
        would get a different session and the guidance would go nowhere.
        """
        del endpoint, api_key
        live = self._live.get(user)
        if live is None:
            return False
        client, session_id = live
        try:
            await client.steer(session_id, message)
            return True
        except Exception as ex:  # pylint: disable=broad-except
            _log.warning("acp/worker: steering %s failed: %s", user, ex)
            return False

    def _watch_cancel(self, cancel: "Any", client: AcpClient, session_id: str) -> None:
        """
        Turn the stop flag into a ``session/cancel``.

        The subprocess still gets killed by the caller afterwards; asking first
        gives the worker the chance to stop cleanly and report what it managed,
        which the old wire could not do.
        """
        import asyncio

        async def waiter() -> None:
            try:
                await cancel.wait()
            except asyncio.CancelledError:
                return
            try:
                await client.cancel(session_id)
            except Exception as ex:  # pylint: disable=broad-except
                _log.debug("acp/worker: cancel of %s failed: %s", session_id, ex)

        asyncio.create_task(waiter())

    async def _translate(
            self,
            update: "dict[str, Any]",
            collected: "list[str]",
            emit: "EventSink | None",
    ) -> None:
        """
        Turn one ``session/update`` back into harness worker-card events.

        The inverse of ``acp.updates`` -- the orchestrator is a client here, so
        it consumes what a bridge produces. Emitting the harness's own
        vocabulary is what makes the two wires indistinguishable to the UI.
        """
        kind = str(update.get("sessionUpdate") or "")

        if kind == "agent_message_chunk":
            text = _text_of(update.get("content"))
            if text:
                collected.append(text)
                if emit is not None:
                    shown = strip_data_urls(text)
                    if shown:
                        await emit({"type": "token", "text": shown})
            return

        if kind == "agent_message":
            # The full message REPLACES the chunks streamed under the same id
            # (v2 patch semantics), so the report is rebuilt from it rather
            # than appended to what we already accumulated.
            text = _text_of(update.get("content"))
            if text:
                collected[:] = [text]
            return

        if kind == "tool_call_update":
            if emit is None:
                return
            extra = (update.get("_meta") or {}).get(META_NAMESPACE) or {}
            status = str(update.get("status") or "")
            # Prefer the peer's own state word when it sent one: ACP folds a
            # declined call and a failed one both into `failed`, losing the
            # distinction the UI shows. Either way it is normalized, so this
            # wire and the chat wire spell the same outcome the same.
            raw_state = str(extra.get("state") or _STATE_FROM_STATUS.get(status, "running"))
            await emit({
                "type": "tool_status",
                "call_id": str(update.get("toolCallId") or ""),
                "name": str(update.get("name") or update.get("title") or ""),
                "arguments": extra.get("arguments", ""),
                "state": normalize_tool_state(raw_state),
                "summary": _tool_summary(update.get("content")),
            })
            return

        if kind in ("agent_thought", "agent_thought_chunk", "user_message",
                    "user_message_chunk", "state_update", "session_info_update",
                    "plan_update", "plan_removed", "usage_update",
                    "available_commands_update", "config_option_update",
                    "terminal_update", "terminal_output_chunk",
                    "tool_call_content_chunk"):
            return

        _log.debug("acp/worker: ignoring update %r", kind)


def _text_of(content: "Any") -> str:
    """Flatten a content block, or a list of them, to text."""
    if isinstance(content, dict):
        return str(content.get("text") or "") if content.get("type") == "text" else ""
    if isinstance(content, list):
        return "".join(_text_of(block) for block in content)
    return ""


def _tool_summary(content: "Any") -> str:
    """The text a tool-call update carries as its result summary."""
    if not isinstance(content, list):
        return ""
    parts: "list[str]" = []
    for entry in content:
        if isinstance(entry, dict):
            parts.append(_text_of(entry.get("content")))
    return "".join(parts)
