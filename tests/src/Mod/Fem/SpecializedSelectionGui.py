# SPDX-License-Identifier: LGPL-2.1-or-later

"""Native specialized-panel selections on disposable geometry, not solver acceptance.

Run with FreeCAD -P tests/src/Mod/Fem -t SpecializedSelectionGui.
Set FREECAD_S78_DOCUMENT to save the occurrence-selection fixture; run again
with FREECAD_S78_REOPEN pointing to it to check serialized owners cold.
"""

import os
import unittest

import FreeCAD as App
import FreeCADGui as Gui
import FemGui
import ObjectsFem
from PySide import QtCore, QtGui


@unittest.skipUnless(App.GuiUp, "Requires native task panels")
class SpecializedSelectionGui(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("SpecializedSelection")
        self.analysis = ObjectsFem.makeAnalysis(self.doc)
        FemGui.setActiveAnalysis(self.analysis)
        self.cylinder = self.doc.addObject("Part::Cylinder", "Source")
        self.cylinder.Radius, self.cylinder.Height = 7, 11
        self.box = self.doc.addObject("Part::Box", "Datum")
        self.link = self.doc.addObject("App::Link", "Occurrence")
        self.link.setLink(self.cylinder)
        self.plane = self.doc.addObject("App::Link", "DatumOccurrence")
        self.plane.setLink(self.box)
        self.plane.Placement.Base = App.Vector(-5, -5, 17)
        self.parent = self.doc.addObject("App::Part", "Parent")
        self.parent.Placement = App.Placement(
            App.Vector(80, 90, 100), App.Rotation(App.Vector(0, 1, 0), 90))
        self.parent.addObject(self.link)
        self.parent.addObject(self.plane)
        self.doc.recompute()
        Gui.activateWorkbench("FemWorkbench")
        self.warnings = []
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.dismiss_warning)
        self.timer.start(50)

    def dismiss_warning(self):
        for widget in QtGui.QApplication.topLevelWidgets():
            if isinstance(widget, QtGui.QMessageBox):
                self.warnings.append(widget.text())
                widget.accept()

    def tearDown(self):
        self.timer.stop()
        Gui.activeDocument().resetEdit()
        Gui.Selection.clearSelection()
        App.closeDocument(self.doc.Name)

    def button(self, name):
        widget = Gui.getMainWindow().findChild(QtGui.QAbstractButton, name)
        self.assertIsNotNone(widget, name)
        widget.click()
        Gui.updateGui()

    def edit(self, kind):
        obj = getattr(ObjectsFem, "makeConstraint" + kind)(self.doc, kind)
        self.analysis.addObject(obj)
        self.assertTrue(Gui.activeDocument().setEdit(obj.Name))
        Gui.updateGui()
        return obj

    def select(self, owner, sub="Face1"):
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, owner.Name, sub)
        Gui.updateGui()

    def assert_geometry(self, obj):
        self.assertEqual(obj.References[0][0], self.link)
        self.assertEqual(list(obj.References[0][1]), ["Face1"])
        self.assertEqual(obj.Location[0], self.plane)
        self.assertAlmostEqual(obj.Radius, 7)
        self.assertAlmostEqual(obj.Height, 11)
        expected = self.parent.Placement.multVec(App.Vector(0, 0, 17))
        self.assertLess((obj.BasePoint - expected).Length, 1e-7)
        axis = self.parent.Placement.Rotation.multVec(App.Vector(0, 0, -1))
        self.assertLess((obj.Axis - axis).Length, 1e-7)
        self.assertNotIn("Invalid", obj.State)

    def test_bearing_family_occurrence_selection(self):
        for kind in ("Bearing", "Gear", "Pulley"):
            with self.subTest(kind=kind):
                obj = self.edit(kind)
                self.doc.openTransaction("Select occurrence references")
                # Exercise the native selection callback, not References assignment.
                self.select(self.link)
                self.assertEqual(obj.References[0][0], self.link)
                self.button("buttonLocation")
                self.select(self.plane, "Face5")
                self.assert_geometry(obj)
                Gui.activeDocument().resetEdit()
                self.doc.commitTransaction()
                self.doc.undo()
                self.assertEqual(obj.References, [])
                self.doc.redo()
                self.doc.recompute()
                self.assert_geometry(obj)
        self.assertEqual(self.warnings, [])
        filename = os.environ.get("FREECAD_S78_DOCUMENT")
        if filename:
            self.doc.recompute()
            self.doc.saveAs(filename)

    def test_direction_link_rejection_and_direct_control(self):
        for kind in ("Gear", "Pulley"):
            with self.subTest(kind=kind):
                obj = self.edit(kind)
                self.button("buttonDirection")
                self.select(self.plane, "Face5")
                self.assertTrue(self.warnings)
                self.assertIsNone(obj.Direction)
                self.warnings.clear()
                self.select(self.box, "Face5")
                self.assertEqual(obj.Direction[0], self.box)
                self.assertEqual(self.warnings, [])
                Gui.activeDocument().resetEdit()

    def test_bearing_rejects_unresolvable_and_wrong_topology(self):
        obj = self.edit("Bearing")
        empty = self.doc.addObject("App::FeaturePython", "NotGeometry")
        self.select(empty)
        self.assertTrue(self.warnings)
        self.assertEqual(obj.References, [])
        self.warnings.clear()
        self.select(self.link, "Vertex1")
        self.assertTrue(self.warnings)
        self.assertEqual(obj.References, [])
        self.warnings.clear()
        self.select(self.link)
        self.assertEqual(obj.References[0][0], self.link)
        self.assertEqual(self.warnings, [])

    def test_guarded_panels_reject_link(self):
        for kind in ("PlaneRotation", "Transform", "FluidBoundary"):
            with self.subTest(kind=kind):
                if kind == "Transform":
                    force = ObjectsFem.makeConstraintForce(self.doc)
                    force.References = [(self.box, ["Face5"])]
                    self.analysis.addObject(force)
                obj = self.edit(kind)
                if kind == "FluidBoundary":
                    self.select(self.plane, "Face5")
                    # Direction is a one-shot selection consumer, not an observer.
                    button = Gui.getMainWindow().findChild(
                        QtGui.QAbstractButton, "buttonDirection")
                    self.assertIsNotNone(button)
                    # Default wall subtype disables this button. Choose inlet velocity.
                    combo = Gui.getMainWindow().findChild(QtGui.QComboBox, "comboBoundaryType")
                    combo.setCurrentText("inlet")
                    subtype = Gui.getMainWindow().findChild(QtGui.QComboBox, "comboSubtype")
                    subtype.setCurrentText("uniformVelocity")
                    self.assertTrue(button.isEnabled())
                    self.button("buttonDirection")
                else:
                    self.select(self.plane, "Face5")
                    self.button("btnAdd")
                self.assertTrue(self.warnings, kind)
                self.assertEqual(obj.References, [])
                self.warnings.clear()
                self.select(self.box, "Face5")
                if kind == "FluidBoundary":
                    self.button("buttonDirection")
                    self.assertEqual(obj.Direction[0], self.box)
                else:
                    self.button("btnAdd")
                    self.assertEqual(obj.References[0][0], self.box)
                self.assertEqual(self.warnings, [])
                Gui.activeDocument().resetEdit()

    def test_cold_reopen(self):
        filename = os.environ.get("FREECAD_S78_REOPEN")
        if not filename:
            self.skipTest("No saved occurrence fixture supplied")
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(filename)
        self.link = self.doc.getObject("Occurrence")
        self.plane = self.doc.getObject("DatumOccurrence")
        self.parent = self.doc.getObject("Parent")
        for kind in ("Bearing", "Gear", "Pulley"):
            self.assert_geometry(self.doc.getObject(kind))
        self.parent.Placement.Base = App.Vector(-30, 20, 60)
        self.doc.recompute()
        for kind in ("Bearing", "Gear", "Pulley"):
            self.assert_geometry(self.doc.getObject(kind))
