# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Shared helper for attaching rendered images to tool results.

Used by the ``render_*_to_path`` tools: after a successful render, the
image file is fetched back through the bridge (downscaled to fit the
MCP message size limit, see ``tools/_image_fetch_toolcode.py``) and
returned as an ``ImageContent`` block alongside the JSON response, so
vision-capable agents can see what they rendered.
"""

__all__ = (
    "response_with_image_blocks",
)

import json
import os

from blmcp.tools_helpers import (
    toolcode_format_call,
    toolcode_load_from_filepath,
    toolcode_wrap_with_calling_convention,
)
from blmcp.tools_helpers.connection import send_code
from mcp.types import ImageContent, TextContent  # pylint: disable=import-error,no-name-in-module

_TOOLS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")

_IMAGE_FETCH_CALL = toolcode_wrap_with_calling_convention(toolcode_load_from_filepath(
    os.path.join(_TOOLS_DIR, "_image_fetch.py")))


def response_with_image_blocks(response: dict[str, object]) -> "list[TextContent | ImageContent]":
    """
    Build content blocks for a render-style *response*: the response
    JSON first (wire-compatible with the previous dict-only return),
    then the rendered image as an attachment when the render succeeded.
    Image-fetch failures are silently dropped - the render result
    itself is what matters.
    """
    from blmcp.tools._image_fetch_toolcode import Params as ImageFetchParams

    blocks: "list[TextContent | ImageContent]" = [
        TextContent(type="text", text=json.dumps(response)),
    ]
    result = response.get("result")
    if (
            response.get("status") == "ok"
            and isinstance(result, dict)
            and result.get("status") == "ok"
            and result.get("filepath")
    ):
        fetch_params = ImageFetchParams(filepath=str(result["filepath"]))
        fetch = send_code(toolcode_format_call(_IMAGE_FETCH_CALL, fetch_params), strict_json=True)
        fetch_result = fetch.get("result")
        if (
                fetch.get("status") == "ok"
                and isinstance(fetch_result, dict)
                and fetch_result.get("status") == "ok"
                and fetch_result.get("image_base64")
        ):
            blocks.append(ImageContent(
                type="image",
                data=str(fetch_result["image_base64"]),
                mimeType="image/png",
            ))
    return blocks
