---
name: rigging-mechanical
description: Parameters and behavior of the mechanical rigging skills — rig_chain, rig_rigid_assembly, rig_hinge, rig_piston, rig_wheel, rig_turret — with worked rig() tool-call examples including gap bridging and chain composition.
keywords: chain, limb, leg, arm, tail, tentacle, boom, spider, insect, robot, robotic, hinge, door, lid, jaw, joint, piston, cylinder, wheel, tire, gear, fan, propeller, turret, vehicle, car, airplane, landing gear, crane, excavator, linkage, assembly, parts
aliases: [rig_chain, rig_rigid_assembly, rig_hinge, rig_piston, rig_wheel, rig_turret]
---

# Mechanical rigging skills

All calls go through the single `rig` tool: `rig("run", {"skill": ...,
"objects": [...], "params": {...}})` (and the same shape for "diagnose").

## rig_chain — ordered segments, any joint types, gaps welcome

THE primitive for limbs, arms, tails, booms, landing gear. Objects are
given IN ORDER (root first); each consecutive pair gets a joint at their
contact — or, when they don't touch, a BRIDGED joint at the nearest-pair
midpoint (no tolerance tuning needed; the order says they connect).

Params: `joint_types` (list of "ball"/"hinge", one per joint; default all
ball), `hinge_axis_hint`, `hinge_limits_deg` (default ±120),
`armature` + `parent_bone` (compose this chain INTO an existing rig),
`name`, `contact_tolerance`, `ignore_health`.

```
rig("run", {"skill": "rig_chain",
            "objects": ["Shoulder", "UpperArm", "Forearm"],
            "params": {"joint_types": ["ball", "hinge"],
                       "armature": "Rig.Robot"}})
```
A knee-style hinge axis defaults to the cross product of the two
segments' directions; pass `hinge_axis_hint` when segments are parallel.

All of these build a standard-compliant armature (root bone, `DEF-` deform
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
rig("run", {"skill": "rig_hinge", "objects": ["Frame", "Door"],
            "params": {"min_angle_deg": 0, "max_angle_deg": 90}})
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
rig("run", {"skill": "rig_turret", "objects": ["Base", "Drum", "Barrel"],
            "params": {"pitch_limits_deg": [0, 75]}})  # never below horizontal
```

## rig_rigid_assembly — the general case

Any number of objects, or ONE mesh whose loose parts are the assembly.
Builds bone-per-part from the contact graph (spanning tree per connected
group, rooted at the largest part), inserts a `CTL-<part>` joint at every
contact, classifies joints `hinge_like`/`ball_like`/`bridged_ball`.

Disconnected groups: with `bridge_gaps` set, each group attaches to its
nearest already-connected part with a free ball joint at the gap midpoint
(an 8-legged creature rigs in ONE call — legs keep their internal joints
and join the body across the modeled clearance). Without it, group
anchors parent to the rig root as `floating`, and `floating_detail`
reports each one's nearest part + gap so the right `bridge_gaps` is one
rerun away. Params: `root_part`, `name`, `contact_tolerance`,
`bridge_gaps`, `ignore_health`.

```
rig("run", {"skill": "rig_rigid_assembly",
            "objects": ["Body", "LimbSegment1", "LimbSegment2", ...],
            "params": {"bridge_gaps": 0.05}})
```
Take the `bridge_gaps` value from inspect's suggestion (it computes one
from the measured gaps) rather than guessing.

## Direct library access (advanced)

The same logic is importable inside `execute_blender_code` when you need
custom orchestration — see the `files` list of this skill for the import
bootstrap; prefer the rig tool otherwise.
