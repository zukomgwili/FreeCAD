# SPDX-License-Identifier: LGPL-2.1-or-later

"""Native contact facets must retain independently meshed CAD ownership.

No rigid bodies, connector, material, load, or solver are needed to expose this
lookup/export bug.  Native Gmsh face connectivity provides the oracle; no node
sets or solver surfaces are repaired by the test.
"""

import io
from pathlib import Path
import re
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest

import FreeCAD as App
import Fem
import ObjectsFem
from femmesh import gmshtools
from femmesh import meshsetsgetter
from femmesh import meshtools
from femsolver.calculix import calculixutils, write_constraint_contact


@unittest.skipUnless(shutil.which("gmsh"), "Gmsh binary required")
class TestContactOwnership(unittest.TestCase):
    def test_second_order_linear_planar_contact_writer_survives_reopen(self):
        self.mesh.SecondOrderLinear = True
        self.generate_mesh()
        expected_counts = [len(facets) for facets, _nodes in self.assert_owned_contact()]
        self.reopen()
        # Native persistence can renumber volumes: compare a fresh physical
        # connectivity oracle, never saved numeric element labels.
        self.assertEqual(
            [len(facets) for facets, _nodes in self.assert_owned_contact()], expected_counts
        )

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="freecad-contact-ownership-")
        self.doc = App.newDocument("ContactOwnership")
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
        self.mesh = ObjectsFem.makeMeshGmsh(self.doc, "Mesh")
        self.mesh.Shape = self.compound
        self.mesh.ElementOrder = "2nd"
        self.mesh.CharacteristicLengthMax = 8
        self.mesh.CharacteristicLengthMin = 4
        self.mesh.CoherenceMesh = False
        self.analysis.addObject(self.mesh)
        self.contact = ObjectsFem.makeConstraintContact(self.doc, "Contact")
        self.contact.References = [(self.first, ["Face2"]), (self.second, ["Face1"])]
        self.contact.Adjust = "0 mm"
        self.analysis.addObject(self.contact)
        self.prefs = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/General")
        self.previous_groups = self.prefs.GetBool("AnalysisGroupMeshing", False)
        self.had_groups = self.previous_groups == self.prefs.GetBool("AnalysisGroupMeshing", True)
        # Base native CAD entity groups suffice; analysis-object groups are not
        # needed to reproduce the independent-owner conflation.
        self.prefs.SetBool("AnalysisGroupMeshing", False)
        self.mesh_number = 0
        self.doc.recompute()

    def tearDown(self):
        try:
            if self.doc and self.doc.Name in App.listDocuments():
                App.closeDocument(self.doc.Name)
        finally:
            if self.had_groups:
                self.prefs.SetBool("AnalysisGroupMeshing", self.previous_groups)
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
        return tool

    def group_elements(self, name):
        mesh = self.mesh.FemMesh
        groups = [group for group in mesh.Groups if mesh.getGroupName(group) == name]
        self.assertEqual(len(groups), 1, name)
        elements = set(mesh.getGroupElements(groups[0]))
        self.assertTrue(elements, name)
        return elements

    def owned_facet_oracle(self, face, solid):
        """Derive boundary adjacency from native face/volume connectivity only."""
        mesh = self.mesh.FemMesh
        volumes = self.group_elements(solid)
        self.assertTrue(volumes <= set(mesh.Volumes))
        # Native FemMesh tetra10 ordering differs from VTK ordering.  These
        # complete six-node masks were crosschecked through public native
        # connectivity against the retained stock CalculiX surface fragment.
        masks = {1: (0, 1, 2, 4, 5, 6), 2: (0, 1, 3, 4, 7, 8),
                 3: (0, 2, 3, 6, 7, 9), 4: (1, 2, 3, 5, 8, 9)}
        facets, owned_nodes = set(), set()
        for element in self.group_elements(face):
            self.assertIn(element, mesh.Faces)
            face_nodes = set(mesh.getElementNodes(element))
            self.assertEqual(len(face_nodes), 6)
            owned_nodes.update(face_nodes)
            adjacent = [volume for volume in volumes
                        if face_nodes <= set(mesh.getElementNodes(volume))]
            self.assertEqual(len(adjacent), 1, "Each independent face needs one owned volume")
            volume = adjacent[0]
            all_adjacent = [candidate for candidate in mesh.Volumes
                            if face_nodes <= set(mesh.getElementNodes(candidate))]
            self.assertEqual(all_adjacent, adjacent,
                             "Native connectivity must not share this face across owners")
            connectivity = mesh.getElementNodes(volume)
            self.assertEqual(len(connectivity), 10)
            sides = [side for side, indices in masks.items()
                     if {connectivity[index] for index in indices} == face_nodes]
            self.assertEqual(len(sides), 1)
            facets.add((volume, sides[0]))
        self.assertEqual(len(facets), len(self.group_elements(face)))
        return facets, owned_nodes

    def contact_getter(self, rows):
        getter = meshsetsgetter.MeshSetsGetter(
            self.analysis,
            SimpleNamespace(AnalysisType="static", ModelSpace="3D"),
            self.mesh,
            SimpleNamespace(cons_contact=rows),
        )
        for name, mask in calculixutils.define_masks(SimpleNamespace(ModelSpace="3D")).items():
            setattr(getter, "mask_" + name, mask)
        return getter

    def contact_row(self):
        row = {"Object": self.contact}
        self.contact_getter([row]).get_constraints_contact_faces()
        return row

    def assert_owned_contact(self, entities=(("Face2", "Solid1"), ("Face7", "Solid2")),
                             coincident=True, allow_same_region=False):
        expected = [self.owned_facet_oracle(face, solid) for face, solid in entities]
        if not allow_same_region:
            self.assertFalse(expected[0][1].intersection(expected[1][1]))
            self.assertFalse(expected[0][0].intersection(expected[1][0]))
        if coincident:
            union = expected[0][1] | expected[1][1]
            for owner, names in self.contact.References:
                self.assertEqual(set(self.mesh.FemMesh.getNodesByFace(
                    owner.getSubObject(names[0]))), union,
                    "Coordinates alone must expose both independent owners")
        row = self.contact_row()
        stream = io.StringIO()
        write_constraint_contact.write_meshdata_constraint(stream, row, self.contact, None)
        written, current = {}, None
        for line in stream.getvalue().splitlines():
            if line.startswith("*SURFACE,"):
                current = line.split("NAME=", 1)[1]
                written[current] = set()
            else:
                match = re.fullmatch(r"(\d+),S([1-4])", line)
                self.assertIsNotNone(match, line)
                self.assertIsNotNone(current)
                written[current].add(tuple(map(int, match.groups())))
        for key, prefix, (facets, _) in zip(
                ("ContactSlaveFaces", "ContactMasterFaces"), ("DEP", "IND"), expected):
            self.assertEqual(len(row[key]), 1)
            _references, actual, _is_sub_element = row[key][0]
            actual = {tuple(pair) for pair in actual}
            actual_volumes = {volume for volume, _side in actual}
            self.assertTrue({volume for volume, _side in facets} <= actual_volumes)
            self.assertTrue(facets <= actual,
                            "Correctly owned facets must retain exact six-node side identity")
            self.assertEqual(written[prefix + self.contact.Name], actual,
                             "The stock writer must serialize the actual native facet pairs")
            with self.subTest(side=key, seam="native getter"):
                self.assertEqual(actual, facets)
            with self.subTest(side=key, seam="stock writer"):
                self.assertEqual(written[prefix + self.contact.Name], facets)
        return expected

    def assert_contact_rejected(self):
        with self.assertRaisesRegex((ValueError, RuntimeError),
                                    "(?i)mesh|remesh|regenerat|owner|group|reference|region"):
            self.contact_row()

    def reopen(self):
        filename = str(Path(self.directory.name) / "contact.FCStd")
        self.doc.saveAs(filename)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(filename)
        for attribute, name in (("first", "First"), ("second", "Second"),
                                ("compound", "Compound"), ("analysis", "Analysis"),
                                ("mesh", "Mesh"), ("contact", "Contact")):
            setattr(self, attribute, self.doc.getObject(name))

    def clear_provenance(self):
        self.mesh.ElementGroupNames = []
        self.mesh.ElementGroupReferences = []
        self.mesh.ElementGroupGeometry = ""

    def test_contact_sides_only_export_facets_of_the_selected_native_owner(self):
        self.generate_mesh()
        self.assertFalse(self.mesh.CoherenceMesh)
        self.assert_owned_contact()

    def test_owned_contact_geometry_checks_classify_only_candidate_nodes(self):
        self.generate_mesh()
        classified = []
        previous = sys.getprofile()

        def profile(frame, event, function):
            if event == "c_call" and getattr(function, "__name__", "") == "getNodesByFace":
                classified.append(function.__self__.NodeCount)

        try:
            sys.setprofile(profile)
            self.contact_row()
        finally:
            sys.setprofile(previous)
        self.assertEqual(len(classified), 2)
        self.assertTrue(
            all(count < self.mesh.FemMesh.NodeCount for count in classified),
            "Owned face validation must not scan every node in the mesh",
        )

    def test_volume_nonface_contact_retains_existing_fallback(self):
        self.generate_mesh()
        self.contact.References = [(self.first, ["Solid1"]), (self.second, ["Solid1"])]
        self.mesh.ElementGroupGeometry = "not used by the non-face fallback"
        row = {"Object": self.contact}
        getter = self.contact_getter([row])
        expected = [
            meshtools.get_contact_elements(getter, self.contact, pair)
            for pair in meshtools.pair_obj_reference(self.contact.References)
        ]
        getter.get_constraints_contact_faces()
        self.assertEqual(row["ContactSlaveFaces"], expected[:-1])
        self.assertEqual(row["ContactMasterFaces"], expected[-1:])

    def test_transformed_sparse_node_mesh_preserves_owned_contact(self):
        self.generate_mesh()
        original = self.mesh.FemMesh
        coordinates = original.Nodes
        transformed = Fem.FemMesh()
        offset = App.Vector(11, -7, 3)
        node_ids = {node: 100 + 7 * node for node in coordinates}
        for node, point in coordinates.items():
            point = point - offset
            transformed.addNode(point.x, point.y, point.z, node_ids[node])
        for elements, add in (
            (original.Edges, transformed.addEdge),
            (original.Faces, transformed.addFace),
            (original.Volumes, transformed.addVolume),
        ):
            for element in elements:
                add([node_ids[node] for node in original.getElementNodes(element)], element)
        for group in original.Groups:
            kind = original.getGroupElementType(group)
            new_group = transformed.addGroup(original.getGroupName(group), kind)
            members = original.getGroupElements(group)
            transformed.addGroupElements(
                new_group, [node_ids[node] for node in members] if kind == "Node" else list(members)
            )
        transformed.setTransform(App.Placement(offset, App.Rotation()))
        self.mesh.FemMesh = transformed
        self.assertEqual(set(self.mesh.FemMesh.Nodes), set(node_ids.values()))
        for old, new in node_ids.items():
            self.assertLess((self.mesh.FemMesh.getNodeById(new) - coordinates[old]).Length, 1e-12)
        self.assert_owned_contact()

    def test_contact_batch_reuses_unchanged_validation(self):
        self.generate_mesh()
        rows = [{"Object": self.contact}]
        for _ in range(9):
            contact = ObjectsFem.makeConstraintContact(self.doc, "RepeatedContact")
            contact.References = self.contact.References
            rows.append({"Object": contact})
        getter = self.contact_getter(rows)
        counts = {"geometry": 0, "face": 0}
        previous = sys.getprofile()

        def profile(frame, event, function):
            if event == "call" and frame.f_code.co_name == "get_mesh_geometry_signature":
                counts["geometry"] += 1
            if event == "c_call" and getattr(function, "__name__", "") == "getNodesByFace":
                counts["face"] += 1

        try:
            sys.setprofile(profile)
            getter.get_constraints_contact_faces()
        finally:
            sys.setprofile(previous)
        self.assertLessEqual(counts["geometry"], 2, "Validate geometry at batch entry and exit")
        self.assertEqual(counts["face"], 2, "Validate each unchanged native face only once")
        for row in rows:
            self.assertEqual(row["ContactSlaveFaces"][0][1], rows[0]["ContactSlaveFaces"][0][1])
            self.assertEqual(row["ContactMasterFaces"][0][1], rows[0]["ContactMasterFaces"][0][1])

    def test_reused_getter_follows_changed_contact_references(self):
        self.generate_mesh()
        row = {"Object": self.contact}
        getter = self.contact_getter([row])
        getter.get_constraints_contact_faces()
        previous_slave = row["ContactSlaveFaces"][0][1]
        previous_master = row["ContactMasterFaces"][0][1]
        self.assertNotEqual(previous_slave, previous_master)
        self.contact.References = list(reversed(self.contact.References))
        self.doc.recompute()
        getter.get_constraints_contact_faces()
        self.assertEqual(row["ContactSlaveFaces"][0][1], previous_master)
        self.assertEqual(row["ContactMasterFaces"][0][1], previous_slave)

    def test_reused_getter_rejects_changed_geometry(self):
        self.generate_mesh()
        row = {"Object": self.contact}
        getter = self.contact_getter([row])
        getter.get_constraints_contact_faces()
        self.first.Width = 24
        self.doc.recompute()
        with self.assertRaisesRegex(ValueError, "(?i)geometry|mesh|regenerat"):
            getter.get_constraints_contact_faces()

    def test_reused_getter_rejects_changed_native_groups(self):
        self.generate_mesh()
        row = {"Object": self.contact}
        getter = self.contact_getter([row])
        getter.get_constraints_contact_faces()
        mesh = self.mesh.FemMesh
        group = next(group for group in mesh.Groups if mesh.getGroupName(group) == "Face2")
        mesh.removeGroup(group)
        with self.assertRaisesRegex(ValueError, "(?i)group|mesh|regenerat"):
            getter.get_constraints_contact_faces()

    def test_reused_getter_rejects_added_native_node(self):
        self.generate_mesh()
        row = {"Object": self.contact}
        getter = self.contact_getter([row])
        getter.get_constraints_contact_faces()
        mesh = Fem.FemMesh(self.mesh.FemMesh)
        mesh.addNode(1000, 1000, 1000)
        self.mesh.FemMesh = mesh
        self.assertEqual(
            mesh.NodeCount,
            self.mesh.FemMesh.NodeCount,
            "The current mesh feature must contain the added native node",
        )
        with self.assertRaisesRegex(ValueError, "(?i)node|mesh|regenerat"):
            getter.get_constraints_contact_faces()

    def test_reused_getter_rejects_native_node_motion(self):
        self.generate_mesh()
        row = {"Object": self.contact}
        getter = self.contact_getter([row])
        getter.get_constraints_contact_faces()
        mesh = Fem.FemMesh(self.mesh.FemMesh)
        node = next(iter(mesh.Nodes))
        previous = self.mesh.FemMesh.getNodeById(node)
        mesh.setTransform(App.Placement(App.Vector(0, 0, 1), App.Rotation()))
        self.mesh.FemMesh = mesh
        self.assertEqual(
            self.mesh.FemMesh.getNodeById(node),
            previous + App.Vector(0, 0, 1),
            "A fresh wrapper must observe motion with unchanged node IDs and count",
        )
        with self.assertRaisesRegex(ValueError, "(?i)node|mesh|regenerat"):
            getter.get_constraints_contact_faces()

    def assert_contact_batch_mutation_rejected(self, mutation):
        self.generate_mesh()
        other = ObjectsFem.makeConstraintContact(self.doc, "OtherContact")
        other.References = self.contact.References
        rows = [
            {
                "Object": contact,
                "ContactSlaveFaces": ["previous slave"],
                "ContactMasterFaces": ["previous master"],
            }
            for contact in (self.contact, other)
        ]
        previous_outputs = [(row["ContactSlaveFaces"], row["ContactMasterFaces"]) for row in rows]
        getter = self.contact_getter(rows)
        injected = False
        previous = sys.getprofile()

        def profile(frame, event, function):
            nonlocal injected
            if (
                not injected
                and event == "c_call"
                and getattr(function, "__name__", "") == "getNodesByFace"
            ):
                injected = True
                mutation()

        try:
            sys.setprofile(profile)
            with self.assertRaisesRegex(ValueError, "(?i)reference|group|node|mesh|regenerat"):
                getter.get_constraints_contact_faces()
        finally:
            sys.setprofile(previous)
        self.assertTrue(injected, "Fault injection must occur during native face validation")
        for row, (slave, master) in zip(rows, previous_outputs):
            self.assertIs(
                row["ContactSlaveFaces"],
                slave,
                "A failed batch must not publish even its earlier Contact rows",
            )
            self.assertIs(row["ContactMasterFaces"], master)

    def test_contact_batch_reference_change_does_not_publish_partial_rows(self):
        def swap_references():
            self.contact.References = list(reversed(self.contact.References))

        self.assert_contact_batch_mutation_rejected(swap_references)

    def test_contact_batch_native_group_change_does_not_publish_partial_rows(self):
        def remove_face_group():
            mesh = self.mesh.FemMesh
            group = next(group for group in mesh.Groups if mesh.getGroupName(group) == "Face2")
            mesh.removeGroup(group)

        self.assert_contact_batch_mutation_rejected(remove_face_group)

    def test_contact_batch_native_mesh_change_does_not_publish_partial_rows(self):
        def add_native_node():
            mesh = Fem.FemMesh(self.mesh.FemMesh)
            mesh.addNode(1000, 1000, 1000)
            self.mesh.FemMesh = mesh

        self.assert_contact_batch_mutation_rejected(add_native_node)

    def test_save_reopen_preserves_owned_contact_before_recompute(self):
        self.generate_mesh()
        old_nodes = [nodes for _facets, nodes in self.assert_owned_contact()]
        self.reopen()
        # Native element IDs may renumber; owned node identities must not.
        self.assertEqual([nodes for _facets, nodes in self.assert_owned_contact()], old_nodes)

    def test_reference_swap_rebind_and_remesh_follow_current_owner(self):
        self.generate_mesh()
        self.assert_owned_contact()
        self.contact.References = list(reversed(self.contact.References))
        self.doc.recompute()
        self.assert_owned_contact((("Face7", "Solid2"), ("Face2", "Solid1")))
        self.contact.References = [(self.first, ["Face1"]), (self.second, ["Face2"])]
        self.doc.recompute()
        self.assert_owned_contact((("Face1", "Solid1"), ("Face8", "Solid2")), coincident=False)
        self.generate_mesh()
        self.assert_owned_contact((("Face1", "Solid1"), ("Face8", "Solid2")), coincident=False)

    def test_compound_reorder_requires_remesh_and_keeps_original_owners(self):
        self.generate_mesh()
        self.assert_owned_contact()
        self.compound.Links = [self.second, self.first]
        self.doc.recompute()
        self.assert_contact_rejected()
        self.generate_mesh()
        self.assert_owned_contact((("Face8", "Solid2"), ("Face1", "Solid1")))

    def test_link_occurrence_move_requires_remesh_then_resolves_owned_facets(self):
        left = self.doc.addObject("App::Link", "Left")
        right = self.doc.addObject("App::Link", "Right")
        left.setLink(self.first)
        right.setLink(self.first)
        right.Placement.Base = App.Vector(20, 0, 0)
        self.compound.Links = [left, right]
        self.contact.References = [(left, ["Face2"]), (right, ["Face1"])]
        self.generate_mesh()
        self.assert_owned_contact()
        self.reopen()
        self.assert_owned_contact()
        left, right = self.doc.getObject("Left"), self.doc.getObject("Right")
        left.Placement.Base = App.Vector(3, 4, 5)
        right.Placement.Base = App.Vector(23, 4, 5)
        self.compound.Links = [right, left]
        self.doc.recompute()
        self.assert_contact_rejected()
        self.generate_mesh()
        self.assert_owned_contact((("Face8", "Solid2"), ("Face1", "Solid1")))

    def test_expanded_face_rejects_stale_mesh_even_when_old_nodes_still_fit(self):
        self.generate_mesh()
        expected = self.assert_owned_contact()
        for box in (self.first, self.second):
            box.Width = 24
            box.Height = 15
        self.doc.recompute()
        for (owner, names), (_facets, old_nodes) in zip(self.contact.References, expected):
            self.assertTrue(old_nodes <= set(self.mesh.FemMesh.getNodesByFace(
                owner.getSubObject(names[0]))))
        self.assert_contact_rejected()

    def test_missing_geometry_owner_is_not_a_coordinate_fallback(self):
        self.generate_mesh()
        self.assert_owned_contact()
        self.mesh.Shape = None
        self.doc.recompute()
        self.assert_contact_rejected()

    def test_incomplete_provenance_fails_closed(self):
        for name, missing in (("ElementGroupNames", []), ("ElementGroupReferences", []),
                              ("ElementGroupGeometry", "")):
            with self.subTest(property=name):
                self.generate_mesh()
                self.assert_owned_contact()
                setattr(self.mesh, name, missing)
                self.assert_contact_rejected()

    def test_missing_owned_face_group_fails_closed(self):
        self.generate_mesh()
        self.assert_owned_contact()
        mesh = self.mesh.FemMesh
        group = next(group for group in mesh.Groups if mesh.getGroupName(group) == "Face2")
        mesh.removeGroup(group)
        self.assert_contact_rejected()

    def test_absent_external_reference_never_silently_exports_partial_surface(self):
        self.generate_mesh()
        self.assert_owned_contact()
        external = self.doc.addObject("Part::Box", "External")
        external.Placement.Base = App.Vector(100, 0, 0)
        self.contact.References = [(external, ["Face1"]), (self.second, ["Face1"])]
        self.doc.recompute()
        self.assert_contact_rejected()

    def test_ambiguous_legacy_mesh_rejects_coincident_contact_owners(self):
        self.generate_mesh()
        self.assert_owned_contact()
        self.clear_provenance()
        self.assert_contact_rejected()

    def test_unambiguous_noncoincident_legacy_contact_remains_supported(self):
        self.second.Placement.Base = App.Vector(40, 0, 0)
        self.generate_mesh()
        self.clear_provenance()
        self.assert_owned_contact(coincident=False)

    def test_normal_noncoincident_contact_with_native_analysis_groups(self):
        self.second.Placement.Base = App.Vector(40, 0, 0)
        self.mesh.CoherenceMesh = True
        self.prefs.SetBool("AnalysisGroupMeshing", True)
        self.generate_mesh()
        self.assert_owned_contact(coincident=False)

    def test_welded_shared_face_patch_is_ambiguous_not_arbitrarily_assigned(self):
        # Native Boolean fragments retain two volumes with one shared kernel
        # face.  A coherence flag alone need not produce conforming triangulation
        # from two independently owned surfaces, so verify actual adjacency.
        fragments = self.doc.addObject("Part::Feature", "Fragments")
        fragments.Shape = self.first.Shape.generalFuse([self.second.Shape])[0]
        self.assertEqual(len(fragments.Shape.Solids), 2)
        shared = [index for index, face in enumerate(fragments.Shape.Faces, 1)
                  if sum(any(face.isSame(candidate) for candidate in solid.Faces)
                         for solid in fragments.Shape.Solids) > 1]
        self.assertEqual(len(shared), 1)
        face_name = f"Face{shared[0]}"
        self.mesh.Shape = fragments
        self.contact.References = [(fragments, [face_name]), (fragments, [face_name])]
        self.mesh.CoherenceMesh = True
        self.generate_mesh()
        mesh = self.mesh.FemMesh
        patches = [set(mesh.getElementNodes(face)) for face in self.group_elements(face_name)]
        incidences = [sum(patch <= set(mesh.getElementNodes(volume)) for volume in mesh.Volumes)
                      for patch in patches]
        self.assertTrue(any(count > 1 for count in incidences),
                        "The native coherent mesh must genuinely share a selected patch")
        self.assert_contact_rejected()

    def test_node_union_cannot_invent_a_facet_absent_from_owned_face_cells(self):
        self.generate_mesh()
        mesh = self.mesh.FemMesh
        group = next(group for group in mesh.Groups if mesh.getGroupName(group) == "Face2")
        elements = set(mesh.getGroupElements(group))
        omitted = None
        for element in sorted(elements):
            patch = set(mesh.getElementNodes(element))
            other_nodes = {node for other in elements - {element}
                           for node in mesh.getElementNodes(other)}
            if patch <= other_nodes:
                omitted = element
                break
        self.assertIsNotNone(omitted,
                             "A native interior patch must share every node with neighbours")
        # Focused fault injection, not a project repair: remove one face-cell
        # membership while retaining its entire node union in neighbouring cells.
        # The CAD geometry, mesh cells and all nodes remain untouched.  Export
        # must follow actual owned face cells, never invent the omitted patch.
        mesh.removeGroup(group)
        replacement = mesh.addGroup("Face2", "Face")
        mesh.addGroupElements(replacement, sorted(elements - {omitted}))
        self.assert_owned_contact()

    def test_partially_overlapping_coplanar_legacy_faces_need_owned_provenance(self):
        self.second.Placement.Base = App.Vector(20, 8, 0)
        self.generate_mesh()
        first = self.first.getSubObject("Face2")
        second = self.second.getSubObject("Face1")
        common = first.common(second).Area
        self.assertGreater(common, 0)
        self.assertLess(common, first.Area)
        self.clear_provenance()
        self.assert_contact_rejected()

    def test_true_self_contact_and_native_encoded_alias_preserve_one_canonical_face(self):
        self.contact.References = [(self.compound, ["Face2"]), (self.compound, ["Face2"])]
        self.generate_mesh()
        entity = (("Face2", "Solid1"), ("Face2", "Solid1"))
        self.assert_owned_contact(entity, coincident=False, allow_same_region=True)
        alias = self.compound.Shape.getElementMappedName("Face2")
        self.assertTrue(alias)
        self.assertNotEqual(alias, "Face2")
        self.contact.References = [(self.compound, ["Face2"]), (self.compound, [alias])]
        self.doc.recompute()
        self.assert_owned_contact(entity, coincident=False, allow_same_region=True)

    def test_legacy_self_contact_direct_box_and_encoded_compound_face_are_equivalent(self):
        self.generate_mesh()
        self.clear_provenance()
        # Face1 is the outside face, not the independently duplicated interface.
        alias = self.compound.Shape.getElementMappedName("Face1")
        self.assertTrue(alias)
        self.assertNotEqual(alias, "Face1")
        self.contact.References = [(self.first, ["Face1"]), (self.compound, [alias])]
        self.doc.recompute()
        self.assert_owned_contact((("Face1", "Solid1"), ("Face1", "Solid1")),
                                  coincident=False, allow_same_region=True)

    def test_legacy_self_contact_direct_box_and_native_hierarchy_are_equivalent(self):
        self.generate_mesh()
        self.clear_provenance()
        assembly = self.doc.addObject("App::Part", "Assembly")
        assembly.addObject(self.first)
        self.doc.recompute()
        path = self.first.Name + ".Face1"
        self.assertIn(self.first, assembly.getSubObjectList(path))
        self.contact.References = [(self.first, ["Face1"]), (assembly, [path])]
        self.doc.recompute()
        self.assert_owned_contact((("Face1", "Solid1"), ("Face1", "Solid1")),
                                  coincident=False, allow_same_region=True)

    def test_legacy_distinct_link_occurrence_paths_cannot_collapse_to_the_shared_base(self):
        self.generate_mesh()
        self.clear_provenance()
        # Reuse real native connectivity as an imported/legacy context.  There
        # is deliberately no meshed CAD owner from which to infer occurrence.
        self.mesh.Shape = None
        base = self.doc.addObject("App::Part", "AssemblyBase")
        base.addObject(self.first)
        outer = self.doc.addObject("App::Part", "Assembly")
        left = self.doc.addObject("App::Link", "Left")
        right = self.doc.addObject("App::Link", "Right")
        for link in (left, right):
            link.setLink(base)
            outer.addObject(link)
        self.doc.recompute()
        paths = [link.Name + "." + self.first.Name + ".Face1" for link in (left, right)]
        chains = [outer.getSubObjectList(path) for path in paths]
        self.assertIn(left, chains[0])
        self.assertIn(right, chains[1])
        self.assertNotEqual(chains[0], chains[1])
        resolved = [outer.resolveSubElement(path)[0] for path in paths]
        self.assertEqual(resolved[0], resolved[1],
                         "Control must expose resolved-base occurrence information loss")
        self.contact.References = [(outer, [path]) for path in paths]
        self.doc.recompute()
        self.assert_contact_rejected()

    def test_legacy_missing_mesh_owner_does_not_accept_malformed_face_as_face_one(self):
        self.generate_mesh()
        self.clear_provenance()
        self.mesh.Shape = None
        owner, mapped, indexed = self.first.resolveSubElement("Facex1")
        self.assertEqual(owner, self.first)
        self.assertFalse(mapped)
        self.assertEqual(indexed, "Facex1")
        # Native shape lookup permissively returns a real Face1 for this invalid
        # name.  Contact must validate the unresolved reference before falling
        # back to geometric node/facet search in an imported legacy mesh.
        permissive = self.first.getSubObject("Facex1")
        self.assertEqual(permissive.ShapeType, "Face")
        self.assertTrue(permissive.isSame(self.first.getSubObject("Face1")))
        self.contact.References = [(self.first, ["Facex1"]), (self.first, ["Facex1"])]
        self.doc.recompute()
        with self.assertRaisesRegex(ValueError, "(?i)unresolved|invalid.*reference"):
            self.contact_row()
