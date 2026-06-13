# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
rig_quadruped_multipart: a four-legged creature modeled as MULTIPLE
meshes / shell piles (body, legs, head as separate overlapping
primitives, non-manifold) -> full Rigify quadruped control rig with
weights transferred onto every original part.

The organic counterpart to rig_rigid_assembly for animals: assembly with
bridge_gaps gives a MECHANICAL rig (rigid parts + ball joints), this gives
smooth bone-heat DEFORMATION. Shares the disposable fused weight proxy
with rig_biped_multipart (see ``_organic`` / ``_proxy``) - only the target
Rigify metarig differs.

Triggers: four-legged characters (dogs/horses/etc.) built from several
objects or a pile of overlapping shells; a quadruped mesh that fails
rig_quadruped_rigify with bone_heat_failed.
Anti-triggers: one clean symmetric quadruped mesh (rig_quadruped_rigify
directly); humanoids (rig_biped_multipart); genuinely rigid mechanical
assemblies you want jointed, not deformed (rig_rigid_assembly + bridge_gaps).

params:
- ``name``: rig object name, default "Rig.Quadruped".
- ``keep_metarig``: keep the fitted metarig (default False).
- ``symmetrize``: union the proxy with its X-mirror across the midline
  (default True). Disable only for genuinely symmetric multi-part inputs.
- ``voxel_size``: proxy remesh voxel, default height/150.
- ``center_x``: midline override; default is the largest cluster of
  per-part bbox-center x (resists one heavy one-sided part).
- ``side_margin``: midline dead-zone half-width for cross-side leg-weight
  cleanup (front AND hind legs), default 2x voxel_size.
- ``ignore_health``: override the per-part fatal-health gate.

Failure codes: ``proxy_not_fused``, ``transfer_failed``, plus everything
``rig_quadruped_rigify`` can return (``bone_heat_failed``, ...).
"""

__all__ = (
    "diagnose",
    "run",
    "verify",
)

from . import _character
from . import _organic

_SKILL = "rig_quadruped_multipart"

_POSE_PROBES = (
    ("front_thigh", "front_thigh_fk.L", "x", 40.0),
    ("thigh", "thigh_fk.L", "x", -40.0),
)


def diagnose(ctx: dict, params: dict | None = None) -> dict:
    return _organic.diagnose(_SKILL, ctx, params)


def run(ctx: dict, params: dict | None = None) -> dict:
    # Same shared organic path as the biped, fitting the QUADRUPED metarig.
    return _organic.run(_SKILL, "quadruped", "Rig.Quadruped", ctx, params)


def verify(ctx: dict) -> dict:
    return _character.character_verify(_SKILL, ctx, _POSE_PROBES)
