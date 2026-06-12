# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
The appendage/assembly path for radially-legged creatures of ANY
configuration. A general parametric asset (corpus.legged_creature)
stands in for spiders, crabs, hexapods, ants, etc.; the tests assert
invariants computed from the asset's parameters, never a memorised
layout. This is the regression cover for the disconnected-component bug
(legs that clear the body must keep their internal joints and be
bridgeable) and for rig_chain on ball-jointed appendages.

Configs span leg counts (4/6/8), segment counts (2/3), with and without
a floating detail part - so a fix has to hold for the family, not one
creature.
"""

__all__ = ()

import bpy
import numpy as np

import corpus

from tests.bl_test_base import BlenderTestCase

from blrig.skills import _bones, rig_chain, rig_rigid_assembly

# Diverse gapped, multi-segment creatures - the legs clear the body, so
# every one exercises component bridging. Each is (label, kwargs).
_GAPPED_CONFIGS = (
    ("arachnid_8x3", dict(name="Arachnid", n_legs=8, leg_segments=3, leg_clearance=0.07,
                          detail={"name": "Head", "radius": 0.15, "offset": (0.0, 1.0, 0.9)})),
    ("crab_8x2", dict(name="Crab", n_legs=8, leg_segments=2, leg_clearance=0.05,
                      body_radius=0.7)),
    ("hexapod_6x3", dict(name="Hexapod", n_legs=6, leg_segments=3, leg_clearance=0.06,
                         detail={"name": "Head", "radius": 0.12, "offset": (0.0, 0.9, 0.7)})),
    ("quadruped_4x3", dict(name="Critter", n_legs=4, leg_segments=3, leg_clearance=0.08)),
)


class TestLeggedAssembly(BlenderTestCase):

    def test_components_keep_internal_joints(self) -> None:
        """
        The original bug: 0 joints, everything floating. Legs never touch
        the body, but each leg's internal contacts must become joints -
        and that must hold for any leg/segment count.
        """
        for label, kwargs in _GAPPED_CONFIGS:
            with self.subTest(label):
                self.setUp()  # fresh scene per config
                manifest = corpus.legged_creature(**kwargs)
                truth = manifest["truth"]
                report = rig_rigid_assembly.diagnose({"objects": manifest["objects"]})
                self.assertTrue(report["ok"], report)
                plan = report["plan"]
                self.assertEqual(len(plan["joints"]), truth["leg_internal_joints"])
                # One anchor per leg (re-rooted at the segment nearest the
                # body) plus the floating detail, if any.
                expected_floating = truth["n_legs"] + (1 if truth["has_detail"] else 0)
                self.assertEqual(len(plan["floating"]), expected_floating)
                anchors = set(truth["first_segments"])
                if truth["detail"]:
                    anchors.add(truth["detail"])
                self.assertEqual(set(plan["floating"]), anchors)

    def test_floating_detail_names_gap_and_neighbor(self) -> None:
        for label, kwargs in _GAPPED_CONFIGS:
            with self.subTest(label):
                self.setUp()
                manifest = corpus.legged_creature(**kwargs)
                truth = manifest["truth"]
                plan = rig_rigid_assembly.diagnose({"objects": manifest["objects"]})["plan"]
                roots = set(truth["first_segments"])
                root_entries = [d for d in plan["floating_detail"] if d["part"] in roots]
                self.assertEqual(len(root_entries), truth["n_legs"])
                for entry in root_entries:
                    self.assertEqual(entry["nearest_part"], truth["body"])
                    self.assertLess(entry["gap"], truth["body_leg_gap"] + 0.02)
                    self.assertGreater(entry["gap"], 0.01)

    def test_bridge_gaps_attaches_legs(self) -> None:
        for label, kwargs in _GAPPED_CONFIGS:
            with self.subTest(label):
                self.setUp()
                manifest = corpus.legged_creature(**kwargs)
                truth = manifest["truth"]
                ctx = {"objects": manifest["objects"]}
                # Bridge cap above the leg gap but below the detail's gap.
                result = rig_rigid_assembly.run(ctx, params={"bridge_gaps": 0.15})
                self.assertTrue(result["ok"], result)
                assembly = result["assembly"]
                bridged = [j for j in assembly["joints"] if j["kind"] == "bridged_ball"]
                self.assertEqual(len(bridged), truth["n_legs"])
                self.assertTrue(all(j["parent"] == truth["body"] for j in bridged))
                # A far floating detail stays floating - visibly.
                if truth["detail"]:
                    self.assertEqual(assembly["floating"], [truth["detail"]])
                else:
                    self.assertEqual(assembly["floating"], [])
                verify_report = rig_rigid_assembly.verify(ctx)
                self.assertTrue(verify_report["ok"],
                                [c for c in verify_report["checks"] if not c["ok"]])

    def test_bridged_leg_articulates_from_body(self) -> None:
        manifest = corpus.legged_creature(
            name="Arachnid", n_legs=8, leg_segments=3, leg_clearance=0.07)
        truth = manifest["truth"]
        ctx = {"objects": manifest["objects"]}
        rig_rigid_assembly.run(ctx, params={"bridge_gaps": 0.15})
        rig = bpy.data.objects[ctx["armature"]]

        body = bpy.data.objects[truth["body"]]
        leg0 = truth["legs"][0]
        tip = bpy.data.objects[leg0[-1]]
        rest_body = _bones.evaluated_verts(body)
        rest_tip = _bones.evaluated_verts(tip)

        _bones.pose_rotate(rig, "CTL-" + leg0[0], "y", 35.0)
        self.assertGreater(
            float(np.abs(_bones.evaluated_verts(tip) - rest_tip).max()), 0.05)
        self.assertLess(
            float(np.abs(_bones.evaluated_verts(body) - rest_body).max()), 1e-5)
        _bones.reset_pose(rig)

    def test_generous_bridge_attaches_detail_too(self) -> None:
        manifest = corpus.legged_creature(
            name="Arachnid", n_legs=8, leg_segments=3, leg_clearance=0.07,
            detail={"name": "Head", "radius": 0.15, "offset": (0.0, 1.0, 0.9)})
        truth = manifest["truth"]
        plan = rig_rigid_assembly.diagnose(
            {"objects": manifest["objects"]}, {"bridge_gaps": 4.0})["plan"]
        self.assertEqual(plan["floating"], [])
        # Internal joints + one bridge per leg + one for the detail.
        self.assertEqual(
            len(plan["joints"]),
            truth["leg_internal_joints"] + truth["n_legs"] + 1)


class TestChain(BlenderTestCase):

    def test_leg_chain_with_bridged_root(self) -> None:
        manifest = corpus.legged_creature(name="Arachnid", n_legs=8, leg_segments=3,
                                          leg_clearance=0.07)
        leg0 = manifest["truth"]["legs"][0]
        ctx = {"objects": leg0}
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
        manifest = corpus.legged_creature(name="Arachnid", n_legs=8, leg_segments=3,
                                          leg_clearance=0.07)
        truth = manifest["truth"]
        # Body -> first leg segment never touch; chain order says they connect.
        ctx = {"objects": [truth["body"], truth["first_segments"][0]]}
        report = rig_chain.diagnose(ctx)
        self.assertTrue(report["ok"], report)
        joint = report["plan"]["joints"][0]
        self.assertEqual(joint["contact_kind"], "bridged")
        self.assertGreater(joint["gap"], 0.01)

        result = rig_chain.run(ctx)
        self.assertTrue(result["ok"], result)
        self.assertTrue(rig_chain.verify(ctx)["ok"])

    def test_chain_composes_into_existing_armature(self) -> None:
        manifest = corpus.legged_creature(name="Arachnid", n_legs=8, leg_segments=3,
                                          leg_clearance=0.07)
        legs = manifest["truth"]["legs"]
        rig_chain.run({"objects": legs[0]}, params={"name": "Rig.Creature"})

        second = {"objects": legs[1]}
        result = rig_chain.run(second, params={"armature": "Rig.Creature"})
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["chain"]["extended_existing"])
        self.assertEqual(second["armature"], "Rig.Creature")

        rig = bpy.data.objects["Rig.Creature"]
        self.assertIn("DEF-" + legs[0][-1], rig.data.bones)
        self.assertIn("DEF-" + legs[1][-1], rig.data.bones)
        self.assertTrue(rig_chain.verify(second)["ok"])

    def test_duplicate_chain_rolls_back(self) -> None:
        manifest = corpus.legged_creature(name="Arachnid", n_legs=8, leg_segments=3,
                                          leg_clearance=0.07)
        leg0 = manifest["truth"]["legs"][0]
        rig_chain.run({"objects": leg0}, params={"name": "Rig.Creature"})
        rig = bpy.data.objects["Rig.Creature"]
        n_bones = len(rig.data.bones)

        again = rig_chain.run({"objects": leg0}, params={"armature": "Rig.Creature"})
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

    def test_legged_creature_routes_to_assembly_with_bridge(self) -> None:
        from blrig.skills import inspect_scene

        for label, kwargs in _GAPPED_CONFIGS:
            with self.subTest(label):
                self.setUp()
                manifest = corpus.legged_creature(**kwargs)
                truth = manifest["truth"]
                report = inspect_scene.inspect(manifest["objects"])
                structure = report["structure"]
                self.assertEqual(structure["appendage_chains"], truth["n_legs"])
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

        manifest = corpus.legged_creature(name="Arachnid", n_legs=8, leg_segments=3,
                                          leg_clearance=0.07)
        truth = manifest["truth"]
        report = inspect_scene.inspect([truth["body"], truth["first_segments"][0]])
        self.assertEqual(report["suggested"][0]["skill"], "rig_chain")
        component = next(
            c for c in report["structure"]["components"] if not c["is_main"])
        self.assertLess(component["nearest"]["gap"], 0.1)

    def test_compact_by_default(self) -> None:
        """
        Production feedback (2026-06-12): a 40-part inspect buried the
        routing under per-object OBB dumps and the agent bailed to raw
        bpy. Suggestions lead; objects are one line each.
        """
        from blrig.skills import inspect_scene

        manifest = corpus.legged_creature(name="Arachnid", n_legs=8, leg_segments=3,
                                          leg_clearance=0.07)
        body = manifest["truth"]["body"]
        report = inspect_scene.inspect(manifest["objects"])
        self.assertEqual(list(report)[:2], ["suggested", "next"])
        self.assertIn("rig_rigid_assembly", report["next"])
        summary = report["objects"][body]
        self.assertEqual(set(summary),
                         {"health", "size", "n_loose_parts", "symmetric"})
        self.assertNotIn("contact_graph", report)
        self.assertGreater(report["contacts"]["n_edges"], 0)

    def test_detail_restores_full_perception(self) -> None:
        from blrig.skills import inspect_scene

        manifest = corpus.legged_creature(name="Arachnid", n_legs=8, leg_segments=3,
                                          leg_clearance=0.07)
        body = manifest["truth"]["body"]
        report = inspect_scene.inspect(manifest["objects"], detail=True)
        self.assertIn("axes", report["objects"][body]["obb"])
        self.assertTrue(report["contact_graph"]["edges"])


class TestAuto(BlenderTestCase):

    def test_legged_creature_in_one_call(self) -> None:
        from blrig.skills import auto_rig

        manifest = corpus.legged_creature(name="Hexapod", n_legs=6, leg_segments=3,
                                          leg_clearance=0.06)
        result = auto_rig.auto(manifest["objects"])
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["skill"], "rig_rigid_assembly")
        self.assertIn(result["armature"], bpy.data.objects)
        self.assertEqual([s["stage"] for s in result["stages"]],
                         ["inspect", "diagnose", "run", "verify"])
        # bridge_gaps was inherited from the inspect suggestion.
        self.assertIn("bridge_gaps", result["stages"][0]["params"])

    def test_door_in_one_call(self) -> None:
        from blrig.skills import auto_rig

        manifest = corpus.build("door_and_frame")
        result = auto_rig.auto(manifest["objects"])
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["skill"], "rig_hinge")

    def test_skill_override_keeps_suggested_defaults(self) -> None:
        from blrig.skills import auto_rig

        manifest = corpus.legged_creature(name="Arachnid", n_legs=8, leg_segments=3,
                                          leg_clearance=0.07)
        leg0 = manifest["truth"]["legs"][0]
        result = auto_rig.auto(
            leg0, skill="rig_chain",
            params={"joint_types": ["ball", "hinge"]})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["skill"], "rig_chain")
        self.assertEqual(result["stages"][0]["reason"], "caller override")

    def test_missing_object_fails_fast(self) -> None:
        from blrig.skills import auto_rig

        result = auto_rig.auto(["Nonexistent"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["fail"], "object_not_found")
        self.assertEqual(result["missing"], ["Nonexistent"])


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
