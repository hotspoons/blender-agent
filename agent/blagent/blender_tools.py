# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Direct, in-process invocation of the ``blmcp`` tool surface.

The agent harness shares a process with ``blmcp`` and calls its tools
as plain Python — no MCP protocol on this path. The same ``FastMCP``
registry instance can optionally be exposed over streamable-HTTP MCP
(see ``app.py``), so MCP clients and the agent see an identical surface.

Tool discovery mirrors ``blmcp.main`` exactly: every public module in
``blmcp.tools`` with a ``register()`` hook.
"""

__all__ = (
    "BlenderTool",
    "build_blender_registry",
    "load_initial_instructions",
)

import json
import os

from typing import Any

import yaml

from mcp.server.fastmcp import FastMCP

from .tools import Tool, ToolContext, ToolResult


def _build_fastmcp() -> FastMCP:
    """
    Build the shared ``FastMCP`` instance with all blmcp tools registered.
    """
    mcp = FastMCP("blender-mcp", instructions=load_initial_instructions())

    # Shared with `blmcp.main`: core tools + optional tools extensions
    # (e.g. blender-mcp-extensions' rigging toolset) + skills subsystem.
    from blmcp.registry import register_all_tools
    register_all_tools(mcp)
    return mcp


def load_initial_instructions() -> str:
    """
    Return blmcp's ``initial_instructions`` prompt text.
    """
    import blmcp

    data_dir = os.path.join(os.path.dirname(os.path.abspath(blmcp.__file__)), "data")
    with open(os.path.join(data_dir, "prompts.yml"), encoding="utf-8") as fh:
        prompts = yaml.safe_load(fh)
    return str(prompts["initial_instructions"])


class BlenderTool(Tool):
    """
    One blmcp tool projected into the agent registry, dispatched
    in-process through the shared ``FastMCP`` instance.
    """

    def __init__(
            self,
            mcp: FastMCP,
            name: str,
            description: str,
            schema: dict[str, Any],
            destructive: bool,
            volatile: bool = False,
    ) -> None:
        self._mcp = mcp
        self.name = name
        self.description = description
        self._schema = schema
        self.destructive = destructive
        self.volatile = volatile

    def input_schema(self) -> dict[str, Any]:
        return self._schema

    async def call(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        result = await self._mcp.call_tool(self.name, args)

        # The SDK returns either a content-block sequence or a
        # ``(content_blocks, structured)`` tuple depending on version.
        blocks: list[Any]
        structured: object = None
        if isinstance(result, tuple):
            blocks, structured = result
        elif isinstance(result, dict):
            blocks, structured = [], result
        else:
            blocks = list(result)

        data: object = structured
        media_ids: list[str] = []
        texts: list[str] = []
        for block in blocks:
            kind = getattr(block, "type", "")
            if kind == "text":
                texts.append(block.text)
            elif kind == "image":
                media_id = ctx.media.register_base64(
                    block.data,
                    mime=block.mimeType or "image/png",
                    label=self.name,
                )
                media_ids.append(media_id)
        if data is None and texts:
            joined = "\n".join(texts)
            try:
                data = json.loads(joined)
            except ValueError:
                data = joined

        return ToolResult(
            summary=_summarize(self.name, data, media_ids),
            data=data,
            media_ids=media_ids,
        )


def _summarize(name: str, data: object, media_ids: list[str]) -> str:
    """
    Short tool-card status line derived from the result payload.
    """
    if media_ids:
        return "{:s}: produced {:d} image(s) [{:s}]".format(name, len(media_ids), ", ".join(media_ids))
    if isinstance(data, dict):
        status = data.get("status")
        message = data.get("message")
        if status == "error" and message:
            first = str(message).strip().splitlines()[-1]
            return "error: {:s}".format(first[:160])
        if status is not None:
            return "{:s}: {:s}".format(name, str(status))
    text = json.dumps(data) if not isinstance(data, str) else data
    text = " ".join(text.split())
    return "{:s}: {:s}".format(name, text[:160] or "done")


async def build_blender_registry() -> tuple[FastMCP, list[Tool]]:
    """
    Return the shared ``FastMCP`` instance and the blmcp tools wrapped
    for the agent registry. Async because tool listing is async in the
    SDK.
    """
    mcp = _build_fastmcp()
    tools: list[Tool] = []
    for spec in await mcp.list_tools():
        annotations = spec.annotations
        destructive = bool(annotations.destructiveHint) if annotations is not None else False
        # Read-only tools are scene queries: their results are volatile
        # (stale after the next edit) and age out of the context harder.
        volatile = bool(annotations.readOnlyHint) if annotations is not None else False
        tools.append(BlenderTool(
            mcp,
            name=spec.name,
            description=spec.description or "",
            schema=spec.inputSchema,
            destructive=destructive,
            volatile=volatile,
        ))
    return mcp, tools
