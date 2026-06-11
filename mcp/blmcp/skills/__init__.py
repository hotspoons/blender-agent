# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Core skills subsystem.

Skills are knowledge documents (not executable tools): folders in the
Anthropic-standard layout — one directory per skill holding a ``SKILL.md``
(YAML frontmatter ``name``/``description`` + markdown body) and any
ancillary files (scripts, references, templates) beside it. The model
reads a skill and applies it itself, typically via ``execute_blender_code``;
nothing in a skill is imported into the server runtime.

Sources, indexed at startup (and on demand via refresh):

- the drop folder (``~/.config/blender-mcp/skills`` by default) — drop a
  collection in, it is parsed on the next startup;
- directories and git repos listed in the config file
  (``~/.config/blender-mcp/skills.json``) — repos are cloned/pulled into a
  local cache at index time;
- collections bundled by tools extensions (registered via
  :func:`register_extension_skills`).
"""

__all__ = (
    "Skill",
    "ensure_index",
    "get_index",
    "register_extension_skills",
)

from .index import (
    Skill,
    ensure_index,
    get_index,
    register_extension_skills,
)
