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
