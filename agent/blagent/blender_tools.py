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
    "blender_profile",
    "build_blender_registry",
    "load_initial_instructions",
    "make_backend",
)

import json
import os

from typing import Any

import yaml

from mcp.server.fastmcp import FastMCP

from agentcore.profile import AgentProfile
from agentcore.tools import Tool, ToolContext, ToolResult

_SYSTEM_PROMPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "system_prompt.md")


def blender_profile() -> AgentProfile:
    """The Blender build's profile: branding + the Blender system prompt. The
    default until a YAML build overrides it."""
    try:
        with open(_SYSTEM_PROMPT_PATH, encoding="utf-8") as fh:
            system_prompt = fh.read()
    except OSError:
        system_prompt = ""
    return AgentProfile(
        noun="scene",
        chat_field_prefix="blender",
        title="Blender Agent",
        brand_word="Blender",
        brand_rest=" Agent",
        welcome_word="Blender",
        welcome_rest=" Agent",
        welcome_body="Connected to your Blender session through the MCP tool surface.",
        welcome_hint='Try: "what\'s in my scene?" or "make the selected mesh manifold".',
        composer_placeholder="Ask the Blender agent…",
        swarm_blurb="Parallel workers, each its own headless Blender, merged at the end.",
        system_prompt=system_prompt,
    )


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
            read_only: bool = False,
    ) -> None:
        self._mcp = mcp
        self.name = name
        self.description = description
        self._schema = schema
        self.destructive = destructive
        self.volatile = volatile
        self.read_only = read_only

    def input_schema(self) -> dict[str, Any]:
        return self._schema

    async def call(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        if self.name == "media_io":
            # Jail the media tool to THIS session's media folder. The
            # injection happens here — server-side of the LLM — so the
            # model never chooses the root.
            args = {**args, "args": {**(args.get("args") or {}), "jail_root": ctx.media.directory}}

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

        if self.name == "media_io":
            # Exports were written into the session media folder by
            # Blender directly; index them so the UI can serve/preview
            # them and the user can download.
            ctx.media.refresh()
            payload = data.get("result") if isinstance(data, dict) else None
            for name in (payload or {}).get("jail_files", []) if isinstance(payload, dict) else []:
                if ctx.media.get(name) is not None and name not in media_ids:
                    media_ids.append(name)

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
    from blmcp.registry import strip_welcome_nudge

    mcp = _build_fastmcp()
    tools: list[Tool] = []
    for spec in await mcp.list_tools():
        annotations = spec.annotations
        destructive = bool(annotations.destructiveHint) if annotations is not None else False
        # Read-only tools are scene queries: their results are volatile
        # (stale after the next edit) and age out of the context harder.
        # readOnlyHint also marks them as cheap introspection for the
        # weighted round budget.
        read_only = bool(annotations.readOnlyHint) if annotations is not None else False
        volatile = read_only
        tools.append(BlenderTool(
            mcp,
            name=spec.name,
            # Strip the client-facing "call welcome first" nudge: our agents are
            # pre-welcomed (the welcome content is injected into their prompt)
            # and have no welcome tool, so the nudge is a contradiction. MCP
            # clients still see it — they read the server's tool descriptions,
            # not this wrapped copy.
            description=strip_welcome_nudge(spec.description or ""),
            schema=spec.inputSchema,
            destructive=destructive,
            volatile=volatile,
            read_only=read_only,
        ))
    return mcp, tools


async def make_backend(**_options: Any) -> "Any":
    """
    The Blender build's ``ToolBackend`` factory, referenced from ``agent.yaml``
    (``backend.factory: blagent.blender_tools:make_backend``). Wraps the blmcp
    tool surface in a ``PythonToolBackend`` and wires the ground-truth scene
    probe (``scene("objects")``) used by the autonomy evaluator/auditor.

    Assumes a Blender bridge is reachable (tool *calls* need it); spawning the
    headless surface remains the launcher's job. Extra YAML ``options`` are
    accepted and ignored here for forward-compatibility.
    """
    import tempfile
    from agentcore.backend import PythonToolBackend
    from agentcore.media import MediaLibrary

    _mcp, tools = await build_blender_registry()
    by_name = {t.name: t for t in tools}

    async def _probe(session_id: str) -> str:
        tool = by_name.get("scene")
        if tool is None:
            return "(scene unavailable)"
        media = MediaLibrary(tempfile.mkdtemp(prefix="probe_"))
        try:
            result = await tool.call(
                ToolContext(media=media, session_id=session_id),
                {"verb": "objects", "args": {}})
        except Exception as ex:  # pylint: disable=broad-except
            return "(scene probe failed: {:s})".format(str(ex))
        data = result.data if result.data is not None else result.summary
        text = data if isinstance(data, str) else json.dumps(data, default=str)
        return text[:6000]

    return PythonToolBackend(tools, probe=_probe)
