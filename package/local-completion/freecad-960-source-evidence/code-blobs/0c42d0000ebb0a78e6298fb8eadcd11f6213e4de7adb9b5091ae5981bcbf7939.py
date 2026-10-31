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
    force.Force = magnitude
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

    def test_transverse_y_root_has_signed_shear_and_bending_equilibrium(self):
        # Independent predeclared free body: a +0.1 N Y force at x=100 mm
        # requires root action (0,-0.1,0) N and couple (0,0,-10) N*mm.
        # Neither reference nor the unchanged 1% limits uses recovered output.
        model = make_straight_case(self.doc, load_vector=(0.0, 0.1, 0.0))
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
            self.temporary = tempfile.TemporaryDirectory(prefix="freecad-beam-transverse-y-")
            directory = Path(self.temporary.name)
        fea = FemToolsCcx(analysis=model.analysis, solver=model.solver)
        fea.update_objects()
        fea.setup_working_dir(str(directory))
        self.assertEqual(Path(fea.working_dir).resolve(), directory.resolve())
        self.assertFalse(fea.check_prerequisites())
        self.assertFalse(fea.write_inp_file())
        self.assertEqual(fea.ccx_run(), 0, fea.ccx_stdout + fea.ccx_stderr)
        fea.load_results()
        results = [
            obj
            for obj in model.analysis.Group
            if getattr(getattr(obj, "Proxy", None), "Type", "")
            == "Fem::BeamSectionForceResult"
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
        self.assertEqual(len(data["provenance"]["elements"]), 5)
        for element in data["provenance"]["elements"]:
            self.assertEqual(element["section"], model.section.Name)
            self.assertEqual(element["dimensions_mm"], [2.0, 4.0])
            # Qualify what the stock writer actually wrote; never inject an
            # input orientation or replace the observed current face basis.
            self.assertEqual(element["reference_n1"], [0.0, 1.0, 0.0])
        self.assertEqual(len(data["frames"]), 1)
        frame = data["frames"][0]
        self.assertEqual(frame["step"], 1)
        self.assertEqual(frame["time"], 1.0)
        expected_ends = {
            (element, node, end)
            for element in range(1, 6)
            for node, end in ((2 * element - 1, 1), (2 * element + 1, 3))
        }
        self.assertEqual(
            {(row["element"], row["node"], row["end"]) for row in frame["samples"]},
            expected_ends,
        )
        roots = [
            row for row in frame["samples"]
            if (row["element"], row["node"], row["end"]) == (1, model.root_node, 1)
        ]
        self.assertEqual(len(roots), 1)
        force = App.Vector(*roots[0]["force_global"])
        moment = App.Vector(*roots[0]["moment_global"])
        self.assertLessEqual((force - App.Vector(0.0, -0.1, 0.0)).Length / 0.1, 0.01)
        self.assertLessEqual((moment - App.Vector(0.0, 0.0, -10.0)).Length / 10.0, 0.01)
        self.assertTrue(result.Status.startswith("Current"), result.Status)
