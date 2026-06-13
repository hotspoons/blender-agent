# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Shared "disconnected organic mesh -> fused weight proxy -> Rigify
character rig -> weights transferred back onto the originals" path.

``rig_biped_multipart`` and ``rig_quadruped_multipart`` are thin wrappers
that only choose the target Rigify metarig (``human`` / ``quadruped``).
Nothing here is specialized to a species: the proxy machinery in
``_proxy`` fuses whatever overlapping shells it is given, the chosen
metarig is fitted to the fused blob, bone-heat binds the proxy, and the
validated weights are interpolated back onto the untouched originals.

See ``_proxy`` for the fuse/symmetrize/transfer primitives and the
gotchas that produced them.
"""

__all__ = (
    "diagnose",
    "run",
)

import os

import bpy

from .. import perception
from . import _character
from . import _contract
from . import _proxy

_PROXY_NAME = "_blrig_weight_proxy"

# Same fatal gates as the character skills: bone-heat on the proxy is
# transform-safe (the proxy bakes world transforms), but binding ORIGINALS
# that carry non-uniform/negative scale still deforms garbage.
_FATAL_HEALTH = ("unapplied_scale", "negative_scale", "non_uniform_scale", "empty_mesh")

# Leg-chain deform-group stems for cross-side weight cleanup: fattening
# fuses the legs at the centerline, so the heat field bleeds a little
# weight across the midline. Arms are excluded on purpose - they
# legitimately weight chest verts near the centerline. Keyed by metarig
# so a quadruped's front legs are cleaned up too.
_LEG_STEMS = {
    "human": ("pelvis", "thigh", "shin", "foot", "toe"),
    "basic_human": ("pelvis", "thigh", "shin", "foot", "toe"),
    "quadruped": ("pelvis", "thigh", "shin", "foot", "toe",
                  "front_thigh", "front_shin", "front_foot", "front_toe"),
}
_DEFAULT_LEG_STEMS = _LEG_STEMS["human"]


def _combined_bounds(objects):
    from mathutils import Vector
    lo = Vector((1e18, 1e18, 1e18))
    hi = Vector((-1e18, -1e18, -1e18))
    for obj in objects:
        for corner in obj.bound_box:
            world = obj.matrix_world @ Vector(corner)
            lo.x = min(lo.x, world.x); lo.y = min(lo.y, world.y); lo.z = min(lo.z, world.z)
            hi.x = max(hi.x, world.x); hi.y = max(hi.y, world.y); hi.z = max(hi.z, world.z)
    return lo, hi


def diagnose(skill: str, ctx: dict, params: dict | None = None) -> dict:
    params = params or {}
    objects, err = _contract.resolve_objects(ctx)
    if err is None and not objects:
        err = _contract.fail("wrong_object_count",
                             detail="need at least 1 mesh in ctx['objects']")
    if err is not None:
        _contract.log_failure(skill, "diagnose", err)
        return err

    issues = {}
    for obj in objects:
        health = perception.mesh_health(obj)
        issues[obj.name] = health["issues"]
        fatal = [i for i in health["issues"] if i in _FATAL_HEALTH]
        if fatal and not params.get("ignore_health"):
            report = _contract.fail(
                "unhealthy_mesh", object=obj.name, issues=health["issues"],
                suggest="apply scale / fix mesh, or params={'ignore_health': True}")
            _contract.log_failure(skill, "diagnose", report)
            return report

    lo, hi = _combined_bounds(objects)
    height = float(hi.z - lo.z)
    voxel = float(params.get("voxel_size") or max(height / 150.0, 1e-5))
    cx = params.get("center_x")
    center_x = float(cx if cx is not None
                     else _proxy.estimate_midline_x(objects, height))
    return _contract.ok(plan={
        "parts": [o.name for o in objects],
        "bbox_min": list(lo), "bbox_max": list(hi),
        "height": height,
        "center_x": center_x,
        "voxel_size": voxel,
        "symmetrize": bool(params.get("symmetrize", True)),
        "health_issues": issues,
    })


def run(skill: str, metarig_kind: str, default_name: str,
        ctx: dict, params: dict | None = None) -> dict:
    params = dict(params or {})
    planned = diagnose(skill, ctx, params)
    if not planned["ok"]:
        return planned
    plan = planned["plan"]
    part_names = plan["parts"]
    voxel = plan["voxel_size"]
    center_x = plan["center_x"]
    margin = float(params.get("side_margin") or 2.0 * voxel)
    kind = params.get("metarig", metarig_kind)
    leg_stems = _LEG_STEMS.get(kind, _DEFAULT_LEG_STEMS)

    snapshot = _contract.scene_snapshot()
    try:
        objects = [bpy.data.objects[n] for n in part_names]
        fused = _proxy.build_fused_proxy(objects, _PROXY_NAME, voxel)
        if fused["islands"] > 1:
            _contract.scene_restore(snapshot)
            report = _contract.fail(
                "proxy_not_fused",
                islands=fused["islands"], rounds=fused["rounds"],
                suggest="parts are too far apart to fuse; raise voxel_size, "
                        "or rig as parts with rig_rigid_assembly")
            _contract.log_failure(skill, "run", report)
            return report
        proxy = fused["object"]
        if plan["symmetrize"]:
            _proxy.symmetrize_union(proxy, center_x, voxel)

        inner_params = {
            "name": params.get("name", default_name),
            "keep_metarig": params.get("keep_metarig", False),
        }
        if not plan["symmetrize"]:
            # Caller opted out of mirroring; the gate would measure the raw
            # multi-part asymmetry, which is the caller's call now.
            inner_params["ignore_symmetry"] = bool(params.get("ignore_symmetry"))
        inner = _character.character_run(
            skill, kind, inner_params["name"], {"objects": [proxy.name]}, inner_params)
        if not inner["ok"]:
            _contract.scene_restore(snapshot)
            _contract.log_failure(skill, "run", inner)
            return inner

        # Inner run succeeded: no restore happened, but re-resolve by name
        # anyway — snapshot/restore invalidation bugs are silent.
        proxy = bpy.data.objects[_PROXY_NAME]
        rig = bpy.data.objects[inner["armature"]]
        uncovered = {}
        for part_name in part_names:
            part = bpy.data.objects[part_name]
            _proxy.transfer_weights(proxy, part)
            _proxy.bind_to_rig(part, rig)
            _proxy.strip_cross_side_leg_weights(
                part, rig, margin=margin, center_x=center_x, leg_stems=leg_stems)
            missing = sum(
                1 for v in part.data.vertices
                if not any(e.weight > 1e-6 for e in v.groups))
            if missing:
                uncovered[part_name] = missing
        if uncovered:
            _contract.scene_restore(snapshot)
            report = _contract.fail(
                "transfer_failed", uncovered=uncovered,
                suggest="proxy surface too far from these parts; lower "
                        "voxel_size so the proxy hugs the originals")
            _contract.log_failure(skill, "run", report)
            return report

        proxy_stats = {"verts": fused["verts"], "rounds": fused["rounds"]}
        mesh = proxy.data
        bpy.data.objects.remove(proxy)
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)

        bpy.context.view_layer.update()
        ctx["armature"] = rig.name
        return _contract.ok(
            armature=rig.name,
            character=inner["character"],
            multipart={
                "parts_bound": part_names,
                "center_x": center_x,
                "voxel_size": voxel,
                "metarig": kind,
                "proxy": proxy_stats,
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
        if os.path.exists(snapshot):
            os.unlink(snapshot)
