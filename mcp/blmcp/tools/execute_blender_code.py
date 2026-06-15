# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

# pylint: disable=C0114  # See tool doc-string.

__all__ = (
    "register",
)

from blmcp.tools_helpers.blender_cli import run_blender_cli, synced_blend_for_cli
from blmcp.tools_helpers.connection import send_code
from mcp.server.fastmcp import FastMCP  # pylint: disable=import-error,no-name-in-module
from mcp.types import ToolAnnotations  # pylint: disable=import-error,no-name-in-module


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Execute Python Code",
            destructiveHint=True,
        )
    )
    def execute_blender_code(code: str, blend_file: str | None = None) -> dict[str, object]:
        """
        Execute Python code in Blender. With full access to ``bpy``; to
        return data, assign a JSON-serialisable dict to a variable named
        ``result``.

        Without *blend_file* the code runs in the connected interactive
        Blender instance (deferred completion via ``check_is_finished``
        is supported here). Pass *blend_file* to instead open that file
        with ``blender --background`` and run the code in a one-shot
        background process (no deferred completion).
        """
        if blend_file:
            # LLM-generated code may return non-JSON-serializable values
            # (e.g. Blender objects), handled by `run_blender_cli` via `default=repr`.
            with synced_blend_for_cli(blend_file) as synced_path:
                value = run_blender_cli(synced_path, code)
                assert isinstance(value, dict), \
                    "Expected dict from `run_blender_cli`, got {!r}".format(type(value))
                return value
        # Not strict: LLM-generated code may return non-JSON-serializable values
        # (e.g. Blender objects). Use `repr` as a fallback instead of erroring.
        return send_code(code, strict_json=False)
