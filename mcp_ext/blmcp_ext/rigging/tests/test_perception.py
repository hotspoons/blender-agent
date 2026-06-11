# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Phase 1 property tests: the perception layer against exact-answer fixtures.
Everything downstream trusts these functions — overtest them.
"""

__all__ = ()

import json
import math

from tests.bl_test_base import BlenderTestCase
from tests import fixtures

from blrig import perception


class TestLooseParts(BlenderTestCase):

    def test_single_cube(self) -> None:
        obj = fixtures.make_cube(size=2.0)
        parts = perception.loose_parts(obj)
        self.assertEqual(len(parts), 1)
        p = parts[0]
        self.assertEqual(p["n_verts"], 8)
        self.assertEqual(p["n_faces"], 12)  # loop triangles
        self.assertTrue(p["is_closed"])
        self.assertAlmostEqual(p["volume"], 8.0, places=5)
        self.assertAlmostEqual(p["surface_area"], 24.0, places=5)
        for c in p["centroid"]:
            self.assertAlmostEqual(c, 0.0, places=6)

    def test_mirrored_pair_two_parts(self) -> None:
        obj = fixtures.make_mirrored_pair(offset=2.0)
        parts = perception.loose_parts(obj)
        self.assertEqual(len(parts), 2)
        for p in parts:
            self.assertEqual(p["n_verts"], 8)
            self.assertTrue(p["is_closed"])
            self.assertAlmostEqual(p["volume"], 1.0, places=5)
        xs = sorted(p["centroid"][0] for p in parts)
        self.assertAlmostEqual(xs[0], -2.0, places=5)
        self.assertAlmostEqual(xs[1], 2.0, places=5)

    def test_open_part_flagged(self) -> None:
        obj = fixtures.make_broken_cube(kind="open")
        parts = perception.loose_parts(obj)
        self.assertEqual(len(parts), 1)
        self.assertFalse(parts[0]["is_closed"])

    def test_world_transform_respected(self) -> None:
        obj = fixtures.make_cube(size=2.0, location=(10.0, 0.0, 0.0))
        import bpy
        bpy.context.view_layer.update()
        parts = perception.loose_parts(obj)
        self.assertAlmostEqual(parts[0]["centroid"][0], 10.0, places=5)

    def test_json_serializable(self) -> None:
        obj = fixtures.make_mirrored_pair()
        json.dumps(perception.loose_parts(obj))


class TestPartObb(BlenderTestCase):

    def test_axis_aligned_box(self) -> None:
        obj = fixtures.make_box(dims=(4.0, 2.0, 1.0))
        obb = perception.part_obb(obj)
        self.assertAlmostEqual(obb["half_extents"][0], 2.0, places=5)
        self.assertAlmostEqual(obb["half_extents"][1], 1.0, places=5)
        self.assertAlmostEqual(obb["half_extents"][2], 0.5, places=5)
        self.assertAlmostEqual(abs(obb["axes"][0][0]), 1.0, places=5)
        self.assertAlmostEqual(obb["volume"], 8.0, places=4)

    def test_rotated_box_recovers_extents(self) -> None:
        obj = fixtures.make_box(dims=(4.0, 2.0, 1.0), rotation=(0.3, 0.7, 1.1))
        obb = perception.part_obb(obj)
        self.assertAlmostEqual(obb["half_extents"][0], 2.0, places=4)
        self.assertAlmostEqual(obb["half_extents"][1], 1.0, places=4)
        self.assertAlmostEqual(obb["half_extents"][2], 0.5, places=4)

    def test_per_part(self) -> None:
        obj = fixtures.make_mirrored_pair(offset=3.0)
        parts = perception.loose_parts(obj)
        obb = perception.part_obb(obj, parts[0])
        for h in obb["half_extents"]:
            self.assertAlmostEqual(h, 0.5, places=5)
        self.assertAlmostEqual(abs(obb["center"][0]), 3.0, places=5)

    def test_right_handed(self) -> None:
        import numpy as np
        obj = fixtures.make_box(dims=(3.0, 2.0, 1.0), rotation=(0.5, 0.2, 0.9))
        obb = perception.part_obb(obj)
        self.assertGreater(np.linalg.det(np.asarray(obb["axes"])), 0.0)


class TestSymmetryPlane(BlenderTestCase):

    def test_cube_symmetric(self) -> None:
        obj = fixtures.make_cube()
        result = perception.symmetry_plane(obj)
        self.assertTrue(result["found"])
        self.assertLess(result["asymmetry_pct"], 0.5)

    def test_mirrored_pair_finds_x_plane(self) -> None:
        obj = fixtures.make_mirrored_pair(offset=2.0)
        result = perception.symmetry_plane(obj)
        self.assertTrue(result["found"])
        normal = result["normal"]
        self.assertAlmostEqual(abs(normal[0]), 1.0, places=3)
        # Plane passes through x = 0.
        x0 = sum(p * n for p, n in zip(result["point"], normal)) / normal[0]
        self.assertAlmostEqual(x0, 0.0, places=3)

    def test_asymmetric_rejected(self) -> None:
        obj = fixtures.make_asymmetric_cube()
        result = perception.symmetry_plane(obj)
        self.assertGreater(result["asymmetry_pct"], 2.0)
        self.assertFalse(result["found"])

    def test_structured_not_bool(self) -> None:
        obj = fixtures.make_cube()
        result = perception.symmetry_plane(obj)
        for key in ("found", "point", "normal", "asymmetry_pct", "candidates"):
            self.assertIn(key, result)


class TestCrossSections(BlenderTestCase):

    def test_cylinder_area_constant(self) -> None:
        radius = 0.5
        obj = fixtures.make_cylinder(radius=radius, depth=2.0, axis="z")
        sections = perception.cross_sections(obj, axis="z", n=8)
        self.assertEqual(len(sections), 8)
        expected = math.pi * radius * radius
        for s in sections:
            # 64-gon area is ~0.16% under the circle; allow 1%.
            self.assertAlmostEqual(s["area"], expected, delta=expected * 0.01)
            self.assertAlmostEqual(s["centroid"][0], 0.0, places=4)
            self.assertAlmostEqual(s["centroid"][1], 0.0, places=4)

    def test_positive_area_sign(self) -> None:
        obj = fixtures.make_cylinder(radius=0.5, depth=2.0, axis="z")
        for s in perception.cross_sections(obj, axis="z", n=4):
            self.assertGreater(s["area"], 0.0)

    def test_limb_waist_minimum_at_center(self) -> None:
        obj = fixtures.make_tapered_limb(length=4.0)
        sections = perception.cross_sections(obj, axis="z", n=21)
        areas = [s["area"] for s in sections]
        min_index = areas.index(min(areas))
        # Waist is at t = 0.5 -> index 10 of 21; allow one step of slack.
        self.assertIn(min_index, (9, 10, 11))

    def test_axis_as_vector(self) -> None:
        obj = fixtures.make_cylinder(radius=0.5, depth=2.0, axis="x")
        sections = perception.cross_sections(obj, axis=(1.0, 0.0, 0.0), n=4)
        expected = math.pi * 0.25
        for s in sections:
            self.assertAlmostEqual(s["area"], expected, delta=expected * 0.01)

    def test_offsets_monotonic(self) -> None:
        obj = fixtures.make_cylinder()
        sections = perception.cross_sections(obj, axis="z", n=6)
        offsets = [s["offset"] for s in sections]
        self.assertEqual(offsets, sorted(offsets))
        self.assertGreater(offsets[0], 0.0)
        self.assertLess(offsets[-1], 2.0)


class TestPointInside(BlenderTestCase):

    def test_cube(self) -> None:
        obj = fixtures.make_cube(size=2.0)
        self.assertTrue(perception.point_inside(obj, (0.0, 0.0, 0.0)))
        self.assertTrue(perception.point_inside(obj, (0.9, 0.9, 0.9)))
        self.assertFalse(perception.point_inside(obj, (1.5, 0.0, 0.0)))
        self.assertFalse(perception.point_inside(obj, (0.0, 0.0, 5.0)))

    def test_sphere(self) -> None:
        obj = fixtures.make_sphere(radius=1.0)
        self.assertTrue(perception.point_inside(obj, (0.0, 0.0, 0.0)))
        self.assertFalse(perception.point_inside(obj, (0.0, 0.0, 1.05)))

    def test_batch(self) -> None:
        obj = fixtures.make_cube(size=2.0)
        result = perception.points_inside(obj, [(0.0, 0.0, 0.0), (3.0, 0.0, 0.0)])
        self.assertEqual(result, [True, False])

    def test_translated_object(self) -> None:
        import bpy
        obj = fixtures.make_cube(size=2.0, location=(5.0, 5.0, 5.0))
        bpy.context.view_layer.update()
        self.assertTrue(perception.point_inside(obj, (5.0, 5.0, 5.0)))
        self.assertFalse(perception.point_inside(obj, (0.0, 0.0, 0.0)))


class TestContactGraph(BlenderTestCase):

    def test_touching_cubes(self) -> None:
        import bpy
        a = fixtures.make_cube("A", size=1.0, location=(0.0, 0.0, 0.0))
        b = fixtures.make_cube("B", size=1.0, location=(1.0, 0.0, 0.0))  # faces meet at x=0.5
        bpy.context.view_layer.update()
        graph = perception.contact_graph([a, b])
        self.assertEqual(len(graph["edges"]), 1)
        edge = graph["edges"][0]
        self.assertAlmostEqual(edge["centroid"][0], 0.5, places=2)
        self.assertEqual(graph["n_components"], 1)

    def test_separated_cubes_no_edge(self) -> None:
        import bpy
        a = fixtures.make_cube("A", size=1.0, location=(0.0, 0.0, 0.0))
        b = fixtures.make_cube("B", size=1.0, location=(5.0, 0.0, 0.0))
        bpy.context.view_layer.update()
        graph = perception.contact_graph([a, b])
        self.assertEqual(len(graph["edges"]), 0)
        self.assertEqual(graph["n_components"], 2)

    def test_small_gap_proximity(self) -> None:
        import bpy
        a = fixtures.make_cube("A", size=1.0, location=(0.0, 0.0, 0.0))
        b = fixtures.make_cube("B", size=1.0, location=(1.001, 0.0, 0.0))
        bpy.context.view_layer.update()
        graph = perception.contact_graph([a, b], tol=0.01)
        self.assertEqual(len(graph["edges"]), 1)
        self.assertEqual(graph["edges"][0]["kind"], "proximity")
        self.assertLessEqual(graph["edges"][0]["max_gap"], 0.01)

    def test_intersecting_cubes(self) -> None:
        import bpy
        a = fixtures.make_cube("A", size=1.0, location=(0.0, 0.0, 0.0))
        b = fixtures.make_cube("B", size=1.0, location=(0.8, 0.0, 0.0))
        bpy.context.view_layer.update()
        graph = perception.contact_graph([a, b])
        self.assertEqual(len(graph["edges"]), 1)
        self.assertEqual(graph["edges"][0]["kind"], "intersect")

    def test_loose_parts_as_items(self) -> None:
        obj = fixtures.make_mirrored_pair(offset=0.5)  # cubes touch at x=0
        parts = perception.loose_parts(obj)
        graph = perception.contact_graph([(obj, parts[0]), (obj, parts[1])])
        self.assertEqual(len(graph["edges"]), 1)

    def test_chain_components(self) -> None:
        import bpy
        a = fixtures.make_cube("A", size=1.0, location=(0.0, 0.0, 0.0))
        b = fixtures.make_cube("B", size=1.0, location=(1.0, 0.0, 0.0))
        c = fixtures.make_cube("C", size=1.0, location=(2.0, 0.0, 0.0))
        d = fixtures.make_cube("D", size=1.0, location=(9.0, 0.0, 0.0))
        bpy.context.view_layer.update()
        graph = perception.contact_graph([a, b, c, d])
        self.assertEqual(len(graph["edges"]), 2)
        self.assertEqual(graph["n_components"], 2)


class TestMeshHealth(BlenderTestCase):

    def test_clean_cube_ok(self) -> None:
        report = perception.mesh_health(fixtures.make_cube())
        self.assertTrue(report["ok"])
        self.assertEqual(report["issues"], [])
        self.assertTrue(report["is_closed"])

    def test_open_cube(self) -> None:
        report = perception.mesh_health(fixtures.make_broken_cube(kind="open"))
        self.assertFalse(report["ok"])
        self.assertIn("boundary_edges", report["issues"])
        self.assertFalse(report["is_closed"])

    def test_degenerate_face(self) -> None:
        report = perception.mesh_health(fixtures.make_broken_cube(kind="degenerate"))
        self.assertFalse(report["ok"])
        self.assertIn("degenerate_faces", report["issues"])

    def test_duplicate_verts(self) -> None:
        report = perception.mesh_health(fixtures.make_broken_cube(kind="duplicates"))
        self.assertFalse(report["ok"])
        self.assertIn("duplicate_verts", report["issues"])

    def test_unapplied_scale(self) -> None:
        import bpy
        obj = fixtures.make_broken_cube(kind="scaled")
        bpy.context.view_layer.update()
        report = perception.mesh_health(obj)
        self.assertFalse(report["ok"])
        self.assertIn("unapplied_scale", report["issues"])
        self.assertIn("non_uniform_scale", report["issues"])

    def test_json_serializable(self) -> None:
        json.dumps(perception.mesh_health(fixtures.make_cube()))
