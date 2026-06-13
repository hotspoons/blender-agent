---
name: animating-at-scale
description: Bulk keyframing and parametric motion cycles with the anim(verb, args) tool — phase-offset oscillator cycles for walks/idles/mechanical loops on ANY rig, seamless looping, visual-keying bakes, and layered-Action/NLA management. Builds on the core animating-basics skill.
keywords: animate, animation, keyframe, keyframes, walk, walk cycle, gait, idle, cycle, loop, looping, action, actions, NLA, bake, baking, fcurve, motion, locomotion, swing, oscillate, bob, wave, spin, frames, timeline
aliases: [anim, animation-at-scale]
---

# Animating at scale with the anim tool

Read `animating-basics` (core skill) first for the Blender 5.x
layered-Action model — actions are layered/slotted, `action.fcurves` no
longer exists. `anim(verb, args)` encodes those recipes as deterministic
bulk operations: never hand-write keyframe loops in
`execute_blender_code`. Failed mutations roll the scene back.

## What animates what

Animate the rig's CONTROL bones: `CTL-` bones on rigs built by the
`rig` tool, the unprefixed controls on Rigify rigs (`*_fk.*`, `*_ik.*`,
`torso`, `root`) — never `DEF-`/`ORG-`/`MCH-` bones. Check
`pose("get", {bones: ["*"]})` for what exists, and mind the IK/FK
switch state (`posing` skill) — keys on controls the limb isn't
listening to animate nothing.

## Bulk keyframing

`anim("keyframe", {armature, keys: [{frame, bones: {glob: channels}}]})`
sets channels then keys them, per bone x frame, handling rotation_mode
per bone. Good for staged poses (key poses of an action). Check what
landed with `anim("inspect", {armature})`.

## Parametric cycles (walks, idles, mechanical loops)

`anim("cycle", ...)` builds a seamless loop from PHASE-OFFSET
OSCILLATORS — you say which bones swing, how far, and in what phase
relationship; it computes every key:

```json
{"armature": "RIG-...", "frames": 24, "channels": [
  {"bones": ["thigh_fk.L"], "axis": "x", "amplitude": 25, "phase": 0.0},
  {"bones": ["thigh_fk.R"], "axis": "x", "amplitude": 25, "phase": 0.5},
  {"bones": ["upper_arm_fk.L"], "axis": "x", "amplitude": 15, "phase": 0.5},
  {"bones": ["upper_arm_fk.R"], "axis": "x", "amplitude": 15, "phase": 0.0},
  {"bones": ["torso"], "channel": "location", "axis": "z",
   "amplitude": 0.03, "frequency": 2}
]}
```

Each channel: `value(t) = offset + amplitude * sin(2π·frequency·(t+phase))`,
keyed so t=1 equals t=0 (seamless) with CYCLES extrapolation added.

Gaits are phase relationships, not stored configurations — derive them
from the rig in front of you:
- Alternating pairs (biped legs, opposite arms): phase 0 vs 0.5.
- Diagonal pairs (quadruped trot): front-left + hind-right at 0, the
  other diagonal at 0.5.
- N-legged tripod/wave gaits: list the legs in order and use
  `phase_step` (0.5 for alternating tripods, 1/n_legs for a wave).
- Weight/bob (root or torso vertical): `channel: "location"`,
  `frequency: 2` — once per footfall.
- Subtle idle: tiny amplitudes on torso/head, slow `frames` (e.g. 96).
- Mechanical spin/swing: one channel on the part's control bone.

Amplitudes are semantic (degrees / world units) — start moderate
(15–30° limbs), render a frame, adjust. `cycle_static` failure means
the bones you keyed don't drive the rig (wrong bones or constraint
override) — re-check the control names.

## Looping, baking, layering

- `anim("loop", {armature})` — fix an existing action to loop: pins
  last key = first value, adds CYCLES modifiers, sets the frame range
  (stops one frame short of the wrap so the loop doesn't stutter).
- `anim("bake", {armature, bones?, frame_start?, frame_end?})` — bake
  the evaluated result (IK, constraints, drivers) to plain keys; use
  before export or before deleting helper constraints.
- `anim("actions", {armature, op: "push_nla"})` — finished layer to an
  NLA track, freeing the action slot for the next layer (the
  `animating-basics` layering model). `op: "list"/"new"/"assign"`
  manage actions; `anim("clear")` unlinks.

## Verifying headless

`anim("cycle")` self-checks that pose matrices actually change between
frames. For anything else, compare full pose matrices across frames
(`animating-basics` shows the snippet), or render a frame mid-cycle.
Keys exist but nothing moves → wrong bones, rotation_mode, or IK/FK
state — `anim("inspect")` + `pose("get")` localize it fast.

See also: `animating-basics` (core: layered-Action API, manual
verification), `posing` (static poses, IK/FK), `rigging-overview`
(building the rig first).
