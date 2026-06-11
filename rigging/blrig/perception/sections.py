# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Cross-section profiles along an axis (limb taper, joint-location candidates).
"""

__all__ = (
    "cross_sections",
)

import bpy
import numpy as np

from . import _mesh

_AXIS_BY_NAME = {
    "x": (1.0, 0.0, 0.0),
    "y": (0.0, 1.0, 0.0),
    "z": (0.0, 0.0, 1.0),
}


def _plane_basis(direction: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Orthonormal in-plane basis ``(e1, e2)`` with ``(e1, e2, direction)``
    right-handed.
    """
    helper = np.array([0.0, 0.0, 1.0]) if abs(direction[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    e1 = np.cross(helper, direction)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(direction, e1)
    return e1, e2


def cross_sections(
        obj: bpy.types.Object,
        axis="z",
        n: int = 16,
        part: dict | None = None,
) -> list[dict]:
    """
    Sample *n* planar cross-sections of *obj* uniformly along *axis*
    (``"x"``/``"y"``/``"z"`` or a world-space vector), optionally restricted
    to one loose *part*.

    Area and centroid come from Green's theorem over the oriented
    triangle/plane intersection segments — no loop assembly, robust to
    multiple loops and holes (hole loops contribute negative area). Signs
    are only meaningful on closed meshes with consistent outward normals.

    Each sample: ``t`` (0..1 along the sampled span), ``offset`` (world
    distance along axis from the first vertex), ``plane_point`` (world),
    ``area``, ``centroid`` (world, equals ``plane_point`` when empty),
    ``n_segments``.
    """
    direction = np.asarray(_AXIS_BY_NAME.get(axis, axis), dtype=np.float64)
    direction = direction / np.linalg.norm(direction)

    verts, tris = _mesh.mesh_arrays(obj)
    if part is not None:
        keep = np.zeros(len(verts), dtype=bool)
        keep[np.asarray(part["vert_indices"], dtype=np.int64)] = True
        tris = tris[np.all(keep[tris], axis=1)]
    if len(verts) == 0 or len(tris) == 0:
        return []

    proj = verts @ direction
    lo, hi = float(proj.min()), float(proj.max())
    span = hi - lo
    if span < 1e-12 or n < 1:
        return []

    e1, e2 = _plane_basis(direction)
    _areas, tri_normals = _mesh.tri_areas_normals(verts, tris)
    tri_proj = proj[tris]
    tri_lo = tri_proj.min(axis=1)
    tri_hi = tri_proj.max(axis=1)

    sections = []
    for i in range(n):
        t = (i + 0.5) / n
        offset = lo + t * span
        plane_point = verts.mean(axis=0) + (offset - float(verts.mean(axis=0) @ direction)) * direction

        # Nudge off exact vertex coordinates to dodge degenerate crossings.
        d_all = proj - offset
        if np.any(np.abs(d_all) < span * 1e-9):
            offset += span * 3e-9
            d_all = proj - offset

        candidates = np.flatnonzero((tri_lo < offset) & (tri_hi > offset))

        area = 0.0
        cx = 0.0
        cy = 0.0
        n_segments = 0
        for ti in candidates:
            tri = tris[ti]
            d = d_all[tri]
            pts = []
            for a in range(3):
                b = (a + 1) % 3
                if (d[a] > 0.0) != (d[b] > 0.0):
                    f = d[a] / (d[a] - d[b])
                    pts.append(verts[tri[a]] + f * (verts[tri[b]] - verts[tri[a]]))
            if len(pts) != 2:
                continue
            seg_dir = np.cross(direction, tri_normals[ti])
            if float(np.dot(pts[1] - pts[0], seg_dir)) < 0.0:
                pts.reverse()
            ua, va = float((pts[0] - plane_point) @ e1), float((pts[0] - plane_point) @ e2)
            ub, vb = float((pts[1] - plane_point) @ e1), float((pts[1] - plane_point) @ e2)
            cross = ua * vb - ub * va
            area += 0.5 * cross
            cx += (ua + ub) * cross / 6.0
            cy += (va + vb) * cross / 6.0
            n_segments += 1

        if abs(area) > 1e-12:
            centroid = plane_point + (cx / area) * e1 + (cy / area) * e2
        else:
            centroid = plane_point

        sections.append({
            "t": t,
            "offset": offset - lo,
            "plane_point": plane_point.tolist(),
            "area": area,
            "centroid": centroid.tolist(),
            "n_segments": n_segments,
        })
    return sections
