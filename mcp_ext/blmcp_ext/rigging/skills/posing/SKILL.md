---
name: posing
description: Pose armatures in bulk with the pose(verb, args) tool — batch transforms via bone globs, pose mirroring, IK/FK switching with snapping, named poses, and the gotchas that make hand-written posing code silently do nothing.
keywords: pose, posing, pose bones, bone, rotate, rotation, transform, mirror pose, flip pose, IK, FK, IK/FK, switch, snap, rest pose, reset, T-pose, pose library, named pose, wave, point, reach, gesture, stance
aliases: [pose, poses]
---

# Posing with the pose tool

`pose(verb, args)` batch-poses armatures; bone names take globs so one
call poses a whole limb set. It owns the four classic silent failures
(below) so you don't reproduce them in `execute_blender_code`. Failed
calls restore the prior pose.

## Workflow

1. `pose("get", {"armature": ...})` — what's posed now, plus IK/FK
   switch state. On an unfamiliar rig pass `{"bones": ["*"]}` once to
   see the control names you can drive.
2. `pose("set", {"armature": ..., "bones": {glob: channels}})` —
   e.g. raise both arms in one call:
   `{"upper_arm_fk.*": {"rotation_deg": [0, 0, -45]}}`. `additive: true`
   nudges from the current pose instead of replacing it.
3. Verify visually (render) or by reading back `pose("get")`.

Other verbs:
- `pose("mirror", {armature, from_side: "L"})` — copy one side onto the
  other, flipped (paste-flipped channel math: -loc.x, euler -y/-z).
  Pose one arm, mirror, done.
- `pose("reset", {armature, bones?})` — rest pose (subset via globs).
- `pose("save_named"` / `"apply_named"` / `"list_named"`, `{armature,
  name})` — stash and recall poses while exploring.

## IK/FK on Rigify rigs

`pose("ik_fk", {armature, to: "fk"|"ik", limbs?: [globs], snap: true})`
switches Rigify limbs and snaps the destination controls to the current
visual pose so nothing jumps.

THE RULE: a limb listens to its FK controls only when its `IK_FK`
property is 1, and to its IK controls only at 0. Posing `hand_ik.*`
while the limb is in FK (or vice versa) is a silent no-op — the pose
"doesn't take" with no error. `pose("get")` reports every switch's
state; switch first, then pose. Small `snap_drift` on to-ik is normal
(the solver can't always reach the FK pose exactly); `snap_drift_ok`
tells you whether it's within tolerance.

On rigs built by the `rig` tool (non-Rigify), there is no IK_FK —
drive the `CTL-` bones directly.

## The silent failures this tool absorbs

- **EDIT-mode freeze**: an armature left in EDIT mode accepts pose
  transforms but never evaluates them — every probe reads 0.0 motion.
  Every verb forces OBJECT mode first.
- **rotation_mode mismatch**: setting `rotation_euler` on a
  QUATERNION-mode bone changes nothing visible. `rotation_deg` values
  are converted to the bone's actual mode, never dropped.
- **Stale reads**: computed transforms are only valid after a depsgraph
  update; `get` updates before reading.
- **IK_FK left flipped**: a switch left at the wrong value makes a
  whole control family inert (see above) — `ik_fk` is the only thing
  that should touch it.

Pose changes are NOT keyframes — they evaporate on frame change unless
keyed. To animate over time use `anim(...)` (`animating-at-scale`).

See also: `rigging-overview` (control naming), `weight-painting` (when
a pose moves the bone but not the mesh).
