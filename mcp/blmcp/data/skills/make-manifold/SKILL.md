---
name: make-manifold
description: Diagnose and repair non-manifold geometry so a mesh is watertight for booleans, 3D printing, and volumetrics.
---

# Make a mesh manifold (watertight)

Diagnose and repair non-manifold geometry so a mesh is watertight for booleans, 3D printing, and volumetrics.

## Diagnose first

```python
import bpy, bmesh
obj = bpy.data.objects["TARGET"]
bm = bmesh.new()
bm.from_mesh(obj.data)
non_manifold_edges = [e for e in bm.edges if not e.is_manifold]
boundary_edges = [e for e in bm.edges if e.is_boundary]
loose_verts = [v for v in bm.verts if not v.link_edges]
result = {
    "non_manifold_edges": len(non_manifold_edges),
    "boundary_edges": len(boundary_edges),
    "loose_verts": len(loose_verts),
}
bm.free()
```

Interpretation: boundary edges = holes; non-manifold non-boundary
edges = internal faces or >2 faces per edge; loose verts = debris.

## Repair recipe (escalating)

1. Remove debris and merge doubles:

```python
import bpy, bmesh
obj = bpy.data.objects["TARGET"]
bm = bmesh.new()
bm.from_mesh(obj.data)
bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
loose = [v for v in bm.verts if not v.link_faces]
bmesh.ops.delete(bm, geom=loose, context="VERTS")
bm.to_mesh(obj.data)
bm.free()
obj.data.update()
```

2. Fill simple holes (boundary loops):

```python
bmesh.ops.holes_fill(bm, edges=bm.edges, sides=0)  # sides=0: any size
```

3. Delete interior faces: select non-manifold, non-boundary edges and
   remove their faces, then re-fill holes.

4. Recalculate normals outside at the end:

```python
bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
```

5. Last resort for hopeless meshes: the Remesh modifier
   (`mode='VOXEL'`, pick `voxel_size` ~ 1/200 of the object's largest
   dimension) produces a guaranteed-manifold result at the cost of
   re-topologizing everything.

## Gotchas

- `remove_doubles` with too large a `dist` welds intentional details;
  start at 1e-5 and only increase if the diagnosis count doesn't drop.
- Always re-run the diagnosis block after each step and report counts;
  stop as soon as the mesh is clean.
- Mirror/Solidify/Boolean modifiers can re-introduce non-manifold
  geometry on apply - check after applying the stack, not before.
