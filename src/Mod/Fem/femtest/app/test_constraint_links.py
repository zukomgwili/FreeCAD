# SPDX-License-Identifier: LGPL-2.1-or-later

"""Native constraint reference geometry must preserve the selected occurrence."""

from pathlib import Path
import tempfile
import unittest

import FreeCAD as App
import ObjectsFem
import Part


class TestConstraintLinks(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("ConstraintLinks")
        self.source = self.doc.addObject("Part::Box", "Source")
        self.source.Length, self.source.Width, self.source.Height = 20, 30, 40
        self.link = self.doc.addObject("App::Link", "Occurrence")
        self.link.setLink(self.source)
        self.link.Placement = App.Placement(
            App.Vector(11, 13, 17), App.Rotation(App.Vector(0, 0, 1), 90))
        self.doc.recompute()

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def constraint(self, owner, subname="Face1", factory=ObjectsFem.makeConstraintRigidBody):
        result = factory(self.doc)
        result.References = [(owner, [subname])]
        return result

    def assert_vector(self, actual, expected):
        self.assertLess((actual - expected).Length, 1e-7, (actual, expected))

    def assert_face_symbols(self, constraint, face):
        expected = face.normalAt(0, 0)
        self.assert_vector(constraint.NormalDirection, expected)
        self.assertTrue(constraint.Points)
        self.assertEqual(len(constraint.Points), len(constraint.Normals))
        for point, normal in zip(constraint.Points, constraint.Normals):
            self.assertLess(Part.Vertex(point).distToShape(face)[0], 1e-7)
            self.assert_vector(normal, expected)

    def test_direct_part_control(self):
        constraint = self.constraint(self.source)
        self.assert_face_symbols(constraint, self.source.getSubObject("Face1"))

    def test_rigid_body_link_face(self):
        self.assertFalse(self.link.getSubObject("Face1").isNull())
        constraint = self.constraint(self.link)
        self.assertEqual(constraint.References[0][0], self.link)
        self.assert_face_symbols(constraint, self.link.getSubObject("Face1"))

    def test_direct_part_edge_and_vertex(self):
        for name in ("Edge1", "Vertex1"):
            with self.subTest(name=name):
                constraint = self.constraint(self.source, name)
                shape = self.source.getSubObject(name)
                self.assertTrue(constraint.Points)
                for point in constraint.Points:
                    self.assertLess(Part.Vertex(point).distToShape(shape)[0], 1e-7)

    def test_link_edge_and_vertex(self):
        for name in ("Edge1", "Vertex1"):
            with self.subTest(name=name):
                constraint = self.constraint(self.link, name)
                shape = self.link.getSubObject(name)
                self.assertTrue(constraint.Points)
                for point in constraint.Points:
                    self.assertLess(Part.Vertex(point).distToShape(shape)[0], 1e-7)

    def test_nested_link(self):
        outer = self.doc.addObject("App::Link", "Outer")
        outer.setLink(self.link)
        outer.Placement = App.Placement(App.Vector(50, 60, 70),
                                        App.Rotation(App.Vector(0, 1, 0), 90))
        self.doc.recompute()
        constraint = self.constraint(outer)
        self.assert_face_symbols(constraint, outer.getSubObject("Face1"))

    def test_parent_geometry_group(self):
        parent = self.doc.addObject("App::Part", "Parent")
        parent.Placement = App.Placement(App.Vector(80, 90, 100),
                                         App.Rotation(App.Vector(0, 1, 0), 90))
        parent.addObject(self.link)
        self.doc.recompute()
        constraint = self.constraint(self.link)
        face = self.link.getSubObject("Face1")
        face.transformShape(parent.Placement.toMatrix())
        self.assert_face_symbols(constraint, face)

    def test_link_relocation_refreshes_symbols(self):
        constraint = self.constraint(self.link)
        self.link.Placement = App.Placement(
            App.Vector(-30, 20, 60), App.Rotation(App.Vector(1, 0, 0), 90))
        self.assert_face_symbols(constraint, self.link.getSubObject("Face1"))

    def test_native_constraint_factories(self):
        factories = (ObjectsFem.makeConstraintFixed, ObjectsFem.makeConstraintDisplacement,
                     ObjectsFem.makeConstraintForce, ObjectsFem.makeConstraintPressure,
                     ObjectsFem.makeConstraintTemperature)
        for factory in factories:
            with self.subTest(factory=factory.__name__):
                constraint = self.constraint(self.link, factory=factory)
                self.assert_face_symbols(constraint, self.link.getSubObject("Face1"))

    def test_shapeless_reference_clears_symbols(self):
        constraint = self.constraint(self.source)
        shapeless = self.doc.addObject("App::FeaturePython", "NoShape")
        constraint.References = [(shapeless, ["Face1"])]
        self.assertFalse(constraint.Points)
        self.assertFalse(constraint.Normals)

    def test_broken_link_is_safe(self):
        constraint = self.constraint(self.source)
        empty = self.doc.addObject("App::Link", "Empty")
        constraint.References = [(empty, ["Face1"])]
        self.assertFalse(constraint.Points)
        self.assertFalse(constraint.Normals)

    def test_invalid_subelement_is_safe(self):
        constraint = self.constraint(self.source)
        constraint.References = [(self.link, ["Face999"])]
        self.assertFalse(constraint.Points)
        self.assertFalse(constraint.Normals)
        self.doc.recompute()
        self.assertIn("Invalid", constraint.State)

    def test_removed_link_is_safe(self):
        constraint = self.constraint(self.link)
        self.doc.removeObject(self.link.Name)
        self.doc.recompute()
        self.assertFalse(constraint.Points)
        self.assertFalse(constraint.Normals)

    def test_link_transform_false(self):
        self.source.Placement = App.Placement(
            App.Vector(5, 7, 9), App.Rotation(App.Vector(1, 0, 0), 30))
        self.link.LinkTransform = False
        self.doc.recompute()
        constraint = self.constraint(self.link)
        self.assert_face_symbols(constraint, self.link.getSubObject("Face1"))

    def test_dotted_reference_path(self):
        parent = self.doc.addObject("App::Part", "Parent")
        parent.Placement.Base = App.Vector(100, 200, 300)
        parent.addObject(self.link)
        self.doc.recompute()
        constraint = self.constraint(parent, "Occurrence.Face1")
        face = self.link.getSubObject("Face1")
        face.transformShape(parent.Placement.toMatrix())
        self.assert_face_symbols(constraint, face)

    def test_parent_relocation_refreshes_symbols(self):
        parent = self.doc.addObject("App::Part", "Parent")
        parent.addObject(self.link)
        constraint = self.constraint(self.link)
        parent.Placement = App.Placement(
            App.Vector(80, 90, 100), App.Rotation(App.Vector(0, 1, 0), 90))
        face = self.link.getSubObject("Face1")
        face.transformShape(parent.Placement.toMatrix())
        self.assert_face_symbols(constraint, face)

    def cylinder_link(self):
        cylinder = self.doc.addObject("Part::Cylinder", "Cylinder")
        cylinder.Radius, cylinder.Height = 7, 11
        self.link.setLink(cylinder)
        self.link.Placement = App.Placement(
            App.Vector(11, 13, 17), App.Rotation(App.Vector(0, 1, 0), 90))
        self.doc.recompute()
        return cylinder

    def test_bearing_cylindrical_link_reference(self):
        cylinder = self.cylinder_link()
        direct = self.constraint(cylinder, factory=ObjectsFem.makeConstraintBearing)
        constraint = self.constraint(self.link, factory=ObjectsFem.makeConstraintBearing)
        self.assertAlmostEqual(constraint.Radius, 7)
        self.assertAlmostEqual(constraint.Height, 11)
        self.assert_vector(constraint.Axis, self.link.Placement.Rotation.multVec(direct.Axis))
        self.assert_vector(constraint.BasePoint, self.link.Placement.multVec(direct.BasePoint))
        self.assertTrue(constraint.Points)

    def test_cylindrical_transform_link_reference(self):
        cylinder = self.cylinder_link()
        direct = ObjectsFem.makeConstraintTransform(self.doc, "Direct")
        direct.TransformType = "Cylindrical"
        direct.References = [(cylinder, ["Face1"])]
        constraint = ObjectsFem.makeConstraintTransform(self.doc)
        constraint.TransformType = "Cylindrical"
        constraint.References = [(self.link, ["Face1"])]
        self.assert_vector(constraint.Axis, self.link.Placement.Rotation.multVec(direct.Axis))
        self.assert_vector(constraint.BasePoint, App.Vector(16.5, 13, 17))
        self.assertTrue(constraint.Points)
        empty = self.doc.addObject("App::Link", "Empty")
        constraint.References = [(empty, ["Face1"])]
        self.assertFalse(constraint.Points)
        self.assertFalse(constraint.Normals)

    def test_bearing_location_link_is_safe(self):
        cylinder = self.cylinder_link()
        # A local X-normal face becomes a global Z-normal plane at Z17.
        self.link.setLink(self.source)
        self.link.Placement = App.Placement(
            App.Vector(0, 0, 17), App.Rotation(App.Vector(0, 1, 0), 90))
        self.doc.recompute()
        constraint = self.constraint(cylinder, factory=ObjectsFem.makeConstraintBearing)
        constraint.Location = (self.link, ["Face1"])
        # Exercise References with the Location already assigned as well.
        constraint.References = [(cylinder, ["Face1"])]
        self.assert_vector(constraint.BasePoint, App.Vector(0, 0, 17))

    def test_save_reopen_and_regeneration(self):
        constraint = self.constraint(self.link)
        name = constraint.Name
        with tempfile.TemporaryDirectory(prefix="freecad-constraint-links-") as directory:
            filename = str(Path(directory) / "links.FCStd")
            self.doc.saveAs(filename)
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(filename)
            constraint = self.doc.getObject(name)
            link = self.doc.getObject("Occurrence")
            self.assertEqual(constraint.References[0][0], link)
            self.assert_face_symbols(constraint, link.getSubObject("Face1"))
            link.Placement = App.Placement(App.Vector(80, 30, 20),
                                           App.Rotation(App.Vector(0, 0, 1), -90))
            self.doc.recompute()
            self.assert_face_symbols(constraint, link.getSubObject("Face1"))
