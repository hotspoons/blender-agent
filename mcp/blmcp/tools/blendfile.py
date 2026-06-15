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
from blmcp.tools_helpers.blender_cli import run_blender_cli, synced_blend_for_cli
from blmcp.tools_helpers.connection import send_code
from mcp.server.fastmcp import FastMCP  # pylint: disable=import-error,no-name-in-module
from mcp.types import ToolAnnotations  # pylint: disable=import-error,no-name-in-module

_DIR = os.path.dirname(os.path.abspath(__file__))


def _load(stem: str) -> str:
    """Load and wrap the ``<stem>_toolcode.py`` payload for bridge dispatch."""
    return toolcode_wrap_with_calling_convention(
        toolcode_load_from_filepath(os.path.join(_DIR, stem + ".py")))


# Aspect -> toolcode stem. Each payload is parameter-less.
_ASPECTS = {
    "datablocks": "get_blendfile_summary_datablocks",
    "path": "get_blendfile_summary_path_info",
    "usage": "get_blendfile_summary_usage_guess",
    "missing": "get_blendfile_summary_missing_files",
    "libraries": "get_blendfile_summary_of_linked_libraries",
}
_TC = {aspect: _load(stem) for aspect, stem in _ASPECTS.items()}


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Blend-file summary",
            readOnlyHint=True,
        )
    )
    def blendfile(verb: str, args: dict[str, Any]) -> dict[str, object]:
        """
        Summarise a .blend file. The *verb* selects the aspect; pass
        ``blend_file`` in args to inspect a file on disk in a background
        Blender (``--background``) instead of the connected session.

        Aspects (args = {} for the live session, or {blend_file}):
        - blendfile("datablocks", {...}) — data-block counts, active
          workspace, render engine.
        - blendfile("path", {...}) — fast path/save-status/age/backups.
        - blendfile("usage", {...}) — guess primary use-cases
          (animation, modeling, rendering, ...) scored 0-100.
        - blendfile("missing", {...}) — external references missing from
          disk (images, libraries, fonts, sounds, clips, caches, sequences).
        - blendfile("libraries", {...}) — tree of directly and indirectly
          linked library files.
        """
        a = args if isinstance(args, dict) else {}
        tc = _TC.get(verb)
        if tc is None:
            return {"error": "unknown aspect {!r}; valid: {!r}".format(verb, list(_ASPECTS))}
        code = toolcode_format_call(tc, None)
        blend_file = a.get("blend_file")
        if blend_file:
            with synced_blend_for_cli(str(blend_file)) as synced_path:
                return run_blender_cli(synced_path, code)
        return send_code(code, strict_json=True)
