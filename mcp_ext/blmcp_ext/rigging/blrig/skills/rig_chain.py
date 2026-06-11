# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
rig_chain: an ORDERED series of parts -> serial joint chain with a ball
or hinge joint between each consecutive pair (spider legs, robot arms,
tails, landing gear, excavator booms — any linkage).

This is the composable primitive the specific mechanisms don't cover:
joints are placed at the contact between consecutive parts, or — when
parts are modeled with clearance — BRIDGED at the nearest-pair midpoint
automatically (no contact required, the order already says they connect).
Pass ``armature`` to add the chain to an EXISTING rig (e.g. legs onto the
armature rig_rigid_assembly built for the body) instead of creating one.

ctx["objects"] order is semantic: root segment first, tip last.

params:
- ``joint_types``: list of "ball"/"hinge", one per joint (len(objects)-1);
  default all "ball". Hinges get limit-rotation constraints; balls rotate
  freely.
- ``hinge_axis_hint``: "x"/"y"/"z" world-axis hint applied to hinge joints
  whose axis cannot be derived (no elongated contact); default: the cross
  product of the two segments' major axes (a knee bends perpendicular to
  both bones).
- ``hinge_limits_deg``: [min, max] for hinge joints, default [-120, 120].
- ``armature``: name of an existing armature to extend; the chain's first
  control parents to ``parent_bone`` (default "root") in it.
- ``parent_bone``: bone in ``armature`` to hang the chain from.
- ``name``: armature name when creating one, default "Rig.Chain".
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
_HINGE_ELONGATION = 3.0


def _plan(ctx: dict, params: dict | None) -> dict:
    params = params or {}
    objects, err = _contract.resolve_objects(ctx)
    if err is not None:
        return err
    if len(objects) < 2:
        return _contract.fail(
            "wrong_object_count",
            detail="a chain needs at least 2 ordered parts in ctx['objects']")

    if not params.get("ignore_health"):
        for obj in objects:
            health = perception.mesh_health(obj)
            if not health["ok"]:
                return _contract.fail(
                    "unhealthy_mesh", object=obj.name, issues=health["issues"],
                    suggest="apply scale / clean mesh, or params={'ignore_health': True}")

    joint_types = params.get("joint_types") or ["ball"] * (len(objects) - 1)
    if len(joint_types) != len(objects) - 1:
        return _contract.fail(
            "bad_param", param="joint_types",
            detail="need {:d} joint types for {:d} parts, got {:d}".format(
                len(objects) - 1, len(objects), len(joint_types)))
    bad_types = [t for t in joint_types if t not in ("ball", "hinge")]
    if bad_types:
        return _contract.fail(
            "bad_param", param="joint_types",
            detail="unknown joint type(s) {!r}; valid: ball, hinge".format(bad_types))

    armature_name = params.get("armature")
    if armature_name is not None:
        existing = bpy.data.objects.get(armature_name)
        if existing is None or existing.type != "ARMATURE":
            return _contract.fail("bad_param", param="armature",
                                  detail="{!r} is not an armature object".format(armature_name))
        parent_bone = params.get("parent_bone", "root")
        if parent_bone not in existing.data.bones:
            return _contract.fail("bad_param", param="parent_bone",
                                  detail="no bone {!r} in {!r}".format(parent_bone, armature_name))

    obbs = [perception.part_obb(obj) for obj in objects]
    hint = params.get("hinge_axis_hint")

    joints = []
    for i, joint_type in enumerate(joint_types):
        a, b = objects[i], objects[i + 1]
        graph = perception.contact_graph(
            [a, b], tol=params.get("contact_tolerance"))
        if graph["edges"]:
            edge = max(graph["edges"], key=lambda e: e["n_points"])
            point = edge["centroid"]
            gap = float(edge.get("max_gap", 0.0))
            contact_kind = edge["kind"]
            contact_axis = edge["axis"]
            elongation = edge["extents"][0] / max(edge["extents"][1], 1e-9)
        else:
            near = perception.nearest_gap(a, b)
            if near["point"] is None:
                return _contract.fail(
                    "no_geometry", object=a.name if not a.data.vertices else b.name)
            point = near["point"]
            gap = float(near["distance"])
            contact_kind = "bridged"
            contact_axis = None
            elongation = 0.0

        axis = None
        if joint_type == "hinge":
            if hint is not None:
                axis = np.asarray(_AXES[hint], dtype=np.float64)
            elif contact_axis is not None and elongation >= _HINGE_ELONGATION:
                axis = np.asarray(contact_axis, dtype=np.float64)
            else:
                # A knee bends perpendicular to both segments.
                cross = np.cross(np.asarray(obbs[i]["axes"][0]),
                                 np.asarray(obbs[i + 1]["axes"][0]))
                norm = float(np.linalg.norm(cross))
                if norm < 0.1:
                    return _contract.fail(
                        "ambiguous_axis", joint=i,
                        detail="segments {:s}->{:s} are parallel; hinge axis "
                               "unclear".format(a.name, b.name),
                        suggest="pass params={'hinge_axis_hint': 'x'|'y'|'z'}")
                axis = cross / norm
            if axis[int(np.argmax(np.abs(axis)))] < 0.0:
                axis = -axis

        joints.append({
            "parent": a.name,
            "child": b.name,
            "type": joint_type,
            "point": list(point),
            "axis": axis.tolist() if axis is not None else None,
            "contact_kind": contact_kind,
            "gap": gap,
        })

    all_pts = np.concatenate([perception._mesh.mesh_arrays(o)[0] for o in objects])
    bbox_min = all_pts.min(axis=0)
    bbox_center = (all_pts.min(axis=0) + all_pts.max(axis=0)) * 0.5
    diag = float(np.linalg.norm(all_pts.max(axis=0) - all_pts.min(axis=0)))

    def part_bone(index):
        obb = obbs[index]
        head = np.asarray(obb["center"], dtype=np.float64)
        direction = np.asarray(obb["axes"][0], dtype=np.float64)
        if direction[int(np.argmax(np.abs(direction)))] < 0.0:
            direction = -direction
        return head.tolist(), (head + direction * max(float(obb["half_extents"][0]), 1e-3)).tolist()

    return _contract.ok(plan={
        "parts": [o.name for o in objects],
        "bones": [part_bone(i) for i in range(len(objects))],
        "joints": joints,
        "hinge_limits_deg": [float(v) for v in params.get("hinge_limits_deg", [-120.0, 120.0])],
        "armature": armature_name,
        "parent_bone": params.get("parent_bone", "root"),
        "name": params.get("name", "Rig.Chain"),
        "root_head": [float(bbox_center[0]), float(bbox_center[1]), float(bbox_min[2])],
        "root_len": 0.25 * diag,
        "joint_len": 0.12 * diag,
    })


def diagnose(ctx: dict, params: dict | None = None) -> dict:
    report = _plan(ctx, params)
    if not report["ok"]:
        _contract.log_failure("rig_chain", "diagnose", report)
    return report


def run(ctx: dict, params: dict | None = None) -> dict:
    planned = _plan(ctx, params)
    if not planned["ok"]:
        _contract.log_failure("rig_chain", "run", planned)
        return planned
    plan = planned["plan"]

    def body(rollback: _contract.Rollback) -> dict:
        specs = []
        parent = None
        for i, part in enumerate(plan["parts"]):
            if i > 0:
                joint = plan["joints"][i - 1]
                point = np.asarray(joint["point"])
                if joint["type"] == "hinge":
                    direction = np.asarray(joint["axis"])
                else:
                    # Ball joints aim at the next part's center.
                    direction = np.asarray(plan["bones"][i][0]) - point
                    norm = np.linalg.norm(direction)
                    direction = direction / norm if norm > 1e-9 else np.array([0.0, 0.0, 1.0])
                ctl = "CTL-" + part
                specs.append({
                    "name": ctl, "parent": parent,
                    "head": point.tolist(),
                    "tail": (point + direction * plan["joint_len"]).tolist(),
                })
                parent = ctl
            deform = "DEF-" + part
            specs.append({
                "name": deform, "parent": parent, "use_deform": True,
                "head": plan["bones"][i][0], "tail": plan["bones"][i][1],
            })
            parent = deform

        if plan["armature"]:
            rig = bpy.data.objects[plan["armature"]]
            collision = next(
                (s["name"] for s in specs if s["name"] in rig.data.bones), None)
            if collision is not None:
                return _contract.fail(
                    "bone_exists", bone=collision,
                    detail="{!r} already exists in {!r}".format(collision, rig.name))
            specs[0]["parent"] = plan["parent_bone"]
            rollback.track_bones(rig, _armature.add_bones(rig, specs))
        else:
            root_head = np.asarray(plan["root_head"])
            root_spec = {
                "name": "root",
                "head": root_head.tolist(),
                "tail": (root_head + [0.0, plan["root_len"], 0.0]).tolist(),
            }
            specs[0]["parent"] = "root"
            rig = _armature.build_armature(plan["name"], [root_spec] + specs)
            rollback.track_object(rig)

        for i, joint in enumerate(plan["joints"]):
            ctl = "CTL-" + plan["parts"][i + 1]
            pb = rig.pose.bones[ctl]
            pb.rotation_mode = "XYZ"
            pb.lock_location = (True, True, True)
            pb.lock_scale = (True, True, True)
            if joint["type"] == "hinge":
                _bones.add_limit_rotation(
                    rig, ctl, free_axis="y",
                    min_deg=plan["hinge_limits_deg"][0],
                    max_deg=plan["hinge_limits_deg"][1],
                    rollback=rollback)

        for part in plan["parts"]:
            _bones.bind_rigid(bpy.data.objects[part], rig, "DEF-" + part,
                              rollback=rollback)
        _bones.assign_custom_shapes(rig, rollback=rollback)
        bpy.context.view_layer.update()

        ctx["armature"] = rig.name
        ctx["chain_controls"] = ["CTL-" + p for p in plan["parts"][1:]]
        return _contract.ok(
            armature=rig.name,
            chain={
                "parts": plan["parts"],
                "joints": plan["joints"],
                "controls": ctx["chain_controls"],
                "extended_existing": bool(plan["armature"]),
            },
        )

    return _contract.run_with_rollback("rig_chain", body)


def verify(ctx: dict) -> dict:
    """
    Postconditions: standard-valid rig, valid weights, and the chain
    chains — rotating joint k moves every part distal to it and none
    proximal to it.
    """
    name = ctx.get("armature", "")
    checks = _contract.verify_common(name)
    rig = bpy.data.objects.get(name)
    if rig is None:
        report = _contract.fail("no_armature", checks=checks)
        _contract.log_failure("rig_chain", "verify", report)
        return report

    controls = ctx.get("chain_controls") or [
        b.name for b in rig.data.bones if b.name.startswith("CTL-")]
    parts = []
    for ctl in controls:
        mesh_obj = bpy.data.objects.get(ctl[len("CTL-"):])
        if mesh_obj is not None:
            parts.append(mesh_obj)
            weights = validate_weights(mesh_obj, rig)
            checks.append(_contract.check(
                "weights_{:s}".format(mesh_obj.name), weights["ok"],
                str(weights["errors"])))

    if parts:
        rest = {o.name: _bones.evaluated_verts(o) for o in parts}
        sizes = {o.name: max(o.dimensions) for o in parts}
        for k, ctl in enumerate(controls):
            # Hinge constraints free local Y; ball joints are free on
            # all axes, so Y exercises both kinds.
            _bones.pose_rotate(rig, ctl, "y", 30.0)
            for j, obj in enumerate(parts):
                moved = float(np.abs(
                    _bones.evaluated_verts(obj) - rest[obj.name]).max())
                if j >= k:
                    checks.append(_contract.check(
                        "joint{:d}_moves_{:s}".format(k, obj.name),
                        moved > 0.01 * sizes[obj.name],
                        "displacement {:.4f}".format(moved)))
                else:
                    checks.append(_contract.check(
                        "joint{:d}_keeps_{:s}".format(k, obj.name),
                        moved < 1e-5,
                        "displacement {:.2e}".format(moved)))
            _bones.reset_pose(rig)

    failed = [c for c in checks if not c["ok"]]
    report = {"ok": not failed, "checks": checks}
    if failed:
        report["fail"] = "verify_failed"
        _contract.log_failure("rig_chain", "verify", report)
    return report
