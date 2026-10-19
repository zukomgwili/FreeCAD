"""FreeCAD-3sc installed identity and trusted product-suite discovery checks."""

import ctypes
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest
from harness_config import (COMMIT, REVISION, FEM_TEST_COUNT, REGRESSION_COUNTS,
                            MATERIAL_APP_TEST_COUNT, MATERIAL_GUI_TEST_COUNT)

# Embedded FreeCAD does not honor PYTHONDONTWRITEBYTECODE consistently. Set it
# before production imports; this is test isolation, not an app preference.
sys.dont_write_bytecode = True

import FreeCAD as App
import Fem
import Materials
import ObjectsFem
import Part
import TestFemApp
import freecad
import freecad.utils
from femmesh import gmshtools, meshtools, meshsetsgetter, ownership_context
from femmesh import quality
from femsolver.calculix import write_constraint_contact, writer
from femtest.app import test_contact_ownership, test_elastic_connector, test_material_groups
from femtest.app import test_rigid_region_ownership
from femtest.app import test_force_accounting
from femtools import elastic_connector, material_orthotropic
from femtools import force_accounting
from femtools import native_properties


REPOSITORY = Path("/Users/zukomgwili/src/FreeCAD")
PINNED_COMMIT = COMMIT
PINNED_REVISION = REVISION
COCOA = REPOSITORY / ".pixi/envs/default/lib/qt6/plugins/platforms/libqcocoa.dylib"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def flatten(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from flatten(test)
        else:
            yield test


class InstalledIdentity(unittest.TestCase):
    def test_installed_identity(self):
        root = Path(os.environ["EXPECTED_RESOURCES"]).resolve()
        commit = os.environ["EXPECTED_COMMIT"]
        revision = os.environ["EXPECTED_REVISION"]
        report_path = Path(os.environ["IDENTITY_REPORT"])
        result = {"runtime": App.Version(), "root": str(root), "gui_up": App.GuiUp,
                  "expected_commit": commit, "expected_revision": revision,
                  "passed": False}
        try:
            self.assertEqual(commit, PINNED_COMMIT)
            self.assertEqual(revision, PINNED_REVISION)
            self.assertEqual(App.Version()[-1], commit)
            self.assertEqual(App.Version()[:3], ["27", "1", "0"])
            self.assertEqual(App.Version()[3], revision)
            self.assertEqual(Path(App.getHomePath()).resolve(), root)
            self.assertTrue(sys.dont_write_bytecode)
            modules = [Fem, Materials, Part, ObjectsFem, gmshtools, meshtools, meshsetsgetter,
                       ownership_context, test_material_groups,
                       elastic_connector, material_orthotropic, writer,
                       write_constraint_contact, TestFemApp, test_contact_ownership,
                       test_rigid_region_ownership, test_elastic_connector,
                       freecad, freecad.utils, force_accounting, test_force_accounting,
                       quality, native_properties]
            if App.GuiUp:
                import MatGui
                import ArchPipe
                import ArchSectionPlane
                from draftobjects import dimension
                from femtaskpanels import task_material_common
                modules += [MatGui, ArchPipe, ArchSectionPlane, dimension, task_material_common]
            self.assertEqual(Materials.Array2D().TypedArray, [])
            paths = {module.__name__: str(Path(module.__file__).resolve())
                     for module in modules}
            result["modules"] = paths
            result["module_sha256"] = {name: digest(path) for name, path in paths.items()}
            for path in paths.values():
                self.assertTrue(Path(path).is_relative_to(root), path)
            namespace_root = root / "Ext/freecad"
            result["application_namespace"] = {}
            for module, relative in ((freecad, "__init__.py"), (freecad.utils, "utils.py")):
                actual = Path(module.__file__).resolve()
                self.assertEqual(actual, (namespace_root / relative).resolve())
                if relative == "__init__.py":
                    source = REPOSITORY / "build/release/Ext/freecad/__init__.py"
                else:
                    source = REPOSITORY / "src/Ext/freecad" / relative
                self.assertEqual(digest(actual), digest(source), relative)
                result["application_namespace"][relative] = {
                    "origin": str(actual), "source": str(source), "sha256": digest(actual)}
                if relative == "__init__.py":
                    template = REPOSITORY / "src/Ext/freecad/__init__.py.template"
                    result["application_namespace"][relative].update({
                        "source_kind": "configured_build_output",
                        "template_origin": str(template), "template_sha256": digest(template)})
            python_preference = App.ParamGet("User parameter:BaseApp/Preferences/PythonConsole")
            self.assertEqual(python_preference.GetString("PathToPythonExecutable", ""), "")
            python_exe = freecad.utils.get_python_exe()
            expected_python = REPOSITORY / ".pixi/envs/default/bin/python3"
            self.assertTrue(Path(python_exe).is_file(), python_exe)
            self.assertTrue(os.access(python_exe, os.X_OK), python_exe)
            self.assertEqual(Path(python_exe).resolve(), expected_python.resolve())
            result["application_namespace"]["python_executable"] = {
                "reported": python_exe, "resolved": str(Path(python_exe).resolve()),
                "expected": str(expected_python), "sha256": digest(python_exe),
                "preference_overridden": False, "sys_prefix": sys.prefix}
            source_paths = {
                native_properties: "femtools/native_properties.py",
                quality: "femmesh/quality.py",
                force_accounting: "femtools/force_accounting.py",
                test_force_accounting: "femtest/app/test_force_accounting.py",
                ObjectsFem: "ObjectsFem.py",
                gmshtools: "femmesh/gmshtools.py",
                meshtools: "femmesh/meshtools.py",
                meshsetsgetter: "femmesh/meshsetsgetter.py",
                ownership_context: "femmesh/ownership_context.py",
                test_material_groups: "femtest/app/test_material_groups.py",
                elastic_connector: "femtools/elastic_connector.py",
                material_orthotropic: "femtools/material_orthotropic.py",
                writer: "femsolver/calculix/writer.py",
                write_constraint_contact: "femsolver/calculix/write_constraint_contact.py",
                TestFemApp: "TestFemApp.py",
                test_contact_ownership: "femtest/app/test_contact_ownership.py",
                test_rigid_region_ownership: "femtest/app/test_rigid_region_ownership.py",
                test_elastic_connector: "femtest/app/test_elastic_connector.py",
            }
            result["copied_source_sha256"] = {}
            for module, relative in source_paths.items():
                original = REPOSITORY / "src/Mod/Fem" / relative
                self.assertEqual(digest(module.__file__), digest(original), relative)
                result["copied_source_sha256"][relative] = digest(original)
            fem_suite = unittest.defaultTestLoader.loadTestsFromModule(TestFemApp)
            result["TestFemApp_count"] = fem_suite.countTestCases()
            self.assertEqual(result["TestFemApp_count"], FEM_TEST_COUNT)
            groups = {
                "contact": (test_contact_ownership.TestContactOwnership, REGRESSION_COUNTS["contact"]),
                "material_groups": (test_material_groups.TestMaterialGroups, REGRESSION_COUNTS["material_groups"]),
                "rigid_region_ownership":
                    (test_rigid_region_ownership.TestRigidRegionOwnership, REGRESSION_COUNTS["rigid_region_ownership"]),
                "rigid_port_connector": (test_elastic_connector.TestRigidPortConnector, REGRESSION_COUNTS["rigid_port_connector"]),
                "force_accounting": (test_force_accounting.TestForceAccounting, REGRESSION_COUNTS["force_accounting"]),
            }
            result["regressions_discovered"] = {}
            for name, (case, required_count) in groups.items():
                methods = unittest.defaultTestLoader.getTestCaseNames(case)
                self.assertEqual(len(methods), required_count, name)
                expected = [case(method).id() for method in methods]
                discovered = [test.id() for test in flatten(fem_suite) if type(test) is case]
                self.assertCountEqual(discovered, expected, name)
                self.assertEqual(len(discovered), required_count, name)
                self.assertFalse(getattr(case, "__unittest_skip__", False), name)
                result["regressions_discovered"][name] = discovered
            result["contact_regressions_discovered"] = result["regressions_discovered"]["contact"]
            self.assertTrue((root / "Mod/BIM/bimtests/fixtures/"
                             "area_projection_open_loop.brep").is_file())
            result["configured_suite_counts"] = {}
            result["configured_suite_origins"] = {}
            for name in json.loads(os.environ["CONFIGURED_TEST_SUITES"]):
                if name == "InstalledIdentity":
                    result["configured_suite_counts"][name] = 1
                    continue
                suite = unittest.defaultTestLoader.loadTestsFromName(name)
                self.assertGreater(suite.countTestCases(), 0, name)
                self.assertFalse(any(type(test).__name__ == "_FailedTest"
                                     for test in flatten(suite)), name)
                result["configured_suite_counts"][name] = suite.countTestCases()
                module = sys.modules[name.split(".", 1)[0]]
                module_path = Path(module.__file__).resolve()
                result["configured_suite_origins"][name] = str(module_path)
                # Scratch-only observers are intentional; product suites must
                # come from the application under test, never the source tree.
                if name not in json.loads(os.environ["SCRATCH_TEST_SUITES"]):
                    self.assertTrue(module_path.is_relative_to(root), str(module_path))
            result["configured_test_count"] = sum(result["configured_suite_counts"].values())
            for name, required in (("TestMaterialsApp", MATERIAL_APP_TEST_COUNT),
                                   ("TestMaterialsGui", MATERIAL_GUI_TEST_COUNT)):
                if name in result["configured_suite_counts"]:
                    self.assertEqual(result["configured_suite_counts"][name], required, name)
            dyld = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
            dyld._NSGetExecutablePath.argtypes = [ctypes.c_void_p,
                                                ctypes.POINTER(ctypes.c_uint32)]
            dyld._NSGetExecutablePath.restype = ctypes.c_int
            size = ctypes.c_uint32(4096)
            buffer = ctypes.create_string_buffer(size.value)
            self.assertEqual(dyld._NSGetExecutablePath(buffer, ctypes.byref(size)), 0)
            executable = Path(os.fsdecode(buffer.value)).resolve()
            result["process_executable"] = str(executable)
            # The preserved native MacOS wrapper execs the binary in Resources.
            expected_executable = root / "bin" / ("FreeCAD" if App.GuiUp else "FreeCADCmd")
            self.assertEqual(executable, expected_executable.resolve())
            dyld._dyld_image_count.restype = ctypes.c_uint32
            dyld._dyld_get_image_name.argtypes = [ctypes.c_uint32]
            dyld._dyld_get_image_name.restype = ctypes.c_char_p
            images = [os.fsdecode(dyld._dyld_get_image_name(index))
                      for index in range(dyld._dyld_image_count())]
            native_materials = [str(Path(path).resolve()) for path in images
                                if Path(path).name in ("Materials.so", "MatGui.so")]
            expected_materials = [str(Path(Materials.__file__).resolve())]
            if App.GuiUp:
                expected_materials.append(str(Path(MatGui.__file__).resolve()))
            self.assertCountEqual(native_materials, expected_materials)
            self.assertTrue(all(Path(path).is_relative_to(root) for path in native_materials))
            result["loaded_material_images"] = [
                {"path": path, "sha256": digest(path)} for path in native_materials]
            if App.GuiUp:
                cocoa = [str(Path(path).resolve()) for path in images
                         if Path(path).name == "libqcocoa.dylib"]
                self.assertEqual(cocoa, [str(COCOA.resolve())])
                result["cocoa_plugin"] = cocoa[0]
                result["cocoa_sha256"] = digest(cocoa[0])
            result["passed"] = True
        finally:
            with report_path.open("x") as handle:
                handle.write(json.dumps(result, indent=2) + "\n")
