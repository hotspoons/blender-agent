---
name: rigging-overview
description: How to rig ANYTHING in Blender with the rig(verb, args) tool — creatures with any number of legs, vehicles, robots, props. Decision table, gap bridging, the diagnose/run/verify contract, and every failure code with its fix.
keywords: rig, rigging, armature, skeleton, bones, skinning, weights, creature, animal, insect, arthropod, spider, crab, lobster, scorpion, ant, centipede, hexapod, octopod, horse, quadruped, monster, legs, limbs, character, vehicle, car, airplane, plane, robot, mech, machine, prop, animate, animation
aliases: [rig, rigging]
---

# Rigging with the deterministic rigging tool

ONE tool covers the whole domain: `rig(verb, args)`. You select a skill
and pass semantic parameters; deterministic geometry code inside Blender
computes every coordinate. Never compute bone positions yourself, and
never hand-build armatures via `execute_blender_code` for cases below.

## Fast path

`rig("auto", {"objects": [...]})` — inspects, picks the best skill,
diagnoses, builds and verifies in ONE call; the result is a staged
transcript ending in `ok` + `armature`. Pass `skill` to override its
routing and `params` for extras; suggested params still fill in as
defaults. When `auto` fails it stops at the failing stage with the
failure code — fall back to the step-by-step flow below.

## Workflow (step-by-step, always this order)

1. `rig("inspect", {"objects": [...]})` — read-only COMPACT summary:
   `suggested` ranked skills with ready-to-use params and a `next` call
   to make come FIRST, then one line of health/size per object and the
   component structure with gaps. `{"detail": true}` for raw OBBs,
   per-part breakdowns and contact points. START HERE.
2. `rig("diagnose", {"skill": ..., "objects": [...], "params": {...}})`
   — dry-run; read the plan or the failure code.
3. `rig("run", {...same...})` — builds the rig; rolls back on failure.
4. `rig("verify", {"skill": ..., "armature": ...})` — REQUIRED before
   reporting success (`auto` already includes it).

## Skill selection

| Situation (from inspect) | Skill |
|---|---|
| ORDERED segments forming a limb/arm/tail/boom — touching or not | `rig_chain` |
| Any pile of rigid parts; one mesh with many loose parts; creature with N legs | `rig_rigid_assembly` |
| 2 parts, elongated contact (door/lid/jaw) | `rig_hinge` |
| 2 rod-like coaxial parts that slide | `rig_piston` |
| 1 disc-like part that spins (wheel/gear/fan/prop) | `rig_wheel` |
| base + rotating platform + elevating member | `rig_turret` |
| symmetric standing humanoid, ONE clean mesh | `rig_biped_rigify` |
| humanoid as SEVERAL meshes, shell piles, or with one-sided appendages | `rig_biped_multipart` |
| symmetric four-legged character | `rig_quadruped_rigify` |

**Multi-legged creatures — ANY number of legs, ANY segments per leg**
(quadrupeds of disjoint limbs, hexapod ants, octopod spiders/crabs,
many-legged centipedes, radial mechanisms): the approach is the same
regardless of count. `rig_rigid_assembly` with `bridge_gaps` rigs the
whole thing in one call — each leg chain keeps its internal joints and
attaches to the body across modeled clearance gaps. For precise
per-joint control instead, rig the body first, then each leg with
`rig_chain` passing `armature` so all chains compose into ONE rig.
Nothing about this is specialized to a particular creature; drive it
from what `inspect` reports (leg count, gaps), not a fixed template.

**Vehicles (cars, planes):** `rig_rigid_assembly` for the body/chassis,
`rig_wheel` per wheel/propeller, `rig_hinge` for doors/control surfaces,
`rig_piston` for suspension/gear struts, `rig_chain` for landing-gear
linkages — chains and re-runs compose via the `armature` param.

## Gaps and tolerances (parts that don't touch)

Models are often built with clearance — nothing touches. Two levers:

- `contact_tolerance` (assembly/chain/hinge): max distance that still
  counts as touching. Default 0.1% of the assembly size.
- `bridge_gaps` (assembly): attach whole disconnected groups with a free
  ball joint at the nearest-pair midpoint. The result's
  `floating_detail` lists every unattached group's nearest part and gap
  — the right value is one rerun away. `rig_chain` bridges automatically
  (the part order already says they connect).

## Failure codes (act on `suggest`, don't force)

| code | meaning | usual action |
|---|---|---|
| `unhealthy_mesh` | unapplied scale, junk geometry | apply scale / clean; `ignore_health` only if the user insists |
| `no_contact` | hinge/turret parts never touch | use rig_chain (bridges) or assembly `bridge_gaps` |
| `ambiguous_axis` | contact/segments give no hinge axis | pass `axis_hint` / `hinge_axis_hint` |
| `not_a_wheel` / `not_coaxial` / `not_elongated` | wrong skill for the shape | follow `suggest` |
| `no_chain` | turret order wrong | objects = [base, platform, member] |
| `asymmetric` | character not bilaterally symmetric | tell the user; `ignore_symmetry` on their say-so |
| `bone_heat_failed` | auto-weights found no solution | `rig_biped_multipart` (proxy path), repair mesh (make-manifold), or rig as parts |
| `proxy_not_fused` | multipart proxy stayed disconnected | raise `voxel_size`, or rig_rigid_assembly |
| `transfer_failed` | a part got unweighted verts after transfer | lower `voxel_size` so the proxy hugs the parts |
| `bone_exists` | chain composed twice into one armature | pick different part set / armature |
| `verify_failed` | rig built but moves wrong | read `checks`; do not ship |

Failed runs roll back — retrying a different skill is always safe.

See also: `rigging-mechanical`, `rigging-characters`,
`rigging-multipart-characters`, `rigging-stretchy-limbs`,
`rigging-standard`.
