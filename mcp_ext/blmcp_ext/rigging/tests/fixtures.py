# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Deterministic primitive fixtures for perception tests. Data-level only
(no operators), so they work in any context.
"""

__all__ = (
    "make_asymmetric_cube",
    "make_box",
    "make_broken_cube",
    "make_cube",
    "make_cylinder",
    "make_mirrored_pair",
    "make_sided_rig",
    "make_sphere",
    "make_subdivided_bar",
    "make_tapered_limb",
)

import math

import bmesh
import bpy

from mathutils import Matrix, Vector


def _to_object(bm: bmesh.types.BMesh, name: str) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def make_cube(name: str = "Cube", size: float = 2.0, location=(0.0, 0.0, 0.0)) -> bpy.types.Object:
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=size)
    obj = _to_object(bm, name)
    obj.location = location
    return obj


def make_box(name: str = "Box", dims=(2.0, 1.0, 0.5), rotation=(0.0, 0.0, 0.0)) -> bpy.types.Object:
    """
    Box with the given full dimensions, baked (applied) rotation.
    """
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    mat = Matrix.LocRotScale(None, None, Vector(dims))
    rot = (
        Matrix.Rotation(rotation[2], 4, "Z")
        @ Matrix.Rotation(rotation[1], 4, "Y")
        @ Matrix.Rotation(rotation[0], 4, "X")
    )
    bmesh.ops.transform(bm, matrix=rot @ mat, verts=bm.verts)
    return _to_object(bm, name)


def make_cylinder(
        name: str = "Cylinder",
        radius: float = 0.5,
        depth: float = 2.0,
        axis: str = "z",
        segments: int = 64,
        location=(0.0, 0.0, 0.0),
) -> bpy.types.Object:
    bm = bmesh.new()
    bmesh.ops.create_cone(
        bm,
        cap_ends=True,
        cap_tris=True,
        segments=segments,
        radius1=radius,
        radius2=radius,
        depth=depth,
    )
    if axis == "x":
        bmesh.ops.transform(bm, matrix=Matrix.Rotation(math.pi / 2, 4, "Y"), verts=bm.verts)
    elif axis == "y":
        bmesh.ops.transform(bm, matrix=Matrix.Rotation(math.pi / 2, 4, "X"), verts=bm.verts)
    obj = _to_object(bm, name)
    obj.location = location
    return obj


def make_sphere(name: str = "Sphere", radius: float = 1.0, location=(0.0, 0.0, 0.0)) -> bpy.types.Object:
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=radius)
    obj = _to_object(bm, name)
    obj.location = location
    return obj


def make_mirrored_pair(name: str = "Pair", offset: float = 2.0) -> bpy.types.Object:
    """
    One mesh, two cube parts mirrored across X=0 — loose-parts + symmetry
    fixture.
    """
    bm = bmesh.new()
    for sign in (-1.0, 1.0):
        ret = bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.translate(bm, vec=(sign * offset, 0.0, 0.0), verts=ret["verts"])
    return _to_object(bm, name)


def make_sided_rig(name: str = "Rig", deform: bool = True) -> bpy.types.Object:
    """
    Minimal bilateral armature for weight/pose/anim ops tests: a root and
    one bone per side along +-x (``DEF-arm.L``/``DEF-arm.R``, or
    unprefixed control bones with ``deform=False``).
    """
    from blrig import _armature

    prefix = "DEF-" if deform else ""
    rig = _armature.build_armature(name, [
        {"name": "root", "head": (0.0, 0.0, 0.0), "tail": (0.0, 0.5, 0.0)},
        {"name": prefix + "arm.L", "parent": "root", "use_deform": deform,
         "head": (0.1, 0.0, 0.0), "tail": (1.2, 0.0, 0.0)},
        {"name": prefix + "arm.R", "parent": "root", "use_deform": deform,
         "head": (-0.1, 0.0, 0.0), "tail": (-1.2, 0.0, 0.0)},
    ])
    # Euler bones (new pose bones default to QUATERNION) — matches the
    # rigs the mechanical skills build and keeps channel asserts direct.
    for pb in rig.pose.bones:
        pb.rotation_mode = "XYZ"
    return rig


def make_subdivided_bar(name: str = "Bar", dims=(2.4, 0.6, 0.6),
                        cuts: int = 7) -> bpy.types.Object:
    """
    Axis-aligned box centered at the origin with a subdivision grid —
    enough vertices on both sides of x=0 for weight-op tests.
    """
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=cuts,
                              use_grid_fill=True)
    bmesh.ops.transform(bm, matrix=Matrix.LocRotScale(None, None, Vector(dims)),
                        verts=bm.verts)
    return _to_object(bm, name)


def make_asymmetric_cube(name: str = "Lumpy") -> bpy.types.Object:
    """
    Cube with one corner pulled far out — must NOT read as symmetric.
    """
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=2.0)
    bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=3, use_grid_fill=True)
    bm.verts.ensure_lookup_table()
    for v in bm.verts:
        if v.co.x > 0.9 and v.co.y > 0.4 and v.co.z > 0.4:
            v.co += Vector((1.5, 0.8, 0.6))
    return _to_object(bm, name)


def make_tapered_limb(
        name: str = "Limb",
        length: float = 4.0,
        r_base: float = 0.6,
        r_waist: float = 0.25,
        segments: int = 48,
        rings: int = 33,
) -> bpy.types.Object:
    """
    Closed lathe along +Z whose radius dips to *r_waist* at the midpoint —
    the cross-section minimum a joint-finder must locate at z = length/2.
    """
    bm = bmesh.new()
    ring_verts = []
    for ring in range(rings):
        t = ring / (rings - 1)
        # Smooth taper: wide at both ends, narrow waist in the middle.
        radius = r_waist + (r_base - r_waist) * abs(2.0 * t - 1.0) ** 1.5
        z = t * length
        ring_verts.append([
            bm.verts.new((radius * math.cos(a), radius * math.sin(a), z))
            for a in (2.0 * math.pi * s / segments for s in range(segments))
        ])
    for ra, rb in zip(ring_verts, ring_verts[1:]):
        for s in range(segments):
            sn = (s + 1) % segments
            bm.faces.new((ra[s], ra[sn], rb[sn], rb[s]))
    for ring, reverse in ((ring_verts[0], False), (ring_verts[-1], True)):
        face = bm.faces.new(tuple(reversed(ring)) if reverse else tuple(ring))
        face.normal_update()
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return _to_object(bm, name)


def make_broken_cube(name: str = "Broken", kind: str = "open") -> bpy.types.Object:
    """
    Deliberately unhealthy cube. *kind*: ``open`` (missing face),
    ``degenerate`` (zero-area face), ``duplicates`` (doubled vertices),
    ``scaled`` (unapplied non-uniform scale).
    """
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=2.0)
    if kind == "open":
        bm.faces.ensure_lookup_table()
        bm.faces.remove(bm.faces[0])
    elif kind == "degenerate":
        bm.verts.ensure_lookup_table()
        v = bm.verts.new((3.0, 0.0, 0.0))
        bm.faces.new((v, bm.verts.new((3.0, 0.0, 0.0)), bm.verts.new((3.0, 0.0, 0.0))))
    elif kind == "duplicates":
        bm.verts.ensure_lookup_table()
        co = bm.verts[0].co.copy()
        bm.verts.new(co)
    obj = _to_object(bm, name)
    if kind == "scaled":
        obj.scale = (2.0, 1.0, 0.5)
    return obj
