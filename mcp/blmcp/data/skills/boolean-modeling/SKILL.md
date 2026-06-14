---
name: boolean-modeling
description: Combine, subtract, and intersect meshes reliably with the Boolean modifier.
keywords: boolean, union, difference, subtract, intersect, cut, hole, carve, merge, combine, csg
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

For N operands that *overlap each other* (e.g. one socket per face of a
box, meeting at the edges), prefer **sequential** unions of closed
solids over a single combined operand with `use_self=True`. Sequential
closed-vs-closed unions stay manifold; one `use_self` pass over a
self-intersecting combined mesh tends to spray non-manifold slivers.

## Open shells and receptacles (cups, ports, vents, sockets)

An operand that is an open shell - a cup, a recess, a vent with an
unclosed mouth - breaks the boolean: the solver can't decide inside vs
outside, so unions leave holes and `use_self=True` makes it worse. The
robust pattern is **cap -> boolean as closed solids -> re-open**:

1. Cap the opening so the shell is a closed manifold (fill the boundary
   loop, e.g. `bmesh.ops.edgenet_fill`). Extruding the rim ~1 mm before
   capping keeps the cap clear of the target's surface and avoids the
   coplanar-face failure mode.
2. Run the boolean as closed-vs-closed (union to add the body, or
   difference to carve the cavity). This stays manifold.
3. Re-open the mouth by deleting the cap faces - locate them by a
   geometric test (centroid on the cap plane, inside the opening
   footprint) or by tagging them with a material/vertex group before
   the boolean.

To make a recess flush instead of a protruding lump, grow the target
body out to the rim plane and *difference* the shell - a difference of
two closed solids is inherently watertight, and "cut the cavity into
solid material" is what gives a snap-fit undercut something to bite.

## Diagnose precisely: open vs non-manifold vs degenerate

`len(e.link_faces) != 2` lumps three different problems together. Split
them - they have different causes and fixes:

- **open / boundary** (`e.is_boundary`, 1 face) - a hole or an
  *intentional* opening (a pocket mouth). Not always a bug.
- **non-manifold** (`not e.is_manifold and not e.is_boundary`, >2 faces
  or wire) - a real defect from coplanar overlaps or self-intersection.
- **degenerate faces** (`f.calc_area() < 1e-8`) - zero-area slivers,
  usually boolean debris; clear with `dissolve_degenerate`.

`get_mesh_diagnostics(name)` returns exactly this triage (plus
`is_watertight`, volume, world bounds, scale/normal flags) in one call -
run it after each boolean instead of re-typing a `bmesh` stats block.

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
