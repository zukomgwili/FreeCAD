# SPDX-License-Identifier: LGPL-2.1-or-later

import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtCore, QtWidgets


REENTRY_WARNING = "FREECAD_NOTIFICATION_REENTRY_WARNING\n"
REENTRY_WARNING_TEXT = REENTRY_WARNING.rstrip()


class ReentryProbe(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.tripped = False
        self.nested_warning_returned = False

    def eventFilter(self, obj, event):
        if (
            not self.tripped
            and event.type() == QtCore.QEvent.Type.Show
            and obj.metaObject().className() == "Gui::NotificationLabel"
            and REENTRY_WARNING_TEXT in obj.property("text")
        ):
            self.tripped = True
            print("FREECAD_NOTIFICATION_REENTRY_BOUNDARY", flush=True)
            # Re-send the same warning to exercise the grouped-notification restart path.
            App.Console.PrintWarning(REENTRY_WARNING)
            self.nested_warning_returned = True
            print("FREECAD_NOTIFICATION_REENTRY_NESTED_RETURNED", flush=True)
        return False


preferences = App.ParamGet("User parameter:BaseApp/Preferences/NotificationArea")
preferences.SetBool("NotificationAreaEnabled", True)
preferences.SetBool("NonIntrusiveNotificationsEnabled", True)
preferences.SetBool("PreventNonIntrusiveNotificationsWhenWindowNotActive", False)
preferences.SetBool("HideNonIntrusiveNotificationsWhenWindowDeactivated", False)
preferences.SetInt("NotificationTime", 1)

Gui.showMainWindow()
Gui.getMainWindow().hide()

application = QtWidgets.QApplication.instance()
probe = ReentryProbe()
application.installEventFilter(probe)


def send_outer_warning():
    print("FREECAD_NOTIFICATION_REENTRY_OUTER_WARNING", flush=True)
    App.Console.PrintWarning(REENTRY_WARNING)
    print("FREECAD_NOTIFICATION_REENTRY_OUTER_RETURNED", flush=True)


def complete():
    if not probe.tripped:
        raise RuntimeError("Notification label show event was not reached")
    if not probe.nested_warning_returned:
        raise RuntimeError("Nested warning did not return")
    application.removeEventFilter(probe)
    preferences.SetBool("NotificationAreaEnabled", False)
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    application.processEvents()
    print("FREECAD_NOTIFICATION_REENTRY_COMPLETED", flush=True)


send_outer_warning()

deadline = time.monotonic() + 3.0
while time.monotonic() < deadline:
    application.processEvents()
    time.sleep(0.01)

complete()
