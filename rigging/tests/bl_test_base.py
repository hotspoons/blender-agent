# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Shared base class for in-Blender tests: every test gets an empty scene.
"""

__all__ = (
    "BlenderTestCase",
)

import unittest

import bpy


class BlenderTestCase(unittest.TestCase):
    """
    Resets to an empty factory scene before each test, so tests never
    depend on each other's leftovers.
    """

    def setUp(self) -> None:
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def link_object(self, obj: bpy.types.Object) -> bpy.types.Object:
        bpy.context.scene.collection.objects.link(obj)
        return obj
