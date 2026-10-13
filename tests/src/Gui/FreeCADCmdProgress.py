# SPDX-License-Identifier: LGPL-2.1-or-later

"""Progress cursor, update, event-delivery and cancellation process regression."""

import time
import threading

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

import sys
from types import ModuleType


def run_probe():
    Gui.showMainWindow()
    import _ProgressBarTestSupport as ProgressSupport

    quit_on_last_window = QtWidgets.QApplication.quitOnLastWindowClosed()
    QtWidgets.QApplication.setQuitOnLastWindowClosed(False)
    window = Gui.getMainWindow()
    window.hide()
    progress = App.Base.ProgressIndicator()
    initial_cursor = QtWidgets.QApplication.overrideCursor()
    QtWidgets.QApplication.setOverrideCursor(QtGui.QCursor(QtCore.Qt.CrossCursor))

    def assert_host_cursor():
        assert QtWidgets.QApplication.overrideCursor().shape() == QtCore.Qt.CrossCursor

    for _ in range(10):
        progress.start("Short native operation", 1)
        try:
            assert (
                QtWidgets.QApplication.overrideCursor().shape() == QtCore.Qt.CrossCursor
            ), "Short operations must defer the wait cursor until the existing update interval"
            progress.next()
        finally:
            progress.stop()
        assert_host_cursor()
    print("FREECAD_SHORT_PROGRESS_CURSOR_DEFERRED", flush=True)

    progress.start("Long native operation", 100)
    time.sleep(0.11)
    progress.next()
    assert QtWidgets.QApplication.overrideCursor().shape() == QtCore.Qt.WaitCursor

    nested = App.Base.ProgressIndicator()
    nested.start("Nested native operation", 1)
    nested.next()
    nested.stop()
    assert QtWidgets.QApplication.overrideCursor().shape() == QtCore.Qt.WaitCursor
    progress.stop()
    assert_host_cursor()
    print("FREECAD_LONG_NESTED_PROGRESS_CURSOR_RESTORED", flush=True)

    bar = window.statusBar().findChild(QtWidgets.QProgressBar, "progressBar")
    assert bar is not None
    assert QtCore.QMetaObject.invokeMethod(
        bar, "setMinimumDuration", QtCore.Qt.DirectConnection, QtCore.Q_ARG(int, 20)
    )
    try:
        # Do not drain the old completion before starting the next operation.
        progress.start("Short predecessor", 1)
        progress.stop()
        progress.start("Long successor", 100)
        time.sleep(0.11)
        progress.next()
        assert not bar.isHidden(), "A stale completion must not cancel the new progress timer"
    finally:
        progress.stop()
        QtCore.QMetaObject.invokeMethod(
            bar, "setMinimumDuration", QtCore.Qt.DirectConnection, QtCore.Q_ARG(int, 2000)
        )
    assert_host_cursor()
    print("FREECAD_PROGRESS_SUCCESSOR_TIMER_RETAINED", flush=True)

    worker_ready = threading.Event()
    worker_continue = threading.Event()
    worker_errors = []

    def worker_progress():
        worker_indicator = App.Base.ProgressIndicator()
        try:
            worker_indicator.start("Worker native operation", 100)
            worker_ready.set()
            assert worker_continue.wait(2)
            worker_indicator.next()
        except Exception as error:
            worker_errors.append(str(error))
        finally:
            worker_indicator.stop()

    QtCore.QMetaObject.invokeMethod(
        bar, "setMinimumDuration", QtCore.Qt.DirectConnection, QtCore.Q_ARG(int, 20)
    )
    worker = threading.Thread(target=worker_progress)
    try:
        worker.start()
        assert worker_ready.wait(2)
        QtWidgets.QApplication.processEvents()  # Apply the queued worker start.
        time.sleep(0.04)
        QtWidgets.QApplication.processEvents()
        assert not bar.isHidden(), "Worker progress must still become visible"
        assert_host_cursor()
        time.sleep(0.11)
        # Main-thread controller callbacks must not acquire a cursor for a
        # worker-owned job: its queued completion does not own that cursor.
        ProgressSupport.check_abort()
        print(
            "Worker cursor after native checkAbort:",
            QtWidgets.QApplication.overrideCursor().shape(),
            flush=True,
        )
        assert_host_cursor()
        ProgressSupport.pause_resume()
        assert_host_cursor()
    finally:
        worker_continue.set()
        worker.join(timeout=2)
        QtWidgets.QApplication.processEvents()  # Apply the queued worker completion.
        QtCore.QMetaObject.invokeMethod(
            bar, "setMinimumDuration", QtCore.Qt.DirectConnection, QtCore.Q_ARG(int, 2000)
        )
    assert not worker.is_alive() and not worker_errors, worker_errors
    assert bar.isHidden()
    assert_host_cursor()
    print("FREECAD_PROGRESS_WORKER_COMPLETION_RETAINED", flush=True)
    print("FREECAD_PROGRESS_WORKER_CURSOR_RETAINED", flush=True)

    # Own the timer and disconnect it before teardown; do not use a static
    # PySide QTimer.singleShot whose Python callback can outlive the interpreter.
    answer_timer = QtCore.QTimer(window)
    answer_timer.setInterval(1)
    paused_cursor_errors = []

    def answer_abort():
        for widget in QtWidgets.QApplication.topLevelWidgets():
            if isinstance(widget, QtWidgets.QMessageBox) and widget.isVisible():
                if QtWidgets.QApplication.overrideCursor().shape() != QtCore.Qt.ArrowCursor:
                    paused_cursor_errors.append("Abort confirmation must pause the busy cursor")
                widget.button(QtWidgets.QMessageBox.Yes).click()
                answer_timer.stop()

    answer_timer.timeout.connect(answer_abort)
    try:
        for long_operation in (False, True):
            progress.start("Cancelable native operation", 100)
            if long_operation:
                time.sleep(0.11)
                progress.next()
                assert QtWidgets.QApplication.overrideCursor().shape() == QtCore.Qt.WaitCursor
            escape = QtGui.QKeyEvent(
                QtCore.QEvent.KeyPress, QtCore.Qt.Key_Escape, QtCore.Qt.NoModifier
            )
            QtWidgets.QApplication.sendEvent(window, escape)
            answer_timer.start()
            try:
                progress.next(True)
            except RuntimeError as error:
                assert "abort" in str(error).lower(), str(error)
            else:
                raise AssertionError(f"Escape must still cancel progress (long={long_operation})")
            assert_host_cursor()
            print(
                (
                    "FREECAD_PROGRESS_ABORTED_LONG"
                    if long_operation
                    else "FREECAD_PROGRESS_ABORTED_SHORT"
                ),
                flush=True,
            )
    finally:
        answer_timer.stop()
        answer_timer.timeout.disconnect(answer_abort)
        progress.stop()
    assert not paused_cursor_errors, paused_cursor_errors
    assert_host_cursor()
    print("FREECAD_SHORT_PROGRESS_CANCELLATION_RETAINED", flush=True)

    events = []
    delivery_timer = QtCore.QTimer(window)
    delivery_timer.setSingleShot(True)
    delivery_timer.timeout.connect(lambda: events.append(True))
    progress.start("Responsive native operation", 100)
    delivery_timer.start(0)
    # Sleep rather than qWait, so only the sequencer's update can deliver the timer.
    time.sleep(0.11)
    progress.next()
    assert events
    progress.stop()
    delivery_timer.stop()
    delivery_timer.timeout.disconnect()
    assert_host_cursor()
    print("FREECAD_PROGRESS_EVENT_DELIVERY_RETAINED", flush=True)
    QtWidgets.QApplication.restoreOverrideCursor()
    assert QtWidgets.QApplication.overrideCursor() is initial_cursor
    print("FREECAD_PROGRESS_HOST_CURSOR_RESTORED", flush=True)
    QtWidgets.QApplication.setQuitOnLastWindowClosed(quit_on_last_window)


# Lazy GUI startup can load the current command-line script recursively.
# Register the guard before showMainWindow(), and keep Qt wrappers local so
# they are released before native application shutdown.
_guard = "freecad_progress_process_probe_running"
if _guard not in sys.modules:
    sys.modules[_guard] = ModuleType(_guard)
    run_probe()
