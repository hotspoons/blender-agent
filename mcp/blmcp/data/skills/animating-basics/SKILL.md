---
name: animating-basics
description: Keyframe animation that works in modern Blender (5.x layered/slotted Actions) - keyframing pose bones, reading f-curves back, seamless loops with cycles modifiers, gait patterns, and headless verification without a viewport.
keywords: animate, animation, keyframe, keyframes, walk, cycle, loop, looping, action, fcurve, f-curve, timeline, frame, pose, motion, gait, walk cycle, cyclic, interpolation
aliases: [animation, keyframing]
---

# Keyframe animation (layered Actions)

The single biggest time sink for agents animating in Blender 5.x:
`action.fcurves` NO LONGER EXISTS. Actions are layered and slotted now.
Write keyframes the normal way (it handles the new structure for you);
read them back through the channelbag.

## Writing keyframes — let keyframe_insert do the work

```python
arm = bpy.data.objects["MyRig"]
pb = arm.pose.bones["CTL-some_control"]
pb.rotation_euler[1] = 0.35
pb.keyframe_insert("rotation_euler", frame=1)
```

- No pose mode, no operators, no manual Action/slot/layer setup needed —
  `keyframe_insert` creates the action, slot, layer, strip and f-curves.
- Mind `rotation_mode`: keying `rotation_euler` on a bone whose mode is
  `QUATERNION` (the default) animates nothing visible. Either set
  `pb.rotation_mode = "XYZ"` first or key `rotation_quaternion`.
- On rigs built by the `rig` tool, animate `CTL-` bones only — never
  `DEF-` bones (deformation follows the controls).

## Reading f-curves back — the layered API

```python
action = arm.animation_data.action
slot = action.slots[0]
fcurves = []
for layer in action.layers:
    for strip in layer.strips:
        bag = strip.channelbag(slot)
        if bag:
            fcurves.extend(bag.fcurves)
# fc.data_path is e.g. 'pose.bones["CTL-some_control"].rotation_euler'
```

Symptoms of doing it the old way: `AttributeError: ... fcurves`, or
"0 fcurves" on an action that clearly animates. Do not fight it with
`dir()` exploration — the path is always layers → strips →
`channelbag(slot)` → `fcurves`.

## Seamless loops

1. Make the last keyed frame's pose IDENTICAL to the first (key the
   same values at `frame_start` and `frame_end`), and
2. add a cycles modifier to every f-curve so the motion extrapolates:

```python
for fc in fcurves:
    if not any(m.type == "CYCLES" for m in fc.modifiers):
        fc.modifiers.new("CYCLES")
scene = bpy.context.scene
scene.frame_start, scene.frame_end = 1, 24
```

## Gait patterns (walks with any number of legs)

Split legs into alternating support groups (biped: L/R; quadruped:
diagonal pairs; 6-8 legs: alternating tripods/tetrapods — adjacent legs
in different groups). Give the groups the same keys offset by half the
cycle, e.g. group A plants at frame 1 while group B lifts, swapping at
the midpoint. A small root-bone bob at the support transfers (1/4 and
3/4 of the cycle) sells the weight.

## Verifying headless (no viewport needed)

```python
scene.frame_set(1)
bpy.context.view_layer.update()
m1 = arm.pose.bones["CTL-some_control"].matrix.copy()
scene.frame_set(12)
bpy.context.view_layer.update()
assert arm.pose.bones["CTL-some_control"].matrix != m1  # keys drive the bone
```

Compare the FULL pose matrix (`.matrix.translation` alone misses
rotation-only animation — a bone rotating about its own head does not
translate). For deformation-level proof, compare evaluated mesh
vertices across frames:
`obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).data.vertices`.
If nothing changes, the keys are not driving anything (wrong
rotation_mode, wrong bone, or keys on the object instead of the pose
bone). For a visual check, render a frame with
`media_io("render", {"frame": ...})` when that tool is available —
window/viewport screenshot tools do not work headless.

## Failure notes

- `action.fcurves` AttributeError → layered API above.
- Keys exist but nothing moves → rotation_mode mismatch, or you keyed
  `arm.rotation_euler` (the object) instead of a pose bone's.
- Loop pops at wrap-around → first/last keys not identical, or some
  f-curves missing the cycles modifier.
- Frame range still default → set `scene.frame_start/frame_end`; the
  cycles modifier extrapolates beyond the keyed range either way.
