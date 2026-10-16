# SPDX-License-Identifier: LGPL-2.1-or-later

"""Native reference correspondence, without solver or building-design assumptions."""

from pathlib import Path
import shutil
import tempfile
import unittest

import FreeCAD as App
import ObjectsFem
import Part
from femmesh import gmshtools, meshtools
from femtools import geomtools


class TestReferenceGroups(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("ReferenceGroups")
        self.first = self.doc.addObject("Part::Box", "First")
        self.second = self.doc.addObject("Part::Box", "Second")
        for box in (self.first, self.second):
            box.Length = box.Width = box.Height = 1
        self.second.Placement.Base = App.Vector(1, 0, 0)
        self.compound = self.doc.addObject("Part::Compound", "Compound")
        self.compound.Links = [self.first, self.second]
        self.analysis = ObjectsFem.makeAnalysis(self.doc)
        self.a = ObjectsFem.makeConstraintRigidBody(self.doc, "FirstBody")
        self.b = ObjectsFem.makeConstraintRigidBody(self.doc, "SecondBody")
        self.a.References = [(self.first, ["Face2"])]
        self.b.References = [(self.second, ["Face1"])]
        self.analysis.addObject(self.a)
        self.analysis.addObject(self.b)
        self.doc.recompute()

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def groups(self):
        return meshtools.get_analysis_group_elements(self.analysis, self.compound)

    def test_independently_owned_coincident_faces(self):
        left = self.first.getSubObject("Face2")
        right = self.second.getSubObject("Face1")
        self.assertFalse(left.isPartner(right))
        self.assertTrue(geomtools.is_same_geometry(left, right))
        self.assertEqual(self.groups(), {"FirstBody": ["Face2"], "SecondBody": ["Face7"]})

    def test_explicit_compound_face(self):
        self.b.References = [(self.compound, ["Face7"])]
        self.assertEqual(self.groups()["SecondBody"], ["Face7"])

    def test_exact_identity_precedes_geometry(self):
        shape = Part.makeCompound([Part.makeBox(1, 1, 1),
                                   Part.makeBox(1, 1, 1, App.Vector(1, 0, 0))])
        face = shape.Faces[6]
        self.assertTrue(geomtools.is_same_geometry(shape.Faces[1], face))
        self.assertEqual(geomtools.find_element_in_shape(shape, face), "Face7")

    def test_opposite_orientation(self):
        shape = Part.makeBox(1, 1, 1)
        face = shape.Faces[1]
        reversed_face = face.reversed()
        self.assertTrue(face.isSame(reversed_face))
        self.assertEqual(geomtools.find_element_in_shape(shape, reversed_face), "Face2")

    def test_unique_external_geometry(self):
        # Copies lose TShape identity but remain a supported unambiguous reference.
        face = self.second.getSubObject("Face2").copy()
        self.assertEqual(geomtools.find_element_in_shape(self.compound.Shape, face), "Face8")

    def test_external_coincident_geometry_is_ambiguous(self):
        face = self.second.getSubObject("Face1").copy()
        with self.assertRaisesRegex(ValueError, "Ambiguous.*Face2.*Face7"):
            geomtools.find_element_in_shape(self.compound.Shape, face)

    def test_ambiguous_group_fails_closed(self):
        external = self.doc.addObject("Part::Feature", "External")
        external.Shape = self.second.getSubObject("Face1").copy()
        self.b.References = [(external, ["Face1"])]
        with self.assertRaisesRegex(ValueError, "SecondBody.*External.*Face1"):
            self.groups()

    def test_noncoincident_and_regeneration(self):
        self.second.Placement.Base = App.Vector(3, 0, 0)
        self.doc.recompute()
        self.assertEqual(self.groups()["SecondBody"], ["Face7"])
        self.compound.Links = [self.second, self.first]
        self.doc.recompute()
        self.assertEqual(self.groups(), {"FirstBody": ["Face8"], "SecondBody": ["Face1"]})

    def test_partner_placement_is_not_ignored(self):
        shape = Part.makeBox(1, 1, 1)
        moved = shape.translated(App.Vector(3, 0, 0))
        compound = Part.makeCompound([shape, moved])
        self.assertTrue(shape.Faces[0].isPartner(moved.Faces[0]))
        self.assertEqual(geomtools.find_element_in_shape(compound, moved.Faces[0]), "Face7")

    def test_link_occurrence_ownership_after_reopen(self):
        left = self.doc.addObject("App::Link", "Left")
        right = self.doc.addObject("App::Link", "Right")
        for link in (left, right):
            link.setLink(self.first)
        right.Placement.Base = App.Vector(3, 0, 0)
        self.compound.Links = [left, right]
        mesh = ObjectsFem.makeMeshGmsh(self.doc, "Mesh")
        mesh.Shape = self.compound
        left_group = ObjectsFem.makeMeshGroup(self.doc, mesh, False, "LeftGroup")
        right_group = ObjectsFem.makeMeshGroup(self.doc, mesh, False, "RightGroup")
        left_group.References = [(left, ["Face1"])]
        right_group.References = [(right, ["Face1"])]
        self.doc.recompute()
        for phase in ("live", "reopened"):
            with self.subTest(phase=phase):
                for name, expected in (("LeftGroup", "Face1"), ("RightGroup", "Face7")):
                    group = self.doc.getObject(name)
                    self.assertEqual(meshtools.get_reference_group_elements(
                        group, self.compound)[1], [expected])
            if phase == "live":
                self.reopen()

    def test_nested_compound_ownership_after_reopen(self):
        outer = self.doc.addObject("Part::Compound", "Outer")
        outer.Links = [self.compound]
        self.doc.recompute()
        self.compound = outer
        self.reopen("Outer")
        self.assertEqual(self.groups(), {"FirstBody": ["Face2"], "SecondBody": ["Face7"]})

    def test_explicit_index_with_reversed_owner(self):
        feature = self.doc.addObject("Part::Feature", "Repeated")
        feature.Shape = Part.makeCompound([self.first.Shape, self.second.Shape.reversed()])
        self.doc.recompute()
        self.b.References = [(feature, ["Face7"])]
        self.assertEqual(meshtools.get_reference_group_elements(self.b, feature)[1], ["Face7"])

    def test_solids_edges_and_vertices(self):
        for subname, expected in (("Solid1", "Solid2"), ("Edge1", "Edge13"),
                                  ("Vertex1", "Vertex9")):
            with self.subTest(subname=subname):
                self.b.References = [(self.second, [subname])]
                self.assertEqual(self.groups()["SecondBody"], [expected])

    def test_whole_compound_reference(self):
        self.b.References = [(self.compound, [""])]
        self.assertEqual(self.groups()["SecondBody"], ["Solid1", "Solid2"])

    def test_missing_geometry_still_returns_none(self):
        face = Part.makeBox(1, 1, 1, App.Vector(10, 0, 0)).Faces[0]
        self.assertIsNone(geomtools.find_element_in_shape(self.compound.Shape, face))

    def reopen(self, compound_name="Compound"):
        with tempfile.TemporaryDirectory(prefix="freecad-reference-groups-") as output:
            filename = str(Path(output) / "groups.FCStd")
            self.doc.saveAs(filename)
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(filename)
            self.analysis = self.doc.getObject("Analysis")
            self.compound = self.doc.getObject(compound_name)

    def test_persistence_and_group_regeneration(self):
        self.reopen()
        self.assertEqual(self.groups(), {"FirstBody": ["Face2"], "SecondBody": ["Face7"]})
        self.compound.Links = list(reversed(self.compound.Links))
        self.doc.recompute()
        self.assertEqual(self.groups(), {"FirstBody": ["Face8"], "SecondBody": ["Face1"]})

    @unittest.skipUnless(shutil.which("gmsh"), "Gmsh binary required")
    def test_native_mesh_groups(self):
        # Real generated mesh groups, never hand-filtered or repaired nodes.
        mesh = ObjectsFem.makeMeshGmsh(self.doc, "Mesh")
        mesh.Shape = self.compound
        mesh.CharacteristicLengthMax = 0.7
        mesh.CharacteristicLengthMin = 0.7
        self.analysis.addObject(mesh)
        first_group = ObjectsFem.makeMeshGroup(self.doc, mesh, False, "FirstGroup")
        second_group = ObjectsFem.makeMeshGroup(self.doc, mesh, False, "SecondGroup")
        first_group.References = self.a.References
        second_group.References = self.b.References
        self.doc.recompute()
        prefs = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/General")
        previous = prefs.GetBool("AnalysisGroupMeshing", False)
        had_preference = previous == prefs.GetBool("AnalysisGroupMeshing", True)
        try:
            prefs.SetBool("AnalysisGroupMeshing", True)
            with tempfile.TemporaryDirectory(prefix="freecad-reference-mesh-") as output:
                mesh.WorkingDirectory = output
                tool = gmshtools.GmshTools(mesh)
                tool.create_mesh()
                self.assertEqual(tool.process.exitCode(), 0)
                self.assertEqual(tool.process.exitStatus(), tool.process.ExitStatus.NormalExit)
                groups = {mesh.FemMesh.getGroupName(g): tuple(mesh.FemMesh.getGroupElements(g))
                          for g in mesh.FemMesh.Groups}
                for name, face in (("FirstGroup", "Face2"), ("SecondGroup", "Face7"),
                                   ("FirstBody", "Face2"), ("SecondBody", "Face7")):
                    self.assertTrue(groups[name], name)
                    self.assertEqual(groups[name], groups[face], name)
                self.assertNotEqual(groups["FirstGroup"], groups["SecondGroup"])
        finally:
            if had_preference:
                prefs.SetBool("AnalysisGroupMeshing", previous)
            else:
                prefs.RemBool("AnalysisGroupMeshing")
