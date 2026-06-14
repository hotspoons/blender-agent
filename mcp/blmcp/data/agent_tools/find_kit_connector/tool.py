# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Bundled Tier-B tool: find a kit part's connector peg and its joint axis.

Decompose into loose islands; the cog 'tooth ring' (>=4 near-identical small
square posts) defines the joint axis + center; the lone elongated square island
coaxial with that ring is the connector peg. Robust where socket detection on
the assembled copy is ambiguous. See the kitbash-axis-stacking skill.

Reads dict ``params`` (name, min_verts, coax_dist); assigns dict ``result``.
"""

import bmesh  # pylint: disable=import-error,no-name-in-module
import numpy as np  # pylint: disable=import-error
from mathutils import Vector  # pylint: disable=import-error,no-name-in-module


def _islands(o, min_verts):
    bm = bmesh.new()
    bm.from_mesh(o.data)
    seen = set()
    comps = []
    for v in bm.verts:
        if v.index in seen:
            continue
        stack = [v]
        comp = []
        seen.add(v.index)
        while stack:
            cur = stack.pop()
            comp.append(cur)
            for e in cur.link_edges:
                ov = e.other_vert(cur)
                if ov.index not in seen:
                    seen.add(ov.index)
                    stack.append(ov)
        if len(comp) >= min_verts:
            comps.append(comp)
    mw = o.matrix_world
    out = [np.array([(mw @ v.co)[:] for v in comp], dtype=float) for comp in comps]
    bm.free()
    return out


def _describe(pts):
    c = pts.mean(0)
    X = pts - c
    _, V = np.linalg.eigh(X.T @ X)
    axis = V[:, 2]
    proj = X @ axis
    length = float(proj.max() - proj.min())
    perp = X - np.outer(X @ axis, axis)
    c1 = float((perp @ V[:, 1]).max() - (perp @ V[:, 1]).min())
    c2 = float((perp @ V[:, 0]).max() - (perp @ V[:, 0]).min())
    mid, lo = max(c1, c2), min(c1, c2)
    return {
        "center": c, "axis": axis, "length": length, "mid": mid, "lo": lo,
        "verts": len(pts),
        "squareness": (lo / mid) if mid > 1e-6 else 0.0,
        "elong": (length / mid) if mid > 1e-6 else 0.0,
    }


def _fmt(d):
    return {
        "center": [round(float(x), 3) for x in d["center"]],
        "axis": [round(float(x), 3) for x in d["axis"]],
        "length": round(d["length"], 3),
        "cross_section": [round(d["mid"], 3), round(d["lo"], 3)],
        "squareness": round(d["squareness"], 3),
        "elongation": round(d["elong"], 3),
        "verts": d["verts"],
    }


def _run(params):
    import bpy  # pylint: disable=import-error,no-name-in-module

    name = params["name"]
    min_verts = int(params.get("min_verts", 8))
    coax_dist = float(params.get("coax_dist", 6.0))
    o = bpy.data.objects.get(name)
    if o is None or o.type != "MESH":
        return {"status": "error", "message": "Object %r not found or not a MESH." % name}

    islands = _islands(o, min_verts)
    if not islands:
        return {"status": "ok", "connector": None, "message": "No islands."}
    data = [_describe(p) for p in islands]
    max_size = max(d["verts"] for d in data)

    groups = []
    for i, d in enumerate(data):
        placed = False
        for g in groups:
            r = data[g[0]]
            if abs(d["length"] - r["length"]) < 0.15 * max(r["length"], 1) and \
               abs(d["mid"] - r["mid"]) < 0.15 * max(r["mid"], 1):
                g.append(i)
                placed = True
                break
        if not placed:
            groups.append([i])
    teeth = max(groups, key=len)

    if len(teeth) >= 4:
        ref = Vector(data[teeth[0]]["axis"])
        cog_axis = Vector((0, 0, 0))
        for i in teeth:
            a = Vector(data[i]["axis"])
            cog_axis += a if a.dot(ref) >= 0 else -a
        cog_axis.normalize()
        ring_center = Vector((0, 0, 0))
        for i in teeth:
            ring_center += Vector(data[i]["center"])
        ring_center /= len(teeth)

        best = None
        for i, d in enumerate(data):
            if i in teeth:
                continue
            if abs(Vector(d["axis"]).dot(cog_axis)) < 0.9:
                continue
            dv = Vector(d["center"]) - ring_center
            perp = (dv - dv.dot(cog_axis) * cog_axis).length
            if perp > coax_dist or d["squareness"] < 0.8 or d["elong"] < 1.4:
                continue
            if best is None or d["mid"] > best[0]:
                best = (d["mid"], d)
        if best is not None:
            return {
                "status": "ok",
                "method": "cog-ring coaxial",
                "connector": _fmt(best[1]),
                "joint_axis": [round(float(x), 3) for x in cog_axis],
                "joint_center": [round(float(x), 3) for x in ring_center],
                "teeth_count": len(teeth),
            }

    ranked = []
    for d in data:
        not_largest = 1.0 if d["verts"] < max_size else 0.35
        ranked.append((d["squareness"] * min(d["elong"], 4.0) * d["mid"] * not_largest, d))
    ranked.sort(key=lambda t: -t[0])
    return {
        "status": "ok",
        "method": "fallback ranking",
        "connector": _fmt(ranked[0][1]),
        "candidates": [_fmt(d) for _, d in ranked[:5]],
    }


result = _run(params)  # noqa: F821  (params/result injected by the sandbox)
