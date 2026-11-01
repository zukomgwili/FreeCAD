import sys
sys.dont_write_bytecode = True
import importlib.util
import unittest

spec = importlib.util.spec_from_file_location('control_source', '/Users/zukomgwili/src/FreeCAD/src/Mod/Fem/femtest/app/test_static_step_amplitude.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
TestStaticStepAmplitude = module.TestStaticStepAmplitude

def suite():
    return unittest.TestSuite(module.TestStaticStepAmplitude(name) for name in (
        'test_step_holds_volumetric_gravity_and_keeps_explicit_force_and_pressure_histories',
        'test_enabled_missing_or_invalid_load_amplitudes_are_refused_without_repair',
    ))
