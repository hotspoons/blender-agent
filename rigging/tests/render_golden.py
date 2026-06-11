# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Golden-render regression tier: rig corpus assets, strike a canonical pose,
render with the Workbench engine (deterministic, no sampling noise) and
diff against committed baselines with a perceptual threshold.

Refresh baselines after an intentional visual change:

    BLRIG_UPDATE_GOLDEN=1 make test-render
"""

__all__ = ()

import os

import bpy
import numpy as np

import corpus

from tests.bl_test_base import BlenderTestCase

from blrig import skills as skill_registry
from blrig.skills import _bones

_GOLDEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden")
_RESOLUTION = 160
# Mean absolute pixel difference (0..1) tolerated — perceptual, not exact:
# antialiasing and GPU rasterization may vary slightly across machines.
_DIFF_THRESHOLD = 0.02


def _pose_hinge(rig: bpy.types.Object) -> None:
    _bones.pose_rotate(rig, "CTL-hinge", "y", 60.0)


def _pose_lamp(rig: bpy.types.Object) -> None:
    _bones.pose_rotate(rig, "CTL-ArmLower", "y", 25.0)
    _bones.pose_rotate(rig, "CTL-Head", "y", -30.0)


def _pose_biped(rig: bpy.types.Object) -> None:
    holder = rig.pose.bones.get("upper_arm_parent.L")
    if holder is not None and "IK_FK" in holder:
        holder["IK_FK"] = 1.0
    _bones.pose_rotate(rig, "upper_arm_fk.L", "x", 50.0)


_CASES = (
    ("door_and_frame", "rig_hinge", _pose_hinge),
    ("desk_lamp", "rig_rigid_assembly", _pose_lamp),
    ("humanoid", "rig_biped_rigify", _pose_biped),
)


def _setup_camera_and_render(filepath: str) -> None:
    """
    Frame all mesh objects from a fixed three-quarter view and render with
    Workbench to *filepath*.
    """
    from mathutils import Vector

    meshes = [o for o in bpy.data.objects if o.type == "MESH" and o.visible_get()]
    pts = [o.matrix_world @ Vector(corner) for o in meshes for corner in o.bound_box]
    lo = np.array([min(p[i] for p in pts) for i in range(3)])
    hi = np.array([max(p[i] for p in pts) for i in range(3)])
    center = (lo + hi) * 0.5
    size = float(np.linalg.norm(hi - lo))

    cam_data = bpy.data.cameras.new("GoldenCam")
    cam = bpy.data.objects.new("GoldenCam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    direction = np.array([1.0, -1.0, 0.6])
    direction /= np.linalg.norm(direction)
    cam.location = (center + direction * size * 1.8).tolist()

    # Aim at the center.
    look = Vector(center.tolist()) - cam.location
    cam.rotation_euler = look.to_track_quat("-Z", "Y").to_euler()

    scene = bpy.context.scene
    scene.camera = cam
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "FLAT"
    scene.display.shading.color_type = "OBJECT"
    scene.render.resolution_x = _RESOLUTION
    scene.render.resolution_y = _RESOLUTION
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = filepath
    bpy.ops.render.render(write_still=True)


def _load_pixels(filepath: str) -> np.ndarray:
    image = bpy.data.images.load(filepath)
    try:
        pixels = np.array(image.pixels[:], dtype=np.float32)
        return pixels.reshape(-1, 4)[:, :3]
    finally:
        bpy.data.images.remove(image)


class TestGoldenRenders(BlenderTestCase):

    def test_golden_corpus(self) -> None:
        update = os.environ.get("BLRIG_UPDATE_GOLDEN", "") not in ("", "0")
        os.makedirs(_GOLDEN_DIR, exist_ok=True)

        for asset, skill_name, pose in _CASES:
            with self.subTest(asset=asset):
                bpy.ops.wm.read_factory_settings(use_empty=True)
                manifest = corpus.build(asset)
                ctx = {"objects": manifest["objects"]}
                skill = skill_registry.get_skill(skill_name)
                result = skill.run(ctx)
                self.assertTrue(result["ok"], (asset, result))

                rig = bpy.data.objects[ctx["armature"]]
                pose(rig)

                rendered = os.path.join(
                    os.environ.get("BLRIG_LOG_DIR", "/tmp"),
                    "render_{:s}.png".format(asset))
                _setup_camera_and_render(rendered)

                baseline = os.path.join(_GOLDEN_DIR, "{:s}.png".format(asset))
                if update or not os.path.exists(baseline):
                    import shutil
                    shutil.copyfile(rendered, baseline)
                    if not update:
                        self.fail(
                            "baseline for {!r} was missing — wrote it; verify "
                            "visually and commit tests/golden/{:s}.png".format(asset, asset))
                    continue

                diff = float(np.abs(
                    _load_pixels(rendered) - _load_pixels(baseline)).mean())
                self.assertLess(
                    diff, _DIFF_THRESHOLD,
                    "{:s} drifted from baseline (mean diff {:.4f}); if the "
                    "change is intentional rerun with BLRIG_UPDATE_GOLDEN=1".format(
                        asset, diff))
