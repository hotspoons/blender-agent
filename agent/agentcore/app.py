# SPDX-FileCopyrightText: 2026 agentcore contributors
#
# SPDX-License-Identifier: MIT OR Apache-2.0

"""
Starlette application: static web UI, the agent control-plane
WebSocket, the local-model reverse-tunnel WebSocket, and media serving.

Domain-agnostic. The web UI is served from an ordered list of *web
roots* (``LayeredStaticFiles``): a domain build overlays its own files
(extension module, branding, viewers) on top of the generic shell, and
``create_app`` accepts ``extra_routes`` so a build can mount extra
endpoints (e.g. an OpenAI-compatible facade) without this module
knowing about them.

Control-plane protocol (JSON over ``/ws``):

Client -> server:
    ``{"type": "chat", "session_id": "", "content": "..."}``
    ``{"type": "objectives", "session_id": "", "objectives": [{"text", "acceptance"}], "max_rounds"?}``
    ``{"type": "draft_objectives", "session_id": "", "goal": "..."}``  -> emits objectives_draft
    ``{"type": "update_objectives", "session_id": "", "objectives": [...]}``  -> edit a live run
    ``{"type": "inject", "agent_id": "...", "content": "...", "mode": "now"|"after_round"}``
    ``{"type": "interrupt_worker", "agent_id": "..."}``   -> promote a queued injection to land now
    ``{"type": "stop_worker", "agent_id": "..."}``        -> cancel a runaway worker
    ``{"type": "set_autonomy_level", "session_id": "", "level": "ask"|"yolo"|"orchestrator"|"swarm"}``
    ``{"type": "new_session"}``
    ``{"type": "load_session", "id": ...}``
    ``{"type": "delete_session", "id": ...}``
    ``{"type": "set_config", ...partial config...}``
    ``{"type": "confirm", "session_id": ..., "call_id": ..., "approve": true}``
    ``{"type": "elicit_response", "session_id": ..., "elicit_id": ..., "choices": [...], "text": "..."}``
    ``{"type": "abort", "session_id": ...}``

Server -> client: ``hello``, ``sessions``, ``session_loaded``,
``user_record``, ``token``, ``assistant_done``, ``tool_status``,
``turn_done``, ``config``, ``local_llm_status``, ``error`` - see the
handlers below for shapes.
"""

__all__ = (
    "DEFAULT_WEB_ROOT",
    "LayeredStaticFiles",
    "create_app",
)

import os

from typing import Any, Sequence

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from agentcore.acp.bridge import RuntimeBridge
from agentcore.acp.transport import acp_routes
from agentcore.runtime import AgentRuntime

# The generic shell shipped with agentcore. A domain build overlays its
# own root ahead of this one (see ``create_app(web_roots=...)``).
DEFAULT_WEB_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


class LayeredStaticFiles(StaticFiles):
    """
    Serve ``/static`` from an ordered list of roots, first match wins.
    Lets a domain build overlay its own files (extension, branding,
    viewers) on top of the generic shell without copying the shell.
    ``StaticFiles`` already searches ``all_directories`` in order, so we
    just seed it with the full list.
    """

    def __init__(self, roots: Sequence[str]) -> None:
        super().__init__(directory=roots[0], check_dir=False)
        self.all_directories = list(roots)


def _index_path(web_roots: Sequence[str]) -> str:
    """First root that carries an ``index.html`` (a domain overlay wins)."""
    for root in web_roots:
        candidate = os.path.join(root, "index.html")
        if os.path.isfile(candidate):
            return candidate
    return os.path.join(web_roots[0], "index.html")


def create_app(
        runtime: AgentRuntime,
        *,
        web_roots: "Sequence[str] | None" = None,
        extra_routes: "list[Any] | None" = None,
) -> Starlette:
    """
    Build the ASGI app around *runtime*.

    *web_roots* is the ordered static search path (default: the generic
    agentcore shell alone). *extra_routes* are prepended to the route
    table so a domain build can mount its own endpoints.
    """
    roots = list(web_roots) if web_roots else [DEFAULT_WEB_ROOT]
    index_path = _index_path(roots)

    async def index(_request: Request) -> FileResponse:
        return FileResponse(index_path)

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
        Accept a pasted/dropped attachment (raw body) and register it in
        the session's media library. ``session_id`` of ``new`` creates a
        session. Returns ``{"session_id", "id"}``.

        Images keep the short-id scheme (``i<N>``, fed to vision models).
        Everything else (meshes, audio, documents — the ``X-File-Name``
        header carries the original name) lands in the session's media
        folder under its own collision-suffixed filename, where the
        ``media_io`` tool can import it into the scene.
        """
        session_id = request.path_params["session_id"]
        if session_id == "new":
            session_id = runtime.new_session()
        from urllib.parse import unquote
        mime = request.headers.get("content-type", "application/octet-stream")
        filename = unquote(request.headers.get("x-file-name", ""))
        body = await request.body()
        if len(body) > 64 * 1024 * 1024:
            return JSONResponse({"error": "attachment too large (64 MiB max)"}, status_code=413)
        library = runtime._get_or_load_session(session_id).media  # pylint: disable=protected-access
        if mime.startswith("image/") and not mime.startswith("image/svg"):
            media_id = library.register_bytes(body, mime=mime, label=filename or "user attachment")
        else:
            from agentcore.media import mime_for_name
            name = filename or "attachment.bin"
            media_id = library.register_named_bytes(
                body, name,
                mime=mime if mime != "application/octet-stream" else mime_for_name(name))
        return JSONResponse({"session_id": session_id, "id": media_id})

    async def media(request: Request) -> Response:
        session_id = request.path_params["session_id"]
        media_id = request.path_params["media_id"]
        item = runtime._get_or_load_session(session_id).media.get(media_id)  # pylint: disable=protected-access
        if item is None or not os.path.isfile(item.path):
            return Response(status_code=404)
        return FileResponse(item.path, media_type=item.mime)

    async def worker_media(request: Request) -> Response:
        # In-process worker (orchestrator mode) tool-produced media: served
        # from the worker's own jail rather than the main session library.
        agent_id = request.path_params["agent_id"]
        media_id = request.path_params["media_id"]
        item = runtime.worker_media_library(agent_id).get(media_id)
        if item is None or not os.path.isfile(item.path):
            return Response(status_code=404)
        return FileResponse(item.path, media_type=item.mime)

    async def ws_control(ws: WebSocket) -> None:
        await ws.accept()
        queue = runtime.subscribe()

        import asyncio

        # Serialize every send: the pump task (event stream) and the
        # request handler both write this socket, and two concurrent
        # send_json -> drain() trip websockets' concurrent-drain
        # AssertionError, killing the connection. One lock = one writer
        # draining at a time.
        send_lock = asyncio.Lock()
        _raw_send = ws.send_json

        async def _locked_send(event: Any) -> None:
            async with send_lock:
                await _raw_send(event)

        ws.send_json = _locked_send  # type: ignore[method-assign]

        async def pump() -> None:
            while True:
                event = await queue.get()
                await ws.send_json(event)

        pump_task = asyncio.create_task(pump())
        try:
            await ws.send_json({
                "type": "hello",
                "config": runtime.store.config.as_public(),
                "profile": runtime.public_ui_profile(),
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
        Route("/worker-media/{agent_id}/{media_id}", worker_media),
        Route("/upload/{session_id}", media_upload, methods=["POST"]),
        Route("/instance", instance_update, methods=["POST"]),
        WebSocketRoute("/ws", ws_control),
        WebSocketRoute("/ws/local-llm", ws_local_llm),
        Mount("/static", app=LayeredStaticFiles(roots), name="static"),
    ]

    # ACP (v2 draft + v1) on the main port, so any ACP-capable client or
    # orchestrator can drive this agent without a second listener. A pod that
    # wants ACP isolated from the UI binds it a port of its own as well; see
    # the agent's --acp-port.
    routes.extend(acp_routes(lambda: RuntimeBridge(runtime)))

    # A domain build injects its own endpoints here (e.g. blagent's
    # OpenAI-compatible chat facade), prepended so they take precedence.
    if extra_routes:
        routes = list(extra_routes) + routes

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
        elif msg_type == "objectives":
            # Autonomy mode: pursue a set of objectives across rounds.
            raw = data.get("objectives", [])
            objectives = [
                {"id": str(o.get("id", "")), "text": str(o.get("text", "")),
                 "acceptance": str(o.get("acceptance", ""))}
                for o in raw if isinstance(o, dict) and str(o.get("text", "")).strip()
            ]
            if not objectives:
                await ws.send_json({"type": "error", "message": "no objectives provided"})
            else:
                mr = data.get("max_rounds")
                session_id = await runtime.run_autonomy_turn(
                    str(data.get("session_id", "")),
                    objectives,
                    max_rounds=int(mr) if isinstance(mr, int) else None,
                )
                await ws.send_json({"type": "autonomy_accepted", "session_id": session_id})
        elif msg_type == "update_objectives":
            # Mid-run: edit/append the live objectives; the orchestrator picks
            # them up next round and interjects them to in-process workers now.
            sid = str(data.get("session_id", ""))
            raw = data.get("objectives", [])
            objectives = [
                {"text": str(o.get("text", "")), "acceptance": str(o.get("acceptance", ""))}
                for o in raw if isinstance(o, dict) and str(o.get("text", "")).strip()
            ]
            payload = runtime.update_objectives(sid, objectives)
            if payload is None:
                await ws.send_json({
                    "type": "error", "message": "no live autonomy run to update for this session"})
            else:
                await runtime.emit({
                    "type": "objectives_update", "session_id": sid, "objectives": payload})
        elif msg_type == "draft_objectives":
            # Guided intake: turn a one-line goal into draft objectives. Returns
            # the session id (created when absent) so the client adopts it — the
            # planning card + persisted history then resolve to this session.
            goal = str(data.get("goal", "")).strip()
            if goal:
                sid = runtime.draft_objectives(str(data.get("session_id", "")), goal)
                await ws.send_json({"type": "draft_accepted", "session_id": sid})
        elif msg_type == "inject":
            # Voice of god: queue a message into a running worker's context
            # (lands at its next round boundary).
            agent_id = str(data.get("agent_id", ""))
            ok = runtime.inject_into_worker(
                agent_id,
                str(data.get("content", "")),
                now=str(data.get("mode", "")) == "now",
            )
            if not ok:
                await ws.send_json({
                    "type": "error",
                    "message": "no live worker {!r} to inject into".format(agent_id),
                })
        elif msg_type == "interrupt_worker":
            # Step two of injection: promote the queued message to land now.
            ok = runtime.interrupt_worker(str(data.get("agent_id", "")))
            if not ok:
                await ws.send_json({
                    "type": "error",
                    "message": "no live worker {!r} to interrupt".format(data.get("agent_id", "")),
                })
        elif msg_type == "stop_worker":
            # Cancel a runaway worker (cooperative abort / subprocess kill).
            ok = runtime.stop_worker(str(data.get("agent_id", "")))
            if not ok:
                await ws.send_json({
                    "type": "error",
                    "message": "no live worker {!r} to stop".format(data.get("agent_id", "")),
                })
        elif msg_type == "set_autonomy_level":
            # The composer's autonomy slider: minimal | yolo | orchestrator | swarm.
            # Scoped to the sender's session, so a second window (or an ACP
            # client) on this agent keeps its own level. The echo carries
            # session_id for that reason - see store.js.
            public = runtime.set_autonomy_level(
                str(data.get("session_id", "")), str(data.get("level", "")))
            await runtime.emit({"type": "config", "config": public})
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
                # Backend-owned orchestrator history: every run's durable view in
                # transcript order, plus the current LIVE view (active run/draft).
                # The frontend holds no autonomy state of its own — it projects these.
                "autonomy_runs": runtime.session_autonomy_runs(session_id),
                "autonomy_view": runtime.session_autonomy_view(session_id),
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
        elif msg_type == "elicit_response":
            # The user's answer to an ask_user elicitation.
            ok = runtime.resolve_elicit(
                str(data.get("session_id", "")),
                str(data.get("elicit_id", "")),
                {
                    "choices": [str(c) for c in (data.get("choices") or [])],
                    "text": str(data.get("text", "")),
                    "cancelled": bool(data.get("cancelled", False)),
                },
            )
            if not ok:
                await ws.send_json({"type": "error", "message": "no pending elicitation for that id"})
        elif msg_type == "approve_agent_tool":
            name = str(data.get("name", ""))
            approve = bool(data.get("approve", False))
            ok = runtime.approve_agent_tool(name, approve)
            await runtime.emit({
                "type": "agent_tool_approval",
                "name": name,
                "approved": bool(approve and ok),
                "ok": ok,
            })
            if not ok:
                await ws.send_json({
                    "type": "error",
                    "message": "no agent tool {!r} awaiting approval".format(name)})
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
