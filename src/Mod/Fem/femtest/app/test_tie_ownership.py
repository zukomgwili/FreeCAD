# SPDX-License-Identifier: LGPL-2.1-or-later

"""Ordinary Tie export must retain independently meshed face ownership."""

import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import FreeCAD as App

import Part

import Fem
import ObjectsFem
from femmesh import gmshtools
from femmesh import meshsetsgetter
from femsolver.calculix import calculixutils
from femtools.ccxtools import FemToolsCcx


@unittest.skipUnless(shutil.which("gmsh"), "Gmsh binary required")
class TestTieOwnership(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="freecad-tie-ownership-")
        self.doc = App.newDocument("TieOwnership")
        self.first = self.doc.addObject("Part::Box", "First")
        self.second = self.doc.addObject("Part::Box", "Second")
        for box in (self.first, self.second):
            box.Length = 10
            box.Width = 10
            box.Height = 10
        self.second.Placement.Base = App.Vector(10, 0, 0)
        self.compound = self.doc.addObject("Part::Compound", "Compound")
        self.compound.Links = [self.first, self.second]
        self.analysis = ObjectsFem.makeAnalysis(self.doc)
        self.solver = ObjectsFem.makeSolverCalculiXCcxTools(self.doc)
        self.analysis.addObject(self.solver)
        material = ObjectsFem.makeMaterialSolid(self.doc)
        material.Material = {
            "Name": "Steel",
            "YoungsModulus": "200000 MPa",
            "PoissonRatio": "0.3",
            "Density": "7900 kg/m^3",
        }
        self.analysis.addObject(material)
        self.tie = ObjectsFem.makeConstraintTie(self.doc, "Tie")
        self.tie.References = [(self.first, ["Face2"]), (self.second, ["Face1"])]
        self.tie.Tolerance = 0
        self.analysis.addObject(self.tie)
        self.mesh = ObjectsFem.makeMeshGmsh(self.doc, "Mesh")
        self.mesh.Shape = self.compound
        self.mesh.ElementOrder = "2nd"
        self.mesh.SecondOrderLinear = False
        self.mesh.CoherenceMesh = False
        self.mesh.CharacteristicLengthMax = 5
        self.mesh.CharacteristicLengthMin = 3
        self.mesh.WorkingDirectory = self.directory.name
        self.analysis.addObject(self.mesh)
        self._generate_mesh()

    def _generate_mesh(self):
        self.doc.recompute()
        mesher = gmshtools.GmshTools(self.mesh)
        mesher.create_mesh()
        self.assertEqual(mesher.process.exitCode(), 0)
        self.assertEqual(mesher.process.exitStatus(), mesher.process.ExitStatus.NormalExit)

    def tearDown(self):
        try:
            if self.doc.Name in App.listDocuments():
                App.closeDocument(self.doc.Name)
        finally:
            self.directory.cleanup()

    def _group_elements(self, name):
        mesh = self.mesh.FemMesh
        groups = [g for g in mesh.Groups if mesh.getGroupName(g) == name]
        self.assertEqual(len(groups), 1, name)
        members = set(mesh.getGroupElements(groups[0]))
        self.assertTrue(members, name)
        return members

    def _owned_facets(self, face, solid):
        """Complete native face/volume incidence is independent of CAD node search."""
        mesh = self.mesh.FemMesh
        # Complete native Tet10 face masks, crosschecked against the retained
        # stock CalculiX surface labels in NativeContactOwnership.
        masks = {
            1: (0, 1, 2, 4, 5, 6),
            2: (0, 1, 3, 4, 7, 8),
            3: (0, 2, 3, 6, 7, 9),
            4: (1, 2, 3, 5, 8, 9),
        }
        facets = set()
        owner_volumes = self._group_elements(solid)
        for face_id in self._group_elements(face):
            nodes = set(mesh.getElementNodes(face_id))
            self.assertEqual(len(nodes), 6)
            adjacent = [v for v in mesh.Volumes if nodes <= set(mesh.getElementNodes(v))]
            self.assertEqual(len(adjacent), 1)
            volume = adjacent[0]
            self.assertIn(volume, owner_volumes)
            connectivity = mesh.getElementNodes(volume)
            sides = [
                side
                for side, indices in masks.items()
                if {connectivity[index] for index in indices} == nodes
            ]
            self.assertEqual(len(sides), 1)
            facets.add((volume, sides[0]))
        self.assertEqual(len(facets), len(self._group_elements(face)))
        return facets

    def _mesh_snapshot(self):
        mesh = self.mesh.FemMesh
        return (
            {node: tuple(point) for node, point in mesh.Nodes.items()},
            {
                element: tuple(mesh.getElementNodes(element))
                for element in mesh.getIdByElementType("All")
            },
            [
                (mesh.getGroupName(g), mesh.getGroupElementType(g), tuple(mesh.getGroupElements(g)))
                for g in mesh.Groups
            ],
            list(self.mesh.ElementGroupNames),
            list(self.mesh.ElementGroupReferences),
            self.mesh.ElementGroupGeometry,
        )

    def _write_surfaces(self):
        tool = FemToolsCcx(analysis=self.analysis, solver=self.solver)
        tool.update_objects()
        tool.setup_working_dir(self.directory.name)
        tool.write_inp_file()
        text = Path(tool.inp_file_name).read_text()
        result, current = {}, None
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("**"):
                continue
            if line.startswith("*"):
                current = None
                if line.upper().startswith("*SURFACE,"):
                    current = next(
                        part.split("=", 1)[1].strip()
                        for part in line.split(",")
                        if part.strip().upper().startswith("NAME=")
                    )
                    self.assertNotIn(current, result)
                    result[current] = set()
            elif current:
                element, side = [part.strip() for part in line.split(",")]
                self.assertTrue(side.startswith("S"))
                pair = (int(element), int(side[1:]))
                self.assertNotIn(pair, result[current])
                result[current].add(pair)
        return result, text

    def _tie_getter(self, rows):
        getter = meshsetsgetter.MeshSetsGetter(
            self.analysis, self.solver, self.mesh, SimpleNamespace(cons_tie=rows)
        )
        for name, mask in calculixutils.define_masks(self.solver).items():
            setattr(getter, "mask_" + name, mask)
        return getter

    def test_stock_writer_preserves_independent_coincident_face_owners(self):
        first = self.first.getSubObject("Face2")
        second = self.second.getSubObject("Face1")
        self.assertFalse(first.isSame(second))
        self.assertAlmostEqual(first.common(second).Area, first.Area, places=10)
        owned_nodes = [
            {
                node
                for face in self._group_elements(name)
                for node in self.mesh.FemMesh.getElementNodes(face)
            }
            for name in ("Face2", "Face7")
        ]
        self.assertFalse(owned_nodes[0] & owned_nodes[1])
        self.assertTrue(
            owned_nodes[0] | owned_nodes[1] <= set(self.mesh.FemMesh.getNodesByFace(first))
        )
        expected = [self._owned_facets("Face2", "Solid1"), self._owned_facets("Face7", "Solid2")]
        self.assertFalse(expected[0] & expected[1])
        before = self._mesh_snapshot()
        written, text = self._write_surfaces()
        self.assertEqual(self._mesh_snapshot(), before)
        for prefix, facets in zip(("TIE_DEP", "TIE_IND"), expected):
            self.assertEqual(written[prefix + self.tie.Name], facets)
        self.assertIn("*TIE, POSITION TOLERANCE=0, ADJUST=NO, NAME=TIE" + self.tie.Name, text)
        self.assertIn(f"TIE_DEP{self.tie.Name}, TIE_IND{self.tie.Name}", text)

    def test_unresolved_tie_face_reports_the_tie_region(self):
        for invalid in (0, 1):
            with self.subTest(invalid_side=invalid):
                references = [(self.first, ["Face2"]), (self.second, ["Face1"])]
                references[invalid] = (references[invalid][0], ["Face999"])
                self.tie.References = references
                with self.assertRaisesRegex(ValueError, "Tie.*unresolved Tie region"):
                    self._write_surfaces()

    def test_shared_volume_patch_reports_ambiguous_tie_ownership(self):
        fragments = self.doc.addObject("Part::Feature", "Fragments")
        fragments.Shape = self.first.Shape.generalFuse([self.second.Shape])[0]
        self.assertEqual(len(fragments.Shape.Solids), 2)
        shared = [
            index
            for index, face in enumerate(fragments.Shape.Faces, 1)
            if sum(
                any(face.isSame(candidate) for candidate in solid.Faces)
                for solid in fragments.Shape.Solids
            )
            > 1
        ]
        self.assertEqual(len(shared), 1)
        face_name = f"Face{shared[0]}"
        self.mesh.Shape = fragments
        self.tie.References = [(fragments, [face_name]), (fragments, [face_name])]
        self.mesh.CoherenceMesh = True
        self._generate_mesh()
        mesh = self.mesh.FemMesh
        patches = [set(mesh.getElementNodes(face)) for face in self._group_elements(face_name)]
        incidences = [
            sum(patch <= set(mesh.getElementNodes(volume)) for volume in mesh.Volumes)
            for patch in patches
        ]
        self.assertTrue(any(count > 1 for count in incidences))
        with self.assertRaisesRegex(ValueError, "ambiguous Tie ownership"):
            self._write_surfaces()

    def test_invalid_later_tie_does_not_publish_earlier_rows(self):
        other = ObjectsFem.makeConstraintTie(self.doc, "InvalidTie")
        other.References = [(self.first, ["Face2"]), (self.second, ["Face999"])]
        rows = [
            {"Object": tie, "TieSlaveFaces": ["old slave"], "TieMasterFaces": ["old master"]}
            for tie in (self.tie, other)
        ]
        previous = [(row["TieSlaveFaces"], row["TieMasterFaces"]) for row in rows]
        with self.assertRaisesRegex(ValueError, "unresolved Tie region"):
            self._tie_getter(rows).get_constraints_tie_faces()
        for row, (slave, master) in zip(rows, previous):
            self.assertIs(row["TieSlaveFaces"], slave)
            self.assertIs(row["TieMasterFaces"], master)

    def test_legacy_fallback_requires_unambiguous_noncoincident_faces(self):
        for coincident in (True, False):
            if not coincident:
                self.second.Placement.Base = App.Vector(40, 0, 0)
                self._generate_mesh()
            self.mesh.ElementGroupNames = []
            self.mesh.ElementGroupReferences = []
            self.mesh.ElementGroupGeometry = ""
            if coincident:
                with self.assertRaisesRegex(
                    ValueError, "coincident regions need owned mesh groups"
                ):
                    self._write_surfaces()
            else:
                before = self._mesh_snapshot()
                written, _text = self._write_surfaces()
                self.assertEqual(
                    written["TIE_DEP" + self.tie.Name], self._owned_facets("Face2", "Solid1")
                )
                self.assertEqual(
                    written["TIE_IND" + self.tie.Name], self._owned_facets("Face7", "Solid2")
                )
                self.assertEqual(self._mesh_snapshot(), before)

    def test_incomplete_tie_provenance_is_rejected(self):
        for index, (name, empty) in enumerate(
            (
                ("ElementGroupNames", []),
                ("ElementGroupReferences", []),
                ("ElementGroupGeometry", ""),
            )
        ):
            with self.subTest(property=name):
                if index:
                    self._generate_mesh()
                # Deliberate negative fixture, never a repair of project data.
                setattr(self.mesh, name, empty)
                with self.assertRaisesRegex(ValueError, "(?i)mesh|provenance|group"):
                    self._tie_getter([{"Object": self.tie}]).get_constraints_tie_faces()

    def test_geometry_reorder_requires_native_remesh_and_preserves_owners(self):
        self.compound.Links = [self.second, self.first]
        self.doc.recompute()
        with self.assertRaisesRegex(ValueError, "(?i)geometry.*regenerate"):
            self._tie_getter([{"Object": self.tie}]).get_constraints_tie_faces()
        self._generate_mesh()
        before = self._mesh_snapshot()
        written, _text = self._write_surfaces()
        self.assertEqual(written["TIE_DEP" + self.tie.Name], self._owned_facets("Face8", "Solid2"))
        self.assertEqual(written["TIE_IND" + self.tie.Name], self._owned_facets("Face1", "Solid1"))
        self.assertEqual(self._mesh_snapshot(), before)

    def test_saved_tie_writes_after_reopen_and_reference_swap(self):
        names = {
            name: getattr(self, name).Name
            for name in ("first", "second", "compound", "analysis", "solver", "tie", "mesh")
        }
        references = [(owner.Name, tuple(names)) for owner, names in self.tie.References]
        path = Path(self.directory.name) / "owned-tie.FCStd"
        self.doc.saveAs(str(path))
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(str(path))
        for attribute, name in names.items():
            setattr(self, attribute, self.doc.getObject(name))
        self.assertEqual(
            [(owner.Name, tuple(names)) for owner, names in self.tie.References], references
        )
        expected = [self._owned_facets("Face2", "Solid1"), self._owned_facets("Face7", "Solid2")]
        for reverse in (False, True):
            if reverse:
                self.tie.References = list(reversed(self.tie.References))
                self.doc.recompute()
            before = self._mesh_snapshot()
            written, _text = self._write_surfaces()
            self.assertEqual(self._mesh_snapshot(), before)
            for prefix, facets in zip(
                ("TIE_DEP", "TIE_IND"), reversed(expected) if reverse else expected
            ):
                self.assertEqual(written[prefix + self.tie.Name], facets)


class TestTieShellCompatibility(unittest.TestCase):
    def test_shell_tie_keeps_stock_reversed_surface_sides(self):
        doc = App.newDocument("TieShellCompatibility")
        self.addCleanup(App.closeDocument, doc.Name)
        analysis = ObjectsFem.makeAnalysis(doc)
        solver = ObjectsFem.makeSolverCalculiXCcxTools(doc)
        analysis.addObject(solver)
        material = ObjectsFem.makeMaterialSolid(doc)
        material.Material = {
            "Name": "Steel",
            "YoungsModulus": "200000 MPa",
            "PoissonRatio": "0.3",
            "Density": "7900 kg/m^3",
        }
        analysis.addObject(material)
        analysis.addObject(ObjectsFem.makeElementGeometry2D(doc, 0.1))
        planes = []
        native = Fem.FemMesh()
        for offset, z in ((0, 0), (3, 2)):
            plane = doc.addObject("Part::Feature", "Plane")
            plane.Shape = Part.makePlane(2, 2, App.Vector(0, 0, z))
            planes.append(plane)
            for index, (x, y) in enumerate(((0, 0), (2, 0), (0, 2)), 1):
                native.addNode(x, y, z, offset + index)
        native.addFace([1, 2, 3], 10)
        native.addFace([4, 5, 6], 20)
        compound = doc.addObject("Part::Compound", "ShellGeometry")
        compound.Links = planes
        mesh = ObjectsFem.makeMeshGmsh(doc)
        mesh.Shape = compound
        mesh.FemMesh = native
        mesh.ElementOrder = "1st"
        analysis.addObject(mesh)
        tie = ObjectsFem.makeConstraintTie(doc)
        tie.References = [(plane, ["Face1"]) for plane in planes]
        analysis.addObject(tie)
        doc.recompute()
        self.assertEqual(mesh.FemMesh.VolumeCount, 0)
        self.assertEqual(set(mesh.FemMesh.Faces), {10, 20})
        with tempfile.TemporaryDirectory(prefix="freecad-tie-shell-") as directory:
            tool = FemToolsCcx(analysis=analysis, solver=solver)
            tool.update_objects()
            tool.setup_working_dir(directory)
            for slave, master in ((False, False), (True, False), (False, True), (True, True)):
                with self.subTest(reversed_slave=slave, reversed_master=master):
                    tie.ReversedSlave = [slave]
                    tie.ReversedMaster = [master]
                    tool.write_inp_file()
                    text = Path(tool.inp_file_name).read_text()
                    self.assertIn(
                        f"*SURFACE, NAME=TIE_DEP{tie.Name}\n" f"10,S{1 if slave else 2}\n", text
                    )
                    self.assertIn(
                        f"*SURFACE, NAME=TIE_IND{tie.Name}\n" f"20,S{1 if master else 2}\n", text
                    )
