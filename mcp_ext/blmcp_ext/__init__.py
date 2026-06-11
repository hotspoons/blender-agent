# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
``blmcp_ext``: optional tools extensions for the Blender MCP server.

Each subpackage is one extension (entry point in the
``blender_mcp.extensions`` group) exposing ``register(mcp)`` for its MCP
tools and optionally ``skills_dir()`` for a bundled skill collection.
Extensions make complex Blender workflows available to agents as
deterministic toolsets instead of large programming exercises.
"""

__all__ = ()
