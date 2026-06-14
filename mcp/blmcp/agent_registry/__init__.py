# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Agent capability registry — the dynamic "Tier B" library of tools (and,
via the core skills index, skills) that agents author at runtime to
improve themselves, discovered by SEARCH rather than by polluting the
tool surface.

- :mod:`.store` — filesystem persistence + search for authored tools.
- :mod:`.sandbox` — the import jail (AST author-time gate + frame-scoped
  runtime guard) and the elicitation policy classifier.
- :mod:`.loader` — compose an authored tool into a guarded bridge payload
  and run it through the same transport as ``execute_blender_code``.

The MCP meta-tools that expose all this live in
``blmcp.tools.agent_registry`` (auto-registered for both the server and
the in-process agent).
"""

__all__ = (
    "loader",
    "sandbox",
    "store",
)

from . import loader
from . import sandbox
from . import store
