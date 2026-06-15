# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

# pylint: disable=C0114  # See tool doc-string.

__all__ = (
    "register",
)

from typing import Any

import os

from blmcp.tools_helpers import (
    toolcode_format_call,
    toolcode_load_from_filepath,
    toolcode_wrap_with_calling_convention,
)
from blmcp.tools_helpers.connection import send_code
from blmcp.tools.get_object_detail_summary_toolcode import Params as _ObjectParams
from blmcp.tools.get_mesh_diagnostics_toolcode import Params as _MeshParams
from mcp.server.fastmcp import FastMCP  # pylint: disable=import-error,no-name-in-module
from mcp.types import ToolAnnotations  # pylint: disable=import-error,no-name-in-module

_DIR = os.path.dirname(os.path.abspath(__file__))


def _load(stem: str) -> str:
    """Load and wrap the ``<stem>_toolcode.py`` payload for bridge dispatch."""
    return toolcode_wrap_with_calling_convention(
        toolcode_load_from_filepath(os.path.join(_DIR, stem + ".py")))


_OBJECTS = _load("get_objects_summary")
_LAYOUT = _load("get_screenshot_of_window_as_json")
_OBJECT = _load("get_object_detail_summary")
_MESH = _load("get_mesh_diagnostics")

_VERBS = ("objects", "object", "mesh", "layout")


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Scene inspection",
            readOnlyHint=True,
        )
    )
    def scene(verb: str, args: dict[str, Any]) -> dict[str, object]:
        """
        Read the live scene — the inspect-before-acting entry point. One
        tool, verb-dispatched (args in {}):

        - scene("objects", {}) — the scene's collection hierarchy and
          their objects (name, type, parent, data name, selection,
          visibility) plus nested child collections. START HERE.
        - scene("object", {name}) — structured detail for one object:
          type, transforms, parent, children, modifiers, constraints,
          materials, visibility, data-block name, collections.
        - scene("mesh", {name, evaluated?}) — topology / printability
          report: vert/edge/face counts, holes vs non-manifold vs
          degenerate triage, boundary loops, is_watertight, volume,
          world dimensions/bbox, scale-applied and normals-consistent
          flags. evaluated defaults true (modifiers applied); pass
          false for the raw base mesh.
        - scene("layout", {}) — JSON of the window layout, areas, active
          object, and selection (no pixels; use capture(...) for an image).

        Run `welcome` first if you have not this session.
        """
        a = args if isinstance(args, dict) else {}
        if verb == "objects":
            return send_code(toolcode_format_call(_OBJECTS, None), strict_json=True)
        if verb == "layout":
            return send_code(toolcode_format_call(_LAYOUT, None), strict_json=True)
        if verb == "object":
            name = a.get("name")
            if not name:
                return {"error": "scene('object', {'name': ...}) requires 'name'"}
            return send_code(
                toolcode_format_call(_OBJECT, _ObjectParams(name=str(name))),
                strict_json=True)
        if verb == "mesh":
            name = a.get("name")
            if not name:
                return {"error": "scene('mesh', {'name': ..., 'evaluated'?: bool}) requires 'name'"}
            p = _MeshParams(name=str(name), evaluated=bool(a.get("evaluated", True)))
            return send_code(toolcode_format_call(_MESH, p), strict_json=True)
        return {"error": "unknown verb {!r}; valid: {!r}".format(verb, list(_VERBS))}
