# SPDX-License-Identifier: LGPL-2.1-or-later

"""Owned native mesh regions must not be replaced by coincident coordinates.

The Gmsh integration cases intentionally retain separate, coincident interface
nodes.  Their oracle is native face-element connectivity, not the region lookup
under test and not a manually repaired project node set.  These are software
ownership checks, not a physical joint or building-design qualification.
"""

from pathlib import Path
import shutil
import tempfile
import unittest

import FreeCAD as App
import Fem
import ObjectsFem
import Part
from femmesh import gmshtools, meshtools
from femtools import elastic_connector


@unittest.skipUnless(shutil.which("gmsh"), "Gmsh binary required")
class TestSecondOrderLinearOwnership(unittest.TestCase):
    """Characterize native curved-face limits, not a relaxed CAD classifier."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="freecad-linear-ownership-")
        self.doc = App.newDocument("SecondOrderLinearOwnership")
        self.solid = self.doc.addObject("Part::Cylinder", "Cylinder")
        self.solid.Radius = 3
        self.solid.Height = 5
        self.analysis = ObjectsFem.makeAnalysis(self.doc)
        self.body = ObjectsFem.makeConstraintRigidBody(self.doc, "CurvedBody")
        self.body.References = [(self.solid, ["Face1"])]
        self.analysis.addObject(self.body)
        self.mesh = ObjectsFem.makeMeshGmsh(self.doc, "Mesh")
        self.mesh.Shape = self.solid
        self.mesh.ElementOrder = "2nd"
        self.mesh.CharacteristicLengthMax = 2
        self.mesh.CharacteristicLengthMin = 1
        self.analysis.addObject(self.mesh)
        self.doc.recompute()

    def tearDown(self):
        try:
            App.closeDocument(self.doc.Name)
        finally:
            self.directory.cleanup()

    def generate(self, linear):
        self.mesh.SecondOrderLinear = linear
        self.mesh.WorkingDirectory = self.directory.name
        tool = gmshtools.GmshTools(self.mesh)
        tool.create_mesh()
        self.assertEqual(tool.process.exitCode(), 0)
        self.assertEqual(tool.process.exitStatus(), tool.process.ExitStatus.NormalExit)
        self.assertGreater(self.mesh.FemMesh.VolumeCount, 0)

    def nodes(self):
        return meshtools.get_femnodes_by_femobj_with_references(
            self.mesh.FemMesh, {"Object": self.body}, self.mesh
        )

    def test_curved_linear_limitation_is_actionable_after_reopen(self):
        self.generate(True)
        for phase in ("live", "cold-reopened"):
            with self.subTest(phase=phase):
                self.assertEqual(
                    self.mesh.ElementGroupGeometry,
                    meshtools.get_mesh_geometry_signature(self.solid),
                )
                with self.assertRaisesRegex(ValueError, "SecondOrderLinear.*curved.*Face1"):
                    self.nodes()
            if phase == "live":
                path = str(Path(self.directory.name) / "linear.FCStd")
                self.doc.saveAs(path)
                App.closeDocument(self.doc.Name)
                self.doc = App.openDocument(path)
                self.solid = self.doc.Cylinder
                self.mesh = self.doc.Mesh
                self.body = self.doc.CurvedBody

    def test_curved_second_order_still_requires_current_geometry(self):
        self.generate(False)
        mesh = self.mesh.FemMesh
        group = [g for g in mesh.Groups if mesh.getGroupName(g) == "Face1"]
        self.assertEqual(len(group), 1)
        expected = {
            node
            for element in mesh.getGroupElements(group[0])
            for node in mesh.getElementNodes(element)
        }
        self.assertTrue(expected)
        self.assertEqual(set(self.nodes()), expected)
        self.solid.Radius = 3.5
        self.doc.recompute()
        with self.assertRaisesRegex(ValueError, "changed mesh geometry"):
            self.nodes()


@unittest.skipUnless(shutil.which("gmsh"), "Gmsh binary required")
class TestRigidRegionOwnership(unittest.TestCase):
    def test_second_order_linear_planar_regions_survive_reopen(self):
        self.mesh.SecondOrderLinear = True
        self.generate_mesh()
        self.assert_owned_regions()
        self.reopen()
        self.assert_owned_regions()

    def test_closed_curve_occurrences_do_not_match_only_their_seam_vertex(self):
        source = self.doc.addObject("Part::Feature", "Circle")
        source.Shape = Part.makeCircle(5)
        left = self.doc.addObject("App::Link", "CircleLeft")
        right = self.doc.addObject("App::Link", "CircleRight")
        left.setLink(source)
        right.setLink(source)
        right.Placement.Rotation = App.Rotation(App.Vector(1, 0, 0), 90)
        self.compound.Links = [left, right]
        self.a.References = [(right, ["Edge1"])]
        self.doc.recompute()
        for stage in ("live", "reopened"):
            with self.subTest(stage=stage):
                self.assertEqual(meshtools.get_reference_group_elements(
                    self.a, self.compound)[1], ["Edge2"])
            if stage == "live":
                self.reopen()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="freecad-rigid-region-")
        self.doc = App.newDocument("RigidRegionOwnership")
        self.first = self.doc.addObject("Part::Box", "First")
        self.second = self.doc.addObject("Part::Box", "Second")
        for box in (self.first, self.second):
            box.Length = 20
            box.Width = 16
            box.Height = 10
        self.second.Placement.Base = App.Vector(20, 0, 0)
        self.compound = self.doc.addObject("Part::Compound", "Compound")
        self.compound.Links = [self.first, self.second]
        self.analysis = ObjectsFem.makeAnalysis(self.doc)
        self.a = ObjectsFem.makeConstraintRigidBody(self.doc, "FirstBody")
        self.b = ObjectsFem.makeConstraintRigidBody(self.doc, "SecondBody")
        self.a.References = [(self.first, ["Face2"])]
        self.b.References = [(self.second, ["Face1"])]
        for body in (self.a, self.b):
            body.ReferenceNode = App.Vector(20, 8, 5)
            self.analysis.addObject(body)
        self.mesh = ObjectsFem.makeMeshGmsh(self.doc, "Mesh")
        self.mesh.Shape = self.compound
        self.mesh.ElementOrder = "2nd"
        self.mesh.CharacteristicLengthMax = 8
        self.mesh.CharacteristicLengthMin = 4
        self.mesh.CoherenceMesh = False
        self.analysis.addObject(self.mesh)
        self.connector = ObjectsFem.makeConstraintElasticConnector(self.doc, "Connector")
        self.connector.Attachment = "Rigid body ports"
        self.connector.Kind = "Translational"
        self.connector.Mode = "Two points"
        self.connector.Axis = "Y"
        self.connector.Stiffness = "1000 N/mm"
        self.connector.RigidBody1 = self.a
        self.connector.RigidBody2 = self.b
        self.analysis.addObject(self.connector)
        self.prefs = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/General")
        previous = self.prefs.GetBool("AnalysisGroupMeshing", False)
        self.previous_group_meshing = previous
        self.had_group_meshing = previous == self.prefs.GetBool("AnalysisGroupMeshing", True)
        self.prefs.SetBool("AnalysisGroupMeshing", True)
        self.mesh_number = 0
        self.doc.recompute()

    def tearDown(self):
        try:
            if self.doc and self.doc.Name in App.listDocuments():
                App.closeDocument(self.doc.Name)
        finally:
            if self.had_group_meshing:
                self.prefs.SetBool("AnalysisGroupMeshing", self.previous_group_meshing)
            else:
                self.prefs.RemBool("AnalysisGroupMeshing")
            self.directory.cleanup()

    def generate_mesh(self):
        self.mesh_number += 1
        output = Path(self.directory.name) / f"mesh-{self.mesh_number}"
        output.mkdir()
        self.mesh.WorkingDirectory = str(output)
        self.doc.recompute()
        tool = gmshtools.GmshTools(self.mesh)
        tool.create_mesh()
        self.assertEqual(tool.process.exitCode(), 0)
        self.assertEqual(tool.process.exitStatus(), tool.process.ExitStatus.NormalExit)
        self.assertGreater(self.mesh.FemMesh.VolumeCount, 0)
        self.assertFalse(self.mesh.CoherenceMesh)
        return tool

    def group_elements(self, name):
        mesh = self.mesh.FemMesh
        groups = [group for group in mesh.Groups if mesh.getGroupName(group) == name]
        self.assertEqual(len(groups), 1, name)
        elements = set(mesh.getGroupElements(groups[0]))
        self.assertTrue(elements, name)
        return elements

    def face_nodes(self, face):
        """Independent native connectivity oracle, including midside nodes."""
        mesh = self.mesh.FemMesh
        nodes = set()
        for element in self.group_elements(face):
            self.assertIn(element, mesh.Faces)
            connectivity = mesh.getElementNodes(element)
            self.assertEqual(len(connectivity), 6, "Expected second-order triangular faces")
            nodes.update(connectivity)
        self.assertGreaterEqual(len(nodes), 6)
        self.assertTrue(nodes <= set(mesh.Nodes))
        return nodes

    def region_resolvers(self, body):
        return (
            ("ordinary RBE writer", lambda: set(
                meshtools.get_femnodes_by_femobj_with_references(
                    self.mesh.FemMesh, {"Object": body}))),
            ("rigid port validation", lambda: elastic_connector.rigid_body_nodes(body, self.mesh)),
        )

    def assert_owned_regions(self, faces=("Face2", "Face7"), coincident=True,
                             analysis_groups=True):
        mesh = self.mesh.FemMesh
        expected = [self.face_nodes(face) for face in faces]
        self.assertFalse(expected[0].intersection(expected[1]))
        for body, face, nodes in zip((self.a, self.b), faces, expected):
            if analysis_groups:
                self.assertEqual(self.group_elements(body.Name), self.group_elements(face))
            for resolver_name, resolve in self.region_resolvers(body):
                with self.subTest(body=body.Name, face=face, resolver=resolver_name):
                    self.assertEqual(resolve(), nodes, f"{resolver_name} lost mesh ownership")
            if coincident:
                owner, names = body.References[0]
                coordinate_nodes = set(mesh.getNodesByFace(owner.getSubObject(names[0])))
                self.assertEqual(coordinate_nodes, expected[0] | expected[1])
                self.assertGreater(len(coordinate_nodes), len(nodes))
        resolved = elastic_connector.resolve_connector(self.connector, self.mesh, self.analysis)
        self.assertEqual(resolved["bodies"], [self.a, self.b])
        self.assertEqual(resolved["regions"], expected)
        return expected

    def assert_current_nodes_or_actionable_rejection(self, expected=None):
        """Never silently accept an obsolete group or a newly coincident owner."""
        for index, body in enumerate((self.a, self.b)):
            for resolver_name, resolve in self.region_resolvers(body):
                with self.subTest(body=body.Name, resolver=resolver_name):
                    try:
                        actual = resolve()
                    except (ValueError, RuntimeError) as error:
                        self.assertRegex(str(error).lower(),
                                         "mesh|regenerat|stale|changed|current|remesh|ownership")
                    else:
                        self.assertIsNotNone(expected, "Changed geometry requires a remesh error")
                        self.assertEqual(actual, expected[index],
                                         "Resolver accepted stale or wrong-owner native groups")

    def assert_regions_rejected(self, bodies=None, pattern="mesh|remesh|regenerat|owner|reference"):
        for body in bodies or (self.a, self.b):
            for resolver_name, resolve in self.region_resolvers(body):
                with self.subTest(body=body.Name, resolver=resolver_name):
                    with self.assertRaisesRegex((ValueError, RuntimeError), f"(?i){pattern}"):
                        resolve()

    def reopen(self):
        filename = str(Path(self.directory.name) / "regions.FCStd")
        self.doc.saveAs(filename)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(filename)
        for attribute, name in (("first", "First"), ("second", "Second"),
                                ("compound", "Compound"), ("analysis", "Analysis"),
                                ("a", "FirstBody"), ("b", "SecondBody"),
                                ("mesh", "Mesh"), ("connector", "Connector")):
            setattr(self, attribute, self.doc.getObject(name))

    def test_separate_coincident_regions_match_native_face_connectivity(self):
        self.generate_mesh()
        self.assert_owned_regions()

    def test_saved_mesh_reopen_and_reference_rebind_remesh(self):
        self.generate_mesh()
        self.assert_owned_regions()
        self.reopen()
        # Resolve from serialized native groups before any new mesh generation.
        self.assert_owned_regions()
        self.a.References = [(self.first, ["Face1"])]
        self.b.References = [(self.second, ["Face2"])]
        self.doc.recompute()
        self.assert_current_nodes_or_actionable_rejection(
            [self.face_nodes("Face1"), self.face_nodes("Face8")])
        self.generate_mesh()
        self.assert_owned_regions(("Face1", "Face8"), coincident=False)
        # Rebinding back must derive current interface ownership, not cached IDs.
        self.a.References = [(self.first, ["Face2"])]
        self.b.References = [(self.second, ["Face1"])]
        self.generate_mesh()
        self.assert_owned_regions()

    def test_base_cad_groups_work_without_analysis_group_meshing(self):
        self.prefs.SetBool("AnalysisGroupMeshing", False)
        self.generate_mesh()
        names = [self.mesh.FemMesh.getGroupName(group) for group in self.mesh.FemMesh.Groups]
        self.assertNotIn(self.a.Name, names)
        self.assertNotIn(self.b.Name, names)
        self.assert_owned_regions(analysis_groups=False)

    def test_coincident_compound_reorder_does_not_swap_current_owners(self):
        self.generate_mesh()
        expected = self.assert_owned_regions()
        self.compound.Links = [self.second, self.first]
        self.doc.recompute()
        self.assert_current_nodes_or_actionable_rejection(expected)
        self.generate_mesh()
        self.assert_owned_regions(("Face8", "Face1"))

    def test_link_occurrences_reorder_move_and_remesh(self):
        left = self.doc.addObject("App::Link", "Left")
        right = self.doc.addObject("App::Link", "Right")
        left.setLink(self.first)
        right.setLink(self.first)
        right.Placement.Base = App.Vector(20, 0, 0)
        self.compound.Links = [left, right]
        self.a.References = [(left, ["Face2"])]
        self.b.References = [(right, ["Face1"])]
        self.generate_mesh()
        self.assert_owned_regions()
        self.reopen()
        self.assert_owned_regions()
        left, right = self.doc.getObject("Left"), self.doc.getObject("Right")
        left.Placement.Base = App.Vector(3, 4, 5)
        right.Placement.Base = App.Vector(23, 4, 5)
        self.compound.Links = [right, left]
        self.doc.recompute()
        self.assert_current_nodes_or_actionable_rejection()
        self.generate_mesh()
        self.assert_owned_regions(("Face8", "Face1"))

    def test_genuinely_shared_region_still_rejects_connector(self):
        self.b.References = self.a.References
        self.generate_mesh()
        expected = self.face_nodes("Face2")
        for body in (self.a, self.b):
            self.assertEqual(self.group_elements(body.Name), self.group_elements("Face2"))
            self.assertEqual(set(meshtools.get_femnodes_by_femobj_with_references(
                self.mesh.FemMesh, {"Object": body})), expected)
            self.assertEqual(elastic_connector.rigid_body_nodes(body, self.mesh), expected)
        with self.assertRaisesRegex(ValueError, "regions must not overlap"):
            elastic_connector.resolve_connector(self.connector, self.mesh, self.analysis)

    def test_noncollinear_vertex_regions_use_native_zero_dimensional_connectivity(self):
        selected_vertices = []
        for offset, body, owner, face_name in (
                (0, self.a, self.first, "Face2"), (8, self.b, self.second, "Face1")):
            vertices = owner.getSubObject(face_name).Vertexes[:3]
            names = [f"Vertex{index}" for vertex in vertices
                     for index, candidate in enumerate(owner.Shape.Vertexes, 1)
                     if candidate.isSame(vertex)]
            self.assertEqual(len(names), 3)
            body.References = [(owner, names)]
            # This controlled compound contains two ordered eight-vertex boxes.
            # Expected group indices do not call the ownership resolver under test.
            selected_vertices.append([f"Vertex{offset + int(name[6:])}" for name in names])
        tool = self.generate_mesh()
        # Read untouched native Gmsh cells independently of the loaded object's
        # postprocessing.  Native FCStd/UNV drops 0D element groups, so the
        # persistent VertexN groups must contain these exact owned node IDs.
        raw_mesh = Fem.FemMesh()
        raw_mesh.read(tool.temp_file_mesh, vtk_cell_group_array="CellEntityIds")
        raw_groups = {raw_mesh.getGroupName(group): group for group in raw_mesh.Groups}
        zero_dimensional = set(raw_mesh.getIdByElementType("0DElement"))
        self.assertTrue(zero_dimensional)
        expected = []
        expected_groups = {}
        for compound_names in selected_vertices:
            nodes = set()
            for name in compound_names:
                raw_group = raw_groups[str(tool.group_indices[name])]
                owned_nodes = set()
                for element in raw_mesh.getGroupElements(raw_group):
                    self.assertIn(element, zero_dimensional)
                    connectivity = raw_mesh.getElementNodes(element)
                    self.assertEqual(len(connectivity), 1)
                    owned_nodes.update(connectivity)
                self.assertEqual(len(owned_nodes), 1)
                expected_groups[name] = owned_nodes
                nodes.update(owned_nodes)
            self.assertEqual(len(nodes), 3)
            points = [raw_mesh.Nodes[node] for node in sorted(nodes)]
            self.assertGreater((points[1] - points[0]).cross(points[2] - points[0]).Length, 0)
            expected.append(nodes)
        self.assertFalse(expected[0].intersection(expected[1]))
        for phase in ("generated", "reopened"):
            with self.subTest(phase=phase):
                mesh = self.mesh.FemMesh
                groups = {mesh.getGroupName(group): group for group in mesh.Groups}
                for name, nodes in expected_groups.items():
                    self.assertIn(name, groups)
                    self.assertEqual(mesh.getGroupElementType(groups[name]), "Node")
                    self.assertEqual(set(mesh.getGroupElements(groups[name])), nodes)
                for body, nodes in zip((self.a, self.b), expected):
                    for resolver_name, resolve in self.region_resolvers(body):
                        with self.subTest(body=body.Name, resolver=resolver_name):
                            self.assertEqual(resolve(), nodes)
                resolved = elastic_connector.resolve_connector(
                    self.connector, self.mesh, self.analysis)
                self.assertEqual(resolved["regions"], expected)
            if phase == "generated":
                self.reopen()

    def test_expanded_faces_reject_old_mesh_even_when_all_old_nodes_still_fit(self):
        self.generate_mesh()
        expected = self.assert_owned_regions()
        for box in (self.first, self.second):
            box.Width = 24
            box.Height = 15
        self.doc.recompute()
        for body, old_nodes in zip((self.a, self.b), expected):
            owner, names = body.References[0]
            coordinate_nodes = set(self.mesh.FemMesh.getNodesByFace(
                owner.getSubObject(names[0])))
            self.assertTrue(old_nodes <= coordinate_nodes,
                            "Control must expose geometric-subset validation's blind spot")
        self.assert_regions_rejected(pattern="changed|stale|regenerat|remesh|current")

    def test_cleared_geometry_owner_never_uses_coordinate_fallback(self):
        self.generate_mesh()
        self.assert_owned_regions()
        self.assertTrue(self.mesh.ElementGroupGeometry)
        self.mesh.Shape = None
        self.doc.recompute()
        self.assert_regions_rejected(pattern="missing.*(geometry|owner)|regenerat|remesh")

    def test_mixed_valid_and_absent_reference_never_returns_partial_region(self):
        self.generate_mesh()
        self.assert_owned_regions()
        external = self.doc.addObject("Part::Box", "External")
        external.Placement.Base = App.Vector(100, 0, 0)
        self.doc.recompute()
        self.a.References = [(self.first, ["Face2"]), (external, ["Face1"])]
        self.doc.recompute()
        self.assert_regions_rejected([self.a], pattern="absent|reference|mesh")

    def test_legacy_raw_mesh_reader_reestablishes_native_group_provenance(self):
        self.first.Placement.Base = App.Vector(3, 4, 5)
        self.second.Placement.Base = App.Vector(23, 4, 5)
        tool = self.generate_mesh()
        expected = self.assert_owned_regions()
        self.assertTrue(Path(tool.temp_file_mesh).is_file())
        # The public prepare step captures current native geometry and resets
        # group construction state, as in the historic meshing workflow.
        tool.prepare()
        # Discard the loaded result, not its original native Gmsh output.  The
        # historic public reader must repopulate both connectivity and metadata.
        self.mesh.FemMesh = Fem.FemMesh()
        self.mesh.ElementGroupNames = []
        self.mesh.ElementGroupReferences = []
        self.mesh.ElementGroupGeometry = ""
        tool.read_and_set_new_mesh()
        self.assertTrue(self.mesh.ElementGroupNames)
        self.assertTrue(self.mesh.ElementGroupReferences)
        self.assertTrue(self.mesh.ElementGroupGeometry)
        self.assertEqual(self.assert_owned_regions(), expected)

    def test_geometry_changed_during_meshing_cannot_replace_existing_result(self):
        tool = self.generate_mesh()
        self.assert_owned_regions()
        tool.prepare()
        self.assertTrue(Path(tool.temp_file_mesh).is_file())
        mesh = self.mesh.FemMesh
        old_nodes = dict(mesh.Nodes)
        old_elements = {element: mesh.getElementNodes(element)
                        for element in mesh.getIdByElementType("All")}
        old_groups = [(mesh.getGroupName(group), mesh.getGroupElementType(group),
                       tuple(mesh.getGroupElements(group))) for group in mesh.Groups]
        old_names = list(self.mesh.ElementGroupNames)
        old_references = [(owner.Name, list(names))
                          for owner, names in self.mesh.ElementGroupReferences]
        old_geometry = self.mesh.ElementGroupGeometry
        for box in (self.first, self.second):
            box.Width = 24
        self.doc.recompute()
        with self.assertRaisesRegex(gmshtools.GmshError, "(?i)changed|regenerat|remesh"):
            tool.update_properties()
        mesh = self.mesh.FemMesh
        self.assertEqual(dict(mesh.Nodes), old_nodes)
        self.assertEqual(
            {element: mesh.getElementNodes(element) for element in mesh.getIdByElementType("All")},
            old_elements,
        )
        self.assertEqual(
            [
                (
                    mesh.getGroupName(group),
                    mesh.getGroupElementType(group),
                    tuple(mesh.getGroupElements(group)),
                )
                for group in mesh.Groups
            ],
            old_groups,
        )
        self.assertEqual(list(self.mesh.ElementGroupNames), old_names)
        self.assertEqual([(owner.Name, list(names))
                          for owner, names in self.mesh.ElementGroupReferences], old_references)
        self.assertEqual(self.mesh.ElementGroupGeometry, old_geometry)

    def test_unrelated_femmesh_cannot_borrow_inferred_analysis_provenance(self):
        self.generate_mesh()
        self.assert_owned_regions()
        unrelated = Fem.FemMesh()
        unrelated.addNode(100, 200, 300, 1)
        with self.assertRaisesRegex((ValueError, RuntimeError), "(?i)mesh.*(match|owner)"):
            meshtools.get_femnodes_by_femobj_with_references(unrelated, {"Object": self.a})
