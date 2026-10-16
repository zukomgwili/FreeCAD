# SPDX-License-Identifier: LGPL-2.1-or-later

"""Opt-in native App::Link constraint persistence and placement regression.

Set FREECAD_6JM_OUTPUT to a new directory and run this test in the GUI. Run
again in an independent GUI process with FREECAD_6JM_REOPEN pointing to the
first native-constraint-links.FCStd. The reopen checks stored reference and
symbol geometry before any explicit recompute, then relocates both the link
and its parent and verifies that regenerated symbols follow that occurrence.
Only synthetic geometry is used; this is not a building-design acceptance.
"""

import json
import os
from pathlib import Path
import unittest
from zipfile import ZipFile
from PySide import QtCore

import FreeCAD as App
import FreeCADGui as Gui
import Fem
import ObjectsFem
import Part


@unittest.skipUnless(App.GuiUp, "Requires native GUI to preserve view providers")
class ConstraintLinksGui(unittest.TestCase):
    tolerance = 1e-7

    @staticmethod
    def vector_values(value):
        return [value.x, value.y, value.z]

    def assert_vector(self, actual, expected):
        self.assertLess((actual - expected).Length, self.tolerance,
                        (self.vector_values(actual), self.vector_values(expected)))

    @staticmethod
    def world_face(link, parent):
        # getSubObject includes the occurrence placement, but not the parent
        # geometry-group placement. Keep the expected face independent of the
        # constraint's own calculated normal and point properties.
        face = link.getSubObject("Face1")
        face.transformShape(parent.Placement.toMatrix())
        return face

    def assert_symbols(self, doc, expected_normal):
        source = doc.getObject("Source")
        link = doc.getObject("Occurrence")
        parent = doc.getObject("Parent")
        constraint = doc.getObject("RigidBody")
        self.assertEqual(link.TypeId, "App::Link")
        self.assertEqual(link.LinkedObject, source)
        self.assertEqual(list(parent.Group), [link])
        references = constraint.References
        self.assertEqual(len(references), 1)
        self.assertEqual(references[0][0], link)
        self.assertEqual(list(references[0][1]), ["Face1"])
        self.assertEqual(constraint.ViewObject.TypeId,
                         "FemGui::ViewProviderFemConstraintRigidBody")
        self.assertIsNotNone(Gui.activeDocument().getObject(constraint.Name))
        face = self.world_face(link, parent)
        self.assert_vector(face.normalAt(0, 0), expected_normal)
        self.assert_vector(constraint.NormalDirection, expected_normal)
        self.assertTrue(constraint.Points)
        self.assertEqual(len(constraint.Points), len(constraint.Normals))
        for point, normal in zip(constraint.Points, constraint.Normals):
            self.assertLess(Part.Vertex(point).distToShape(face)[0], self.tolerance)
            self.assert_vector(normal, expected_normal)
        return {
            "reference_owner": references[0][0].Name,
            "reference_owner_type": references[0][0].TypeId,
            "subelements": list(references[0][1]),
            "view_provider_type": constraint.ViewObject.TypeId,
            "normal_direction": self.vector_values(constraint.NormalDirection),
            "expected_world_normal": self.vector_values(expected_normal),
            "world_face_center": self.vector_values(face.CenterOfMass),
            "points": [self.vector_values(point) for point in constraint.Points],
            "normals": [self.vector_values(normal) for normal in constraint.Normals],
        }

    @staticmethod
    def create_model(doc):
        source = doc.addObject("Part::Box", "Source")
        source.Length, source.Width, source.Height = 20, 30, 40
        link = doc.addObject("App::Link", "Occurrence")
        link.setLink(source)
        link.Placement = App.Placement(App.Vector(11, 13, 17),
                                       App.Rotation(App.Vector(0, 0, 1), 90))
        parent = doc.addObject("App::Part", "Parent")
        parent.Placement = App.Placement(App.Vector(80, 90, 100),
                                         App.Rotation(App.Vector(1, 0, 0), 90))
        parent.addObject(link)
        doc.recompute()
        constraint = ObjectsFem.makeConstraintRigidBody(doc, "RigidBody")
        constraint.References = [(link, ["Face1"])]
        doc.recompute()

    def test_native_fresh_process_link_owner_and_symbol_regeneration(self):
        root = Path(os.environ["FREECAD_6JM_OUTPUT"])
        root.mkdir(parents=True, exist_ok=False)
        reopen = os.environ.get("FREECAD_6JM_REOPEN")
        doc = None
        try:
            doc = App.openDocument(reopen) if reopen else App.newDocument("ConstraintLinksNative")
            if not reopen:
                self.create_model(doc)
            # In the cold process nothing above this assertion explicitly
            # recomputes or reassigns References to repair loaded state.
            initial = self.assert_symbols(doc, App.Vector(0, 0, -1))
            saved = initial
            if reopen:
                link = doc.getObject("Occurrence")
                parent = doc.getObject("Parent")
                link.Placement = App.Placement(App.Vector(-30, 20, 60),
                                               App.Rotation(App.Vector(0, 1, 0), 90))
                parent.Placement = App.Placement(App.Vector(150, -80, 35),
                                                 App.Rotation(App.Vector(0, 0, 1), 90))
                doc.recompute()
                saved = self.assert_symbols(doc, App.Vector(0, 0, 1))
                self.assertNotEqual(initial["points"], saved["points"])
                self.assertNotEqual(initial["normal_direction"], saved["normal_direction"])
            doc.getObject("Source").ViewObject.Visibility = False
            doc.getObject("Parent").ViewObject.Visibility = True
            doc.getObject("Occurrence").ViewObject.Visibility = True
            doc.getObject("RigidBody").ViewObject.Visibility = True
            Gui.activateWorkbench("FemWorkbench")
            Gui.activeDocument().activeView().viewAxonometric()
            Gui.activeDocument().activeView().fitAll()
            Gui.updateGui()
            loop = QtCore.QEventLoop()
            QtCore.QTimer.singleShot(250, loop.quit)
            loop.exec()
            Gui.activeDocument().activeView().saveImage(
                str(root / "native-constraint-view.png"), 1000, 700, "White")
            filename = root / "native-constraint-links.FCStd"
            doc.saveAs(str(filename))
            with ZipFile(filename) as archive:
                self.assertIn("GuiDocument.xml", archive.namelist())
            self.assertTrue(Gui.getMainWindow().grab().save(
                str(root / "native-constraint-links.png")))
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
                "initial_symbols": initial,
                "saved_symbols": saved,
                "native_gui_document_preserved": True,
                "synthetic_geometry_only": True,
                "building_design_accepted": False,
            }, indent=2))
        finally:
            if doc:
                App.closeDocument(doc.Name)
