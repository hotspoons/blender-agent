# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Phase 4: rig_hinge end-to-end on corpus assets, including the garbage case.
"""

__all__ = ()

import bpy
import numpy as np

import corpus

from tests.bl_test_base import BlenderTestCase

from blrig.skills import rig_hinge


class TestHingeDiagnose(BlenderTestCase):

    def test_door_plan(self) -> None:
        manifest = corpus.build("door_and_frame")
        ctx = {"objects": manifest["objects"]}
        report = rig_hinge.diagnose(ctx)
        self.assertTrue(report["ok"], report)
        plan = report["plan"]
        truth = manifest["truth"]
        # Axis matches ground truth (sign-normalized).
        axis = np.asarray(plan["axis"])
        self.assertGreater(abs(float(axis @ np.asarray(truth["hinge_axis"]))), 0.99)
        self.assertEqual(plan["moving"], truth["moving"])
        self.assertAlmostEqual(plan["hinge_point"][0], truth["hinge_point_xy"][0], delta=0.05)
        self.assertAlmostEqual(plan["hinge_point"][1], truth["hinge_point_xy"][1], delta=0.05)

    def test_garbage_gated(self) -> None:
        manifest = corpus.build("door_and_frame_garbage")
        report = rig_hinge.diagnose({"objects": manifest["objects"]})
        self.assertFalse(report["ok"])
        self.assertEqual(report["fail"], "unhealthy_mesh")
        for issue in manifest["truth"]["health_issues"]:
            if report["object"] == "Door":
                self.assertIn(issue, report["issues"])
        self.assertIn("suggest", report)

    def test_no_contact(self) -> None:
        corpus.build("door_and_frame")
        bpy.data.objects["Door"].location.x += 5.0
        bpy.context.view_layer.update()
        report = rig_hinge.diagnose({"objects": ["Frame", "Door"]})
        self.assertFalse(report["ok"])
        self.assertEqual(report["fail"], "no_contact")
        self.assertIn("suggest", report)

    def test_missing_object(self) -> None:
        report = rig_hinge.diagnose({"objects": ["Nope", "AlsoNope"]})
        self.assertFalse(report["ok"])
        self.assertEqual(report["fail"], "object_not_found")

    def test_diagnose_does_not_mutate(self) -> None:
        manifest = corpus.build("door_and_frame")
        before = set(bpy.data.objects.keys())
        rig_hinge.diagnose({"objects": manifest["objects"]})
        self.assertEqual(set(bpy.data.objects.keys()), before)


class TestHingeRun(BlenderTestCase):

    def test_door_end_to_end(self) -> None:
        manifest = corpus.build("door_and_frame")
        ctx = {"objects": manifest["objects"]}
        result = rig_hinge.run(ctx)
        self.assertTrue(result["ok"], result)
        self.assertEqual(ctx["armature"], result["armature"])
        self.assertIn(result["armature"], bpy.data.objects)

        report = rig_hinge.verify(ctx)
        self.assertTrue(report["ok"], report["checks"])

    def test_ambiguous_contact_needs_hint(self) -> None:
        # Face-on-face stack: contact region is a square, axis ambiguous.
        manifest = corpus.build("crate_stack")
        ctx = {"objects": manifest["objects"][:2]}
        report = rig_hinge.run(ctx)
        self.assertFalse(report["ok"])
        self.assertEqual(report["fail"], "ambiguous_axis")

        result = rig_hinge.run(ctx, params={"axis_hint": "z"})
        self.assertTrue(result["ok"], result)
        self.assertTrue(rig_hinge.verify(ctx)["ok"])

    def test_explicit_moving_part(self) -> None:
        manifest = corpus.build("door_and_frame")
        ctx = {"objects": manifest["objects"]}
        result = rig_hinge.run(ctx, params={"moving": "Frame"})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["hinge"]["moving"], "Frame")

    def test_failed_run_rolls_back(self) -> None:
        corpus.build("door_and_frame")
        bpy.data.objects["Door"].location.x += 5.0
        bpy.context.view_layer.update()
        before = set(bpy.data.objects.keys())
        report = rig_hinge.run({"objects": ["Frame", "Door"]})
        self.assertFalse(report["ok"])
        self.assertEqual(set(bpy.data.objects.keys()), before)
        self.assertEqual(len(bpy.data.objects["Door"].modifiers), 0)

    def test_custom_limits(self) -> None:
        manifest = corpus.build("door_and_frame")
        ctx = {"objects": manifest["objects"]}
        result = rig_hinge.run(ctx, params={"min_angle_deg": 0.0, "max_angle_deg": 90.0})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["hinge"]["limits_deg"], [0.0, 90.0])
        self.assertTrue(rig_hinge.verify(ctx)["ok"])
