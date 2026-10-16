# SPDX-License-Identifier: LGPL-2.1-or-later

"""Topology-preserving transient planar XY projection, not material repair."""

import math

import Arch
import ArchComponent
import FreeCAD as App
import Part
from bimtests import TestArchAreaDiagnostics as area_tests
from bimtests.TestArchBase import TestArchBase


class TestArchPlanarProjection(TestArchBase):
    def project(self, face):
        return ArchComponent._project_planar_face_to_xy(face)

    def assert_projection(self, face, expected_area, wires=2, tolerance=1e-7):
        before = face.exportBrepToString()
        placement = face.Placement
        max_tolerance = face.getTolerance(1)
        mapping = face.ElementMap
        projected = self.project(face)
        self.assertIsNotNone(projected)
        self.assertTrue(projected.isValid())
        self.assertEqual(len(projected.Faces), 1)
        self.assertEqual(len(projected.Wires), wires)
        self.assertTrue(all(wire.isClosed() for wire in projected.Wires))
        self.assertAlmostEqual(projected.getSurfaceArea(), expected_area, delta=tolerance)
        self.assertAlmostEqual(projected.BoundBox.ZMin, 0, delta=1e-7)
        self.assertAlmostEqual(projected.BoundBox.ZMax, 0, delta=1e-7)
        self.assertEqual(projected.ElementMapSize, 0)
        self.assertEqual(face.Placement, placement)
        self.assertEqual(face.getTolerance(1), max_tolerance)
        self.assertEqual(face.ElementMap, mapping)
        self.assertEqual(face.exportBrepToString(), before)
        return projected

    @staticmethod
    def curved_holes():
        outer = Part.makePlane(30, 20)
        holes = [Part.Face(Part.Wire(Part.makeCircle(radius, App.Vector(x, 10, 0))))
                 for x, radius in ((8, 2), (22, 3))]
        return outer.cut(Part.makeCompound(holes)).Faces[0]

    def test_original_toleranced_face(self):
        face = area_tests.TestArchAreaDiagnostics.projection_face()
        face.ElementMap = {"OriginalFace": "OriginalFace"}
        self.assertGreater(face.ElementMapSize, 0)
        projected = self.assert_projection(face, 20000)
        self.assertEqual(len(projected.Edges), 8)
        self.assertAlmostEqual(projected.Faces[0].OuterWire.Length, 900, delta=1e-7)

    def test_placed_sloping_curved_holes_and_reversal(self):
        face = self.curved_holes()
        face.Placement = App.Placement(
            App.Vector(120, -80, 75), App.Rotation(App.Vector(1, 0, 0), 60))
        expected_area = (600 - 13 * math.pi) * 0.5
        for reversed_face in (False, True):
            with self.subTest(reversed=reversed_face):
                if reversed_face:
                    face.reverse()
                projected = self.assert_projection(face, expected_area, wires=3)
                self.assertAlmostEqual(projected.Faces[0].OuterWire.Length, 80, delta=1e-7)
                self.assertAlmostEqual(projected.BoundBox.XMin, 120, delta=1e-7)
                self.assertAlmostEqual(projected.BoundBox.XMax, 150, delta=1e-7)
                self.assertAlmostEqual(projected.BoundBox.YMin, -80, delta=1e-7)
                self.assertAlmostEqual(projected.BoundBox.YMax, -70, delta=1e-7)

    def test_placed_planar_bspline(self):
        face = self.curved_holes().toNurbs().Faces[0]
        self.assertEqual(face.Surface.TypeId, "Part::GeomBSplineSurface")
        face.Placement = App.Placement(
            App.Vector(70, -40, 20), App.Rotation(App.Vector(0, 1, 0), 40))
        self.assert_projection(face, (600 - 13 * math.pi) * math.cos(math.radians(40)),
                               wires=3)

    def test_vertical_and_near_vertical(self):
        vertical = Part.Face(Part.makePolygon([App.Vector(0, 0, 0), App.Vector(10, 0, 0),
                                              App.Vector(10, 0, 20), App.Vector(0, 0, 20),
                                              App.Vector(0, 0, 0)]))
        self.assertIsNone(self.project(vertical))
        sloped = Part.makePlane(10, 20)
        sloped.rotate(App.Vector(), App.Vector(1, 0, 0), 89.999)
        expected = 200 * math.cos(math.radians(89.999))
        self.assert_projection(sloped, expected, wires=1, tolerance=1e-8)

    def test_union_preserves_holes_and_overlap(self):
        face = self.curved_holes()
        upper = face.copy()
        upper.translate(App.Vector(0, 0, 90))
        projected = self.project(face)
        coincident = ArchComponent._make_projected_horizontal_area_face(
            [projected, self.project(upper)])
        self.assertAlmostEqual(coincident.getSurfaceArea(), 600 - 13 * math.pi, delta=1e-7)
        self.assertEqual(len(coincident.Wires), 3)
        # Fill only the left hole with an independently projected face.
        disk = Part.Face(Part.Wire(Part.makeCircle(2, App.Vector(8, 10, 50))))
        union = ArchComponent._make_projected_horizontal_area_face(
            [projected, self.project(disk)])
        self.assertAlmostEqual(union.getSurfaceArea(), 600 - 9 * math.pi, delta=1e-7)
        self.assertEqual(len(union.Wires), 2)
        remote = face.copy()
        remote.translate(App.Vector(100, 0, 0))
        disjoint = ArchComponent._make_projected_horizontal_area_face(
            [projected, self.project(remote)])
        self.assertEqual(len(disjoint.Faces), 2)
        self.assertAlmostEqual(disjoint.getSurfaceArea(), 2 * (600 - 13 * math.pi), delta=1e-7)

    def test_curved_outline_native_quantities(self):
        disk = Part.Face(Part.Wire(Part.makeCircle(10)))
        disk.rotate(App.Vector(), App.Vector(1, 0, 0), 60)
        base = self.document.addObject("Part::Feature", "Disk")
        base.Shape = disk
        obj = Arch.makeComponent(base)
        self.document.recompute()
        self.assertAlmostEqual(obj.HorizontalArea.Value, 50 * math.pi, delta=1e-7)
        # Independent analytic ellipse curve, rather than the transformed spline.
        ellipse = Part.Ellipse()
        ellipse.MajorRadius = 10
        ellipse.MinorRadius = 5
        self.assertAlmostEqual(obj.PerimeterLength.Value, ellipse.length(), delta=1e-7)

    def test_nonplanar_is_not_affinely_flattened(self):
        cylinder = Part.makeCylinder(5, 10)
        with self.assertRaises(ValueError):
            self.project(cylinder.Faces[0])

    def test_native_vertical_edit_clears_projected_quantities(self):
        base = self.document.addObject("Part::Feature", "Plane")
        base.Shape = Part.makePlane(10, 20)
        obj = Arch.makeComponent(base)
        self.document.recompute()
        self.assertAlmostEqual(obj.HorizontalArea.Value, 200)
        base.Shape = Part.Face(Part.makePolygon([
            App.Vector(0, 0, 0), App.Vector(10, 0, 0), App.Vector(10, 0, 20),
            App.Vector(0, 0, 20), App.Vector(0, 0, 0)]))
        self.document.recompute()
        self.assertEqual(obj.HorizontalArea.Value, 0)
        self.assertEqual(obj.PerimeterLength.Value, 0)
        self.assertAlmostEqual(obj.VerticalArea.Value, 200)
