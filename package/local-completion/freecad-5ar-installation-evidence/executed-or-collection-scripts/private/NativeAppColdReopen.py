"""Read-only cold restore of a fresh, exact application-bound Tie QA fixture.

AppNativeIdentity runs first in this same process. This witness never writes
input documents, runs a writer/solve or repairs a saved status/fingerprint.
"""

import sys
sys.dont_write_bytecode = True

import hashlib
import json
import os
from pathlib import Path
import shutil
import traceback
import unittest

import FreeCAD as App

from AppNativeIdentity import PINNED_COMMIT, PINNED_REVISION, PINNED_SOLVER


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def string_digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class NativeAppColdReopen(unittest.TestCase):
    def test_fresh_application_tie_history_cold_restore_without_repair(self):
        output = Path(os.environ["APPQA_COLD_OUTPUT"])
        application = Path(os.environ["APPQA_APPLICATION"]).resolve()
        resources = application / "Contents/Resources"
        manifest = Path(os.environ["APPQA_COLD_MANIFEST"]).resolve()
        expected_manifest = os.environ["APPQA_COLD_MANIFEST_SHA256"]
        report = {"passed": False, "application": str(application),
                  "scope": "separate-process app-bound Tie observation history only",
                  "Oomakhi_opened_or_solved": False, "writer_run": False,
                  "solver_solve_run": False, "saved_document_written": False,
                  "status_hash_or_fingerprint_repaired": False}
        protected, before = {}, {}
        doc = None
        try:
            identity = json.loads(Path(os.environ["APPQA_REPORT"]).read_text())
            self.assertTrue(identity["passed"])
            self.assertEqual(identity["application"], str(application))
            self.assertFalse(App.GuiUp)
            self.assertTrue(sys.dont_write_bytecode)
            self.assertEqual(Path(App.getHomePath()).resolve(), resources.resolve())
            self.assertEqual(App.Version()[-1], PINNED_COMMIT)
            self.assertEqual(App.Version()[3], PINNED_REVISION)
            self.assertEqual(digest(manifest), expected_manifest)
            case = json.loads(manifest.read_text())
            self.assertEqual(case["scope"],
                             "native Tie observation persistence; not engineering acceptance")
            self.assertEqual(case["version"], App.Version())
            document = Path(case["document"]).resolve(strict=True)
            self.assertEqual(digest(document), case["document_sha256"])
            movement = case["movement_source"]
            self.assertEqual(movement["status"], "BOUND")
            binary = Path(movement["binary"]).resolve(strict=True)
            self.assertTrue(binary.is_relative_to(resources))
            self.assertEqual(binary,
                             (resources / "data/NativeSolvers/ccx-force-accounting").resolve())
            self.assertEqual(movement["binary_sha256"], PINNED_SOLVER)
            protected = {"witness": Path(__file__), "manifest": manifest,
                         "saved_document": document, "identity_witness":
                         Path(__file__).with_name("AppNativeIdentity.py")}
            for name, path_key, hash_key in (("frd", "path", "sha256"),
                                             ("deck", "deck", "deck_sha256"),
                                             ("request", "request", "request_sha256"),
                                             ("solver", "binary", "binary_sha256")):
                path = Path(movement[path_key]).resolve(strict=True)
                self.assertEqual(digest(path), movement[hash_key])
                protected["bound_" + name] = path
            before = {name: digest(path) for name, path in protected.items()}
            report["protected_before"] = before
            copied = output / "cold-copy.FCStd"
            shutil.copy2(document, copied)
            self.assertEqual(digest(copied), case["document_sha256"])
            doc = App.openDocument(str(copied))
            objects = {name: doc.getObject(case[name]) for name in (
                "analysis", "solver", "mesh", "accounting", "result", "tie", "contact",
                "geometry", "reverse", "rear_cut", "front_cut")}
            self.assertTrue(all(objects.values()))
            analysis, accounting, result = (objects[name] for name in
                                             ("analysis", "accounting", "result"))
            for name in ("solver", "mesh", "accounting", "result", "tie", "contact",
                         "rear_cut", "front_cut"):
                self.assertIn(objects[name], analysis.Group)
            self.assertEqual(result.Analysis, analysis)
            self.assertEqual(result.Mesh, objects["mesh"])
            self.assertEqual(result.AccountingResult, accounting)
            self.assertEqual([obj.Name for obj in result.Contacts], [case["tie"], case["contact"]])
            self.assertEqual(objects["mesh"].Shape, objects["geometry"])
            self.assertEqual(objects["reverse"].Source, objects["geometry"])
            self.assertTrue(objects["rear_cut"].NativeEquilibriumCut)
            self.assertTrue(objects["front_cut"].NativeEquilibriumCut)
            self.assertFalse(objects["tie"].Adjust)
            self.assertFalse(objects["tie"].CyclicSymmetry)
            self.assertEqual((result.PointSide, result.SlaveVertex, result.MasterVertex),
                             (case["point_side"], case["slave_vertex"], case["master_vertex"]))
            for constraint, expected in zip(result.Contacts, case["definition"]["contacts"]):
                actual = [[owner.Name, [name]] for owner, names in constraint.References
                          for name in names]
                self.assertEqual(actual, expected["references_slave_then_master"])
            raw, accounting_raw = result.ObservationData, accounting.AccountingData
            self.assertEqual(string_digest(raw), case["observation_sha256"])
            self.assertEqual(result.ObservationHash, case["observation_hash"])
            self.assertEqual(string_digest(accounting_raw), case["accounting_sha256"])
            observed, metadata = json.loads(raw), json.loads(accounting_raw)
            self.assertEqual(observed["schema"], "FreeCAD.INTERFACE_SIDE_OBSERVATION_V2")
            self.assertEqual(observed["definition"], case["definition"])
            self.assertEqual([row["constraint_kind"] for row in observed["contacts"]],
                             ["Tie", "Contact"])
            self.assertEqual(observed["units"], "mm")
            self.assertEqual(observed["frame"],
                             "Global Cartesian; original reference geometry (not CDIS)")
            self.assertEqual(metadata["schema"], "CCX_FORCE_ACCOUNTING_V2")
            self.assertEqual(metadata["units"], "N and Nmm")
            self.assertEqual(metadata["frame"], "Global Cartesian, original reference-state "
                             "nodal application positions")
            self.assertEqual(metadata["movement_source"], movement)
            self.assertEqual(observed["source"]["accounting"]["name"], case["accounting"])
            self.assertEqual(observed["source"]["frd"], case["frd"])
            self.assertEqual(observed["source"]["observed_time"], case["observed_time"])
            self.assertEqual(observed["source"]["requested_end_time"], case["requested_end_time"])
            self.assertEqual(case["observed_time"], case["requested_end_time"])
            self.assertFalse(observed["engineering_acceptance"])
            self.assertTrue(result.Status.startswith("Historical"), result.Status)
            self.assertTrue(accounting.Status.startswith("Stale"), accounting.Status)
            with self.assertRaises(ValueError):
                result.Proxy.getObservations(result)
            doc.recompute()
            self.assertTrue(result.Status.startswith("Historical"), result.Status)
            self.assertTrue(accounting.Status.startswith("Stale"), accounting.Status)
            self.assertEqual(result.ObservationData, raw)
            self.assertEqual(accounting.AccountingData, accounting_raw)
            with self.assertRaises(ValueError):
                result.Proxy.getObservations(result)
            report["historical_until_explicit_refresh"] = True
            report["literal_observation_sha256"] = string_digest(raw)
            report["literal_accounting_sha256"] = string_digest(accounting_raw)
            result.Proxy.refresh(result)
            self.assertTrue(accounting.Status.startswith("Stale"), accounting.Status)
            report["after_explicit_refresh"] = result.Status
            if result.Status.startswith("Available"):
                refreshed = result.Proxy.getObservations(result)
                self.assertEqual(refreshed["source"]["accounting"]["name"], case["accounting"])
                self.assertEqual(refreshed["source"]["frd"], case["frd"])
                report["unchanged_original_source_revalidated"] = True
            else:
                with self.assertRaises(ValueError):
                    result.Proxy.getObservations(result)
                self.assertEqual(result.ObservationData, raw)
                self.assertEqual(result.ObservationHash, case["observation_hash"])
                report["unchanged_original_source_revalidated"] = False
            report["accounting_not_promoted_to_Current"] = True
            self.assertEqual(digest(copied), case["document_sha256"])
            report["opened_copy_unsaved"] = True
            report["passed"] = True
        except BaseException as error:
            report["error"] = repr(error)
            report["traceback"] = traceback.format_exc()
            raise
        finally:
            if doc is not None:
                App.closeDocument(doc.Name)
            custody_error = None
            if protected and before:
                after = {name: digest(path) for name, path in protected.items()}
                report["protected_after"] = after
                report["protected_inputs_unchanged"] = after == before
                if after != before:
                    report["passed"] = False
                    custody_error = "Protected cold-reopen inputs changed"
            (output / "probe.json").write_text(json.dumps(report, indent=2) + "\n")
            if custody_error:
                raise AssertionError(custody_error)
