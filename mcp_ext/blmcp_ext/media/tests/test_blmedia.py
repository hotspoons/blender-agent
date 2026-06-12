# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
blmedia tests: jail containment, collision suffixing, import/export
roundtrips for the major formats. Runs inside Blender (see bl_run.py).
"""

__all__ = ()

import os
import tempfile
import unittest

import bmesh
import bpy

import blmedia


def _make_cube(name: str = "Cube") -> bpy.types.Object:
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=2.0)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


class _MediaTestCase(unittest.TestCase):

    def setUp(self) -> None:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self._tmp = tempfile.TemporaryDirectory(prefix="blmedia_test_")
        self.jail = self._tmp.name

    def tearDown(self) -> None:
        self._tmp.cleanup()


class TestJail(_MediaTestCase):

    def test_escape_rejected(self) -> None:
        root = blmedia.resolve_jail(self.jail)
        for bad in ("../evil.stl", "/etc/passwd", "a/../../b.stl"):
            with self.assertRaises(ValueError):
                blmedia.jail_path(root, bad)

    def test_missing_file_rejected(self) -> None:
        root = blmedia.resolve_jail(self.jail)
        with self.assertRaises(ValueError):
            blmedia.jail_path(root, "ghost.stl", must_exist=True)

    def test_unique_path_suffixes(self) -> None:
        root = blmedia.resolve_jail(self.jail)
        first = blmedia.unique_path(root, "model.stl")
        self.assertEqual(os.path.basename(first), "model.stl")
        open(first, "w").close()
        second = blmedia.unique_path(root, "model.stl")
        self.assertEqual(os.path.basename(second), "model-2.stl")
        open(second, "w").close()
        third = blmedia.unique_path(root, "model.stl")
        self.assertEqual(os.path.basename(third), "model-3.stl")

    def test_safe_name(self) -> None:
        self.assertEqual(blmedia.safe_name("../../weird name?.stl"), "weird name_.stl")
        self.assertEqual(blmedia.safe_name(".hidden"), "hidden")
        self.assertEqual(blmedia.safe_name("C:\\Users\\x\\part.stl"), "part.stl")

    def test_env_default(self) -> None:
        previous = os.environ.get("BLENDER_MCP_MEDIA_DIR")
        os.environ["BLENDER_MCP_MEDIA_DIR"] = os.path.join(self.jail, "global")
        try:
            root = blmedia.resolve_jail(None)
            self.assertTrue(root.endswith("global"))
            self.assertTrue(os.path.isdir(root))
        finally:
            if previous is None:
                os.environ.pop("BLENDER_MCP_MEDIA_DIR", None)
            else:
                os.environ["BLENDER_MCP_MEDIA_DIR"] = previous


class TestExportImport(_MediaTestCase):

    def test_stl_roundtrip(self) -> None:
        _make_cube("Widget")
        out = blmedia.export_file("stl", self.jail, objects=["Widget"])
        self.assertEqual(out["file"], "Widget.stl")
        self.assertGreater(out["size"], 80)

        listing = blmedia.list_files(self.jail)
        self.assertEqual([f["name"] for f in listing["files"]], ["Widget.stl"])
        self.assertEqual(listing["files"][0]["kind"], "mesh")

        bpy.ops.wm.read_factory_settings(use_empty=True)
        report = blmedia.import_file("Widget.stl", self.jail)
        self.assertEqual(report["kind"], "mesh")
        self.assertEqual(report["n_objects"], 1)
        imported = bpy.data.objects[report["objects"][0]]
        self.assertEqual(len(imported.data.vertices), 8)

    def test_export_collision_suffixes(self) -> None:
        _make_cube("Part")
        first = blmedia.export_file("stl", self.jail, objects=["Part"])
        second = blmedia.export_file("stl", self.jail, objects=["Part"])
        self.assertEqual(first["file"], "Part.stl")
        self.assertEqual(second["file"], "Part-2.stl")

    def test_export_selected_only(self) -> None:
        _make_cube("Keep")
        _make_cube("Drop")
        out = blmedia.export_file("obj", self.jail, objects=["Keep"])
        bpy.ops.wm.read_factory_settings(use_empty=True)
        report = blmedia.import_file(out["file"], self.jail)
        self.assertEqual(report["n_objects"], 1)

    def test_export_scene_blend_and_glb(self) -> None:
        _make_cube("A")
        _make_cube("B")
        blend = blmedia.export_file("blend", self.jail, filename="project")
        self.assertEqual(blend["file"], "project.blend")
        glb = blmedia.export_file("glb", self.jail)
        self.assertTrue(glb["file"].endswith(".glb"))
        self.assertGreater(glb["size"], 100)

    def test_export_unknown_format(self) -> None:
        with self.assertRaises(ValueError):
            blmedia.export_file("doc", self.jail)

    def test_export_missing_object(self) -> None:
        with self.assertRaises(ValueError):
            blmedia.export_file("stl", self.jail, objects=["Ghost"])

    def test_svg_export_without_grease_pencil(self) -> None:
        _make_cube()
        with self.assertRaises(ValueError):
            blmedia.export_file("svg", self.jail)

    def test_import_image_as_reference(self) -> None:
        # Render a tiny image to import.
        import numpy as np
        path = blmedia.unique_path(blmedia.resolve_jail(self.jail), "ref.png")
        image = bpy.data.images.new("tmp", width=4, height=4)
        image.filepath_raw = path
        image.file_format = "PNG"
        image.save()
        report = blmedia.import_file("ref.png", self.jail)
        self.assertEqual(report["kind"], "image")
        empty = bpy.data.objects[report["objects"][0]]
        self.assertEqual(empty.empty_display_type, "IMAGE")

    def test_import_svg_as_curves(self) -> None:
        path = os.path.join(blmedia.resolve_jail(self.jail), "shape.svg")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
                     '<rect x="10" y="10" width="80" height="80"/></svg>')
        report = blmedia.import_file("shape.svg", self.jail)
        self.assertEqual(report["kind"], "vector")
        self.assertGreaterEqual(report["n_objects"], 1)

    def test_import_rejects_other(self) -> None:
        path = os.path.join(blmedia.resolve_jail(self.jail), "notes.txt")
        open(path, "w").close()
        with self.assertRaises(ValueError):
            blmedia.import_file("notes.txt", self.jail)


def _add_camera(name: str = "Cam") -> bpy.types.Object:
    cam_data = bpy.data.cameras.new(name)
    cam = bpy.data.objects.new(name, cam_data)
    cam.location = (4.0, -4.0, 3.0)
    bpy.context.scene.collection.objects.link(cam)
    return cam


class TestRenderFrame(_MediaTestCase):
    """
    media_io("render", ...): the one-call "show the user an image" path
    (production gap 2026-06-12: the model had to hand-copy a render into
    the jail because export had no image story).
    """

    def setUp(self) -> None:
        super().setUp()
        _make_cube()
        scene = bpy.context.scene
        scene.render.engine = "BLENDER_WORKBENCH"
        scene.render.resolution_x = 64
        scene.render.resolution_y = 64

    def test_render_uses_sole_camera_and_restores_settings(self) -> None:
        _add_camera()
        self.assertIsNone(bpy.context.scene.camera)
        previous_path = bpy.context.scene.render.filepath
        report = blmedia.render_frame(self.jail, frame=7, filename="pose")
        self.assertEqual(report["file"], "pose.png")
        self.assertEqual(report["camera"], "Cam")
        self.assertEqual(report["frame"], 7)
        self.assertGreater(report["size"], 0)
        self.assertTrue(os.path.isfile(os.path.join(report["folder"], "pose.png")))
        # Output settings and the active camera were restored.
        self.assertEqual(bpy.context.scene.render.filepath, previous_path)
        self.assertIsNone(bpy.context.scene.camera)

    def test_render_without_camera_is_actionable(self) -> None:
        with self.assertRaises(ValueError) as caught:
            blmedia.render_frame(self.jail)
        self.assertIn("camera", str(caught.exception))

    def test_render_named_camera(self) -> None:
        _add_camera("A")
        _add_camera("B")
        report = blmedia.render_frame(self.jail, camera="B")
        self.assertEqual(report["camera"], "B")

    def test_export_image_format_delegates_to_render(self) -> None:
        _add_camera()
        report = blmedia.export_file("png", self.jail, filename="snap")
        self.assertEqual(report["file"], "snap.png")
        self.assertEqual(report["format"], "png")

    def test_export_unknown_format_suggests_render_and_stage(self) -> None:
        with self.assertRaises(ValueError) as caught:
            blmedia.export_file("doc", self.jail)
        message = str(caught.exception)
        self.assertIn("png", message)
        self.assertIn("stage", message)


class TestStage(_MediaTestCase):

    def test_stage_copies_with_collision_suffix(self) -> None:
        outside = os.path.join(self._tmp.name, "elsewhere")
        os.makedirs(outside)
        source = os.path.join(outside, "frame.png")
        with open(source, "wb") as fh:
            fh.write(b"not-really-a-png")
        first = blmedia.stage_file(source, self.jail)
        self.assertEqual(first["file"], "frame.png")
        self.assertEqual(first["kind"], "image")
        self.assertEqual(first["staged_from"], source)
        second = blmedia.stage_file(source, self.jail)
        self.assertEqual(second["file"], "frame-2.png")

    def test_stage_missing_file(self) -> None:
        with self.assertRaises(ValueError):
            blmedia.stage_file("/nonexistent/nowhere.png", self.jail)

    def test_stage_rename(self) -> None:
        source = os.path.join(self._tmp.name, "0001.png")
        with open(source, "wb") as fh:
            fh.write(b"x")
        report = blmedia.stage_file(source, self.jail, filename="walk-frame12.png")
        self.assertEqual(report["file"], "walk-frame12.png")
