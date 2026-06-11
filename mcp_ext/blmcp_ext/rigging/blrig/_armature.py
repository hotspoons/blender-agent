# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Armature construction/edit helpers shared by skills and tests.

Edit-bone access needs EDIT mode with a correct active object — these
helpers own that state dance so nothing else has to (headless-safe).
"""

__all__ = (
    "add_bones",
    "build_armature",
    "edit_bones",
    "ensure_bone_collections",
    "remove_bones",
)

import contextlib

import bpy


@contextlib.contextmanager
def edit_bones(obj: bpy.types.Object):
    """
    Context manager: puts *obj* (armature) into EDIT mode with proper
    selection state, yields ``obj.data.edit_bones``, restores OBJECT mode.
    """
    view_layer = bpy.context.view_layer
    prev_active = view_layer.objects.active
    view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        yield obj.data.edit_bones
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
        view_layer.objects.active = prev_active


def ensure_bone_collections(obj: bpy.types.Object) -> None:
    """
    Create the standard DEF/MCH/CTL bone collections and assign every bone
    by its name prefix. DEF and MCH collections are hidden.
    """
    arm = obj.data
    for name, visible in (("DEF", False), ("MCH", False), ("CTL", True)):
        coll = arm.collections.get(name) or arm.collections.new(name)
        coll.is_visible = visible
    for bone in arm.bones:
        for prefix in ("DEF-", "MCH-", "CTL-"):
            if bone.name.startswith(prefix):
                arm.collections[prefix[:-1]].assign(bone)


def build_armature(name: str, bone_specs: list[dict], link: bool = True) -> bpy.types.Object:
    """
    Create an armature object from declarative *bone_specs*, in order:

    ``{"name", "head", "tail", "parent": str|None, "connect": bool,
       "use_deform": bool, "roll": float}``

    Heads/tails are armature-local. Bones default to non-deforming;
    parents must precede children in the list.
    """
    arm = bpy.data.armatures.new(name)
    obj = bpy.data.objects.new(name, arm)
    if link:
        bpy.context.scene.collection.objects.link(obj)

    with edit_bones(obj) as ebones:
        _create_bones(ebones, bone_specs)

    ensure_bone_collections(obj)
    return obj


def _create_bones(ebones, bone_specs: list[dict]) -> None:
    for spec in bone_specs:
        eb = ebones.new(spec["name"])
        eb.head = spec["head"]
        eb.tail = spec["tail"]
        eb.roll = spec.get("roll", 0.0)
        eb.use_deform = spec.get("use_deform", False)
        parent = spec.get("parent")
        if parent is not None:
            eb.parent = ebones[parent]
            eb.use_connect = spec.get("connect", False)


def add_bones(obj: bpy.types.Object, bone_specs: list[dict]) -> list[str]:
    """
    Add *bone_specs* to an EXISTING armature (chains composing into a
    larger rig). Parents may be pre-existing bones. Returns the created
    bone names (for rollback).
    """
    with edit_bones(obj) as ebones:
        _create_bones(ebones, bone_specs)
    ensure_bone_collections(obj)
    return [spec["name"] for spec in bone_specs]


def remove_bones(obj: bpy.types.Object, names: list[str]) -> None:
    """
    Remove bones by name (rollback path for :func:`add_bones`).
    """
    with edit_bones(obj) as ebones:
        for name in names:
            eb = ebones.get(name)
            if eb is not None:
                ebones.remove(eb)
