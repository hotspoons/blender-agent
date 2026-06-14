# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Comprehensive swarm assembly end-to-end: four real worker subprocesses, each
in its own headless Blender, build a distinct component IN PARALLEL — character
A, character B, props, and a scene — and a final gather agent merges every
component .blend into one master scene.

Heavy (4 Blenders + an LLM round-trip each); gated behind SWARM_E2E=1 and a
reachable model. Run directly to watch it, or via unittest:

    SWARM_E2E=1 BLENDER_AGENT_ENDPOINT=http://172.16.10.252:8000/v1 \
        BLENDER_AGENT_MODEL=moonshot/kimi-k2.7-Code \
        python -m unittest tests.e2e_swarm_assembly -v

    # or standalone (prints progress):
    SWARM_E2E=1 BLENDER_AGENT_ENDPOINT=... BLENDER_AGENT_MODEL=... \
        python tests/e2e_swarm_assembly.py
"""

__all__ = ()

import asyncio
import os
import shutil
import sys
import tempfile
import types
import unittest

_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_REPO_DIR, "mcp"), os.path.join(_REPO_DIR, "agent")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# The four components, each built by its own worker in its own Blender. Kept
# to cheap primitive modelling so the workers finish quickly and deterministically.
_TASKS = [
    ("char_a", "Build a simple robot CHARACTER from primitives: a box body, a "
               "sphere head, and two cylinder legs. Name the objects clearly "
               "(e.g. RobotA_body, RobotA_head). Keep it near the world origin."),
    ("char_b", "Build a simple snowman CHARACTER from three stacked spheres of "
               "decreasing size. Name them clearly (e.g. SnowmanB_base, "
               "SnowmanB_mid, SnowmanB_head)."),
    ("props", "Build a few simple PROPS: a cone 'tree', a torus 'tire', and a "
              "cube 'crate'. Name them Prop_tree, Prop_tire, Prop_crate."),
    ("scene", "Build a simple SCENE base: a large flat ground plane named "
              "Scene_ground, and a small cylinder pedestal named Scene_pedestal."),
]


def _make_strategy(exchange_dir):
    from blagent.swarm import RemoteWorkerStrategy
    endpoint = os.environ["BLENDER_AGENT_ENDPOINT"]
    model = os.environ["BLENDER_AGENT_MODEL"]
    return RemoteWorkerStrategy(
        endpoint=endpoint, model=model, exchange_dir=exchange_dir,
        api_key=os.environ.get("BLENDER_AGENT_API_KEY", ""),
        session_id="assembly")


async def _run(strategy):
    from blagent.autonomy import ParallelScheduler

    tasks = [types.SimpleNamespace(id=tid, objective_id=tid, instruction=instr, context="")
             for tid, instr in _TASKS]
    results = await ParallelScheduler(max_concurrency=4).run(tasks, strategy)
    components = strategy.list_components()
    master = await strategy.gather()
    return results, components, master


def _read_master_objects(master_path):
    """Read object names from the merged master .blend via headless Blender."""
    import subprocess
    expr = (
        "import bpy,sys;"
        "[print('OBJ:'+o.name) for o in bpy.data.objects]"
    )
    out = subprocess.run(
        ["blender", "-b", master_path, "--python-expr", expr],
        capture_output=True, text=True, timeout=120, check=False).stdout
    return [ln[4:] for ln in out.splitlines() if ln.startswith("OBJ:")]


@unittest.skipUnless(
    os.environ.get("SWARM_E2E") == "1" and shutil.which("blender")
    and os.environ.get("BLENDER_AGENT_ENDPOINT") and os.environ.get("BLENDER_AGENT_MODEL"),
    "comprehensive swarm assembly (set SWARM_E2E=1 + BLENDER_AGENT_ENDPOINT/MODEL, needs Blender)")
class TestSwarmAssembly(unittest.TestCase):

    def test_four_workers_build_and_gather_into_master(self) -> None:
        exchange = tempfile.mkdtemp(prefix="assembly_")
        strategy = _make_strategy(exchange)
        results, components, master = asyncio.new_event_loop().run_until_complete(_run(strategy))

        ok = [r for r in results if r and r.ok]
        self.assertGreaterEqual(len(ok), 3, "at least 3/4 workers should produce a component")
        self.assertGreaterEqual(len(components), 3, "components written to the exchange dir")
        self.assertIsNotNone(master, "gather must produce a master .blend")
        objs = _read_master_objects(master)
        self.assertGreaterEqual(
            len(objs), 6, "master should contain the merged objects from several components")


def _main() -> int:
    if os.environ.get("SWARM_E2E") != "1":
        print("set SWARM_E2E=1 (+ BLENDER_AGENT_ENDPOINT/MODEL) to run", flush=True)
        return 2
    exchange = tempfile.mkdtemp(prefix="assembly_")
    print("exchange dir:", exchange, flush=True)
    strategy = _make_strategy(exchange)
    results, components, master = asyncio.new_event_loop().run_until_complete(_run(strategy))
    for r in results:
        if r:
            print("  worker {}: ok={} artifacts={}".format(
                r.task_id, r.ok, getattr(r, "artifacts", None)), flush=True)
    print("components:", [os.path.basename(c) for c in components], flush=True)
    print("master:", master, flush=True)
    if master:
        objs = _read_master_objects(master)
        print("MASTER OBJECTS ({}): {}".format(len(objs), objs), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
