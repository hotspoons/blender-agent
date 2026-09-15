# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Phase 5: Rigify-wrapping character skills on the procedural character
corpus. These are the slowest tests in the property tier (Rigify generation
+ bone-heat each take a second or two).
"""

__all__ = ()

import bpy

import corpus

from tests.bl_test_base import BlenderTestCase

from blrig.skills import _rigify, rig_biped_rigify, rig_quadruped_rigify


class TestFitMetarig(BlenderTestCase):
    """fit_metarig must land the bone cloud exactly inside the target bounds.

    Regression: the fit read and wrote head/tail in one interleaved pass. A connected bone's head
    IS its parent's tail, so writing the child moved the parent's tail, and the parent's own write
    then transformed that already-transformed value — f(f(x)) instead of f(x). A 1.98m metarig
    fitted to a 1.7m target came out spanning 2.41m with its feet 0.7m below the floor.

    It failed silently: the rig still generated and bone-heat still bound, so it read as Rigify
    placing joints badly rather than as a bug.
    """

    def _fit(self, kind, target_min, target_max):
        meta = _rigify.add_metarig(kind, name="metarig")
        _rigify.fit_metarig(meta, target_min, target_max, center_x=0.0)
        return _rigify.metarig_bounds(meta)

    def test_spans_target_height_exactly(self) -> None:
        target_min, target_max = [-0.5, -0.2, 0.0], [0.5, 0.2, 1.7]
        lo, hi = self._fit("human", target_min, target_max)
        self.assertAlmostEqual(float(lo[2]), target_min[2], places=3)
        self.assertAlmostEqual(float(hi[2]), target_max[2], places=3)

    def test_no_bone_below_the_floor(self) -> None:
        target_min, target_max = [-0.5, -0.2, 0.0], [0.5, 0.2, 1.7]
        lo, _hi = self._fit("human", target_min, target_max)
        self.assertGreaterEqual(float(lo[2]), target_min[2] - 1e-3)

    def test_offset_target_is_not_doubled(self) -> None:
        # Feet below the origin is the case that exposed it: a mesh centred on its own origin,
        # which is what a reconstruction arrives as.
        target_min, target_max = [-0.5, -0.2, -0.85], [0.5, 0.2, 0.85]
        lo, hi = self._fit("human", target_min, target_max)
        self.assertAlmostEqual(float(hi[2] - lo[2]), 1.7, places=3)
        self.assertAlmostEqual(float(lo[2]), -0.85, places=3)

    def test_basic_human_too(self) -> None:
        target_min, target_max = [-0.5, -0.2, 0.0], [0.5, 0.2, 1.6]
        lo, hi = self._fit("basic_human", target_min, target_max)
        self.assertAlmostEqual(float(hi[2] - lo[2]), 1.6, places=3)


class TestBipedDiagnose(BlenderTestCase):

    def test_humanoid_ok(self) -> None:
        manifest = corpus.build("humanoid")
        report = rig_biped_rigify.diagnose({"objects": manifest["objects"]})
        self.assertTrue(report["ok"], report)
        self.assertGreater(report["plan"]["height"], 1.0)
        self.assertLess(abs(report["plan"]["center_x"]), 0.05)

    def test_asymmetric_gated(self) -> None:
        manifest = corpus.build("humanoid_asymmetric")
        report = rig_biped_rigify.diagnose({"objects": manifest["objects"]})
        self.assertFalse(report["ok"])
        self.assertEqual(report["fail"], "asymmetric")
        self.assertIn("suggest", report)

    def test_scaled_gated(self) -> None:
        manifest = corpus.build("humanoid")
        bpy.data.objects[manifest["objects"][0]].scale = (1.1, 1.0, 1.0)
        bpy.context.view_layer.update()
        report = rig_biped_rigify.diagnose({"objects": manifest["objects"]})
        self.assertFalse(report["ok"])
        self.assertEqual(report["fail"], "unhealthy_mesh")


class TestBipedEndToEnd(BlenderTestCase):

    def test_humanoid_full_pipeline(self) -> None:
        manifest = corpus.build("humanoid")
        ctx = {"objects": manifest["objects"]}
        result = rig_biped_rigify.run(ctx)
        self.assertTrue(result["ok"], result)
        self.assertGreater(result["character"]["n_deform"], 50)
        self.assertNotIn("META-" + result["armature"], bpy.data.objects)

        report = rig_biped_rigify.verify(ctx)
        self.assertTrue(report["ok"], [c for c in report["checks"] if not c["ok"]])

    def test_failed_diagnose_means_no_rig(self) -> None:
        manifest = corpus.build("humanoid_asymmetric")
        before = set(bpy.data.objects.keys())
        report = rig_biped_rigify.run({"objects": manifest["objects"]})
        self.assertFalse(report["ok"])
        self.assertEqual(set(bpy.data.objects.keys()), before)


class TestQuadrupedEndToEnd(BlenderTestCase):

    def test_quadruped_full_pipeline(self) -> None:
        manifest = corpus.build("quadruped")
        ctx = {"objects": manifest["objects"]}
        result = rig_quadruped_rigify.run(ctx)
        self.assertTrue(result["ok"], result)
        report = rig_quadruped_rigify.verify(ctx)
        self.assertTrue(report["ok"], [c for c in report["checks"] if not c["ok"]])
