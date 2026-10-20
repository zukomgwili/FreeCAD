"""Identity of the current source build, separately from the untouched app."""
import hashlib
import ctypes
import importlib
import json
import os
from pathlib import Path
import re
import sys
import unittest

sys.dont_write_bytecode = True
import FreeCAD as App
import Fem

REPO = Path('/Users/zukomgwili/src/FreeCAD')
BUILD = REPO / 'build/release'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class SourceYwuIdentity(unittest.TestCase):
    def test_source_build_and_native_contract(self):
        report = {'passed': False, 'runtime': App.Version(), 'gui_up': bool(App.GuiUp)}
        temporary = None
        try:
            expected_gui = os.environ.get('YWU_EXPECT_GUI') == '1'
            self.assertEqual(bool(App.GuiUp), expected_gui)
            header = BUILD / 'src/Build/Version.h'
            macros = dict(re.findall(r'^#define\s+(\w+)\s+"([^"]*)"', header.read_text(), re.M))
            self.assertEqual(App.Version()[3], macros['FCRevision'])
            self.assertEqual(App.Version()[-1], macros['FCRepositoryHash'])
            self.assertEqual(Path(App.getHomePath()).resolve(), BUILD)
            # Embedded FreeCAD is a built-in module, not a Python file. Check
            # the actual Mach-O process and loaded native library instead.
            dyld = ctypes.CDLL('/usr/lib/libSystem.B.dylib')
            dyld._NSGetExecutablePath.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
            size = ctypes.c_uint32(4096)
            buffer = ctypes.create_string_buffer(size.value)
            self.assertEqual(dyld._NSGetExecutablePath(buffer, ctypes.byref(size)), 0)
            executable = Path(os.fsdecode(buffer.value)).resolve()
            self.assertEqual(executable, BUILD / 'bin' / ('FreeCAD' if expected_gui else 'FreeCADCmd'))
            dyld._dyld_image_count.restype = ctypes.c_uint32
            dyld._dyld_get_image_name.argtypes = [ctypes.c_uint32]
            dyld._dyld_get_image_name.restype = ctypes.c_char_p
            images = [Path(os.fsdecode(dyld._dyld_get_image_name(index))).resolve()
                      for index in range(dyld._dyld_image_count())]
            library = BUILD / 'lib/libFreeCADApp.dylib'
            self.assertEqual([path for path in images if path.name == library.name], [library])
            report['process'] = {'path': str(executable), 'sha256': sha(executable)}
            report['app_library'] = {'path': str(library), 'sha256': sha(library)}
            self.assertEqual(Path(Fem.__file__).resolve(), BUILD / 'Mod/Fem/Fem.so')
            report['header'] = {'path': str(header), 'sha256': sha(header)}
            report['modules'] = {}
            for name, relative in (
                ('ObjectsFem', 'ObjectsFem.py'),
                ('TestFemApp', 'TestFemApp.py'),
                ('femtest.app.test_moving_port_accounting_native',
                 'femtest/app/test_moving_port_accounting_native.py'),
                ('femtools.force_accounting', 'femtools/force_accounting.py'),
                ('femtools.ccxtools', 'femtools/ccxtools.py'),
                ('femobjects.solver_ccxtools', 'femobjects/solver_ccxtools.py'),
                ('femsolver.calculix.write_constraint_elastic_connector',
                 'femsolver/calculix/write_constraint_elastic_connector.py'),
                ('femresult.contact_observation_source', 'femresult/contact_observation_source.py'),
            ):
                actual = Path(importlib.import_module(name).__file__).resolve()
                self.assertEqual(actual, BUILD / 'Mod/Fem' / relative)
                self.assertEqual(sha(actual), sha(REPO / 'src/Mod/Fem' / relative))
                report['modules'][name] = {'path': str(actual), 'sha256': sha(actual)}
            app_suite = unittest.defaultTestLoader.loadTestsFromName('TestFemApp')
            self.assertEqual(app_suite.countTestCases(), 395)
            report['TestFemApp_count'] = app_suite.countTestCases()
            if expected_gui:
                gui_module = importlib.import_module('FemGui')
                self.assertEqual(Path(gui_module.__file__).resolve(), BUILD / 'Mod/Fem/FemGui.so')
                gui_suite = unittest.defaultTestLoader.loadTestsFromName('TestFemGui')
                self.assertEqual(gui_suite.countTestCases(), 8)
                report['TestFemGui_count'] = gui_suite.countTestCases()
            report['loaded_fem_python'] = {}
            for name, module in list(sys.modules.items()):
                filename = getattr(module, '__file__', None)
                if filename and name.startswith('fem'):
                    actual = Path(filename).resolve()
                    self.assertTrue(actual.is_relative_to(BUILD / 'Mod/Fem'), str(actual))
                    original = REPO / 'src/Mod/Fem' / actual.relative_to(BUILD / 'Mod/Fem')
                    self.assertTrue(original.is_file(), str(original))
                    self.assertEqual(sha(actual), sha(original), name)
                    report['loaded_fem_python'][name] = {'path': str(actual), 'sha256': sha(actual)}
            from femtools import force_accounting
            import ObjectsFem
            temporary = App.newDocument('YwuSourceIdentity')
            solver = ObjectsFem.makeSolverCalculiXCcxTools(temporary)
            self.assertEqual(solver.NativeAccountingSupports, [])
            self.assertEqual(solver.NativeAccountingSolver, '')
            candidate = Path(force_accounting.solver_binary(solver)).resolve()
            self.assertEqual(candidate, BUILD / 'data/NativeSolvers/ccx-force-accounting')
            self.assertEqual(force_accounting.SCHEMA, 'CCX_FORCE_ACCOUNTING_V3')
            force_accounting.require_capability(candidate)
            report['candidate'] = {'path': str(candidate), 'sha256': sha(candidate),
                                   'capability': force_accounting.SCHEMA, 'override': False}
            report['passed'] = True
        except BaseException as error:
            report['error'] = repr(error)
            raise
        finally:
            if temporary is not None:
                App.closeDocument(temporary.Name)
            with Path(os.environ['YWU_IDENTITY']).open('x') as stream:
                stream.write(json.dumps(report, indent=2) + '\n')
