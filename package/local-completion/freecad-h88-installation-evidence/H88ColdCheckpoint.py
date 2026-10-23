"""Private saved-copy and separate-process reopen of the actual checkpoint."""
import sys

sys.dont_write_bytecode = True

import json
import os
from pathlib import Path
import unittest

import FreeCAD as App

from H88OriginalCheckpoint import (
    SOURCE, controls, health, material_differences, module_origins, sha,
)

ROOT = Path(__file__).resolve().parent
SAVED = Path(os.environ["H88_SAVE_DIR"]) / "private-checkpoint.FCStd"
SAVE_REPORT = Path(os.environ["H88_SAVE_DIR"]) / "cold-observation.json"


class H88ColdCheckpoint(unittest.TestCase):
    def test_valid_wrapper_and_material_survive_private_save_or_cold_reopen(self):
        saving = os.environ["H88_COLD_PHASE"] == "save"
        source = SOURCE if saving else SAVED
        expected_sha = ("570e7ffd62c4dfb95c7b0bcbb1eafab69f11c5d54152bf9fd840ad0464402a33"
                        if saving else json.loads(SAVE_REPORT.read_text())["saved_sha256"])
        self.assertEqual(sha(source), expected_sha)
        report = {"schema": "FreeCAD-h88-private-cold-roundtrip-v1",
                  "phase": "save" if saving else "cold-reopen",
                  "runtime": App.Version(), "modules": module_origins(),
                  "input_sha256": expected_sha, "no_shape_assignment": True,
                  "no_mesh_or_solve": True, "original_project_mutated": False}
        doc = App.openDocument(str(source))
        try:
            report["controls_before"] = controls(doc)
            wrapper = doc.getObject("Structure671")
            base = doc.getObject("R67C16BoredRail")
            if not saving:
                self.assertEqual(report["controls_before"],
                                 json.loads(SAVE_REPORT.read_text())["controls_after"])
                report["restored_wrapper"] = health(wrapper)
                self.assertTrue(report["restored_wrapper"]["valid"])
                report["restored_material"] = material_differences(
                    self, base.Shape, wrapper.Shape)
            wrapper.touch()
            self.assertIs(wrapper.recompute(), True)
            report["wrapper_after"] = health(wrapper)
            self.assertTrue(report["wrapper_after"]["valid"])
            self.assertEqual(report["wrapper_after"]["solid_count"], 1)
            self.assertTrue(report["wrapper_after"]["closed"])
            report["material_after"] = material_differences(self, base.Shape, wrapper.Shape)
            report["controls_after"] = controls(doc)
            self.assertEqual(report["controls_after"], report["controls_before"])
            if saving:
                self.assertFalse(SAVED.exists(), "Never overwrite retained private evidence")
                doc.saveAs(str(SAVED))
                report["saved_sha256"] = sha(SAVED)
                self.assertEqual(controls(doc), report["controls_before"])
            report["passed"] = True
            print("[H88-COLD-CHECKPOINT]", json.dumps(report, sort_keys=True), flush=True)
        finally:
            App.closeDocument(doc.Name)
            report["input_unchanged"] = sha(source) == expected_sha
            with (Path(os.environ["H88_RUN_DIR"]) / "cold-observation.json").open("x") as stream:
                json.dump(report, stream, indent=2)
                stream.write("\n")


def load_tests(loader, _tests, _pattern):
    return loader.loadTestsFromTestCase(H88ColdCheckpoint)
