# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
rig_rigid_assembly: any pile of rigid parts -> bone-per-part skeleton with
joint controls at every contact, parented along the contact tree (lamps,
machines, furniture, robots — the general mechanical case).

Accepts either several mesh objects, or ONE mesh object whose loose parts
form the assembly (vertex-subset binding).

The contact graph's spanning tree (rooted at the largest part) becomes the
bone hierarchy; every tree edge gets a ``CTL-<child>`` joint bone at the
contact centroid, aligned to the contact region's dominant axis. Joints are
classified ``hinge_like`` (elongated contact) or ``ball_like`` and reported
— the agent can re-rig a specific pair with rig_hinge for hard limits.
Parts with no contact to the main component parent to root (``floating``).

Triggers: >2 parts, unknown/mixed joint types, "just make it poseable".
Anti-triggers: known specific mechanisms — prefer rig_hinge / rig_piston /
rig_wheel / rig_turret for their constraints and verification.

params:
- ``name``: armature name, default "Rig.Assembly".
- ``root_part``: part name to use as the anchor; default largest volume.
- ``ignore_health``: accept unhealthy meshes (default False).
"""

__all__ = (
    "diagnose",
    "run",
    "verify",
)

import numpy as np

import bpy

from .. import perception
from .. import _armature
from ..standard import validate_weights
from . import _bones
from . import _contract

_HINGE_ELONGATION = 3.0


def _gather_parts(ctx: dict, params: dict) -> tuple[list[dict], dict | None]:
    """
    Normalize input to part records:
    ``{"name", "object", "vert_indices" (None = whole object), "obb",
    "volume", "item" (contact_graph item)}``.
    """
    objects, err = _contract.resolve_objects(ctx)
    if err is not None:
        return [], err
    if not objects:
        return [], _contract.fail("wrong_object_count", detail="ctx['objects'] is empty")

    if not params.get("ignore_health"):
        for obj in objects:
            health = perception.mesh_health(obj)
            bad = [i for i in health["issues"]
                   if i in ("unapplied_scale", "negative_scale", "non_uniform_scale",
                            "empty_mesh")]
            if bad:
                return [], _contract.fail(
                    "unhealthy_mesh", object=obj.name, issues=health["issues"],
                    suggest="apply scale, or params={'ignore_health': True}")

    parts: list[dict] = []
    if len(objects) == 1:
        obj = objects[0]
        loose = perception.loose_parts(obj)
        if len(loose) < 2:
            return [], _contract.fail(
                "single_part",
                detail="one object with one connected component is not an assembly",
                suggest="rig_wheel / rig_hinge, or pass the other parts too")
        for i, part in enumerate(loose):
            parts.append({
                "name": "{:s}_p{:d}".format(obj.name, i),
                "object": obj.name,
                "vert_indices": part["vert_indices"],
                "obb": perception.part_obb(obj, part),
                "volume": part["volume"],
                "item": (obj, part),
            })
    else:
        for obj in objects:
            loose = perception.loose_parts(obj)
            parts.append({
                "name": obj.name,
                "object": obj.name,
                "vert_indices": None,
                "obb": perception.part_obb(obj),
                "volume": sum(p["volume"] for p in loose),
                "item": obj,
            })
    return parts, None


def _plan(ctx: dict, params: dict | None) -> dict:
    params = params or {}
    parts, err = _gather_parts(ctx, params)
    if err is not None:
        return err

    graph = perception.contact_graph([p["item"] for p in parts])

    root_name = params.get("root_part")
    if root_name is not None:
        root_index = next((i for i, p in enumerate(parts) if p["name"] == root_name), None)
        if root_index is None:
            return _contract.fail("bad_param", param="root_part",
                                  detail="no part named {!r}".format(root_name))
    else:
        root_index = max(range(len(parts)), key=lambda i: parts[i]["volume"])

    # BFS spanning tree from the root over contact edges (strongest first).
    adjacency: dict[int, list[tuple[int, dict]]] = {i: [] for i in range(len(parts))}
    for edge in graph["edges"]:
        adjacency[edge["a"]].append((edge["b"], edge))
        adjacency[edge["b"]].append((edge["a"], edge))
    for neighbors in adjacency.values():
        neighbors.sort(key=lambda n: -n[1]["n_points"])

    parent_of: dict[int, tuple[int, dict] | None] = {root_index: None}
    queue = [root_index]
    while queue:
        current = queue.pop(0)
        for neighbor, edge in adjacency[current]:
            if neighbor not in parent_of:
                parent_of[neighbor] = (current, edge)
                queue.append(neighbor)

    joints = []
    floating = []
    for i, part in enumerate(parts):
        if i == root_index:
            continue
        link = parent_of.get(i)
        if link is None:
            floating.append(part["name"])
            continue
        parent_index, edge = link
        extents = edge["extents"]
        elongation = extents[0] / max(extents[1], 1e-9)
        axis = edge["axis"]
        if axis is None:
            axis = [0.0, 0.0, 1.0]
        axis = np.asarray(axis, dtype=np.float64)
        if axis[int(np.argmax(np.abs(axis)))] < 0.0:
            axis = -axis
        joints.append({
            "parent": parts[parent_index]["name"],
            "child": part["name"],
            "point": edge["centroid"],
            "axis": axis.tolist(),
            "kind": "hinge_like" if elongation >= _HINGE_ELONGATION else "ball_like",
            "elongation": float(elongation),
            "contact_kind": edge["kind"],
        })

    all_pts = np.concatenate([
        perception._mesh.mesh_arrays(bpy.data.objects[name])[0]
        for name in {p["object"] for p in parts}])
    bbox_min = all_pts.min(axis=0)
    bbox_center = (all_pts.min(axis=0) + all_pts.max(axis=0)) * 0.5
    diag = float(np.linalg.norm(all_pts.max(axis=0) - all_pts.min(axis=0)))

    def part_bone(part):
        obb = part["obb"]
        head = np.asarray(obb["center"], dtype=np.float64)
        direction = np.asarray(obb["axes"][0], dtype=np.float64)
        if direction[int(np.argmax(np.abs(direction)))] < 0.0:
            direction = -direction
        return head.tolist(), (head + direction * max(float(obb["half_extents"][0]), 1e-3)).tolist()

    return _contract.ok(plan={
        "parts": [{
            "name": p["name"], "object": p["object"],
            "vert_indices": p["vert_indices"], "bone": part_bone(p),
        } for p in parts],
        "root_part": parts[root_index]["name"],
        "joints": joints,
        "floating": floating,
        "n_components": graph["n_components"],
        "name": params.get("name", "Rig.Assembly"),
        "root_head": [float(bbox_center[0]), float(bbox_center[1]), float(bbox_min[2])],
        "root_len": 0.25 * diag,
        "joint_len": 0.1 * diag,
    })


def diagnose(ctx: dict, params: dict | None = None) -> dict:
    report = _plan(ctx, params)
    if not report["ok"]:
        _contract.log_failure("rig_rigid_assembly", "diagnose", report)
    return report


def run(ctx: dict, params: dict | None = None) -> dict:
    planned = _plan(ctx, params)
    if not planned["ok"]:
        _contract.log_failure("rig_rigid_assembly", "run", planned)
        return planned
    plan = planned["plan"]

    def body(rollback: _contract.Rollback) -> dict:
        root_head = np.asarray(plan["root_head"])
        specs = [{
            "name": "root",
            "head": root_head.tolist(),
            "tail": (root_head + [0.0, plan["root_len"], 0.0]).tolist(),
        }]
        by_name = {p["name"]: p for p in plan["parts"]}
        joint_of = {j["child"]: j for j in plan["joints"]}

        # Parents must precede children: emit bones in BFS order from root.
        emitted = {plan["root_part"]}
        specs.append({
            "name": "DEF-" + plan["root_part"], "parent": "root", "use_deform": True,
            "head": by_name[plan["root_part"]]["bone"][0],
            "tail": by_name[plan["root_part"]]["bone"][1],
        })
        for name in plan["floating"]:
            emitted.add(name)
            specs.append({
                "name": "DEF-" + name, "parent": "root", "use_deform": True,
                "head": by_name[name]["bone"][0], "tail": by_name[name]["bone"][1],
            })
        pending = [j for j in plan["joints"]]
        while pending:
            progressed = False
            for joint in list(pending):
                if joint["parent"] not in emitted:
                    continue
                point = np.asarray(joint["point"])
                axis = np.asarray(joint["axis"])
                ctl = "CTL-" + joint["child"]
                specs.append({
                    "name": ctl, "parent": "DEF-" + joint["parent"],
                    "head": point.tolist(),
                    "tail": (point + axis * plan["joint_len"]).tolist(),
                })
                specs.append({
                    "name": "DEF-" + joint["child"], "parent": ctl, "use_deform": True,
                    "head": by_name[joint["child"]]["bone"][0],
                    "tail": by_name[joint["child"]]["bone"][1],
                })
                emitted.add(joint["child"])
                pending.remove(joint)
                progressed = True
            if not progressed:
                return _contract.fail(
                    "joint_cycle", detail="could not order joints {!r}".format(
                        [j["child"] for j in pending]))

        rig = _armature.build_armature(plan["name"], specs)
        rollback.track_object(rig)

        for part in plan["parts"]:
            _bones.bind_rigid(
                bpy.data.objects[part["object"]], rig, "DEF-" + part["name"],
                vert_indices=part["vert_indices"], rollback=rollback)
        _bones.assign_custom_shapes(rig, rollback=rollback)
        bpy.context.view_layer.update()

        ctx["armature"] = rig.name
        return _contract.ok(
            armature=rig.name,
            assembly={
                "root_part": plan["root_part"],
                "joints": plan["joints"],
                "floating": plan["floating"],
                "n_components": plan["n_components"],
                "controls": ["CTL-" + j["child"] for j in plan["joints"]],
            },
        )

    return _contract.run_with_rollback("rig_rigid_assembly", body)


def verify(ctx: dict) -> dict:
    name = ctx.get("armature", "")
    checks = _contract.verify_common(name)
    rig = bpy.data.objects.get(name)
    if rig is None:
        report = _contract.fail("no_armature", checks=checks)
        _contract.log_failure("rig_rigid_assembly", "verify", report)
        return report

    mesh_objects = {
        obj for obj in bpy.data.objects
        if obj.type == "MESH"
        and any(m.type == "ARMATURE" and m.object == rig for m in obj.modifiers)}
    for obj in mesh_objects:
        weights = validate_weights(obj, rig)
        checks.append(_contract.check(
            "weights_{:s}".format(obj.name), weights["ok"], str(weights["errors"])))

    # Pose every joint: each subtree must move while root-part verts hold.
    controls = [b.name for b in rig.data.bones if b.name.startswith("CTL-")]
    root_deform = next(
        (b.name for b in rig.data.bones if b.use_deform and b.parent and b.parent.name == "root"),
        None)
    snap = {o.name: _bones.evaluated_verts(o) for o in mesh_objects}
    for ctl in controls:
        _bones.pose_rotate(rig, ctl, "y", 20.0)
    posed = {o.name: _bones.evaluated_verts(o) for o in mesh_objects}
    _bones.reset_pose(rig)

    if controls:
        any_moved = any(
            float(np.abs(posed[o] - snap[o]).max()) > 1e-4 for o in posed)
        checks.append(_contract.check("joints_articulate", any_moved))
    checks.append(_contract.check("has_root_deform", root_deform is not None))

    failed = [c for c in checks if not c["ok"]]
    report = {"ok": not failed, "checks": checks}
    if failed:
        report["fail"] = "verify_failed"
        _contract.log_failure("rig_rigid_assembly", "verify", report)
    return report
