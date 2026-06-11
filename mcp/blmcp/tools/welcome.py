# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

# pylint: disable=C0114  # See tool doc-string.

__all__ = (
    "register",
)

import os

from mcp.server.fastmcp import FastMCP  # pylint: disable=import-error,no-name-in-module
from mcp.types import ToolAnnotations  # pylint: disable=import-error,no-name-in-module

_PROMPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "welcome_prompt.md")


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Welcome (run first)",
            readOnlyHint=True,
        )
    )
    def welcome() -> dict[str, object]:
        """
        RUN THIS FIRST, once per session, before any other tool.

        Returns the working instructions this Blender toolset is designed
        around: inspection-before-action workflow, API verification, the
        skills library (`skills_search`/`skills_read`), code-execution
        conventions, and any installed extension toolsets. Adopt the
        returned instructions for the rest of the session.
        """
        with open(_PROMPT_PATH, encoding="utf-8") as fh:
            prompt = fh.read()

        # Tell the agent what is actually installed right now.
        from blmcp.skills import ensure_index
        index = ensure_index()
        skills = sorted(index.skills)
        return {
            "instructions": prompt,
            "available_skills": skills,
            "n_skills": len(skills),
        }
