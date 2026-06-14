---
name: posing-kit-limbs
description: Pose a multi-part kit limb (arm/leg joined at cog/peg hinges) into a natural shape — the kinematic model, what fails, and why you should rig it rather than hand-rotate rigid lumps.
keywords: kit, limb, arm, leg, pose, joint, hinge, elbow, shoulder, cog, peg, kinematic, rig, articulate, robot, hang
---

# Posing a kit limb (arm/leg) — the kinematic reality

This is the companion to `kitbash-axis-stacking`. That skill gets the *connection*
right (peg coaxial through the cog-center holes — see `find_kit_connector`). This
skill is about the much harder part: making the assembled limb *look like a limb*.

## The model you must hold in your head

A kit limb is a chain of **links** (rotator = upper arm, wrist = forearm, ...)
joined at **rotational hinges** — the cog/peg joints. Two facts decide everything:

1. **A cog/peg joint is a hinge, not a ball.** The link on the far side can only
   *rotate about the joint axis*. Its body sweeps in the plane **perpendicular to
   that axis**.
2. **The link body is perpendicular to its joint axis.** So a forearm hangs in the
   plane perpendicular to the elbow hinge. **If the hinge axis points vertically,
   the forearm physically cannot hang down — it can only swivel horizontally.**

That second fact is the trap. You will assemble the limb correctly (peg through
the cogs), orient the whole rigid lump to "hang", and it will still look like a
stub bunched at the shoulder. Check the hinge axis: `find_kit_connector` returns
`joint_axis`. **For a limb to hang, every hinge axis must be roughly horizontal
(perpendicular to gravity).**

## What does NOT work (I burned a whole session proving it)

- **Hand-rotating the rigid assembly** ("rotate the arm about the ball until it
  hangs"). The internal elbow angle is baked in, so no single rigid orientation
  makes both the upper arm *and* the forearm vertical — orienting one swings the
  other sideways.
- **Roll-searching about the hang axis to minimise torso penetration.** It stops
  the limb clipping the body, but rolls the bulk into the depth and the limb reads
  as a flat stub.
- **Sequential ad-hoc rotations** (align hinge → point upper arm down → swing
  forearm) do not converge to anything natural and usually fling a link outward.

## What works: RIG it

A multi-joint limb you want to *pose* is a rigging problem. Don't fight it with
matrices:

1. `find_kit_connector` on each source link → the joint axis + center for each
   hinge (robust; teeth-ring derived).
2. Build an **armature**: one bone per hinge, the bone's roll axis aligned to that
   joint axis, bones laid head-to-tail down the limb. Use the `rig` tool /
   `rigging-mechanical` skill (rigid-assembly rigging — parent each part to its
   bone, no weight painting needed for hard-surface kit parts).
3. **Pose the bones**, not the meshes. Now the elbow is a real hinge: rotate the
   forearm bone and the forearm swings in its correct plane. The shoulder bone
   sets the hang; the elbow bone sets the bend.

This is also usually the user's actual ask ("...and a Blender rig") — so it's not
a detour, it's the deliverable.

## If you must place parts without a rig

Use the reliable primitives and accept a straight (un-bent) limb:

- `find_kit_connector` → joint frame; `snap_fit` → seat one part's joint onto a
  target frame; `stack_parts` → collinear chain with peg insertion.
- Compose: shoulder joint at the body, each subsequent joint one link-length down
  the **horizontal-hinge** plane. Keep hinge axes horizontal or the limb won't hang.

## Two meta-rules this session paid for

- **Verify from front + side + a PERSPECTIVE shot.** A single front-ortho hides
  depth — an arm that looks like it hangs down the side can actually be folded
  into the torso. Always add a non-ortho view before declaring success.
- **Solve the task, then the problem — and don't punt the 3D reasoning to the
  user.** Derive the constraint from geometry (`find_kit_connector`, the hinge
  model) and ship the tool/skill so the next run starts from the answer.
