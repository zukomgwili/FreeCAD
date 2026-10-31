"""Cold literal beam history through the current application; never rerun analysis."""

import sys

sys.dont_write_bytecode = True

import hashlib
import json
import os
from pathlib import Path
import unittest

import FreeCAD as App
from AppBeam960 import APP, IDENTITY, IDENTITY_PATH, NATIVE_SHA, check_identity
from AppBeam960 import sha, source_origins, write_report


class ColdBeam960(unittest.TestCase):
    def test_saved_literal_axes_case_and_output_request_survive_cold_restore(self):
        self.assertEqual(os.environ["I960_MODE"], "cold")
        self.assertFalse(App.GuiUp)
        identity = check_identity(self)
        path = Path(os.environ["I960_COLD_DOCUMENT"])
        literal_path = Path(os.environ["I960_COLD_LITERAL"])
        self.assertTrue(path.is_absolute() and literal_path.is_absolute())
        self.assertFalse(path.is_symlink() or literal_path.is_symlink())
        document_sha, literal_sha = sha(path), sha(literal_path)
        if os.environ.get("I960_COLD_DOCUMENT_SHA256"):
            self.assertEqual(document_sha, os.environ["I960_COLD_DOCUMENT_SHA256"])
        if os.environ.get("I960_COLD_LITERAL_SHA256"):
            self.assertEqual(literal_sha, os.environ["I960_COLD_LITERAL_SHA256"])
        literal = literal_path.read_text()
        data = json.loads(literal)
        self.assertEqual(hashlib.sha256(literal.encode()).hexdigest(), literal_sha)
        doc = App.openDocument(str(path))
        try:
            results = [
                obj
                for obj in doc.Objects
                if getattr(getattr(obj, "Proxy", None), "Type", "") == "Fem::BeamSectionForceResult"
            ]
            self.assertEqual(len(results), 1)
            result = results[0]
            self.assertTrue(result.Solver.BeamSectionForces)
            self.assertFalse(result.Solver.Output3d)
            self.assertFalse(result.CompletedRun)
            self.assertTrue(result.Status.startswith("Historical"), result.Status)
            self.assertEqual(result.SectionData, literal)
            self.assertEqual(result.SectionHash, literal_sha)
            historical = result.Proxy.getSectionForces(result, historical=True)
            self.assertEqual(historical, data)
            self.assertEqual(historical["schema"], "CCX_BEAM_SECTION_V1")
            self.assertEqual(historical["units"], {"length": "mm", "force": "N", "moment": "N*mm"})
            self.assertEqual(len(historical["frames"]), 1)
            frame = historical["frames"][0]
            self.assertEqual((frame["step"], frame["increment"], frame["time"]), (1, 1, 1.0))
            self.assertEqual(len(frame["samples"]), 10)
            for row in frame["samples"]:
                self.assertEqual(set(row["basis"]), {"e1", "e2", "normal"})
            with self.assertRaisesRegex(ValueError, "historical|withdrawn"):
                result.Proxy.getSectionForces(result)
            self.assertFalse(result.Status.startswith("Current"))
            self.assertEqual(result.Proxy.getSectionForces(result, historical=True), historical)
            self.assertEqual(result.SectionData, literal)
            self.assertEqual(result.SectionHash, literal_sha)
            observation = {
                "schema": "FreeCAD-960-cold-beam-history-v1",
                "passed": True,
                "application": str(APP),
                "commit": IDENTITY["commit"],
                "revision": IDENTITY["revision"],
                "native_sha256": NATIVE_SHA,
                "document": {"path": str(path), "sha256": document_sha},
                "literal": {"path": str(literal_path), "sha256": literal_sha},
                "case": historical["provenance"]["case"],
                "frames": len(historical["frames"]),
                "samples": len(frame["samples"]),
                "status": result.Status,
                "completed_run": result.CompletedRun,
                "source_inputs_rebound_or_history_promoted_current": False,
                "analysis_solver_rerun": False,
                "input_unchanged": True,
                "source_or_build_import_override": False,
                "identity": identity,
            }
        finally:
            App.closeDocument(doc.Name)
        self.assertEqual(sha(path), document_sha)
        self.assertEqual(sha(literal_path), literal_sha)
        write_report("cold-observation.json", observation)


class ColdSuite(unittest.TestSuite):
    def run(self, result, debug=False):
        super().run(result, debug=debug)
        passed = bool(result.wasSuccessful() and not result.skipped and result.testsRun == 1)
        write_report(
            "regression.json",
            {
                "schema": "FreeCAD-960-installation-regression-v1",
                "passed": passed,
                "mode": "cold",
                "application": str(APP),
                "gui": False,
                "commit": IDENTITY["commit"],
                "revision": IDENTITY["revision"],
                "native_sha256": NATIVE_SHA,
                "identity_sha256": sha(IDENTITY_PATH),
                "expected_tests": 1,
                "executed_tests": result.testsRun,
                "selected_test_ids": [
                    "ColdBeam960.ColdBeam960.test_saved_literal_axes_case_and_output_request_survive_cold_restore"
                ],
                "skipped": [test.id() for test, _reason in result.skipped],
                "failures": [test.id() for test, _traceback in result.failures],
                "errors": [test.id() for test, _traceback in result.errors],
                "source_or_build_import_override": False,
                "native_solver_override": False,
                "only_public_native_interfaces": True,
                "analysis_solver_rerun": False,
                "original_project_opened_changed_or_solved": False,
                "module_sha256": sha(__file__),
                "final_module_origins": source_origins(),
            },
        )
        return result


def load_tests(loader, _tests, _pattern):
    return ColdSuite(loader.loadTestsFromTestCase(ColdBeam960))
