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
import tempfile
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

    def _captured_worker_context(self, share: bool) -> str:
        a = _import_autonomy()
        llm = self._scripted_llm([
            '{"tasks": [{"objective_id": "o1", "instruction": "do it"}]}',
            '{"verdicts": [{"objective_id": "o1", "met": true, "evidence": "done"}]}',
        ])
        captured: list[str] = []

        async def worker_runner(task: Any) -> Any:
            captured.append(task.context)
            return a.WorkerResult(task.id, task.objective_id, "ok", ok=True)

        async def emit(event: dict[str, Any]) -> None:
            pass

        objectives = [a.Objective(id="o1", text="a watertight torso", acceptance="is watertight")]
        orch = a.AutonomyOrchestrator(
            planner=a.LlmPlanner(llm, "m"),
            scheduler=a.SequentialScheduler(),
            evaluator=a.StateAwareEvaluator(llm, "m"),
            policy=a.AutoUntilDonePolicy(),
            worker_runner=worker_runner,
            emit=emit,
            session_id="s1",
            share_context=share,
        )
        _run(orch.run(objectives, max_rounds=2))
        return captured[0] if captured else ""

    def test_share_context_switch(self) -> None:
        blind = self._captured_worker_context(share=False)
        informed = self._captured_worker_context(share=True)
        self.assertEqual(blind, "")
        self.assertIn("watertight torso", informed)

    def test_draft_objectives_parses_goal_into_objectives(self) -> None:
        a = _import_autonomy()
        llm = self._scripted_llm([
            '{"objectives": [{"text": "a watertight torso", "acceptance": "is watertight"},'
            ' {"text": "two arms", "acceptance": "two arm objects"}, {"text": "", "acceptance": "skip"}]}',
        ])
        objs = _run(a.draft_objectives(llm, "m", "build a robot"))
        self.assertEqual(len(objs), 2)  # the empty-text one is dropped
        self.assertEqual(objs[0]["text"], "a watertight torso")
        self.assertEqual(objs[0]["acceptance"], "is watertight")

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

    def test_parallel_scheduler_runs_concurrently_and_bounds(self) -> None:
        a = _import_autonomy()
        tasks = [a.WorkerTask(id="t{:d}".format(i), objective_id="o", instruction="i")
                 for i in range(6)]
        live = {"now": 0, "peak": 0}

        async def runner(task: Any) -> Any:
            live["now"] += 1
            live["peak"] = max(live["peak"], live["now"])
            await asyncio.sleep(0.02)  # overlap window
            live["now"] -= 1
            return a.WorkerResult(task.id, "o", "ok")

        out = _run(a.ParallelScheduler(max_concurrency=3).run(tasks, runner))
        # All ran, results carry every task, and concurrency was real but capped.
        self.assertEqual({r.task_id for r in out}, {t.id for t in tasks})
        self.assertGreater(live["peak"], 1, "tasks must overlap (ran in parallel)")
        self.assertLessEqual(live["peak"], 3, "concurrency must respect the cap")


@unittest.skipUnless(_HAS_AGENT_DEPS, "agent dependencies not installed (optional feature)")
class TestIndependentAuditor(unittest.TestCase):
    """Opt-in adversarial audit: re-checks goals against state, flags overclaims."""

    def _llm(self, text: str) -> Any:
        from blagent.llm import LlmChunk, LlmClient

        class Once(LlmClient):
            async def stream(self, request: dict[str, Any]) -> Any:
                yield LlmChunk(content=text)
        return Once()

    def _objs(self, a: Any) -> Any:
        o1 = a.Objective(id="o1", text="torso", acceptance="torso exists", status="met",
                         evidence="orchestrator says built")
        o2 = a.Objective(id="o2", text="arms", acceptance="two arms", status="met",
                         evidence="orchestrator says built")
        return [o1, o2]

    def test_audit_passes_when_state_corroborates(self) -> None:
        a = _import_autonomy()
        llm = self._llm(
            '{"summary":"all good","verdicts":['
            '{"objective_id":"o1","met":true,"overclaim":false,"evidence":"torso in scene"},'
            '{"objective_id":"o2","met":true,"overclaim":false,"evidence":"two arms in scene"}]}')

        async def probe() -> str:
            return "objects: torso, arm_L, arm_R"

        report = _run(a.IndependentAuditor(llm, "m", probe=probe).audit(self._objs(a)))
        self.assertTrue(report.passed)
        self.assertEqual(report.overclaims, [])

    def test_audit_catches_overclaim(self) -> None:
        a = _import_autonomy()
        # Orchestrator claimed both met; auditor finds o2 missing from the scene.
        llm = self._llm(
            '{"summary":"o2 missing","verdicts":['
            '{"objective_id":"o1","met":true,"overclaim":false,"evidence":"torso present"},'
            '{"objective_id":"o2","met":false,"overclaim":true,"evidence":"no arm objects in scene"}]}')

        async def probe() -> str:
            return "objects: torso"

        report = _run(a.IndependentAuditor(llm, "m", probe=probe).audit(self._objs(a)))
        self.assertFalse(report.passed)
        self.assertIn("o2", report.overclaims)

    def test_audit_fails_closed_and_infers_overclaim(self) -> None:
        a = _import_autonomy()
        # Auditor returns met=false WITHOUT setting overclaim; since the
        # orchestrator claimed o1 met, the auditor must still flag the overclaim.
        llm = self._llm(
            '{"verdicts":[{"objective_id":"o1","met":false,"evidence":"empty scene"}]}')

        async def probe() -> str:
            return "objects: (none)"

        report = _run(a.IndependentAuditor(llm, "m", probe=probe).audit(self._objs(a)))
        self.assertFalse(report.passed)
        by_id = {v.objective_id: v for v in report.verdicts}
        self.assertTrue(by_id["o1"].overclaim)          # inferred from claim vs ruling
        self.assertFalse(by_id["o2"].met)               # no verdict -> unverified
        self.assertTrue(by_id["o2"].overclaim)          # was claimed met


@unittest.skipUnless(_HAS_AGENT_DEPS, "agent dependencies not installed (optional feature)")
class TestChildSessionRunner(unittest.TestCase):
    """
    The child-session strategy made real: a worker task runs in its own
    AgentEngine with the full tool surface, and the orchestrator gets back
    the worker's final report as proof. Events are tagged for the bounded UI.
    """

    def test_worker_runs_real_turn_and_returns_proof(self) -> None:
        for path in (os.path.join(_REPO_DIR, "mcp"), os.path.join(_REPO_DIR, "agent")):
            if path not in sys.path:
                sys.path.insert(0, path)
        from blagent.autonomy import WorkerTask
        from blagent.llm import LlmChunk, LlmClient
        from blagent.media import MediaLibrary
        from blagent.runtime import ChildSessionRunner
        from blagent.tools import Tool, ToolRegistry, ToolResult

        tool_calls: list[dict[str, Any]] = []

        class StubTool(Tool):
            name = "build_thing"
            description = "build a thing"

            def input_schema(self) -> dict[str, Any]:
                return {"type": "object", "properties": {}}

            async def call(self, ctx: Any, args: dict[str, Any]) -> Any:
                tool_calls.append(args)
                return ToolResult(summary="built", data={"created": "Cube"})

        class FakeLlm(LlmClient):
            def __init__(self) -> None:
                self.round = 0

            async def stream(self, request: dict[str, Any]) -> Any:
                self.round += 1
                if self.round == 1:
                    yield LlmChunk(tool_calls=[{
                        "index": 0, "id": "c1",
                        "function": {"name": "build_thing", "arguments": "{}"},
                    }])
                else:
                    yield LlmChunk(content="PROOF OF WORK: created object Cube.")

        events: list[dict[str, Any]] = []

        async def emit(event: dict[str, Any]) -> None:
            events.append(event)

        live: dict[str, Any] = {}
        registered: list[str] = []

        def register(aid: str, eng: Any) -> None:
            live[aid] = eng
            registered.append(aid)

        def unregister(aid: str) -> None:
            live.pop(aid, None)

        tmp = tempfile.mkdtemp(prefix="worker_")
        runner = ChildSessionRunner(
            registry=ToolRegistry([StubTool()]),
            make_llm=lambda: FakeLlm(),
            model="m",
            emit=emit,
            system_prompt="",
            media_factory=lambda agent_id: MediaLibrary(
                os.path.join(tmp, agent_id.replace(":", "_"))),
            parent_session_id="orch1",
            autonomy="auto",
            max_rounds=4,
            register=register,
            unregister=unregister,
        )
        result = _run(runner(WorkerTask(id="t1", objective_id="o1", instruction="build it")))

        self.assertTrue(result.ok)
        self.assertIn("Cube", result.proof)
        self.assertEqual(result.transcript_ref, "orch1:w:t1")
        self.assertEqual(len(tool_calls), 1)  # the worker really ran the tool
        # Registered for injection during the run, cleaned up after.
        self.assertEqual(registered, ["orch1:w:t1"])
        self.assertEqual(live, {})
        worker_events = [e for e in events if e.get("parent_session_id") == "orch1"]
        self.assertTrue(worker_events)
        self.assertTrue(all(e.get("role") == "worker" for e in worker_events))
        self.assertTrue(any(e.get("session_id") == "orch1:w:t1" for e in worker_events))

    def test_worker_registry_restricted_and_mission_pinned(self) -> None:
        for path in (os.path.join(_REPO_DIR, "mcp"), os.path.join(_REPO_DIR, "agent")):
            if path not in sys.path:
                sys.path.insert(0, path)
        from blagent.autonomy import WorkerTask
        from blagent.llm import LlmChunk, LlmClient
        from blagent.media import MediaLibrary
        from blagent.runtime import ChildSessionRunner
        from blagent.tools import Tool, ToolRegistry, ToolResult

        def _stub(tool_name: str) -> Any:
            class _T(Tool):
                name = tool_name
                description = tool_name

                def input_schema(self) -> dict[str, Any]:
                    return {"type": "object", "properties": {}}

                async def call(self, ctx: Any, args: dict[str, Any]) -> Any:
                    return ToolResult(summary="ok")
            return _T()

        seen: dict[str, Any] = {}

        class FakeLlm(LlmClient):
            async def stream(self, request: dict[str, Any]) -> Any:
                seen.setdefault("system", request["messages"][0]["content"])
                seen.setdefault("tools", [t["function"]["name"] for t in request.get("tools", [])])
                yield LlmChunk(content="PROOF OF WORK: done.")

        async def emit(_e: dict[str, Any]) -> None:
            pass

        tmp = tempfile.mkdtemp(prefix="worker_")
        runner = ChildSessionRunner(
            registry=ToolRegistry([_stub("build_thing"), _stub("set_autonomy"), _stub("ask_user")]),
            make_llm=lambda: FakeLlm(),
            model="m",
            emit=emit,
            system_prompt="BASE PROMPT.",
            media_factory=lambda agent_id: MediaLibrary(os.path.join(tmp, agent_id.replace(":", "_"))),
            parent_session_id="orch1",
        )
        _run(runner(WorkerTask(
            id="t1", objective_id="o1", instruction="model a peg",
            goal="assemble the arm", acceptance="peg mates with socket")))

        # Orchestrator/user-only tools are stripped from the worker surface.
        self.assertIn("build_thing", seen["tools"])
        self.assertNotIn("set_autonomy", seen["tools"])
        self.assertNotIn("ask_user", seen["tools"])
        # Mission is pinned in the SYSTEM prompt (survives context trimming).
        sysmsg = seen["system"]
        self.assertIn("BASE PROMPT.", sysmsg)
        self.assertIn("model a peg", sysmsg)
        self.assertIn("assemble the arm", sysmsg)
        self.assertIn("peg mates with socket", sysmsg)
        self.assertIn("no user to ask", sysmsg.lower())


if __name__ == "__main__":
    unittest.main()
