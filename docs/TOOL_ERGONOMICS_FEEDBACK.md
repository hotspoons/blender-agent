# Blender MCP — Tool Ergonomics Feedback

Field notes captured while driving the MCP toolset on a real modeling task
(designing a print-ready "witch hat" knob for a Mesa Boogie amp: grafting a new
fluted/numbered body onto a donor model's D-shaft collet). Captured 2026-06-20.

## What worked well

- **`welcome` → live skills list.** The forced "call this first" framing
  actually landed; reading it shaped how the rest of the session was driven.
- **`scene("mesh")` printability triage.** Watertight / non-manifold /
  degenerate / volume in one call is the right altitude for this domain. Ended up
  reproducing it with bmesh anyway, but having it as one call is great.
- **Verb-dispatched polymorphic tools** (`scene`, `capture`, `media_io`) keep the
  toolspace small and discoverable.
- **`media_io` "everything goes through the media folder, never write files via
  execute".** Clear mental model, no ambiguity about where deliverables land. The
  no-overwrite suffixing is a nice touch.

## Friction points

- **`capture("screenshot")` depends on hidden viewport state.** Getting a
  top/3-4 view required dropping into `execute_blender_code` and driving
  `view3d.view_axis` + `view_orbit` through a `temp_override` context dance. A lot
  of incantation for "show me the top." This was the single most awkward thing in
  the session.
- **No measurement/raycast primitive.** The thing most needed for a precision-fit
  part was "probe the geometry." Hand-rolled `obj.ray_cast` loops three times to
  characterize the bore (diameter, D-flat position, depth). A native cross-section
  / probe would have replaced all of it.
- **`execute_blender_code` is still load-bearing for anything constructive.** All
  the actual modeling (lathe, knurl, booleans, text) was hand-written `bpy`. Fine
  as an escape hatch, but the boolean → verify → recalc-normals loop is common
  enough to deserve a first-class tool.
- **No structured error affordance on bmesh ops.** Failed booleans tend to fail
  silently into non-manifold geometry; only caught because `is_manifold` was
  checked manually after every step. A helper that refuses to apply and reports
  the failure would remove that self-policing burden.

## Tools wanted (priority order)

1. **`capture` / viewport with explicit named views + auto-frame.**
   `view: "top"|"front"|"iso"|{azimuth,elevation}` and `frame_object: "name"`.
   Kills the `temp_override` dance.
2. **A geometry probe** — raycast, cross-section, or caliper ("distance between
   these two features"). e.g. `scene("section", {axis, at})` returning a
   cross-section polyline. Precision-fit parts live or die on this.
3. **A boolean / modifier-apply helper that verifies manifoldness and reports
   failure** instead of leaving bad geometry. e.g.
   `model("boolean", {a, b, op, verify: true})`.
4. **A "fillet / chamfer this edge loop" verb.** Bevels are constantly needed and
   fiddly via raw bmesh.
5. **`media_io("export")` with a units/scale guarantee + a printability gate** —
   auto-run the `scene("mesh")` triage on export and warn if not watertight.

## Summary

The overall design instinct is right: small polymorphic tools, inspect-before-act,
skills as recipes. The gap is the **mechanical-CAD middle layer** — probe
geometry, do a verified boolean, fillet an edge. Today all three drop to raw `bpy`.
