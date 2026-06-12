# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Scene inspection with ROUTING: the "what am I looking at" pass that runs
before any rigging skill. Beyond raw perception (health, parts, symmetry,
contacts) it reports structure — connected groups, gaps between them,
appendage chains — and suggests the skill(s) plus concrete params, so the
agent never has to translate geometry into a skill choice by itself.

The default report is COMPACT (suggestions first, one summary line per
object): a 40-part scene must not bury the routing under 40 OBB dumps.
``detail=True`` restores the full perception output.
"""

__all__ = (
    "inspect",
)

import bpy
import numpy as np

from .. import perception

_HINGE_ELONGATION = 3.0


def _component_structure(objects: list, graph: dict) -> dict:
    """
    Group parts into contact components; classify simple chains; measure
    the gap from every secondary component to the main one.
    """
    n = len(objects)
    component_of = list(range(n))

    def find(i: int) -> int:
        while component_of[i] != i:
            component_of[i] = component_of[component_of[i]]
            i = component_of[i]
        return i

    degree = [0] * n
    for edge in graph["edges"]:
        degree[edge["a"]] += 1
        degree[edge["b"]] += 1
        ra, rb = find(edge["a"]), find(edge["b"])
        if ra != rb:
            component_of[rb] = ra

    members: dict[int, list[int]] = {}
    for i in range(n):
        members.setdefault(find(i), []).append(i)

    volumes = [
        sum(p["volume"] for p in perception.loose_parts(obj)) for obj in objects]
    main_key = find(int(np.argmax(volumes)))

    components = []
    chains = 0
    for key, indices in members.items():
        is_chain = len(indices) >= 2 and all(degree[i] <= 2 for i in indices)
        if is_chain and key != main_key:
            chains += 1
        entry = {
            "parts": [objects[i].name for i in indices],
            "is_main": key == main_key,
            "is_chain": is_chain,
        }
        if key != main_key:
            best = None
            for i in indices:
                for j in members[main_key]:
                    gap = perception.nearest_gap(objects[i], objects[j])
                    if best is None or gap["distance"] < best["gap"]:
                        best = {"gap": gap["distance"],
                                "part": objects[i].name,
                                "main_part": objects[j].name}
            entry["nearest"] = best
        components.append(entry)
    components.sort(key=lambda c: (not c["is_main"], c["parts"]))
    return {
        "n_components": len(components),
        "components": components,
        "appendage_chains": chains,
    }


def _suggest(objects: list, infos: dict, graph: dict | None,
             structure: dict | None) -> list[dict]:
    """
    Ranked skill suggestions with ready-to-use params and a reason each.
    """
    suggestions: list[dict] = []
    names = [o.name for o in objects]

    if len(objects) == 1:
        obj = objects[0]
        info = infos[obj.name]
        aspect = info["obb"]["aspect"]
        n_loose = len(info["loose_parts"])
        if n_loose > 1:
            suggestions.append({
                "skill": "rig_rigid_assembly", "params": {},
                "reason": "one mesh with {:d} loose parts".format(n_loose)})
        elif abs(aspect[0] - aspect[1]) < 0.15 and aspect[2] < 0.7:
            suggestions.append({
                "skill": "rig_wheel", "params": {},
                "reason": "disc-like proportions (two equal extents, thin third)"})
        elif info["symmetry"].get("found"):
            suggestions.append({
                "skill": "rig_biped_rigify", "params": {},
                "reason": "single symmetric organic mesh; use "
                          "rig_quadruped_rigify instead if it is four-legged"})
        return suggestions

    gaps = [c["nearest"]["gap"] for c in (structure or {}).get("components", ())
            if not c["is_main"] and c.get("nearest")]
    bridge = round(max(gaps) * 1.5, 4) if gaps else None

    if structure and structure["appendage_chains"] >= 2:
        params = {"bridge_gaps": bridge} if bridge else {}
        suggestions.append({
            "skill": "rig_rigid_assembly", "params": params,
            "reason": "central body with {:d} appendage chains (creature/"
                      "machine with limbs); bridge_gaps attaches the gapped "
                      "chains at their nearest points".format(
                          structure["appendage_chains"])})
        suggestions.append({
            "skill": "rig_chain",
            "params": {"armature": "<assembly rig>", "joint_types": ["ball", "..."]},
            "reason": "alternative: rig each appendage chain in order and "
                      "compose into one armature for precise joint types"})
        return suggestions

    if len(objects) == 2:
        edge = max(graph["edges"], key=lambda e: e["n_points"]) if graph["edges"] else None
        if edge is not None:
            elongation = edge["extents"][0] / max(edge["extents"][1], 1e-9)
            if elongation >= _HINGE_ELONGATION:
                suggestions.append({
                    "skill": "rig_hinge", "params": {},
                    "reason": "two parts with an elongated contact region"})
            else:
                suggestions.append({
                    "skill": "rig_chain", "params": {"joint_types": ["ball"]},
                    "reason": "two parts with a compact (ball-like) contact"})
        else:
            suggestions.append({
                "skill": "rig_chain", "params": {"joint_types": ["ball"]},
                "reason": "two parts with no contact — rig_chain bridges "
                          "the gap at the nearest-pair midpoint"})
        aspects = [infos[n]["obb"]["aspect"] for n in names]
        if all(a[1] < 0.7 for a in aspects):
            suggestions.append({
                "skill": "rig_piston", "params": {},
                "reason": "both parts are rod-like; if they slide rather "
                          "than swing, this is a piston"})
        return suggestions

    params = {"bridge_gaps": bridge} if bridge else {}
    reason = "general multi-part assembly"
    if bridge:
        reason += "; {:d} disconnected group(s), largest gap {:.4f} — " \
                  "bridge_gaps joints them at their nearest parts".format(len(gaps), max(gaps))
    suggestions.append({"skill": "rig_rigid_assembly", "params": params, "reason": reason})
    return suggestions


def _summarize_object(info: dict) -> dict:
    """
    One readable line per object: enough to sanity-check the routing,
    nothing the skills don't recompute themselves anyway.
    """
    health = info["health"]
    return {
        "health": "ok" if health["ok"] else health["issues"],
        "size": [round(2.0 * h, 4) for h in info["obb"]["half_extents"]],
        "n_loose_parts": len(info["loose_parts"]),
        "symmetric": bool(info["symmetry"].get("found")),
    }


def _next_hint(suggested: list[dict]) -> str:
    if not suggested:
        return ("no skill suggestion for this object set — adjust the set, "
                "or consult skills_read('rigging-overview')")
    top = suggested[0]
    return ("rig('auto', {{'objects': [...same list...]}}) picks "
            "{skill!r}, diagnoses, builds and verifies in ONE call; or step "
            "through manually: rig('diagnose', {{'skill': {skill!r}, "
            "'objects': [...], 'params': {params!r}}})").format(
                skill=top["skill"], params=top["params"])


def inspect(object_names: list[str], contact_tolerance: float | None = None,
            detail: bool = False) -> dict:
    """
    Read-only perception + routing over *object_names*. Compact by
    default; *detail* returns full OBBs (axes/centers), per-part
    breakdowns and contact points.
    """
    infos: dict = {}
    missing: list[str] = []
    objects = []
    for name in object_names:
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != "MESH":
            missing.append(name)
            continue
        objects.append(obj)
        parts = perception.loose_parts(obj)
        for part in parts:
            del part["vert_indices"]
        symmetry = perception.symmetry_plane(obj)
        symmetry.pop("candidates", None)
        infos[name] = {
            "health": perception.mesh_health(obj),
            "obb": perception.part_obb(obj),
            "loose_parts": parts,
            "symmetry": symmetry,
        }

    graph = None
    structure = None
    if len(objects) > 1:
        graph = perception.contact_graph(objects, tol=contact_tolerance)
        structure = _component_structure(objects, graph)
    suggested = _suggest(objects, infos, graph, structure) if objects else []

    # Suggestions and the call-to-action lead; raw perception follows.
    out: dict = {"suggested": suggested, "next": _next_hint(suggested)}
    if detail:
        out["objects"] = infos
        out["contact_graph"] = graph
    else:
        out["objects"] = {name: _summarize_object(info)
                          for name, info in infos.items()}
        if graph is not None:
            out["contacts"] = {"n_edges": len(graph["edges"])}
        out["detail_hint"] = ("pass {'detail': true} for full OBBs, "
                              "loose-part breakdowns and contact points")
    out["structure"] = structure
    out["missing"] = missing
    return out
