# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Agent runtime, ported from Foyer Studio's ``foyer-agent/src/runtime.rs``:
session registry, per-session engines, turn task management, the
confirm gate, and the event broadcast that fans out to every connected
WebSocket client.
"""

__all__ = (
    "AgentRuntime",
)

import asyncio
import logging
import os


from typing import Any

from .agent_tools import ContinueWorkingTool, MediaTool, SkillsTool
from .engine import AgentEngine
from .llm import LlmClient, LlmError, LocalLlmBridgeClient, OpenAiHttpClient
from .media import MediaLibrary
from .store import AgentStore, SessionBusyError
from .tools import Tool, ToolRegistry
from .local_llm import LocalLlmBridge

_log = logging.getLogger("blagent.runtime")

_SYSTEM_PROMPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "system_prompt.md")


class _Session:
    """
    One conversation: engine + media library + at most one running turn.
    """

    def __init__(self, session_id: str, engine: AgentEngine, media: MediaLibrary) -> None:
        self.session_id = session_id
        self.engine = engine
        self.media = media
        self.task: asyncio.Task[None] | None = None

    @property
    def busy(self) -> bool:
        return self.task is not None and not self.task.done()


class AgentRuntime:
    """
    Owns the store, the tool registry, the local-model bridge, and all
    live sessions. Every UI (web, future TUI, tests) is a thin client over
    this object.
    """

    def __init__(self, store: AgentStore, blender_tools: list[Tool]) -> None:
        self.store = store
        self.local_llm = LocalLlmBridge()
        # Instance label (e.g. the .blend file name) + bound UI port,
        # surfaced as the browser tab title to tell instances apart.
        self.instance_title = ""
        self.instance_port = 0
        tools: list[Tool] = list(blender_tools)
        tools.append(SkillsTool(store))
        tools.append(MediaTool())
        tools.append(ContinueWorkingTool())
        self.registry = ToolRegistry(tools)
        self._sessions: dict[str, _Session] = {}
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._system_prompt = self._load_system_prompt()

    def _load_system_prompt(self) -> str:
        # No skills index here: the prompt compels a `welcome` call, whose
        # response carries the live skill inventory — duplicating it in the
        # system prompt would cost tokens on every turn.
        with open(_SYSTEM_PROMPT_PATH, encoding="utf-8") as fh:
            return fh.read()

    # ------------------------------------------------------------------
    # Event broadcast.

    def subscribe(self) -> "asyncio.Queue[dict[str, Any]]":
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=2048)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: "asyncio.Queue[dict[str, Any]]") -> None:
        self._subscribers.discard(queue)

    async def emit(self, event: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Slow consumer; drop it rather than stall the engine.
                self._subscribers.discard(queue)

    # ------------------------------------------------------------------
    # Sessions.

    def _get_or_load_session(self, session_id: str) -> _Session:
        session = self._sessions.get(session_id)
        if session is not None:
            return session
        media = MediaLibrary(os.path.join(self.store.session_dir(session_id), "media"))

        def _append_record(record: dict[str, Any], _sid: str = session_id) -> None:
            # append_record returns the re-read transcript: with two
            # agent windows on one session (multiple Blender instances
            # sharing a data dir), the on-disk file is the merge point.
            # Adopting it after every write folds in foreign appends.
            engine.records[:] = self.store.append_record(_sid, record)

        engine = AgentEngine(
            registry=self.registry,
            media=media,
            system_prompt=self._system_prompt,
            emit=self.emit,
            append_record=_append_record,
        )
        engine.records = self.store.load_records(session_id)
        session = _Session(session_id, engine, media)
        self._sessions[session_id] = session
        return session

    def new_session(self) -> str:
        session_id = self.store.new_session_id()
        self._get_or_load_session(session_id)
        return session_id

    def list_sessions(self) -> list[dict[str, object]]:
        return self.store.list_sessions()

    def session_records(self, session_id: str) -> list[dict[str, Any]]:
        session = self._get_or_load_session(session_id)
        # Re-sync from disk when idle so a second window's appends show
        # up; a running turn keeps its in-memory view (it converges on
        # its own next write).
        if not session.busy:
            session.engine.records[:] = self.store.load_records(session_id)
        return session.engine.records

    def session_media(self, session_id: str) -> list[dict[str, object]]:
        return self._get_or_load_session(session_id).media.list_public()

    def delete_session(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session is not None and session.task is not None:
            session.task.cancel()
        self.store.delete_session(session_id)

    # ------------------------------------------------------------------
    # LLM resolution.

    def _make_llm(self) -> LlmClient:
        # Local (in-browser Transformers.js) and remote endpoints are
        # mutually exclusive modes: `use_local_llm` selects local
        # regardless of any stored endpoint, so switching back and
        # forth never loses settings.
        config = self.store.config
        if config.use_local_llm:
            return LocalLlmBridgeClient(self.local_llm)
        if config.endpoint:
            return OpenAiHttpClient(config.endpoint, api_key=config.api_key)
        raise LlmError("no LLM configured - pick a local or remote model in settings")

    def _model_name(self) -> str:
        config = self.store.config
        if config.use_local_llm:
            return self.local_llm.model_id or "local"
        return config.model or "default"

    # ------------------------------------------------------------------
    # Turn entry points (called from the WS handler).

    async def send_user_message(
            self,
            session_id: str,
            content: str,
            media_ids: list[str] | None = None,
            autonomy: str | None = None,
    ) -> str:
        """
        Start a turn. Returns the session id (a new one when blank).
        Raises ``RuntimeError`` when the session is already busy.
        *autonomy* overrides the configured mode for this turn (the chat
        API forces "auto": nobody can answer a confirm over that wire).
        """
        if not session_id:
            session_id = self.new_session()
        session = self._get_or_load_session(session_id)
        if session.busy:
            raise RuntimeError("a turn is already running in this session")

        config = self.store.config
        turn_autonomy = autonomy if autonomy is not None else config.autonomy
        llm = self._make_llm()
        model = self._model_name()

        async def _run() -> None:
            try:
                await session.engine.run_turn(
                    session_id=session_id,
                    user_text=content,
                    llm=llm,
                    model=model,
                    autonomy=turn_autonomy,
                    max_rounds=config.max_rounds,
                    media_ids=media_ids,
                    context_tokens=config.context_tokens,
                    budget_review=config.budget_review,
                )
                # Between-turns compaction: one bounded request that
                # summarizes the older history when the projection has
                # outgrown the budget. Failures only mean the guard-rail
                # trimming carries the load next turn.
                #
                # The session lock is held for the whole step (it spans
                # an LLM request): the summary's covers_count indexes
                # into the transcript, so a foreign window appending
                # mid-summarization would corrupt the coverage. A short
                # timeout means we simply skip compaction when another
                # window is active - never block its turn.
                try:
                    with self.store.session_lock(session_id, timeout=1.0):
                        session.engine.records[:] = self.store.load_records(session_id)
                        if await session.engine.maybe_compact(llm, model, config.context_tokens):
                            await self.emit({"type": "compacted", "session_id": session_id})
                except SessionBusyError:
                    _log.info("compaction skipped session=%s: held by another window", session_id)
                except Exception as ex:  # pylint: disable=broad-exception-caught
                    _log.warning("compaction failed session=%s: %s", session_id, ex)
            except asyncio.CancelledError:
                await self.emit({"type": "turn_done", "session_id": session_id, "aborted": True})
                raise
            except SessionBusyError as ex:
                # Lost a lock race against another window on the same
                # session (e.g. it was holding the long compaction
                # lock). Nothing is corrupted - the record that could
                # not be appended is dropped with an explicit error.
                _log.warning("session lock contention session=%s: %s", session_id, ex)
                await self.emit({
                    "type": "error",
                    "session_id": session_id,
                    "message": "another agent window is writing to this session - "
                               "please retry in a moment",
                })
                await self.emit({"type": "turn_done", "session_id": session_id})
            except LlmError as ex:
                _log.error("turn failed session=%s: %s", session_id, ex)
                await self.emit({"type": "error", "session_id": session_id, "message": str(ex)})
                await self.emit({"type": "turn_done", "session_id": session_id})
            except Exception as ex:  # pylint: disable=broad-exception-caught
                await self.emit({
                    "type": "error",
                    "session_id": session_id,
                    "message": "internal error: {:s}: {:s}".format(type(ex).__name__, str(ex)),
                })
                await self.emit({"type": "turn_done", "session_id": session_id})

        session.task = asyncio.create_task(_run())
        return session_id

    def confirm_tool(self, session_id: str, call_id: str, approve: bool) -> bool:
        session = self._sessions.get(session_id)
        if session is None:
            return False
        return session.engine.resolve_confirm(call_id, approve)

    def abort(self, session_id: str) -> bool:
        session = self._sessions.get(session_id)
        if session is None or session.task is None or session.task.done():
            return False
        session.task.cancel()
        return True

    # ------------------------------------------------------------------
    # Config.

    def instance_info(self) -> dict[str, object]:
        return {"title": self.instance_title, "port": self.instance_port}

    def set_config(self, updates: dict[str, Any]) -> dict[str, object]:
        config = self.store.config
        for key in ("endpoint", "model", "autonomy"):
            if key in updates:
                setattr(config, key, str(updates[key]))
        if "api_key" in updates:
            config.api_key = str(updates["api_key"])
        if "use_local_llm" in updates:
            config.use_local_llm = bool(updates["use_local_llm"])
        if "max_rounds" in updates:
            config.max_rounds = max(1, int(updates["max_rounds"]))
        if "budget_review" in updates:
            config.budget_review = bool(updates["budget_review"])
        if "context_tokens" in updates:
            config.context_tokens = max(2_048, int(updates["context_tokens"]))
        self.store.save_config()
        return config.as_public()
