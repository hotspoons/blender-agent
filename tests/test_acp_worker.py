# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Tests for driving worker sub-agents over ACP
(``agent/agentcore/acp/client.py``, ``acp/worker.py``, ``worker_wire.py``).

The orchestrator is an ACP client and a worker is an ACP agent, so these run
BOTH halves of this repo's own implementation against each other over a real
socket: an ``AcpWire`` drives a real ``AgentRuntime`` served over ACP by
uvicorn. What is asserted is that the wire emits the same harness events the
chat-completions wire does -- that is the parity the cutover depends on, since
the UI cannot tell the two apart.

    python -m unittest tests.test_acp_worker -v
"""

__all__ = ()

import asyncio
import importlib.util
import os
import sys
import tempfile
import unittest
from typing import Any

_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_AGENT_DIR = os.path.join(_REPO_DIR, "agent")
_MCP_DIR = os.path.join(_REPO_DIR, "mcp")

for _path in (_MCP_DIR, _AGENT_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)

_HAS_DEPS = all(
    importlib.util.find_spec(mod) is not None
    for mod in ("acp", "pydantic", "starlette", "uvicorn", "websockets", "httpx",
                "mcp", "blmcp"))

_PORT = 18711


def _fake_llm(reply: str, tool_call: bool = False) -> Any:
    from agentcore.llm import LlmChunk, LlmClient

    class FakeLlm(LlmClient):  # type: ignore[misc]
        def __init__(self) -> None:
            self.turns = 0

        async def stream(self, request):  # type: ignore[no-untyped-def]
            self.turns += 1
            if tool_call and self.turns == 1:
                yield LlmChunk(tool_calls=[{
                    "index": 0, "id": "call-1",
                    "function": {"name": "probe", "arguments": "{}"}}])
                return
            for word in reply.split(" "):
                yield LlmChunk(content=word + " ")

    instance = FakeLlm()
    return lambda: instance


def _probe_tool() -> Any:
    from agentcore.tools import Tool, ToolResult

    class Probe(Tool):  # type: ignore[misc]
        name = "probe"
        description = "Probe the scene."
        read_only = True

        def input_schema(self) -> "dict[str, Any]":
            return {"type": "object", "properties": {}}

        async def call(self, ctx: Any, args: "dict[str, Any]") -> Any:
            del ctx, args
            return ToolResult(data={"objects": 1}, summary="probed the scene")

    return Probe()


class _ServedAgent:
    """A real runtime served over ACP on a port, as a worker would be."""

    def __init__(self, reply: str, tools: "list[Any]", tool_call: bool, port: int) -> None:
        self._reply = reply
        self._tools = tools
        self._tool_call = tool_call
        self._port = port
        self.runtime: Any = None
        self._server: Any = None
        self._task: "asyncio.Task[None] | None" = None

    async def __aenter__(self) -> "_ServedAgent":
        import uvicorn
        from starlette.applications import Starlette
        from agentcore.acp.bridge import RuntimeBridge
        from agentcore.acp.transport import acp_routes
        from agentcore.runtime import AgentRuntime
        from agentcore.store import AgentStore

        self._tmp = tempfile.TemporaryDirectory()
        store = AgentStore(data_dir=self._tmp.name)
        store.config.endpoint = "http://fake-endpoint/v1"
        store.config.model = "fake-model"
        store.config.autonomy_level = "yolo"
        store.config.autonomy = "auto"
        self.runtime = AgentRuntime(store, self._tools)
        self.runtime._make_llm = _fake_llm(self._reply, self._tool_call)
        self.runtime._model_name = lambda: "fake-model"

        app = Starlette(routes=acp_routes(lambda: RuntimeBridge(self.runtime), prefix="/acp"))
        self._server = uvicorn.Server(uvicorn.Config(
            app, host="127.0.0.1", port=self._port, log_level="error",
            ws_ping_interval=None, ws_ping_timeout=None))
        self._task = asyncio.create_task(self._server.serve())
        while not self._server.started:
            await asyncio.sleep(0.02)
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._task is not None:
            await self._task
        self._tmp.cleanup()

    @property
    def endpoint(self) -> str:
        return "ws://127.0.0.1:{:d}/acp".format(self._port)


@unittest.skipUnless(_HAS_DEPS, "agent dependencies not installed")
class TestAcpWire(unittest.TestCase):

    def test_converse_returns_the_report_and_streams_prose(self) -> None:
        events: "list[dict[str, Any]]" = []

        async def run() -> str:
            from agentcore.acp.worker import AcpWire

            async def emit(event: "dict[str, Any]") -> None:
                events.append(event)

            async with _ServedAgent("Built it. PROOF: one cube.", [], False, _PORT) as agent:
                return await AcpWire().converse(
                    agent.endpoint, "build a cube", user="task-1", emit=emit)

        report = asyncio.run(run())
        self.assertIn("PROOF", report)
        self.assertIn("token", [e["type"] for e in events])

    def test_tool_calls_arrive_as_tool_status_events(self) -> None:
        """
        The UI renders worker activity from tool_status events. If ACP-driven
        workers did not produce them, a swarm run would look empty -- which is
        the parity the cutover turns on.
        """
        events: "list[dict[str, Any]]" = []

        async def run() -> None:
            from agentcore.acp.worker import AcpWire

            async def emit(event: "dict[str, Any]") -> None:
                events.append(event)

            async with _ServedAgent(
                    "Done. PROOF: probed.", [_probe_tool()], True, _PORT + 1) as agent:
                await AcpWire().converse(
                    agent.endpoint, "probe the scene", user="task-2", emit=emit)

        asyncio.run(run())
        tool_events = [e for e in events if e["type"] == "tool_status"]
        self.assertTrue(tool_events, "no tool_status events reached the worker card")
        self.assertEqual(tool_events[-1]["name"], "probe")
        # done -> ok, matching what the chat-completions wire emits.
        self.assertEqual(tool_events[-1]["state"], "ok")
        self.assertIn("probed", tool_events[-1]["summary"])

    def test_context_fork_seeds_the_worker_session(self) -> None:
        """
        The 'full' handoff forks the parent conversation into the worker. ACP
        has no seed field, so it rides under _meta on session/new -- verify it
        actually lands rather than being silently dropped.
        """
        async def run() -> "tuple[Any, str]":
            from agentcore.acp.worker import AcpWire

            async with _ServedAgent("ok PROOF: x", [], False, _PORT + 2) as agent:
                await AcpWire().converse(
                    agent.endpoint, "carry on", user="task-3",
                    seed_messages=[
                        {"role": "user", "content": "the mission is a village"},
                        {"role": "assistant", "content": "understood"},
                    ])
                sessions = agent.runtime.list_sessions()
                sid = str(sessions[0]["id"]) if sessions else ""
                engine = agent.runtime._get_or_load_session(sid).engine
                seeded = " ".join(str(m.get("content", "")) for m in engine._seed_messages)
                return agent.runtime, seeded

        _runtime, seeded = asyncio.run(run())
        self.assertIn("the mission is a village", seeded)

    def test_endpoint_and_ready_path(self) -> None:
        from agentcore.acp.worker import AcpWire

        wire = AcpWire()
        self.assertEqual(wire.endpoint("localhost", 9000), "ws://localhost:9000/acp")
        # /healthz, not /v1/models: an ACP worker need not serve the chat API.
        self.assertEqual(wire.ready_path, "/healthz")
        self.assertTrue(wire.supports_steering)

    def test_chat_wire_does_not_claim_steering(self) -> None:
        """
        The old wire has no way to reach a working agent; saying so lets the
        orchestrator fall back to a round boundary instead of assuming the
        message landed.
        """
        from agentcore.worker_wire import ChatCompletionsWire

        wire = ChatCompletionsWire()
        self.assertFalse(wire.supports_steering)
        self.assertEqual(wire.endpoint("h", 1), "http://h:1/v1")
        self.assertEqual(
            asyncio.run(wire.steer("http://h:1/v1", "u", "hurry up")), False)


@unittest.skipUnless(_HAS_DEPS, "agent dependencies not installed")
class TestSteering(unittest.TestCase):
    """
    Steering a working agent -- the reason this wire wanted v2 at all.

    v1 treats a session as strictly turn-based, so there is no legal way to say
    anything to an agent mid-turn. v2 drops that: a prompt to a busy session is
    guidance, delivered at the running turn's next round boundary.
    """

    def test_prompting_a_busy_session_steers_it(self) -> None:
        """
        End to end over a socket: prompt, steer while it works, and confirm the
        guidance landed in the transcript of the SAME turn rather than starting
        a second one.
        """
        from agentcore.llm import LlmChunk, LlmClient

        started = asyncio.Event()
        release = asyncio.Event()

        class SlowLlm(LlmClient):  # type: ignore[misc]
            def __init__(self) -> None:
                self.rounds = 0
                self.saw: "list[str]" = []

            async def stream(self, request):  # type: ignore[no-untyped-def]
                self.rounds += 1
                # Record every user message this round can see. `request` is the
                # raw OpenAI-shaped dict the engine builds.
                for message in (request or {}).get("messages") or []:
                    if isinstance(message, dict) and message.get("role") == "user":
                        content = message.get("content")
                        if isinstance(content, str):
                            self.saw.append(content)
                        elif isinstance(content, list):
                            for part in content:
                                if isinstance(part, dict) and part.get("type") == "text":
                                    self.saw.append(str(part.get("text") or ""))
                if self.rounds == 1:
                    started.set()
                    await release.wait()
                    # A tool call keeps the turn going to a second round, which
                    # is where an injection gets picked up.
                    yield LlmChunk(tool_calls=[{
                        "index": 0, "id": "c1",
                        "function": {"name": "probe", "arguments": "{}"}}])
                    return
                yield LlmChunk(content="Adjusted. PROOF: done.")

        llm = SlowLlm()

        async def run() -> "tuple[list[str], int]":
            import uvicorn
            from starlette.applications import Starlette
            from agentcore.acp.bridge import RuntimeBridge
            from agentcore.acp.client import AcpClient
            from agentcore.acp.transport import acp_routes
            from agentcore.runtime import AgentRuntime
            from agentcore.store import AgentStore

            tmp = tempfile.TemporaryDirectory()
            store = AgentStore(data_dir=tmp.name)
            store.config.endpoint = "http://fake/v1"
            store.config.model = "fake"
            store.config.autonomy = "auto"
            store.config.autonomy_level = "yolo"
            runtime = AgentRuntime(store, [_probe_tool()])
            runtime._make_llm = lambda: llm
            runtime._model_name = lambda: "fake"

            app = Starlette(routes=acp_routes(
                lambda: RuntimeBridge(runtime), prefix="/acp"))
            server = uvicorn.Server(uvicorn.Config(
                app, host="127.0.0.1", port=_PORT + 5, log_level="error",
                ws_ping_interval=None, ws_ping_timeout=None))
            serve = asyncio.create_task(server.serve())
            while not server.started:
                await asyncio.sleep(0.02)
            try:
                async with AcpClient("ws://127.0.0.1:{:d}/acp".format(_PORT + 5)) as client:
                    session_id = await client.new_session()
                    turn = asyncio.create_task(client.prompt(session_id, "build a ball"))
                    await asyncio.wait_for(started.wait(), timeout=10)
                    # The turn is in flight; steer it.
                    await client.steer(session_id, "make it red instead")
                    await asyncio.sleep(0.2)
                    release.set()
                    await asyncio.wait_for(turn, timeout=15)
            finally:
                server.should_exit = True
                await serve
                tmp.cleanup()
            return llm.saw, llm.rounds

        saw, rounds = asyncio.run(run())
        self.assertGreaterEqual(rounds, 2, "the turn did not reach a second round")
        joined = " ".join(saw)
        self.assertIn("build a ball", joined)
        self.assertIn(
            "make it red instead", joined,
            "the steering message never reached the running turn")

    def test_steering_is_refused_on_v1(self) -> None:
        """
        v1 has no contract for this, so the client must refuse rather than send
        a prompt that the peer is entitled to reject.
        """
        from agentcore.acp.client import AcpClient, AcpClientError

        client = AcpClient("ws://127.0.0.1:1/acp")
        client.version = 1
        with self.assertRaises(AcpClientError):
            asyncio.run(client.steer("s1", "hurry up"))


@unittest.skipUnless(_HAS_DEPS, "agent dependencies not installed")
class TestWireParity(unittest.TestCase):
    """
    The two wires must be indistinguishable to everything downstream.

    The cutover plan is "build in place, drop the old one once parity holds",
    and this is what parity means concretely: the same worker outcome produces
    the same harness events, so the UI, the orchestrator's review step and the
    persisted run view cannot tell which protocol carried it.
    """

    def test_success_normalizes_to_the_same_state(self) -> None:
        from agentcore.worker_wire import normalize_tool_state

        # Each producer spells success differently; the card has always said ok.
        self.assertEqual(normalize_tool_state("done"), "ok")        # engine
        self.assertEqual(normalize_tool_state("completed"), "ok")   # ACP
        self.assertEqual(normalize_tool_state("ok"), "ok")          # chat_api
        # Distinctions the UI renders are preserved ...
        self.assertEqual(normalize_tool_state("rejected"), "rejected")
        self.assertEqual(normalize_tool_state("pending_confirm"), "pending_confirm")
        self.assertEqual(normalize_tool_state("running"), "running")
        # ... and anything unrecognised fails loudly rather than looking fine.
        self.assertEqual(normalize_tool_state("who-knows"), "error")

    def test_both_wires_emit_the_same_event_shape(self) -> None:
        """
        A completed tool call must produce the same event keys and values from
        either wire, given equivalent input.
        """
        from agentcore.acp.updates import META_NAMESPACE
        from agentcore.acp.worker import AcpWire
        from agentcore.worker_wire import ChatCompletionsWire

        chat_events: "list[dict[str, Any]]" = []
        acp_events: "list[dict[str, Any]]" = []

        async def run() -> None:
            async def chat_emit(event: "dict[str, Any]") -> None:
                chat_events.append(event)

            async def acp_emit(event: "dict[str, Any]") -> None:
                acp_events.append(event)

            chat = ChatCompletionsWire(
                tool_calls_key="blender_tool_calls", media_key="blender_media")
            await chat._stream_delta({"blender_tool_calls": [{
                "call_id": "c1", "name": "probe", "args_json": "{}",
                "status": "done", "summary": "probed the scene"}]}, [], chat_emit)

            await AcpWire()._translate({
                "sessionUpdate": "tool_call_update",
                "toolCallId": "c1", "name": "probe", "status": "completed",
                "content": [{"type": "content",
                             "content": {"type": "text", "text": "probed the scene"}}],
                "_meta": {META_NAMESPACE: {"arguments": "{}", "state": "done"}},
            }, [], acp_emit)

        asyncio.run(run())
        self.assertEqual(len(chat_events), 1)
        self.assertEqual(len(acp_events), 1)
        self.assertEqual(chat_events[0], acp_events[0])

    def test_both_wires_emit_prose_the_same_way(self) -> None:
        from agentcore.acp.worker import AcpWire
        from agentcore.worker_wire import ChatCompletionsWire

        chat_events: "list[dict[str, Any]]" = []
        acp_events: "list[dict[str, Any]]" = []
        blob = "Rendered:\n![scene](data:image/png;base64,QUJD)\nDone."

        async def run() -> None:
            async def chat_emit(event: "dict[str, Any]") -> None:
                chat_events.append(event)

            async def acp_emit(event: "dict[str, Any]") -> None:
                acp_events.append(event)

            await ChatCompletionsWire()._stream_delta({"content": blob}, [], chat_emit)
            await AcpWire()._translate({
                "sessionUpdate": "agent_message_chunk",
                "messageId": "m1",
                "content": {"type": "text", "text": blob},
            }, [], acp_emit)

        asyncio.run(run())
        self.assertEqual(chat_events, acp_events)
        # Both strip the inlined data URL from the streamed prose.
        self.assertNotIn("data:image", chat_events[0]["text"])


@unittest.skipUnless(_HAS_DEPS, "agent dependencies not installed")
class TestWireSelection(unittest.TestCase):
    """The config knob, and that the default path is untouched."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _runtime(self) -> Any:
        from agentcore.runtime import AgentRuntime
        from agentcore.store import AgentStore

        store = AgentStore(data_dir=self._tmp.name)
        store.config.endpoint = "http://fake-endpoint/v1"
        store.config.model = "fake-model"
        return AgentRuntime(store, [])

    def test_default_keeps_the_original_wire(self) -> None:
        runtime = self._runtime()
        self.assertEqual(runtime.store.config.autonomy_wire, "chat")
        # None means "strategy builds its own chat wire", leaving the original
        # path byte-identical while ACP is proven.
        self.assertIsNone(runtime._worker_wire())

    def test_acp_selects_the_protocol_wire(self) -> None:
        from agentcore.acp.worker import AcpWire

        runtime = self._runtime()
        runtime.set_config({"autonomy_wire": "acp"})
        self.assertIsInstance(runtime._worker_wire(), AcpWire)

    def test_unknown_wire_is_ignored(self) -> None:
        runtime = self._runtime()
        runtime.set_config({"autonomy_wire": "carrier-pigeon"})
        self.assertEqual(runtime.store.config.autonomy_wire, "chat")

    def test_strategy_defaults_to_chat_wire(self) -> None:
        from agentcore.swarm import RemoteWorkerStrategy
        from agentcore.worker_wire import ChatCompletionsWire

        strategy = RemoteWorkerStrategy(
            endpoint="http://x/v1", model="m", exchange_dir=self._tmp.name)
        self.assertIsInstance(strategy.wire, ChatCompletionsWire)

    def test_strategy_adopts_the_wire_readiness_path(self) -> None:
        """
        A worker's readiness probe follows the wire: the chat API answers
        /v1/models, but an ACP worker may not serve it at all.
        """
        from agentcore.acp.worker import AcpWire
        from agentcore.swarm import WorkerInstance

        worker = WorkerInstance(
            worker_id="w", api_port=9100, data_dir=self._tmp.name, command=["true"])
        self.assertTrue(worker.ready_url.endswith("/v1/models"))
        worker.adopt_wire(AcpWire().ready_path, AcpWire().launch_env)
        self.assertTrue(worker.ready_url.endswith("/healthz"))


if __name__ == "__main__":
    unittest.main()
