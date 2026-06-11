# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Rigging tools extension.

Deterministic rigging for LLM agents: the model selects and parameterizes
skills; the bundled ``blrig`` library (which runs inside Blender) owns
every coordinate-level decision. Exposes ``rigging_*`` MCP tools and a
bundled skill collection documenting when each applies.
"""

__all__ = (
    "BLRIG_PARENT_DIR",
    "register",
    "skills_dir",
)

import os

_HERE = os.path.dirname(os.path.abspath(__file__))

# Inserted into sys.path inside Blender so `import blrig` resolves; server
# and Blender share a filesystem (the bridge is local TCP).
BLRIG_PARENT_DIR = _HERE


def skills_dir() -> str:
    """
    Bundled skill collection (Anthropic SKILL.md layout), registered into
    the core skills index.
    """
    return os.path.join(_HERE, "skills")


def register(mcp) -> None:
    from . import tools
    tools.register(mcp)
