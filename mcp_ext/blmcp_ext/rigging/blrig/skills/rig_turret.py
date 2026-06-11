# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
rig_turret: a base / rotating platform / elevating member stack -> yaw +
pitch controls with limits (gun turrets, cranes, security cameras, periscopes).

ctx["objects"] order is semantic: ``[base, yaw_part, pitch_part]`` — the
base stays put, the yaw part spins about a vertical axis on the base, the
pitch part elevates about a horizontal axis on the yaw part.

Triggers: three-part aiming stacks.
Anti-triggers: a single swinging joint (rig_hinge), free-form assemblies
(rig_rigid_assembly).

params:
- ``yaw_axis``: world axis of the yaw rotation, default "z".
- ``yaw_limits_deg``: [min, max], default [-180, 180].
- ``pitch_limits_deg``: [min, max], default [-15, 75].
- ``name``: armature name, default "Rig.Turret".
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

_AXES = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}


def _contact_between(graph: dict, ia: int, ib: int) -> dict | None:
    for edge in graph["edges"]:
        if {edge["a"], edge["b"]} == {ia, ib}:
            return edge
    return None


def _plan(ctx: dict, params: dict | None) -> dict:
    params = params or {}
    objects, err = _contract.resolve_objects(ctx, expected=3)
    if err is not None:
        return err
    base, yaw_part, pitch_part = objects

    if not params.get("ignore_health"):
        for obj in objects:
            health = perception.mesh_health(obj)
            if not health["ok"]:
                return _contract.fail(
                    "unhealthy_mesh", object=obj.name, issues=health["issues"],
                    suggest="apply scale / clean mesh, or params={'ignore_health': True}")

    graph = perception.contact_graph(objects)
    base_yaw = _contact_between(graph, 0, 1)
    yaw_pitch = _contact_between(graph, 1, 2)
    if base_yaw is None or yaw_pitch is None:
        return _contract.fail(
            "no_chain",
            detail="need contacts base<->yaw and yaw<->pitch; found edges {!r}".format(
                [(e["a"], e["b"]) for e in graph["edges"]]),
            suggest="check ctx['objects'] order is [base, yaw_part, pitch_part], "
                    "or use rig_rigid_assembly")

    yaw_axis = np.asarray(_AXES[params.get("yaw_axis", "z")], dtype=np.float64)

    # Pitch axis: horizontal, perpendicular to where the pitch member points.
    obb_pitch = perception.part_obb(pitch_part)
    barrel_dir = np.asarray(obb_pitch["axes"][0], dtype=np.float64)
    pitch_axis = np.cross(yaw_axis, barrel_dir)
    norm = np.linalg.norm(pitch_axis)
    if norm < 0.1:
        return _contract.fail(
            "degenerate_pitch_axis",
            detail="pitch member's major axis is parallel to the yaw axis",
            suggest="check object order, or rig_hinge the joints individually")
    pitch_axis /= norm
    if pitch_axis[int(np.argmax(np.abs(pitch_axis)))] < 0.0:
        pitch_axis = -pitch_axis

    # Yaw pivot: the base/yaw contact centroid projected onto the yaw part's
    # spin axis (its own center): rotation must happen about the drum center.
    obb_yaw = perception.part_obb(yaw_part)
    yaw_center = np.asarray(obb_yaw["center"], dtype=np.float64)
    contact_c = np.asarray(base_yaw["centroid"], dtype=np.float64)
    yaw_point = yaw_center + (float((contact_c - yaw_center) @ yaw_axis)) * yaw_axis

    pitch_point = np.asarray(yaw_pitch["centroid"], dtype=np.float64)

    all_pts = np.concatenate([perception._mesh.mesh_arrays(o)[0] for o in objects])
    bbox_min = all_pts.min(axis=0)
    bbox_center = (all_pts.min(axis=0) + all_pts.max(axis=0)) * 0.5
    diag = float(np.linalg.norm(all_pts.max(axis=0) - all_pts.min(axis=0)))

    yaw_limits = [float(v) for v in params.get("yaw_limits_deg", [-180.0, 180.0])]
    pitch_limits = [float(v) for v in params.get("pitch_limits_deg", [-15.0, 75.0])]

    def part_bone(obj):
        obb = perception.part_obb(obj)
        head = np.asarray(obb["center"], dtype=np.float64)
        direction = np.asarray(obb["axes"][0], dtype=np.float64)
        if direction[int(np.argmax(np.abs(direction)))] < 0.0:
            direction = -direction
        return head.tolist(), (head + direction * max(float(obb["half_extents"][0]), 1e-3)).tolist()

    return _contract.ok(plan={
        "base": base.name, "yaw": yaw_part.name, "pitch": pitch_part.name,
        "yaw_axis": yaw_axis.tolist(), "pitch_axis": pitch_axis.tolist(),
        "yaw_point": yaw_point.tolist(), "pitch_point": pitch_point.tolist(),
        "yaw_len": max(float(obb_yaw["half_extents"][0]), 1e-3),
        "pitch_len": max(float(obb_pitch["half_extents"][1]), 0.25 * float(obb_pitch["half_extents"][0])),
        "yaw_limits_deg": yaw_limits, "pitch_limits_deg": pitch_limits,
        "name": params.get("name", "Rig.Turret"),
        "root_head": [float(bbox_center[0]), float(bbox_center[1]), float(bbox_min[2])],
        "root_len": 0.25 * diag,
        "bones": {"base": part_bone(base), "yaw": part_bone(yaw_part),
                  "pitch": part_bone(pitch_part)},
    })


def diagnose(ctx: dict, params: dict | None = None) -> dict:
    report = _plan(ctx, params)
    if not report["ok"]:
        _contract.log_failure("rig_turret", "diagnose", report)
    return report


def run(ctx: dict, params: dict | None = None) -> dict:
    planned = _plan(ctx, params)
    if not planned["ok"]:
        _contract.log_failure("rig_turret", "run", planned)
        return planned
    plan = planned["plan"]

    def body(rollback: _contract.Rollback) -> dict:
        yaw_axis = np.asarray(plan["yaw_axis"])
        pitch_axis = np.asarray(plan["pitch_axis"])
        yaw_point = np.asarray(plan["yaw_point"])
        pitch_point = np.asarray(plan["pitch_point"])
        root_head = np.asarray(plan["root_head"])
        def_base = "DEF-" + plan["base"]
        def_yaw = "DEF-" + plan["yaw"]
        def_pitch = "DEF-" + plan["pitch"]

        rig = _armature.build_armature(plan["name"], [
            {"name": "root", "head": root_head.tolist(),
             "tail": (root_head + [0.0, plan["root_len"], 0.0]).tolist()},
            {"name": def_base, "parent": "root", "use_deform": True,
             "head": plan["bones"]["base"][0], "tail": plan["bones"]["base"][1]},
            {"name": "CTL-yaw", "parent": def_base,
             "head": yaw_point.tolist(),
             "tail": (yaw_point + yaw_axis * plan["yaw_len"]).tolist()},
            {"name": def_yaw, "parent": "CTL-yaw", "use_deform": True,
             "head": plan["bones"]["yaw"][0], "tail": plan["bones"]["yaw"][1]},
            {"name": "CTL-pitch", "parent": def_yaw,
             "head": pitch_point.tolist(),
             "tail": (pitch_point + pitch_axis * plan["pitch_len"]).tolist()},
            {"name": def_pitch, "parent": "CTL-pitch", "use_deform": True,
             "head": plan["bones"]["pitch"][0], "tail": plan["bones"]["pitch"][1]},
        ])
        rollback.track_object(rig)

        _bones.add_limit_rotation(
            rig, "CTL-yaw", free_axis="y",
            min_deg=plan["yaw_limits_deg"][0], max_deg=plan["yaw_limits_deg"][1],
            rollback=rollback)
        _bones.add_limit_rotation(
            rig, "CTL-pitch", free_axis="y",
            min_deg=plan["pitch_limits_deg"][0], max_deg=plan["pitch_limits_deg"][1],
            rollback=rollback)
        for part, bone in ((plan["base"], def_base), (plan["yaw"], def_yaw),
                           (plan["pitch"], def_pitch)):
            _bones.bind_rigid(bpy.data.objects[part], rig, bone, rollback=rollback)
        _bones.assign_custom_shapes(rig, rollback=rollback)
        bpy.context.view_layer.update()

        ctx["armature"] = rig.name
        return _contract.ok(
            armature=rig.name,
            turret={
                "controls": {"yaw": "CTL-yaw", "pitch": "CTL-pitch"},
                "yaw_axis": plan["yaw_axis"], "pitch_axis": plan["pitch_axis"],
                "yaw_limits_deg": plan["yaw_limits_deg"],
                "pitch_limits_deg": plan["pitch_limits_deg"],
            },
        )

    return _contract.run_with_rollback("rig_turret", body)


def verify(ctx: dict) -> dict:
    name = ctx.get("armature", "")
    checks = _contract.verify_common(name)
    rig = bpy.data.objects.get(name)
    if rig is None:
        report = _contract.fail("no_armature", checks=checks)
        _contract.log_failure("rig_turret", "verify", report)
        return report

    deform_bones = [b.name for b in rig.data.bones if b.use_deform]
    meshes = {b: bpy.data.objects.get(b[len("DEF-"):]) for b in deform_bones}
    for bone, mesh_obj in meshes.items():
        if mesh_obj is None:
            checks.append(_contract.check("mesh_for_{:s}".format(bone), False))
            continue
        weights = validate_weights(mesh_obj, rig)
        checks.append(_contract.check(
            "weights_{:s}".format(mesh_obj.name), weights["ok"], str(weights["errors"])))

    chain = {b.name: (b.parent.name if b.parent else None) for b in rig.data.bones}
    base_bone = next((b for b in deform_bones if chain.get(b) == "root"), None)
    yaw_bone = next((b for b in deform_bones if chain.get(b) == "CTL-yaw"), None)
    pitch_bone = next((b for b in deform_bones if chain.get(b) == "CTL-pitch"), None)
    checks.append(_contract.check(
        "turret_topology", None not in (base_bone, yaw_bone, pitch_bone)))

    if None not in (base_bone, yaw_bone, pitch_bone) and all(meshes.values()):
        base_mesh = meshes[base_bone]
        yaw_mesh = meshes[yaw_bone]
        pitch_mesh = meshes[pitch_bone]
        sizes = {o.name: max(o.dimensions) for o in meshes.values()}

        snap = {o.name: _bones.evaluated_verts(o) for o in meshes.values()}
        _bones.pose_rotate(rig, "CTL-yaw", "y", 40.0)
        yawed = {o.name: _bones.evaluated_verts(o) for o in meshes.values()}
        checks.append(_contract.check(
            "yaw_moves_platform",
            float(np.abs(yawed[yaw_mesh.name] - snap[yaw_mesh.name]).max()) > 0.02 * sizes[yaw_mesh.name]))
        checks.append(_contract.check(
            "yaw_moves_member",
            float(np.abs(yawed[pitch_mesh.name] - snap[pitch_mesh.name]).max()) > 0.02 * sizes[pitch_mesh.name]))
        checks.append(_contract.check(
            "yaw_keeps_base",
            float(np.abs(yawed[base_mesh.name] - snap[base_mesh.name]).max()) < 1e-5))

        _bones.reset_pose(rig)
        _bones.pose_rotate(rig, "CTL-pitch", "y", 30.0)
        pitched = {o.name: _bones.evaluated_verts(o) for o in meshes.values()}
        checks.append(_contract.check(
            "pitch_moves_member",
            float(np.abs(pitched[pitch_mesh.name] - snap[pitch_mesh.name]).max()) > 0.02 * sizes[pitch_mesh.name]))
        checks.append(_contract.check(
            "pitch_keeps_platform",
            float(np.abs(pitched[yaw_mesh.name] - snap[yaw_mesh.name]).max()) < 1e-5))
        checks.append(_contract.check(
            "pitch_keeps_base",
            float(np.abs(pitched[base_mesh.name] - snap[base_mesh.name]).max()) < 1e-5))
        _bones.reset_pose(rig)

    failed = [c for c in checks if not c["ok"]]
    report = {"ok": not failed, "checks": checks}
    if failed:
        report["fail"] = "verify_failed"
        _contract.log_failure("rig_turret", "verify", report)
    return report
