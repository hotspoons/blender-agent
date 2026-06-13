# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
rig_biped_multipart: a humanoid modeled as MULTIPLE meshes / shell piles
(non-manifold, hundreds of loose parts, asymmetric attachments) -> full
Rigify control rig with weights transferred onto every original part.

The visible meshes are never repaired or modified — a disposable fused
weight proxy (see ``_proxy``) absorbs the voxel remeshing, fattening and
mirror-union, gets rigged and bone-heat-bound by ``rig_biped_rigify``,
and donates its validated weights back to the originals before being
deleted.

Triggers: humanoid characters split across several objects; single-object
characters whose mesh is a pile of overlapping shells (bone_heat_failed
from rig_biped_rigify); characters with one-sided appendages that skew
the symmetric fit.
Anti-triggers: one clean symmetric watertight mesh (rig_biped_rigify
directly), mechanical assemblies (rig_rigid_assembly).

params:
- ``name``: rig object name, default "Rig.Biped".
- ``metarig``: "human" (default) or "basic_human".
- ``keep_metarig``: keep the fitted metarig for joint tweaks +
  regeneration (default False).
- ``symmetrize``: union the proxy with its own X-mirror across the
  character midline (default True). Disable only for genuinely
  symmetric multi-part characters; the inner symmetry gate then applies.
- ``voxel_size``: proxy remesh voxel, default height/150.
- ``center_x``: midline override; default is the largest cluster of
  per-part bbox-center x values (NOT the combined bbox center, which a
  single long one-sided appendage drags off the body).
- ``side_margin``: midline dead-zone half-width for cross-side leg
  weight cleanup, default 2x voxel_size.
- ``ignore_health``: override the per-part fatal-health gate.

Failure codes: ``proxy_not_fused`` (shells would not fuse into one
island), ``transfer_failed`` (an original ended up with unweighted
verts), plus everything ``rig_biped_rigify`` can return
(``bone_heat_failed``, ``unhealthy_mesh``, ...).
"""

__all__ = (
    "diagnose",
    "run",
    "verify",
)

import bpy

from .. import perception
from . import _character
from . import _contract
from . import _proxy

_SKILL = "rig_biped_multipart"

_PROXY_NAME = "_blrig_weight_proxy"

# Same fatal gates as the character skills: bone-heat on the proxy is
# transform-safe (the proxy bakes world transforms), but binding ORIGINALS
# that carry non-uniform/negative scale still deforms garbage.
_FATAL_HEALTH = ("unapplied_scale", "negative_scale", "non_uniform_scale", "empty_mesh")


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


def diagnose(ctx: dict, params: dict | None = None) -> dict:
    params = params or {}
    objects, err = _contract.resolve_objects(ctx)
    if err is None and not objects:
        err = _contract.fail("wrong_object_count",
                             detail="need at least 1 mesh in ctx['objects']")
    if err is not None:
        _contract.log_failure(_SKILL, "diagnose", err)
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
            _contract.log_failure(_SKILL, "diagnose", report)
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


def run(ctx: dict, params: dict | None = None) -> dict:
    params = dict(params or {})
    planned = diagnose(ctx, params)
    if not planned["ok"]:
        return planned
    plan = planned["plan"]
    part_names = plan["parts"]
    voxel = plan["voxel_size"]
    center_x = plan["center_x"]
    margin = float(params.get("side_margin") or 2.0 * voxel)

    import os
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
            _contract.log_failure(_SKILL, "run", report)
            return report
        proxy = fused["object"]
        if plan["symmetrize"]:
            _proxy.symmetrize_union(proxy, center_x, voxel)

        from . import rig_biped_rigify
        inner_params = {
            "name": params.get("name", "Rig.Biped"),
            "metarig": params.get("metarig", "human"),
            "keep_metarig": params.get("keep_metarig", False),
        }
        if not plan["symmetrize"]:
            # Caller opted out of mirroring; the gate would measure the
            # raw multi-part asymmetry, which is the caller's call now.
            inner_params["ignore_symmetry"] = bool(params.get("ignore_symmetry"))
        inner = rig_biped_rigify.run({"objects": [proxy.name]}, inner_params)
        if not inner["ok"]:
            _contract.scene_restore(snapshot)
            _contract.log_failure(_SKILL, "run", inner)
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
                part, rig, margin=margin, center_x=center_x)
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
            _contract.log_failure(_SKILL, "run", report)
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
                "proxy": proxy_stats,
            },
        )
    except Exception as ex:
        import traceback
        _contract.scene_restore(snapshot)
        report = _contract.fail("exception", error=str(ex),
                                traceback=traceback.format_exc())
        _contract.log_failure(_SKILL, "run", report)
        return report
    finally:
        if os.path.exists(snapshot):
            os.unlink(snapshot)


_POSE_PROBES = (
    ("upper_arm", "upper_arm_fk.L", "x", 50.0),
    ("upper_arm", "upper_arm_fk.R", "x", 50.0),
    ("thigh", "thigh_fk.L", "x", -45.0),
)


def verify(ctx: dict) -> dict:
    return _character.character_verify(_SKILL, ctx, _POSE_PROBES)
