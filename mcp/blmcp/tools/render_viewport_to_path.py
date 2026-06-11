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
from blmcp.tools_helpers.image_fetch import response_with_image_blocks
from blmcp.tools.render_viewport_to_path_toolcode import Params
from mcp.server.fastmcp import FastMCP  # pylint: disable=import-error,no-name-in-module
from mcp.types import ImageContent, TextContent, ToolAnnotations  # pylint: disable=import-error,no-name-in-module

_TOOL_CALL = toolcode_wrap_with_calling_convention(toolcode_load_from_filepath(__file__))


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Render Viewport to Path",
            readOnlyHint=True,
        ),
        structured_output=False,
    )
    def render_viewport_to_path(output_path: str) -> "list[TextContent | ImageContent]":
        """
        Render the current scene to *output_path* using current render settings.

        On success the rendered image is also attached to the result
        (downscaled to fit the message size limit) so vision-capable
        agents can see the render without a separate screenshot call.
        """
        p = Params(output_path=output_path)
        code = toolcode_format_call(_TOOL_CALL, p)
        return response_with_image_blocks(send_code(code, strict_json=True))
