# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
blrig public SDK — the STABLE surface agent-authored tools may build on.

When an agent authors a tool, ``blrig`` is on the import allowlist (the
rigging extension registers it as an SDK), so a single jailed tool can
compose the rigging framework instead of reinventing it::

    from blrig import api
    insp = api.inspect(["Body", "Leg.001", ...])      # perception-backed routing
    res  = api.run("rig_chain", ["Tail1", "Tail2"], {"armature": "Rig.Dragon"})
    api.run("rig_rigid_assembly", parts, {"bridge_gaps": True})
    result = {"armature": res["armature"]}

Prefer this module over reaching into ``blrig`` internals (``blrig.skills``,
``blrig._contract``, ...) — those are not part of the SDK contract and may
change. Everything here runs INSIDE Blender (it touches ``bpy``).
"""

__all__ = (
    "diagnose",
    "inspect",
    "list_skills",
    "ok",
    "perception",
    "run",
    "verify",
)

from . import perception
from .skills import _contract, get_skill, list_skills

# Structured result helpers, re-exported so authored tools return reports in
# the same shape the core skills do.
ok = _contract.ok
fail = _contract.fail
check = _contract.check


def _skill_or_raise(name: str):
    skill = get_skill(name)
    if skill is None:
        raise ValueError("unknown rig skill {!r}; see api.list_skills()".format(name))
    return skill


def inspect(objects, detail: bool = False) -> dict:
    """Read-only scene inspection + ranked skill suggestions (the `rig inspect`)."""
    from .skills import inspect_scene
    return inspect_scene.inspect(list(objects), detail=detail)


def diagnose(skill: str, objects, params: dict | None = None) -> dict:
    """Dry-run a skill: returns its plan or a structured failure code."""
    return _skill_or_raise(skill).diagnose(
        {"objects": list(objects)}, params or {})


def run(skill: str, objects, params: dict | None = None) -> dict:
    """
    Build a rig with *skill* over *objects*; rolls back on failure. Compose
    several (pass an existing ``armature`` in params) to assemble bigger rigs.
    """
    return _skill_or_raise(skill).run({"objects": list(objects)}, params or {})


def verify(skill: str, armature: str) -> dict:
    """Verify a built rig (pose-extreme checks). REQUIRED before claiming success."""
    return _skill_or_raise(skill).verify({"armature": armature})
