---
name: rigging-mechanical
description: Parameters and behavior of the mechanical rigging skills — rig_hinge, rig_piston, rig_wheel, rig_turret, rig_rigid_assembly — with worked tool-call examples.
---

# Mechanical rigging skills

All five build a standard-compliant armature (root bone, `DEF-` deform
bones rigid-bound at weight 1.0, `CTL-` controls with custom shapes) and
verify themselves by actually posing the rig through the depsgraph.

## rig_hinge — two parts that swing where they meet

The hinge axis comes from the contact region's dominant direction; the
swinging part is the one reaching away from the hinge line (a door extends
from its hinges; the frame post sits on them).

Params: `axis_hint` ("x"/"y"/"z", only when diagnose says ambiguous_axis),
`moving` (object name override), `min_angle_deg`/`max_angle_deg`
(default ±120), `name`.

```
rigging_run(skill="rig_hinge", objects=["Frame", "Door"],
            params={"min_angle_deg": 0, "max_angle_deg": 90})
```
Animator surface: rotate `CTL-hinge` about its local Y (constraint-limited).

## rig_piston — paired damped-track bones

Two rod-like, roughly coaxial parts; each half aims at the other's anchor,
so dragging either `CTL-anchor.A`/`CTL-anchor.B` extends/retracts while
both stay aligned. Params: `name`, `ignore_alignment`.

## rig_wheel — free spin about the disc axis

Disc detection: two near-equal OBB extents + a smaller third; the spin
axis is the minor axis. Params: `axis_hint` (near-spherical parts), `name`.
Animator surface: `CTL-spin`, local Y, unlimited.

## rig_turret — yaw/pitch aiming stack

Object order is semantic: `objects=[base, rotating_platform,
elevating_member]`. Yaw pivots about the platform's own vertical axis at
the base interface; pitch axis is horizontal, perpendicular to the member.
Params: `yaw_axis` (default "z"), `yaw_limits_deg` (default [-180,180]),
`pitch_limits_deg` (default [-15,75]), `name`.

```
rigging_run(skill="rig_turret", objects=["Base", "Drum", "Barrel"],
            params={"pitch_limits_deg": [0, 75]})   # never below horizontal
```

## rig_rigid_assembly — the general case

Any number of objects, or ONE mesh whose loose parts are the assembly.
Builds bone-per-part from the contact graph's spanning tree (rooted at the
largest part), inserts a `CTL-<part>` joint at every contact, classifies
each joint `hinge_like`/`ball_like` in the result, parents non-touching
parts to root as `floating`. Params: `root_part`, `name`.

Use when nothing more specific fits, or first — its joint classification
tells you which pairs deserve a precise rig_hinge re-rig with limits.

## Direct library access (advanced)

The same logic is importable inside `execute_blender_code` when you need
custom orchestration — see the `files` list of this skill for the import
bootstrap; prefer the rigging_* tools otherwise.
