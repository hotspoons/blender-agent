---
name: rigging-multipart-characters
description: Rig humanoids modeled as piles of separate shell meshes with rig_biped_multipart — fused disposable weight proxy, Rigify on the proxy, weight transfer back to the untouched originals. Includes every gotcha from the live session that produced it.
keywords: character, humanoid, multi-part, multipart, parts, shells, non-manifold, loose parts, bone heat failed, weight transfer, proxy, asymmetric, prosthetic, accessories, separate meshes
aliases: [rig_biped_multipart]
---

# Multi-part / shell-pile character rigging

`rig_biped_rigify` wants ONE symmetric watertight mesh. Real stylized
characters are usually the opposite: eight objects, ~290 overlapping
non-manifold shells, a shoe made of 138 loose parts, and a giant
one-sided appendage. This skill rigs those WITHOUT repairing or
modifying any visible mesh.

```
rig("inspect", {"objects": [<all character parts>]})
rig("run", {"skill": "rig_biped_multipart",
            "objects": ["Body", "Head", "Pants", "Shoes", ...]})
rig("verify", {"skill": "rig_biped_multipart", "armature": "Rig.Biped"})
```

Params: `name`, `metarig`, `keep_metarig`, `symmetrize` (default True),
`voxel_size` (default height/150), `center_x` (midline override),
`side_margin`, `ignore_health`.

## How it works (and why each step exists)

1. **Disposable weight proxy.** Copies of all parts are joined,
   voxel-remeshed, and repeatedly fattened (displace along normals) and
   re-remeshed until everything fuses into ONE island; clearance gaps
   that never fuse (e.g. pant legs modeled as two open tubes) are
   bridged with cylinders between nearest island points. Bone heat needs
   one connected volume — on a shell pile it either fails outright or
   "succeeds" with one bone's weights eaten by a neighbor.
2. **Mirror-union symmetrization.** The proxy is unioned with its own
   X-mirror across the character's midline, making it EXACTLY bilateral.
   The midline is the largest cluster of per-part bbox-center x values —
   NOT the combined bbox center, which one heavy one-sided appendage
   drags sideways. (Live failure: a 0.9m hand dragged the fit center
   +0.23m; the "right leg" bones landed inside the LEFT pant leg and the
   left-leg bones in empty air — and bones outside all geometry are
   exactly the ones whose heat solve fails, so the left leg ended up
   with ZERO weights while right-leg bones absorbed the whole lower
   body.)
3. **Rigify on the proxy** via `rig_biped_rigify` (same gates, same
   bone-heat coverage check).
4. **Weight transfer back**: world-space `POLYINTERP_NEAREST` per
   original — exact enough even though the fattened proxy surface sits
   a few cm outside the originals.
5. **Cross-side leg cleanup**: fattening fuses the two legs/shoes at the
   centerline, so heat bleeds a little weight across the midline. Verify
   by lifting one foot IK and measuring the OTHER shoe through the
   depsgraph — it must read 0.0. The fix strips .L leg-chain weights
   from clearly-right verts (and vice versa) outside a small midline
   dead zone, then renormalizes. Keep the dead zone narrow (~2x voxel):
   the crotch should blend both thighs, but the inner faces of paired
   shoes must not.
6. **Proxy deleted.** Originals end up with transferred weights, an
   armature modifier, and rig parenting — geometry untouched.

## Fixing a bad metarig fit (`keep_metarig`)

The proportional fit can land joints outside the mesh on stylized
proportions (live: ankles 15cm underground, head bone INVERTED above the
crown, wrists at the fattened blob tip). The designed correction loop:

1. `run` with `keep_metarig: true`.
2. Move the metarig edit-bones to anatomy computed from the real part
   bounding boxes (ankle inside the shoe, ball + toe at the front, heel
   marker on the ground plane, elbow mid-arm with a consistent backward
   bend, head bone from neck-top up through the skull).
3. Delete metarig bones the character cannot use — fingers/palms for
   mitt hands, the whole `face` hierarchy for a solid cartoon head,
   breast bones. Rigify handles arbitrary subsets; 132 fewer bones makes
   a far cleaner rig and stops finger/face bones from stealing weights.
4. Regenerate: select the metarig, `bpy.ops.pose.rigify_generate()` —
   it rebuilds the SAME target rig (`data.rigify_target_rig`).
5. Re-bind (clear vgroups + `parent_set(type='ARMATURE_AUTO')`) and
   re-verify. Weight quality after joint correction is the tell:
   head ~0.8 to the head bone, hand ~0.8 to `DEF-hand`, shoe a
   foot/toe/shin blend with the toe region ~0.8 toe.

## Accessories and rigid parts

Parts that should follow one bone rigidly (helmets, armor plates,
attachments at a joint) skip transfer: one vertex group at weight 1.0 on
the right DEF bone + armature modifier. Verify rigidity through the
depsgraph: pairwise vertex distances must be preserved EXACTLY (error
0.0), and uniform displacement across the part.

## Gotchas that cost real debugging time (all hit live)

- **EDIT-mode freeze**: an armature left in edit mode accepts pose-bone
  transforms from Python but evaluates NONE of them — every probe
  measures 0.0 displacement against a perfectly healthy rig. Check
  `rig.mode` FIRST when "nothing moves". (verify() now guards this.)
- **IK_FK left flipped**: FK pose tests flip `["IK_FK"]` to 1; if it is
  not restored, every IK control becomes a silent no-op. If `hand_ik.*`
  does nothing, read the `*_parent` custom props before debugging
  weights. (verify() now restores them.)
- **Sampling bias**: voxel-remesh output vertex order is spatially
  sorted (bottom-up z slabs). "Check the first N verts" silently tests
  only the feet. Sample the whole mesh or stride it.
- **Coverage ≠ quality**: full weight coverage with a skewed skeleton
  still deforms garbage. After any bind, audit dominant groups per body
  REGION (head / chest / each limb / each shoe) — symmetric regions must
  report mirrored groups at similar magnitudes.
- **`parent_set(ARMATURE_AUTO)` only warns** on bone-heat failure; the
  reliable signal is coverage counting afterwards (the skills do this —
  do the same in ad-hoc code).
- **Mirror-bake flips winding**: applying a negative scale inverts face
  normals; reverse faces afterwards or the next voxel remesh produces an
  inside-out union.
