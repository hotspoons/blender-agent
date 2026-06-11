# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
rig_piston: two elongated, roughly coaxial parts that slide/aim along the
line between their anchor points (hydraulic cylinders, shock absorbers,
telescopes).

Implementation: paired damped-track bones — each part's bone aims at the
other part's anchor control, so dragging either anchor extends/retracts the
piston while both halves stay aligned.

Triggers: rod-in-sleeve pairs, anything that extends/retracts along a line.
Anti-triggers: parts that rotate about a shared edge (rig_hinge) or spin in
place (rig_wheel).

params:
- ``name``: armature name, default "Rig.Piston".
- ``ignore_health``: accept unhealthy meshes (default False).
- ``ignore_alignment``: skip the coaxiality check (default False).
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

# Minimum |dot| between the two parts' major axes to count as coaxial.
_COAXIAL_DOT = 0.9
# Major extent must dominate the second extent for a part to read as a rod.
_ELONGATION = 1.5


def _plan(ctx: dict, params: dict | None) -> dict:
    params = params or {}
    objects, err = _contract.resolve_objects(ctx, expected=2)
    if err is not None:
        return err

    if not params.get("ignore_health"):
        for obj in objects:
            health = perception.mesh_health(obj)
            if not health["ok"]:
                return _contract.fail(
                    "unhealthy_mesh", object=obj.name, issues=health["issues"],
                    suggest="apply scale / clean mesh, or params={'ignore_health': True}")

    obbs = {o.name: perception.part_obb(o) for o in objects}
    axes = {}
    for o in objects:
        half = obbs[o.name]["half_extents"]
        if half[0] < _ELONGATION * max(half[1], 1e-9):
            return _contract.fail(
                "not_elongated", object=o.name,
                aspect=[float(a) for a in obbs[o.name]["aspect"]],
                detail="piston halves must be rod-like (major extent >= {:.1f}x second)".format(
                    _ELONGATION),
                suggest="rig_hinge or rig_rigid_assembly")
        axes[o.name] = np.asarray(obbs[o.name]["axes"][0], dtype=np.float64)

    a, b = objects
    alignment = abs(float(axes[a.name] @ axes[b.name]))
    if alignment < _COAXIAL_DOT and not params.get("ignore_alignment"):
        return _contract.fail(
            "not_coaxial", alignment=alignment,
            detail="major axes disagree (|dot|={:.2f}, need >={:.2f})".format(
                alignment, _COAXIAL_DOT),
            suggest="rig_hinge if they pivot where they meet, or "
                    "params={'ignore_alignment': True}")

    # Anchor of each part: the major-axis OBB endpoint farther from the
    # other part's center — the "outer" end the piston hangs from.
    anchors = {}
    for this, other in ((a, b), (b, a)):
        obb = obbs[this.name]
        center = np.asarray(obb["center"], dtype=np.float64)
        offset = axes[this.name] * float(obb["half_extents"][0])
        ends = (center + offset, center - offset)
        other_center = np.asarray(obbs[other.name]["center"], dtype=np.float64)
        anchors[this.name] = max(
            ends, key=lambda e: float(np.linalg.norm(e - other_center)))

    all_pts = np.concatenate([perception._mesh.mesh_arrays(o)[0] for o in objects])
    bbox_min = all_pts.min(axis=0)
    bbox_center = (all_pts.min(axis=0) + all_pts.max(axis=0)) * 0.5
    diag = float(np.linalg.norm(all_pts.max(axis=0) - all_pts.min(axis=0)))

    return _contract.ok(plan={
        "a": a.name,
        "b": b.name,
        "anchor_a": anchors[a.name].tolist(),
        "anchor_b": anchors[b.name].tolist(),
        "alignment": alignment,
        "name": params.get("name", "Rig.Piston"),
        "root_head": [bbox_center[0], bbox_center[1], float(bbox_min[2])],
        "root_len": 0.25 * diag,
    })


def diagnose(ctx: dict, params: dict | None = None) -> dict:
    report = _plan(ctx, params)
    if not report["ok"]:
        _contract.log_failure("rig_piston", "diagnose", report)
    return report


def run(ctx: dict, params: dict | None = None) -> dict:
    planned = _plan(ctx, params)
    if not planned["ok"]:
        _contract.log_failure("rig_piston", "run", planned)
        return planned
    plan = planned["plan"]

    def body(rollback: _contract.Rollback) -> dict:
        anchor_a = np.asarray(plan["anchor_a"])
        anchor_b = np.asarray(plan["anchor_b"])
        span = anchor_b - anchor_a
        length = float(np.linalg.norm(span))
        direction = span / max(length, 1e-9)
        ctl_len = max(0.15 * length, 1e-3)
        root_head = np.asarray(plan["root_head"])
        def_a = "DEF-" + plan["a"]
        def_b = "DEF-" + plan["b"]

        # Anchor controls stick outward; deform bones aim inward at the
        # opposite anchor and damped-track it at runtime.
        rig = _armature.build_armature(plan["name"], [
            {"name": "root", "head": root_head.tolist(),
             "tail": (root_head + [0.0, plan["root_len"], 0.0]).tolist()},
            {"name": "CTL-anchor.A", "parent": "root",
             "head": anchor_a.tolist(), "tail": (anchor_a - direction * ctl_len).tolist()},
            {"name": "CTL-anchor.B", "parent": "root",
             "head": anchor_b.tolist(), "tail": (anchor_b + direction * ctl_len).tolist()},
            {"name": def_a, "parent": "CTL-anchor.A", "use_deform": True,
             "head": anchor_a.tolist(), "tail": anchor_b.tolist()},
            {"name": def_b, "parent": "CTL-anchor.B", "use_deform": True,
             "head": anchor_b.tolist(), "tail": anchor_a.tolist()},
        ])
        rollback.track_object(rig)

        _bones.add_damped_track(rig, def_a, "CTL-anchor.B", rollback=rollback)
        _bones.add_damped_track(rig, def_b, "CTL-anchor.A", rollback=rollback)
        _bones.bind_rigid(bpy.data.objects[plan["a"]], rig, def_a, rollback=rollback)
        _bones.bind_rigid(bpy.data.objects[plan["b"]], rig, def_b, rollback=rollback)
        _bones.assign_custom_shapes(rig, rollback=rollback)
        bpy.context.view_layer.update()

        ctx["armature"] = rig.name
        return _contract.ok(
            armature=rig.name,
            piston={
                "anchors": {plan["a"]: plan["anchor_a"], plan["b"]: plan["anchor_b"]},
                "controls": ["CTL-anchor.A", "CTL-anchor.B"],
                "length": length,
            },
        )

    return _contract.run_with_rollback("rig_piston", body)


def _bone_y_world(rig: bpy.types.Object, bone: str) -> np.ndarray:
    """
    The evaluated world-space Y (aim) axis of a pose bone.
    """
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_rig = rig.evaluated_get(depsgraph)
    mat = eval_rig.matrix_world @ eval_rig.pose.bones[bone].matrix
    y = np.array([mat[0][1], mat[1][1], mat[2][1]], dtype=np.float64)
    return y / np.linalg.norm(y)


def verify(ctx: dict) -> dict:
    name = ctx.get("armature", "")
    checks = _contract.verify_common(name)
    rig = bpy.data.objects.get(name)
    if rig is None:
        report = _contract.fail("no_armature", checks=checks)
        _contract.log_failure("rig_piston", "verify", report)
        return report

    deform_bones = [b.name for b in rig.data.bones if b.use_deform]
    checks.append(_contract.check("two_deform_bones", len(deform_bones) == 2))

    for bone in deform_bones:
        mesh_obj = bpy.data.objects.get(bone[len("DEF-"):])
        if mesh_obj is None:
            checks.append(_contract.check("mesh_for_{:s}".format(bone), False))
            continue
        weights = validate_weights(mesh_obj, rig)
        checks.append(_contract.check(
            "weights_{:s}".format(mesh_obj.name), weights["ok"], str(weights["errors"])))

    if len(deform_bones) == 2:
        # Drag anchor B sideways: both deform bones must still aim along the
        # (new) line between the two anchors — that's what a piston does.
        pb = rig.pose.bones["CTL-anchor.B"]
        pb.location = (0.6, 0.4, 0.3)
        bpy.context.view_layer.update()

        depsgraph = bpy.context.evaluated_depsgraph_get()
        eval_rig = rig.evaluated_get(depsgraph)
        head_a = np.array(
            (eval_rig.matrix_world @ eval_rig.pose.bones["CTL-anchor.A"].matrix).translation)
        head_b = np.array(
            (eval_rig.matrix_world @ eval_rig.pose.bones["CTL-anchor.B"].matrix).translation)
        line = head_b - head_a
        line /= np.linalg.norm(line)

        aim_a = _bone_y_world(rig, deform_bones[0])
        aim_b = _bone_y_world(rig, deform_bones[1])
        align_a = abs(float(aim_a @ line))
        align_b = abs(float(aim_b @ line))
        checks.append(_contract.check(
            "tracks_when_extended", align_a > 0.999 and align_b > 0.999,
            "alignment {:.4f}/{:.4f}".format(align_a, align_b)))

        moved = np.linalg.norm(head_b - np.array(rig.matrix_world @ rig.data.bones["CTL-anchor.B"].head_local))
        checks.append(_contract.check("anchor_moves", float(moved) > 0.1))
        _bones.reset_pose(rig)

    failed = [c for c in checks if not c["ok"]]
    report = {"ok": not failed, "checks": checks}
    if failed:
        report["fail"] = "verify_failed"
        _contract.log_failure("rig_piston", "verify", report)
    return report
