# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

# pylint: disable=C0114  # See tool doc-string.

__all__ = (
    "register",
)

from blmcp.tools_helpers import (
    toolcode_format_call,
    toolcode_load_from_filepath,
    toolcode_wrap_with_calling_convention,
)
from blmcp.tools_helpers.connection import send_code
from blmcp.tools.get_mesh_diagnostics_toolcode import Params
from mcp.server.fastmcp import FastMCP  # pylint: disable=import-error,no-name-in-module
from mcp.types import ToolAnnotations  # pylint: disable=import-error,no-name-in-module

_TOOL_CALL = toolcode_wrap_with_calling_convention(toolcode_load_from_filepath(__file__))


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Get Mesh Diagnostics",
            readOnlyHint=True,
        )
    )
    def get_mesh_diagnostics(
        name: str,
        evaluated: bool = True,
    ) -> dict[str, object]:
        """
        Return a topology / printability report for a mesh object.

        Answers "is this watertight / printable?" in one call: vert/edge/face
        counts; the triage of open boundary edges (holes/openings) vs
        non-manifold edges (>2 faces or wire) vs degenerate faces; the number
        of distinct boundary loops; an ``is_watertight`` flag; bmesh volume;
        world-space dimensions and bounding box; and whether scale is applied
        and normals are consistent.

        Useful before a boolean, before export, or after applying a modifier
        stack. With *evaluated* True (default) it reports the geometry you
        would export (modifiers applied); set it False to inspect the raw
        base mesh.
        """
        p = Params(name=name, evaluated=evaluated)
        code = toolcode_format_call(_TOOL_CALL, p)
        return send_code(code, strict_json=True)
