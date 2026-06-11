# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Phase 0 smoke test: the harness itself works (create -> query -> assert).
"""

__all__ = ()

import bmesh
import bpy

from tests.bl_test_base import BlenderTestCase


class TestSmoke(BlenderTestCase):

    def test_cube_roundtrip(self) -> None:
        mesh = bpy.data.meshes.new("m")
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=2.0)
        bm.to_mesh(mesh)
        bm.free()
        obj = self.link_object(bpy.data.objects.new("Cube", mesh))

        self.assertEqual(len(mesh.vertices), 8)
        lo = [min(v.co[i] for v in mesh.vertices) for i in range(3)]
        hi = [max(v.co[i] for v in mesh.vertices) for i in range(3)]
        self.assertEqual(lo, [-1.0, -1.0, -1.0])
        self.assertEqual(hi, [1.0, 1.0, 1.0])
        self.assertIn("Cube", bpy.context.scene.collection.objects)

    def test_blrig_importable(self) -> None:
        import blrig
        self.assertTrue(blrig.__version__)
