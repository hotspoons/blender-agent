# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
rig_biped_multipart on the multi-part character corpus: fused weight
proxy -> Rigify -> weight transfer back to the untouched originals.
Slow (several remesh rounds + Rigify + bone-heat per end-to-end test).
"""

__all__ = ()

import bpy

import corpus

from tests.bl_test_base import BlenderTestCase

from blrig.skills import rig_biped_multipart


class TestMultipartDiagnose(BlenderTestCase):

    def test_parts_ok(self) -> None:
        manifest = corpus.build("humanoid_parts")
        report = rig_biped_multipart.diagnose({"objects": manifest["objects"]})
        self.assertTrue(report["ok"], report)
        self.assertEqual(len(report["plan"]["parts"]), manifest["truth"]["n_parts"])
        self.assertLess(abs(report["plan"]["center_x"]), 0.05)

    def test_bighand_midline_not_bbox_center(self) -> None:
        # The giant one-sided hand drags the combined bbox center off the
        # body midline; the midline estimate must NOT follow it.
        manifest = corpus.build("humanoid_parts_bighand")
        report = rig_biped_multipart.diagnose({"objects": manifest["objects"]})
        self.assertTrue(report["ok"], report)
        plan = report["plan"]
        bbox_center_x = (plan["bbox_min"][0] + plan["bbox_max"][0]) * 0.5
        self.assertGreater(abs(bbox_center_x), 0.05)  # skew is real
        self.assertLess(abs(plan["center_x"]), 0.05)  # estimate resists it

    def test_scaled_part_gated(self) -> None:
        manifest = corpus.build("humanoid_parts")
        bpy.data.objects[manifest["objects"][0]].scale = (1.1, 1.0, 1.0)
        bpy.context.view_layer.update()
        report = rig_biped_multipart.diagnose({"objects": manifest["objects"]})
        self.assertFalse(report["ok"])
        self.assertEqual(report["fail"], "unhealthy_mesh")


class TestMultipartEndToEnd(BlenderTestCase):

    def _assert_bound(self, manifest: dict, result: dict) -> None:
        rig = bpy.data.objects[result["armature"]]
        for part_name in manifest["objects"]:
            part = bpy.data.objects[part_name]
            self.assertTrue(
                any(m.type == "ARMATURE" and m.object == rig
                    for m in part.modifiers), part_name)
            self.assertIs(part.parent, rig, part_name)
            uncovered = sum(
                1 for v in part.data.vertices
                if not any(e.weight > 1e-6 for e in v.groups))
            self.assertEqual(uncovered, 0, part_name)

    def test_parts_full_pipeline(self) -> None:
        manifest = corpus.build("humanoid_parts")
        n_verts_before = {
            n: len(bpy.data.objects[n].data.vertices) for n in manifest["objects"]}
        ctx = {"objects": manifest["objects"]}
        result = rig_biped_multipart.run(ctx)
        self.assertTrue(result["ok"], result)
        self._assert_bound(manifest, result)
        # Originals untouched geometrically; proxy gone.
        for name, n_verts in n_verts_before.items():
            self.assertEqual(len(bpy.data.objects[name].data.vertices), n_verts)
        self.assertNotIn("_blrig_weight_proxy", bpy.data.objects)

        report = rig_biped_multipart.verify(ctx)
        self.assertTrue(report["ok"], [c for c in report["checks"] if not c["ok"]])

    def test_bighand_full_pipeline(self) -> None:
        # The one-sided appendage scenario: symmetrize-union must keep the
        # skeleton on the body midline and both legs weighted.
        manifest = corpus.build("humanoid_parts_bighand")
        ctx = {"objects": manifest["objects"]}
        result = rig_biped_multipart.run(ctx)
        self.assertTrue(result["ok"], result)
        self._assert_bound(manifest, result)

        report = rig_biped_multipart.verify(ctx)
        self.assertTrue(report["ok"], [c for c in report["checks"] if not c["ok"]])

    def test_failed_gate_means_no_rig(self) -> None:
        manifest = corpus.build("humanoid_parts")
        bpy.data.objects[manifest["objects"][0]].scale = (1.1, 1.0, 1.0)
        bpy.context.view_layer.update()
        before = set(bpy.data.objects.keys())
        report = rig_biped_multipart.run({"objects": manifest["objects"]})
        self.assertFalse(report["ok"])
        self.assertEqual(set(bpy.data.objects.keys()), before)
