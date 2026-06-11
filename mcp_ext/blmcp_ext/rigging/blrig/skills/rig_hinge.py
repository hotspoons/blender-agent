# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
rig_hinge: two parts meeting along an elongated contact region -> hinge
bone with a limit-rotation constraint (door, lid, jaw, flap).

Triggers: exactly two rigid parts that should rotate relative to each other
about the line where they meet.
Anti-triggers: parts that slide (rig_piston), spin freely about their own
axis (rig_wheel), or >2 parts (rig_rigid_assembly).

params (all optional, semantic only):
- ``axis_hint``: "x"/"y"/"z" world axis when the contact region alone is
  ambiguous (e.g. face-on-face contact); default auto from contact PCA.
- ``moving``: object name of the part that swings; default smaller volume.
- ``min_angle_deg``/``max_angle_deg``: rotation limits, default -120/120.
- ``name``: armature object name, default "Rig.Hinge".
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

# Contact-PCA elongation (largest/second extent) above which the hinge axis
# is considered unambiguous without a hint.
_AXIS_CONFIDENT_RATIO = 3.0


def _plan(ctx: dict, params: dict | None) -> dict:
    """
    Everything coordinate-level, decided deterministically: health gates,
    contact detection, hinge axis/point, moving part, bone layout. Returns
    an ok-report carrying ``plan`` or a structured failure.
    """
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

    graph = perception.contact_graph(objects)
    if not graph["edges"]:
        return _contract.fail(
            "no_contact",
            detail="parts never touch (tol={:.2e})".format(graph["tol"]),
            suggest="rig_rigid_assembly on the full set, or check object selection")
    edge = max(graph["edges"], key=lambda e: e["n_points"])

    axis_hint = params.get("axis_hint")
    extents = edge["extents"]
    elongation = extents[0] / max(extents[1], 1e-9)
    if axis_hint is not None:
        axis = np.asarray(_AXES.get(axis_hint, axis_hint), dtype=np.float64)
        axis /= np.linalg.norm(axis)
    elif edge["axis"] is not None and elongation >= _AXIS_CONFIDENT_RATIO:
        axis = np.asarray(edge["axis"], dtype=np.float64)
    else:
        return _contract.fail(
            "ambiguous_axis",
            elongation=float(elongation),
            detail="contact region is not elongated; hinge direction unclear",
            suggest="pass params={'axis_hint': 'x'|'y'|'z'}")
    # Deterministic sign: largest-magnitude component positive.
    if axis[int(np.argmax(np.abs(axis)))] < 0.0:
        axis = -axis

    centroid = np.asarray(edge["centroid"], dtype=np.float64)
    obbs = {obj.name: perception.part_obb(obj) for obj in objects}

    def hinge_line_distance(obj) -> float:
        v = np.asarray(obbs[obj.name]["center"]) - centroid
        return float(np.linalg.norm(v - (v @ axis) * axis))

    moving_name = params.get("moving")
    if moving_name is not None:
        moving = bpy.data.objects.get(moving_name)
        if moving not in objects:
            return _contract.fail("bad_param", param="moving",
                                  detail="must be one of ctx['objects']")
    else:
        # The swinging part reaches away from the hinge line (a door extends
        # from its hinges; the frame post sits on them). Near-ties (stacked
        # parts) fall back to "smaller part moves".
        d0, d1 = (hinge_line_distance(o) for o in objects)
        sizes = [max(float(h) for h in obbs[o.name]["half_extents"]) for o in objects]
        if abs(d0 - d1) > 0.1 * max(sizes):
            moving = objects[0] if d0 > d1 else objects[1]
        else:
            moving = min(objects, key=lambda o: obbs[o.name]["volume"])
    fixed = next(o for o in objects if o is not moving)

    obb_fixed = obbs[fixed.name]
    obb_moving = obbs[moving.name]
    hinge_len = max(float(extents[0]), 0.25 * float(obb_moving["half_extents"][0]))

    all_pts = np.concatenate([perception._mesh.mesh_arrays(o)[0] for o in objects])
    bbox_min = all_pts.min(axis=0)
    bbox_center = (all_pts.min(axis=0) + all_pts.max(axis=0)) * 0.5
    diag = float(np.linalg.norm(all_pts.max(axis=0) - all_pts.min(axis=0)))

    def part_bone(obb):
        head = np.asarray(obb["center"], dtype=np.float64)
        direction = np.asarray(obb["axes"][0], dtype=np.float64)
        if direction[int(np.argmax(np.abs(direction)))] < 0.0:
            direction = -direction
        return head, head + direction * max(float(obb["half_extents"][0]), 1e-3)

    fixed_head, fixed_tail = part_bone(obb_fixed)
    moving_head, moving_tail = part_bone(obb_moving)

    return _contract.ok(plan={
        "fixed": fixed.name,
        "moving": moving.name,
        "axis": axis.tolist(),
        "hinge_point": centroid.tolist(),
        "hinge_len": hinge_len,
        "elongation": float(elongation),
        "contact_kind": edge["kind"],
        "min_angle_deg": float(params.get("min_angle_deg", -120.0)),
        "max_angle_deg": float(params.get("max_angle_deg", 120.0)),
        "name": params.get("name", "Rig.Hinge"),
        "root_head": [bbox_center[0], bbox_center[1], bbox_min[2]],
        "root_len": 0.25 * diag,
        "bones": {
            "fixed": [fixed_head.tolist(), fixed_tail.tolist()],
            "moving": [moving_head.tolist(), moving_tail.tolist()],
        },
    })


def diagnose(ctx: dict, params: dict | None = None) -> dict:
    """
    Precondition check; never mutates the scene.
    """
    report = _plan(ctx, params)
    if not report["ok"]:
        _contract.log_failure("rig_hinge", "diagnose", report)
    return report


def run(ctx: dict, params: dict | None = None) -> dict:
    planned = _plan(ctx, params)
    if not planned["ok"]:
        _contract.log_failure("rig_hinge", "run", planned)
        return planned
    plan = planned["plan"]

    def body(rollback: _contract.Rollback) -> dict:
        axis = np.asarray(plan["axis"])
        point = np.asarray(plan["hinge_point"])
        root_head = np.asarray(plan["root_head"])
        fixed_bone = "DEF-" + plan["fixed"]
        moving_bone = "DEF-" + plan["moving"]

        rig = _armature.build_armature(plan["name"], [
            {"name": "root", "head": root_head.tolist(),
             "tail": (root_head + [0.0, plan["root_len"], 0.0]).tolist()},
            {"name": fixed_bone, "parent": "root", "use_deform": True,
             "head": plan["bones"]["fixed"][0], "tail": plan["bones"]["fixed"][1]},
            {"name": "CTL-hinge", "parent": fixed_bone,
             "head": point.tolist(),
             "tail": (point + axis * plan["hinge_len"]).tolist()},
            {"name": moving_bone, "parent": "CTL-hinge", "use_deform": True,
             "head": plan["bones"]["moving"][0], "tail": plan["bones"]["moving"][1]},
        ])
        rollback.track_object(rig)

        _bones.add_limit_rotation(
            rig, "CTL-hinge", free_axis="y",
            min_deg=plan["min_angle_deg"], max_deg=plan["max_angle_deg"],
            rollback=rollback)
        _bones.bind_rigid(bpy.data.objects[plan["fixed"]], rig, fixed_bone, rollback=rollback)
        _bones.bind_rigid(bpy.data.objects[plan["moving"]], rig, moving_bone, rollback=rollback)
        _bones.assign_custom_shapes(rig, rollback=rollback)
        bpy.context.view_layer.update()

        ctx["armature"] = rig.name
        return _contract.ok(
            armature=rig.name,
            hinge={
                "point": plan["hinge_point"],
                "axis": plan["axis"],
                "moving": plan["moving"],
                "control": "CTL-hinge",
                "limits_deg": [plan["min_angle_deg"], plan["max_angle_deg"]],
            },
        )

    return _contract.run_with_rollback("rig_hinge", body)


def verify(ctx: dict) -> dict:
    """
    Postconditions: standard-valid rig, valid weights, and the hinge
    actually hinges — moving part swings, fixed part stays, limits clamp.
    """
    name = ctx.get("armature", "")
    checks = _contract.verify_common(name)
    rig = bpy.data.objects.get(name)
    if rig is None:
        report = _contract.fail("no_armature", checks=checks)
        _contract.log_failure("rig_hinge", "verify", report)
        return report

    moving_bone = next((b.name for b in rig.data.bones
                        if b.use_deform and b.parent and b.parent.name == "CTL-hinge"), None)
    fixed_bone = next((b.name for b in rig.data.bones
                       if b.use_deform and b.name != moving_bone), None)
    checks.append(_contract.check("hinge_topology", moving_bone is not None and fixed_bone is not None))

    if moving_bone and fixed_bone:
        moving = bpy.data.objects.get(moving_bone[len("DEF-"):])
        fixed = bpy.data.objects.get(fixed_bone[len("DEF-"):])
        for mesh_obj in (moving, fixed):
            weights = validate_weights(mesh_obj, rig)
            checks.append(_contract.check(
                "weights_{:s}".format(mesh_obj.name), weights["ok"], str(weights["errors"])))

        size = max(moving.dimensions)
        base_moving = _bones.evaluated_verts(moving)
        base_fixed = _bones.evaluated_verts(fixed)

        _bones.pose_rotate(rig, "CTL-hinge", "y", 45.0)
        swung = _bones.evaluated_verts(moving)
        fixed_now = _bones.evaluated_verts(fixed)
        moved = float(np.abs(swung - base_moving).max())
        fixed_drift = float(np.abs(fixed_now - base_fixed).max())
        checks.append(_contract.check(
            "moving_part_swings", moved > 0.05 * size,
            "max displacement {:.4f}".format(moved)))
        checks.append(_contract.check(
            "fixed_part_static", fixed_drift < 1e-5,
            "max drift {:.2e}".format(fixed_drift)))

        # Rigidity: pairwise distances within the moving part preserved.
        idx = np.linspace(0, len(base_moving) - 1, min(8, len(base_moving)), dtype=int)
        d_before = np.linalg.norm(base_moving[idx][None] - base_moving[idx][:, None], axis=-1)
        d_after = np.linalg.norm(swung[idx][None] - swung[idx][:, None], axis=-1)
        checks.append(_contract.check(
            "moving_part_rigid", float(np.abs(d_before - d_after).max()) < 1e-5 * max(size, 1.0)))

        # Limits clamp: posing far past the max changes nothing vs at-max.
        limit = rig.pose.bones["CTL-hinge"].constraints[0].max_y
        import math
        _bones.pose_rotate(rig, "CTL-hinge", "y", math.degrees(limit))
        at_max = _bones.evaluated_verts(moving)
        _bones.pose_rotate(rig, "CTL-hinge", "y", math.degrees(limit) + 40.0)
        past_max = _bones.evaluated_verts(moving)
        checks.append(_contract.check(
            "limits_clamp", float(np.abs(at_max - past_max).max()) < 1e-5,
            "drift past limit {:.2e}".format(float(np.abs(at_max - past_max).max()))))

        _bones.reset_pose(rig)

    failed = [c for c in checks if not c["ok"]]
    report = {"ok": not failed, "checks": checks}
    if failed:
        report["fail"] = "verify_failed"
        _contract.log_failure("rig_hinge", "verify", report)
    return report
