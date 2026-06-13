# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Shared implementation of the Rigify-based character skills: metarig
placement from perception, generation, bone-heat skinning, deformation
verification. ``rig_biped_rigify`` / ``rig_quadruped_rigify`` are thin
parameterizations of this module.
"""

__all__ = (
    "character_diagnose",
    "character_run",
    "character_verify",
)

import numpy as np

import bpy

from .. import perception
from ..standard import validate_rig, validate_weights
from . import _bones
from . import _contract
from . import _rigify

# Asymmetry above this fails diagnose (bone-heat + symmetrize both assume
# bilateral symmetry).
_MAX_ASYMMETRY_PCT = 10.0

# Hard health gates for bone-heat; everything else is reported, not fatal.
_FATAL_HEALTH = ("unapplied_scale", "negative_scale", "non_uniform_scale", "empty_mesh")

# Pose-extreme volume budget: bone-heat rigid blobs shouldn't collapse.
_VOLUME_TOLERANCE = 0.35


def character_diagnose(skill: str, ctx: dict, params: dict | None) -> dict:
    params = params or {}
    objects, err = _contract.resolve_objects(ctx, expected=1)
    if err is not None:
        _contract.log_failure(skill, "diagnose", err)
        return err
    mesh_obj = objects[0]

    health = perception.mesh_health(mesh_obj)
    fatal = [i for i in health["issues"] if i in _FATAL_HEALTH]
    if fatal and not params.get("ignore_health"):
        report = _contract.fail(
            "unhealthy_mesh", object=mesh_obj.name, issues=health["issues"],
            suggest="apply scale / fix mesh, or params={'ignore_health': True}")
        _contract.log_failure(skill, "diagnose", report)
        return report

    symmetry = perception.symmetry_plane(mesh_obj)
    if (not params.get("ignore_symmetry")
            and symmetry.get("asymmetry_pct", 100.0) > _MAX_ASYMMETRY_PCT):
        report = _contract.fail(
            "asymmetric",
            asymmetry_pct=symmetry.get("asymmetry_pct"),
            detail="character meshes must be bilaterally symmetric for "
                   "metarig mirroring and weight symmetrize",
            suggest="rig_rigid_assembly, or params={'ignore_symmetry': True}")
        _contract.log_failure(skill, "diagnose", report)
        return report

    verts, _tris = perception._mesh.mesh_arrays(mesh_obj)
    lo = verts.min(axis=0)
    hi = verts.max(axis=0)

    # Center the rig on the symmetry plane when it is X-ish, else bbox.
    center_x = float((lo[0] + hi[0]) * 0.5)
    normal = symmetry.get("normal")
    if normal is not None and abs(normal[0]) > 0.9:
        point = np.asarray(symmetry["point"])
        normal = np.asarray(normal)
        center_x = float(point @ normal / normal[0])

    return _contract.ok(plan={
        "mesh": mesh_obj.name,
        "bbox_min": lo.tolist(),
        "bbox_max": hi.tolist(),
        "height": float(hi[2] - lo[2]),
        "center_x": center_x,
        "asymmetry_pct": symmetry.get("asymmetry_pct"),
        "health_issues": health["issues"],
    })


def character_run(skill: str, metarig_kind: str, default_name: str,
                  ctx: dict, params: dict | None) -> dict:
    params = params or {}
    planned = character_diagnose(skill, ctx, params)
    if not planned["ok"]:
        return planned
    plan = planned["plan"]
    rig_name = params.get("name", default_name)

    # Rigify generation + bone-heat have diffuse side effects: snapshot
    # rollback instead of tracked rollback.
    snapshot = _contract.scene_snapshot()
    try:
        meta = _rigify.add_metarig(metarig_kind, name="META-" + rig_name)
        fit = _rigify.fit_metarig(
            meta, plan["bbox_min"], plan["bbox_max"], center_x=plan["center_x"])
        rig = _rigify.generate(meta, rig_name)

        mesh_obj = bpy.data.objects[plan["mesh"]]
        _rigify.bind_auto_weights(mesh_obj, rig)

        weights = validate_weights(mesh_obj, rig)
        unweighted = next(
            (e for e in weights["errors"] if e["rule"] == "E_UNWEIGHTED"), None)
        if unweighted is not None:
            # Bone-heat failed (it only warns on the console — coverage is
            # the reliable signal).
            _contract.scene_restore(snapshot)
            report = _contract.fail(
                "bone_heat_failed",
                detail=unweighted["detail"],
                suggest="fix non-manifold/overlapping geometry, or rig with "
                        "rig_rigid_assembly if the model is actually rigid parts")
            _contract.log_failure(skill, "run", report)
            return report

        if not params.get("keep_metarig"):
            arm_data = meta.data
            bpy.data.objects.remove(meta)
            bpy.data.armatures.remove(arm_data)

        bpy.context.view_layer.update()
        ctx["armature"] = rig.name
        return _contract.ok(
            armature=rig.name,
            character={
                "metarig": metarig_kind,
                "fit_scale": fit["scale"],
                "n_bones": len(rig.data.bones),
                "n_deform": sum(1 for b in rig.data.bones if b.use_deform),
            },
        )
    except Exception as ex:
        import traceback
        _contract.scene_restore(snapshot)
        report = _contract.fail("exception", error=str(ex),
                                traceback=traceback.format_exc())
        _contract.log_failure(skill, "run", report)
        return report
    finally:
        import os
        if os.path.exists(snapshot):
            os.unlink(snapshot)


def _set_fk(rig: bpy.types.Object, side: str, limbs) -> dict:
    """
    Flip Rigify IK/FK snap properties to FK so FK pose tests actually
    drive the mesh. Returns the previous values so callers can restore
    them — leaving a limb silently switched to FK makes every IK control
    a no-op afterwards (found live: posing ``hand_ik.R`` did nothing
    because an earlier verify had left ``IK_FK`` at 1).
    """
    previous = {}
    for limb in limbs:
        holder = rig.pose.bones.get("{:s}_parent{:s}".format(limb, side))
        if holder is not None and "IK_FK" in holder:
            previous[holder.name] = float(holder["IK_FK"])
            holder["IK_FK"] = 1.0
    return previous


def _restore_fk(rig: bpy.types.Object, previous: dict) -> None:
    for holder_name, value in previous.items():
        holder = rig.pose.bones.get(holder_name)
        if holder is not None:
            holder["IK_FK"] = value
    rig.update_tag()


def _ensure_object_mode(rig: bpy.types.Object) -> None:
    """
    Pose evaluation is FROZEN while an armature sits in EDIT mode: every
    pose-bone transform set from Python is accepted but never reaches the
    depsgraph, so probes measure 0.0 displacement against a healthy rig.
    Guard verify against whatever mode the session left the armature in.
    """
    if rig.mode != "OBJECT":
        prev_active = bpy.context.view_layer.objects.active
        bpy.context.view_layer.objects.active = rig
        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.context.view_layer.objects.active = prev_active


def character_verify(skill: str, ctx: dict, pose_bones) -> dict:
    """
    *pose_bones*: list of ``(fk_prop_limb, bone_name, axis, angle_deg)``
    pose-extreme probes, e.g. ``("upper_arm", "upper_arm_fk.L", "x", 60)``.
    """
    name = ctx.get("armature", "")
    checks = _contract.verify_common(name)
    rig = bpy.data.objects.get(name)
    if rig is None:
        report = _contract.fail("no_armature", checks=checks)
        _contract.log_failure(skill, "verify", report)
        return report
    _ensure_object_mode(rig)

    # ALL meshes bound to the rig: a multi-part character legitimately has
    # parts a probe must not move (the head during a thigh probe) — judge
    # each probe on the union, not on whichever mesh happens to come first.
    mesh_objs = [
        o for o in bpy.data.objects
        if o.type == "MESH"
        and any(m.type == "ARMATURE" and m.object == rig for m in o.modifiers)]
    checks.append(_contract.check("skinned_mesh_found", bool(mesh_objs)))

    if mesh_objs:
        weight_reports = [validate_weights(o, rig) for o in mesh_objs]
        checks.append(_contract.check(
            "weights", all(w["ok"] for w in weight_reports),
            str([e for w in weight_reports for e in w["errors"]])))

        rest_verts = np.vstack([_bones.evaluated_verts(o) for o in mesh_objs])
        rest_volume = sum(_bones.evaluated_volume(o) for o in mesh_objs)
        size = float(max(max(o.dimensions) for o in mesh_objs))

        for limb, bone, axis, angle in pose_bones:
            pb = rig.pose.bones.get(bone)
            checks.append(_contract.check("bone_{:s}".format(bone), pb is not None))
            if pb is None:
                continue
            previous_fk = _set_fk(rig, bone[-2:], [limb])
            _bones.pose_rotate(rig, bone, axis, angle)
            posed = np.vstack([_bones.evaluated_verts(o) for o in mesh_objs])
            moved = float(np.abs(posed - rest_verts).max())
            volume = sum(_bones.evaluated_volume(o) for o in mesh_objs)
            ratio = volume / max(rest_volume, 1e-12)
            checks.append(_contract.check(
                "pose_{:s}_moves".format(bone), moved > 0.02 * size,
                "max displacement {:.4f}".format(moved)))
            checks.append(_contract.check(
                "pose_{:s}_volume".format(bone),
                abs(ratio - 1.0) < _VOLUME_TOLERANCE,
                "volume ratio {:.3f}".format(ratio)))
            _bones.reset_pose(rig)
            _restore_fk(rig, previous_fk)

    failed = [c for c in checks if not c["ok"]]
    report = {"ok": not failed, "checks": checks}
    if failed:
        report["fail"] = "verify_failed"
        _contract.log_failure(skill, "verify", report)
    return report
