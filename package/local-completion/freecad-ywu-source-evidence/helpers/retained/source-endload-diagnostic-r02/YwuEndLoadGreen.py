# SPDX-License-Identifier: LGPL-2.1-or-later
"""Separate end-edge loaded V3 benchmark; never repairs the original RED.

No deck patches, mocked solver outputs or private accounting helpers are used.
This is a software fixture, not an Oomakhi or structural-design analysis.
"""

import json
import math
import os
from pathlib import Path
import re
import traceback
import unittest

import FreeCAD as App
import ObjectsFem
import Part
from BOPTools.SplitAPI import booleanFragments
from femmesh import gmshtools
from femtools.ccxtools import FemToolsCcx

from YwuMovingPortWitness import plain, sha, write_json


class EndLoadGreenWitness(unittest.TestCase):
    def test_native_v3_moving_face_ports_are_not_fixed_supports(self):
        output = Path(os.environ["YWU_OUTPUT"]) / "witness"
        output.mkdir()
        for directory in ("mesh", "native"):
            (output / directory).mkdir()
        checks = []
        oracle = Path(__file__).resolve().parent / "endload-oracle.json"
        receipt = {
            "passed": False,
            "schema": "FreeCAD-ywu-native-v3-end-edge-loaded-ports-v1",
            "separate_benchmark_not_a_repair_of_original_side_loaded_RED": True,
            "only_public_native_interfaces": True,
            "no_deck_patches_or_mocks": True,
            "Oomakhi_opened_or_solved": False,
            "physical_beams": 2,
            "geometric_cells_for_conforming_cuts": 4,
            "moment_origin": [0, 0, 0],
            "frozen_independent_oracle": str(oracle),
            "frozen_independent_oracle_sha256": sha(oracle),
            "force_error_limit": 0.01,
            "moment_error_limit": 0.01,
            "zero_force_scale": 12,
            "zero_moment_scale": math.sqrt(1908),
            "checks": checks,
            "limits": "Analytical software fixture only; no engineering acceptance",
        }
        doc = App.newDocument("YwuMovingPortGreen")
        try:
            analysis = ObjectsFem.makeAnalysis(doc, "Analysis")
            solver = ObjectsFem.makeSolverCalculiXCcxTools(doc, "SolverCcxTools")
            solver.NativeForceAccounting = True
            solver.SplitInputWriter = False
            solver.AnalysisType = "static"
            solver.WorkingDir = str(output / "native")
            candidate = os.environ.get("YWU_CANDIDATE")
            if candidate:
                solver.NativeAccountingSolver = candidate
            receipt["explicit_solver_override"] = candidate
            analysis.addObject(solver)

            geometry = doc.addObject("Part::Feature", "BeamCells")
            beam_a = booleanFragments(
                [Part.makeBox(5, 2, 2, App.Vector(x, 1, 2)) for x in (0, 5)],
                "CompSolid",
            )
            beam_b = booleanFragments(
                [Part.makeBox(5, 2, 2, App.Vector(x, 1, 2)) for x in (20, 25)],
                "CompSolid",
            )
            geometry.Shape = Part.makeCompound([beam_a, beam_b])
            doc.recompute()
            self.assertEqual(len(geometry.Shape.Solids), 4)
            self.assertAlmostEqual(geometry.Shape.Volume, 80, places=9)

            def solid_at(x):
                matches = [f"Solid{index}" for index, solid in enumerate(geometry.Shape.Solids, 1)
                           if abs(solid.CenterOfMass.x - x) < 1e-8]
                self.assertEqual(len(matches), 1, (x, matches))
                return matches[0]

            def faces_at(owner, axis, coordinate, normal, x_bounds=None):
                matches = []
                for index, face in enumerate(owner.Shape.Faces, 1):
                    point = face.CenterOfMass
                    if abs(getattr(point, axis) - coordinate) >= 1e-8:
                        continue
                    if normal * getattr(face.normalAt(0, 0), axis) <= 0.99:
                        continue
                    if x_bounds is not None and not x_bounds[0] < point.x < x_bounds[1]:
                        continue
                    matches.append(f"Face{index}")
                return matches

            def one_face(axis, coordinate, normal):
                names = faces_at(geometry, axis, coordinate, normal)
                self.assertEqual(len(names), 1, (axis, coordinate, normal, names))
                return names[0]

            solids = {name: solid_at(x) for name, x in (
                ("a_left", 2.5), ("a_right", 7.5), ("b_left", 22.5), ("b_right", 27.5))}
            faces = {
                "external_support": one_face("x", 0, -1),
                "moving_a": one_face("x", 10, 1),
                "moving_b": one_face("x", 20, -1),
                "axial_load": one_face("x", 30, 1),
                "torque_plus_z": faces_at(geometry, "y", 3, 1, (20, 30)),
                "torque_minus_z": faces_at(geometry, "y", 1, -1, (20, 30)),
            }
            self.assertEqual(len(faces["torque_plus_z"]), 2)
            self.assertEqual(len(faces["torque_minus_z"]), 2)
            def end_edge(y):
                names = [f"Edge{index}" for index, edge in enumerate(geometry.Shape.Edges, 1)
                         if all(abs(vertex.Point.x - 30) < 1e-8
                                and abs(vertex.Point.y - y) < 1e-8 for vertex in edge.Vertexes)
                         and abs(edge.Length - 2) < 1e-8]
                self.assertEqual(len(names), 1, (y, names))
                return names[0]
            end_edges = {"positive_z": end_edge(3), "negative_z": end_edge(1)}
            material = ObjectsFem.makeMaterialSolid(doc, "WitnessMaterial")
            material.Material = {
                "Name": "Ywu synthetic linear material", "YoungsModulus": "20000 MPa",
                "PoissonRatio": "0.3", "Density": "1 kg/m^3"}
            analysis.addObject(material)

            bodies = []
            for name, key, x, prescribed in (
                ("ExternalSupport", "external_support", 0, True),
                ("MovingPortA", "moving_a", 10, False),
                ("MovingPortB", "moving_b", 20, False),
            ):
                body = ObjectsFem.makeConstraintRigidBody(doc, name)
                body.References = [(geometry, [faces[key]])]
                body.ReferenceNode = App.Vector(x, 2, 3)
                body.Displacement = App.Vector()
                body.Rotation = App.Rotation()
                for axis in "XYZ":
                    mode = "Constraint" if prescribed else "Free"
                    setattr(body, "TranslationalMode" + axis, mode)
                    setattr(body, "RotationalMode" + axis, mode)
                    setattr(body, "Force" + axis, "0 N")
                    setattr(body, "Moment" + axis, "0 N*mm")
                analysis.addObject(body)
                self.assertEqual(body.References[0][0], geometry)
                self.assertTrue(body.References[0][1][0].startswith("Face"))
                self.assertEqual(geometry.getSubObject(faces[key]).ShapeType, "Face")
                bodies.append(body)
            solver.NativeAccountingSupports = [bodies[0]]
            self.assertEqual(list(solver.NativeAccountingSupports), [bodies[0]])

            connectors = []
            for kind, prefix, stiffness in (
                ("Translational", "T", "1200 N/mm"),
                ("Rotational", "R", "6000 N*mm/rad"),
            ):
                for axis in "XYZ":
                    connector = ObjectsFem.makeConstraintElasticConnector(doc, "Connector" + prefix + axis)
                    connector.Attachment = "Rigid body ports"
                    connector.Mode = "Two points"
                    connector.Kind = kind
                    connector.Axis = axis
                    connector.Orientation = App.Rotation()
                    connector.RigidBody1 = bodies[1]
                    connector.RigidBody2 = bodies[2]
                    if kind == "Translational":
                        connector.Stiffness = stiffness
                    else:
                        connector.RotationalStiffness = App.Units.Quantity(stiffness)
                    analysis.addObject(connector)
                    connectors.append(connector)

            for name, keys, amount, vector in (
                ("AxialLoad", [faces["axial_load"]], 12, App.Vector(1, 0, 0)),
                ("TorquePositiveZ", [end_edges["positive_z"]], 3, App.Vector(0, 0, 1)),
                ("TorqueNegativeZ", [end_edges["negative_z"]], 3, App.Vector(0, 0, -1)),
            ):
                direction = doc.addObject("Part::Feature", name + "Direction")
                direction.Shape = Part.makeLine(App.Vector(), vector)
                load = ObjectsFem.makeConstraintForce(doc, name)
                load.References = [(geometry, keys)]
                load.Force = f"{amount} N"
                load.Direction = (direction, ["Edge1"])
                load.Reversed = False
                analysis.addObject(load)

            cuts = []
            for name, x, normal, solid in (
                ("CutARight", 5, -1, solids["a_right"]),
                ("CutBLeft", 25, 1, solids["b_left"]),
            ):
                owner = geometry
                names = faces_at(owner, "x", x, normal)
                if not names:
                    owner = doc.addObject("Part::Reverse", name + "Orientation")
                    owner.Source = geometry
                    doc.recompute()
                    names = faces_at(owner, "x", x, normal)
                self.assertEqual(len(names), 1, (name, names))
                section = ObjectsFem.makeConstraintSectionPrint(doc, name)
                section.References = [(owner, names)]
                section.AccountingBody = [(geometry, [solid])]
                section.NativeEquilibriumCut = True
                analysis.addObject(section)
                cuts.append(section)

            mesh = ObjectsFem.makeMeshGmsh(doc, "Mesh")
            mesh.Shape = geometry
            mesh.ElementOrder = "2nd"
            mesh.SecondOrderLinear = False
            mesh.CoherenceMesh = False
            mesh.CharacteristicLengthMax = 1.5
            mesh.CharacteristicLengthMin = 0.75
            mesh.WorkingDirectory = str(output / "mesh")
            analysis.addObject(mesh)
            doc.recompute()
            mesher = gmshtools.GmshTools(mesh)
            mesher.create_mesh()
            self.assertEqual(mesher.process.exitCode(), 0)
            self.assertEqual(mesher.process.exitStatus(), mesher.process.ExitStatus.NormalExit)
            self.assertGreater(mesh.FemMesh.VolumeCount, 0)
            membership = {}
            for key in ("external_support", "moving_a", "moving_b"):
                membership[key] = sorted(mesh.FemMesh.getNodesByFace(geometry.getSubObject(faces[key])))
                self.assertGreaterEqual(len(membership[key]), 3)
            self.assertFalse(set(membership["moving_a"]) & set(membership["moving_b"]))
            groups = {mesh.FemMesh.getGroupName(group): sorted(mesh.FemMesh.getGroupElements(group))
                      for group in mesh.FemMesh.Groups}
            write_json(output / "mesh-membership.json", {
                "selected_face_nodes": membership, "native_groups": groups,
                "nodes": {str(node): plain(point) for node, point in mesh.FemMesh.Nodes.items()},
                "volume_connectivity": {
                    str(element): list(mesh.FemMesh.getElementNodes(element)) for element in mesh.FemMesh.Volumes},
                "face_keys": faces, "end_edge_loads": end_edges, "solid_keys": solids})
            property_names = (
                "References", "ReferenceNode", "Displacement", "Rotation",
                *("TranslationalMode" + axis for axis in "XYZ"),
                *("RotationalMode" + axis for axis in "XYZ"),
                *("Force" + axis for axis in "XYZ"), *("Moment" + axis for axis in "XYZ"),
                "Attachment", "Mode", "Kind", "Axis", "Orientation", "RigidBody1", "RigidBody2",
                "Stiffness", "RotationalStiffness", "Force", "Direction", "Reversed",
                "NativeEquilibriumCut", "AccountingBody", "NativeForceAccounting",
                "NativeAccountingSolver", "NativeAccountingSupports", "Material")
            properties = {
                item.Name: {"type": item.TypeId, "properties": {
                    name: {"type": item.getTypeIdOfProperty(name), "value": plain(getattr(item, name))}
                    for name in property_names if name in item.PropertiesList}}
                for item in analysis.Group if item != mesh}
            write_json(output / "native-properties.json", properties)
            doc.recompute()
            doc.saveAs(str(output / "moving-face-ports-before-solve.FCStd"))

            fea = FemToolsCcx(analysis=analysis, solver=solver)
            fea.update_objects()
            fea.setup_working_dir(str(output / "native"))
            fea.write_inp_file()
            deck = Path(fea.inp_file_name)
            request = deck.with_suffix(".accounting")
            receipt["deck"] = str(deck)
            receipt["deck_sha256_before_solve"] = sha(deck)
            receipt["request_sha256_before_solve"] = sha(request)
            original_deck = deck.read_text()
            rbe_ids = {}
            for name in ("ExternalSupport", "MovingPortA", "MovingPortB"):
                rows = re.findall(r"^\*RIGID BODY, NSET=" + re.escape(name)
                                  + r", REF NODE=(\d+), ROT NODE=(\d+)\s*$", original_deck, re.M | re.I)
                self.assertEqual(len(rows), 1, name)
                rbe_ids[name] = [int(value) for value in rows[0]]
            self.assertEqual(len(set(sum(rbe_ids.values(), []))), 6)
            self.assertGreater(min(sum(rbe_ids.values(), [])), max(mesh.FemMesh.Nodes))
            receipt["original_deck_rbe_reference_rotation_ids"] = rbe_ids
            code = fea.ccx_run()
            (output / "native.stdout").write_text(fea.ccx_stdout)
            (output / "native.stderr").write_text(fea.ccx_stderr)
            receipt["solver_returncode"] = code
            receipt["actual_binary"] = str(fea.ccx_binary)
            receipt["actual_binary_sha256"] = sha(fea.ccx_binary)
            self.assertEqual(code, 0)
            self.assertEqual(sha(deck), receipt["deck_sha256_before_solve"])
            self.assertEqual(sha(request), receipt["request_sha256_before_solve"])
            wire_output = deck.with_suffix(".accounting.out")
            self.assertEqual(wire_output.read_text().splitlines()[0], "CCX_FORCE_ACCOUNTING_V3")
            reports = [item for item in analysis.Group
                       if getattr(getattr(item, "Proxy", None), "Type", None) == "Fem::NativeForceAccountingResult"]
            self.assertEqual(len(reports), 1)
            report = reports[0]
            self.assertTrue(report.Status.startswith("Current"), report.Status)
            native_literal = report.AccountingData
            data = json.loads(native_literal)
            (output / "native-accounting-data.json").write_text(native_literal)
            self.assertEqual(data["schema"], "CCX_FORCE_ACCOUNTING_V3")
            self.assertEqual(data["movement_source"]["status"], "BOUND")
            self.assertEqual(data["binary"], str(fea.ccx_binary))
            expected = {
                "SUPPORT": {"ExternalSupport": [-12, 0, 0, -6, -36, 24]},
                "CUT": {"CutARight": [-12, 0, 0, -6, -36, 24], "CutBLeft": [12, 0, 0, 6, 36, -24]},
                "LOAD": {"CutARight": [0, 0, 0, 0, 0, 0], "CutBLeft": [0, 0, 0, 0, 0, 0]},
                "CONTACT": {"CutARight": [0, 0, 0, 0, 0, 0], "CutBLeft": [0, 0, 0, 0, 0, 0]},
                "MPC": {"CutARight": [12, 0, 0, 6, 36, -24], "CutBLeft": [-12, 0, 0, -6, -36, 24]},
            }
            wrenches = data["wrenches"]
            self.assertEqual(set(wrenches), set(expected))

            def vector_check(name, actual, reference, zero_scale):
                self.assertEqual(len(actual), 3)
                self.assertTrue(all(math.isfinite(value) for value in actual))
                error = math.sqrt(sum((value - target) ** 2 for value, target in zip(actual, reference)))
                norm = math.sqrt(sum(value ** 2 for value in reference))
                scale = norm if norm else zero_scale
                row = {"name": name, "actual": list(actual), "reference": list(reference),
                       "error_norm": error, "reference_norm": norm, "scale": scale,
                       "relative_error": error / scale, "limit": 0.01,
                       "passed": error <= 0.01 * scale}
                checks.append(row)
                self.assertTrue(row["passed"], row)

            for kind, targets in expected.items():
                self.assertEqual(set(wrenches[kind]), set(targets), kind)
                for name, reference in targets.items():
                    actual = wrenches[kind][name]
                    self.assertEqual(len(actual), 6)
                    vector_check(kind + "/" + name + "/force", actual[:3], reference[:3], 12)
                    vector_check(kind + "/" + name + "/moment", actual[3:], reference[3:], math.sqrt(1908))
            for name in ("CutARight", "CutBLeft"):
                balance = [sum(wrenches[kind][name][index] for kind in ("CUT", "LOAD", "CONTACT", "MPC"))
                           for index in range(6)]
                vector_check(name + "/body-balance/force", balance[:3], [0, 0, 0], 12)
                vector_check(name + "/body-balance/moment", balance[3:], [0, 0, 0], math.sqrt(1908))

            # The stock DAT reference/rotation sets are read before FEM import.
            # Auxiliary-node IDs are bound to the original native deck, never
            # guessed from the mesh produced by the importer.
            dat_text = deck.with_suffix(".dat").read_text()
            motion = {}
            for body_name in ("MovingPortA", "MovingPortB"):
                motion[body_name] = {}
                for index, suffix in enumerate(("RefNode", "RotNode")):
                    set_name = body_name + "_" + suffix
                    rows = re.findall(
                        r"displacements \(vx,vy,vz\) for set " + re.escape(set_name)
                        + r" and time\s+([^\s]+)\s*\n\s*\n\s*([^\n]+)", dat_text, re.I)
                    self.assertEqual(len(rows), 1, set_name)
                    time, row = rows[0]
                    fields = row.split()
                    self.assertEqual(len(fields), 4)
                    self.assertEqual(int(fields[0]), rbe_ids[body_name][index])
                    self.assertAlmostEqual(float(time), 1, places=12)
                    value = [float(item) for item in fields[1:]]
                    self.assertTrue(all(math.isfinite(item) for item in value))
                    self.assertGreater(value[0], 1e-9, (set_name, value))
                    motion[body_name][suffix] = {"set": set_name, "node": int(fields[0]),
                                               "time": float(time), "value": value}
            delta_ux = motion["MovingPortB"]["RefNode"]["value"][0] - motion["MovingPortA"]["RefNode"]["value"][0]
            delta_rx = motion["MovingPortB"]["RotNode"]["value"][0] - motion["MovingPortA"]["RotNode"]["value"][0]
            vector_check("scalar-TX-k-times-delta", [1200 * delta_ux, 0, 0], [12, 0, 0], 12)
            vector_check("scalar-RX-k-times-delta", [6000 * delta_rx, 0, 0], [6, 0, 0], 6)
            receipt["physical_moving_face_port_motion_from_original_dat_sets"] = motion
            receipt["relative_ux"] = delta_ux
            receipt["relative_rx_radians"] = delta_rx
            write_json(output / "motion-from-stock-dat.json", motion)

            receipt["result_import_lifecycle"] = []
            for phase, import_phase in (("FRD", fea.load_results_ccxfrd),
                                        ("DAT", fea.load_results_ccxdat),
                                        ("recompute", doc.recompute)):
                import_phase()
                receipt["result_import_lifecycle"].append({
                    "phase": phase, "status": report.Status,
                    "analysis_members": [{"name": obj.Name, "type": obj.TypeId,
                                          "proxy_type": getattr(getattr(obj, "Proxy", None), "Type", None)}
                                         for obj in analysis.Group]})
            self.assertTrue(fea.results_present)
            fem_results = [item for item in analysis.Group if item.isDerivedFrom("Fem::FemResultObject")]
            self.assertTrue(fem_results)
            receipt["fem_result_objects"] = [item.Name for item in fem_results]
            self.assertTrue(report.Status.startswith("Current"), report.Status)
            self.assertEqual(report.AccountingData, native_literal)
            resultants = plain(list(report.Resultants))
            doc.recompute()
            saved = output / "moving-face-ports-native-v3.FCStd"
            doc.saveAs(str(saved))
            self.assertEqual(report.AccountingData, native_literal)
            paths = {"deck": deck, "request": request, "native_output": wire_output,
                     "frd": deck.with_suffix(".frd"), "dat": deck.with_suffix(".dat")}
            cold = {
                "schema": "FreeCAD-ywu-native-cold-case-v1", "document": str(saved),
                "document_sha256": sha(saved), "report_name": report.Name,
                "analysis_name": analysis.Name, "solver_name": solver.Name, "mesh_name": mesh.Name,
                "accounting_data_literal": native_literal, "resultants_literal": resultants,
                "saved_status_literal": report.Status, "movement_source_literal": data["movement_source"],
                "binary": data["binary"], "binary_sha256": sha(data["binary"]),
                "source_files": {name: {"path": str(path), "sha256": sha(path)} for name, path in paths.items()},
                "explicit_supports": [item.Name for item in solver.NativeAccountingSupports],
                "saved_references": {item.Name: plain(item.References) for item in bodies + cuts},
                "saved_native_properties": properties,
                "no_cold_restore_performed_yet": True,
                "no_history_or_provenance_repair": True,
            }
            write_json(output / "cold-case.json", cold)
            receipt["cold_manifest"] = str(output / "cold-case.json")
            receipt["cold_manifest_sha256"] = sha(output / "cold-case.json")
            receipt["current_native_report"] = {"name": report.Name, "status": report.Status,
                                                 "schema": data["schema"], "movement_status": data["movement_source"]["status"]}
            receipt["passed"] = True
        except BaseException as error:
            receipt["witness_error"] = {"type": type(error).__name__, "message": str(error),
                                        "traceback": traceback.format_exc()}
            raise
        finally:
            receipt["retained_files"] = {
                str(path.relative_to(output)): {"bytes": path.stat().st_size, "sha256": sha(path)}
                for path in sorted(output.rglob("*")) if path.is_file()}
            write_json(output / "witness-receipt.json", receipt)
            print("YWU_NATIVE_GREEN_WITNESS=" + str(output), flush=True)
            if doc.Name in App.listDocuments():
                App.closeDocument(doc.Name)
