# SPDX-License-Identifier: LGPL-2.1-or-later

"""Standalone RBE coverage must not depend on an Elastic Connector existing."""

import io
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest

import FreeCAD as App
import ObjectsFem
from femmesh import gmshtools
from femtools.elastic_connector import rigid_body_node_ids, validation_errors


@unittest.skipUnless(shutil.which("gmsh"), "Gmsh binary required")
class TestRigidBodyPreflight(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="freecad-rbe-preflight-")
        self.doc = App.newDocument("RigidBodyPreflight")
        self.shape = self.doc.addObject("Part::Box", "Box")
        self.analysis = ObjectsFem.makeAnalysis(self.doc)
        self.solver = ObjectsFem.makeSolverCalculiXCcxTools(self.doc)
        self.analysis.addObject(self.solver)
        self.bodies = []
        for face in ("Face1", "Face3"):
            body = ObjectsFem.makeConstraintRigidBody(self.doc)
            body.References = [(self.shape, [face])]
            for axis in "XYZ":
                setattr(body, "TranslationalMode" + axis, "Constraint")
                setattr(body, "RotationalMode" + axis, "Constraint")
            self.analysis.addObject(body)
            self.bodies.append(body)
        self.mesh = ObjectsFem.makeMeshGmsh(self.doc, "Mesh")
        self.mesh.Shape = self.shape
        self.mesh.ElementOrder = "1st"
        self.mesh.CharacteristicLengthMax = 4
        self.mesh.CharacteristicLengthMin = 2
        self.mesh.WorkingDirectory = self.directory.name
        self.analysis.addObject(self.mesh)
        self.doc.recompute()
        tool = gmshtools.GmshTools(self.mesh)
        tool.create_mesh()
        self.assertEqual(tool.process.exitCode(), 0)

    def tearDown(self):
        App.closeDocument(self.doc.Name)
        self.directory.cleanup()

    def errors(self):
        return validation_errors(self.analysis, self.solver, self.mesh)

    def test_incompatible_shared_prescribed_translations_are_rejected(self):
        self.bodies[1].Displacement = App.Vector(0.1, 0, 0)
        self.assertTrue(any("incompatible" in error.lower() for error in self.errors()))

    def test_matching_zero_overlap_and_cold_ownership_are_supported(self):
        self.assertEqual(self.errors(), [])
        path = str(Path(self.directory.name) / "rbe.FCStd")
        names = [body.Name for body in self.bodies]
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        self.analysis = self.doc.Analysis
        self.solver = self.doc.SolverCcxTools
        self.mesh = self.doc.Mesh
        self.bodies = [self.doc.getObject(name) for name in names]
        self.assertEqual(self.errors(), [])
        self.doc.Box.Length = 11
        self.doc.recompute()
        self.assertTrue(any("changed mesh geometry" in error for error in self.errors()))

    def test_disjoint_standalone_regions_have_distinct_external_ports(self):
        self.bodies[1].References = [(self.shape, ["Face2"])]
        # Regenerate native ownership after changing the selected regions.
        gmshtools.GmshTools(self.mesh).create_mesh()
        self.assertEqual(self.errors(), [])
        ids = [
            node
            for body in self.bodies
            for node in rigid_body_node_ids(self.analysis, self.mesh, body)
        ]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreater(min(ids), max(self.mesh.FemMesh.Nodes))
        from femsolver.calculix import write_constraint_rigidbody as writer

        output = io.StringIO()
        context = SimpleNamespace(analysis=self.analysis, mesh_object=self.mesh)
        for body in self.bodies:
            writer.write_constraint(output, {}, body, context)
        for body in self.bodies:
            ref, rot = rigid_body_node_ids(self.analysis, self.mesh, body)
            self.assertIn(f"REF NODE={ref}, ROT NODE={rot}", output.getvalue())

    def test_unqualified_overlap_is_diagnostic_not_a_blanket_rejection(self):
        from femtools.rigid_body import validation_diagnostics

        self.bodies[1].TranslationalModeX = "Free"
        diagnostics = validation_diagnostics(self.analysis, self.solver, self.mesh)
        self.assertTrue(any(item["severity"] == "warning" for item in diagnostics))
        self.assertEqual(self.errors(), [])

    def test_standalone_line_with_all_rotations_prescribed_is_not_a_connector_port(self):
        self.bodies[0].References = [(self.shape, ["Edge1"])]
        gmshtools.GmshTools(self.mesh).create_mesh()
        self.assertEqual(self.errors(), [])

    @unittest.skipUnless(shutil.which("ccx"), "CalculiX binary required")
    def test_matching_zero_overlap_uses_unchanged_native_writer_and_solver(self):
        from femtools.ccxtools import FemToolsCcx

        material = ObjectsFem.makeMaterialSolid(self.doc)
        material.Material = {
            "Name": "Rigid preflight",
            "YoungsModulus": "200000 MPa",
            "PoissonRatio": "0.3",
        }
        self.analysis.addObject(material)
        self.doc.recompute()
        self.assertEqual(self.errors(), [])
        fea = FemToolsCcx(analysis=self.analysis, solver=self.solver)
        fea.update_objects()
        fea.setup_working_dir(self.directory.name)
        fea.write_inp_file()
        self.assertEqual(fea.ccx_run(), 0)
        self.assertIn("*WARNING reading *RIGID BODY", fea.ccx_stdout)
        self.assertIn("no rigid", fea.ccx_stdout)
