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
import os

from typing import Any

from .agent_tools import ContinueWorkingTool, MediaTool, SkillsTool
from .engine import AgentEngine
from .llm import LlmClient, LlmError, OpenAiHttpClient, WebLlmBridgeClient
from .media import MediaLibrary
from .store import AgentStore
from .tools import Tool, ToolRegistry
from .webllm import WebLlmBridge

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
    Owns the store, the tool registry, the WebLLM bridge, and all live
    sessions. Every UI (web, future TUI, tests) is a thin client over
    this object.
    """

    def __init__(self, store: AgentStore, blender_tools: list[Tool]) -> None:
        self.store = store
        self.webllm = WebLlmBridge()
        tools: list[Tool] = list(blender_tools)
        tools.append(SkillsTool(store))
        tools.append(MediaTool())
        tools.append(ContinueWorkingTool())
        self.registry = ToolRegistry(tools)
        self._sessions: dict[str, _Session] = {}
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._system_prompt = self._load_system_prompt()

    def _load_system_prompt(self) -> str:
        with open(_SYSTEM_PROMPT_PATH, encoding="utf-8") as fh:
            prompt = fh.read()
        skills = self.store.list_skills()
        if skills:
            index = "\n".join("- {:s}: {:s}".format(s.name, s.summary) for s in skills)
            prompt += "\n\n## Available skills\n{:s}\n".format(index)
        return prompt

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
            self.store.append_record(_sid, record)

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
        return self._get_or_load_session(session_id).engine.records

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
        config = self.store.config
        if config.endpoint:
            return OpenAiHttpClient(config.endpoint, api_key=config.api_key)
        if config.use_webllm:
            return WebLlmBridgeClient(self.webllm)
        raise LlmError("no LLM configured - set an endpoint in settings or enable WebLLM")

    def _model_name(self) -> str:
        config = self.store.config
        if config.endpoint:
            return config.model or "default"
        return self.webllm.model_id or "webllm"

    # ------------------------------------------------------------------
    # Turn entry points (called from the WS handler).

    async def send_user_message(self, session_id: str, content: str) -> str:
        """
        Start a turn. Returns the session id (a new one when blank).
        Raises ``RuntimeError`` when the session is already busy.
        """
        if not session_id:
            session_id = self.new_session()
        session = self._get_or_load_session(session_id)
        if session.busy:
            raise RuntimeError("a turn is already running in this session")

        config = self.store.config
        llm = self._make_llm()
        model = self._model_name()

        async def _run() -> None:
            try:
                await session.engine.run_turn(
                    session_id=session_id,
                    user_text=content,
                    llm=llm,
                    model=model,
                    autonomy=config.autonomy,
                    max_rounds=config.max_rounds,
                )
            except asyncio.CancelledError:
                await self.emit({"type": "turn_done", "session_id": session_id, "aborted": True})
                raise
            except LlmError as ex:
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

    def set_config(self, updates: dict[str, Any]) -> dict[str, object]:
        config = self.store.config
        for key in ("endpoint", "model", "autonomy"):
            if key in updates:
                setattr(config, key, str(updates[key]))
        if "api_key" in updates:
            config.api_key = str(updates["api_key"])
        if "use_webllm" in updates:
            config.use_webllm = bool(updates["use_webllm"])
        if "max_rounds" in updates:
            config.max_rounds = max(1, int(updates["max_rounds"]))
        self.store.save_config()
        return config.as_public()
