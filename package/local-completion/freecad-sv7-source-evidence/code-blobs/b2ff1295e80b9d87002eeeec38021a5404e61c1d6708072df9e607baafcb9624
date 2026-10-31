# SPDX-License-Identifier: LGPL-2.1-or-later
"""Inspect native coupled beam actions through the public result double-click."""

import os
from pathlib import Path
import tempfile
import unittest

import FreeCAD as App

from femtest.app.test_beam_coupling_native import make_series
from femtools.beam_section_forces import require_capability
from femtools.ccxtools import FemToolsCcx
from femtools.force_accounting import solver_binary

if App.GuiUp:
    from PySide import QtCore
    from PySide import QtWidgets

    import FreeCADGui as Gui
    import FemGui


@unittest.skipUnless(App.GuiUp, "A native FreeCAD GUI is required")
class TestBeamCouplingGui(unittest.TestCase):
    def setUp(self):
        previous = App.activeDocument()
        self.previous_document = previous.Name if previous is not None else None
        self.previous_analysis = FemGui.getActiveAnalysis()
        workbench = Gui.activeWorkbench()
        self.previous_workbench = workbench.name() if workbench is not None else None
        window = Gui.getMainWindow()
        self.previous_window_visible = window.isVisible()
        self.previous_window_state = window.windowState()
        self.mdi = window.findChild(QtWidgets.QMdiArea)
        self.previous_mdi_window = self.mdi.activeSubWindow() if self.mdi is not None else None
        self.previous_mdi_state = (
            self.previous_mdi_window.windowState() if self.previous_mdi_window is not None else None
        )
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
        self.temporary = None
        self.addCleanup(self._restore_session)
        self._drain_deferred_deletes()
        Gui.showMainWindow()
        window.showNormal()
        Gui.activateWorkbench("FemWorkbench")
        self.general.SetBool(self.overwrite_key, False)
        self.ccx_preferences.SetInt(self.cpu_key, 2)
        retained = os.environ.get("SV7_WITNESS_ROOT")
        if retained:
            self.directory = Path(retained) / self._testMethodName
            self.directory.mkdir(parents=True)
        else:
            self.temporary = tempfile.TemporaryDirectory(prefix="freecad-beam-coupling-gui-")
            self.directory = Path(self.temporary.name)
        self.doc = App.newDocument("CoupledBeamInspectorGui")
        self.model = make_series(self.doc)
        selected = os.environ.get("SV7_TEST_SOLVER")
        if selected:
            self.model.solver.NativeAccountingSolver = selected
        else:
            selected = solver_binary(self.model.solver)
            try:
                require_capability(selected, coupled=True)
            except (OSError, ValueError) as error:
                self.skipTest("Qualified coupled beam observer required: " + str(error))
            self.model.solver.NativeAccountingSolver = selected
        self.model.solver.WorkingDir = str(self.directory)
        FemGui.setActiveAnalysis(self.model.analysis)
        self.doc.recompute()
        view = Gui.getDocument(self.doc.Name).activeView()
        view.viewAxonometric()
        view.fitAll()
        Gui.updateGui()

    @staticmethod
    def _drain_deferred_deletes():
        # Complete only queued MDI deletion before native action updates try
        # to access the view that belonged to the closed test document.
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)

    def _restore_session(self):
        try:
            if self.doc is not None and self.doc.Name in App.listDocuments():
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
                if self.previous_mdi_window is not None:
                    self.previous_mdi_window.setWindowState(self.previous_mdi_state)
                    if self.mdi is not None:
                        self.mdi.setActiveSubWindow(self.previous_mdi_window)
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

    @staticmethod
    def _headers(table):
        return [table.horizontalHeaderItem(index).text() for index in range(table.columnCount())]

    @staticmethod
    def _text(table, row, column):
        item = table.item(row, column)
        return item.text() if item is not None else ""

    def test_inspector_shows_native_coupled_actions_and_withdraws_after_stiffness_edit(self):
        fea = FemToolsCcx(analysis=self.model.analysis, solver=self.model.solver)
        fea.update_objects()
        fea.setup_working_dir(str(self.directory))
        self.assertFalse(fea.check_prerequisites())
        self.assertFalse(fea.write_inp_file())
        self.assertEqual(fea.ccx_run(), 0, fea.ccx_stdout + fea.ccx_stderr)
        fea.load_results()
        result = next(
            obj
            for obj in self.model.analysis.Group
            if getattr(getattr(obj, "Proxy", None), "Type", "") == "Fem::BeamSectionForceResult"
        )
        data = result.Proxy.getSectionForces(result)
        self.assertEqual(data["schema"], "CCX_BEAM_SECTION_V2")
        self.assertTrue(result.Status.startswith("Current"), result.Status)
        self.assertEqual(len(data["frames"][-1]["samples"]), 10)
        self.assertTrue(callable(getattr(result.ViewObject.Proxy, "doubleClicked", None)))
        existing = {
            id(dialog)
            for dialog in Gui.getMainWindow().findChildren(
                QtWidgets.QDialog, "NativeBeamSectionInspector"
            )
        }
        inspected, timers = {}, []

        def own_dialogs():
            return [
                dialog
                for dialog in Gui.getMainWindow().findChildren(
                    QtWidgets.QDialog, "NativeBeamSectionInspector"
                )
                if id(dialog) not in existing
            ]

        def fail_callback(error):
            inspected.setdefault("error", error)
            for dialog in own_dialogs():
                dialog.reject()

        def check_withdrawal():
            try:
                dialog = inspected["dialog"]
                for table in inspected["tables"]:
                    self.assertEqual(table.rowCount(), 0, table.objectName())
                availability = dialog.findChild(QtWidgets.QLabel, "NativeBeamSectionAvailability")
                self.assertIsNotNone(availability)
                self.assertIn("Unavailable", availability.text())
                frames = dialog.findChild(QtWidgets.QComboBox, "NativeBeamSectionFrames")
                self.assertFalse(frames.isEnabled())
                self.assertFalse(result.Status.startswith("Current"), result.Status)
                inspected["withdrawn"] = True
                if os.environ.get("SV7_WITNESS_ROOT"):
                    self.assertTrue(
                        dialog.grab().save(str(self.directory / "withdrawn-inspector.png"))
                    )
                dialog.accept()
            except Exception as error:
                fail_callback(error)

        def inspect_dialog():
            try:
                dialogs = own_dialogs()
                self.assertEqual(len(dialogs), 1, "Expected one new native result inspector")
                dialog = dialogs[0]
                inspected["dialog"] = dialog
                samples = dialog.findChild(QtWidgets.QTableWidget, "NativeBeamSectionSamples")
                actions = dialog.findChild(QtWidgets.QTableWidget, "NativeCoupledBeamActions")
                supports = dialog.findChild(QtWidgets.QTableWidget, "NativeCoupledBeamSupportDofs")
                self.assertIsNotNone(samples)
                self.assertIsNotNone(
                    actions, "Native coupled source/spring/support table is missing"
                )
                self.assertIsNotNone(supports, "Native support DOF classification table is missing")
                self.assertEqual(samples.rowCount(), 10)
                self.assertEqual(actions.rowCount(), 3)
                self.assertEqual(supports.rowCount(), 8)
                labels = " ".join(label.text() for label in dialog.findChildren(QtWidgets.QLabel))
                self.assertIn("Current", labels)
                self.assertIn("global origin", labels.lower())
                self.assertIn("N*mm", labels)
                action_headers = self._headers(actions)
                for name in (
                    "Action",
                    "Owner",
                    "Fx (N)",
                    "Fy (N)",
                    "Fz (N)",
                    "Mx about origin (N*mm)",
                    "My about origin (N*mm)",
                    "Mz about origin (N*mm)",
                ):
                    self.assertIn(name, action_headers)
                rows = {
                    self._text(actions, row, action_headers.index("Action")).lower(): row
                    for row in range(actions.rowCount())
                }
                self.assertEqual(set(rows), {"source", "spring", "support"})
                for name, owner, force, moment in (
                    ("source", "Force", (10, 0, 0), (0, 300, -200)),
                    ("spring", "GroundSpring", (-10, 0, 0), (0, -300, 200)),
                    ("support", "Stabilizer", (0, 0, 0), (0, 0, 0)),
                ):
                    row = rows[name]
                    self.assertEqual(self._text(actions, row, action_headers.index("Owner")), owner)
                    for axis, expected in zip("xyz", force):
                        self.assertAlmostEqual(
                            float(self._text(actions, row, action_headers.index(f"F{axis} (N)"))),
                            expected,
                            delta=0.001,
                        )
                    for axis, expected in zip("xyz", moment):
                        self.assertAlmostEqual(
                            float(
                                self._text(
                                    actions,
                                    row,
                                    action_headers.index(f"M{axis} about origin (N*mm)"),
                                )
                            ),
                            expected,
                            delta=0.1,
                        )
                support_headers = self._headers(supports)
                self.assertIn("Role", support_headers)
                roles = [
                    self._text(supports, row, support_headers.index("Role"))
                    for row in range(supports.rowCount())
                ]
                self.assertEqual(roles.count("TRANSLATION"), 2)
                self.assertEqual(roles.count("ANGLE"), 3)
                self.assertEqual(roles.count("ALGEBRAIC"), 3)
                inspected["tables"] = (samples, actions, supports)
                inspected["rows"] = (samples.rowCount(), actions.rowCount(), supports.rowCount())
                if os.environ.get("SV7_WITNESS_ROOT"):
                    self.assertTrue(dialog.grab().save(str(self.directory / "inspector.png")))
                # A physical edit must withdraw every displayed Current table
                # through the inspector's own periodic public-result validation.
                self.model.connector.Stiffness = "2001 N/mm"
                self.doc.recompute()
                withdrawal_timer.start(1000)
            except Exception as error:
                fail_callback(error)

        inspection_timer = QtCore.QTimer()
        inspection_timer.setSingleShot(True)
        inspection_timer.timeout.connect(inspect_dialog)
        withdrawal_timer = QtCore.QTimer()
        withdrawal_timer.setSingleShot(True)
        withdrawal_timer.timeout.connect(check_withdrawal)
        watchdog = QtCore.QTimer()
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(
            lambda: fail_callback(AssertionError("Native coupled beam inspector timed out"))
        )
        timers.extend((inspection_timer, withdrawal_timer, watchdog))
        inspection_timer.start(100)
        watchdog.start(15000)
        try:
            self.assertTrue(result.ViewObject.Proxy.doubleClicked(result.ViewObject))
        finally:
            for timer in timers:
                timer.stop()
            for dialog in own_dialogs():
                dialog.reject()
        if "error" in inspected:
            raise inspected["error"]
        self.assertEqual(inspected.get("rows"), (10, 3, 8))
        self.assertTrue(
            inspected.get("withdrawn"), "A physical spring edit left Current rows visible"
        )
