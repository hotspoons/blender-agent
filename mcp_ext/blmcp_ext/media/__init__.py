# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Media import/export tools extension.

One polymorphic ``media_io`` tool moves assets between the user and the
Blender scene: import meshes/vectors/images/audio from a jailed media
folder, export the scene or named objects to any format Blender ships an
exporter for. The jail is the agent's per-session media folder when run
through the agent (injected), or a global folder for standalone MCP
clients.
"""

__all__ = (
    "BLMEDIA_PARENT_DIR",
    "register",
    "skills_dir",
)

import os

_HERE = os.path.dirname(os.path.abspath(__file__))

# Inserted into sys.path inside Blender so `import blmedia` resolves.
BLMEDIA_PARENT_DIR = _HERE


def skills_dir() -> str:
    return os.path.join(_HERE, "skills")


def register(mcp) -> None:
    from . import tools
    tools.register(mcp)
