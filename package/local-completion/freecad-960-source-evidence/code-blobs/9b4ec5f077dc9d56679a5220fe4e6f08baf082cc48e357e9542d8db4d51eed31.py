"""Load the next single public-interface axial tracer, without product overlays."""
import sys
sys.dont_write_bytecode = True
import importlib.util
from pathlib import Path


def load_tests(loader, _tests, _pattern):
    path = Path('/Users/zukomgwili/src/FreeCAD/src/Mod/Fem/femtest/app/test_beam_section_forces.py')
    spec = importlib.util.spec_from_file_location('Beam960AxialPublicTracer', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return loader.loadTestsFromTestCase(module.TestBeamSectionForcesNative)
