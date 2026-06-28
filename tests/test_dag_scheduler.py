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
    DAG, DagScheduler, WorkerTask, WorkerResult, InMemoryGraphData, StepData)


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


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
