# SPDX-FileCopyrightText: 2026 agentcore contributors
#
# SPDX-License-Identifier: MIT OR Apache-2.0

"""
Autonomy mode: an orchestrator that pursues user OBJECTIVES (not single
tasks) by spawning worker sub-agents, demanding proof of work, and
re-rounding until a context-blind evaluator confirms every objective is
met against the actual project state.

Same philosophy as ``reviewer.py``: judge evidence, not narrative. The
orchestrator never trusts a worker's say-so — the ``GoalEvaluator``
inspects the project (read-only scene probes) and checks each objective's
acceptance criteria.

This is Phase 0/1: the backend loop plus default, safe implementations.
The seams are pluggable so the isolation strategy (child-session vs
sub-turn — realized by which ``worker_runner`` the runtime injects), the
autonomy policy (auto-until-done vs pause-when-blocked) and the scheduler
(sequential vs parallel across multiple headless Blender instances) can
vary. The UI (bounded sub-agent panels) and parallel scheduling land in
later phases; the events emitted here are already shaped for them.
"""

__all__ = (
    "CONTINUE",
    "PAUSE",
    "DONE",
    "Objective",
    "WorkerTask",
    "WorkerResult",
    "GoalVerdict",
    "RoundResult",
    "draft_objectives",
    "LlmPlanner",
    "StateAwareEvaluator",
    "SequentialScheduler",
    "ParallelScheduler",
    "DAG",
    "DagScheduler",
    "AutoUntilDonePolicy",
    "AutoPauseWhenBlockedPolicy",
    "AutonomyOrchestrator",
)

import asyncio
import dataclasses
import json
import logging
from collections import deque
from typing import Any, Awaitable, Callable

from agentcore.llm import LlmClient

_log = logging.getLogger(__name__)

# Policy decisions returned by AutonomyPolicy.decide().
CONTINUE = "continue"   # run another round
PAUSE = "pause"         # stop and wait for the user
DONE = "done"           # objectives met (or budget reached); finish


# --------------------------------------------------------------------------
# Data contracts (Phase 0)
# --------------------------------------------------------------------------

@dataclasses.dataclass
class Objective:
    """A user goal and how to know it's met. Established via guided intake."""

    id: str
    text: str                 # what the user wants
    acceptance: str           # criteria the evaluator checks against
    status: str = "unmet"     # "unmet" | "met"
    evidence: str = ""        # the evaluator's latest evidence


@dataclasses.dataclass
class WorkerTask:
    """A scoped instruction handed to one worker sub-agent."""

    id: str
    objective_id: str
    instruction: str
    # The objective this task serves + its acceptance criteria. Always passed
    # to the worker (pinned in its system prompt) so it knows WHY it is acting
    # and what "done" means — independent of the share_context experiment.
    goal: str = ""
    acceptance: str = ""
    # Orchestrator context shared with the worker (objectives + status).
    # Empty == the worker runs blind on just its instruction. Set by the
    # orchestrator when share_context is on, so blind vs informed workers
    # can be compared on the same problem.
    context: str = ""
    # IDs of the tasks this one depends on. Empty == no prerequisites (runs in
    # the first generation). The DagScheduler runs a task only once every id in
    # depends_on has completed, so an "assemble" task waits for its parts and a
    # "validate" task waits for the assembly. (Ported from zip-ties' DAG model.)
    depends_on: list[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class WorkerResult:
    """A worker's proof-of-work, returned to the orchestrator."""

    task_id: str
    objective_id: str
    proof: str
    ok: bool = True
    transcript_ref: str = ""   # child session / agent id (or worker URL) for drill-down
    # Files the worker produced for downstream steps (e.g. a component .blend
    # in the shared exchange dir, for the gather agent to merge).
    artifacts: list[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class GoalVerdict:
    """The evaluator's per-objective ruling against project state."""

    objective_id: str
    met: bool
    evidence: str
    next_action: str = ""      # if unmet: what to try next (empty == blocked)


@dataclasses.dataclass
class RoundResult:
    round_index: int
    tasks: list[WorkerTask]
    results: list[WorkerResult]
    verdicts: list[GoalVerdict]
    all_met: bool


# --------------------------------------------------------------------------
# LLM helpers
# --------------------------------------------------------------------------

# Orchestrator/draft/eval/audit LLM calls are backend-only (no UI stream). Cap
# them so a hung or pathologically-slow model degrades gracefully (the callers
# fall back: empty plan -> one task per objective, empty verdict -> unmet)
# instead of freezing the whole run.
_COMPLETE_TIMEOUT_SECONDS = 240.0


async def _complete(llm: LlmClient, model: str, system: str, user: str,
                    timeout: float = _COMPLETE_TIMEOUT_SECONDS,
                    on_delta: "Callable[[str, str], Awaitable[None]] | None" = None,
                    trace_label: str = "complete") -> str:
    """One completion; returns the content (falling back to the reasoning trace
    when a reasoning model answers there and leaves content empty). Bounded by
    *timeout* so a hang surfaces as a partial/empty result. When *on_delta* is
    given it is awaited per chunk with ``(content_delta, reasoning_delta)`` so a
    caller can stream the planner/draft "looking around" to the UI. *trace_label*
    tags the call for the context trace (BLENDER_AGENT_TRACE_CONTEXT)."""
    request = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "_trace_label": trace_label,
    }
    content: list[str] = []
    reasoning: list[str] = []

    async def _drain() -> None:
        async for chunk in llm.stream(request):
            if chunk.content:
                content.append(chunk.content)
            trace = getattr(chunk, "reasoning", "")
            if trace:
                reasoning.append(trace)
            if on_delta is not None and (chunk.content or trace):
                await on_delta(chunk.content or "", trace or "")

    try:
        await asyncio.wait_for(_drain(), timeout=timeout)
    except asyncio.TimeoutError:
        _log.warning("LLM completion timed out after %.0fs; using partial result", timeout)
    text = "".join(content).strip()
    # Reasoning models sometimes emit the whole answer (incl. the JSON) in the
    # reasoning channel with empty content — let the JSON extractor see it.
    return text or "".join(reasoning).strip()


def _extract_json_object(text: str) -> dict[str, Any]:
    """
    Pull the first JSON object out of *text* (models wrap it in prose or
    fences). Returns {} when nothing parses — callers degrade gracefully.
    """
    start = text.find("{")
    end = text.rfind("}")
    if 0 <= start < end:
        try:
            data = json.loads(text[start:end + 1])
            if isinstance(data, dict):
                return data
        except ValueError:
            pass
    return {}


# --------------------------------------------------------------------------
# Guided intake — draft objectives from a one-line goal
# --------------------------------------------------------------------------

_DRAFT_SYSTEM = (
    "You turn a user's one-line goal for a Blender project into a short list of "
    "concrete, independently-verifiable OBJECTIVES. Each objective needs a clear "
    "'acceptance' criterion the result can be checked against (object names, "
    "counts, watertight, exported files, ...). Prefer 2-6 objectives. Reply with "
    'ONLY a JSON object: {"objectives": [{"text": "<goal>", "acceptance": "<done-when>"}]}'
)

# Tool-enabled variant (when a *runner* is given): the same contract, but the
# step first looks at the real scene so objectives fit what's actually there.
_DRAFT_SYSTEM_TOOLED = (
    _DRAFT_SYSTEM
    + "\n\nYou have Blender tools. BEFORE drafting, briefly inspect the current "
      "scene to ground the objectives in what actually exists — view it "
      "(summarize objects, screenshot/render a viewport) and pose/adjust only if "
      "that clarifies the work. A few tool calls, not the work itself. Then end "
      "your turn with ONLY the JSON object."
)

# Async tool-using planning step: (system, user) -> final assistant text.
# Injected by the runtime; lets the planner/draft inspect + pose the real scene
# on the `planner` RBAC surface. autonomy.py stays decoupled from the engine.
PlannerRunner = Callable[[str, str], Awaitable[str]]


async def draft_objectives(
        llm: LlmClient, model: str, goal: str,
        on_delta: "Callable[[str, str], Awaitable[None]] | None" = None,
        context: str = "",
        runner: "PlannerRunner | None" = None) -> list[dict[str, str]]:
    """
    Propose objectives (each {text, acceptance}) for *goal*. The user edits/
    confirms before a run starts (guided intake, with an explicit-edit fallback).
    *on_delta* streams the draft's reasoning/content to the UI as it decomposes.
    *context* is the recent conversation (the user's notes + agent replies) so
    the objectives reflect what was actually discussed, not just the bare goal.
    *runner*, when given, runs the draft as a tool-using sub-agent that inspects
    (and may pose) the real scene first; otherwise it is a single blind LLM call.
    """
    user = "GOAL: " + goal
    if context:
        user = ("CONVERSATION SO FAR (the user's notes and your replies — fold any "
                "relevant intent into the objectives):\n{:s}\n\n{:s}".format(context, user))
    if runner is not None:
        text = await runner(_DRAFT_SYSTEM_TOOLED, user)
    else:
        text = await _complete(llm, model, _DRAFT_SYSTEM, user, on_delta=on_delta,
                               trace_label="draft")
    data = _extract_json_object(text)
    out: list[dict[str, str]] = []
    for raw in data.get("objectives", []) or []:
        if isinstance(raw, dict) and str(raw.get("text", "")).strip():
            out.append({
                "text": str(raw["text"]).strip(),
                "acceptance": str(raw.get("acceptance", "")).strip(),
            })
    return out


# --------------------------------------------------------------------------
# Planner (default) — decompose unmet objectives into worker tasks
# --------------------------------------------------------------------------

_PLANNER_SYSTEM = (
    "You are the planning half of an autonomy orchestrator for a Blender "
    "agent. You are given the user's UNMET objectives (each with acceptance "
    "criteria). Decompose them into concrete, independently-executable worker "
    "tasks — one or a few per objective — that a capable worker agent with the "
    "full Blender tool surface can carry out and then prove. Be specific and "
    "action-oriented. Reply with ONLY a JSON object:\n"
    '{"tasks": [{"objective_id": "<id>", "instruction": "<imperative task>"}]}'
)

# Tool-enabled variant (when a *runner* is given): decompose against the real
# scene rather than blind. View + pose to understand it, then emit the JSON.
_PLANNER_SYSTEM_TOOLED = (
    _PLANNER_SYSTEM
    + "\n\nYou have Blender tools. BEFORE decomposing, look at the actual scene "
      "so the tasks fit reality — view it (summarize objects, screenshot/render "
      "a viewport) and, where it clarifies the work, pose or adjust the scene to "
      "understand the layout and rig. Keep it brief: a few tool calls to see "
      "what you're planning against, NOT to do the workers' construction. Then "
      "end your turn with ONLY the JSON object."
)


class LlmPlanner:
    """Default planner: asks the LLM to decompose unmet objectives. When given
    an *emit* + *session_id* it streams its "looking around" (reasoning/content)
    to the UI as ``planner_stream`` events, so a run shows decomposition
    feedback between a round starting and its workers spawning. When given a
    *runner* it instead decomposes as a tool-using sub-agent that views and
    poses the real scene first (surfaced by the runtime as its own panel)."""

    def __init__(self, llm: LlmClient, model: str,
                 emit: "Callable[[dict[str, Any]], Awaitable[None]] | None" = None,
                 session_id: str = "", context: str = "",
                 runner: "PlannerRunner | None" = None) -> None:
        self._llm = llm
        self._model = model
        self._emit = emit
        self._session_id = session_id
        # Recent conversation (user notes + agent replies) so task instructions
        # carry the user's actual intent to workers, not just the objective text.
        self._context = context
        self._runner = runner

    async def _planner_event(self, state: str, content: str = "", reasoning: str = "") -> None:
        if self._emit is None:
            return
        await self._emit({
            "type": "planner_stream", "session_id": self._session_id,
            "phase": "plan", "state": state, "content": content, "reasoning": reasoning,
        })

    async def plan(self, unmet: list[Objective]) -> list[WorkerTask]:
        listing = "\n".join(
            "- id={:s} | goal: {:s} | acceptance: {:s}".format(o.id, o.text, o.acceptance)
            for o in unmet
        )
        user = "UNMET OBJECTIVES:\n" + listing
        if self._context:
            user = ("CONVERSATION SO FAR (the user's notes and the agent's replies — let it "
                    "inform the task instructions):\n{:s}\n\n{:s}".format(self._context, user))
        if self._runner is not None:
            # Tool-using planner: it views/poses the scene; the runtime surfaces
            # that as its own sub-agent panel, so no planner_stream card here.
            text = await self._runner(_PLANNER_SYSTEM_TOOLED, user)
        else:
            await self._planner_event("start")

            async def on_delta(content: str, reasoning: str) -> None:
                await self._planner_event("delta", content, reasoning)

            text = await _complete(self._llm, self._model, _PLANNER_SYSTEM, user,
                                   on_delta=on_delta, trace_label="planner")
            await self._planner_event("done")
        data = _extract_json_object(text)
        by_id = {o.id: o for o in unmet}
        tasks: list[WorkerTask] = []
        for i, raw in enumerate(data.get("tasks", []) or []):
            if not isinstance(raw, dict):
                continue
            instruction = str(raw.get("instruction", "")).strip()
            oid = str(raw.get("objective_id", "")).strip()
            obj = by_id.get(oid) or unmet[0]  # mis-tagged task still belongs to the round
            if instruction:
                tasks.append(WorkerTask(
                    id="task-{:d}-{:d}".format(len(tasks), i),
                    objective_id=obj.id, instruction=instruction,
                    goal=obj.text, acceptance=obj.acceptance))
        if not tasks:
            # Degrade to one task per unmet objective rather than stalling.
            tasks = [
                WorkerTask(id="task-{:d}".format(i), objective_id=o.id,
                           instruction=o.text, goal=o.text, acceptance=o.acceptance)
                for i, o in enumerate(unmet)
            ]
        return tasks


# --------------------------------------------------------------------------
# Evaluator (default) — judge objectives against project state + proofs
# --------------------------------------------------------------------------

_EVAL_SYSTEM = (
    "You are the evaluator for a Blender autonomy orchestrator — strict but "
    "fair, and you judge EVIDENCE, not the workers' narrative. For each "
    "objective decide whether its acceptance criteria are met, using the "
    "PROJECT STATE snapshot (the actual scene) as ground truth and the worker "
    "proofs as claims to corroborate, never to take on faith. If unmet, give a "
    "concrete next_action; leave next_action empty ONLY if you believe the goal "
    "is blocked and needs the user. Reply with ONLY a JSON object:\n"
    '{"verdicts": [{"objective_id": "<id>", "met": true|false, '
    '"evidence": "<what the state shows>", "next_action": "<what to do next>"}]}'
)


class StateAwareEvaluator:
    """
    Default evaluator: generalizes ``reviewer.py`` from budget to goals.
    Inspects project state via an injected read-only *probe* and rules on
    each objective's acceptance criteria.
    """

    def __init__(
            self,
            llm: LlmClient,
            model: str,
            probe: Callable[[], Awaitable[str]] | None = None,
    ) -> None:
        self._llm = llm
        self._model = model
        self._probe = probe

    async def evaluate(
            self,
            objectives: list[Objective],
            results: list[WorkerResult],
    ) -> list[GoalVerdict]:
        state = "(no project-state probe configured)"
        if self._probe is not None:
            try:
                state = await self._probe()
            except Exception as ex:  # pylint: disable=broad-except
                state = "(project-state probe failed: {:s})".format(ex)
        objs = "\n".join(
            "- id={:s} | goal: {:s} | acceptance: {:s}".format(o.id, o.text, o.acceptance)
            for o in objectives
        )
        proofs = "\n".join(
            "- objective={:s} ok={!s}: {:s}".format(r.objective_id, r.ok, r.proof)
            for r in results
        ) or "(no worker proofs this round)"
        user = (
            "OBJECTIVES:\n{:s}\n\nWORKER PROOFS (claims):\n{:s}\n\n"
            "PROJECT STATE (ground truth):\n{:s}".format(objs, proofs, state)
        )
        text = await _complete(self._llm, self._model, _EVAL_SYSTEM, user, trace_label="evaluator")
        data = _extract_json_object(text)
        verdicts: list[GoalVerdict] = []
        seen: set[str] = set()
        for raw in data.get("verdicts", []) or []:
            if not isinstance(raw, dict):
                continue
            oid = str(raw.get("objective_id", "")).strip()
            if not oid or oid in seen:
                continue
            seen.add(oid)
            verdicts.append(GoalVerdict(
                objective_id=oid,
                met=bool(raw.get("met", False)),
                evidence=str(raw.get("evidence", "")).strip(),
                next_action=str(raw.get("next_action", "")).strip(),
            ))
        # Fail closed: any objective without a verdict stays unmet.
        for o in objectives:
            if o.id not in seen:
                verdicts.append(GoalVerdict(
                    o.id, False, "evaluator returned no verdict for this objective", ""))
        return verdicts


# --------------------------------------------------------------------------
# Independent auditor (opt-in) — adversarial final check for reward-hacking
# --------------------------------------------------------------------------

@dataclasses.dataclass
class AuditVerdict:
    """The auditor's independent ruling on one objective."""

    objective_id: str
    met: bool                 # the auditor's OWN judgement from project state
    overclaim: bool           # orchestrator claimed met, but the auditor says not
    evidence: str             # what the state actually shows


@dataclasses.dataclass
class AuditReport:
    passed: bool                       # auditor independently agrees every objective is met
    verdicts: list[AuditVerdict]
    summary: str
    overclaims: list[str]              # objective ids the orchestrator overclaimed


_AUDIT_SYSTEM = (
    "You are an INDEPENDENT AUDITOR, brought in AFTER a Blender autonomy "
    "orchestrator declared its work finished. You do NOT share the "
    "orchestrator's context, history, or assumptions. Your job is to catch "
    "reward-hacking: agents routinely OVERCLAIM success or take shortcuts — "
    "exporting an empty file, renaming without modelling, reporting 'done' "
    "without doing the work. Trust ONLY the PROJECT STATE (the actual scene / "
    "files) as ground truth. Treat the orchestrator's claims as suspect until "
    "the state corroborates them. For each objective, rule independently on "
    "whether its acceptance criteria are ACTUALLY met by the state, and set "
    "overclaim=true when the orchestrator claimed it met but the state does "
    "not substantiate that. Be specific in evidence; cite what the state shows "
    "or fails to show. Reply with ONLY a JSON object:\n"
    '{"summary": "<one-line overall verdict>", "verdicts": [{"objective_id": '
    '"<id>", "met": true|false, "overclaim": true|false, "evidence": "<what '
    'the state shows>"}]}'
)


class IndependentAuditor:
    """
    Opt-in final check that does NOT share the orchestrator's context: a fresh
    LLM session re-probes the real project state and rules, adversarially,
    on whether each objective was ACTUALLY met — calling out overclaims when
    the orchestrator declared success the state does not support.

    Independence is by construction: it is given a fresh ``llm`` (no shared
    transcript), the objectives + the orchestrator's CLAIMED status (to check
    against, not to trust), and the same read-only ground-truth ``probe``.
    """

    def __init__(
            self,
            llm: LlmClient,
            model: str,
            probe: Callable[[], Awaitable[str]] | None = None,
    ) -> None:
        self._llm = llm
        self._model = model
        self._probe = probe

    async def audit(self, objectives: list[Objective]) -> AuditReport:
        state = "(no project-state probe configured)"
        if self._probe is not None:
            try:
                state = await self._probe()
            except Exception as ex:  # pylint: disable=broad-except
                state = "(project-state probe failed: {:s})".format(ex)
        claims = "\n".join(
            "- id={:s} | goal: {:s} | acceptance: {:s} | orchestrator CLAIMED: {:s}{:s}".format(
                o.id, o.text, o.acceptance,
                "MET" if o.status == "met" else "unmet",
                " | its evidence: {:s}".format(o.evidence) if o.evidence else "")
            for o in objectives
        )
        user = (
            "OBJECTIVES & THE ORCHESTRATOR'S CLAIMS:\n{:s}\n\n"
            "PROJECT STATE (ground truth — judge against THIS):\n{:s}".format(claims, state)
        )
        text = await _complete(self._llm, self._model, _AUDIT_SYSTEM, user, trace_label="auditor")
        data = _extract_json_object(text)
        claimed_met = {o.id for o in objectives if o.status == "met"}
        verdicts: list[AuditVerdict] = []
        seen: set[str] = set()
        for raw in data.get("verdicts", []) or []:
            if not isinstance(raw, dict):
                continue
            oid = str(raw.get("objective_id", "")).strip()
            if not oid or oid in seen:
                continue
            seen.add(oid)
            met = bool(raw.get("met", False))
            # Overclaim: trust the auditor's ruling — flag whenever the
            # orchestrator said met but the auditor (or the model) says not.
            overclaim = bool(raw.get("overclaim", False)) or (oid in claimed_met and not met)
            verdicts.append(AuditVerdict(
                objective_id=oid, met=met, overclaim=overclaim,
                evidence=str(raw.get("evidence", "")).strip()))
        # Fail closed: an objective the auditor skipped is treated as unverified
        # (not met), and as an overclaim if the orchestrator had claimed it.
        for o in objectives:
            if o.id not in seen:
                verdicts.append(AuditVerdict(
                    o.id, False, o.id in claimed_met,
                    "auditor returned no verdict — treated as unverified"))
        overclaims = [v.objective_id for v in verdicts if v.overclaim]
        passed = all(v.met for v in verdicts) and bool(verdicts)
        summary = str(data.get("summary", "")).strip() or (
            "All objectives independently verified." if passed
            else "Independent audit found unmet/overclaimed objectives.")
        return AuditReport(
            passed=passed, verdicts=verdicts, summary=summary, overclaims=overclaims)


# --------------------------------------------------------------------------
# Schedulers — how worker tasks map onto runtimes
# --------------------------------------------------------------------------

WorkerRunner = Callable[[WorkerTask], Awaitable[WorkerResult]]


class SequentialScheduler:
    """One worker at a time — safe on a single shared Blender instance."""

    async def run(self, tasks: list[WorkerTask], run_worker: WorkerRunner) -> list[WorkerResult]:
        results: list[WorkerResult] = []
        for task in tasks:
            results.append(await run_worker(task))
        return results


class ParallelScheduler:
    """
    Bounded-concurrency scheduler: runs up to ``max_concurrency`` workers at
    once. Used in swarm mode, where each worker is a real subprocess with its
    own headless Blender (see ``swarm.RemoteWorkerStrategy``).
    """

    def __init__(self, max_concurrency: int = 4) -> None:
        self._sem = asyncio.Semaphore(max(1, max_concurrency))

    async def run(self, tasks: list[WorkerTask], run_worker: WorkerRunner) -> list[WorkerResult]:
        async def _guarded(task: WorkerTask) -> WorkerResult:
            async with self._sem:
                return await run_worker(task)

        return list(await asyncio.gather(*(_guarded(t) for t in tasks)))


class DAG:
    """Lightweight directed acyclic graph: nodes, dependency edges, topological
    generations, cycle detection, and dynamic fan-out.

    Ported from zip-ties (``zip_ties_core.automata.dag.DAG``) and kept API-
    compatible on purpose, so the local copy can later be swapped for the
    upstream package with a light refactor. ONE documented edge convention
    (zip-ties carried two conflicting ones): ``add_edge(dep, node)`` means
    "*dep* must finish before *node*" — edges point from prerequisite to
    dependent, and ``topological_generations`` yields prerequisites first
    (networkx ``topological_generations`` semantics).
    """

    def __init__(self, name: str = "") -> None:
        self.name = name
        self._nodes: set[str] = set()
        self._deps: dict[str, set[str]] = {}       # node -> its prerequisites
        self._dependents: dict[str, set[str]] = {}  # node -> nodes waiting on it

    def add_node(self, node_id: str) -> None:
        self._nodes.add(node_id)
        self._deps.setdefault(node_id, set())
        self._dependents.setdefault(node_id, set())

    def add_edge(self, dep: str, node: str) -> None:
        """Record that *node* depends on *dep* (dep runs first)."""
        self.add_node(dep)
        self.add_node(node)
        self._deps[node].add(dep)
        self._dependents[dep].add(node)

    def is_dag(self) -> bool:
        indeg = {n: len(self._deps[n]) for n in self._nodes}
        queue = deque(n for n, d in indeg.items() if d == 0)
        seen = 0
        while queue:
            n = queue.popleft()
            seen += 1
            for m in self._dependents[n]:
                indeg[m] -= 1
                if indeg[m] == 0:
                    queue.append(m)
        return seen == len(self._nodes)

    def topological_generations(self) -> "list[set[str]]":
        """Nodes grouped into generations: each generation's prerequisites all
        live in earlier generations, so a generation can run concurrently."""
        indeg = {n: len(self._deps[n]) for n in self._nodes}
        gen = {n for n, d in indeg.items() if d == 0}
        generations: list[set[str]] = []
        while gen:
            generations.append(gen)
            nxt: set[str] = set()
            for n in gen:
                for m in self._dependents[n]:
                    indeg[m] -= 1
                    if indeg[m] == 0:
                        nxt.add(m)
            gen = nxt
        return generations

    def replace_node_with_fan(self, template_id: str, instance_ids: "list[str]") -> None:
        """Replace one node with N parallel instances: each instance inherits
        the template's prerequisites, and every dependent now waits on ALL
        instances (fan-out then fan-in). Used for dynamic per-item expansion."""
        if template_id not in self._nodes:
            raise ValueError("node {!r} not in graph".format(template_id))
        deps = set(self._deps.get(template_id, set()))
        dependents = set(self._dependents.get(template_id, set()))
        self._remove(template_id)
        for inst in instance_ids:
            self.add_node(inst)
            for d in deps:
                self.add_edge(d, inst)
            for dep_node in dependents:
                self.add_edge(inst, dep_node)

    def _remove(self, node_id: str) -> None:
        self._nodes.discard(node_id)
        for d in self._deps.pop(node_id, set()):
            self._dependents.get(d, set()).discard(node_id)
        for m in self._dependents.pop(node_id, set()):
            self._deps.get(m, set()).discard(node_id)


class DagScheduler:
    """Dependency-aware scheduler: runs tasks by topological generation, up to
    ``max_concurrency`` at once within a generation, so a downstream task (e.g.
    an ``assemble`` node) only starts once every task in its ``depends_on`` has
    finished. Implements the same ``run(tasks, run_worker)`` seam as the other
    schedulers, so it is a drop-in. A task whose dependency failed is skipped
    with a failed result (the failure propagates instead of running blind).

    This is the executor half of the ported zip-ties DAG model; the planner
    supplies ``WorkerTask.depends_on`` (the edges)."""

    def __init__(self, max_concurrency: int = 4) -> None:
        self._sem = asyncio.Semaphore(max(1, max_concurrency))

    async def run(self, tasks: list[WorkerTask], run_worker: WorkerRunner) -> list[WorkerResult]:
        by_id = {t.id: t for t in tasks}
        dag = DAG()
        for t in tasks:
            dag.add_node(t.id)
            for dep in t.depends_on:
                if dep in by_id:            # ignore dangling deps the planner invented
                    dag.add_edge(dep, t.id)
        if not dag.is_dag():
            # A cycle would deadlock the generations — fall back to a flat run
            # rather than hang, and let the evaluator sort it out.
            return await ParallelScheduler(self._sem._value).run(tasks, run_worker)

        results: dict[str, WorkerResult] = {}

        async def _guarded(task: WorkerTask) -> WorkerResult:
            failed_deps = [d for d in task.depends_on if d in results and not results[d].ok]
            if failed_deps:
                return WorkerResult(task_id=task.id, objective_id=task.objective_id,
                                    proof="skipped: prerequisite task(s) failed: {:s}".format(
                                        ", ".join(failed_deps)), ok=False)
            async with self._sem:
                return await run_worker(task)

        for generation in dag.topological_generations():
            gen_tasks = [by_id[nid] for nid in generation if nid in by_id]
            done = await asyncio.gather(*(_guarded(t) for t in gen_tasks))
            for r in done:
                results[r.task_id] = r
        return [results[t.id] for t in tasks if t.id in results]


# --------------------------------------------------------------------------
# Policies — what to do at a round boundary
# --------------------------------------------------------------------------

class AutoUntilDonePolicy:
    """Run round after round until every objective is met or rounds run out."""

    def decide(self, result: RoundResult, rounds_used: int, max_rounds: int) -> str:
        if result.all_met:
            return DONE
        if rounds_used + 1 >= max_rounds:
            return DONE  # budget reached; orchestrator reports what's left
        return CONTINUE


class AutoPauseWhenBlockedPolicy:
    """
    Autonomous, but hand control back when stuck: if no objective was met
    this round and every unmet verdict is blocked (no next_action), pause
    for the user instead of spinning.
    """

    def decide(self, result: RoundResult, rounds_used: int, max_rounds: int) -> str:
        if result.all_met:
            return DONE
        unmet = [v for v in result.verdicts if not v.met]
        if unmet and all(not v.next_action for v in unmet):
            return PAUSE
        if rounds_used + 1 >= max_rounds:
            return DONE
        return CONTINUE


# --------------------------------------------------------------------------
# Orchestrator (Phase 1)
# --------------------------------------------------------------------------

class AutonomyOrchestrator:
    """
    Drives the goal-level loop: assess -> plan -> dispatch workers ->
    evaluate against project state -> decide. Emits UI events shaped for
    bounded sub-agent panels (``agent_spawned`` / ``agent_done``) and goal
    tracking (``objectives_update``).

    Dependencies are injected so the loop is testable headless and the
    isolation strategy is whatever ``worker_runner`` the runtime supplies.
    """

    def __init__(
            self,
            *,
            planner: "LlmPlanner",
            scheduler: "SequentialScheduler | ParallelScheduler",
            evaluator: "StateAwareEvaluator",
            policy: "AutoUntilDonePolicy | AutoPauseWhenBlockedPolicy",
            worker_runner: WorkerRunner,
            emit: Callable[[dict[str, Any]], Awaitable[None]],
            session_id: str = "",
            share_context: bool = False,
    ) -> None:
        self._planner = planner
        self._scheduler = scheduler
        self._evaluator = evaluator
        self._policy = policy
        self._worker_runner = worker_runner
        self._emit = emit
        self._session_id = session_id
        self._share_context = share_context

    def _shared_context(self, objectives: list[Objective]) -> str:
        """The orchestrator's objective view, shared with informed workers."""
        lines = ["Autonomy run — the orchestrator's objectives and current status:"]
        for o in objectives:
            line = "- [{:s}] {:s} (done-when: {:s})".format(
                "MET" if o.status == "met" else "unmet", o.text, o.acceptance)
            if o.evidence:
                line += " | latest: {:s}".format(o.evidence)
            lines.append(line)
        lines.append(
            "Do your assigned task; the orchestrator will verify the result "
            "against these objectives.")
        return "\n".join(lines)

    def _objectives_payload(self, objectives: list[Objective]) -> list[dict[str, Any]]:
        return [dataclasses.asdict(o) for o in objectives]

    async def _run_one_worker(self, task: WorkerTask) -> WorkerResult:
        agent_id = "{:s}:w:{:s}".format(self._session_id, task.id)
        await self._emit({
            "type": "agent_spawned",
            "session_id": self._session_id,
            "agent_id": agent_id,
            "role": "worker",
            "objective_id": task.objective_id,
            "task": task.instruction,
        })
        try:
            result = await self._worker_runner(task)
        except Exception as ex:  # pylint: disable=broad-except
            _log.warning("worker %s failed: %s", task.id, ex)
            result = WorkerResult(
                task_id=task.id, objective_id=task.objective_id,
                proof="worker errored: {:s}".format(ex), ok=False)
        if not result.transcript_ref:
            result.transcript_ref = agent_id
        await self._emit({
            "type": "agent_done",
            "session_id": self._session_id,
            # Key on the SAME id we spawned with, so the UI updates the card it
            # opened (the worker's URL/child-session id rides along separately).
            "agent_id": agent_id,
            "ref": result.transcript_ref,
            "role": "worker",
            "objective_id": task.objective_id,
            "ok": result.ok,
            "proof": result.proof,
            "artifacts": result.artifacts,
        })
        return result

    async def run(self, objectives: list[Objective], max_rounds: int = 6) -> dict[str, Any]:
        """
        Pursue *objectives* across up to *max_rounds* rounds. Returns a
        summary dict; emits events throughout.
        """
        decision = DONE
        rounds_run = 0
        for round_index in range(max_rounds):
            rounds_run = round_index + 1
            # Rebuilt each round so objectives edited/added mid-run (see
            # AgentRuntime.update_objectives) are first-class from here on.
            by_id = {o.id: o for o in objectives}
            unmet = [o for o in objectives if o.status != "met"]
            await self._emit({
                "type": "autonomy_round_start",
                "session_id": self._session_id,
                "round": round_index,
                "unmet": [o.id for o in unmet],
                "objectives": self._objectives_payload(objectives),
            })
            if not unmet:
                decision = DONE
                break

            tasks = await self._planner.plan(unmet)
            if self._share_context:
                shared = self._shared_context(objectives)
                for task in tasks:
                    task.context = shared
            results = await self._scheduler.run(tasks, self._run_one_worker)
            verdicts = await self._evaluator.evaluate(objectives, results)

            for verdict in verdicts:
                obj = by_id.get(verdict.objective_id)
                if obj is not None:
                    obj.status = "met" if verdict.met else "unmet"
                    obj.evidence = verdict.evidence

            all_met = all(o.status == "met" for o in objectives)
            round_result = RoundResult(round_index, tasks, results, verdicts, all_met)
            await self._emit({
                "type": "autonomy_round_done",
                "session_id": self._session_id,
                "round": round_index,
                "all_met": all_met,
                "verdicts": [dataclasses.asdict(v) for v in verdicts],
            })
            await self._emit({
                "type": "objectives_update",
                "session_id": self._session_id,
                "objectives": self._objectives_payload(objectives),
            })

            decision = self._policy.decide(round_result, round_index, max_rounds)
            if decision in (DONE, PAUSE):
                break

        all_met = all(o.status == "met" for o in objectives)
        await self._emit({
            "type": "autonomy_paused" if decision == PAUSE else "autonomy_done",
            "session_id": self._session_id,
            "all_met": all_met,
            "rounds": rounds_run,
            "objectives": self._objectives_payload(objectives),
        })
        return {
            "decision": decision,
            "all_met": all_met,
            "rounds": rounds_run,
            "objectives": self._objectives_payload(objectives),
        }
