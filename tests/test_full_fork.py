# SPDX-License-Identifier: GPL-3.0-or-later
"""The 'full' context-handoff fork (agentcore.engine seed_messages +
ChildSessionRunner/evaluator wiring).

Pins the fork contract: every forked agent shares one byte-identical prefix
(system prompt + the parent conversation seeded behind it) with its mission
arriving as the first user message, pinned against context trimming — the
layout that lets a prefix-caching server pay for the parent context once
across the whole worker/QA/evaluator fleet."""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp"))

from agentcore.autonomy import (  # noqa: E402
    HANDOFF_FULL, AutonomyOrchestrator, Objective, StateAwareEvaluator,
    WorkerResult, WorkerTask)
from agentcore.engine import AgentEngine  # noqa: E402
from agentcore.llm import LlmChunk, LlmClient  # noqa: E402
from agentcore.media import MediaLibrary  # noqa: E402
from agentcore.tools import ToolRegistry  # noqa: E402
from agentcore.runtime import _WORKER_FORK_PREAMBLE, ChildSessionRunner  # noqa: E402


async def _noop(_e):
    return None


def _engine(tmp, system="SYS", seed=None):
    return AgentEngine(
        registry=ToolRegistry([]), media=MediaLibrary(tmp), system_prompt=system,
        emit=_noop, append_record=lambda r: None, seed_messages=seed)


_SEED = [
    {"role": "user", "content": "please build a fantasy village"},
    {"role": "assistant", "content": "Understood — planning the village."},
]


def test_seed_projects_between_system_and_own_records():
    with tempfile.TemporaryDirectory() as tmp:
        eng = _engine(tmp, seed=_SEED)
        eng.push_record({"role": "user", "content": "your task: build the well"})
        messages = eng._llm_messages()
        # system, seed user, seed assistant, tool roster, own record.
        assert [m["role"] for m in messages] == ["system", "user", "assistant", "user", "user"]
        assert messages[1]["content"] == "please build a fantasy village"
        assert "[Context handoff]" in messages[3]["content"]
        assert messages[4]["content"] == "your task: build the well"


def test_seeded_engine_declares_its_own_tool_roster():
    from agentcore.tools import Tool

    class WellTool(Tool):
        name = "dig_well"
        description = "Digs a well.\nLong details the roster must not include."

    with tempfile.TemporaryDirectory() as tmp:
        eng = AgentEngine(
            registry=ToolRegistry([WellTool()]), media=MediaLibrary(tmp),
            system_prompt="SYS", emit=_noop, append_record=lambda r: None,
            seed_messages=_SEED)
        roster = eng._llm_messages()[3]["content"]
        assert "dig_well — Digs a well." in roster
        assert "Long details" not in roster
        # Unseeded engines carry no roster note at all.
        bare = _engine(tmp)
        bare.push_record({"role": "user", "content": "hi"})
        assert all("[Context handoff]" not in str(m.get("content", ""))
                   for m in bare._llm_messages())


def test_post_construction_seed_only_on_virgin_engine():
    with tempfile.TemporaryDirectory() as tmp:
        eng = _engine(tmp)
        assert eng.seed(_SEED) is True
        assert eng.seed(_SEED) is False           # no double seed
        used = _engine(tmp)
        used.push_record({"role": "user", "content": "already talking"})
        assert used.seed(_SEED) is False          # not an injection channel


def test_seed_is_deep_copied_per_fork():
    with tempfile.TemporaryDirectory() as tmp:
        source = [{"role": "user", "content": "original"}]
        a, b = _engine(tmp, seed=source), _engine(tmp, seed=source)
        source[0]["content"] = "mutated after spawn"
        assert a._llm_messages()[1]["content"] == "original"
        # One fork trimming its copy must not contaminate a sibling fork.
        a._seed_messages[0]["content"] = "trimmed"
        assert b._llm_messages()[1]["content"] == "original"


def test_fit_context_drops_seed_first_and_keeps_pinned_mission():
    with tempfile.TemporaryDirectory() as tmp:
        seed = [{"role": "user" if i % 2 == 0 else "assistant", "content": "x" * 2000}
                for i in range(10)]
        eng = _engine(tmp, seed=seed)
        eng.push_record({"role": "user", "content": "YOUR MISSION: build the well", "pinned": True})
        eng.push_record({"role": "assistant", "content": "on it"})
        messages = eng._llm_messages(context_tokens=3000)
        texts = [str(m.get("content", "")) for m in messages]
        assert any("YOUR MISSION" in t for t in texts)   # pinned survives
        assert sum("x" * 100 in t for t in texts) < 10   # seed trimmed from the front
        assert all("_pinned" not in m for m in messages)  # marker never on the wire


def test_fork_messages_is_projection_minus_system():
    with tempfile.TemporaryDirectory() as tmp:
        eng = _engine(tmp)
        eng.push_record({"role": "user", "content": "hello"})
        eng.push_record({"role": "assistant", "content": "hi"})
        fork = eng.fork_messages()
        assert [m["role"] for m in fork] == ["user", "assistant"]


class _OneShotLlm(LlmClient):
    def __init__(self):
        self.requests = []

    async def stream(self, request):
        self.requests.append(request)
        yield LlmChunk(content="done — proof of work: built it")


def _task(tid="t1"):
    return WorkerTask(id=tid, objective_id="obj-0", instruction="build the well",
                      goal="a village", acceptance="a well exists")


def _spawn_worker(tmp, handoff, seed):
    llm = _OneShotLlm()
    runner = ChildSessionRunner(
        registry=ToolRegistry([]), make_llm=lambda: llm, model="m", emit=_noop,
        system_prompt="SYS", media_factory=lambda aid: MediaLibrary(os.path.join(tmp, aid.replace(":", "_"))),
        parent_session_id="s", handoff=handoff, seed=seed)
    result = asyncio.run(runner(_task()))
    engine = runner._live["s:w:t1"]["engine"]
    return result, engine, llm


def test_full_fork_spawn_shares_system_and_pins_mission_as_user():
    with tempfile.TemporaryDirectory() as tmp:
        _, eng1, llm1 = _spawn_worker(tmp, HANDOFF_FULL, lambda: _SEED)
        _, eng2, _ = _spawn_worker(tmp, HANDOFF_FULL, lambda: _SEED)
        # Byte-identical prefix across workers: same system, same seed.
        assert eng1._system_prompt == eng2._system_prompt
        assert eng1._system_prompt.endswith(_WORKER_FORK_PREAMBLE)
        assert "build the well" not in eng1._system_prompt     # mission NOT in system
        assert eng1._seed_messages[0]["content"] == "please build a fantasy village"
        # Mission rides as the first (pinned) user message after the seed.
        first = eng1.records[0]
        assert first["role"] == "user" and first.get("pinned") is True
        assert "build the well" in first["content"]
        wire = llm1.requests[0]["messages"]
        assert [m["role"] for m in wire[:3]] == ["system", "user", "assistant"]
        assert "[Context handoff]" in wire[3]["content"]   # roster after the seed
        assert "build the well" in wire[4]["content"]      # mission last


def test_non_full_handoff_keeps_mission_in_system():
    with tempfile.TemporaryDirectory() as tmp:
        _, eng, _ = _spawn_worker(tmp, "handoff", lambda: _SEED)
        assert "build the well" in eng._system_prompt
        assert eng._seed_messages == []
        assert not eng.records[0].get("pinned")


def test_full_fork_falls_back_unseeded_when_seed_fails():
    def boom():
        raise RuntimeError("no parent")
    with tempfile.TemporaryDirectory() as tmp:
        result, eng, _ = _spawn_worker(tmp, HANDOFF_FULL, boom)
        assert result.ok
        assert "build the well" in eng._system_prompt   # classic system pinning


def test_orchestrator_full_fork_skips_context_paste():
    orch = AutonomyOrchestrator(
        planner=None, scheduler=None, evaluator=None, policy=None,
        worker_runner=None, emit=_noop, session_id="s",
        handoff=HANDOFF_FULL, context="USER: make a robot", full_fork=True)
    tasks = [_task()]
    asyncio.run(orch._apply_handoff(tasks, [Objective(id="obj-0", text="village", acceptance="done")]))
    assert "Full orchestrator context" not in tasks[0].context   # the runner forks instead
    assert "village" in tasks[0].context                          # concise brief still rides


def test_swarm_strategy_passes_seed_to_worker_chat():
    from agentcore.swarm import RemoteWorkerStrategy

    captured = {}

    class FakeWorker:
        base_url = "http://localhost:1/v1"

        def start(self, allocator=None):
            pass

        async def wait_ready(self, timeout):
            return True

        def stop(self, timeout=20.0):
            pass

    class Strategy(RemoteWorkerStrategy):
        def _make_worker(self, worker_id, api_port, data_dir):
            return FakeWorker()

        async def _chat(self, base_url, prompt, user, agent_id=None,
                        cancel=None, seed_messages=None):
            captured["seed"] = seed_messages
            captured["prompt"] = prompt
            return "proof"

    with tempfile.TemporaryDirectory() as tmp:
        strategy = Strategy(endpoint="http://llm", model="m", exchange_dir=tmp,
                            seed=lambda: _SEED)
        result = asyncio.run(strategy(_task()))
    assert captured["seed"] == _SEED
    assert "build the well" in captured["prompt"]
    assert result.proof == "proof"


def test_evaluator_seed_prefixes_verdict_call_text_only():
    llm = _OneShotLlm()
    seed = [{"role": "user", "content": [
        {"type": "text", "text": "make it stone"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,xx"}}]}]
    evaluator = StateAwareEvaluator(llm, "m", seed=lambda: seed)
    asyncio.run(evaluator.evaluate(
        [Objective(id="obj-0", text="village", acceptance="done")],
        [WorkerResult(task_id="t1", objective_id="obj-0", proof="built", ok=True)]))
    messages = llm.requests[0]["messages"]
    assert messages[0]["role"] == "system"
    assert messages[1] == {"role": "user", "content": "make it stone\n[image omitted]"}
    assert messages[-1]["role"] == "user" and "OBJECTIVES" in messages[-1]["content"]
