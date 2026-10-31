# SPDX-License-Identifier: LGPL-2.1-or-later
"""Analytical native beam-end actions through the stock author/solve/read route.

These small software fixtures do not qualify a building or substitute a model.
The native observer is selected normally; generated solver input is not edited.
"""

import math
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import FreeCAD as App
import Fem
import ObjectsFem
from femtools.ccxtools import FemToolsCcx
from femtools.force_accounting import solver_binary


def make_straight_case(doc, load_vector=(100.0, 0.0, 0.0)):
    """Author the fixed 100 mm, 2 by 4 mm, five-Seg3 qualification beam."""
    if len(load_vector) != 3:
        raise ValueError("load_vector must have three components")
    load_vector = tuple(float(value) for value in load_vector)
    if not all(math.isfinite(value) for value in load_vector):
        raise ValueError("load_vector components must be finite")
    magnitude = math.sqrt(sum(value * value for value in load_vector))
    if not math.isfinite(magnitude) or magnitude <= 0:
        raise ValueError("load_vector must have a finite positive magnitude")

    geometry = doc.addObject("Part::Line", "BeamLine")
    geometry.X1 = geometry.Y1 = geometry.Z1 = 0.0
    geometry.X2 = 100.0
    geometry.Y2 = geometry.Z2 = 0.0
    load_direction = doc.addObject("Part::Line", "LoadDirection")
    load_direction.X1 = load_direction.Y1 = load_direction.Z1 = 0.0
    load_direction.X2, load_direction.Y2, load_direction.Z2 = (
        value / magnitude for value in load_vector
    )
    doc.recompute()

    analysis = ObjectsFem.makeAnalysis(doc, "Analysis")
    solver = ObjectsFem.makeSolverCalculiXCcxTools(doc, "Solver")
    solver.AnalysisType = "static"
    solver.GeometricalNonlinearity = False
    solver.ReducedIntegration = True
    solver.Output3d = False
    solver.BeamSectionForces = True
    solver.SplitInputWriter = False
    solver.WorkingDir = ""
    analysis.addObject(solver)

    section = ObjectsFem.makeElementGeometry1D(
        doc,
        sectiontype="Rectangular",
        width=2.0,
        height=4.0,
        name="BeamCrossSection",
    )
    analysis.addObject(section)
    material = ObjectsFem.makeMaterialSolid(doc, "MechanicalMaterial")
    material.Material = {
        "Name": "Beam960LinearElastic",
        "YoungsModulus": "100000 MPa",
        "PoissonRatio": "0.30",
        "Density": "7850 kg/m^3",
    }
    analysis.addObject(material)
    fixed = ObjectsFem.makeConstraintFixed(doc, "Fixed")
    fixed.References = [(geometry, "Vertex1")]
    analysis.addObject(fixed)
    force = ObjectsFem.makeConstraintForce(doc, "Force")
    force.References = [(geometry, "Vertex2")]
    force.Force = f"{magnitude:.17g} N"
    force.Direction = (load_direction, ["Edge1"])
    force.Reversed = False
    analysis.addObject(force)

    native_mesh = Fem.FemMesh()
    for node in range(1, 12):
        native_mesh.addNode(10.0 * (node - 1), 0.0, 0.0, node)
    for element in range(1, 6):
        start = 2 * element - 1
        # Native FemMesh Seg3 ordering is start, end, midside.
        native_mesh.addEdge([start, start + 2, start + 1], element)
    mesh = ObjectsFem.makeMeshGmsh(doc, "Mesh")
    mesh.Shape = geometry
    mesh.FemMesh = native_mesh
    mesh.SecondOrderLinear = False
    mesh.ElementDimension = "1D"
    mesh.CharacteristicLengthMax = "20 mm"
    mesh.CharacteristicLengthMin = "20 mm"
    analysis.addObject(mesh)
    doc.recompute()
    if App.GuiUp:
        load_direction.ViewObject.Visibility = False
    return SimpleNamespace(
        doc=doc,
        analysis=analysis,
        solver=solver,
        mesh=mesh,
        section=section,
        force=force,
        geometry=geometry,
        root_node=1,
        tip_node=11,
    )


def make_torsion_case(doc):
    """Author one shared-node T frame loaded by an explicit native force couple."""
    model = make_straight_case(doc, load_vector=(0.0, 0.0, 0.01))
    stem = model.geometry
    positive_arm = doc.addObject("Part::Line", "PositiveArm")
    negative_arm = doc.addObject("Part::Line", "NegativeArm")
    for arm, end_y in ((positive_arm, 10.0), (negative_arm, -10.0)):
        arm.X1 = arm.X2 = 100.0
        arm.Y1 = arm.Z1 = arm.Z2 = 0.0
        arm.Y2 = end_y
    geometry = doc.addObject("Part::Compound", "TFrame")
    geometry.Links = [stem, positive_arm, negative_arm]
    model.force.References = [(positive_arm, "Vertex2")]
    model.force.Force = "0.01 N"
    negative_force = ObjectsFem.makeConstraintForce(doc, "NegativeForce")
    negative_force.References = [(negative_arm, "Vertex2")]
    negative_force.Force = "0.01 N"
    negative_force.Direction = model.force.Direction
    negative_force.Reversed = True
    model.analysis.addObject(negative_force)

    native_mesh = Fem.FemMesh()
    for node in range(1, 12):
        native_mesh.addNode(10.0 * (node - 1), 0.0, 0.0, node)
    for element in range(1, 6):
        start = 2 * element - 1
        native_mesh.addEdge([start, start + 2, start + 1], element)
    for node, y in ((12, 5.0), (13, 10.0), (14, -5.0), (15, -10.0)):
        native_mesh.addNode(100.0, y, 0.0, node)
    native_mesh.addEdge([11, 13, 12], 6)
    native_mesh.addEdge([11, 15, 14], 7)
    model.mesh.Shape = geometry
    model.mesh.FemMesh = native_mesh
    doc.recompute()
    model.geometry = geometry
    model.stem = stem
    model.positive_arm = positive_arm
    model.negative_arm = negative_arm
    model.negative_force = negative_force
    model.junction_node = 11
    return model


class TestBeamSectionForcesNative(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("BeamSectionForcesTransverse")
        self.temporary = None
        self.preferences = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/Ccx")
        self.previous_binary = self.preferences.GetString("ccxBinaryPath", "")
        self.had_binary = self.previous_binary == self.preferences.GetString(
            "ccxBinaryPath", "<absent>"
        )
        self.previous_cpus = self.preferences.GetInt("AnalysisNumCPUs", 1)
        self.had_cpus = self.previous_cpus == self.preferences.GetInt("AnalysisNumCPUs", 2)

    def tearDown(self):
        try:
            if self.doc.Name in App.listDocuments():
                App.closeDocument(self.doc.Name)
        finally:
            if self.had_binary:
                self.preferences.SetString("ccxBinaryPath", self.previous_binary)
            else:
                self.preferences.RemString("ccxBinaryPath")
            if self.had_cpus:
                self.preferences.SetInt("AnalysisNumCPUs", self.previous_cpus)
            else:
                self.preferences.RemInt("AnalysisNumCPUs")
            if self.temporary is not None:
                self.temporary.cleanup()

    def solve_straight_case(self, load_vector):
        model = make_straight_case(self.doc, load_vector=load_vector)
        # A bare numeric Force is in FreeCAD's internal millinewtons. Check
        # the native authored quantity and the untouched stock CLOAD below,
        # so a fixture unit mistake cannot be classified as solver error.
        magnitude = math.sqrt(sum(value * value for value in load_vector))
        self.assertAlmostEqual(model.force.Force.getValueAs("N").Value, magnitude)
        expected_loads = [
            (model.tip_node, direction, value)
            for direction, value in enumerate(load_vector, 1)
            if value
        ]
        expected_ends = {
            (element, node, end)
            for element in range(1, 6)
            for node, end in ((2 * element - 1, 1), (2 * element + 1, 3))
        }
        expected_axes = {element: [0.0, 1.0, 0.0] for element in range(1, 6)}
        return self.solve_model(model, expected_loads, expected_ends, expected_axes)

    def solve_model(self, model, expected_loads, expected_ends, expected_axes):
        binary = Path(os.environ.get("B960_TEST_SOLVER", solver_binary(model.solver)))
        self.assertTrue(binary.is_absolute(), "Select the absolute qualified native solver")
        binary = str(binary.resolve(strict=True))
        model.solver.NativeAccountingSolver = binary
        self.preferences.SetString("ccxBinaryPath", binary)
        self.preferences.SetInt("AnalysisNumCPUs", 2)

        retained = os.environ.get("B960_WITNESS_ROOT")
        if retained:
            directory = Path(retained) / self._testMethodName
            directory.mkdir()
        else:
            self.temporary = tempfile.TemporaryDirectory(prefix="freecad-beam-native-")
            directory = Path(self.temporary.name)
        fea = FemToolsCcx(analysis=model.analysis, solver=model.solver)
        fea.update_objects()
        fea.setup_working_dir(str(directory))
        self.assertEqual(Path(fea.working_dir).resolve(), directory.resolve())
        self.assertFalse(fea.check_prerequisites())
        self.assertFalse(fea.write_inp_file())
        mode = ""
        loads = []
        for raw in Path(fea.inp_file_name).read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("**"):
                continue
            if line.startswith("*"):
                mode = line.split(",", 1)[0].upper()
            elif mode == "*CLOAD":
                node, direction, value = line.split(",")
                loads.append((int(node), int(direction), float(value)))
        self.assertEqual(len(loads), len(expected_loads))
        for actual, expected in zip(sorted(loads), sorted(expected_loads)):
            self.assertEqual(actual[:2], expected[:2])
            self.assertTrue(math.isclose(actual[2], expected[2], rel_tol=1e-12, abs_tol=0.0))
        self.assertEqual(fea.ccx_run(), 0, fea.ccx_stdout + fea.ccx_stderr)
        fea.load_results()
        results = [
            obj
            for obj in model.analysis.Group
            if getattr(getattr(obj, "Proxy", None), "Type", "") == "Fem::BeamSectionForceResult"
        ]
        self.assertEqual(len(results), 1)
        result = results[0]
        data = result.Proxy.getSectionForces(result)
        self.assertEqual(data["schema"], "CCX_BEAM_SECTION_V1")
        self.assertEqual(data["units"], {"length": "mm", "force": "N", "moment": "N*mm"})
        self.assertEqual(
            data["provenance"]["case"],
            {"analysis": model.analysis.Name, "solver": model.solver.Name, "mesh": model.mesh.Name},
        )
        self.assertEqual(len(data["provenance"]["elements"]), len(expected_ends) // 2)
        for element in data["provenance"]["elements"]:
            self.assertEqual(element["section"], model.section.Name)
            self.assertEqual(element["dimensions_mm"], [2.0, 4.0])
            # Qualify what the stock writer actually wrote; never inject an
            # input orientation or replace the observed current face basis.
            reference = element["reference_n1"]
            self.assertTrue(all(math.isfinite(value) for value in reference))
            reference_axis = App.Vector(*reference)
            self.assertAlmostEqual(reference_axis.Length, 1.0, delta=1e-10)
            first, _, last = element["nodes"]
            direction = model.mesh.FemMesh.Nodes[last] - model.mesh.FemMesh.Nodes[first]
            self.assertLessEqual(abs(reference_axis.dot(direction)) / direction.Length, 1e-10)
            if expected_axes is not None:
                self.assertEqual(reference, expected_axes[element["element"]])
        self.assertEqual(len(data["frames"]), 1)
        frame = data["frames"][0]
        self.assertEqual(frame["step"], 1)
        self.assertEqual(frame["time"], 1.0)
        self.assertEqual(
            {(row["element"], row["node"], row["end"]) for row in frame["samples"]},
            expected_ends,
        )
        roots = [
            row
            for row in frame["samples"]
            if (row["element"], row["node"], row["end"]) == (1, model.root_node, 1)
        ]
        self.assertEqual(len(roots), 1)
        self.assertTrue(result.Status.startswith("Current"), result.Status)
        return SimpleNamespace(
            model=model, fea=fea, result=result, data=data, frame=frame, root=roots[0]
        )

    def assert_root_action(self, case, expected_force, expected_moment, force_scale, moment_scale):
        force = App.Vector(*case.root["force_global"])
        moment = App.Vector(*case.root["moment_global"])
        self.assertLessEqual((force - App.Vector(*expected_force)).Length / force_scale, 0.01)
        self.assertLessEqual((moment - App.Vector(*expected_moment)).Length / moment_scale, 0.01)

    def assert_t_junction_identity(self, case):
        junction = [row for row in case.frame["samples"] if row["node"] == case.model.junction_node]
        self.assertEqual(len(junction), 3)
        self.assertEqual(
            {(row["element"], row["node"], row["end"]) for row in junction},
            {(5, 11, 3), (6, 11, 1), (7, 11, 1)},
        )

    def assert_literal_native_projections(self, case):
        for row in case.frame["samples"]:
            axes = {name: App.Vector(*value) for name, value in row["basis"].items()}
            determinant = axes["e1"].cross(axes["e2"]).dot(axes["normal"])
            self.assertAlmostEqual(determinant, -1.0 if row["end"] == 1 else 1.0, delta=1e-8)
            force = App.Vector(*row["force_global"])
            moment = App.Vector(*row["moment_global"])
            for channel, axis, global_vector in (
                ("shear1", "e1", force),
                ("shear2", "e2", force),
                ("axial", "normal", force),
                ("torque", "normal", moment),
                ("bend2", "e2", moment),
                ("bend1", "e1", moment),
            ):
                projected = axes[axis].dot(global_vector)
                literal = row["native_channels"][channel]
                # Wire/projection consistency is separate from equilibrium.
                # Dot projection is valid even in the first-end left-handed
                # frame; do not invent a right-handed replacement normal.
                self.assertLessEqual(
                    abs(literal - projected), 1e-12 * max(1.0, abs(literal), abs(projected))
                )

    def test_transverse_y_root_has_signed_shear_and_bending_equilibrium(self):
        # Independent predeclared free body: a +0.1 N Y force at x=100 mm
        # requires root action (0,-0.1,0) N and couple (0,0,-10) N*mm.
        # Neither reference nor the unchanged 1% limits uses recovered output.
        case = self.solve_straight_case((0.0, 0.1, 0.0))
        self.assert_root_action(case, (0.0, -0.1, 0.0), (0.0, 0.0, -10.0), 0.1, 10.0)

    def test_transverse_z_root_has_signed_shear_and_orthogonal_bending_equilibrium(self):
        # +0.2 N Z at x=100 mm gives applied M=(0,-20,0) N*mm;
        # the retained member's root action is the opposite wrench.
        case = self.solve_straight_case((0.0, 0.0, 0.2))
        self.assert_root_action(case, (0.0, 0.0, -0.2), (0.0, 20.0, 0.0), 0.2, 20.0)

    def test_axial_tension_root_has_negative_global_end_action(self):
        case = self.solve_straight_case((100.0, 0.0, 0.0))
        # Zero moment uses the fixed applied-force times 100 mm length scale,
        # not a floor or a reference computed from recovered section output.
        self.assert_root_action(case, (-100.0, 0.0, 0.0), (0.0, 0.0, 0.0), 100.0, 10000.0)

    def test_axial_compression_root_reverses_the_global_end_action(self):
        case = self.solve_straight_case((-100.0, 0.0, 0.0))
        self.assert_root_action(case, (100.0, 0.0, 0.0), (0.0, 0.0, 0.0), 100.0, 10000.0)

    def test_torsion_couple_preserves_distinct_native_ends_at_a_shared_joint(self):
        # A +0.01 N Z load at y=+10 mm and -0.01 N Z at y=-10 mm
        # give zero force and +0.2 N*mm X moment. The root action is the
        # opposite wrench. The zero-force scale is the fixed 0.02 N sum of
        # the two applied load magnitudes; neither 1% limit is relaxed.
        model = make_torsion_case(self.doc)
        self.assertAlmostEqual(model.force.Force.getValueAs("N").Value, 0.01)
        self.assertAlmostEqual(model.negative_force.Force.getValueAs("N").Value, 0.01)
        expected_ends = {
            (element, node, end)
            for element in range(1, 6)
            for node, end in ((2 * element - 1, 1), (2 * element + 1, 3))
        } | {(6, 11, 1), (6, 13, 3), (7, 11, 1), (7, 15, 3)}
        expected_axes = {
            **{element: [0.0, 1.0, 0.0] for element in range(1, 6)},
            6: [-1.0, 0.0, 0.0],
            7: [1.0, 0.0, 0.0],
        }
        case = self.solve_model(
            model,
            [(13, 3, 0.01), (15, 3, -0.01)],
            expected_ends,
            expected_axes,
        )
        self.assert_root_action(case, (0.0, 0.0, 0.0), (-0.2, 0.0, 0.0), 0.02, 0.2)
        self.assert_t_junction_identity(case)
        self.assert_literal_native_projections(case)

    def test_rotated_translated_torsion_preserves_global_actions_and_native_end_axes(self):
        model = make_torsion_case(self.doc)
        rotation = App.Rotation(App.Vector(1.0, 2.0, 3.0), 31.0)
        translation = App.Vector(37.0, -19.0, 11.0)

        # Move the actual native line endpoints, not result Shapes or a deck.
        # The direction line is translated too; only its rotated vector sets
        # force direction. The two native force magnitudes remain 0.01 N.
        load_direction = model.force.Direction[0]
        for line in (model.stem, model.positive_arm, model.negative_arm, load_direction):
            first, last = (vertex.Point for vertex in line.Shape.Vertexes)
            first = rotation.multVec(first) + translation
            last = rotation.multVec(last) + translation
            line.X1, line.Y1, line.Z1 = first
            line.X2, line.Y2, line.Z2 = last
        original = model.mesh.FemMesh
        nodes = {node: App.Vector(point) for node, point in original.Nodes.items()}
        connectivity = {
            element: tuple(original.getElementNodes(element)) for element in original.Edges
        }
        transformed = Fem.FemMesh()
        for node, point in sorted(nodes.items()):
            point = rotation.multVec(point) + translation
            transformed.addNode(point.x, point.y, point.z, node)
        for element, ids in sorted(connectivity.items()):
            transformed.addEdge(list(ids), element)
        model.mesh.FemMesh = transformed
        self.doc.recompute()
        self.assertEqual(set(model.mesh.FemMesh.Nodes), set(nodes))
        self.assertEqual(
            {
                element: tuple(model.mesh.FemMesh.getElementNodes(element))
                for element in model.mesh.FemMesh.Edges
            },
            connectivity,
        )
        self.assertAlmostEqual(model.force.Force.getValueAs("N").Value, 0.01)
        self.assertAlmostEqual(model.negative_force.Force.getValueAs("N").Value, 0.01)
        direction = rotation.multVec(App.Vector(0.0, 0.0, 1.0))
        expected_loads = [
            (node, axis, sign * 0.01 * value)
            for node, sign in ((13, 1.0), (15, -1.0))
            for axis, value in enumerate(direction, 1)
            if value
        ]
        expected_ends = {
            (element, node, end)
            for element in range(1, 6)
            for node, end in ((2 * element - 1, 1), (2 * element + 1, 3))
        } | {(6, 11, 1), (6, 13, 3), (7, 11, 1), (7, 15, 3)}
        # Stock automatic section orientation is global-frame dependent. Its
        # actual written axis is checked for finiteness and orthonormality,
        # not replaced by R times the old reference direction.
        case = self.solve_model(model, expected_loads, expected_ends, expected_axes=None)
        expected_moment = rotation.multVec(App.Vector(-0.2, 0.0, 0.0))
        self.assert_root_action(case, (0.0, 0.0, 0.0), tuple(expected_moment), 0.02, 0.2)
        self.assertLessEqual((App.Vector(*case.root["position"]) - translation).Length, 1e-8)
        self.assertEqual(case.data["moment_reference"], "NATIVE_SECTION_CENTROID")
        self.assert_t_junction_identity(case)
        self.assert_literal_native_projections(case)
        tangent = rotation.multVec(App.Vector(1.0, 0.0, 0.0))
        for row in case.frame["samples"]:
            if row["element"] <= 5:
                expected_normal = tangent * (-1.0 if row["end"] == 1 else 1.0)
                normal = App.Vector(*row["basis"]["normal"])
                # Predeclared small-angle geometry check, independent of the
                # unchanged force/moment equilibrium and wire tolerances.
                self.assertLessEqual(normal.getAngle(expected_normal), 0.001)
