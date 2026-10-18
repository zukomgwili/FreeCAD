# SPDX-License-Identifier: LGPL-2.1-or-later

"""Native diagnostic readiness is deliberately narrower than mesh acceptance."""

from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest

import FreeCAD as App
import Fem
import ObjectsFem
from femmesh import gmshtools, quality
from femtools.ccxtools import FemToolsCcx


class TestMeshQuality(unittest.TestCase):
    def test_geometry_changed_during_check_cannot_acquire_old_diagnostics(self):
        signature = quality.input_fingerprint(self.mesh)
        self.solid.Radius = 4
        self.doc.recompute()
        result = quality.record(
            self.mesh,
            "CalculiX",
            "*ERROR in e_c3d: nonpositive jacobian",
            input_signature=signature,
        )
        self.assertEqual(result["state"], "Unchecked")
        self.assertIn("historical", result["summary"])

    def setUp(self):
        self.doc = App.newDocument("MeshQualityReadiness")
        self.solid = self.doc.addObject("Part::Cylinder", "Solid")
        self.solid.Radius = 3
        self.solid.Height = 5
        self.mesh = ObjectsFem.makeMeshGmsh(self.doc, "Mesh")
        self.mesh.Shape = self.solid
        self.doc.recompute()

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def test_unchecked_and_native_ids_are_not_quality_acceptance(self):
        self.assertEqual(quality.readiness(self.mesh)["state"], "Unchecked")
        # Same native diagnostic grammar consumed by the existing highlighter.
        native = Fem.FemMesh()
        node_ids = [
            native.addNode(*point) for point in ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1))
        ]
        element = native.addVolume(node_ids)
        self.mesh.FemMesh = native
        stdout = (
            "*ERROR in e_c3d: nonpositive jacobian\n"
            f"determinant in element {element}\n"
            f"determinant in element {element}\n"
        )
        tool = SimpleNamespace(mesh=self.mesh, ccx_stdout=stdout, ccx_binary="ccx")
        self.assertTrue(FemToolsCcx.has_nonpositive_jacobians(tool))
        result = quality.readiness(self.mesh)
        self.assertEqual(result["state"], "Known failed")
        self.assertEqual(result["evidence"]["element_ids"], [element])
        self.assertEqual(result["evidence"]["element_id_namespace"], "FreeCAD input deck")
        quality.record(self.mesh, "CalculiX", "", exit_code=0)
        self.assertEqual(self.mesh.QualityState, "Known failed")
        native.addNode(2, 2, 2)
        self.mesh.FemMesh = native
        self.assertEqual(quality.readiness(self.mesh)["state"], "Unchecked")

    def test_control_geometry_and_cold_restore_invalidate(self):
        text = "Warning : Volume mesh: 7 elements with jac. < 0"
        for change in ("controls", "geometry", "restore"):
            with self.subTest(change=change):
                quality.record(self.mesh, "Gmsh", text)
                self.assertEqual(self.mesh.QualityState, "Known failed")
                if change == "controls":
                    self.mesh.SecondOrderLinear = True
                elif change == "geometry":
                    self.solid.Radius = 4
                    self.doc.recompute()
                else:
                    with tempfile.TemporaryDirectory() as directory:
                        path = str(Path(directory) / "quality.FCStd")
                        self.doc.saveAs(path)
                        App.closeDocument(self.doc.Name)
                        self.doc = App.openDocument(path)
                        self.mesh = self.doc.Mesh
                result = quality.readiness(self.mesh)
                self.assertEqual(result["state"], "Unchecked")
                self.assertEqual(result["evidence"]["source"], "Gmsh")

    @unittest.skipUnless(shutil.which("gmsh"), "Gmsh binary required")
    def test_curved_quadratic_native_warning_preserves_raw_output(self):
        torus = self.doc.addObject("Part::Torus", "Torus")
        torus.Radius1, torus.Radius2, torus.Angle3 = 3, 1, 180
        self.mesh.Shape = torus
        self.mesh.ElementOrder = "2nd"
        self.mesh.HighOrderOptimize = "None"
        self.mesh.CharacteristicLengthMax = 3
        self.mesh.CharacteristicLengthMin = 1
        self.doc.recompute()
        with tempfile.TemporaryDirectory() as directory:
            self.mesh.WorkingDirectory = directory
            tool = gmshtools.GmshTools(self.mesh)
            raw_chunks = []
            tool.process.readyReadStandardError.connect(
                lambda: raw_chunks.append(bytes(tool.process.readAllStandardError()).decode())
            )
            tool.create_mesh()
            self.assertEqual(tool.process.exitCode(), 0)
            self.assertGreater(self.mesh.FemMesh.VolumeCount, 0)
            raw = "".join(raw_chunks) + bytes(tool.process.readAllStandardError()).decode()
            self.assertIn("elements with jac. < 0", raw)
            result = quality.readiness(self.mesh)
            self.assertEqual(result["state"], "Known failed")
            self.assertEqual(result["evidence"]["source"], "Gmsh")
            self.assertEqual(result["evidence"]["element_ids"], [])
            # Native Gmsh warns but imports successfully: import is not a pass.
            self.assertIn("generation attempt", result["evidence"]["scope"])

    @unittest.skipUnless(shutil.which("gmsh"), "Gmsh binary required")
    def test_successful_curved_generation_remains_unchecked(self):
        self.mesh.ElementOrder = "2nd"
        self.mesh.CharacteristicLengthMax = 2
        self.mesh.CharacteristicLengthMin = 1
        self.doc.recompute()
        with tempfile.TemporaryDirectory() as directory:
            self.mesh.WorkingDirectory = directory
            tool = gmshtools.GmshTools(self.mesh)
            tool.create_mesh()
            self.assertEqual(tool.process.exitCode(), 0)
            self.assertGreater(self.mesh.FemMesh.VolumeCount, 0)
            self.assertEqual(quality.readiness(self.mesh)["state"], "Unchecked")
