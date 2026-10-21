"""Load the source regression only; production imports stay installed stock."""
import importlib.util
import unittest

path = "/Users/zukomgwili/src/FreeCAD/src/Mod/Fem/femtest/app/test_contact_state_native.py"
spec = importlib.util.spec_from_file_location("contact_state_source_test", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def load_tests(loader, tests, pattern):
    return loader.loadTestsFromTestCase(module.TestContactStateNative)
