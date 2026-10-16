# SPDX-License-Identifier: LGPL-2.1-or-later

"""Native bearing location changes must not require a References workaround."""

import unittest
from pathlib import Path
import tempfile

import FreeCAD as App
import ObjectsFem
import Part


class TestBearingLocation(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("BearingLocation")
        self.cylinder = self.doc.addObject("Part::Cylinder", "Cylinder")
        self.cylinder.Radius, self.cylinder.Height = 7, 11
        self.plane = self.doc.addObject("Part::Box", "LocationPlane")
        self.plane.Placement.Base = App.Vector(0, 0, 17)
        self.doc.recompute()
        self.bearing = ObjectsFem.makeConstraintBearing(self.doc, "Bearing")
        self.bearing.References = [(self.cylinder, ["Face1"])]

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def assert_point(self, expected):
        self.assertLess((self.bearing.BasePoint - expected).Length, 1e-7)

    def test_location_updates_without_reference_refresh(self):
        self.bearing.Location = (self.plane, ["Face5"])
        print("LOCATION_BASEPOINT:", self.bearing.BasePoint)
        self.assert_point(App.Vector(0, 0, 17))

    def test_distance_updates_without_reference_refresh(self):
        self.bearing.Location = (self.plane, ["Face5"])
        # Establish the legacy reference-refresh control before changing Dist.
        self.bearing.References = [(self.cylinder, ["Face1"])]
        self.assert_point(App.Vector(0, 0, 17))
        self.bearing.Dist = 2
        print("DISTANCE_BASEPOINT:", self.bearing.BasePoint)
        self.assert_point(App.Vector(0, 0, 15))

    def locate(self):
        self.bearing.Location = (self.plane, ["Face5"])

    def assert_invalid(self, message):
        self.doc.recompute()
        self.assertIn("Invalid", self.bearing.State)
        self.assertRegex(self.bearing.getStatusString(), message)
        self.assertEqual(self.bearing.Radius, 0)

    def test_signed_distance_and_property_order(self):
        self.bearing.Dist = 2
        self.locate()
        self.assert_point(App.Vector(0, 0, 15))
        for distance, expected in ((-2, 19), (0, 17), (2, 15)):
            self.bearing.Dist = distance
            self.assert_point(App.Vector(0, 0, expected))

    def test_clear_location_restores_reference_default(self):
        default = self.bearing.BasePoint
        self.locate()
        self.bearing.Dist = 2
        self.bearing.Location = None
        self.assert_point(default)
        self.bearing.Dist = -2
        self.assert_point(default)

    def test_plane_through_reference_base_preserves_legacy_offset(self):
        self.plane.Placement.Base = App.Vector(0, 0, self.bearing.BasePoint.z)
        self.doc.recompute()
        default = self.bearing.BasePoint
        self.locate()
        self.bearing.Dist = 2
        self.assert_point(default)

    def test_oblique_plane_distance_is_normal_not_axial(self):
        self.plane.Placement = App.Placement(
            App.Vector(0, 0, 17), App.Rotation(App.Vector(0, 1, 0), 45))
        self.doc.recompute()
        self.locate()
        self.bearing.Dist = 2
        self.assert_point(App.Vector(0, 0, 17 - 2 * 2**0.5))

    def test_distance_toward_reference_base_is_orientation_independent(self):
        self.plane.Placement = App.Placement(
            App.Vector(0, 0, 17), App.Rotation(App.Vector(1, 0, 0), 180))
        self.doc.recompute()
        self.locate()
        self.bearing.Dist = 2
        self.assert_point(App.Vector(0, 0, 15))
        self.plane.Placement.Base = App.Vector(0, 0, -17)
        self.doc.recompute()
        self.assert_point(App.Vector(0, 0, -15))

    def test_linear_edge_location(self):
        edge = self.doc.addObject("Part::Feature", "Line")
        edge.Shape = Part.makeLine(App.Vector(0, 0, 17), App.Vector(3, 0, 17))
        self.bearing.Location = (edge, ["Edge1"])
        self.assert_point(App.Vector(0, 0, 17))
        self.bearing.Dist = 2
        self.assert_point(App.Vector(0, 0, 15))

    def test_parallel_edge_rejected(self):
        edge = self.doc.addObject("Part::Feature", "Line")
        edge.Shape = Part.makeLine(App.Vector(1, 0, 0), App.Vector(1, 0, 10))
        self.bearing.Location = (edge, ["Edge1"])
        self.assert_invalid("Location.*parallel")

    def test_curved_edge_rejected(self):
        edge = self.doc.addObject("Part::Feature", "Circle")
        edge.Shape = Part.makeCircle(3, App.Vector(0, 0, 17))
        self.bearing.Location = (edge, ["Edge1"])
        self.assert_invalid("Location.*planar face or linear edge")

    def test_parallel_plane_rejected(self):
        for offset in (0, 10):
            with self.subTest(offset=offset):
                self.plane.Placement.Base = App.Vector(offset, 0, 17)
                self.bearing.Location = (self.plane, ["Face1"])
                self.assert_invalid("Location.*intersect")

    def test_invalid_location_types_and_recovery(self):
        cases = ((self.plane, ["Vertex1"]), (self.plane, [""]),
                 (self.cylinder, ["Face1"]), (self.cylinder, ["Edge1"]),
                 (self.plane, ["Face5", "Face6"]))
        for owner, names in cases:
            with self.subTest(names=names, owner=owner.Name):
                self.bearing.Location = (owner, names)
                self.assert_invalid("Location")
                self.locate()
                self.doc.recompute()
                self.assertNotIn("Invalid", self.bearing.State)
                self.assert_point(App.Vector(0, 0, 17))
                self.assertAlmostEqual(self.bearing.Radius, 7)

    def test_broken_and_missing_location(self):
        empty = self.doc.addObject("App::Link", "Empty")
        shapeless = self.doc.addObject("App::FeaturePython", "NoShape")
        for owner, name in ((empty, "Face1"), (shapeless, "Face1"),
                            (self.plane, "Face999")):
            with self.subTest(owner=owner.Name):
                self.bearing.Location = (owner, [name])
                self.assert_invalid("Location")

    def test_nonfinite_distance_rejected(self):
        self.locate()
        self.bearing.Dist = float("nan")
        self.assert_invalid("distance.*finite")

    def test_location_motion_and_regeneration(self):
        self.locate()
        self.bearing.Dist = 2
        self.plane.Placement.Base = App.Vector(0, 0, 23)
        self.doc.recompute()
        self.assert_point(App.Vector(0, 0, 21))

    def test_clear_and_invalid_primary_references(self):
        self.locate()
        self.bearing.References = [(self.cylinder, ["Vertex1"])]
        self.assert_invalid("References.*cylindrical")
        self.bearing.References = []
        self.doc.recompute()
        self.assertEqual(self.bearing.Radius, 0)
        self.assertFalse(self.bearing.Points)
        self.bearing.References = [(self.cylinder, ["Face1"])]
        self.doc.recompute()
        self.assertNotIn("Invalid", self.bearing.State)
        self.assert_point(App.Vector(0, 0, 17))

    def test_distance_undo_redo(self):
        self.locate()
        self.doc.openTransaction("Move bearing")
        self.bearing.Dist = 2
        self.doc.commitTransaction()
        self.assert_point(App.Vector(0, 0, 15))
        self.doc.undo()
        self.assert_point(App.Vector(0, 0, 17))
        self.doc.redo()
        self.assert_point(App.Vector(0, 0, 15))

    def test_placed_links(self):
        cylinder = self.doc.addObject("App::Link", "CylinderOccurrence")
        cylinder.setLink(self.cylinder)
        location = self.doc.addObject("App::Link", "LocationOccurrence")
        location.setLink(self.plane)
        location.Placement.Base = App.Vector(0, 0, 17)
        parent = self.doc.addObject("App::Part", "Parent")
        parent.addObject(cylinder)
        parent.addObject(location)
        parent.Placement = App.Placement(
            App.Vector(100, 200, 300), App.Rotation(App.Vector(0, 1, 0), 90))
        self.doc.recompute()
        self.bearing.References = [(cylinder, ["Face1"])]
        self.bearing.Location = (location, ["Face5"])
        self.bearing.Dist = 2
        self.assert_point(parent.Placement.multVec(App.Vector(0, 0, 15)))
        location.Placement.Base = App.Vector(0, 0, 23)
        self.doc.recompute()
        self.assert_point(parent.Placement.multVec(App.Vector(0, 0, 21)))

    def test_gear_and_pulley_inherit_updates(self):
        for factory in (ObjectsFem.makeConstraintGear, ObjectsFem.makeConstraintPulley):
            with self.subTest(factory=factory.__name__):
                self.bearing = factory(self.doc)
                self.bearing.References = [(self.cylinder, ["Face1"])]
                self.locate()
                self.bearing.Dist = 2
                self.assert_point(App.Vector(0, 0, 15))

    def test_save_reopen_and_regeneration(self):
        self.locate()
        self.bearing.Dist = 2
        with tempfile.TemporaryDirectory(prefix="freecad-bearing-location-") as output:
            filename = str(Path(output) / "bearing.FCStd")
            self.doc.saveAs(filename)
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(filename)
            self.bearing = self.doc.getObject("Bearing")
            self.assert_point(App.Vector(0, 0, 15))
            self.bearing.Dist = -2
            self.assert_point(App.Vector(0, 0, 19))
