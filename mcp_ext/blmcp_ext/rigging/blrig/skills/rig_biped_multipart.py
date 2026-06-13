# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
rig_biped_multipart: a humanoid modeled as MULTIPLE meshes / shell piles
(non-manifold, hundreds of loose parts, asymmetric attachments) -> full
Rigify control rig with weights transferred onto every original part.

The visible meshes are never repaired or modified — a disposable fused
weight proxy (see ``_proxy``) absorbs the voxel remeshing, fattening and
mirror-union, gets rigged and bone-heat-bound by ``rig_biped_rigify``,
and donates its validated weights back to the originals before being
deleted.

Triggers: humanoid characters split across several objects; single-object
characters whose mesh is a pile of overlapping shells (bone_heat_failed
from rig_biped_rigify); characters with one-sided appendages that skew
the symmetric fit.
Anti-triggers: one clean symmetric watertight mesh (rig_biped_rigify
directly), mechanical assemblies (rig_rigid_assembly).

params:
- ``name``: rig object name, default "Rig.Biped".
- ``metarig``: "human" (default) or "basic_human".
- ``keep_metarig``: keep the fitted metarig for joint tweaks +
  regeneration (default False).
- ``symmetrize``: union the proxy with its own X-mirror across the
  character midline (default True). Disable only for genuinely
  symmetric multi-part characters; the inner symmetry gate then applies.
- ``voxel_size``: proxy remesh voxel, default height/150.
- ``center_x``: midline override; default is the largest cluster of
  per-part bbox-center x values (NOT the combined bbox center, which a
  single long one-sided appendage drags off the body).
- ``side_margin``: midline dead-zone half-width for cross-side leg
  weight cleanup, default 2x voxel_size.
- ``ignore_health``: override the per-part fatal-health gate.

Failure codes: ``proxy_not_fused`` (shells would not fuse into one
island), ``transfer_failed`` (an original ended up with unweighted
verts), plus everything ``rig_biped_rigify`` can return
(``bone_heat_failed``, ``unhealthy_mesh``, ...).
"""

__all__ = (
    "diagnose",
    "run",
    "verify",
)

from . import _character
from . import _organic

_SKILL = "rig_biped_multipart"

_POSE_PROBES = (
    ("upper_arm", "upper_arm_fk.L", "x", 50.0),
    ("upper_arm", "upper_arm_fk.R", "x", 50.0),
    ("thigh", "thigh_fk.L", "x", -45.0),
)


def diagnose(ctx: dict, params: dict | None = None) -> dict:
    return _organic.diagnose(_SKILL, ctx, params)


def run(ctx: dict, params: dict | None = None) -> dict:
    # The shared organic path fuses the shells, fits the HUMAN metarig,
    # bone-heat-binds the proxy, and transfers weights back to originals.
    return _organic.run(_SKILL, "human", "Rig.Biped", ctx, params)


def verify(ctx: dict) -> dict:
    return _character.character_verify(_SKILL, ctx, _POSE_PROBES)
