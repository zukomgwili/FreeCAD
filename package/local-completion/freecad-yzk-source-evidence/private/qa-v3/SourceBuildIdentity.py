"""Source-build identity; discovery is not feature execution or qualification."""
import sys
sys.dont_write_bytecode = True
import ctypes
import importlib
import json
import os
from pathlib import Path
import unittest

import FreeCAD as App
import Fem

QA = Path(__file__).resolve().parent
TASK = QA.parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
BUILD = REPO / 'build/release'
sys.path.insert(0, str(TASK))
sys.path.insert(0, str(QA))
from YzkBuildSupport import (sha, write, fem_python_copy_plan, fem_python_copy_parity,
                             fem_capacity_json_copy_plan, fem_capacity_json_copy_parity)


def flatten(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from flatten(test)
        else:
            yield test


class SourceBuildIdentity(unittest.TestCase):
    def test_exact_source_build_and_selected_public_suite(self):
        manifest_path = Path(os.environ['YZK_QA_MANIFEST'])
        manifest = json.loads(manifest_path.read_text())
        report = {'passed': False, 'runtime': App.Version(), 'gui_up': bool(App.GuiUp),
                  'discovery_only': manifest['discovery_only'], 'unit_only': manifest['unit_only'],
                  'native_capacity_qualification_claimed': False}
        doc = None
        try:
            self.assertEqual(manifest['schema'], 'FreeCAD-yzk-source-run-manifest-v3')
            self.assertEqual(sha(manifest_path), os.environ['YZK_QA_MANIFEST_SHA'])
            self.assertEqual(fem_python_copy_plan(), manifest['fem_python_copy_plan'])
            self.assertEqual(fem_python_copy_parity(manifest['fem_python_copy_plan']),
                             {'passed': True, 'missing': [], 'mismatched': []})
            self.assertEqual(fem_capacity_json_copy_plan(), manifest['fem_capacity_json_copy_plan'])
            self.assertEqual(fem_capacity_json_copy_parity(manifest['fem_capacity_json_copy_plan']),
                             {'passed': True, 'missing': [], 'mismatched': []})
            for path, expected in manifest['inputs']['files'].items():
                self.assertEqual(sha(path), expected, path)
            header = manifest['version_header']
            self.assertEqual(App.Version()[3], header['FCRevision'])
            self.assertEqual(App.Version()[-1], header['FCRepositoryHash'])
            self.assertEqual(bool(App.GuiUp), manifest['gui'])
            self.assertEqual(Path(App.getHomePath()).resolve(), BUILD)
            dyld = ctypes.CDLL('/usr/lib/libSystem.B.dylib')
            dyld._NSGetExecutablePath.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
            size, buffer = ctypes.c_uint32(4096), ctypes.create_string_buffer(4096)
            self.assertEqual(dyld._NSGetExecutablePath(buffer, ctypes.byref(size)), 0)
            process = Path(os.fsdecode(buffer.value)).resolve()
            self.assertEqual(process, BUILD / 'bin' / ('FreeCAD' if manifest['gui'] else 'FreeCADCmd'))
            self.assertEqual(sha(process), manifest['inputs']['files'][str(process)])
            dyld._dyld_image_count.restype = ctypes.c_uint32
            dyld._dyld_get_image_name.argtypes = [ctypes.c_uint32]
            dyld._dyld_get_image_name.restype = ctypes.c_char_p
            images = [Path(os.fsdecode(dyld._dyld_get_image_name(index))).resolve()
                      for index in range(dyld._dyld_image_count())]
            library = BUILD / 'lib/libFreeCADApp.dylib'
            self.assertEqual([path for path in images if path.name == library.name], [library])
            self.assertEqual(Path(Fem.__file__).resolve(), BUILD / 'Mod/Fem/Fem.so')
            if manifest['gui']:
                self.assertEqual(Path(importlib.import_module('FemGui').__file__).resolve(), BUILD / 'Mod/Fem/FemGui.so')
            suite = unittest.defaultTestLoader.loadTestsFromName(manifest['module'])
            tests = list(flatten(suite))
            self.assertTrue(tests)
            self.assertFalse(any(type(test).__name__ == '_FailedTest' for test in tests))
            ids = [test.id() for test in tests]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertFalse(any(getattr(type(test), '__unittest_skip__', False) or
                                 getattr(getattr(type(test), test._testMethodName), '__unittest_skip__', False)
                                 for test in tests), 'Selected method/class is skipped')
            if not manifest['discovery_only']:
                self.assertCountEqual(ids, manifest['expected_ids'])
                self.assertEqual(len(ids) + 1, manifest['expected_count'])
            origins = {}
            for test in tests:
                name = type(test).__module__
                actual = Path(importlib.import_module(name).__file__).resolve()
                if name.startswith('Yzk'):
                    self.assertEqual(actual.parent, TASK)
                else:
                    self.assertTrue(actual.is_relative_to(BUILD / 'Mod/Fem'), str(actual))
                self.assertEqual(sha(actual), manifest['inputs']['files'][str(actual)], str(actual))
                origins[name] = {'path': str(actual), 'sha256': sha(actual)}
            report['selected_suite'] = {'name': manifest['module'], 'count': len(ids), 'ids': ids, 'origins': origins}
            report['public_FEM_count'] = unittest.defaultTestLoader.loadTestsFromName('TestFemApp').countTestCases()
            if manifest['gui']:
                report['public_GUI_count'] = unittest.defaultTestLoader.loadTestsFromName('TestFemGui').countTestCases()
            loaded = {}
            for name, module in list(sys.modules.items()):
                filename = getattr(module, '__file__', None)
                if filename and name.startswith('fem'):
                    actual = Path(filename).resolve()
                    self.assertTrue(actual.is_relative_to(BUILD / 'Mod/Fem'), str(actual))
                    source = REPO / 'src/Mod/Fem' / actual.relative_to(BUILD / 'Mod/Fem')
                    self.assertEqual(sha(actual), sha(source), name)
                    self.assertEqual(sha(actual), manifest['inputs']['files'][str(actual)], name)
                    loaded[name] = {'path': str(actual), 'source': str(source), 'sha256': sha(actual)}
            from femtools import force_accounting
            import ObjectsFem
            doc = App.newDocument('YzkSourceIdentity')
            solver = ObjectsFem.makeSolverCalculiXCcxTools(doc)
            self.assertEqual(solver.NativeAccountingSolver, '')
            self.assertEqual(list(solver.NativeAccountingSupports), [])
            candidate = Path(force_accounting.solver_binary(solver)).resolve()
            self.assertEqual(candidate, BUILD / 'data/NativeSolvers/ccx-force-accounting')
            self.assertEqual(sha(candidate), manifest['candidate']['sha256'])
            self.assertEqual(force_accounting.SCHEMA, manifest['candidate']['schema'])
            force_accounting.require_capability(candidate)
            report.update(passed=True, loaded_FEM_python=loaded,
                          process={'path': str(process), 'sha256': sha(process)},
                          app_library={'path': str(library), 'sha256': sha(library)},
                          candidate=manifest['candidate'], native_source_compilation_attested=bool(manifest['native_build_receipt']),
                          native_build_receipt=manifest['native_build_receipt'])
        finally:
            if doc is not None and doc.Name in App.listDocuments():
                App.closeDocument(doc.Name)
            write(Path(os.environ['YZK_OUTPUT']) / 'identity.json', report)
