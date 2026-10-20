"""Identity of the current source build, separately from the untouched app."""
import hashlib
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
            header = BUILD / 'src/Build/Version.h'
            macros = dict(re.findall(r'^#define\s+(\w+)\s+"([^"]*)"', header.read_text(), re.M))
            self.assertEqual(App.Version()[3], macros['FCRevision'])
            self.assertEqual(App.Version()[-1], macros['FCRepositoryHash'])
            self.assertEqual(Path(App.getHomePath()).resolve(), BUILD)
            self.assertEqual(Path(App.__file__).resolve(), BUILD / 'lib/FreeCAD.so')
            self.assertEqual(Path(Fem.__file__).resolve(), BUILD / 'Mod/Fem/Fem.so')
            report['header'] = {'path': str(header), 'sha256': sha(header)}
            report['modules'] = {}
            for name, relative in (
                ('ObjectsFem', 'ObjectsFem.py'),
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
