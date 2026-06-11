# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
``rigging_*`` MCP tools. Each composes Python that runs inside the
connected Blender (where ``blrig`` does the geometry); the server side
only validates inputs and ships code over the bridge.
"""

__all__ = (
    "register",
)

from blmcp.tools_helpers.connection import send_code
from mcp.server.fastmcp import FastMCP  # pylint: disable=import-error,no-name-in-module
from mcp.types import ToolAnnotations  # pylint: disable=import-error,no-name-in-module

from . import BLRIG_PARENT_DIR

_SKILLS = (
    "rig_hinge",
    "rig_piston",
    "rig_wheel",
    "rig_turret",
    "rig_rigid_assembly",
    "rig_biped_rigify",
    "rig_quadruped_rigify",
)

_BOOTSTRAP = (
    "import sys\n"
    "if {path!r} not in sys.path:\n"
    "    sys.path.insert(0, {path!r})\n"
).format(path=BLRIG_PARENT_DIR)


def _skill_call(stage: str, skill: str, ctx: dict, params: dict | None) -> dict[str, object]:
    if skill not in _SKILLS:
        return {"error": "unknown skill {!r}; valid: {!r}".format(skill, list(_SKILLS))}
    if stage == "verify":
        call = "_mod.verify(_ctx)"
    else:
        call = "_mod.{:s}(_ctx, {!r})".format(stage, params)
    code = _BOOTSTRAP + (
        "from blrig import skills as _skills\n"
        "_mod = _skills.get_skill({skill!r})\n"
        "_ctx = {ctx!r}\n"
        "result = {{'report': {call:s}, 'ctx': _ctx}}\n"
    ).format(skill=skill, ctx=ctx, call=call)
    return send_code(code, strict_json=False)


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Rigging: Inspect Geometry",
            readOnlyHint=True,
        )
    )
    def rigging_inspect(objects: list[str]) -> dict[str, object]:
        """
        Geometric perception over the named mesh objects, read-only: mesh
        health (gates every rigging skill), loose-part decomposition,
        bilateral-symmetry estimate per object, and the contact graph
        between them. Use this FIRST to pick a rigging skill: elongated
        two-part contact -> rig_hinge; disc-like part -> rig_wheel; coaxial
        rods -> rig_piston; base/platform/member stack -> rig_turret; many
        parts / unknown -> rig_rigid_assembly; symmetric organic ->
        rig_biped_rigify / rig_quadruped_rigify.

        Read the `rigging-overview` skill (skills_read) for the decision
        table and failure codes. Run `welcome` first if you have not.
        """
        code = _BOOTSTRAP + (
            "import bpy\n"
            "from blrig import perception as _p\n"
            "_objs = {objects!r}\n"
            "_out = {{'objects': {{}}, 'contact_graph': None, 'missing': []}}\n"
            "_found = []\n"
            "for _name in _objs:\n"
            "    _o = bpy.data.objects.get(_name)\n"
            "    if _o is None or _o.type != 'MESH':\n"
            "        _out['missing'].append(_name)\n"
            "        continue\n"
            "    _found.append(_o)\n"
            "    _parts = _p.loose_parts(_o)\n"
            "    for _part in _parts:\n"
            "        del _part['vert_indices']\n"
            "    _sym = _p.symmetry_plane(_o)\n"
            "    _sym.pop('candidates', None)\n"
            "    _out['objects'][_name] = {{\n"
            "        'health': _p.mesh_health(_o),\n"
            "        'obb': _p.part_obb(_o),\n"
            "        'loose_parts': _parts,\n"
            "        'symmetry': _sym,\n"
            "    }}\n"
            "if len(_found) > 1:\n"
            "    _out['contact_graph'] = _p.contact_graph(_found)\n"
            "result = _out\n"
        ).format(objects=objects)
        return send_code(code, strict_json=False)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Rigging: Diagnose (precondition check)",
            readOnlyHint=True,
        )
    )
    def rigging_diagnose(skill: str, objects: list[str],
                         params: dict | None = None) -> dict[str, object]:
        """
        Dry-run precondition check for a rigging skill — never mutates the
        scene. Returns the deterministic plan (axes, pivots, part roles) on
        success, or a structured failure with a machine-readable code and a
        `suggest` field (e.g. unhealthy_mesh, no_contact, ambiguous_axis,
        not_a_wheel, asymmetric). ALWAYS act on `suggest` rather than
        forcing parameters.

        Skills: rig_hinge, rig_piston, rig_wheel, rig_turret,
        rig_rigid_assembly, rig_biped_rigify, rig_quadruped_rigify.
        Params are semantic only (see the rigging skills via skills_read).
        """
        return _skill_call("diagnose", skill, {"objects": objects}, params)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Rigging: Run Skill",
            destructiveHint=True,
        )
    )
    def rigging_run(skill: str, objects: list[str],
                    params: dict | None = None) -> dict[str, object]:
        """
        Execute a rigging skill: builds the armature, constraints and
        skinning for the named objects. Rolls back cleanly on failure (a
        failed run never corrupts the scene). The returned ctx carries the
        created armature name — pass it to rigging_verify, ALWAYS, before
        reporting success.

        Run rigging_diagnose first when unsure; run() re-checks the same
        preconditions and fails with the same structured codes.
        """
        return _skill_call("run", skill, {"objects": objects}, params)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Rigging: Verify Rig",
            readOnlyHint=True,
        )
    )
    def rigging_verify(skill: str, armature: str,
                       objects: list[str] | None = None) -> dict[str, object]:
        """
        Postcondition check for a rig produced by rigging_run: standard
        compliance (validate_rig), weight validity, and skill-specific pose
        tests through the real depsgraph (does the hinge hinge, does the
        fixed part stay put, do limits clamp, does the character deform
        without volume collapse). The pose is reset afterwards.

        "Technically valid" is not "deforms acceptably" — only report a rig
        as done after this passes.
        """
        ctx = {"objects": objects or [], "armature": armature}
        return _skill_call("verify", skill, ctx, None)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Rigging: Validate Against Standard",
            readOnlyHint=True,
        )
    )
    def rigging_validate_rig(armature: str) -> dict[str, object]:
        """
        Validate any armature (including hand-built or imported ones)
        against the rig standard: naming prefixes (DEF/CTL/MCH), single
        root, deform/control separation, zero-length bones, side pairing.
        Returns machine-readable errors/warnings per rule.
        """
        code = _BOOTSTRAP + (
            "import bpy\n"
            "from blrig import standard as _std\n"
            "_o = bpy.data.objects.get({armature!r})\n"
            "result = _std.validate_rig(_o)\n"
        ).format(armature=armature)
        return send_code(code, strict_json=False)
