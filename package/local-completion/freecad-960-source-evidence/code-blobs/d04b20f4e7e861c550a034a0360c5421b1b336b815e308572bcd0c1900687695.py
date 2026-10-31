# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native beam output must never be relabelled as ordinary mechanical stress."""

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

import FreeCAD as App
from femexamples.ccx_cantilever_base_edge import setup_cantilever_base_edge
from femtools.ccxtools import FemToolsCcx
from femtools.force_accounting import solver_binary


class TestBeamSectionForcesSafety(unittest.TestCase):
    def setUp(self):
        previous = App.activeDocument()
        self.previous_document = previous.Name if previous is not None else None
        self.doc = None
        self.temporary = None
        self.preferences = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/Ccx")
        self.cpu_key = "AnalysisNumCPUs"
        self.cpu_value = self.preferences.GetInt(self.cpu_key, 1)
        self.cpu_present = self.preferences.GetInt(self.cpu_key, 1) == self.preferences.GetInt(
            self.cpu_key, 2
        )
        self.addCleanup(self._restore_session)
        self.preferences.SetInt(self.cpu_key, 2)
        retained = os.environ.get("B960_WITNESS_ROOT")
        if retained:
            self.directory = Path(retained) / self._testMethodName
            self.directory.mkdir()
        else:
            self.temporary = tempfile.TemporaryDirectory(prefix="freecad-beam-output-safety-")
            self.directory = Path(self.temporary.name)
        self.doc = App.newDocument("BeamSectionForcesSafety")
        setup_cantilever_base_edge(self.doc)
        self.solver = self.doc.CalculiXCcxTools
        self.solver.BeamSectionForces = True
        self.solver.Output3d = False
        self.solver.NativeAccountingSolver = os.environ.get(
            "B960_TEST_SOLVER", solver_binary(self.solver)
        )
        self.doc.LoadLine.X1 = self.doc.LoadLine.Y1 = self.doc.LoadLine.Z1 = 0
        self.doc.LoadLine.X2 = 1
        self.doc.LoadLine.Y2 = self.doc.LoadLine.Z2 = 0
        self.doc.Force.Force = "100 N"
        self.doc.recompute()

    def _restore_session(self):
        try:
            if self.doc is not None and self.doc.Name in App.listDocuments():
                App.closeDocument(self.doc.Name)
        finally:
            if self.temporary is not None:
                self.temporary.cleanup()
            if self.cpu_present:
                self.preferences.SetInt(self.cpu_key, self.cpu_value)
            else:
                self.preferences.RemInt(self.cpu_key)
            if self.previous_document in App.listDocuments():
                App.setActiveDocument(self.previous_document)

    def test_relative_solver_selection_is_not_accepted_for_native_beam_output(self):
        binary = Path(self.solver.NativeAccountingSolver).resolve(strict=True)
        relative = os.path.relpath(binary, Path.cwd())
        self.assertFalse(Path(relative).is_absolute())
        self.solver.NativeAccountingSolver = relative
        fea = FemToolsCcx(analysis=self.doc.Analysis, solver=self.solver)
        fea.update_objects()
        fea.setup_working_dir(str(self.directory))
        self.assertFalse(fea.check_prerequisites())
        with self.assertRaises(ValueError):
            fea.write_inp_file()

    def test_saved_local_channel_must_match_its_retained_native_wrench_projection(self):
        fea = FemToolsCcx(analysis=self.doc.Analysis, solver=self.solver)
        fea.update_objects()
        fea.setup_working_dir(str(self.directory))
        self.assertFalse(fea.check_prerequisites())
        self.assertFalse(fea.write_inp_file())
        self.assertEqual(fea.ccx_run(), 0, fea.ccx_stdout + fea.ccx_stderr)
        fea.load_results()
        results = [
            obj
            for obj in self.doc.Analysis.Group
            if getattr(getattr(obj, "Proxy", None), "Type", "") == "Fem::BeamSectionForceResult"
        ]
        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertTrue(result.Status.startswith("Current"), result.Status)
        data = result.Proxy.getSectionForces(result)
        # Retain every genuine native force, moment, basis and identity. A
        # modified scalar must not become a consistent historical action merely
        # because its storage hash was recalculated.
        data["frames"][0]["samples"][0]["native_channels"]["axial"] += 10.0
        literal = json.dumps(data, sort_keys=True, allow_nan=False)
        result.SectionData = literal
        result.SectionHash = hashlib.sha256(literal.encode()).hexdigest()
        with self.assertRaises(ValueError):
            result.Proxy.getSectionForces(result, historical=True)

    def test_disabling_and_rewriting_does_not_relabel_old_beam_frd_as_stress(self):
        fea = FemToolsCcx(analysis=self.doc.Analysis, solver=self.solver)
        fea.update_objects()
        fea.setup_working_dir(str(self.directory))
        self.assertFalse(fea.check_prerequisites())
        self.assertFalse(fea.write_inp_file())
        self.assertEqual(fea.ccx_run(), 0, fea.ccx_stdout + fea.ccx_stderr)
        fea.load_results()
        beam_results = [
            obj
            for obj in self.doc.Analysis.Group
            if getattr(getattr(obj, "Proxy", None), "Type", "") == "Fem::BeamSectionForceResult"
        ]
        self.assertEqual(len(beam_results), 1)
        self.assertTrue(beam_results[0].Status.startswith("Current"), beam_results[0].Status)
        data = beam_results[0].Proxy.getSectionForces(beam_results[0])
        roots = [
            row
            for row in data["frames"][-1]["samples"]
            if (row["element"], row["node"], row["end"]) == (1, 1, 1)
        ]
        self.assertEqual(len(roots), 1)
        self.assertLessEqual(
            (App.Vector(*roots[0]["force_global"]) - App.Vector(-100, 0, 0)).Length / 100,
            0.01,
        )
        frd = Path(fea.inp_file_name).with_suffix(".frd")
        self.assertTrue(frd.is_file(), "The first native run must actually emit an FRD")

        # The next stock export changes only the output request, not geometry
        # or loading. No second solve occurs: the existing FRD is still the
        # first run's force/moment channels, whatever the new flag says.
        self.solver.BeamSectionForces = False
        self.doc.recompute()
        self.assertFalse(fea.write_inp_file())
        self.assertFalse(beam_results[0].Status.startswith("Current"))
        if frd.exists() or frd.is_symlink():
            with self.assertRaises(ValueError):
                fea.load_results()
        else:
            fea.load_results()
        for obj in self.doc.Analysis.Group:
            if obj.isDerivedFrom("Fem::FemResultObject"):
                for name in (
                    "NodeStressXX",
                    "NodeStressYY",
                    "NodeStressZZ",
                    "NodeStressXY",
                    "NodeStressXZ",
                    "NodeStressYZ",
                ):
                    self.assertFalse(getattr(obj, name), "Old beam resultants became stress")
                self.assertFalse(obj.vonMises, "Old beam resultants acquired a stress invariant")
