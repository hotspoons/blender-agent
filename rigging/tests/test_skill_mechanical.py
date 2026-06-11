# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Phase 4: rig_wheel, rig_piston, rig_turret, rig_rigid_assembly on the
corpus, including garbage-topology gating and rollback.
"""

__all__ = ()

import bpy
import numpy as np

import corpus

from tests.bl_test_base import BlenderTestCase

from blrig.skills import rig_piston, rig_rigid_assembly, rig_turret, rig_wheel


class TestWheel(BlenderTestCase):

    def test_diagnose_axis(self) -> None:
        manifest = corpus.build("cart_wheel")
        report = rig_wheel.diagnose({"objects": manifest["objects"]})
        self.assertTrue(report["ok"], report)
        axis = np.asarray(report["plan"]["axis"])
        truth = np.asarray(manifest["truth"]["axis"])
        self.assertGreater(abs(float(axis @ truth)), 0.99)
        self.assertAlmostEqual(report["plan"]["radius"], manifest["truth"]["radius"], delta=0.01)

    def test_scaled_wheel_gated(self) -> None:
        manifest = corpus.build("cart_wheel_scaled")
        report = rig_wheel.diagnose({"objects": manifest["objects"]})
        self.assertFalse(report["ok"])
        self.assertEqual(report["fail"], "unhealthy_mesh")
        self.assertIn("unapplied_scale", report["issues"])

    def test_cube_rejected(self) -> None:
        from tests import fixtures
        fixtures.make_cube("Block")
        report = rig_wheel.diagnose({"objects": ["Block"]})
        self.assertFalse(report["ok"])
        self.assertEqual(report["fail"], "not_a_wheel")
        self.assertIn("suggest", report)

    def test_end_to_end(self) -> None:
        manifest = corpus.build("cart_wheel")
        ctx = {"objects": manifest["objects"]}
        result = rig_wheel.run(ctx)
        self.assertTrue(result["ok"], result)
        report = rig_wheel.verify(ctx)
        self.assertTrue(report["ok"], report["checks"])


class TestPiston(BlenderTestCase):

    def test_diagnose_anchors(self) -> None:
        manifest = corpus.build("piston_pair")
        report = rig_piston.diagnose({"objects": manifest["objects"]})
        self.assertTrue(report["ok"], report)
        plan = report["plan"]
        # Outer ends: sleeve's at x=-1, rod's at x=+1.15.
        self.assertLess(plan["anchor_a"][0], -0.9)
        self.assertGreater(plan["anchor_b"][0], 1.0)
        self.assertGreater(plan["alignment"], 0.99)

    def test_perpendicular_rejected(self) -> None:
        from tests import fixtures
        fixtures.make_cylinder("RodA", radius=0.1, depth=1.5, axis="x")
        fixtures.make_cylinder("RodB", radius=0.1, depth=1.5, axis="z", location=(1.0, 0, 0))
        bpy.context.view_layer.update()
        report = rig_piston.diagnose({"objects": ["RodA", "RodB"]})
        self.assertFalse(report["ok"])
        self.assertEqual(report["fail"], "not_coaxial")

    def test_blob_rejected(self) -> None:
        from tests import fixtures
        fixtures.make_cube("BlobA")
        fixtures.make_cube("BlobB", location=(2.2, 0, 0))
        bpy.context.view_layer.update()
        report = rig_piston.diagnose({"objects": ["BlobA", "BlobB"]})
        self.assertFalse(report["ok"])
        self.assertEqual(report["fail"], "not_elongated")

    def test_end_to_end(self) -> None:
        manifest = corpus.build("piston_pair")
        ctx = {"objects": manifest["objects"]}
        result = rig_piston.run(ctx)
        self.assertTrue(result["ok"], result)
        report = rig_piston.verify(ctx)
        self.assertTrue(report["ok"], report["checks"])


class TestTurret(BlenderTestCase):

    def test_diagnose_axes(self) -> None:
        manifest = corpus.build("turret")
        report = rig_turret.diagnose({"objects": manifest["objects"]})
        self.assertTrue(report["ok"], report)
        plan = report["plan"]
        truth = manifest["truth"]
        self.assertGreater(abs(float(
            np.asarray(plan["yaw_axis"]) @ np.asarray(truth["yaw_axis"]))), 0.99)
        self.assertGreater(abs(float(
            np.asarray(plan["pitch_axis"]) @ np.asarray(truth["pitch_axis"]))), 0.95)
        self.assertAlmostEqual(plan["yaw_point"][0], truth["yaw_point_xy"][0], delta=0.05)
        self.assertAlmostEqual(plan["yaw_point"][1], truth["yaw_point_xy"][1], delta=0.05)

    def test_broken_chain(self) -> None:
        manifest = corpus.build("turret")
        bpy.data.objects["Barrel"].location.z += 3.0
        bpy.context.view_layer.update()
        report = rig_turret.diagnose({"objects": manifest["objects"]})
        self.assertFalse(report["ok"])
        self.assertEqual(report["fail"], "no_chain")

    def test_end_to_end(self) -> None:
        manifest = corpus.build("turret")
        ctx = {"objects": manifest["objects"]}
        result = rig_turret.run(ctx, params={"pitch_limits_deg": [-10.0, 60.0]})
        self.assertTrue(result["ok"], result)
        report = rig_turret.verify(ctx)
        self.assertTrue(report["ok"], report["checks"])

    def test_failed_run_rolls_back(self) -> None:
        manifest = corpus.build("turret")
        bpy.data.objects["Barrel"].location.z += 3.0
        bpy.context.view_layer.update()
        before = set(bpy.data.objects.keys())
        report = rig_turret.run({"objects": manifest["objects"]})
        self.assertFalse(report["ok"])
        self.assertEqual(set(bpy.data.objects.keys()), before)


class TestRigidAssembly(BlenderTestCase):

    def test_lamp_objects(self) -> None:
        manifest = corpus.build("desk_lamp")
        ctx = {"objects": manifest["objects"]}
        report = rig_rigid_assembly.diagnose(ctx)
        self.assertTrue(report["ok"], report)
        plan = report["plan"]
        self.assertEqual(len(plan["parts"]), manifest["truth"]["n_parts"])
        self.assertEqual(plan["root_part"], manifest["truth"]["root_part"])
        # A chain: every non-root part has a joint, nothing floats.
        self.assertEqual(len(plan["joints"]), 3)
        self.assertEqual(plan["floating"], [])

        result = rig_rigid_assembly.run(ctx)
        self.assertTrue(result["ok"], result)
        verify_report = rig_rigid_assembly.verify(ctx)
        self.assertTrue(verify_report["ok"], verify_report["checks"])

    def test_lamp_single_mesh(self) -> None:
        manifest = corpus.build("desk_lamp_single_mesh")
        ctx = {"objects": manifest["objects"]}
        result = rig_rigid_assembly.run(ctx)
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(result["assembly"]["joints"]), 3)
        verify_report = rig_rigid_assembly.verify(ctx)
        self.assertTrue(verify_report["ok"], verify_report["checks"])

    def test_disconnected_floats(self) -> None:
        manifest = corpus.build("crate_stack")
        ctx = {"objects": manifest["objects"]}
        result = rig_rigid_assembly.run(ctx)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["assembly"]["floating"], ["CrateC"])
        self.assertEqual(result["assembly"]["n_components"], 2)
        self.assertTrue(rig_rigid_assembly.verify(ctx)["ok"])

    def test_single_part_rejected(self) -> None:
        from tests import fixtures
        fixtures.make_cube("Solo")
        report = rig_rigid_assembly.diagnose({"objects": ["Solo"]})
        self.assertFalse(report["ok"])
        self.assertEqual(report["fail"], "single_part")
        self.assertIn("suggest", report)

    def test_pose_moves_subtree_not_root(self) -> None:
        from blrig.skills import _bones
        manifest = corpus.build("desk_lamp")
        ctx = {"objects": manifest["objects"]}
        rig_rigid_assembly.run(ctx)
        rig = bpy.data.objects[ctx["armature"]]
        base = bpy.data.objects["LampBase"]
        head = bpy.data.objects["Head"]

        before_base = _bones.evaluated_verts(base)
        before_head = _bones.evaluated_verts(head)
        _bones.pose_rotate(rig, "CTL-ArmLower", "y", 25.0)
        self.assertGreater(
            float(np.abs(_bones.evaluated_verts(head) - before_head).max()), 0.05)
        self.assertLess(
            float(np.abs(_bones.evaluated_verts(base) - before_base).max()), 1e-6)
        _bones.reset_pose(rig)
