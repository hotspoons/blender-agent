# SPDX-FileCopyrightText: 2026 agentcore contributors
#
# SPDX-License-Identifier: MIT OR Apache-2.0

"""
The HTTP transport for the portable ToolBackend boundary (see ``backend.py``
and docs/AGENT_CORE.md). Two pieces:

- ``HttpToolBackend(base_url)`` — drives a tool service over the documented
  OpenAPI 3.1 REST contract, so a domain can run in any language / process /
  host. Satisfies the same ``ToolBackend`` protocol as ``PythonToolBackend``,
  so the harness stays transport-blind.
- ``serve_backend(backend)`` — the reference handler: a small Starlette app
  that re-exposes ANY in-process ``ToolBackend`` over the same REST contract.
  Dogfoods the contract end to end and makes it testable in-process.
"""

__all__ = ("HttpToolBackend", "serve_backend", "TOOL_BACKEND_OPENAPI")

import dataclasses
from typing import Any

from .backend import MediaRef, ToolBackend, ToolCallResult, ToolSpec, _DefaultBackendMixin


class HttpToolBackend(_DefaultBackendMixin):
    """A ToolBackend that speaks the REST contract to a remote tool service."""

    def __init__(self, base_url: str, *, api_key: str = "",
                 client: "Any" = None, timeout: float = 120.0) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {"Authorization": "Bearer " + api_key} if api_key else {}
        self._client = client          # injected (tests / shared pool) or lazy
        self._owns_client = client is None
        self._timeout = timeout
        self._caps: "set[str] | None" = None

    def _url(self, path: str) -> str:
        return self._base + path

    def _http(self) -> "Any":
        if self._client is None:
            import httpx
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def list_tools(self) -> list[ToolSpec]:
        r = await self._http().get(self._url("/tools"), headers=self._headers)
        r.raise_for_status()
        out = []
        for t in r.json().get("tools", []):
            out.append(ToolSpec(
                name=t["name"], description=t.get("description", ""),
                input_schema=t.get("input_schema") or {},
                destructive=bool(t.get("destructive")), read_only=bool(t.get("read_only"))))
        return out

    async def call_tool(self, name: str, args: dict[str, Any], *,
                        session_id: str, media: "Any" = None) -> ToolCallResult:
        try:
            r = await self._http().post(
                self._url("/tools/" + name), headers=self._headers,
                json={"args": args, "session_id": session_id})
        except Exception as ex:  # pylint: disable=broad-except
            return ToolCallResult(summary="", status="error", error="transport error: " + str(ex))
        if r.status_code >= 400:
            return ToolCallResult(summary="", status="error",
                                  error="backend returned HTTP {:d}".format(r.status_code))
        d = r.json()
        return ToolCallResult(
            summary=d.get("summary", ""), data=d.get("data"),
            status=d.get("status", "ok"), error=d.get("error", ""),
            media=[MediaRef(id=m.get("id", ""), mime=m.get("mime", ""),
                            data_url=m.get("data_url")) for m in (d.get("media") or [])])

    async def fetch_capabilities(self) -> set[str]:
        try:
            r = await self._http().get(self._url("/capabilities"), headers=self._headers)
            self._caps = set(r.json().get("capabilities", [])) if r.status_code < 400 else set()
        except Exception:  # pylint: disable=broad-except
            self._caps = set()
        return self._caps

    def capabilities(self) -> set[str]:
        # Sync per the protocol; populated by open()/fetch_capabilities().
        return set(self._caps or set())

    async def state_probe(self, *, session_id: str) -> "str | None":
        try:
            r = await self._http().get(self._url("/state"), headers=self._headers,
                                       params={"session_id": session_id})
            if r.status_code >= 400:
                return None
            return r.json().get("state")
        except Exception:  # pylint: disable=broad-except
            return None

    async def read_media(self, media_id: str) -> "tuple[bytes, str] | None":
        try:
            r = await self._http().get(self._url("/media/" + media_id), headers=self._headers)
            if r.status_code >= 400:
                return None
            return r.content, r.headers.get("content-type", "application/octet-stream")
        except Exception:  # pylint: disable=broad-except
            return None

    async def open(self) -> None:
        await self.fetch_capabilities()
        if "surface" in (self._caps or set()):
            try:
                await self._http().post(self._url("/surface/open"), headers=self._headers)
            except Exception:  # pylint: disable=broad-except
                pass

    async def close(self) -> None:
        if "surface" in (self._caps or set()):
            try:
                await self._http().post(self._url("/surface/close"), headers=self._headers)
            except Exception:  # pylint: disable=broad-except
                pass
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None


# --------------------------------------------------------------------------
# Reference handler — re-expose any ToolBackend over the REST contract
# --------------------------------------------------------------------------

def serve_backend(backend: ToolBackend, *, api_key: str = "") -> "Any":
    """A Starlette app exposing *backend* over the OpenAPI tool-backend contract.
    The Blender build (or any domain) can run this to serve a Python backend to
    a remote ``HttpToolBackend``; tests point an in-process client at it."""
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse, Response
    from starlette.routing import Route

    def authorized(request: "Any") -> bool:
        return (not api_key) or request.headers.get("authorization") == "Bearer " + api_key

    def _deny() -> "Any":
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    async def tools(request: "Any") -> "Any":
        if not authorized(request):
            return _deny()
        specs = await backend.list_tools()
        return JSONResponse({"tools": [dataclasses.asdict(s) for s in specs]})

    async def call(request: "Any") -> "Any":
        if not authorized(request):
            return _deny()
        body = await request.json()
        result = await backend.call_tool(
            request.path_params["name"], body.get("args") or {},
            session_id=str(body.get("session_id", "")))
        return JSONResponse({
            "summary": result.summary, "data": result.data,
            "status": result.status, "error": result.error,
            "media": [dataclasses.asdict(m) for m in result.media]})

    async def state(request: "Any") -> "Any":
        if not authorized(request):
            return _deny()
        s = await backend.state_probe(session_id=request.query_params.get("session_id", ""))
        return JSONResponse({"state": s})

    async def media(request: "Any") -> "Any":
        if not authorized(request):
            return _deny()
        got = await backend.read_media(request.path_params["id"])
        if got is None:
            return Response(status_code=404)
        data, mime = got
        return Response(data, media_type=mime)

    async def surface_open(request: "Any") -> "Any":
        await backend.open()
        return JSONResponse({"ok": True})

    async def surface_close(request: "Any") -> "Any":
        await backend.close()
        return JSONResponse({"ok": True})

    async def capabilities(request: "Any") -> "Any":
        return JSONResponse({"capabilities": sorted(backend.capabilities())})

    async def healthz(_request: "Any") -> "Any":
        return JSONResponse({"status": "ok"})

    async def openapi(_request: "Any") -> "Any":
        return JSONResponse(TOOL_BACKEND_OPENAPI)

    return Starlette(routes=[
        Route("/tools", tools),
        Route("/tools/{name}", call, methods=["POST"]),
        Route("/state", state),
        Route("/media/{id}", media),
        Route("/surface/open", surface_open, methods=["POST"]),
        Route("/surface/close", surface_close, methods=["POST"]),
        Route("/capabilities", capabilities),
        Route("/healthz", healthz),
        Route("/openapi.json", openapi),
    ])


# The OpenAPI 3.1 schema for the contract — served at /openapi.json so a backend
# in any language can be generated/validated against it.
TOOL_BACKEND_OPENAPI: dict[str, Any] = {
    "openapi": "3.1.0",
    "info": {"title": "agentcore tool-backend", "version": "1.0.0",
             "description": "Portable tool-backend contract for the agent harness."},
    "paths": {
        "/tools": {"get": {"summary": "List tools",
                           "responses": {"200": {"description": "tool specs"}}}},
        "/tools/{name}": {"post": {
            "summary": "Call a tool", "parameters": [
                {"name": "name", "in": "path", "required": True, "schema": {"type": "string"}}],
            "requestBody": {"content": {"application/json": {"schema": {"type": "object",
                "properties": {"args": {"type": "object"}, "session_id": {"type": "string"}}}}}},
            "responses": {"200": {"description": "tool result"}}}},
        "/state": {"get": {"summary": "Project state probe (optional)",
                           "parameters": [{"name": "session_id", "in": "query",
                                           "schema": {"type": "string"}}],
                           "responses": {"200": {"description": "state text"}}}},
        "/media/{id}": {"get": {"summary": "Fetch media bytes (optional)",
                                "parameters": [{"name": "id", "in": "path", "required": True,
                                                "schema": {"type": "string"}}],
                                "responses": {"200": {"description": "raw bytes"},
                                              "404": {"description": "no such media"}}}},
        "/surface/open": {"post": {"summary": "Bring the compute surface up (optional)",
                                   "responses": {"200": {"description": "ok"}}}},
        "/surface/close": {"post": {"summary": "Tear the compute surface down (optional)",
                                    "responses": {"200": {"description": "ok"}}}},
        "/capabilities": {"get": {"summary": "Advertised optional capabilities",
                                  "responses": {"200": {"description": "capability list"}}}},
        "/healthz": {"get": {"summary": "Liveness", "responses": {"200": {"description": "ok"}}}},
    },
    "components": {"schemas": {
        "ToolSpec": {"type": "object", "required": ["name", "input_schema"], "properties": {
            "name": {"type": "string"}, "description": {"type": "string"},
            "input_schema": {"type": "object"},
            "destructive": {"type": "boolean"}, "read_only": {"type": "boolean"}}},
        "MediaRef": {"type": "object", "required": ["id"], "properties": {
            "id": {"type": "string"}, "mime": {"type": "string"},
            "data_url": {"type": ["string", "null"]}}},
        "ToolCallResult": {"type": "object", "required": ["summary", "status"], "properties": {
            "summary": {"type": "string"}, "data": {},
            "status": {"type": "string", "enum": ["ok", "error"]}, "error": {"type": "string"},
            "media": {"type": "array", "items": {"$ref": "#/components/schemas/MediaRef"}}}},
    }},
}
