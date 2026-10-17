# SPDX-License-Identifier: LGPL-2.1-or-later

"""Material groups are volume partitions, not just equal element counts."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import FreeCAD as App

import Fem
import ObjectsFem

from femmesh import gmshtools
from femmesh import meshsetsgetter
from femmesh import meshtools


class TestMaterialGroups(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("MaterialGroups")
        self.material = ObjectsFem.makeMaterialSolid(self.doc, "Material")
        self.other = ObjectsFem.makeMaterialSolid(self.doc, "OtherMaterial")
        self.first = self.doc.addObject("Part::Box", "First")
        self.second = self.doc.addObject("Part::Box", "Second")
        for box in (self.first, self.second):
            box.Length = box.Width = box.Height = 1
        self.second.Placement.Base = App.Vector(4, 0, 0)
        self.material.References = [(self.first, ["Solid1"])]
        self.other.References = [(self.second, ["Solid1"])]
        self.doc.recompute()
        self.mesh = Fem.FemMesh()
        for node, xyz in enumerate(((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)), 1):
            self.mesh.addNode(*xyz, node)
        self.mesh.addVolume([1, 2, 3, 4], 1)
        for node, xyz in enumerate(((4, 0, 0), (5, 0, 0), (4, 1, 0), (4, 0, 1)), 5):
            self.mesh.addNode(*xyz, node)
        self.mesh.addVolume([5, 6, 7, 8], 2)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def test_exact_name_all_group_supplies_volume_ids(self):
        group = self.mesh.addGroup(self.material.Name, "All")
        self.mesh.addGroupElements(group, [1])
        actual = meshtools.get_femmesh_groupdata_sets_by_name(
            self.mesh, {"Object": self.material}, "Volume"
        )
        self.assertEqual(set(actual), {1})

    def test_all_group_projects_only_requested_element_dimension(self):
        self.mesh.addFace([1, 2, 3], 3)
        group = self.mesh.addGroup(self.material.Name, "All")
        self.mesh.addGroupElements(group, [1, 3])
        self.assertEqual(
            meshtools.get_femmesh_groupdata_sets_by_name(
                self.mesh, {"Object": self.material}, "Volume"
            ),
            (1,),
        )

    def test_node_group_does_not_supply_colliding_volume_ids(self):
        group = self.mesh.addGroup(self.material.Name, "Node")
        self.mesh.addGroupElements(group, [1])
        self.assertEqual(
            meshtools.get_femmesh_groupdata_sets_by_name(
                self.mesh, {"Object": self.material}, "Volume"
            ),
            (),
        )

    def test_legacy_typed_groups_are_combined(self):
        for suffix, element in (("_Solid1", 1), ("_Solid2", 2)):
            group = self.mesh.addGroup(self.material.Name + suffix, "Volume")
            self.mesh.addGroupElements(group, [element])
        self.assertEqual(
            meshtools.get_femmesh_groupdata_sets_by_name(
                self.mesh, {"Object": self.material}, "Volume"
            ),
            (1, 2),
        )

    def test_equal_counts_do_not_hide_overlap_and_missing_volume(self):
        for obj in (self.material, self.other):
            group = self.mesh.addGroup(obj.Name, "All")
            self.mesh.addGroupElements(group, [1])
        with self.assertRaisesRegex(ValueError, "overlap"):
            meshtools.get_femelement_sets_from_group_data(
                self.mesh, [{"Object": self.material}, {"Object": self.other}]
            )

    def test_legacy_partition_discards_old_reference_results(self):
        for obj, element in ((self.material, 1), (self.other, 2)):
            group = self.mesh.addGroup(obj.Name + "_Solid1", "Volume")
            self.mesh.addGroupElements(group, [element])
        rows = [
            {"Object": obj, "MaterialElements": ["stale"]} for obj in (self.material, self.other)
        ]
        self.assertTrue(meshtools.get_femelement_sets_from_group_data(self.mesh, rows))
        self.assertEqual([row["FEMElements"] for row in rows], [(1,), (2,)])
        self.assertTrue(all("MaterialElements" not in row for row in rows))

    def generate_mesh(self, directory):
        analysis = ObjectsFem.makeAnalysis(self.doc)
        compound = self.doc.addObject("Part::Compound", "Compound")
        compound.Links = [self.first, self.second]
        mesh = ObjectsFem.makeMeshGmsh(self.doc, "Mesh")
        mesh.Shape = compound
        mesh.ElementOrder = "1st"
        mesh.CharacteristicLengthMin = mesh.CharacteristicLengthMax = 0.7
        mesh.WorkingDirectory = directory
        for obj in (mesh, self.material, self.other):
            analysis.addObject(obj)
        self.doc.recompute()
        prefs = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/General")
        previous = prefs.GetBool("AnalysisGroupMeshing", False)
        present = previous == prefs.GetBool("AnalysisGroupMeshing", True)
        try:
            prefs.SetBool("AnalysisGroupMeshing", True)
            tool = gmshtools.GmshTools(mesh)
            tool.create_mesh()
            self.assertEqual(tool.process.exitCode(), 0)
            self.assertEqual(tool.process.exitStatus(), tool.process.ExitStatus.NormalExit)
        finally:
            if present:
                prefs.SetBool("AnalysisGroupMeshing", previous)
            else:
                prefs.RemBool("AnalysisGroupMeshing")
        return analysis, mesh

    @unittest.skipUnless(shutil.which("gmsh"), "Gmsh binary required")
    def test_missing_native_solid_group_is_not_replaced_by_material_snapshot(self):
        with tempfile.TemporaryDirectory(prefix="freecad-material-missing-") as directory:
            _, mesh = self.generate_mesh(directory)
            native = mesh.FemMesh
            for group in native.Groups:
                if native.getGroupName(group) == "Solid2":
                    self.assertTrue(native.removeGroup(group))
                    break
            else:
                self.fail("Gmsh did not create the expected Solid2 group")
            mesh.FemMesh = native
            rows = [{"Object": obj} for obj in (self.material, self.other)]
            with self.assertRaisesRegex(ValueError, "missing or ambiguous"):
                meshtools.get_femelement_sets_from_group_data(mesh.FemMesh, rows, mesh)
            self.assertTrue(all("FEMElements" not in row for row in rows))

    @unittest.skipUnless(shutil.which("gmsh"), "Gmsh binary required")
    def test_saved_mesh_uses_current_references_not_old_material_aggregates(self):
        with tempfile.TemporaryDirectory(prefix="freecad-material-reopen-") as directory:
            _, mesh = self.generate_mesh(directory)
            expected = {}
            for group in mesh.FemMesh.Groups:
                name = mesh.FemMesh.getGroupName(group)
                if name in ("Solid1", "Solid2"):
                    expected[name] = set(mesh.FemMesh.getGroupElements(group))
            self.assertEqual(set(expected), {"Solid1", "Solid2"})
            path = Path(directory) / "groups.FCStd"
            self.doc.saveAs(str(path))
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(str(path))
            mesh = self.doc.getObject("Mesh")
            expected = {
                mesh.FemMesh.getGroupName(group): set(mesh.FemMesh.getGroupElements(group))
                for group in mesh.FemMesh.Groups
                if mesh.FemMesh.getGroupName(group) in ("Solid1", "Solid2")
            }
            material = self.doc.getObject("Material")
            other = self.doc.getObject("OtherMaterial")
            material.References = [(self.doc.getObject("Second"), ["Solid1"])]
            other.References = []
            rows = [{"Object": obj} for obj in (material, other)]
            self.assertTrue(meshtools.get_femelement_sets_from_group_data(mesh.FemMesh, rows, mesh))
            self.assertEqual(set(rows[0]["FEMElements"]), expected["Solid2"])
            self.assertEqual(set(rows[1]["FEMElements"]), expected["Solid1"])
            self.assertEqual(set(rows[0]["MaterialElements"][0][1]), expected["Solid2"])
            self.assertEqual(rows[1]["MaterialElements"], [])
            material.References = [(self.doc.getObject("First"), ["Solid1"])]
            self.assertTrue(meshtools.get_femelement_sets_from_group_data(mesh.FemMesh, rows, mesh))
            self.assertEqual(set(rows[0]["FEMElements"]), expected["Solid1"])
            self.doc.getObject("First").Length = 2
            self.doc.recompute()
            with self.assertRaisesRegex(ValueError, "geometry changed"):
                meshtools.get_femelement_sets_from_group_data(mesh.FemMesh, rows, mesh)

    def test_missing_coverage_does_not_commit_partial_results(self):
        group = self.mesh.addGroup(self.material.Name, "Volume")
        self.mesh.addGroupElements(group, [1])
        rows = [{"Object": self.material}]
        with self.assertRaisesRegex(ValueError, "cover every"):
            meshtools.get_femelement_sets_from_group_data(self.mesh, rows)
        self.assertNotIn("FEMElements", rows[0])

    def test_multiple_defaults_are_rejected(self):
        self.material.References = []
        self.other.References = []
        with self.assertRaisesRegex(ValueError, "Multiple default"):
            meshtools.get_femelement_sets_from_group_data(
                self.mesh, [{"Object": self.material}, {"Object": self.other}]
            )

    def test_exact_group_takes_precedence_over_legacy_prefix(self):
        for name, kind, members in (
            (self.material.Name, "All", [1]),
            (self.material.Name + "_old", "Volume", [2]),
        ):
            group = self.mesh.addGroup(name, kind)
            self.mesh.addGroupElements(group, members)
        self.assertEqual(
            meshtools.get_femmesh_groupdata_sets_by_name(
                self.mesh, {"Object": self.material}, "Volume"
            ),
            (1,),
        )

    @unittest.skipUnless(shutil.which("gmsh"), "Gmsh binary required")
    def test_both_material_passes_use_native_groups(self):
        with tempfile.TemporaryDirectory(prefix="freecad-material-groups-") as directory:
            analysis, mesh = self.generate_mesh(directory)
            expected = {}
            for group in mesh.FemMesh.Groups:
                name = mesh.FemMesh.getGroupName(group)
                if name in (self.material.Name, self.other.Name):
                    expected[name] = set(mesh.FemMesh.getGroupElements(group))
            self.assertEqual(set(expected), {self.material.Name, self.other.Name})
            rows = [{"Object": obj} for obj in (self.material, self.other)]
            member = SimpleNamespace(
                mats_linear=rows, geos_shellthickness=[], geos_beamsection=[], geos_fluidsection=[]
            )
            getter = meshsetsgetter.MeshSetsGetter(
                analysis, SimpleNamespace(AnalysisType="static"), mesh, member
            )
            calls = []
            previous = sys.getprofile()
            try:

                def profile(frame, event, function):
                    if event == "c_call" and getattr(function, "__name__", "") == "getNodesBySolid":
                        calls.append("getNodesBySolid")

                sys.setprofile(profile)
                getter.get_material_elements()
                getter.get_materials_elements()
            finally:
                sys.setprofile(previous)
            self.assertEqual(calls, [], "Neither material pass needs CAD node classification")
            for row in rows:
                wanted = expected[row["Object"].Name]
                self.assertEqual(set(row["FEMElements"]), wanted)
                self.assertEqual(
                    {element for _, elements, _ in row["MaterialElements"] for element in elements},
                    wanted,
                )
