# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Tests for the swarm worker lifecycle (``agent/blagent/swarm.py``).

``PortAllocator`` is unit-tested (fast, deterministic). The real-subprocess
worker spawn is heavy (launches Blender + an agent + an LLM round-trip) and
needs Blender plus a reachable remote LLM, so it is gated behind
``SWARM_E2E=1``; it mirrors the manual smoke check.

    python -m unittest tests.test_swarm -v
    SWARM_E2E=1 BLENDER_AGENT_ENDPOINT=http://172.16.10.252:8000/v1 \
        BLENDER_AGENT_MODEL=moonshot/kimi-k2.7-Code python -m unittest \
        tests.test_swarm.TestWorkerSpawn -v
"""

__all__ = ()

import asyncio
import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
from typing import Any

_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_HAS_AGENT_DEPS = all(
    importlib.util.find_spec(mod) is not None
    for mod in ("starlette", "uvicorn", "httpx", "mcp", "blmcp")
)


def _import_swarm() -> Any:
    for path in (os.path.join(_REPO_DIR, "mcp"), os.path.join(_REPO_DIR, "agent")):
        if path not in sys.path:
            sys.path.insert(0, path)
    import importlib
    return importlib.import_module("blagent.swarm")


@unittest.skipUnless(_HAS_AGENT_DEPS, "agent dependencies not installed (optional feature)")
class TestPortAllocator(unittest.TestCase):

    def test_allocates_distinct_ports(self) -> None:
        swarm = _import_swarm()
        alloc = swarm.PortAllocator()
        try:
            ports = [alloc.allocate() for _ in range(25)]
            self.assertEqual(len(set(ports)), 25, "ports must be distinct")
            self.assertTrue(all(1024 < p < 65536 for p in ports))
        finally:
            alloc.release_all()

    def test_release_is_idempotent(self) -> None:
        swarm = _import_swarm()
        alloc = swarm.PortAllocator()
        port = alloc.allocate()
        alloc.release(port)
        alloc.release(port)  # no error on double-release
        alloc.release(99999)  # no error on unknown port

    def test_base_url_shape(self) -> None:
        swarm = _import_swarm()
        w = swarm.WorkerInstance(
            worker_id="w0", api_port=12345, bridge_port=23456,
            data_dir=tempfile.mkdtemp(prefix="swarm_t_"),
            endpoint="http://x/v1", model="m")
        self.assertEqual(w.base_url, "http://localhost:12345/v1")


@unittest.skipUnless(_HAS_AGENT_DEPS, "agent dependencies not installed (optional feature)")
class TestRemoteWorkerStrategy(unittest.TestCase):

    def _strategy(self, exchange: str) -> Any:
        swarm = _import_swarm()
        return swarm.RemoteWorkerStrategy(
            endpoint="http://x/v1", model="m", exchange_dir=exchange)

    def test_build_prompt_demands_blend_export_and_proof(self) -> None:
        import types
        exch = tempfile.mkdtemp(prefix="exch_")
        strat = self._strategy(exch)
        task = types.SimpleNamespace(id="char_a", objective_id="o1",
                                     instruction="model a knight", context="")
        prompt = strat._build_prompt(task, "component_char_a")
        self.assertIn("model a knight", prompt)
        self.assertIn("component_char_a.blend", prompt)
        self.assertIn("PROOF OF WORK", prompt)
        # context is prepended only when present
        task.context = "objectives: knight + dragon"
        self.assertIn("Orchestrator context", strat._build_prompt(task, "component_char_a"))

    def test_collect_blend_copies_newest_to_exchange(self) -> None:
        exch = tempfile.mkdtemp(prefix="exch_")
        strat = self._strategy(exch)
        wdir = tempfile.mkdtemp(prefix="wdir_")
        nested = os.path.join(wdir, "sessions", "s1", "media")
        os.makedirs(nested, exist_ok=True)
        blend = os.path.join(nested, "scene.blend")
        with open(blend, "wb") as fh:
            fh.write(b"BLENDER-fake")
        dest = strat._collect_blend(wdir, "component_x")
        self.assertIsNotNone(dest)
        self.assertEqual(os.path.basename(dest), "component_x.blend")
        self.assertTrue(os.path.isfile(dest))
        with open(dest, "rb") as fh:
            self.assertEqual(fh.read(), b"BLENDER-fake")
        # no .blend -> None
        self.assertIsNone(strat._collect_blend(tempfile.mkdtemp(prefix="empty_"), "c2"))

    def test_list_components_and_gather_noop(self) -> None:
        exch = tempfile.mkdtemp(prefix="exch_")
        strat = self._strategy(exch)
        self.assertEqual(strat.list_components(), [])
        # gather with nothing to merge spawns no worker and returns None.
        self.assertIsNone(asyncio.new_event_loop().run_until_complete(strat.gather()))
        for name in ("component_b", "component_a"):
            with open(os.path.join(exch, name + ".blend"), "wb") as fh:
                fh.write(b"x")
        comps = strat.list_components()
        self.assertEqual([os.path.basename(c) for c in comps],
                         ["component_a.blend", "component_b.blend"])  # sorted


@unittest.skipUnless(_HAS_AGENT_DEPS, "agent dependencies not installed (optional feature)")
class TestAutonomyLevel(unittest.TestCase):

    def test_set_level_maps_config_and_pushes_notice(self) -> None:
        for path in (os.path.join(_REPO_DIR, "mcp"), os.path.join(_REPO_DIR, "agent")):
            if path not in sys.path:
                sys.path.insert(0, path)
        from blagent.runtime import AgentRuntime
        from blagent.store import AgentStore

        store = AgentStore(tempfile.mkdtemp(prefix="agentdata_"))
        rt = AgentRuntime(store, [])
        sid = rt.new_session()

        pub = rt.set_autonomy_level(sid, "swarm")
        self.assertEqual(pub["autonomy_level"], "swarm")
        self.assertEqual(pub["autonomy_workers"], "swarm")
        self.assertTrue(pub["autonomy_mode"])
        self.assertEqual(pub["autonomy"], "auto")

        recs = rt.session_records(sid)
        notice = [r for r in recs if r.get("autonomy_notice") == "swarm"]
        self.assertTrue(notice, "a mode-change notice must be pushed into the session")
        self.assertIn("tool catalog", str(notice[-1]["content"]).lower())

        # minimal maps to confirm-mutations
        pub = rt.set_autonomy_level(sid, "minimal")
        self.assertEqual(pub["autonomy"], "ask")
        self.assertFalse(pub["autonomy_mode"])

    def test_set_autonomy_tool_over_endpoint(self) -> None:
        for path in (os.path.join(_REPO_DIR, "mcp"), os.path.join(_REPO_DIR, "agent")):
            if path not in sys.path:
                sys.path.insert(0, path)
        from blagent.runtime import AgentRuntime
        from blagent.store import AgentStore
        from blagent.tools import ToolContext, ToolError

        rt = AgentRuntime(AgentStore(tempfile.mkdtemp(prefix="agentdata_")), [])
        sid = rt.new_session()
        tool = rt.registry.get("set_autonomy")
        self.assertIsNotNone(tool, "the agent must expose a set_autonomy tool")
        assert tool is not None
        ctx = ToolContext(media=rt._get_or_load_session(sid).media, session_id=sid)

        res = asyncio.new_event_loop().run_until_complete(tool.call(ctx, {"level": "swarm"}))
        self.assertIn("swarm", res.summary)
        self.assertEqual(rt.store.config.autonomy_level, "swarm")
        self.assertEqual(rt.store.config.autonomy_workers, "swarm")

        with self.assertRaises(ToolError):
            asyncio.new_event_loop().run_until_complete(tool.call(ctx, {"level": "bogus"}))


@unittest.skipUnless(
    os.environ.get("SWARM_E2E") == "1" and shutil.which("blender") and _HAS_AGENT_DEPS,
    "real worker spawn (set SWARM_E2E=1, needs Blender + a reachable remote LLM)")
class TestWorkerSpawn(unittest.TestCase):

    def test_spawn_worker_serves_models(self) -> None:
        swarm = _import_swarm()
        endpoint = os.environ.get("BLENDER_AGENT_ENDPOINT", "http://172.16.10.252:8000/v1")
        model = os.environ.get("BLENDER_AGENT_MODEL", "moonshot/kimi-k2.7-Code")

        async def run() -> bool:
            alloc = swarm.PortAllocator()
            api, bridge = alloc.allocate(), alloc.allocate()
            worker = swarm.WorkerInstance(
                worker_id="w0", api_port=api, bridge_port=bridge,
                data_dir=tempfile.mkdtemp(prefix="swarm_e2e_"),
                endpoint=endpoint, model=model)
            worker.start(allocator=alloc)
            try:
                ready = await worker.wait_ready(timeout=180)
                self.assertTrue(ready, "worker did not become ready:\n" + worker.tail_log())
                return ready
            finally:
                worker.stop()

        self.assertTrue(asyncio.new_event_loop().run_until_complete(run()))


if __name__ == "__main__":
    unittest.main()
