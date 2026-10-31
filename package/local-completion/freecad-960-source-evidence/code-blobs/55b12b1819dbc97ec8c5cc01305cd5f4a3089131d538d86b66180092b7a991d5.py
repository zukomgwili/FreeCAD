"""Run selected shipped tests with exact built module-origin qualification."""
import sys
sys.dont_write_bytecode = True
import hashlib
import importlib
import json
import os
from pathlib import Path
import FreeCAD as App

REPO = Path('/Users/zukomgwili/src/FreeCAD')


def load_tests(loader, _tests, _pattern):
    records = {}
    for name, relative in (
        ('femtools.beam_section_forces', 'femtools/beam_section_forces.py'),
        ('femtools.ccxtools', 'femtools/ccxtools.py'),
        ('femobjects.solver_ccxtools', 'femobjects/solver_ccxtools.py'),
        ('femtest.app.test_beam_section_forces', 'femtest/app/test_beam_section_forces.py'),
    ):
        module = importlib.import_module(name)
        path = Path(module.__file__).resolve()
        assert path == (REPO / 'build/release/Mod/Fem' / relative).resolve(), path
        wanted = (REPO / 'src/Mod/Fem' / relative).read_bytes()
        assert path.read_bytes() == wanted
        records[name] = {'path': str(path), 'sha256': hashlib.sha256(wanted).hexdigest()}
    print('[BEAM960-QUALIFIED-ORIGINS]', json.dumps({'runtime': App.Version(), 'modules': records}), flush=True)
    module = importlib.import_module('femtest.app.test_beam_section_forces')
    names = {
        'request': 'TestBeamSectionForces',
        'axial': 'TestBeamSectionForcesNative.test_axial_member_ends_have_native_identity_units_and_signed_actions',
    }
    return loader.loadTestsFromName(names[os.environ['B960_CASE']], module)
