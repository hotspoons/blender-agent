# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mesh-health report: gates every rigging skill (bone-heat weights, OBBs, and
booleans all silently misbehave on unhealthy input).
"""

__all__ = (
    "mesh_health",
)

import bmesh
import bpy
import numpy as np

import mathutils
from mathutils import kdtree

from . import _mesh


def mesh_health(obj: bpy.types.Object) -> dict:
    """
    Structured health report for *obj* (a mesh object).

    ``issues`` lists machine-readable problem codes; ``ok`` is True when it
    is empty. Codes: ``empty_mesh``, ``non_manifold_edges``,
    ``non_manifold_verts``, ``boundary_edges``, ``loose_verts``,
    ``loose_edges``, ``inconsistent_normals``, ``degenerate_faces``,
    ``duplicate_verts``, ``unapplied_scale``, ``negative_scale``,
    ``non_uniform_scale``.
    """
    report: dict = {"object": obj.name, "issues": []}

    scale = obj.matrix_world.to_scale()
    report["scale"] = list(scale)
    report["unapplied_scale"] = any(abs(s - 1.0) > 1e-6 for s in scale)
    report["negative_scale"] = any(s < 0.0 for s in scale)
    report["non_uniform_scale"] = (max(scale) - min(scale)) > 1e-6

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    try:
        report["n_verts"] = len(bm.verts)
        report["n_edges"] = len(bm.edges)
        report["n_faces"] = len(bm.faces)

        if len(bm.verts) == 0:
            report["issues"].append("empty_mesh")
            report["ok"] = False
            return report

        report["non_manifold_edges"] = sum(1 for e in bm.edges if not e.is_manifold)
        report["non_manifold_verts"] = sum(1 for v in bm.verts if not v.is_manifold)
        report["boundary_edges"] = sum(1 for e in bm.edges if e.is_boundary)
        report["loose_verts"] = sum(1 for v in bm.verts if not v.link_edges)
        report["loose_edges"] = sum(1 for e in bm.edges if not e.link_faces)
        report["is_closed"] = report["boundary_edges"] == 0

        # Winding consistency: across a manifold edge, the two faces must
        # traverse the edge in opposite vertex orders.
        inconsistent = 0
        for e in bm.edges:
            if len(e.link_faces) != 2:
                continue
            directions = []
            for f in e.link_faces:
                fverts = [v.index for v in f.verts]
                ia = fverts.index(e.verts[0].index)
                directions.append(fverts[(ia + 1) % len(fverts)] == e.verts[1].index)
            if directions[0] == directions[1]:
                inconsistent += 1
        report["inconsistent_normals"] = inconsistent

        scale_factor = max(abs(max(scale)), abs(min(scale)), 1e-12)
        verts_local = np.array([v.co[:] for v in bm.verts])
        diag_world = _mesh.bbox_diagonal(verts_local) * scale_factor
        eps_area = max((diag_world * 1e-6) ** 2, 1e-20)
        report["degenerate_faces"] = sum(1 for f in bm.faces if f.calc_area() * scale_factor**2 < eps_area)

        eps_dist = max(diag_world * 1e-7 / scale_factor, 1e-12)
        tree = kdtree.KDTree(len(bm.verts))
        for i, v in enumerate(bm.verts):
            tree.insert(v.co, i)
        tree.balance()
        duplicates = 0
        for i, v in enumerate(bm.verts):
            for _co, j, dist in tree.find_range(v.co, eps_dist):
                if j > i:
                    duplicates += 1
        report["duplicate_verts"] = duplicates
    finally:
        bm.free()

    for code, bad in (
        ("non_manifold_edges", report["non_manifold_edges"] > 0),
        ("non_manifold_verts", report["non_manifold_verts"] > 0),
        ("boundary_edges", report["boundary_edges"] > 0),
        ("loose_verts", report["loose_verts"] > 0),
        ("loose_edges", report["loose_edges"] > 0),
        ("inconsistent_normals", report["inconsistent_normals"] > 0),
        ("degenerate_faces", report["degenerate_faces"] > 0),
        ("duplicate_verts", report["duplicate_verts"] > 0),
        ("unapplied_scale", report["unapplied_scale"]),
        ("negative_scale", report["negative_scale"]),
        ("non_uniform_scale", report["non_uniform_scale"]),
    ):
        if bad:
            report["issues"].append(code)

    report["ok"] = not report["issues"]
    return report
