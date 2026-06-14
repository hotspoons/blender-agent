---
name: kitbash-axis-stacking
description: Assemble imported kit parts into a clean collinear chain (limb/linkage) using end-cap centroids — robust where gear-toothed joints defeat ring detectors.
keywords: kitbash, kit-bash, assembly, stack, collinear, limb, arm, leg, linkage, joint, align, fitting, dowel, peg, socket, chain, mate
---

# Kit-bash assembly: stacking imported parts into a clean collinear chain

When you assemble a limb / mechanism from imported kit parts (a modular arm,
a leg, a robotic linkage), the parts arrive with arbitrary origins and the
joints almost never line up by just sharing a Z. Butting them
bounding-box-center to bounding-box-center makes the chain **zig-zag**,
because each part's real connection face (the socket/cog/peg) sits at a
different lateral offset from its origin.

## Why joint-*ring* detection often fails here

The obvious tool — detect each part's cylindrical port (a ring of side-faces
whose normals are perpendicular to the joint axis, e.g. the `measure_joints`
tool) and mate them — breaks on the parts that need it most. **Gear teeth,
knurling, splines, and bolt detail shatter the "clean ring" assumption**: the
side faces no longer form a single smooth-radius ring, so a covariance/ring
detector returns a tiny spurious radius or picks a world axis at random. If a
port detector gives you a suspiciously small radius or an axis that's obviously
not down the limb, stop trusting it for that part.

## The robust signal: end-cap centroids along a shared axis

Connection faces sit at the **ends** of a part's long axis. So:

1. Pick the chain **axis** (world space). Best source, in order:
   - An explicit axis you already know (e.g. the kit's convention — many kits
     pre-rotate every segment so its long axis is local **Z**; take
     `obj.matrix_world.to_3x3() @ Vector((0,0,1))`).
   - The **principal axis** (largest-eigenvalue eigenvector of the vertex
     covariance) of the *most elongated* part in the chain. Reliable for long
     parts (forearms, shins); **unreliable for chunky/cube-ish parts** whose
     longest extent is a body diagonal, not the joint axis.
2. For each part, project its world-space verts onto the axis, take the
   centroid of the verts in the top slice and the bottom slice (~12% of the
   length each). Those two **cap centroids** are the connection-face centers,
   and they lie on the part's true joint line — teeth and all, because a
   centroid ignores the ring shape.
3. Keep part 0 fixed (base/shoulder end). Translate each subsequent part so its
   **near cap** lands on the previous part's **far cap**, offset by a `gap`
   along the axis. Because each part's own two caps lie on the axis, making the
   junctions coincide forces the **whole chain collinear** — pure translation,
   no per-part rotation needed when the parts are already roughly oriented.
4. **Negative gap = insertion overlap** — seat a dowel/peg a millimetre or two
   into each socket instead of leaving a visible butt seam.

## The tool

`stack_parts` (bundled Tier-B agent tool — find via `search_agent_tools`, run
via `run_agent_tool`) implements exactly this. Args: `names` (ordered chain,
base first), optional `axis` (omit to auto-pick the most-elongated part's
principal axis), `gap` (negative to insert), `align_axes` (rotate each part's
principal axis onto the target first — leave **false** for chunky parts),
`frac` (cap-slice fraction, 0.12).

Verify visually afterward (front + side ortho): the parts should read as one
straight limb. If a part is flipped end-for-end (hand pointing the wrong way),
rotate that one part 180° about the axis before stacking — the stacker aligns
positions, not which end is "out."

## When to reach for what

- Clean cylindrical ports (smooth bores, ball-sockets, plain pegs) →
  `measure_joints` + `snap_fit` is fine and gives you the axis for free.
- Toothed / knurled / detailed joints, or you just need a tidy linear stack →
  `stack_parts` (cap centroids). It does not care about surface detail.
