# SPDX-License-Identifier: LGPL-2.1-or-later

"""Native reference/group persistence probe using synthetic touching boxes.

Set FREECAD_S0X_OUTPUT to a new output directory. Run again in an independent
GUI process with FREECAD_S0X_REOPEN pointing to the first native-groups.FCStd.
The cold reopen checks the saved groups before any explicit recompute; it then
reorders the compound and regenerates the mesh through the stock Gmsh tool.
"""

import json
import os
from pathlib import Path
import unittest
from zipfile import ZipFile

import FreeCAD as App
import FreeCADGui as Gui
import ObjectsFem

from femmesh import gmshtools
from femmesh import meshtools
from PySide import QtCore


@unittest.skipUnless(App.GuiUp, "Requires native GUI to preserve view providers")
class ReferenceGroupsGui(unittest.TestCase):
    initial_faces = {"FirstBody": "Face2", "SecondBody": "Face7"}
    reordered_faces = {"FirstBody": "Face8", "SecondBody": "Face1"}

    def correspondence(self, doc):
        return meshtools.get_analysis_group_elements(
            doc.getObject("Analysis"), doc.getObject("Compound"))

    @staticmethod
    def mesh_groups(mesh):
        # Actual native element groups, not derived/filtered node selections.
        data = mesh.FemMesh
        return {data.getGroupName(group): sorted(data.getGroupElements(group))
                for group in data.Groups}

    def assert_groups(self, groups, faces):
        for body, named in (("FirstBody", "FirstGroup"),
                            ("SecondBody", "SecondGroup")):
            face = faces[body]
            self.assertIn(face, groups)
            self.assertTrue(groups[face], face)
            self.assertEqual(groups[body], groups[face], body)
            self.assertEqual(groups[named], groups[face], named)
        self.assertNotEqual(groups["FirstGroup"], groups["SecondGroup"])
        self.assertNotEqual(groups["FirstBody"], groups["SecondBody"])

    def generate_mesh(self, mesh, directory):
        directory.mkdir()
        # ObjectTools reads this native property; tool.working_dir is not used.
        mesh.WorkingDirectory = str(directory)
        tool = gmshtools.GmshTools(mesh)
        tool.create_mesh()
        self.assertEqual(tool.process.exitStatus(), QtCore.QProcess.NormalExit)
        self.assertEqual(tool.process.exitCode(), 0)
        self.assertGreater(mesh.FemMesh.VolumeCount, 0)
        self.assertTrue(Path(tool.temp_file_mesh).is_file())
        return self.mesh_groups(mesh)

    def create_model(self, doc):
        first = doc.addObject("Part::Box", "First")
        second = doc.addObject("Part::Box", "Second")
        for box in (first, second):
            box.Length = box.Width = box.Height = 1
        second.Placement.Base = App.Vector(1, 0, 0)
        compound = doc.addObject("Part::Compound", "Compound")
        compound.Links = [first, second]
        analysis = ObjectsFem.makeAnalysis(doc)
        first_body = ObjectsFem.makeConstraintRigidBody(doc, "FirstBody")
        second_body = ObjectsFem.makeConstraintRigidBody(doc, "SecondBody")
        first_body.References = [(first, ["Face2"])]
        second_body.References = [(second, ["Face1"])]
        analysis.addObject(first_body)
        analysis.addObject(second_body)
        mesh = ObjectsFem.makeMeshGmsh(doc, "Mesh")
        mesh.Shape = compound
        mesh.CharacteristicLengthMin = 0.7
        mesh.CharacteristicLengthMax = 0.7
        analysis.addObject(mesh)
        first_group = ObjectsFem.makeMeshGroup(doc, mesh, False, "FirstGroup")
        second_group = ObjectsFem.makeMeshGroup(doc, mesh, False, "SecondGroup")
        first_group.References = first_body.References
        second_group.References = second_body.References
        doc.recompute()
        return mesh

    def test_native_fresh_process_groups_and_regeneration(self):
        root = Path(os.environ["FREECAD_S0X_OUTPUT"])
        root.mkdir(parents=True, exist_ok=False)
        reopen = os.environ.get("FREECAD_S0X_REOPEN")
        prefs = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/General")
        previous = prefs.GetBool("AnalysisGroupMeshing", False)
        had_preference = previous == prefs.GetBool("AnalysisGroupMeshing", True)
        doc = None
        try:
            prefs.SetBool("AnalysisGroupMeshing", True)
            doc = App.openDocument(reopen) if reopen else App.newDocument("ReferenceGroupsNative")
            if reopen:
                # No recompute or mesh regeneration may precede these checks.
                mesh = doc.getObject("Mesh")
                self.assertEqual([obj.Name for obj in doc.getObject("Compound").Links],
                                 ["First", "Second"])
                self.assertEqual(self.correspondence(doc),
                                 {body: [face] for body, face in self.initial_faces.items()})
                initial_groups = self.mesh_groups(mesh)
                self.assert_groups(initial_groups, self.initial_faces)
                for body, owner, face in (("FirstBody", "First", "Face2"),
                                          ("SecondBody", "Second", "Face1")):
                    reference = doc.getObject(body).References
                    self.assertEqual(len(reference), 1)
                    self.assertEqual(reference[0][0].Name, owner)
                    self.assertEqual(list(reference[0][1]), [face])
                doc.getObject("Compound").Links = [doc.getObject("Second"), doc.getObject("First")]
                doc.recompute()
                expected = self.reordered_faces
                self.assertEqual(self.correspondence(doc),
                                 {body: [face] for body, face in expected.items()})
                groups = self.generate_mesh(mesh, root / "gmsh-reordered")
            else:
                mesh = self.create_model(doc)
                expected = self.initial_faces
                self.assertEqual(self.correspondence(doc),
                                 {body: [face] for body, face in expected.items()})
                groups = self.generate_mesh(mesh, root / "gmsh-initial")
                initial_groups = groups
            self.assert_groups(groups, expected)
            doc.recompute()
            doc.getObject("First").ViewObject.Visibility = False
            doc.getObject("Second").ViewObject.Visibility = False
            doc.getObject("Compound").ViewObject.Visibility = False
            mesh.ViewObject.Visibility = True
            Gui.activeDocument().activeView().viewAxonometric()
            Gui.activeDocument().activeView().fitAll()
            filename = root / "native-groups.FCStd"
            doc.saveAs(str(filename))
            with ZipFile(filename) as archive:
                self.assertIn("GuiDocument.xml", archive.namelist())
            (root / "report.json").write_text(json.dumps({
                "runtime": App.Version(),
                "gui_up": App.GuiUp,
                "fresh_process_reopen": bool(reopen),
                "initial_correspondence": {body: [face]
                                           for body, face in self.initial_faces.items()},
                "initial_mesh_groups": initial_groups,
                "saved_correspondence": self.correspondence(doc),
                "saved_mesh_groups": groups,
                "native_gui_document_preserved": True,
                "building_design_accepted": False,
            }, indent=2))
        finally:
            if had_preference:
                prefs.SetBool("AnalysisGroupMeshing", previous)
            else:
                prefs.RemBool("AnalysisGroupMeshing")
            if doc:
                App.closeDocument(doc.Name)
