# SPDX-License-Identifier: LGPL-2.1-or-later
"""Beam output availability through native export and saved result interfaces."""

import hashlib
import json
import os
from pathlib import Path
import shutil
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
        self.cpu_present = self.preferences.GetInt("AnalysisNumCPUs", 1) == self.preferences.GetInt(
            "AnalysisNumCPUs", 2
        )
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
            if getattr(getattr(obj, "Proxy", None), "Type", "") == "Fem::BeamSectionForceResult"
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

    def test_preexisting_frd_alias_is_refused_without_changing_its_target(self):
        for kind in ("symlink", "hardlink"):
            with self.subTest(alias=kind):
                directory = self.directory / kind
                directory.mkdir()
                self.fea.setup_working_dir(str(directory))
                self.assertFalse(self.fea.check_prerequisites())
                self.assertFalse(self.fea.write_inp_file())
                deck = Path(self.fea.inp_file_name)
                frd = deck.with_suffix(".frd")
                target = self.directory / ("protected-" + kind + ".frd")
                original = b"Preexisting user-owned result; the solver must not open this file.\n"
                target.write_bytes(original)
                if kind == "symlink":
                    frd.symlink_to(target)
                else:
                    os.link(target, frd)
                before = target.stat()
                with self.assertRaisesRegex(ValueError, "regular|unshared|symlink"):
                    self.fea.ccx_run()
                after = target.stat()
                self.assertEqual(target.read_bytes(), original)
                self.assertEqual(
                    (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_nlink),
                    (
                        before.st_dev,
                        before.st_ino,
                        before.st_size,
                        before.st_mtime_ns,
                        before.st_nlink,
                    ),
                )
                self.assertTrue(frd.samefile(target))
                self.assertEqual(frd.is_symlink(), kind == "symlink")
                self.assertFalse(deck.with_suffix(".dat").exists())
                self.assertFalse(deck.with_suffix(".sta").exists())
                self.assertFalse(
                    any(
                        getattr(getattr(obj, "Proxy", None), "Type", "")
                        == "Fem::BeamSectionForceResult"
                        and obj.Status.startswith("Current")
                        for obj in self.model.analysis.Group
                    )
                )

    def test_bare_copied_beam_frd_cannot_be_imported_as_stress(self):
        from feminout import importCcxFrdResults

        self.assertFalse(self.fea.check_prerequisites())
        self.assertFalse(self.fea.write_inp_file())
        self.assertEqual(self.fea.ccx_run(), 0, self.fea.ccx_stdout + self.fea.ccx_stderr)
        self.fea.load_results()
        results = [
            obj
            for obj in self.model.analysis.Group
            if getattr(getattr(obj, "Proxy", None), "Type", "") == "Fem::BeamSectionForceResult"
        ]
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].Status.startswith("Current"), results[0].Status)
        self.assertEqual(
            results[0].Proxy.getSectionForces(results[0])["schema"], "CCX_BEAM_SECTION_V1"
        )
        directory = self.directory / "bare"
        directory.mkdir()
        bare = directory / "unbound.frd"
        shutil.copyfile(Path(self.fea.inp_file_name).with_suffix(".frd"), bare)
        self.assertEqual(list(directory.iterdir()), [bare])
        before = {obj.Name for obj in self.doc.Objects}
        with self.assertRaisesRegex(ValueError, "Bare original-beam FRD"):
            importCcxFrdResults.importFrd(str(bare), self.model.analysis)
        self.assertEqual({obj.Name for obj in self.doc.Objects}, before)
        for obj in self.model.analysis.Group:
            if obj.isDerivedFrom("Fem::FemResultObject"):
                for name in (
                    "NodeStressXX",
                    "NodeStressYY",
                    "NodeStressZZ",
                    "NodeStressXY",
                    "NodeStressXZ",
                    "NodeStressYZ",
                ):
                    self.assertFalse(getattr(obj, name), "Unbound beam resultants became stress")
                self.assertFalse(
                    obj.vonMises, "Unbound beam resultants acquired a stress invariant"
                )

    def test_altered_export_metadata_is_refused_before_native_solve(self):
        self.assertFalse(self.fea.check_prerequisites())
        self.assertFalse(self.fea.write_inp_file())
        deck = Path(self.fea.inp_file_name)
        request = deck.with_suffix(".beam-section")
        metadata_path = Path(str(request) + ".json")
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (deck, request)}
        metadata = json.loads(metadata_path.read_text())
        self.assertTrue(metadata["elements"])
        self.assertNotEqual(metadata["elements"][0]["section"], "WrongSection")
        # Only the diagnostic sidecar changes. The stock solver input,
        # native request, physical section and load remain untouched.
        metadata["elements"][0]["section"] = "WrongSection"
        metadata_path.write_text(json.dumps(metadata, sort_keys=True, allow_nan=False))
        with self.assertRaises(ValueError):
            self.fea.ccx_run()
        self.assertEqual(
            {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (deck, request)},
            before,
        )
        self.assertFalse(deck.with_suffix(".dat").exists())
        self.assertFalse(deck.with_suffix(".sta").exists())
        self.assertFalse(
            any(
                getattr(getattr(obj, "Proxy", None), "Type", "") == "Fem::BeamSectionForceResult"
                and obj.Status.startswith("Current")
                for obj in self.model.analysis.Group
            )
        )

    def test_warm_rerun_keeps_export_and_preserves_previous_native_output(self):
        self.assertFalse(self.fea.check_prerequisites())
        self.assertFalse(self.fea.write_inp_file())
        deck = Path(self.fea.inp_file_name)
        request = deck.with_suffix(".beam-section")
        metadata_path = Path(str(request) + ".json")
        exported = {
            path: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (deck, request, metadata_path)
        }

        def current_data():
            results = [
                obj
                for obj in self.model.analysis.Group
                if getattr(getattr(obj, "Proxy", None), "Type", "") == "Fem::BeamSectionForceResult"
            ]
            self.assertEqual(len(results), 1)
            result = results[0]
            self.assertTrue(result.CompletedRun)
            self.assertTrue(result.Status.startswith("Current"), result.Status)
            data = result.Proxy.getSectionForces(result)
            roots = [
                row
                for row in data["frames"][-1]["samples"]
                if (row["element"], row["node"], row["end"]) == (1, self.model.root_node, 1)
            ]
            self.assertEqual(len(roots), 1)
            self.assertLessEqual(
                (App.Vector(*roots[0]["force_global"]) - App.Vector(-100, 0, 0)).Length / 100,
                0.01,
            )
            return data

        self.assertEqual(self.fea.ccx_run(), 0, self.fea.ccx_stdout + self.fea.ccx_stderr)
        self.fea.load_results()
        first = current_data()
        first_request = Path(first["provenance"]["run"]["path"])
        first_output = Path(first["provenance"]["output"])
        preserved = {path: path.read_bytes() for path in (first_request, first_output)}

        # ReRun uses the same genuine stock export, with no Rewrite or edit
        # of geometry, loading, request, metadata or generated solver input.
        self.assertEqual(self.fea.ccx_run(), 0, self.fea.ccx_stdout + self.fea.ccx_stderr)
        self.fea.load_results()
        second = current_data()
        self.assertNotEqual(
            second["provenance"]["run"]["token"], first["provenance"]["run"]["token"]
        )
        self.assertNotEqual(second["provenance"]["output"], str(first_output))
        self.assertEqual(second["provenance"]["request"], first["provenance"]["request"])
        self.assertEqual(
            {path: path.read_bytes() for path in preserved},
            preserved,
        )
        self.assertEqual(
            {
                path: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (deck, request, metadata_path)
            },
            exported,
        )
