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

## Find the joint axis from the SOURCE part — don't guess on the copy

The slow, wrong way to assemble a kit limb is to detect sockets on the
already-placed/rotated/scaled copies: they have multiple square features (a
cog-center hole, side box pockets, a claw) and you cannot tell which one the
designer meant. **Go back to the clean source part instead** — its connector
geometry is unambiguous.

Kit connectors are almost always **coaxial with the joint**: the designer parks
a loose square peg island at the part's cog center, running along the cog axis,
so it threads through the square hole in the middle of the toothed cog face. The
side "boxes" are just housing around that axial joint — not separate sockets.

`find_kit_connector` (bundled Tier-B tool) extracts this for you:

1. Decomposes the mesh into loose islands.
2. Detects the **cog tooth ring** — a group of >=4 near-identical small square
   posts. That ring *defines* the joint axis and center (robust: teeth come in a
   ring, so they're trivially distinguished from the lone peg).
3. Returns the lone elongated square island that is **coaxial** with the ring
   (axis parallel, centered on the ring axis) as the `connector`, plus
   `joint_axis` and `joint_center`.

Run it on the source parts of a chain (e.g. `modular_rotator`, `modular_elbow`)
— if they report the same connector cross-section + a consistent axis, that IS
the kit's connector and the axis you assemble along.

### Assembling a pegged chain

With the connector length `L` and an insertion depth `d` (~1.5mm), stack
`[partA, peg, partB]` along `joint_axis` so the peg threads through both
cog-center holes:

- peg inserts `d` into partA and `d` into partB,
- the **exposed** connector between the two cog faces is `L - 2*d` (set the
  cog-face spacing to this so the peg reads as a visible connector, not buried).

Use `stack_parts` with a negative gap for the insertion, or place by cap-centroid
math directly. The parts stay three separate solids — printable, and the peg is
its own part.

## Don't punt the hard part

If an assembly is fiddly, the answer is to **read the source geometry and derive
the constraint deterministically** (as above) — not to hand the 3D reasoning back
to the user. The whole point of this toolkit is that a model figures the kit out
once and ships a tool so nobody re-derives it. Solve the task, then generalise it
into a tool/skill so the next run starts from the solution.

## When to reach for what

- Clean cylindrical ports (smooth bores, ball-sockets, plain pegs) →
  `measure_joints` + `snap_fit` is fine and gives you the axis for free.
- Toothed / knurled / detailed joints, or you just need a tidy linear stack →
  `stack_parts` (cap centroids). It does not care about surface detail.
