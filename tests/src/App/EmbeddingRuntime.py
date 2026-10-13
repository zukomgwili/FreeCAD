# SPDX-License-Identifier: LGPL-2.1-or-later

"""Exercise embedding in isolated processes, including incompatible hosts."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

parser = argparse.ArgumentParser()
parser.add_argument("--host", required=True)
parser.add_argument("--module-dir", required=True)
parser.add_argument("--freecadcmd", required=True)
options, test_args = parser.parse_known_args()

IMPORT_PROBE = """
import sys
try:
    import FreeCAD as App
except ImportError as error:
    assert "different Python runtime" in str(error), str(error)
    assert "FreeCAD" not in sys.modules
    print("FREECAD_RUNTIME_REJECTED")
else:
    document = App.newDocument("EmbeddingRuntimeProbe")
    feature = document.addObject("App::FeaturePython", "Probe")
    document.recompute()
    assert feature.Name == "Probe"
    App.closeDocument(document.Name)
    print("FREECAD_RUNTIME_SUPPORTED")
"""


class EmbeddingRuntime(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="freecad-embedding-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.environment = os.environ.copy()
        self.environment.update(
            PYTHONPATH=options.module_dir,
            PYTHONDONTWRITEBYTECODE="1",
            FREECAD_USER_HOME=str(self.root / "user"),
            FREECAD_USER_DATA=str(self.root / "data"),
            FREECAD_USER_TEMP=str(self.root / "temp"),
        )

    def run_host(self, command):
        process = subprocess.run(
            command,
            cwd=self.root,
            env=self.environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            process.returncode,
            0,
            f"{command[0]} exited {process.returncode}\n"
            f"stdout:\n{process.stdout}\nstderr:\n{process.stderr}",
        )
        return process.stdout + process.stderr

    def test_configured_interpreter_import_or_safe_runtime_rejection(self):
        output = self.run_host([sys.executable, "-c", IMPORT_PROBE])
        self.assertTrue(
            "FREECAD_RUNTIME_SUPPORTED" in output or "FREECAD_RUNTIME_REJECTED" in output,
            output,
        )
        if "FREECAD_RUNTIME_REJECTED" in output:
            # Rejection must happen before application/user-data initialization.
            for folder in ("user", "data", "temp"):
                self.assertFalse((self.root / folder).exists(), output)

    def test_matching_shared_runtime_import(self):
        self.environment["PYTHONHOME"] = sys.prefix
        output = self.run_host([options.host, "-c", IMPORT_PROBE])
        self.assertIn("FREECAD_RUNTIME_SUPPORTED", output)
        self.assertNotIn("FREECAD_RUNTIME_REJECTED", output)

    def test_existing_command_line_script_runtime(self):
        script = self.root / "probe.py"
        script.write_text(IMPORT_PROBE, encoding="utf-8")
        output = self.run_host(
            [
                options.freecadcmd,
                "-u",
                str(self.root / "user.cfg"),
                "-s",
                str(self.root / "system.cfg"),
                str(script),
            ]
        )
        self.assertIn("FREECAD_RUNTIME_SUPPORTED", output)
        self.assertNotIn("FREECAD_RUNTIME_REJECTED", output)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0], *test_args])
