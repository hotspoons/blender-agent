# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Skills index adapter: exposes blmcp's global skill index to the agentcore
store (which is otherwise skills-index-agnostic — it ships a local scanner
by default). Injecting this gives the Blender build's agent the full blmcp
index: builtins, the drop folder, configured dirs/git repos, and
tools-extension collections.
"""

__all__ = ("BlmcpSkillIndex",)

from typing import Any


class BlmcpSkillIndex:
    """Adapts ``blmcp.skills`` to the ``AgentStore(skills_index=...)`` seam."""

    def register_source(self, name: str, path: str) -> None:
        from blmcp.skills import register_skills_source
        register_skills_source(name, path)

    def ensure(self, refresh: bool = False) -> Any:
        from blmcp.skills import ensure_index
        return ensure_index(refresh=refresh)
