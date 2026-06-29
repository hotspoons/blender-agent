# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

# pylint: disable=C0114  # See tool doc-string.

__all__ = (
    "register",
)

from typing import Any

import json
import os

from blmcp.tools_helpers import (
    toolcode_format_call,
    toolcode_load_from_filepath,
    toolcode_wrap_with_calling_convention,
)
from blmcp.tools_helpers.connection import send_code
from blmcp.tools_helpers.image_fetch import response_with_image_blocks
from blmcp.tools.get_screenshot_of_window_as_image_toolcode import Params as _WinParams
from blmcp.tools.get_screenshot_of_area_as_image_toolcode import Params as _AreaParams
from blmcp.tools.render_viewport_to_path_toolcode import Params as _RenderParams
from blmcp.tools.render_thumbnail_to_path_toolcode import Params as _ThumbParams
from mcp.server.fastmcp import FastMCP  # pylint: disable=import-error,no-name-in-module
from mcp.types import ImageContent, TextContent, ToolAnnotations  # pylint: disable=import-error,no-name-in-module

_DIR = os.path.dirname(os.path.abspath(__file__))


def _load(stem: str) -> str:
    """Load and wrap the ``<stem>_toolcode.py`` payload for bridge dispatch."""
    return toolcode_wrap_with_calling_convention(
        toolcode_load_from_filepath(os.path.join(_DIR, stem + ".py")))


_WIN = _load("get_screenshot_of_window_as_image")
_AREA = _load("get_screenshot_of_area_as_image")
_RENDER = _load("render_viewport_to_path")
_THUMB = _load("render_thumbnail_to_path")


def _err(message: str) -> "list[TextContent | ImageContent]":
    return [TextContent(type="text", text=json.dumps({"error": message}))]


def _shot_blocks(response: dict[str, object]) -> "list[TextContent | ImageContent]":
    """Turn a screenshot toolcode response into a single image block."""
    if response.get("status") != "ok":
        raise RuntimeError(str(response.get("message", "Unknown error")))
    result = response["result"]
    assert isinstance(result, dict)
    if result.get("status") != "ok":
        raise RuntimeError(str(result.get("message", "Unknown error")))
    return [ImageContent(type="image", data=str(result["image_base64"]), mimeType="image/png")]


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Capture (screenshot / render)",
            readOnlyHint=True,
        ),
        structured_output=False,
    )
    def capture(verb: str, args: dict[str, Any]) -> "list[TextContent | ImageContent]":
        """
        See the scene as pixels. One tool, verb-dispatched (args in {}):

        - capture("screenshot", {scope?: "window"|"area", area_ui_type?,
          size_limit?}) — PNG of the Blender UI. scope defaults to
          "window"; for "area" pass area_ui_type (the area's ui_type,
          e.g. "VIEW_3D"). size_limit caps bytes (0 = MCP message limit).
        - capture("render", {path, quality?: "full"|"thumbnail"}) —
          render the scene to *path* and attach the image so vision
          agents see it. quality "full" (default) uses current render
          settings; "thumbnail" is a fast, low-quality preview.

        For deliverable files the user can download, prefer media_io(...)
        if the media extension is installed.
        """
        a = args if isinstance(args, dict) else {}
        if verb == "screenshot":
            scope = a.get("scope", "window")
            size = int(a.get("size_limit", 0) or 0)
            if scope == "window":
                code = toolcode_format_call(_WIN, _WinParams(size_limit_in_bytes=size))
                return _shot_blocks(send_code(code, strict_json=True))
            if scope == "area":
                area = a.get("area_ui_type")
                if not area:
                    return _err("capture('screenshot', {'scope': 'area', 'area_ui_type': ...}) "
                                "requires 'area_ui_type'")
                code = toolcode_format_call(
                    _AREA, _AreaParams(area_ui_type=area, size_limit_in_bytes=size))
                return _shot_blocks(send_code(code, strict_json=True))
            return _err("scope must be 'window' or 'area'")
        if verb == "render":
            path = a.get("path")
            if not path:
                return _err("capture('render', {'path': ..., 'quality'?: 'full'|'thumbnail'}) "
                            "requires 'path'")
            if a.get("quality") == "thumbnail":
                code = toolcode_format_call(_THUMB, _ThumbParams(output_path=str(path)))
            else:
                code = toolcode_format_call(_RENDER, _RenderParams(output_path=str(path)))
            return response_with_image_blocks(send_code(code, strict_json=True))
        return _err("unknown verb {!r}; valid: ['screenshot', 'render']".format(verb))
