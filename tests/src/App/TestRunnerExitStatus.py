# SPDX-License-Identifier: LGPL-2.1-or-later

"""Check unittest outcomes against real FreeCAD/FreeCADCmd process statuses."""

import argparse
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import unittest

parser = argparse.ArgumentParser()
parser.add_argument("--executable", required=True)
parser.add_argument("--gui", action="store_true")
options, test_args = parser.parse_known_args()
FIXTURE = "TestRunnerExitStatusFixture"
FIXTURE_DIRECTORY = Path(__file__).resolve().parent


class TestRunnerExitStatus(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="freecad-test-exit-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.environment = os.environ.copy()
        for name in ("PYTHONPATH", "PYTHONHOME"):
            self.environment.pop(name, None)
        self.environment["PYTHONDONTWRITEBYTECODE"] = "1"
        for name, folder in (
            ("FREECAD_USER_HOME", "user"),
            ("FREECAD_USER_DATA", "data"),
            ("FREECAD_USER_TEMP", "temp"),
            ("XDG_CONFIG_HOME", "config"),
            ("XDG_CACHE_HOME", "cache"),
            ("XDG_DATA_HOME", "xdg-data"),
        ):
            target = self.root / folder
            target.mkdir()
            self.environment[name] = str(target)

    def run_freecad(self, arguments):
        command = [
            options.executable,
            "--safe-mode",
            "--user-cfg",
            str(self.root / "user.cfg"),
            "--system-cfg",
            str(self.root / "system.cfg"),
            *arguments,
        ]
        process = subprocess.Popen(
            command,
            cwd=self.root,
            env=self.environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=os.name == "posix",
        )
        try:
            output, _ = process.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                pass
            output, _ = process.communicate()
            self.fail("FreeCAD process exceeded 30 seconds:\n" + output)
        return process.returncode, output

    def check_outcome(self, suites, expected_code, markers, summary, test_count=1, flag="-t"):
        arguments = ["-P", str(FIXTURE_DIRECTORY)]
        for suite in suites:
            arguments.extend((flag, f"{FIXTURE}.{suite}"))
        code, output = self.run_freecad(arguments)
        # Require unittest to finish and the requested cases to execute: a
        # startup failure or crash is not evidence of correct failure status.
        self.assertEqual(code, expected_code, output)
        for marker in markers:
            self.assertIn(f"TEST_RUNNER_EXECUTED {FIXTURE}.{marker}", output, output)
        actual_summaries = re.findall(r"^(OK(?: \([^\n]*\))?|FAILED \([^\n]*\))$", output, re.M)
        self.assertEqual(actual_summaries, [summary], output)
        self.assertEqual(
            re.findall(r"^Ran (\d+) tests? in ", output, re.M), [str(test_count)], output
        )
        return output

    def test_pass(self):
        self.check_outcome(("Passing",), 0, ("Passing.test_pass",), "OK")

    def test_assertion_failure(self):
        self.check_outcome(("Failing",), 1, ("Failing.test_failure",), "FAILED (failures=1)")

    def test_runtime_error(self):
        self.check_outcome(("Error",), 1, ("Error.test_error",), "FAILED (errors=1)")

    def test_mixed_suite(self):
        self.check_outcome(
            ("Mixed",),
            1,
            ("Mixed.test_failure", "Mixed.test_pass"),
            "FAILED (failures=1)",
            test_count=2,
        )

    def test_failure_then_pass(self):
        self.check_outcome(
            ("Failing", "Passing"),
            1,
            ("Failing.test_failure", "Passing.test_pass"),
            "FAILED (failures=1)",
            test_count=2,
        )

    def test_pass_then_failure(self):
        self.check_outcome(
            ("Passing", "Failing"),
            1,
            ("Passing.test_pass", "Failing.test_failure"),
            "FAILED (failures=1)",
            test_count=2,
        )

    def test_skip_is_success(self):
        self.check_outcome(("Skipped",), 0, ("Skipped.test_skip",), "OK (skipped=1)")

    def test_expected_failure_is_success(self):
        self.check_outcome(
            ("ExpectedFailure",),
            0,
            ("ExpectedFailure.test_expected_failure",),
            "OK (expected failures=1)",
        )

    def test_unexpected_success_is_failure(self):
        self.check_outcome(
            ("UnexpectedSuccess",),
            1,
            ("UnexpectedSuccess.test_unexpected_success",),
            "FAILED (unexpected successes=1)",
        )

    def test_loader_error_is_failure(self):
        output = self.check_outcome(("MissingTestCase",), 1, (), "FAILED (errors=1)")
        self.assertIn("MissingTestCase", output)

    def test_suite_factory_exception_is_failure(self):
        code, output = self.run_freecad(
            ("-P", str(FIXTURE_DIRECTORY), "-t", f"{FIXTURE}.exploding_suite")
        )
        self.assertEqual(code, 1, output)
        self.assertIn("TEST_RUNNER_SUITE_FACTORY_REACHED", output)
        self.assertIn("deliberate test-runner suite-factory error", output)
        self.assertNotRegex(output, r"(?m)^Ran \d+ tests? in ")

    @unittest.skipUnless(options.gui, "run-open event loop applies only to FreeCAD")
    def test_run_open_stays_open_until_normal_quit(self):
        output = self.check_outcome(
            ("RunOpenFailing",),
            0,
            ("RunOpenFailing.test_failure",),
            "FAILED (failures=1)",
            flag="--run-open",
        )
        marker = "TEST_RUNNER_RUN_OPEN_EVENT_LOOP_REACHED"
        self.assertIn(marker, output)
        self.assertLess(output.index("FAILED (failures=1)"), output.index(marker), output)

    @unittest.skipUnless(options.gui, "ordinary GUI startup applies only to FreeCAD")
    def test_ordinary_gui_startup_is_success(self):
        macro = self.root / "ordinary-gui.FCMacro"
        macro.write_text(
            "import FreeCADGui as Gui\n"
            "from PySide import QtCore, QtWidgets\n"
            "def finish():\n"
            "    assert Gui.getMainWindow() is not None\n"
            "    print('TEST_RUNNER_ORDINARY_GUI_STARTED', flush=True)\n"
            "    QtWidgets.QApplication.instance().quit()\n"
            "QtCore.QTimer.singleShot(0, finish)\n",
            encoding="utf-8",
        )
        code, output = self.run_freecad((str(macro),))
        self.assertEqual(code, 0, output)
        self.assertIn("TEST_RUNNER_ORDINARY_GUI_STARTED", output)
        self.assertNotRegex(output, r"(?m)^Ran \d+ tests? in ")


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0], *test_args])
