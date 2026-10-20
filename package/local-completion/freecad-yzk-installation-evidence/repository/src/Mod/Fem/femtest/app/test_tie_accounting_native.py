# SPDX-License-Identifier: LGPL-2.1-or-later

"""Native ordinary Tie and finite-penalty contact equilibrium accounting.

This analytical software fixture does not qualify stresses, building geometry,
anchorage, mesh convergence or engineering acceptance. Generated native outputs
are retained in a private temporary directory for diagnosis.
"""

import hashlib
import json
import math
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import FreeCAD as App

import Part
from BOPTools.SplitAPI import booleanFragments

import Fem
import ObjectsFem
from femmesh import gmshtools
from feminout.importCcxFrdResults import read_frd_result
from femtools import force_accounting
from femtools.ccxtools import FemToolsCcx


@unittest.skipUnless(shutil.which("gmsh"), "Native Gmsh executable required")
class TestTieAccountingNative(unittest.TestCase):
    def setUp(self):
        try:
            Fem.FemMesh().toVTK()
        except NotImplementedError:
            self.skipTest("Native VTK Python wrappers are unavailable in this build")
        self.doc = App.newDocument("TieAccountingNative")
        self.output = Path(tempfile.mkdtemp(prefix="freecad-tie-accounting-native-"))

    def tearDown(self):
        if self.doc is not None and self.doc.Name in App.listDocuments():
            App.closeDocument(self.doc.Name)

    @staticmethod
    def _file_hash(path):
        with Path(path).open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()

    def _make_native_model(self, face_support=False):
        analysis = ObjectsFem.makeAnalysis(self.doc)
        solver = ObjectsFem.makeSolverCalculiXCcxTools(self.doc)
        solver.NativeForceAccounting = True
        candidate = os.environ.get("FREECAD_9ZT_PRODUCTION_CCX")
        if candidate:
            solver.NativeAccountingSolver = candidate
        binary = Path(force_accounting.solver_binary(solver))
        if not binary.is_file() or not os.access(binary, os.X_OK):
            self.skipTest("Qualified native force-accounting solver is unavailable")
        force_accounting.require_capability(binary)
        analysis.addObject(solver)

        geometry = self.doc.addObject("Part::Feature", "FourBodies")
        base = Part.makeBox(10, 10, 10)
        rear = Part.makeBox(10, 10, 10, App.Vector(0, 0, 10))
        front = Part.makeBox(10, 10, 10, App.Vector(0, 0, 20))
        sidepad = Part.makeBox(10, 10, 10, App.Vector(10, 0, 10))
        geometry.Shape = Part.makeCompound(
            [base, booleanFragments([rear, front], "CompSolid"), sidepad]
        )
        self.doc.recompute()
        self.assertEqual(len(geometry.Shape.Solids), 4)

        def solid_at(x, z):
            matches = [
                index
                for index, solid in enumerate(geometry.Shape.Solids, 1)
                if abs(solid.CenterOfMass.x - x) < 1e-7 and abs(solid.CenterOfMass.z - z) < 1e-7
            ]
            self.assertEqual(len(matches), 1, (x, z, matches))
            return f"Solid{matches[0]}"

        def face_at(axis, position, normal, centre_axis, centre):
            matches = [
                index
                for index, face in enumerate(geometry.Shape.Faces, 1)
                if abs(getattr(face.CenterOfMass, axis) - position) < 1e-7
                and abs(getattr(face.CenterOfMass, centre_axis) - centre) < 1e-7
                and getattr(face.normalAt(0, 0), axis) * normal > 0.99
            ]
            self.assertEqual(len(matches), 1, (axis, position, normal, matches))
            return f"Face{matches[0]}"

        solids = {
            "base": solid_at(5, 5),
            "rear": solid_at(5, 15),
            "front": solid_at(5, 25),
            "sidepad": solid_at(15, 15),
        }
        faces = {
            "support": face_at("z", 0, -1, "x", 5),
            "tie_slave": face_at("z", 10, -1, "x", 5),
            "tie_master": face_at("z", 10, 1, "x", 5),
            "cut": face_at("z", 20, 1, "x", 5),
            "top": face_at("z", 30, 1, "x", 5),
            "contact_slave": face_at("x", 10, -1, "z", 15),
            "contact_master": face_at("x", 10, 1, "z", 15),
            "side": face_at("x", 20, 1, "z", 15),
        }
        for slave, master in (("tie_slave", "tie_master"), ("contact_slave", "contact_master")):
            slave_shape = geometry.getSubObject(faces[slave])
            master_shape = geometry.getSubObject(faces[master])
            self.assertFalse(slave_shape.isSame(master_shape))
            self.assertAlmostEqual(slave_shape.distToShape(master_shape)[0], 0, places=10)
            self.assertAlmostEqual(slave_shape.common(master_shape).Area, 100, places=10)

        material = ObjectsFem.makeMaterialSolid(self.doc)
        material.Material = {
            "Name": "Steel",
            "YoungsModulus": "200000 MPa",
            "PoissonRatio": "0.3",
            "Density": "7900 kg/m^3",
        }
        analysis.addObject(material)
        support = ObjectsFem.makeConstraintRigidBody(self.doc, "BaseSupport")
        support.References = [(geometry, [faces["support"] if face_support else solids["base"]])]
        support.ReferenceNode = App.Vector(-5, -5, -5)
        for kind in ("Translational", "Rotational"):
            for axis in "XYZ":
                setattr(support, kind + "Mode" + axis, "Constraint")
        analysis.addObject(support)
        tie = ObjectsFem.makeConstraintTie(self.doc, "RearOrdinaryTie")
        tie.References = [(geometry, [faces["tie_slave"]]), (geometry, [faces["tie_master"]])]
        tie.Tolerance = 0
        tie.Adjust = False
        analysis.addObject(tie)
        contact = ObjectsFem.makeConstraintContact(self.doc, "SidepadContact")
        contact.References = [
            (geometry, [faces["contact_slave"]]),
            (geometry, [faces["contact_master"]]),
        ]
        contact.SurfaceBehavior = "Tied"
        contact.Slope = "1000000 MPa/mm"
        contact.Friction = True
        contact.FrictionCoefficient = 0.3
        contact.StickSlope = "1000000 MPa/mm"
        contact.Adjust = "0 mm"
        analysis.addObject(contact)
        for name, face in (("TopPressure", faces["top"]), ("SidePressure", faces["side"])):
            pressure = ObjectsFem.makeConstraintPressure(self.doc, name)
            pressure.References = [(geometry, [face])]
            pressure.Pressure = "1 MPa"
            analysis.addObject(pressure)
        gravity = ObjectsFem.makeConstraintSelfWeight(self.doc)
        gravity.GravityAcceleration = "9.81 m/s^2"
        analysis.addObject(gravity)
        rear_cut = ObjectsFem.makeConstraintSectionPrint(self.doc, "RearCut")
        rear_cut.References = [(geometry, [faces["cut"]])]
        rear_cut.NativeEquilibriumCut = True
        rear_cut.AccountingBody = [(geometry, [solids["rear"]])]
        analysis.addObject(rear_cut)

        # A native Reverse supplies the other reference orientation without
        # duplicating or inserting geometry into the physical mesh assembly.
        reverse = self.doc.addObject("Part::Reverse", "FrontCutOrientation")
        reverse.Source = geometry
        self.doc.recompute()
        original_face = geometry.getSubObject(faces["cut"])
        self.assertEqual(reverse.Source, geometry)
        matches = [
            index
            for index, face in enumerate(reverse.Shape.Faces, 1)
            if abs(face.CenterOfMass.z - 20) < 1e-7
            and abs(face.CenterOfMass.x - 5) < 1e-7
            and face.normalAt(0, 0).z < -0.99
        ]
        self.assertEqual(len(matches), 1)
        faces["front_cut"] = f"Face{matches[0]}"
        reversed_face = reverse.getSubObject(faces["front_cut"])
        self.assertAlmostEqual(reversed_face.Area, 100, places=10)
        self.assertAlmostEqual(original_face.distToShape(reversed_face)[0], 0, places=10)
        self.assertAlmostEqual(original_face.common(reversed_face).Area, 100, places=10)
        self.assertAlmostEqual(
            original_face.normalAt(0, 0).dot(reversed_face.normalAt(0, 0)), -1, places=10
        )
        front_cut = ObjectsFem.makeConstraintSectionPrint(self.doc, "FrontCut")
        front_cut.References = [(reverse, [faces["front_cut"]])]
        front_cut.NativeEquilibriumCut = True
        front_cut.AccountingBody = [(geometry, [solids["front"]])]
        analysis.addObject(front_cut)

        mesh = ObjectsFem.makeMeshGmsh(self.doc, "Mesh")
        mesh.Shape = geometry
        mesh.ElementOrder = "2nd"
        mesh.SecondOrderLinear = False
        mesh.CoherenceMesh = False
        mesh.CharacteristicLengthMax = 4
        mesh.CharacteristicLengthMin = 2
        mesh.WorkingDirectory = str(self.output)
        analysis.addObject(mesh)
        self.doc.recompute()
        mesher = gmshtools.GmshTools(mesh)
        mesher.create_mesh()
        self.assertEqual(mesher.process.exitCode(), 0)
        self.assertEqual(mesher.process.exitStatus(), mesher.process.ExitStatus.NormalExit)
        self.assertGreater(mesh.FemMesh.VolumeCount, 0)
        self.assertEqual(mesh.Shape, geometry)
        self.assertNotIn(reverse, analysis.Group)
        return SimpleNamespace(
            analysis=analysis,
            solver=solver,
            binary=binary,
            geometry=geometry,
            solids=solids,
            faces=faces,
            material=material,
            support=support,
            tie=tie,
            contact=contact,
            gravity=gravity,
            rear_cut=rear_cut,
            front_cut=front_cut,
            reverse=reverse,
            mesh=mesh,
        )

    def _group_elements(self, model, name):
        mesh = model.mesh.FemMesh
        groups = [group for group in mesh.Groups if mesh.getGroupName(group) == name]
        self.assertEqual(len(groups), 1, name)
        result = set(mesh.getGroupElements(groups[0]))
        self.assertTrue(result, name)
        return result

    def _owned_surface_oracle(self, model):
        """Complete native Tet10 incidence, independently of CAD node lookup."""
        mesh = model.mesh.FemMesh
        masks = {
            1: (0, 1, 2, 4, 5, 6),
            2: (0, 1, 3, 4, 7, 8),
            3: (0, 2, 3, 6, 7, 9),
            4: (1, 2, 3, 5, 8, 9),
        }
        incidence = {}
        for element in mesh.Volumes:
            nodes = mesh.getElementNodes(element)
            self.assertEqual(len(nodes), 10)
            for side, indices in masks.items():
                key = frozenset(nodes[index] for index in indices)
                incidence.setdefault(key, []).append((element, side))

        def owned_facets(face, solid, adjacency):
            owners = self._group_elements(model, solid)
            result = set()
            for element in self._group_elements(model, face):
                nodes = frozenset(mesh.getElementNodes(element))
                self.assertEqual(len(nodes), 6)
                adjacent = incidence[nodes]
                self.assertEqual(len(adjacent), adjacency)
                owned = [pair for pair in adjacent if pair[0] in owners]
                self.assertEqual(len(owned), 1)
                self.assertNotIn(owned[0], result)
                result.add(owned[0])
            return result

        for slave, master in (("tie_slave", "tie_master"), ("contact_slave", "contact_master")):
            side_nodes = [
                {
                    node
                    for face in self._group_elements(model, model.faces[name])
                    for node in mesh.getElementNodes(face)
                }
                for name in (slave, master)
            ]
            self.assertFalse(side_nodes[0] & side_nodes[1])
        return {
            "TIE_DEP"
            + model.tie.Name: owned_facets(model.faces["tie_slave"], model.solids["rear"], 1),
            "TIE_IND"
            + model.tie.Name: owned_facets(model.faces["tie_master"], model.solids["base"], 1),
            "DEP"
            + model.contact.Name: owned_facets(
                model.faces["contact_slave"], model.solids["sidepad"], 1
            ),
            "IND"
            + model.contact.Name: owned_facets(
                model.faces["contact_master"], model.solids["rear"], 1
            ),
            "SECTIONFACE"
            + model.rear_cut.Name: owned_facets(model.faces["cut"], model.solids["rear"], 2),
            "SECTIONFACE"
            + model.front_cut.Name: owned_facets(model.faces["cut"], model.solids["front"], 2),
        }

    @staticmethod
    def _mesh_snapshot(model):
        mesh = model.mesh.FemMesh
        return (
            {node: tuple(point) for node, point in mesh.Nodes.items()},
            {
                element: tuple(mesh.getElementNodes(element))
                for element in mesh.getIdByElementType("All")
            },
            [
                (
                    mesh.getGroupName(group),
                    mesh.getGroupElementType(group),
                    tuple(mesh.getGroupElements(group)),
                )
                for group in mesh.Groups
            ],
            list(model.mesh.ElementGroupNames),
            list(model.mesh.ElementGroupReferences),
            model.mesh.ElementGroupGeometry,
        )

    def _stock_write_and_solve(self, model):
        expected_surfaces = self._owned_surface_oracle(model)
        mesh_before = self._mesh_snapshot(model)
        fea = FemToolsCcx(analysis=model.analysis, solver=model.solver)
        fea.update_objects()
        fea.setup_working_dir(str(self.output))
        fea.write_inp_file()
        deck = Path(fea.inp_file_name)
        deck_hash = self._file_hash(deck)
        request = deck.with_suffix(".accounting")
        request_hash = self._file_hash(request)
        text = deck.read_text()
        self.assertIn("*TIE, POSITION TOLERANCE=0, ADJUST=NO, NAME=TIE" + model.tie.Name, text)
        self.assertIn("*CONTACT PAIR", text)
        self.assertNotIn("LateralGuide", text)
        actual_surfaces, current = {}, None
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("**"):
                continue
            if line.startswith("*"):
                current = None
                if line.upper().startswith("*SURFACE,"):
                    current = next(
                        part.split("=", 1)[1].strip()
                        for part in line.split(",")
                        if part.strip().upper().startswith("NAME=")
                    )
                    self.assertNotIn(current, actual_surfaces)
                    actual_surfaces[current] = set()
            elif current:
                element, side = [part.strip() for part in line.split(",")]
                self.assertTrue(side.startswith("S"))
                pair = (int(element), int(side[1:]))
                self.assertNotIn(pair, actual_surfaces[current])
                actual_surfaces[current].add(pair)
        for name, expected in expected_surfaces.items():
            self.assertEqual(actual_surfaces[name], expected, name)
        self.assertEqual(self._mesh_snapshot(model), mesh_before)
        code = fea.ccx_run()
        (self.output / "solver.stdout").write_text(fea.ccx_stdout)
        (self.output / "solver.stderr").write_text(fea.ccx_stderr)
        self.assertEqual(code, 0, fea.ccx_stdout + fea.ccx_stderr)
        self.assertEqual(Path(fea.ccx_binary).resolve(), model.binary.resolve())
        self.assertEqual(self._file_hash(deck), deck_hash)
        self.assertEqual(self._file_hash(request), request_hash)
        self.assertEqual(self._mesh_snapshot(model), mesh_before)
        accounting = next(
            item
            for item in model.analysis.Group
            if isinstance(getattr(item, "Proxy", None), force_accounting.AccountingResult)
            and item.Status.startswith("Current")
        )
        self.assertTrue(accounting.Status.startswith("Current"), accounting.Status)
        data = json.loads(accounting.AccountingData)
        self.assertEqual(data["schema"], force_accounting.SCHEMA)
        model.fea = fea
        model.accounting = accounting
        model.data = data
        return model

    def _assert_wrench(self, data, kind, name, wanted):
        actual = data["wrenches"][kind][name]
        force = App.Vector(*wanted[:3])
        moment = App.Vector(*wanted[3:])
        self.assertLessEqual(
            (App.Vector(*actual[:3]) - force).Length / max(force.Length, 1),
            0.01,
            (kind, name, "force", actual, wanted),
        )
        self.assertLessEqual(
            (App.Vector(*actual[3:]) - moment).Length / max(moment.Length, 1),
            0.01,
            (kind, name, "origin moment", actual, wanted),
        )

    def test_mixed_tie_contact_bodies_preserve_paired_physical_cut_equilibrium(self):
        model = self._stock_write_and_solve(self._make_native_model())
        for actual, obj, subelement in (
            (model.rear_cut.AccountingBody, model.geometry, model.solids["rear"]),
            (model.front_cut.AccountingBody, model.geometry, model.solids["front"]),
            (model.rear_cut.References, model.geometry, model.faces["cut"]),
            (model.front_cut.References, model.reverse, model.faces["front_cut"]),
        ):
            self.assertEqual([(item, list(subs)) for item, subs in actual], [(obj, [subelement])])
        weight = 1000 * 1e-9 * 7900 * model.gravity.GravityAcceleration.getValueAs("m/s^2").Value
        rear = model.rear_cut.Name
        front = model.front_cut.Name
        for kind, name, wanted in (
            (
                "SUPPORT",
                model.support.Name,
                [100, 0, 100 + 4 * weight, 500 + 20 * weight, 1000 - 30 * weight, -500],
            ),
            ("CUT", rear, [0, 0, -100 - weight, -500 - 5 * weight, 500 + 5 * weight, 0]),
            ("LOAD", rear, [0, 0, -weight, -5 * weight, 5 * weight, 0]),
            ("CONTACT", rear, [-100, 0, -weight, -5 * weight, -1500 + 15 * weight, 500]),
            ("MPC", rear, [100, 0, 100 + 3 * weight, 500 + 15 * weight, 1000 - 25 * weight, -500]),
            ("CUT", front, [0, 0, 100 + weight, 500 + 5 * weight, -500 - 5 * weight, 0]),
            ("LOAD", front, [0, 0, -100 - weight, -500 - 5 * weight, 500 + 5 * weight, 0]),
            ("CONTACT", front, [0] * 6),
            ("MPC", front, [0] * 6),
        ):
            with self.subTest(kind=kind, name=name):
                self._assert_wrench(model.data, kind, name, wanted)
        rear_values = model.data["wrenches"]["CUT"][rear]
        front_values = model.data["wrenches"]["CUT"][front]
        for offset in (0, 3):
            end = offset + 3
            rear_vector = App.Vector(*rear_values[offset:end])
            front_vector = App.Vector(*front_values[offset:end])
            self.assertLessEqual(
                (rear_vector + front_vector).Length / max(front_vector.Length, 1), 0.01
            )
        (self.output / "analytical-accounting.json").write_text(
            json.dumps(model.data, indent=2) + "\n"
        )

    def test_mixed_native_interfaces_keep_independent_nonzero_original_displacements(self):
        model = self._stock_write_and_solve(self._make_native_model(face_support=True))
        result = ObjectsFem.makeResultContactObservation(
            self.doc, model.analysis, model.accounting, [model.contact, model.tie]
        )
        result.Proxy.refresh(result)
        self.assertTrue(result.Status.startswith("Available"), result.Status)
        data = result.Proxy.getObservations(result)
        self.assertEqual(data["schema"], "FreeCAD.INTERFACE_SIDE_OBSERVATION_V2")
        self.assertEqual([row["constraint_kind"] for row in data["contacts"]], ["Contact", "Tie"])
        self.assertEqual(
            [row["contact"] for row in data["contacts"]], [model.contact.Name, model.tie.Name]
        )
        row = data["contacts"][1]
        self.assertEqual(
            row["references_slave_then_master"],
            [
                [model.geometry.Name, [model.faces["tie_slave"]]],
                [model.geometry.Name, [model.faces["tie_master"]]],
            ],
        )
        field = read_frd_result(str(Path(model.fea.inp_file_name).with_suffix(".frd")))
        displacement = field["Results"][-1]["disp"]
        point = App.Vector(*row["point_mm"])
        expected_nodes = []
        native = model.mesh.FemMesh
        for side, owner in (("slave", "rear"), ("master", "base")):
            nodes = {
                node
                for element in self._group_elements(model, model.solids[owner])
                for node in native.getElementNodes(element)
            }
            matching = [node for node in nodes if (native.getNodeById(node) - point).Length < 1e-10]
            self.assertEqual(len(matching), 1)
            node = matching[0]
            expected_nodes.append(node)
            actual = row[side]
            self.assertEqual(actual["method"], "ORIGINAL_NODE")
            self.assertEqual(actual["original_node_id"], node)
            self.assertEqual(actual["source_node_ids"], [node])
            self.assertEqual(actual["value_mm"], list(displacement[node]))
            self.assertGreater(App.Vector(*displacement[node]).Length, 1e-9)
            self.assertEqual(tuple(native.getNodeById(node)), tuple(point))
        self.assertNotEqual(*expected_nodes)
        self.assertEqual(data["source"]["accounting"]["name"], model.accounting.Name)
        self.assertFalse(data["engineering_acceptance"])

    def test_nonconformal_tie_uses_native_master_surface_without_an_original_query_node(self):
        slave = self.doc.addObject("Part::Box", "Slave")
        slave.Length, slave.Width, slave.Height = 2, 1.1, 0.9
        slave.Placement.Base = App.Vector(0, 1.3, 1.7)
        master = self.doc.addObject("Part::Box", "Master")
        master.Length, master.Width, master.Height = 2, 5, 5
        master.Placement.Base = App.Vector(2, 0, 0)
        geometry = self.doc.addObject("Part::Compound", "Geometry")
        geometry.Links = [slave, master]
        analysis = ObjectsFem.makeAnalysis(self.doc)
        solver = ObjectsFem.makeSolverCalculiXCcxTools(self.doc)
        solver.NativeForceAccounting = True
        candidate = os.environ.get("FREECAD_9ZT_PRODUCTION_CCX")
        if candidate:
            solver.NativeAccountingSolver = candidate
        binary = Path(force_accounting.solver_binary(solver))
        if not binary.is_file() or not os.access(binary, os.X_OK):
            self.skipTest("Qualified native force-accounting solver is unavailable")
        force_accounting.require_capability(binary)
        analysis.addObject(solver)
        material = ObjectsFem.makeMaterialSolid(self.doc)
        material.Material = {
            "Name": "Steel",
            "YoungsModulus": "200000 MPa",
            "PoissonRatio": "0.3",
            "Density": "7900 kg/m^3",
        }
        analysis.addObject(material)
        support = ObjectsFem.makeConstraintRigidBody(self.doc, "MasterSupport")
        support.References = [(master, ["Face2"])]
        support.ReferenceNode = App.Vector(5, 0, 0)
        for kind in ("Translational", "Rotational"):
            for axis in "XYZ":
                setattr(support, kind + "Mode" + axis, "Constraint")
        analysis.addObject(support)
        tie = ObjectsFem.makeConstraintTie(self.doc, "NonconformalOrdinaryTie")
        tie.References = [(slave, ["Face2"]), (master, ["Face1"])]
        tie.Tolerance = 0
        tie.Adjust = False
        analysis.addObject(tie)
        pressure = ObjectsFem.makeConstraintPressure(self.doc)
        pressure.References = [(slave, ["Face1"])]
        pressure.Pressure = "1 MPa"
        analysis.addObject(pressure)
        gravity = ObjectsFem.makeConstraintSelfWeight(self.doc)
        gravity.GravityAcceleration = "9.81 m/s^2"
        analysis.addObject(gravity)
        mesh = ObjectsFem.makeMeshGmsh(self.doc, "Mesh")
        mesh.Shape = geometry
        mesh.ElementOrder = "2nd"
        mesh.SecondOrderLinear = True
        mesh.CoherenceMesh = False
        mesh.CharacteristicLengthMax = 1.4
        mesh.CharacteristicLengthMin = 0.4
        mesh.WorkingDirectory = str(self.output)
        analysis.addObject(mesh)
        self.doc.recompute()
        mesher = gmshtools.GmshTools(mesh)
        mesher.create_mesh()
        self.assertEqual(mesher.process.exitCode(), 0)
        self.assertEqual(mesher.process.exitStatus(), mesher.process.ExitStatus.NormalExit)
        model = SimpleNamespace(mesh=mesh)
        native = mesh.FemMesh
        point = slave.getSubObject("Face2").Vertexes[0].Point
        owner_nodes = [
            {
                node
                for element in self._group_elements(model, solid)
                for node in native.getElementNodes(element)
            }
            for solid in ("Solid1", "Solid2")
        ]
        matching = [
            [node for node in nodes if (native.getNodeById(node) - point).Length < 1e-10]
            for nodes in owner_nodes
        ]
        self.assertEqual(tuple(map(len, matching)), (1, 0))
        self.assertFalse(owner_nodes[0] & owner_nodes[1])
        mesh_before = self._mesh_snapshot(model)
        fea = FemToolsCcx(analysis=analysis, solver=solver)
        fea.update_objects()
        fea.setup_working_dir(str(self.output))
        fea.write_inp_file()
        deck = Path(fea.inp_file_name)
        original_deck = self._file_hash(deck)
        self.assertIn("*TIE, POSITION TOLERANCE=0, ADJUST=NO", deck.read_text())
        self.assertNotIn("*CONTACT PAIR", deck.read_text())
        self.assertEqual(fea.ccx_run(), 0, fea.ccx_stdout + fea.ccx_stderr)
        self.assertEqual(self._file_hash(deck), original_deck)
        self.assertEqual(self._mesh_snapshot(model), mesh_before)
        accounting = next(
            item
            for item in analysis.Group
            if isinstance(getattr(item, "Proxy", None), force_accounting.AccountingResult)
        )
        self.assertTrue(accounting.Status.startswith("Current"), accounting.Status)
        result = ObjectsFem.makeResultContactObservation(self.doc, analysis, accounting, [tie])
        result.Proxy.refresh(result)
        self.assertTrue(result.Status.startswith("Available"), result.Status)
        data = result.Proxy.getObservations(result)
        self.assertEqual(data["schema"], "FreeCAD.INTERFACE_SIDE_OBSERVATION_V2")
        row = data["contacts"][0]
        self.assertEqual(row["constraint_kind"], "Tie")
        self.assertEqual(row["point_mm"], list(point))
        self.assertEqual(row["slave"]["method"], "ORIGINAL_NODE")
        self.assertEqual(row["slave"]["original_node_id"], matching[0][0])
        self.assertEqual(row["master"]["method"], "NATIVE_VTK_SURFACE")
        self.assertEqual(row["master"]["status"], "AVAILABLE")
        self.assertTrue(row["master"]["source_element_ids"])
        self.assertLessEqual(
            set(row["master"]["source_element_ids"]), self._group_elements(model, "Face7")
        )
        self.assertLessEqual(set(row["master"]["source_node_ids"]), owner_nodes[1])
        self.assertTrue(all(math.isfinite(value) for value in row["master"]["value_mm"]))
        self.assertGreater(App.Vector(*row["master"]["value_mm"]).Length, 1e-9)
        displacement = read_frd_result(str(deck.with_suffix(".frd")))["Results"][-1]["disp"]
        self.assertEqual(row["slave"]["value_mm"], list(displacement[matching[0][0]]))
        self.assertGreater(App.Vector(*row["slave"]["value_mm"]).Length, 1e-9)

    def test_tie_edits_fail_closed_and_saved_native_observation_remains_historical(self):
        model = self._stock_write_and_solve(self._make_native_model(face_support=True))
        result = ObjectsFem.makeResultContactObservation(
            self.doc, model.analysis, model.accounting, [model.tie, model.contact]
        )
        result.Proxy.refresh(result)
        self.assertTrue(result.Status.startswith("Available"), result.Status)
        result.Proxy.getObservations(result)
        raw = result.ObservationData
        raw_hash = result.ObservationHash
        self.assertEqual(raw_hash, hashlib.sha256(raw.encode()).hexdigest())
        result.PointSide = "Master"
        self.assertTrue(result.Status.startswith("Stale"), result.Status)
        with self.assertRaises(ValueError):
            result.Proxy.getObservations(result)
        self.assertEqual((result.ObservationData, result.ObservationHash), (raw, raw_hash))
        result.PointSide = "Slave"
        result.Proxy.refresh(result)
        self.assertTrue(result.Status.startswith("Available"), result.Status)
        result.Proxy.getObservations(result)
        raw, raw_hash = result.ObservationData, result.ObservationHash

        references = list(model.tie.References)
        model.tie.References = [
            (
                model.geometry,
                [model.faces["tie_slave"], model.faces["tie_master"], model.faces["support"]],
            )
        ]
        result.Proxy.refresh(result)
        self.assertIn("one independent face per side", result.Status)
        with self.assertRaises(ValueError):
            result.Proxy.getObservations(result)
        self.assertEqual((result.ObservationData, result.ObservationHash), (raw, raw_hash))
        model.tie.References = references
        for property_name in ("Adjust", "CyclicSymmetry"):
            with self.subTest(unsupported=property_name):
                setattr(model.tie, property_name, True)
                result.Proxy.refresh(result)
                self.assertIn("ADJUST=NO without cyclic symmetry", result.Status)
                with self.assertRaises(ValueError):
                    result.Proxy.getObservations(result)
                self.assertEqual((result.ObservationData, result.ObservationHash), (raw, raw_hash))
                setattr(model.tie, property_name, False)
        self.assertTrue(model.accounting.Status.startswith("Stale"), model.accounting.Status)

        # Restoring physical inputs is not provenance repair. Only the ordinary
        # writer/solver establishes a fresh current source after those edits.
        old_accounting = model.accounting
        model = self._stock_write_and_solve(model)
        self.assertNotEqual(model.accounting, old_accounting)
        self.assertTrue(old_accounting.Status.startswith("Stale"), old_accounting.Status)
        result.AccountingResult = model.accounting
        result.Proxy.refresh(result)
        self.assertTrue(result.Status.startswith("Available"), result.Status)
        data = result.Proxy.getObservations(result)
        self.assertEqual(data["schema"], "FreeCAD.INTERFACE_SIDE_OBSERVATION_V2")
        raw, raw_hash = result.ObservationData, result.ObservationHash
        accounting_raw = model.accounting.AccountingData
        self.assertEqual(json.loads(accounting_raw)["movement_source"]["status"], "BOUND")
        self.doc.recompute()
        document_path = self.output / "tie-observation.FCStd"
        self.doc.saveAs(str(document_path))
        self.assertTrue(model.accounting.Status.startswith("Current"), model.accounting.Status)
        result.Proxy.getObservations(result)
        case = {
            "scope": "native Tie observation persistence; not engineering acceptance",
            "document": str(document_path),
            "document_sha256": self._file_hash(document_path),
            "version": App.Version(),
            "analysis": model.analysis.Name,
            "solver": model.solver.Name,
            "mesh": model.mesh.Name,
            "accounting": model.accounting.Name,
            "result": result.Name,
            "tie": model.tie.Name,
            "contact": model.contact.Name,
            "geometry": model.geometry.Name,
            "reverse": model.reverse.Name,
            "rear_cut": model.rear_cut.Name,
            "front_cut": model.front_cut.Name,
            "observation_sha256": hashlib.sha256(raw.encode()).hexdigest(),
            "observation_hash": raw_hash,
            "accounting_sha256": hashlib.sha256(accounting_raw.encode()).hexdigest(),
            "movement_source": json.loads(accounting_raw)["movement_source"],
            "observed_time": data["source"]["observed_time"],
            "requested_end_time": data["source"]["requested_end_time"],
            "frd": data["source"]["frd"],
            "definition": data["definition"],
            "schema": data["schema"],
            "point_side": result.PointSide,
            "slave_vertex": result.SlaveVertex,
            "master_vertex": result.MasterVertex,
        }
        case_path = self.output / "tie-cold-case.json"
        case_path.write_text(json.dumps(case, indent=2) + "\n")
        App.Console.PrintMessage("TIE_ACCOUNTING_COLD_CASE=" + str(case_path) + "\n")
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(str(document_path))
        restored = self.doc.getObject(case["result"])
        accounting = self.doc.getObject(case["accounting"])
        self.assertTrue(restored.Status.startswith("Historical"), restored.Status)
        self.assertTrue(accounting.Status.startswith("Stale"), accounting.Status)
        self.assertEqual((restored.ObservationData, restored.ObservationHash), (raw, raw_hash))
        self.assertEqual(accounting.AccountingData, accounting_raw)
        with self.assertRaises(ValueError):
            restored.Proxy.getObservations(restored)
        self.doc.recompute()
        self.assertTrue(restored.Status.startswith("Historical"), restored.Status)
        with self.assertRaises(ValueError):
            restored.Proxy.getObservations(restored)
        # Explicit refresh may revalidate identical original IDs and bytes, as
        # for legacy Contact results, but cannot make historical accounting
        # Current or repair a renumbered native field.
        restored.Proxy.refresh(restored)
        self.assertTrue(accounting.Status.startswith("Stale"), accounting.Status)
        if restored.Status.startswith("Available"):
            refreshed = restored.Proxy.getObservations(restored)
            self.assertEqual(refreshed["source"]["accounting"]["name"], case["accounting"])
        else:
            with self.assertRaises(ValueError):
                restored.Proxy.getObservations(restored)
            self.assertEqual((restored.ObservationData, restored.ObservationHash), (raw, raw_hash))
