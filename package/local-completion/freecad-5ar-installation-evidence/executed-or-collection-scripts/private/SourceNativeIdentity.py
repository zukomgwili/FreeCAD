"""Private build-tree identity observer for FreeCAD-ro1 source qualification."""

import sys
sys.dont_write_bytecode = True

import ctypes
import importlib
import hashlib
import json
import os
from pathlib import Path
import re
import unittest

import FreeCAD as App
import Fem

REPOSITORY = Path("/Users/zukomgwili/src/FreeCAD")
BUILD = REPOSITORY / "build/release"
# These are copied build inputs, not a source-path override.
SOURCES = {
    "femtools.force_accounting": "femtools/force_accounting.py",
    "femresult.contact_observation": "femresult/contact_observation.py",
    "femresult.contact_observation_source": "femresult/contact_observation_source.py",
    "femobjects.result_contact_observation": "femobjects/result_contact_observation.py",
    "femtest.app.test_tie_accounting_native": "femtest/app/test_tie_accounting_native.py",
    "ObjectsFem": "ObjectsFem.py",
    "TestFemApp": "TestFemApp.py",
    "femmesh.meshsetsgetter": "femmesh/meshsetsgetter.py",
    "femmesh.meshtools": "femmesh/meshtools.py",
    "femmesh.ownership_context": "femmesh/ownership_context.py",
    "femsolver.calculix.write_constraint_tie": "femsolver/calculix/write_constraint_tie.py",
    "femsolver.calculix.write_constraint_contact": "femsolver/calculix/write_constraint_contact.py",
    "femtools.ccxtools": "femtools/ccxtools.py",
    "femtools.femutils": "femtools/femutils.py",
    "femtools.membertools": "femtools/membertools.py",
    "femtest.app.test_tie_ownership": "femtest/app/test_tie_ownership.py",
    "femtest.app.test_contact_ownership": "femtest/app/test_contact_ownership.py",
    "femtest.app.test_rigid_region_ownership": "femtest/app/test_rigid_region_ownership.py",
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def flatten(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from flatten(test)
        else:
            yield test


class SourceNativeIdentity(unittest.TestCase):
    def test_built_native_and_copied_source_identity(self):
        report = {"passed": False, "runtime": App.Version(), "gui_up": bool(App.GuiUp),
                  "home": App.getHomePath(), "source_override": False}
        try:
            self.assertEqual(bool(App.GuiUp), os.environ["RO1_TEST_MODE"] == "gui")
            self.assertEqual(Path(App.getHomePath()).resolve(), BUILD.resolve())
            self.assertTrue(sys.dont_write_bytecode)
            header = (BUILD / "src/Build/Version.h").read_text()
            for macro, actual in (("FCRevision", App.Version()[3]),
                                  ("FCRepositoryHash", App.Version()[-1])):
                match = re.search(r'^#define\s+' + macro + r'\s+"([^"]+)"', header, re.M)
                self.assertIsNotNone(match, macro)
                self.assertEqual(actual, match.group(1), macro)
            sources = dict(SOURCES)
            if App.GuiUp:
                sources["TestFemGui"] = "TestFemGui.py"
                sources["femcommands.commands"] = "femcommands/commands.py"
            report["copied_modules"] = {}
            for name, relative in sources.items():
                module = importlib.import_module(name)
                actual = Path(module.__file__).resolve()
                original = REPOSITORY / "src/Mod/Fem" / relative
                copied = BUILD / "Mod/Fem" / relative
                self.assertEqual(actual, copied.resolve(), name)
                self.assertEqual(digest(original), digest(actual), name)
                report["copied_modules"][name] = {
                    "origin": str(actual), "source": str(original), "sha256": digest(actual)}

            tie = importlib.import_module("femtest.app.test_tie_ownership").TestTieOwnership
            expected_tie = [tie(method).id() for method in
                            unittest.defaultTestLoader.getTestCaseNames(tie)]
            self.assertTrue(expected_tie)
            self.assertFalse(getattr(tie, "__unittest_skip__", False))
            registered = unittest.defaultTestLoader.loadTestsFromModule(
                importlib.import_module("TestFemApp"))
            actual_tie = [test.id() for test in flatten(registered) if type(test) is tie]
            self.assertCountEqual(actual_tie, expected_tie)
            cmake = REPOSITORY / "src/Mod/Fem/CMakeLists.txt"
            self.assertIn("femtest/app/test_tie_ownership.py", cmake.read_text())
            report["cmake_registration"] = {"path": str(cmake), "sha256": digest(cmake)}
            report["registered_tie_ids"] = actual_tie
            report["TestFemApp_count"] = registered.countTestCases()

            native_tie = importlib.import_module(
                "femtest.app.test_tie_accounting_native").TestTieAccountingNative
            expected_native = [native_tie(method).id() for method in
                               unittest.defaultTestLoader.getTestCaseNames(native_tie)]
            self.assertEqual(len(expected_native), 4)
            self.assertFalse(getattr(native_tie, "__unittest_skip__", False))
            actual_native = [test.id() for test in flatten(registered)
                             if type(test) is native_tie]
            self.assertCountEqual(actual_native, expected_native)
            self.assertIn("femtest/app/test_tie_accounting_native.py", cmake.read_text())
            report["registered_native_tie_ids"] = actual_native

            report["configured_suites"] = {}
            for name in json.loads(os.environ["RO1_TEST_SUITES"]):
                suite = unittest.defaultTestLoader.loadTestsFromName(name)
                tests = list(flatten(suite))
                self.assertTrue(tests, name)
                self.assertFalse(any(type(test).__name__ == "_FailedTest" for test in tests), name)
                origins = {}
                for test in tests:
                    module = importlib.import_module(type(test).__module__)
                    actual = Path(module.__file__).resolve()
                    self.assertTrue(actual.is_relative_to(BUILD), str(actual))
                    origins[module.__name__] = {"origin": str(actual), "sha256": digest(actual)}
                report["configured_suites"][name] = {
                    "count": suite.countTestCases(), "ids": [test.id() for test in tests],
                    "origins": origins}
            report["expected_total_count"] = 1 + sum(
                suite["count"] for suite in report["configured_suites"].values())

            dyld = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
            dyld._NSGetExecutablePath.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
            dyld._NSGetExecutablePath.restype = ctypes.c_int
            size = ctypes.c_uint32(4096)
            buffer = ctypes.create_string_buffer(size.value)
            self.assertEqual(dyld._NSGetExecutablePath(buffer, ctypes.byref(size)), 0)
            executable = Path(os.fsdecode(buffer.value)).resolve()
            self.assertEqual(executable, (BUILD / "bin" / (
                "FreeCAD" if App.GuiUp else "FreeCADCmd")).resolve())
            report["process_executable"] = {"path": str(executable), "sha256": digest(executable)}
            expected_native = [BUILD / "Mod/Fem/Fem.so"]
            self.assertEqual(Path(Fem.__file__).resolve(), expected_native[0].resolve())
            if App.GuiUp:
                import FemGui
                expected_native.append(BUILD / "Mod/Fem/FemGui.so")
                self.assertEqual(Path(FemGui.__file__).resolve(), expected_native[1].resolve())
            dyld._dyld_image_count.restype = ctypes.c_uint32
            dyld._dyld_get_image_name.argtypes = [ctypes.c_uint32]
            dyld._dyld_get_image_name.restype = ctypes.c_char_p
            images = [Path(os.fsdecode(dyld._dyld_get_image_name(index))).resolve()
                      for index in range(dyld._dyld_image_count())]
            fem_images = [path for path in images if path.name in ("Fem.so", "FemGui.so")]
            self.assertCountEqual(fem_images, [path.resolve() for path in expected_native])
            report["loaded_fem_images"] = [{"path": str(path), "sha256": digest(path)}
                                           for path in fem_images]
            report["passed"] = True
        except BaseException as error:
            report["error"] = repr(error)
            raise
        finally:
            with Path(os.environ["RO1_IDENTITY_REPORT"]).open("x") as handle:
                handle.write(json.dumps(report, indent=2) + "\n")
