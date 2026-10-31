# SPDX-License-Identifier: LGPL-2.1-or-later
"""Coupled native beam actions through ordinary author/export/solve/import APIs."""

import json
import os
from pathlib import Path
import tempfile
import unittest

import FreeCAD as App
import Fem
import ObjectsFem

from femtest.app.test_beam_section_forces_native import make_straight_case
from femtools.ccxtools import FemToolsCcx
from femtools.beam_section_forces import require_capability
from femtools.force_accounting import solver_binary


def make_series(doc, load_vector=(10, 0, 0)):
    """The independently specified translated beam and scalar ground spring."""
    model = make_straight_case(doc, load_vector=load_vector)
    shift = App.Vector(10, 20, 30)
    for axis, value in zip("XYZ", shift):
        for end in ("1", "2"):
            setattr(model.geometry, axis + end, getattr(model.geometry, axis + end).Value + value)
    original = model.mesh.FemMesh
    native = Fem.FemMesh()
    for node, point in original.Nodes.items():
        native.addNode(*(point + shift), node)
    for element in original.Edges:
        native.addEdge(list(original.getElementNodes(element)), element)
    model.mesh.FemMesh = native
    doc.removeObject("Fixed")
    support = ObjectsFem.makeConstraintDisplacement(doc, "Stabilizer")
    support.References = [(model.geometry, "Vertex1")]
    support.xFree = True
    support.yFree = support.zFree = False
    support.rotxFree = support.rotyFree = support.rotzFree = False
    model.analysis.addObject(support)
    connector = ObjectsFem.makeConstraintElasticConnector(doc, "GroundSpring")
    connector.End1 = (model.geometry, ["Vertex1"])
    connector.Stiffness = "2000 N/mm"
    connector.Axis = "X"
    connector.Mode = "Ground"
    model.analysis.addObject(connector)
    model.connector, model.stabilizer = connector, support
    doc.recompute()
    return model


class TestBeamCouplingNative(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("NativeCoupledBeam")
        self.temporary = None

    def tearDown(self):
        if self.doc.Name in App.listDocuments():
            App.closeDocument(self.doc.Name)
        if self.temporary is not None:
            self.temporary.cleanup()

    def solve(self, load_vector=(10, 0, 0)):
        model = make_series(self.doc, load_vector)
        if os.environ.get("SV7_TEST_SOLVER"):
            model.solver.NativeAccountingSolver = os.environ["SV7_TEST_SOLVER"]
        else:
            try:
                require_capability(solver_binary(model.solver), coupled=True)
            except (OSError, ValueError) as error:
                self.skipTest("Qualified coupled beam observer required: " + str(error))
        retained = os.environ.get("SV7_WITNESS_ROOT")
        if retained:
            directory = Path(retained) / self._testMethodName
            directory.mkdir(parents=True)
        else:
            self.temporary = tempfile.TemporaryDirectory(prefix="freecad-beam-coupling-")
            directory = Path(self.temporary.name)
        fea = FemToolsCcx(analysis=model.analysis, solver=model.solver)
        fea.update_objects()
        fea.setup_working_dir(str(directory))
        self.assertFalse(fea.check_prerequisites())
        self.assertFalse(fea.write_inp_file())
        deck = Path(fea.inp_file_name).read_bytes()
        (directory / "stock-input.inp").write_bytes(deck)
        self.assertEqual(fea.ccx_run(), 0, fea.ccx_stdout + fea.ccx_stderr)
        self.assertEqual(Path(fea.inp_file_name).read_bytes(), deck)
        fea.load_results()
        result = next(obj for obj in model.analysis.Group if obj.Name == "BeamSectionForces")
        data = result.Proxy.getSectionForces(result)
        self.assertEqual(data["schema"], "CCX_BEAM_SECTION_V2")
        (directory / "observed.json").write_text(json.dumps(data, indent=2))
        return model, result, data, directory

    def assert_vector(self, actual, expected, limit):
        self.assertLessEqual((App.Vector(*actual) - App.Vector(*expected)).Length, limit)

    def test_series_beam_ground_spring_and_restraints_share_one_owned_frame(self):
        model, result, data, directory = self.solve()
        frame = data["frames"][-1]
        actions = frame["native_actions"]
        self.assertEqual(actions["position_frame"], "ORIGINAL_GLOBAL")
        self.assertEqual(actions["moment_reference"], "GLOBAL_ORIGIN")
        self.assertEqual(actions["force_action"], "ON_STRUCTURAL_MODEL")
        for name, owner, force, moment in (
            ("source", "Force", (10, 0, 0), (0, 300, -200)),
            ("spring", "GroundSpring", (-10, 0, 0), (0, -300, 200)),
            ("support", "Stabilizer", (0, 0, 0), (0, 0, 0)),
        ):
            row = actions[name]
            self.assertEqual(row["owner"], owner)
            self.assert_vector(row["force_global"], force, 0.001)
            self.assert_vector(row["moment_origin"], moment, 0.1)
        spring = actions["spring"]
        self.assertEqual((spring["element"], spring["node"]), (6, 1))
        self.assert_vector(spring["native_resisting_force"], (10, 0, 0), 0.001)
        self.assertAlmostEqual(spring["displacement"][0], 0.005, delta=0.0000005)
        self.assertEqual(len(actions["support"]["spcs"]), 8)
        self.assertEqual(
            {row["role"] for row in actions["support"]["spcs"]},
            {"TRANSLATION", "ANGLE", "ALGEBRAIC"},
        )
        self.assertEqual(
            {(row["element"], row["node"], row["end"]) for row in frame["samples"]},
            {
                (element, node, end)
                for element in range(1, 6)
                for node, end in ((2 * element - 1, 1), (2 * element + 1, 3))
            },
        )
        for row in frame["samples"]:
            sign = -1 if row["end"] == 1 else 1
            self.assert_vector(row["force_global"], (sign * 10, 0, 0), 0.01)
            self.assert_vector(row["moment_global"], (0, 0, 0), 0.04)
        self.assertTrue(result.Status.startswith("Current"), result.Status)
        self.doc.saveAs(str(directory / "series.FCStd"))
        self.assertEqual(result.Proxy.getSectionForces(result), data)

    def test_transverse_components_observe_nonzero_physical_rotation_reactions(self):
        # Independently frozen small-displacement control; limits include the
        # bounded native-map geometry products, not measured errors.
        model, result, data, directory = self.solve((0.01, 0.0001, 0.0002))
        frame = data["frames"][-1]
        actions = frame["native_actions"]
        for name, force, moment in (
            ("source", (0.01, 0.0001, 0.0002), (0.001, 0.278, -0.189)),
            ("spring", (-0.01, 0, 0), (0, -0.3, 0.2)),
            ("support", (0, -0.0001, -0.0002), (-0.001, 0.022, -0.011)),
        ):
            self.assert_vector(actions[name]["force_global"], force, 0.000001)
            self.assert_vector(actions[name]["moment_origin"], moment, 0.0001)
        spcs = actions["support"]["spcs"]
        angles = {row["original_direction"]: row["value"] for row in spcs if row["role"] == "ANGLE"}
        self.assertAlmostEqual(angles[5], 0.02, delta=0.0001)
        self.assertAlmostEqual(angles[6], -0.01, delta=0.0001)
        self.assertTrue(
            any(abs(row["value"]) > 0.000001 for row in spcs if row["role"] == "ALGEBRAIC")
        )
        self.assertAlmostEqual(actions["spring"]["displacement"][0], 0.000005, delta=0.0000000005)
        for row in frame["samples"]:
            sign = -1 if row["end"] == 1 else 1
            for actual, expected, limit in zip(
                row["force_global"],
                (sign * 0.01, sign * 0.0001, sign * 0.0002),
                (0.00001, 0.0000001, 0.0000002),
            ):
                self.assertAlmostEqual(actual, expected, delta=limit)
        root = next(row for row in frame["samples"] if (row["element"], row["end"]) == (1, 1))
        self.assert_vector(root["moment_global"], (0, 0.02, -0.01), 0.00004)
        self.assertTrue(result.Status.startswith("Current"), result.Status)

    def test_unqualified_couplings_and_restraints_are_refused_before_export(self):
        changes = (
            ("two_ports", lambda model: setattr(model.connector, "Mode", "Two points")),
            ("rotational", lambda model: setattr(model.connector, "Kind", "Rotational")),
            ("prescribed", lambda model: setattr(model.stabilizer, "yDisplacement", "0.1 mm")),
            ("fixed_spring_dof", lambda model: setattr(model.stabilizer, "xFree", False)),
            (
                "solid_accounting",
                lambda model: setattr(model.solver, "NativeForceAccounting", True),
            ),
            (
                "support_selection",
                lambda model: setattr(model.solver, "NativeAccountingSupports", [model.stabilizer]),
            ),
        )
        for name, change in changes:
            with self.subTest(name=name):
                App.closeDocument(self.doc.Name)
                self.doc = App.newDocument("NativeCoupledRefusal")
                model = make_series(self.doc)
                change(model)
                with tempfile.TemporaryDirectory(prefix="freecad-beam-refusal-") as directory:
                    fea = FemToolsCcx(analysis=model.analysis, solver=model.solver)
                    fea.update_objects()
                    fea.setup_working_dir(directory)
                    with self.assertRaises(ValueError):
                        fea.write_inp_file()
                    self.assertFalse(list(Path(directory).glob("*.beam-section")))

    def test_stiffness_edit_withdraws_current_actions_and_preserves_literal_history(self):
        model, result, data, directory = self.solve()
        model.connector.Stiffness = "3000 N/mm"
        with self.assertRaises(ValueError):
            result.Proxy.getSectionForces(result)
        self.assertTrue(result.Status.startswith("Stale"), result.Status)
        self.assertEqual(result.Proxy.getSectionForces(result, historical=True), data)
        model.connector.Stiffness = "2000 N/mm"
        with self.assertRaises(ValueError):
            result.Proxy.getSectionForces(result)
