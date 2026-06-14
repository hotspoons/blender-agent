# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Bundled Tier-B tool: stack an ordered chain of mesh parts collinearly.

The robust signal is each part's two end-cap centroids projected on a shared
axis (a centroid ignores gear teeth / knurling, which break ring detectors).
Keep part 0 fixed; translate each next part so its near cap-center meets the
previous part's far cap-center, offset by ``gap`` (negative = insertion).

Reads dict ``params`` (names, axis, gap, align_axes, frac); assigns dict
``result``. See the kitbash-axis-stacking skill for the full rationale.
"""

import numpy as np  # pylint: disable=import-error
from mathutils import Vector, Matrix  # pylint: disable=import-error,no-name-in-module


def _world_pts(o):
    mw = o.matrix_world
    return np.array([(mw @ v.co)[:] for v in o.data.vertices], dtype=float)


def _principal_axis(pts):
    c = pts.mean(0)
    X = pts - c
    w, V = np.linalg.eigh(X.T @ X)
    return V[:, int(np.argmax(w))]


def _caps(o, axis_np, frac):
    pts = _world_pts(o)
    proj = pts @ axis_np
    lo, hi = float(proj.min()), float(proj.max())
    L = hi - lo
    if L <= 1e-9:
        c = pts.mean(0)
        return Vector(c), Vector(c)
    near = pts[proj <= lo + frac * L].mean(0)
    far = pts[proj >= hi - frac * L].mean(0)
    return Vector(near), Vector(far)


def _run(params: dict) -> dict:
    import bpy  # pylint: disable=import-error,no-name-in-module

    names = params["names"]
    if not isinstance(names, (list, tuple)) or len(names) < 2:
        return {"status": "error", "message": "Provide >=2 object names in 'names'."}
    objs = []
    for n in names:
        o = bpy.data.objects.get(n)
        if o is None:
            return {"status": "error", "message": "Object %r not found." % n}
        if o.type != "MESH":
            return {"status": "error", "message": "Object %r is %s, not MESH." % (n, o.type)}
        objs.append(o)

    gap = float(params.get("gap", 0.0))
    align_axes = bool(params.get("align_axes", False))
    frac = float(params.get("frac", 0.12))

    if params.get("axis"):
        axis = Vector(params["axis"]).normalized()
    else:
        best, best_score = None, -1.0
        for o in objs:
            pts = _world_pts(o)
            pa = _principal_axis(pts)
            proj = pts @ pa
            spread = float(proj.max() - proj.min())
            perp = pts - np.outer(pts @ pa, pa)
            perp_spread = float(np.linalg.norm(perp - perp.mean(0), axis=1).max()) + 1e-9
            score = spread / perp_spread
            if score > best_score:
                best_score, best = score, pa
        axis = Vector(best).normalized()

    ax = np.array(axis[:], dtype=float)
    c0 = _world_pts(objs[0]).mean(0)
    c1 = _world_pts(objs[1]).mean(0)
    g = axis if float((c1 - c0) @ ax) >= 0.0 else -axis
    gnp = np.array(g[:], dtype=float)

    if align_axes:
        for o in objs:
            pav = Vector(_principal_axis(_world_pts(o)))
            if pav.dot(g) < 0:
                pav = -pav
            rot = pav.rotation_difference(g).to_matrix().to_4x4()
            c = Vector(_world_pts(o).mean(0))
            o.matrix_world = Matrix.Translation(c) @ rot @ Matrix.Translation(-c) @ o.matrix_world
        bpy.context.view_layer.update()

    _, prev_far = _caps(objs[0], gnp, frac)
    placed = [{"name": objs[0].name, "moved": [0.0, 0.0, 0.0]}]
    for o in objs[1:]:
        near, _ = _caps(o, gnp, frac)
        delta = (prev_far + g * gap) - near
        o.matrix_world = Matrix.Translation(delta) @ o.matrix_world
        bpy.context.view_layer.update()
        _, prev_far = _caps(o, gnp, frac)
        placed.append({"name": o.name, "moved": [round(x, 3) for x in delta]})

    return {"status": "ok",
            "axis": [round(x, 4) for x in axis],
            "growth": [round(x, 4) for x in g],
            "chain": placed}


result = _run(params)  # noqa: F821  (params/result are injected by the sandbox)
