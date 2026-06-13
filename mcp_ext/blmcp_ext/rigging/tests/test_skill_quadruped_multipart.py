# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
rig_quadruped_multipart on the multi-part quadruped corpus: fused weight
proxy -> Rigify quadruped -> weights transferred back to the untouched
originals. Exercises the SAME shared organic path as the biped multipart
skill, with the quadruped metarig. Slow (remesh rounds + Rigify).
"""

__all__ = ()

import bpy

import corpus

from tests.bl_test_base import BlenderTestCase

from blrig.skills import rig_quadruped_multipart


class TestQuadrupedMultipartDiagnose(BlenderTestCase):

    def test_parts_ok(self) -> None:
        manifest = corpus.build("quadruped_parts")
        report = rig_quadruped_multipart.diagnose({"objects": manifest["objects"]})
        self.assertTrue(report["ok"], report)
        self.assertEqual(len(report["plan"]["parts"]), manifest["truth"]["n_parts"])

    def test_scaled_part_gated(self) -> None:
        manifest = corpus.build("quadruped_parts")
        bpy.data.objects[manifest["objects"][0]].scale = (1.1, 1.0, 1.0)
        bpy.context.view_layer.update()
        report = rig_quadruped_multipart.diagnose({"objects": manifest["objects"]})
        self.assertFalse(report["ok"])
        self.assertEqual(report["fail"], "unhealthy_mesh")


class TestQuadrupedMultipartEndToEnd(BlenderTestCase):

    def test_parts_full_pipeline(self) -> None:
        manifest = corpus.build("quadruped_parts")
        ctx = {"objects": manifest["objects"]}
        result = rig_quadruped_multipart.run(ctx)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["multipart"]["metarig"], "quadruped")

        rig = bpy.data.objects[result["armature"]]
        for part_name in manifest["objects"]:
            part = bpy.data.objects[part_name]
            self.assertTrue(
                any(m.type == "ARMATURE" and m.object == rig
                    for m in part.modifiers), part_name)
            self.assertIs(part.parent, rig, part_name)
            # Every original vertex must be weighted after transfer.
            self.assertTrue(
                all(any(e.weight > 1e-6 for e in v.groups)
                    for v in part.data.vertices), part_name)

        # The disposable proxy is gone.
        self.assertNotIn("_blrig_weight_proxy", bpy.data.objects)

        report = rig_quadruped_multipart.verify(ctx)
        self.assertTrue(report["ok"], [c for c in report["checks"] if not c["ok"]])
