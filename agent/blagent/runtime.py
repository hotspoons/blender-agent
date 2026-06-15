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
import dataclasses
import json
import logging
import os
import time


from typing import Any, Awaitable, Callable

from .agent_tools import AskUserTool, ContinueWorkingTool, MediaTool, SetAutonomyTool, SkillsTool
from .backend import PythonToolBackend, ToolBackend
from .engine import AgentEngine, _strip_thinking
from .orchestrator_view import OrchestratorView
from .permissions import ToolPermissions, WORKER_DENY
from .profile import AgentProfile, blender_profile
from .llm import LlmClient, LlmError, LocalLlmBridgeClient, OpenAiHttpClient
from .media import MediaLibrary
from .store import AgentStore, SessionBusyError
from .tools import Tool, ToolContext, ToolRegistry
from .local_llm import LocalLlmBridge

_log = logging.getLogger("blagent.runtime")

# A real .blend (even an empty scene) is comfortably larger than this; a file
# below it is almost certainly a failed/partial export, surfaced as suspect.
_MIN_BLEND_BYTES = 1024

# Defense-in-depth floor for the worker surface: even if the RBAC matrix is
# misconfigured, a worker engine must never reach these orchestrator/user-only
# meta-tools. Mirrors the `worker` role's deny list in permissions.yaml.
_WORKER_TOOL_DENYLIST = frozenset(WORKER_DENY)

# Pinned into the worker's SYSTEM prompt (which _fit_context never trims), so
# the mission survives even after huge welcome/scene-summary tool results
# balloon the context. Reframes the worker as autonomous: no user to ask.
_WORKER_MISSION = """

---
# YOUR ROLE: autonomous worker sub-agent
An orchestrator has delegated ONE task to you. You are NOT in a conversation
with a human — there is no user to ask. Do NOT ask clarifying questions, do
NOT offer menus of options, and do NOT wait for confirmation or approval.
Make the most reasonable interpretation, ACT, verify, and report. Note any
assumptions in your proof of work.

## YOUR TASK
{instruction}

## OBJECTIVE THIS SERVES
{goal}

## DONE WHEN
{acceptance}
{context}
Stay strictly on this task — do not wander, do not "tidy up" unrelated things,
do not redo other workers' work. This section is your ground truth: if the
running conversation is ever trimmed, your assignment still lives HERE.

When finished, end your turn with a short PROOF OF WORK: what you changed and
concrete evidence (object names, counts, verify output, a rendered image). To
show the scene visually, RENDER it (media_io verb 'render', or
render_thumbnail_to_path) — this Blender is headless, so viewport screenshot
tools do not work. If you could not finish, say so plainly and why.
"""


class ChildSessionRunner:
    """
    The child-session isolation strategy made real: each worker task runs
    in its OWN ``AgentEngine`` (isolated transcript + media) with a
    RESTRICTED tool surface (no orchestrator/user-facing meta-tools — see
    ``_WORKER_TOOL_DENYLIST``) and its mission pinned in the system prompt.
    The orchestrator gets back only the worker's proof — the worker's
    chatter never enters the orchestrator's context. Events are tagged with
    the worker's agent id + parent so the UI nests them in a bounded panel.

    Dependencies are explicit so it is testable without the full runtime.
    """

    def __init__(
            self,
            *,
            registry: ToolRegistry,
            make_llm: "Callable[[], LlmClient]",
            model: str,
            emit: "Callable[[dict[str, Any]], Awaitable[None]]",
            system_prompt: str,
            media_factory: "Callable[[str], MediaLibrary]",
            parent_session_id: str,
            autonomy: str = "auto",
            max_rounds: int = 8,
            context_tokens: int = 0,
            budget_review: bool = False,
            register: "Callable[[str, AgentEngine], None] | None" = None,
            unregister: "Callable[[str], None] | None" = None,
    ) -> None:
        # Workers run on a restricted surface: strip orchestrator/user-only
        # tools (set_autonomy, ask_user) so a worker can't change autonomy or
        # sit waiting on a user that does not exist.
        self._registry = ToolRegistry(
            [t for t in registry if t.name not in _WORKER_TOOL_DENYLIST])
        self._make_llm = make_llm
        self._model = model
        self._emit = emit
        self._system_prompt = system_prompt
        self._media_factory = media_factory
        self._parent = parent_session_id
        self._autonomy = autonomy
        self._max_rounds = max_rounds
        self._context_tokens = context_tokens
        self._budget_review = budget_review
        # Lets the runtime track the live worker engine by agent id so the
        # user can inject messages straight into it (voice of god).
        self._register = register
        self._unregister = unregister

    async def __call__(self, task: Any) -> Any:
        from .autonomy import WorkerResult

        agent_id = "{:s}:w:{:s}".format(self._parent, task.id)
        records: list[dict[str, Any]] = []

        async def child_emit(event: dict[str, Any]) -> None:
            await self._emit({**event, "parent_session_id": self._parent, "role": "worker"})

        def append(record: dict[str, Any]) -> None:
            records.append(record)

        # Pin the full mission in the SYSTEM prompt (which _fit_context never
        # trims), so huge welcome/scene-summary tool results can't push the
        # worker's task out of context and disorient it. The informed-worker
        # context (share_context) rides along here too — pinned, not a
        # trimmable synthetic user turn.
        context_block = ""
        if getattr(task, "context", ""):
            context_block = "\n## ORCHESTRATOR CONTEXT\n{:s}\n".format(task.context)
        worker_system = self._system_prompt + _WORKER_MISSION.format(
            instruction=task.instruction,
            goal=getattr(task, "goal", "") or "(not specified)",
            acceptance=getattr(task, "acceptance", "") or "the task is accomplished and verifiable",
            context=context_block,
        )
        engine = AgentEngine(
            registry=self._registry,
            media=self._media_factory(agent_id),
            system_prompt=worker_system,
            emit=child_emit,
            append_record=append,
        )
        if self._register is not None:
            self._register(agent_id, engine)
        try:
            await engine.run_turn(
                session_id=agent_id,
                user_text="Begin now — execute your assigned task end to end, "
                          "then report your proof of work.",
                llm=self._make_llm(),
                model=self._model,
                autonomy=self._autonomy,
                max_rounds=self._max_rounds,
                context_tokens=self._context_tokens,
                budget_review=self._budget_review,
            )
        except Exception as ex:  # pylint: disable=broad-except
            _log.warning("worker %s failed: %s", task.id, ex)
            return WorkerResult(
                task_id=task.id, objective_id=task.objective_id,
                proof="worker errored: {:s}".format(ex), ok=False, transcript_ref=agent_id)
        finally:
            if self._unregister is not None:
                self._unregister(agent_id)

        proof = ""
        for record in reversed(records):
            if record.get("role") == "assistant":
                # Strip the reasoning trace: the proof is the worker's CLAIM,
                # shown in the card and judged by the evaluator — not its
                # chain-of-thought. (A think-only round strips to empty -> skip.)
                content = _strip_thinking(str(record.get("content", ""))).strip()
                if content:
                    proof = content
                    break
        return WorkerResult(
            task_id=task.id, objective_id=task.objective_id,
            proof=proof or "(worker produced no final report)",
            ok=bool(proof), transcript_ref=agent_id)

_SYSTEM_PROMPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "system_prompt.md")

# The orchestrator/swarm run state is owned by the BACKEND: events are reduced
# into an OrchestratorView (blagent.orchestrator_view) and the snapshot is
# emitted as `autonomy_view` + persisted, so the frontend is a pure projection
# (it renders the snapshot; it does NOT reduce events). Token-driven snapshots
# are throttled to this interval to avoid flooding the socket on live streaming.
_VIEW_THROTTLE_SECONDS = 0.12


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

    def __init__(self, store: AgentStore, backend: "ToolBackend | list[Tool]",
                 profile: "AgentProfile | None" = None,
                 permissions: "ToolPermissions | None" = None) -> None:
        self.store = store
        # Domain flavor (brand/copy/prompts). Defaults to the Blender build's
        # profile; a YAML build passes its own.
        self.profile = profile or blender_profile()
        # Tool RBAC matrix (role -> allowed tools), from data/permissions.yaml.
        self.permissions = permissions or ToolPermissions.load()
        self.local_llm = LocalLlmBridge()
        # Instance label (e.g. the .blend file name) + bound UI port,
        # surfaced as the browser tab title to tell instances apart.
        self.instance_title = ""
        self.instance_port = 0
        # The portable domain boundary. The Blender build passes a list of
        # tools (or a PythonToolBackend); we wrap a bare list so the runtime
        # always holds a ToolBackend and reaches the domain's ground-truth
        # probe + compute surface through it — never via a Blender-named tool.
        # In-process tool *execution* still uses the raw tools on the registry
        # below, to preserve the engine's full ToolContext (confirm/elicit).
        # A generic/HTTP backend is wired via AgentRuntime.create() (async).
        if isinstance(backend, PythonToolBackend):
            self.backend: ToolBackend = backend
            domain_tools: list[Tool] = backend.tools
        elif isinstance(backend, list):
            domain_tools = list(backend)
            self.backend = PythonToolBackend(domain_tools, probe=self._probe_state)
        else:
            raise TypeError(
                "AgentRuntime(store, ...) takes a list[Tool] or PythonToolBackend; "
                "for a generic/HTTP ToolBackend use `await AgentRuntime.create(...)`")
        self.registry = ToolRegistry(list(domain_tools) + self._core_tools())
        self._sessions: dict[str, _Session] = {}
        # Live worker engines by agent id, for voice-of-god injection.
        self._workers: dict[str, AgentEngine] = {}
        # Swarm (subprocess) workers by agent id -> stop hook. No live engine
        # here, so these support stop/cancel but not injection.
        self._swarm_stoppers: dict[str, "Callable[[], None]"] = {}
        # Live autonomy objective lists by session id, for mid-run updates.
        self._autonomy_objs: dict[str, list[Any]] = {}
        # Backend-owned orchestrator view (the frontend projects its snapshot).
        self._views: dict[str, OrchestratorView] = {}
        self._view_emit_at: dict[str, float] = {}
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._system_prompt = self._load_system_prompt()

    def _core_tools(self) -> list[Tool]:
        """The domain-agnostic harness tools added to every registry,
        regardless of backend/transport."""
        return [
            SkillsTool(self.store),
            MediaTool(),
            ContinueWorkingTool(),
            # Lets the agent ask the user a question (multiple choice + freeform).
            AskUserTool(),
            # Lets the agent adjust its own autonomy level (also over the OpenAI
            # endpoint), instead of only via the UI slider.
            SetAutonomyTool(self.set_autonomy_level),
        ]

    def public_ui_profile(self) -> dict[str, Any]:
        """The UI branding block pushed to the frontend (web applyProfile)."""
        return self.profile.as_ui_public()

    def registry_for_role(self, role: str) -> ToolRegistry:
        """The tool registry a given RBAC *role* may use (see permissions.yaml).
        The interactive/orchestrator path uses the full ``self.registry``; a
        worker gets the matrix-filtered surface."""
        return ToolRegistry(self.permissions.filter_tools(role, list(self.registry)))

    @classmethod
    async def create(cls, store: AgentStore, backend: ToolBackend,
                     profile: "AgentProfile | None" = None,
                     permissions: "ToolPermissions | None" = None) -> "AgentRuntime":
        """
        Async constructor for a generic ``ToolBackend`` (e.g. an HTTP backend):
        the tool list is discovered via ``backend.list_tools()`` and adapted
        with ``BackendTool``, so tool calls route over the transport. (For an
        HTTP backend the engine's confirm/elicit callbacks are local-only and
        do not cross the wire — there is nothing to lose by routing through
        ``call_tool``.) The in-process Blender path uses the sync constructor.
        """
        from .backend import registry_from_backend

        self = cls.__new__(cls)
        self.store = store
        self.profile = profile or AgentProfile()
        self.permissions = permissions or ToolPermissions.load()
        self.local_llm = LocalLlmBridge()
        self.instance_title = ""
        self.instance_port = 0
        self.backend = backend
        self.registry = await registry_from_backend(backend, extra=self._core_tools())
        self._sessions = {}
        self._workers = {}
        self._swarm_stoppers = {}
        self._autonomy_objs = {}
        self._views = {}
        self._view_emit_at = {}
        self._subscribers = set()
        self._system_prompt = self._load_system_prompt()
        return self

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

    @staticmethod
    def _agent_id_from_safe(session_id: str, safe: str) -> "str | None":
        """Reverse ``agent_id.replace(':', '_')`` for this session's workers/
        gather dirs (session ids carry no colons, so this is unambiguous)."""
        w = session_id + "_w_"
        g = session_id + "_gather"
        if safe.startswith(w):
            return session_id + ":w:" + safe[len(w):]
        if safe.startswith(g):
            return session_id + ":gather" + safe[len(g):]
        return None

    def _view_path(self, session_id: str) -> str:
        return os.path.join(self.store.session_dir(session_id), "autonomy_view.json")

    def _reset_view(self, session_id: str) -> "OrchestratorView":
        """Start a fresh view for a new run (reload shows the latest run)."""
        view = OrchestratorView()
        self._views[session_id] = view
        try:
            path = self._view_path(session_id)
            if os.path.isfile(path):
                os.remove(path)
        except Exception:  # pylint: disable=broad-except
            pass
        return view

    def _persist_view(self, session_id: str, view: "OrchestratorView") -> None:
        try:
            path = self._view_path(session_id)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(view.snapshot(), fh, default=str)
        except Exception as ex:  # pylint: disable=broad-except
            _log.warning("persist autonomy view failed session=%s: %s", session_id, ex)

    def session_autonomy_view(self, session_id: str) -> "dict[str, Any] | None":
        """The backend-owned orchestrator view snapshot — the frontend renders
        it directly (it holds no autonomy state of its own)."""
        view = self._views.get(session_id)
        if view is not None:
            return view.snapshot()
        path = self._view_path(session_id)
        if not os.path.isfile(path):
            return None
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception as ex:  # pylint: disable=broad-except
            _log.warning("read autonomy view failed session=%s: %s", session_id, ex)
            return None

    def session_media(self, session_id: str) -> list[dict[str, object]]:
        session = self._get_or_load_session(session_id)
        # Each item carries an explicit `url`; the session's own media serve
        # from /media, worker-produced media from /worker-media.
        items: list[dict[str, object]] = [
            {**it, "url": "/media/{:s}/{:s}".format(session_id, str(it["id"]))}
            for it in session.media.list_public()
        ]
        # Aggregate media produced by this session's workers (renders, etc.) so
        # they appear in the session artifacts panel — not only inside each
        # worker card.
        workers_dir = os.path.join(self.store.session_dir(session_id), "workers")
        if os.path.isdir(workers_dir):
            for safe in sorted(os.listdir(workers_dir)):
                agent_id = self._agent_id_from_safe(session_id, safe)
                if agent_id is None:
                    continue
                try:
                    lib = MediaLibrary(os.path.join(workers_dir, safe))
                except Exception:  # pylint: disable=broad-except
                    continue
                for it in lib.list_public():
                    items.append({
                        **it, "worker": agent_id,
                        "url": "/worker-media/{:s}/{:s}".format(agent_id, str(it["id"])),
                    })
        return items

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

    # ------------------------------------------------------------------
    # Autonomy mode (blagent.autonomy).

    def _make_probe(self, session_id: str) -> "Callable[[], Awaitable[str]]":
        """A read-only state snapshot for the goal evaluator (ground truth),
        obtained through the domain backend rather than a named tool."""

        async def probe() -> str:
            text = await self.backend.state_probe(session_id=session_id)
            return text or "(no state probe available)"

        return probe

    async def _probe_state(self, session_id: str) -> str:
        """The Blender ground-truth probe wired into the PythonToolBackend:
        a read-only scene snapshot via ``get_objects_summary``. (Lives here
        until the Blender backend factory owns it after the package split.)"""
        tool = self.registry.get("get_objects_summary")
        if tool is None:
            return "(get_objects_summary unavailable)"
        media = self._get_or_load_session(session_id).media
        try:
            result = await tool.call(ToolContext(media=media, session_id=session_id), {})
        except Exception as ex:  # pylint: disable=broad-except
            return "(scene probe failed: {:s})".format(ex)
        data = result.data if result.data is not None else result.summary
        text = data if isinstance(data, str) else json.dumps(data, default=str)
        return text[:6000]

    async def _read_blend_objects(self, path: str) -> list[str]:
        """Open a .blend headless and return its object names (best-effort)."""
        blender = os.environ.get("BLENDER_PATH", "blender")
        try:
            proc = await asyncio.create_subprocess_exec(
                blender, "-b", "--online-mode", path, "--python-expr",
                "import bpy;print('OBJ:'+'|'.join(sorted(o.name for o in bpy.data.objects)))",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
        except Exception:  # pylint: disable=broad-except
            return []
        for line in out.decode("utf-8", "replace").splitlines():
            if line.startswith("OBJ:"):
                return [x for x in line[4:].split("|") if x]
        return []

    def _make_swarm_probe(self, exchange_dir: str) -> "Callable[[], Awaitable[str]]":
        """
        Ground truth for the evaluator in swarm mode (the orchestrator has no
        Blender of its own): read the object lists of the component .blend
        files workers have written to the exchange dir.
        """
        import glob

        async def probe() -> str:
            comps = sorted(glob.glob(os.path.join(exchange_dir, "component_*.blend")))
            if not comps:
                return "(no component .blend files produced yet)"
            lines = ["Components produced so far (objects per file):"]
            total = 0
            for path in comps:
                size = os.path.getsize(path) if os.path.isfile(path) else 0
                objs = await self._read_blend_objects(path)
                total += len(objs)
                if not os.path.isfile(path):
                    detail = "(missing on disk)"
                elif size < _MIN_BLEND_BYTES:
                    detail = "(suspect: only {:d} bytes — export may have failed)".format(size)
                elif objs:
                    detail = "{:d} object(s): {:s}".format(len(objs), ", ".join(objs))
                else:
                    detail = "0 objects (empty or unreadable scene)"
                lines.append("- {:s} [{:d} B]: {:s}".format(
                    os.path.basename(path), size, detail))
            lines.append("Total: {:d} component file(s), {:d} object(s) across them.".format(
                len(comps), total))
            return "\n".join(lines)

        return probe

    def draft_objectives(self, session_id: str, goal: str) -> None:
        """
        Guided intake: draft objectives from a one-line *goal* (LLM), emitting
        ``objectives_draft`` for the composer's editor. Fire-and-forget task.
        """
        from .autonomy import draft_objectives as _draft

        async def _run() -> None:
            try:
                objs = await _draft(self._make_llm(), self._model_name(), goal)
            except Exception as ex:  # pylint: disable=broad-except
                _log.warning("draft_objectives failed: %s", ex)
                objs = []
            await self.emit({
                "type": "objectives_draft", "session_id": session_id,
                "goal": goal, "objectives": objs,
            })

        asyncio.create_task(_run())

    async def run_autonomy_turn(
            self,
            session_id: str,
            objectives: list[dict[str, Any]],
            max_rounds: int | None = None,
    ) -> str:
        """
        Pursue *objectives* (each {id?, text, acceptance}) via the autonomy
        orchestrator: plan -> spawn worker child-sessions -> evaluate scene
        state -> re-round. Runs as the session's turn task; events stream to
        the UI. Returns the session id.
        """
        from .autonomy import (
            AutonomyOrchestrator, AutoPauseWhenBlockedPolicy, AutoUntilDonePolicy,
            IndependentAuditor, LlmPlanner, Objective, SequentialScheduler,
            StateAwareEvaluator, WorkerReviewer,
        )

        if not session_id:
            session_id = self.new_session()
        session = self._get_or_load_session(session_id)
        if session.busy:
            raise RuntimeError("a turn is already running in this session")

        config = self.store.config
        llm = self._make_llm()
        model = self._model_name()

        objs = [
            Objective(
                id=str(o.get("id") or "obj-{:d}".format(i)),
                text=str(o.get("text", "")).strip(),
                acceptance=str(o.get("acceptance", "")).strip(),
            )
            for i, o in enumerate(objectives)
        ]
        # Expose the live objective list so update_objectives can edit/append
        # mid-run; the orchestrator re-reads it each round.
        self._autonomy_objs[session_id] = objs
        rounds_cap = max_rounds or config.max_autonomy_rounds

        # Persist the run to the session transcript so it isn't empty on reload
        # (the live orchestrator view is event-driven/ephemeral). The objectives
        # become the session's first real record (and its title).
        session.engine.push_record({
            "role": "user",
            "content": "**Objectives** (orchestrator, {:d} round{:s} max):\n{:s}".format(
                rounds_cap, "" if rounds_cap == 1 else "s",
                "\n".join(
                    "{:d}. {:s}{:s}".format(
                        i + 1, o.text,
                        "\n   _done when: {:s}_".format(o.acceptance) if o.acceptance else "")
                    for i, o in enumerate(objs))),
            "autonomy_objectives": [dataclasses.asdict(o) for o in objs],
        })

        view = self._reset_view(session_id)   # fresh backend-owned view for this run

        async def persist_emit(event: dict[str, Any]) -> None:
            # Reduce the event into the backend-owned view, then emit the
            # SNAPSHOT (the frontend renders it; it holds no autonomy state).
            # The raw event still flows for non-autonomy consumers; the UI
            # ignores autonomy events now (no JS reducer). Token-driven
            # snapshots are throttled; milestones persist the snapshot to disk.
            changed = False
            try:
                changed = view.apply(event)
            except Exception as ex:  # pylint: disable=broad-except
                _log.warning("orchestrator view.apply failed session=%s: %s", session_id, ex)
            await self.emit(event)
            if changed:
                is_token = event.get("type") == "token"
                now = time.monotonic()
                if (not is_token) or (now - self._view_emit_at.get(session_id, 0.0) >= _VIEW_THROTTLE_SECONDS):
                    self._view_emit_at[session_id] = now
                    await self.emit({"type": "autonomy_view", "session_id": session_id,
                                     "view": view.snapshot()})
                    if not is_token:        # persist on milestones (not every token)
                        self._persist_view(session_id, view)

        policy = (
            AutoPauseWhenBlockedPolicy()
            if config.autonomy_policy == "pause_when_blocked"
            else AutoUntilDonePolicy()
        )

        def media_factory(agent_id: str) -> MediaLibrary:
            safe = agent_id.replace(":", "_")
            return MediaLibrary(os.path.join(self.store.session_dir(session_id), "workers", safe))

        # Worker strategy + scheduler by mode. Default in-process (local child
        # sessions, sequential); swarm = real subprocess workers (own Blender
        # each), fanned out in parallel, exchanging .blend via a shared dir.
        if config.autonomy_workers == "swarm" and config.endpoint:
            from .autonomy import ParallelScheduler
            from .swarm import RemoteWorkerStrategy

            exchange_dir = os.path.join(self.store.session_dir(session_id), "exchange")
            swarm_strategy: "Any" = RemoteWorkerStrategy(
                endpoint=config.endpoint, model=model, exchange_dir=exchange_dir,
                api_key=config.api_key, emit=persist_emit, session_id=session_id,
                register_stop=self._register_swarm_worker,
                unregister_stop=self._unregister_swarm_worker)
            runner: "Callable[[Any], Awaitable[Any]]" = swarm_strategy
            scheduler: "Any" = ParallelScheduler(max_concurrency=4)
            # No local Blender in swarm mode: ground the evaluator on the
            # component .blends the workers wrote to the exchange dir.
            probe: "Callable[[], Awaitable[str]]" = self._make_swarm_probe(exchange_dir)
        else:
            swarm_strategy = None
            probe = self._make_probe(session_id)
            runner = ChildSessionRunner(
                # RBAC: workers get the matrix-filtered tool surface.
                registry=self.registry_for_role("worker"),
                make_llm=self._make_llm,
                model=model,
                emit=persist_emit,
                system_prompt=self._system_prompt,
                media_factory=media_factory,
                parent_session_id=session_id,
                autonomy="auto",
                max_rounds=config.max_rounds,
                context_tokens=config.context_tokens,
                budget_review=config.budget_review,
                register=self._register_worker,
                unregister=self._unregister_worker,
            )
            scheduler = SequentialScheduler()
        # Opt-in dedicated QA reviewer (a fresh LLM context + read-only probe),
        # reviewing each worker's proof before the next worker runs.
        reviewer = (
            WorkerReviewer(self._make_llm(), model, probe=probe)
            if config.autonomy_qa else None
        )
        orchestrator = AutonomyOrchestrator(
            planner=LlmPlanner(llm, model),
            scheduler=scheduler,
            evaluator=StateAwareEvaluator(llm, model, probe=probe),
            policy=policy,
            worker_runner=runner,
            emit=persist_emit,
            session_id=session_id,
            share_context=config.autonomy_share_context,
            reviewer=reviewer,
        )
        rounds = rounds_cap

        def _persist(role: str, content: str) -> None:
            try:
                session.engine.push_record({"role": role, "content": content})
            except Exception as ex:  # pylint: disable=broad-except
                _log.warning("persist autonomy record failed session=%s: %s", session_id, ex)

        async def _run() -> None:
            try:
                result = await orchestrator.run(objs, max_rounds=rounds)
                # Persist a readable outcome so the session reloads with what
                # the orchestrator actually did (not an empty transcript).
                lines = ["**Orchestrator run complete** — {:s} ({:d} round{:s}).".format(
                    "all objectives met" if result.get("all_met") else "stopped with unmet objectives",
                    int(result.get("rounds", 0)), "" if result.get("rounds") == 1 else "s")]
                for o in objs:
                    lines.append("- [{:s}] {:s}{:s}".format(
                        "met" if o.status == "met" else "unmet", o.text,
                        " — {:s}".format(o.evidence) if getattr(o, "evidence", "") else ""))
                _persist("assistant", "\n".join(lines))
                # Swarm: after workers finish, the gather agent merges their
                # component .blends into one master scene.
                if swarm_strategy is not None:
                    master = await swarm_strategy.gather()
                    objects = await self._read_blend_objects(master) if master else []
                    await self.emit({
                        "type": "swarm_gathered", "session_id": session_id,
                        "master": master,
                        "components": swarm_strategy.list_components(),
                        "objects": objects,
                    })
                # Opt-in independent audit: a FRESH LLM context (no shared
                # orchestrator history) re-checks every objective against the
                # real state and calls out reward-hacking / overclaims.
                if config.autonomy_audit:
                    auditor = IndependentAuditor(self._make_llm(), model, probe=probe)
                    report = await auditor.audit(objs)
                    await self.emit({
                        "type": "autonomy_audit",
                        "session_id": session_id,
                        "passed": report.passed,
                        "summary": report.summary,
                        "overclaims": report.overclaims,
                        "verdicts": [dataclasses.asdict(v) for v in report.verdicts],
                    })
                    _persist("assistant", "**Independent audit: {:s}** — {:s}".format(
                        "PASS" if report.passed else "FAIL", report.summary))
            except asyncio.CancelledError:
                await self.emit({"type": "turn_done", "session_id": session_id, "aborted": True})
                raise
            except LlmError as ex:
                await self.emit({"type": "error", "session_id": session_id, "message": str(ex)})
            except Exception as ex:  # pylint: disable=broad-except
                _log.error("autonomy turn failed session=%s: %s", session_id, ex)
                await self.emit({
                    "type": "error", "session_id": session_id,
                    "message": "autonomy error: {:s}: {:s}".format(type(ex).__name__, str(ex)),
                })
            finally:
                self._autonomy_objs.pop(session_id, None)
                await self.emit({"type": "turn_done", "session_id": session_id})

        session.task = asyncio.create_task(_run())
        return session_id

    def update_objectives(
            self, session_id: str,
            objectives: list[dict[str, Any]]) -> "list[dict[str, Any]] | None":
        """
        Mid-run objective update: edit/append the live objectives of a running
        autonomy turn (the orchestrator re-reads them each round) and interject
        the new instructions into any in-process workers that are running right
        now (voice of god). Swarm workers run out of process — they can't be
        interjected mid-task, but the updated objectives still steer the next
        round. Returns the updated objectives payload, or None if no autonomy
        run is live for this session.
        """
        from .autonomy import Objective

        live = self._autonomy_objs.get(session_id)
        if not live:
            return None
        changed: list[str] = []
        for i, spec in enumerate(objectives):
            text = str(spec.get("text", "")).strip()
            if not text:
                continue
            acceptance = str(spec.get("acceptance", "")).strip()
            if i < len(live):
                obj = live[i]
                if obj.text != text or obj.acceptance != acceptance:
                    obj.text, obj.acceptance = text, acceptance
                    obj.status = "unmet"  # re-verify against the new criteria
                    changed.append(obj.text)
            else:
                live.append(Objective(
                    id="obj-upd-{:d}".format(i), text=text, acceptance=acceptance))
                changed.append(text)
        # Interject into in-process workers running under this session.
        note = "[Objectives updated by the user mid-run] Current goals:\n" + "\n".join(
            "- {:s} (done when: {:s})".format(o.text, o.acceptance or "n/a") for o in live)
        for agent_id, engine in list(self._workers.items()):
            if agent_id.startswith(session_id + ":w:"):
                engine.inject(note, now=False)
        return [dataclasses.asdict(o) for o in live]

    def worker_media_library(self, agent_id: str) -> MediaLibrary:
        """
        The media library for an in-process worker, by its agent id. Mirrors
        ``media_factory`` in ``run_autonomy_turn``: workers write under the
        parent session's ``workers/<agent_id>`` jail. Lets the HTTP media route
        serve a worker's tool-produced images (screenshots, renders).
        """
        safe = agent_id.replace(":", "_")
        # Parent session id is the agent id minus its worker/gather suffix.
        parent = agent_id.split(":w:")[0].split(":gather")[0]
        return MediaLibrary(os.path.join(self.store.session_dir(parent), "workers", safe))

    def _register_worker(self, agent_id: str, engine: AgentEngine) -> None:
        self._workers[agent_id] = engine

    def _unregister_worker(self, agent_id: str) -> None:
        self._workers.pop(agent_id, None)

    def _register_swarm_worker(
            self, agent_id: str, stop: "Callable[[], None]") -> None:
        """Track a swarm (subprocess) worker so it can be stopped by id.

        Swarm workers run out of process and are driven over HTTP, so they
        have no live engine to inject into — only a *stop* hook (kill the
        subprocess + cancel the in-flight request)."""
        self._swarm_stoppers[agent_id] = stop

    def _unregister_swarm_worker(self, agent_id: str) -> None:
        self._swarm_stoppers.pop(agent_id, None)

    def worker_supports_injection(self, agent_id: str) -> bool:
        """True only for in-process workers (a live engine to inject into)."""
        return agent_id in self._workers

    def inject_into_worker(self, agent_id: str, content: str, now: bool = False) -> bool:
        """
        Voice of god: push *content* straight into a running worker's context,
        bypassing the orchestrator. *now* cuts its in-flight generation short
        (applied after any running tool finishes); otherwise it lands at the
        worker's next round boundary. Returns False if no such worker is live
        (e.g. a swarm worker, which runs out of process with no engine here).
        """
        engine = self._workers.get(agent_id)
        if engine is None:
            return False
        engine.inject(content, now=now)
        return True

    def interrupt_worker(self, agent_id: str) -> bool:
        """
        Promote a worker's already-queued injection to land now: cut its
        in-flight generation so the guidance applies at once. In-process
        workers only. Returns False if no such live worker.
        """
        engine = self._workers.get(agent_id)
        if engine is None:
            return False
        engine.interrupt()
        return True

    def stop_worker(self, agent_id: str) -> bool:
        """
        Cancel a runaway worker. In-process: cooperatively abort its turn (a
        running tool still finishes). Swarm: kill its subprocess + cancel the
        in-flight request. Returns False if no such live worker.
        """
        engine = self._workers.get(agent_id)
        if engine is not None:
            engine.abort()
            return True
        stop = self._swarm_stoppers.get(agent_id)
        if stop is not None:
            stop()
            return True
        return False

    def confirm_tool(self, session_id: str, call_id: str, approve: bool) -> bool:
        session = self._sessions.get(session_id)
        if session is None:
            return False
        return session.engine.resolve_confirm(call_id, approve)

    def resolve_elicit(self, session_id: str, elicit_id: str, response: dict[str, Any]) -> bool:
        """Deliver the user's answer to a tool waiting on an elicitation."""
        session = self._sessions.get(session_id)
        if session is None:
            return False
        return session.engine.resolve_elicit(elicit_id, response)

    def approve_agent_tool(self, name: str, approve: bool) -> bool:
        """
        Human decision on an agent-authored tool that was saved INERT
        pending import approval. Trusted path (the model cannot reach it):
        flips the registry store so an approved tool becomes runnable, or a
        rejected one is removed. Returns True when a pending tool matched.
        """
        try:
            from blmcp.agent_registry import store
        except ImportError:
            return False
        tool = store.get(name)
        if tool is None or not tool.pending_imports:
            return False
        store.set_approval(name, approve)
        return True

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
        if "autonomy_policy" in updates:
            config.autonomy_policy = str(updates["autonomy_policy"])
        if "max_autonomy_rounds" in updates:
            config.max_autonomy_rounds = max(1, int(updates["max_autonomy_rounds"]))
        if "autonomy_share_context" in updates:
            config.autonomy_share_context = bool(updates["autonomy_share_context"])
        if "autonomy_audit" in updates:
            config.autonomy_audit = bool(updates["autonomy_audit"])
        if "autonomy_qa" in updates:
            config.autonomy_qa = bool(updates["autonomy_qa"])
        if "autonomy_workers" in updates:
            config.autonomy_workers = str(updates["autonomy_workers"])
        if "autonomy_level" in updates:
            config.autonomy_level = str(updates["autonomy_level"])
        self.store.save_config()
        return config.as_public()

    _AUTONOMY_NOTICE = {
        "ask": "Your autonomy was set to ASK: you act directly, but every "
               "mutating tool call pauses for the user's confirmation.",
        "yolo": "Your autonomy was set to YOLO: you act directly and run tool calls "
                "without confirmation. Move fast; verify your own work.",
        "orchestrator": "Your autonomy was set to ORCHESTRATOR: pursue the user's "
                        "OBJECTIVES by planning tasks and delegating to in-process "
                        "worker sub-agents, then verify their proof against the scene.",
        "swarm": "Your autonomy was set to SWARM: objectives are fanned out to "
                 "parallel worker agents, each in its own headless Blender; their "
                 "component .blend files are merged by a final gather agent.",
    }

    def _tool_catalog_summary(self) -> str:
        lines = []
        for tool in self.registry:
            desc = (tool.description or "").strip().splitlines()
            first = desc[0][:100] if desc else ""
            lines.append("- {:s}: {:s}".format(tool.name, first))
        return "\n".join(lines)

    def set_autonomy_level(self, session_id: str, level: str) -> dict[str, object]:
        """
        Set the autonomy slider and, in the session, re-issue the tool catalog
        with a notice that autonomy changed — so the agent re-grounds on its new
        mode on the next turn. Maps the level onto the concrete config knobs.
        """
        if level == "minimal":  # legacy alias
            level = "ask"
        if level not in self._AUTONOMY_NOTICE:
            level = "yolo"
        config = self.store.config
        config.autonomy_level = level
        config.autonomy = "ask" if level == "ask" else "auto"
        config.autonomy_workers = "swarm" if level == "swarm" else "in_process"
        self.store.save_config()
        # Swarm spawns a Blender per worker on the host — surface its
        # cross-platform requirements (and any missing ones) up front.
        swarm_ready, swarm_report = True, ""
        if level == "swarm":
            from .blender_surface import swarm_preflight
            swarm_ready, swarm_report = swarm_preflight()
        if session_id:
            session = self._get_or_load_session(session_id)
            notice = "[Autonomy changed] {:s}\n\nYour current tool catalog:\n{:s}".format(
                self._AUTONOMY_NOTICE[level], self._tool_catalog_summary())
            if swarm_report:
                notice += "\n\n{:s}".format(swarm_report)
            session.engine.push_record({
                "role": "user", "content": notice,
                "synthetic": True, "autonomy_notice": level,
            })
        public = config.as_public()
        if level == "swarm":
            # Let the UI warn the user about missing requirements (e.g. no
            # Blender / no Xvfb) at the moment they pick swarm.
            public["swarm_preflight"] = {"ready": swarm_ready, "report": swarm_report}
        return public
