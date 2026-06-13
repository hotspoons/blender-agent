# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
anim(verb) ops: bulk keyframing through the 5.x layered-Action API,
parametric cycle construction (seamless wrap, phase relationships),
loop fixing, visual-keying bake, action/NLA management.
"""

__all__ = ()

import math

import bpy

from tests.bl_test_base import BlenderTestCase
from tests import fixtures

from blrig.skills import anim_ops


def _bone_matrix(rig, bone, frame):
    bpy.context.scene.frame_set(frame)
    bpy.context.view_layer.update()
    return rig.pose.bones[bone].matrix.copy()


def _euler_x_deg(rig, bone, frame) -> float:
    bpy.context.scene.frame_set(frame)
    bpy.context.view_layer.update()
    return math.degrees(rig.pose.bones[bone].rotation_euler.x)


class TestKeyframe(BlenderTestCase):

    def test_bulk_insert_drives_bones(self) -> None:
        rig = fixtures.make_sided_rig(deform=False)
        report = anim_ops.dispatch("keyframe", {
            "armature": rig.name,
            "keys": [
                {"frame": 1, "bones": {"arm.*": {"rotation_deg": [0, 0, 0]}}},
                {"frame": 12, "bones": {"arm.*": {"rotation_deg": [40, 0, 0]}}},
            ]})
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["n_keys"], 4)
        self.assertGreater(report["n_fcurves"], 0)

        m1 = _bone_matrix(rig, "arm.L", 1)
        m12 = _bone_matrix(rig, "arm.L", 12)
        self.assertGreater(
            max(abs(a - b) for ra, rb in zip(m1, m12) for a, b in zip(ra, rb)),
            1e-4)

    def test_inspect_reads_layered_action(self) -> None:
        rig = fixtures.make_sided_rig(deform=False)
        anim_ops.dispatch("keyframe", {
            "armature": rig.name,
            "keys": [{"frame": 1, "bones": {"arm.L": {"location": [0, 0, 1]}}},
                     {"frame": 10, "bones": {"arm.L": {"location": [0, 0, 0]}}}]})
        report = anim_ops.dispatch("inspect", {"armature": rig.name})
        self.assertTrue(report["ok"], report)
        self.assertIsNotNone(report["action"])
        self.assertEqual(report["keyed_frame_range"], [1.0, 10.0])
        self.assertIn("arm.L", report["keyed_bones"])
        self.assertIn("location", report["keyed_bones"]["arm.L"])

    def test_no_bones_matched_rolls_back(self) -> None:
        rig = fixtures.make_sided_rig(deform=False)
        report = anim_ops.dispatch("keyframe", {
            "armature": rig.name,
            "keys": [{"frame": 1, "bones": {"ghost*": {"location": [0, 0, 1]}}}]})
        self.assertFalse(report["ok"])
        self.assertEqual(report["fail"], "no_bones_matched")
        rig = bpy.data.objects["Rig"]
        self.assertTrue(rig.animation_data is None
                        or rig.animation_data.action is None)


class TestCycle(BlenderTestCase):

    def _swing_cycle(self, rig, frames=24, start=1):
        return anim_ops.dispatch("cycle", {
            "armature": rig.name, "frames": frames, "start": start,
            "channels": [
                {"bones": ["arm.L"], "axis": "x", "amplitude": 25.0,
                 "phase": 0.0},
                {"bones": ["arm.R"], "axis": "x", "amplitude": 25.0,
                 "phase": 0.5},
                {"bones": ["root"], "channel": "location", "axis": "z",
                 "amplitude": 0.05, "frequency": 2},
            ]})

    def test_seamless_and_phase_offset(self) -> None:
        rig = fixtures.make_sided_rig(deform=False)
        report = self._swing_cycle(rig)
        self.assertTrue(report["ok"], report)
        self.assertGreater(report["n_cyclic_fcurves"], 0)
        self.assertEqual(bpy.context.scene.frame_start, 1)
        self.assertEqual(bpy.context.scene.frame_end, 24)

        rig = bpy.data.objects["Rig"]
        # Seamless: the wrap frame (1 + 24) equals frame 1.
        m_first = _bone_matrix(rig, "arm.L", 1)
        m_wrap = _bone_matrix(rig, "arm.L", 25)
        self.assertLess(
            max(abs(a - b) for ra, rb in zip(m_first, m_wrap)
                for a, b in zip(ra, rb)), 1e-4)
        # Motion: quarter cycle differs from the start.
        self.assertAlmostEqual(_euler_x_deg(rig, "arm.L", 7), 25.0, delta=1.5)
        # Anti-phase legs-style relationship: R trails L by half a cycle.
        self.assertAlmostEqual(
            _euler_x_deg(rig, "arm.L", 7), _euler_x_deg(rig, "arm.R", 19),
            delta=1.5)
        self.assertAlmostEqual(
            _euler_x_deg(rig, "arm.L", 7), -_euler_x_deg(rig, "arm.R", 7),
            delta=1.5)
        # Root bob at frequency 2: peak twice per cycle.
        bpy.context.scene.frame_set(4)
        bpy.context.view_layer.update()
        z_quarter = rig.pose.bones["root"].location.z
        bpy.context.scene.frame_set(16)
        bpy.context.view_layer.update()
        z_three_quarter = rig.pose.bones["root"].location.z
        self.assertAlmostEqual(z_quarter, z_three_quarter, places=3)

    def test_phase_step_spreads_bones(self) -> None:
        rig = fixtures.make_sided_rig(deform=False)
        report = anim_ops.dispatch("cycle", {
            "armature": rig.name, "frames": 24,
            "channels": [{"bones": ["arm.L", "arm.R"], "axis": "x",
                          "amplitude": 20.0, "phase_step": 0.5}]})
        self.assertTrue(report["ok"], report)
        rig = bpy.data.objects["Rig"]
        self.assertAlmostEqual(
            _euler_x_deg(rig, "arm.L", 7), -_euler_x_deg(rig, "arm.R", 7),
            delta=1.5)

    def test_lenient_axis_forms(self) -> None:
        # Live agents pass "X" and bare indices — both must work.
        rig = fixtures.make_sided_rig(deform=False)
        report = anim_ops.dispatch("cycle", {
            "armature": rig.name, "frames": 12,
            "channels": [
                {"bones": ["arm.L"], "axis": "X", "amplitude": 10.0},
                {"bones": ["arm.R"], "axis": 2, "amplitude": 10.0},
                {"bones": ["root"], "channel": "location", "axis": "z",
                 "amplitude": 0.02, "frequency": 1.7},
            ]})
        self.assertTrue(report["ok"], report)
        channels = {c["bones"][0]: c for c in report["channels"]}
        self.assertEqual(channels["arm.L"]["axis_index"], 0)
        self.assertEqual(channels["arm.R"]["axis_index"], 2)
        self.assertEqual(channels["root"]["frequency"], 2)

    def test_zero_amplitude_rejected(self) -> None:
        rig = fixtures.make_sided_rig(deform=False)
        report = anim_ops.dispatch("cycle", {
            "armature": rig.name,
            "channels": [{"bones": ["arm.L"], "axis": "x", "amplitude": 0.0}]})
        self.assertFalse(report["ok"])
        self.assertEqual(report["fail"], "bad_args")

    def test_quaternion_bone_switched_to_euler(self) -> None:
        rig = fixtures.make_sided_rig(deform=False)
        rig.pose.bones["arm.L"].rotation_mode = "QUATERNION"
        report = anim_ops.dispatch("cycle", {
            "armature": rig.name, "frames": 12,
            "channels": [{"bones": ["arm.L"], "axis": "x", "amplitude": 30.0}]})
        self.assertTrue(report["ok"], report)
        rig = bpy.data.objects["Rig"]
        m1 = _bone_matrix(rig, "arm.L", 1)
        m4 = _bone_matrix(rig, "arm.L", 4)
        self.assertGreater(
            max(abs(a - b) for ra, rb in zip(m1, m4) for a, b in zip(ra, rb)),
            1e-4)


class TestLoop(BlenderTestCase):

    def test_fixes_end_keys_and_adds_cycles(self) -> None:
        rig = fixtures.make_sided_rig(deform=False)
        anim_ops.dispatch("keyframe", {
            "armature": rig.name,
            "keys": [
                {"frame": 1, "bones": {"arm.L": {"rotation_deg": [0, 0, 0]}}},
                {"frame": 20, "bones": {"arm.L": {"rotation_deg": [50, 0, 0]}}},
            ]})
        report = anim_ops.dispatch("loop", {"armature": rig.name})
        self.assertTrue(report["ok"], report)
        self.assertGreater(report["n_end_keys_fixed"], 0)
        self.assertGreater(report["n_cycles_modifiers_added"], 0)

        rig = bpy.data.objects["Rig"]
        # Last keyed frame now matches the first pose.
        self.assertAlmostEqual(
            _euler_x_deg(rig, "arm.L", 20), _euler_x_deg(rig, "arm.L", 1),
            places=3)
        self.assertEqual(bpy.context.scene.frame_end, 19)


class TestBake(BlenderTestCase):

    def test_visual_keying_bakes_constraint(self) -> None:
        rig = fixtures.make_sided_rig(deform=False)
        # arm.R copies arm.L's rotation; only arm.L is keyed.
        con = rig.pose.bones["arm.R"].constraints.new("COPY_ROTATION")
        con.target = rig
        con.subtarget = "arm.L"
        anim_ops.dispatch("cycle", {
            "armature": rig.name, "frames": 12,
            "channels": [{"bones": ["arm.L"], "axis": "x", "amplitude": 30.0}]})

        posed = _bone_matrix(rig, "arm.R", 4)
        report = anim_ops.dispatch("bake", {
            "armature": rig.name, "frame_start": 1, "frame_end": 12,
            "bones": ["arm.R"], "clear_constraints": True})
        self.assertTrue(report["ok"], report)

        rig = bpy.data.objects["Rig"]
        self.assertFalse(rig.pose.bones["arm.R"].constraints)
        baked = _bone_matrix(rig, "arm.R", 4)
        self.assertLess(
            max(abs(a - b) for ra, rb in zip(posed, baked)
                for a, b in zip(ra, rb)), 1e-3)


class TestActionsClear(BlenderTestCase):

    def test_layering_round_trip(self) -> None:
        rig = fixtures.make_sided_rig(deform=False)
        anim_ops.dispatch("cycle", {
            "armature": rig.name, "frames": 12,
            "channels": [{"bones": ["arm.L"], "axis": "x", "amplitude": 20.0}]})

        listing = anim_ops.dispatch(
            "actions", {"armature": rig.name, "op": "list"})
        self.assertTrue(listing["ok"])
        self.assertIsNotNone(listing["active"])
        active = listing["active"]

        pushed = anim_ops.dispatch(
            "actions", {"armature": rig.name, "op": "push_nla", "name": "base"})
        self.assertTrue(pushed["ok"], pushed)
        self.assertEqual(pushed["pushed"], active)
        self.assertIsNone(rig.animation_data.action)
        self.assertEqual(len(rig.animation_data.nla_tracks), 1)

        report = anim_ops.dispatch("inspect", {"armature": rig.name})
        self.assertEqual(report["nla_tracks"][0]["name"], "base")

        assigned = anim_ops.dispatch(
            "actions", {"armature": rig.name, "op": "assign", "name": active})
        self.assertTrue(assigned["ok"], assigned)
        self.assertEqual(rig.animation_data.action.name, active)

    def test_clear(self) -> None:
        rig = fixtures.make_sided_rig(deform=False)
        anim_ops.dispatch("keyframe", {
            "armature": rig.name,
            "keys": [{"frame": 1, "bones": {"arm.L": {"location": [0, 0, 1]}}}]})
        report = anim_ops.dispatch(
            "clear", {"armature": rig.name, "remove_action": True})
        self.assertTrue(report["ok"], report)
        rig = bpy.data.objects["Rig"]
        self.assertIsNone(rig.animation_data.action)
        self.assertTrue(report["action_removed"])

    def test_loop_without_action_fails_clean(self) -> None:
        rig = fixtures.make_sided_rig(deform=False)
        report = anim_ops.dispatch("loop", {"armature": rig.name})
        self.assertFalse(report["ok"])
        self.assertEqual(report["fail"], "no_action")
