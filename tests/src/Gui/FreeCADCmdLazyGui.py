# SPDX-License-Identifier: LGPL-2.1-or-later

import os
import threading

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

mode = os.environ["FREECAD_LAZY_GUI_TEST_MODE"]
host_application = None
if mode in {"threaded-rejected", "threaded-recovery"}:
    assert QtCore.QCoreApplication.instance() is None
    for _ in range(2):
        try:
            Gui.showMainWindow(True)
        except RuntimeError as error:
            assert "main thread" in str(error)
        else:
            raise AssertionError("Threaded QApplication startup must be rejected")
        assert QtCore.QCoreApplication.instance() is None
    print("FREECADCMD_THREADED_GUI_REJECTED", flush=True)
    if mode == "threaded-recovery":
        Gui.showMainWindow()
elif mode == "host-application":
    host_application = QtWidgets.QApplication([])
    Gui.showMainWindow(True)
    assert QtCore.QCoreApplication.instance() is host_application
elif mode == "without-gui":
    assert QtCore.QCoreApplication.instance() is None
    Gui.setupWithoutGUI()
    assert QtCore.QCoreApplication.instance() is None

    class DocumentProxy:
        def __del__(self):
            App.ParamGet("User parameter:BaseApp")
            print("FREECADCMD_LAZY_GUI_DOCUMENT_DESTROYED", flush=True)

    doc = App.newDocument("LazyServicesShutdownProbe")
    feature = doc.addObject("App::FeaturePython", "Feature")
    feature.Proxy = DocumentProxy()
    doc.recompute()
    print("FREECADCMD_LAZY_SERVICES_INITIALIZED", flush=True)
else:
    Gui.showMainWindow()
    # The legacy flag is harmless once a main-thread QApplication exists.
    Gui.showMainWindow(True)

if mode not in {"threaded-rejected", "without-gui"}:
    window = Gui.getMainWindow()
    window.hide()
    assert "ReportOutput" in App.Console.GetObservers()
    assert "StatusBar" in App.Console.GetObservers()

    errors = []

    def worker_show():
        try:
            Gui.showMainWindow(True)
        except RuntimeError as error:
            errors.append(str(error))

    worker = threading.Thread(target=worker_show)
    worker.start()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert len(errors) == 1 and "main thread" in errors[0]

    def window_destroyed():
        assert QtCore.QCoreApplication.instance() is not None
        if host_application is not None:
            assert QtCore.QCoreApplication.instance() is host_application
        App.ParamGet("User parameter:BaseApp")
        print("FREECADCMD_LAZY_GUI_WINDOW_DESTROYED", flush=True)

    window.destroyed.connect(window_destroyed)
    doc = App.newDocument("LazyGuiShutdownProbe")
    doc.addObject("App::FeaturePython", "Feature")
    doc.recompute()

    class ShutdownManipulator:
        def __del__(self):
            App.ParamGet("User parameter:BaseApp")
            print("FREECADCMD_LAZY_GUI_PARAMETERS_AVAILABLE", flush=True)

    Gui.addWorkbenchManipulator(ShutdownManipulator())
    print("FREECADCMD_LAZY_GUI_INITIALIZED", flush=True)
