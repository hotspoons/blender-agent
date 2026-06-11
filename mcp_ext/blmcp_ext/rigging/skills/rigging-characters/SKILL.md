---
name: rigging-characters
description: Character rigging with rig_biped_rigify and rig_quadruped_rigify — Rigify-generated control rigs with bone-heat automatic weights, symmetry/health gates, IK/FK, and deformation verification.
---

# Character rigging skills

Both skills wrap Blender's own machinery — a Rigify metarig fitted to the
mesh from perception measurements, the Rigify generator for the control
rig (IK/FK limbs included), and bone-heat automatic weights with explicit
normalization. Nothing is reimplemented; nothing is eyeballed.

## rig_biped_rigify

One symmetric, standing (Z-up) humanoid mesh.

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
  skill detects it via weight coverage and rolls the scene back. Repair the
  mesh first (see the make-manifold skill) or, if the model is actually
  rigid pieces, use rig_rigid_assembly instead.

## After generation

- The rig is a full Rigify rig: FK controls (`upper_arm_fk.L`, ...), IK
  controls (`hand_ik.L`, `foot_ik.L`, ...), IK/FK switches as custom
  properties on `*_parent.L/R` bones (`["IK_FK"]`, 0=IK 1=FK; call
  `rig.update_tag()` + `view_layer.update()` after setting from Python).
- verify() already pose-tests limbs and checks volume preservation; treat
  its `checks` list as the acceptance record.
- Keep posing via controls only — never rotate `DEF-`/`ORG-` bones.
