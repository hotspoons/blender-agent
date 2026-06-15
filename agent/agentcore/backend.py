# SPDX-FileCopyrightText: 2026 agentcore contributors
#
# SPDX-License-Identifier: MIT OR Apache-2.0

"""
The portable boundary between the core agent harness and a domain (Blender,
or anything else). The core drives a domain ONLY through ``ToolBackend`` — it
never imports domain code. A backend is implemented either in-process
(``PythonToolBackend``) or over the documented HTTP/OpenAPI contract
(``HttpToolBackend``, see ``http_backend.py``); both satisfy the same protocol,
so the harness is transport-blind.

See docs/AGENT_CORE.md for the full design + the REST contract.
"""

__all__ = (
    "BackendTool",
    "MediaRef",
    "PythonToolBackend",
    "ToolBackend",
    "ToolCallResult",
    "ToolSpec",
    "registry_from_backend",
)

import dataclasses
from typing import Any, Protocol, runtime_checkable

from .media import MediaLibrary
from .tools import Tool, ToolContext, ToolError, ToolRegistry, ToolResult


@dataclasses.dataclass
class ToolSpec:
    """A tool the backend exposes, in transport-neutral form."""

    name: str
    description: str
    input_schema: dict[str, Any]
    destructive: bool = False
    read_only: bool = False


@dataclasses.dataclass
class MediaRef:
    """A piece of tool-produced media. ``data_url`` inlines bytes (HTTP); a
    Python backend that already wrote into the session library leaves it None
    and the id resolves there."""

    id: str
    mime: str = ""
    data_url: str | None = None


@dataclasses.dataclass
class ToolCallResult:
    summary: str
    data: Any = None
    media: list[MediaRef] = dataclasses.field(default_factory=list)
    status: str = "ok"          # "ok" | "error"
    error: str | None = None


@runtime_checkable
class ToolBackend(Protocol):
    """
    The one interface the harness uses to reach a domain. Required:
    ``list_tools`` + ``call_tool``. The rest are optional capabilities — a
    backend advertises what it supports via ``capabilities()`` and may no-op
    the others.
    """

    async def list_tools(self) -> list[ToolSpec]: ...

    async def call_tool(
        self, name: str, args: dict[str, Any], *,
        session_id: str, media: "MediaLibrary | None" = None,
    ) -> ToolCallResult: ...

    def capabilities(self) -> set[str]: ...           # {"probe","media","surface","swarm"}

    async def state_probe(self, *, session_id: str) -> "str | None": ...

    async def read_media(self, media_id: str) -> "tuple[bytes, str] | None": ...

    async def open(self) -> None: ...                 # bring the compute surface up

    async def close(self) -> None: ...                # tear it down


class _DefaultBackendMixin:
    """Neutral no-op implementations of the optional capabilities."""

    def capabilities(self) -> set[str]:
        return set()

    async def state_probe(self, *, session_id: str) -> "str | None":
        return None

    async def read_media(self, media_id: str) -> "tuple[bytes, str] | None":
        return None

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None


class PythonToolBackend(_DefaultBackendMixin):
    """
    In-process backend: wraps a list of core ``Tool`` objects (e.g. the Blender
    tool surface). Tools write media into the per-call session library exactly
    as before, so this is a zero-overhead pass-through. A domain provides one
    of these (plus, optionally, a probe / surface) as its binding.
    """

    def __init__(
            self,
            tools: list[Tool],
            *,
            probe: "Any" = None,           # async (session_id, media) -> str
            surface_open: "Any" = None,    # async () -> None
            surface_close: "Any" = None,   # async () -> None
    ) -> None:
        self._tools = {t.name: t for t in tools}
        self._probe = probe
        self._surface_open = surface_open
        self._surface_close = surface_close

    @property
    def tools(self) -> list[Tool]:
        """The wrapped core tools. The in-process runtime executes these
        directly (preserving the full ``ToolContext`` — confirm/elicit
        callbacks the transport-neutral ``call_tool`` cannot convey); the
        backend's role for the Python transport is probe + surface."""
        return list(self._tools.values())

    async def list_tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name=t.name, description=t.description, input_schema=t.input_schema(),
                destructive=t.destructive, read_only=t.read_only)
            for t in self._tools.values()
        ]

    async def call_tool(
            self, name: str, args: dict[str, Any], *,
            session_id: str, media: "MediaLibrary | None" = None,
    ) -> ToolCallResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolCallResult(summary="", status="error", error="unknown tool: " + name)
        ctx = ToolContext(media=media, session_id=session_id)  # type: ignore[arg-type]
        try:
            result = await tool.call(ctx, args)
        except ToolError as ex:
            return ToolCallResult(summary="", status="error", error=str(ex))
        return ToolCallResult(
            summary=result.summary, data=result.data,
            media=[MediaRef(id=m) for m in (result.media_ids or [])])

    def capabilities(self) -> set[str]:
        caps = {"media"}
        if self._probe is not None:
            caps.add("probe")
        if self._surface_open is not None or self._surface_close is not None:
            caps.add("surface")
        return caps

    async def state_probe(self, *, session_id: str) -> "str | None":
        if self._probe is None:
            return None
        return await self._probe(session_id)

    async def open(self) -> None:
        if self._surface_open is not None:
            await self._surface_open()

    async def close(self) -> None:
        if self._surface_close is not None:
            await self._surface_close()


class BackendTool(Tool):
    """
    Adapts one backend ``ToolSpec`` into a core ``Tool`` the engine can call.
    Routes the call through the backend and, for transports that return media
    inline (HTTP), ingests it into the session library so the existing
    media-by-id serving path is unchanged.
    """

    def __init__(self, backend: ToolBackend, spec: ToolSpec) -> None:
        self._backend = backend
        self._spec = spec
        self.name = spec.name
        self.description = spec.description
        self.destructive = spec.destructive
        self.read_only = spec.read_only

    def input_schema(self) -> dict[str, Any]:
        return self._spec.input_schema

    async def call(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        result = await self._backend.call_tool(
            self.name, args, session_id=ctx.session_id, media=ctx.media)
        if result.status == "error":
            raise ToolError(result.error or "tool failed")
        media_ids: list[str] = []
        for ref in result.media:
            if ref.data_url and ctx.media is not None:
                media_ids.append(ctx.media.register_data_url(ref.data_url, label=self.name))
            elif ref.id:
                media_ids.append(ref.id)
        return ToolResult(summary=result.summary, data=result.data, media_ids=media_ids)


async def registry_from_backend(
        backend: ToolBackend, extra: "list[Tool] | None" = None) -> ToolRegistry:
    """Build a ToolRegistry from a backend's tools plus any core/harness tools."""
    specs = await backend.list_tools()
    tools: list[Tool] = [BackendTool(backend, s) for s in specs]
    if extra:
        tools.extend(extra)
    return ToolRegistry(tools)
