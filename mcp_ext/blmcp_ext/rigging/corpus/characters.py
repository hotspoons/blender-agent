# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Character corpus: humanoid and quadruped meshes generated from the Rigify
metarigs' own joint positions via a Skin modifier — single manifold mesh,
deterministic, and proportioned exactly like the metarig that will rig it.
"""

__all__ = (
    "CHARACTERS",
)

import bpy

from mathutils import Vector

# Bone chains (by metarig bone name) that become skin-skeleton edges, with
# per-joint skin radius.
# Chains must cover the metarig's full extent (toes included) — the skills
# fit the metarig to the mesh bbox, so a mesh missing landmarks the metarig
# has would misplace every bone.
_HUMAN_CHAINS = (
    # (bone names walked head-to-head, radius)
    (("spine", "spine.001", "spine.002", "spine.003"), 0.13),
    (("spine.004", "spine.005", "spine.006"), 0.06),  # neck->head
    (("upper_arm.L", "forearm.L", "hand.L"), 0.05),
    (("upper_arm.R", "forearm.R", "hand.R"), 0.05),
    (("thigh.L", "shin.L", "foot.L", "toe.L"), 0.07),
    (("thigh.R", "shin.R", "foot.R", "toe.R"), 0.07),
)
_HUMAN_HEAD_RADIUS = 0.11

_QUAD_CHAINS = (
    (("spine", "spine.001", "spine.002", "spine.003", "spine.004"), 0.14),
    (("spine.005", "spine.006", "spine.007"), 0.07),  # neck->head
    (("front_thigh.L", "front_shin.L", "front_foot.L", "front_toe.L"), 0.05),
    (("front_thigh.R", "front_shin.R", "front_foot.R", "front_toe.R"), 0.05),
    (("thigh.L", "shin.L", "foot.L", "toe.L"), 0.06),
    (("thigh.R", "shin.R", "foot.R", "toe.R"), 0.06),
)
_QUAD_HEAD_RADIUS = 0.09


def _skin_mesh_from_metarig(kind: str, chains, head_radius: float,
                            head_bone: str, name: str) -> bpy.types.Object:
    from blrig.skills import _rigify

    meta = _rigify.add_metarig(kind, name="_corpus_meta")
    bones = meta.data.bones

    verts: list[Vector] = []
    edges: list[tuple[int, int]] = []
    radii: list[float] = []

    def add_vert(co: Vector, radius: float) -> int:
        for i, v in enumerate(verts):
            if (v - co).length < 1e-6:
                radii[i] = max(radii[i], radius)
                return i
        verts.append(co.copy())
        radii.append(radius)
        return len(verts) - 1

    for chain, radius in chains:
        previous = None
        for bone_name in chain:
            bone = bones[bone_name]
            index = add_vert(bone.head_local, radius)
            if previous is not None:
                edges.append((previous, index))
            previous = index
        tail_index = add_vert(bones[chain[-1]].tail_local, radius)
        edges.append((previous, tail_index))

    # Connect limb roots to the nearest spine joint so the skeleton is one
    # connected component.
    spine_indices = [i for i, _v in enumerate(verts)
                     if any(abs((verts[i] - bones[b].head_local).length) < 1e-6
                            for chain, _r in chains[:2] for b in chain)]
    for chain, _radius in chains[2:]:
        root = next(i for i, v in enumerate(verts)
                    if (v - bones[chain[0]].head_local).length < 1e-6)
        nearest = min(spine_indices, key=lambda i: (verts[i] - verts[root]).length)
        edges.append((nearest, root))

    # Enlarge the head joint.
    head_index = add_vert(bones[head_bone].tail_local, head_radius)
    radii[head_index] = head_radius

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([tuple(v) for v in verts], edges, [])
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)

    mod = obj.modifiers.new("Skin", type="SKIN")
    mod.use_smooth_shade = False
    for i, radius in enumerate(radii):
        sv = mesh.skin_vertices[0].data[i]
        sv.radius = (radius, radius)
    # Mark the pelvis as skin root for stable results.
    mesh.skin_vertices[0].data[0].use_root = True

    sub = obj.modifiers.new("Subsurf", type="SUBSURF")
    sub.levels = 1
    sub.render_levels = 1

    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.modifier_apply(modifier="Skin")
    bpy.ops.object.modifier_apply(modifier="Subsurf")

    # Skin-modifier output leaves junk at branch junctions (duplicate verts,
    # degenerate shards, loose elements) that breaks bone-heat — heal it.
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-4)
    bmesh.ops.dissolve_degenerate(bm, edges=bm.edges[:], dist=1e-5)
    loose_verts = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose_verts, context="VERTS")

    # Branch junctions can pinch off small shard islands; keep the body.
    bm.verts.ensure_lookup_table()
    seen: set[int] = set()
    islands: list[list] = []
    for seed in bm.verts:
        if seed.index in seen:
            continue
        stack = [seed]
        seen.add(seed.index)
        island = []
        while stack:
            v = stack.pop()
            island.append(v)
            for e in v.link_edges:
                o = e.other_vert(v)
                if o.index not in seen:
                    seen.add(o.index)
                    stack.append(o)
        islands.append(island)
    islands.sort(key=len, reverse=True)
    if len(islands) > 1 and len(islands[0]) > 0.7 * len(bm.verts):
        doomed = [v for island in islands[1:] for v in island]
        bmesh.ops.delete(bm, geom=doomed, context="VERTS")

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 4])
    bm.to_mesh(obj.data)
    bm.free()

    # Drop the scaffold metarig; the corpus asset is just the mesh.
    arm_data = meta.data
    bpy.data.objects.remove(meta)
    bpy.data.armatures.remove(arm_data)
    bpy.context.view_layer.update()
    return obj


def humanoid() -> dict:
    """
    Manifold skin-mesh humanoid at human-metarig proportions.
    """
    obj = _skin_mesh_from_metarig(
        "human", _HUMAN_CHAINS, _HUMAN_HEAD_RADIUS, "spine.006", "Humanoid")
    return {
        "objects": [obj.name],
        "skill": "rig_biped_rigify",
        "truth": {"symmetric": True, "standing": True},
    }


def humanoid_asymmetric() -> dict:
    """
    Humanoid with one arm dragged far down — symmetry gate must trip.
    """
    manifest = humanoid()
    obj = bpy.data.objects[manifest["objects"][0]]
    for v in obj.data.vertices:
        if v.co.x > 0.25:
            v.co.z -= 0.55
            v.co.x += 0.3
    bpy.context.view_layer.update()
    manifest["truth"]["symmetric"] = False
    return manifest


def _band_part(source: bpy.types.Object, name: str,
               z_lo: float, z_hi: float) -> bpy.types.Object:
    """
    Copy *source* keeping only verts with z in [z_lo, z_hi]. The cut
    leaves OPEN boundaries — each part is deliberately non-manifold, like
    real multi-part character models.
    """
    import bmesh
    obj = source.copy()
    obj.data = source.data.copy()
    obj.name = name
    bpy.context.scene.collection.objects.link(obj)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    doomed = [v for v in bm.verts if not z_lo <= v.co.z <= z_hi]
    bmesh.ops.delete(bm, geom=doomed, context="VERTS")
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return obj


def humanoid_parts() -> dict:
    """
    The humanoid split into overlapping z-bands (head / torso+arms /
    legs), each an open non-manifold shell — the multi-part shell-pile
    character class that defeats direct bone-heat binding.
    """
    base = bpy.data.objects[humanoid()["objects"][0]]
    z_lo = min(v.co.z for v in base.data.vertices)
    z_hi = max(v.co.z for v in base.data.vertices)
    height = z_hi - z_lo
    # Bands overlap by ~4% of height so the weight proxy can fuse them.
    bands = (
        ("Parts.Legs", z_lo - 0.01, z_lo + 0.50 * height),
        ("Parts.Torso", z_lo + 0.46 * height, z_lo + 0.84 * height),
        ("Parts.Head", z_lo + 0.80 * height, z_hi + 0.01),
    )
    parts = [_band_part(base, name, lo, hi) for name, lo, hi in bands]
    mesh = base.data
    bpy.data.objects.remove(base)
    bpy.data.meshes.remove(mesh)
    bpy.context.view_layer.update()
    return {
        "objects": [p.name for p in parts],
        "skill": "rig_biped_multipart",
        "truth": {"symmetric": True, "n_parts": len(parts)},
    }


def humanoid_parts_bighand() -> dict:
    """
    Multi-part humanoid with one giant one-sided hand: the combined bbox
    center is dragged toward the hand, so any bbox-centered fit places
    the skeleton off the body midline (leg bones inside the wrong leg,
    far-side bones in empty air -> one-sided bone-heat failure). The
    midline must come from the bilateral parts instead.
    """
    manifest = humanoid_parts()
    torso = bpy.data.objects["Parts.Torso"]
    # Tip of the left arm (max x).
    tip = max((v.co for v in torso.data.vertices), key=lambda co: co.x)
    bpy.ops.mesh.primitive_uv_sphere_add(
        radius=0.22, location=(tip.x + 0.15, tip.y, tip.z), segments=16,
        ring_count=8)
    hand = bpy.context.view_layer.objects.active
    hand.name = "Parts.BigHand"
    bpy.context.view_layer.update()
    manifest["objects"].append(hand.name)
    manifest["truth"]["symmetric"] = False
    manifest["truth"]["n_parts"] += 1
    return manifest


def quadruped() -> dict:
    """
    Manifold skin-mesh quadruped at basic-quadruped-metarig proportions.
    """
    obj = _skin_mesh_from_metarig(
        "quadruped", _QUAD_CHAINS, _QUAD_HEAD_RADIUS, "spine.007", "Quadruped")
    return {
        "objects": [obj.name],
        "skill": "rig_quadruped_rigify",
        "truth": {"symmetric": True},
    }


CHARACTERS = {
    "humanoid": humanoid,
    "humanoid_asymmetric": humanoid_asymmetric,
    "humanoid_parts": humanoid_parts,
    "humanoid_parts_bighand": humanoid_parts_bighand,
    "quadruped": quadruped,
}
