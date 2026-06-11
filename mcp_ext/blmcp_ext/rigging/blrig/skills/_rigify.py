# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Rigify wrappers — never reimplement what Blender ships. These helpers own
the operator state dance (enable, metarig add, generate, bone-heat bind)
so skills stay declarative.
"""

__all__ = (
    "add_metarig",
    "bind_auto_weights",
    "normalize_weights",
    "ensure_rigify",
    "fit_metarig",
    "generate",
)

import bpy
import numpy as np


def ensure_rigify() -> None:
    """
    Enable the bundled Rigify add-on. ``preferences.addon_enable`` (not
    ``addon_utils.enable(default_set=False)``) — Rigify's register() reads
    its own entry in ``preferences.addons`` to load feature sets, and a
    half-registered Rigify fails generation with missing RigifyParameters
    attributes (e.g. ``make_custom_pivot``).
    """
    if "rigify" not in bpy.context.preferences.addons:
        bpy.ops.preferences.addon_enable(module="rigify")


_METARIG_OPS = {
    "human": "armature_human_metarig_add",
    "basic_human": "armature_basic_human_metarig_add",
    "quadruped": "armature_basic_quadruped_metarig_add",
    "cat": "armature_cat_metarig_add",
    "wolf": "armature_wolf_metarig_add",
    "horse": "armature_horse_metarig_add",
    "bird": "armature_bird_metarig_add",
    "shark": "armature_shark_metarig_add",
}


def add_metarig(kind: str = "human", name: str = "metarig") -> bpy.types.Object:
    ensure_rigify()
    getattr(bpy.ops.object, _METARIG_OPS[kind])()
    meta = bpy.context.object
    meta.name = name
    return meta


def metarig_bounds(meta: bpy.types.Object) -> tuple[np.ndarray, np.ndarray]:
    heads = np.array([b.head_local[:] for b in meta.data.bones])
    tails = np.array([b.tail_local[:] for b in meta.data.bones])
    pts = np.concatenate([heads, tails])
    return pts.min(axis=0), pts.max(axis=0)


def fit_metarig(meta: bpy.types.Object, target_min, target_max,
                center_x: float = 0.0) -> dict:
    """
    Proportional fit: uniformly scale and translate *meta* so its bone
    cloud spans the target's vertical range, feet at the floor, centered
    on ``center_x``. Scale is APPLIED to the armature data (object scale
    stays identity, per the standard).

    Proportional fit is deliberate v1: joint refinement belongs in
    perception-driven snapping, not in eyeballed offsets.
    """
    target_min = np.asarray(target_min, dtype=np.float64)
    target_max = np.asarray(target_max, dtype=np.float64)
    lo, hi = metarig_bounds(meta)

    scale = float((target_max[2] - target_min[2]) / max(hi[2] - lo[2], 1e-9))

    # Transform bone positions directly in edit mode (applied transform).
    # After (v - lo) * scale the bone cloud spans [0, (hi-lo)*scale]; its
    # center sits at (hi-lo)*0.5*scale, which is what recentering must
    # subtract.
    span = (hi - lo) * scale
    from .. import _armature
    with _armature.edit_bones(meta) as ebones:
        for eb in ebones:
            for attr in ("head", "tail"):
                v = np.asarray(getattr(eb, attr)[:], dtype=np.float64)
                v = (v - lo) * scale
                v[0] += center_x - span[0] * 0.5
                v[1] += (target_min[1] + target_max[1]) * 0.5 - span[1] * 0.5
                v[2] += target_min[2]
                setattr(eb, attr, v.tolist())
    return {"scale": scale}


def generate(meta: bpy.types.Object, rig_name: str) -> bpy.types.Object:
    """
    Run the Rigify generator for *meta* and return the generated rig.
    """
    ensure_rigify()
    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)
    meta.select_set(True)
    bpy.context.view_layer.objects.active = meta
    bpy.ops.pose.rigify_generate()
    rig = bpy.context.object
    rig.name = rig_name
    return rig


def bind_auto_weights(mesh_obj: bpy.types.Object, rig: bpy.types.Object) -> None:
    """
    Bone-heat automatic weights. NOTE: bone-heat failure on bad topology is
    a console warning, not an exception — callers must check coverage via
    ``validate_weights`` (E_UNWEIGHTED) afterwards.
    """
    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)
    mesh_obj.select_set(True)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    normalize_weights(mesh_obj, rig)


def normalize_weights(mesh_obj: bpy.types.Object, rig: bpy.types.Object) -> None:
    """
    Rescale each vertex's deform weights to sum to 1. Bone-heat output is
    only implicitly normalized (the armature modifier renormalizes at eval
    time); the rig standard requires explicit sums.
    """
    deform_groups = {
        g.index: g for g in mesh_obj.vertex_groups
        if (bone := rig.data.bones.get(g.name)) is not None and bone.use_deform}
    for v in mesh_obj.data.vertices:
        entries = [(ge.group, ge.weight) for ge in v.groups if ge.group in deform_groups]
        total = sum(w for _g, w in entries)
        if total > 1e-9 and abs(total - 1.0) > 1e-6:
            for group_index, weight in entries:
                deform_groups[group_index].add([v.index], weight / total, "REPLACE")
