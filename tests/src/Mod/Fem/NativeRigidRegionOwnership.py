# SPDX-License-Identifier: LGPL-2.1-or-later

"""Opt-in exact R26 native mesh-ownership witness for FreeCAD-eb7.

Run FreeCAD or FreeCADCmd -P tests/src/Mod/Fem -t NativeRigidRegionOwnership
with FREECAD_EB7_DIRECTORY naming a disposable evidence directory and
FREECAD_EB7_INPUT naming the unchanged original native-faying-face-witness.FCStd.
Run stage=create, then stage=reopen in a fresh process, using the same directory
and original input. Optional FREECAD_EB7_EXPECTED_COMMIT checks the runtime.

This invokes native Gmsh and compares native resolvers against independent raw
VTK cell connectivity. It never repairs node groups, writes solver decks, or
accepts physical stiffness, joint behaviour or a building design.
"""

import hashlib
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest
from zipfile import ZipFile

import FreeCAD as App
import Fem
import ObjectsFem
import Part
from femmesh import gmshtools, meshsetsgetter, meshtools
from femtools import elastic_connector


WITNESS_SHA256 = "519cd5777e278e29b8186ba4f5b1132022019e5218b5e6434383fb3541c16b18"


@unittest.skipUnless(os.environ.get("FREECAD_EB7_DIRECTORY")
                     and os.environ.get("FREECAD_EB7_INPUT"),
                     "Requires an immutable R26 input and disposable evidence directory")
class NativeRigidRegionOwnership(unittest.TestCase):
    def setUp(self):
        self.doc = None
        self.directory = Path(os.environ["FREECAD_EB7_DIRECTORY"]).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.source = Path(os.environ["FREECAD_EB7_INPUT"]).resolve()
        self.assertEqual(self.digest(self.source), WITNESS_SHA256,
                         "The exact original R26 witness is required")
        self.assertFalse(self.source.is_relative_to(self.directory),
                         "The original witness must remain outside the owned evidence directory")
        self.stage = os.environ.get("FREECAD_EB7_STAGE", "create")
        self.assertIn(self.stage, ("create", "reopen"))
        self.assertFalse((self.directory / f"{self.stage}-result.json").exists(),
                         "Use a fresh evidence directory; retain earlier stage receipts")
        expected = os.environ.get("FREECAD_EB7_EXPECTED_COMMIT",
                                  os.environ.get("EXPECTED_COMMIT"))
        if expected:
            self.assertEqual(App.Version()[-1], expected)
        self.gmsh = shutil.which("gmsh")
        self.assertIsNotNone(self.gmsh, "The declared runtime must expose real Gmsh")
        self.general = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/General")
        self.gmsh_prefs = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/Gmsh")
        self.old_groups = self.general.GetBool("AnalysisGroupMeshing", False)
        self.had_groups = self.old_groups == self.general.GetBool("AnalysisGroupMeshing", True)
        self.old_gmsh = self.gmsh_prefs.GetString("gmshBinaryPath", "")
        self.had_gmsh = self.old_gmsh == self.gmsh_prefs.GetString("gmshBinaryPath", "<absent>")
        self.general.SetBool("AnalysisGroupMeshing", True)
        self.gmsh_prefs.SetString("gmshBinaryPath", self.gmsh)

    def tearDown(self):
        if self.doc is not None and self.doc.Name in App.listDocuments():
            App.closeDocument(self.doc.Name)
        if self.had_groups:
            self.general.SetBool("AnalysisGroupMeshing", self.old_groups)
        else:
            self.general.RemBool("AnalysisGroupMeshing")
        if self.had_gmsh:
            self.gmsh_prefs.SetString("gmshBinaryPath", self.old_gmsh)
        else:
            self.gmsh_prefs.RemString("gmshBinaryPath")
        self.assertEqual(self.digest(self.source), WITNESS_SHA256,
                         "Never overwrite the original witness")

    @staticmethod
    def digest(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def objects(self):
        names = ("TouchingFootprints", "RBERC", "RBELedger", "PortRegionAnalysis",
                 "PortRegionMesh", "RegionConnector")
        values = [self.doc.getObject(name) for name in names]
        self.assertTrue(all(value is not None for value in values))
        if App.GuiUp:
            self.assertTrue(all(value.ViewObject is not None for value in values),
                            "Native GUI objects must retain their view providers")
        return values

    def geometry(self):
        compound = self.doc.getObject("TouchingFootprints")
        rc = self.doc.getObject("RCFootprint")
        ledger = self.doc.getObject("LedgerFootprint")
        self.assertEqual(compound.Links, [rc, ledger])
        self.assertEqual([rc.Length.Value, rc.Width.Value, rc.Height.Value], [180, 100, 80])
        self.assertEqual([ledger.Length.Value, ledger.Width.Value, ledger.Height.Value],
                         [95, 100, 80])
        center = App.Vector(62.5, 2843, 5835)
        faces = [rc.getSubObject("Face2"), ledger.getSubObject("Face1")]
        self.assertFalse(faces[0].isSame(faces[1]))
        for face in faces:
            self.assertLess((face.CenterOfMass - center).Length, 1e-8)
            self.assertAlmostEqual(face.Area, 8000, places=8)
        return {"source_geometry": meshtools.get_mesh_geometry_signature(compound),
                "face_areas_mm2": [face.Area for face in faces],
                "face_centers_mm": [list(face.CenterOfMass) for face in faces],
                "independent_native_faces": True}

    def settings(self):
        compound, first, second, analysis, mesh, connector = self.objects()
        self.assertEqual(mesh.Shape, compound)
        self.assertEqual(mesh.ElementOrder, "2nd")
        self.assertEqual(mesh.CharacteristicLengthMax.Value, 40)
        self.assertEqual(mesh.CharacteristicLengthMin.Value, 20)
        self.assertFalse(mesh.CoherenceMesh)
        self.assertEqual(connector.Attachment, "Rigid body ports")
        self.assertEqual(connector.Kind, "Translational")
        self.assertEqual(connector.Mode, "Two points")
        self.assertEqual(connector.Axis, "Y")
        self.assertEqual(connector.Stiffness.getValueAs("N/mm").Value, 1000)
        self.assertEqual([connector.RigidBody1, connector.RigidBody2], [first, second])
        self.assertEqual(analysis.Group, [first, second, mesh, connector])
        for body, owner, name, entity in ((first, "RCFootprint", "Face2", "Face2"),
                                          (second, "LedgerFootprint", "Face1", "Face7")):
            self.assertEqual(body.References, [(self.doc.getObject(owner), (name,))])
            self.assertEqual(list(body.ReferenceNode), [62.5, 2843, 5835])
            self.assertEqual(meshtools.get_reference_group_elements(body, compound)[1], [entity])
        return {"Shape": mesh.Shape.Name, "ElementOrder": mesh.ElementOrder,
                "ElementDimension": mesh.ElementDimension,
                "CharacteristicLengthMax_mm": mesh.CharacteristicLengthMax.Value,
                "CharacteristicLengthMin_mm": mesh.CharacteristicLengthMin.Value,
                "CoherenceMesh": mesh.CoherenceMesh,
                "GeometryTolerance": mesh.GeometryTolerance,
                "AnalysisGroupMeshing": self.general.GetBool("AnalysisGroupMeshing"),
                "RBE_references": [[[owner.Name, list(names)] for owner, names in body.References]
                                   for body in (first, second)],
                "RBE_reference_positions_mm": [list(body.ReferenceNode)
                                               for body in (first, second)],
                "connector": {"Attachment": connector.Attachment, "Kind": connector.Kind,
                              "Mode": connector.Mode, "Axis": connector.Axis,
                              "stiffness_N_per_mm": 1000},
                "provenance": {"names": list(mesh.ElementGroupNames),
                               "references": [[owner.Name, list(names)]
                                              for owner, names in mesh.ElementGroupReferences],
                               "geometry": mesh.ElementGroupGeometry}}

    def vtk_oracle(self, raw_file, tags):
        # VTK's legacy reader is independent of FreeCAD's group-node resolver.
        from vtkmodules.vtkIOLegacy import vtkUnstructuredGridReader

        reader = vtkUnstructuredGridReader()
        reader.SetFileName(str(raw_file))
        reader.Update()
        grid = reader.GetOutput()
        self.assertGreater(grid.GetNumberOfPoints(), 0)
        entities = grid.GetCellData().GetArray("CellEntityIds")
        self.assertIsNotNone(entities)
        regions = {}
        for name in ("Face2", "Face7"):
            cells, nodes, connectivity = [], set(), []
            for index in range(grid.GetNumberOfCells()):
                if int(entities.GetTuple1(index)) != tags[name]:
                    continue
                # GetCell reuses a cached native wrapper; consume it immediately.
                cell = grid.GetCell(index)
                self.assertEqual(cell.GetCellType(), 22)  # VTK_QUADRATIC_TRIANGLE
                self.assertEqual(cell.GetNumberOfPoints(), 6)
                cells.append(index + 1)
                cell_nodes = [cell.GetPointId(i) + 1 for i in range(cell.GetNumberOfPoints())]
                nodes.update(cell_nodes)
                connectivity.append(sorted(cell_nodes))
            self.assertEqual(len(cells), 18)
            self.assertEqual(len(nodes), 47)
            regions[name] = {"cells": cells, "nodes": sorted(nodes),
                             "connectivity": sorted(connectivity)}
        self.assertFalse(set(regions["Face2"]["nodes"]) & set(regions["Face7"]["nodes"]))
        self.assertEqual({tuple(grid.GetPoint(i - 1)) for i in regions["Face2"]["nodes"]},
                         {tuple(grid.GetPoint(i - 1)) for i in regions["Face7"]["nodes"]})
        return {"points": grid.GetNumberOfPoints(), "cells": grid.GetNumberOfCells(),
                "physical_entity_tags": tags, "regions": regions,
                "raw_mesh": str(raw_file), "raw_sha256": self.digest(raw_file),
                "owner_intersection": [], "owner_union_count": 94}

    def check_regions(self, oracle):
        _, first, second, analysis, mesh, connector = self.objects()
        fm = mesh.FemMesh
        expected = [set(oracle["regions"][name]["nodes"]) for name in ("Face2", "Face7")]
        result = []
        for body, face, nodes in zip((first, second), ("Face2", "Face7"), expected):
            for name in (face, body.Name):
                groups = [group for group in fm.Groups if fm.getGroupName(group) == name]
                self.assertEqual(len(groups), 1)
                elements = fm.getGroupElements(groups[0])
                # Native FCStd serialization may renumber element IDs. Compare
                # their actual node connectivity, not obsolete raw VTK cell IDs.
                self.assertEqual(len(elements), len(oracle["regions"][face]["cells"]))
                self.assertTrue(set(elements) <= set(fm.Faces))
                self.assertEqual(sorted(sorted(fm.getElementNodes(element))
                                        for element in elements),
                                 oracle["regions"][face]["connectivity"])
            public = set(meshtools.get_femnodes_by_femobj_with_references(fm, {"Object": body}))
            explicit = set(meshtools.get_femnodes_by_femobj_with_references(
                fm, {"Object": body}, mesh))
            port = elastic_connector.rigid_body_nodes(body, mesh)
            self.assertEqual(public, nodes)
            self.assertEqual(explicit, nodes)
            self.assertEqual(port, nodes)
            owner, names = body.References[0]
            self.assertEqual(set(fm.getNodesByFace(owner.getSubObject(names[0]))),
                             expected[0] | expected[1])
            result.append({"body": body.Name, "public_writer_node_ids": sorted(public),
                           "explicit_writer_node_ids": sorted(explicit),
                           "port_node_ids": sorted(port)})
        # Exercise the actual ordinary writer's sets-getter without creating a
        # solver object, material, load or hand-authored solver deck.
        members = SimpleNamespace(cons_rigidbody=[{"Object": first}, {"Object": second}])
        getter = meshsetsgetter.MeshSetsGetter(
            analysis, SimpleNamespace(AnalysisType="static"), mesh, members)
        getter.get_constraints_rigidbody_nodes()
        self.assertEqual([set(item["Nodes"]) for item in members.cons_rigidbody], expected)
        resolved = elastic_connector.resolve_connector(connector, mesh, analysis)
        self.assertEqual(resolved["bodies"], [first, second])
        self.assertEqual(resolved["regions"], expected)
        self.assertEqual(resolved["stiffness"], 1000)
        self.assertEqual(resolved["dof"], 2)
        return {"regions": result, "meshsetsgetter_matches_raw_connectivity": True,
                "connector_resolves": True,
                "counts": {"nodes": fm.NodeCount, "volumes": fm.VolumeCount,
                           "faces": fm.FaceCount, "groups": fm.GroupCount}}

    def create(self, report):
        work = self.directory / "create"
        work.mkdir(exist_ok=False)
        copied = work / "input.FCStd"
        shutil.copyfile(self.source, copied)
        self.assertEqual(self.digest(copied), WITNESS_SHA256)
        self.doc = App.openDocument(str(copied))
        self.assertEqual(Path(self.doc.FileName).resolve(), copied)
        report["geometry"] = self.geometry()
        bodies = [self.doc.getObject(name) for name in ("RBERC", "RBELedger")]
        analysis = ObjectsFem.makeAnalysis(self.doc, "PortRegionAnalysis")
        for body in bodies:
            body.ReferenceNode = App.Vector(62.5, 2843, 5835)
            analysis.addObject(body)
        mesh = ObjectsFem.makeMeshGmsh(self.doc, "PortRegionMesh")
        mesh.Shape = self.doc.getObject("TouchingFootprints")
        mesh.ElementOrder = "2nd"
        mesh.CharacteristicLengthMax = "40 mm"
        mesh.CharacteristicLengthMin = "20 mm"
        mesh.CoherenceMesh = False
        mesh_dir = work / "mesh"
        mesh_dir.mkdir()
        mesh.WorkingDirectory = str(mesh_dir)
        analysis.addObject(mesh)
        connector = ObjectsFem.makeConstraintElasticConnector(self.doc, "RegionConnector")
        connector.Attachment = "Rigid body ports"
        connector.Kind = "Translational"
        connector.Mode = "Two points"
        connector.Axis = "Y"
        connector.Stiffness = "1000 N/mm"
        connector.RigidBody1, connector.RigidBody2 = bodies
        analysis.addObject(connector)
        self.doc.recompute()
        tool = gmshtools.GmshTools(mesh)
        tool.create_mesh()
        (work / "gmsh-stdout.txt").write_bytes(tool.process.readAllStandardOutput().data())
        (work / "gmsh-stderr.txt").write_bytes(tool.process.readAllStandardError().data())
        self.assertEqual(tool.process.exitCode(), 0)
        self.assertEqual(tool.process.exitStatus(), tool.process.ExitStatus.NormalExit)
        report["gmsh"] = {"binary": self.gmsh, "exit_code": tool.process.exitCode(),
                          "geometry": tool.temp_file_geometry, "geo": tool.model_file,
                          "raw_mesh": tool.temp_file_mesh}
        tags = {name: tool.group_indices[name] for name in ("Face2", "Face7")}
        report["oracle"] = self.vtk_oracle(Path(tool.temp_file_mesh), tags)
        report["settings"] = self.settings()
        report["before_save"] = self.check_regions(report["oracle"])
        output = self.directory / "owned.FCStd"
        self.assertFalse(output.exists(), "Never overwrite an earlier owned fixture")
        self.doc.saveAs(str(output))
        if App.GuiUp:
            with ZipFile(output) as archive:
                self.assertIn("GuiDocument.xml", archive.namelist())
        self.assertEqual(report["before_save"], self.check_regions(report["oracle"]))
        report["owned_native"] = str(output)
        report["owned_sha256"] = self.digest(output)

    def reopen(self, report):
        created = json.loads((self.directory / "create-result.json").read_text())
        self.assertTrue(created["passed"])
        source = self.directory / "owned.FCStd"
        self.assertEqual(self.digest(source), created["owned_sha256"])
        work = self.directory / "reopen"
        work.mkdir(exist_ok=False)
        copied = work / "input.FCStd"
        shutil.copyfile(source, copied)
        self.doc = App.openDocument(str(copied))
        self.assertEqual(Path(self.doc.FileName).resolve(), copied)
        # No recompute or new Gmsh invocation may precede these cold checks.
        report["geometry"] = self.geometry()
        report["settings"] = self.settings()
        self.assertEqual(report["geometry"], created["geometry"])
        self.assertEqual(report["settings"], created["settings"])
        old_oracle = created["oracle"]
        report["oracle"] = self.vtk_oracle(Path(old_oracle["raw_mesh"]),
                                           old_oracle["physical_entity_tags"])
        self.assertEqual(report["oracle"], old_oracle)
        report["cold_before_manual_recompute"] = self.check_regions(report["oracle"])
        # Native serialization may omit zero-D cells and renumber element IDs;
        # the generated vertex ownership persists in native node groups.
        expected = created["before_save"]
        actual = report["cold_before_manual_recompute"]
        self.assertEqual(actual["regions"], expected["regions"])
        for kind in ("nodes", "volumes", "faces", "groups"):
            self.assertEqual(actual["counts"][kind], expected["counts"][kind])
        self.doc.recompute(None, True)
        report["after_forced_recompute"] = self.check_regions(report["oracle"])
        self.assertEqual(report["after_forced_recompute"], actual)
        output = work / "successor.FCStd"
        self.doc.saveAs(str(output))
        if App.GuiUp:
            with ZipFile(output) as archive:
                self.assertIn("GuiDocument.xml", archive.namelist())
        report["owned_native"] = str(output)
        report["owned_sha256"] = self.digest(output)
        self.assertEqual(self.digest(source), created["owned_sha256"])

    def test_exact_native_regions_and_cold_restore(self):
        modules = (Fem, Part, ObjectsFem, gmshtools, meshtools,
                   meshsetsgetter, elastic_connector)
        paths = {module.__name__: str(Path(module.__file__).resolve()) for module in modules}
        report = {"runtime": App.Version(), "home": App.getHomePath(),
                  "gui_up": App.GuiUp, "stage": self.stage, "loaded_modules": paths,
                  "module_sha256": {name: self.digest(path) for name, path in paths.items()},
                  "harness": str(Path(__file__).resolve()), "source_witness": str(self.source),
                  "source_witness_sha256": WITNESS_SHA256, "passed": False,
                  "solver_material_load_or_hand_deck_created": False,
                  "physical_joint_or_building_design_accepted": False}
        try:
            if self.stage == "create":
                self.create(report)
            else:
                self.reopen(report)
            self.assertEqual(self.digest(self.source), WITNESS_SHA256)
            report["passed"] = True
        except BaseException as error:
            report["error"] = repr(error)
            raise
        finally:
            report["source_witness_unchanged"] = self.digest(self.source) == WITNESS_SHA256
            (self.directory / f"{self.stage}-result.json").write_text(
                json.dumps(report, indent=2) + "\n")
