---
name: rigging-stretchy-limbs
description: Add a cartoon rubber-hose stretchy limb (no elbow/wrist joints) to an existing Rigify rig — single Stretch To deform bone, rigid end-effector, grabbable control. Recipe with exact bones, constraints, and depsgraph acceptance tests.
keywords: stretchy, stretch, rubber, rubber-hose, cartoon, elastic, limb, arm, tentacle, no joints, stretch to, prosthetic, luffy
---

# Stretchy limb on a Rigify rig

"One arm is stretchy with no joints beyond the shoulder" = exactly THREE
bones composed into the generated rig. Validated live end-to-end.

## Bones (edit mode on the generated rig)

| bone | head -> tail | parent | deform |
|---|---|---|---|
| `hand_ik_stretch.L` (control) | wrist point -> hand end | `root` | no |
| `DEF-arm_stretch.L` | shoulder attach -> wrist point | `ORG-shoulder.L` | yes |
| `DEF-hand_stretch.L` | wrist point -> hand end | `hand_ik_stretch.L` | yes |

- Anchor the stretch bone's head at the limb/torso attachment point and
  parent it to `ORG-shoulder.L` (offset child, `use_connect=False`) so
  the shoulder shrug control still carries the whole limb.
- Parent the control to `root` so pulling the torso away stretches the
  arm — IK-like behavior, which is the fun of a stretchy limb.

## Constraint

One `STRETCH_TO` on `DEF-arm_stretch.L`, target = the control bone,
`volume='NO_VOLUME'` — a cartoon limb keeps its thickness; volume
preservation makes it balloon. The bone's tail coincides with the
control's head at rest, so rest length auto-computes correctly.

## Weights

- Limb mesh -> `DEF-arm_stretch.L` at 1.0 (it stretches along the bone).
- End-effector mesh (hand) -> `DEF-hand_stretch.L` at 1.0 (rigid; a hand
  must not smear when the arm stretches).
- A joint cap / shoulder attachment mesh -> `DEF-shoulder.L` at 1.0.

## Rig hygiene

- Hide the superseded Rigify limb control collections ("Arm.L (IK)",
  "Arm.L (FK)", "Arm.L (Tweak)") instead of deleting bones — deleting
  generated bones breaks drivers; hiding is reversible.
- Assign the new `DEF-` bones to the `DEF` bone collection and give the
  control a widget (reuse an existing `WGT-*hand_ik*` object) + a theme
  color; `validate_rig()` flags unhomed prefixed bones, and an unmarked
  control is undiscoverable.
- Expect a `W_UNPAIRED_SIDE` validate warning — correct and intentional
  for a deliberately asymmetric character; do not "fix" it.

## Acceptance tests (run them through the depsgraph, numbers from live)

Pull the control hard (e.g. +0.7 along the limb) and measure evaluated
world-space verts per mesh:

- Limb mesh: displacement GRADIENT along the limb — near zero at the
  anchor (0.004), maximal at the wrist (0.884). Uniform displacement
  means it is not stretching; zero everywhere means weights or
  evaluation are broken.
- End-effector: uniform displacement AND pairwise vertex distances
  preserved exactly (rigidity error 0.0).
- Torso and everything else: exactly 0.0 — any movement is weight
  leakage into the stretch bone.
- Release the control: everything returns to rest positions exactly.
