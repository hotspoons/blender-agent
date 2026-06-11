# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Bone/constraint/skinning helpers shared by the mechanical skills.
All coordinate-level decisions live here or in perception — never in the LLM.
"""

__all__ = (
    "add_damped_track",
    "add_limit_rotation",
    "assign_custom_shapes",
    "bind_rigid",
    "evaluated_verts",
    "evaluated_volume",
    "pose_rotate",
    "reset_pose",
)

import math

import bmesh
import bpy
import numpy as np

from mathutils import Euler

_WGT_COLLECTION = "WGT-blrig"
_WGT_CIRCLE = "WGT-blrig-circle"


def _ensure_widget_circle(rollback=None) -> bpy.types.Object:
    """
    A shared wire-circle widget object in a hidden collection, created once
    per scene.
    """
    obj = bpy.data.objects.get(_WGT_CIRCLE)
    if obj is not None:
        return obj

    mesh = bpy.data.meshes.new(_WGT_CIRCLE)
    bm = bmesh.new()
    bmesh.ops.create_circle(bm, cap_ends=False, radius=1.0, segments=32)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(_WGT_CIRCLE, mesh)

    coll = bpy.data.collections.get(_WGT_COLLECTION)
    if coll is None:
        coll = bpy.data.collections.new(_WGT_COLLECTION)
        bpy.context.scene.collection.children.link(coll)
        coll.hide_viewport = True
        coll.hide_render = True
    coll.objects.link(obj)
    if rollback is not None:
        rollback.track_object(obj)
    return obj


def assign_custom_shapes(armature_obj: bpy.types.Object, rollback=None) -> None:
    """
    Give every ``CTL-`` pose bone the shared circle widget.
    """
    widget = _ensure_widget_circle(rollback)
    for pb in armature_obj.pose.bones:
        if pb.name.startswith("CTL-") and pb.custom_shape is None:
            pb.custom_shape = widget
            pb.use_custom_shape_bone_size = True


def add_limit_rotation(armature_obj: bpy.types.Object, bone_name: str,
                       free_axis: str = "y",
                       min_deg: float = -180.0, max_deg: float = 180.0,
                       rollback=None):
    """
    Lock all rotation except *free_axis* (bone-local), limited to
    ``[min_deg, max_deg]``. Also locks location/scale on the pose bone so
    the control is a pure hinge.
    """
    pb = armature_obj.pose.bones[bone_name]
    pb.rotation_mode = "XYZ"
    pb.lock_location = (True, True, True)
    pb.lock_scale = (True, True, True)

    con = pb.constraints.new("LIMIT_ROTATION")
    con.owner_space = "LOCAL"
    con.use_transform_limit = True
    for axis in "xyz":
        is_free = axis == free_axis
        setattr(con, "use_limit_{:s}".format(axis), True)
        setattr(con, "min_{:s}".format(axis), math.radians(min_deg) if is_free else 0.0)
        setattr(con, "max_{:s}".format(axis), math.radians(max_deg) if is_free else 0.0)
        pb.lock_rotation[("x", "y", "z").index(axis)] = not is_free
    if rollback is not None:
        rollback.track_constraint(pb, con)
    return con


def add_damped_track(armature_obj: bpy.types.Object, bone_name: str,
                     target_bone: str, head_tail: float = 0.0,
                     track_axis: str = "TRACK_Y", rollback=None):
    """
    Damped-track *bone_name* at *target_bone*'s head (or tail with
    ``head_tail=1``) on the same armature — the piston primitive.
    """
    pb = armature_obj.pose.bones[bone_name]
    con = pb.constraints.new("DAMPED_TRACK")
    con.target = armature_obj
    con.subtarget = target_bone
    con.head_tail = head_tail
    con.track_axis = track_axis
    if rollback is not None:
        rollback.track_constraint(pb, con)
    return con


def bind_rigid(obj: bpy.types.Object, armature_obj: bpy.types.Object,
               bone_name: str, vert_indices=None, rollback=None) -> None:
    """
    Rigid-skin *obj* (or a subset of its verts) to one deform bone: vertex
    group at weight 1.0 + a single armature modifier.
    """
    if vert_indices is None:
        vert_indices = range(len(obj.data.vertices))

    group = obj.vertex_groups.get(bone_name)
    if group is None:
        group = obj.vertex_groups.new(name=bone_name)
        if rollback is not None:
            rollback.track_vgroup(obj, group)
    group.add(list(vert_indices), 1.0, "REPLACE")

    if not any(m.type == "ARMATURE" and m.object == armature_obj for m in obj.modifiers):
        mod = obj.modifiers.new("Armature", type="ARMATURE")
        mod.object = armature_obj
        if rollback is not None:
            rollback.track_modifier(obj, mod)


def evaluated_volume(obj: bpy.types.Object) -> float:
    """
    Unsigned volume of the evaluated (post-modifier) mesh, divergence
    theorem over world-space triangles. Meaningful for closed meshes.
    """
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    mesh = eval_obj.to_mesh()
    try:
        n = len(mesh.vertices)
        co = np.empty(n * 3, dtype=np.float64)
        mesh.vertices.foreach_get("co", co)
        co = co.reshape(n, 3)
        mw = np.array(eval_obj.matrix_world, dtype=np.float64)
        verts = co @ mw[:3, :3].T + mw[:3, 3]
        mesh.calc_loop_triangles()
        m = len(mesh.loop_triangles)
        tris = np.empty(m * 3, dtype=np.int64)
        mesh.loop_triangles.foreach_get("vertices", tris)
        tris = tris.reshape(m, 3)
        center = verts.mean(axis=0)
        a0 = verts[tris[:, 0]] - center
        a1 = verts[tris[:, 1]] - center
        a2 = verts[tris[:, 2]] - center
        return float(abs(np.einsum("ij,ij->i", a0, np.cross(a1, a2)).sum()) / 6.0)
    finally:
        eval_obj.to_mesh_clear()


def evaluated_verts(obj: bpy.types.Object) -> np.ndarray:
    """
    World-space vertex positions after modifiers (depsgraph-evaluated).
    """
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    mesh = eval_obj.to_mesh()
    try:
        n = len(mesh.vertices)
        co = np.empty(n * 3, dtype=np.float64)
        mesh.vertices.foreach_get("co", co)
        co = co.reshape(n, 3)
        mw = np.array(eval_obj.matrix_world, dtype=np.float64)
        return co @ mw[:3, :3].T + mw[:3, 3]
    finally:
        eval_obj.to_mesh_clear()


def pose_rotate(armature_obj: bpy.types.Object, bone_name: str,
                axis: str, angle_deg: float) -> None:
    """
    Set a pose bone's local rotation about one axis and update the depsgraph.
    """
    pb = armature_obj.pose.bones[bone_name]
    pb.rotation_mode = "XYZ"
    euler = Euler((0.0, 0.0, 0.0), "XYZ")
    setattr(euler, axis, math.radians(angle_deg))
    pb.rotation_euler = euler
    bpy.context.view_layer.update()


def reset_pose(armature_obj: bpy.types.Object) -> None:
    for pb in armature_obj.pose.bones:
        pb.rotation_euler = (0.0, 0.0, 0.0)
        pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        pb.location = (0.0, 0.0, 0.0)
        pb.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()
