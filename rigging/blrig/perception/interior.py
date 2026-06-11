# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interior test via raycast parity.
"""

__all__ = (
    "point_inside",
    "points_inside",
)

import bpy
import numpy as np

from . import _mesh

# Deliberately irrational-looking direction: avoids rays running along
# axis-aligned faces/edges, which break parity counting.
_RAY_DIR = np.array([0.285839, 0.570423, 0.770107], dtype=np.float64)
_RAY_DIR /= np.linalg.norm(_RAY_DIR)


def points_inside(obj: bpy.types.Object, points: list, max_hits: int = 4096) -> list[bool]:
    """
    Raycast-parity interior test for many world-space *points* at once.
    Requires a closed (watertight) mesh for meaningful results — gate with
    :func:`blrig.perception.mesh_health` first.
    """
    verts, tris = _mesh.mesh_arrays(obj)
    if len(tris) == 0:
        return [False] * len(points)
    bvh = _mesh.bvh_from_arrays(verts, tris)
    eps = max(_mesh.bbox_diagonal(verts) * 1e-6, 1e-12)

    results = []
    for p in points:
        origin = np.asarray(p, dtype=np.float64)
        hits = 0
        for _ in range(max_hits):
            location, _normal, _index, _dist = bvh.ray_cast(tuple(origin), tuple(_RAY_DIR))
            if location is None:
                break
            hits += 1
            origin = np.asarray(location, dtype=np.float64) + _RAY_DIR * eps
        results.append(hits % 2 == 1)
    return results


def point_inside(obj: bpy.types.Object, p) -> bool:
    """
    Raycast-parity interior test for one world-space point.
    """
    return points_inside(obj, [p])[0]
