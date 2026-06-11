---
name: boolean-modeling
description: Combine, subtract, and intersect meshes reliably with the Boolean modifier.
---

# Additive and subtractive boolean modeling

Combine, subtract, and intersect meshes reliably with the Boolean modifier.

## The reliable pattern

```python
import bpy

target = bpy.data.objects["TARGET"]
cutter = bpy.data.objects["CUTTER"]

mod = target.modifiers.new("Bool", type="BOOLEAN")
mod.operation = "DIFFERENCE"   # or "UNION", "INTERSECT"
mod.object = cutter
mod.solver = "EXACT"           # robust; "FAST" only for clean convex cases
mod.use_self = False

# Hide the cutter rather than deleting it - keeps the op adjustable.
cutter.display_type = "WIRE"
cutter.hide_render = True
result = {"modifier": mod.name, "operation": mod.operation}
```

Apply when the user asks for final geometry (requires the evaluated
depsgraph if other modifiers precede it):

```python
import bpy
target = bpy.data.objects["TARGET"]
with bpy.context.temp_override(object=target, active_object=target):
    bpy.ops.object.modifier_apply(modifier="Bool")
```

## Preconditions (check BEFORE the boolean)

- Both meshes manifold (see the make-manifold skill) - the EXACT
  solver tolerates some open geometry but results degrade fast.
- Normals consistently outward on both operands
  (`bmesh.ops.recalc_face_normals`).
- No exactly-coplanar overlapping faces between operands; nudge one
  operand by a tiny epsilon (1e-4 in the cut direction) when faces
  would lie flush.

## Many cutters

Batch with a loop, one modifier per cutter, or join the cutters into
one mesh first (faster, single modifier). For repeated hole patterns,
instance one cutter with an Array modifier, then use it as the
boolean object (apply the array on the cutter first).

## Gotchas

- A boolean that "does nothing" usually means inverted normals on the
  cutter or `solver="FAST"` hitting coplanar faces.
- Unapplied non-uniform scale on either operand distorts the EXACT
  solver's intersection - apply scale first.
- The result inherits materials from the target; transfer material
  slots from the cutter explicitly if a "different material inside the
  cut" look is wanted (use `use_hole_tolerant=True` and material index
  transfer, or post-assign by face selection).
- After applying, re-run a manifold check; boolean seams love to leave
  stray edges.
