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
class TestWebLlmBridge(unittest.TestCase):
    """
    Request/response correlation on the WebLLM reverse tunnel.
    """

    def test_streaming_roundtrip(self) -> None:
        """
        Checks chunk/done correlation between a fake browser and the bridge.
        """
        _import_blagent()
        from blagent.webllm import WebLlmBridge

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
            bridge = WebLlmBridge()
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
        from blagent.webllm import WebLlmBridge

        class SilentWs:
            async def send_json(self, data: Any) -> None:
                pass

        async def run() -> int:
            bridge = WebLlmBridge()
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


if __name__ == "__main__":
    unittest.main()
