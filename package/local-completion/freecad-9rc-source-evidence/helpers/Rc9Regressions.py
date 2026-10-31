"""Legacy observer contracts, one native case at a time."""
import unittest
import os
from pathlib import Path

def load_tests(loader, tests, pattern):
    Path(os.environ['B960_WITNESS_ROOT']).mkdir(parents=True,exist_ok=True)
    return unittest.TestSuite(loader.loadTestsFromName(name) for name in (
        'femtest.app.test_beam_section_forces_native',
        'femtest.app.test_beam_coupling_native',
        'femtest.app.test_beam_solid_coupling_native',
        'femtest.app.test_contact_state_native'))
