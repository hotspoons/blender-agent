# SPDX-FileCopyrightText: 2026 agentcore contributors
#
# SPDX-License-Identifier: MIT OR Apache-2.0

"""
Translation from harness events to ACP ``session/update`` notifications.

The harness emits a flat, self-invented event vocabulary (``token``,
``tool_status``, ``turn_done``, ...). ACP has its own. This module is the only
place that knows both, so the runtime keeps emitting what its own web UI
already consumes and ACP clients still get spec-shaped updates.

Not everything maps. Objectives, DAG views and worker cards are harness
concepts with no ACP counterpart; rather than invent variants (which a strict
client would reject) they ride under ``_meta``, which is precisely what v2
reserves it for. A client that understands them can read them; one that does
not ignores them and still sees a correct conversation.
"""

__all__ = (
    "META_NAMESPACE",
    "SessionTranslator",
    "stop_reason_for",
)

from typing import Any

from agentcore.acp import wire

# Harness-specific payloads live under one key so they can never collide with
# a field ACP adds later.
META_NAMESPACE = "ai.patapsco.blender-agent"

# Harness tool states -> ACP ToolCallStatus.
_TOOL_STATUS = {
    "pending_confirm": "pending",
    "running": "in_progress",
    "done": "completed",
    "ok": "completed",
    "error": "failed",
    "rejected": "failed",
}

# Events the UI needs but ACP has no vocabulary for. Carried as _meta so a
# harness-aware client keeps its orchestrator view.
_META_ONLY = frozenset({
    "agent_done",
    "agent_spawned",
    "autonomy_goal",
    "autonomy_view",
    "objectives_draft",
    "objectives_update",
    "orchestrator_review",
    "planner_stream",
    "swarm_gathered",
    "worker_media",
    "worker_question",
    "worker_question_answered",
    "worker_review",
})

# Purely local concerns: connection heartbeats, UI config echoes, and the
# browser-hosted model's status. An ACP client has no use for any of it.
_IGNORED = frozenset({
    "compacted",
    "config",
    "hello",
    "instance",
    "llm_quiet",
    "local_llm_status",
    "models",
    "pong",
    "session_loaded",
    "sessions",
    "tool_drafting",
})


def stop_reason_for(event: "dict[str, Any]") -> str:
    """
    Map a ``turn_done`` event to an ACP stop reason.

    The harness only distinguishes aborted from not; ``refusal`` and
    ``max_tokens`` have no equivalent upstream, so claiming them would be
    fiction.
    """
    return "cancelled" if event.get("aborted") else "end_turn"


def _meta(event: "dict[str, Any]") -> "dict[str, Any]":
    return {META_NAMESPACE: event}


class SessionTranslator:
    """
    Per-session translation state.

    Stateful because ACP v2 patches messages by a stable ``messageId`` and the
    harness has no message identity at all -- its events carry only a session
    id. Minting ids here keeps ``engine.py`` untouched, but it means one
    translator per session: sharing one across sessions would merge their
    assistant messages into a single ever-growing one.

    A message is closed by whatever ends a contiguous run of assistant prose:
    the round's ``assistant_done``, or the end of the turn.
    """

    def __init__(self, session_id: str) -> None:
        self._session_id = session_id
        self._counter = 0
        self._open: "str | None" = None

    def _current(self) -> str:
        if self._open is None:
            self._counter += 1
            self._open = "{:s}:{:d}".format(self._session_id, self._counter)
        return self._open

    def _close(self) -> str:
        current = self._current()
        self._open = None
        return current

    def translate(self, event: "dict[str, Any]") -> "list[dict[str, Any]]":
        """
        Convert one harness event into zero or more ``session/update`` payloads.

        Zero is a normal outcome: most events are either local-only or already
        represented by another update.
        """
        kind = str(event.get("type") or "")

        if kind in _IGNORED:
            return []

        if kind == "token":
            body = str(event.get("text") or "")
            if not body:
                return []
            return [wire.dump(wire.AgentMessageChunk(
                session_update="agent_message_chunk",
                message_id=wire.message_id(self._current()),
                content=wire.text(body),
            ))]

        if kind == "assistant_done":
            body = str(event.get("content") or "")
            if not body:
                self._open = None
                return []
            # Same id as the chunks that preceded it: v2 says a later
            # full-content update REPLACES the accumulated chunks, which is
            # exactly the reconciliation we want after streaming.
            return [wire.dump(wire.AgentMessage(
                session_update="agent_message",
                message_id=wire.message_id(self._close()),
                content=[wire.text(body)],
            ))]

        if kind == "user_record":
            body = str(event.get("content") or "")
            if not body:
                return []
            # A user message is its own message, and it must not consume the
            # id an in-flight assistant reply is streaming under.
            self._counter += 1
            return [wire.dump(wire.UserMessage(
                session_update="user_message",
                message_id=wire.message_id(
                    "{:s}:{:d}".format(self._session_id, self._counter)),
                content=[wire.text(body)],
            ))]

        if kind == "tool_status":
            # A tool call interrupts the prose run; the next tokens belong to a
            # new assistant message.
            self._open = None
            return [_tool_call(event)]

        if kind == "turn_done":
            self._open = None
            return [wire.dump(wire.SessionIdle(
                session_update="state_update",
                state="idle",
                stop_reason=wire.stop_reason(stop_reason_for(event)),
            ))]

        if kind == "error":
            # Surfaced as agent prose: ACP has no error update, and silently
            # dropping it would leave the client waiting on an explanation that
            # never comes.
            message = str(event.get("message") or "")
            if not message:
                return []
            return [wire.dump(wire.AgentMessage(
                session_update="agent_message",
                message_id=wire.message_id(self._close()),
                content=[wire.text("Error: " + message)],
                field_meta=_meta(event),
            ))]

        # Harness concepts with no ACP vocabulary, and anything we have not
        # classified: pass through under _meta rather than dropping. A new
        # harness event should degrade to "opaque extra data", never to
        # silence.
        return [wire.dump(wire.SessionInfoUpdate(
            session_update="session_info_update",
            field_meta=_meta(event),
        ))]


def _tool_call(event: "dict[str, Any]") -> "dict[str, Any]":
    """
    Translate a ``tool_status`` event into a ``tool_call_update``.

    v2 patches by id: fields we omit stay as the client already has them, so a
    later update carrying only a status does not blank out the title or the
    arguments sent with the first one.
    """
    state = str(event.get("state") or "")
    status = _TOOL_STATUS.get(state, "pending")
    name = str(event.get("name") or "")

    content: "list[Any]" = []
    summary = event.get("summary")
    if summary:
        content.append({"type": "content", "content": {"type": "text", "text": str(summary)}})

    update: "dict[str, Any]" = {
        "sessionUpdate": "tool_call_update",
        "toolCallId": str(event.get("call_id") or ""),
        "status": status,
    }
    if name:
        update["title"] = name
        update["name"] = name
    if content:
        update["content"] = content

    raw_args = event.get("arguments")
    extra: "dict[str, Any]" = {}
    if raw_args:
        extra["arguments"] = raw_args
    media = event.get("media_ids")
    if media:
        extra["mediaIds"] = list(media)
    if state:
        # Keep the harness's own state word: `rejected` and `error` both map to
        # ACP `failed`, and a client that cares can tell them apart here.
        extra["state"] = state
    if extra:
        update["_meta"] = {META_NAMESPACE: extra}
    return update
