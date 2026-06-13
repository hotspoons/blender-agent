# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
The polymorphic rigging-domain MCP tools — ``rig``, ``weights``, ``pose``
and ``anim`` — one verb-dispatched entry point per tool family, so each
domain costs ONE tool definition in the model's context. The server side
validates inputs and ships code over the bridge; ``blrig`` (inside
Blender) does the geometry.
"""

__all__ = (
    "register",
)

from blmcp.tools_helpers.connection import send_code
from mcp.server.fastmcp import FastMCP  # pylint: disable=import-error,no-name-in-module
from mcp.types import ToolAnnotations  # pylint: disable=import-error,no-name-in-module

from . import BLRIG_PARENT_DIR

_SKILLS = (
    "rig_chain",
    "rig_rigid_assembly",
    "rig_hinge",
    "rig_piston",
    "rig_wheel",
    "rig_turret",
    "rig_biped_rigify",
    "rig_biped_multipart",
    "rig_quadruped_rigify",
    "rig_quadruped_multipart",
)

_VERBS = ("auto", "inspect", "diagnose", "run", "verify", "validate")

_WEIGHTS_VERBS = ("inspect", "transfer", "mirror", "clean", "smooth", "bind",
                  "validate")
_POSE_VERBS = ("get", "set", "mirror", "reset", "ik_fk", "save_named",
               "apply_named", "list_named")
_ANIM_VERBS = ("inspect", "keyframe", "cycle", "loop", "bake", "actions",
               "clear")

_BOOTSTRAP = (
    "import sys\n"
    "if {path!r} not in sys.path:\n"
    "    sys.path.insert(0, {path!r})\n"
).format(path=BLRIG_PARENT_DIR)


def _error(message: str) -> dict[str, object]:
    return {"error": message}


def _code_for(verb: str, args: dict) -> dict[str, object] | str:
    """
    Validate (verb, args) and compose the in-Blender code, or return an
    error dict the model can act on.
    """
    objects = args.get("objects")
    skill = args.get("skill")
    params = args.get("params")

    if verb == "auto":
        if not isinstance(objects, list) or not objects:
            return _error("auto needs args={'objects': [mesh names], "
                          "'skill'?, 'params'?, 'contact_tolerance'?}")
        if skill is not None and skill not in _SKILLS:
            return _error("unknown skill {!r}; valid: {!r}".format(skill, list(_SKILLS)))
        return _BOOTSTRAP + (
            "from blrig.skills import auto_rig as _a\n"
            "result = _a.auto({objects!r}, skill={skill!r}, params={params!r},\n"
            "                 contact_tolerance={tol!r})\n"
        ).format(objects=objects, skill=skill, params=params,
                 tol=args.get("contact_tolerance"))

    if verb == "inspect":
        if not isinstance(objects, list) or not objects:
            return _error("inspect needs args={'objects': [mesh names]}")
        return _BOOTSTRAP + (
            "from blrig.skills import inspect_scene as _i\n"
            "result = _i.inspect({objects!r}, contact_tolerance={tol!r}, "
            "detail={detail!r})\n"
        ).format(objects=objects, tol=args.get("contact_tolerance"),
                 detail=bool(args.get("detail")))

    if verb == "validate":
        armature = args.get("armature")
        if not armature:
            return _error("validate needs args={'armature': name}")
        return _BOOTSTRAP + (
            "import bpy\n"
            "from blrig import standard as _std\n"
            "result = _std.validate_rig(bpy.data.objects.get({armature!r}))\n"
        ).format(armature=armature)

    if verb in ("diagnose", "run"):
        if skill not in _SKILLS:
            return _error("unknown skill {!r}; valid: {!r}".format(skill, list(_SKILLS)))
        if not isinstance(objects, list) or not objects:
            return _error("{:s} needs args={{'skill', 'objects': [names], 'params'?}}".format(verb))
        ctx = {"objects": objects}
        return _BOOTSTRAP + (
            "from blrig import skills as _skills\n"
            "_mod = _skills.get_skill({skill!r})\n"
            "_ctx = {ctx!r}\n"
            "result = {{'report': _mod.{verb:s}(_ctx, {params!r}), 'ctx': _ctx}}\n"
        ).format(skill=skill, ctx=ctx, verb=verb, params=params)

    if verb == "verify":
        if skill not in _SKILLS:
            return _error("unknown skill {!r}; valid: {!r}".format(skill, list(_SKILLS)))
        armature = args.get("armature")
        if not armature:
            return _error("verify needs args={'skill', 'armature', 'objects'?}")
        ctx = {"objects": objects or [], "armature": armature}
        return _BOOTSTRAP + (
            "from blrig import skills as _skills\n"
            "_mod = _skills.get_skill({skill!r})\n"
            "_ctx = {ctx!r}\n"
            "result = {{'report': _mod.verify(_ctx), 'ctx': _ctx}}\n"
        ).format(skill=skill, ctx=ctx)

    return _error("unknown verb {!r}; valid: {!r}".format(verb, list(_VERBS)))


def _ops_call(module: str, valid_verbs: tuple, verb: str, args) -> dict[str, object]:
    """
    Validate and ship a verb-dispatched ops call (weight_ops / pose_ops /
    anim_ops) over the bridge.
    """
    if verb not in valid_verbs:
        return _error("unknown verb {!r}; valid: {!r}".format(verb, list(valid_verbs)))
    if args is not None and not isinstance(args, dict):
        return _error("args must be a dict")
    code = _BOOTSTRAP + (
        "from blrig.skills import {module:s} as _ops\n"
        "result = _ops.dispatch({verb!r}, {args!r})\n"
    ).format(module=module, verb=verb, args=args or {})
    return send_code(code, strict_json=False)


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Rig (deterministic rigging toolset)",
            destructiveHint=True,
        )
    )
    def rig(verb: str, args: dict) -> dict[str, object]:
        """
        Rig ANYTHING — creatures with any number of legs, vehicles,
        robots, props — WITHOUT writing armature code by hand. The
        deterministic geometry code inside Blender computes every
        coordinate (pivots, axes, rolls, weights), rolls back cleanly on
        failure and pose-tests the result; hand-building armatures via
        execute_blender_code forfeits all of that. ALWAYS try this tool
        first for any rigging task.

        FAST PATH — usually the only call you need:
        - rig("auto", {objects: [names]}) — inspects the parts, picks the
          skill, diagnoses, builds AND verifies in one shot; returns a
          staged transcript. Optional args: skill (override its routing),
          params, contact_tolerance.

        Step-by-step verbs (when auto fails, or for fine control):
        - rig("inspect", {objects}) — read-only COMPACT summary: ranked
          `suggested` skills with ready-to-use params, a `next` call to
          make, one line of health/size per object. Pass detail:true only
          if you need raw OBBs and contact points.
        - rig("diagnose", {skill, objects, params?}) — dry-run; returns
          the plan, or a failure code + `suggest` (act on it).
        - rig("run", {...same...}) — build the rig (armature, constraints,
          skinning); rolls back cleanly on failure.
        - rig("verify", {skill, armature, objects?}) — pose-tests through
          the depsgraph; REQUIRED before reporting success (auto already
          includes it).
        - rig("validate", {armature}) — rig-standard report for ANY
          armature, including imported/hand-built ones.

        Skills: rig_chain (ORDERED parts -> ball/hinge joint chain;
        bridges clearance gaps; `armature` param composes chains into an
        existing rig — spider legs, robot arms, landing gear),
        rig_rigid_assembly (any pile of parts; `contact_tolerance`,
        `bridge_gaps`), rig_hinge, rig_piston, rig_wheel, rig_turret,
        rig_biped_rigify (ONE clean symmetric humanoid mesh),
        rig_biped_multipart (humanoid split across several meshes or
        built from non-manifold shell piles — fused weight proxy +
        weight transfer; originals untouched), rig_quadruped_rigify (ONE
        clean four-legged mesh), rig_quadruped_multipart (four-legged
        creature as several meshes / shell piles — same proxy path).

        Param/failure-code reference: skills_read("rigging-overview").
        """
        code = _code_for(str(verb), args if isinstance(args, dict) else {})
        if isinstance(code, dict):
            return code
        return send_code(code, strict_json=False)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Weights (bulk weight painting)",
            destructiveHint=True,
        )
    )
    def weights(verb: str, args: dict) -> dict[str, object]:
        """
        Diagnose and FIX skinning/weight-paint problems in bulk — never
        loop over vertices via execute_blender_code. Use when a mesh
        deforms wrong (collapsing, dragging, not following its bone),
        after importing a rigged model, or to skin meshes against an
        existing armature. Mutating verbs snapshot the scene and roll
        back on failure; retrying is always safe.

        Verbs (args in {}):
        - weights("inspect", {object, armature?}) — START HERE. Coverage
          report: per-group weighted-vert counts, empty groups, L/R
          imbalance, unweighted verts, deform bones with no group.
        - weights("transfer", {source, targets: [names], armature?}) —
          copy all weights mesh->mesh by nearest-face interpolation
          (clothes/props from a body; originals from a repaired proxy).
        - weights("mirror", {object, from_side: "L"|"R", armature?,
          center_x?, tolerance?}) — copy one side's weights onto the
          other across the detected symmetry midline, flipping .L/.R
          group names. Fixes one-sided bone-heat failures.
        - weights("clean", {object, threshold?, limit?, armature?}) —
          prune weights below threshold, cap influences per vert
          (default 4), drop empty groups, normalize.
        - weights("smooth", {object, groups?: [globs], factor?,
          iterations?, armature?}) — blur weights along topology; fixes
          hard seams after transfer and stair-step deformation.
        - weights("bind", {objects: [names], armature}) — armature
          modifier + parent, transform preserved. Weights must already
          exist (else it fails; pass allow_unweighted to bind first).
        - weights("validate", {objects: [names], armature}) — the QA
          gate: unweighted/unnormalized verts, non-deform groups.

        For rigging from scratch use rig(...); for full guidance
        skills_read("weight-painting").
        """
        return _ops_call("weight_ops", _WEIGHTS_VERBS, str(verb), args)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Pose (batch posing toolset)",
            destructiveHint=True,
        )
    )
    def pose(verb: str, args: dict) -> dict[str, object]:
        """
        Read and set armature poses in bulk — bone names take globs, so
        one call poses a whole limb set. Handles the silent killers for
        you: rotation_mode mismatches (values converted, never dropped),
        armatures stuck in EDIT mode, depsgraph updates before reads,
        Rigify IK_FK switch state. Failed calls restore the prior pose.

        Verbs (args in {}):
        - pose("get", {armature, bones?: [globs]}) — read pose channels
          (default: only bones posed away from rest) + IK/FK switch
          state. START HERE on an unfamiliar rig.
        - pose("set", {armature, bones: {glob: {rotation_deg: [x,y,z],
          location?, scale?}}, additive?}) — batch-set transforms; e.g.
          one call raises both arms: {"upper_arm_fk.*": {...}}.
        - pose("mirror", {armature, from_side: "L"|"R", bones?}) — copy
          a pose onto the other side, flipped (paste-flipped math).
        - pose("reset", {armature, bones?}) — back to rest pose.
        - pose("ik_fk", {armature, to: "fk"|"ik", limbs?: [globs],
          snap?}) — switch Rigify limbs IK<->FK and snap the destination
          controls so nothing jumps. Pose FK chains AFTER switching to
          fk, IK targets after switching to ik — otherwise the controls
          you move are silent no-ops.
        - pose("save_named"/"apply_named"/"list_named", {armature,
          name}) — store and recall named poses on the armature.

        Animate over time with anim(...); full guidance:
        skills_read("posing").
        """
        return _ops_call("pose_ops", _POSE_VERBS, str(verb), args)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Anim (bulk keyframing + parametric cycles)",
            destructiveHint=True,
        )
    )
    def anim(verb: str, args: dict) -> dict[str, object]:
        """
        Keyframe animation at scale on Blender 5.x layered Actions —
        bulk key insertion, PARAMETRIC motion cycles (walks, idles,
        mechanical loops for ANY rig), seamless looping, visual-keying
        bakes and NLA layering. Never hand-write keyframe loops or read
        action.fcurves (it no longer exists) via execute_blender_code.
        Failed mutations roll the scene back.

        Verbs (args in {}):
        - anim("inspect", {armature}) — what's animated: action, keyed
          bones/channels, key range, loop modifiers, NLA tracks.
        - anim("keyframe", {armature, keys: [{frame, bones: {glob:
          {rotation_deg|location|scale}}}]}) — bulk insert across
          bones x frames; rotation_mode handled per bone.
        - anim("cycle", {armature, frames?, channels: [{bones: [globs],
          channel: "rotation"|"location", axis, amplitude, phase?,
          phase_step?, frequency?, offset?}]}) — build a seamless
          parametric cycle from phase-offset oscillators. Gaits are
          phase relationships: opposite legs phase 0 and 0.5, tripod
          groups via phase_step, root bob at frequency 2. Drive bones
          the rig actually has (check pose("get") / the rig's controls).
        - anim("loop", {armature}) — make the current action loop
          cleanly: pin last key = first, CYCLES extrapolation, frame
          range.
        - anim("bake", {armature, frame_start?, frame_end?, bones?,
          step?}) — bake constraints/IK to plain keys (visual keying).
        - anim("actions", {armature, op: "list"|"new"|"assign"|
          "push_nla"|"rename"|"remove", name?}) — layered-Action and
          NLA management; push_nla stacks finished layers.
        - anim("clear", {armature, remove_action?, nla?}).

        Static poses: pose(...). Guidance + gait patterns:
        skills_read("animating-at-scale") and the core
        skills_read("animating-basics").
        """
        return _ops_call("anim_ops", _ANIM_VERBS, str(verb), args)
