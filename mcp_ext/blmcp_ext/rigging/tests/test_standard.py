# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Phase 2 tests: validate_rig() / validate_weights() against conforming and
deliberately broken armatures.
"""

__all__ = ()

import json

import bpy

from tests.bl_test_base import BlenderTestCase
from tests import fixtures

from blrig import _armature
from blrig import standard


def _good_rig() -> bpy.types.Object:
    return _armature.build_armature("Rig", [
        {"name": "root", "head": (0, 0, 0), "tail": (0, 0.5, 0)},
        {"name": "DEF-base", "head": (0, 0, 0), "tail": (0, 0, 1),
         "parent": "root", "use_deform": True},
        {"name": "MCH-pivot", "head": (0, 0, 1), "tail": (0, 0, 1.4), "parent": "root"},
        {"name": "CTL-arm.L", "head": (0.5, 0, 1), "tail": (1, 0, 1), "parent": "MCH-pivot"},
        {"name": "CTL-arm.R", "head": (-0.5, 0, 1), "tail": (-1, 0, 1), "parent": "MCH-pivot"},
    ])


def _rules(findings: list[dict]) -> set[str]:
    return {f["rule"] for f in findings}


class TestValidateRig(BlenderTestCase):

    def test_good_rig_passes(self) -> None:
        result = standard.validate_rig(_good_rig())
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["stats"]["n_bones"], 5)
        self.assertEqual(result["stats"]["n_deform"], 1)

    def test_not_armature(self) -> None:
        result = standard.validate_rig(fixtures.make_cube())
        self.assertFalse(result["ok"])
        self.assertIn("E_NOT_ARMATURE", _rules(result["errors"]))

    def test_no_bones(self) -> None:
        arm = bpy.data.armatures.new("Empty")
        obj = bpy.data.objects.new("Empty", arm)
        bpy.context.scene.collection.objects.link(obj)
        result = standard.validate_rig(obj)
        self.assertIn("E_NO_BONES", _rules(result["errors"]))

    def test_multiple_roots(self) -> None:
        obj = _armature.build_armature("Rig", [
            {"name": "root", "head": (0, 0, 0), "tail": (0, 1, 0)},
            {"name": "CTL-stray", "head": (2, 0, 0), "tail": (2, 1, 0)},
        ])
        result = standard.validate_rig(obj)
        self.assertFalse(result["ok"])
        self.assertIn("E_ROOT_COUNT", _rules(result["errors"]))

    def test_deform_without_prefix(self) -> None:
        obj = _armature.build_armature("Rig", [
            {"name": "root", "head": (0, 0, 0), "tail": (0, 1, 0)},
            {"name": "CTL-bad", "head": (0, 0, 0), "tail": (0, 0, 1),
             "parent": "root", "use_deform": True},
        ])
        result = standard.validate_rig(obj)
        self.assertIn("E_DEFORM_PREFIX", _rules(result["errors"]))
        bad = [e for e in result["errors"] if e["rule"] == "E_DEFORM_PREFIX"][0]
        self.assertEqual(bad["bones"], ["CTL-bad"])

    def test_def_prefix_not_deforming(self) -> None:
        obj = _armature.build_armature("Rig", [
            {"name": "root", "head": (0, 0, 0), "tail": (0, 1, 0)},
            {"name": "DEF-dead", "head": (0, 0, 0), "tail": (0, 0, 1), "parent": "root"},
        ])
        result = standard.validate_rig(obj)
        self.assertIn("E_PREFIX_DEFORM", _rules(result["errors"]))

    def test_default_name(self) -> None:
        obj = _armature.build_armature("Rig", [
            {"name": "root", "head": (0, 0, 0), "tail": (0, 1, 0)},
            {"name": "Bone", "head": (0, 0, 0), "tail": (0, 0, 1), "parent": "root"},
        ])
        result = standard.validate_rig(obj)
        self.assertIn("E_DEFAULT_NAME", _rules(result["errors"]))

    def test_unapplied_scale(self) -> None:
        obj = _good_rig()
        obj.scale = (2.0, 2.0, 2.0)
        bpy.context.view_layer.update()
        result = standard.validate_rig(obj)
        self.assertIn("E_UNAPPLIED_SCALE", _rules(result["errors"]))

    def test_unpaired_side_warning(self) -> None:
        obj = _armature.build_armature("Rig", [
            {"name": "root", "head": (0, 0, 0), "tail": (0, 1, 0)},
            {"name": "CTL-arm.L", "head": (0.5, 0, 0), "tail": (1, 0, 0), "parent": "root"},
        ])
        result = standard.validate_rig(obj)
        self.assertTrue(result["ok"])  # warning, not error
        self.assertIn("W_UNPAIRED_SIDE", _rules(result["warnings"]))

    def test_root_name_warning(self) -> None:
        obj = _armature.build_armature("Rig", [
            {"name": "CTL-main", "head": (0, 0, 0), "tail": (0, 1, 0)},
        ])
        result = standard.validate_rig(obj)
        self.assertIn("W_ROOT_NAME", _rules(result["warnings"]))

    def test_collections_warning(self) -> None:
        obj = _good_rig()
        # Knock a bone out of its collection.
        obj.data.collections["CTL"].unassign(obj.data.bones["CTL-arm.L"])
        result = standard.validate_rig(obj)
        self.assertIn("W_BONE_COLLECTIONS", _rules(result["warnings"]))

    def test_json_serializable(self) -> None:
        json.dumps(standard.validate_rig(_good_rig()))


class TestBoneClass(BlenderTestCase):

    def test_classes(self) -> None:
        self.assertEqual(standard.bone_class("root"), "root")
        self.assertEqual(standard.bone_class("DEF-arm.L"), "deform")
        self.assertEqual(standard.bone_class("CTL-lid"), "control")
        self.assertEqual(standard.bone_class("MCH-pivot"), "mechanism")
        self.assertEqual(standard.bone_class("ORG-spine"), "mechanism")
        self.assertEqual(standard.bone_class("hand_ik.L"), "control")


class TestValidateWeights(BlenderTestCase):

    def _skinned_pair(self):
        rig = _armature.build_armature("Rig", [
            {"name": "root", "head": (0, 0, 0), "tail": (0, 0.5, 0)},
            {"name": "DEF-cube", "head": (0, 0, -1), "tail": (0, 0, 1),
             "parent": "root", "use_deform": True},
        ])
        cube = fixtures.make_cube()
        mod = cube.modifiers.new("Armature", type="ARMATURE")
        mod.object = rig
        group = cube.vertex_groups.new(name="DEF-cube")
        group.add(range(len(cube.data.vertices)), 1.0, "REPLACE")
        return cube, rig

    def test_good_weights_pass(self) -> None:
        cube, rig = self._skinned_pair()
        result = standard.validate_weights(cube, rig)
        self.assertTrue(result["ok"], result)

    def test_missing_modifier(self) -> None:
        cube, rig = self._skinned_pair()
        cube.modifiers.clear()
        result = standard.validate_weights(cube, rig)
        self.assertIn("E_NO_ARMATURE_MODIFIER", _rules(result["errors"]))

    def test_non_deform_group(self) -> None:
        cube, rig = self._skinned_pair()
        cube.vertex_groups.new(name="root")
        result = standard.validate_weights(cube, rig)
        self.assertIn("E_NON_DEFORM_GROUP", _rules(result["errors"]))

    def test_unweighted_verts(self) -> None:
        cube, rig = self._skinned_pair()
        cube.vertex_groups["DEF-cube"].remove([0, 1])
        result = standard.validate_weights(cube, rig)
        self.assertIn("E_UNWEIGHTED", _rules(result["errors"]))

    def test_unnormalized(self) -> None:
        cube, rig = self._skinned_pair()
        cube.vertex_groups["DEF-cube"].add([0], 0.5, "REPLACE")
        result = standard.validate_weights(cube, rig)
        self.assertIn("E_UNNORMALIZED", _rules(result["errors"]))
