"""Literal application identity plus shipped native beam regression suites."""

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
import tempfile
import unittest

import FreeCAD as App

REPO = Path("/Users/zukomgwili/src/FreeCAD")
APP = Path(os.environ["ISV7_APP"])
RESOURCES = APP / "Contents/Resources"
IDENTITY_PATH = Path(os.environ["ISV7_IDENTITY"])
IDENTITY_BYTES = IDENTITY_PATH.read_bytes()
IDENTITY = json.loads(IDENTITY_BYTES)
MODE = os.environ["ISV7_MODE"]
WORK = Path(os.environ["B960_WITNESS_ROOT"])
RESULTS = {}
NATIVE_SHA = "1f6281e8d779deeeb0f6a587d2cdcb5a7fc935e95f90b394cb28e761b22a603e"
COMMON = {
    "femobjects.solver_ccxtools": "femobjects/solver_ccxtools.py",
    "femtools.beam_coupling": "femtools/beam_coupling.py",
    "femtools.beam_solid_coupling": "femtools/beam_solid_coupling.py",
    "femtools.beam_solid_results": "femtools/beam_solid_results.py",
    "femtools.elastic_connector": "femtools/elastic_connector.py",
    "femobjects.constraint_elastic_connector": "femobjects/constraint_elastic_connector.py",
    "femtools.beam_section_forces": "femtools/beam_section_forces.py",
    "femtools.ccxtools": "femtools/ccxtools.py",
    "femtools.force_accounting": "femtools/force_accounting.py",
    "feminout.importCcxFrdResults": "feminout/importCcxFrdResults.py",
    "femsolver.calculix.write_step_output": "femsolver/calculix/write_step_output.py",
    "femsolver.calculix.writer": "femsolver/calculix/writer.py",
}
CMD_MODULES = (
    "femtest.app.test_beam_section_forces",
    "femtest.app.test_beam_section_forces_native",
    "femtest.app.test_beam_section_forces_lifecycle",
    "femtest.app.test_beam_section_forces_safety",
    "femtest.app.test_beam_coupling_native",
    "femtest.app.test_beam_solid_coupling_native",
)
GUI_MODULES = (
    "femtest.gui.test_beam_section_forces",
    "femtest.gui.test_beam_coupling",
    "femtest.gui.test_beam_solid_coupling",
)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_report(name, data):
    with (WORK / name).open("x") as stream:
        json.dump(data, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def source_origins():
    """Reject any source/build overlay, even for transitively loaded modules."""
    forbidden = (REPO / "src", REPO / "build")
    for entry in sys.path:
        actual = Path(entry or os.getcwd()).resolve()
        assert not any(actual.is_relative_to(root) for root in forbidden), actual
    rows = {}
    for name, module in tuple(sys.modules.items()):
        origin = getattr(module, "__file__", None)
        if not origin:
            continue
        actual = Path(origin).resolve()
        assert not any(actual.is_relative_to(root) for root in forbidden), (name, actual)
        if (
            name.startswith(
                (
                    "femtools",
                    "femmesh",
                    "femresult",
                    "femobjects",
                    "feminout",
                    "femsolver",
                    "femtest",
                    "femtaskpanels",
                    "femviewprovider",
                )
            )
            or name == "ObjectsFem"
        ):
            assert actual.is_relative_to(RESOURCES / "Mod/Fem"), (name, actual)
            relative = actual.relative_to(RESOURCES / "Mod/Fem")
            source = REPO / "src/Mod/Fem" / relative
            assert source.is_file() and source.read_bytes() == actual.read_bytes(), name
            rows[name] = {"path": str(actual), "sha256": sha(actual)}
    return rows


def check_identity(test):
    test.assertEqual(IDENTITY["schema"], "FreeCAD-sv7-install-identity-v1")
    test.assertEqual(IDENTITY["commit"], "2f6ed5df7bd9786449230ad01366a7d8e10ae0e2")
    test.assertEqual(IDENTITY["native_sha256"], NATIVE_SHA)
    test.assertEqual(IDENTITY_PATH.read_bytes(), IDENTITY_BYTES)
    test.assertTrue(APP.is_absolute())
    test.assertEqual(APP.resolve(strict=True), APP)
    test.assertFalse(APP.is_symlink())
    test.assertEqual(Path(App.getHomePath()).resolve(strict=True), RESOURCES)
    test.assertEqual(Path(App.ConfigGet("AppHomePath")).resolve(strict=True), RESOURCES)
    runtime = App.Version()
    test.assertEqual(runtime[:3], ["27", "1", "0"])
    test.assertEqual(runtime[3], IDENTITY["revision"])
    test.assertEqual(runtime[-1], IDENTITY["commit"])
    test.assertEqual(bool(App.GuiUp), MODE == "gui")
    test.assertNotIn("B960_TEST_SOLVER", os.environ)
    test.assertNotIn("SV7_TEST_SOLVER", os.environ)
    test.assertNotIn("FREECAD_CONTACT_STATE_SOLVER", os.environ)
    test.assertTrue(sys.dont_write_bytecode)
    for name, relative in COMMON.items():
        module = importlib.import_module(name)
        path = Path(module.__file__).resolve(strict=True)
        test.assertEqual(path, RESOURCES / "Mod/Fem" / relative)
        test.assertEqual(path.read_bytes(), (REPO / "src/Mod/Fem" / relative).read_bytes())
    if App.GuiUp:
        for name, relative in (
            ("femtaskpanels.task_solver_ccxtools", "femtaskpanels/task_solver_ccxtools.py"),
            (
                "femviewprovider.view_beam_section_forces",
                "femviewprovider/view_beam_section_forces.py",
            ),
        ):
            module = importlib.import_module(name)
            path = Path(module.__file__).resolve(strict=True)
            test.assertEqual(path, RESOURCES / "Mod/Fem" / relative)
            test.assertEqual(path.read_bytes(), (REPO / "src/Mod/Fem" / relative).read_bytes())

    modules = {"FreeCAD": App}
    modules.update({name: importlib.import_module(name) for name in ("Part", "Fem")})
    if App.GuiUp:
        modules.update({name: importlib.import_module(name) for name in ("FreeCADGui", "FemGui")})
    dyld = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
    dyld._NSGetExecutablePath.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    dyld._NSGetExecutablePath.restype = ctypes.c_int
    size = ctypes.c_uint32(4096)
    buffer = ctypes.create_string_buffer(size.value)
    test.assertEqual(dyld._NSGetExecutablePath(buffer, ctypes.byref(size)), 0)
    executable = Path(os.fsdecode(buffer.value)).resolve(strict=True)
    test.assertEqual(executable, RESOURCES / "bin" / ("FreeCAD" if App.GuiUp else "FreeCADCmd"))
    dyld._dyld_image_count.restype = ctypes.c_uint32
    dyld._dyld_get_image_name.argtypes = [ctypes.c_uint32]
    dyld._dyld_get_image_name.restype = ctypes.c_char_p
    images = [
        Path(os.fsdecode(dyld._dyld_get_image_name(index))).resolve()
        for index in range(dyld._dyld_image_count())
    ]
    native = {}
    libraries = ["libFreeCADBase.dylib", "libFreeCADApp.dylib"]
    if App.GuiUp:
        libraries.append("libFreeCADGui.dylib")
    for name in libraries:
        wanted = RESOURCES / "lib" / name
        test.assertEqual([path for path in images if path.name == name], [wanted])
        native[name] = {"path": str(wanted), "sha256": sha(wanted)}
    for name, module in modules.items():
        wanted = RESOURCES / "lib" / (name + ".so")
        origin = getattr(module, "__file__", None)
        matching = [path for path in images if path.name == wanted.name]
        if origin:
            test.assertEqual(Path(origin).resolve(strict=True), wanted)
            test.assertEqual(matching, [wanted])
            native[name] = {"path": str(wanted), "sha256": sha(wanted)}
        else:
            test.assertIn(name, ("FreeCAD", "FreeCADGui"))
            test.assertTrue(
                inspect.isbuiltin(App.Version if name == "FreeCAD" else module.updateGui)
            )
            test.assertIn(matching, ([], [wanted]))
            native[name] = {"embedded_native_binding": True, "standalone_loaded": bool(matching)}

    import ObjectsFem
    from femtools.force_accounting import solver_binary

    previous = App.activeDocument()
    previous_name = previous.Name if previous else None
    doc = App.newDocument("BeamSv7LiteralBundleIdentity")
    try:
        solver = ObjectsFem.makeSolverCalculiXCcxTools(doc)
        test.assertEqual(solver.NativeAccountingSolver, "")
        test.assertFalse(solver.BeamSectionForces)
        candidate = Path(solver_binary(solver))
        test.assertEqual(candidate, RESOURCES / "data/NativeSolvers/ccx-force-accounting")
        test.assertFalse(candidate.is_symlink())
        test.assertEqual(sha(candidate), NATIVE_SHA)
        capabilities = {}
        environment = {
            key: value for key, value in os.environ.items() if not key.startswith("CCX_")
        }
        with tempfile.TemporaryDirectory(
            prefix="beam-sv7-installed-capability-", dir=WORK
        ) as directory:
            for option, expected in (
                ("--freecad-force-accounting-version", "CCX_FORCE_ACCOUNTING_V3"),
                ("--freecad-contact-state-version", "CCX_CONTACT_STATE_V1"),
                ("--freecad-beam-section-version", "CCX_BEAM_SECTION_V1"),
                ("--freecad-beam-coupling-version", "CCX_BEAM_SECTION_V2"),
                ("--freecad-beam-solid-version", "CCX_BEAM_SECTION_V3"),
            ):
                child = subprocess.run(
                    [str(candidate), option],
                    cwd=directory,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    timeout=10,
                    text=True,
                    check=False,
                )
                test.assertEqual(child.returncode, 0, child.stderr)
                test.assertEqual(child.stdout.strip(), expected)
                capabilities[option] = child.stdout.strip()
        test.assertEqual(sha(candidate), NATIVE_SHA)
    finally:
        App.closeDocument(doc.Name)
        if previous_name in App.listDocuments():
            App.setActiveDocument(previous_name)
    observation = {
        "schema": "FreeCAD-sv7-literal-application-identity-v1",
        "application": str(APP),
        "runtime": runtime,
        "GuiUp": bool(App.GuiUp),
        "home_path": App.getHomePath(),
        "process_executable": {"path": str(executable), "sha256": sha(executable)},
        "native_origins": native,
        "python_origins": source_origins(),
        "candidate": {
            "path": str(candidate),
            "sha256": sha(candidate),
            "override": False,
            "capabilities": capabilities,
        },
        "source_or_build_import_override": False,
    }
    RESULTS["identity"] = observation
    write_report("identity-observation.json", observation)
    return observation


class AppBeamIdentity(unittest.TestCase):
    def test_exact_application_identity_native_origins_and_default_solver(self):
        check_identity(self)


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


class VerifiedSuite(unittest.TestSuite):
    def run(self, result, debug=False):
        ids = [test.id() for test in flatten(self)]
        expected = {"cmd": 31, "gui": 6}[MODE]
        assert len(ids) == len(set(ids)) == expected, ids
        super().run(result, debug=debug)
        origins = source_origins()
        passed = bool(
            result.wasSuccessful()
            and not result.skipped
            and result.testsRun == expected
            and "identity" in RESULTS
        )
        write_report(
            "regression.json",
            {
                "schema": "FreeCAD-sv7-installation-regression-v1",
                "passed": passed,
                "mode": MODE,
                "application": str(APP),
                "gui": bool(App.GuiUp),
                "commit": IDENTITY["commit"],
                "revision": IDENTITY["revision"],
                "native_sha256": NATIVE_SHA,
                "identity_sha256": sha(IDENTITY_PATH),
                "expected_tests": expected,
                "executed_tests": result.testsRun,
                "selected_test_ids": ids,
                "skipped": [test.id() for test, _reason in result.skipped],
                "failures": [test.id() for test, _traceback in result.failures],
                "errors": [test.id() for test, _traceback in result.errors],
                "source_or_build_import_override": False,
                "native_solver_override": False,
                "only_public_native_interfaces": True,
                "original_project_opened_changed_or_solved": False,
                "module_sha256": sha(__file__),
                "final_module_origins": origins,
                "identity": RESULTS.get("identity"),
            },
        )
        return result


def load_tests(loader, _tests, _pattern):
    assert MODE in ("cmd", "gui"), MODE
    suite = VerifiedSuite(
        [AppBeamIdentity("test_exact_application_identity_native_origins_and_default_solver")]
    )
    names = CMD_MODULES if MODE == "cmd" else GUI_MODULES
    for name in names:
        module = importlib.import_module(name)
        actual = Path(module.__file__).resolve(strict=True)
        relative = name.replace(".", "/") + ".py"
        assert actual == RESOURCES / "Mod/Fem" / relative, actual
        assert actual.read_bytes() == (REPO / "src/Mod/Fem" / relative).read_bytes()
        suite.addTests(loader.loadTestsFromModule(module))
    return suite
