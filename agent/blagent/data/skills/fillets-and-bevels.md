# Fillets, rounded corners, and bevels

Round edges and corners predictably - the Bevel modifier (non-destructive, preferred) or bmesh bevel (destructive, scriptable).

## Non-destructive: Bevel modifier

```python
import bpy
obj = bpy.data.objects["TARGET"]
mod = obj.modifiers.get("Bevel") or obj.modifiers.new("Bevel", type="BEVEL")
mod.width = 0.01          # meters - scale-dependent, see gotchas
mod.segments = 4          # 3-6 looks round; 1 is a chamfer
mod.limit_method = "ANGLE"
mod.angle_limit = 0.785398  # 45 degrees
mod.miter_outer = "MITER_ARC"
result = {"modifier": mod.name, "width": mod.width}
```

For selective edges, use `limit_method = "WEIGHT"` and set per-edge
bevel weights:

```python
import bpy, bmesh
obj = bpy.data.objects["TARGET"]
bm = bmesh.new()
bm.from_mesh(obj.data)
layer = bm.edges.layers.float.get("bevel_weight_edge") or bm.edges.layers.float.new("bevel_weight_edge")
for e in bm.edges:
    if abs(e.verts[0].co.z - e.verts[1].co.z) < 1e-6:  # example: horizontal edges
        e[layer] = 1.0
bm.to_mesh(obj.data)
bm.free()
```

## Destructive: bmesh bevel on specific edges

```python
import bpy, bmesh, math
obj = bpy.data.objects["TARGET"]
bm = bmesh.new()
bm.from_mesh(obj.data)
to_bevel = [e for e in bm.edges if e.calc_face_angle(0) > math.radians(30)]
bmesh.ops.bevel(
    bm, geom=to_bevel, offset=0.01, segments=4, profile=0.5,
    affect="EDGES", clamp_overlap=True,
)
bm.to_mesh(obj.data)
bm.free()
obj.data.update()
```

## Gotchas

- UNAPPLIED OBJECT SCALE breaks bevel widths (a 0.01 bevel on a
  scale-2.0 object cuts 0.02). Check `obj.scale`; if not (1,1,1),
  apply scale first or compensate.
- `clamp_overlap=True` prevents self-intersection on tight corners but
  can silently shrink the bevel - verify visually.
- Bevel after Boolean in the modifier stack usually fails on the new
  intersection edges; apply the boolean first, then bevel with WEIGHT
  on the seam edges.
- A `profile` of 0.5 is circular; ~0.7 approximates a squircle; 1.0 is
  a hard chamfer of the segment polyline.
