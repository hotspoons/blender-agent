# SPDX-License-Identifier: GPL-3.0-or-later
"""The ported DAG model + dependency-gated scheduler (agentcore.autonomy).

Pins the executor contract the swarm relies on: build-part tasks run in
parallel, a downstream 'assemble' task waits for its parts, 'validate' waits for
assemble, and a task whose prerequisite failed is skipped (the failure
propagates instead of running blind). Also covers the graph primitives ported
from zip-ties (topological generations w/ the single fixed edge convention,
cycle detection, dynamic fan-out)."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp"))

from agentcore.autonomy import (  # noqa: E402
    DAG, DagScheduler, WorkerTask, WorkerResult, InMemoryGraphData, StepData,
    LlmPlanner, Objective, AutonomyOrchestrator,
    HANDOFF_BLIND, HANDOFF_HANDOFF, HANDOFF_COMPACTION, HANDOFF_FULL)


async def _noop(_e):
    return None


def _orch(handoff, compactor=None, context=""):
    return AutonomyOrchestrator(
        planner=None, scheduler=None, evaluator=None, policy=None,
        worker_runner=None, emit=_noop, session_id="s",
        handoff=handoff, compactor=compactor, context=context)


def test_topological_generations_dep_runs_first():
    # add_edge(dep, node): dep must finish before node.
    g = DAG()
    for n in ("a", "b", "assemble", "validate"):
        g.add_node(n)
    g.add_edge("a", "assemble")
    g.add_edge("b", "assemble")
    g.add_edge("assemble", "validate")
    gens = g.topological_generations()
    assert g.is_dag()
    assert gens[0] == {"a", "b"}        # parts first, together
    assert gens[1] == {"assemble"}      # then assemble
    assert gens[2] == {"validate"}      # then validate


def test_cycle_detected():
    g = DAG()
    g.add_edge("a", "b")
    g.add_edge("b", "a")
    assert not g.is_dag()


def test_fan_out_inherits_deps_and_dependents():
    g = DAG()
    g.add_edge("seed", "chars")        # chars depends on seed
    g.add_edge("chars", "assemble")    # assemble depends on chars
    g.replace_node_with_fan("chars", ["chars_0", "chars_1"])
    gens = g.topological_generations()
    assert gens[0] == {"seed"}
    assert gens[1] == {"chars_0", "chars_1"}   # both instances run together
    assert gens[2] == {"assemble"}             # assemble waits for ALL instances


def _task(tid, deps=()):
    return WorkerTask(id=tid, objective_id=tid, instruction=tid, depends_on=list(deps))


def test_scheduler_runs_deps_before_dependents():
    started = []

    async def run_worker(task):
        started.append(("start", task.id))
        await asyncio.sleep(0.01)
        started.append(("end", task.id))
        return WorkerResult(task_id=task.id, objective_id=task.objective_id, proof="ok", ok=True)

    tasks = [
        _task("body"), _task("head"),
        _task("assemble", deps=["body", "head"]),
        _task("validate", deps=["assemble"]),
    ]
    results = asyncio.run(DagScheduler(max_concurrency=4).run(tasks, run_worker))
    assert all(r.ok for r in results)
    # assemble must not start until both parts ended
    assemble_start = started.index(("start", "assemble"))
    assert started.index(("end", "body")) < assemble_start
    assert started.index(("end", "head")) < assemble_start
    # validate after assemble ends
    assert started.index(("end", "assemble")) < started.index(("start", "validate"))
    # parts run concurrently (both start before either ends)
    assert started[0][0] == "start" and started[1][0] == "start"


def test_failed_prerequisite_skips_dependent():
    async def run_worker(task):
        ok = task.id != "body"   # body fails
        return WorkerResult(task_id=task.id, objective_id=task.objective_id,
                            proof="x", ok=ok)

    tasks = [_task("body"), _task("head"), _task("assemble", deps=["body", "head"])]
    results = asyncio.run(DagScheduler().run(tasks, run_worker))
    by = {r.task_id: r for r in results}
    assert by["body"].ok is False
    assert by["assemble"].ok is False and "prerequisite" in by["assemble"].proof


def test_step_store_records_and_feeds_upstream_to_downstream():
    seen_context = {}

    async def run_worker(task):
        seen_context[task.id] = task.context
        return WorkerResult(task_id=task.id, objective_id=task.objective_id,
                            proof="built {}".format(task.id), ok=True)

    graph = InMemoryGraphData()
    tasks = [_task("body"), _task("head"), _task("assemble", deps=["body", "head"])]
    asyncio.run(DagScheduler(graph=graph).run(tasks, run_worker))

    # Every node's result is recorded in the store.
    assert {sd.agent_id for sd in graph.fetch_all_data()} == {"body", "head", "assemble"}
    assert graph.fetch_last_data_by_id("body").text == "built body"
    # The downstream node was handed its upstream results (context sharing).
    ctx = seen_context["assemble"]
    assert "built body" in ctx and "built head" in ctx
    # Upstream parts had no context injected.
    assert not seen_context["body"]


def test_fan_in_results_from_store():
    graph = InMemoryGraphData()
    for i in range(3):
        graph.put_data(StepData(agent_id="char_{}".format(i), text="char {}".format(i)))
    graph.put_data(StepData(agent_id="terrain", text="ground"))
    fan = graph.fetch_fan_in_results("char")
    assert [sd.agent_id for sd in fan] == ["char_0", "char_1", "char_2"]


def test_planner_emits_depends_on_and_resolves_forward_refs():
    plan_json = (
        '{"tasks": ['
        '{"id": "chars", "objective_id": "obj-0", "instruction": "build chars"},'
        '{"id": "assemble", "objective_id": "obj-1", "instruction": "assemble all",'
        ' "depends_on": ["chars", "terrain"]},'           # terrain is defined AFTER (forward ref)
        '{"id": "terrain", "objective_id": "obj-0", "instruction": "build terrain"}'
        ']}'
    )

    async def stub_runner(system, user):
        return plan_json

    planner = LlmPlanner(llm=None, model="x", runner=stub_runner)
    unmet = [Objective(id="obj-0", text="parts", acceptance="parts exist"),
             Objective(id="obj-1", text="assembled", acceptance="one scene")]
    tasks = asyncio.run(planner.plan(unmet))
    by = {t.id: t for t in tasks}
    assert set(by) == {"chars", "assemble", "terrain"}
    assert by["chars"].depends_on == []
    assert sorted(by["assemble"].depends_on) == ["chars", "terrain"]  # forward ref resolved
    # and the resulting DAG schedules parts before assemble
    dag = DAG()
    for t in tasks:
        dag.add_node(t.id)
        for d in t.depends_on:
            dag.add_edge(d, t.id)
    gens = dag.topological_generations()
    assert gens[0] == {"chars", "terrain"} and gens[1] == {"assemble"}


def test_planner_sanitizes_ids_and_drops_self_dep():
    async def stub_runner(system, user):
        return ('{"tasks": [{"id": "build chars!", "objective_id": "obj-0", '
                '"instruction": "x", "depends_on": ["build chars!"]}]}')   # self-dep
    planner = LlmPlanner(llm=None, model="x", runner=stub_runner)
    tasks = asyncio.run(planner.plan([Objective(id="obj-0", text="t", acceptance="a")]))
    assert tasks[0].id == "build-chars"      # sanitized to a safe id
    assert tasks[0].depends_on == []          # self-dependency dropped


def _objs():
    return [Objective(id="obj-0", text="build a body", acceptance="Body mesh exists")]


def test_handoff_blind_injects_nothing():
    tasks = [_task("t")]
    asyncio.run(_orch(HANDOFF_BLIND)._apply_handoff(tasks, _objs()))
    assert tasks[0].context == ""


def test_handoff_handoff_injects_objectives():
    tasks = [_task("t")]
    asyncio.run(_orch(HANDOFF_HANDOFF)._apply_handoff(tasks, _objs()))
    assert "build a body" in tasks[0].context and "done-when" in tasks[0].context


def test_handoff_full_includes_conversation():
    tasks = [_task("t")]
    asyncio.run(_orch(HANDOFF_FULL, context="USER: make a robot")._apply_handoff(tasks, _objs()))
    assert "Full orchestrator context" in tasks[0].context and "make a robot" in tasks[0].context


def test_handoff_compaction_uses_compactor_else_falls_back():
    async def compactor(objectives, ctx):
        return "BRIEF: build the body, nothing done yet."
    tasks = [_task("t")]
    asyncio.run(_orch(HANDOFF_COMPACTION, compactor=compactor)._apply_handoff(tasks, _objs()))
    assert tasks[0].context == "BRIEF: build the body, nothing done yet."
    # no compactor wired -> falls back to the concise handoff
    tasks2 = [_task("t")]
    asyncio.run(_orch(HANDOFF_COMPACTION)._apply_handoff(tasks2, _objs()))
    assert "build a body" in tasks2[0].context


def test_fanout_expands_to_instances_with_iteration_tree():
    ran = []

    async def run_worker(task):
        ran.append((task.id, task.context))
        return WorkerResult(task_id=task.id, objective_id=task.objective_id,
                            proof="did {}".format(task.id), ok=True)

    graph = InMemoryGraphData()
    tasks = [
        WorkerTask(id="trees", objective_id="obj-0", instruction="plant a tree",
                   fan_out=[{"context": "tree A"}, {"context": "tree B"}, {"context": "tree C"}]),
        WorkerTask(id="assemble", objective_id="obj-1", instruction="assemble", depends_on=["trees"]),
    ]
    results = asyncio.run(DagScheduler(graph=graph).run(tasks, run_worker))
    ids = {r.task_id for r in results}
    assert ids == {"trees_0", "trees_1", "trees_2", "assemble"}
    # each instance got its assignment context
    ctx = dict(ran)
    assert "tree A" in ctx["trees_0"] and "tree C" in ctx["trees_2"]
    # iteration_tree recorded per instance in the step store
    assert graph.fetch_data("trees_1", [1]) is not None
    assert graph.fetch_data("trees_0", [0]) is not None
    # fan-in: assemble depended on the template -> rewired to ALL instances,
    # so its context carries every instance's result
    asm_ctx = ctx["assemble"]
    assert "did trees_0" in asm_ctx and "did trees_1" in asm_ctx and "did trees_2" in asm_ctx


def test_pre_eval_runs_before_evaluation():
    from agentcore.autonomy import GoalVerdict, AutoUntilDonePolicy

    order = []

    class StubPlanner:
        async def plan(self, unmet):
            return [WorkerTask(id="t", objective_id="obj-0", instruction="x")]

    class StubScheduler:
        async def run(self, tasks, run_worker):
            order.append("workers")
            return [WorkerResult(task_id="t", objective_id="obj-0", proof="p", ok=True)]

    class StubEvaluator:
        async def evaluate(self, objectives, results):
            order.append("eval")
            return [GoalVerdict(objective_id=o.id, met=True, evidence="ok", next_action="")
                    for o in objectives]

    async def pre_eval(tasks, results):
        order.append("pre_eval")

    orch = AutonomyOrchestrator(
        planner=StubPlanner(), scheduler=StubScheduler(), evaluator=StubEvaluator(),
        policy=AutoUntilDonePolicy(), worker_runner=None, emit=_noop, session_id="s",
        pre_eval=pre_eval)
    asyncio.run(orch.run([Objective(id="obj-0", text="g", acceptance="a")], max_rounds=2))
    # gather (pre_eval) must happen after the workers and BEFORE evaluation
    assert order[:3] == ["workers", "pre_eval", "eval"]


def test_worker_exception_does_not_crash_run():
    # A worker that RAISES (not returns ok=False) must not tear down the
    # generation via asyncio.gather — it becomes a failed result and its
    # siblings still complete. Regression for the swarm 1011 server crash.
    async def run_worker(task):
        if task.id == "boom":
            raise ValueError("kaboom")          # non-string-formattable too
        return WorkerResult(task_id=task.id, objective_id=task.objective_id, proof="ok", ok=True)

    tasks = [_task("boom"), _task("fine")]
    results = asyncio.run(DagScheduler(max_concurrency=2).run(tasks, run_worker))
    by = {r.task_id: r for r in results}
    assert by["boom"].ok is False and "kaboom" in by["boom"].proof
    assert by["fine"].ok is True               # sibling unaffected


def test_legacy_share_context_maps_to_handoff_mode():
    orch = AutonomyOrchestrator(planner=None, scheduler=None, evaluator=None, policy=None,
                                worker_runner=None, emit=_noop, share_context=True)
    tasks = [_task("t")]
    asyncio.run(orch._apply_handoff(tasks, _objs()))
    assert "build a body" in tasks[0].context   # share_context=True == handoff mode


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
