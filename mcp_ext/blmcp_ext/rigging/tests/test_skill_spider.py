# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
The cartoon-spider production failure (2026-06-11): disconnected
components must keep their internal joints, gaps must be bridgeable, and
rig_chain must cover ball-jointed appendages. Exercises the assembly
component fix, bridge_gaps, contact_tolerance, rig_chain (standalone and
composed into an existing armature) and the E_NO_DEFORM_GROUPS hole.
"""

__all__ = ()

import bpy
import numpy as np

import corpus

from tests.bl_test_base import BlenderTestCase

from blrig.skills import _bones, rig_chain, rig_rigid_assembly

_LEG0 = ["Leg0_Coxa", "Leg0_Femur", "Leg0_Tibia"]


class TestSpiderAssembly(BlenderTestCase):

    def test_components_keep_internal_joints(self) -> None:
        """
        The original bug: 0 joints, everything floating. Legs never touch
        the body, but each leg's internal contacts must become joints.
        """
        manifest = corpus.build("cartoon_spider")
        report = rig_rigid_assembly.diagnose({"objects": manifest["objects"]})
        self.assertTrue(report["ok"], report)
        plan = report["plan"]
        self.assertEqual(len(plan["joints"]), manifest["truth"]["leg_internal_joints"])
        # One anchor per leg (re-rooted at the coxa, the part nearest the
        # body) plus the far-away head.
        self.assertEqual(len(plan["floating"]), manifest["truth"]["n_legs"] + 1)
        self.assertTrue(all("Coxa" in n or n == "SpiderHead" for n in plan["floating"]))

    def test_floating_detail_names_gap_and_neighbor(self) -> None:
        manifest = corpus.build("cartoon_spider")
        plan = rig_rigid_assembly.diagnose({"objects": manifest["objects"]})["plan"]
        coxa_entries = [d for d in plan["floating_detail"] if "Coxa" in d["part"]]
        self.assertEqual(len(coxa_entries), manifest["truth"]["n_legs"])
        for entry in coxa_entries:
            self.assertEqual(entry["nearest_part"], "SpiderBody")
            self.assertLess(entry["gap"], manifest["truth"]["body_leg_gap"] + 0.02)
            self.assertGreater(entry["gap"], 0.01)

    def test_bridge_gaps_attaches_legs(self) -> None:
        manifest = corpus.build("cartoon_spider")
        ctx = {"objects": manifest["objects"]}
        result = rig_rigid_assembly.run(ctx, params={"bridge_gaps": 0.12})
        self.assertTrue(result["ok"], result)
        assembly = result["assembly"]
        bridged = [j for j in assembly["joints"] if j["kind"] == "bridged_ball"]
        self.assertEqual(len(bridged), manifest["truth"]["n_legs"])
        self.assertTrue(all(j["parent"] == "SpiderBody" for j in bridged))
        # The head is beyond the bridge cap and stays floating — visibly.
        self.assertEqual(assembly["floating"], ["SpiderHead"])

        verify_report = rig_rigid_assembly.verify(ctx)
        self.assertTrue(verify_report["ok"],
                        [c for c in verify_report["checks"] if not c["ok"]])

    def test_bridged_leg_articulates_from_body(self) -> None:
        manifest = corpus.build("cartoon_spider")
        ctx = {"objects": manifest["objects"]}
        rig_rigid_assembly.run(ctx, params={"bridge_gaps": 0.12})
        rig = bpy.data.objects[ctx["armature"]]

        body = bpy.data.objects["SpiderBody"]
        tibia = bpy.data.objects["Leg0_Tibia"]
        rest_body = _bones.evaluated_verts(body)
        rest_tibia = _bones.evaluated_verts(tibia)

        _bones.pose_rotate(rig, "CTL-Leg0_Coxa", "y", 35.0)
        self.assertGreater(
            float(np.abs(_bones.evaluated_verts(tibia) - rest_tibia).max()), 0.05)
        self.assertLess(
            float(np.abs(_bones.evaluated_verts(body) - rest_body).max()), 1e-5)
        _bones.reset_pose(rig)

    def test_generous_bridge_attaches_head_too(self) -> None:
        manifest = corpus.build("cartoon_spider")
        plan = rig_rigid_assembly.diagnose(
            {"objects": manifest["objects"]}, {"bridge_gaps": 2.0})["plan"]
        self.assertEqual(plan["floating"], [])
        self.assertEqual(len(plan["joints"]), 24 + 1)  # +SpiderHead bridge


class TestChain(BlenderTestCase):

    def test_leg_chain_with_bridged_root(self) -> None:
        corpus.build("cartoon_spider")
        ctx = {"objects": _LEG0}
        report = rig_chain.diagnose(ctx, params={"joint_types": ["ball", "hinge"]})
        self.assertTrue(report["ok"], report)
        joints = report["plan"]["joints"]
        self.assertEqual([j["type"] for j in joints], ["ball", "hinge"])
        # Segments interpenetrate, so both joints come from real contact.
        self.assertTrue(all(j["contact_kind"] != "bridged" for j in joints))

        result = rig_chain.run(ctx, params={"joint_types": ["ball", "hinge"]})
        self.assertTrue(result["ok"], result)
        verify_report = rig_chain.verify(ctx)
        self.assertTrue(verify_report["ok"],
                        [c for c in verify_report["checks"] if not c["ok"]])

    def test_gapped_pair_bridges(self) -> None:
        corpus.build("cartoon_spider")
        # Body -> coxa never touch; chain order says they connect anyway.
        ctx = {"objects": ["SpiderBody", "Leg0_Coxa"]}
        report = rig_chain.diagnose(ctx)
        self.assertTrue(report["ok"], report)
        joint = report["plan"]["joints"][0]
        self.assertEqual(joint["contact_kind"], "bridged")
        self.assertGreater(joint["gap"], 0.01)

        result = rig_chain.run(ctx)
        self.assertTrue(result["ok"], result)
        self.assertTrue(rig_chain.verify(ctx)["ok"])

    def test_chain_composes_into_existing_armature(self) -> None:
        corpus.build("cartoon_spider")
        first = {"objects": _LEG0}
        rig_chain.run(first, params={"name": "Rig.Spider"})

        second = {"objects": ["Leg1_Coxa", "Leg1_Femur", "Leg1_Tibia"]}
        result = rig_chain.run(second, params={"armature": "Rig.Spider"})
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["chain"]["extended_existing"])
        self.assertEqual(second["armature"], "Rig.Spider")

        rig = bpy.data.objects["Rig.Spider"]
        self.assertIn("DEF-Leg0_Tibia", rig.data.bones)
        self.assertIn("DEF-Leg1_Tibia", rig.data.bones)
        self.assertTrue(rig_chain.verify(second)["ok"])

    def test_duplicate_chain_rolls_back(self) -> None:
        corpus.build("cartoon_spider")
        ctx = {"objects": _LEG0}
        rig_chain.run(ctx, params={"name": "Rig.Spider"})
        rig = bpy.data.objects["Rig.Spider"]
        n_bones = len(rig.data.bones)

        again = rig_chain.run({"objects": _LEG0}, params={"armature": "Rig.Spider"})
        self.assertFalse(again["ok"])
        self.assertEqual(again["fail"], "bone_exists")
        self.assertEqual(len(rig.data.bones), n_bones)

    def test_parallel_hinge_needs_hint(self) -> None:
        from tests import fixtures
        fixtures.make_cylinder("RodA", radius=0.1, depth=1.0, axis="z")
        fixtures.make_cylinder("RodB", radius=0.1, depth=1.0, axis="z",
                               location=(0.0, 0.0, 1.0))
        bpy.context.view_layer.update()
        report = rig_chain.diagnose(
            {"objects": ["RodA", "RodB"]}, params={"joint_types": ["hinge"]})
        self.assertFalse(report["ok"])
        self.assertEqual(report["fail"], "ambiguous_axis")

        report = rig_chain.diagnose(
            {"objects": ["RodA", "RodB"]},
            params={"joint_types": ["hinge"], "hinge_axis_hint": "x"})
        self.assertTrue(report["ok"], report)


class TestInspectRouting(BlenderTestCase):

    def test_spider_routes_to_assembly_with_bridge(self) -> None:
        from blrig.skills import inspect_scene

        manifest = corpus.build("cartoon_spider")
        report = inspect_scene.inspect(manifest["objects"])
        structure = report["structure"]
        self.assertEqual(structure["appendage_chains"], manifest["truth"]["n_legs"])
        top = report["suggested"][0]
        self.assertEqual(top["skill"], "rig_rigid_assembly")
        self.assertGreater(top["params"]["bridge_gaps"], 0.05)
        # The alternative (per-leg chains composed into one rig) is offered.
        self.assertIn("rig_chain", [s["skill"] for s in report["suggested"]])

    def test_door_routes_to_hinge(self) -> None:
        from blrig.skills import inspect_scene

        manifest = corpus.build("door_and_frame")
        report = inspect_scene.inspect(manifest["objects"])
        self.assertEqual(report["suggested"][0]["skill"], "rig_hinge")

    def test_wheel_routes_to_wheel(self) -> None:
        from blrig.skills import inspect_scene

        manifest = corpus.build("cart_wheel")
        report = inspect_scene.inspect(manifest["objects"])
        self.assertEqual(report["suggested"][0]["skill"], "rig_wheel")

    def test_gapped_pair_routes_to_chain(self) -> None:
        from blrig.skills import inspect_scene

        corpus.build("cartoon_spider")
        report = inspect_scene.inspect(["SpiderBody", "Leg0_Coxa"])
        self.assertEqual(report["suggested"][0]["skill"], "rig_chain")
        component = next(
            c for c in report["structure"]["components"] if not c["is_main"])
        self.assertLess(component["nearest"]["gap"], 0.1)


class TestWeightHole(BlenderTestCase):

    def test_bound_mesh_without_groups_fails(self) -> None:
        from blrig import _armature
        from blrig.standard import validate_weights
        from tests import fixtures

        rig = _armature.build_armature("Rig", [
            {"name": "root", "head": (0, 0, 0), "tail": (0, 0.5, 0)},
            {"name": "DEF-x", "head": (0, 0, 0), "tail": (0, 0, 1),
             "parent": "root", "use_deform": True},
        ])
        cube = fixtures.make_cube()
        mod = cube.modifiers.new("Armature", type="ARMATURE")
        mod.object = rig

        report = validate_weights(cube, rig)
        self.assertFalse(report["ok"])
        self.assertIn("E_NO_DEFORM_GROUPS", {e["rule"] for e in report["errors"]})
