"""Literal-bundle deployment qualification; no source or build import overlay.

The root supervisor supplies a frozen, location-specific manifest. Existing
shipped tests own all contact author/write/solve/import and GUI exercises.
"""
import sys

sys.dont_write_bytecode = True

import ctypes
import hashlib
import importlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import unittest

import FreeCAD as App

REPOSITORY = Path("/Users/zukomgwili/src/FreeCAD")
MANIFEST_PATH = Path(os.environ["F9II_INSTALL_MANIFEST"])
MANIFEST_BYTES = MANIFEST_PATH.read_bytes()
MANIFEST = json.loads(MANIFEST_BYTES)
RESULTS = {}
REGRESSION_MODULES = (
    "femtest.app.test_ccxtools",
    "femtest.app.test_force_accounting",
    "femtest.app.test_mesh_quality",
    "femtest.app.test_contact_observation",
    "femtest.app.test_contact_observation_source",
    "femtest.app.test_movement_provenance",
    "femtest.app.test_geometry_signature",
    "femtest.app.test_reference_groups",
)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_origins():
    resources = Path(MANIFEST["application"]) / "Contents/Resources"
    origins = {}
    for entry in sys.path:
        actual = Path(entry or os.getcwd()).resolve()
        for forbidden in (REPOSITORY / "src", REPOSITORY / "build"):
            if actual.is_relative_to(forbidden):
                raise AssertionError("Source/build import path: " + str(actual))
    for name, module in tuple(sys.modules.items()):
        origin = getattr(module, "__file__", None)
        if not origin:
            continue
        actual = Path(origin).resolve()
        for forbidden in (REPOSITORY / "src", REPOSITORY / "build"):
            if actual.is_relative_to(forbidden):
                raise AssertionError("Source/build module: " + name + ": " + str(actual))
        if name.lower().startswith("fem") or name in ("ObjectsFem", "TestFemApp", "TestFemGui"):
            if not actual.is_relative_to(resources):
                raise AssertionError("Non-bundle FEM module: " + name + ": " + str(actual))
            origins[name] = {"path": str(actual), "sha256": sha(actual)}
    return origins


class App9iiIdentity(unittest.TestCase):
    def test_exact_application_identity_and_loaded_native_origins(self):
        manifest = MANIFEST
        application = Path(manifest["application"])
        self.assertTrue(application.is_absolute())
        self.assertEqual(application.resolve(strict=True), application)
        self.assertFalse(application.is_symlink())
        resources = application / "Contents/Resources"
        runtime = App.Version()
        self.assertEqual(runtime[:3], ["27", "1", "0"])
        self.assertEqual(runtime[3], manifest["revision"])
        self.assertEqual(runtime[-1], manifest["commit"])
        self.assertEqual(bool(App.GuiUp), manifest["gui"])
        self.assertEqual(Path(App.getHomePath()).resolve(), resources)
        self.assertTrue(sys.dont_write_bytecode)
        self.assertNotIn("FREECAD_CONTACT_STATE_SOLVER", os.environ)
        expected = manifest["expected_native_files"]
        for filename, wanted in expected.items():
            path = Path(filename)
            self.assertEqual(path.resolve(strict=True), path)
            self.assertTrue(path.is_relative_to(resources))
            self.assertFalse(path.is_symlink())
            self.assertEqual(sha(path), wanted)
        for relative, wanted in manifest["expected_source_files"].items():
            path = resources / relative
            self.assertEqual(path.resolve(strict=True), path)
            self.assertFalse(path.is_symlink())
            self.assertEqual(sha(path), wanted, relative)

        dyld = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        dyld._NSGetExecutablePath.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        dyld._NSGetExecutablePath.restype = ctypes.c_int
        size = ctypes.c_uint32(4096)
        buffer = ctypes.create_string_buffer(size.value)
        self.assertEqual(dyld._NSGetExecutablePath(buffer, ctypes.byref(size)), 0)
        executable = Path(os.fsdecode(buffer.value)).resolve()
        self.assertEqual(executable, resources / "bin" / ("FreeCAD" if App.GuiUp else "FreeCADCmd"))
        self.assertEqual(sha(executable), expected[str(executable)])

        modules = {name: importlib.import_module(name) for name in ("Fem", "Part", "Materials")}
        modules["FreeCAD"] = App
        if App.GuiUp:
            modules.update({name: importlib.import_module(name) for name in ("FreeCADGui", "FemGui")})
        dyld._dyld_image_count.restype = ctypes.c_uint32
        dyld._dyld_get_image_name.argtypes = [ctypes.c_uint32]
        dyld._dyld_get_image_name.restype = ctypes.c_char_p
        images = [Path(os.fsdecode(dyld._dyld_get_image_name(index))).resolve()
                  for index in range(dyld._dyld_image_count())]
        loaded = {}
        libraries = ["libFreeCADBase.dylib", "libFreeCADApp.dylib"]
        if App.GuiUp:
            libraries.append("libFreeCADGui.dylib")
        for name in libraries:
            wanted = resources / "lib" / name
            self.assertEqual([path for path in images if path.name == name], [wanted])
            self.assertEqual(sha(wanted), expected[str(wanted)])
            loaded[name] = {"path": str(wanted), "sha256": sha(wanted)}
        for name, module in modules.items():
            wanted = resources / "lib" / (name + ".so")
            origin = getattr(module, "__file__", None)
            matching = [path for path in images if path.name == wanted.name]
            if origin:
                self.assertEqual(Path(origin).resolve(), wanted)
                self.assertEqual(matching, [wanted])
                self.assertEqual(sha(wanted), expected[str(wanted)])
                loaded[name] = {"path": str(wanted), "sha256": sha(wanted)}
            else:
                self.assertIn(name, ("FreeCAD", "FreeCADGui"))
                self.assertTrue(inspect.isbuiltin(App.Version if name == "FreeCAD" else module.updateGui))
                self.assertIn(matching, ([], [wanted]))
                loaded[name] = {"embedded_native_binding": True, "standalone_loaded": bool(matching)}

        from femtools import contact_state
        from femtools import force_accounting
        import ObjectsFem

        doc = App.newDocument("LiteralBundleDefaultSolverIdentity")
        try:
            solver = ObjectsFem.makeSolverCalculiXCcxTools(doc)
            self.assertEqual(solver.NativeAccountingSolver, "")
            candidate = Path(force_accounting.solver_binary(solver))
            self.assertEqual(candidate, resources / "data/NativeSolvers/ccx-force-accounting")
            self.assertEqual(sha(candidate), manifest["native_sha256"])
            capabilities = {}
            for option, wanted in (("--freecad-force-accounting-version", "CCX_FORCE_ACCOUNTING_V3"),
                                   ("--freecad-contact-state-version", "CCX_CONTACT_STATE_V1")):
                child = subprocess.run([str(candidate), option], cwd=manifest["working_directory"],
                                       stdin=subprocess.DEVNULL, capture_output=True, timeout=10,
                                       text=True, check=False)
                self.assertEqual(child.returncode, 0)
                self.assertEqual(child.stdout.strip(), wanted)
                capabilities[option] = child.stdout.strip()
        finally:
            App.closeDocument(doc.Name)
        RESULTS["identity"] = {
            "runtime": runtime, "home_path": App.getHomePath(), "native_origins": loaded,
            "process_executable": {"path": str(executable), "sha256": sha(executable)},
            "candidate": {"path": str(candidate), "sha256": sha(candidate),
                          "override": False, "capabilities": capabilities},
            "source_or_build_import_override": False, "initial_module_origins": source_origins(),
        }


class Backup8rkRegression(unittest.TestCase):
    def setUp(self):
        self.preferences = App.ParamGet("User parameter:BaseApp/Preferences/Document")
        self.preference_kinds = {
            "BackupPolicy": "Bool", "CreateBackupFiles": "Bool", "UseFCBakExtension": "Bool",
            "CheckExtension": "Bool", "CountBackupFiles": "Int", "SaveBackupDateFormat": "String",
        }
        self.saved = {}
        for name, kind in self.preference_kinds.items():
            first, second = {"Bool": (False, True), "Int": (-987654321, 987654321),
                             "String": ("missing-first", "missing-second")}[kind]
            getter = getattr(self.preferences, "Get" + kind)
            self.saved[name] = (getter(name, first) == getter(name, second), getter(name, first))

    def tearDown(self):
        for name, (present, value) in self.saved.items():
            kind = self.preference_kinds[name]
            if present:
                getattr(self.preferences, "Set" + kind)(name, value)
            else:
                getattr(self.preferences, "Rem" + kind)(name)

    def test_extensionless_timestamp_backup_stays_in_dotted_directory_and_reopens(self):
        witness = Path(MANIFEST["witness_path"])
        self.assertFalse(witness.exists() or witness.is_symlink())
        directory = witness / "dotted.parent"
        directory.mkdir(parents=True)
        target = directory / "target"
        backups = [directory / "target.fixed.FCBak", directory / "target.fixed-1.FCBak"]
        preferences = self.preferences
        for key, value in {"BackupPolicy": True, "CreateBackupFiles": True,
                           "UseFCBakExtension": True, "CheckExtension": False}.items():
            preferences.SetBool(key, value)
        preferences.SetInt("CountBackupFiles", 3)
        preferences.SetString("SaveBackupDateFormat", "fixed")
        hashes = []
        doc = App.newDocument("LiteralBundle8rkBackupWitness")
        try:
            state = doc.addObject("App::FeaturePython", "SavedState")
            state.addProperty("App::PropertyString", "Marker", "Regression")
            for index, marker in enumerate(("first", "second", "third")):
                state.Marker = marker
                doc.recompute()
                self.assertIsNone(doc.saveAs(str(target)) if index == 0 else doc.save())
                self.assertEqual(doc.FileName, str(target))
                hashes.append(sha(target))
                self.assertEqual(len(set(hashes)), len(hashes))
                for number in range(index):
                    self.assertEqual(sha(backups[number]), hashes[number])
        finally:
            App.closeDocument(doc.Name)
        layout = {"dotted.parent", "dotted.parent/target", "dotted.parent/target.fixed.FCBak",
                  "dotted.parent/target.fixed-1.FCBak"}
        self.assertEqual({str(path.relative_to(witness)) for path in witness.rglob("*")}, layout)
        self.assertTrue(all(not path.is_symlink() for path in witness.rglob("*")))
        before = {str(path): sha(path) for path in (target, *backups)}
        reopened = []
        for path, marker in ((target, "third"), (backups[0], "first"), (backups[1], "second")):
            doc = App.openDocument(str(path))
            try:
                self.assertEqual(doc.getObject("SavedState").Marker, marker)
                reopened.append({"path": str(path), "marker": marker})
            finally:
                App.closeDocument(doc.Name)
        self.assertEqual(before, {str(path): sha(path) for path in (target, *backups)})
        self.assertEqual({str(path.relative_to(witness)) for path in witness.rglob("*")}, layout)
        RESULTS["backup_regression"] = {
            "backups_contain_exact_previous_target_bytes": True,
            "no_escape_or_temporary_leftovers": True, "same_process_native_reopen": reopened,
            "file_sha256": before, "only_public_native_interfaces": True,
        }


class ColdContactRestore(unittest.TestCase):
    def test_cold_historical_raw_labels_cannot_be_promoted_onto_restored_mesh(self):
        case = MANIFEST["cold_case"]
        before = {row["path"]: sha(row["path"]) for row in case["source_files"]}
        self.assertEqual(before, {row["path"]: row["sha256"] for row in case["source_files"]})
        doc = App.openDocument(case["document"])
        try:
            result = doc.getObject(case["result_name"])
            self.assertEqual(result.ContactData, case["contact_data_literal"])
            self.assertEqual(result.ContactHash, case["contact_hash_literal"])
            self.assertTrue(result.Status.startswith("Historical"), result.Status)
            initial = result.Status
            self.assertEqual(result.Solver.NativeAccountingSolver, "")
            self.assertEqual([obj.Name for obj in result.Solver.NativeContactOutputs], case["contacts"])
            with self.assertRaises(ValueError):
                result.Proxy.getContactStates(result)
            result.Proxy.refresh(result)
            with self.assertRaises(ValueError):
                result.Proxy.getContactStates(result)
            self.assertTrue(result.Status.startswith("Unavailable"), result.Status)
            self.assertEqual(result.ContactData, case["contact_data_literal"])
            self.assertEqual(result.ContactHash, case["contact_hash_literal"])
            final = result.Status
        finally:
            App.closeDocument(doc.Name)
        after = {row["path"]: sha(row["path"]) for row in case["source_files"]}
        self.assertEqual(before, after)
        RESULTS["cold_restore"] = {
            "document": case["document"], "source_files_before": before,
            "source_files_after": after, "initial_status": initial, "refresh_status": final,
            "saved_contact_hash": case["contact_hash_literal"],
            "no_native_solve": True, "no_history_or_provenance_repair": True,
            "literal_original_raw_labels_preserved": True,
        }


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


class VerifiedSuite(unittest.TestSuite):
    def run(self, result, debug=False):
        actual = list(flatten(self))
        ids = [test.id() for test in actual]
        if len(ids) != MANIFEST["expected_tests"] or len(set(ids)) != len(ids):
            raise AssertionError("Wrong literal-application suite or repeated tests")
        super().run(result, debug=debug)
        if result.wasSuccessful() and not result.skipped and result.testsRun == len(ids):
            if MANIFEST_PATH.read_bytes() != MANIFEST_BYTES:
                raise AssertionError("Manifest changed during application execution")
            required = {"identity", "cold_restore"} if MANIFEST["mode"] == "cold" else {
                "identity", "backup_regression"}
            if set(RESULTS) != required:
                raise AssertionError("Required literal application witnesses are missing")
            report = {
                "schema": "FreeCAD-9ii-installation-regression-v1", "passed": True,
                "application": MANIFEST["application"], "location": MANIFEST["location"],
                "mode": MANIFEST["mode"], "gui": MANIFEST["gui"],
                "commit": MANIFEST["commit"], "revision": MANIFEST["revision"],
                "native_sha256": MANIFEST["native_sha256"], "test_count": len(ids),
                "selected_test_ids": ids, "manifest_sha256": hashlib.sha256(MANIFEST_BYTES).hexdigest(),
                "module_sha256": sha(__file__), "final_module_origins": source_origins(),
                "only_public_native_interfaces": True, "Oomakhi_opened_or_solved": False,
                "source_or_build_import_override": False, **RESULTS,
            }
            path = Path(MANIFEST["report_path"])
            with path.open("x") as stream:
                json.dump(report, stream, indent=2, sort_keys=True)
                stream.write("\n")
        return result


def load_tests(loader, _tests, _pattern):
    suite = VerifiedSuite([App9iiIdentity("test_exact_application_identity_and_loaded_native_origins")])
    mode = MANIFEST["mode"]
    if mode == "cold":
        suite.addTests(loader.loadTestsFromTestCase(ColdContactRestore))
    else:
        suite.addTests(loader.loadTestsFromTestCase(Backup8rkRegression))
        names = ("femtest.gui.test_contact_state", "TestFemGui") if mode == "gui" else (
            "femtest.app.test_contact_state_native", "femtest.app.test_contact_state_interfaces",
            "femtest.app.test_input_fingerprint", *REGRESSION_MODULES)
        suite.addTests(loader.loadTestsFromNames(names))
    return suite
