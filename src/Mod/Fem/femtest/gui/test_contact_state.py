# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native solver task-panel and local-contact inspection qualification."""

import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path

import FreeCAD as App

import ObjectsFem

from femtest.app import test_contact_state_native as native_contact
from femtools.femutils import is_of_type

if App.GuiUp:
    from PySide import QtCore
    from PySide import QtWidgets

    import FreeCADGui as Gui
    import FemGui


@unittest.skipUnless(
    App.GuiUp and shutil.which("gmsh"), "A native FreeCAD GUI and Gmsh are required"
)
class TestContactStateGui(unittest.TestCase):
    def setUp(self):
        previous = App.activeDocument()
        self.previous_document = previous.Name if previous is not None else None
        self.previous_analysis = FemGui.getActiveAnalysis()
        workbench = Gui.activeWorkbench()
        self.previous_workbench = workbench.name() if workbench is not None else None
        self.previous_window_visible = Gui.getMainWindow().isVisible()
        self.previous_window_state = Gui.getMainWindow().windowState()
        self.preferences = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/General")
        self.overwrite_key = "OverwriteSolverWorkingDirectory"
        self.overwrite_value = self.preferences.GetBool(self.overwrite_key, True)
        self.overwrite_present = self.preferences.GetBool(
            self.overwrite_key, True
        ) == self.preferences.GetBool(self.overwrite_key, False)
        self.fixture = None
        self.addCleanup(self._restore_session)
        self._drain_deferred_deletes()
        # Native -t startup can create the GUI without showing its window.
        # Exercise the public visible workflow, never hidden child controls.
        Gui.showMainWindow()
        Gui.getMainWindow().showNormal()
        self._pump_until(
            lambda: Gui.getMainWindow().isVisible() and not Gui.getMainWindow().isMinimized(),
            10,
            "Native FreeCAD main window did not become visible",
        )
        Gui.activateWorkbench("FemWorkbench")
        self.preferences.SetBool(self.overwrite_key, False)
        # Import the module, not its TestCase into this module's discovery
        # namespace. The helper uses ordinary author/write/solve interfaces.
        self.fixture = native_contact.TestContactStateNative()
        self.fixture.setUp()
        self.model = self.fixture.make_case()

    @staticmethod
    def _drain_deferred_deletes():
        # Closing a native document clears its 3D camera before the MDI
        # widget's deferred deletion. Finish that teardown without dispatching
        # action-update timers against a camera-less, not-yet-deleted view.
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

    def _visible_buttons(self, name):
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
        # Only public task/GUI actions are used, including cancellation if a
        # bounded solver wait failed. Never leave an owned solver child running.
        try:
            for button in Gui.getMainWindow().findChildren(QtWidgets.QPushButton, "pb_run_ccx"):
                if button.isVisible() and button.text() == "Stop CalculiX":
                    button.click()
                    self._pump_until(
                        lambda: button.text() != "Stop CalculiX",
                        10,
                        "Native solver did not finish cancellation",
                    )
            if self.fixture is not None and hasattr(self.fixture, "doc"):
                name = self.fixture.doc.Name
                if name in App.listDocuments():
                    Gui.getDocument(name).resetEdit()
                FemGui.setActiveAnalysis()
                self.fixture.tearDown()
        finally:
            self._drain_deferred_deletes()
            if self.overwrite_present:
                self.preferences.SetBool(self.overwrite_key, self.overwrite_value)
            else:
                self.preferences.RemBool(self.overwrite_key)
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

    def test_native_gui_run_imports_fresh_state_and_withdraws_open_inspector(self):
        self._check_native_gui_run_and_inspector(with_accounting=False)

    def test_dual_opt_in_gui_run_preserves_accounting_and_saved_observation(self):
        self._check_native_gui_run_and_inspector(with_accounting=True)

    def test_retargeted_selected_solver_withdraws_open_inspector_without_frame_change(self):
        self._check_native_gui_run_and_inspector(with_accounting=False, retarget_solver=True)

    def test_retargeted_solver_directory_withdraws_open_inspector_without_frame_change(self):
        self._check_native_gui_run_and_inspector(with_accounting=False, retarget_directory=True)

    def _check_native_gui_run_and_inspector(
        self, with_accounting, retarget_solver=False, retarget_directory=False
    ):
        model = self.model
        old_token = model.data["provenance"]["run"]["token"]
        previous_frd = Path(model.fea.inp_file_name).with_suffix(".frd")
        previous_frd_inode = previous_frd.stat().st_ino
        if retarget_solver or retarget_directory:
            original_binary = Path(model.data["provenance"]["binary"])
            # A sibling private selection directory is not already watched as
            # a deck/request/output/binary parent. Neither test can pass merely
            # because another bound source shares the retargeted link's parent.
            selection_directory = Path(
                tempfile.mkdtemp(
                    prefix="freecad-contact-state-selection-", dir=self.fixture.directory.parent
                )
            )
            if retarget_directory:
                original_directory = selection_directory / "original"
                original_directory.mkdir()
                (original_directory / "ccx").symlink_to(original_binary)
                replacement = selection_directory / "replacement"
                replacement.mkdir()
                shutil.copy2(original_binary, replacement / "ccx")
                selected_link = selection_directory / "current"
                selected_link.symlink_to(original_directory, target_is_directory=True)
                selected_solver = selected_link / "ccx"
            else:
                replacement = selection_directory / "replacement-solver"
                shutil.copy2(original_binary, replacement)
                selected_link = selection_directory / "selected-solver"
                selected_link.symlink_to(original_binary)
                selected_solver = selected_link
            model.solver.NativeAccountingSolver = str(selected_solver)
        if with_accounting:
            model.solver.NativeForceAccounting = True
            # Only the ordinary zero-motion support is external. The moving
            # right-hand prescribed displacement is deliberately not selected.
            model.solver.NativeAccountingSupports = [self.fixture.doc.getObject("Fixed")]
        FemGui.setActiveAnalysis(model.analysis)
        model.solver.WorkingDir = str(self.fixture.directory)
        self.fixture.doc.recompute()
        self.assertTrue(Gui.activeDocument().setEdit(model.solver.Name))
        Gui.Control.showTaskView()
        self._pump_until(
            lambda: len(self._visible_buttons("pb_write_inp")) == 1
            and len(self._visible_buttons("pb_run_ccx")) == 1,
            10,
            "Native solver task buttons did not become visible in the Tasks pane",
        )
        write = self._button("pb_write_inp")
        self.assertTrue(write.isEnabled())
        write.click()
        self._pump_until(
            lambda: self._button("pb_run_ccx").isEnabled(),
            30,
            "Native task panel did not finish writing the input",
        )
        self.assertFalse(model.result.Status.startswith("Current"), model.result.Status)
        with self.assertRaises(ValueError):
            model.result.Proxy.getContactStates(model.result)
        self._button("pb_run_ccx").click()
        completed = {}

        def fresh_result_is_available():
            current = [
                result
                for result in model.analysis.Group
                if is_of_type(result, "Fem::ContactStateResult")
                and result.Status.startswith("Current")
            ]
            if len(current) != 1:
                return False
            try:
                data = current[0].Proxy.getContactStates(current[0])
            except ValueError:
                return False
            if data["provenance"]["run"]["token"] == old_token:
                return False
            completed.update(result=current[0], data=data)
            return True

        self._pump_until(
            fresh_result_is_available,
            90,
            "Native GUI run did not import a fresh, qualified local-contact result",
        )
        result = completed["result"]
        data = completed["data"]
        self.assertNotEqual(data["provenance"]["run"]["token"], old_token)
        self.assertTrue(result.CompletedRun)
        self.assertTrue(data["frames"][-1]["samples"])
        self.assertTrue(any(row["state"] == "STICK" for row in data["frames"][-1]["samples"]))
        if retarget_solver or retarget_directory:
            source = data["provenance"]
            watched_source_parents = {
                Path(source[key]).parent for key in ("deck", "request_path", "output", "binary")
            } | {Path(source["run"]["path"]).parent}
            self.assertNotIn(selection_directory.resolve(), watched_source_parents)
        accounting = None
        observation = None
        if with_accounting:
            current = [
                item
                for item in model.analysis.Group
                if is_of_type(item, "Fem::NativeForceAccountingResult")
                and item.Status.startswith("Current")
            ]
            self.assertEqual(len(current), 1, "Expected fresh native GUI force accounting")
            accounting = current[0]
            metadata = json.loads(accounting.AccountingData)
            self.assertEqual(metadata["schema"], "CCX_FORCE_ACCOUNTING_V3")
            source = metadata["movement_source"]
            self.assertEqual(source["status"], "BOUND", source)
            self.assertEqual(source["deck"], data["provenance"]["deck"])
            self.assertEqual(source["deck_sha256"], data["provenance"]["deck_sha256"])
            self.assertEqual(source["binary_sha256"], data["provenance"]["binary_sha256"])
            self.assertEqual(Path(source["path"]), previous_frd.resolve())
            # The actual GUI child owns a new FRD, while the earlier fixture's
            # literal source remains recoverable, not relabelled as fresh.
            self.assertEqual(Path(source["recovery_path"]).stat().st_ino, previous_frd_inode)
            self.assertNotEqual(Path(source["path"]).stat().st_ino, previous_frd_inode)
            self.assertTrue(accounting.Resultants)
            accounting_literal = accounting.AccountingData
            resultants = list(accounting.Resultants)
            observation = ObjectsFem.makeResultContactObservation(
                self.fixture.doc, model.analysis, accounting, [model.contact]
            )
            observation.Proxy.refresh(observation)
            report = observation.Proxy.getObservations(observation)
            self.assertEqual(report["status"], "AVAILABLE", observation.Status)
            observation_literal = observation.ObservationData
            observation_hash = observation.ObservationHash
            self.fixture.doc.recompute()
            self.fixture.doc.saveAs(str(self.fixture.directory / "native-contact-gui.FCStd"))
            self.assertEqual(observation.Proxy.getObservations(observation), report)
        Gui.getDocument(self.fixture.doc.Name).resetEdit()
        Gui.updateGui()
        outcome = {}

        def inspect_and_edit_native_contact():
            dialog = QtWidgets.QApplication.activeModalWidget()
            if dialog is None:
                visible = [
                    widget
                    for widget in QtWidgets.QApplication.topLevelWidgets()
                    if isinstance(widget, QtWidgets.QDialog)
                    and widget.objectName() == "NativeContactStateInspector"
                ]
                dialog = visible[0] if len(visible) == 1 else None
            try:
                self.assertIsInstance(dialog, QtWidgets.QDialog)
                self.assertEqual(dialog.objectName(), "NativeContactStateInspector")
                table = dialog.findChild(QtWidgets.QTableWidget, "NativeContactStateSamples")
                frames = dialog.findChild(QtWidgets.QComboBox, "NativeContactStateFrames")
                status = dialog.findChild(QtWidgets.QLabel, "NativeContactStateAvailability")
                self.assertIsNotNone(table)
                self.assertIsNotNone(frames)
                self.assertIsNotNone(status)
                self.assertGreater(table.rowCount(), 0)
                self.assertEqual(table.editTriggers(), QtWidgets.QAbstractItemView.NoEditTriggers)
                headers = [
                    table.horizontalHeaderItem(column).text()
                    for column in range(table.columnCount())
                ]
                self.assertEqual(table.item(0, headers.index("contact")).text(), model.contact.Name)
                self.assertGreater(float(table.item(0, headers.index("pressure")).text()), 0)
                selected_frame = frames.currentIndex()
                if retarget_solver or retarget_directory:
                    selected_link.unlink()
                    selected_link.symlink_to(replacement, target_is_directory=retarget_directory)
                    self.assertTrue(original_binary.is_file())
                    if retarget_directory:
                        self.assertEqual(
                            (original_directory / "ccx").resolve(strict=True), original_binary
                        )
                else:
                    model.contact.FrictionCoefficient = 0.31
                    self.fixture.doc.recompute()
                # Deliver actual QFileSystemWatcher/native model events. Do
                # not touch the frame selector or call the qualified getter.
                self._pump_until(
                    lambda: table.rowCount() == 0 and not frames.isEnabled(),
                    10,
                    "The native inspector retained values after source withdrawal",
                )
                self.assertEqual(table.rowCount(), 0)
                self.assertFalse(frames.isEnabled())
                self.assertEqual(frames.currentIndex(), selected_frame)
                self.assertTrue(status.text().startswith("Unavailable:"), status.text())
                outcome["checked"] = True
            except Exception as error:
                outcome["error"] = error
            finally:
                if isinstance(dialog, QtWidgets.QDialog):
                    dialog.accept()

        timer = QtCore.QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(inspect_and_edit_native_contact)
        timer.start(0)
        try:
            self.assertTrue(result.ViewObject.Proxy.doubleClicked(result.ViewObject))
        finally:
            timer.stop()
            timer.timeout.disconnect(inspect_and_edit_native_contact)
            timer.deleteLater()
            self._drain_deferred_deletes()
        if "error" in outcome:
            raise outcome["error"]
        self.assertTrue(outcome.get("checked"), "The native inspector callback did not run")
        with self.assertRaises(ValueError):
            result.Proxy.getContactStates(result)
        self.assertFalse(result.Status.startswith("Current"), result.Status)
        if with_accounting:
            self.assertFalse(accounting.Status.startswith("Current"), accounting.Status)
            self.assertEqual(accounting.AccountingData, accounting_literal)
            self.assertEqual(list(accounting.Resultants), resultants)
            self.assertEqual(observation.ObservationData, observation_literal)
            self.assertEqual(observation.ObservationHash, observation_hash)
            with self.assertRaises(ValueError):
                observation.Proxy.getObservations(observation)
