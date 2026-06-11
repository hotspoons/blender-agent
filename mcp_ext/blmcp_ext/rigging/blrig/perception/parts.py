# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Connected-component decomposition and part-contact detection.
"""

__all__ = (
    "contact_graph",
    "loose_parts",
)

import math

import bpy
import numpy as np

from . import _mesh


def _union_find_components(n_verts: int, edges: np.ndarray) -> np.ndarray:
    """
    Label each vertex with a component id (0..k-1) via union-find over edges.
    """
    parent = np.arange(n_verts, dtype=np.int64)

    def find(i: int) -> int:
        root = i
        while parent[root] != root:
            root = parent[root]
        while parent[i] != root:
            parent[i], i = root, parent[i]
        return root

    for a, b in edges:
        ra, rb = find(int(a)), find(int(b))
        if ra != rb:
            parent[rb] = ra

    roots = np.array([find(int(i)) for i in range(n_verts)], dtype=np.int64)
    _, labels = np.unique(roots, return_inverse=True)
    return labels


def loose_parts(obj: bpy.types.Object) -> list[dict]:
    """
    Decompose *obj* into connected components ("loose parts").

    Returns one dict per part, sorted by descending volume:
    ``index``, ``vert_indices``, ``n_verts``, ``n_faces``, ``centroid``
    (area-weighted surface centroid, world), ``bbox_min``/``bbox_max`` (world
    AABB), ``surface_area``, ``volume`` (unsigned, divergence theorem — only
    meaningful for closed parts), ``is_closed`` (no boundary edges).
    """
    verts, tris = _mesh.mesh_arrays(obj)
    edges = _mesh.edge_array(obj)
    if len(verts) == 0:
        return []

    labels = _union_find_components(len(verts), edges)
    n_parts = int(labels.max()) + 1 if len(labels) else 0
    tri_label = labels[tris[:, 0]] if len(tris) else np.empty(0, dtype=np.int64)

    # Boundary detection: count face-uses per edge of each triangle.
    edge_use: dict[tuple[int, int], int] = {}
    for t in tris:
        for i in range(3):
            a, b = int(t[i]), int(t[(i + 1) % 3])
            key = (a, b) if a < b else (b, a)
            edge_use[key] = edge_use.get(key, 0) + 1
    open_part = set()
    for (a, _b), count in edge_use.items():
        if count == 1:
            open_part.add(int(labels[a]))

    areas, _normals = _mesh.tri_areas_normals(verts, tris)

    parts = []
    for part in range(n_parts):
        vmask = labels == part
        tmask = tri_label == part
        pverts = verts[vmask]
        ptris = tris[tmask]
        parea = areas[tmask]
        total_area = float(parea.sum())

        if total_area > 1e-20:
            tri_centroids = verts[ptris].mean(axis=1)
            centroid = (tri_centroids * parea[:, None]).sum(axis=0) / total_area
        else:
            centroid = pverts.mean(axis=0)

        # Divergence theorem; world-space coords, so translation-invariant
        # only for closed parts (we report `is_closed` so callers can judge).
        a0 = verts[ptris[:, 0]] - centroid if len(ptris) else np.zeros((0, 3))
        a1 = verts[ptris[:, 1]] - centroid if len(ptris) else np.zeros((0, 3))
        a2 = verts[ptris[:, 2]] - centroid if len(ptris) else np.zeros((0, 3))
        volume = float(abs(np.einsum("ij,ij->i", a0, np.cross(a1, a2)).sum()) / 6.0)

        parts.append({
            "index": part,
            "vert_indices": np.flatnonzero(vmask).tolist(),
            "n_verts": int(vmask.sum()),
            "n_faces": int(tmask.sum()),
            "centroid": centroid.tolist(),
            "bbox_min": pverts.min(axis=0).tolist(),
            "bbox_max": pverts.max(axis=0).tolist(),
            "surface_area": total_area,
            "volume": volume,
            "is_closed": part not in open_part,
        })

    parts.sort(key=lambda p: -p["volume"])
    for i, part in enumerate(parts):
        part["index"] = i
    return parts


def _item_arrays(item) -> tuple[str, np.ndarray, np.ndarray]:
    """
    Normalize a contact-graph item into ``(name, world_verts, local_tris)``.

    Accepts a ``bpy.types.Object`` or an ``(object, part_dict)`` tuple where
    ``part_dict`` comes from :func:`loose_parts`.
    """
    if isinstance(item, tuple):
        obj, part = item
        verts, tris = _mesh.mesh_arrays(obj)
        vert_indices = np.asarray(part["vert_indices"], dtype=np.int64)
        remap = np.full(len(verts), -1, dtype=np.int64)
        remap[vert_indices] = np.arange(len(vert_indices))
        mask = np.all(remap[tris] >= 0, axis=1)
        return (
            "{:s}:part{:d}".format(obj.name, int(part["index"])),
            verts[vert_indices],
            remap[tris[mask]],
        )
    verts, tris = _mesh.mesh_arrays(item)
    return item.name, verts, tris


def contact_graph(items: list, tol: float | None = None, max_samples: int = 2000) -> dict:
    """
    Detect contacts between parts.

    *items*: list of objects and/or ``(object, part_dict)`` tuples.
    *tol*: max gap (world units) to count as touching; defaults to 0.1% of
    the combined bbox diagonal.

    Returns ``{"nodes", "edges", "tol", "n_components"}``. Each edge carries
    ``a``/``b`` (node indices), ``kind`` (``intersect``/``proximity``),
    ``centroid``, ``axis`` (dominant PCA axis of the contact region — a hinge
    axis candidate), ``extents`` (PCA half-extents), ``max_gap``,
    ``n_points``.
    """
    norm = [_item_arrays(item) for item in items]
    names = [name for name, _v, _t in norm]

    all_verts = np.concatenate([v for _n, v, _t in norm if len(v)]) if norm else np.zeros((0, 3))
    diag = _mesh.bbox_diagonal(all_verts)
    if tol is None:
        tol = max(diag * 1e-3, 1e-9)

    bvhs = [_mesh.bvh_from_arrays(v, t) if len(t) else None for _n, v, t in norm]

    edges = []
    for ia in range(len(norm)):
        for ib in range(ia + 1, len(norm)):
            if bvhs[ia] is None or bvhs[ib] is None:
                continue
            contact = _pair_contact(norm[ia], norm[ib], bvhs[ia], bvhs[ib], tol, max_samples)
            if contact is not None:
                contact["a"] = ia
                contact["b"] = ib
                edges.append(contact)

    # Connected components of the contact graph.
    comp = list(range(len(norm)))

    def find(i: int) -> int:
        while comp[i] != i:
            comp[i] = comp[comp[i]]
            i = comp[i]
        return i

    for e in edges:
        ra, rb = find(e["a"]), find(e["b"])
        if ra != rb:
            comp[rb] = ra
    n_components = len({find(i) for i in range(len(norm))})

    return {"nodes": names, "edges": edges, "tol": tol, "n_components": n_components}


def _point_in_tri(p: np.ndarray, tri: np.ndarray, eps: float) -> bool:
    """
    Point-in-triangle (3D, point assumed near the triangle plane) via
    barycentric coordinates, with *eps* slack so edges/corners count.
    """
    v0 = tri[1] - tri[0]
    v1 = tri[2] - tri[0]
    v2 = p - tri[0]
    d00 = float(v0 @ v0)
    d01 = float(v0 @ v1)
    d11 = float(v1 @ v1)
    d20 = float(v2 @ v0)
    d21 = float(v2 @ v1)
    denom = d00 * d11 - d01 * d01
    if abs(denom) < 1e-20:
        return False
    v = (d11 * d20 - d01 * d21) / denom
    w = (d00 * d21 - d01 * d20) / denom
    rel = eps / max(math.sqrt(max(d00, d11)), 1e-12)
    return v >= -rel and w >= -rel and (v + w) <= 1.0 + rel


def _tri_contact_points(ta: np.ndarray, tb: np.ndarray, eps: float) -> list[np.ndarray]:
    """
    Contact points of two known-overlapping triangles: edge/plane crossings
    that land inside the other triangle, plus vertex containment for the
    coplanar (face-on-face) case.
    """
    points: list[np.ndarray] = []
    for p, q in ((ta, tb), (tb, ta)):
        n = np.cross(q[1] - q[0], q[2] - q[0])
        norm = np.linalg.norm(n)
        if norm < 1e-20:
            continue
        n = n / norm
        d = (p - q[0]) @ n
        if np.all(np.abs(d) < eps):
            for v, dv in zip(p, d):
                on_plane = v - dv * n
                if _point_in_tri(on_plane, q, eps):
                    points.append(on_plane)
            continue
        for a in range(3):
            b = (a + 1) % 3
            if (d[a] > 0.0) != (d[b] > 0.0):
                f = d[a] / (d[a] - d[b])
                x = p[a] + f * (p[b] - p[a])
                if _point_in_tri(x, q, eps):
                    points.append(x)
    return points


def _pair_contact(item_a, item_b, bvh_a, bvh_b, tol: float, max_samples: int) -> dict | None:
    _na, verts_a, tris_a = item_a
    _nb, verts_b, tris_b = item_b

    points = []
    gaps = []
    kind = None

    overlap = bvh_a.overlap(bvh_b)
    if overlap:
        kind = "intersect"
        for ta, tb in overlap[: max_samples]:
            tri_a = verts_a[tris_a[ta]]
            tri_b = verts_b[tris_b[tb]]
            contact = _tri_contact_points(tri_a, tri_b, tol)
            if not contact:
                # Numeric edge case: fall back to the centroid midpoint.
                contact = [(tri_a.mean(axis=0) + tri_b.mean(axis=0)) * 0.5]
            points.extend(contact)
            gaps.extend([0.0] * len(contact))
    else:
        # Proximity: sample verts of each part against the other's surface.
        for verts, bvh in ((verts_a, bvh_b), (verts_b, bvh_a)):
            stride = max(1, len(verts) // max_samples)
            for v in verts[::stride]:
                hit = bvh.find_nearest(tuple(v), tol)
                if hit is not None and hit[0] is not None:
                    location = np.array(hit[0], dtype=np.float64)
                    points.append((v + location) * 0.5)
                    gaps.append(float(np.linalg.norm(v - location)))
        if points:
            kind = "proximity"

    if kind is None:
        return None

    pts = np.asarray(points)
    if len(pts) >= 3:
        _center, axes, eigvals = _mesh.pca_axes(pts)
        axis = axes[0].tolist()
        extents = np.sqrt(np.maximum(eigvals, 0.0)).tolist()
    else:
        axis = None
        extents = [0.0, 0.0, 0.0]

    return {
        "kind": kind,
        "n_points": len(pts),
        "centroid": pts.mean(axis=0).tolist(),
        "axis": axis,
        "extents": extents,
        "max_gap": float(max(gaps)) if gaps else 0.0,
    }
