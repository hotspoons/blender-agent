# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Starlette application: static web UI, the agent control-plane
WebSocket, the WebLLM reverse-tunnel WebSocket, media serving, and the
optional MCP-over-HTTP exposure of the same tool registry.

Control-plane protocol (JSON over ``/ws``):

Client -> server:
    ``{"type": "chat", "session_id": "", "content": "..."}``
    ``{"type": "new_session"}``
    ``{"type": "load_session", "id": ...}``
    ``{"type": "delete_session", "id": ...}``
    ``{"type": "set_config", ...partial config...}``
    ``{"type": "confirm", "session_id": ..., "call_id": ..., "approve": true}``
    ``{"type": "abort", "session_id": ...}``

Server -> client: ``hello``, ``sessions``, ``session_loaded``,
``user_record``, ``token``, ``assistant_done``, ``tool_status``,
``turn_done``, ``config``, ``webllm_status``, ``error`` - see the
handlers below for shapes.
"""

__all__ = (
    "create_app",
)

import os

from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from .runtime import AgentRuntime

_WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


def create_app(runtime: AgentRuntime) -> Starlette:
    """
    Build the ASGI app around *runtime*.
    """

    async def index(_request: Request) -> FileResponse:
        return FileResponse(os.path.join(_WEB_DIR, "index.html"))

    async def healthz(_request: Request) -> JSONResponse:
        return JSONResponse({
            "status": "ok",
            "webllm": runtime.webllm.public_status(),
        })

    async def media(request: Request) -> Response:
        session_id = request.path_params["session_id"]
        media_id = request.path_params["media_id"]
        item = runtime._get_or_load_session(session_id).media.get(media_id)  # pylint: disable=protected-access
        if item is None or not os.path.isfile(item.path):
            return Response(status_code=404)
        return FileResponse(item.path, media_type=item.mime)

    async def ws_control(ws: WebSocket) -> None:
        await ws.accept()
        queue = runtime.subscribe()

        async def pump() -> None:
            while True:
                event = await queue.get()
                await ws.send_json(event)

        import asyncio

        pump_task = asyncio.create_task(pump())
        try:
            await ws.send_json({
                "type": "hello",
                "config": runtime.store.config.as_public(),
                "sessions": runtime.list_sessions(),
                "webllm": runtime.webllm.public_status(),
            })
            while True:
                data = await ws.receive_json()
                await _handle_control(runtime, ws, data)
        except WebSocketDisconnect:
            pass
        finally:
            pump_task.cancel()
            runtime.unsubscribe(queue)

    async def ws_webllm(ws: WebSocket) -> None:
        await ws.accept()
        await runtime.webllm.connect(ws)
        await runtime.emit({"type": "webllm_status", **runtime.webllm.public_status()})
        try:
            while True:
                data = await ws.receive_json()
                await runtime.webllm.handle_message(data)
                if data.get("type") == "model_info":
                    await runtime.emit({"type": "webllm_status", **runtime.webllm.public_status()})
        except WebSocketDisconnect:
            pass
        finally:
            await runtime.webllm.disconnect()
            await runtime.emit({"type": "webllm_status", **runtime.webllm.public_status()})

    routes = [
        Route("/", index),
        Route("/healthz", healthz),
        Route("/media/{session_id}/{media_id}", media),
        WebSocketRoute("/ws", ws_control),
        WebSocketRoute("/ws/webllm", ws_webllm),
        Mount("/static", app=StaticFiles(directory=_WEB_DIR), name="static"),
    ]
    return Starlette(routes=routes)


async def _handle_control(runtime: AgentRuntime, ws: WebSocket, data: dict[str, Any]) -> None:
    """
    Dispatch one control-plane message. Errors are reported on the
    socket rather than raised, so a bad message never kills the
    connection.
    """
    msg_type = data.get("type")
    try:
        if msg_type == "chat":
            session_id = await runtime.send_user_message(
                str(data.get("session_id", "")),
                str(data.get("content", "")),
            )
            await ws.send_json({"type": "chat_accepted", "session_id": session_id})
        elif msg_type == "new_session":
            session_id = runtime.new_session()
            await ws.send_json({"type": "session_loaded", "session_id": session_id, "records": [], "media": []})
            await runtime.emit({"type": "sessions", "sessions": runtime.list_sessions()})
        elif msg_type == "load_session":
            session_id = str(data.get("id", ""))
            await ws.send_json({
                "type": "session_loaded",
                "session_id": session_id,
                "records": runtime.session_records(session_id),
                "media": runtime.session_media(session_id),
            })
        elif msg_type == "delete_session":
            runtime.delete_session(str(data.get("id", "")))
            await runtime.emit({"type": "sessions", "sessions": runtime.list_sessions()})
        elif msg_type == "list_sessions":
            await ws.send_json({"type": "sessions", "sessions": runtime.list_sessions()})
        elif msg_type == "set_config":
            public = runtime.set_config({k: v for k, v in data.items() if k != "type"})
            await runtime.emit({"type": "config", "config": public})
        elif msg_type == "confirm":
            ok = runtime.confirm_tool(
                str(data.get("session_id", "")),
                str(data.get("call_id", "")),
                bool(data.get("approve", False)),
            )
            if not ok:
                await ws.send_json({"type": "error", "message": "no pending confirmation for that call"})
        elif msg_type == "abort":
            runtime.abort(str(data.get("session_id", "")))
        elif msg_type == "ping":
            await ws.send_json({"type": "pong"})
        else:
            await ws.send_json({"type": "error", "message": "unknown message type: {!r}".format(msg_type)})
    except RuntimeError as ex:
        await ws.send_json({"type": "error", "message": str(ex)})
