# SPDX-License-Identifier: LGPL-2.1-or-later
"""Separate-process, read-only restore of the saved analytical Tie observation.

Root alone launches this through run_native_gate. Only a byte-copy of the
pinned private software fixture is opened. No writer, solve, save, geometry
edit, Current assignment or fingerprint/hash repair is performed.
"""

import sys
sys.dont_write_bytecode = True

import ctypes
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import traceback
import unittest

import FreeCAD as App
import Fem
import Part


REPOSITORY = Path("/Users/zukomgwili/src/FreeCAD")
BUILD = REPOSITORY / "build/release"
MANIFEST = Path(
    "/private/tmp/freecad-5ar-wYCAxF/native-tie-persistence-first/freecad_user_temp/"
    "freecad-tie-accounting-native-8mpdvwnk/tie-cold-case.json"
)
MANIFEST_SHA256 = "b36058cbca6a7dd2e1b40bbc820a56cbaa4c112ad63803728357135a6fbdacdb"
DOCUMENT_SHA256 = "cb28d8c793c42496017fe8d7875ca2fc351887412cb735e679294d0d9b163702"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def string_digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class NativeTieColdReopen(unittest.TestCase):
    def test_pinned_native_tie_observation_is_historical_in_a_separate_process(self):
        output = Path(os.environ["FIVEAR_RUN"])
        report = {
            "passed": False,
            "scope": "separate cold-process analytical Tie observation history only",
            "Oomakhi_opened_or_solved": False,
            "writer_run": False,
            "solver_run": False,
            "document_saved": False,
            "status_or_hash_repaired": False,
        }
        doc = None
        protected = {}
        before = {}
        try:
            self.assertFalse(App.GuiUp)
            self.assertTrue(sys.dont_write_bytecode)
            self.assertEqual(Path(App.getHomePath()).resolve(), BUILD.resolve())
            self.assertEqual(digest(MANIFEST), MANIFEST_SHA256)
            case = json.loads(MANIFEST.read_text())
            document = Path(case["document"])
            self.assertEqual(case["document_sha256"], DOCUMENT_SHA256)
            self.assertEqual(digest(document), DOCUMENT_SHA256)
            protected = {
                "witness": Path(__file__), "manifest": MANIFEST, "saved_document": document,
                "version_header": BUILD / "src/Build/Version.h",
                "executable": BUILD / "bin/FreeCADCmd",
                "native_fem": BUILD / "Mod/Fem/Fem.so",
                "native_part": BUILD / "Mod/Part/Part.so",
                "native_app": BUILD / "lib/libFreeCADApp.dylib",
            }
            for key, path_key, hash_key in (("frd", "path", "sha256"),
                                             ("deck", "deck", "deck_sha256"),
                                             ("request", "request", "request_sha256"),
                                             ("solver", "binary", "binary_sha256")):
                path = Path(case["movement_source"][path_key])
                self.assertEqual(digest(path), case["movement_source"][hash_key])
                protected["bound_" + key] = path
            for name, relative in {
                "ObjectsFem": "ObjectsFem.py",
                "femtools.force_accounting": "femtools/force_accounting.py",
                "femresult.contact_observation": "femresult/contact_observation.py",
                "femresult.contact_observation_source": "femresult/contact_observation_source.py",
                "femobjects.result_contact_observation": "femobjects/result_contact_observation.py",
            }.items():
                actual = Path(importlib.import_module(name).__file__).resolve()
                source = REPOSITORY / "src/Mod/Fem" / relative
                self.assertEqual(actual, (BUILD / "Mod/Fem" / relative).resolve(), name)
                self.assertEqual(digest(actual), digest(source), name)
                protected["source:" + name] = source
                protected["copied:" + name] = actual
            before = {name: digest(path) for name, path in protected.items()}
            report["protected_before"] = before
            header = protected["version_header"].read_text()
            for macro, actual in (("FCRevision", App.Version()[3]),
                                  ("FCRepositoryHash", App.Version()[-1])):
                match = re.search(r'^#define\s+' + macro + r'\s+"([^\"]+)"', header, re.M)
                self.assertIsNotNone(match, macro)
                self.assertEqual(actual, match.group(1), macro)
            report["runtime"] = App.Version()
            report["saved_runtime"] = case["version"]
            dyld = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
            dyld._NSGetExecutablePath.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
            dyld._NSGetExecutablePath.restype = ctypes.c_int
            size = ctypes.c_uint32(4096)
            buffer = ctypes.create_string_buffer(size.value)
            self.assertEqual(dyld._NSGetExecutablePath(buffer, ctypes.byref(size)), 0)
            executable = Path(os.fsdecode(buffer.value)).resolve()
            self.assertEqual(executable, protected["executable"].resolve())
            dyld._dyld_image_count.restype = ctypes.c_uint32
            dyld._dyld_get_image_name.argtypes = [ctypes.c_uint32]
            dyld._dyld_get_image_name.restype = ctypes.c_char_p
            images = [Path(os.fsdecode(dyld._dyld_get_image_name(index))).resolve()
                      for index in range(dyld._dyld_image_count())]
            for key in ("native_fem", "native_part", "native_app"):
                self.assertIn(protected[key].resolve(), images)
            self.assertEqual(Path(Fem.__file__).resolve(), protected["native_fem"].resolve())
            self.assertEqual(Path(Part.__file__).resolve(), protected["native_part"].resolve())

            copied = output / "cold-copy.FCStd"
            shutil.copy2(document, copied)
            self.assertEqual(digest(copied), DOCUMENT_SHA256)
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
                refs = [[owner.Name, [name]] for owner, names in constraint.References
                        for name in names]
                self.assertEqual(refs, expected["references_slave_then_master"])

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
            self.assertEqual(metadata["frame"],
                             "Global Cartesian, original reference-state "
                             "nodal application positions")
            self.assertEqual(metadata["movement_source"], case["movement_source"])
            self.assertEqual(metadata["movement_source"]["status"], "BOUND")
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
            report["opened_copy_unsaved"] = digest(copied) == DOCUMENT_SHA256
            self.assertTrue(report["opened_copy_unsaved"])
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
