# SPDX-FileCopyrightText: 2026 agentcore contributors
#
# SPDX-License-Identifier: MIT OR Apache-2.0

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
import uuid


from typing import Any, Awaitable, Callable

from .agent_tools import (
    AskOrchestratorTool, AskUserTool, ContinueWorkingTool, MediaTool, SetAutonomyTool, SkillsTool)
from agentcore.backend import PythonToolBackend, ToolBackend
from .engine import AgentEngine, _strip_thinking
from .orchestrator_view import OrchestratorView
from .permissions import ToolPermissions, WORKER_DENY
from .profile import AgentProfile
from agentcore.llm import LlmClient, LlmError, LocalLlmBridgeClient, OpenAiHttpClient
from agentcore.media import MediaLibrary
from .store import AgentStore, SessionBusyError
from agentcore.tools import Tool, ToolContext, ToolRegistry
from .local_llm import LocalLlmBridge

_log = logging.getLogger("blagent.runtime")

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
with a human. STRONGLY prefer to make the most reasonable interpretation, ACT,
verify, and report — noting any assumptions in your proof of work. Only if the
task is genuinely ambiguous and a wrong guess would waste real work, you may
call `ask_orchestrator` once; the orchestrator answers from context or, rarely,
asks the user. Never wait for approval otherwise.

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

## SAVE BEFORE RISKY EDITS
Before any heavy or crash-prone operation — large boolean / remesh / voxel ops,
high subdivision or applying modifiers on dense meshes, big imports, physics or
particle bakes — first snapshot the file with `media_io` (verb 'export', format
'blend'). Cheap insurance: if Blender hangs or crashes, the prior work survives.

When finished, end your turn with a short PROOF OF WORK: what you changed and
concrete evidence (object names, counts, verify output, a rendered image). To
show the scene visually, RENDER it (media_io verb 'render', or
capture verb 'render') — this Blender is headless, so viewport screenshot
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
        # Engines kept alive between review cycles (continue_ / release).
        self._live: dict[str, dict[str, Any]] = {}

    async def __call__(self, task: Any) -> Any:
        agent_id = "{:s}:w:{:s}".format(self._parent, task.id)
        records: list[dict[str, Any]] = []

        async def child_emit(event: dict[str, Any]) -> None:
            await self._emit({**event, "parent_session_id": self._parent, "role": "worker"})

        # Pin the full mission in the SYSTEM prompt (which _fit_context never
        # trims), so huge welcome/scene-summary tool results can't push the
        # worker's task out of context and disorient it.
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
            append_record=records.append,
            trace_label="worker:{:s}".format(agent_id),
        )
        # Kept alive so the orchestrator can replenish the budget and continue
        # the SAME worker (continue_) after a review; released explicitly.
        self._live[agent_id] = {"engine": engine, "records": records, "task": task}
        if self._register is not None:
            self._register(agent_id, engine)
        return await self._turn(
            agent_id, engine, records, task,
            "Begin now — execute your assigned task end to end, then report your proof of work.")

    async def _turn(self, agent_id: str, engine: "AgentEngine",
                    records: list[dict[str, Any]], task: Any, user_text: str) -> Any:
        from .autonomy import WorkerResult
        try:
            await engine.run_turn(
                session_id=agent_id, user_text=user_text, llm=self._make_llm(),
                model=self._model, autonomy=self._autonomy, max_rounds=self._max_rounds,
                context_tokens=self._context_tokens, budget_review=self._budget_review)
        except Exception as ex:  # pylint: disable=broad-except
            _log.warning("worker %s failed: %s", task.id, ex)
            return WorkerResult(
                task_id=task.id, objective_id=task.objective_id,
                proof="worker errored: {:s}".format(ex), ok=False, transcript_ref=agent_id)
        proof = self._extract_proof(records)
        return WorkerResult(
            task_id=task.id, objective_id=task.objective_id,
            proof=proof or "(worker produced no final report)",
            ok=bool(proof), transcript_ref=agent_id)

    async def continue_(self, task: Any, guidance: str) -> Any:
        """Replenish the worker's budget and continue the SAME engine with the
        orchestrator's guidance (after a review cycle)."""
        agent_id = "{:s}:w:{:s}".format(self._parent, task.id)
        live = self._live.get(agent_id)
        if live is None:
            return await self(task)
        return await self._turn(
            agent_id, live["engine"], live["records"], task,
            "[Orchestrator guidance — your tool budget is replenished. Address this, then "
            "report your updated proof of work.]\n{:s}".format(guidance))

    def release(self, task: Any) -> None:
        agent_id = "{:s}:w:{:s}".format(self._parent, task.id)
        self._live.pop(agent_id, None)
        if self._unregister is not None:
            self._unregister(agent_id)

    @staticmethod
    def _extract_proof(records: list[dict[str, Any]]) -> str:
        # The proof is the worker's latest CLAIM (shown in the card, judged by
        # the evaluator) — not its chain-of-thought, so strip the reasoning.
        for record in reversed(records):
            if record.get("role") == "assistant":
                content = _strip_thinking(str(record.get("content", ""))).strip()
                if content:
                    return content
        return ""

_DEFAULT_SYSTEM_PROMPT = (
    "You are a capable autonomous agent operating a workspace through a set of "
    "tools. Use the tools to accomplish the user's request, verify your own "
    "work, and report concisely what you did. Prefer acting over asking when the "
    "intent is clear."
)

# The orchestrator/swarm run state is owned by the BACKEND: events are reduced
# into an OrchestratorView (blagent.orchestrator_view) and the snapshot is
# emitted as `autonomy_view` + persisted, so the frontend is a pure projection
# (it renders the snapshot; it does NOT reduce events). Token-driven snapshots
# are throttled to this interval to avoid flooding the socket on live streaming.
_VIEW_THROTTLE_SECONDS = 0.12

_ORCH_DECIDE_SYSTEM = (
    "You are the ORCHESTRATOR of a Blender autonomy run. A worker sub-agent hit "
    "a genuinely unclear point and asked a question. You hold the objective "
    "context. STRONGLY prefer answering it yourself from the objectives and "
    "sensible defaults — do NOT bother the user unless the question truly cannot "
    "be resolved without a human decision (a real preference or missing intent "
    "only they can supply). Reply with ONLY a JSON object: either "
    '{"answer": "<direct answer to the worker>"} or, only if you must, '
    '{"escalate": true, "question": "<the question rephrased for the user>"}.'
)

_REVIEW_SYSTEM = (
    "You are the ORCHESTRATOR of a Blender autonomy run, reviewing ONE worker's "
    "result against its task and acceptance criteria, using the project-state "
    "evidence (and any QA inspector findings) as ground truth — not the worker's "
    "narrative. Decide: is this piece of work good enough to accept? If not, give "
    "SPECIFIC, actionable guidance the worker can act on with a replenished tool "
    "budget. Set request_qa when you need an independent inspection of the scene "
    "before judging. If the worker was STOPPED by the user, do NOT ask to re-run "
    "it — accept the partial result and note what remains. Reply with ONLY a JSON "
    'object: {"accept": true|false, "guidance": "<what to fix, if not accepted>", '
    '"request_qa": true|false}.'
)

_QA_INSPECT_MISSION = """

---
# YOUR ROLE: QA inspector
A worker just finished a task and CLAIMS a result. Independently INSPECT the
actual scene to verify the claim against the acceptance criteria. You MAY use
any tools to see the result (move the camera, render a view, run diagnostics),
but do NOT redo the worker's task or make substantive edits. Be quick — a couple
of tool calls at most. Then end your turn with concise QA FINDINGS: what holds
up, and what is missing or wrong.

## THE TASK UNDER REVIEW
{instruction}

## ACCEPTANCE CRITERIA
{acceptance}

## THE WORKER'S CLAIM
{proof}
"""


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

    # When set (e.g. "worker" for a swarm sub-agent process), every session
    # engine uses the RBAC-filtered registry for that role instead of the full
    # surface — so a worker process can't reach set_autonomy/ask_user. Class
    # default keeps it defined across both constructors (__init__ and create()).
    session_role: "str | None" = None

    def __init__(self, store: AgentStore, backend: "ToolBackend | list[Tool]",
                 profile: "AgentProfile | None" = None,
                 permissions: "ToolPermissions | None" = None) -> None:
        self.store = store
        # Domain flavor (brand/copy/prompts). Defaults to the Blender build's
        # profile; a YAML build passes its own.
        self.profile = profile or AgentProfile()
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
        # Domain swarm surface (subprocess workers + their ground-truth probe).
        # None on a generic build -> swarm mode falls back to in-process workers.
        # The Blender build sets this to a BlenderSwarmProvider.
        self.swarm_provider: "Any" = None
        # Registry backing agent-authored tools (get/set_approval). None on a
        # build without a tool-authoring surface -> approval is a no-op. The
        # Blender build sets this to blmcp.agent_registry.store.
        self.agent_tool_registry: "Any" = None
        # Live autonomy objective lists by session id, for mid-run updates.
        self._autonomy_objs: dict[str, list[Any]] = {}
        self._stopped_workers: set[str] = set()
        # Autonomy-level switch requested mid-turn: applied when the turn ends
        # (or immediately on stop), so a switch never disrupts a running turn.
        self._pending_autonomy: dict[str, str] = {}
        # Backend-owned orchestrator view (the frontend projects its snapshot).
        self._views: dict[str, OrchestratorView] = {}
        # session_id -> run_id of the run currently being reduced into _views,
        # so its events/snapshots persist to runs/<run_id>.json (durable history).
        self._active_run: dict[str, str] = {}
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
        from agentcore.backend import registry_from_backend

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
        self._stopped_workers = set()
        self._pending_autonomy = {}
        self._views = {}
        self._active_run = {}
        self._view_emit_at = {}
        self._subscribers = set()
        self._system_prompt = self._load_system_prompt()
        return self

    def _load_system_prompt(self) -> str:
        # The domain build supplies the base prompt via its profile; agentcore
        # falls back to a neutral default.
        return self.profile.system_prompt or _DEFAULT_SYSTEM_PROMPT

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

        # A worker sub-agent process (session_role="worker") gets the
        # RBAC-filtered surface — no set_autonomy/ask_user — matching the
        # in-process orchestrator workers. Default: the full registry.
        registry = self.registry if not self.session_role else self.registry_for_role(self.session_role)
        engine = AgentEngine(
            registry=registry,
            media=media,
            system_prompt=self._system_prompt,
            emit=self.emit,
            append_record=_append_record,
            trace_label="chat:{:s}".format(session_id),
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
        # Legacy single-view file (pre per-run runs/). Only READ now, for
        # back-compat of sessions recorded before per-run durability.
        return os.path.join(self.store.session_dir(session_id), "autonomy_view.json")

    def _run_view_path(self, session_id: str, run_id: str) -> str:
        return os.path.join(self.store.session_dir(session_id), "runs", "{:s}.json".format(run_id))

    def _reset_view(self, session_id: str) -> "OrchestratorView":
        """Fresh live/scratch view for a new draft or the next run. Does NOT
        delete any durable per-run files: orchestrator runs are kept permanently
        under runs/<run_id>.json so a prior run survives a later draft/run and a
        reload (the backend is the source of truth, the UI a pure projection)."""
        view = OrchestratorView()
        self._views[session_id] = view
        self._active_run.pop(session_id, None)
        return view

    def _begin_run_view(self, session_id: str, run_id: str) -> "OrchestratorView":
        """Start a fresh DURABLE view for a new orchestrator run (persisted to its
        own runs/<run_id>.json), leaving earlier runs intact."""
        view = OrchestratorView()
        self._views[session_id] = view
        self._active_run[session_id] = run_id
        return view

    def _persist_emit_for(
            self, session_id: str,
            view: "OrchestratorView",
            run_id: "str | None" = None) -> "Callable[[dict[str, Any]], Awaitable[None]]":
        """Build the emit used by autonomy runs AND guided-intake drafting:
        reduce each event into the backend-owned view, emit the raw event for
        non-autonomy consumers, then emit the view SNAPSHOT (the frontend's only
        autonomy state — a pure projection). Token-like deltas are throttled;
        milestones persist the snapshot so a reload re-projects the latest. Every
        event is tagged with *run_id* (when this is a run) so the UI files it
        under the right run block — multiple runs coexist in one session."""
        async def persist_emit(event: dict[str, Any]) -> None:
            if run_id is not None and "run_id" not in event:
                event["run_id"] = run_id
            changed = False
            try:
                changed = view.apply(event)
            except Exception as ex:  # pylint: disable=broad-except
                _log.warning("orchestrator view.apply failed session=%s: %s", session_id, ex)
            await self.emit(event)
            if changed:
                t = event.get("type")
                is_token = t == "token" or (t == "planner_stream" and event.get("state") == "delta")
                now = time.monotonic()
                if (not is_token) or (now - self._view_emit_at.get(session_id, 0.0) >= _VIEW_THROTTLE_SECONDS):
                    self._view_emit_at[session_id] = now
                    await self.emit({"type": "autonomy_view", "session_id": session_id,
                                     "run_id": run_id, "view": view.snapshot()})
                    if not is_token:        # persist on milestones (not every token)
                        self._persist_view(session_id, view, run_id)
        return persist_emit

    def _autonomy_prompts(self, session_id: str) -> list[str]:
        """The user's intake prompts (the request that shaped the objectives),
        in order — shown in the Request card above the objectives."""
        out: list[str] = []
        for r in self.session_records(session_id):
            if r.get("autonomy_goal") and str(r.get("content", "")).strip():
                out.append(str(r["content"]).strip())
        return out

    def _finalize_stopped_view(self, session_id: str) -> None:
        """On stop/abort, finalize the view so no worker card shows stale 'running'
        controls, then re-emit + persist the snapshot."""
        view = self._views.get(session_id)
        if view is None:
            return
        view.mark_stopped()
        self._persist_view(session_id, view)
        try:
            asyncio.create_task(self.emit({
                "type": "autonomy_view", "session_id": session_id, "view": view.snapshot()}))
        except RuntimeError:
            pass

    def _persist_view(self, session_id: str, view: "OrchestratorView",
                      run_id: "str | None" = None) -> None:
        # Runs persist to their own durable file; a draft (no active run) is not
        # persisted — it is restored from the last draft record on reload.
        rid = run_id if run_id is not None else self._active_run.get(session_id)
        if rid is None:
            return
        try:
            path = self._run_view_path(session_id, rid)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(view.snapshot(), fh, default=str)
        except Exception as ex:  # pylint: disable=broad-except
            _log.warning("persist autonomy run view failed session=%s run=%s: %s", session_id, rid, ex)

    def session_autonomy_view(self, session_id: str) -> "dict[str, Any] | None":
        """The current LIVE orchestrator view (an active run or in-progress
        draft), or None on a cold reload. Completed runs come from
        ``session_autonomy_runs`` — the durable, per-run source of truth."""
        view = self._views.get(session_id)
        return view.snapshot() if view is not None else None

    def _read_legacy_view(self, session_id: str) -> "dict[str, Any] | None":
        path = self._view_path(session_id)
        if not os.path.isfile(path):
            return None
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception as ex:  # pylint: disable=broad-except
            _log.warning("read legacy autonomy view failed session=%s: %s", session_id, ex)
            return None

    def session_autonomy_runs(self, session_id: str) -> "list[dict[str, Any]]":
        """Every orchestrator run in this session, in transcript order, each as
        ``{run_id, view}`` — the durable history the UI projects. Each run is
        marked by its ``autonomy_objectives`` transcript record. The run's view
        comes from (in order): the live in-memory view if it's the active run;
        runs/<run_id>.json; the single legacy view file (pre per-run sessions);
        else a minimal view synthesized from the record's objectives (so the run
        still shows even if its worker view was lost — e.g. wiped by an older
        build before this fix)."""
        runs: list[dict[str, Any]] = []
        active = self._active_run.get(session_id)
        live = self._views.get(session_id)
        records = self.session_records(session_id)
        legacy_used = False
        for idx, record in enumerate(records):
            if not record.get("autonomy_objectives"):
                continue
            rid = record.get("autonomy_run_id")
            snap: "dict[str, Any] | None" = None
            if rid and rid == active and live is not None:
                snap = live.snapshot()
            elif rid:
                path = self._run_view_path(session_id, str(rid))
                if os.path.isfile(path):
                    try:
                        with open(path, encoding="utf-8") as fh:
                            snap = json.load(fh)
                    except Exception as ex:  # pylint: disable=broad-except
                        _log.warning("read run view failed session=%s run=%s: %s", session_id, rid, ex)
            if snap is None and not legacy_used:
                legacy = self._read_legacy_view(session_id)
                if legacy and (legacy.get("agentOrder") or legacy.get("done") or legacy.get("objectives")):
                    snap, legacy_used = legacy, True
            if snap is None:
                snap = self._synth_run_view(records, idx)
            runs.append({"run_id": str(rid or "run-{:d}".format(idx)), "view": snap})
        return runs

    @staticmethod
    def _synth_run_view(records: "list[dict[str, Any]]", idx: int) -> "dict[str, Any]":
        """A minimal view for a run whose durable view is gone: its objectives,
        and the request that preceded it. No worker cards (that data is lost)."""
        record = records[idx]
        prompts: list[str] = []
        for j in range(idx - 1, -1, -1):
            prev = records[j]
            if prev.get("autonomy_objectives"):
                break
            if prev.get("autonomy_goal") and str(prev.get("content", "")).strip():
                prompts.insert(0, str(prev["content"]).strip())
        return {
            "prompts": prompts,
            "objectives": record.get("autonomy_objectives") or [],
            "agents": {}, "agentOrder": [], "rounds": [],
            "gathered": None, "done": None, "audit": None, "planner": None,
            "currentRound": 0, "draft": None, "recovered": True,
        }

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
            finally:
                await self._apply_pending_autonomy(session_id)

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

    def _make_orchestrator_ask(
            self, session_id: str,
            emit: "Callable[[dict[str, Any]], Awaitable[None]]",
    ) -> "Callable[[str, str, list[str]], Awaitable[dict[str, Any]]]":
        """A worker's ``ask_orchestrator`` channel: the orchestrator decides
        from objective context whether to answer directly or escalate to the
        user. All logic is backend; the user only ever sees a prompt (the
        existing elicitation). The Q&A reduces into the view snapshot."""
        async def ask(worker_id: str, question: str, options: list[str]) -> dict[str, Any]:
            await emit({"type": "worker_question", "session_id": worker_id,
                        "parent_session_id": session_id, "role": "worker",
                        "question": question, "options": options})
            decision = await self._orchestrator_decide(session_id, question, options)
            if decision.get("escalate"):
                resp = await self._get_or_load_session(session_id).engine._elicit(  # noqa: SLF001
                    session_id, question=str(decision.get("question") or question),
                    options=options)
                answer = "; ".join(
                    [c for c in (resp.get("choices") or [])]
                    + ([resp.get("text")] if resp.get("text") else [])).strip()
                if resp.get("cancelled") or not answer:
                    answer = "the user did not answer — use your best judgement and state your assumption"
                source = "user"
            else:
                answer = str(decision.get("answer", "")).strip()
                source = "orchestrator"
            await emit({"type": "worker_question_answered", "session_id": worker_id,
                        "parent_session_id": session_id, "role": "worker",
                        "answer": answer, "source": source})
            return {"answer": answer, "source": source}

        return ask

    async def _orchestrator_decide(
            self, session_id: str, question: str, options: list[str]) -> dict[str, Any]:
        from .autonomy import _complete, _extract_json_object

        objs = self._autonomy_objs.get(session_id) or []
        listing = "\n".join(
            "- {:s} (done when: {:s})".format(o.text, o.acceptance or "n/a") for o in objs
        ) or "(no objectives on record)"
        user = "OBJECTIVES:\n{:s}\n\nA worker asks:\n{:s}\n\nOptions it offered: {:s}".format(
            listing, question, ", ".join(options) or "(none)")
        try:
            text = await _complete(self._make_llm(), self._model_name(), _ORCH_DECIDE_SYSTEM, user,
                                   trace_label="orchestrator_decide")
        except Exception as ex:  # pylint: disable=broad-except
            _log.warning("orchestrator decision failed session=%s: %s", session_id, ex)
            return {"escalate": True, "question": question}
        data = _extract_json_object(text)
        if data.get("escalate") and not str(data.get("answer", "")).strip():
            return {"escalate": True, "question": str(data.get("question") or question)}
        return {"answer": str(data.get("answer", "")).strip()}

    def _make_reviewing_runner(
            self, session_id: str, runner: "ChildSessionRunner",
            emit: "Callable[[dict[str, Any]], Awaitable[None]]",
            probe: "Callable[[], Awaitable[str]]", model: str,
            *, qa_enabled: bool, media_factory: "Callable[[str], MediaLibrary]",
            max_cycles: int = 3) -> "Callable[[Any], Awaitable[Any]]":
        """Wrap a worker runner with the per-worker review loop: the orchestrator
        is pinged with every result, optionally spawns a bounded QA inspector,
        then accepts or replenishes the worker's budget with guidance (capped).
        Returned callable is the orchestrator's worker_runner — the loop is
        invisible to AutonomyOrchestrator."""
        async def reviewing(task: Any) -> Any:
            worker_id = "{:s}:w:{:s}".format(session_id, task.id)
            result = await runner(task)
            try:
                for attempt in range(max_cycles):
                    stopped = worker_id in self._stopped_workers
                    qa = ""
                    if qa_enabled and not stopped:
                        qa = await self._qa_inspect(session_id, task, result, emit, model,
                                                    media_factory, attempt)
                    decision = await self._review_worker(session_id, task, result, qa, stopped)
                    if decision.get("request_qa") and not qa and not stopped:
                        qa = await self._qa_inspect(session_id, task, result, emit, model,
                                                    media_factory, attempt)
                        decision = await self._review_worker(session_id, task, result, qa, stopped)
                    accept = bool(decision.get("accept")) or stopped
                    guidance = str(decision.get("guidance", "")).strip()
                    await emit({
                        "type": "worker_review", "session_id": session_id, "agent_id": worker_id,
                        "passed": accept, "note": guidance, "qa": qa,
                        "attempt": attempt, "stopped": stopped})
                    if accept or attempt == max_cycles - 1 or not guidance:
                        break
                    result = await runner.continue_(task, guidance)
            except Exception as ex:  # pylint: disable=broad-except
                _log.warning("review loop failed session=%s task=%s: %s", session_id, task.id, ex)
            finally:
                runner.release(task)
                self._stopped_workers.discard(worker_id)
            return result

        return reviewing

    async def _review_worker(
            self, session_id: str, task: Any, result: Any,
            qa_findings: str, stopped: bool) -> dict[str, Any]:
        """The orchestrator's per-worker verdict: accept, or guidance to re-run."""
        from .autonomy import _complete, _extract_json_object

        state = "(no project-state probe configured)"
        try:
            state = await self._make_probe(session_id)()
        except Exception:  # pylint: disable=broad-except
            pass
        user = (
            "TASK: {:s}\nACCEPTANCE: {:s}\n\nWORKER CLAIM:\n{:s}\n\n"
            "QA INSPECTOR FINDINGS:\n{:s}\n\nPROJECT STATE (ground truth):\n{:s}\n\n"
            "{:s}".format(
                task.instruction, getattr(task, "acceptance", "") or "(n/a)",
                result.proof or "(no proof)", qa_findings or "(no QA inspection)",
                state, "NOTE: the user STOPPED this worker." if stopped else "")
        )
        try:
            text = await _complete(self._make_llm(), self._model_name(), _REVIEW_SYSTEM, user,
                                   trace_label="orchestrator_review")
        except Exception as ex:  # pylint: disable=broad-except
            _log.warning("worker review failed session=%s: %s", session_id, ex)
            return {"accept": True, "guidance": "", "request_qa": False}
        data = _extract_json_object(text)
        return {"accept": bool(data.get("accept", False)),
                "guidance": str(data.get("guidance", "")).strip(),
                "request_qa": bool(data.get("request_qa", False))}

    async def _qa_inspect(
            self, session_id: str, task: Any, result: Any,
            emit: "Callable[[dict[str, Any]], Awaitable[None]]", model: str,
            media_factory: "Callable[[str], MediaLibrary]", attempt: int) -> str:
        """A bounded QA inspector sub-agent (full tool surface, few rounds): it
        inspects the scene to verify the worker's claim and reports findings.
        Spawns as its own qa-role agent card."""
        qa_id = "{:s}:qa:{:s}:{:d}".format(session_id, task.id, attempt)
        worker_id = "{:s}:w:{:s}".format(session_id, task.id)
        await emit({"type": "agent_spawned", "session_id": session_id, "agent_id": qa_id,
                    "role": "qa", "objective_id": task.objective_id,
                    "task": "QA inspect — {:s}".format(task.instruction), "reviews": worker_id})
        records: list[dict[str, Any]] = []

        async def qa_emit(event: dict[str, Any]) -> None:
            await emit({**event, "parent_session_id": session_id, "role": "qa"})

        system = self._system_prompt + _QA_INSPECT_MISSION.format(
            instruction=task.instruction,
            acceptance=getattr(task, "acceptance", "") or "(n/a)",
            proof=result.proof or "(no proof)")
        engine = AgentEngine(
            registry=self.registry_for_role("worker"),   # full surface (camera/render ok)
            media=media_factory(qa_id), system_prompt=system,
            emit=qa_emit, append_record=records.append,
            trace_label="qa:{:s}".format(qa_id))
        findings = ""
        try:
            await engine.run_turn(
                session_id=qa_id, user_text="Inspect now and report your QA findings.",
                llm=self._make_llm(), model=model, autonomy="auto", max_rounds=2,
                context_tokens=0, budget_review=False)
            for r in reversed(records):
                if r.get("role") == "assistant":
                    c = _strip_thinking(str(r.get("content", ""))).strip()
                    if c:
                        findings = c
                        break
        except Exception as ex:  # pylint: disable=broad-except
            _log.warning("qa inspect failed session=%s: %s", session_id, ex)
            findings = "QA inspection errored: {:s}".format(ex)
        await emit({"type": "agent_done", "session_id": session_id, "agent_id": qa_id,
                    "role": "qa", "objective_id": task.objective_id,
                    "ok": bool(findings), "proof": findings or "(no findings)"})
        return findings

    async def _probe_state(self, session_id: str) -> str:
        """The Blender ground-truth probe wired into the PythonToolBackend:
        a read-only scene snapshot via ``scene("objects")``. (Lives here
        until the Blender backend factory owns it after the package split.)"""
        tool = self.registry.get("scene")
        if tool is None:
            return "(scene unavailable)"
        media = self._get_or_load_session(session_id).media
        try:
            result = await tool.call(
                ToolContext(media=media, session_id=session_id),
                {"verb": "objects", "args": {}})
        except Exception as ex:  # pylint: disable=broad-except
            return "(scene probe failed: {:s})".format(ex)
        data = result.data if result.data is not None else result.summary
        text = data if isinstance(data, str) else json.dumps(data, default=str)
        return text[:6000]

    def _conversation_context(self, session_id: str, limit: int = 4000) -> str:
        """
        The recent genuine conversation for this session (the user's notes and
        the agent's replies), so the draft/planner reflect what was actually
        discussed — not just the bare goal/objectives. Excludes the synthetic
        objective/draft/goal records (those are derived and passed separately),
        and keeps the most recent *limit* characters.
        """
        lines: list[str] = []
        for record in self.session_records(session_id):
            if (record.get("autonomy_objectives") or record.get("autonomy_objectives_draft")
                    or record.get("autonomy_goal") or record.get("autonomy_notice")):
                continue
            role = record.get("role")
            content = record.get("content")
            if role not in ("user", "assistant") or not isinstance(content, str) or not content.strip():
                continue
            lines.append("{:s}: {:s}".format(role, content.strip()))
        text = "\n".join(lines)
        if len(text) > limit:
            text = "…(earlier conversation omitted)…\n" + text[-limit:]
        return text

    def draft_objectives(self, session_id: str, goal: str) -> str:
        """
        Guided intake: draft objectives from a one-line *goal* (LLM). Surfaces a
        live PLANNING CARD via the backend view (``planner_stream`` -> snapshot)
        so the work isn't dropped between submit and objectives appearing, and
        PERSISTS the request + draft to the session so history survives reload.
        Emits ``objectives_draft`` for the composer's read-only list. Returns the
        session id (created when absent) so the caller can adopt it.
        """
        from .autonomy import draft_objectives as _draft

        if not session_id:
            session_id = self.new_session()
        session = self._get_or_load_session(session_id)
        # Prior conversation (the user's notes + agent replies) BEFORE this goal
        # record is pushed, so the draft reflects what was discussed.
        conversation = self._conversation_context(session_id)
        view = self._reset_view(session_id)
        persist_emit = self._persist_emit_for(session_id, view)
        # The submitted request is intake (shown in the Request card + persisted
        # for title), not a raw bottom-of-transcript bubble.
        try:
            session.engine.push_record({
                "role": "user", "content": goal, "autonomy_goal": True,
                "synthetic": True, "title": goal[:80]})
        except Exception as ex:  # pylint: disable=broad-except
            _log.warning("persist draft goal failed session=%s: %s", session_id, ex)

        async def _run() -> None:
            await persist_emit({"type": "autonomy_goal", "session_id": session_id,
                                "prompts": self._autonomy_prompts(session_id)})
            await persist_emit({"type": "planner_stream", "session_id": session_id,
                                "phase": "draft", "state": "start"})

            async def on_delta(content: str, reasoning: str) -> None:
                await persist_emit({"type": "planner_stream", "session_id": session_id,
                                    "phase": "draft", "state": "delta",
                                    "content": content, "reasoning": reasoning})
            try:
                objs = await _draft(self._make_llm(), self._model_name(), goal,
                                    on_delta=on_delta, context=conversation)
            except Exception as ex:  # pylint: disable=broad-except
                _log.warning("draft_objectives failed: %s", ex)
                objs = []
            await persist_emit({"type": "planner_stream", "session_id": session_id,
                                "phase": "draft", "state": "done"})
            await self.emit({
                "type": "objectives_draft", "session_id": session_id,
                "goal": goal, "objectives": objs,
            })
            if objs:
                try:
                    session.engine.push_record({
                        "role": "assistant",
                        "content": "**Proposed objectives** for: {:s}\n{:s}".format(
                            goal, "\n".join(
                                "{:d}. {:s}{:s}".format(
                                    i + 1, o["text"],
                                    "\n   _done when: {:s}_".format(o["acceptance"]) if o.get("acceptance") else "")
                                for i, o in enumerate(objs))),
                        "autonomy_objectives_draft": objs,
                        "synthetic": True,
                    })
                except Exception as ex:  # pylint: disable=broad-except
                    _log.warning("persist draft objectives failed session=%s: %s", session_id, ex)
            self._persist_view(session_id, view)

        asyncio.create_task(_run())
        return session_id

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
            StateAwareEvaluator,
        )

        if not session_id:
            session_id = self.new_session()
        session = self._get_or_load_session(session_id)
        if session.busy:
            raise RuntimeError("a turn is already running in this session")

        config = self.store.config
        llm = self._make_llm()
        model = self._model_name()
        # Prior conversation, captured before the objectives record is pushed,
        # so the planner's task instructions carry the user's actual intent.
        conversation = self._conversation_context(session_id)

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
        # Stable id for THIS run: its objectives record carries it, and the run's
        # durable view persists to runs/<run_id>.json. Lets the session hold many
        # runs without one clobbering another.
        run_id = uuid.uuid4().hex[:12]

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
            "autonomy_run_id": run_id,   # ties this run's durable view to its place
            "synthetic": True,   # shown via the Objectives card, not a raw bubble
            "title": objs[0].text if objs else "Orchestrator run",
        })

        view = self._begin_run_view(session_id, run_id)   # fresh DURABLE per-run view
        persist_emit = self._persist_emit_for(session_id, view, run_id)

        policy = (
            AutoPauseWhenBlockedPolicy()
            if config.autonomy_policy == "pause_when_blocked"
            else AutoUntilDonePolicy()
        )

        def media_factory(agent_id: str) -> MediaLibrary:
            safe = agent_id.replace(":", "_")
            return MediaLibrary(os.path.join(self.store.session_dir(session_id), "workers", safe))

        # Worker strategy + scheduler by mode. Default in-process (local child
        # sessions, sequential); swarm = real subprocess workers (own compute
        # surface each), fanned out in parallel, exchanging artifacts via a
        # shared dir. Swarm needs a domain swarm_provider (the Blender build
        # supplies one); without it, fall back to in-process workers.
        if config.autonomy_workers == "swarm" and config.endpoint and self.swarm_provider is not None:
            from .autonomy import ParallelScheduler

            exchange_dir = os.path.join(self.store.session_dir(session_id), "exchange")
            swarm_strategy: "Any" = self.swarm_provider.make_strategy(
                endpoint=config.endpoint, model=model, exchange_dir=exchange_dir,
                api_key=config.api_key, emit=persist_emit, session_id=session_id,
                register_stop=self._register_swarm_worker,
                unregister_stop=self._unregister_swarm_worker)
            runner: "Callable[[Any], Awaitable[Any]]" = swarm_strategy
            scheduler: "Any" = ParallelScheduler(max_concurrency=4)
            # No local compute surface in swarm mode: ground the evaluator on
            # the artifacts the workers wrote to the exchange dir.
            probe: "Callable[[], Awaitable[str]]" = self.swarm_provider.make_probe(exchange_dir)
        else:
            swarm_strategy = None
            probe = self._make_probe(session_id)
            worker_registry = ToolRegistry(
                list(self.registry_for_role("worker"))
                + [AskOrchestratorTool(self._make_orchestrator_ask(session_id, persist_emit))])
            runner = ChildSessionRunner(
                registry=worker_registry,
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
        # Per-worker review loop: the orchestrator is pinged with every worker
        # result, optionally spawns a bounded QA inspector, then accepts or
        # replenishes the worker's budget with guidance (capped). In-process
        # only — swarm workers run out of process with no continuation handle.
        review_runner = runner
        if swarm_strategy is None:
            review_runner = self._make_reviewing_runner(
                session_id, runner, persist_emit, probe, model,
                qa_enabled=config.autonomy_qa, media_factory=media_factory)
        orchestrator = AutonomyOrchestrator(
            planner=LlmPlanner(llm, model, emit=persist_emit, session_id=session_id,
                               context=conversation),
            scheduler=scheduler,
            evaluator=StateAwareEvaluator(llm, model, probe=probe),
            policy=policy,
            worker_runner=review_runner,
            emit=persist_emit,
            session_id=session_id,
            share_context=config.autonomy_share_context,
        )
        rounds = rounds_cap

        def _persist(role: str, content: str) -> None:
            try:
                session.engine.push_record({"role": role, "content": content})
            except Exception as ex:  # pylint: disable=broad-except
                _log.warning("persist autonomy record failed session=%s: %s", session_id, ex)

        async def _run() -> None:
            try:
                await persist_emit({"type": "autonomy_goal", "session_id": session_id,
                                    "prompts": self._autonomy_prompts(session_id)})
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
                # component artifacts into one master result.
                if swarm_strategy is not None:
                    master = await swarm_strategy.gather()
                    objects = (await self.swarm_provider.read_result_objects(master)
                               if master else [])
                    await self.emit({
                        "type": "swarm_gathered", "session_id": session_id,
                        "master": master,
                        "components": swarm_strategy.list_artifacts(),
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
                self._finalize_stopped_view(session_id)
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
                await self._apply_pending_autonomy(session_id)

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
            self._stopped_workers.add(agent_id)   # the review loop won't re-run it
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
        registry = self.agent_tool_registry
        if registry is None:
            return False
        tool = registry.get(name)
        if tool is None or not tool.pending_imports:
            return False
        registry.set_approval(name, approve)
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

    _SINGLE_LEVELS = ("ask", "yolo")

    def set_autonomy_level(self, session_id: str, level: str) -> dict[str, object]:
        """
        Set the autonomy slider. If a turn is in flight, DEFER the switch until
        it completes (or until the user stops) so it never disrupts a running
        turn; otherwise apply immediately. Maps the level onto config knobs and
        re-grounds the agent with a role-change notice + tool catalog.
        """
        if level == "minimal":  # legacy alias
            level = "ask"
        if level not in self._AUTONOMY_NOTICE:
            level = "yolo"
        session = self._sessions.get(session_id) if session_id else None
        if session is not None and session.busy:
            self._pending_autonomy[session_id] = level
            public = self.store.config.as_public()
            public["pending_autonomy"] = level
            return public
        return self._apply_autonomy_level(session_id, level)

    def _apply_autonomy_level(self, session_id: str, level: str) -> dict[str, object]:
        config = self.store.config
        prev = config.autonomy_level
        config.autonomy_level = level
        config.autonomy = "ask" if level == "ask" else "auto"
        config.autonomy_workers = "swarm" if level == "swarm" else "in_process"
        self.store.save_config()
        # Swarm spawns a worker surface per worker on the host — surface its
        # cross-platform requirements (and any missing ones) up front. The
        # domain swarm_provider knows what those are; a build without one has
        # no swarm surface to offer.
        swarm_ready, swarm_report = True, ""
        if level == "swarm":
            if self.swarm_provider is not None:
                swarm_ready, swarm_report = self.swarm_provider.preflight()
            else:
                swarm_ready, swarm_report = False, (
                    "Swarm mode is unavailable in this build (no swarm surface configured).")
        if session_id:
            session = self._get_or_load_session(session_id)
            notice = self._autonomy_change_notice(prev, level)
            if swarm_report:
                notice += "\n\n{:s}".format(swarm_report)
            session.engine.push_record({
                "role": "user", "content": notice,
                "synthetic": True, "autonomy_notice": level,
            })
        public = config.as_public()
        public["pending_autonomy"] = None
        if level == "swarm":
            public["swarm_preflight"] = {"ready": swarm_ready, "report": swarm_report}
        return public

    def _autonomy_change_notice(self, prev: str, level: str) -> str:
        """The role-change seed: the prior conversation context carries over (same
        session), so make the role transition explicit and re-inject the tools."""
        role = ""
        crossing = (prev in self._SINGLE_LEVELS) != (level in self._SINGLE_LEVELS)
        if crossing and prev in self._SINGLE_LEVELS:
            role = ("\n\nYOUR ROLE CHANGED: single agent -> ORCHESTRATOR. The prior "
                    "conversation context carries over; from here, pursue the user's "
                    "objectives by delegating to worker sub-agents and verifying their work.")
        elif crossing:
            role = ("\n\nYOUR ROLE CHANGED: orchestrator -> single agent. The prior "
                    "context (objectives and worker results) carries over; you now act "
                    "directly with the tools below.")
        return "[Autonomy changed] {:s}{:s}\n\nYour current tool catalog:\n{:s}".format(
            self._AUTONOMY_NOTICE[level], role, self._tool_catalog_summary())

    async def _apply_pending_autonomy(self, session_id: str) -> None:
        """Apply a switch deferred during a turn (called at turn end / on stop)."""
        level = self._pending_autonomy.pop(session_id, None)
        if level is None:
            return
        public = self._apply_autonomy_level(session_id, level)
        await self.emit({"type": "config", "config": public})
