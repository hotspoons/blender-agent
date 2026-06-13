# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
pose(verb) ops: batch set with rotation-mode handling, get round-trip,
paste-flipped mirroring, subset reset, named poses, failure rollback —
plus Rigify IK/FK switch + snap on a generated biped (slow, like the
other Rigify end-to-end tests in this tier).
"""

__all__ = ()

import math

import bpy

import corpus

from tests.bl_test_base import BlenderTestCase
from tests import fixtures

from blrig.skills import pose_ops, rig_biped_rigify


class TestSetGet(BlenderTestCase):

    def test_glob_batch_set_and_get(self) -> None:
        rig = fixtures.make_sided_rig(deform=False)
        report = pose_ops.dispatch("set", {
            "armature": rig.name,
            "bones": {"arm.*": {"rotation_deg": [30.0, 0.0, 0.0]}}})
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["n_bones"], 2)

        read = pose_ops.dispatch("get", {"armature": rig.name})
        self.assertTrue(read["ok"])
        self.assertEqual(sorted(read["bones"]), ["arm.L", "arm.R"])
        self.assertAlmostEqual(
            read["bones"]["arm.L"]["rotation_deg"][0], 30.0, places=3)

    def test_quaternion_mode_respected(self) -> None:
        rig = fixtures.make_sided_rig(deform=False)
        pb = rig.pose.bones["arm.L"]
        pb.rotation_mode = "QUATERNION"
        report = pose_ops.dispatch("set", {
            "armature": rig.name,
            "bones": {"arm.L": {"rotation_deg": [0.0, 0.0, 45.0]}}})
        self.assertTrue(report["ok"], report)
        # The value landed in the quaternion, not the dead euler channel.
        pb = rig.pose.bones["arm.L"]
        self.assertEqual(pb.rotation_mode, "QUATERNION")
        angle = math.degrees(pb.rotation_quaternion.angle)
        self.assertAlmostEqual(angle, 45.0, places=3)

    def test_additive(self) -> None:
        rig = fixtures.make_sided_rig(deform=False)
        for _ in range(2):
            report = pose_ops.dispatch("set", {
                "armature": rig.name, "additive": True,
                "bones": {"arm.L": {"rotation_deg": [10.0, 0.0, 0.0]}}})
            self.assertTrue(report["ok"], report)
        self.assertAlmostEqual(
            math.degrees(rig.pose.bones["arm.L"].rotation_euler.x), 20.0,
            places=3)

    def test_failure_restores_pose(self) -> None:
        rig = fixtures.make_sided_rig(deform=False)
        pose_ops.dispatch("set", {
            "armature": rig.name,
            "bones": {"arm.L": {"rotation_deg": [15.0, 0.0, 0.0]}}})
        report = pose_ops.dispatch("set", {
            "armature": rig.name,
            "bones": {"arm.R": {"rotation_deg": [99.0, 0.0, 0.0]},
                      "zzz_nope*": {"rotation_deg": [1.0, 0.0, 0.0]}}})
        self.assertFalse(report["ok"])
        self.assertEqual(report["fail"], "no_bones_matched")
        # The partial write to arm.R was rolled back; arm.L untouched.
        self.assertAlmostEqual(
            math.degrees(rig.pose.bones["arm.R"].rotation_euler.x), 0.0,
            places=5)
        self.assertAlmostEqual(
            math.degrees(rig.pose.bones["arm.L"].rotation_euler.x), 15.0,
            places=3)


class TestMirrorResetNamed(BlenderTestCase):

    def test_mirror_flips_channels(self) -> None:
        rig = fixtures.make_sided_rig(deform=False)
        pose_ops.dispatch("set", {
            "armature": rig.name,
            "bones": {"arm.L": {"rotation_deg": [10.0, 20.0, 30.0],
                                "location": [0.1, 0.2, 0.3]}}})
        report = pose_ops.dispatch(
            "mirror", {"armature": rig.name, "from_side": "L"})
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["mirrored"], ["arm.R"])

        twin = rig.pose.bones["arm.R"]
        eul = [math.degrees(v) for v in twin.rotation_euler]
        self.assertAlmostEqual(eul[0], 10.0, places=3)
        self.assertAlmostEqual(eul[1], -20.0, places=3)
        self.assertAlmostEqual(eul[2], -30.0, places=3)
        self.assertAlmostEqual(twin.location.x, -0.1, places=5)
        self.assertAlmostEqual(twin.location.y, 0.2, places=5)

    def test_reset_subset(self) -> None:
        rig = fixtures.make_sided_rig(deform=False)
        pose_ops.dispatch("set", {
            "armature": rig.name,
            "bones": {"arm.*": {"rotation_deg": [25.0, 0.0, 0.0]}}})
        report = pose_ops.dispatch(
            "reset", {"armature": rig.name, "bones": ["arm.L"]})
        self.assertTrue(report["ok"], report)
        self.assertAlmostEqual(rig.pose.bones["arm.L"].rotation_euler.x, 0.0)
        self.assertAlmostEqual(
            math.degrees(rig.pose.bones["arm.R"].rotation_euler.x), 25.0,
            places=3)

    def test_named_pose_round_trip(self) -> None:
        rig = fixtures.make_sided_rig(deform=False)
        pose_ops.dispatch("set", {
            "armature": rig.name,
            "bones": {"arm.L": {"rotation_deg": [33.0, 0.0, 0.0]}}})
        saved = pose_ops.dispatch(
            "save_named", {"armature": rig.name, "name": "wave"})
        self.assertTrue(saved["ok"], saved)

        pose_ops.dispatch("reset", {"armature": rig.name})
        self.assertAlmostEqual(rig.pose.bones["arm.L"].rotation_euler.x, 0.0)

        applied = pose_ops.dispatch(
            "apply_named", {"armature": rig.name, "name": "wave"})
        self.assertTrue(applied["ok"], applied)
        self.assertAlmostEqual(
            math.degrees(rig.pose.bones["arm.L"].rotation_euler.x), 33.0,
            places=3)

        listing = pose_ops.dispatch("list_named", {"armature": rig.name})
        self.assertIn("wave", listing["poses"])

    def test_apply_unknown_pose(self) -> None:
        rig = fixtures.make_sided_rig(deform=False)
        report = pose_ops.dispatch(
            "apply_named", {"armature": rig.name, "name": "ghost"})
        self.assertFalse(report["ok"])
        self.assertEqual(report["fail"], "pose_not_found")


class TestEditModeGuard(BlenderTestCase):

    def test_set_works_from_edit_mode(self) -> None:
        rig = fixtures.make_sided_rig(deform=False)
        bpy.context.view_layer.objects.active = rig
        bpy.ops.object.mode_set(mode="EDIT")
        report = pose_ops.dispatch("set", {
            "armature": rig.name,
            "bones": {"arm.L": {"rotation_deg": [30.0, 0.0, 0.0]}}})
        self.assertTrue(report["ok"], report)
        self.assertEqual(rig.mode, "OBJECT")
        # The pose actually evaluates (the EDIT-mode freeze bug).
        pb = rig.pose.bones["arm.L"]
        self.assertGreater(
            (pb.matrix.to_quaternion().angle), 1e-3)


class TestIkFkRigify(BlenderTestCase):

    def test_switch_and_snap_round_trip(self) -> None:
        manifest = corpus.build("humanoid")
        ctx = {"objects": manifest["objects"]}
        result = rig_biped_rigify.run(ctx)
        self.assertTrue(result["ok"], result)
        rig = bpy.data.objects[ctx["armature"]]

        state = pose_ops.dispatch("get", {"armature": rig.name})
        self.assertIn("ik_fk", state)
        self.assertTrue(any(h.startswith("upper_arm_parent")
                            for h in state["ik_fk"]))

        # Pose the arm in IK, then switch to FK with snapping: the hand
        # must not jump.
        pose_ops.dispatch("set", {
            "armature": rig.name,
            "bones": {"hand_ik.L": {"location": [0.05, -0.15, 0.1]}}})
        report = pose_ops.dispatch("ik_fk", {
            "armature": rig.name, "to": "fk",
            "limbs": ["upper_arm_parent.L"], "snap": True})
        self.assertTrue(report["ok"], report)
        limb = report["limbs"]["upper_arm_parent.L"]
        self.assertTrue(limb["switched"])
        self.assertTrue(limb["snapped"])
        self.assertTrue(limb["snap_drift_ok"], limb)
        self.assertEqual(float(rig.pose.bones["upper_arm_parent.L"]["IK_FK"]), 1.0)

        # And back to IK.
        report = pose_ops.dispatch("ik_fk", {
            "armature": rig.name, "to": "ik",
            "limbs": ["upper_arm_parent.L"], "snap": True})
        self.assertTrue(report["ok"], report)
        self.assertEqual(float(rig.pose.bones["upper_arm_parent.L"]["IK_FK"]), 0.0)

    def test_no_ik_fk_on_plain_rig(self) -> None:
        rig = fixtures.make_sided_rig(deform=False)
        report = pose_ops.dispatch(
            "ik_fk", {"armature": rig.name, "to": "fk"})
        self.assertFalse(report["ok"])
        self.assertEqual(report["fail"], "no_ik_fk_properties")
