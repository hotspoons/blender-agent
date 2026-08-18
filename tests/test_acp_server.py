# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Tests for the ACP dispatcher and its transports
(``agent/agentcore/acp/server.py``, ``transport.py``).

These drive the dispatcher against a fake bridge, so they cover the protocol
layer alone: version negotiation, per-version method routing, error mapping,
and the agent -> client direction. The runtime mapping is tested separately.

    python -m unittest tests.test_acp_server -v
"""

__all__ = ()

import asyncio
import importlib.util
import os
import sys
import unittest
from typing import Any

_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_AGENT_DIR = os.path.join(_REPO_DIR, "agent")

_HAS_DEPS = all(
    importlib.util.find_spec(mod) is not None
    for mod in ("acp", "pydantic", "starlette"))


def _import(name: str) -> Any:
    if _AGENT_DIR not in sys.path:
        sys.path.insert(0, _AGENT_DIR)
    import importlib
    return importlib.import_module(name)


class FakeBridge:
    """Records what the dispatcher asked for; returns plausible answers."""

    def __init__(self) -> None:
        self.calls: "list[tuple[str, Any]]" = []
        self.sessions: "list[str]" = []
        self.stop_reason = "end_turn"

    async def new_session(
            self, cwd: Any, mcp_servers: Any, client: Any, meta: Any = None) -> str:
        self.calls.append(("new_session", (cwd, mcp_servers, meta)))
        session_id = "s{:d}".format(len(self.sessions) + 1)
        self.sessions.append(session_id)
        return session_id

    async def prompt(self, session_id: str, blocks: Any, client: Any,
                     await_turn: bool = True) -> "str | None":
        self.calls.append(("prompt", (session_id, blocks, await_turn)))
        return self.stop_reason if await_turn else None

    async def cancel(self, session_id: str) -> None:
        self.calls.append(("cancel", session_id))

    async def list_sessions(self) -> "list[dict[str, Any]]":
        return [{"sessionId": s} for s in self.sessions]

    async def delete_session(self, session_id: str) -> None:
        self.calls.append(("delete", session_id))

    async def resume_session(self, session_id: str, replay_from: Any, client: Any) -> None:
        self.calls.append(("resume", (session_id, replay_from)))

    async def close_session(self, session_id: str) -> None:
        self.calls.append(("close", session_id))

    async def fork_session(self, session_id: str, cwd: Any) -> str:
        self.calls.append(("fork", (session_id, cwd)))
        return session_id + "-fork"

    async def set_config_option(self, session_id: str, option_id: str, value: Any) -> "dict[str, Any]":
        self.calls.append(("set_config", (session_id, option_id, value)))
        return {"configOptions": []}


def _connection(bridge: Any) -> Any:
    server = _import("agentcore.acp.server")
    conn = server.AcpConnection(bridge)
    sent: "list[tuple[str, dict[str, Any]]]" = []

    async def send_request(method: str, params: "dict[str, Any]") -> Any:
        sent.append((method, params))
        return {"outcome": {"outcome": "selected", "optionId": "allow"}}

    async def send_notification(method: str, params: "dict[str, Any]") -> None:
        sent.append((method, params))

    conn.attach(send_request, send_notification)
    conn.sent = sent  # type: ignore[attr-defined]
    return conn


async def _initialize(conn: Any, version: int) -> "dict[str, Any]":
    return await conn.handle(
        "initialize",
        {"protocolVersion": version, "info": {"name": "test-client", "version": "1"}},
        False)


@unittest.skipUnless(_HAS_DEPS, "acp/pydantic/starlette not installed")
class TestNegotiation(unittest.TestCase):
    """One endpoint, two versions -- the whole point of a single dispatcher."""

    def test_v2_client_gets_v2(self) -> None:
        result = asyncio.run(_initialize(_connection(FakeBridge()), 2))
        self.assertEqual(result["protocolVersion"], 2)
        self.assertIn("capabilities", result)
        self.assertEqual(result["capabilities"]["session"]["fork"], {})

    def test_v1_client_gets_v1_shape(self) -> None:
        result = asyncio.run(_initialize(_connection(FakeBridge()), 1))
        self.assertEqual(result["protocolVersion"], 1)
        # v1 advertises flat booleans under agentCapabilities, not v2's nesting.
        self.assertIn("agentCapabilities", result)
        self.assertNotIn("capabilities", result)
        self.assertTrue(result["agentCapabilities"]["loadSession"])

    def test_future_version_is_downgraded_to_our_highest(self) -> None:
        result = asyncio.run(_initialize(_connection(FakeBridge()), 99))
        self.assertEqual(result["protocolVersion"], 2)

    def test_capabilities_only_claim_what_is_implemented(self) -> None:
        """
        An advertised capability is a promise the client acts on. MCP server
        provisioning is accepted-and-ignored today, so it must not appear --
        otherwise a client hands over its tool servers and then wonders why the
        agent never uses them.
        """
        versions = _import("agentcore.acp.versions")
        wire = _import("agentcore.acp.wire")
        caps = wire.dump(versions.agent_capabilities_v2())
        session = caps.get("session", {})

        mcp_claimed = "mcp" in session
        mcp_implemented = any((
            versions._IMPLEMENTS_MCP_STDIO,
            versions._IMPLEMENTS_MCP_HTTP,
            versions._IMPLEMENTS_MCP_ACP))
        self.assertEqual(
            mcp_claimed, mcp_implemented,
            "mcp capability advertisement disagrees with the _IMPLEMENTS_MCP_* flags")

        # Editor-only surfaces are never claimed: they have no meaning for a
        # 3D scene agent and we do not implement them.
        self.assertNotIn("nes", caps)
        self.assertNotIn("providers", caps)

    def test_calls_before_initialize_are_rejected(self) -> None:
        from acp.exceptions import RequestError
        conn = _connection(FakeBridge())
        with self.assertRaises(RequestError) as caught:
            asyncio.run(conn.handle("session/new", {"cwd": "/tmp"}, False))
        self.assertIn("initialize", str(caught.exception))


@unittest.skipUnless(_HAS_DEPS, "acp/pydantic/starlette not installed")
class TestMethodRouting(unittest.TestCase):

    def _ready(self, version: int = 2) -> "tuple[Any, FakeBridge]":
        bridge = FakeBridge()
        conn = _connection(bridge)
        asyncio.run(_initialize(conn, version))
        return conn, bridge

    def test_session_new_and_prompt(self) -> None:
        conn, bridge = self._ready()
        created = asyncio.run(conn.handle("session/new", {"cwd": "/work"}, False))
        self.assertEqual(created["sessionId"], "s1")
        result = asyncio.run(conn.handle(
            "session/prompt",
            {"sessionId": "s1", "prompt": [{"type": "text", "text": "make a cube"}]},
            False))
        # v2's PromptResponse carries no stopReason: the schema says it "does
        # not indicate that the agent has finished processing". Completion
        # arrives as a state_update instead.
        self.assertEqual(result, {})
        self.assertEqual(bridge.calls[-1][0], "prompt")
        self.assertFalse(bridge.calls[-1][1][2], "v2 must not wait for the turn")

    def test_v1_prompt_still_answers_with_a_stop_reason(self) -> None:
        """
        v1's PromptResponse requires stopReason, so a v1 connection must block
        for the turn. Same bridge, different contract.
        """
        conn, bridge = self._ready(version=1)
        asyncio.run(conn.handle("session/new", {"cwd": "/work"}, False))
        result = asyncio.run(conn.handle(
            "session/prompt",
            {"sessionId": "s1", "prompt": [{"type": "text", "text": "go"}]},
            False))
        self.assertEqual(result["stopReason"], "end_turn")
        self.assertTrue(bridge.calls[-1][1][2], "v1 must wait for the turn")

    def test_prompt_requires_array(self) -> None:
        from acp.exceptions import RequestError
        conn, _bridge = self._ready()
        asyncio.run(conn.handle("session/new", {"cwd": "/work"}, False))
        with self.assertRaises(RequestError):
            asyncio.run(conn.handle(
                "session/prompt", {"sessionId": "s1", "prompt": "not a list"}, False))

    def test_missing_session_id_is_invalid_params(self) -> None:
        from acp.exceptions import RequestError
        conn, _bridge = self._ready()
        with self.assertRaises(RequestError) as caught:
            asyncio.run(conn.handle("session/cancel", {}, False))
        self.assertEqual(caught.exception.code, -32602)

    def test_fork_is_v2_only(self) -> None:
        """
        session/fork is unstable-v2. A v1 connection must not reach it, or a v1
        client would get a method it cannot have negotiated.
        """
        from acp.exceptions import RequestError
        conn_v2, _b2 = self._ready(version=2)
        forked = asyncio.run(conn_v2.handle("session/fork", {"sessionId": "s1"}, False))
        self.assertEqual(forked["sessionId"], "s1-fork")

        conn_v1, _b1 = self._ready(version=1)
        with self.assertRaises(RequestError) as caught:
            asyncio.run(conn_v1.handle("session/fork", {"sessionId": "s1"}, False))
        self.assertEqual(caught.exception.code, -32601)

    def test_v1_uses_session_load_not_resume(self) -> None:
        conn_v1, bridge = self._ready(version=1)
        asyncio.run(conn_v1.handle("session/load", {"sessionId": "s1"}, False))
        self.assertEqual(bridge.calls[-1][0], "resume")

        from acp.exceptions import RequestError
        with self.assertRaises(RequestError):
            asyncio.run(conn_v1.handle("session/resume", {"sessionId": "s1"}, False))

    def test_unknown_method_is_method_not_found(self) -> None:
        from acp.exceptions import RequestError
        conn, _bridge = self._ready()
        with self.assertRaises(RequestError) as caught:
            asyncio.run(conn.handle("nes/start", {}, False))
        self.assertEqual(caught.exception.code, -32601)


@unittest.skipUnless(_HAS_DEPS, "acp/pydantic/starlette not installed")
class TestClientProxy(unittest.TestCase):
    """Agent -> client calls, and the v1/v2 payload split."""

    def _proxy(self, version: int) -> "tuple[Any, list[Any]]":
        server = _import("agentcore.acp.server")
        sent: "list[tuple[str, dict[str, Any]]]" = []

        async def send_request(method: str, params: "dict[str, Any]") -> Any:
            sent.append((method, params))
            return {"outcome": {"outcome": "selected", "optionId": "allow"}}

        async def send_notification(method: str, params: "dict[str, Any]") -> None:
            sent.append((method, params))

        return server.ClientProxy(send_request, send_notification, version), sent

    def test_session_update_is_a_notification(self) -> None:
        proxy, sent = self._proxy(2)
        asyncio.run(proxy.session_update("s1", {"sessionUpdate": "agent_message_chunk"}))
        self.assertEqual(sent[0][0], "session/update")
        self.assertEqual(sent[0][1]["sessionId"], "s1")

    def test_permission_v2_carries_title_and_subject(self) -> None:
        proxy, sent = self._proxy(2)
        asyncio.run(proxy.request_permission(
            "s1", "Run script", [{"optionId": "allow", "name": "Allow", "kind": "allow_once"}],
            subject={"toolCall": {"toolCallId": "c1"}}))
        params = sent[0][1]
        self.assertEqual(params["title"], "Run script")
        self.assertEqual(params["subject"], {"toolCall": {"toolCallId": "c1"}})
        self.assertNotIn("toolCall", params)

    def test_permission_v1_reconstructs_the_tool_call_shape(self) -> None:
        """v1 hardwired permission to a tool call; v2 generalised it to a subject."""
        proxy, sent = self._proxy(1)
        asyncio.run(proxy.request_permission(
            "s1", "Run script", [{"optionId": "allow", "name": "Allow", "kind": "allow_once"}],
            subject={"toolCall": {"toolCallId": "c1"}}))
        params = sent[0][1]
        self.assertEqual(params["toolCall"]["toolCallId"], "c1")
        self.assertEqual(params["toolCall"]["title"], "Run script")
        self.assertNotIn("subject", params)


@unittest.skipUnless(_HAS_DEPS, "acp/pydantic/starlette not installed")
class TestWebSocketTransport(unittest.TestCase):
    """The transport a pod actually serves on."""

    def test_full_round_trip_over_websocket(self) -> None:
        from starlette.applications import Starlette
        from starlette.testclient import TestClient
        transport = _import("agentcore.acp.transport")

        bridge = FakeBridge()
        app = Starlette(routes=transport.acp_routes(lambda: bridge))

        with TestClient(app).websocket_connect("/acp") as ws:
            ws.send_json({
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": 2, "info": {"name": "t", "version": "1"}}})
            init = ws.receive_json()
            self.assertEqual(init["result"]["protocolVersion"], 2)

            ws.send_json({
                "jsonrpc": "2.0", "id": 2, "method": "session/new",
                "params": {"cwd": "/work"}})
            created = ws.receive_json()
            self.assertEqual(created["result"]["sessionId"], "s1")

            ws.send_json({
                "jsonrpc": "2.0", "id": 3, "method": "session/prompt",
                "params": {"sessionId": "s1",
                           "prompt": [{"type": "text", "text": "hello"}]}})
            answered = ws.receive_json()
            # v2 acknowledges; it does not report completion here.
            self.assertEqual(answered["result"], {})

    def test_error_comes_back_as_jsonrpc_error(self) -> None:
        from starlette.applications import Starlette
        from starlette.testclient import TestClient
        transport = _import("agentcore.acp.transport")

        app = Starlette(routes=transport.acp_routes(lambda: FakeBridge()))
        with TestClient(app).websocket_connect("/acp") as ws:
            ws.send_json({
                "jsonrpc": "2.0", "id": 1, "method": "session/new", "params": {}})
            reply = ws.receive_json()
            self.assertIn("error", reply)
            self.assertEqual(reply["error"]["code"], -32602)


if __name__ == "__main__":
    unittest.main()
