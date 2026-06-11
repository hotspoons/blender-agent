# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mirror-plane detection.
"""

__all__ = (
    "symmetry_plane",
)

import bpy
import numpy as np

from . import _mesh


def _candidate_planes(obj: bpy.types.Object, verts: np.ndarray) -> list[tuple[np.ndarray, np.ndarray, str]]:
    """
    Candidate ``(point, normal, label)`` mirror planes: PCA axes through the
    vertex centroid, and object-local axes through the AABB center (covers
    the standard modeled-across-X case even when PCA is degenerate).
    """
    candidates = []

    center, axes, _eigvals = _mesh.pca_axes(verts)
    for i, label in enumerate(("pca0", "pca1", "pca2")):
        candidates.append((center, axes[i].copy(), label))

    bbox_center = (verts.min(axis=0) + verts.max(axis=0)) * 0.5
    mw = _mesh.world_matrix(obj)
    for i, label in enumerate(("local_x", "local_y", "local_z")):
        normal = mw[:3, i]
        norm = np.linalg.norm(normal)
        if norm < 1e-12:
            continue
        candidates.append((bbox_center, normal / norm, label))

    # Dedupe near-identical planes (same normal up to sign, same offset).
    diag = max(_mesh.bbox_diagonal(verts), 1e-12)
    unique: list[tuple[np.ndarray, np.ndarray, str]] = []
    for point, normal, label in candidates:
        dup = False
        for upoint, unormal, _ulabel in unique:
            if abs(float(np.dot(normal, unormal))) > 0.999:
                if abs(float(np.dot(normal, point - upoint))) < diag * 1e-4:
                    dup = True
                    break
        if not dup:
            unique.append((point, normal, label))
    return unique


def symmetry_plane(
        obj: bpy.types.Object,
        tol: float = 0.005,
        max_asymmetry_pct: float = 2.0,
        max_samples: int = 5000,
) -> dict:
    """
    Detect the best mirror plane of *obj*.

    Vertices are reflected across each candidate plane and measured against
    the original *surface* (BVH nearest), so differing tessellation on the
    two sides does not read as asymmetry.

    *tol* is relative to the bbox diagonal: a reflected vertex farther than
    ``tol * diagonal`` from the surface counts as asymmetric.

    Returns — never a bare bool — ``found`` (best plane's asymmetry below
    *max_asymmetry_pct*), ``point``/``normal`` (world), ``asymmetry_pct``,
    ``mean_error_rel`` (mean surface distance / diagonal), and per-candidate
    summaries in ``candidates``.
    """
    verts, tris = _mesh.mesh_arrays(obj)
    if len(verts) == 0 or len(tris) == 0:
        return {"found": False, "reason": "empty_mesh", "candidates": []}

    diag = max(_mesh.bbox_diagonal(verts), 1e-12)
    tol_abs = tol * diag
    bvh = _mesh.bvh_from_arrays(verts, tris)

    stride = max(1, len(verts) // max_samples)
    samples = verts[::stride]

    results = []
    for point, normal, label in _candidate_planes(obj, verts):
        dist = (samples - point) @ normal
        mirrored = samples - 2.0 * dist[:, None] * normal[None, :]

        errors = np.empty(len(mirrored))
        for i, m in enumerate(mirrored):
            hit = bvh.find_nearest(tuple(m))
            errors[i] = np.linalg.norm(m - np.asarray(hit[0])) if hit[0] is not None else diag

        results.append({
            "label": label,
            "point": point.tolist(),
            "normal": normal.tolist(),
            "asymmetry_pct": float((errors > tol_abs).mean() * 100.0),
            "mean_error_rel": float(errors.mean() / diag),
        })

    results.sort(key=lambda r: (r["asymmetry_pct"], r["mean_error_rel"]))
    best = results[0]
    return {
        "found": best["asymmetry_pct"] <= max_asymmetry_pct,
        "point": best["point"],
        "normal": best["normal"],
        "asymmetry_pct": best["asymmetry_pct"],
        "mean_error_rel": best["mean_error_rel"],
        "candidates": results,
    }
