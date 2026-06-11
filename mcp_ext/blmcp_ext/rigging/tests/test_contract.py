# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Phase 3 tests: skill-contract machinery — rollback leaves no trace,
failures are structured, snapshots restore.
"""

__all__ = ()

import bpy

from tests.bl_test_base import BlenderTestCase
from tests import fixtures

from blrig import _armature
from blrig.skills import _contract


class TestReports(BlenderTestCase):

    def test_ok_and_fail_shape(self) -> None:
        self.assertEqual(_contract.ok(x=1), {"ok": True, "x": 1})
        report = _contract.fail("asymmetric", suggest="rig_rigid_assembly", pct=12.0)
        self.assertFalse(report["ok"])
        self.assertEqual(report["fail"], "asymmetric")
        self.assertEqual(report["suggest"], "rig_rigid_assembly")
        self.assertEqual(report["pct"], 12.0)

    def test_resolve_objects(self) -> None:
        fixtures.make_cube("Target")
        objs, err = _contract.resolve_objects({"objects": ["Target"]}, expected=1)
        self.assertIsNone(err)
        self.assertEqual(objs[0].name, "Target")

        _objs, err = _contract.resolve_objects({"objects": ["Ghost"]})
        self.assertEqual(err["fail"], "object_not_found")

        _objs, err = _contract.resolve_objects({"objects": ["Target"]}, expected=2)
        self.assertEqual(err["fail"], "wrong_object_count")


class TestRollback(BlenderTestCase):

    def test_rollback_removes_created(self) -> None:
        cube = fixtures.make_cube("Keep")
        before_objects = set(bpy.data.objects.keys())
        before_armatures = set(bpy.data.armatures.keys())

        rollback = _contract.Rollback()
        rig = _armature.build_armature("Rig", [
            {"name": "root", "head": (0, 0, 0), "tail": (0, 1, 0)},
        ])
        rollback.track_object(rig)
        mod = cube.modifiers.new("Armature", type="ARMATURE")
        rollback.track_modifier(cube, mod)
        group = cube.vertex_groups.new(name="DEF-x")
        rollback.track_vgroup(cube, group)

        rollback.undo()

        self.assertEqual(set(bpy.data.objects.keys()), before_objects)
        self.assertEqual(set(bpy.data.armatures.keys()), before_armatures)
        self.assertEqual(len(cube.modifiers), 0)
        self.assertEqual(len(cube.vertex_groups), 0)

    def test_rollback_restores_parent(self) -> None:
        a = fixtures.make_cube("A")
        b = fixtures.make_cube("B", location=(3, 0, 0))
        bpy.context.view_layer.update()
        rollback = _contract.Rollback()
        rollback.track_parent(b)
        b.parent = a
        rollback.undo()
        self.assertIsNone(b.parent)
        self.assertAlmostEqual(b.matrix_world.translation.x, 3.0, places=5)

    def test_run_with_rollback_on_exception(self) -> None:
        before = set(bpy.data.objects.keys())

        def body(rollback):
            rollback.track_object(_armature.build_armature("Doomed", [
                {"name": "root", "head": (0, 0, 0), "tail": (0, 1, 0)},
            ]))
            raise RuntimeError("boom")

        report = _contract.run_with_rollback("test_skill", body)
        self.assertFalse(report["ok"])
        self.assertEqual(report["fail"], "exception")
        self.assertIn("boom", report["error"])
        self.assertEqual(set(bpy.data.objects.keys()), before)

    def test_run_with_rollback_on_failed_report(self) -> None:
        before = set(bpy.data.objects.keys())

        def body(rollback):
            rollback.track_object(_armature.build_armature("Doomed", [
                {"name": "root", "head": (0, 0, 0), "tail": (0, 1, 0)},
            ]))
            return _contract.fail("nope")

        report = _contract.run_with_rollback("test_skill", body)
        self.assertFalse(report["ok"])
        self.assertEqual(set(bpy.data.objects.keys()), before)

    def test_run_with_rollback_success_keeps(self) -> None:
        def body(rollback):
            rollback.track_object(_armature.build_armature("Kept", [
                {"name": "root", "head": (0, 0, 0), "tail": (0, 1, 0)},
            ]))
            return _contract.ok(armature="Kept")

        report = _contract.run_with_rollback("test_skill", body)
        self.assertTrue(report["ok"])
        self.assertIn("Kept", bpy.data.objects)


class TestSnapshot(BlenderTestCase):

    def test_snapshot_restore(self) -> None:
        import os
        fixtures.make_cube("Original")
        path = _contract.scene_snapshot()
        try:
            fixtures.make_cube("Extra")
            self.assertIn("Extra", bpy.data.objects)
            _contract.scene_restore(path)
            self.assertIn("Original", bpy.data.objects)
            self.assertNotIn("Extra", bpy.data.objects)
        finally:
            os.unlink(path)


class TestVerifyCommon(BlenderTestCase):

    def test_missing_armature(self) -> None:
        checks = _contract.verify_common("Ghost")
        self.assertFalse(checks[0]["ok"])

    def test_good_armature(self) -> None:
        _armature.build_armature("Rig", [
            {"name": "root", "head": (0, 0, 0), "tail": (0, 1, 0)},
        ])
        checks = _contract.verify_common("Rig")
        self.assertTrue(all(c["ok"] for c in checks), checks)
