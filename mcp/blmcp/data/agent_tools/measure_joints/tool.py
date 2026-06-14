# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Bundled Tier-B tool: detect cylindrical joint "ports" in a mesh.

Method: a surface of revolution's side-faces have normals perpendicular to its
axis. The axis is estimated from the area-weighted face-normal covariance
(smallest-eigenvalue eigenvector), then faces are clustered along that axis and
filtered to those forming a clean ring (radius near the cluster's modal value).

Reads dict ``params`` (name, perp_thresh, axial_gap, radius_tol); assigns dict
``result`` ({status, name, joints:[{center,axis,radius,faces}], message}).
"""

from typing import Any


def _find_ports(
    normals: Any,
    centers: Any,
    perp_thresh: float,
    axial_gap: float,
    radius_tol: float,
) -> list:
    import numpy as np  # pylint: disable=import-error

    # Candidate axes: the part is usually near-axis-aligned, but also try the
    # covariance smallest-eigenvalue direction (the best-fit cylinder axis).
    cov = (normals[:, :, None] * normals[:, None, :]).sum(0)
    _, eigvecs = np.linalg.eigh(cov)
    candidates = [
        np.array([1.0, 0.0, 0.0]),
        np.array([0.0, 1.0, 0.0]),
        np.array([0.0, 0.0, 1.0]),
        eigvecs[:, 0],
    ]

    raw = []
    for axis in candidates:
        axis = axis / np.linalg.norm(axis)
        side = np.abs(normals @ axis) < perp_thresh
        if side.sum() < 30:
            continue
        pts = centers[side]
        along = pts @ axis
        order = np.argsort(along)
        pts = pts[order]
        along = along[order]
        start = 0
        for i in range(1, len(along) + 1):
            if i == len(along) or along[i] - along[i - 1] > axial_gap:
                cluster = pts[start:i]
                start = i
                if len(cluster) < 40:
                    continue
                proj = cluster - np.outer(cluster @ axis, axis)
                ctr = proj.mean(0)
                radii = np.linalg.norm(proj - ctr, axis=1)
                med = np.median(radii)
                keep = np.abs(radii - med) < med * radius_tol
                if keep.sum() < 20:
                    continue
                rk = radii[keep]
                if rk.std() >= rk.mean() * radius_tol:
                    continue
                center = proj[keep].mean(0) + axis * float((cluster @ axis).mean())
                raw.append((
                    [round(float(x), 3) for x in center],
                    [round(float(x), 3) for x in axis],
                    round(float(rk.mean()), 3),
                    int(keep.sum()),
                ))

    # Deduplicate ports whose centers nearly coincide (found via multiple axes).
    unique = []
    seen = []
    for center, axis_l, radius, faces in raw:
        if any(sum((a - b) ** 2 for a, b in zip(center, s)) < 9.0 for s in seen):
            continue
        seen.append(center)
        unique.append({"center": center, "axis": axis_l, "radius": radius, "faces": faces})
    return unique


def _run(params: dict) -> dict:
    import bmesh  # pylint: disable=import-error,no-name-in-module
    import bpy  # pylint: disable=import-error,no-name-in-module
    import numpy as np  # pylint: disable=import-error

    name = params["name"]
    perp_thresh = float(params.get("perp_thresh", 0.30))
    axial_gap = float(params.get("axial_gap", 6.0))
    radius_tol = float(params.get("radius_tol", 0.18))

    obj = bpy.data.objects.get(name)
    if obj is None:
        available = sorted(bpy.data.objects.keys())
        return {
            "status": "error",
            "message": "Object {!r} not found. Available objects: {:s}".format(
                name, ", ".join(available) if available else "(none)",
            ),
        }
    if obj.type != "MESH":
        return {
            "status": "error",
            "message": "Object {!r} is a {:s}, not a MESH.".format(name, obj.type),
        }

    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bm.normal_update()
        mat = obj.matrix_world
        nmat = mat.to_3x3()
        normals = []
        centers = []
        for face in bm.faces:
            wn = nmat @ face.normal
            if wn.length == 0.0:
                continue
            wn.normalize()
            wc = mat @ face.calc_center_median()
            normals.append((wn.x, wn.y, wn.z))
            centers.append((wc.x, wc.y, wc.z))
    finally:
        bm.free()

    if len(normals) < 30:
        return {"status": "ok", "name": obj.name, "joints": []}

    joints = _find_ports(
        np.array(normals), np.array(centers),
        perp_thresh=perp_thresh, axial_gap=axial_gap, radius_tol=radius_tol,
    )
    return {"status": "ok", "name": obj.name, "joints": joints}


result = _run(params)  # noqa: F821  (params/result are injected by the sandbox)
