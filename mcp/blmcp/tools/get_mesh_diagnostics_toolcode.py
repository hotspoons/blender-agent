# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Tool-code for a read-only topology / printability report on one mesh.

Answers "is this watertight / printable?" in a single call instead of a
hand-written ``bmesh`` stats block: counts, the open-vs-non-manifold-vs-
degenerate triage, boundary-loop count, world bounds, volume, and whether
scale is applied and normals are consistent.
"""

__all__ = (
    "Params",
    "Result",
    "main",
)

from typing import NamedTuple

# Faces below this area (object-local units) are treated as degenerate.
_AREA_EPS = 1e-8


class Params(NamedTuple):
    name: str
    # Evaluate the modifier stack (the geometry you would export) when True;
    # inspect the raw base mesh when False.
    evaluated: bool = True


class Result(NamedTuple):
    status: str
    name: str | None = None
    evaluated: bool | None = None
    verts: int | None = None
    edges: int | None = None
    faces: int | None = None
    # Open boundary edges (exactly one linked face): holes / intentional openings.
    open_edges: int | None = None
    # Edges with >2 faces or zero faces (wire): genuine non-manifold defects.
    non_manifold_edges: int | None = None
    # Faces with near-zero area.
    degenerate_faces: int | None = None
    # Distinct closed loops formed by the open edges.
    boundary_loops: int | None = None
    # True when there are no open edges and no non-manifold edges.
    is_watertight: bool | None = None
    # bmesh volume (only meaningful when watertight).
    volume: float | None = None
    # World-space bounding-box dimensions and min/max corners.
    world_dimensions: list[float] | None = None
    bbox_min: list[float] | None = None
    bbox_max: list[float] | None = None
    # object.scale == (1, 1, 1).
    scale_is_applied: bool | None = None
    # No manifold edge has both faces wound the same way.
    normals_consistent: bool | None = None
    message: str | None = None


def main(params: Params) -> Result:
    import bmesh  # pylint: disable=import-error,no-name-in-module
    import bpy  # pylint: disable=import-error,no-name-in-module
    import mathutils  # pylint: disable=import-error,no-name-in-module

    obj = bpy.data.objects.get(params.name)
    if obj is None:
        available = sorted(bpy.data.objects.keys())
        return Result(
            status="error",
            message="Object {!r} not found. Available objects: {:s}".format(
                params.name, ", ".join(available) if available else "(none)",
            ),
        )
    if obj.type != "MESH":
        return Result(
            status="error",
            message="Object {!r} is a {:s}, not a MESH.".format(params.name, obj.type),
        )

    # Source the mesh: evaluated (modifiers applied) or the raw base mesh.
    eval_obj = None
    if params.evaluated:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        eval_obj = obj.evaluated_get(depsgraph)
        mesh = eval_obj.to_mesh()
    else:
        mesh = obj.data

    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bm.normal_update()

        n_verts = len(bm.verts)
        n_edges = len(bm.edges)
        n_faces = len(bm.faces)

        open_edges = [e for e in bm.edges if e.is_boundary]
        non_manifold_edges = [
            e for e in bm.edges if not e.is_manifold and not e.is_boundary
        ]
        degenerate_faces = sum(1 for f in bm.faces if f.calc_area() < _AREA_EPS)

        # Inconsistent normals: a manifold edge whose two loops start at the
        # same vertex means its two faces wind the same way.
        normals_inconsistent = 0
        for e in bm.edges:
            loops = e.link_loops
            if len(loops) == 2 and loops[0].vert == loops[1].vert:
                normals_inconsistent += 1

        # Count distinct boundary loops (connected components of open edges).
        edge_pairs = [(e.verts[0].index, e.verts[1].index) for e in open_edges]
        boundary_loops = _count_components(edge_pairs)

        volume = bm.calc_volume() if n_faces else 0.0
    finally:
        bm.free()
        if eval_obj is not None:
            eval_obj.to_mesh_clear()

    # World-space bounds from the object's transformed bounding box.
    corners = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
    bbox_min = [min(c[i] for c in corners) for i in range(3)]
    bbox_max = [max(c[i] for c in corners) for i in range(3)]

    return Result(
        status="ok",
        name=obj.name,
        evaluated=params.evaluated,
        verts=n_verts,
        edges=n_edges,
        faces=n_faces,
        open_edges=len(open_edges),
        non_manifold_edges=len(non_manifold_edges),
        degenerate_faces=degenerate_faces,
        boundary_loops=boundary_loops,
        is_watertight=(len(open_edges) == 0 and len(non_manifold_edges) == 0),
        volume=round(volume, 6),
        world_dimensions=[round(v, 6) for v in obj.dimensions],
        bbox_min=[round(v, 6) for v in bbox_min],
        bbox_max=[round(v, 6) for v in bbox_max],
        scale_is_applied=all(abs(s - 1.0) < 1e-6 for s in obj.scale),
        normals_consistent=(normals_inconsistent == 0),
        message=None,
    )


def _count_components(edge_pairs: list[tuple[int, int]]) -> int:
    """
    Count connected components in a list of (vert_index, vert_index) edges.
    Turns a flat set of open edges into a loop count.
    """
    adjacency: dict[int, list[int]] = {}
    for a, b in edge_pairs:
        adjacency.setdefault(a, []).append(b)
        adjacency.setdefault(b, []).append(a)
    seen: set[int] = set()
    components = 0
    for start in adjacency:
        if start in seen:
            continue
        components += 1
        stack = [start]
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            stack.extend(adjacency[node])
    return components
