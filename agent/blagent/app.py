# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Starlette application: static web UI, the agent control-plane
WebSocket, the local-model reverse-tunnel WebSocket, media serving, and
the optional MCP-over-HTTP exposure of the same tool registry.

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
``turn_done``, ``config``, ``local_llm_status``, ``error`` - see the
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
            "local_llm": runtime.local_llm.public_status(),
        })

    async def instance_update(request: Request) -> JSONResponse:
        """
        Update the instance label (browser tab title). The add-on posts
        here from save/load handlers so the title follows the open
        .blend file.
        """
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid JSON"}, status_code=400)
        runtime.instance_title = str(body.get("title", ""))[:200]
        await runtime.emit({"type": "instance", **runtime.instance_info()})
        return JSONResponse({"ok": True})

    async def media_upload(request: Request) -> JSONResponse:
        """
        Accept a pasted/dropped image (raw body) and register it in the
        session's media library. ``session_id`` of ``new`` creates a
        session. Returns ``{"session_id", "id"}``.
        """
        session_id = request.path_params["session_id"]
        if session_id == "new":
            session_id = runtime.new_session()
        mime = request.headers.get("content-type", "application/octet-stream")
        if not mime.startswith("image/"):
            return JSONResponse({"error": "only image attachments are supported"}, status_code=415)
        body = await request.body()
        if len(body) > 8 * 1024 * 1024:
            return JSONResponse({"error": "attachment too large (8 MiB max)"}, status_code=413)
        library = runtime._get_or_load_session(session_id).media  # pylint: disable=protected-access
        media_id = library.register_bytes(body, mime=mime, label="user attachment")
        return JSONResponse({"session_id": session_id, "id": media_id})

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
                "local_llm": runtime.local_llm.public_status(),
                "instance": runtime.instance_info(),
            })
            while True:
                data = await ws.receive_json()
                await _handle_control(runtime, ws, data)
        except WebSocketDisconnect:
            pass
        finally:
            pump_task.cancel()
            runtime.unsubscribe(queue)

    async def ws_local_llm(ws: WebSocket) -> None:
        await ws.accept()
        await runtime.local_llm.connect(ws)
        await runtime.emit({"type": "local_llm_status", **runtime.local_llm.public_status()})
        try:
            while True:
                data = await ws.receive_json()
                await runtime.local_llm.handle_message(data)
                if data.get("type") == "model_info":
                    await runtime.emit({"type": "local_llm_status", **runtime.local_llm.public_status()})
        except WebSocketDisconnect:
            pass
        finally:
            await runtime.local_llm.disconnect()
            await runtime.emit({"type": "local_llm_status", **runtime.local_llm.public_status()})

    routes = [
        Route("/", index),
        Route("/healthz", healthz),
        Route("/media/{session_id}/{media_id}", media),
        Route("/upload/{session_id}", media_upload, methods=["POST"]),
        Route("/instance", instance_update, methods=["POST"]),
        WebSocketRoute("/ws", ws_control),
        WebSocketRoute("/ws/local-llm", ws_local_llm),
        Mount("/static", app=StaticFiles(directory=_WEB_DIR), name="static"),
    ]

    # Optional OpenAI-compatible front end (BLENDER_AGENT_CHAT_API=1):
    # API-only chat with per-client sessions, media both ways, and tool
    # calls as non-standard properties. Raises at startup when the
    # required remote-LLM env vars are missing.
    from . import chat_api
    if chat_api.enabled():
        chat_api.configure(runtime)
        routes = chat_api.routes(runtime) + routes

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
            attachments = [str(m) for m in data.get("attachments", []) if m]
            session_id = await runtime.send_user_message(
                str(data.get("session_id", "")),
                str(data.get("content", "")),
                media_ids=attachments or None,
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
        elif msg_type == "list_models":
            await ws.send_json(await _list_models(runtime, data))
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


async def _list_models(runtime: AgentRuntime, data: dict[str, Any]) -> dict[str, Any]:
    """
    Proxy ``GET {endpoint}/models`` so the settings dialog can populate
    its model combo box (the browser cannot reach arbitrary endpoints
    cross-origin). Uses the supplied API key, falling back to the
    stored one when the endpoint matches the saved configuration.
    Errors are reported in-band; this must never break the socket.
    """
    import httpx

    endpoint = str(data.get("endpoint", "")).rstrip("/")
    api_key = str(data.get("api_key", ""))
    if not endpoint:
        return {"type": "models", "endpoint": endpoint, "models": []}
    config = runtime.store.config
    if not api_key and endpoint == config.endpoint.rstrip("/"):
        api_key = config.api_key

    headers = {}
    if api_key:
        headers["Authorization"] = "Bearer {:s}".format(api_key)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get("{:s}/models".format(endpoint), headers=headers)
        if response.status_code >= 400:
            return {
                "type": "models",
                "endpoint": endpoint,
                "models": [],
                "error": "endpoint returned {:d}{:s}".format(
                    response.status_code,
                    " (API key required?)" if response.status_code in (401, 403) else "",
                ),
            }
        payload = response.json()
        models = sorted(
            str(item.get("id", ""))
            for item in payload.get("data", [])
            if isinstance(item, dict) and item.get("id")
        )
        return {"type": "models", "endpoint": endpoint, "models": models}
    except (httpx.HTTPError, ValueError) as ex:
        return {"type": "models", "endpoint": endpoint, "models": [], "error": str(ex)}
