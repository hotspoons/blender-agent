# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
rig_wheel: a disc-like part -> free-spinning control about its disc axis
(wheels, gears, fans, dials, pulleys).

Triggers: one part that is round about an axis and should spin freely.
Anti-triggers: parts that swing about an edge where they meet another part
(rig_hinge), aiming/sliding pairs (rig_piston).

params:
- ``name``: armature name, default "Rig.Wheel".
- ``axis_hint``: "x"/"y"/"z" override when the disc axis detection is
  ambiguous (nearly spherical parts).
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

# A wheel: two near-equal major extents (rim circle)...
_ROUNDNESS_TOL = 0.15
# ...and a clearly smaller third (disc thickness).
_FLATNESS_RATIO = 0.7


def _plan(ctx: dict, params: dict | None) -> dict:
    params = params or {}
    objects, err = _contract.resolve_objects(ctx, expected=1)
    if err is not None:
        return err
    wheel = objects[0]

    if not params.get("ignore_health"):
        health = perception.mesh_health(wheel)
        if not health["ok"]:
            return _contract.fail(
                "unhealthy_mesh", object=wheel.name, issues=health["issues"],
                suggest="apply scale / clean mesh, or params={'ignore_health': True}")

    obb = perception.part_obb(wheel)
    half = obb["half_extents"]
    roundness = abs(half[0] - half[1]) / max(half[0], 1e-9)
    flatness = half[2] / max(half[0], 1e-9)

    axis_hint = params.get("axis_hint")
    if axis_hint is not None:
        axis = np.asarray(_AXES.get(axis_hint, axis_hint), dtype=np.float64)
        axis /= np.linalg.norm(axis)
    else:
        if roundness > _ROUNDNESS_TOL or flatness > _FLATNESS_RATIO:
            return _contract.fail(
                "not_a_wheel",
                roundness=float(roundness), flatness=float(flatness),
                detail="expected two near-equal extents and a smaller third; "
                       "rim roundness {:.0%} (need <{:.0%}), thickness ratio {:.0%} "
                       "(need <{:.0%})".format(
                           roundness, _ROUNDNESS_TOL, flatness, _FLATNESS_RATIO),
                suggest="rig_hinge for swinging parts, or pass params={'axis_hint': ...}")
        axis = np.asarray(obb["axes"][2], dtype=np.float64)
    if axis[int(np.argmax(np.abs(axis)))] < 0.0:
        axis = -axis

    center = np.asarray(obb["center"], dtype=np.float64)
    radius = float((half[0] + half[1]) * 0.5)

    verts, _tris = perception._mesh.mesh_arrays(wheel)
    return _contract.ok(plan={
        "wheel": wheel.name,
        "axis": axis.tolist(),
        "center": center.tolist(),
        "radius": radius,
        "thickness": float(half[2] * 2.0),
        "name": params.get("name", "Rig.Wheel"),
        "floor_z": float(verts.min(axis=0)[2]),
    })


def diagnose(ctx: dict, params: dict | None = None) -> dict:
    report = _plan(ctx, params)
    if not report["ok"]:
        _contract.log_failure("rig_wheel", "diagnose", report)
    return report


def run(ctx: dict, params: dict | None = None) -> dict:
    planned = _plan(ctx, params)
    if not planned["ok"]:
        _contract.log_failure("rig_wheel", "run", planned)
        return planned
    plan = planned["plan"]

    def body(rollback: _contract.Rollback) -> dict:
        axis = np.asarray(plan["axis"])
        center = np.asarray(plan["center"])
        bone_len = max(plan["radius"] * 0.75, plan["thickness"])
        root_head = np.array([center[0], center[1], plan["floor_z"]])
        deform = "DEF-" + plan["wheel"]

        rig = _armature.build_armature(plan["name"], [
            {"name": "root", "head": root_head.tolist(),
             "tail": (root_head + [0.0, max(plan["radius"], 1e-3), 0.0]).tolist()},
            {"name": "CTL-spin", "parent": "root",
             "head": center.tolist(), "tail": (center + axis * bone_len).tolist()},
            {"name": deform, "parent": "CTL-spin", "use_deform": True,
             "head": center.tolist(), "tail": (center + axis * bone_len * 0.5).tolist()},
        ])
        rollback.track_object(rig)

        # Free spin about the bone axis; everything else locked.
        pb = rig.pose.bones["CTL-spin"]
        pb.rotation_mode = "XYZ"
        pb.lock_location = (True, True, True)
        pb.lock_scale = (True, True, True)
        pb.lock_rotation = (True, False, True)

        _bones.bind_rigid(bpy.data.objects[plan["wheel"]], rig, deform, rollback=rollback)
        _bones.assign_custom_shapes(rig, rollback=rollback)
        bpy.context.view_layer.update()

        ctx["armature"] = rig.name
        return _contract.ok(
            armature=rig.name,
            wheel={"axis": plan["axis"], "center": plan["center"],
                   "radius": plan["radius"], "control": "CTL-spin"},
        )

    return _contract.run_with_rollback("rig_wheel", body)


def verify(ctx: dict) -> dict:
    name = ctx.get("armature", "")
    checks = _contract.verify_common(name)
    rig = bpy.data.objects.get(name)
    if rig is None:
        report = _contract.fail("no_armature", checks=checks)
        _contract.log_failure("rig_wheel", "verify", report)
        return report

    deform = next((b.name for b in rig.data.bones if b.use_deform), None)
    checks.append(_contract.check("deform_bone", deform is not None))
    if deform is not None:
        wheel = bpy.data.objects.get(deform[len("DEF-"):])
        weights = validate_weights(wheel, rig)
        checks.append(_contract.check("weights", weights["ok"], str(weights["errors"])))

        base = _bones.evaluated_verts(wheel)
        _bones.pose_rotate(rig, "CTL-spin", "y", 90.0)
        spun = _bones.evaluated_verts(wheel)
        disp = np.abs(spun - base).max()
        center_drift = float(np.linalg.norm(spun.mean(axis=0) - base.mean(axis=0)))
        radius = float(np.linalg.norm(base - base.mean(axis=0), axis=1).max())
        checks.append(_contract.check(
            "rim_spins", disp > 0.5 * radius, "max displacement {:.4f}".format(float(disp))))
        checks.append(_contract.check(
            "center_fixed", center_drift < 1e-4 * max(radius, 1.0),
            "center drift {:.2e}".format(center_drift)))
        _bones.reset_pose(rig)

    failed = [c for c in checks if not c["ok"]]
    report = {"ok": not failed, "checks": checks}
    if failed:
        report["fail"] = "verify_failed"
        _contract.log_failure("rig_wheel", "verify", report)
    return report
