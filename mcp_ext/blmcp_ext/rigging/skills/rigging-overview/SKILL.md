---
name: rigging-overview
description: How to rig anything in Blender with the rigging_* tools — skill selection decision table, the diagnose/run/verify contract, structured failure codes and what to do about each.
---

# Rigging with the deterministic rigging toolset

The `rigging_*` tools rig models WITHOUT you doing spatial reasoning: you
select a skill and pass semantic parameters; deterministic geometry code
inside Blender picks every coordinate. Never compute bone positions
yourself when one of these applies.

## Workflow (always this order)

1. `rigging_inspect(objects=[...])` — health, parts, symmetry, contacts.
2. Pick the skill from the table below.
3. `rigging_diagnose(skill, objects, params)` — dry-run; read the plan.
4. `rigging_run(skill, objects, params)` — builds armature + skinning.
5. `rigging_verify(skill, armature)` — REQUIRED before reporting success.

## Skill selection

| Situation (from rigging_inspect) | Skill |
|---|---|
| 2 parts, elongated contact region (door/lid/jaw/flap) | `rig_hinge` |
| 2 rod-like coaxial parts that slide/extend | `rig_piston` |
| 1 disc-like part that should spin (wheel/gear/fan/dial) | `rig_wheel` |
| 3-part aiming stack: base, rotating platform, elevating member | `rig_turret` |
| Any other pile of rigid parts; one mesh with many loose parts | `rig_rigid_assembly` |
| Symmetric standing humanoid | `rig_biped_rigify` |
| Symmetric four-legged creature | `rig_quadruped_rigify` |

Anti-patterns: do NOT use rig_hinge for face-on-face stacked parts
(ambiguous axis — assembly is the general tool); do NOT use character
skills on mechanical models; do NOT hand-write armature code via
execute_blender_code for cases the table covers.

## Failure codes (act on `suggest`, don't force)

| code | meaning | usual action |
|---|---|---|
| `unhealthy_mesh` | unapplied scale, junk geometry | apply scale / clean, or relay to user; `ignore_health` only if user insists |
| `no_contact` | parts never touch | check object names; rig_rigid_assembly handles floating parts |
| `ambiguous_axis` | contact is face-like | pass `axis_hint: "x"/"y"/"z"` from user intent |
| `not_a_wheel` | part isn't disc-like | wrong skill — reconsider, or `axis_hint` if it really must spin |
| `not_coaxial` / `not_elongated` | not a piston pair | likely rig_hinge or rig_rigid_assembly |
| `no_chain` | turret parts don't touch in order | ctx order must be [base, yaw, pitch] |
| `asymmetric` | character isn't bilaterally symmetric | tell the user; `ignore_symmetry` only on their say-so |
| `bone_heat_failed` | automatic weights found no solution | mesh needs manifold repair (see make-manifold skill) |
| `verify_failed` | rig built but behaves wrong | read `checks`, report the failing check; do not ship the rig |

Every run is rolled back on failure — a failed attempt leaves the scene
clean, so trying a different skill afterwards is safe.

See also: `rigging-mechanical`, `rigging-characters`, `rigging-standard`.
