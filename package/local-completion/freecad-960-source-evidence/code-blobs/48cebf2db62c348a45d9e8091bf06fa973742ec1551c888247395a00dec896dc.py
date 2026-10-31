"""Public native diagnostic-version tracer for the approved solver extension."""
import sys
sys.dont_write_bytecode = True
import os
from pathlib import Path
import subprocess
import unittest


class Beam960Capability(unittest.TestCase):
    def test_native_beam_section_diagnostic_contract_is_available(self):
        child = subprocess.run(
            [os.environ['B960_BINARY'], '--freecad-beam-section-version'],
            cwd=os.environ['B960_RUN_DIR'], stdin=subprocess.DEVNULL,
            capture_output=True, timeout=10, text=True, check=False)
        print('[BEAM960-CAPABILITY]', child.returncode, repr(child.stdout), flush=True)
        self.assertEqual(child.returncode, 0)
        self.assertEqual(child.stdout.strip(), 'CCX_BEAM_SECTION_V1')


def load_tests(loader, _tests, _pattern):
    return loader.loadTestsFromTestCase(Beam960Capability)
