# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Rigging skills. Every module follows the same contract:

- ``diagnose(ctx) -> report``: pure precondition check; never mutates the
  scene. ``{"ok": False, "fail": <code>, "suggest": <skill>, ...}`` gives
  the agent something to act on.
- ``run(ctx, params=None) -> result``: the operation. Semantic params only
  (``hinge_axis_hint="z"``, never raw coordinates). Rolls back cleanly on
  failure — a failed chain must not corrupt the scene.
- ``verify(ctx) -> report``: postconditions, including ``validate_rig()``.

*ctx* is a JSON-friendly dict naming the targets, e.g.
``{"objects": ["Door", "Frame"]}``; ``run()`` adds ``"armature"``.
"""

__all__ = (
    "get_skill",
    "list_skills",
)

import importlib

# Skill name -> module path. Populated as skills land.
_SKILLS = {
    "rig_chain": "blrig.skills.rig_chain",
    "rig_hinge": "blrig.skills.rig_hinge",
    "rig_piston": "blrig.skills.rig_piston",
    "rig_wheel": "blrig.skills.rig_wheel",
    "rig_turret": "blrig.skills.rig_turret",
    "rig_rigid_assembly": "blrig.skills.rig_rigid_assembly",
    "rig_biped_rigify": "blrig.skills.rig_biped_rigify",
    "rig_biped_multipart": "blrig.skills.rig_biped_multipart",
    "rig_quadruped_rigify": "blrig.skills.rig_quadruped_rigify",
}


def list_skills() -> list[str]:
    return sorted(_SKILLS)


def get_skill(name: str):
    """
    Import and return the skill module for *name* (KeyError if unknown).
    """
    return importlib.import_module(_SKILLS[name])
