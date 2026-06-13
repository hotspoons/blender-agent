# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
weights(verb) ops: coverage inspection, transfer, directional midline
mirror, clean/limit/normalize, topology smoothing, bind gating — and the
snapshot rollback that makes failed mutations safe.
"""

__all__ = ()

import bpy

from tests.bl_test_base import BlenderTestCase
from tests import fixtures

from blrig.skills import weight_ops


def _bind_modifier(obj, rig) -> None:
    mod = obj.modifiers.new("Armature", "ARMATURE")
    mod.object = rig


def _weight_split_bar(rig, name="Bar", left_only=False):
    """
    Subdivided bar with a hard L/R weight split at x=0 (x=0 verts go to
    .L so every vertex carries weight). ``left_only`` leaves x<0 verts
    unweighted — the one-sided-skinning fixture.
    """
    bar = fixtures.make_subdivided_bar(name)
    left = bar.vertex_groups.new(name="DEF-arm.L")
    right = bar.vertex_groups.new(name="DEF-arm.R")
    for v in bar.data.vertices:
        if v.co.x >= 0.0:
            left.add([v.index], 1.0, "REPLACE")
        elif not left_only:
            right.add([v.index], 1.0, "REPLACE")
    _bind_modifier(bar, rig)
    return bar


def _vert_weights(obj, index) -> dict:
    names = {g.index: g.name for g in obj.vertex_groups}
    return {names[ge.group]: ge.weight
            for ge in obj.data.vertices[index].groups if ge.weight > 0.0}


class TestInspect(BlenderTestCase):

    def test_balanced_coverage(self) -> None:
        rig = fixtures.make_sided_rig()
        bar = _weight_split_bar(rig)
        bar.vertex_groups.new(name="Unused")
        report = weight_ops.dispatch(
            "inspect", {"object": bar.name, "armature": rig.name})
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["empty_groups"], ["Unused"])
        self.assertEqual(report["bones_without_group"], [])
        balance = {b["left"]: b for b in report["lr_balance"]}
        self.assertIn("DEF-arm.L", balance)
        # x=0 verts deliberately weight .L, so a small imbalance is real.
        self.assertLess(balance["DEF-arm.L"]["imbalance_pct"], 30.0)
        self.assertTrue(report["validation"]["ok"], report["validation"])

    def test_one_sided_flagged(self) -> None:
        rig = fixtures.make_sided_rig()
        bar = _weight_split_bar(rig, left_only=True)
        report = weight_ops.dispatch(
            "inspect", {"object": bar.name, "armature": rig.name})
        self.assertTrue(report["ok"])
        balance = {b["left"]: b for b in report["lr_balance"]}
        self.assertEqual(balance["DEF-arm.L"]["right_verts"], 0)
        rules = [e["rule"] for e in report["validation"]["errors"]]
        self.assertIn("E_UNWEIGHTED", rules)

    def test_missing_object(self) -> None:
        report = weight_ops.dispatch("inspect", {"object": "Ghost"})
        self.assertEqual(report["fail"], "object_not_found")


class TestMirror(BlenderTestCase):

    def test_mirror_left_to_right(self) -> None:
        rig = fixtures.make_sided_rig()
        bar = _weight_split_bar(rig, left_only=True)
        report = weight_ops.dispatch("mirror", {
            "object": bar.name, "armature": rig.name,
            "from_side": "L", "center_x": 0.0})
        self.assertTrue(report["ok"], report)
        self.assertGreater(report["verts_written"], 0)

        bar = bpy.data.objects["Bar"]
        for v in bar.data.vertices:
            weights = _vert_weights(bar, v.index)
            if v.co.x < -0.05:
                self.assertEqual(weights, {"DEF-arm.R": 1.0},
                                 "vert at x={:.3f}".format(v.co.x))
            elif v.co.x >= 0.0:
                self.assertEqual(weights, {"DEF-arm.L": 1.0})
        validation = weight_ops.dispatch("validate", {
            "objects": [bar.name], "armature": rig.name})
        self.assertTrue(validation["ok"], validation)

    def test_no_side_verts_fails_clean(self) -> None:
        rig = fixtures.make_sided_rig()
        bar = _weight_split_bar(rig)
        report = weight_ops.dispatch("mirror", {
            "object": bar.name, "armature": rig.name,
            "from_side": "L", "center_x": 10.0})
        self.assertFalse(report["ok"])
        self.assertEqual(report["fail"], "mirror_no_side_verts")


class TestTransfer(BlenderTestCase):

    def test_transfer_to_coarser_mesh(self) -> None:
        rig = fixtures.make_sided_rig()
        source = _weight_split_bar(rig, name="Source")
        target = fixtures.make_subdivided_bar("Target", cuts=3)
        report = weight_ops.dispatch("transfer", {
            "source": source.name, "targets": [target.name]})
        self.assertTrue(report["ok"], report)

        target = bpy.data.objects["Target"]
        self.assertEqual(
            sorted(g.name for g in target.vertex_groups),
            ["DEF-arm.L", "DEF-arm.R"])
        for v in target.data.vertices:
            weights = _vert_weights(target, v.index)
            if v.co.x > 0.1:
                self.assertGreater(weights.get("DEF-arm.L", 0.0), 0.5)
            elif v.co.x < -0.1:
                self.assertGreater(weights.get("DEF-arm.R", 0.0), 0.5)

    def test_unweighted_source_fails(self) -> None:
        fixtures.make_subdivided_bar("Bare")
        fixtures.make_subdivided_bar("Target")
        report = weight_ops.dispatch(
            "transfer", {"source": "Bare", "targets": ["Target"]})
        self.assertFalse(report["ok"])
        self.assertEqual(report["fail"], "source_has_no_groups")


class TestClean(BlenderTestCase):

    def test_prunes_normalizes_and_drops_empty(self) -> None:
        rig = fixtures.make_sided_rig()
        bar = _weight_split_bar(rig)
        bar.vertex_groups.new(name="Empty")
        # Sprinkle sub-threshold noise into the opposite group.
        noisy = [v.index for v in bar.data.vertices if v.co.x > 0.2]
        bar.vertex_groups["DEF-arm.R"].add(noisy, 0.004, "REPLACE")

        report = weight_ops.dispatch("clean", {
            "object": bar.name, "armature": rig.name, "threshold": 0.01})
        self.assertTrue(report["ok"], report)
        self.assertIn("Empty", report["removed_empty_groups"])

        bar = bpy.data.objects["Bar"]
        for index in noisy:
            weights = _vert_weights(bar, index)
            self.assertNotIn("DEF-arm.R", weights)
            self.assertAlmostEqual(sum(weights.values()), 1.0, places=3)
        validation = weight_ops.dispatch("validate", {
            "objects": [bar.name], "armature": rig.name})
        self.assertTrue(validation["ok"], validation)


class TestSmooth(BlenderTestCase):

    def test_softens_hard_split(self) -> None:
        rig = fixtures.make_sided_rig()
        bar = _weight_split_bar(rig)
        report = weight_ops.dispatch("smooth", {
            "object": bar.name, "armature": rig.name,
            "factor": 0.5, "iterations": 3})
        self.assertTrue(report["ok"], report)

        bar = bpy.data.objects["Bar"]
        boundary = [v.index for v in bar.data.vertices if abs(v.co.x) < 1e-6]
        self.assertTrue(boundary)
        for index in boundary:
            weights = _vert_weights(bar, index)
            self.assertLess(weights.get("DEF-arm.L", 0.0), 1.0)
            self.assertGreater(weights.get("DEF-arm.R", 0.0), 0.0)
            self.assertAlmostEqual(sum(weights.values()), 1.0, places=3)


class TestBind(BlenderTestCase):

    def test_bind_weighted_mesh(self) -> None:
        rig = fixtures.make_sided_rig()
        bar = _weight_split_bar(rig)
        bar.modifiers.remove(bar.modifiers[0])  # fixture's modifier
        report = weight_ops.dispatch(
            "bind", {"objects": [bar.name], "armature": rig.name})
        self.assertTrue(report["ok"], report)
        bar = bpy.data.objects["Bar"]
        self.assertTrue(any(m.type == "ARMATURE" for m in bar.modifiers))
        self.assertEqual(bar.parent, bpy.data.objects[rig.name])

    def test_unweighted_bind_refused_and_rolled_back(self) -> None:
        rig = fixtures.make_sided_rig()
        bare = fixtures.make_subdivided_bar("Bare")
        report = weight_ops.dispatch(
            "bind", {"objects": [bare.name], "armature": rig.name})
        self.assertFalse(report["ok"])
        self.assertEqual(report["fail"], "bind_unweighted")
        # Snapshot rollback: the failed bind left nothing behind.
        bare = bpy.data.objects["Bare"]
        self.assertFalse(any(m.type == "ARMATURE" for m in bare.modifiers))
        self.assertIsNone(bare.parent)

    def test_allow_unweighted_overrides(self) -> None:
        rig = fixtures.make_sided_rig()
        bare = fixtures.make_subdivided_bar("Bare")
        report = weight_ops.dispatch("bind", {
            "objects": [bare.name], "armature": rig.name,
            "allow_unweighted": True})
        self.assertTrue(report["ok"], report)


class TestDispatch(BlenderTestCase):

    def test_unknown_verb(self) -> None:
        report = weight_ops.dispatch("explode", {})
        self.assertEqual(report["fail"], "unknown_verb")
        self.assertIn("mirror", report["valid"])
