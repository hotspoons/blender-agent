---
name: weight-painting
description: Diagnose and fix skinning problems in bulk with the weights(verb, args) tool — coverage inspection, mesh-to-mesh transfer, midline mirroring, clean/limit/normalize, topology smoothing, binding, and the QA gate. What to do when bone-heat fails.
keywords: weight, weights, weight paint, weight painting, skinning, skin, vertex group, vertex groups, deform, deformation, bind, binding, armature modifier, transfer, mirror, normalize, smooth, unweighted, bone heat, automatic weights, influences, rigged, collapse, dragging
aliases: [weights, skinning, weight-paint]
---

# Weight painting with the weights tool

`weights(verb, args)` does bulk weight work deterministically — never
loop over vertices via `execute_blender_code`. Mutating verbs snapshot
the scene and roll back on failure, so retrying is always safe.

## Workflow

1. `weights("inspect", {"object": ..., "armature": ...})` — START HERE.
   Per-group weighted-vert counts, empty groups, L/R imbalance,
   unweighted verts, deform bones with no group. Symptoms map directly:
   a part that doesn't follow its bone → that bone's group is empty or
   missing; one side deforms and the other doesn't → `lr_balance` shows
   the imbalance.
2. Fix with the matching verb (below).
3. `weights("validate", {"objects": [...], "armature": ...})` — the QA
   gate every fix must pass: no unweighted verts, weights normalized,
   no groups naming non-deform bones.

## Verbs and when to reach for them

| Symptom / goal | Verb |
|---|---|
| Don't know what's wrong yet | `inspect` |
| Clothes/props should follow the body's rig | `transfer` from the body mesh, then `bind` |
| Bone-heat failed on one side; one side works | `mirror` from the good side |
| Imported model has 8+ influences per vert, jitter, tiny stray weights | `clean` |
| Hard seam or stair-stepping at a transfer boundary | `smooth` |
| Mesh has weights but ignores the armature | `bind` (modifier + parent) |
| Prove the skinning is right | `validate` |

- `transfer` `{source, targets: [...], armature?}` — world-space
  nearest-face interpolation, all groups. The source must spatially
  cover the targets; an `E_UNWEIGHTED` failure means it doesn't —
  transfer from a closer-fitting mesh.
- `mirror` `{object, from_side: "L"|"R", armature?}` — finds the
  bilateral midline itself (perception symmetry plane) and copies
  side-to-side with `.L`/`.R` group-name flipping. Verts in a small
  midline margin keep their blend — the crotch SHOULD weight both
  thighs. `no_symmetry_plane` → pass `center_x` explicitly.
  `mirror_no_match` → raise `tolerance` (sides differ in tessellation)
  or the mesh is genuinely asymmetric.
- `clean` `{object, threshold?, limit?, armature?}` — prune < threshold
  (default 0.01), cap influences (default 4 — game-engine friendly),
  drop empty groups, normalize. Never creates unweighted verts
  (keep-single guard).
- `smooth` `{object, groups?: [globs], factor?, iterations?}` — blur
  along topology; restrict with group globs when only one joint seams.

## When bone-heat ("automatic weights") fails

Bone-heat needs one connected volume. On shell piles / multi-part
characters, don't fight it vertex-by-vertex: `rig_biped_multipart`
(see `rigging-multipart-characters`) builds a fused disposable proxy,
solves on that, then transfers the weights back — `weights("transfer")`
is the same primitive standalone. A one-sided solve failure (bones
outside the geometry on one side) is usually fixable after the fact
with `weights("mirror")` from the side that worked.

## Gotchas

- Always `validate` after mutating; unnormalized weights make pose
  tests lie (motion scales with the weight sum).
- A bound mesh with NO deform groups silently doesn't move —
  `weights("bind")` refuses that by default (`bind_unweighted`); pass
  `allow_unweighted: true` only when weights arrive in a later step.
- Group names must match DEFORM bone names (`DEF-` prefixed on rigs
  built here; see `rigging-standard`). `inspect` flags groups naming
  non-deform bones — weights there do nothing.
- `.L` is +x in world space. If `mirror` writes the wrong side, your
  `from_side` is flipped, not the tool.

See also: `rigging-overview` (building rigs), `posing` (testing the
result), `rigging-multipart-characters` (the proxy pattern).
