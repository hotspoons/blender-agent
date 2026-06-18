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
        w = swarm.blender_worker(
            worker_id="w0", api_port=12345, bridge_port=23456,
            data_dir=tempfile.mkdtemp(prefix="swarm_t_"),
            endpoint="http://x/v1", model="m")
        self.assertEqual(w.base_url, "http://localhost:12345/v1")


@unittest.skipUnless(_HAS_AGENT_DEPS, "agent dependencies not installed (optional feature)")
class TestRemoteWorkerStrategy(unittest.TestCase):

    def _strategy(self, exchange: str) -> Any:
        swarm = _import_swarm()
        return swarm.BlenderWorkerStrategy(
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
        body = b"BLENDER-v500RENDH" + b"\x00" * 2048  # magic + realistic size
        with open(blend, "wb") as fh:
            fh.write(body)
        dest = strat._collect_artifact(wdir, "component_x")
        self.assertIsNotNone(dest)
        self.assertEqual(os.path.basename(dest), "component_x.blend")
        self.assertTrue(os.path.isfile(dest))
        with open(dest, "rb") as fh:
            self.assertEqual(fh.read(), body)
        # no .blend -> None
        self.assertIsNone(strat._collect_artifact(tempfile.mkdtemp(prefix="empty_"), "c2"))

    def test_collect_blend_rejects_truncated_export(self) -> None:
        exch = tempfile.mkdtemp(prefix="exch_")
        strat = self._strategy(exch)
        wdir = tempfile.mkdtemp(prefix="wdir_")
        # A tiny/garbage .blend (failed export) must NOT be collected.
        with open(os.path.join(wdir, "broken.blend"), "wb") as fh:
            fh.write(b"oops")
        self.assertIsNone(strat._collect_artifact(wdir, "component_bad"))

    def test_list_components_and_gather_noop(self) -> None:
        exch = tempfile.mkdtemp(prefix="exch_")
        strat = self._strategy(exch)
        self.assertEqual(strat.list_artifacts(), [])
        # gather with nothing to merge spawns no worker and returns None.
        self.assertIsNone(asyncio.new_event_loop().run_until_complete(strat.gather()))
        for name in ("component_b", "component_a"):
            with open(os.path.join(exch, name + ".blend"), "wb") as fh:
                fh.write(b"x")
        comps = strat.list_artifacts()
        self.assertEqual([os.path.basename(c) for c in comps],
                         ["component_a.blend", "component_b.blend"])  # sorted


@unittest.skipUnless(_HAS_AGENT_DEPS, "agent dependencies not installed (optional feature)")
class TestSwarmStreaming(unittest.TestCase):
    """The SSE delta -> worker-card event translation (no subprocess)."""

    def _strategy(self, emit) -> Any:
        swarm = _import_swarm()
        return swarm.BlenderWorkerStrategy(
            endpoint="http://x/v1", model="m",
            exchange_dir=tempfile.mkdtemp(prefix="exch_"),
            emit=emit, session_id="s1")

    def test_agent_id_mirrors_orchestrator(self) -> None:
        strat = self._strategy(None)
        self.assertEqual(strat._agent_id("task-0-0"), "s1:w:task-0-0")

    def test_stream_delta_emits_token_toolcall_media(self) -> None:
        events = []

        async def emit(ev):
            events.append(ev)

        strat = self._strategy(emit)
        loop = asyncio.new_event_loop()
        parts: list = []
        # content token
        loop.run_until_complete(strat._stream_delta("s1:w:t", {"content": "hello "}, parts))
        # tool call (status maps done->ok)
        loop.run_until_complete(strat._stream_delta("s1:w:t", {"blender_tool_calls": [
            {"call_id": "c1", "name": "media_io", "args_json": "{}", "status": "done", "summary": "ok"}]}, parts))
        # media (inline data url)
        loop.run_until_complete(strat._stream_delta("s1:w:t", {"blender_media": [
            {"id": "i1", "data_url": "data:image/png;base64,AAAA"}]}, parts))

        kinds = [e["type"] for e in events]
        self.assertEqual(kinds, ["token", "tool_status", "worker_media"])
        # every event is tagged for the worker card
        for e in events:
            self.assertEqual(e["session_id"], "s1:w:t")
            self.assertEqual(e["parent_session_id"], "s1")
            self.assertEqual(e["role"], "worker")
        self.assertEqual(events[1]["state"], "ok")  # done -> ok
        self.assertEqual(events[2]["data_url"], "data:image/png;base64,AAAA")
        self.assertEqual("".join(parts), "hello ")

    def test_stream_delta_strips_data_url_markdown_from_text(self) -> None:
        events = []

        async def emit(ev):
            events.append(ev)

        strat = self._strategy(emit)
        loop = asyncio.new_event_loop()
        parts: list = []
        blob = "Rendered:\n![scene](data:image/png;base64,QUJDQUJD)\nDone."
        loop.run_until_complete(strat._stream_delta("s1:w:t", {"content": blob}, parts))
        token = [e for e in events if e["type"] == "token"][0]
        self.assertNotIn("data:image", token["text"])
        self.assertIn("Rendered:", token["text"])
        self.assertIn("Done.", token["text"])
        # but the raw text is preserved for the proof accumulator
        self.assertIn("data:image", "".join(parts))

    def test_data_url_regex(self) -> None:
        swarm = _import_swarm()
        s = "a ![x](data:image/png;base64,ZZ) b ![y](data:image/jpeg;base64,QQ) c"
        self.assertEqual(swarm._DATA_URL_MD_RE.sub("", s), "a  b  c")


@unittest.skipUnless(_HAS_AGENT_DEPS, "agent dependencies not installed (optional feature)")
class TestSwarmRequirements(unittest.TestCase):
    """Cross-platform preflight: surface swarm/off-screen-GL requirements."""

    def _surface(self) -> Any:
        for path in (os.path.join(_REPO_DIR, "mcp"), os.path.join(_REPO_DIR, "agent")):
            if path not in sys.path:
                sys.path.insert(0, path)
        import importlib
        return importlib.import_module("blagent.blender_surface")

    def test_offscreen_gl_linux_with_and_without_xvfb(self) -> None:
        s = self._surface()
        import unittest.mock as mock
        with mock.patch.object(s.sys, "platform", "linux"):
            with mock.patch.object(s.shutil, "which", return_value="/usr/bin/Xvfb"):
                ok, msg = s.offscreen_gl_support()
                self.assertTrue(ok)
                self.assertIn("Mesa", msg)  # software-GL guidance present
            with mock.patch.object(s.shutil, "which", return_value=None):
                ok, msg = s.offscreen_gl_support()
                self.assertFalse(ok)
                self.assertIn("xvfb", msg.lower())

    def test_offscreen_gl_unsupported_on_mac_and_windows(self) -> None:
        s = self._surface()
        import unittest.mock as mock
        for plat, needle in (("darwin", "macOS"), ("win32", "Windows")):
            with mock.patch.object(s.sys, "platform", plat):
                ok, msg = s.offscreen_gl_support()
                self.assertFalse(ok)
                self.assertIn(needle, msg)
                self.assertIn("RENDER", msg)  # steered to the portable path

    def test_swarm_preflight_blender_presence(self) -> None:
        s = self._surface()
        import unittest.mock as mock
        with mock.patch.object(s.shutil, "which", return_value="/usr/bin/blender"):
            ready, report = s.swarm_preflight()
            self.assertTrue(ready)
            self.assertIn("Blender found", report)
        with mock.patch.object(s.shutil, "which", return_value=None), \
                mock.patch.object(s.os.path, "isfile", return_value=False):
            ready, report = s.swarm_preflight()
            self.assertFalse(ready)
            self.assertIn("Blender NOT found", report)
        # Render is always advertised as the portable capture path.
        self.assertIn("RENDER", report)

    def test_set_swarm_level_includes_preflight(self) -> None:
        for path in (os.path.join(_REPO_DIR, "mcp"), os.path.join(_REPO_DIR, "agent")):
            if path not in sys.path:
                sys.path.insert(0, path)
        from agentcore.runtime import AgentRuntime
        from agentcore.store import AgentStore
        from blagent.swarm import BlenderSwarmProvider
        rt = AgentRuntime(AgentStore(tempfile.mkdtemp(prefix="agentdata_")), [])
        # The swarm surface (and thus its preflight) is the domain's to supply.
        rt.swarm_provider = BlenderSwarmProvider()
        sid = rt.new_session()
        pub = rt.set_autonomy_level(sid, "swarm")
        self.assertIn("swarm_preflight", pub)
        pf = pub["swarm_preflight"]
        assert isinstance(pf, dict)
        self.assertIn("report", pf)
        # The pushed notice carries the requirements so the agent sees them too.
        notice = [r for r in rt.session_records(sid) if r.get("autonomy_notice") == "swarm"]
        self.assertTrue(notice)
        self.assertIn("requirements", str(notice[-1]["content"]).lower())
        # Non-swarm levels don't carry a preflight payload.
        self.assertNotIn("swarm_preflight", rt.set_autonomy_level(sid, "yolo"))


@unittest.skipUnless(_HAS_AGENT_DEPS, "agent dependencies not installed (optional feature)")
class TestWorkerControls(unittest.TestCase):
    """Runtime stop / interrupt / injection routing (in-process vs swarm)."""

    def _runtime(self) -> Any:
        for path in (os.path.join(_REPO_DIR, "mcp"), os.path.join(_REPO_DIR, "agent")):
            if path not in sys.path:
                sys.path.insert(0, path)
        from agentcore.runtime import AgentRuntime
        from agentcore.store import AgentStore
        return AgentRuntime(AgentStore(tempfile.mkdtemp(prefix="agentdata_")), [])

    def test_orchestrator_runs_are_durable_across_drafts(self) -> None:
        # Regression: an orchestrator run's worker history must survive a LATER
        # draft/run in the same session (and a reload). Previously the single
        # per-session view was reset+deleted on the next draft, wiping it.
        import os
        rt = self._runtime()
        sid = rt.new_session()
        rt._get_or_load_session(sid).engine.push_record({
            "role": "user", "content": "objs", "autonomy_run_id": "run-A", "synthetic": True,
            "autonomy_objectives": [{"id": "o0", "text": "do A", "acceptance": "a"}]})
        view = rt._begin_run_view(sid, "run-A")
        emit = rt._persist_emit_for(sid, view, "run-A")
        loop = asyncio.new_event_loop()
        loop.run_until_complete(emit({"type": "agent_spawned", "session_id": sid,
                                      "agent_id": sid + ":w:t0", "role": "worker", "task": "do A"}))
        loop.run_until_complete(emit({"type": "agent_done", "session_id": sid,
                                      "agent_id": sid + ":w:t0", "role": "worker", "ok": True, "proof": "PROOF"}))
        self.assertTrue(os.path.isfile(rt._run_view_path(sid, "run-A")), "run persists to its own file")
        runs = rt.session_autonomy_runs(sid)
        self.assertEqual([r["run_id"] for r in runs], ["run-A"])
        self.assertEqual(runs[0]["view"]["agents"][sid + ":w:t0"]["proof"], "PROOF")

        # The bug trigger: a NEW draft must NOT destroy run-A.
        rt._reset_view(sid)
        self.assertTrue(os.path.isfile(rt._run_view_path(sid, "run-A")),
                        "a later draft must not delete a prior run's durable view")
        runs = rt.session_autonomy_runs(sid)
        self.assertEqual(len(runs), 1, "the prior run still projects after a draft")
        self.assertEqual(runs[0]["view"]["agents"][sid + ":w:t0"]["proof"], "PROOF")

    def test_worker_session_role_hides_self_management_tools(self) -> None:
        # A swarm worker subprocess runs as the "worker" RBAC role, so its
        # sessions must NOT expose set_autonomy / ask_user (a leaf executor
        # has no user and no authority over its own autonomy). This is the fix
        # for the swarm worker that derailed by calling set_autonomy on itself.
        rt = self._runtime()
        full = rt._get_or_load_session(rt.new_session()).engine._registry
        self.assertIsNotNone(full.get("set_autonomy"), "full surface has set_autonomy")
        self.assertIsNotNone(full.get("ask_user"), "full surface has ask_user")

        rt.session_role = "worker"
        weng = rt._get_or_load_session(rt.new_session()).engine._registry
        self.assertIsNone(weng.get("set_autonomy"), "worker must not reach set_autonomy")
        self.assertIsNone(weng.get("ask_user"), "worker must not reach ask_user")
        self.assertIsNotNone(weng.get("skills"), "worker keeps its real work tools")
        self.assertIsNotNone(weng.get("continue_working"), "worker keeps its real work tools")

    def test_inprocess_worker_inject_interrupt_stop(self) -> None:
        rt = self._runtime()

        class FakeEngine:
            def __init__(self):
                self.injected = []
                self.interrupted = False
                self.aborted = False

            def inject(self, content, now=False):
                self.injected.append((content, now))

            def interrupt(self):
                self.interrupted = True

            def abort(self):
                self.aborted = True

        eng = FakeEngine()
        rt._register_worker("s1:w:t0", eng)
        self.assertTrue(rt.worker_supports_injection("s1:w:t0"))
        self.assertTrue(rt.inject_into_worker("s1:w:t0", "do X"))
        self.assertEqual(eng.injected, [("do X", False)])
        self.assertTrue(rt.interrupt_worker("s1:w:t0"))
        self.assertTrue(eng.interrupted)
        self.assertTrue(rt.stop_worker("s1:w:t0"))
        self.assertTrue(eng.aborted)

    def test_swarm_worker_stop_only(self) -> None:
        rt = self._runtime()
        calls = {"stopped": 0}
        rt._register_swarm_worker("s1:w:t1", lambda: calls.__setitem__("stopped", calls["stopped"] + 1))
        # swarm workers run out of process: no injection, but stop works
        self.assertFalse(rt.worker_supports_injection("s1:w:t1"))
        self.assertFalse(rt.inject_into_worker("s1:w:t1", "x"))
        self.assertFalse(rt.interrupt_worker("s1:w:t1"))
        self.assertTrue(rt.stop_worker("s1:w:t1"))
        self.assertEqual(calls["stopped"], 1)

    def test_unknown_worker_returns_false(self) -> None:
        rt = self._runtime()
        self.assertFalse(rt.stop_worker("nope"))
        self.assertFalse(rt.interrupt_worker("nope"))
        self.assertFalse(rt.inject_into_worker("nope", "x"))

    def test_update_objectives_edits_appends_and_interjects(self) -> None:
        from agentcore.autonomy import Objective
        rt = self._runtime()
        # No live run -> None.
        self.assertIsNone(rt.update_objectives("s1", [{"text": "x"}]))

        # Seed a live run + a running in-process worker.
        live = [Objective(id="obj-0", text="torso", acceptance="torso exists", status="met")]
        rt._autonomy_objs["s1"] = live

        class FakeEngine:
            def __init__(self):
                self.injected = []

            def inject(self, content, now=False):
                self.injected.append(content)
        eng = FakeEngine()
        rt._register_worker("s1:w:t0", eng)

        payload = rt.update_objectives("s1", [
            {"text": "torso WITH bevel", "acceptance": "beveled torso exists"},  # edit obj-0
            {"text": "two arms", "acceptance": "two arm objects"},               # append
        ])
        self.assertIsNotNone(payload)
        self.assertEqual(len(live), 2)
        self.assertEqual(live[0].text, "torso WITH bevel")
        self.assertEqual(live[0].status, "unmet")   # edited -> re-verify
        self.assertEqual(live[1].text, "two arms")
        # The running worker was interjected with the new goals.
        self.assertTrue(eng.injected and "two arms" in eng.injected[-1])


@unittest.skipUnless(_HAS_AGENT_DEPS, "agent dependencies not installed (optional feature)")
class TestAutonomyLevel(unittest.TestCase):

    def test_set_level_maps_config_and_pushes_notice(self) -> None:
        for path in (os.path.join(_REPO_DIR, "mcp"), os.path.join(_REPO_DIR, "agent")):
            if path not in sys.path:
                sys.path.insert(0, path)
        from agentcore.runtime import AgentRuntime
        from agentcore.store import AgentStore

        store = AgentStore(tempfile.mkdtemp(prefix="agentdata_"))
        rt = AgentRuntime(store, [])
        sid = rt.new_session()

        pub = rt.set_autonomy_level(sid, "swarm")
        self.assertEqual(pub["autonomy_level"], "swarm")
        self.assertEqual(pub["autonomy_workers"], "swarm")
        self.assertEqual(pub["autonomy"], "auto")

        recs = rt.session_records(sid)
        notice = [r for r in recs if r.get("autonomy_notice") == "swarm"]
        self.assertTrue(notice, "a mode-change notice must be pushed into the session")
        self.assertIn("tool catalog", str(notice[-1]["content"]).lower())

        # "ask" maps to confirm-mutations; in-process workers
        pub = rt.set_autonomy_level(sid, "ask")
        self.assertEqual(pub["autonomy"], "ask")
        self.assertEqual(pub["autonomy_workers"], "in_process")

        # legacy "minimal" is accepted as an alias for "ask"
        pub = rt.set_autonomy_level(sid, "minimal")
        self.assertEqual(pub["autonomy_level"], "ask")

    def test_set_autonomy_tool_over_endpoint(self) -> None:
        for path in (os.path.join(_REPO_DIR, "mcp"), os.path.join(_REPO_DIR, "agent")):
            if path not in sys.path:
                sys.path.insert(0, path)
        from agentcore.runtime import AgentRuntime
        from agentcore.store import AgentStore
        from agentcore.tools import ToolContext, ToolError

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
            worker = swarm.blender_worker(
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
