# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Corpus assets. Each builder populates the current scene and returns a
manifest: object names, intended skill, and ground-truth annotations
(hinge axes, contact points) that tests assert against.

Mechanical archetypes (door, wheel, piston, turret, lamp, crates) are
minimal fixed primitives. Creatures are NOT - ``legged_creature`` is a
parametric generator so the appendage/assembly path is exercised across
arbitrary configurations rather than one memorised layout.
"""

__all__ = (
    "CORPUS",
    "legged_creature",
)

import math

import bmesh
import bpy

from mathutils import Matrix, Vector


def _box(name: str, dims, location=(0, 0, 0), rotation=(0, 0, 0)) -> bpy.types.Object:
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    rot = (
        Matrix.Rotation(rotation[2], 4, "Z")
        @ Matrix.Rotation(rotation[1], 4, "Y")
        @ Matrix.Rotation(rotation[0], 4, "X")
    )
    bmesh.ops.transform(bm, matrix=rot @ Matrix.LocRotScale(None, None, Vector(dims)), verts=bm.verts)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.location = location
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _cylinder(name: str, radius: float, depth: float, axis: str = "z",
              location=(0, 0, 0), segments: int = 32) -> bpy.types.Object:
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=True, segments=segments,
                          radius1=radius, radius2=radius, depth=depth)
    if axis == "x":
        bmesh.ops.transform(bm, matrix=Matrix.Rotation(math.pi / 2, 4, "Y"), verts=bm.verts)
    elif axis == "y":
        bmesh.ops.transform(bm, matrix=Matrix.Rotation(math.pi / 2, 4, "X"), verts=bm.verts)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.location = location
    bpy.context.scene.collection.objects.link(obj)
    return obj


def door_and_frame() -> dict:
    """
    Door panel meeting a frame post along one vertical edge — canonical
    hinge. Ground truth: hinge axis = world Z at (x=0, y=0).
    """
    _box("Frame", dims=(0.1, 0.1, 2.2), location=(-0.05, 0.0, 1.1))
    _box("Door", dims=(0.9, 0.05, 2.0), location=(0.452, 0.0, 1.0))
    bpy.context.view_layer.update()
    return {
        "objects": ["Frame", "Door"],
        "skill": "rig_hinge",
        "truth": {
            "hinge_axis": [0.0, 0.0, 1.0],
            "hinge_point_xy": [0.0, 0.0],
            "moving": "Door",
        },
    }


def door_and_frame_garbage() -> dict:
    """
    Same hinge, garbage topology: duplicate verts, a floating junk
    triangle and unapplied door scale. diagnose() must gate on health.
    """
    manifest = door_and_frame()
    door = bpy.data.objects["Door"]
    bm = bmesh.new()
    bm.from_mesh(door.data)
    bm.verts.ensure_lookup_table()
    bm.verts.new(bm.verts[0].co)  # duplicate
    a = bm.verts.new((5.0, 5.0, 5.0))
    b = bm.verts.new((5.1, 5.0, 5.0))
    c = bm.verts.new((5.0, 5.1, 5.0))
    bm.faces.new((a, b, c))  # floating junk
    bm.to_mesh(door.data)
    bm.free()
    door.scale = (1.0, 1.0, 1.2)
    bpy.context.view_layer.update()
    manifest["truth"]["health_issues"] = ["duplicate_verts", "unapplied_scale"]
    return manifest


def piston_pair() -> dict:
    """
    Rod sliding inside a sleeve, coaxial along X, slightly interpenetrating.
    """
    _cylinder("Sleeve", radius=0.16, depth=1.0, axis="x", location=(-0.5, 0.0, 0.0))
    _cylinder("Rod", radius=0.1, depth=1.2, axis="x", location=(0.55, 0.0, 0.0))
    bpy.context.view_layer.update()
    return {
        "objects": ["Sleeve", "Rod"],
        "skill": "rig_piston",
        "truth": {"axis": [1.0, 0.0, 0.0]},
    }


def cart_wheel() -> dict:
    """
    Disc wheel, spin axis = world Y.
    """
    _cylinder("Wheel", radius=0.4, depth=0.12, axis="y", segments=48)
    bpy.context.view_layer.update()
    return {
        "objects": ["Wheel"],
        "skill": "rig_wheel",
        "truth": {"axis": [0.0, 1.0, 0.0], "center": [0.0, 0.0, 0.0], "radius": 0.4},
    }


def cart_wheel_scaled() -> dict:
    """
    Wheel with unapplied scale — diagnose() must gate.
    """
    manifest = cart_wheel()
    bpy.data.objects["Wheel"].scale = (1.0, 2.0, 1.0)
    bpy.context.view_layer.update()
    manifest["truth"]["health_issues"] = ["unapplied_scale"]
    return manifest


def turret() -> dict:
    """
    Base slab, yaw drum on top, barrel out the side: yaw stack around Z at
    the base/drum interface, pitch around Y at the drum/barrel interface.
    """
    _box("Base", dims=(1.2, 1.2, 0.2), location=(0.0, 0.0, 0.1))
    _cylinder("Drum", radius=0.4, depth=0.5, axis="z", location=(0.0, 0.0, 0.45))
    _box("Barrel", dims=(1.0, 0.12, 0.12), location=(0.9, 0.0, 0.55))
    bpy.context.view_layer.update()
    return {
        "objects": ["Base", "Drum", "Barrel"],
        "skill": "rig_turret",
        "truth": {
            "yaw_axis": [0.0, 0.0, 1.0],
            "pitch_axis": [0.0, 1.0, 0.0],
            "yaw_point_xy": [0.0, 0.0],
        },
    }


def desk_lamp() -> dict:
    """
    Four-part articulated lamp: base, lower arm, upper arm, head — a chain
    for rig_rigid_assembly with three hinge-like joints along Y axes.
    """
    # Geometry is chained end-to-end with slight embedding so the contact
    # graph sees every joint: each arm's end sits ~0.02 inside its neighbor.
    d_lower = Vector((math.sin(math.radians(20)), 0.0, math.cos(math.radians(20))))
    d_upper = Vector((math.sin(math.radians(-35)), 0.0, math.cos(math.radians(-35))))
    lower_bottom = Vector((0.0, 0.0, 0.06))           # inside the base slab
    lower_center = lower_bottom + d_lower * 0.35
    lower_top = lower_bottom + d_lower * 0.7
    upper_center = lower_top + d_upper * 0.3
    upper_top = lower_top + d_upper * 0.6
    head_center = upper_top + Vector((-0.05, 0.0, 0.0))

    _box("LampBase", dims=(0.5, 0.5, 0.08), location=(0.0, 0.0, 0.04))
    _box("ArmLower", dims=(0.06, 0.06, 0.7),
         location=tuple(lower_center), rotation=(0.0, math.radians(20), 0.0))
    _box("ArmUpper", dims=(0.06, 0.06, 0.6),
         location=tuple(upper_center), rotation=(0.0, math.radians(-35), 0.0))
    _box("Head", dims=(0.22, 0.18, 0.18), location=tuple(head_center))
    bpy.context.view_layer.update()
    return {
        "objects": ["LampBase", "ArmLower", "ArmUpper", "Head"],
        "skill": "rig_rigid_assembly",
        "truth": {"n_parts": 4, "root_part": "LampBase", "chain": True},
    }


def desk_lamp_single_mesh() -> dict:
    """
    The desk lamp as ONE mesh whose loose parts are the four components —
    exercises vertex-subset binding in rig_rigid_assembly.
    """
    manifest = desk_lamp()
    parts = [bpy.data.objects[n] for n in manifest["objects"]]
    bm = bmesh.new()
    for obj in parts:
        offset = Matrix.Translation(obj.location)
        tmp = obj.data.copy()
        tmp.transform(offset)
        bm.from_mesh(tmp)
        bpy.data.meshes.remove(tmp)
    mesh = bpy.data.meshes.new("Lamp")
    bm.to_mesh(mesh)
    bm.free()
    for obj in parts:
        data = obj.data
        bpy.data.objects.remove(obj)
        bpy.data.meshes.remove(data)
    obj = bpy.data.objects.new("Lamp", mesh)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.update()
    return {
        "objects": ["Lamp"],
        "skill": "rig_rigid_assembly",
        "truth": {"n_parts": 4, "chain": True},
    }


def crate_stack() -> dict:
    """
    Disconnected pile: two touching crates plus one separate — assembly
    rigging must handle multiple contact components.
    """
    _box("CrateA", dims=(0.6, 0.6, 0.6), location=(0.0, 0.0, 0.3))
    _box("CrateB", dims=(0.5, 0.5, 0.5), location=(0.0, 0.05, 0.85))
    _box("CrateC", dims=(0.4, 0.4, 0.4), location=(2.0, 0.0, 0.2))
    bpy.context.view_layer.update()
    return {
        "objects": ["CrateA", "CrateB", "CrateC"],
        "skill": "rig_rigid_assembly",
        "truth": {"n_parts": 3, "n_components": 2},
    }


def _cylinder_between(name: str, p0, p1, radius: float,
                      segments: int = 12) -> bpy.types.Object:
    """
    Capped cylinder spanning two world points (leg segments and the like).
    """
    p0 = Vector(p0)
    p1 = Vector(p1)
    span = p1 - p0
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=True, segments=segments,
                          radius1=radius, radius2=radius, depth=span.length)
    rot = span.to_track_quat("Z", "Y").to_matrix().to_4x4()
    bmesh.ops.transform(bm, matrix=rot, verts=bm.verts)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.location = (p0 + p1) * 0.5
    bpy.context.scene.collection.objects.link(obj)
    return obj


def legged_creature(
        name: str = "Creature",
        n_legs: int = 6,
        leg_segments: int = 3,
        body_radius: float = 0.55,
        body_center=(0.0, 0.0, 1.0),
        leg_clearance: float = 0.0,
        segment_embed: float = 0.03,
        base_segment_length: float = 0.55,
        segment_taper: float = 0.85,
        leg_radius: float = 0.06,
        detail: "dict | None" = None,
) -> dict:
    """
    Build a radially-legged creature of ANY configuration — the general
    test asset for the appendage/assembly path. It is deliberately
    parametric so a single builder covers a spider (8 legs, 3 segments),
    a crab (8 legs, 2 segments, wide stance), a hexapod ant (6 legs +
    floating head), a quadruped of disjoint limbs, and so on. There is
    no single canonical creature baked into the code.

    Geometry model (all derived from the parameters):

    - A spherical *body* at ``body_center``.
    - ``n_legs`` legs spaced evenly around the body's Z axis. Each leg is
      a polyline of ``leg_segments`` capped cylinders that reaches out
      and bends progressively downward. Consecutive segments overlap by
      ``segment_embed`` (a real internal contact -> joint); the first
      segment stands ``leg_clearance`` off the body surface (a modeled
      gap -> needs bridging when > 0).
    - An optional floating ``detail`` part (e.g. a head), given as
      ``{"name": str, "radius": float, "offset": (x, y, z)}`` relative to
      the body centre - never touches anything.

    The returned ``truth`` is computed from the parameters (never
    hardcoded), and exposes the generated object names so tests assert
    general invariants rather than a memorised layout.
    """
    body_center = Vector(body_center)
    down = Vector((0.0, 0.0, -1.0))

    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=12, radius=body_radius)
    mesh = bpy.data.meshes.new(name + "_Body")
    bm.to_mesh(mesh)
    bm.free()
    body_name = name + "_Body"
    body = bpy.data.objects.new(body_name, mesh)
    body.location = body_center
    bpy.context.scene.collection.objects.link(body)

    objects = [body_name]
    legs: "list[list[str]]" = []
    for i in range(n_legs):
        theta = 2.0 * math.pi * (i + 0.5) / n_legs
        radial = Vector((math.cos(theta), math.sin(theta), 0.0))
        attach = body_center + radial * body_radius

        leg_names: "list[str]" = []
        prev_dir = None
        cursor = attach + (radial + down * 0.4).normalized() * leg_clearance
        for j in range(leg_segments):
            # Blend each segment from mostly-outward to mostly-downward.
            t = j / max(1, leg_segments - 1)
            seg_dir = (radial * (1.0 - 0.7 * t) + down * (0.4 + 1.3 * t)).normalized()
            length = base_segment_length * (segment_taper ** j)
            start = cursor if prev_dir is None else cursor - prev_dir * segment_embed
            end = start + seg_dir * length
            seg_name = "{:s}_Leg{:d}_Seg{:d}".format(name, i, j)
            _cylinder_between(seg_name, start, end, leg_radius * (segment_taper ** j))
            leg_names.append(seg_name)
            objects.append(seg_name)
            cursor = end
            prev_dir = seg_dir
        legs.append(leg_names)

    detail_name = None
    if detail:
        detail_name = "{:s}_{:s}".format(name, detail.get("name", "Detail"))
        bm = bmesh.new()
        bmesh.ops.create_uvsphere(bm, u_segments=12, v_segments=8,
                                  radius=detail.get("radius", 0.15))
        mesh = bpy.data.meshes.new(detail_name)
        bm.to_mesh(mesh)
        bm.free()
        part = bpy.data.objects.new(detail_name, mesh)
        part.location = body_center + Vector(detail.get("offset", (0.0, 1.0, 0.9)))
        bpy.context.scene.collection.objects.link(part)
        objects.append(detail_name)

    bpy.context.view_layer.update()
    return {
        "objects": objects,
        "skill": "rig_rigid_assembly",
        "params": {
            "n_legs": n_legs,
            "leg_segments": leg_segments,
            "leg_clearance": leg_clearance,
        },
        "truth": {
            "n_parts": len(objects),
            "n_legs": n_legs,
            "leg_segments": leg_segments,
            "body_leg_gap": leg_clearance,
            "leg_internal_joints": n_legs * (leg_segments - 1),
            "has_detail": bool(detail),
            "body": body_name,
            "legs": legs,
            "first_segments": [leg[0] for leg in legs],
            "detail": detail_name,
        },
    }


CORPUS = {
    "door_and_frame": door_and_frame,
    "door_and_frame_garbage": door_and_frame_garbage,
    "piston_pair": piston_pair,
    "cart_wheel": cart_wheel,
    "cart_wheel_scaled": cart_wheel_scaled,
    "turret": turret,
    "desk_lamp": desk_lamp,
    "desk_lamp_single_mesh": desk_lamp_single_mesh,
    "crate_stack": crate_stack,
}
