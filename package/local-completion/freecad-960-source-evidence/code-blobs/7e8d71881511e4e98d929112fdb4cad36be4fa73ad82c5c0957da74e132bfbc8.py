"""Separate-process public save/reopen qualification; never rerun a solver."""
import hashlib
import json
import os
from pathlib import Path
import unittest

import FreeCAD as App

ROOT = Path(__file__).resolve().parent


class TestColdBeam(unittest.TestCase):
    def test_saved_literal_axes_case_and_output_option_survive_cold_restore(self):
        config = json.loads((ROOT / "cold-source.json").read_text())
        path, literal = Path(config["document"]), Path(config["literal"])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), config["document_sha256"])
        expected = literal.read_text()
        self.assertEqual(hashlib.sha256(expected.encode()).hexdigest(), config["literal_sha256"])
        doc = App.openDocument(str(path))
        try:
            results = [obj for obj in doc.Objects if
                       getattr(getattr(obj, "Proxy", None), "Type", "") == "Fem::BeamSectionForceResult"]
            self.assertEqual(len(results), 1)
            result = results[0]
            self.assertTrue(result.Solver.BeamSectionForces)
            self.assertFalse(result.Solver.Output3d)
            self.assertFalse(result.CompletedRun)
            self.assertTrue(result.Status.startswith("Historical"), result.Status)
            self.assertEqual(result.SectionData, expected)
            self.assertEqual(result.SectionHash, config["literal_sha256"])
            historical = result.Proxy.getSectionForces(result, historical=True)
            self.assertEqual(historical, json.loads(expected))
            with self.assertRaisesRegex(ValueError, "historical|withdrawn"):
                result.Proxy.getSectionForces(result)
            self.assertEqual(result.Proxy.getSectionForces(result, historical=True), historical)
            print("[BEAM960-COLD]", json.dumps({"literal_sha256": result.SectionHash,
                  "frames": len(historical["frames"]), "case": historical["provenance"]["case"],
                  "status": result.Status, "rerun": False}), flush=True)
        finally:
            App.closeDocument(doc.Name)


def load_tests(loader, _tests, _pattern):
    return loader.loadTestsFromTestCase(TestColdBeam)
