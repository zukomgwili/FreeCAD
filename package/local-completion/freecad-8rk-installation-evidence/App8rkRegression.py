"""Two literal-application checks for the private FreeCAD-8rk installation gate.

The caller supplies a frozen manifest and isolated configuration. This module
does not alter the installation, source, dependencies, or an existing document.
The normal FreeCAD unittest launcher owns process completion.
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
import re
import unittest

import FreeCAD as App


REPOSITORY = Path("/Users/zukomgwili/src/FreeCAD")
PREFERENCES = "User parameter:BaseApp/Preferences/Document"


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class App8rkRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest_path = Path(os.environ["F8_INSTALL_MANIFEST"])
        if not cls.manifest_path.is_absolute():
            raise AssertionError("Manifest path must be absolute")
        cls.manifest_sha256 = sha256(cls.manifest_path)
        cls.manifest = json.loads(cls.manifest_path.read_text())
        cls.results = {}
        application = Path(cls.manifest["application"])
        if not application.is_absolute() or application.resolve() != application:
            raise AssertionError("Application must be a literal, canonical absolute path")
        if application.is_symlink() or not application.is_dir():
            raise AssertionError("Application must be a real directory")
        if re.fullmatch(r"[0-9a-f]{40}", cls.manifest["commit"]) is None:
            raise AssertionError("Manifest commit must be a complete commit hash")
        if type(cls.manifest["gui"]) is not bool:
            raise AssertionError("Manifest gui must be a boolean")
        if not isinstance(cls.manifest["revision"], str):
            raise AssertionError("Manifest revision must be a string")
        for key in ("report_path", "witness_path"):
            path = Path(cls.manifest[key])
            if not path.is_absolute() or path.resolve() != path:
                raise AssertionError(key + " must be a canonical absolute path")
            if path.exists() or path.is_symlink() or not path.parent.is_dir():
                raise AssertionError(key + " must be new, with an existing parent")
            if path.is_relative_to(application) or path.is_relative_to(REPOSITORY):
                raise AssertionError(key + " must remain in the private task area")
        if Path(cls.manifest["report_path"]).is_relative_to(Path(cls.manifest["witness_path"])):
            raise AssertionError("Report must be outside the document witness")

    @classmethod
    def tearDownClass(cls):
        if set(cls.results) != {"identity", "backup_regression"}:
            return
        if sha256(cls.manifest_path) != cls.manifest_sha256:
            raise AssertionError("Frozen manifest changed")
        report = {
            "schema": "FreeCAD-8rk-installation-regression-v1",
            "passed": True,
            "test_count": 2,
            "application": cls.manifest["application"],
            "commit": cls.manifest["commit"],
            "revision": cls.manifest["revision"],
            "gui": cls.manifest["gui"],
            "manifest_path": str(cls.manifest_path),
            "manifest_sha256": cls.manifest_sha256,
            "module_path": str(Path(__file__).resolve()),
            "module_sha256": sha256(__file__),
            **cls.results,
        }
        with Path(cls.manifest["report_path"]).open("x") as stream:
            stream.write(json.dumps(report, indent=2, sort_keys=True) + "\n")

    def test_exact_application_identity_and_loaded_native_origins(self):
        manifest = self.manifest
        application = Path(manifest["application"])
        resources = application / "Contents/Resources"
        gui = manifest["gui"]
        runtime = App.Version()
        self.assertEqual(runtime[:3], ["27", "1", "0"])
        self.assertEqual(runtime[3], manifest["revision"])
        self.assertEqual(runtime[-1], manifest["commit"])
        self.assertEqual(bool(App.GuiUp), gui)
        self.assertTrue(sys.dont_write_bytecode)
        self.assertEqual(Path(App.getHomePath()).resolve(), resources)

        for entry in sys.path:
            actual = Path(entry or os.getcwd()).resolve()
            for forbidden in (REPOSITORY / "src", REPOSITORY / "build"):
                self.assertFalse(actual.is_relative_to(forbidden), str(actual))
        for name, module in list(sys.modules.items()):
            origin = getattr(module, "__file__", None)
            if not origin:
                continue
            actual = Path(origin).resolve()
            for forbidden in (REPOSITORY / "src", REPOSITORY / "build"):
                self.assertFalse(actual.is_relative_to(forbidden), name + ": " + str(actual))

        expected = manifest["expected_native_files"]
        self.assertIsInstance(expected, dict)
        for filename, wanted in expected.items():
            path = Path(filename)
            self.assertTrue(path.is_absolute() and path.is_relative_to(resources), filename)
            self.assertEqual(path.resolve(), path, filename)
            self.assertTrue(path.is_file() and not path.is_symlink(), filename)
            self.assertRegex(wanted, r"^[0-9a-f]{64}$")
            self.assertEqual(sha256(path), wanted, filename)

        dyld = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        dyld._NSGetExecutablePath.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        dyld._NSGetExecutablePath.restype = ctypes.c_int
        size = ctypes.c_uint32(4096)
        buffer = ctypes.create_string_buffer(size.value)
        self.assertEqual(dyld._NSGetExecutablePath(buffer, ctypes.byref(size)), 0)
        executable = Path(os.fsdecode(buffer.value)).resolve()
        self.assertEqual(executable, resources / "bin" / ("FreeCAD" if gui else "FreeCADCmd"))
        self.assertIn(str(executable), expected)
        self.assertEqual(sha256(executable), expected[str(executable)])

        dyld._dyld_image_count.restype = ctypes.c_uint32
        dyld._dyld_get_image_name.argtypes = [ctypes.c_uint32]
        dyld._dyld_get_image_name.restype = ctypes.c_char_p
        images = [
            Path(os.fsdecode(dyld._dyld_get_image_name(index))).resolve()
            for index in range(dyld._dyld_image_count())
        ]
        libraries = ["libFreeCADBase.dylib", "libFreeCADApp.dylib"]
        modules = {"FreeCAD": App}
        if gui:
            libraries.append("libFreeCADGui.dylib")
            modules["FreeCADGui"] = importlib.import_module("FreeCADGui")
        native_origins = {}
        for basename in libraries:
            wanted = resources / "lib" / basename
            self.assertIn(str(wanted), expected)
            self.assertEqual([path for path in images if path.name == basename], [wanted])
            self.assertEqual(sha256(wanted), expected[str(wanted)])
            native_origins[basename] = {"path": str(wanted), "sha256": sha256(wanted)}
        for name, module in modules.items():
            wanted = resources / "lib" / (name + ".so")
            origin = getattr(module, "__file__", None)
            loaded_bindings = [path for path in images if path.name == wanted.name]
            if origin:
                actual = Path(origin).resolve()
                self.assertEqual(actual, wanted)
                self.assertIn(str(wanted), expected)
                self.assertEqual(loaded_bindings, [wanted])
                self.assertEqual(sha256(wanted), expected[str(wanted)])
                native_origins[name] = {
                    "binding_kind": "standalone native module",
                    "path": str(actual),
                    "sha256": sha256(actual),
                }
            else:
                # The literal executables register these bindings in their
                # Python inittab; a separate FreeCAD.so need not be imported.
                function = App.Version if name == "FreeCAD" else module.updateGui
                self.assertTrue(inspect.isbuiltin(function), name)
                self.assertIn(loaded_bindings, ([], [wanted]))
                if loaded_bindings:
                    self.assertIn(str(wanted), expected)
                    self.assertEqual(sha256(wanted), expected[str(wanted)])
                native_origins[name] = {
                    "binding_kind": "embedded native binding",
                    "builtin_function": name + (".Version" if name == "FreeCAD" else ".updateGui"),
                    "inspect_isbuiltin": True,
                    "standalone_module_loaded": bool(loaded_bindings),
                }
        self.results["identity"] = {
            "runtime": runtime,
            "home_path": App.getHomePath(),
            "gui_up": bool(App.GuiUp),
            "process_executable": {"path": str(executable), "sha256": sha256(executable)},
            "native_origins": native_origins,
            "expected_native_files": expected,
            "source_or_build_import_override": False,
        }

    def test_extensionless_timestamp_backup_and_same_process_native_reopen(self):
        witness = Path(self.manifest["witness_path"])
        self.assertFalse(witness.exists() or witness.is_symlink())
        witness.mkdir()
        directory = witness / "dotted.parent"
        directory.mkdir()
        target = directory / "target"
        backup_one = directory / "target.fixed.FCBak"
        backup_two = directory / "target.fixed-1.FCBak"
        preferences = App.ParamGet(PREFERENCES)
        for name, value in {
            "BackupPolicy": True,
            "CreateBackupFiles": True,
            "UseFCBakExtension": True,
            "CheckExtension": False,
        }.items():
            preferences.SetBool(name, value)
            self.assertEqual(preferences.GetBool(name), value)
        preferences.SetInt("CountBackupFiles", 3)
        preferences.SetString("SaveBackupDateFormat", "fixed")
        self.assertEqual(preferences.GetInt("CountBackupFiles"), 3)
        self.assertEqual(preferences.GetString("SaveBackupDateFormat"), "fixed")

        document = None
        try:
            document = App.newDocument("FreeCAD8rkBackupWitness")
            state = document.addObject("App::FeaturePython", "SavedState")
            state.addProperty("App::PropertyString", "Marker", "Regression")
            state.Marker = "first"
            document.recompute()
            self.assertIsNone(document.saveAs(str(target)))
            self.assertEqual(document.FileName, str(target))
            self.assertTrue(target.is_file() and not target.is_symlink())
            first_hash = sha256(target)
            self.assertEqual({path.name for path in directory.iterdir()}, {"target"})

            state.Marker = "second"
            document.recompute()
            self.assertIsNone(document.save())
            self.assertEqual(document.FileName, str(target))
            self.assertTrue(backup_one.is_file() and not backup_one.is_symlink())
            self.assertEqual(sha256(backup_one), first_hash)
            second_hash = sha256(target)
            self.assertNotEqual(second_hash, first_hash)

            state.Marker = "third"
            document.recompute()
            self.assertIsNone(document.save())
            self.assertTrue(backup_two.is_file() and not backup_two.is_symlink())
            self.assertEqual(sha256(backup_one), first_hash)
            self.assertEqual(sha256(backup_two), second_hash)
            third_hash = sha256(target)
            self.assertNotIn(third_hash, (first_hash, second_hash))
        finally:
            if document is not None:
                App.closeDocument(document.Name)

        expected_layout = {
            "dotted.parent",
            "dotted.parent/target",
            "dotted.parent/target.fixed.FCBak",
            "dotted.parent/target.fixed-1.FCBak",
        }
        self.assertEqual({str(path.relative_to(witness)) for path in witness.rglob("*")},
                         expected_layout)
        self.assertTrue(all(not path.is_symlink() for path in witness.rglob("*")))
        before_open = {str(path): sha256(path) for path in (target, backup_one, backup_two)}
        restored = []
        for path, value in ((target, "third"), (backup_one, "first"), (backup_two, "second")):
            reopened = None
            try:
                reopened = App.openDocument(str(path))
                self.assertEqual(reopened.FileName, str(path))
                self.assertIsNotNone(reopened.getObject("SavedState"))
                self.assertEqual(reopened.getObject("SavedState").Marker, value)
                restored.append({"path": str(path), "marker": value, "sha256": sha256(path)})
            finally:
                if reopened is not None:
                    App.closeDocument(reopened.Name)
        self.assertEqual({str(path): sha256(path) for path in (target, backup_one, backup_two)},
                         before_open)
        self.assertEqual({str(path.relative_to(witness)) for path in witness.rglob("*")},
                         expected_layout)
        self.results["backup_regression"] = {
            "witness_path": str(witness),
            "target": str(target),
            "backup_paths": [str(backup_one), str(backup_two)],
            "first_saved_sha256": first_hash,
            "second_saved_sha256": second_hash,
            "third_saved_sha256": third_hash,
            "final_file_sha256": before_open,
            "same_process_native_reopen": restored,
            "exact_relative_layout": sorted(expected_layout),
            "extensionless_target_preserved": True,
            "backups_contain_exact_previous_target_bytes": True,
            "no_escape_or_temporary_leftovers": True,
            "native_reopen_preserved_all_input_bytes": True,
            "separate_cold_process_launched": False,
            "only_public_native_interfaces": True,
        }


def load_tests(loader, _tests, _pattern):
    return loader.loadTestsFromTestCase(App8rkRegression)
