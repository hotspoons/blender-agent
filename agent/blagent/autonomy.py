# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

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
    "LlmPlanner",
    "StateAwareEvaluator",
    "SequentialScheduler",
    "ParallelScheduler",
    "AutoUntilDonePolicy",
    "AutoPauseWhenBlockedPolicy",
    "AutonomyOrchestrator",
)

import asyncio
import dataclasses
import json
import logging
from typing import Any, Awaitable, Callable

from .llm import LlmClient

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


@dataclasses.dataclass
class WorkerResult:
    """A worker's proof-of-work, returned to the orchestrator."""

    task_id: str
    objective_id: str
    proof: str
    ok: bool = True
    transcript_ref: str = ""   # child session / agent id for UI drill-down


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

async def _complete(llm: LlmClient, model: str, system: str, user: str) -> str:
    """One non-streamed-to-UI completion; returns concatenated content."""
    request = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    parts: list[str] = []
    async for chunk in llm.stream(request):
        if chunk.content:
            parts.append(chunk.content)
    return "".join(parts)


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


class LlmPlanner:
    """Default planner: asks the LLM to decompose unmet objectives."""

    def __init__(self, llm: LlmClient, model: str) -> None:
        self._llm = llm
        self._model = model

    async def plan(self, unmet: list[Objective]) -> list[WorkerTask]:
        listing = "\n".join(
            "- id={:s} | goal: {:s} | acceptance: {:s}".format(o.id, o.text, o.acceptance)
            for o in unmet
        )
        text = await _complete(self._llm, self._model, _PLANNER_SYSTEM,
                               "UNMET OBJECTIVES:\n" + listing)
        data = _extract_json_object(text)
        valid_ids = {o.id for o in unmet}
        tasks: list[WorkerTask] = []
        for i, raw in enumerate(data.get("tasks", []) or []):
            if not isinstance(raw, dict):
                continue
            instruction = str(raw.get("instruction", "")).strip()
            oid = str(raw.get("objective_id", "")).strip()
            if oid not in valid_ids:
                oid = unmet[0].id  # mis-tagged task still belongs to the round
            if instruction:
                tasks.append(WorkerTask(
                    id="task-{:d}-{:d}".format(len(tasks), i),
                    objective_id=oid, instruction=instruction))
        if not tasks:
            # Degrade to one task per unmet objective rather than stalling.
            tasks = [
                WorkerTask(id="task-{:d}".format(i), objective_id=o.id, instruction=o.text)
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
        text = await _complete(self._llm, self._model, _EVAL_SYSTEM, user)
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
    Bounded-concurrency scheduler for a future where workers each bind to
    their own headless Blender instance (see ``blender_surface.py``). Kept
    out of the default path until that binding exists.
    """

    def __init__(self, max_concurrency: int = 4) -> None:
        self._sem = asyncio.Semaphore(max(1, max_concurrency))

    async def run(self, tasks: list[WorkerTask], run_worker: WorkerRunner) -> list[WorkerResult]:
        async def _guarded(task: WorkerTask) -> WorkerResult:
            async with self._sem:
                return await run_worker(task)

        return list(await asyncio.gather(*(_guarded(t) for t in tasks)))


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
    ) -> None:
        self._planner = planner
        self._scheduler = scheduler
        self._evaluator = evaluator
        self._policy = policy
        self._worker_runner = worker_runner
        self._emit = emit
        self._session_id = session_id

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
            "agent_id": result.transcript_ref,
            "role": "worker",
            "objective_id": task.objective_id,
            "ok": result.ok,
            "proof": result.proof,
        })
        return result

    async def run(self, objectives: list[Objective], max_rounds: int = 6) -> dict[str, Any]:
        """
        Pursue *objectives* across up to *max_rounds* rounds. Returns a
        summary dict; emits events throughout.
        """
        by_id = {o.id: o for o in objectives}
        decision = DONE
        rounds_run = 0
        for round_index in range(max_rounds):
            rounds_run = round_index + 1
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
