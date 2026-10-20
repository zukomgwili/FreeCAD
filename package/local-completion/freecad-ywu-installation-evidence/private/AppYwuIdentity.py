"""macOS application-only identity and suite discovery for FreeCAD-ywu QA."""

import sys
sys.dont_write_bytecode = True

import ctypes
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import unittest

import FreeCAD as App
import Fem
import Materials
import Part


REPOSITORY = Path("/Users/zukomgwili/src/FreeCAD")
PINNED_COMMIT = "6cdc1affda07ac4e3b45a98097b7ae11039c80c6"
PINNED_REVISION = "49261 +221 (Git)"
PINNED_SOLVER = "2d59adb06736801f730de077a5f3dbfcfba8c0a430636e5814e5582606b5c89b"
SOURCES = {
    "ObjectsFem": "ObjectsFem.py",
    "TestFemApp": "TestFemApp.py",
    "femmesh.gmshtools": "femmesh/gmshtools.py",
    "femmesh.meshsetsgetter": "femmesh/meshsetsgetter.py",
    "femmesh.meshtools": "femmesh/meshtools.py",
    "femmesh.ownership_context": "femmesh/ownership_context.py",
    "femsolver.calculix.write_constraint_tie": "femsolver/calculix/write_constraint_tie.py",
    "femsolver.calculix.write_constraint_contact": "femsolver/calculix/write_constraint_contact.py",
    "femtools.ccxtools": "femtools/ccxtools.py",
    "femtools.force_accounting": "femtools/force_accounting.py",
    "femresult.contact_observation": "femresult/contact_observation.py",
    "femresult.contact_observation_source": "femresult/contact_observation_source.py",
    "femresult.owned_probe": "femresult/owned_probe.py",
    "femobjects.result_contact_observation": "femobjects/result_contact_observation.py",
    "femtest.app.test_tie_accounting_native": "femtest/app/test_tie_accounting_native.py",
    "femtest.app.test_force_accounting": "femtest/app/test_force_accounting.py",
    "femtest.app.test_contact_observation_native": "femtest/app/test_contact_observation_native.py",
    "femtest.app.test_movement_provenance": "femtest/app/test_movement_provenance.py",
    "femtest.app.test_tie_ownership": "femtest/app/test_tie_ownership.py",
    "femtest.app.test_moving_port_accounting_native": "femtest/app/test_moving_port_accounting_native.py",
    "femobjects.solver_ccxtools": "femobjects/solver_ccxtools.py",
    "femsolver.calculix.write_constraint_elastic_connector": "femsolver/calculix/write_constraint_elastic_connector.py",
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def flatten(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from flatten(test)
        else:
            yield test


class AppNativeIdentity(unittest.TestCase):
    def test_application_only_native_identity_and_registered_suites(self):
        application = Path(os.environ["APPQA_APPLICATION"]).resolve()
        resources = application / "Contents/Resources"
        gui = os.environ["APPQA_MODE"] == "gui"
        report = {"passed": False, "runtime": App.Version(), "gui_up": bool(App.GuiUp),
                  "application": str(application), "resources": str(resources),
                  "source_or_build_import_override": False}
        temporary = None
        try:
            self.assertEqual(bool(App.GuiUp), gui)
            self.assertTrue(sys.dont_write_bytecode)
            self.assertEqual(App.Version()[:3], ["27", "1", "0"])
            self.assertEqual(App.Version()[3], PINNED_REVISION)
            self.assertEqual(App.Version()[-1], PINNED_COMMIT)
            self.assertEqual(Path(App.getHomePath()).resolve(), resources.resolve())
            header = REPOSITORY / "build/release/src/Build/Version.h"
            macros = dict(re.findall(r'^#define\s+(FC\w+)\s+"([^"\n]*)"',
                                     header.read_text(), re.M))
            self.assertEqual(macros["FCRepositoryHash"], PINNED_COMMIT)
            self.assertEqual(macros["FCRevision"], PINNED_REVISION)
            report["version_header"] = {"path": str(header), "sha256": digest(header)}
            for value in sys.path:
                if not value:
                    continue
                resolved = Path(value).resolve()
                self.assertFalse(resolved.is_relative_to(REPOSITORY / "src"), str(resolved))
                self.assertFalse(resolved.is_relative_to(REPOSITORY / "build"), str(resolved))

            sources = dict(SOURCES)
            if gui:
                sources.update({
                    "TestFemGui": "TestFemGui.py",
                    "femcommands.commands": "femcommands/commands.py",
                    "femviewprovider.view_contact_observation":
                        "femviewprovider/view_contact_observation.py",
                    "femtest.gui.test_contact_observation":
                        "femtest/gui/test_contact_observation.py",
                })
            report["copied_modules"] = {}
            for name, relative in sources.items():
                actual = Path(importlib.import_module(name).__file__).resolve()
                copied = resources / "Mod/Fem" / relative
                original = REPOSITORY / "src/Mod/Fem" / relative
                self.assertTrue(actual.is_relative_to(resources), str(actual))
                self.assertEqual(actual, copied.resolve(), name)
                self.assertEqual(digest(actual), digest(original), name)
                report["copied_modules"][name] = {
                    "origin": str(actual), "source": str(original), "sha256": digest(actual)}

            app_suite = unittest.defaultTestLoader.loadTestsFromName("TestFemApp")
            self.assertEqual(app_suite.countTestCases(), 395)
            case = importlib.import_module(
                "femtest.app.test_tie_accounting_native").TestTieAccountingNative
            expected = [case(method).id() for method in
                        unittest.defaultTestLoader.getTestCaseNames(case)]
            self.assertEqual(len(expected), 4)
            self.assertFalse(getattr(case, "__unittest_skip__", False))
            registered = [test.id() for test in flatten(app_suite) if type(test) is case]
            self.assertCountEqual(registered, expected)
            cmake = REPOSITORY / "src/Mod/Fem/CMakeLists.txt"
            self.assertIn("femtest/app/test_tie_accounting_native.py", cmake.read_text())
            report["registered_native_tie_ids"] = registered
            moving_case = importlib.import_module(
                "femtest.app.test_moving_port_accounting_native").TestMovingPortAccountingNative
            moving_expected = [moving_case(method).id() for method in
                               unittest.defaultTestLoader.getTestCaseNames(moving_case)]
            self.assertEqual(len(moving_expected), 5)
            self.assertFalse(getattr(moving_case, "__unittest_skip__", False))
            moving_registered = [test.id() for test in flatten(app_suite) if type(test) is moving_case]
            self.assertCountEqual(moving_registered, moving_expected)
            self.assertIn("femtest/app/test_moving_port_accounting_native.py", cmake.read_text())
            report["registered_native_ids"] = registered + moving_registered
            report["TestFemApp_count"] = app_suite.countTestCases()
            if gui:
                gui_suite = unittest.defaultTestLoader.loadTestsFromName("TestFemGui")
                self.assertEqual(gui_suite.countTestCases(), 8)
                report["TestFemGui_count"] = gui_suite.countTestCases()

            report["configured_suites"] = {}
            all_ids = []
            for name in json.loads(os.environ["APPQA_SUITES"]):
                suite = unittest.defaultTestLoader.loadTestsFromName(name)
                tests = list(flatten(suite))
                self.assertTrue(tests, name)
                self.assertFalse(any(type(test).__name__ == "_FailedTest" for test in tests), name)
                origins = {}
                for test in tests:
                    module = importlib.import_module(type(test).__module__)
                    actual = Path(module.__file__).resolve()
                    custom = name in ("YwuEndLoadGreen", "YwuOrdinaryGreen", "YwuColdRestore")
                    if custom:
                        self.assertEqual(actual, Path(__file__).resolve().parent / (name + ".py"))
                    else:
                        self.assertTrue(actual.is_relative_to(resources), str(actual))
                    origins[module.__name__] = {"origin": str(actual), "sha256": digest(actual)}
                ids = [test.id() for test in tests]
                all_ids.extend(ids)
                report["configured_suites"][name] = {
                    "count": suite.countTestCases(), "ids": ids, "origins": origins}
            self.assertEqual(len(all_ids), len(set(all_ids)), "Configured suites overlap")
            report["expected_total_count"] = len(all_ids) + 1
            self.assertEqual(len(report["configured_suites"]), 1)
            chosen_name, chosen_suite = next(iter(report["configured_suites"].items()))
            report["selected_suite"] = dict(name=chosen_name, **chosen_suite)
            report["loaded_fem_python"] = {}
            for name, module in list(sys.modules.items()):
                filename = getattr(module, "__file__", None)
                if not filename or not name.startswith("fem"):
                    continue
                actual = Path(filename).resolve()
                self.assertTrue(actual.is_relative_to(resources / "Mod/Fem"), str(actual))
                relative = actual.relative_to(resources / "Mod/Fem")
                original = REPOSITORY / "src/Mod/Fem" / relative
                self.assertTrue(original.is_file(), str(original))
                self.assertEqual(digest(actual), digest(original), name)
                report["loaded_fem_python"][name] = {
                    "origin": str(actual), "source": str(original), "sha256": digest(actual)}

            from femtools import force_accounting
            import ObjectsFem
            temporary = App.newDocument("AppNativeAccountingIdentity")
            solver = ObjectsFem.makeSolverCalculiXCcxTools(temporary)
            self.assertEqual(solver.NativeAccountingSolver, "")
            self.assertEqual(solver.NativeAccountingSupports, [])
            binary = Path(force_accounting.solver_binary(solver)).resolve()
            self.assertEqual(binary,
                             (resources / "data/NativeSolvers/ccx-force-accounting").resolve())
            self.assertTrue(binary.is_relative_to(resources))
            self.assertEqual(digest(binary), PINNED_SOLVER)
            self.assertEqual(force_accounting.SCHEMA, "CCX_FORCE_ACCOUNTING_V3")
            force_accounting.require_capability(binary)
            report["bundled_solver"] = {"path": str(binary), "sha256": digest(binary),
                                         "capability": force_accounting.SCHEMA,
                                         "preference_or_candidate_override": False}
            report["candidate"] = {"path": str(binary), "sha256": digest(binary),
                                   "capability": force_accounting.SCHEMA, "override": False}

            dyld = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
            dyld._NSGetExecutablePath.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
            dyld._NSGetExecutablePath.restype = ctypes.c_int
            size = ctypes.c_uint32(4096)
            buffer = ctypes.create_string_buffer(size.value)
            self.assertEqual(dyld._NSGetExecutablePath(buffer, ctypes.byref(size)), 0)
            executable = Path(os.fsdecode(buffer.value)).resolve()
            self.assertEqual(executable, (resources / "bin" / (
                "FreeCAD" if gui else "FreeCADCmd")).resolve())
            report["process_executable"] = {"path": str(executable), "sha256": digest(executable)}
            native = {"Fem": Fem, "Part": Part, "Materials": Materials}
            if gui:
                native["FemGui"] = importlib.import_module("FemGui")
            dyld._dyld_image_count.restype = ctypes.c_uint32
            dyld._dyld_get_image_name.argtypes = [ctypes.c_uint32]
            dyld._dyld_get_image_name.restype = ctypes.c_char_p
            images = [Path(os.fsdecode(dyld._dyld_get_image_name(index))).resolve()
                      for index in range(dyld._dyld_image_count())]
            report["native_modules"] = {}
            for name, module in native.items():
                actual = Path(module.__file__).resolve()
                self.assertTrue(actual.is_relative_to(resources / "lib"), str(actual))
                self.assertEqual(actual, (resources / "lib" / (name + ".so")).resolve())
                same_name = [path for path in images if path.name == name + ".so"]
                self.assertEqual(same_name, [actual], name)
                report["native_modules"][name] = {"path": str(actual), "sha256": digest(actual)}
            app_library = (resources / "lib/libFreeCADApp.dylib").resolve()
            self.assertTrue(app_library.is_relative_to(resources / "lib"))
            self.assertEqual([path for path in images if path.name == app_library.name],
                             [app_library])
            report["app_library"] = {"path": str(app_library), "sha256": digest(app_library)}
            self.assertEqual(Materials.Array2D().TypedArray, [])
            report["passed"] = True
        except BaseException as error:
            report["error"] = repr(error)
            raise
        finally:
            if temporary is not None:
                App.closeDocument(temporary.Name)
            with Path(os.environ["APPQA_REPORT"]).open("x") as handle:
                handle.write(json.dumps(report, indent=2) + "\n")
