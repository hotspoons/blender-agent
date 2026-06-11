# Rig Standard

Conventions every `blrig` skill produces and `validate_rig()` enforces.
Written for two audiences: the agent (read this before rigging) and the
validator (rule ids below are what its reports reference).

## Bone naming

| Pattern | Class | `use_deform` | Purpose |
|---|---|---|---|
| `root` | root | no | The single root control of every rig |
| `DEF-<name>` | deform | **yes** | Bones meshes are weighted to |
| `CTL-<name>` | control | no | Animator-facing controls |
| `MCH-<name>` | mechanism | no | Internal machinery (hidden) |
| `ORG-<name>` | mechanism | no | Rigify originals (generated rigs only) |
| anything else | control | no | Unprefixed controls (Rigify generates these) |

- Side suffixes: `.L` / `.R`, **at the end** of the name (`DEF-arm.upper.L`).
  Required for Blender's symmetrize and pose mirroring to work.
- Never use Blender default names (`Bone`, `Bone.001`, ...).

## Structure

- Exactly **one** parentless bone in the deform/control hierarchy: `root`.
  Everything else descends from it (the hierarchy is therefore a tree).
  Exception: `MCH-`/`ORG-` mechanism bones may float parentless — Rigify's
  parent-switching machinery relies on constraint-driven floaters.
- Deform/control separation is absolute: a bone deforms if and only if it is
  `DEF-`-prefixed. Meshes get vertex groups **only** for `DEF-` bones.
- No (near-)zero-length bones — Blender silently deletes true zero-length
  bones on mode switch, so anything that would round to zero is an error.
- The armature object has applied scale (`1,1,1`) — unapplied scale corrupts
  bone-heat weighting and constraint spaces.

## Bone collections (organizational, warning-level)

- `DEF` — all deform bones, hidden by default
- `MCH` — mechanism bones, hidden by default
- `CTL` — controls, visible

## Controls

- `CTL-` bones should carry a `custom_shape` (warning-level; mechanical rigs
  generated programmatically get simple shapes from the skill layer).
- Constraints live on `MCH-`/`CTL-` bones, never on `DEF-` bones except
  Copy-Transforms followers that track controls.

## Validation

`blrig.standard.validate_rig(armature_object)` returns:

```python
{
  "ok": bool,                 # no errors (warnings allowed)
  "errors":   [ {"rule": "E_...", "bones": [...], "detail": str}, ... ],
  "warnings": [ {"rule": "W_...", "bones": [...], "detail": str}, ... ],
  "stats": {"n_bones": int, "n_deform": int, "n_control": int, "n_mechanism": int},
}
```

Rules:

| id | meaning |
|---|---|
| `E_NOT_ARMATURE` | object is not an armature |
| `E_NO_BONES` | armature has no bones |
| `E_ROOT_COUNT` | not exactly one parentless bone |
| `E_DEFORM_PREFIX` | `use_deform` bone without `DEF-` prefix |
| `E_PREFIX_DEFORM` | `DEF-` bone with `use_deform` off |
| `E_ZERO_LENGTH` | bone length < 1e-5 of armature size |
| `E_DEFAULT_NAME` | Blender default bone name |
| `E_UNAPPLIED_SCALE` | armature object scale is not (1,1,1) |
| `W_UNPAIRED_SIDE` | `.L` bone without `.R` twin (or vice versa) |
| `W_ROOT_NAME` | the parentless bone is not named `root` |
| `W_NO_CUSTOM_SHAPE` | `CTL-` bone without a custom shape |
| `W_BONE_COLLECTIONS` | prefixed bone not in its matching collection |

`blrig.standard.validate_weights(mesh_object, armature_object)` checks the
skinning side: vertex groups must reference only `DEF-` bones, and every
vertex influenced by the armature must have weights summing to ~1.

Every skill calls `validate_rig()` (and `validate_weights()` when it skins)
as a postcondition — a skill that leaves the scene out of standard is a bug.
