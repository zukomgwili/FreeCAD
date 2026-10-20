# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native moving face-port RED, before reading the accounting implementation.

Only public CAD, native FEM objects, Gmsh and the stock CalculiX tools are used.
This is a small software witness, not an Oomakhi or structural-design analysis.
"""

import hashlib
import json
import os
from pathlib import Path
import traceback
import unittest

import FreeCAD as App
import ObjectsFem
import Part
from BOPTools.SplitAPI import booleanFragments
from femmesh import gmshtools
from femtools.ccxtools import FemToolsCcx


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    with Path(path).open("x") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True) + "\n")


def plain(value):
    if isinstance(value, (str, bool, int, float)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    if isinstance(value, App.Vector):
        return [value.x, value.y, value.z]
    if isinstance(value, App.Rotation):
        return list(value.Q)
    if hasattr(value, "Name") and hasattr(value, "Document"):
        return {"object": value.Name, "document": value.Document.Name}
    return str(value)


class MovingPortWitness(unittest.TestCase):
    def test_native_moving_face_ports_are_not_fixed_supports(self):
        output = Path(os.environ["YWU_OUTPUT"]) / "witness"
        output.mkdir()
        for directory in ("mesh", "stock-off", "accounting-on"):
            (output / directory).mkdir()
        receipt = {
            "passed": False,
            "expected_first_red": "stock native accounting rejects moving RBE modes",
            "only_public_native_interfaces": True,
            "no_deck_patches_or_mocks": True,
            "Oomakhi_opened_or_solved": False,
            "physical_beams": 2,
            "geometric_cells_for_conforming_cuts": 4,
            "whole_applied_wrench_original_global_origin": [12, 0, 0, 6, 36, -24],
            "external_support_wrench_original_global_origin": [-12, 0, 0, -6, -36, 24],
            "cut_a_right_expected_wrench": [-12, 0, 0, -6, -36, 24],
            "cut_b_left_expected_wrench": [12, 0, 0, 3, 36, -24],
            "limits": "Analytical software fixture only; no engineering acceptance",
        }
        doc = App.newDocument("YwuMovingPortWitness")
        try:
            analysis = ObjectsFem.makeAnalysis(doc, "Analysis")
            solver = ObjectsFem.makeSolverCalculiXCcxTools(doc, "SolverCcxTools")
            solver.NativeForceAccounting = False
            solver.SplitInputWriter = False
            solver.AnalysisType = "static"
            solver.WorkingDir = str(output / "stock-off")
            analysis.addObject(solver)

            geometry = doc.addObject("Part::Feature", "BeamCells")
            # Shared topology inside each beam, a real 10 mm gap between beams.
            # No coincident independently meshed faces, Tie or extra connector
            # is inserted at either section-print cut.
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
                matches = [
                    f"Solid{index}"
                    for index, solid in enumerate(geometry.Shape.Solids, 1)
                    if abs(solid.CenterOfMass.x - x) < 1e-8
                ]
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
                ("a_left", 2.5), ("a_right", 7.5),
                ("b_left", 22.5), ("b_right", 27.5),
            )}
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

            material = ObjectsFem.makeMaterialSolid(doc, "WitnessMaterial")
            material.Material = {
                "Name": "Ywu synthetic linear material",
                "YoungsModulus": "20000 MPa",
                "PoissonRatio": "0.3",
                "Density": "1 kg/m^3",
            }
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
                    body_mode = "Constraint" if prescribed else "Free"
                    setattr(body, "TranslationalMode" + axis, body_mode)
                    setattr(body, "RotationalMode" + axis, body_mode)
                    setattr(body, "Force" + axis, "0 N")
                    setattr(body, "Moment" + axis, "0 N*mm")
                analysis.addObject(body)
                self.assertEqual(body.References[0][0], geometry)
                self.assertTrue(body.References[0][1][0].startswith("Face"))
                self.assertEqual(geometry.getSubObject(faces[key]).ShapeType, "Face")
                bodies.append(body)

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
                ("TorquePositiveZ", faces["torque_plus_z"], 3, App.Vector(0, 0, 1)),
                ("TorqueNegativeZ", faces["torque_minus_z"], 3, App.Vector(0, 0, -1)),
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
                # An ordinary writer/solve is retained first. These flags alone
                # are enabled with NativeForceAccounting for the second export.
                section.NativeEquilibriumCut = False
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
            groups = {}
            for group in mesh.FemMesh.Groups:
                groups[mesh.FemMesh.getGroupName(group)] = sorted(mesh.FemMesh.getGroupElements(group))
            write_json(output / "mesh-membership.json", {
                "selected_face_nodes": membership,
                "native_groups": groups,
                "nodes": {str(node): plain(point) for node, point in mesh.FemMesh.Nodes.items()},
                "volume_connectivity": {
                    str(element): list(mesh.FemMesh.getElementNodes(element))
                    for element in mesh.FemMesh.Volumes
                },
                "face_keys": faces,
                "solid_keys": solids,
            })

            property_names = (
                "References", "ReferenceNode", "Displacement", "Rotation",
                *("TranslationalMode" + axis for axis in "XYZ"),
                *("RotationalMode" + axis for axis in "XYZ"),
                *("Force" + axis for axis in "XYZ"),
                *("Moment" + axis for axis in "XYZ"),
                "Attachment", "Mode", "Kind", "Axis", "Orientation", "RigidBody1", "RigidBody2",
                "Stiffness", "RotationalStiffness", "Force", "Direction", "Reversed",
                "NativeEquilibriumCut", "AccountingBody", "NativeForceAccounting",
                "NativeAccountingSolver", "Material",
            )

            def model_properties():
                return {
                    item.Name: {
                        "type": item.TypeId,
                        "properties": {
                            name: {"type": item.getTypeIdOfProperty(name), "value": plain(getattr(item, name))}
                            for name in property_names if name in item.PropertiesList
                        },
                    }
                    for item in analysis.Group
                    if item != mesh
                }

            write_json(output / "native-properties-off.json", model_properties())
            doc.recompute()
            doc.saveAs(str(output / "moving-face-ports-stock-off.FCStd"))
            receipt["stock_off_document_sha256"] = sha(output / "moving-face-ports-stock-off.FCStd")
            fea = FemToolsCcx(analysis=analysis, solver=solver)
            fea.update_objects()
            fea.setup_working_dir(str(output / "stock-off"))
            fea.write_inp_file()
            receipt["stock_off_deck"] = fea.inp_file_name
            receipt["stock_off_deck_sha256"] = sha(fea.inp_file_name)
            receipt["stock_off_binary"] = str(fea.ccx_binary)
            if fea.ccx_binary and Path(fea.ccx_binary).is_file():
                receipt["stock_off_binary_sha256"] = sha(fea.ccx_binary)
            returncode = fea.ccx_run()
            (output / "stock-off.stdout").write_text(fea.ccx_stdout)
            (output / "stock-off.stderr").write_text(fea.ccx_stderr)
            receipt["stock_off_returncode"] = returncode
            self.assertEqual(returncode, 0)
            self.assertTrue(Path(fea.inp_file_name).with_suffix(".frd").is_file())
            fea.load_results()
            self.assertTrue(fea.results_present)
            results = [item for item in analysis.Group if item.isDerivedFrom("Fem::FemResultObject")]
            self.assertTrue(results)
            receipt["stock_result_objects"] = [item.Name for item in results]
            write_json(output / "stock-imported-results.json", {
                item.Name: {
                    name: plain(getattr(item, name))
                    for name in ("NodeNumbers", "DisplacementVectors", "Stats")
                    if name in item.PropertiesList
                }
                for item in results
            })

            # This is the public stock writer request that must reject the
            # current unsupported moving modes. No private accounting function
            # is called and neither a request nor output is hand-authored.
            solver.NativeForceAccounting = True
            for section in cuts:
                section.NativeEquilibriumCut = True
            doc.recompute()
            write_json(output / "native-properties-on.json", model_properties())
            doc.saveAs(str(output / "moving-face-ports-accounting-on.FCStd"))
            receipt["accounting_on_document_sha256"] = sha(output / "moving-face-ports-accounting-on.FCStd")
            fea = FemToolsCcx(analysis=analysis, solver=solver)
            fea.update_objects()
            fea.setup_working_dir(str(output / "accounting-on"))
            try:
                fea.write_inp_file()
            except Exception as error:
                receipt["accounting_on_exception"] = {
                    "type": type(error).__name__,
                    "message": str(error),
                    "traceback": traceback.format_exc(),
                }
                receipt["red_reproduced"] = (
                    isinstance(error, ValueError)
                    and "accounting supports" in str(error)
                    and "zero" in str(error)
                )
                write_json(output / "accounting-on-exception.json", receipt["accounting_on_exception"])
                self.assertTrue(receipt["red_reproduced"], str(error))
                receipt["reproduction_capture_complete"] = True
                # The required composition should export successfully. Keep
                # the unmodified product refusal as a genuine failing test.
                raise
            else:
                self.fail("Expected stock moving-RBE accounting refusal was not reproduced")
            receipt["passed"] = True
        except BaseException as error:
            receipt["witness_error"] = {"type": type(error).__name__, "message": str(error),
                                        "traceback": traceback.format_exc()}
            raise
        finally:
            receipt["retained_files"] = {
                str(path.relative_to(output)): {"bytes": path.stat().st_size, "sha256": sha(path)}
                for path in sorted(output.rglob("*")) if path.is_file()
            }
            write_json(output / "witness-receipt.json", receipt)
            print("YWU_NATIVE_WITNESS=" + str(output), flush=True)
            if doc.Name in App.listDocuments():
                App.closeDocument(doc.Name)
