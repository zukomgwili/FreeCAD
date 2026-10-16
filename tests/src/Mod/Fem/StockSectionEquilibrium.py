# SPDX-License-Identifier: LGPL-2.1-or-later

"""Opt-in FreeCAD-9bp acceptance/convergence check, not a recovery tool.

Run FreeCAD[Cmd] -P tests/src/Mod/Fem -t StockSectionEquilibrium with
FREECAD_9BP_OUTPUT set to a new disposable directory. Uses the shipped example
mesh and real stock solver. Optional FREECAD_9BP_SECTION_SIZE (mm) regenerates
the mesh through native Gmsh for a convergence study, keeping the 5 mm global
size. Reads only solver-reported totals; never edits a deck or recovers forces.
The 1% vector-relative example tolerance is checked against exact free-body
equilibrium, not a fitted numerical reference. See the convergence receipt in
package/local-completion/freecad-9bp-convergence.json for the <0.5% refinement
change evidence. Neither tolerance constitutes building-design acceptance.
"""

import json
import os
from pathlib import Path
import re
import sys
import unittest

import FreeCAD as App
import Fem
from femmesh import meshsetsgetter
from femexamples.constraint_section_print import setup
from femtools.ccxtools import FemToolsCcx


class StockSectionEquilibrium(unittest.TestCase):
    def test_mesh_convergence_evidence(self):
        receipt = Path(__file__).resolve().parents[4] / "package/local-completion/freecad-9bp-convergence.json"
        study = json.loads(receipt.read_text())["local_refinement_study"]
        accepted = [row for row in study if row["section_size_mm"] <= 1.25]
        self.assertEqual(len(accepted), 3)
        expected_force = App.Vector(0, -60000, 0)
        expected_moment = App.Vector(0, 0, -3420000)
        previous = None
        for row in accepted:
            force = App.Vector(*row["force_N"])
            moment = App.Vector(*row["origin_moment_Nmm"])
            self.assertLess((force-expected_force).Length / expected_force.Length, 0.01)
            self.assertLess((moment-expected_moment).Length / expected_moment.Length, 0.01)
            if previous:
                self.assertLess((force-previous[0]).Length / expected_force.Length, 0.005)
                self.assertLess((moment-previous[1]).Length / expected_moment.Length, 0.005)
            previous = force, moment

    def test_shipped_example_equilibrium(self):
        root = Path(os.environ["FREECAD_9BP_OUTPUT"])
        root.mkdir(parents=True, exist_ok=False)
        solver_dir = root / "solver"
        solver_dir.mkdir()
        reopen = os.environ.get("FREECAD_9BP_REOPEN")
        doc = App.openDocument(reopen) if reopen else setup(test_mode=True)
        section_size = os.environ.get("FREECAD_9BP_SECTION_SIZE")
        prefs = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/General")
        overwrite = prefs.GetBool("OverwriteSolverWorkingDirectory", True)
        try:
            expected_commit = os.environ.get("FREECAD_9BP_COMMIT")
            if expected_commit:
                self.assertEqual(App.Version()[-1], expected_commit)
            module_paths = {
                "Fem": Fem.__file__,
                "example": sys.modules[setup.__module__].__file__,
                "meshsetsgetter": meshsetsgetter.__file__,
            }
            resource_root = os.environ.get("FREECAD_9BP_RESOURCES")
            if resource_root:
                for module_path in module_paths.values():
                    self.assertTrue(Path(module_path).is_relative_to(resource_root), module_path)
            if section_size:
                from femexamples.meshes.generate_mesh import mesh_from_mesher
                doc.SectionMeshRegion.CharacteristicLength = section_size + " mm"
                doc.recompute()
                self.assertTrue(mesh_from_mesher(doc.Mesh, "gmsh"))
            prefs.SetBool("OverwriteSolverWorkingDirectory", False)
            doc.CalculiXCcxTools.WorkingDir = str(solver_dir)
            fea = FemToolsCcx(analysis=doc.Analysis, solver=doc.CalculiXCcxTools)
            self.assertTrue(fea.run())
            self.assertTrue(fea.results_present)
            data = (solver_dir / "Mesh.dat").read_text()

            def values(title):
                match = re.search(title + r"[^\n]*\n\s*\n([^\n]+)", data)
                self.assertIsNotNone(match, title)
                return [float(value) for value in match.group(1).split()]

            section = doc.ArcExtrude.Shape.getElement("Face2")
            pressure_face = doc.ArcExtrude.Shape.getElement("Face4")
            normal = section.normalAt(*section.Surface.parameter(section.CenterOfMass))
            # For this fixture, the loaded end is in the selected negative-normal
            # half. Its cut resultant must oppose the applied pressure resultant.
            self.assertLess(normal.dot(pressure_face.CenterOfMass-section.CenterOfMass), 0)
            pressure = doc.Pressure.Pressure.getValueAs("MPa").Value
            load = pressure_face.normalAt(0, 0) * (-pressure * pressure_face.Area)
            expected_force = -load
            expected_moment = -pressure_face.CenterOfMass.cross(load)
            expected_cg_moment = expected_moment - section.CenterOfMass.cross(expected_force)
            force_moment = values("total surface force")
            support_force = values("total force")
            cg_moment = values("moment about the center of gravity")
            center_normal = values("center of gravity and mean normal")
            area = values("area, normal force")[0]
            report = {
                "runtime": App.Version(), "gui_up": App.GuiUp,
                "loaded_modules": module_paths,
                "cold_reopened": bool(reopen),
                "stock_setup_unmodified": not bool(section_size),
                "shipped_mesh": not bool(section_size),
                "section_size_mm": float(section_size or "1.25"),
                "volume_elements": doc.Mesh.FemMesh.VolumeCount,
                "solver_test_mode": False,
                "expected_force_N": list(expected_force),
                "expected_origin_moment_Nmm": list(expected_moment),
                "expected_centroid_moment_Nmm": list(expected_cg_moment),
                "reported_centroid_moment_Nmm": cg_moment,
                "reported_force_moment": force_moment,
                "reported_support_force_N": support_force,
                "cad_area_mm2": section.Area, "reported_area_mm2": area,
                "cad_normal": list(normal), "reported_center_normal": center_normal,
                "relative_force_residual": (App.Vector(*force_moment[:3])-expected_force).Length
                                           / expected_force.Length,
                "relative_origin_moment_residual": (App.Vector(*force_moment[3:])-expected_moment).Length
                                                  / expected_moment.Length,
                "relative_centroid_moment_residual": (App.Vector(*cg_moment)-expected_cg_moment).Length
                                                    / expected_cg_moment.Length,
                "example_relative_tolerance": 0.01,
                "raw_solver_dat": data,
                "building_design_accepted": False,
            }
            (root / "report.json").write_text(json.dumps(report, indent=2))
            doc.saveAs(str(root / "stock.FCStd"))
            self.assertAlmostEqual(area, section.Area, delta=section.Area*1e-6)
            self.assertLess((App.Vector(*support_force)-expected_force).Length
                            / expected_force.Length, 1e-6)
            for actual, expected in zip(center_normal[3:], normal):
                self.assertAlmostEqual(actual, expected, delta=1e-6)
            for key in ("relative_force_residual", "relative_origin_moment_residual",
                        "relative_centroid_moment_residual"):
                self.assertLess(report[key], 0.01, key)
        finally:
            prefs.SetBool("OverwriteSolverWorkingDirectory", overwrite)
            App.closeDocument(doc.Name)
