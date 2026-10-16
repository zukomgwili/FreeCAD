# SPDX-License-Identifier: LGPL-2.1-or-later

"""Opt-in native command/undo/persistence checks; no building document."""

import io
import json
import os
from pathlib import Path
import unittest

import FreeCAD as App
import FreeCADGui as Gui
import Fem
import FemGui
import ObjectsFem
import Part

from femtools.elastic_connector import connectors
from femtools.elastic_connector import resolve_connector
from femsolver.calculix.write_constraint_elastic_connector import write_connectors
from types import SimpleNamespace
from PySide import QtCore
from PySide import QtGui


class ElasticConnectorGui(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("ElasticConnectorGui")
        self.analysis = ObjectsFem.makeAnalysis(self.doc)
        FemGui.setActiveAnalysis(self.analysis)
        Gui.activateWorkbench("FemWorkbench")
        self.points = []
        for index in range(3):
            point = self.doc.addObject("Part::Feature", f"Point{index}")
            point.Shape = Part.Vertex(index, 0, 0)
            self.points.append(point)
        self.doc.recompute()
        Gui.Selection.clearSelection()

    def tearDown(self):
        Gui.Selection.clearSelection()
        App.closeDocument(self.doc.Name)

    def create(self, count):
        for point in self.points[:count]:
            Gui.Selection.addSelection(point, "Vertex1")
        Gui.runCommand("FEM_ConstraintElasticConnector")
        return connectors(self.analysis)

    def test_native_command_ground_two_points_and_zero_stiffness(self):
        obj = self.create(1)[0]
        self.assertEqual(obj.Mode, "Ground")
        self.assertEqual(obj.End1[0], self.points[0])
        self.assertEqual(obj.Stiffness.getValueAs("N/mm").Value, 0)
        Gui.Selection.clearSelection()
        other = self.create(2)[-1]
        self.assertEqual(other.Mode, "Two points")
        self.assertEqual(other.End2[0], self.points[1])
        self.assertEqual(Gui.Selection.getSelection(), [other])

    def test_invalid_selection_does_not_create_a_connector(self):
        self.assertEqual(self.create(3), [])
        Gui.Selection.clearSelection()
        edge = self.doc.addObject("Part::Feature", "Edge")
        edge.Shape = Part.makeLine(App.Vector(), App.Vector(1, 0, 0))
        Gui.Selection.addSelection(edge, "Edge1")
        Gui.runCommand("FEM_ConstraintElasticConnector")
        self.assertEqual(connectors(self.analysis), [])

    def test_workbench_exposes_the_connector_action(self):
        actions = Gui.getMainWindow().findChildren(QtGui.QAction)
        self.assertTrue(any(action.text() == "Elastic Connector (CalculiX)"
                            for action in actions))

    def test_native_command_transaction_undo_redo(self):
        self.assertEqual(len(self.create(2)), 1)
        self.doc.undo()
        self.assertEqual(connectors(self.analysis), [])
        self.doc.redo()
        self.assertEqual(len(connectors(self.analysis)), 1)

    def test_native_rigid_ports_command_units_and_cold_persistence(self):
        from femtest.app import test_elastic_connector as app_tests
        helper = app_tests.TestRigidPortConnector()
        helper.doc = self.doc
        self.analysis, _, old, mesh, bodies, _ = helper.model(angle=45)
        self.doc = helper.doc
        self.doc.removeObject(old.Name)
        FemGui.setActiveAnalysis(self.analysis)
        for body in bodies:
            Gui.Selection.addSelection(body)
        Gui.runCommand("FEM_ConstraintElasticConnector")
        obj = connectors(self.analysis)[0]
        self.assertEqual(obj.Attachment, "Rigid body ports")
        self.assertEqual(obj.RigidBody1, bodies[0])
        self.assertEqual(obj.RigidBody2, bodies[1])
        self.doc.undo()
        self.assertEqual(connectors(self.analysis), [])
        self.doc.redo()
        obj = connectors(self.analysis)[0]
        obj.Kind = "Rotational"
        obj.RotationalStiffness = App.Units.Quantity("2 N*m/rad")
        obj.Orientation = App.Rotation(App.Vector(0, 0, 1), 45)
        reopen = os.environ.get("FREECAD_J97_REOPEN")
        if reopen:
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(reopen)
            self.analysis = self.doc.getObject("Analysis")
            mesh = self.doc.getObject("Mesh")
            obj = connectors(self.analysis)[0]
        result = resolve_connector(obj, mesh, self.analysis)
        self.assertAlmostEqual(result["stiffness"], 2000)
        self.assertEqual([len(nodes) for nodes in result["regions"]], [8, 8])
        self.assertTrue(result["rotational"])
        stream = io.StringIO()
        write_connectors(stream, SimpleNamespace(
            analysis=self.analysis, mesh_object=mesh,
            member=SimpleNamespace(cons_elasticconnector=[{"Object": obj}])
        ))
        self.assertIn("*EQUATION", stream.getvalue())
        self.assertIn("TYPE=SPRING2", stream.getvalue())
        output = os.environ.get("FREECAD_J97_OUTPUT")
        if output:
            self.doc.recompute()
            self.doc.saveAs(output)

    def test_native_persistence_and_export(self):
        reopen = os.environ.get("FREECAD_CTQ_REOPEN")
        if reopen:
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(reopen)
            self.analysis = self.doc.getObject("Analysis")
            FemGui.setActiveAnalysis(self.analysis)
            obj = connectors(self.analysis)[0]
            mesh = self.doc.getObject("Mesh")
        else:
            obj = self.create(2)[0]
            obj.Stiffness = "2 kN/mm"
            mesh = ObjectsFem.makeMeshGmsh(self.doc, "Mesh")
            data = Fem.FemMesh()
            data.addNode(0, 0, 0, 1)
            data.addNode(1, 0, 0, 2)
            mesh.FemMesh = data
            self.analysis.addObject(mesh)
            frame = self.doc.addObject("App::Part", "Frame")
            frame.Placement.Rotation = App.Rotation(App.Vector(0, 0, 1), 90)
            obj.OrientationReference = frame
        result = resolve_connector(obj, mesh)
        self.assertEqual(result["nodes"], [1, 2])
        self.assertEqual(result["stiffness"], 2000)
        self.assertLess((result["rotation"].multVec(App.Vector(1, 0, 0))
                         - App.Vector(0, 1, 0)).Length, 1e-12)
        stream = io.StringIO()
        writer = SimpleNamespace(mesh_object=mesh, member=SimpleNamespace(
            cons_elasticconnector=[{"Object": obj}]))
        write_connectors(stream, writer)
        self.assertIn("TYPE=SPRING2", stream.getvalue())
        if reopen:
            self.doc.getObject("Frame").Placement.Rotation = App.Rotation()
            obj.End1, obj.End2 = obj.End2, obj.End1
            result = resolve_connector(obj, mesh)
            self.assertEqual(result["nodes"], [2, 1])
            self.assertLess((result["rotation"].multVec(App.Vector(1, 0, 0))
                             - App.Vector(1, 0, 0)).Length, 1e-12)
            regenerated = io.StringIO()
            write_connectors(regenerated, writer)
            self.assertNotEqual(stream.getvalue(), regenerated.getvalue())
            self.assertIn("\n1,2,1\n", regenerated.getvalue())
            self.assertIn("\n1,0,0,0,1,0\n", regenerated.getvalue())
        output = os.environ.get("FREECAD_CTQ_OUTPUT")
        if output:
            root = Path(output)
            root.mkdir(parents=True, exist_ok=False)
            self.doc.recompute()
            self.doc.saveAs(str(root / "native-connector.FCStd"))
            (root / "report.json").write_text(json.dumps({
                "runtime": App.Version(), "gui_up": App.GuiUp, "fresh_reopen": bool(reopen),
                "nodes": result["nodes"], "stiffness_N_per_mm": result["stiffness"],
                "building_design_accepted": False,
            }, indent=2))
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(obj)
            Gui.updateGui()
            loop = QtCore.QEventLoop()
            QtCore.QTimer.singleShot(250, loop.quit)
            loop.exec()
            texts = []

            def collect(model, parent=QtCore.QModelIndex(), depth=0):
                if depth > 4:
                    return
                for row in range(model.rowCount(parent)):
                    index = model.index(row, 0, parent)
                    texts.append(str(model.data(index)))
                    collect(model, index, depth + 1)
            for tree in Gui.getMainWindow().findChildren(QtGui.QTreeView):
                if tree.model():
                    collect(tree.model())
            self.assertIn("Stiffness", texts, texts)
            Gui.getMainWindow().grab().save(str(root / "native-connector.png"))
