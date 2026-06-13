# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Weight-proxy machinery for characters that are piles of shells.

Real-world character models are frequently NOT one watertight mesh: they
are dozens of overlapping, non-manifold decorative shells spread over
several objects (a live specimen: 8 objects, ~290 disconnected shells,
one shoe alone made of 138 loose parts). Bone-heat cannot solve on that —
the heat field needs one connected volume — and repairing the *visible*
meshes would destroy the model.

The pattern that works, validated end-to-end on the live scene:

1. Join COPIES of the parts into a disposable proxy (originals untouched).
2. Voxel-remesh the proxy (guaranteed manifold, consistent normals).
3. Fatten (displace along normals) + re-remesh until the shells fuse
   into ONE island; bridge stubborn gaps with primitive cylinders placed
   between nearest island points (a clearance gap inside a limb, e.g.
   pant legs modeled as two tubes, never fuses by fattening alone).
4. Optionally union the proxy with its own X-mirror across the
   character's midline, making it EXACTLY bilateral: the metarig fit
   centers correctly and the symmetry gate passes honestly. This matters
   because one heavy one-sided appendage skews a bbox-centered fit badly
   enough to land leg bones inside the wrong leg and arm bones in empty
   air (bones outside all geometry are exactly the ones whose heat solve
   fails).
5. Rig + bone-heat-bind the proxy, then transfer the validated weights
   back onto each original (world-space nearest-face interpolation) and
   bind the originals.
6. Strip cross-side LEG weights with a small midline margin: fattening
   fuses the two legs/shoes at the centerline, so the heat field bleeds
   a little weight across — visible as the right shoe dragging when the
   left foot lifts.
7. Delete the proxy.

Everything here is deterministic geometry; no coordinate is eyeballed.
"""

__all__ = (
    "bind_to_rig",
    "build_fused_proxy",
    "estimate_midline_x",
    "strip_cross_side_leg_weights",
    "symmetrize_union",
    "transfer_weights",
)

import bmesh
import bpy
import numpy as np

from mathutils import Vector

# Cross-side cleanup applies to limb chains that straddle the midline.
# Arms are excluded on purpose: arm bones legitimately weight chest verts
# near the centerline, and stripping them breaks the shoulder blend.
_LEG_GROUP_STEMS = ("pelvis", "thigh", "shin", "foot", "toe")


def _select_only(objects, active=None) -> None:
    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)
    for obj in objects:
        obj.select_set(True)
    if active is not None:
        bpy.context.view_layer.objects.active = active


def _island_sizes(mesh) -> list[list[int]]:
    """
    Connected vertex islands (lists of vertex indices), largest first.
    """
    n = len(mesh.vertices)
    if n == 0:
        return []
    neighbors: list[list[int]] = [[] for _ in range(n)]
    for edge in mesh.edges:
        a, b = edge.vertices
        neighbors[a].append(b)
        neighbors[b].append(a)
    seen = [False] * n
    islands = []
    for seed in range(n):
        if seen[seed]:
            continue
        stack = [seed]
        seen[seed] = True
        island = []
        while stack:
            v = stack.pop()
            island.append(v)
            for o in neighbors[v]:
                if not seen[o]:
                    seen[o] = True
                    stack.append(o)
        islands.append(island)
    islands.sort(key=len, reverse=True)
    return islands


def _apply_modifier(obj, mod) -> None:
    _select_only([obj], active=obj)
    bpy.ops.object.modifier_apply(modifier=mod.name)


def _voxel_remesh(obj, voxel_size: float) -> None:
    mod = obj.modifiers.new("blrig_remesh", "REMESH")
    mod.mode = "VOXEL"
    mod.voxel_size = voxel_size
    _apply_modifier(obj, mod)


def _fatten(obj, strength: float) -> None:
    mod = obj.modifiers.new("blrig_fatten", "DISPLACE")
    mod.direction = "NORMAL"
    mod.mid_level = 0.0
    mod.strength = strength
    _apply_modifier(obj, mod)


def estimate_midline_x(objects, height: float) -> float:
    """
    The character's bilateral midline. The combined bbox center is WRONG
    in general — one long one-sided appendage drags it sideways. Bilateral
    parts (head, torso, pants, paired shoes) share the same bbox-center x;
    one-sided parts don't. Take the largest cluster of per-part center-x
    values (tolerance 2% of height) and use its mean.
    """
    centers = []
    for obj in objects:
        xs = [(obj.matrix_world @ Vector(c)).x for c in obj.bound_box]
        centers.append((min(xs) + max(xs)) * 0.5)
    tolerance = max(height * 0.02, 1e-6)
    best: list[float] = []
    for pivot in centers:
        cluster = [c for c in centers if abs(c - pivot) <= tolerance]
        if len(cluster) > len(best):
            best = cluster
    return float(sum(best) / len(best))


def _bridge_islands(obj, voxel_size: float) -> int:
    """
    Connect every minor island to the largest one with a cylinder between
    their nearest vertex pair, thick enough (4x voxel) to survive the next
    remesh. Returns the number of bridges added.
    """
    from mathutils import kdtree

    islands = _island_sizes(obj.data)
    if len(islands) <= 1:
        return 0
    verts = obj.data.vertices
    hub = islands[0]
    tree = kdtree.KDTree(len(hub))
    for i, vi in enumerate(hub):
        tree.insert(verts[vi].co, i)
    tree.balance()

    bridges = []
    for island in islands[1:]:
        best = None
        for vi in island:
            co, _index, dist = tree.find(verts[vi].co)
            if best is None or dist < best[2]:
                best = (verts[vi].co.copy(), co.copy(), dist)
        if best is None:  # _island_sizes never yields empty islands; guard anyway
            continue
        p0, p1, _dist = best
        direction = p1 - p0
        length = max(direction.length, voxel_size)
        bpy.ops.mesh.primitive_cylinder_add(
            radius=4.0 * voxel_size,
            depth=length + 8.0 * voxel_size,
            location=obj.matrix_world @ ((p0 + p1) * 0.5))
        cyl = bpy.context.view_layer.objects.active
        cyl.rotation_euler = direction.to_track_quat("Z", "Y").to_euler()
        bridges.append(cyl)

    _select_only([obj] + bridges, active=obj)
    bpy.ops.object.join()
    return len(bridges)


def _drop_debris_islands(obj, min_verts: int) -> int:
    islands = _island_sizes(obj.data)
    doomed_indices = {vi for island in islands[1:] if len(island) < min_verts
                      for vi in island}
    if not doomed_indices:
        return 0
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    doomed = [bm.verts[i] for i in doomed_indices]
    bmesh.ops.delete(bm, geom=doomed, context="VERTS")
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return len(doomed_indices)


def build_fused_proxy(objects, name: str, voxel_size: float,
                      fatten_rounds: int = 4, bridge_rounds: int = 2) -> dict:
    """
    Duplicate-join *objects*, voxel-remesh, then fatten/bridge until the
    proxy is ONE connected island. Returns
    ``{"object": proxy, "islands": n, "verts": n, "rounds": [...]}`` —
    callers must treat ``islands > 1`` as failure and roll back.
    """
    scene_collection = bpy.context.scene.collection
    duplicates = []
    for src in objects:
        dup = src.copy()
        dup.data = src.data.copy()
        scene_collection.objects.link(dup)
        duplicates.append(dup)
    _select_only(duplicates, active=duplicates[0])
    bpy.ops.object.join()
    proxy = bpy.context.view_layer.objects.active
    proxy.name = name
    # join() leaves the merged mesh-data named after the last active object
    # (e.g. "Cone.002") - rename it so debug/inspect output is legible.
    proxy.data.name = name + "_mesh"
    # Bake world transforms so proxy-local == world for all later math.
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    rounds = []
    _voxel_remesh(proxy, voxel_size)
    n_islands = len(_island_sizes(proxy.data))
    rounds.append({"op": "remesh", "islands": n_islands})

    for _round in range(fatten_rounds):
        if n_islands <= 1:
            break
        _fatten(proxy, 1.5 * voxel_size)
        _voxel_remesh(proxy, voxel_size)
        n_islands = len(_island_sizes(proxy.data))
        rounds.append({"op": "fatten+remesh", "islands": n_islands})

    for _round in range(bridge_rounds):
        if n_islands <= 1:
            break
        # Debris too small to host a bridge just gets dropped.
        _drop_debris_islands(proxy, min_verts=max(
            100, int(0.003 * len(proxy.data.vertices))))
        n_bridges = _bridge_islands(proxy, voxel_size)
        _voxel_remesh(proxy, voxel_size)
        n_islands = len(_island_sizes(proxy.data))
        rounds.append({"op": "bridge({:d})+remesh".format(n_bridges),
                       "islands": n_islands})

    return {"object": proxy, "islands": n_islands,
            "verts": len(proxy.data.vertices), "rounds": rounds}


def symmetrize_union(proxy, center_x: float, voxel_size: float) -> None:
    """
    Union *proxy* with its own mirror across the vertical plane at
    ``x = center_x``: the result is exactly bilateral, so the metarig fit
    centers on the true midline and the symmetry gate passes honestly.
    """
    mirror = proxy.copy()
    mirror.data = proxy.data.copy()
    bpy.context.scene.collection.objects.link(mirror)
    # Mirror across x = center_x (proxy transforms are applied/identity).
    mirror.scale.x = -1.0
    mirror.location.x = 2.0 * center_x
    _select_only([mirror], active=mirror)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    # Negative-scale bake flips face winding; flip it back.
    bm = bmesh.new()
    bm.from_mesh(mirror.data)
    bmesh.ops.reverse_faces(bm, faces=bm.faces[:])
    bm.to_mesh(mirror.data)
    bm.free()

    _select_only([proxy, mirror], active=proxy)
    bpy.ops.object.join()
    _voxel_remesh(proxy, voxel_size)


def transfer_weights(proxy, target) -> None:
    """
    Copy ALL vertex-group weights proxy -> target by world-space
    nearest-face interpolation (handles the proxy surface sitting a few
    cm outside the original after fattening).
    """
    _select_only([target, proxy], active=proxy)
    bpy.ops.object.data_transfer(
        data_type="VGROUP_WEIGHTS",
        use_create=True,
        vert_mapping="POLYINTERP_NEAREST",
        layers_select_src="ALL",
        layers_select_dst="NAME",
        mix_mode="REPLACE",
    )


def bind_to_rig(target, rig, rollback=None) -> None:
    """
    Armature modifier + parent (transform preserved). Weights must already
    be on *target* (transferred or rigid).
    """
    if not any(m.type == "ARMATURE" and m.object == rig
               for m in target.modifiers):
        mod = target.modifiers.new("Armature", "ARMATURE")
        mod.object = rig
        if rollback is not None:
            rollback.track_modifier(target, mod)
    if rollback is not None:
        rollback.track_parent(target)
    world = target.matrix_world.copy()
    target.parent = rig
    target.matrix_world = world


def strip_cross_side_leg_weights(target, rig, margin: float,
                                 center_x: float = 0.0, leg_stems=None) -> int:
    """
    Zero .L leg-chain weights on clearly right-side verts and vice versa,
    then renormalize. *margin* is the half-width of the midline dead zone
    around ``x = center_x`` (verts inside it keep their mixed weights —
    the crotch SHOULD blend both thighs). Returns the number of zeroed
    entries. A too-wide margin leaves the inner faces of paired shoes
    dragging with the other foot — size it to the real gap between the
    legs (about 2x the proxy voxel works in practice).
    """
    stems = tuple(leg_stems) if leg_stems is not None else _LEG_GROUP_STEMS
    leg_groups: dict[str, set[int]] = {"L": set(), "R": set()}
    for group in target.vertex_groups:
        bone = rig.data.bones.get(group.name)
        if bone is None or not bone.use_deform:
            continue
        stem = group.name.removeprefix("DEF-").split(".")[0]
        if stem in stems:
            if group.name.endswith((".L", ".L.001", ".L.002")):
                leg_groups["L"].add(group.index)
            elif group.name.endswith((".R", ".R.001", ".R.002")):
                leg_groups["R"].add(group.index)

    matrix_world = target.matrix_world
    zeroed = 0
    for vert in target.data.vertices:
        offset = (matrix_world @ vert.co).x - center_x
        strip = (leg_groups["L"] if offset < -margin
                 else leg_groups["R"] if offset > margin else None)
        if not strip:
            continue
        for entry in vert.groups:
            if entry.group in strip and entry.weight > 0.0:
                entry.weight = 0.0
                zeroed += 1
    if zeroed:
        _select_only([target], active=target)
        bpy.ops.object.vertex_group_normalize_all(lock_active=False)
    return zeroed
