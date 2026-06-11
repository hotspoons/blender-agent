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

_VERBS = ("inspect", "diagnose", "run", "verify", "validate")

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

    if verb == "inspect":
        if not isinstance(objects, list) or not objects:
            return _error("inspect needs args={'objects': [mesh names]}")
        return _BOOTSTRAP + (
            "from blrig.skills import inspect_scene as _i\n"
            "result = _i.inspect({objects!r}, contact_tolerance={tol!r})\n"
        ).format(objects=objects, tol=args.get("contact_tolerance"))

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
        Deterministic rigging for ANY model — creatures, vehicles, robots,
        props. You pick a verb and a skill; coordinate-level decisions
        (axes, pivots, weights) are computed from the geometry. One tool,
        verb-dispatched:

        - rig("inspect", {objects: [names]}) — READ-ONLY first step:
          health, parts, symmetry, contacts, disconnected groups with
          their gaps, and `suggested` skills WITH ready-to-use params.
        - rig("diagnose", {skill, objects, params?}) — dry-run check;
          returns the plan, or a failure code + `suggest` (act on it).
        - rig("run", {skill, objects, params?}) — build the rig (armature,
          constraints, skinning); rolls back cleanly on failure.
        - rig("verify", {skill, armature, objects?}) — REQUIRED before
          reporting success: pose-tests the rig through the depsgraph.
        - rig("validate", {armature}) — rig-standard report for any
          armature, including imported/hand-built ones.

        Skills: rig_chain (ORDERED parts -> ball/hinge joint chain;
        bridges clearance gaps; `armature` param composes chains into an
        existing rig — spider legs, robot arms, landing gear),
        rig_rigid_assembly (any pile of parts; `contact_tolerance`,
        `bridge_gaps`), rig_hinge, rig_piston, rig_wheel, rig_turret,
        rig_biped_rigify, rig_quadruped_rigify.

        Typical flow: inspect -> follow `suggested` -> diagnose -> run ->
        verify. Param/failure-code reference: skills_read("rigging-overview").
        """
        code = _code_for(str(verb), args if isinstance(args, dict) else {})
        if isinstance(code, dict):
            return code
        return send_code(code, strict_json=False)
