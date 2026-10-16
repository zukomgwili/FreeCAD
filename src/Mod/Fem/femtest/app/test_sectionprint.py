# SPDX-License-Identifier: LGPL-2.1-or-later

"""Section Print must select one oriented incident side, not both volumes."""

import unittest
import tempfile
import re
import shutil
from pathlib import Path

import FreeCAD as App
import Fem
import ObjectsFem
import Part
from femmesh.meshsetsgetter import MeshSetsGetter
from femsolver.calculix.calculixutils import define_masks
from femtools.membertools import AnalysisMember


class TestSectionPrint(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("SectionPrintSides")
        self.analysis = ObjectsFem.makeAnalysis(self.doc, "Analysis")
        self.solver = ObjectsFem.makeSolverCalculiXCcxTools(self.doc)
        self.analysis.addObject(self.solver)
        self.geometry = self.doc.addObject("Part::Feature", "Section")
        self.geometry.Shape = Part.Face(Part.makePolygon([
            App.Vector(0, 0, 0), App.Vector(1, 0, 0),
            App.Vector(0, 1, 0), App.Vector(0, 0, 0),
        ]))
        mesh = Fem.FemMesh()
        for index, point in enumerate(((0, 0, 0), (1, 0, 0), (0, 1, 0),
                                       (0, 0, -1), (0, 0, 1)), 1):
            mesh.addNode(*point, index)
        mesh.addVolume([1, 2, 3, 4], 10)
        mesh.addVolume([2, 1, 3, 5], 20)
        self.mesh = ObjectsFem.makeMeshGmsh(self.doc)
        self.mesh.Shape = self.geometry
        self.mesh.FemMesh = mesh
        self.analysis.addObject(self.mesh)
        self.section = ObjectsFem.makeConstraintSectionPrint(self.doc)
        self.section.References = [(self.geometry, "Face1")]
        self.analysis.addObject(self.section)
        self.doc.recompute()

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def getter(self):
        getter = MeshSetsGetter(self.analysis, self.solver, self.mesh,
                               AnalysisMember(self.analysis))
        masks = define_masks(self.solver)
        for name in getter.face_masks:
            getter.face_masks[name] = masks[name.removeprefix("mask_")]
        getter.get_constraints_sectionprint_faces()
        return getter

    def test_internal_patch_has_one_oriented_incident_side(self):
        getter = self.getter()
        refs, sides, is_sub_element = getter.member.cons_sectionprint[0]["SectionPrintFaces"][0]
        self.assertTrue(is_sub_element)
        self.assertEqual(sides, [[10, 1]])

    def reverse_reference(self):
        shape = self.geometry.Shape.copy()
        shape.reverse()
        self.geometry.Shape = shape
        self.doc.recompute()

    def test_reversed_internal_reference_selects_other_volume(self):
        self.reverse_reference()
        getter = self.getter()
        self.assertEqual(getter.member.cons_sectionprint[0]["SectionPrintFaces"][0][1], [[20, 1]])

    def test_external_face_is_kept_in_either_cad_orientation(self):
        mesh = Fem.FemMesh()
        for node, point in self.mesh.FemMesh.Nodes.items():
            mesh.addNode(point.x, point.y, point.z, node)
        mesh.addVolume([1, 2, 3, 4], 10)
        self.mesh.FemMesh = mesh
        for reverse in (False, True):
            if reverse:
                self.reverse_reference()
            getter = self.getter()
            self.assertEqual(getter.member.cons_sectionprint[0]["SectionPrintFaces"][0][1], [[10, 1]])

    def test_multiple_sections_choose_sides_independently(self):
        opposite = self.doc.addObject("Part::Feature", "OppositeFace")
        shape = self.geometry.Shape.copy()
        shape.reverse()
        opposite.Shape = shape
        other = ObjectsFem.makeConstraintSectionPrint(self.doc, "OtherSection")
        other.References = [(opposite, "Face1")]
        self.analysis.addObject(other)
        self.doc.recompute()
        result = {item["Object"].Name: item["SectionPrintFaces"][0][1]
                  for item in self.getter().member.cons_sectionprint}
        self.assertEqual(result, {self.section.Name: [[10, 1]], other.Name: [[20, 1]]})

    def test_save_cold_reopen_preserves_oriented_ownership(self):
        self.reverse_reference()
        names = [obj.Name for obj in (self.analysis, self.solver, self.mesh,
                                     self.geometry, self.section)]
        with tempfile.TemporaryDirectory() as directory:
            filename = directory + "/section.FCStd"
            self.doc.saveAs(filename)
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(filename)
            (self.analysis, self.solver, self.mesh, self.geometry,
             self.section) = [self.doc.getObject(name) for name in names]
            self.doc.recompute(None, True)
            # Mesh persistence may renumber elements; check the physical owner.
            getter = self.getter()
            sides = getter.member.cons_sectionprint[0]["SectionPrintFaces"][0][1]
            self.assertEqual(len(sides), 1)
            element, side = sides[0]
            points = [getter.femnodes_mesh[node] for node in getter.femelement_table[element]]
            self.assertGreater(sum(point.z for point in points), 0)
            self.assertEqual(side, 1)
            self.assertLess(self.geometry.Shape.normalAt(0, 0).z, 0)

    def test_shell_elements_are_unchanged(self):
        mesh = Fem.FemMesh()
        for node, point in self.mesh.FemMesh.Nodes.items():
            mesh.addNode(point.x, point.y, point.z, node)
        mesh.addFace([1, 2, 3], 10)
        self.mesh.FemMesh = mesh
        refs, sides, is_sub_element = self.getter().member.cons_sectionprint[0]["SectionPrintFaces"][0]
        self.assertFalse(is_sub_element)
        self.assertEqual(sides, [10])

    def test_nonmanifold_patch_is_rejected(self):
        mesh = Fem.FemMesh()
        for node, point in self.mesh.FemMesh.Nodes.items():
            mesh.addNode(point.x, point.y, point.z, node)
        mesh.addNode(0, 0, 2, 6)
        for nodes, element in (([1, 2, 3, 4], 10), ([2, 1, 3, 5], 20),
                               ([2, 1, 3, 6], 30)):
            mesh.addVolume(nodes, element)
        self.mesh.FemMesh = mesh
        with self.assertRaisesRegex(ValueError, "manifold"):
            self.getter()

    def test_ambiguous_overlapping_incidence_is_rejected(self):
        mesh = Fem.FemMesh()
        for node, point in self.mesh.FemMesh.Nodes.items():
            mesh.addNode(point.x, point.y, -2 if node == 5 else point.z, node)
        mesh.addVolume([1, 2, 3, 4], 10)
        mesh.addVolume([2, 1, 3, 5], 20)
        self.mesh.FemMesh = mesh
        with self.assertRaisesRegex(ValueError, "unique oriented"):
            self.getter()

    def test_placed_face_uses_global_mesh_coordinates(self):
        placement = App.Placement(App.Vector(3, -2, 5), App.Rotation(App.Vector(1, 2, 3), 70))
        mesh = Fem.FemMesh()
        for node, point in self.mesh.FemMesh.Nodes.items():
            moved = placement.multVec(point)
            mesh.addNode(moved.x, moved.y, moved.z, node)
        mesh.addVolume([1, 2, 3, 4], 10)
        mesh.addVolume([2, 1, 3, 5], 20)
        self.geometry.Placement = placement
        self.mesh.FemMesh = mesh
        self.doc.recompute()
        self.assertEqual(self.getter().member.cons_sectionprint[0]["SectionPrintFaces"][0][1],
                         [[10, 1]])

    def test_all_supported_solid_face_masks(self):
        triangle = [(0, 0), (1, 0), (0, 1)]
        square = [(0, 0), (1, 0), (1, 1), (0, 1)]
        tet_edges = [(0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3)]
        hex_edges = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6),
                     (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)]
        wedge_edges = [(0, 1), (1, 2), (2, 0), (3, 4), (4, 5), (5, 3),
                       (0, 3), (1, 4), (2, 5)]
        for family, outline, edges in (("tetra", triangle, tet_edges),
                                       ("hexa", square, hex_edges),
                                       ("penta", triangle, wedge_edges)):
            for quadratic in (False, True):
                with self.subTest(family=family, quadratic=quadratic):
                    mesh = Fem.FemMesh()
                    node_ids = {}

                    def node_at(point):
                        key = tuple(point)
                        if key not in node_ids:
                            node_ids[key] = mesh.addNode(*key)
                        return node_ids[key]

                    for element, sign in ((10, -1), (20, 1)):
                        if family == "tetra":
                            corners = [App.Vector(x, y, 0) for x, y in outline]
                            corners.append(App.Vector(0, 0, sign))
                        else:
                            corners = [App.Vector(x, y, z) for z in (sign, 0)
                                       for x, y in outline]
                        points = list(corners)
                        if quadratic:
                            points.extend((corners[i]+corners[j])/2 for i, j in edges)
                        mesh.addVolume([node_at(point) for point in points], element)
                    points = [App.Vector(x, y, 0) for x, y in outline]
                    self.geometry.Shape = Part.Face(Part.makePolygon(points + points[:1]))
                    self.mesh.FemMesh = mesh
                    self.doc.recompute()
                    getter = self.getter()
                    sides = getter.member.cons_sectionprint[0]["SectionPrintFaces"][0][1]
                    self.assertEqual(len(sides), 1)
                    self.assertEqual(sides[0][0], 10)


@unittest.skipUnless(shutil.which("ccx"), "Requires a real CalculiX executable on PATH")
class TestSectionPrintEquilibrium(unittest.TestCase):
    def test_uniform_stress_signed_force_moment_area_and_multiple_sections(self):
        """A constant-stress patch is exact; no coarse-mesh stress recovery tolerance."""
        from femtools.ccxtools import FemToolsCcx

        doc = App.newDocument("SectionPrintEquilibrium")
        try:
            analysis = ObjectsFem.makeAnalysis(doc, "Analysis")
            solver = ObjectsFem.makeSolverCalculiXCcxTools(doc)
            analysis.addObject(solver)
            geometry = doc.addObject("Part::Feature", "TwoBlocks")
            geometry.Shape = Part.makeCompound([
                Part.makeBox(1, 1, 1), Part.makeBox(1, 1, 1, App.Vector(1, 0, 0))])
            material = ObjectsFem.makeMaterialSolid(doc)
            material.Material = {"Name": "UniformStress", "YoungsModulus": "200000 MPa",
                                 "PoissonRatio": "0.0", "Density": "7900 kg/m^3"}
            analysis.addObject(material)
            mesh = Fem.FemMesh()
            nodes = {}
            for x in range(3):
                for y in range(2):
                    for z in range(2):
                        nodes[x, y, z] = mesh.addNode(x, y, z)
            for x in range(2):
                mesh.addVolume([nodes[p] for p in (
                    (x, 0, 1), (x+1, 0, 1), (x+1, 1, 1), (x, 1, 1),
                    (x, 0, 0), (x+1, 0, 0), (x+1, 1, 0), (x, 1, 0))])
            mesh_obj = ObjectsFem.makeMeshGmsh(doc, "Mesh")
            mesh_obj.Shape = geometry
            mesh_obj.FemMesh = mesh
            analysis.addObject(mesh_obj)

            def face_at(x, nx):
                return next(f"Face{i}" for i, face in enumerate(geometry.Shape.Faces, 1)
                            if abs(face.CenterOfMass.x-x) < 1e-8
                            and abs(face.normalAt(0, 0).x-nx) < 1e-8)

            fixed = ObjectsFem.makeConstraintFixed(doc)
            fixed.References = [(geometry, face_at(0, -1))]
            analysis.addObject(fixed)
            pressure = ObjectsFem.makeConstraintPressure(doc)
            pressure.References = [(geometry, face_at(2, 1))]
            pressure.Pressure = "1 MPa"
            analysis.addObject(pressure)
            for name, x, nx in (("Internal", 1, 1), ("Reversed", 1, -1),
                                ("External", 2, 1)):
                section = ObjectsFem.makeConstraintSectionPrint(doc, name)
                section.References = [(geometry, face_at(x, nx))]
                analysis.addObject(section)
            doc.recompute()
            with tempfile.TemporaryDirectory() as directory:
                solver.WorkingDir = directory
                prefs = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/General")
                overwrite = prefs.GetBool("OverwriteSolverWorkingDirectory", True)
                try:
                    prefs.SetBool("OverwriteSolverWorkingDirectory", False)
                    fea = FemToolsCcx(analysis=analysis, solver=solver)
                    self.assertTrue(fea.run())
                finally:
                    prefs.SetBool("OverwriteSolverWorkingDirectory", overwrite)
                self.assertTrue(fea.results_present)
                data = Path(directory, "Mesh.dat").read_text()
                for name, sign in (("Internal", 1), ("Reversed", -1), ("External", 1)):
                    with self.subTest(section=name):
                        block = re.search(
                            rf"statistics for surface set SECTIONFACE{name.upper()}.*?"
                            r"(?=statistics for surface set|\Z)", data, re.S).group()
                        def values(title):
                            match = re.search(title + r"[^\n]*\n\s*\n([^\n]+)", block)
                            self.assertIsNotNone(match, title)
                            return [float(v) for v in match.group(1).split()]
                        force_moment = values("total surface force")
                        center_normal = values("center of gravity and mean normal")
                        about_center = values("moment about the center of gravity")
                        area = values("area, normal force")[0]
                        # p*A=1N, r=(x,.5,.5); moment=r cross F.
                        for actual, expected in zip(force_moment,
                                                    (-sign, 0, 0, 0, -.5*sign, .5*sign)):
                            self.assertAlmostEqual(actual, expected, places=6)
                        for actual, expected in zip(center_normal[3:], (sign, 0, 0)):
                            self.assertAlmostEqual(actual, expected, places=6)
                        self.assertAlmostEqual(area, 1, places=6)
                        for actual in about_center:
                            self.assertAlmostEqual(actual, 0, places=6)
        finally:
            App.closeDocument(doc.Name)
