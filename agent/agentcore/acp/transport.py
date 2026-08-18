# SPDX-FileCopyrightText: 2026 agentcore contributors
#
# SPDX-License-Identifier: MIT OR Apache-2.0

"""
Transports that carry the ACP dispatcher: WebSocket, Streamable HTTP, stdio.

``acp.connection.Connection`` moves already-decoded JSON-RPC messages over a
tiny ``Transport`` seam (``send`` / ``receive`` / ``close``), so each transport
here is just an adapter onto that seam. The SDK ships its own WS and HTTP
servers, but they bind an ``AcpServer`` to the v1 ``Agent`` interface, which is
exactly the part we replace -- so the adapters are ours while the framing stays
the SDK's.

**WebSocket is the transport to use for a pod.** Spec-compliant Streamable HTTP
wants HTTP/2, which uvicorn does not serve (the SDK's own docs say so); the HTTP
route here is a pragmatic single-shot fallback for clients that cannot open a
socket, and full duplex over it is a proxy/ingress concern.
"""

__all__ = (
    "BridgeFactory",
    "acp_routes",
    "serve_stdio",
)

import asyncio
import json
import logging
from typing import Any, Callable

from acp.connection import Connection
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from agentcore.acp.server import AcpConnection, AgentBridge

_log = logging.getLogger("agentcore.acp")

BridgeFactory = Callable[[], AgentBridge]


class _WebSocketTransport:
    """
    ``acp.Transport`` over a Starlette WebSocket.

    Sends are serialized behind a lock: the update pump and the request
    responder both write this socket, and two concurrent ``send_json`` ->
    ``drain()`` calls trip websockets' concurrent-drain assertion and kill the
    connection. The harness learned this the hard way on its own ``/ws``
    (see ``agentcore.app.ws_control``).
    """

    def __init__(self, ws: WebSocket) -> None:
        self._ws = ws
        self._lock = asyncio.Lock()
        self._closed = False

    async def send(self, message: "dict[str, Any]") -> None:
        if self._closed:
            return
        async with self._lock:
            await self._ws.send_text(json.dumps(message))

    async def receive(self) -> "dict[str, Any] | None":
        try:
            raw = await self._ws.receive_text()
        except (WebSocketDisconnect, RuntimeError):
            return None
        try:
            decoded = json.loads(raw)
        except ValueError:
            # A frame we cannot parse is not a reason to drop the session;
            # report it and keep listening.
            _log.warning("acp/ws: discarding unparseable frame")
            return await self.receive()
        return decoded if isinstance(decoded, dict) else None

    async def close(self) -> None:
        self._closed = True


def _bind(transport: Any, bridge: AgentBridge) -> "tuple[AcpConnection, Connection]":
    """Wire a dispatcher to a message-level ``Transport`` (WebSocket, HTTP)."""
    return _wire(bridge, lambda handler: Connection(handler, transport, listening=False))


def _bind_streams(
        writer: Any,
        reader: Any,
        bridge: AgentBridge,
) -> "tuple[AcpConnection, Connection]":
    """Wire a dispatcher to raw byte streams (stdio); Connection frames them."""
    return _wire(bridge, lambda handler: Connection(handler, writer, reader, listening=False))


def _wire(
        bridge: AgentBridge,
        make_connection: "Callable[[Any], Connection]",
) -> "tuple[AcpConnection, Connection]":
    """
    Tie the dispatcher and the connection together.

    They are mutually dependent -- ``Connection`` needs the handler at
    construction, and the dispatcher needs ``Connection`` to call the client
    back -- so the outbound half is attached immediately after the connection
    exists, and the handler closure never observes the gap because no message
    can arrive before ``main_loop`` starts (``listening=False``).
    """
    acp_conn = AcpConnection(bridge)

    async def handler(
            method: str,
            params: "Any | None",
            is_notification: bool,
    ) -> "Any | None":
        return await acp_conn.handle(
            method, params if isinstance(params, dict) else None, is_notification)

    connection = make_connection(handler)

    async def send_request(method: str, payload: "dict[str, Any]") -> Any:
        return await connection.send_request(method, payload)

    async def send_notification(method: str, payload: "dict[str, Any]") -> None:
        await connection.send_notification(method, payload)

    acp_conn.attach(send_request, send_notification)
    return acp_conn, connection


async def _serve_websocket(ws: WebSocket, bridge_factory: BridgeFactory) -> None:
    await ws.accept()
    transport = _WebSocketTransport(ws)
    acp_conn, connection = _bind(transport, bridge_factory())
    try:
        await connection.main_loop()
    except WebSocketDisconnect:
        pass
    except Exception:  # pylint: disable=broad-except
        _log.exception("acp/ws: connection failed")
    finally:
        await acp_conn.aclose()
        await connection.close()


class _SingleShotTransport:
    """
    ``acp.Transport`` for one request/response exchange over HTTP POST.

    One inbound message, then EOF. Any agent-initiated request has nowhere to
    go on this transport, so it fails fast rather than hanging: a client that
    needs permission prompts or elicitation must use the WebSocket route.
    """

    def __init__(self, message: "dict[str, Any]") -> None:
        self._inbound: "list[dict[str, Any]]" = [message]
        self.outbound: "list[dict[str, Any]]" = []
        self._done = asyncio.Event()

    async def send(self, message: "dict[str, Any]") -> None:
        self.outbound.append(message)
        if "id" in message and ("result" in message or "error" in message):
            self._done.set()

    async def receive(self) -> "dict[str, Any] | None":
        if self._inbound:
            return self._inbound.pop(0)
        await self._done.wait()
        return None

    async def close(self) -> None:
        self._done.set()

    async def wait(self, timeout: float) -> None:
        try:
            await asyncio.wait_for(self._done.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass


async def _serve_http(request: Request, bridge_factory: BridgeFactory) -> Response:
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None,
             "error": {"code": -32700, "message": "Parse error"}},
            status_code=400)
    if not isinstance(payload, dict):
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None,
             "error": {"code": -32600, "message": "Invalid request"}},
            status_code=400)

    transport = _SingleShotTransport(payload)
    acp_conn, connection = _bind(transport, bridge_factory())
    task = asyncio.create_task(connection.main_loop())
    try:
        await transport.wait(timeout=300.0)
    finally:
        await transport.close()
        task.cancel()
        await acp_conn.aclose()
        await connection.close()

    for message in transport.outbound:
        if "id" in message and ("result" in message or "error" in message):
            return JSONResponse(message)
    # A notification produces no response body.
    return Response(status_code=202)


def acp_routes(
        bridge_factory: BridgeFactory,
        prefix: str = "/acp",
) -> "list[Any]":
    """
    Starlette routes serving ACP.

    *bridge_factory* is called once per connection: a bridge holds
    per-connection state (which sessions are open, which client to notify), so
    sharing one across connections would cross-wire them.
    """

    async def ws_endpoint(ws: WebSocket) -> None:
        await _serve_websocket(ws, bridge_factory)

    async def http_endpoint(request: Request) -> Response:
        return await _serve_http(request, bridge_factory)

    return [
        WebSocketRoute(prefix, ws_endpoint),
        Route(prefix, http_endpoint, methods=["POST"]),
    ]


async def serve_stdio(bridge: AgentBridge) -> None:
    """
    Serve ACP over stdin/stdout -- the transport editors launch agents with.

    Nothing may be written to stdout but protocol frames, so a build using this
    must keep its logging on stderr.
    """
    from acp.stdio import stdio_streams

    # stdio_streams handles the posix/windows split; Connection wraps the raw
    # byte streams in its own ndjson framing when given a reader.
    reader, writer = await stdio_streams()
    acp_conn, connection = _bind_streams(writer, reader, bridge)
    try:
        await connection.main_loop()
    finally:
        await acp_conn.aclose()
        await connection.close()
