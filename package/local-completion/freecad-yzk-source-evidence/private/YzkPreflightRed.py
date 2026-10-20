"""One exact new public stock-export regression against the installed baseline.

Only this test is loaded from the working tree. Product modules stay installed;
this is not a source-build qualification or a physical native solver fixture.
"""
import importlib.util
from pathlib import Path
import unittest


TEST_FILE = Path('/Users/zukomgwili/src/FreeCAD/src/Mod/Fem/femtest/app/test_force_accounting.py')
SPEC = importlib.util.spec_from_file_location('YzkNewPublicTest', TEST_FILE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def load_tests(loader, tests, pattern):
    return loader.loadTestsFromName(
        'TestForceAccounting.test_stock_export_refuses_complete_port_count_before_mesh_work', MODULE
    )
