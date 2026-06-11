---
name: rigging-standard
description: The rig standard every blrig skill enforces — DEF/CTL/MCH naming, single-root hierarchy, deform/control separation — and how to validate any armature against it with rig("validate", {"armature": ...}).
---

# The rig standard

Every rig the rigging tools produce conforms to this; `rig("validate", ...)`
checks ANY armature (imported or hand-built too) and returns
machine-readable findings.

## Rules in brief

- Bone classes by prefix: `DEF-` (deforms, the ONLY bones meshes are
  weighted to), `CTL-` (animator-facing), `MCH-`/`ORG-` (machinery,
  hidden). `root` is the single parentless control; mechanism bones may
  float parentless (Rigify parent-switching).
- Side suffixes `.L`/`.R` at the END of the name — required for
  symmetrize and pose mirroring.
- A bone deforms if and only if it is `DEF-` prefixed (`E_DEFORM_PREFIX` /
  `E_PREFIX_DEFORM` otherwise).
- No Blender default names (`Bone.001`), no near-zero-length bones, no
  unapplied armature object scale.
- Vertex groups: only `DEF-` bone names; weights sum to 1 per vertex.

## Reading a validation report

```
rig("validate", {"armature": "Rig.Hinge"})
-> {"ok": true|false, "errors": [{"rule": "E_...", "bones": [...], "detail": ...}],
    "warnings": [...], "stats": {...}}
```

`errors` block acceptance; `warnings` (unpaired sides, missing custom
shapes, collection layout) are advisory. When repairing someone else's
armature, fix errors in this order: scale -> root count -> deform/prefix
agreement -> zero-length -> names.

The full standard text with rationale ships beside this skill as
`RIG_STANDARD.md`.
