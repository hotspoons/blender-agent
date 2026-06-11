# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
rig_biped_rigify: one symmetric, standing humanoid mesh -> full Rigify
control rig (IK/FK limbs, spine, fingers-free basic body) with bone-heat
automatic weights. Wraps Blender's own machinery — never reimplements it.

Triggers: humanoid characters (two arms, two legs, upright).
Anti-triggers: four-legged characters (rig_quadruped_rigify), mechanical
assemblies (rig_rigid_assembly), single props.

params:
- ``name``: rig object name, default "Rig.Biped".
- ``metarig``: "human" (full, default) or "basic_human" (lighter).
- ``keep_metarig``: keep the fitted metarig for manual tweaks (default False).
- ``ignore_symmetry`` / ``ignore_health``: override the gates.
"""

__all__ = (
    "diagnose",
    "run",
    "verify",
)

from . import _character

_SKILL = "rig_biped_rigify"

_POSE_PROBES = (
    ("upper_arm", "upper_arm_fk.L", "x", 50.0),
    ("upper_arm", "upper_arm_fk.R", "x", 50.0),
    ("thigh", "thigh_fk.L", "x", -45.0),
)


def diagnose(ctx: dict, params: dict | None = None) -> dict:
    return _character.character_diagnose(_SKILL, ctx, params)


def run(ctx: dict, params: dict | None = None) -> dict:
    params = dict(params or {})
    metarig = params.pop("metarig", "human")
    if metarig not in ("human", "basic_human"):
        from . import _contract
        return _contract.fail("bad_param", param="metarig",
                              detail="must be 'human' or 'basic_human'")
    return _character.character_run(_SKILL, metarig, "Rig.Biped", ctx, params)


def verify(ctx: dict) -> dict:
    return _character.character_verify(_SKILL, ctx, _POSE_PROBES)
