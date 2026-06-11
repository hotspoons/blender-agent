# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Geometric perception: pure query functions over scene geometry.

Rules of this package:

- **No scene mutation.** Every function here is read-only; any bmesh copies
  are private and freed.
- **World space.** All returned coordinates are world-space unless noted.
- **JSON-serializable returns.** Plain dicts/lists/floats only, so results
  can cross the agent tool boundary verbatim.

These functions are trusted by every skill downstream — they are deliberately
over-tested (see ``tests/test_perception_*.py``).
"""

__all__ = (
    "contact_graph",
    "cross_sections",
    "loose_parts",
    "mesh_health",
    "part_obb",
    "point_inside",
    "points_inside",
    "symmetry_plane",
)

from .parts import contact_graph, loose_parts
from .health import mesh_health
from .interior import point_inside, points_inside
from .obb import part_obb
from .sections import cross_sections
from .symmetry import symmetry_plane
