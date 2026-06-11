# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Oriented bounding boxes via principal component analysis.
"""

__all__ = (
    "part_obb",
)

import bpy
import numpy as np

from . import _mesh


def part_obb(obj: bpy.types.Object, part: dict | None = None) -> dict:
    """
    PCA-oriented bounding box of *obj*, or of one of its loose parts when
    *part* (a dict from :func:`blrig.perception.loose_parts`) is given.

    Returns ``center`` (world), ``axes`` (3 unit row-vectors, descending
    extent, right-handed), ``half_extents`` (along those axes), ``volume``,
    ``aspect`` (extents normalized to the largest). Not the minimal OBB —
    PCA-aligned, which is stable and sufficient for axis/elongation queries.
    """
    verts, _tris = _mesh.mesh_arrays(obj)
    if part is not None:
        verts = verts[np.asarray(part["vert_indices"], dtype=np.int64)]
    if len(verts) == 0:
        return {
            "center": [0.0, 0.0, 0.0],
            "axes": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            "half_extents": [0.0, 0.0, 0.0],
            "volume": 0.0,
            "aspect": [0.0, 0.0, 0.0],
        }

    _pca_center, axes, _eigvals = _mesh.pca_axes(verts)

    proj = (verts - verts.mean(axis=0)) @ axes.T
    lo = proj.min(axis=0)
    hi = proj.max(axis=0)
    half = (hi - lo) * 0.5
    mid = (hi + lo) * 0.5
    center = verts.mean(axis=0) + mid @ axes

    # Re-sort by actual extent (PCA variance order can disagree with the
    # min/max extent order on skewed distributions), keep right-handed.
    order = np.argsort(half)[::-1]
    axes = axes[order]
    half = half[order]
    if np.linalg.det(axes) < 0.0:
        axes[2] = -axes[2]

    largest = max(float(half[0]), 1e-20)
    return {
        "center": center.tolist(),
        "axes": axes.tolist(),
        "half_extents": half.tolist(),
        "volume": float(8.0 * half[0] * half[1] * half[2]),
        "aspect": (half / largest).tolist(),
    }
