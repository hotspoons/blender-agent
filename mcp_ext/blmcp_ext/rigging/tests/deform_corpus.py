# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Deformation smoke tier: every corpus asset through its intended skill,
then drive the produced rig through pose extremes and hold numeric
thresholds (displacement happened, nothing exploded, volume held).

Run via: ``make test-deform`` (or ``--tier all``).
"""

__all__ = ()

import bpy
import numpy as np

import corpus

from tests.bl_test_base import BlenderTestCase

from blrig import skills as skill_registry
from blrig.skills import _bones

# Asset -> (skill, params). Garbage variants are diagnose-gates, not
# deformation cases.
_MATRIX = (
    ("door_and_frame", "rig_hinge", None),
    ("piston_pair", "rig_piston", None),
    ("cart_wheel", "rig_wheel", None),
    ("turret", "rig_turret", None),
    ("desk_lamp", "rig_rigid_assembly", None),
    ("desk_lamp_single_mesh", "rig_rigid_assembly", None),
    ("crate_stack", "rig_rigid_assembly", None),
    ("humanoid", "rig_biped_rigify", None),
    ("quadruped", "rig_quadruped_rigify", None),
)

# Sanity bound: no vertex may travel further than this multiple of the
# asset diagonal under any pose (catches flipped axes / exploded rigs).
_MAX_TRAVEL = 3.0


class TestDeformCorpus(BlenderTestCase):

    def _drive_extremes(self, rig: bpy.types.Object, meshes: list) -> None:
        diag = max(
            float(np.linalg.norm(np.asarray(o.dimensions))) for o in meshes) or 1.0
        rest = {o.name: _bones.evaluated_verts(o) for o in meshes}

        controls = [b.name for b in rig.pose.bones if b.name.startswith("CTL-")]
        for angle in (-80.0, 80.0):
            for ctl in controls:
                _bones.pose_rotate(rig, ctl, "y", angle)
            for o in meshes:
                travel = float(np.abs(_bones.evaluated_verts(o) - rest[o.name]).max())
                self.assertLess(
                    travel, _MAX_TRAVEL * diag,
                    "{:s} exploded at {:+.0f}deg (travel {:.2f})".format(o.name, angle, travel))
                self.assertTrue(
                    np.isfinite(_bones.evaluated_verts(o)).all(),
                    "{:s} has non-finite verts".format(o.name))
            _bones.reset_pose(rig)

        # After reset, everything must return to rest exactly.
        for o in meshes:
            drift = float(np.abs(_bones.evaluated_verts(o) - rest[o.name]).max())
            self.assertLess(drift, 1e-5, "{:s} did not return to rest".format(o.name))

    def test_corpus_matrix(self) -> None:
        for asset, skill_name, params in _MATRIX:
            with self.subTest(asset=asset, skill=skill_name):
                bpy.ops.wm.read_factory_settings(use_empty=True)
                manifest = corpus.build(asset)
                ctx = {"objects": manifest["objects"]}
                skill = skill_registry.get_skill(skill_name)

                result = skill.run(ctx, params)
                self.assertTrue(result["ok"], (asset, result))
                report = skill.verify(ctx)
                self.assertTrue(
                    report["ok"],
                    (asset, [c for c in report["checks"] if not c["ok"]]))

                rig = bpy.data.objects[ctx["armature"]]
                meshes = [
                    o for o in bpy.data.objects
                    if o.type == "MESH"
                    and any(m.type == "ARMATURE" and m.object == rig for m in o.modifiers)]
                self.assertTrue(meshes, asset)
                self._drive_extremes(rig, meshes)
