# SPDX-License-Identifier: LGPL-2.1-or-later
"""Beam output availability through native export and saved result interfaces."""

import os
from pathlib import Path
import tempfile
import unittest

import FreeCAD as App
from femtest.app.test_beam_section_forces_native import make_straight_case
from femtools.ccxtools import FemToolsCcx
from femtools.force_accounting import solver_binary


class TestBeamSectionForcesLifecycle(unittest.TestCase):
    def setUp(self):
        previous = App.activeDocument()
        self.previous_document = previous.Name if previous is not None else None
        self.doc = None
        self.temporary = None
        self.preferences = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/Ccx")
        self.cpu_value = self.preferences.GetInt("AnalysisNumCPUs", 1)
        self.cpu_present = self.preferences.GetInt(
            "AnalysisNumCPUs", 1
        ) == self.preferences.GetInt("AnalysisNumCPUs", 2)
        self.addCleanup(self._restore_session)
        self.preferences.SetInt("AnalysisNumCPUs", 2)
        retained = os.environ.get("B960_WITNESS_ROOT")
        if retained:
            self.directory = Path(retained) / self._testMethodName
            self.directory.mkdir()
        else:
            self.temporary = tempfile.TemporaryDirectory(prefix="freecad-beam-lifecycle-")
            self.directory = Path(self.temporary.name)
        self.doc = App.newDocument("BeamSectionForcesLifecycle")
        self.model = make_straight_case(self.doc, load_vector=(100.0, 0.0, 0.0))
        self.model.solver.NativeAccountingSolver = os.environ.get(
            "B960_TEST_SOLVER", solver_binary(self.model.solver)
        )
        self.fea = FemToolsCcx(analysis=self.model.analysis, solver=self.model.solver)
        self.fea.update_objects()
        self.fea.setup_working_dir(str(self.directory))

    def _restore_session(self):
        try:
            if self.doc is not None and self.doc.Name in App.listDocuments():
                App.closeDocument(self.doc.Name)
        finally:
            if self.temporary is not None:
                self.temporary.cleanup()
            if self.cpu_present:
                self.preferences.SetInt("AnalysisNumCPUs", self.cpu_value)
            else:
                self.preferences.RemInt("AnalysisNumCPUs")
            if self.previous_document in App.listDocuments():
                App.setActiveDocument(self.previous_document)

    def test_unsupported_solver_settings_are_refused_without_silent_changes(self):
        # Each setting requests behavior outside the declared native beam-end
        # domain. Refusal must preserve what the user actually selected.
        unsupported = (
            ("Output3d", True),
            ("GeometricalNonlinearity", True),
            ("AnalysisType", "frequency"),
            ("SplitInputWriter", True),
            ("ExcludeBendingStiffness", True),
            ("ReducedIntegration", False),
        )
        for name, value in unsupported:
            with self.subTest(setting=name):
                original = getattr(self.model.solver, name)
                try:
                    setattr(self.model.solver, name, value)
                    self.doc.recompute()
                    with self.assertRaises(ValueError):
                        self.fea.write_inp_file()
                    self.assertEqual(getattr(self.model.solver, name), value)
                    self.assertTrue(self.model.solver.BeamSectionForces)
                finally:
                    setattr(self.model.solver, name, original)

    def test_physical_load_change_withdraws_current_but_preserves_saved_history(self):
        self.assertFalse(self.fea.check_prerequisites())
        self.assertFalse(self.fea.write_inp_file())
        self.assertEqual(self.fea.ccx_run(), 0, self.fea.ccx_stdout + self.fea.ccx_stderr)
        self.fea.load_results()
        results = [
            obj
            for obj in self.model.analysis.Group
            if getattr(getattr(obj, "Proxy", None), "Type", "")
            == "Fem::BeamSectionForceResult"
        ]
        self.assertEqual(len(results), 1)
        result = results[0]
        data = result.Proxy.getSectionForces(result)
        self.assertTrue(result.Status.startswith("Current"), result.Status)
        literal, digest = result.SectionData, result.SectionHash
        root = [
            row
            for row in data["frames"][-1]["samples"]
            if (row["element"], row["node"], row["end"]) == (1, self.model.root_node, 1)
        ]
        self.assertEqual(len(root), 1)
        self.assertLessEqual(
            (App.Vector(*root[0]["force_global"]) - App.Vector(-100, 0, 0)).Length / 100,
            0.01,
        )

        # Change the native physical input, without touching its generated
        # solver deck or attempting another solve.
        self.model.force.Force = "101 N"
        self.doc.recompute()
        with self.assertRaises(ValueError):
            result.Proxy.getSectionForces(result)
        self.assertFalse(result.Status.startswith("Current"), result.Status)
        self.assertEqual(result.SectionData, literal)
        self.assertEqual(result.SectionHash, digest)
        self.assertEqual(result.Proxy.getSectionForces(result, historical=True), data)
