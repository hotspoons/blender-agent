# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

# pylint: disable=C0114  # See tool doc-strings.

__all__ = (
    "register",
)

import os

from mcp.server.fastmcp import FastMCP  # pylint: disable=import-error,no-name-in-module
from mcp.types import ToolAnnotations  # pylint: disable=import-error,no-name-in-module

from blmcp.skills import ensure_index

# Ancillary files above this size are listed but not returned inline.
_FILE_SIZE_CAP = 256 * 1024


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        annotations=ToolAnnotations(
            title="List Skills",
            readOnlyHint=True,
        )
    )
    def skills_list(refresh: bool = False) -> dict[str, object]:
        """
        List every available skill (name + one-line description) and the
        sources they were indexed from.

        Skills are proven recipes for complex Blender workflows (rigging,
        modeling, repair, ...) with sample code YOU apply via
        ``execute_blender_code`` — read one with ``skills_read`` before
        attempting work it covers. Run the ``welcome`` tool first if you
        have not yet this session.

        Set ``refresh=True`` to re-scan folders and re-sync skill git repos.
        """
        index = ensure_index(refresh=refresh)
        return {
            "skills": [
                {"name": s.name, "description": s.description, "source": s.source}
                for s in sorted(index.skills.values(), key=lambda s: s.name)
            ],
            "sources": index.sources,
        }

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Search Skills",
            readOnlyHint=True,
        )
    )
    def skills_search(query: str, max_results: int = 8) -> dict[str, object]:
        """
        Rank skills against a natural-language *query* (task description,
        keywords). Returns name + description; follow up with
        ``skills_read`` on the best match.

        ALWAYS search before non-trivial geometry, rigging, texturing or
        repair work — skills encode deterministic recipes and their gotchas.
        A miss returns the FULL catalog (it is small) — pick by
        description instead of giving up.
        """
        index = ensure_index()
        matches = index.search(query, max_results=max_results)
        if not matches:
            return {
                "matches": [],
                "note": "no keyword match for {!r}; the full catalog is "
                        "small — pick the closest by description".format(query),
                "all_skills": [
                    {"name": s.name, "description": s.description}
                    for s in sorted(index.skills.values(), key=lambda s: s.name)
                ],
            }
        return {
            "matches": [
                {"name": s.name, "description": s.description,
                 "keywords": s.keywords, "source": s.source}
                for s in matches
            ],
        }

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Read Skill",
            readOnlyHint=True,
        )
    )
    def skills_read(name: str, file: str | None = None) -> dict[str, object]:
        """
        Read a skill's SKILL.md (default) or one of its ancillary files
        (``file`` = relative path from ``skills_read(name)``'s file list).

        The skill body contains instructions and sample code — execute the
        code yourself via ``execute_blender_code``, adapting names/params
        to the scene; nothing runs automatically.
        """
        index = ensure_index()
        skill = index.skills.get(name)
        if skill is None:
            close = index.search(name, max_results=3)
            result: dict[str, object] = {
                "error": "unknown skill {!r}".format(name),
                "did_you_mean": [s.name for s in close],
            }
            if not close:
                result["all_skills"] = [
                    {"name": s.name, "description": s.description}
                    for s in sorted(index.skills.values(), key=lambda s: s.name)
                ]
            return result
        if file is None:
            return {
                "name": skill.name,
                "source": skill.source,
                "body": skill.body(),
                "files": skill.files(),
            }

        target = os.path.abspath(os.path.join(skill.path, file))
        if not target.startswith(os.path.abspath(skill.path) + os.sep):
            return {"error": "file path escapes the skill directory"}
        if not os.path.isfile(target):
            return {"error": "no such file {!r} in skill {!r}".format(file, name)}
        if os.path.getsize(target) > _FILE_SIZE_CAP:
            return {"error": "file too large ({:d} bytes, cap {:d})".format(
                os.path.getsize(target), _FILE_SIZE_CAP)}
        try:
            with open(target, encoding="utf-8") as fh:
                content = fh.read()
        except UnicodeDecodeError:
            return {"error": "file is not utf-8 text"}
        return {"name": skill.name, "file": file, "content": content}
