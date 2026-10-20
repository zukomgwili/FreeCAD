# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native moving finite-face RBE/elastic-port and physical-support accounting.

These are small analytical software fixtures, not stress, mesh-convergence,
anchorage or building-design acceptance. Native outputs are retained in private
temporary directories. No deck patches or accounting-force helpers are used.
"""

import hashlib
import json
import math
import os
import re
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
from feminout import importCcxDatResults
from feminout.importCcxFrdResults import read_frd_result
from femtools import force_accounting
from femtools.ccxtools import FemToolsCcx
from femtools.femutils import is_of_type


@unittest.skipUnless(shutil.which("gmsh"), "Native Gmsh executable required")
class TestMovingPortAccountingNative(unittest.TestCase):
    def setUp(self):
        try:
            Fem.FemMesh().toVTK()
        except NotImplementedError:
            self.skipTest("Native VTK Python wrappers are unavailable in this build")
        self.doc = App.newDocument("MovingPortAccountingNative")
        self.output = Path(tempfile.mkdtemp(prefix="freecad-moving-port-accounting-native-"))

    def tearDown(self):
        if self.doc is not None and self.doc.Name in App.listDocuments():
            App.closeDocument(self.doc.Name)

    @staticmethod
    def _sha(path):
        with Path(path).open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()

    def _make_model(self, ordinary=False):
        analysis = ObjectsFem.makeAnalysis(self.doc)
        solver = ObjectsFem.makeSolverCalculiXCcxTools(self.doc)
        solver.NativeForceAccounting = True
        solver.SplitInputWriter = False
        solver.AnalysisType = "static"
        candidate = os.environ.get("FREECAD_9ZT_PRODUCTION_CCX")
        if candidate:
            solver.NativeAccountingSolver = candidate
        binary = Path(force_accounting.solver_binary(solver))
        if not binary.is_file() or not os.access(binary, os.X_OK):
            self.skipTest("Qualified native force-accounting solver is unavailable")
        force_accounting.require_capability(binary)
        analysis.addObject(solver)
        geometry = self.doc.addObject("Part::Feature", "BeamCells")
        intervals = ((1, 1.75), (1.75, 2.25), (2.25, 3)) if ordinary else ((1, 3),)
        beam_a = booleanFragments(
            [
                Part.makeBox(5, upper - lower, 2, App.Vector(x, lower, 2))
                for x in (0, 5)
                for lower, upper in intervals
            ],
            "CompSolid",
        )
        beam_b = booleanFragments(
            [Part.makeBox(5, 2, 2, App.Vector(x, 1, 2)) for x in (20, 25)], "CompSolid"
        )
        geometry.Shape = Part.makeCompound([beam_a, beam_b])
        self.doc.recompute()
        self.assertEqual(len(geometry.Shape.Solids), 8 if ordinary else 4)
        self.assertAlmostEqual(geometry.Shape.Volume, 80, places=9)

        def faces_at(owner, x, normal):
            return [
                f"Face{index}"
                for index, face in enumerate(owner.Shape.Faces, 1)
                if abs(face.CenterOfMass.x - x) < 1e-8 and face.normalAt(0, 0).x * normal > 0.99
            ]

        def solids_at(x):
            return [
                f"Solid{index}"
                for index, solid in enumerate(geometry.Shape.Solids, 1)
                if abs(solid.CenterOfMass.x - x) < 1e-8
            ]

        faces = {
            "external": faces_at(geometry, 0, -1),
            "moving_a": faces_at(geometry, 10, 1),
            "moving_b": faces_at(geometry, 20, -1),
            "load": faces_at(geometry, 30, 1),
        }
        for name, count, centre in (
            ("moving_a", len(intervals), App.Vector(10, 2, 3)),
            ("moving_b", 1, App.Vector(20, 2, 3)),
        ):
            self.assertEqual(len(faces[name]), count)
            shapes = [geometry.getSubObject(face) for face in faces[name]]
            area = sum(shape.Area for shape in shapes)
            actual = sum((shape.CenterOfMass * shape.Area for shape in shapes), App.Vector()) / area
            self.assertAlmostEqual(area, 4, places=9)
            self.assertLess((actual - centre).Length, 1e-8)
            self.assertTrue(all(shape.ShapeType == "Face" for shape in shapes))
        material = ObjectsFem.makeMaterialSolid(self.doc)
        material.Material = {
            "Name": "Moving-port analytical witness",
            "YoungsModulus": "20000 MPa",
            "PoissonRatio": "0.3",
            "Density": "1 kg/m^3",
        }
        analysis.addObject(material)
        if ordinary:
            self.assertEqual(len(faces["external"]), 3)
            faces["fixed"] = [
                name
                for name in faces["external"]
                if abs(geometry.getSubObject(name).CenterOfMass.y - 1.375) < 1e-8
            ]
            faces["partial"] = [
                name
                for name in faces["external"]
                if abs(geometry.getSubObject(name).CenterOfMass.y - 2.625) < 1e-8
            ]
            for name in ("fixed", "partial"):
                self.assertEqual(len(faces[name]), 1)
                self.assertAlmostEqual(geometry.getSubObject(faces[name][0]).Area, 1.5, places=9)
            self.assertAlmostEqual(
                geometry.getSubObject(faces["fixed"][0]).distToShape(
                    geometry.getSubObject(faces["partial"][0])
                )[0],
                0.5,
                places=9,
            )
            fixed = ObjectsFem.makeConstraintFixed(self.doc, "FixedPatch")
            fixed.References = [(geometry, faces["fixed"])]
            partial = ObjectsFem.makeConstraintDisplacement(self.doc, "PartialAxialPatch")
            partial.References = [(geometry, faces["partial"])]
            partial.xFree, partial.yFree, partial.zFree = False, True, True
            partial.xDisplacement = "0 mm"
            supports = [fixed, partial]
        else:
            fixed = ObjectsFem.makeConstraintRigidBody(self.doc, "ExternalSupport")
            fixed.References = [(geometry, faces["external"])]
            fixed.ReferenceNode = App.Vector(0, 2, 3)
            for kind in ("Translational", "Rotational"):
                for axis in "XYZ":
                    setattr(fixed, kind + "Mode" + axis, "Constraint")
            supports = [fixed]
        for support in supports:
            analysis.addObject(support)
        solver.NativeAccountingSupports = supports
        ports = []
        for name, key, x in (("MovingPortA", "moving_a", 10), ("MovingPortB", "moving_b", 20)):
            port = ObjectsFem.makeConstraintRigidBody(self.doc, name)
            port.References = [(geometry, faces[key])]
            port.ReferenceNode = App.Vector(x, 2, 3)
            for kind in ("Translational", "Rotational"):
                for axis in "XYZ":
                    setattr(port, kind + "Mode" + axis, "Free")
            analysis.addObject(port)
            ports.append(port)
        connectors = []
        for kind, prefix in (("Translational", "T"), ("Rotational", "R")):
            for axis in "XYZ":
                connector = ObjectsFem.makeConstraintElasticConnector(
                    self.doc, "Connector" + prefix + axis
                )
                connector.Attachment = "Rigid body ports"
                connector.Mode = "Two points"
                connector.Kind, connector.Axis = kind, axis
                connector.Orientation = App.Rotation()
                connector.RigidBody1, connector.RigidBody2 = ports
                if kind == "Translational":
                    connector.Stiffness = "1200 N/mm"
                else:
                    connector.RotationalStiffness = App.Units.Quantity("6000 N*mm/rad")
                analysis.addObject(connector)
                connectors.append(connector)

        def end_edge(y):
            names = [
                f"Edge{index}"
                for index, edge in enumerate(geometry.Shape.Edges, 1)
                if all(
                    abs(vertex.Point.x - 30) < 1e-8 and abs(vertex.Point.y - y) < 1e-8
                    for vertex in edge.Vertexes
                )
                and abs(edge.Length - 2) < 1e-8
            ]
            self.assertEqual(len(names), 1, (y, names))
            return names[0]

        for name, names, amount, direction in (
            ("AxialLoad", faces["load"], 12, App.Vector(1, 0, 0)),
            ("TorquePositiveZ", [end_edge(3)], 3, App.Vector(0, 0, 1)),
            ("TorqueNegativeZ", [end_edge(1)], 3, App.Vector(0, 0, -1)),
        ):
            line = self.doc.addObject("Part::Feature", name + "Direction")
            line.Shape = Part.makeLine(App.Vector(), direction)
            load = ObjectsFem.makeConstraintForce(self.doc, name)
            load.References = [(geometry, names)]
            load.Force, load.Direction, load.Reversed = f"{amount} N", (line, ["Edge1"]), False
            analysis.addObject(load)
        cuts = []
        owners = {"CutARight": solids_at(7.5), "CutBLeft": solids_at(22.5)}
        self.assertEqual(len(owners["CutARight"]), len(intervals))
        self.assertEqual(len(owners["CutBLeft"]), 1)
        for name, x, normal, count in (
            ("CutARight", 5, -1, len(intervals)),
            ("CutBLeft", 25, 1, 1),
        ):
            owner = geometry
            names = faces_at(owner, x, normal)
            if not names:
                owner = self.doc.addObject("Part::Reverse", name + "Orientation")
                owner.Source = geometry
                self.doc.recompute()
                names = faces_at(owner, x, normal)
            self.assertEqual(len(names), count)
            self.assertAlmostEqual(
                sum(owner.getSubObject(item).Area for item in names), 4, places=9
            )
            cut = ObjectsFem.makeConstraintSectionPrint(self.doc, name)
            cut.References = [(owner, names)]
            cut.AccountingBody = [(geometry, owners[name])]
            cut.NativeEquilibriumCut = True
            analysis.addObject(cut)
            cuts.append(cut)
        mesh = ObjectsFem.makeMeshGmsh(self.doc, "Mesh")
        mesh.Shape, mesh.ElementOrder = geometry, "2nd"
        mesh.SecondOrderLinear, mesh.CoherenceMesh = False, False
        mesh.CharacteristicLengthMax, mesh.CharacteristicLengthMin = 1.5, 0.75
        mesh.WorkingDirectory = str(self.output)
        analysis.addObject(mesh)
        self.doc.recompute()
        mesher = gmshtools.GmshTools(mesh)
        mesher.create_mesh()
        self.assertEqual(mesher.process.exitCode(), 0)
        self.assertEqual(mesher.process.exitStatus(), mesher.process.ExitStatus.NormalExit)
        self.assertGreater(mesh.FemMesh.VolumeCount, 0)
        groups = {
            mesh.FemMesh.getGroupName(group): set(mesh.FemMesh.getGroupElements(group))
            for group in mesh.FemMesh.Groups
        }
        memberships = {
            name: {
                node
                for face in names
                for node in mesh.FemMesh.getNodesByFace(geometry.getSubObject(face))
            }
            for name, names in faces.items()
        }
        for nodes in memberships.values():
            self.assertGreaterEqual(len(nodes), 3)
        self.assertFalse(memberships["moving_a"] & memberships["moving_b"])
        if ordinary:
            self.assertFalse(memberships["fixed"] & memberships["partial"])
            for key in ("fixed", "partial"):
                self.assertTrue(
                    all(abs(mesh.FemMesh.Nodes[node].x) < 1e-8 for node in memberships[key])
                )
        cell_nodes = {
            f"Solid{index}": {
                node
                for element in groups[f"Solid{index}"]
                for node in mesh.FemMesh.getElementNodes(element)
            }
            for index in range(1, len(geometry.Shape.Solids) + 1)
        }
        beam_cells = [
            [
                f"Solid{index}"
                for index, solid in enumerate(geometry.Shape.Solids, 1)
                if lower < solid.CenterOfMass.x < upper
            ]
            for lower, upper in ((0, 10), (20, 30))
        ]
        self.assertFalse(
            set().union(*(cell_nodes[name] for name in beam_cells[0]))
            & set().union(*(cell_nodes[name] for name in beam_cells[1]))
        )
        for names in beam_cells:
            graph = {name: set() for name in names}
            for index, left in enumerate(names):
                for right in names[index + 1 :]:
                    shared = [
                        face
                        for face in geometry.getSubObject(left).Faces
                        if any(face.isSame(other) for other in geometry.getSubObject(right).Faces)
                    ]
                    for face in shared:
                        face_names = [
                            f"Face{i}"
                            for i, entity in enumerate(geometry.Shape.Faces, 1)
                            if entity.isSame(face)
                        ]
                        self.assertEqual(len(face_names), 1)
                        nodes = {
                            node
                            for element in groups[face_names[0]]
                            for node in mesh.FemMesh.getElementNodes(element)
                        }
                        self.assertGreaterEqual(len(nodes), 6)
                        self.assertLessEqual(nodes, cell_nodes[left] & cell_nodes[right])
                        self.assertEqual(nodes, set(mesh.FemMesh.getNodesByFace(face)))
                        graph[left].add(right)
                        graph[right].add(left)
            visited, pending = set(), [names[0]]
            while pending:
                current = pending.pop()
                if current not in visited:
                    visited.add(current)
                    pending.extend(graph[current] - visited)
            self.assertEqual(visited, set(names))
        if ordinary:
            for names in owners.values():
                nodes = set().union(*(cell_nodes[name] for name in names))
                self.assertFalse(nodes & (memberships["fixed"] | memberships["partial"]))
        return SimpleNamespace(
            analysis=analysis,
            solver=solver,
            binary=binary,
            geometry=geometry,
            mesh=mesh,
            supports=supports,
            ports=ports,
            connectors=connectors,
            cuts=cuts,
            groups=groups,
            memberships=memberships,
            ordinary=ordinary,
        )

    @staticmethod
    def _stock_boundary(deck):
        sets, rows, loads = {}, [], []
        section = current = None
        generated = False
        for raw in deck.splitlines():
            line = raw.strip()
            if not line or line.startswith("**"):
                continue
            if line.startswith("*"):
                fields = [field.strip() for field in line.upper().split(",")]
                section = fields[0]
                if section == "*NSET":
                    current = next(
                        field.split("=", 1)[1] for field in fields[1:] if field.startswith("NSET=")
                    )
                    generated = "GENERATE" in fields[1:]
                    sets.setdefault(current, [])
                continue
            fields = [field.strip() for field in line.split(",") if field.strip()]
            if section == "*NSET":
                if generated:
                    start, stop = map(int, fields[:2])
                    stride = int(fields[2]) if len(fields) == 3 else 1
                    sets[current].extend(range(start, stop + 1, stride))
                else:
                    sets[current].extend(
                        int(value) if value.isdigit() else value.upper() for value in fields
                    )
            elif section == "*BOUNDARY":
                node = int(fields[0]) if fields[0].isdigit() else fields[0].upper()
                first = int(fields[1])
                last = int(fields[2]) if len(fields) >= 3 else first
                rows.append((node, first, last, float(fields[3]) if len(fields) == 4 else 0.0))
            elif section == "*CLOAD":
                loads.append((int(fields[0]), int(fields[1]), float(fields[2])))

        def resolve(name, active=()):
            if isinstance(name, int):
                return {name}
            if name in active:
                raise ValueError("Cyclic literal node set")
            return set().union(*(resolve(item, active + (name,)) for item in sets[name]))

        boundary = [
            (node, direction, value)
            for target, first, last, value in rows
            for node in resolve(target)
            for direction in range(first, last + 1)
        ]
        return {name: resolve(name) for name in sets}, boundary, loads

    def _assert_vector(self, actual, reference, zero_scale, label):
        self.assertEqual(len(actual), 3)
        self.assertTrue(all(math.isfinite(value) for value in actual))
        target = App.Vector(*reference)
        scale = target.Length if target.Length else zero_scale
        self.assertLessEqual(
            (App.Vector(*actual) - target).Length / scale, 0.01, (label, actual, reference, scale)
        )

    def _assert_wrench(self, actual, reference, label):
        self.assertEqual(len(actual), 6)
        self._assert_vector(actual[:3], reference[:3], 12, label + "/force")
        self._assert_vector(actual[3:], reference[3:], math.sqrt(1908), label + "/origin moment")

    def _write(self, model, name):
        directory = self.output / name
        directory.mkdir()
        fea = FemToolsCcx(analysis=model.analysis, solver=model.solver)
        fea.update_objects()
        fea.setup_working_dir(str(directory))
        fea.write_inp_file()
        return fea

    def _assert_physical_spc_binding(self, model, deck, request):
        sets, boundary, _ = self._stock_boundary(deck)
        expected = {
            "FixedPatch": {
                (node, direction) for node in model.memberships["fixed"] for direction in (1, 2, 3)
            },
            "PartialAxialPatch": {(node, 1) for node in model.memberships["partial"]},
        }
        physical_nodes = set(model.mesh.FemMesh.Nodes)
        physical = [
            (node, direction, value)
            for node, direction, value in boundary
            if node in physical_nodes
        ]
        wanted = set().union(*expected.values())
        self.assertEqual(len(physical), len(wanted))
        self.assertEqual({(node, direction) for node, direction, _ in physical}, wanted)
        self.assertTrue(all(value == 0 for _, _, value in physical))
        self.assertEqual(sets["FIXEDPATCH"], model.memberships["fixed"])
        self.assertEqual(sets["PARTIALAXIALPATCH"], model.memberships["partial"])
        actual = {}
        lines = [line.strip() for line in request.splitlines() if line.strip()]
        for index, line in enumerate(lines):
            words = line.split()
            if words[0] == "SPC_SUPPORT":
                self.assertEqual(len(words), 3)
                self.assertNotIn(words[1], actual)
                count = int(words[2])
                self.assertGreater(count, 0)
                terms = [
                    tuple(map(int, row.split())) for row in lines[index + 1 : index + 1 + count]
                ]
                self.assertEqual(len(terms), count)
                self.assertEqual(len(set(terms)), count)
                actual[words[1]] = set(terms)
        self.assertEqual(actual, expected)
        self.assertNotRegex(request, r"(?m)^SUPPORT\s")
        helpers = {
            (node, direction) for node, direction, _ in boundary if node not in physical_nodes
        }
        self.assertTrue(helpers)
        self.assertFalse(helpers & wanted)

    def _solve_and_check(self, model):
        fea = self._write(model, "solve")
        deck = Path(fea.inp_file_name)
        request = deck.with_suffix(".accounting")
        deck_hash, request_hash = self._sha(deck), self._sha(request)
        text, request_text = deck.read_text(), request.read_text()
        self.assertEqual(request_text.splitlines()[0], "CCX_FORCE_ACCOUNTING_V3")
        self.assertNotIn("*TIE,", text)
        self.assertNotIn("*CONTACT PAIR", text)
        if model.ordinary:
            self._assert_physical_spc_binding(model, text, request_text)
        positions = model.mesh.FemMesh.Nodes
        _, _, loads = self._stock_boundary(text)
        total_force, total_moment = App.Vector(), App.Vector()
        self.assertTrue(loads)
        for node, direction, value in loads:
            if value:
                self.assertIn(node, positions)
                self.assertAlmostEqual(positions[node].x, 30, places=9)
                component = [0.0, 0.0, 0.0]
                component[direction - 1] = value
                force = App.Vector(*component)
                total_force += force
                total_moment += positions[node].cross(force)
        # Independent statics: +12N at (30,2,3); two opposite 3N end-edge
        # forces at y3/y1 form +6Nmm X torque. M is about the original origin.
        self._assert_wrench(
            list(total_force) + list(total_moment), [12, 0, 0, 6, 36, -24], "applied loads"
        )
        ids = {}
        for port in model.ports:
            rows = re.findall(
                r"^\*RIGID BODY, NSET="
                + re.escape(port.Name)
                + r", REF NODE=(\d+), ROT NODE=(\d+)\s*$",
                text,
                re.M | re.I,
            )
            self.assertEqual(len(rows), 1)
            ids[port.Name] = tuple(map(int, rows[0]))
        self.assertEqual(len(set(sum(ids.values(), ()))), 4)
        self.assertGreater(min(sum(ids.values(), ())), max(positions))
        self.assertEqual(fea.ccx_run(), 0, fea.ccx_stdout + fea.ccx_stderr)
        (self.output / "solver.stdout").write_text(fea.ccx_stdout)
        (self.output / "solver.stderr").write_text(fea.ccx_stderr)
        self.assertEqual(Path(fea.ccx_binary).resolve(), model.binary.resolve())
        self.assertEqual((self._sha(deck), self._sha(request)), (deck_hash, request_hash))
        self.assertEqual(
            deck.with_suffix(".accounting.out").read_text().splitlines()[0],
            "CCX_FORCE_ACCOUNTING_V3",
        )
        reports = [
            item
            for item in model.analysis.Group
            if is_of_type(item, "Fem::NativeForceAccountingResult")
        ]
        self.assertEqual(len(reports), 1)
        report = reports[0]
        self.assertTrue(report.Status.startswith("Current"), report.Status)
        literal = report.AccountingData
        data = json.loads(literal)
        self.assertEqual(data["schema"], "CCX_FORCE_ACCOUNTING_V3")
        self.assertEqual(data["movement_source"]["status"], "BOUND")
        self.assertEqual(data["movement_source"]["sha256"], self._sha(deck.with_suffix(".frd")))
        wrenches = data["wrenches"]
        self.assertEqual(set(wrenches), {"SUPPORT", "CUT", "LOAD", "CONTACT", "MPC"})
        self.assertEqual(set(wrenches["SUPPORT"]), {item.Name for item in model.supports})
        for wrench in wrenches["SUPPORT"].values():
            self.assertTrue(all(math.isfinite(value) for value in wrench))
        aggregate = [
            sum(wrench[index] for wrench in wrenches["SUPPORT"].values()) for index in range(6)
        ]
        self._assert_wrench(aggregate, [-12, 0, 0, -6, -36, 24], "aggregate physical support")
        if model.ordinary:
            partial = wrenches["SUPPORT"]["PartialAxialPatch"]
            self.assertEqual([partial[index] for index in (1, 2, 3)], [0, 0, 0])
            self.assertGreater(abs(partial[0]), 1e-9)
        expected = {
            "CUT": {"CutARight": [-12, 0, 0, -6, -36, 24], "CutBLeft": [12, 0, 0, 6, 36, -24]},
            "LOAD": {"CutARight": [0] * 6, "CutBLeft": [0] * 6},
            "CONTACT": {"CutARight": [0] * 6, "CutBLeft": [0] * 6},
            "MPC": {"CutARight": [12, 0, 0, 6, 36, -24], "CutBLeft": [-12, 0, 0, -6, -36, 24]},
        }
        for kind, names in expected.items():
            self.assertEqual(set(wrenches[kind]), set(names))
            for name, wanted in names.items():
                self._assert_wrench(wrenches[kind][name], wanted, kind + "/" + name)
        for name in ("CutARight", "CutBLeft"):
            balance = [
                sum(wrenches[kind][name][index] for kind in ("CUT", "LOAD", "CONTACT", "MPC"))
                for index in range(6)
            ]
            self._assert_wrench(balance, [0] * 6, name + "/balance")
        dat = deck.with_suffix(".dat").read_text()
        motion = {}
        for name, pair in ids.items():
            motion[name] = []
            for index, suffix in enumerate(("RefNode", "RotNode")):
                rows = re.findall(
                    r"displacements \(vx,vy,vz\) for set "
                    + re.escape(name + "_" + suffix)
                    + r" and time\s+([^\s]+)\s*\n\s*\n\s*([^\n]+)",
                    dat,
                    re.I,
                )
                self.assertEqual(len(rows), 1)
                time, row = rows[0]
                fields = row.split()
                self.assertEqual(len(fields), 4)
                self.assertEqual(int(fields[0]), pair[index])
                self.assertAlmostEqual(float(time), 1, places=12)
                values = [float(value) for value in fields[1:]]
                self.assertTrue(all(math.isfinite(value) for value in values))
                self.assertGreater(values[0], 1e-9)
                motion[name].append(values)
        displacement = read_frd_result(str(deck.with_suffix(".frd")))["Results"][-1]["disp"]
        for port, key in zip(model.ports, ("moving_a", "moving_b")):
            reference = port.ReferenceNode
            corners = []
            for y, z in ((1, 2), (3, 2), (1, 4)):
                point = App.Vector(reference.x, y, z)
                matches = [
                    node
                    for node in model.memberships[key]
                    if (positions[node] - point).Length < 1e-8
                ]
                self.assertEqual(len(matches), 1)
                corners.append(matches[0])
            self.assertEqual(len(set(corners)), 3)
            self.assertGreater(
                (positions[corners[1]] - positions[corners[0]])
                .cross(positions[corners[2]] - positions[corners[0]])
                .Length,
                1,
            )
            translation, rotation = (App.Vector(*values) for values in motion[port.Name])
            for node in model.memberships[key]:
                actual = App.Vector(*displacement[node])
                predicted = translation + rotation.cross(positions[node] - reference)
                self.assertGreater(predicted.Length, 1e-9)
                self.assertLessEqual((actual - predicted).Length / predicted.Length, 0.01)
            # These three non-collinear physical corner nodes establish the
            # finite receiving face's actual translation and X rotation. They
            # are original solid nodes, not imported auxiliary-node numbers.
            physical_ux = (displacement[corners[1]][0] + displacement[corners[2]][0]) / 2
            physical_rx = (displacement[corners[1]][2] - displacement[corners[0]][2]) / 2
            self.assertGreater(physical_ux, 1e-9)
            self.assertGreater(physical_rx, 1e-9)
            self.assertLessEqual(abs(physical_ux - translation.x) / abs(translation.x), 0.01)
            self.assertLessEqual(abs(physical_rx - rotation.x) / abs(rotation.x), 0.01)
        if model.ordinary:
            partial_motion = [displacement[node] for node in model.memberships["partial"]]
            self.assertTrue(all(abs(value[0]) < 1e-12 for value in partial_motion))
            self.assertGreater(max(abs(value[1]) for value in partial_motion), 1e-9)
            self.assertGreater(max(abs(value[2]) for value in partial_motion), 1e-9)
        self._assert_vector(
            [1200 * (motion["MovingPortB"][0][0] - motion["MovingPortA"][0][0]), 0, 0],
            [12, 0, 0],
            12,
            "scalar axial constitutive response",
        )
        self._assert_vector(
            [6000 * (motion["MovingPortB"][1][0] - motion["MovingPortA"][1][0]), 0, 0],
            [6, 0, 0],
            6,
            "scalar rotational constitutive response",
        )
        fea.load_results()
        self.assertTrue(fea.results_present)
        self.assertTrue(
            any(item.isDerivedFrom("Fem::FemResultObject") for item in model.analysis.Group)
        )
        self.assertTrue(report.Status.startswith("Current"), report.Status)
        self.assertEqual(report.AccountingData, literal)
        importCcxDatResults.import_dat(str(deck.with_suffix(".dat")), model.analysis)
        self.assertTrue(report.Status.startswith("Current"), report.Status)
        self.assertEqual(report.AccountingData, literal)
        (self.output / "native-accounting-data.json").write_text(literal)
        return report, literal

    def _assert_historical_roundtrip(self, report, literal):
        resultants, name = list(report.Resultants), report.Name
        path = self.output / "moving-ports.FCStd"
        self.doc.recompute()
        self.doc.saveAs(str(path))
        self.assertEqual(report.AccountingData, literal)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(str(path))
        restored = self.doc.getObject(name)
        self.assertTrue(restored.Status.startswith("Stale"), restored.Status)
        self.assertEqual(restored.AccountingData, literal)
        self.assertEqual(list(restored.Resultants), resultants)
        self.doc.recompute()
        self.assertTrue(restored.Status.startswith("Stale"), restored.Status)
        self.assertEqual(restored.AccountingData, literal)

    def test_moving_finite_rbe_ports_keep_elastic_transfer_separate_from_physical_support(self):
        model = self._make_model()
        report, literal = self._solve_and_check(model)
        original = model.connectors[0].Stiffness
        model.connectors[0].Stiffness = "1201 N/mm"
        self.assertTrue(report.Status.startswith("Stale"), report.Status)
        self.assertEqual(report.AccountingData, literal)
        model.connectors[0].Stiffness = original
        self.assertTrue(report.Status.startswith("Stale"), report.Status)
        self._assert_historical_roundtrip(report, literal)

    def test_ordinary_fixed_and_partial_supports_preserve_aggregate_physical_equilibrium(self):
        model = self._make_model(ordinary=True)
        report, literal = self._solve_and_check(model)
        model.solver.NativeAccountingSupports = [model.supports[0]]
        self.assertTrue(report.Status.startswith("Stale"), report.Status)
        self.assertEqual(report.AccountingData, literal)
        model.solver.NativeAccountingSupports = model.supports
        self.assertTrue(report.Status.startswith("Stale"), report.Status)
        self._assert_historical_roundtrip(report, literal)

    def test_invalid_physical_support_selections_fail_at_stock_export_without_solving(self):
        model = self._make_model(ordinary=True)
        partial = model.supports[1]
        references = list(partial.References)

        def refused(label, message):
            with self.subTest(control=label):
                with self.assertRaisesRegex(ValueError, message):
                    self._write(model, label)

        partial.References = list(model.supports[0].References)
        refused("selected-overlap", "physical support degrees of freedom overlap")
        partial.References = references
        duplicate = ObjectsFem.makeConstraintDisplacement(self.doc, "UnselectedDuplicate")
        duplicate.References = references
        duplicate.xFree, duplicate.yFree, duplicate.zFree = False, True, True
        model.analysis.addObject(duplicate)
        refused("unselected-duplicate", "physical support degrees of freedom overlap")
        model.analysis.removeObject(duplicate)
        self.doc.removeObject(duplicate.Name)
        partial.xDisplacement = "0.1 mm"
        refused("nonzero-motion", "zero support motions without amplitude")
        partial.xDisplacement = "0 mm"
        partial.EnableAmplitude = True
        partial.AmplitudeValues = ["0, 0", "1, 1"]
        refused("amplitude", "zero support motions without amplitude")
        partial.EnableAmplitude = False
        foreign = ObjectsFem.makeConstraintFixed(self.doc, "ForeignSupport")
        foreign.References = references
        model.solver.NativeAccountingSupports = [model.supports[0], foreign]
        refused("foreign-support", "not a supported analysis constraint")
        model.solver.NativeAccountingSupports = model.supports + [model.supports[0]]
        refused("duplicate-selection", "support selection contains duplicates")
        model.solver.NativeAccountingSupports = []
        refused("legacy-empty-moving-rbe", "all six motions prescribed at zero")
        model.solver.NativeAccountingSupports = [model.ports[0]]
        refused("explicit-moving-support", "all six motions prescribed at zero")
        model.solver.NativeAccountingSupports = model.supports
        connector = model.connectors[0]
        connector.Mode = "Ground"
        connector.RigidBody2 = None
        refused("ground-connector", "not ground or direct solid-node springs")
        connector.Mode = "Two points"
        connector.Attachment = "Vertices"
        connector.RigidBody1 = None
        for prop, x in (("End1", 10), ("End2", 20)):
            vertices = [
                f"Vertex{index}"
                for index, vertex in enumerate(model.geometry.Shape.Vertexes, 1)
                if (vertex.Point - App.Vector(x, 1, 2)).Length < 1e-8
            ]
            self.assertEqual(len(vertices), 1)
            setattr(connector, prop, (model.geometry, vertices))
        refused("solid-node-connector", "not ground or direct solid-node springs")

    def test_longitudinal_side_load_on_shared_cut_is_refused_without_current_accounting(self):
        """Keep the original side-loaded fixture's ambiguous-node refusal."""
        model = self._make_model()
        for name, y, sign in (("TorquePositiveZ", 3, 1), ("TorqueNegativeZ", 1, -1)):
            faces = [
                f"Face{index}"
                for index, face in enumerate(model.geometry.Shape.Faces, 1)
                if abs(face.CenterOfMass.y - y) < 1e-8
                and 20 < face.CenterOfMass.x < 30
                and face.normalAt(0, 0).y * sign > 0.99
            ]
            self.assertEqual(len(faces), 2)
            self.doc.getObject(name).References = [(model.geometry, faces)]
        fea = self._write(model, "ambiguous-side-load")
        deck = Path(fea.inp_file_name)
        request = deck.with_suffix(".accounting")
        before = (self._sha(deck), self._sha(request))
        _, _, loads = self._stock_boundary(deck.read_text())
        self.assertTrue(
            any(
                value and abs(model.mesh.FemMesh.Nodes[node].x - 25) < 1e-8
                for node, _, value in loads
            )
        )
        self.assertEqual(fea.ccx_run(), 201)
        (self.output / "ambiguous-side-load.stdout").write_text(fea.ccx_stdout)
        (self.output / "ambiguous-side-load.stderr").write_text(fea.ccx_stderr)
        self.assertIn(
            "point load on cut has ambiguous body ownership", fea.ccx_stdout + fea.ccx_stderr
        )
        self.assertEqual((self._sha(deck), self._sha(request)), before)
        self.assertFalse(
            any(
                is_of_type(item, "Fem::NativeForceAccountingResult")
                and item.Status.startswith("Current")
                for item in model.analysis.Group
            )
        )
        output = deck.with_suffix(".accounting.out")
        if output.is_file():
            self.assertNotRegex(output.read_text(), r"(?m)^END\s*$")

    def test_unselected_ordinary_boundary_cannot_overlap_a_selected_fixed_rbe(self):
        model = self._make_model()
        duplicate = ObjectsFem.makeConstraintFixed(self.doc, "UnselectedFixedDuplicate")
        duplicate.References = model.supports[0].References
        model.analysis.addObject(duplicate)
        self.assertEqual(list(model.solver.NativeAccountingSupports), model.supports)
        with self.assertRaisesRegex(ValueError, "overlap a selected external RBE receiving region"):
            self._write(model, "unselected-ordinary-on-rbe")
