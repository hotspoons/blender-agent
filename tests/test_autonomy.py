# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Tests for autonomy mode (``agent/blagent/autonomy.py``): the goal-level
orchestrator loop, default planner/evaluator/scheduler/policy, and the
emitted sub-agent events. Driven by a scripted fake LLM — no Blender, no
network. Skipped when agent deps are absent.

    python -m unittest tests.test_autonomy -v
"""

__all__ = ()

import asyncio
import importlib
import importlib.util
import os
import sys
import unittest
from typing import Any

_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_HAS_AGENT_DEPS = all(
    importlib.util.find_spec(mod) is not None
    for mod in ("starlette", "uvicorn", "httpx", "mcp", "blmcp")
)


def _import_autonomy() -> Any:
    for path in (os.path.join(_REPO_DIR, "mcp"), os.path.join(_REPO_DIR, "agent")):
        if path not in sys.path:
            sys.path.insert(0, path)
    return importlib.import_module("blagent.autonomy")


def _run(coro: Any) -> Any:
    return asyncio.new_event_loop().run_until_complete(coro)


@unittest.skipUnless(_HAS_AGENT_DEPS, "agent dependencies not installed (optional feature)")
class TestAutonomyLoop(unittest.TestCase):

    def _scripted_llm(self, scripted: list[str]) -> Any:
        from blagent.llm import LlmChunk, LlmClient

        class ScriptedLlm(LlmClient):
            def __init__(self) -> None:
                self.queue = list(scripted)
                self.calls = 0

            async def stream(self, request: dict[str, Any]) -> Any:
                self.calls += 1
                text = self.queue.pop(0) if self.queue else "{}"
                yield LlmChunk(content=text)

        return ScriptedLlm()

    def test_loop_runs_until_all_objectives_met(self) -> None:
        a = _import_autonomy()

        # Round 0: plan both, evaluator says o1 met / o2 unmet (with next step).
        # Round 1: plan o2, evaluator says both met -> DONE after 2 rounds.
        llm = self._scripted_llm([
            '{"tasks": [{"objective_id": "o1", "instruction": "build o1"},'
            ' {"objective_id": "o2", "instruction": "build o2"}]}',
            '{"verdicts": [{"objective_id": "o1", "met": true, "evidence": "o1 in scene", "next_action": ""},'
            ' {"objective_id": "o2", "met": false, "evidence": "missing", "next_action": "add o2"}]}',
            '{"tasks": [{"objective_id": "o2", "instruction": "finish o2"}]}',
            '{"verdicts": [{"objective_id": "o1", "met": true, "evidence": "still there", "next_action": ""},'
            ' {"objective_id": "o2", "met": true, "evidence": "o2 in scene", "next_action": ""}]}',
        ])

        seen_tasks: list[str] = []

        async def worker_runner(task: Any) -> Any:
            seen_tasks.append(task.id)
            return a.WorkerResult(
                task_id=task.id, objective_id=task.objective_id,
                proof="did {:s}".format(task.instruction), ok=True)

        events: list[dict[str, Any]] = []

        async def emit(event: dict[str, Any]) -> None:
            events.append(event)

        probe_calls = [0]

        async def probe() -> str:
            probe_calls[0] += 1
            return "objects: [...]"

        objectives = [
            a.Objective(id="o1", text="a torso", acceptance="torso object exists"),
            a.Objective(id="o2", text="two arms", acceptance="two arm objects exist"),
        ]
        orch = a.AutonomyOrchestrator(
            planner=a.LlmPlanner(llm, "m"),
            scheduler=a.SequentialScheduler(),
            evaluator=a.StateAwareEvaluator(llm, "m", probe=probe),
            policy=a.AutoUntilDonePolicy(),
            worker_runner=worker_runner,
            emit=emit,
            session_id="s1",
        )
        result = _run(orch.run(objectives, max_rounds=6))

        self.assertEqual(result["decision"], a.DONE)
        self.assertTrue(result["all_met"])
        self.assertEqual(result["rounds"], 2)
        self.assertTrue(all(o.status == "met" for o in objectives))
        # 3 workers spawned total (2 in round 0, 1 in round 1).
        self.assertEqual(len(seen_tasks), 3)
        # Evaluator probed project state each round.
        self.assertEqual(probe_calls[0], 2)
        # Bounded sub-agent events bracket each worker, and the loop closes done.
        self.assertEqual(sum(e["type"] == "agent_spawned" for e in events), 3)
        self.assertEqual(sum(e["type"] == "agent_done" for e in events), 3)
        self.assertEqual(sum(e["type"] == "autonomy_round_start" for e in events), 2)
        self.assertTrue(any(e["type"] == "autonomy_done" and e["all_met"] for e in events))

    def test_pause_when_blocked(self) -> None:
        a = _import_autonomy()
        llm = self._scripted_llm([
            '{"tasks": [{"objective_id": "o1", "instruction": "try o1"}]}',
            '{"verdicts": [{"objective_id": "o1", "met": false, "evidence": "cannot", "next_action": ""}]}',
        ])

        async def worker_runner(task: Any) -> Any:
            return a.WorkerResult(task.id, task.objective_id, "tried", ok=True)

        events: list[dict[str, Any]] = []

        async def emit(event: dict[str, Any]) -> None:
            events.append(event)

        objectives = [a.Objective(id="o1", text="impossible", acceptance="???")]
        orch = a.AutonomyOrchestrator(
            planner=a.LlmPlanner(llm, "m"),
            scheduler=a.SequentialScheduler(),
            evaluator=a.StateAwareEvaluator(llm, "m"),
            policy=a.AutoPauseWhenBlockedPolicy(),
            worker_runner=worker_runner,
            emit=emit,
            session_id="s1",
        )
        result = _run(orch.run(objectives, max_rounds=6))

        self.assertEqual(result["decision"], a.PAUSE)
        self.assertFalse(result["all_met"])
        self.assertEqual(result["rounds"], 1)
        self.assertTrue(any(e["type"] == "autonomy_paused" for e in events))

    def test_evaluator_fails_closed_on_missing_verdict(self) -> None:
        a = _import_autonomy()
        # Evaluator returns a verdict only for o1; o2 must stay unmet.
        llm = self._scripted_llm([
            '{"verdicts": [{"objective_id": "o1", "met": true, "evidence": "ok"}]}',
        ])
        objs = [
            a.Objective(id="o1", text="x", acceptance="x"),
            a.Objective(id="o2", text="y", acceptance="y"),
        ]
        evaluator = a.StateAwareEvaluator(llm, "m")
        verdicts = _run(evaluator.evaluate(objs, []))
        by_id = {v.objective_id: v for v in verdicts}
        self.assertTrue(by_id["o1"].met)
        self.assertFalse(by_id["o2"].met)

    def test_sequential_scheduler_preserves_order(self) -> None:
        a = _import_autonomy()
        tasks = [a.WorkerTask(id="t{:d}".format(i), objective_id="o", instruction="i")
                 for i in range(4)]
        order: list[str] = []

        async def runner(task: Any) -> Any:
            order.append(task.id)
            return a.WorkerResult(task.id, "o", "ok")

        out = _run(a.SequentialScheduler().run(tasks, runner))
        self.assertEqual(order, ["t0", "t1", "t2", "t3"])
        self.assertEqual([r.task_id for r in out], ["t0", "t1", "t2", "t3"])


if __name__ == "__main__":
    unittest.main()
