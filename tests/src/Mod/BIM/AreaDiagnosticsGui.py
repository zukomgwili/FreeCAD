# SPDX-License-Identifier: LGPL-2.1-or-later

"""Native optional-area failure persistence on an isolated, minimized fixture.

Set FREECAD_0O1_OUTPUT to a new evidence directory. For an independent cold
process set FREECAD_0O1_REOPEN to the first saved optional-area.FCStd.
No building document is opened, repaired, or accepted by this probe.
"""

import json
import os
from pathlib import Path
import unittest
from zipfile import ZipFile

import ArchComponent
import FreeCAD as App
import FreeCADGui as Gui
from bimtests import TestArchAreaDiagnostics as area_tests
from PySide import QtCore


@unittest.skipUnless(App.GuiUp, "Requires a native GUI document")
class AreaDiagnosticsGui(unittest.TestCase):
    def test_native_saved_dependency_and_cold_recompute(self):
        root = Path(os.environ["FREECAD_0O1_OUTPUT"])
        root.mkdir(parents=True, exist_ok=False)
        fixture = area_tests.TestArchAreaDiagnostics(
            "test_valid_quantities_and_preference_restoration")
        fixture.setUp()
        try:
            reopen = os.environ.get("FREECAD_0O1_REOPEN")
            if reopen:
                App.closeDocument(fixture.document.Name)
                fixture.document = App.openDocument(reopen)
                covering = fixture.document.getObjectsByLabel("Covering")[0]
                union = fixture.document.getObject("Downstream")
            else:
                covering, union = fixture.make_model()
                fixture.document.recompute()
            # Cold process has not touched or recomputed the restored target yet.
            fixture.assert_model(covering, union)
            fixture.assert_zero_areas(covering)
            saved_volumes = [covering.Shape.Volume, union.Shape.Volume]
            for unused in range(2):
                covering.touch()
                fixture.document.recompute()
                fixture.assert_model(covering, union)
                fixture.assert_zero_areas(covering)
                self.assertEqual(saved_volumes, [covering.Shape.Volume, union.Shape.Volume])
            for obj in fixture.document.Objects:
                obj.ViewObject.Visibility = obj == union
            Gui.activeDocument().activeView().viewAxonometric()
            Gui.activeDocument().activeView().fitAll()
            Gui.updateGui()
            loop = QtCore.QEventLoop()
            QtCore.QTimer.singleShot(250, loop.quit)
            loop.exec()
            Gui.activeDocument().activeView().saveImage(
                str(root / "native-valid-union.png"), 1000, 700, "White")
            filename = root / "optional-area.FCStd"
            fixture.document.saveAs(str(filename))
            with ZipFile(filename) as archive:
                self.assertIn("GuiDocument.xml", archive.namelist())
            (root / "report.json").write_text(json.dumps({
                "version": App.Version(),
                "module": ArchComponent.__file__,
                "cold_process": bool(reopen),
                "covering_state": covering.State,
                "union_state": union.State,
                "volumes_mm3": saved_volumes,
                "area_quantities_unavailable": True,
                "building_or_quantity_acceptance": False,
            }, indent=2))
        finally:
            fixture.tearDown()
