# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
rig_quadruped_rigify: one symmetric four-legged mesh -> Rigify quadruped
control rig with bone-heat automatic weights.

Triggers: four-legged characters (dogs, horses, generic creatures).
Anti-triggers: humanoids (rig_biped_rigify), mechanical assemblies
(rig_rigid_assembly).

params:
- ``name``: rig object name, default "Rig.Quadruped".
- ``keep_metarig``: keep the fitted metarig (default False).
- ``ignore_symmetry`` / ``ignore_health``: override the gates.
"""

__all__ = (
    "diagnose",
    "run",
    "verify",
)

from . import _character

_SKILL = "rig_quadruped_rigify"

_POSE_PROBES = (
    ("front_thigh", "front_thigh_fk.L", "x", 40.0),
    ("thigh", "thigh_fk.L", "x", -40.0),
)


def diagnose(ctx: dict, params: dict | None = None) -> dict:
    return _character.character_diagnose(_SKILL, ctx, params)


def run(ctx: dict, params: dict | None = None) -> dict:
    return _character.character_run(_SKILL, "quadruped", "Rig.Quadruped", ctx, params)


def verify(ctx: dict) -> dict:
    return _character.character_verify(_SKILL, ctx, _POSE_PROBES)
