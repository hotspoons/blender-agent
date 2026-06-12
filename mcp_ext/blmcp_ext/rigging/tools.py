# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
The single polymorphic ``rig`` MCP tool: one entry point, verb-dispatched,
so the rigging domain costs ONE tool definition in the model's context
instead of five. The server side validates inputs and ships code over the
bridge; ``blrig`` (inside Blender) does the geometry.
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
    "rig_quadruped_rigify",
)

_VERBS = ("auto", "inspect", "diagnose", "run", "verify", "validate")

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
        rig_biped_rigify, rig_quadruped_rigify.

        Param/failure-code reference: skills_read("rigging-overview").
        """
        code = _code_for(str(verb), args if isinstance(args, dict) else {})
        if isinstance(code, dict):
            return code
        return send_code(code, strict_json=False)
