# SPDX-License-Identifier: LGPL-2.1-or-later

"""Deliberate unittest outcomes for the real executable's -t process tests."""

import unittest


class Outcome(unittest.TestCase):
    def setUp(self):
        print("TEST_RUNNER_EXECUTED " + self.id(), flush=True)


class Passing(Outcome):
    def test_pass(self):
        self.assertTrue(True)


class Failing(Outcome):
    def test_failure(self):
        self.fail("deliberate test-runner assertion failure")


class Error(Outcome):
    def test_error(self):
        raise RuntimeError("deliberate test-runner runtime error")


class Mixed(Outcome):
    def test_failure(self):
        self.fail("deliberate mixed-suite assertion failure")

    def test_pass(self):
        self.assertTrue(True)


class Skipped(Outcome):
    def test_skip(self):
        self.skipTest("deliberate test-runner skip")


class ExpectedFailure(Outcome):
    @unittest.expectedFailure
    def test_expected_failure(self):
        self.fail("deliberate test-runner expected failure")


class UnexpectedSuccess(Outcome):
    @unittest.expectedFailure
    def test_unexpected_success(self):
        self.assertTrue(True)


def exploding_suite():
    print("TEST_RUNNER_SUITE_FACTORY_REACHED", flush=True)
    raise RuntimeError("deliberate test-runner suite-factory error")


class RunOpenFailing(Outcome):
    def test_failure(self):
        import FreeCADGui as Gui
        from PySide import QtCore, QtWidgets

        def finish():
            assert Gui.getMainWindow() is not None
            print("TEST_RUNNER_RUN_OPEN_EVENT_LOOP_REACHED", flush=True)
            QtWidgets.QApplication.instance().quit()

        # This callback cannot run until the synchronous tests finish and the
        # GUI event loop resumes. --run-open must not exit on the failed test.
        QtCore.QTimer.singleShot(0, finish)
        self.fail("deliberate run-open assertion failure")
