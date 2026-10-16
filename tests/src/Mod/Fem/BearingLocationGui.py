# SPDX-License-Identifier: LGPL-2.1-or-later

"""Native bearing distance/location persistence probe on synthetic geometry.

Set FREECAD_3R2_OUTPUT to a new directory and run in the GUI. Run again in an
independent GUI process with FREECAD_3R2_REOPEN pointing to the first
native-bearing-location.FCStd. The cold process checks stored link ownership
and the saved base point before any explicit recompute, then changes the datum
occurrence and the common parent placement without reassigning References.
No building document or engineering design data is used.
"""

import json
import os
from pathlib import Path
import unittest
from zipfile import ZipFile

import FreeCAD as App
import FreeCADGui as Gui
import Fem
import ObjectsFem
import Part

from PySide import QtCore
from PySide import QtGui


@unittest.skipUnless(App.GuiUp, "Requires native GUI to preserve view providers")
class BearingLocationGui(unittest.TestCase):
    tolerance = 1e-7

    @staticmethod
    def vector_values(value):
        return [value.x, value.y, value.z]

    def assert_vector(self, actual, expected):
        self.assertLess((actual - expected).Length, self.tolerance,
                        (self.vector_values(actual), self.vector_values(expected)))

    @staticmethod
    def create_model(doc):
        cylinder = doc.addObject("Part::Cylinder", "SeatSource")
        cylinder.Radius = 7
        cylinder.Height = 11
        datum = doc.addObject("Part::Box", "DatumSource")
        datum.Length = datum.Width = 20
        datum.Height = 2
        seat = doc.addObject("App::Link", "SeatOccurrence")
        seat.setLink(cylinder)
        plane = doc.addObject("App::Link", "DatumOccurrence")
        plane.setLink(datum)
        plane.Placement.Base = App.Vector(-10, -10, 17)
        parent = doc.addObject("App::Part", "Parent")
        parent.Placement = App.Placement(App.Vector(80, 90, 100),
                                         App.Rotation(App.Vector(0, 1, 0), 90))
        parent.addObject(seat)
        parent.addObject(plane)
        doc.recompute()
        bearing = ObjectsFem.makeConstraintBearing(doc, "Bearing")
        bearing.References = [(seat, ["Face1"])]
        bearing.Location = (plane, ["Face5"])
        bearing.Dist = 2
        doc.recompute()

    def assert_bearing(self, doc, local_z, distance=2):
        bearing = doc.getObject("Bearing")
        seat = doc.getObject("SeatOccurrence")
        plane = doc.getObject("DatumOccurrence")
        parent = doc.getObject("Parent")
        self.assertEqual(seat.TypeId, "App::Link")
        self.assertEqual(plane.TypeId, "App::Link")
        self.assertEqual(seat.LinkedObject, doc.getObject("SeatSource"))
        self.assertEqual(plane.LinkedObject, doc.getObject("DatumSource"))
        self.assertEqual(list(parent.Group), [seat, plane])
        self.assertEqual(len(bearing.References), 1)
        self.assertEqual(bearing.References[0][0], seat)
        self.assertEqual(list(bearing.References[0][1]), ["Face1"])
        self.assertEqual(bearing.Location[0], plane)
        self.assertEqual(list(bearing.Location[1]), ["Face5"])
        self.assertAlmostEqual(bearing.Dist, distance)
        self.assertAlmostEqual(bearing.Radius, 7)
        self.assertAlmostEqual(bearing.Height, 11)
        self.assertEqual(bearing.ViewObject.TypeId,
                         "FemGui::ViewProviderFemConstraintBearing")
        expected = parent.Placement.multVec(App.Vector(0, 0, local_z))
        self.assert_vector(bearing.BasePoint, expected)
        # Preserve the native cylinder parameterization qualified by the direct
        # References-path control; do not infer a new axis from the face normal.
        expected_axis = parent.Placement.Rotation.multVec(App.Vector(0, 0, -1))
        self.assert_vector(bearing.Axis, expected_axis)
        return {
            "reference_owner": seat.Name,
            "reference_owner_type": seat.TypeId,
            "reference_subelements": list(bearing.References[0][1]),
            "location_owner": plane.Name,
            "location_owner_type": plane.TypeId,
            "location_subelements": list(bearing.Location[1]),
            "distance_mm": bearing.Dist,
            "radius_mm": bearing.Radius,
            "height_mm": bearing.Height,
            "base_point": self.vector_values(bearing.BasePoint),
            "expected_base_point": self.vector_values(expected),
            "axis": self.vector_values(bearing.Axis),
            "expected_axis": self.vector_values(expected_axis),
            "view_provider_type": bearing.ViewObject.TypeId,
        }

    def edit_native_distance(self, doc):
        gui_doc = Gui.activeDocument()
        self.assertTrue(gui_doc.setEdit("Bearing"))
        try:
            Gui.updateGui()
            spin = Gui.getMainWindow().findChild(QtGui.QDoubleSpinBox, "spinDistance")
            self.assertIsNotNone(spin)
            self.assertAlmostEqual(spin.value(), 2)
            # These are the native widget's valueChanged path. In particular,
            # no References assignment or document recompute repairs its data.
            spin.setValue(-2)
            Gui.updateGui()
            negative = self.assert_bearing(doc, 19, distance=-2)
            spin.setValue(2)
            Gui.updateGui()
            positive = self.assert_bearing(doc, 15)
            return {"negative_distance": negative, "positive_distance": positive}
        finally:
            gui_doc.resetEdit()

    def test_bearing_family_clears_invalid_symbols(self):
        from pivy import coin

        def glyph_shape_count(obj):
            search = coin.SoSearchAction()
            search.setType(coin.SoShape.getClassTypeId(), True)
            search.setInterest(coin.SoSearchAction.ALL)
            search.setSearchingAll(True)
            search.apply(obj.ViewObject.RootNode)
            return search.getPaths().getLength()

        doc = App.newDocument("BearingDerivedSymbolsNative")
        try:
            cylinder = doc.addObject("Part::Cylinder", "Cylinder")
            cylinder.Radius, cylinder.Height = 7, 11
            plane = doc.addObject("Part::Box", "LocationPlane")
            plane.Placement.Base = App.Vector(0, 0, 17)
            doc.recompute()
            for factory in (ObjectsFem.makeConstraintBearing, ObjectsFem.makeConstraintGear,
                            ObjectsFem.makeConstraintPulley):
                with self.subTest(factory=factory.__name__):
                    constraint = factory(doc)
                    constraint.References = [(cylinder, ["Face1"])]
                    constraint.Location = (plane, ["Face5"])
                    constraint.Dist = 2
                    doc.recompute()
                    Gui.updateGui()
                    self.assertNotIn("Invalid", constraint.State)
                    self.assertAlmostEqual(constraint.Radius, 7)
                    self.assertGreater(glyph_shape_count(constraint), 0)

                    constraint.Location = (plane, ["Vertex1"])
                    doc.recompute()
                    Gui.updateGui()
                    self.assertIn("Invalid", constraint.State)
                    self.assertEqual(constraint.Radius, 0)
                    self.assertEqual(glyph_shape_count(constraint), 0,
                                     "Invalid Location must remove the inherited glyph")

                    constraint.Location = (plane, ["Face5"])
                    doc.recompute()
                    Gui.updateGui()
                    self.assertNotIn("Invalid", constraint.State)
                    self.assertAlmostEqual(constraint.Radius, 7)
                    self.assertGreater(glyph_shape_count(constraint), 0)

                    constraint.References = []
                    doc.recompute()
                    Gui.updateGui()
                    self.assertEqual(constraint.Radius, 0)
                    self.assertEqual(glyph_shape_count(constraint), 0,
                                     "Cleared References must remove the inherited glyph")
        finally:
            App.closeDocument(doc.Name)

    def test_native_distance_location_and_fresh_process_placement(self):
        root = Path(os.environ["FREECAD_3R2_OUTPUT"])
        root.mkdir(parents=True, exist_ok=False)
        reopen = os.environ.get("FREECAD_3R2_REOPEN")
        doc = None
        try:
            doc = App.openDocument(reopen) if reopen else App.newDocument("BearingLocationNative")
            if not reopen:
                self.create_model(doc)
            # No explicit recompute, property assignment or task-panel opening
            # precedes the cold-process check of the serialized constraint.
            initial = self.assert_bearing(doc, 15)
            Gui.activateWorkbench("FemWorkbench")
            live_widget = self.edit_native_distance(doc)
            saved = self.assert_bearing(doc, 15)
            moves = {}
            if reopen:
                doc.getObject("DatumOccurrence").Placement.Base = App.Vector(-10, -10, 23)
                doc.recompute()
                moves["location_occurrence"] = self.assert_bearing(doc, 21)
                doc.getObject("Parent").Placement = App.Placement(
                    App.Vector(-25, 45, 60), App.Rotation(App.Vector(1, 0, 0), 90))
                doc.recompute()
                saved = self.assert_bearing(doc, 21)
                moves["common_parent"] = saved
                self.assertNotEqual(initial["base_point"], saved["base_point"])
                self.assertNotEqual(initial["axis"], saved["axis"])
            for name in ("SeatSource", "DatumSource"):
                doc.getObject(name).ViewObject.Visibility = False
            for name in ("Parent", "SeatOccurrence", "DatumOccurrence", "Bearing"):
                doc.getObject(name).ViewObject.Visibility = True
            Gui.Selection.clearSelection()
            Gui.activeDocument().activeView().viewAxonometric()
            Gui.activeDocument().activeView().fitAll()
            Gui.updateGui()
            loop = QtCore.QEventLoop()
            QtCore.QTimer.singleShot(250, loop.quit)
            loop.exec()
            Gui.activeDocument().activeView().saveImage(
                str(root / "native-bearing-view.png"), 1000, 700, "White")
            filename = root / "native-bearing-location.FCStd"
            doc.saveAs(str(filename))
            with ZipFile(filename) as archive:
                self.assertIn("GuiDocument.xml", archive.namelist())
            self.assertTrue(Gui.getMainWindow().grab().save(
                str(root / "native-bearing-location.png")))
            (root / "report.json").write_text(json.dumps({
                "runtime": App.Version(),
                "gui_up": App.GuiUp,
                "loaded_modules": {
                    "Fem": Fem.__file__,
                    "ObjectsFem": ObjectsFem.__file__,
                    "Part": Part.__file__,
                    "FreeCADGui": getattr(Gui, "__file__", None),
                },
                "fresh_process_reopen": bool(reopen),
                "restored_before_explicit_recompute": bool(reopen),
                "initial_bearing": initial,
                "native_distance_widget": live_widget,
                "placement_changes": moves,
                "saved_bearing": saved,
                "native_gui_document_preserved": True,
                "references_reassigned_after_creation": False,
                "geometry_selected_in_test": False,
                "synthetic_geometry_only": True,
                "building_design_accepted": False,
            }, indent=2))
        finally:
            Gui.Selection.clearSelection()
            if doc:
                App.closeDocument(doc.Name)
