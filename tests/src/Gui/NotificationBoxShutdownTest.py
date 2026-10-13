# SPDX-License-Identifier: LGPL-2.1-or-later

"""Native-process popup ownership regression, with no invalid drawing fixture."""

import unittest

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore
from PySide6 import QtTest, QtWidgets
import _NotificationBoxTestSupport as Native


class NotificationBoxShutdownTest(unittest.TestCase):
    @staticmethod
    def _preferences():
        return App.ParamGet("User parameter:BaseApp/Preferences/NotificationArea")

    def _observe_popup(self):
        deadline = QtCore.QElapsedTimer()
        deadline.start()
        observed = False
        while deadline.elapsed() < 2000 and not observed:
            Gui.updateGui()
            QtTest.QTest.qWait(25)
            observed = Native.observe_popup()
        self.assertTrue(observed, "Require an actual visible native notification before shutdown")

    def test_cancelled_close_preserves_document_and_popup(self):
        preferences = self._preferences()
        preferences.SetBool("NonIntrusiveNotificationsEnabled", True)
        preferences.SetBool("PreventNonIntrusiveNotificationsWhenWindowNotActive", False)
        # A modal save prompt may deactivate its parent. Disable only that
        # ordinary hide policy to isolate whether rejected close destroys it.
        preferences.SetBool("HideNonIntrusiveNotificationsWhenWindowDeactivated", False)
        doc = App.newDocument("NotificationCancelledClose")
        doc.addObject("App::FeaturePython", "UnsavedObject")
        Gui.getDocument(doc.Name).Modified = True
        App.Console.PrintError("Notification cancelled close control\n")
        self._observe_popup()
        cancelled = []
        timer = QtCore.QTimer(Gui.getMainWindow())

        def cancel_save():
            for widget in QtWidgets.QApplication.topLevelWidgets():
                if (
                    isinstance(widget, QtWidgets.QMessageBox)
                    and widget.objectName() == "confirmSave"
                ):
                    cancelled.append(True)
                    widget.button(QtWidgets.QMessageBox.Cancel).click()
                    timer.stop()
                    break

        timer.timeout.connect(cancel_save)
        timer.start(25)
        try:
            self.assertFalse(Gui.getMainWindow().close())
            self.assertTrue(cancelled, "Require the actual unsaved-document Cancel action")
            self.assertIn(doc.Name, App.listDocuments())
            self.assertTrue(Gui.getDocument(doc.Name).Modified)
            self.assertTrue(Native.observe_popup(), "Rejected close must not destroy the popup")
            print("NATIVE_NOTIFICATION_CANCELLED_CLOSE_REACHED", flush=True)
        finally:
            timer.stop()
            timer.timeout.disconnect(cancel_save)
            App.closeDocument(doc.Name)
            Gui.updateGui()
            preferences.SetBool("HideNonIntrusiveNotificationsWhenWindowDeactivated", True)

    def test_ordinary_native_error_popup(self):
        preferences = self._preferences()
        preferences.SetBool("NonIntrusiveNotificationsEnabled", True)
        preferences.SetBool("PreventNonIntrusiveNotificationsWhenWindowNotActive", False)
        # Keep the stock hide-on-deactivation policy: disabling it masks the
        # late-deletion path that happens when the application exits.
        preferences.SetBool("HideNonIntrusiveNotificationsWhenWindowDeactivated", True)
        Native.emit_error()
        self._observe_popup()
        print("NATIVE_NOTIFICATION_POPUP_REACHED", flush=True)
