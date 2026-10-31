# SPDX-License-Identifier: LGPL-2.1-or-later
"""Signed beam resultants through native authoring, export and result interfaces."""

import tempfile
import unittest
import os
from pathlib import Path

import FreeCAD as App
from femexamples.ccx_cantilever_base_edge import setup_cantilever_base_edge
from femtools.ccxtools import FemToolsCcx


class TestBeamSectionForces(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="freecad-beam-resultants-")
        self.doc = App.newDocument("BeamSectionForces")
        setup_cantilever_base_edge(self.doc)
        self.analysis = self.doc.Analysis
        self.solver = self.doc.CalculiXCcxTools

    def tearDown(self):
        App.closeDocument(self.doc.Name)
        self.directory.cleanup()

    def test_native_request_exports_section_forces_in_original_beam_nodes(self):
        self.assertIn("BeamSectionForces", self.solver.PropertiesList)
        self.solver.BeamSectionForces = True
        self.solver.Output3d = False
        fea = FemToolsCcx(analysis=self.analysis, solver=self.solver)
        fea.update_objects()
        fea.setup_working_dir(self.directory.name)
        self.assertFalse(fea.check_prerequisites())
        self.assertFalse(fea.write_inp_file())
        text = Path(fea.inp_file_name).read_text().upper()
        self.assertIn("*ELEMENT, TYPE=B32R", text)
        self.assertIn("*NODE FILE, OUTPUT=2D", text)
        self.assertIn("*EL FILE, OUTPUT=2D, SECTION FORCES\nS, NOE", text)


class TestBeamSectionForcesNative(unittest.TestCase):
    def test_axial_member_ends_have_native_identity_units_and_signed_actions(self):
        from femtools.force_accounting import solver_binary

        doc = App.newDocument("BeamSectionForcesAxial")
        try:
            setup_cantilever_base_edge(doc)
            solver = doc.CalculiXCcxTools
            solver.BeamSectionForces = True
            solver.Output3d = False
            # Change the native load direction, never the generated input.
            doc.LoadLine.X1 = doc.LoadLine.Y1 = doc.LoadLine.Z1 = 0
            doc.LoadLine.X2 = 1
            doc.LoadLine.Y2 = doc.LoadLine.Z2 = 0
            doc.Force.Force = "100 N"
            binary = os.environ.get("FREECAD_BEAM_TEST_SOLVER", solver_binary(solver))
            solver.NativeAccountingSolver = binary
            prefs = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/Ccx")
            previous = prefs.GetString("ccxBinaryPath", "")
            prefs.SetString("ccxBinaryPath", binary)
            prefs.SetInt("AnalysisNumCPUs", 2)
            doc.recompute()
            try:
                with tempfile.TemporaryDirectory(prefix="freecad-beam-axial-") as directory:
                    fea = FemToolsCcx(analysis=doc.Analysis, solver=solver)
                    fea.update_objects()
                    fea.setup_working_dir(directory)
                    self.assertFalse(fea.check_prerequisites())
                    self.assertFalse(fea.write_inp_file())
                    self.assertEqual(fea.ccx_run(), 0, fea.ccx_stdout + fea.ccx_stderr)
                    fea.load_results()
                    results = [obj for obj in doc.Analysis.Group
                               if getattr(getattr(obj, "Proxy", None), "Type", "")
                               == "Fem::BeamSectionForceResult"]
                    self.assertEqual(len(results), 1)
                    data = results[0].Proxy.getSectionForces(results[0])
                    self.assertEqual(data["schema"], "CCX_BEAM_SECTION_V1")
                    self.assertEqual(data["units"], {"length": "mm", "force": "N", "moment": "N*mm"})
                    self.assertEqual(len(data["frames"]), 1)
                    frame = data["frames"][0]
                    self.assertEqual(frame["step"], 1)
                    self.assertEqual(frame["time"], 1.0)
                    self.assertEqual(len(frame["samples"]), 10)
                    roots = [row for row in frame["samples"]
                             if (row["element"], row["node"], row["end"]) == (1, 1, 1)]
                    self.assertEqual(len(roots), 1)
                    # Independent free-body balance: the retained member's
                    # root action is -100 N along X, no applied end couple.
                    force = App.Vector(*roots[0]["force_global"])
                    moment = App.Vector(*roots[0]["moment_global"])
                    self.assertLessEqual((force - App.Vector(-100, 0, 0)).Length / 100, 0.01)
                    self.assertLessEqual(moment.Length / (100 * 8000), 0.01)
                    self.assertTrue(results[0].Status.startswith("Current"))
            finally:
                prefs.SetString("ccxBinaryPath", previous)
        finally:
            App.closeDocument(doc.Name)
