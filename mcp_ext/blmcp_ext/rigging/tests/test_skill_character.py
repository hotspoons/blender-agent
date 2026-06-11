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

from blrig.skills import rig_biped_rigify, rig_quadruped_rigify


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
