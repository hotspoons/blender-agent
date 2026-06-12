# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Tests for the optional web agent (``agent/blagent``).

Does not require Blender (a fake bridge socket stands in for the
add-on). Skipped entirely when the agent package or its dependencies
are not installed. Run with::

    python -m unittest tests.test_agent -v
"""

__all__ = ()

import asyncio
import importlib
import importlib.util
import json
import os
import socket
import sys
import tempfile
import threading
import unittest

from typing import Any

_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_HAS_AGENT_DEPS = all(
    importlib.util.find_spec(mod) is not None
    for mod in ("starlette", "uvicorn", "httpx", "mcp", "blmcp")
)


def _import_blagent() -> Any:
    for path in (os.path.join(_REPO_DIR, "mcp"), os.path.join(_REPO_DIR, "agent")):
        if path not in sys.path:
            sys.path.insert(0, path)
    return importlib.import_module("blagent")


class _FakeBridge:
    """
    Stand-in for the add-on's TCP bridge: answers every request with a
    fixed payload, on an auto-assigned port.
    """

    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("localhost", 0))
        self._srv.listen(5)
        self.port = self._srv.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _addr = self._srv.accept()
            except OSError:
                return
            buf = bytearray()
            while b"\0" not in buf:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buf.extend(chunk)
            conn.sendall((json.dumps(self._payload) + "\0").encode("utf-8"))
            conn.close()

    def close(self) -> None:
        self._srv.close()


@unittest.skipUnless(_HAS_AGENT_DEPS, "agent dependencies not installed (optional feature)")
class TestSkillsStore(unittest.TestCase):
    """
    Skills seeding, retrieval, and full-text search.
    """

    def setUp(self) -> None:
        _import_blagent()
        from blagent.store import AgentStore

        self._tmp = tempfile.TemporaryDirectory()
        self.store = AgentStore(data_dir=self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_seeded_skills_present(self) -> None:
        """
        Checks that the bundled example skills are seeded on first run.
        """
        names = {s.name for s in self.store.list_skills()}
        for expected in (
            "make-manifold",
            "fillets-and-bevels",
            "boolean-modeling",
            "texturing-basics",
            "lighting-setups",
        ):
            self.assertIn(expected, names)

    def test_search_ranks_relevant_skill_first(self) -> None:
        """
        Checks that searching for fillet terminology finds the bevel skill.
        """
        from blagent.store import search_skills

        hits = search_skills(self.store.list_skills(), "rounded corners fillet")
        self.assertTrue(hits)
        self.assertEqual(hits[0][0].name, "fillets-and-bevels")

    def test_get_and_save_roundtrip(self) -> None:
        """
        Checks saving a new skill makes it retrievable and searchable.
        """
        self.store.save_skill("test-skill", "# Test\n\nA recipe about gizmos.\n")
        skill = self.store.get_skill("test-skill")
        assert skill is not None
        self.assertIn("gizmos", skill.body)


@unittest.skipUnless(_HAS_AGENT_DEPS, "agent dependencies not installed (optional feature)")
class TestLocalLlmBridge(unittest.TestCase):
    """
    Request/response correlation on the local-model reverse tunnel.
    """

    def test_streaming_roundtrip(self) -> None:
        """
        Checks chunk/done correlation between a fake browser and the bridge.
        """
        _import_blagent()
        from blagent.local_llm import LocalLlmBridge

        class FakeWs:
            def __init__(self, bridge: Any) -> None:
                self.bridge = bridge

            async def send_json(self, data: Any) -> None:
                rid = data["id"]
                await self.bridge.handle_message({
                    "id": rid, "type": "chunk",
                    "choices": [{"index": 0, "delta": {"content": "hi"}, "finish_reason": None}],
                })
                await self.bridge.handle_message({"id": rid, "type": "done"})

        async def run() -> list[dict[str, Any]]:
            bridge = LocalLlmBridge()
            await bridge.connect(FakeWs(bridge))
            await bridge.handle_message({"type": "model_info", "model_id": "m", "status": "ready"})
            self.assertTrue(bridge.is_ready())
            chunks = []
            async for chunk in bridge.send_streaming_request({"messages": []}):
                chunks.append(chunk)
            return chunks

        chunks = asyncio.run(run())
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["choices"][0]["delta"]["content"], "hi")

    def test_disconnect_fails_pending_streams(self) -> None:
        """
        Checks that a browser disconnect terminates in-flight streams.
        """
        _import_blagent()
        from blagent.local_llm import LocalLlmBridge

        class SilentWs:
            async def send_json(self, data: Any) -> None:
                pass

        async def run() -> int:
            bridge = LocalLlmBridge()
            await bridge.connect(SilentWs())
            bridge.status = "ready"

            async def consume() -> int:
                count = 0
                async for _chunk in bridge.send_streaming_request({"messages": []}):
                    count += 1
                return count

            task = asyncio.create_task(consume())
            await asyncio.sleep(0.05)
            await bridge.disconnect()
            return await task

        self.assertEqual(asyncio.run(run()), 0)


@unittest.skipUnless(_HAS_AGENT_DEPS, "agent dependencies not installed (optional feature)")
class TestPortAutoAssign(unittest.TestCase):
    """
    Port auto-assignment for multiple Blender instances.
    """

    def test_pick_free_port_walks_past_taken_port(self) -> None:
        """
        Checks that a taken preferred port resolves to the next free one.
        """
        blagent = _import_blagent()
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        blocker.bind(("127.0.0.1", 0))
        taken = blocker.getsockname()[1]
        try:
            picked = blagent.pick_free_port("127.0.0.1", taken)
            self.assertGreater(picked, taken)
            self.assertLessEqual(picked, taken + 20)
        finally:
            blocker.close()


class TestBlenderSurface(unittest.TestCase):
    """
    Standalone launch: process-tree recursion guard, the attach/spawn
    decision, argv, and a real spawn/teardown against a fake Blender.
    The module is dependency-free, so this runs without agent deps.
    """

    def _surface(self) -> Any:
        if os.path.join(_REPO_DIR, "agent") not in sys.path:
            sys.path.insert(0, os.path.join(_REPO_DIR, "agent"))
        return importlib.import_module("blagent.blender_surface")

    def test_decision_matrix(self) -> None:
        s = self._surface()
        self.assertEqual(s.surface_decision(bridge_up=True, is_blender_child=False, want_spawn=True), "attach")
        # Guard beats spawn: a Blender child never spawns Blender.
        self.assertEqual(s.surface_decision(bridge_up=False, is_blender_child=True, want_spawn=True), "guarded")
        self.assertEqual(s.surface_decision(bridge_up=False, is_blender_child=False, want_spawn=True), "spawn")
        self.assertEqual(s.surface_decision(bridge_up=False, is_blender_child=False, want_spawn=False), "none")

    def test_blender_name_matcher(self) -> None:
        s = self._surface()
        for ok in ("blender", "Blender", "blender.exe", "blender-4.2", "/usr/bin/blender", "blender4.5"):
            self.assertTrue(s._name_is_blender(ok), ok)  # pylint: disable=protected-access
        for no in ("blender-agent", "blender_mcp", "blender-mcp", "blenderkit", "python", ""):
            self.assertFalse(s._name_is_blender(no), no)  # pylint: disable=protected-access

    def test_ancestor_walk_finds_blender(self) -> None:
        s = self._surface()
        me = os.getpid()
        # Fake tree: me -> 100 (shell) -> 200 (blender) -> 1 (init).
        tree = {me: (100, "blender-agent"), 100: (200, "bash"), 200: (1, "blender"), 1: (0, "init")}
        found = s.blender_ancestor_pid(_reader=lambda pid: tree.get(pid))
        self.assertEqual(found, 200)

    def test_ancestor_walk_no_blender(self) -> None:
        s = self._surface()
        me = os.getpid()
        tree = {me: (100, "blender-agent"), 100: (200, "bash"), 200: (1, "tmux"), 1: (0, "init")}
        self.assertIsNone(s.blender_ancestor_pid(_reader=lambda pid: tree.get(pid)))

    def test_env_marker_is_authoritative(self) -> None:
        s = self._surface()
        # No Blender in the (empty) tree, but the add-on marker is set.
        self.assertTrue(s.spawned_by_blender(
            env={"BLENDER_AGENT_SPAWNED_BY_BLENDER": "1"},
            _reader=lambda pid: None))
        self.assertFalse(s.spawned_by_blender(env={}, _reader=lambda pid: None))

    def test_argv_shape(self) -> None:
        s = self._surface()
        argv = s.build_blender_argv("blender", "localhost", 9876, "/tmp/x.blend", True)
        self.assertEqual(argv[:2], ["blender", "--background"])
        self.assertIn("/tmp/x.blend", argv)
        self.assertIn("--online-mode", argv)
        self.assertEqual(argv[-6:], ["--command", "blender_mcp", "--host", "localhost", "--port", "9876"])
        # No blend file and no online mode -> both omitted.
        bare = s.build_blender_argv("blender", "h", 1, None, False)
        self.assertNotIn("--online-mode", bare)
        self.assertEqual([a for a in bare if a.endswith(".blend")], [])

    def test_bridge_reachable(self) -> None:
        s = self._surface()
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        try:
            self.assertTrue(s.bridge_reachable("127.0.0.1", port))
        finally:
            srv.close()
        # Nothing listening on a just-freed port.
        self.assertFalse(s.bridge_reachable("127.0.0.1", port, timeout=0.2))

    def test_spawn_and_teardown_against_fake_blender(self) -> None:
        """
        BlenderSurface spawns a process and waits for its bridge; a fake
        'blender' opens the requested --port. stop() terminates it.
        """
        s = self._surface()
        script = os.path.join(tempfile.mkdtemp(prefix="fakeblender-"), "blender")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(
                "#!/usr/bin/env python3\n"
                "import sys, socket, time\n"
                "argv = sys.argv[1:]\n"
                "port = int(argv[argv.index('--port') + 1])\n"
                "srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
                "srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
                "srv.bind(('127.0.0.1', port)); srv.listen(5)\n"
                "time.sleep(30)\n"
            )
        os.chmod(script, 0o755)
        free = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        free.bind(("127.0.0.1", 0))
        port = free.getsockname()[1]
        free.close()
        surface = s.BlenderSurface(host="127.0.0.1", port=port, blender_path=script)
        surface.start(timeout=15.0)
        try:
            self.assertTrue(s.bridge_reachable("127.0.0.1", port))
            self.assertIsNotNone(surface.proc)
            self.assertIsNone(surface.proc.poll())  # still running
        finally:
            surface.stop()
        self.assertIsNotNone(surface.proc.poll())  # terminated

    def test_spawn_raises_when_process_exits_early(self) -> None:
        s = self._surface()
        script = os.path.join(tempfile.mkdtemp(prefix="fakeblender-"), "blender")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write("#!/usr/bin/env python3\nimport sys\nsys.exit(3)\n")
        os.chmod(script, 0o755)
        surface = s.BlenderSurface(host="127.0.0.1", port=59999, blender_path=script)
        with self.assertRaises(RuntimeError) as cm:
            surface.start(timeout=5.0)
        self.assertIn("exited", str(cm.exception))


@unittest.skipUnless(_HAS_AGENT_DEPS, "agent dependencies not installed (optional feature)")
class TestAgentTurn(unittest.TestCase):
    """
    A full agent turn: scripted LLM drives a real blmcp tool through a
    fake bridge, over the real control-plane WebSocket.
    """

    def test_turn_with_tool_call(self) -> None:
        """
        Checks token streaming, tool dispatch, result feedback, and the
        event sequence over /ws.
        """
        _import_blagent()
        from blagent.app import create_app
        from blagent.blender_tools import build_blender_registry
        from blagent.llm import LlmChunk, LlmClient
        from blagent.runtime import AgentRuntime
        from blagent.store import AgentStore

        from starlette.testclient import TestClient

        bridge = _FakeBridge({"status": "ok", "result": {"objects": ["Cube"]}})
        os.environ["BLENDER_MCP_PORT"] = str(bridge.port)

        class FakeLlm(LlmClient):
            def __init__(self) -> None:
                self.round = 0

            async def stream(self, request: dict[str, Any]) -> Any:
                self.round += 1
                if self.round == 1:
                    yield LlmChunk(content="Checking. ")
                    yield LlmChunk(tool_calls=[{
                        "index": 0, "id": "call_1",
                        "function": {
                            "name": "execute_blender_code",
                            "arguments": json.dumps({"code": "result = {}"}),
                        },
                    }])
                else:
                    tool_messages = [m for m in request["messages"] if m["role"] == "tool"]
                    assert tool_messages and "Cube" in tool_messages[-1]["content"]
                    yield LlmChunk(content="You have a Cube.")

        async def build() -> AgentRuntime:
            _mcp, tools = await build_blender_registry()
            store = AgentStore(data_dir=tempfile.mkdtemp(prefix="blagent-test-"))
            store.config.autonomy = "auto"
            runtime = AgentRuntime(store, tools)
            runtime._make_llm = lambda: FakeLlm()  # type: ignore[method-assign]
            runtime._model_name = lambda: "fake"  # type: ignore[method-assign]
            return runtime

        runtime = asyncio.new_event_loop().run_until_complete(build())
        app = create_app(runtime)
        events: list[str] = []
        with TestClient(app).websocket_connect("/ws") as ws:
            ws.receive_json()  # hello
            ws.send_json({"type": "chat", "session_id": "", "content": "what's in my scene?"})
            final = ""
            while True:
                event = ws.receive_json()
                events.append(event["type"])
                if event["type"] == "assistant_done":
                    final = event["content"] or final
                if event["type"] == "error":
                    self.fail(event["message"])
                if event["type"] == "turn_done":
                    break
        bridge.close()
        self.assertIn("token", events)
        self.assertIn("tool_status", events)
        self.assertEqual(final, "You have a Cube.")


@unittest.skipUnless(_HAS_AGENT_DEPS, "agent dependencies not installed (optional feature)")
class TestTurnBudgetExhaustion(unittest.TestCase):
    """
    Production bug (2026-06-12): when the round budget ran out, the
    assistant record kept its tool calls but they were never executed
    NOR recorded — a silent "dead" tool call in the UI and a dangling
    call in the LLM transcript. They must be recorded as skipped, with
    a visible error-state tool_status.
    """

    def test_unrun_calls_get_skipped_records(self) -> None:
        _import_blagent()
        from blagent.engine import AgentEngine
        from blagent.llm import LlmChunk, LlmClient
        from blagent.tools import ToolRegistry

        events: list[dict[str, Any]] = []

        async def emit(event: dict[str, Any]) -> None:
            events.append(event)

        engine = AgentEngine(
            registry=ToolRegistry([]),
            media=None,
            system_prompt="",
            emit=emit,
            append_record=lambda record: None,
        )

        class EndlessCaller(LlmClient):
            def __init__(self) -> None:
                self.round = 0

            async def stream(self, request: dict[str, Any]) -> Any:
                self.round += 1
                yield LlmChunk(content="round {:d}".format(self.round))
                yield LlmChunk(tool_calls=[{
                    "index": 0, "id": "call_{:d}".format(self.round),
                    "function": {"name": "some_tool", "arguments": "{}"},
                }])

        asyncio.new_event_loop().run_until_complete(engine.run_turn(
            "s1", "go", EndlessCaller(), "m", autonomy="auto", max_rounds=1,
            budget_review=False))

        # The final round's call is recorded as skipped, not lost.
        tool_records = [r for r in engine.records if r.get("role") == "tool"]
        last = tool_records[-1]
        parsed = json.loads(str(last["content"]))
        self.assertEqual(parsed["status"], "skipped")
        self.assertIn("round budget", parsed["message"])

        # And it surfaced visibly: an error-state tool_status plus the
        # turn-level error, before turn_done.
        statuses = [e for e in events if e["type"] == "tool_status" and e["state"] == "error"]
        self.assertTrue(any("round budget" in str(e.get("summary", "")) for e in statuses))
        self.assertTrue(any(e["type"] == "error" for e in events))
        self.assertEqual(events[-1]["type"], "turn_done")


@unittest.skipUnless(_HAS_AGENT_DEPS, "agent dependencies not installed (optional feature)")
class TestUnknownToolSuggestion(unittest.TestCase):
    """
    Production slip (2026-06-12): the model called "media" instead of
    "media_io" and burned a round on a bare "unknown tool" error. Close
    names get a did-you-mean.
    """

    def test_close_match_suggested(self) -> None:
        _import_blagent()
        from blagent.engine import AgentEngine
        from blagent.llm import LlmChunk, LlmClient
        from blagent.tools import Tool, ToolRegistry

        class Stub(Tool):
            def __init__(self, name: str) -> None:
                self.name = name
                self.description = ""

            def input_schema(self):
                return {"type": "object", "properties": {}}

        events: list[dict[str, Any]] = []

        async def emit(event: dict[str, Any]) -> None:
            events.append(event)

        engine = AgentEngine(
            registry=ToolRegistry([Stub("media_io"), Stub("rig")]),
            media=None,
            system_prompt="",
            emit=emit,
            append_record=lambda record: None,
        )

        class SlipsOnce(LlmClient):
            def __init__(self) -> None:
                self.round = 0

            async def stream(self, request: dict[str, Any]) -> Any:
                self.round += 1
                if self.round == 1:
                    yield LlmChunk(tool_calls=[{
                        "index": 0, "id": "c1",
                        "function": {"name": "media", "arguments": "{}"},
                    }])
                else:
                    yield LlmChunk(content="ok")

        asyncio.new_event_loop().run_until_complete(engine.run_turn(
            "s1", "go", SlipsOnce(), "m", autonomy="auto", max_rounds=4))

        record = next(r for r in engine.records if r.get("role") == "tool")
        self.assertIn("did you mean media_io", str(record["content"]))


@unittest.skipUnless(_HAS_AGENT_DEPS, "agent dependencies not installed (optional feature)")
class TestBudgetReview(unittest.TestCase):
    """
    The orchestrator checkpoint: at budget exhaustion the worker
    self-reports out of band, a context-blind reviewer judges it via
    its two tools, and the verdict either replenishes rounds (the
    pending calls then RUN) or stops the turn.
    """

    def _engine(self, events: list[dict[str, Any]]) -> Any:
        _import_blagent()
        from blagent.engine import AgentEngine
        from blagent.tools import ToolRegistry

        async def emit(event: dict[str, Any]) -> None:
            events.append(event)

        return AgentEngine(
            registry=ToolRegistry([]),
            media=None,
            system_prompt="",
            emit=emit,
            append_record=lambda record: None,
        )

    def _llm(self, verdict_json: str) -> Any:
        from blagent.llm import LlmChunk, LlmClient

        class Orchestrated(LlmClient):
            """Dispatches by request shape: reviewer / self-report / worker."""

            def __init__(self) -> None:
                self.worker_rounds = 0
                self.reviewer_called = False

            async def stream(self, request: dict[str, Any]) -> Any:
                messages = request["messages"]
                system = str(messages[0].get("content", "")) if messages else ""
                last = str(messages[-1].get("content", "")) if messages else ""
                if "strict but fair reviewer" in system:
                    self.reviewer_called = True
                    yield LlmChunk(content=verdict_json)
                    return
                if "Budget checkpoint" in last:
                    yield LlmChunk(content="Objective: rig the cube. Evidence: "
                                           "DEF-Cube bone exists per tool output. "
                                           "One more round finishes the IK.")
                    return
                self.worker_rounds += 1
                if self.worker_rounds <= 2:
                    yield LlmChunk(content="working {:d}. ".format(self.worker_rounds))
                    yield LlmChunk(tool_calls=[{
                        "index": 0, "id": "call_{:d}".format(self.worker_rounds),
                        "function": {"name": "some_tool", "arguments": "{}"},
                    }])
                else:
                    yield LlmChunk(content="All done.")

        return Orchestrated()

    def test_grant_resumes_pending_calls(self) -> None:
        events: list[dict[str, Any]] = []
        engine = self._engine(events)
        llm = self._llm('{"verdict": "continue", "grant_rounds": 2, '
                        '"summary": "Evidence is concrete; one round remains."}')
        asyncio.new_event_loop().run_until_complete(engine.run_turn(
            "s1", "rig the cube", llm, "m", autonomy="auto", max_rounds=1))

        self.assertTrue(llm.reviewer_called)
        review = next(r for r in engine.records if r.get("role") == "review")
        self.assertEqual(review["verdict"], "continue")
        # The requested 2 rounds clamp to max_grant (= max_rounds = 1).
        self.assertEqual(review["granted_rounds"], 1)
        self.assertIn("self_report", review["detail"])
        # The pending call RAN after the grant (unknown-tool error, not
        # budget-skipped) and the turn closed normally.
        tool_contents = [json.loads(str(r["content"]))
                         for r in engine.records if r.get("role") == "tool"]
        self.assertFalse(any(c.get("status") == "skipped" for c in tool_contents))
        # The worker was told about the grant.
        notes = [r for r in engine.records
                 if r.get("synthetic") and "Budget review" in str(r.get("content"))]
        self.assertEqual(len(notes), 1)
        self.assertTrue(any(e["type"] == "orchestrator_review" for e in events))
        self.assertEqual(events[-1]["type"], "turn_done")

    def test_stop_keeps_skip_records_and_self_report(self) -> None:
        events: list[dict[str, Any]] = []
        engine = self._engine(events)
        llm = self._llm('{"verdict": "stop", "grant_rounds": 0, '
                        '"summary": "No evidence of progress; stopping."}')
        asyncio.new_event_loop().run_until_complete(engine.run_turn(
            "s1", "rig the cube", llm, "m", autonomy="auto", max_rounds=1))

        review = next(r for r in engine.records if r.get("role") == "review")
        self.assertEqual(review["granted_rounds"], 0)
        # Pending call recorded as skipped; the worker's self-report
        # closes the turn as a normal assistant message.
        tool_contents = [json.loads(str(r["content"]))
                         for r in engine.records if r.get("role") == "tool"]
        self.assertTrue(any(c.get("status") == "skipped" for c in tool_contents))
        self.assertIn("DEF-Cube", str(engine.records[-1].get("content")))
        self.assertEqual(engine.records[-1].get("role"), "assistant")
        self.assertEqual(events[-1]["type"], "turn_done")


@unittest.skipUnless(_HAS_AGENT_DEPS, "agent dependencies not installed (optional feature)")
class TestContextBudget(unittest.TestCase):
    """
    The context_tokens budget trims old tool results first, then whole
    exchanges (keeping tool replies attached to their assistant call),
    and never drops the system prompt or the latest user message.
    """

    def _engine(self) -> Any:
        _import_blagent()
        from blagent.engine import AgentEngine
        from blagent.media import MediaLibrary
        from blagent.tools import ToolRegistry

        async def emit(_event: Any) -> None:
            pass

        return AgentEngine(
            registry=ToolRegistry([]),
            media=MediaLibrary(tempfile.mkdtemp(prefix="blagent-ctx-")),
            system_prompt="system prompt",
            emit=emit,
            append_record=lambda record: None,
        )

    def test_trims_old_tool_results_then_drops_exchanges(self) -> None:
        engine = self._engine()
        big = "x" * 8_000
        for index in range(6):
            engine.records.append({"role": "user", "content": "question {:d}".format(index)})
            engine.records.append({
                "role": "assistant", "content": "",
                "tool_calls": [{"id": "c{:d}".format(index), "name": "t", "arguments": "{}"}],
            })
            engine.records.append({"role": "tool", "tool_call_id": "c{:d}".format(index), "content": big})
            engine.records.append({"role": "assistant", "content": "answer {:d}".format(index)})

        messages = engine._llm_messages(4_096)  # pylint: disable=protected-access
        # System prompt and the newest exchange survive.
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("answer 5", json.dumps(messages))
        # A trim notice is present exactly once.
        joined = json.dumps(messages)
        self.assertEqual(joined.count("trimmed to fit the context window."), 1)
        # No orphaned tool message: every tool message follows an
        # assistant message that carries tool_calls.
        for index, message in enumerate(messages):
            if message.get("role") == "tool":
                prev = messages[index - 1]
                self.assertTrue(
                    prev.get("tool_calls") or prev.get("role") == "tool",
                    "orphaned tool message at {:d}".format(index))
        # Budget roughly respected.
        estimate = engine._estimate_tokens(messages)  # pylint: disable=protected-access
        self.assertLessEqual(estimate, 4_096)

    def test_small_history_untouched(self) -> None:
        engine = self._engine()
        engine.records.append({"role": "user", "content": "hi"})
        engine.records.append({"role": "assistant", "content": "hello"})
        messages = engine._llm_messages(16_384)  # pylint: disable=protected-access
        self.assertNotIn("trimmed", json.dumps(messages))
        self.assertEqual(len(messages), 3)

    def test_thinking_stripped_from_projection(self) -> None:
        """
        <think>/<thinking> blocks stay in the transcript (the UI shows
        them as collapsible cards) but never go back to the model -
        templates expect old reasoning dropped and it wastes budget.
        An unterminated block (aborted generation) is removed too.
        """
        engine = self._engine()
        engine.records.append({"role": "user", "content": "hi"})
        engine.records.append({
            "role": "assistant",
            "content": "<think>secret plan</think>Done.<thinking>more</thinking>",
        })
        engine.records.append({"role": "user", "content": "again"})
        engine.records.append({"role": "assistant", "content": "<think>aborted mid-think"})
        messages = engine._llm_messages(16_384)  # pylint: disable=protected-access
        joined = json.dumps(messages)
        self.assertNotIn("secret plan", joined)
        self.assertNotIn("aborted mid-think", joined)
        self.assertIn("Done.", joined)
        # The transcript itself is untouched.
        self.assertIn("secret plan", engine.records[1]["content"])

    def test_volatile_results_age_before_others(self) -> None:
        """
        Read-only (volatile) scene-query results shrink to stubs before
        ordinary tool results are touched.
        """
        from blagent.tools import Tool

        class VolatileTool(Tool):
            name = "scene_query"
            volatile = True

        engine = self._engine_with_tools([VolatileTool()])
        big = "v" * 6_000
        for index in range(3):
            engine.records.append({"role": "user", "content": "q{:d}".format(index)})
            engine.records.append({
                "role": "assistant", "content": "",
                "tool_calls": [{"id": "v{:d}".format(index), "name": "scene_query", "arguments": "{}"}],
            })
            engine.records.append({
                "role": "tool", "tool_call_id": "v{:d}".format(index),
                "name": "scene_query", "content": big})
            engine.records.append({
                "role": "assistant", "content": "",
                "tool_calls": [{"id": "w{:d}".format(index), "name": "worker", "arguments": "{}"}],
            })
            engine.records.append({
                "role": "tool", "tool_call_id": "w{:d}".format(index),
                "name": "worker", "content": big})
            engine.records.append({"role": "assistant", "content": "done"})

        messages = engine._llm_messages(8_192)  # pylint: disable=protected-access
        joined = json.dumps(messages)
        self.assertIn("stale scene-query result trimmed", joined)
        # The newest volatile result stays verbatim.
        volatile = [m for m in messages if m.get("role") == "tool" and m["tool_call_id"].startswith("v")]
        self.assertNotIn("stale scene-query", volatile[-1]["content"])

    def test_old_images_demoted_to_placeholders(self) -> None:
        engine = self._engine()
        from blagent.media import MediaLibrary  # noqa: F401  (engine already has one)

        ids = [engine._media.register_bytes(b"\x89PNG fake", mime="image/png", label="p")
               for _ in range(5)]
        for media_id in ids:
            engine.records.append({"role": "user", "content": "look", "media_ids": [media_id]})
            engine.records.append({"role": "assistant", "content": "ok"})
        messages = engine._llm_messages()  # pylint: disable=protected-access
        image_parts = sum(
            1 for m in messages if isinstance(m.get("content"), list)
            for p in m["content"] if p.get("type") == "image_url")
        placeholders = sum(
            1 for m in messages if isinstance(m.get("content"), list)
            for p in m["content"] if p.get("type") == "text" and "older image was omitted" in p["text"])
        self.assertEqual(image_parts, 3)
        self.assertEqual(placeholders, 2)

    def _engine_with_tools(self, tools: "list[Any]") -> Any:
        from blagent.engine import AgentEngine
        from blagent.media import MediaLibrary
        from blagent.tools import ToolRegistry

        async def emit(_event: Any) -> None:
            pass

        return AgentEngine(
            registry=ToolRegistry(tools),
            media=MediaLibrary(tempfile.mkdtemp(prefix="blagent-ctx-")),
            system_prompt="system prompt",
            emit=emit,
            append_record=lambda record: None,
        )


@unittest.skipUnless(_HAS_AGENT_DEPS, "agent dependencies not installed (optional feature)")
class TestCompaction(unittest.TestCase):
    """
    Summarization compaction: a summary record supersedes the records
    it covers in the LLM projection; the transcript keeps everything.
    """

    def _engine(self) -> Any:
        _import_blagent()
        from blagent.engine import AgentEngine
        from blagent.media import MediaLibrary
        from blagent.tools import ToolRegistry

        async def emit(_event: Any) -> None:
            pass

        return AgentEngine(
            registry=ToolRegistry([]),
            media=MediaLibrary(tempfile.mkdtemp(prefix="blagent-cmp-")),
            system_prompt="system prompt",
            emit=emit,
            append_record=lambda record: None,
        )

    def test_compacts_and_projection_uses_summary(self) -> None:
        from blagent.llm import LlmChunk, LlmClient

        class Summarizer(LlmClient):
            def __init__(self) -> None:
                self.requests: list[dict[str, Any]] = []

            async def stream(self, request: dict[str, Any]) -> Any:
                self.requests.append(request)
                yield LlmChunk(content="SUMMARY: cube exists, user prefers metric.")

        engine = self._engine()
        for index in range(10):
            engine.records.append({"role": "user", "content": "msg {:d} ".format(index) + "x" * 3_000})
            engine.records.append({"role": "assistant", "content": "reply {:d} ".format(index) + "y" * 3_000})

        llm = Summarizer()
        compacted = asyncio.run(engine.maybe_compact(llm, "m", 8_192))
        self.assertTrue(compacted)
        # Summary record persisted with coverage.
        summary = engine.records[-1]
        self.assertEqual(summary["role"], "summary")
        self.assertGreater(summary["covers_count"], 0)
        # The summarizer saw the old history, and the briefing request
        # asks for the scaled word budget (floor at small contexts) and
        # the technical-lessons section.
        prompt = json.dumps(llm.requests[0]["messages"])
        self.assertIn("msg 0", prompt)
        self.assertIn("at most 400 words", prompt)
        self.assertIn("Technical lessons", prompt)
        # Projection: summary present, covered content absent, tail intact.
        messages = engine._llm_messages()  # pylint: disable=protected-access
        joined = json.dumps(messages)
        self.assertIn("SUMMARY: cube exists", joined)
        self.assertNotIn("msg 0", joined)
        self.assertIn("reply 9", joined)
        # Below threshold afterwards: no second compaction.
        self.assertFalse(asyncio.run(engine.maybe_compact(llm, "m", 8_192)))

    def test_summary_budget_scales_with_context(self) -> None:
        """
        Production feedback (2026-06-12): a fixed 400-word summary is
        far too brief for a large-context session — the word target
        scales with the budget (capped at 2500).
        """
        from blagent.llm import LlmChunk, LlmClient

        class Summarizer(LlmClient):
            def __init__(self) -> None:
                self.requests: list[dict[str, Any]] = []

            async def stream(self, request: dict[str, Any]) -> Any:
                self.requests.append(request)
                yield LlmChunk(content="SUMMARY.")

        engine = self._engine()
        for index in range(24):
            engine.records.append(
                {"role": "user", "content": "msg {:d} ".format(index) + "x" * 25_000})
            engine.records.append(
                {"role": "assistant", "content": "reply {:d} ".format(index) + "y" * 25_000})

        llm = Summarizer()
        self.assertTrue(asyncio.run(engine.maybe_compact(llm, "m", 150_000)))
        prompt = str(llm.requests[0]["messages"][1]["content"])
        self.assertIn("at most 2500 words", prompt)
        # The history shown to the summarizer also scales past the floor.
        self.assertGreater(len(prompt), 100_000)

    def test_no_compaction_under_threshold(self) -> None:
        from blagent.llm import LlmClient

        class Exploder(LlmClient):
            async def stream(self, request: dict[str, Any]) -> Any:
                raise AssertionError("must not be called")
                yield  # pylint: disable=unreachable

        engine = self._engine()
        engine.records.append({"role": "user", "content": "hi"})
        engine.records.append({"role": "assistant", "content": "hello"})
        engine.records.append({"role": "user", "content": "more"})
        engine.records.append({"role": "assistant", "content": "sure"})
        self.assertFalse(asyncio.run(engine.maybe_compact(Exploder(), "m", 16_384)))


@unittest.skipUnless(_HAS_AGENT_DEPS, "agent dependencies not installed (optional feature)")
class TestInstanceTitle(unittest.TestCase):
    """
    Instance labeling for multi-Blender setups: the title rides the
    ``hello`` message and ``POST /instance`` broadcasts updates (the
    add-on posts from save/load handlers).
    """

    def test_hello_carries_title_and_update_broadcasts(self) -> None:
        _import_blagent()
        from blagent.app import create_app
        from blagent.runtime import AgentRuntime
        from blagent.store import AgentStore

        from starlette.testclient import TestClient

        async def build() -> AgentRuntime:
            store = AgentStore(data_dir=tempfile.mkdtemp(prefix="blagent-title-"))
            return AgentRuntime(store, [])

        runtime = asyncio.new_event_loop().run_until_complete(build())
        runtime.instance_title = "house.blend"
        runtime.instance_port = 10102
        client = TestClient(create_app(runtime))
        with client.websocket_connect("/ws") as ws:
            hello = ws.receive_json()
            self.assertEqual(hello["instance"], {"title": "house.blend", "port": 10102})
            response = client.post("/instance", json={"title": "barn.blend"})
            self.assertEqual(response.status_code, 200)
            event = ws.receive_json()
            self.assertEqual(event["type"], "instance")
            self.assertEqual(event["title"], "barn.blend")
            self.assertEqual(event["port"], 10102)


@unittest.skipUnless(_HAS_AGENT_DEPS, "agent dependencies not installed (optional feature)")
class TestVisionFallback(unittest.TestCase):
    """
    Endpoints without an image encoder (e.g. vLLM hosting a text-only
    model) reject multimodal content; the engine must strip images,
    retry once, and continue text-only.
    """

    def test_image_rejection_falls_back_to_text(self) -> None:
        _import_blagent()
        from blagent.engine import AgentEngine
        from blagent.llm import LlmChunk, LlmClient, LlmError
        from blagent.media import MediaLibrary
        from blagent.tools import ToolRegistry

        media_dir = tempfile.mkdtemp(prefix="blagent-vision-")
        media = MediaLibrary(media_dir)
        media_id = media.register_bytes(b"\x89PNG fake", mime="image/png", label="probe")

        class RejectingLlm(LlmClient):
            def __init__(self) -> None:
                self.calls: list[bool] = []

            async def stream(self, request: dict[str, Any]) -> Any:
                has_images = any(
                    isinstance(m.get("content"), list) for m in request["messages"])
                self.calls.append(has_images)
                if has_images:
                    raise LlmError("400: image input not supported by this model")
                yield LlmChunk(content="Understood, text only.")

        events: list[dict[str, Any]] = []

        async def emit(event: dict[str, Any]) -> None:
            events.append(event)

        engine = AgentEngine(
            registry=ToolRegistry([]),
            media=media,
            system_prompt="test",
            emit=emit,
            append_record=lambda record: None,
        )
        llm = RejectingLlm()
        asyncio.run(engine.run_turn(
            session_id="s1",
            user_text="look at this",
            llm=llm,
            model="text-only",
            autonomy="auto",
            max_rounds=4,
            media_ids=[media_id],
        ))
        # First call carried images and was rejected; the retry did not.
        self.assertEqual(llm.calls, [True, False])
        self.assertFalse(engine.vision_ok)
        # The blind model must be told it cannot see, not handed a
        # bare attachment placeholder to confabulate from.
        retry_messages = engine._llm_messages()  # pylint: disable=protected-access
        joined = json.dumps(retry_messages)
        self.assertIn("TEXT-ONLY", joined)
        self.assertIn("cannot see images", joined)
        messages = [e for e in events if e["type"] == "error"]
        self.assertTrue(any("image input" in m["message"] or "text placeholders" in m["message"]
                            for m in messages))
        self.assertEqual(events[-1]["type"], "turn_done")


class TestSessionLocking(unittest.TestCase):
    """
    Cross-process advisory locks on session transcripts: appends merge
    through the on-disk file, the lock is re-entrant within one store,
    and a loser that cannot acquire the lock gets SessionBusyError
    instead of corrupting anything. Two AgentStore instances stand in
    for two processes (flock contends per file description).
    """

    def _stores(self) -> Any:
        _import_blagent()
        from blagent.store import AgentStore

        data_dir = tempfile.mkdtemp(prefix="blagent-lock-")
        return AgentStore(data_dir), AgentStore(data_dir)

    def test_append_returns_merged_view(self) -> None:
        store_a, store_b = self._stores()
        sid = "20260611-000000-aaaaaa"
        store_a.append_record(sid, {"role": "user", "content": "from a"})
        store_b.append_record(sid, {"role": "assistant", "content": "from b"})
        merged = store_a.append_record(sid, {"role": "user", "content": "a again"})
        self.assertEqual(
            [r["content"] for r in merged],
            ["from a", "from b", "a again"])
        # Both stores converge on the same on-disk truth.
        self.assertEqual(merged, store_b.load_records(sid))

    def test_lock_is_reentrant_within_store(self) -> None:
        store_a, _ = self._stores()
        sid = "20260611-000000-bbbbbb"
        with store_a.session_lock(sid, timeout=1.0):
            with store_a.session_lock(sid, timeout=1.0):
                store_a.append_record(sid, {"role": "user", "content": "nested"})
            records = store_a.load_records(sid)
        self.assertEqual(records[0]["content"], "nested")

    def test_loser_gets_busy_error_and_reads_still_work(self) -> None:
        _import_blagent()
        from blagent.store import SessionBusyError

        store_a, store_b = self._stores()
        sid = "20260611-000000-cccccc"
        store_a.append_record(sid, {"role": "user", "content": "first"})
        with store_a.session_lock(sid, timeout=1.0):
            # A second window cannot write while the lock is held...
            with self.assertRaises(SessionBusyError):
                store_b.append_record(sid, {"role": "user", "content": "loser"}, timeout=0.2)
            # ...but viewing falls back to a lockless read.
            records = store_b.load_records(sid)
        self.assertEqual([r["content"] for r in records], ["first"])
        # After release the loser can write again.
        merged = store_b.append_record(sid, {"role": "user", "content": "second"})
        self.assertEqual([r["content"] for r in merged], ["first", "second"])


class TestLlmOutputParser(unittest.TestCase):
    """
    Wrapper around the node-based unit tests for the browser-side
    streaming output parser (tool-call grammars + think tags). The
    parser is plain ESM with no dependencies, so `node --test` runs it
    directly; skipped when node is not installed.
    """

    def test_node_suite(self) -> None:
        import shutil
        import subprocess

        node = shutil.which("node")
        if node is None:
            self.skipTest("node not on PATH")
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        proc = subprocess.run(
            [node, "--test", os.path.join(repo, "tests", "test_llm_output_parser.mjs")],
            capture_output=True, text=True, timeout=120, check=False,
        )
        self.assertEqual(proc.returncode, 0, "node tests failed:\n" + proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
