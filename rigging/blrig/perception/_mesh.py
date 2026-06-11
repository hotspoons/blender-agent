# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Internal mesh-access helpers shared by perception queries.
"""

__all__ = (
    "bbox_diagonal",
    "bvh_from_arrays",
    "edge_array",
    "mesh_arrays",
    "pca_axes",
    "tri_areas_normals",
    "world_matrix",
)

import bpy
import numpy as np

from mathutils.bvhtree import BVHTree


def world_matrix(obj: bpy.types.Object) -> np.ndarray:
    return np.array(obj.matrix_world, dtype=np.float64)


def mesh_arrays(obj: bpy.types.Object) -> tuple[np.ndarray, np.ndarray]:
    """
    Return ``(verts, tris)``: world-space vertex coordinates ``(N, 3)`` and
    loop-triangle vertex indices ``(M, 3)`` (winding matches face normals).
    """
    mesh = obj.data
    n = len(mesh.vertices)
    co = np.empty(n * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(n, 3)

    mw = world_matrix(obj)
    verts = co @ mw[:3, :3].T + mw[:3, 3]

    mesh.calc_loop_triangles()
    m = len(mesh.loop_triangles)
    tris = np.empty(m * 3, dtype=np.int64)
    mesh.loop_triangles.foreach_get("vertices", tris)
    return verts, tris.reshape(m, 3)


def edge_array(obj: bpy.types.Object) -> np.ndarray:
    """
    Return edge vertex indices ``(E, 2)``.
    """
    mesh = obj.data
    e = len(mesh.edges)
    edges = np.empty(e * 2, dtype=np.int64)
    mesh.edges.foreach_get("vertices", edges)
    return edges.reshape(e, 2)


def bbox_diagonal(verts: np.ndarray) -> float:
    if len(verts) == 0:
        return 0.0
    return float(np.linalg.norm(verts.max(axis=0) - verts.min(axis=0)))


def tri_areas_normals(verts: np.ndarray, tris: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Per-triangle areas ``(M,)`` and unit normals ``(M, 3)``
    (zero vector for degenerate triangles).
    """
    a = verts[tris[:, 0]]
    cr = np.cross(verts[tris[:, 1]] - a, verts[tris[:, 2]] - a)
    norm = np.linalg.norm(cr, axis=1)
    areas = norm * 0.5
    safe = np.where(norm > 1e-20, norm, 1.0)[:, None]
    normals = np.where(norm[:, None] > 1e-20, cr / safe, 0.0)
    return areas, normals


def pca_axes(points: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Principal axes of a point cloud.

    Returns ``(center, axes, eigenvalues)`` where ``axes`` rows are unit
    vectors sorted by descending variance and form a right-handed frame.
    """
    center = points.mean(axis=0)
    centered = points - center
    cov = centered.T @ centered / max(len(points), 1)
    eigvals, eigvecs = np.linalg.eigh(cov)
    order = np.argsort(eigvals)[::-1]
    axes = eigvecs[:, order].T
    eigvals = eigvals[order]
    if np.linalg.det(axes) < 0.0:
        axes[2] = -axes[2]
    return center, axes, eigvals


def bvh_from_arrays(verts: np.ndarray, tris: np.ndarray) -> BVHTree:
    return BVHTree.FromPolygons(
        [tuple(v) for v in verts],
        [tuple(int(i) for i in t) for t in tris],
        all_triangles=True,
    )
