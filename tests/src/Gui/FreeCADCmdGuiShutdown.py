# SPDX-License-Identifier: LGPL-2.1-or-later

import FreeCAD as App
import FreeCADGui as Gui


class ResurrectedManipulator:
    def __del__(self):
        print("FREECADCMD_GUI_RESURRECTED_MANIPULATOR_DESTROYED", flush=True)


class ShutdownManipulator:
    def __del__(self):
        try:
            App.ParamGet("User parameter:BaseApp")
        except ValueError:
            print("FREECADCMD_GUI_PARAMETERS_UNAVAILABLE", flush=True)
        else:
            print("FREECADCMD_GUI_PARAMETERS_AVAILABLE", flush=True)
        Gui.addWorkbenchManipulator(ResurrectedManipulator())


def install_shutdown_manipulator():
    Gui.addWorkbenchManipulator(ShutdownManipulator())


Gui.showMainWindow()
Gui.getMainWindow().hide()
install_shutdown_manipulator()
print("FREECADCMD_GUI_INITIALIZED", flush=True)
