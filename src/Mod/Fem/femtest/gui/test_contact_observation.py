# SPDX-License-Identifier: LGPL-2.1-or-later

"""Saved contact-side observation command and property-editor workflow."""

import tempfile
import unittest
from pathlib import Path

import FreeCAD as App


@unittest.skipUnless(App.GuiUp, "A native FreeCAD GUI session is required")
class TestContactObservationGui(unittest.TestCase):
    def setUp(self):
        import FemGui
        import FreeCADGui as Gui
        import ObjectsFem
        from femtools import force_accounting

        self.previous_document = App.ActiveDocument
        self.previous_analysis = FemGui.getActiveAnalysis()
        workbench = Gui.activeWorkbench()
        self.previous_workbench = workbench.name() if workbench is not None else None
        Gui.activateWorkbench("FemWorkbench")
        self.document = App.newDocument("ContactObservationGui")
        self.analysis = ObjectsFem.makeAnalysis(self.document)
        FemGui.setActiveAnalysis(self.analysis)
        self.mesh = self.document.addObject("Fem::FemMeshObject", "OriginalMesh")
        self.analysis.addObject(self.mesh)
        self.source = force_accounting.make_result(self.analysis)
        self.contacts = [
            self.document.addObject("Fem::ConstraintContact", name)
            for name in ("ContactA", "ContactB")
        ]
        for contact in self.contacts:
            self.analysis.addObject(contact)
        self.directory = tempfile.TemporaryDirectory(prefix="freecad-contact-observation-gui-")
        Gui.Selection.clearSelection()

    def tearDown(self):
        import FemGui
        import FreeCADGui as Gui

        Gui.Selection.clearSelection()
        FemGui.setActiveAnalysis()
        App.closeDocument(self.document.Name)
        if self.previous_document is not None:
            App.setActiveDocument(self.previous_document.Name)
        if self.previous_analysis is not None:
            FemGui.setActiveAnalysis(self.previous_analysis)
        if self.previous_workbench is not None:
            Gui.activateWorkbench(self.previous_workbench)
        self.directory.cleanup()

    def create_from_selection(self, selected):
        import FreeCADGui as Gui

        self.assertTrue(
            "FEM_ResultContactObservation" in Gui.listCommands(),
            "The native FEM contact-side observation command is missing",
        )
        Gui.Selection.clearSelection()
        for obj in selected:
            Gui.Selection.addSelection(obj)
        before = set(self.document.Objects)
        Gui.Command.update()
        self.assertTrue(Gui.Command.get("FEM_ResultContactObservation").isActive())
        Gui.runCommand("FEM_ResultContactObservation")
        results = [
            obj
            for obj in self.document.Objects
            if obj not in before
            and getattr(getattr(obj, "Proxy", None), "Type", None) == "Fem::ContactSideObservation"
        ]
        self.assertEqual(len(results), 1)
        return results[0]

    def test_command_is_registered_in_the_native_fem_workbench(self):
        import FreeCADGui as Gui
        from PySide import QtGui, QtWidgets

        self.assertTrue(
            "FEM_ResultContactObservation" in Gui.listCommands(),
            "The native FEM contact-side observation command is missing",
        )
        Gui.updateGui()
        actions = Gui.Command.get("FEM_ResultContactObservation").getAction()
        self.assertEqual(len(actions), 1)
        title = App.Qt.translate("Workbench", "&Results").replace("&", "")
        menus = [
            action.menu()
            for action in Gui.getMainWindow().menuBar().actions()
            if action.menu() and action.text().replace("&", "") == title
        ]
        self.assertEqual(len(menus), 1)
        self.assertIn(actions[0], menus[0].actions())
        self.assertTrue(
            any(
                actions[0] in toolbar.actions()
                for toolbar in Gui.getMainWindow().findChildren(QtWidgets.QToolBar)
            )
        )
        self.assertFalse(QtGui.QIcon(":/icons/FEM_PostFilterDataAtPoint.svg").isNull())

    def test_selected_source_contacts_and_editable_native_links(self):
        result = self.create_from_selection([self.source, *self.contacts])
        self.assertEqual(result.TypeId, "App::FeaturePython")
        self.assertEqual(result.Analysis, self.analysis)
        self.assertEqual(result.AccountingResult, self.source)
        self.assertEqual(result.Mesh, self.mesh)
        self.assertEqual(list(result.Contacts), self.contacts)
        self.assertIn(result, self.analysis.Group)
        for name in ("Analysis", "Mesh", "AccountingResult", "Contacts", "SlaveVertex"):
            self.assertNotIn("ReadOnly", result.getEditorMode(name), name)
            self.assertNotIn("Hidden", result.getEditorMode(name), name)
        result.Contacts = self.contacts[:1]
        result.SlaveVertex = 2
        self.assertEqual(list(result.Contacts), self.contacts[:1])
        self.assertEqual(result.SlaveVertex, 2)
        self.assertTrue(result.Status.startswith("Stale"))
        with self.assertRaises(ValueError):
            result.Proxy.getObservations(result)

    def test_missing_or_ambiguous_selected_source_is_not_guessed(self):
        from femtools import force_accounting

        # One existing source is not permission to choose it when unselected.
        result = self.create_from_selection(self.contacts)
        self.assertIsNone(result.AccountingResult)
        other = force_accounting.make_result(self.analysis)
        result = self.create_from_selection([self.source, other, *self.contacts])
        self.assertIsNone(result.AccountingResult)
        self.assertEqual(list(result.Contacts), self.contacts)
        self.assertFalse(result.Status.startswith("Available"))

    def test_context_refresh_and_cold_restore_keep_unavailable_history_explicit(self):
        from PySide import QtWidgets

        result = self.create_from_selection([self.source, *self.contacts])
        menu = QtWidgets.QMenu()
        result.ViewObject.Proxy.setupContextMenu(result.ViewObject, menu)
        self.assertEqual(len(menu.actions()), 1)
        menu.actions()[0].trigger()
        self.assertTrue(result.Status.startswith("Unavailable"), result.Status)
        before = result.ObservationData, result.ObservationHash
        name = result.Name
        path = Path(self.directory.name) / "ContactObservation.FCStd"
        self.document.saveAs(str(path))
        App.closeDocument(self.document.Name)
        self.document = App.openDocument(str(path))
        result = self.document.getObject(name)
        self.assertEqual(result.Proxy.Type, "Fem::ContactSideObservation")
        self.assertTrue(result.Status.startswith("Historical"), result.Status)
        self.assertEqual((result.ObservationData, result.ObservationHash), before)
        self.document.recompute()
        self.assertTrue(result.Status.startswith("Historical"), result.Status)
        self.assertEqual((result.ObservationData, result.ObservationHash), before)
        with self.assertRaises(ValueError):
            result.Proxy.getObservations(result)
