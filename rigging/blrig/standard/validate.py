# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
``validate_rig()`` / ``validate_weights()`` — machine-readable enforcement
of ``RIG_STANDARD.md``. Every skill runs these as postconditions.
"""

__all__ = (
    "bone_class",
    "validate_rig",
    "validate_weights",
)

import re

import bpy

_DEFAULT_NAME_RE = re.compile(r"^Bone(\.\d+)?$")
_SIDE_RE = re.compile(r"^(.*)\.(L|R)$")

# Prefix -> class. Unprefixed bones are controls (Rigify generates those);
# `root` is its own class.
_PREFIX_CLASS = (
    ("DEF-", "deform"),
    ("CTL-", "control"),
    ("MCH-", "mechanism"),
    ("ORG-", "mechanism"),
    ("WGT-", "mechanism"),
)


def bone_class(name: str) -> str:
    """
    Classify a bone name per the standard: ``root``, ``deform``,
    ``control`` or ``mechanism``.
    """
    if name == "root":
        return "root"
    for prefix, cls in _PREFIX_CLASS:
        if name.startswith(prefix):
            return cls
    return "control"


def _finding(rule: str, bones: list[str], detail: str) -> dict:
    return {"rule": rule, "bones": bones, "detail": detail}


def validate_rig(obj: bpy.types.Object) -> dict:
    """
    Validate *obj* (an armature object) against the rig standard.

    Returns ``{"ok", "errors", "warnings", "stats"}``; ``ok`` means no
    errors (warnings allowed). See ``RIG_STANDARD.md`` for rule ids.
    """
    errors: list[dict] = []
    warnings: list[dict] = []

    if obj is None or obj.type != "ARMATURE":
        return {
            "ok": False,
            "errors": [_finding("E_NOT_ARMATURE", [], "object is not an armature")],
            "warnings": [],
            "stats": {},
        }

    bones = obj.data.bones
    stats = {"n_bones": len(bones), "n_deform": 0, "n_control": 0, "n_mechanism": 0}

    if len(bones) == 0:
        errors.append(_finding("E_NO_BONES", [], "armature has no bones"))
        return {"ok": False, "errors": errors, "warnings": warnings, "stats": stats}

    scale = obj.matrix_world.to_scale()
    if any(abs(s - 1.0) > 1e-6 for s in scale):
        errors.append(_finding(
            "E_UNAPPLIED_SCALE", [],
            "armature object scale is {!r}, must be applied".format(tuple(round(s, 4) for s in scale)),
        ))

    roots = [b.name for b in bones if b.parent is None]
    if len(roots) != 1:
        errors.append(_finding(
            "E_ROOT_COUNT", roots,
            "expected exactly 1 parentless bone, found {:d}".format(len(roots)),
        ))
    elif roots[0] != "root":
        warnings.append(_finding("W_ROOT_NAME", roots, "parentless bone should be named 'root'"))

    # Size reference for the zero-length rule.
    size = max(
        max((b.head_local - b.tail_local).length for b in bones),
        max(obj.dimensions) if max(obj.dimensions) > 0.0 else 0.0,
        1e-12,
    )

    bad_deform = []
    bad_prefix = []
    zero_len = []
    default_names = []
    no_shape = []
    bad_collection = []
    by_side: dict[str, set[str]] = {"L": set(), "R": set()}

    pose_bones = obj.pose.bones if obj.pose else None

    for b in bones:
        cls = bone_class(b.name)
        if cls == "deform":
            stats["n_deform"] += 1
        elif cls in ("control", "root"):
            stats["n_control"] += 1
        else:
            stats["n_mechanism"] += 1

        if b.use_deform and cls != "deform":
            bad_deform.append(b.name)
        if not b.use_deform and cls == "deform":
            bad_prefix.append(b.name)
        if (b.head_local - b.tail_local).length < size * 1e-5:
            zero_len.append(b.name)
        if _DEFAULT_NAME_RE.match(b.name):
            default_names.append(b.name)

        side = _SIDE_RE.match(b.name)
        if side:
            by_side[side.group(2)].add(side.group(1))

        if b.name.startswith("CTL-") and pose_bones is not None:
            pb = pose_bones.get(b.name)
            if pb is not None and pb.custom_shape is None:
                no_shape.append(b.name)

        for prefix in ("DEF-", "CTL-", "MCH-"):
            if b.name.startswith(prefix):
                wanted = prefix[:-1]
                if wanted not in {c.name for c in b.collections}:
                    bad_collection.append(b.name)

    if bad_deform:
        errors.append(_finding(
            "E_DEFORM_PREFIX", bad_deform, "use_deform bones must be 'DEF-' prefixed"))
    if bad_prefix:
        errors.append(_finding(
            "E_PREFIX_DEFORM", bad_prefix, "'DEF-' bones must have use_deform enabled"))
    if zero_len:
        errors.append(_finding("E_ZERO_LENGTH", zero_len, "near-zero-length bones"))
    if default_names:
        errors.append(_finding(
            "E_DEFAULT_NAME", default_names, "Blender default bone names are forbidden"))

    unpaired = sorted(by_side["L"] ^ by_side["R"])
    if unpaired:
        warnings.append(_finding(
            "W_UNPAIRED_SIDE", unpaired, "sided bones without a twin on the other side"))
    if no_shape:
        warnings.append(_finding(
            "W_NO_CUSTOM_SHAPE", no_shape, "CTL- bones should carry a custom shape"))
    if bad_collection:
        warnings.append(_finding(
            "W_BONE_COLLECTIONS", bad_collection,
            "prefixed bones should sit in their matching bone collection"))

    return {"ok": not errors, "errors": errors, "warnings": warnings, "stats": stats}


def validate_weights(mesh_obj: bpy.types.Object, armature_obj: bpy.types.Object,
                     tol: float = 1e-3) -> dict:
    """
    Validate the skinning of *mesh_obj* against *armature_obj*.

    Errors: ``E_NOT_MESH``, ``E_NO_ARMATURE_MODIFIER``, ``E_NON_DEFORM_GROUP``
    (vertex group naming a bone that is not a deform bone),
    ``E_UNNORMALIZED`` (vertices whose deform weights don't sum to ~1),
    ``E_UNWEIGHTED`` (vertices with no deform weight at all).
    """
    errors: list[dict] = []
    if mesh_obj is None or mesh_obj.type != "MESH":
        return {"ok": False, "errors": [_finding("E_NOT_MESH", [], "not a mesh object")]}

    has_mod = any(
        m.type == "ARMATURE" and m.object == armature_obj for m in mesh_obj.modifiers)
    if not has_mod:
        errors.append(_finding(
            "E_NO_ARMATURE_MODIFIER", [],
            "mesh has no armature modifier targeting {!r}".format(armature_obj.name)))

    bones = armature_obj.data.bones if armature_obj and armature_obj.type == "ARMATURE" else []
    deform_names = {b.name for b in bones if b.use_deform}
    bone_names = {b.name for b in bones}

    bad_groups = [
        g.name for g in mesh_obj.vertex_groups
        if g.name in bone_names and g.name not in deform_names
    ]
    if bad_groups:
        errors.append(_finding(
            "E_NON_DEFORM_GROUP", bad_groups,
            "vertex groups reference non-deform bones"))

    deform_group_indices = {
        g.index for g in mesh_obj.vertex_groups if g.name in deform_names}
    unweighted = 0
    unnormalized = 0
    for v in mesh_obj.data.vertices:
        total = sum(
            ge.weight for ge in v.groups if ge.group in deform_group_indices)
        if total < tol:
            unweighted += 1
        elif abs(total - 1.0) > tol:
            unnormalized += 1
    if unweighted and deform_group_indices:
        errors.append(_finding(
            "E_UNWEIGHTED", [],
            "{:d} vertices carry no deform weight".format(unweighted)))
    if unnormalized:
        errors.append(_finding(
            "E_UNNORMALIZED", [],
            "{:d} vertices have weights not summing to 1".format(unnormalized)))

    return {
        "ok": not errors,
        "errors": errors,
        "stats": {
            "n_vertex_groups": len(mesh_obj.vertex_groups),
            "n_unweighted": unweighted,
            "n_unnormalized": unnormalized,
        },
    }
