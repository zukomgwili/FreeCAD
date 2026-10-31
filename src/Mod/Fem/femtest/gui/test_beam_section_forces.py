# SPDX-License-Identifier: LGPL-2.1-or-later
"""Beam section output through the visible native solver task panel."""

import os
import tempfile
import time
import unittest
from pathlib import Path

import FreeCAD as App
from femexamples.ccx_cantilever_base_edge import setup_cantilever_base_edge
from femtools.force_accounting import solver_binary

if App.GuiUp:
    from PySide import QtCore
    from PySide import QtWidgets

    import FreeCADGui as Gui
    import FemGui


@unittest.skipUnless(App.GuiUp, "A native FreeCAD GUI is required")
class TestBeamSectionForcesGui(unittest.TestCase):
    def setUp(self):
        previous = App.activeDocument()
        self.previous_document = previous.Name if previous is not None else None
        self.previous_analysis = FemGui.getActiveAnalysis()
        workbench = Gui.activeWorkbench()
        self.previous_workbench = workbench.name() if workbench is not None else None
        self.previous_window_visible = Gui.getMainWindow().isVisible()
        self.previous_window_state = Gui.getMainWindow().windowState()
        self.general = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/General")
        self.overwrite_key = "OverwriteSolverWorkingDirectory"
        self.overwrite_value = self.general.GetBool(self.overwrite_key, True)
        self.overwrite_present = self.general.GetBool(
            self.overwrite_key, True
        ) == self.general.GetBool(self.overwrite_key, False)
        self.ccx_preferences = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/Ccx")
        self.cpu_key = "AnalysisNumCPUs"
        self.cpu_value = self.ccx_preferences.GetInt(self.cpu_key, 1)
        self.cpu_present = self.ccx_preferences.GetInt(
            self.cpu_key, 1
        ) == self.ccx_preferences.GetInt(self.cpu_key, 2)
        self.doc = None
        self.own_edit = False
        self.temporary = None
        self.addCleanup(self._restore_session)
        self._drain_deferred_deletes()
        Gui.showMainWindow()
        Gui.getMainWindow().showNormal()
        self._pump_until(
            lambda: Gui.getMainWindow().isVisible() and not Gui.getMainWindow().isMinimized(),
            10,
            "Native FreeCAD main window did not become visible",
        )
        Gui.activateWorkbench("FemWorkbench")
        self.general.SetBool(self.overwrite_key, False)
        self.ccx_preferences.SetInt(self.cpu_key, 2)
        retained = os.environ.get("B960_WITNESS_ROOT")
        if retained:
            self.directory = Path(retained) / self._testMethodName
            self.directory.mkdir()
        else:
            self.temporary = tempfile.TemporaryDirectory(prefix="freecad-beam-gui-")
            self.directory = Path(self.temporary.name)
        self.doc = App.newDocument("BeamSectionForcesGui")
        setup_cantilever_base_edge(self.doc)
        self.analysis = self.doc.Analysis
        self.solver = self.doc.CalculiXCcxTools
        self.solver.BeamSectionForces = True
        self.solver.Output3d = False
        self.solver.NativeAccountingSolver = os.environ.get(
            "B960_TEST_SOLVER", solver_binary(self.solver)
        )
        self.solver.WorkingDir = str(self.directory)
        # Apply a native 100 N axial load; never edit the generated input deck.
        self.doc.LoadLine.X1 = self.doc.LoadLine.Y1 = self.doc.LoadLine.Z1 = 0
        self.doc.LoadLine.X2 = 1
        self.doc.LoadLine.Y2 = self.doc.LoadLine.Z2 = 0
        self.doc.Force.Force = "100 N"
        self.doc.recompute()

    @staticmethod
    def _drain_deferred_deletes():
        # Complete MDI deletion before action updates encounter a camera-less
        # view after closing the test document.
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)

    def _pump_until(self, predicate, timeout, message):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            QtWidgets.QApplication.processEvents(QtCore.QEventLoop.AllEvents, 25)
            Gui.updateGui()
            if predicate():
                return
            QtCore.QThread.msleep(10)
        self.fail(message)

    @staticmethod
    def _visible_buttons(name):
        return [
            button
            for button in Gui.getMainWindow().findChildren(QtWidgets.QPushButton, name)
            if button.isVisible()
        ]

    def _button(self, name):
        buttons = self._visible_buttons(name)
        self.assertEqual(len(buttons), 1, "Expected one visible native solver button: " + name)
        return buttons[0]

    def _restore_session(self):
        try:
            if self.doc is not None and self.doc.Name in App.listDocuments():
                if self.own_edit:
                    # Cancel only this test's task through its public Stop
                    # action; the task panel owns and synchronously reaps it.
                    for button in self._visible_buttons("pb_run_ccx"):
                        if button.text() == "Stop CalculiX":
                            button.click()
                            self._pump_until(
                                lambda: button.text() != "Stop CalculiX",
                                10,
                                "Native beam solver did not finish cancellation",
                            )
                    Gui.getDocument(self.doc.Name).resetEdit()
                FemGui.setActiveAnalysis()
                App.closeDocument(self.doc.Name)
        finally:
            self._drain_deferred_deletes()
            if self.temporary is not None:
                self.temporary.cleanup()
            if self.overwrite_present:
                self.general.SetBool(self.overwrite_key, self.overwrite_value)
            else:
                self.general.RemBool(self.overwrite_key)
            if self.cpu_present:
                self.ccx_preferences.SetInt(self.cpu_key, self.cpu_value)
            else:
                self.ccx_preferences.RemInt(self.cpu_key)
            if self.previous_document in App.listDocuments():
                App.setActiveDocument(self.previous_document)
            if (
                self.previous_analysis is not None
                and self.previous_analysis.Document.Name in App.listDocuments()
            ):
                FemGui.setActiveAnalysis(self.previous_analysis)
            if self.previous_workbench is not None:
                Gui.activateWorkbench(self.previous_workbench)
            Gui.getMainWindow().setWindowState(self.previous_window_state)
            if not self.previous_window_visible:
                Gui.getMainWindow().hide()

    def test_stop_button_cancels_only_its_owned_beam_attempt(self):
        FemGui.setActiveAnalysis(self.analysis)
        self.assertTrue(Gui.activeDocument().setEdit(self.solver.Name))
        self.own_edit = True
        Gui.Control.showTaskView()
        self._pump_until(
            lambda: len(self._visible_buttons("pb_write_inp")) == 1,
            10,
            "Native solver Write button did not become visible",
        )
        self._button("pb_write_inp").click()
        run = self._button("pb_run_ccx")
        self.assertTrue(run.isEnabled())
        # Two immediate native clicks exercise Starting as well as Running,
        # without waiting for this deliberately small solver case to finish.
        run.click()
        run.click()
        self._pump_until(
            lambda: run.text() != "Stop CalculiX",
            10,
            "Owned beam attempt did not finish cancellation",
        )
        requests = [
            path
            for path in self.directory.glob("*.beam-section.run-*")
            if len(path.name.rsplit(".run-", 1)[-1]) == 32
        ]
        self.assertEqual(len(requests), 1, "The Stop click must not start another child")
        self.assertFalse(
            any(
                getattr(getattr(obj, "Proxy", None), "Type", "") == "Fem::BeamSectionForceResult"
                and obj.Status.startswith("Current")
                for obj in self.analysis.Group
            )
        )

    def test_invalid_output_request_reports_error_and_clears_busy_cursor(self):
        self.addCleanup(QtWidgets.QApplication.restoreOverrideCursor)
        FemGui.setActiveAnalysis(self.analysis)
        self.assertTrue(Gui.activeDocument().setEdit(self.solver.Name))
        self.own_edit = True
        Gui.Control.showTaskView()
        self._pump_until(
            lambda: len(self._visible_buttons("pb_write_inp")) == 1,
            10,
            "Native solver Write button did not become visible",
        )
        self._button("pb_write_inp").click()
        self.assertTrue(self._button("pb_run_ccx").isEnabled())
        self.solver.Output3d = True
        self._button("pb_write_inp").click()
        QtWidgets.QApplication.processEvents()
        self.assertIsNone(QtWidgets.QApplication.overrideCursor())
        self.assertFalse(self._button("pb_run_ccx").isEnabled())
        self.assertFalse(self._button("pb_edit_inp").isEnabled())
        output = [
            item
            for item in Gui.getMainWindow().findChildren(QtWidgets.QTextEdit, "textEdit_Output")
            if item.isVisible()
        ]
        self.assertEqual(len(output), 1)
        self.assertIn("Output3d=False", output[0].toPlainText())

    def test_visible_solver_write_and_run_saves_current_native_beam_end_actions(self):
        FemGui.setActiveAnalysis(self.analysis)
        self.assertTrue(Gui.activeDocument().setEdit(self.solver.Name))
        self.own_edit = True
        Gui.Control.showTaskView()
        self._pump_until(
            lambda: len(self._visible_buttons("pb_write_inp")) == 1
            and len(self._visible_buttons("pb_run_ccx")) == 1,
            10,
            "Native solver buttons did not become visible in the Tasks pane",
        )
        write = self._button("pb_write_inp")
        self.assertTrue(write.isEnabled())
        write.click()
        self._pump_until(
            lambda: self._button("pb_run_ccx").isEnabled(),
            20,
            "Native solver task did not finish writing beam input",
        )
        self._button("pb_run_ccx").click()
        completed = {}

        def current_result_is_available():
            results = [
                obj
                for obj in self.analysis.Group
                if getattr(getattr(obj, "Proxy", None), "Type", "") == "Fem::BeamSectionForceResult"
                and obj.Status.startswith("Current")
            ]
            if len(results) != 1:
                return False
            try:
                data = results[0].Proxy.getSectionForces(results[0])
            except ValueError:
                return False
            completed.update(result=results[0], data=data)
            return True

        self._pump_until(
            current_result_is_available,
            20,
            "Visible native solver run did not publish a qualified beam-end result",
        )
        result, data = completed["result"], completed["data"]
        self.assertTrue(result.CompletedRun)
        self.assertEqual(data["schema"], "CCX_BEAM_SECTION_V1")
        self.assertEqual(data["units"], {"length": "mm", "force": "N", "moment": "N*mm"})
        self.assertEqual(len(data["frames"][-1]["samples"]), 10)
        roots = [
            row
            for row in data["frames"][-1]["samples"]
            if (row["element"], row["node"], row["end"]) == (1, 1, 1)
        ]
        self.assertEqual(len(roots), 1)
        self.assertLessEqual(
            (App.Vector(*roots[0]["force_global"]) - App.Vector(-100, 0, 0)).Length / 100,
            0.01,
        )
        Gui.getDocument(self.doc.Name).resetEdit()
        self.own_edit = False
        literal, digest = result.SectionData, result.SectionHash
        if os.environ.get("B960_WITNESS_ROOT"):
            (self.directory / "saved-output.json").write_text(literal)
        saved = self.directory / "native-beam-gui.FCStd"
        self.doc.recompute()
        self.doc.saveAs(str(saved))
        self.assertTrue(saved.is_file())
        self.assertTrue(result.Status.startswith("Current"), result.Status)
        self.assertEqual(result.SectionData, literal)
        self.assertEqual(result.SectionHash, digest)
        self.assertEqual(result.Proxy.getSectionForces(result), data)
        # The ordinary result double-click must provide a readable inspector.
        self.assertTrue(callable(getattr(result.ViewObject.Proxy, "doubleClicked", None)))
        inspected = {}

        def inspect_visible_dialog():
            try:
                dialog = Gui.getMainWindow().findChild(
                    QtWidgets.QDialog, "NativeBeamSectionInspector"
                )
                self.assertIsNotNone(dialog)
                table = dialog.findChild(QtWidgets.QTableWidget, "NativeBeamSectionSamples")
                self.assertEqual(table.rowCount(), 10)
                labels = " ".join(label.text() for label in dialog.findChildren(QtWidgets.QLabel))
                self.assertIn("N*mm", labels)
                self.assertIn("Current", labels)
                headers = [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())]
                for name in ("Element", "End", "Section", "Fx (N)", "Mx (N*mm)", "e1", "normal"):
                    self.assertIn(name, headers)
                inspected["rows"] = table.rowCount()
                if os.environ.get("B960_WITNESS_ROOT"):
                    self.assertTrue(dialog.grab().save(str(self.directory / "inspector.png")))
                # A physical load edit must withdraw all displayed Current rows.
                self.doc.Force.Force = "101 N"
                obj = result
                with self.assertRaises(ValueError):
                    obj.Proxy.getSectionForces(obj)
                self.assertEqual(table.rowCount(), 0)
                dialog.accept()
            except Exception as error:
                inspected["error"] = error
                for dialog in Gui.getMainWindow().findChildren(QtWidgets.QDialog):
                    if dialog.objectName() == "NativeBeamSectionInspector":
                        dialog.reject()

        QtCore.QTimer.singleShot(100, inspect_visible_dialog)
        self.assertTrue(result.ViewObject.Proxy.doubleClicked(result.ViewObject))
        if "error" in inspected:
            raise inspected["error"]
        self.assertEqual(inspected.get("rows"), 10)
