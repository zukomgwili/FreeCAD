# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the FreeCAD project.

import unittest
from unittest.mock import patch

import FreeCAD as App
import FreeCADGui as Gui
import Arch
from PySide import QtCore, QtGui
from bimcommands import BimViews


class _DocumentEvents:
    def __init__(self, document):
        self.document = document
        self.reset()

    def reset(self):
        self.transactions = []
        self.recomputes = 0
        self.changes = []

    def slotOpenTransaction(self, document, name):
        if document == self.document:
            self.transactions.append(name)

    def slotRecomputedDocument(self, document):
        if document == self.document:
            self.recomputes += 1

    def slotChangedObject(self, obj, prop):
        if obj.Document == self.document:
            self.changes.append((obj.Name, prop))


@unittest.skipUnless(App.GuiUp, "Views Manager requires the GUI")
class TestBimViewsGui(unittest.TestCase):
    def setUp(self):
        self.document = App.newDocument("BimViewsRefreshTest")
        self.building = Arch.makeBuildingPart(name="Building")
        self.building.IfcType = "Building"
        self.level = Arch.makeBuildingPart(name="Level")
        self.level.IfcType = "Building Storey"
        self.level.Height = 3000
        self.building.Group = [self.level]
        self.document.recompute()
        self.widget = QtGui.QDockWidget(Gui.getMainWindow())
        contents = QtGui.QWidget()
        layout = QtGui.QVBoxLayout(contents)
        self.widget.tree = QtGui.QTreeWidget()
        self.widget.tree.setColumnCount(3)
        self.widget.viewtree = QtGui.QTreeWidget()
        layout.addWidget(self.widget.tree)
        layout.addWidget(self.widget.viewtree)
        self.widget.setWidget(contents)
        self.widget.show()
        self.manager = BimViews.BIM_Views()
        self.manager.oldData = [[], []]
        self.manager.allItemsInTree = []
        self.widget.tree.itemChanged.connect(self.manager.editObject)
        self.locator = patch.object(BimViews, "findWidget", return_value=self.widget)
        self.locator.start()
        self.events = _DocumentEvents(self.document)
        App.addDocumentObserver(self.events)
        self.color_present = any(
            row[1] == "TreeActiveColor"
            for row in (
                App.ParamGet("User parameter:BaseApp/Preferences/TreeView").GetContents() or []
            )
        )
        self.old_color = App.ParamGet("User parameter:BaseApp/Preferences/TreeView").GetUnsigned(
            "TreeActiveColor", 0
        )

    def tearDown(self):
        App.removeDocumentObserver(self.events)
        Gui.Selection.clearSelection()
        Gui.activeDocument().activeView().setActiveObject("Arch", None)
        color_params = App.ParamGet("User parameter:BaseApp/Preferences/TreeView")
        if self.color_present:
            color_params.SetUnsigned("TreeActiveColor", self.old_color)
        else:
            color_params.RemUnsigned("TreeActiveColor")
        self.locator.stop()
        self.widget.close()
        self.widget.deleteLater()
        App.closeDocument(self.document.Name)

    def refresh(self):
        self.manager.update(retrigger=False)

    def assertNoDocumentEdits(self):
        self.assertEqual(self.events.transactions, [])
        self.assertEqual(self.events.recomputes, 0)
        self.assertEqual(self.events.changes, [])

    def levelItem(self):
        return next(
            item
            for item in BimViews.getAllItemsInTree(self.widget.tree)
            if item.toolTip(0) == self.level.Name
        )

    def testInitialAndIdleRefresh(self):
        self.refresh()
        self.assertNoDocumentEdits()
        self.assertEqual(self.levelItem().text(0), self.level.Label)
        for _ in range(3):
            self.refresh()
        self.assertNoDocumentEdits()

    def testSelectionAndActiveHighlight(self):
        self.refresh()
        self.events.reset()
        App.ParamGet("User parameter:BaseApp/Preferences/TreeView").SetUnsigned(
            "TreeActiveColor", 0xFF0000FF
        )
        Gui.Selection.addSelection(self.level)
        Gui.activeDocument().activeView().setActiveObject("Arch", self.level)
        self.events.reset()
        self.refresh()
        self.assertTrue(self.levelItem().isSelected())
        self.assertTrue(self.levelItem().font(0).bold())
        self.assertEqual(self.levelItem().background(0).color(), QtGui.QColor("red"))
        self.assertNoDocumentEdits()
        Gui.Selection.clearSelection()
        Gui.activeDocument().activeView().setActiveObject("Arch", None)
        self.events.reset()
        self.refresh()
        self.assertFalse(self.levelItem().isSelected())
        self.assertFalse(self.levelItem().font(0).bold())
        self.assertNoDocumentEdits()

    def testSignalStateRestoredAfterFailure(self):
        import Draft

        self.widget.viewtree.blockSignals(True)
        with patch.object(Draft, "getType", side_effect=RuntimeError("refresh failure")):
            with self.assertRaisesRegex(RuntimeError, "refresh failure"):
                self.refresh()
        self.assertFalse(self.widget.tree.signalsBlocked())
        self.assertTrue(self.widget.viewtree.signalsBlocked())
        self.assertNoDocumentEdits()

    def testActualEditsStillRecompute(self):
        self.refresh()
        for column, text in ((0, "Renamed level"), (1, "1200 mm"), (2, "3500 mm")):
            self.events.reset()
            self.levelItem().setText(column, text)
            self.assertEqual(self.events.transactions, ["Edit level"])
            self.assertEqual(self.events.recomputes, 1)
            if column == 0:
                self.assertEqual(self.level.Label, text)
            elif column == 1:
                self.assertAlmostEqual(self.level.Placement.Base.z, 1200)
            else:
                self.assertAlmostEqual(self.level.Height.Value, 3500)
            self.events.reset()
            self.refresh()
            self.assertNoDocumentEdits()
