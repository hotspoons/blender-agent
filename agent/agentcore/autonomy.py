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
    "HANDOFF_BLIND",
    "HANDOFF_HANDOFF",
    "HANDOFF_COMPACTION",
    "HANDOFF_FULL",
    "HANDOFF_MODES",
    "GATHER_PLANNER",
    "GATHER_ALWAYS",
    "GATHER_OFF",
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
    "StepData",
    "GraphData",
    "InMemoryGraphData",
    "AutoUntilDonePolicy",
    "AutoPauseWhenBlockedPolicy",
    "AutonomyOrchestrator",
)

import asyncio
import dataclasses
import json
import logging
import re
from abc import ABC, abstractmethod
from collections import OrderedDict, deque
from datetime import datetime
from typing import Any, Awaitable, Callable

from agentcore.llm import LlmClient

_log = logging.getLogger(__name__)

# Policy decisions returned by AutonomyPolicy.decide().
CONTINUE = "continue"   # run another round
PAUSE = "pause"         # stop and wait for the user
DONE = "done"           # objectives met (or budget reached); finish

# Context-handoff modes for spawned workers (autonomy_handoff). zip-ties only
# ever ran 'blind' — see zip-ties-dag-port memory.
HANDOFF_BLIND = "blind"          # instruction + acceptance only
HANDOFF_HANDOFF = "handoff"      # + concise objectives/status (cheap)
HANDOFF_COMPACTION = "compaction"  # + a dense brief from a compactor pass
HANDOFF_FULL = "full"            # + the orchestrator's full conversation
HANDOFF_MODES = (HANDOFF_BLIND, HANDOFF_HANDOFF, HANDOFF_COMPACTION, HANDOFF_FULL)

# Gather/assemble policy for swarm (autonomy_gather).
GATHER_PLANNER = "planner"   # only if the planner emits an assemble node
GATHER_ALWAYS = "always"     # always run a final gather-all before review
GATHER_OFF = "off"           # never gather (components stay separate)


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
    # Optional dynamic fan-out (nested sub-graph): a list of per-instance
    # assignments ({label, context}). The DagScheduler expands this task into one
    # parallel instance per entry ("{id}_{i}", zip-ties' clone /
    # replace_node_with_fan), each tagged with its iteration_tree position in the
    # step store; any dependent fans in over ALL instances.
    fan_out: list[dict] = dataclasses.field(default_factory=list)


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


def _text_only(messages: "list[dict[str, Any]]") -> "list[dict[str, Any]]":
    """Forked messages with inline images flattened to placeholders — judge
    completions carry no vision fallback, so an image part would hard-fail
    the request on a text-only endpoint."""
    out: list[dict[str, Any]] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            text = "\n".join(
                part.get("text", "") if part.get("type") == "text" else "[image omitted]"
                for part in content)
            message = {**message, "content": text}
        out.append(message)
    return out


async def _complete(llm: LlmClient, model: str, system: str, user: str,
                    timeout: float = _COMPLETE_TIMEOUT_SECONDS,
                    on_delta: "Callable[[str, str], Awaitable[None]] | None" = None,
                    trace_label: str = "complete",
                    prefix: "list[dict[str, Any]] | None" = None) -> str:
    """One completion; returns the content (falling back to the reasoning trace
    when a reasoning model answers there and leaves content empty). Bounded by
    *timeout* so a hang surfaces as a partial/empty result. When *on_delta* is
    given it is awaited per chunk with ``(content_delta, reasoning_delta)`` so a
    caller can stream the planner/draft "looking around" to the UI. *trace_label*
    tags the call for the context trace (BLENDER_AGENT_TRACE_CONTEXT). *prefix*
    interposes forked conversation messages between system and user ('full'
    handoff: the evaluator/reviewer judges with the parent context in view, and
    identical prefixes across calls share the server's KV cache)."""
    request = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            *_text_only(prefix or []),
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
    "action-oriented.\n\n"
    "Model the work as a DAG. Give every task a short unique 'id'. Tasks with "
    "no 'depends_on' run IN PARALLEL — keep independent parts (that build "
    "different objects) dependency-free so they fan out. If a task needs the "
    "OUTPUT of others — e.g. ASSEMBLING/positioning the parts the others built, "
    "or VALIDATING the whole — list those task ids in 'depends_on' so it runs "
    "only after them. When objectives require parts to come together, prefer ONE "
    "integration/'assemble' task that depends_on the part tasks (and a single "
    "validate task that depends_on the assemble). Do not invent dependencies "
    "between genuinely independent parts — that just serializes them.\n\n"
    "For repeated per-item work you MAY give one task a 'fan_out': a list of "
    "per-item briefs [{\"label\": ..., \"context\": ...}] — it runs as N parallel "
    "instances and any dependent fans in over all of them. CRITICAL: each "
    "fan_out instance must produce a DIFFERENT, non-overlapping slice — name the "
    "distinct output(s) each one owns in its context. GOOD: fan_out a 'trees' "
    "task into [{label:'oak',context:'build Tree_1'},{label:'pine',context:'build "
    "Tree_2'}] — instance i builds only Tree_i. BAD: three instances that each "
    "'build the terrain and all the trees' — that is the SAME work done N times, "
    "wasting workers and spawning duplicate objects. If you cannot give each "
    "instance a distinct output, DO NOT fan out — use a single task. Never "
    "fan_out an objective's whole scope; fan_out only the genuinely repeated unit "
    "within it.\n\n"
    "Reply with ONLY a JSON object:\n"
    '{"tasks": [{"id": "<short unique id>", "objective_id": "<id>", '
    '"instruction": "<imperative task>", "depends_on": ["<task id>", ...], '
    '"fan_out": [{"label": "<item>", "context": "<per-item brief>"}]}]}'
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
        raw_tasks = [r for r in (data.get("tasks") or [])
                     if isinstance(r, dict) and str(r.get("instruction", "")).strip()]

        # Pass 1: assign each task a final id (the planner's own id, sanitized —
        # it becomes a component filename / agent id downstream — else generated)
        # and remember the planner id -> final id mapping so depends_on resolves.
        id_map: dict[str, str] = {}
        used: set[str] = set()
        specs: list[tuple[str, Objective, str, list, list]] = []
        for i, raw in enumerate(raw_tasks):
            pid = str(raw.get("id", "")).strip()
            safe = re.sub(r"[^A-Za-z0-9_-]+", "-", pid).strip("-") or "task-{:d}".format(i)
            base, n = safe, 1
            while safe in used:
                safe, n = "{:s}-{:d}".format(base, n), n + 1
            used.add(safe)
            if pid:
                id_map[pid] = safe
            obj = by_id.get(str(raw.get("objective_id", "")).strip()) or unmet[0]
            # Drop duplicate fan-out briefs: instances with identical
            # label+context are the same work cloned N times (wasteful, spawns
            # duplicate objects), not a real per-item split. Collapse them so a
            # mis-fanned task runs once instead of N times.
            fan, _fseen = [], set()
            for a in (raw.get("fan_out") or []):
                if not isinstance(a, dict):
                    continue
                key = (str(a.get("label", "")).strip(), str(a.get("context", "")).strip())
                if key in _fseen:
                    continue
                _fseen.add(key)
                fan.append(a)
            specs.append((safe, obj, str(raw.get("instruction", "")).strip(),
                          raw.get("depends_on") or [], fan))

        # Pass 2: build tasks, resolving depends_on (planner id OR final id) and
        # dropping self/dangling references (the DagScheduler also guards these).
        tasks: list[WorkerTask] = []
        for fid, obj, instruction, raw_deps, fan in specs:
            deps = []
            for d in raw_deps:
                d = str(d).strip()
                resolved = id_map.get(d, d if d in used else "")
                if resolved and resolved != fid and resolved not in deps:
                    deps.append(resolved)
            tasks.append(WorkerTask(
                id=fid, objective_id=obj.id, instruction=instruction,
                goal=obj.text, acceptance=obj.acceptance, depends_on=deps, fan_out=fan))

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
            seed: "Callable[[], list[dict[str, Any]]] | None" = None,
    ) -> None:
        self._llm = llm
        self._model = model
        self._probe = probe
        # 'full' handoff: the verdict call carries the forked parent
        # conversation, so objectives are judged against the user's actual
        # asks — not just the objective text.
        self._seed = seed

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
        text = await _complete(self._llm, self._model, _EVAL_SYSTEM, user, trace_label="evaluator",
                               prefix=self._seed() if self._seed is not None else None)
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


# --------------------------------------------------------------------------
# Step store — ported faithfully from zip-ties
# (``zip_ties_core.interfaces.graph_data``). It is the shared record of every
# node's execution: downstream nodes read upstream outputs from HERE rather
# than re-deriving them, which is how the orchestrator and its sub-agents stay
# on the same page instead of looping. ``iteration_tree`` is the position in a
# nested/fanned execution (top-level == ``[]``). Kept API-identical to the
# upstream so it can later be swapped for the KV-backed store with a light
# refactor — this in-memory impl mirrors ``KVGraphData``'s keying.
# --------------------------------------------------------------------------

@dataclasses.dataclass(kw_only=True)
class StepData:
    input_data: "dict | None" = None
    output_data: "dict | None" = None
    metadata: "dict | None" = None
    text: str = ""
    start: "datetime | None" = None
    end: "datetime | None" = None
    agent_id: str = ""
    session_id: "str | None" = None
    cell_id: "str | None" = None
    iteration_tree: list[int] = dataclasses.field(default_factory=list)
    success: bool = True


class GraphData(ABC):
    """Abstract step store. Same surface as zip-ties so a KV/Valkey-backed
    implementation drops in unchanged later."""

    @abstractmethod
    def put_data(self, step_data: StepData) -> None: ...

    @abstractmethod
    def fetch_all_data(self) -> list[StepData]: ...

    @abstractmethod
    def fetch_all_data_dict(self) -> "OrderedDict[str, StepData]": ...

    @abstractmethod
    def fetch_data(self, node_id: str, iteration_tree: list[int]) -> "StepData | None": ...

    @abstractmethod
    def fetch_all_data_by_id(self, node_id: str) -> list[StepData]: ...

    def fetch_datas(self, query_dict: dict[str, list[int]]) -> list[StepData]:
        out: list[StepData] = []
        for node_id, it in query_dict.items():
            sd = self.fetch_data(node_id, it)
            if sd is not None:
                out.append(sd)
        return out

    def fetch_last_data_by_id(self, node_id: str) -> "StepData | None":
        items = self.fetch_all_data_by_id(node_id)
        return items[-1] if items else None

    def fetch_first_data_by_id(self, node_id: str) -> "StepData | None":
        items = self.fetch_all_data_by_id(node_id)
        return items[0] if items else None

    _FAN_IN_RE = re.compile(r"^(.+)_\d+$")

    def fetch_fan_in_results(self, template_name: str) -> list[StepData]:
        """Results from every cloned instance ``{template_name}_N`` of a fanned
        node, sorted by id — the fan-in side of ``replace_node_with_fan``."""
        pattern = re.compile(r"^{:s}_\d+$".format(re.escape(template_name)))
        results = [sd for sd in self.fetch_all_data() if pattern.match(sd.agent_id)]
        results.sort(key=lambda sd: sd.agent_id)
        return results


class InMemoryGraphData(GraphData):
    """Process-local step store (no external KV). Keyed ``{agent_id}::{iteration_tree}``
    exactly like ``KVGraphData`` so the swap is mechanical."""

    def __init__(self) -> None:
        self._steps: "OrderedDict[str, StepData]" = OrderedDict()

    @staticmethod
    def _format_id(node_id: str, iteration_tree: list[int]) -> str:
        return "{:s}::{}".format(node_id, iteration_tree)

    def put_data(self, step_data: StepData) -> None:
        self._steps[self._format_id(step_data.agent_id, step_data.iteration_tree)] = step_data

    def fetch_all_data(self) -> list[StepData]:
        return list(self._steps.values())

    def fetch_all_data_dict(self) -> "OrderedDict[str, StepData]":
        return OrderedDict(self._steps)

    def fetch_data(self, node_id: str, iteration_tree: list[int]) -> "StepData | None":
        return self._steps.get(self._format_id(node_id, iteration_tree))

    def fetch_all_data_by_id(self, node_id: str) -> list[StepData]:
        out = [sd for sd in self._steps.values() if sd.agent_id == node_id]
        out.sort(key=lambda sd: sd.start or datetime.min)
        return out


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
    supplies ``WorkerTask.depends_on`` (the edges). When a ``GraphData`` step
    store is provided, each node's result is recorded as a ``StepData`` and each
    task is handed its upstream results (read from the store) — the shared-state
    path that keeps downstream agents aligned with what ran before them."""

    def __init__(self, max_concurrency: int = 4, graph: "GraphData | None" = None) -> None:
        self._sem = asyncio.Semaphore(max(1, max_concurrency))
        self._graph = graph

    @staticmethod
    def _expand_fanout(tasks: list[WorkerTask]) -> "tuple[list[WorkerTask], dict[str, list[int]]]":
        """Expand any fan-out task into N parallel instances ("{id}_{i}"), each
        carrying its assignment context and an iteration_tree position; rewire
        dependents to fan in over all instances. Returns (tasks, iter_tree)."""
        fan_map: dict[str, list[str]] = {}
        iter_tree: dict[str, list[int]] = {}
        expanded: list[WorkerTask] = []
        for t in tasks:
            if t.fan_out:
                for i, assign in enumerate(t.fan_out):
                    iid = "{:s}_{:d}".format(t.id, i)
                    actx = str((assign or {}).get("context", "")).strip()
                    ctx = (t.context + "\n\n" + actx).strip() if actx else t.context
                    expanded.append(dataclasses.replace(
                        t, id=iid, context=ctx, fan_out=[], depends_on=list(t.depends_on)))
                    iter_tree[iid] = [i]
                    fan_map.setdefault(t.id, []).append(iid)
            else:
                expanded.append(t)
                iter_tree.setdefault(t.id, [])
        # A dependent of a fanned template now depends on ALL its instances.
        for t in expanded:
            if any(d in fan_map for d in t.depends_on):
                new_deps: list[str] = []
                for d in t.depends_on:
                    new_deps.extend(fan_map[d]) if d in fan_map else new_deps.append(d)
                t.depends_on = new_deps
        return expanded, iter_tree

    async def run(self, tasks: list[WorkerTask], run_worker: WorkerRunner) -> list[WorkerResult]:
        tasks, iter_tree = self._expand_fanout(tasks)
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

        def _record(r: WorkerResult) -> None:
            results[r.task_id] = r
            if self._graph is not None:
                self._graph.put_data(StepData(
                    agent_id=r.task_id, success=bool(r.ok), text=r.proof or "",
                    output_data={"proof": r.proof, "ok": r.ok, "artifacts": r.artifacts},
                    iteration_tree=iter_tree.get(r.task_id, []), end=datetime.now()))

        def _inject_upstream(task: WorkerTask) -> None:
            # Hand the task what its prerequisites produced, read from the store.
            if self._graph is None or not task.depends_on:
                return
            lines = []
            for dep in task.depends_on:
                sd = self._graph.fetch_last_data_by_id(dep)
                if sd is not None:
                    lines.append("- {:s}: {:s}".format(dep, (sd.text or "(no report)")[:500]))
            if lines:
                upstream = "Upstream results you build on:\n" + "\n".join(lines)
                task.context = (task.context + "\n\n" + upstream).strip() if task.context else upstream

        async def _guarded(task: WorkerTask) -> WorkerResult:
            failed_deps = [d for d in task.depends_on if d in results and not results[d].ok]
            if failed_deps:
                return WorkerResult(task_id=task.id, objective_id=task.objective_id,
                                    proof="skipped: prerequisite task(s) failed: {:s}".format(
                                        ", ".join(failed_deps)), ok=False)
            _inject_upstream(task)
            async with self._sem:
                # A worker runner must never crash the whole generation/run:
                # asyncio.gather propagates the first exception and would tear
                # down every sibling task (and the server). Convert any escape
                # into a failed result so the evaluator handles it as a miss.
                try:
                    return await run_worker(task)
                except Exception as ex:  # pylint: disable=broad-except
                    return WorkerResult(
                        task_id=task.id, objective_id=task.objective_id,
                        proof="worker errored: {:s}".format(str(ex)), ok=False)

        for generation in dag.topological_generations():
            gen_tasks = [by_id[nid] for nid in generation if nid in by_id]
            done = await asyncio.gather(*(_guarded(t) for t in gen_tasks))
            for r in done:
                _record(r)
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
            handoff: str = "",
            compactor: "Callable[[list[Objective], str], Awaitable[str]] | None" = None,
            context: str = "",
            full_fork: bool = False,
            pre_eval: "Callable[[list[WorkerTask], list[WorkerResult]], Awaitable[None]] | None" = None,
    ) -> None:
        self._planner = planner
        self._scheduler = scheduler
        self._evaluator = evaluator
        self._policy = policy
        self._worker_runner = worker_runner
        self._emit = emit
        self._session_id = session_id
        # Context-handoff mode for spawned workers (the knob zip-ties lacked —
        # it only ever ran 'blind'). Legacy share_context bool maps onto it.
        self._handoff = handoff or (HANDOFF_HANDOFF if share_context else HANDOFF_BLIND)
        self._compactor = compactor
        self._context = context     # the orchestrator's conversation, for 'full'
        # True when the worker runner forks the parent conversation itself
        # (message-level seed, KV-cache-shareable) — 'full' then skips the
        # text paste here. False = paste fallback (e.g. subprocess swarm
        # workers, which take a string brief but no message seed).
        self._full_fork = full_fork
        # Runs after the workers finish but BEFORE evaluation (swarm uses it to
        # gather components into the assembled master, so integration objectives
        # are judged against the assembled scene, not loose parts).
        self._pre_eval = pre_eval

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

    async def _apply_handoff(self, tasks: list[WorkerTask], objectives: list[Objective]) -> None:
        """Set each task's shared context per the handoff mode (DagScheduler then
        layers each task's upstream node results on top). The per-worker fork is
        assembled once here; tools are restated per worker at spawn downstream.
          blind      — nothing (worker runs on its instruction + acceptance only)
          handoff    — concise objectives + status (cheap)
          compaction — a dense brief from the injected compactor (one pass), else
                       falls back to handoff
          full       — objectives + status + the orchestrator's conversation
                       (as text; when the runner forks the conversation at
                       message level instead, only the concise brief rides
                       here — the fork carries the rest)"""
        mode = self._handoff
        if mode == HANDOFF_BLIND:
            return
        if mode == HANDOFF_COMPACTION and self._compactor is not None:
            try:
                brief = await self._compactor(objectives, self._context)
            except Exception as ex:  # pylint: disable=broad-except
                _log.warning("handoff compaction failed (%s); using concise handoff", ex)
                brief = self._shared_context(objectives)
        elif mode == HANDOFF_FULL and not self._full_fork:
            brief = self._shared_context(objectives)
            if self._context:
                brief = "Full orchestrator context:\n{:s}\n\n{:s}".format(self._context, brief)
        else:   # handoff, or compaction with no compactor wired
            brief = self._shared_context(objectives)
        for task in tasks:
            task.context = (task.context + "\n\n" + brief).strip() if task.context else brief

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
            # DAG edges for the pipeline viewer: dependency task ids mapped to the
            # same agent-id scheme this worker uses, so the UI can draw them.
            "depends_on": ["{:s}:w:{:s}".format(self._session_id, d)
                           for d in (getattr(task, "depends_on", None) or [])],
        })
        try:
            result = await self._worker_runner(task)
        except Exception as ex:  # pylint: disable=broad-except
            _log.warning("worker %s failed: %s", task.id, ex)
            result = WorkerResult(
                task_id=task.id, objective_id=task.objective_id,
                proof="worker errored: {:s}".format(str(ex)), ok=False)
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
            await self._apply_handoff(tasks, objectives)
            results = await self._scheduler.run(tasks, self._run_one_worker)
            if self._pre_eval is not None:
                await self._pre_eval(tasks, results)
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
