# SPDX-FileCopyrightText: 2026 agentcore contributors
#
# SPDX-License-Identifier: MIT OR Apache-2.0

"""
The ACP surface backed by a live :class:`~agentcore.runtime.AgentRuntime`.

Implements the dispatcher's ``AgentBridge`` against the harness. Most of the
mapping is direct -- the runtime's session API already has ACP's shape -- with
three places where the two models genuinely differ:

**Turn completion, per version.** ``send_user_message`` starts a task and
returns immediately. v1's ``session/prompt`` answers with a ``stopReason``, so
it must wait for the turn; v2's answers with nothing but ``_meta`` and reports
completion through a ``state_update`` instead. So the prompt path does both:
acknowledge-and-return for v2, block-for-the-stop-reason for v1. Getting this
backwards would either invent a field v2 does not have or drop one v1 requires.

**Steering.** Because a v2 prompt is not a turn boundary, one arriving while the
session is busy is guidance rather than an error: it is injected into the
running turn at its next round boundary. This is the concrete reason the worker
wire wanted v2 -- v1 has no way to say anything to a working agent.

**Update delivery.** A per-session pump translates events and pushes them, and
it outlives any single turn because v2 permits updates outside one. If the
client falls far enough behind that the subscription overflows, the bridge says
so rather than quietly skipping, and the client recovers with
``session/resume``.

**Permission and elicitation.** These invert the direction -- the agent calls
the client and blocks. The runtime already models both as futures resolved from
outside (``confirm_tool``, ``resolve_elicit``), so the bridge answers them from
the ACP client's reply instead of from a websocket message.
"""

__all__ = (
    "RuntimeBridge",
)

import asyncio
import contextlib
import logging
from typing import Any

from acp.exceptions import RequestError

from agentcore.acp.server import INVALID_PARAMS, ClientProxy
from agentcore.acp.updates import META_NAMESPACE, SessionTranslator, stop_reason_for
from agentcore.runtime import AgentRuntime, SessionSubscription

_log = logging.getLogger("agentcore.acp")

# How long to wait for a turn's `turn_done` before giving up on it. The turn
# itself is not bounded by this -- the runtime owns its own budgets; this only
# bounds how long a prompt call will sit waiting for one.
_TURN_TIMEOUT = 3600.0


class _SessionPump:
    """
    Drains one session's events for as long as the session is open.

    Lives across turns rather than per prompt, because v2 allows updates
    outside a user-initiated turn. Each turn gets a future that resolves with
    that turn's stop reason, which is what a v1 ``session/prompt`` waits on.
    """

    def __init__(
            self,
            bridge: "RuntimeBridge",
            session_id: str,
            subscription: SessionSubscription,
            translator: SessionTranslator,
            client: ClientProxy,
    ) -> None:
        self._bridge = bridge
        self._session_id = session_id
        self._subscription = subscription
        self._translator = translator
        self.client = client
        self._task: "asyncio.Task[None] | None" = None
        self._turn: "asyncio.Future[str] | None" = None

    @property
    def alive(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        self._task = asyncio.create_task(self._guarded_run())

    async def _guarded_run(self) -> None:
        """
        Run the pump, and never let it die quietly.

        A pump that raises takes the turn's future with it: the prompt call
        waits forever on a stop reason nobody will ever set. This bit during
        development -- one AttributeError in the pump body and every prompt hung
        indefinitely with no error surfaced. So a failure resolves the turn and
        is logged, rather than vanishing into an unretrieved task exception.
        """
        try:
            await self._run()
        except asyncio.CancelledError:
            self._finish_turn("cancelled")
            raise
        except Exception:  # pylint: disable=broad-except
            _log.exception("acp: update pump for %s failed", self._session_id)
            self._finish_turn("_pump_failed")

    def begin_turn(self) -> "asyncio.Future[str]":
        """A future resolving with the next turn's stop reason."""
        loop = asyncio.get_running_loop()
        if self._turn is None or self._turn.done():
            self._turn = loop.create_future()
        return self._turn

    async def wait(self) -> str:
        """Wait for the turn currently in flight (or the next one) to end."""
        return await self.begin_turn()

    def _finish_turn(self, stop_reason: str) -> None:
        if self._turn is not None and not self._turn.done():
            self._turn.set_result(stop_reason)

    async def stop(self) -> None:
        self._finish_turn("cancelled")
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
        self._bridge.release_subscription(self._subscription)

    async def _run(self) -> None:
        while True:
            if self._subscription.overflowed:
                # The client could not keep up. Say so rather than stream it a
                # transcript with a hole in it; `_`-prefixed values are v2's
                # extension escape, and resume is the documented recovery.
                await self.client.session_update(self._session_id, {
                    "sessionUpdate": "session_info_update",
                    "_meta": {META_NAMESPACE: {
                        "overflow": True,
                        "recover": "call session/resume with replayFrom {'type':'start'}",
                    }},
                })
                self._finish_turn("_overflow")
                return

            event = await self._subscription.queue.get()
            for update in self._translator.translate(event):
                await self.client.session_update(self._session_id, update)

            kind = event.get("type")
            # A destructive tool in `ask` autonomy parks on a future until
            # somebody answers. Ask the client -- concurrently, because the
            # engine keeps emitting while it waits and a blocked pump would
            # stall the very updates the client needs in order to decide.
            if kind == "tool_status" and event.get("state") == "pending_confirm":
                asyncio.create_task(
                    self._bridge.ask_permission(self._session_id, event, self.client))
            # Same shape of problem: a tool calling ask_user parks on a future.
            elif kind == "elicitation":
                asyncio.create_task(
                    self._bridge.ask_elicitation(self._session_id, event, self.client))
            elif kind == "turn_done" and event.get("session_id") == self._session_id:
                self._finish_turn(stop_reason_for(event))


class RuntimeBridge:
    """
    One ACP connection's view of the runtime.

    Per-connection, not per-process: it holds the translator state for each
    session this client has open, and the client handle to push updates at.
    Two clients on one session each get their own bridge and their own
    subscription, so neither steals the other's events.
    """

    def __init__(self, runtime: AgentRuntime) -> None:
        self._runtime = runtime
        self._translators: "dict[str, SessionTranslator]" = {}
        self._pumps: "dict[str, _SessionPump]" = {}

    # ------------------------------------------------------------------
    # Sessions.

    async def new_session(
            self,
            cwd: "str | None",
            mcp_servers: "list[dict[str, Any]] | None",
            client: ClientProxy,
            meta: "dict[str, Any] | None" = None,
    ) -> str:
        # `cwd` has no analogue: the agent's workspace is the Blender scene and
        # its data dir, not a checkout. Accepted and ignored rather than
        # rejected, because it is required by the schema.
        del cwd
        if mcp_servers:
            _log.info(
                "acp: session/new requested %d MCP server(s); tool provisioning "
                "over ACP is not wired yet", len(mcp_servers))
        session_id = self._runtime.new_session()
        self._translators[session_id] = SessionTranslator(session_id)
        self._apply_seed(session_id, meta)
        del client
        return session_id

    def _apply_seed(self, session_id: str, meta: "dict[str, Any] | None") -> None:
        """
        Honour a context fork carried on ``session/new``.

        ACP has no field for "start this session already holding that
        conversation", so an orchestrator forking context into a worker sends it
        under our ``_meta`` namespace. This is the receiving half of the
        harness's ``full`` handoff, and the same operation ``session/fork``
        performs when the parent lives on this agent.
        """
        payload = (meta or {}).get(META_NAMESPACE)
        if not isinstance(payload, dict):
            return
        raw = payload.get("seedMessages")
        if not isinstance(raw, list) or not raw:
            return
        messages = [
            {"role": str(m.get("role", "user")), "content": str(m.get("content", ""))}
            for m in raw
            if isinstance(m, dict) and str(m.get("content", ""))
        ]
        if not messages:
            return
        if self._runtime.seed_session(session_id, messages):
            _log.info("acp: seeded session %s with %d forked message(s)",
                      session_id, len(messages))
        else:
            # seed() refuses once a session has history or a prior seed --
            # seeding is a spawn-time act, not an injection channel.
            _log.warning("acp: seed refused for %s (already has history)", session_id)

    async def list_sessions(self) -> "list[dict[str, Any]]":
        sessions = []
        for record in self._runtime.list_sessions():
            entry: "dict[str, Any]" = {"sessionId": str(record.get("id", ""))}
            title = record.get("title")
            if title:
                entry["title"] = str(title)
            sessions.append(entry)
        return sessions

    async def delete_session(self, session_id: str) -> None:
        await self._stop_pump(session_id)
        self._runtime.delete_session(session_id)
        self._translators.pop(session_id, None)

    async def close_session(self, session_id: str) -> None:
        await self._stop_pump(session_id)
        self._translators.pop(session_id, None)

    async def fork_session(self, session_id: str, cwd: "str | None") -> str:
        """
        Fork a session's context into a new one.

        The harness already does exactly this for its ``full`` context handoff:
        seed a fresh session with the parent's messages. ``session/fork`` is
        that operation with a spec-shaped name.
        """
        del cwd
        records = self._runtime.session_records(session_id)
        if not records:
            raise RequestError(INVALID_PARAMS, "unknown session {!r}".format(session_id))
        forked = self._runtime.new_session()
        messages = [
            {"role": r.get("role"), "content": r.get("content", "")}
            for r in records
            if r.get("role") in ("user", "assistant") and r.get("content")
        ]
        if not self._runtime.seed_session(forked, messages):
            raise RequestError(INVALID_PARAMS, "could not seed forked session")
        self._translators[forked] = SessionTranslator(forked)
        return forked

    async def resume_session(
            self,
            session_id: str,
            replay_from: "dict[str, Any] | None",
            client: ClientProxy,
    ) -> None:
        """
        Re-attach to a session, optionally replaying its history.

        Replay is how a client recovers from a gap -- including one this bridge
        reported after an overflow. The transcript on disk is the source of
        truth, so replay is exact rather than best-effort.
        """
        self._translators[session_id] = SessionTranslator(session_id)
        if not replay_from:
            return
        if str(replay_from.get("type") or "") != "start":
            raise RequestError(
                INVALID_PARAMS,
                "only replayFrom {{'type': 'start'}} is supported; got {!r}".format(replay_from))

        translator = self._translators[session_id]
        for record in self._runtime.session_records(session_id):
            for event in _record_to_events(session_id, record):
                for update in translator.translate(event):
                    await client.session_update(session_id, update)

    async def set_config_option(
            self,
            session_id: str,
            option_id: str,
            value: "Any",
    ) -> "dict[str, Any]":
        """
        Set one session option.

        Only ``autonomy`` is exposed (ask | yolo | orchestrator | swarm). It is
        scoped to this session: a pod serving several ACP clients and web UI
        windows keeps a level per conversation, with the stored config as the
        default for sessions that have not chosen one.
        """
        if option_id != "autonomy":
            raise RequestError(
                INVALID_PARAMS,
                "unknown config option {!r}; this agent exposes 'autonomy'".format(option_id))
        applied = self._runtime.set_autonomy_level(session_id, str(value))
        return {"configOptions": [
            {"id": "autonomy", "value": applied.get("autonomy_level", value)}]}

    # ------------------------------------------------------------------
    # Turns.

    async def prompt(
            self,
            session_id: str,
            blocks: "list[dict[str, Any]]",
            client: ClientProxy,
            await_turn: bool = True,
    ) -> "str | None":
        """
        Deliver a prompt. Returns a stop reason only when *await_turn*.

        The two versions mean different things by this call. v1's
        ``PromptResponse`` carries a ``stopReason``, so the call must not answer
        until the turn is over. v2's carries nothing but ``_meta`` -- it
        "does not indicate that the agent has finished processing", which is
        reported through ``state_update`` instead. So a v2 prompt acknowledges
        and returns, and the client learns the turn ended from the idle update.

        That difference is also what makes steering work: a v2 prompt arriving
        while the session is busy is not an error, it is guidance for the turn
        already running.
        """
        text = _blocks_to_text(blocks)
        if not text:
            raise RequestError(
                INVALID_PARAMS, "prompt contained no text content the agent can read")

        # Subscribe BEFORE starting the turn: the engine emits its first events
        # synchronously inside send_user_message, so a subscription taken
        # afterwards would miss the opening of the turn.
        pump = self._ensure_pump(session_id, client)

        if self._runtime.session_busy(session_id):
            # Steering, not a new turn. Lands at the running turn's next round
            # boundary, so a tool in flight is never cut in half.
            if not self._runtime.inject_into_session(session_id, text):
                raise RequestError(
                    INVALID_PARAMS,
                    "session {!r} is busy and could not accept the message".format(session_id))
            _log.info("acp: steered live turn in %s", session_id)
            if not await_turn:
                return None
            return await pump.wait()

        turn = pump.begin_turn()
        try:
            await self._runtime.send_user_message(session_id, text)
        except RuntimeError as ex:
            # Lost a race against another client starting a turn.
            raise RequestError(INVALID_PARAMS, str(ex)) from ex
        if not await_turn:
            return None
        return await turn

    def _ensure_pump(self, session_id: str, client: ClientProxy) -> "_SessionPump":
        """
        The background task that turns this session's events into updates.

        One per session, started on first use and running until the session is
        closed -- not per turn. v2 permits (and expects) updates outside a
        user-initiated turn, so a pump that only lived for the duration of a
        prompt would go deaf exactly when an idle agent has something to say.
        """
        pump = self._pumps.get(session_id)
        if pump is not None and pump.alive:
            pump.client = client
            return pump
        translator = self._translators.setdefault(session_id, SessionTranslator(session_id))
        subscription = self._runtime.subscribe_session(session_id)
        pump = _SessionPump(self, session_id, subscription, translator, client)
        self._pumps[session_id] = pump
        pump.start()
        return pump

    # ------------------------------------------------------------------
    # Answering the agent's questions, by asking the client.

    async def ask_permission(
            self,
            session_id: str,
            event: "dict[str, Any]",
            client: ClientProxy,
    ) -> None:
        """
        Put one tool call to the client and resolve the engine's confirm gate.

        Without this the gate simply waits out its ten-minute timeout and
        auto-declines -- which is what a live run did before it was wired: the
        worker got as far as ``execute_blender_code`` and was refused by nobody.
        """
        call_id = str(event.get("call_id") or "")
        name = str(event.get("name") or "tool")
        if not call_id:
            return
        options = [
            {"optionId": "allow_once", "name": "Allow", "kind": "allow_once"},
            {"optionId": "allow_always", "name": "Always allow", "kind": "allow_always"},
            {"optionId": "reject_once", "name": "Reject", "kind": "reject_once"},
        ]
        approved = False
        try:
            answer = await client.request_permission(
                session_id,
                "Run {:s}".format(name),
                options,
                subject={"toolCall": {"toolCallId": call_id, "title": name}},
                description=str(event.get("arguments") or "") or None,
            )
            outcome = answer.get("outcome")
            if isinstance(outcome, dict):
                chosen = str(outcome.get("optionId") or "")
                approved = (outcome.get("outcome") == "selected"
                            and chosen.startswith("allow"))
        except Exception as ex:  # pylint: disable=broad-except
            # A client that cannot answer is a decline, not a hang: the engine
            # is holding a turn open waiting for this.
            _log.warning("acp: permission request for %s failed: %s", call_id, ex)
        self._runtime.confirm_tool(session_id, call_id, approved)

    async def ask_elicitation(
            self,
            session_id: str,
            event: "dict[str, Any]",
            client: ClientProxy,
    ) -> None:
        """
        Put a tool's question to the client and hand back the answer.

        The harness's own answer shape is ``{choices, text, cancelled}``; ACP
        returns an elicitation outcome, so the two are translated here. A client
        that declines or errors is recorded as cancelled, which is the signal
        ``ask_user`` already knows how to take.
        """
        elicit_id = str(event.get("elicit_id") or "")
        if not elicit_id:
            return
        options = [str(o) for o in event.get("options") or []]
        response: "dict[str, Any]" = {"choices": [], "text": "", "cancelled": True}
        try:
            answer = await client.create_elicitation(
                session_id,
                str(event.get("question") or ""),
                requested_schema=_elicit_schema(
                    options, bool(event.get("allow_freeform", True))),
            )
            outcome = answer.get("outcome")
            if isinstance(outcome, dict) and outcome.get("outcome") == "accepted":
                content = outcome.get("content")
                content = content if isinstance(content, dict) else {}
                choice = content.get("choice")
                response = {
                    "choices": [str(choice)] if choice else [],
                    "text": str(content.get("text") or ""),
                    "cancelled": False,
                }
        except Exception as ex:  # pylint: disable=broad-except
            _log.warning("acp: elicitation %s failed: %s", elicit_id, ex)
        self._runtime.resolve_elicit(session_id, elicit_id, response)

    async def cancel(self, session_id: str) -> None:
        """
        Interrupt the running turn.

        A notification, so there is nothing to report back: the in-flight
        ``session/prompt`` observes the abort and answers ``cancelled``, which
        is where the client learns it landed.
        """
        self._runtime.abort(session_id)

    # ------------------------------------------------------------------

    async def _stop_pump(self, session_id: str) -> None:
        pump = self._pumps.pop(session_id, None)
        if pump is not None:
            await pump.stop()

    def release_subscription(self, subscription: SessionSubscription) -> None:
        """Hand a pump's subscription back to the runtime."""
        self._runtime.unsubscribe_session(subscription)


def _blocks_to_text(blocks: "list[dict[str, Any]]") -> str:
    """
    Flatten ACP content blocks into the single string a turn takes.

    Text and embedded-resource text are read; image and audio blocks are
    dropped here because attaching them needs a media id from the session's
    library, which is a separate registration step.
    """
    parts: "list[str]" = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text":
            body = block.get("text")
            if isinstance(body, str) and body:
                parts.append(body)
        elif kind == "resource":
            resource = block.get("resource")
            if isinstance(resource, dict):
                body = resource.get("text")
                if isinstance(body, str) and body:
                    parts.append(body)
        elif kind == "resource_link":
            uri = block.get("uri")
            if isinstance(uri, str) and uri:
                parts.append(uri)
    return "\n\n".join(parts).strip()


def _elicit_schema(options: "list[str]", allow_freeform: bool) -> "dict[str, Any]":
    """A JSON schema describing what the tool is asking for."""
    properties: "dict[str, Any]" = {}
    if options:
        properties["choice"] = {"type": "string", "enum": options}
    if allow_freeform or not options:
        properties["text"] = {"type": "string"}
    return {"type": "object", "properties": properties}


def _record_to_events(session_id: str, record: "dict[str, Any]") -> "list[dict[str, Any]]":
    """
    Turn one stored transcript record back into the events that produced it.

    Replay goes through the same translator as live traffic, so a resumed
    client sees the identical update shapes it would have seen live.
    """
    role = record.get("role")
    content = record.get("content")
    if not isinstance(content, str) or not content:
        return []
    if role == "user":
        return [{"type": "user_record", "session_id": session_id, "content": content}]
    if role == "assistant":
        return [{"type": "assistant_done", "session_id": session_id, "content": content}]
    return []
