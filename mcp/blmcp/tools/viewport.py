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
from blmcp.tools.jump_to_view3d_object_by_name_toolcode import Params as _FocusObjParams
from blmcp.tools.jump_to_view3d_object_data_by_name_toolcode import Params as _FocusDataParams
from blmcp.tools.jump_to_tab_by_name_toolcode import Params as _TabNameParams
from blmcp.tools.jump_to_tab_by_space_type_toolcode import Params as _TabSpaceParams
from mcp.server.fastmcp import FastMCP  # pylint: disable=import-error,no-name-in-module
from mcp.types import ToolAnnotations  # pylint: disable=import-error,no-name-in-module

_DIR = os.path.dirname(os.path.abspath(__file__))


def _load(stem: str) -> str:
    """Load and wrap the ``<stem>_toolcode.py`` payload for bridge dispatch."""
    return toolcode_wrap_with_calling_convention(
        toolcode_load_from_filepath(os.path.join(_DIR, stem + ".py")))


_FOCUS_OBJ = _load("jump_to_view3d_object_by_name")
_FOCUS_DATA = _load("jump_to_view3d_object_data_by_name")
_TAB_NAME = _load("jump_to_tab_by_name")
_TAB_SPACE = _load("jump_to_tab_by_space_type")


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Viewport / workspace navigation",
            destructiveHint=True,
        )
    )
    def viewport(verb: str, args: dict[str, Any]) -> dict[str, object]:
        """
        Drive what the viewport shows. One tool, verb-dispatched
        (args in {}):

        - viewport("focus", {name, target?: "object"|"data",
          allow_edits?}) — move the 3D viewport onto an object.
          target "object" (default) matches by object name; "data"
          matches by data-block name. With allow_edits true the object
          may be un-hidden and its collections enabled to reveal it.
        - viewport("tab", {name? | space_type?, allow_edits?}) — switch
          the active workspace. Pass name for an exact tab, or
          space_type to match the first workspace whose main area is
          that type; with allow_edits and space_type, a new workspace is
          created if none matches.
        """
        a = args if isinstance(args, dict) else {}
        if verb == "focus":
            name = a.get("name")
            if not name:
                return {"error": "viewport('focus', {'name': ..., 'target'?: 'object'|'data', "
                                 "'allow_edits'?: bool}) requires 'name'"}
            allow = bool(a.get("allow_edits", False))
            target = a.get("target", "object")
            if target == "object":
                return send_code(toolcode_format_call(
                    _FOCUS_OBJ, _FocusObjParams(name=str(name), allow_edits=allow)),
                    strict_json=True)
            if target == "data":
                return send_code(toolcode_format_call(
                    _FOCUS_DATA, _FocusDataParams(name=str(name), allow_edits=allow)),
                    strict_json=True)
            return {"error": "target must be 'object' or 'data'"}
        if verb == "tab":
            name = a.get("name")
            space_type = a.get("space_type")
            if name:
                return send_code(toolcode_format_call(
                    _TAB_NAME, _TabNameParams(name=str(name))), strict_json=True)
            if space_type:
                return send_code(toolcode_format_call(
                    _TAB_SPACE, _TabSpaceParams(space_type=str(space_type),
                                                allow_edits=bool(a.get("allow_edits", False)))),
                    strict_json=True)
            return {"error": "viewport('tab', ...) requires 'name' or 'space_type'"}
        return {"error": "unknown verb {!r}; valid: ['focus', 'tab']".format(verb)}
