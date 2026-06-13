---
name: rigging-characters
description: Character rigging with rig_biped_rigify and rig_quadruped_rigify — Rigify-generated control rigs with bone-heat automatic weights, symmetry/health gates, IK/FK, and deformation verification.
keywords: character, humanoid, human, person, figure, biped, quadruped, dog, cat, horse, wolf, deer, creature, animal, rigify, ik, fk, walk, pose, organic
aliases: [rig_biped_rigify, rig_quadruped_rigify]
---

# Character rigging skills

Both skills wrap Blender's own machinery — a Rigify metarig fitted to the
mesh from perception measurements, the Rigify generator for the control
rig (IK/FK limbs included), and bone-heat automatic weights with explicit
normalization. Nothing is reimplemented; nothing is eyeballed.

## rig_biped_rigify

One symmetric, standing (Z-up) humanoid mesh. If the character is split
across SEVERAL meshes, or is one mesh made of overlapping non-manifold
shells, use `rig_biped_multipart` instead (see
rigging-multipart-characters) — it rigs a disposable fused weight proxy
and transfers the weights back without touching the originals.

```
rig("run", {"skill": "rig_biped_rigify", "objects": ["Hero"]})
rig("verify", {"skill": "rig_biped_rigify", "armature": "Rig.Biped"})
```

Params: `name` (default "Rig.Biped"), `metarig` ("human" full-featured
default, "basic_human" lighter), `keep_metarig` (keep the fitted metarig
for manual joint tweaks before re-generating), `ignore_symmetry`,
`ignore_health`.

## rig_quadruped_rigify

One symmetric four-legged mesh. Params: `name`, `keep_metarig`,
`ignore_symmetry`, `ignore_health`.

## Gates you will hit

- `asymmetric`: bilateral symmetry is required for metarig mirroring and
  weight symmetrize. Report the measured `asymmetry_pct` to the user;
  only override with `ignore_symmetry` on their instruction.
- `unhealthy_mesh` (unapplied/non-uniform scale): bone-heat silently
  produces garbage on unapplied scale — apply scale, don't override.
- `bone_heat_failed`: automatic weights found no solution (non-manifold or
  overlapping shells). Blender only prints a console warning for this; the
  skill detects it via weight coverage and rolls the scene back. Prefer
  `rig_biped_multipart` (rigs a fused disposable proxy and transfers the
  weights back — no destructive repair of the visible mesh); repair the
  mesh only when you may modify it (see the make-manifold skill), or use
  rig_rigid_assembly if the model is actually rigid pieces.

## After generation

- The rig is a full Rigify rig: FK controls (`upper_arm_fk.L`, ...), IK
  controls (`hand_ik.L`, `foot_ik.L`, ...), IK/FK switches as custom
  properties on `*_parent.L/R` bones (`["IK_FK"]`, 0=IK 1=FK; call
  `rig.update_tag()` + `view_layer.update()` after setting from Python).
- verify() already pose-tests limbs and checks volume preservation; treat
  its `checks` list as the acceptance record.
- Keep posing via controls only — never rotate `DEF-`/`ORG-` bones.
- If posing from Python ever measures 0.0 displacement on a healthy rig,
  check `rig.mode` — an armature left in EDIT mode accepts pose values
  but evaluates none of them. And if `hand_ik.*`/`foot_ik.*` controls do
  nothing, read `["IK_FK"]` on the `*_parent` bones (1 = FK wins) before
  suspecting weights.

## Fixing a bad metarig fit

The proportional fit is deliberate v1 and can misplace joints on
stylized proportions (ankles below the floor, head bone above the
skull). Use `keep_metarig: true`, correct the metarig edit-bone joints
from the real anatomy, optionally delete unusable features (fingers for
mitt hands, the `face` hierarchy for solid cartoon heads — Rigify
handles arbitrary subsets), then `bpy.ops.pose.rigify_generate()` to
rebuild the SAME target rig, and re-bind. Full recipe:
rigging-multipart-characters.
