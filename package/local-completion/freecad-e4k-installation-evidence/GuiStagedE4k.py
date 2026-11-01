# SPDX-License-Identifier: LGPL-2.1-or-later
"""One real native property-editor/task-panel staged-gravity GUI qualification.

Only the root runs this helper. It does not call the fixture's solve method:
input writing, the native child and ordinary result import use the visible
stock solver task buttons. Frozen statics remain in the native fixture.
"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
from types import SimpleNamespace
import unittest

sys.dont_write_bytecode = True

import FreeCAD as App

if App.GuiUp:
    from PySide import QtCore
    from PySide import QtWidgets

    import FreeCADGui as Gui
    import FemGui


from femtest.app import test_staged_selfweight_native as native_fixture
import AppStagedE4k as app_checks
SOURCE = Path(native_fixture.__file__).resolve(strict=True)
assert SOURCE == app_checks.RESOURCES/'Mod/Fem/femtest/app/test_staged_selfweight_native.py'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class TestE4kGui(unittest.TestCase):
    def setUp(self):
        app_checks.check_identity(self)
        self.assertTrue(App.GuiUp, "A real native FreeCAD GUI is required")
        self.assertIsNotNone(shutil.which("gmsh"), "Native Gmsh is required; never skip")
        self.output = Path(os.environ["E4K_RUN"])
        previous = App.activeDocument()
        self.previous_document = previous.Name if previous is not None else None
        self.previous_analysis = FemGui.getActiveAnalysis()
        workbench = Gui.activeWorkbench()
        self.previous_workbench = workbench.name() if workbench is not None else None
        window = Gui.getMainWindow()
        self.previous_window_visible = window.isVisible()
        self.previous_window_state = window.windowState()
        self.previous_window_size = window.size()
        self.preferences = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/General")
        self.overwrite_key = "OverwriteSolverWorkingDirectory"
        self.overwrite_value = self.preferences.GetBool(self.overwrite_key, True)
        self.overwrite_present = self.preferences.GetBool(
            self.overwrite_key, True
        ) == self.preferences.GetBool(self.overwrite_key, False)
        self.fixture = None
        self.addCleanup(self._restore_session)
        self._drain_deferred_deletes()
        Gui.showMainWindow()
        window.showNormal()
        window.resize(1440, 1000)
        self._pump_until(
            lambda: window.isVisible() and not window.isMinimized(),
            10,
            "Native main window did not become visible",
        )
        Gui.activateWorkbench("FemWorkbench")
        self.preferences.SetBool(self.overwrite_key, False)
        # Keep the helper class inside the imported module; unittest discovery
        # in this module must contain exactly our single GUI TestCase/test.
        self.fixture = native_fixture.TestStagedSelfweightNative()
        self.fixture.setUp()
        self.model = self.fixture.make_case(source="pressure")
        self.model.solver.TimePeriod = "0.4 s"
        self.model.solver.StaticStepAmplitude = "Ramp"
        self.run_directory = self.output / "native-task-run"
        self.run_directory.mkdir()
        self.model.solver.WorkingDir = str(self.run_directory)
        self.fixture.doc.recompute()
        for obj in self.fixture.doc.Objects:
            if obj.TypeId == "Part::Reverse":
                obj.ViewObject.Visibility = False
        self.model.geometry.ViewObject.Visibility = True
        self.model.mesh.ViewObject.Visibility = False
        Gui.activeDocument().activeView().viewAxonometric()
        Gui.activeDocument().activeView().fitAll()
        FemGui.setActiveAnalysis(self.model.analysis)

    @staticmethod
    def _drain_deferred_deletes():
        # Complete native MDI teardown before an action-update timer can use
        # a view whose document close already removed its camera.
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

    def _screenshot(self, name):
        Gui.updateGui()
        self.assertTrue(Gui.getMainWindow().grab().save(str(self.output / name)))

    def _restore_session(self):
        try:
            for button in Gui.getMainWindow().findChildren(QtWidgets.QPushButton, "pb_run_ccx"):
                if button.isVisible() and button.text() == "Stop CalculiX":
                    button.click()
                    self._pump_until(
                        lambda: button.text() != "Stop CalculiX",
                        15,
                        "Native solver did not complete cancellation",
                    )
            if self.fixture is not None and hasattr(self.fixture, "doc"):
                name = self.fixture.doc.Name
                if name in App.listDocuments():
                    Gui.getDocument(name).resetEdit()
                    Gui.Selection.clearSelection()
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
            Gui.getMainWindow().resize(self.previous_window_size)
            Gui.getMainWindow().setWindowState(self.previous_window_state)
            if not self.previous_window_visible:
                Gui.getMainWindow().hide()

    @staticmethod
    def _property_indexes(model, parent=QtCore.QModelIndex()):
        found = []
        for row in range(model.rowCount(parent)):
            index = model.index(row, 0, parent)
            found.append(index)
            found.extend(TestE4kGui._property_indexes(model, index))
        return found

    def _activate_visible_step_property(self):
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.model.solver)
        window = Gui.getMainWindow()
        editor = window.findChild(QtWidgets.QTreeView, "propertyEditorData")
        self.assertIsNotNone(editor, "Native Data property editor is missing")
        parent = editor.parentWidget()
        while parent is not None:
            if isinstance(parent, QtWidgets.QDockWidget):
                parent.show()
                window.resizeDocks([parent], [480], QtCore.Qt.Horizontal)
            parent = parent.parentWidget()
        tabs = window.findChild(QtWidgets.QTabWidget, "propertyTab")
        self.assertIsNotNone(tabs)
        self.assertGreaterEqual(tabs.indexOf(editor), 0)
        tabs.setCurrentIndex(tabs.indexOf(editor))
        self._pump_until(
            lambda: editor.isVisible() and editor.model().rowCount() > 0,
            10,
            "Selected solver did not populate the visible Data property editor",
        )
        editor.expandAll()
        editor.setColumnWidth(0, 270)
        model = editor.model()
        indexes = self._property_indexes(model)
        labels = [str(model.data(index, QtCore.Qt.DisplayRole)) for index in indexes]
        matches = [
            index
            for index in indexes
            if "".join(
                char.lower()
                for char in str(model.data(index, QtCore.Qt.DisplayRole))
                if char.isalnum()
            )
            == "staticstepamplitude"
        ]
        self.assertEqual(len(matches), 1, labels)
        index = model.index(matches[0].row(), 1, matches[0].parent())
        self.assertTrue(bool(model.flags(index) & QtCore.Qt.ItemIsEditable))
        editor.scrollTo(index)
        editor.setCurrentIndex(index)
        # Follow the native property editor's own visible activation route,
        # including its persistent editor and transaction lifetime.
        editor.clicked.emit(index)

        def combos():
            return [
                combo
                for combo in editor.findChildren(QtWidgets.QComboBox)
                if combo.isVisible()
                and [combo.itemText(i) for i in range(combo.count())] == ["Ramp", "Step"]
            ]

        self._pump_until(lambda: len(combos()) == 1, 10, "Visible Ramp/Step editor did not open")
        combo = combos()[0]
        choices = [combo.itemText(i) for i in range(combo.count())]
        self.assertEqual(combo.currentText(), "Ramp")
        self._screenshot("solver-property-editor-ramp.png")
        step_index = combo.findText("Step")
        self.assertGreaterEqual(step_index, 0)
        # Activate the real visible native enum widget and its standard user
        # activation signal; no document assignment implements the selection.
        combo.setCurrentIndex(step_index)
        combo.activated[int].emit(step_index)
        self._pump_until(
            lambda: self.model.solver.StaticStepAmplitude == "Step",
            10,
            "Native property editor did not commit the selected Step enum",
        )
        self.fixture.doc.recompute()
        self._screenshot("solver-property-editor-step.png")
        return {"property_labels": labels, "visible_choices": choices, "committed": "Step"}

    def test_visible_step_property_and_stock_solver_buttons_qualify_current_equilibrium(self):
        property_receipt = self._activate_visible_step_property()
        self.assertTrue(Gui.activeDocument().setEdit(self.model.solver.Name))
        Gui.Control.showTaskView()
        self._pump_until(
            lambda: len(self._visible_buttons("pb_write_inp")) == 1
            and len(self._visible_buttons("pb_run_ccx")) == 1,
            10,
            "Native stock solver task buttons did not become visible",
        )
        write = self._button("pb_write_inp")
        self.assertTrue(write.isEnabled())
        self._screenshot("native-solver-panel-before-write.png")
        write.click()
        self._pump_until(
            lambda: self._button("pb_run_ccx").isEnabled()
            and len(list(self.run_directory.glob("*.contact-state.json"))) == 1,
            60,
            "Stock GUI Write did not publish a qualified native deck/request",
        )
        export = json.loads(next(self.run_directory.glob("*.contact-state.json")).read_text())
        deck = Path(export["deck"])
        self.assertEqual(deck.parent, self.run_directory.resolve())
        deck_text = deck.read_text()
        self.assertEqual(deck_text.count("*STEP,"), 1)
        self.assertIn("AMPLITUDE=STEP", deck_text)
        self.assertIn("Eall,GRAV,9806.65,0,0,-1", deck_text)
        self.assertIn("\n".join(native_fixture.HISTORY), deck_text)
        self.assertIn(f"*DLOAD, AMPLITUDE={self.model.load.Name}", deck_text)
        written_hash = sha(deck)
        self.assertEqual(written_hash, export["deck_sha256"])
        self._screenshot("native-solver-panel-before-run.png")
        self._button("pb_run_ccx").click()
        completed = {}

        def imported_current_and_mechanical_results():
            accounting = [
                obj
                for obj in self.model.analysis.Group
                if getattr(getattr(obj, "Proxy", None), "Type", "")
                == "Fem::NativeForceAccountingResult"
                and obj.Status.startswith("Current")
            ]
            contacts = [
                obj
                for obj in self.model.analysis.Group
                if getattr(getattr(obj, "Proxy", None), "Type", "") == "Fem::ContactStateResult"
                and obj.Status.startswith("Current")
            ]
            mechanical = [
                obj
                for obj in self.model.analysis.Group
                if obj.isDerivedFrom("Fem::FemResultObject")
            ]
            if len(accounting) != 1 or len(contacts) != 1 or not mechanical:
                return False
            try:
                contact = contacts[0].Proxy.getContactStates(contacts[0])
            except ValueError:
                return False
            completed.update(
                accounting=accounting[0],
                data=json.loads(accounting[0].AccountingData),
                observation=contacts[0],
                contact=contact,
                mechanical=mechanical,
            )
            return True

        self._pump_until(
            imported_current_and_mechanical_results,
            180,
            "Stock GUI Run did not finish native current observations and ordinary result import",
        )
        self.assertNotEqual(self._button("pb_run_ccx").text(), "Stop CalculiX")
        self.assertEqual(sha(deck), written_hash, "The actual executed stock deck changed")
        data = completed["data"]
        contact = completed["contact"]
        self.assertTrue(completed["observation"].CompletedRun)
        for name in ("model_digest", "deck_sha256", "binary_sha256"):
            self.assertEqual(data[name], contact["provenance"][name])
        frame = contact["frames"][-1]
        state = deck.with_suffix(".accounting.out").read_text().splitlines()[1].split()
        self.assertEqual(state[0], "STATE")
        self.assertEqual((int(state[1]), int(state[2])), (frame["step"], frame["increment"]))
        self.assertAlmostEqual(float(state[3]), 0.4, delta=1e-10)
        self.assertAlmostEqual(frame["time"], 0.4, delta=1e-10)
        active = [row for row in frame["samples"] if row["availability"] == "ACTIVE"]
        self.assertTrue(active)
        self.assertTrue(all(row["state"] == "STICK" and row["pressure"] > 0 for row in active))
        for mechanical in completed["mechanical"]:
            self.assertTrue(mechanical.NodeNumbers)
        run = SimpleNamespace(**completed, folder=self.run_directory)
        # Uses the independent frozen .4s +10N reference and exact same
        # component/near-zero limits as command-line native qualification.
        self.fixture.check_endpoint(self.model, run, 1)
        self._screenshot("native-solver-panel-completed.png")
        Gui.getDocument(self.fixture.doc.Name).resetEdit()
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(completed["accounting"])
        Gui.activeDocument().activeView().viewAxonometric()
        Gui.activeDocument().activeView().fitAll()
        self._screenshot("native-staged-results.png")
        self.fixture.doc.recompute()
        saved = self.output / "native-staged-gui.FCStd"
        self.fixture.doc.saveAs(str(saved))
        receipt = {
            "passed": True,
            "test_count": 1,
            "skips": 0,
            "fixture_source": str(SOURCE),
            "fixture_source_sha256": sha(SOURCE),
            "gui_helper_sha256": sha(__file__),
            "visible_property_editor": property_receipt,
            "native_routes": ["pb_write_inp.click", "pb_run_ccx.click", "stock result import"],
            "deck": str(deck),
            "deck_sha256": written_hash,
            "executed_deck_unchanged": True,
            "binary": data["binary"],
            "binary_sha256": data["binary_sha256"],
            "physical_state": {"step": frame["step"], "increment": frame["increment"], "time": frame["time"]},
            "accounting_name": completed["accounting"].Name,
            "contact_name": completed["observation"].Name,
            "mechanical_result_names": [obj.Name for obj in completed["mechanical"]],
            "fixed_oracle_endpoint_s": 0.4,
            "fixed_oracle_Q_factor": 1,
            "source_and_current_frame_bound": True,
            "saved": str(saved),
            "not_engineering_acceptance": True,
        }
        (self.output / "gui-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


def _original_single_suite():
    return unittest.TestSuite(
        [
            TestE4kGui(
                "test_visible_step_property_and_stock_solver_buttons_qualify_current_equilibrium"
            )
        ]
    )


def load_tests(_loader, _tests, _pattern):
    return app_checks.VerifiedSuite([TestE4kGui('test_visible_step_property_and_stock_solver_buttons_qualify_current_equilibrium')])
