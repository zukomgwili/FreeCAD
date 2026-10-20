# SPDX-License-Identifier: LGPL-2.1-or-later
"""First native ordinary-support RED on real moving finite face ports.

The physical support partition and aggregate equilibrium targets are declared
before execution in oracle-spec-proposal.json. No private accounting helper,
deck patch, auxiliary support RBE or added stiffness is used.
"""

import os
from pathlib import Path
import traceback
from types import SimpleNamespace
import unittest

import FreeCAD as App
import ObjectsFem
import Part
from BOPTools.SplitAPI import booleanFragments
from femmesh import gmshtools
from femtools.ccxtools import FemToolsCcx

from YwuMovingPortWitness import plain, sha, write_json


def make_fixture(testcase, doc, output):
    """One unchanged native fixture usable by the later positive slice."""
    analysis = ObjectsFem.makeAnalysis(doc, "Analysis")
    solver = ObjectsFem.makeSolverCalculiXCcxTools(doc, "SolverCcxTools")
    solver.NativeForceAccounting = False
    solver.SplitInputWriter = False
    solver.AnalysisType = "static"
    solver.WorkingDir = str(output / "stock-off")
    candidate = os.environ.get("YWU_CANDIDATE")
    if candidate:
        solver.NativeAccountingSolver = candidate
    analysis.addObject(solver)
    geometry = doc.addObject("Part::Feature", "BeamCells")
    y_intervals = ((1, 1.75), (1.75, 2.25), (2.25, 3))
    beam_a = booleanFragments([
        Part.makeBox(5, upper - lower, 2, App.Vector(x, lower, 2))
        for x in (0, 5) for lower, upper in y_intervals
    ], "CompSolid")
    beam_b = booleanFragments([
        Part.makeBox(5, 2, 2, App.Vector(x, 1, 2)) for x in (20, 25)
    ], "CompSolid")
    geometry.Shape = Part.makeCompound([beam_a, beam_b])
    doc.recompute()
    testcase.assertEqual(len(geometry.Shape.Solids), 8)
    testcase.assertAlmostEqual(geometry.Shape.Volume, 80, places=9)

    def solids_at(x):
        return [f"Solid{index}" for index, solid in enumerate(geometry.Shape.Solids, 1)
                if abs(solid.CenterOfMass.x - x) < 1e-8]

    def faces_at(owner, axis, coordinate, normal):
        return [f"Face{index}" for index, face in enumerate(owner.Shape.Faces, 1)
                if abs(getattr(face.CenterOfMass, axis) - coordinate) < 1e-8
                and normal * getattr(face.normalAt(0, 0), axis) > 0.99]

    support_faces = faces_at(geometry, "x", 0, -1)
    testcase.assertEqual(len(support_faces), 3)
    fixed_names = [name for name in support_faces
                   if abs(geometry.getSubObject(name).CenterOfMass.y - 1.375) < 1e-8]
    partial_names = [name for name in support_faces
                     if abs(geometry.getSubObject(name).CenterOfMass.y - 2.625) < 1e-8]
    gap_names = [name for name in support_faces
                 if abs(geometry.getSubObject(name).CenterOfMass.y - 2) < 1e-8]
    testcase.assertEqual(len(fixed_names), 1)
    testcase.assertEqual(len(partial_names), 1)
    testcase.assertEqual(len(gap_names), 1)
    faces = {"fixed": fixed_names, "partial": partial_names, "gap": gap_names,
             "moving_a": faces_at(geometry, "x", 10, 1),
             "moving_b": faces_at(geometry, "x", 20, -1),
             "axial_load": faces_at(geometry, "x", 30, 1)}
    testcase.assertEqual(len(faces["moving_a"]), 3)
    testcase.assertEqual(len(faces["moving_b"]), 1)
    testcase.assertEqual(len(faces["axial_load"]), 1)
    for key, expected_area, expected_centre in (
        ("fixed", 1.5, App.Vector(0, 1.375, 3)),
        ("partial", 1.5, App.Vector(0, 2.625, 3)),
        ("gap", 1, App.Vector(0, 2, 3)),
        ("moving_a", 4, App.Vector(10, 2, 3)),
        ("moving_b", 4, App.Vector(20, 2, 3)),
    ):
        shapes = [geometry.getSubObject(name) for name in faces[key]]
        area = sum(shape.Area for shape in shapes)
        centre = sum((shape.CenterOfMass * shape.Area for shape in shapes), App.Vector()) / area
        testcase.assertAlmostEqual(area, expected_area, places=9)
        testcase.assertLess((centre - expected_centre).Length, 1e-8)
        testcase.assertTrue(all(shape.ShapeType == "Face" for shape in shapes))
    testcase.assertAlmostEqual(
        geometry.getSubObject(fixed_names[0]).distToShape(geometry.getSubObject(partial_names[0]))[0],
        0.5, places=9)

    material = ObjectsFem.makeMaterialSolid(doc, "WitnessMaterial")
    material.Material = {"Name": "Ywu synthetic linear material", "YoungsModulus": "20000 MPa",
                         "PoissonRatio": "0.3", "Density": "1 kg/m^3"}
    analysis.addObject(material)
    fixed = ObjectsFem.makeConstraintFixed(doc, "FixedPatch")
    fixed.References = [(geometry, fixed_names)]
    analysis.addObject(fixed)
    partial = ObjectsFem.makeConstraintDisplacement(doc, "PartialAxialPatch")
    partial.References = [(geometry, partial_names)]
    partial.xFree = False
    partial.yFree = True
    partial.zFree = True
    partial.xDisplacement = "0 mm"
    partial.yDisplacement = "0 mm"
    partial.zDisplacement = "0 mm"
    analysis.addObject(partial)
    supports = [fixed, partial]
    solver.NativeAccountingSupports = supports
    testcase.assertEqual(list(solver.NativeAccountingSupports), supports)

    bodies = []
    for name, key, x in (("MovingPortA", "moving_a", 10), ("MovingPortB", "moving_b", 20)):
        body = ObjectsFem.makeConstraintRigidBody(doc, name)
        body.References = [(geometry, faces[key])]
        body.ReferenceNode = App.Vector(x, 2, 3)
        body.Displacement = App.Vector()
        body.Rotation = App.Rotation()
        for axis in "XYZ":
            setattr(body, "TranslationalMode" + axis, "Free")
            setattr(body, "RotationalMode" + axis, "Free")
            setattr(body, "Force" + axis, "0 N")
            setattr(body, "Moment" + axis, "0 N*mm")
        analysis.addObject(body)
        bodies.append(body)
    for kind, prefix, stiffness in (
        ("Translational", "T", "1200 N/mm"), ("Rotational", "R", "6000 N*mm/rad"),
    ):
        for axis in "XYZ":
            connector = ObjectsFem.makeConstraintElasticConnector(doc, "Connector" + prefix + axis)
            connector.Attachment = "Rigid body ports"
            connector.Mode = "Two points"
            connector.Kind = kind
            connector.Axis = axis
            connector.Orientation = App.Rotation()
            connector.RigidBody1 = bodies[0]
            connector.RigidBody2 = bodies[1]
            if kind == "Translational":
                connector.Stiffness = stiffness
            else:
                connector.RotationalStiffness = App.Units.Quantity(stiffness)
            analysis.addObject(connector)

    def end_edge(y):
        names = [f"Edge{index}" for index, edge in enumerate(geometry.Shape.Edges, 1)
                 if all(abs(vertex.Point.x - 30) < 1e-8 and abs(vertex.Point.y - y) < 1e-8
                        for vertex in edge.Vertexes) and abs(edge.Length - 2) < 1e-8]
        testcase.assertEqual(len(names), 1, (y, names))
        return names[0]

    end_edges = {"positive_z": end_edge(3), "negative_z": end_edge(1)}
    for name, names, amount, direction in (
        ("AxialLoad", faces["axial_load"], 12, App.Vector(1, 0, 0)),
        ("TorquePositiveZ", [end_edges["positive_z"]], 3, App.Vector(0, 0, 1)),
        ("TorqueNegativeZ", [end_edges["negative_z"]], 3, App.Vector(0, 0, -1)),
    ):
        line = doc.addObject("Part::Feature", name + "Direction")
        line.Shape = Part.makeLine(App.Vector(), direction)
        load = ObjectsFem.makeConstraintForce(doc, name)
        load.References = [(geometry, names)]
        load.Force = f"{amount} N"
        load.Direction = (line, ["Edge1"])
        load.Reversed = False
        analysis.addObject(load)

    cuts = []
    solids = {"a_right": solids_at(7.5), "b_left": solids_at(22.5)}
    testcase.assertEqual(len(solids["a_right"]), 3)
    testcase.assertEqual(len(solids["b_left"]), 1)
    for name, x, normal, owner_names, face_count in (
        ("CutARight", 5, -1, solids["a_right"], 3),
        ("CutBLeft", 25, 1, solids["b_left"], 1),
    ):
        owner = geometry
        names = faces_at(owner, "x", x, normal)
        if not names:
            owner = doc.addObject("Part::Reverse", name + "Orientation")
            owner.Source = geometry
            doc.recompute()
            names = faces_at(owner, "x", x, normal)
        testcase.assertEqual(len(names), face_count, (name, names))
        testcase.assertAlmostEqual(sum(owner.getSubObject(item).Area for item in names), 4, places=9)
        section = ObjectsFem.makeConstraintSectionPrint(doc, name)
        section.References = [(owner, names)]
        section.AccountingBody = [(geometry, owner_names)]
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
    testcase.assertEqual(mesher.process.exitCode(), 0)
    testcase.assertEqual(mesher.process.exitStatus(), mesher.process.ExitStatus.NormalExit)
    testcase.assertGreater(mesh.FemMesh.VolumeCount, 0)
    memberships = {}
    for key in ("fixed", "partial", "moving_a", "moving_b"):
        memberships[key] = sorted({node for name in faces[key]
                                   for node in mesh.FemMesh.getNodesByFace(geometry.getSubObject(name))})
        testcase.assertGreaterEqual(len(memberships[key]), 3)
    testcase.assertFalse(set(memberships["fixed"]) & set(memberships["partial"]))
    testcase.assertFalse(set(memberships["moving_a"]) & set(memberships["moving_b"]))
    for key in ("fixed", "partial"):
        testcase.assertTrue(all(abs(mesh.FemMesh.Nodes[node].x) < 1e-8 for node in memberships[key]))
    groups = {mesh.FemMesh.getGroupName(group): set(mesh.FemMesh.getGroupElements(group))
              for group in mesh.FemMesh.Groups}
    cell_nodes = {}
    for index in range(1, 9):
        name = f"Solid{index}"
        testcase.assertTrue(groups[name], name)
        cell_nodes[name] = {node for element in groups[name] for node in mesh.FemMesh.getElementNodes(element)}
    continuity = {"shared_native_face_pairs": [], "physical_beam_components": []}
    beam_cells = [[f"Solid{index}" for index, solid in enumerate(geometry.Shape.Solids, 1)
                   if lower < solid.CenterOfMass.x < upper] for lower, upper in ((0, 10), (20, 30))]
    beam_nodes = [set().union(*(cell_nodes[name] for name in names)) for names in beam_cells]
    testcase.assertFalse(beam_nodes[0] & beam_nodes[1])
    for names in beam_cells:
        adjacent = {name: set() for name in names}
        for left_index, left in enumerate(names):
            for right in names[left_index + 1:]:
                area = geometry.getSubObject(left).common(geometry.getSubObject(right)).Area
                if area > 1e-8:
                    shared = cell_nodes[left] & cell_nodes[right]
                    testcase.assertGreaterEqual(len(shared), 6, (left, right, area, shared))
                    adjacent[left].add(right)
                    adjacent[right].add(left)
                    continuity["shared_native_face_pairs"].append(
                        {"left": left, "right": right, "shared_CAD_area_mm2": area,
                         "shared_native_node_count": len(shared)})
        visited = set()
        pending = [names[0]]
        while pending:
            current = pending.pop()
            if current not in visited:
                visited.add(current)
                pending.extend(adjacent[current] - visited)
        testcase.assertEqual(visited, set(names))
        continuity["physical_beam_components"].append(sorted(visited))
    for owner_names in solids.values():
        body_nodes = set().union(*(cell_nodes[name] for name in owner_names))
        for key in ("fixed", "partial"):
            testcase.assertFalse(set(memberships[key]) & body_nodes)
    return SimpleNamespace(analysis=analysis, solver=solver, geometry=geometry, material=material,
                           supports=supports, bodies=bodies, cuts=cuts, mesh=mesh,
                           faces=faces, solids=solids, memberships=memberships, end_edges=end_edges,
                           continuum_membership_proof=continuity)


def properties(model):
    names = (
        "References", "ReferenceNode", "Displacement", "Rotation",
        *("TranslationalMode" + axis for axis in "XYZ"), *("RotationalMode" + axis for axis in "XYZ"),
        "xFree", "yFree", "zFree", "xDisplacement", "yDisplacement", "zDisplacement",
        "Attachment", "Mode", "Kind", "Axis", "Orientation", "RigidBody1", "RigidBody2",
        "Stiffness", "RotationalStiffness", "Force", "Direction", "Reversed",
        "NativeEquilibriumCut", "AccountingBody", "NativeForceAccounting",
        "NativeAccountingSolver", "NativeAccountingSupports", "Material")
    return {item.Name: {"type": item.TypeId, "properties": {
        name: {"type": item.getTypeIdOfProperty(name), "value": plain(getattr(item, name))}
        for name in names if name in item.PropertiesList}}
        for item in model.analysis.Group if item != model.mesh}


class OrdinarySupportsWitness(unittest.TestCase):
    def test_native_fixed_and_partial_support_selection_first_red(self):
        output = Path(os.environ["YWU_OUTPUT"]) / "witness"
        output.mkdir()
        for directory in ("mesh", "stock-off", "accounting-on"):
            (output / directory).mkdir()
        proposal = Path(__file__).resolve().parent / "oracle-spec-proposal.json"
        receipt = {"passed": False, "schema": "FreeCAD-ywu-native-ordinary-support-first-red-v1",
                   "frozen_support_partition_oracle": str(proposal), "oracle_sha256": sha(proposal),
                   "Oomakhi_opened_or_solved": False, "no_deck_patches_or_mocks": True,
                   "no_external_support_RBE_or_added_stiffness": True,
                   "aggregate_support_target": [-12, 0, 0, -6, -36, 24],
                   "individual_patch_reaction_targets": "Unspecified; not fitted."}
        doc = App.newDocument("YwuOrdinarySupports")
        try:
            model = make_fixture(self, doc, output)
            data = model.mesh.FemMesh
            write_json(output / "mesh-membership.json", {
                "selected_face_nodes": model.memberships, "face_keys": model.faces,
                "cut_owner_solid_keys": model.solids, "end_edge_loads": model.end_edges,
                "actual_geometry_solid_count": len(model.geometry.Shape.Solids),
                "actual_geometry_volume_mm3": model.geometry.Shape.Volume,
                "conforming_continuum_membership_proof": model.continuum_membership_proof,
                "native_groups": {data.getGroupName(group): sorted(data.getGroupElements(group))
                                  for group in data.Groups},
                "nodes": {str(node): plain(point) for node, point in data.Nodes.items()},
                "volume_connectivity": {str(element): list(data.getElementNodes(element))
                                        for element in data.Volumes}})
            write_json(output / "native-properties-off.json", properties(model))
            doc.recompute()
            saved_off = output / "ordinary-supports-stock-off.FCStd"
            doc.saveAs(str(saved_off))
            receipt["stock_off_document_sha256"] = sha(saved_off)
            fea = FemToolsCcx(analysis=model.analysis, solver=model.solver)
            fea.update_objects()
            fea.setup_working_dir(str(output / "stock-off"))
            fea.write_inp_file()
            receipt["stock_off_deck"] = fea.inp_file_name
            receipt["stock_off_deck_sha256"] = sha(fea.inp_file_name)
            code = fea.ccx_run()
            (output / "stock-off.stdout").write_text(fea.ccx_stdout)
            (output / "stock-off.stderr").write_text(fea.ccx_stderr)
            receipt["stock_off_returncode"] = code
            receipt["stock_off_binary"] = str(fea.ccx_binary)
            receipt["stock_off_binary_sha256"] = sha(fea.ccx_binary)
            self.assertEqual(code, 0)
            self.assertTrue(Path(fea.inp_file_name).with_suffix(".frd").is_file())
            fea.load_results()
            self.assertTrue(fea.results_present)
            results = [item for item in model.analysis.Group if item.isDerivedFrom("Fem::FemResultObject")]
            self.assertTrue(results)
            receipt["stock_imported_result_objects"] = [item.Name for item in results]

            model.solver.NativeForceAccounting = True
            for cut in model.cuts:
                cut.NativeEquilibriumCut = True
            self.assertEqual(list(model.solver.NativeAccountingSupports), model.supports)
            self.assertFalse(model.supports[1].xFree)
            self.assertTrue(model.supports[1].yFree)
            self.assertTrue(model.supports[1].zFree)
            doc.recompute()
            write_json(output / "native-properties-on.json", properties(model))
            saved_on = output / "ordinary-supports-accounting-on.FCStd"
            doc.saveAs(str(saved_on))
            receipt["accounting_on_document_sha256"] = sha(saved_on)
            fea = FemToolsCcx(analysis=model.analysis, solver=model.solver)
            fea.update_objects()
            fea.setup_working_dir(str(output / "accounting-on"))
            try:
                fea.write_inp_file()
            except ValueError as error:
                receipt["accounting_on_exception"] = {"type": type(error).__name__, "message": str(error),
                                                       "traceback": traceback.format_exc()}
                write_json(output / "accounting-on-exception.json", receipt["accounting_on_exception"])
                self.assertIn("Selected native accounting support is not a supported analysis constraint.", str(error))
                receipt["expected_unsupported_selection_red_reproduced"] = True
            else:
                self.fail("Expected unsupported ordinary-support selection ValueError was not reproduced")
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
            print("YWU_ORDINARY_SUPPORTS_RED=" + str(output), flush=True)
            if doc.Name in App.listDocuments():
                App.closeDocument(doc.Name)
