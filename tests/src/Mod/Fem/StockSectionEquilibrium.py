# SPDX-License-Identifier: LGPL-2.1-or-later

"""Opt-in unresolved FreeCAD-9bp acceptance check, not a result-recovery tool.

Run FreeCAD[Cmd] -P tests/src/Mod/Fem -t StockSectionEquilibrium with
FREECAD_9BP_OUTPUT set to a new disposable directory. Uses the unchanged shipped
example mesh and real stock solver. Reads only solver-reported totals; never
edits an input deck or substitutes recovered forces. Currently expected to FAIL
equilibrium even after the one-sided export correction; keep the bead open.
"""

import json
import os
from pathlib import Path
import re
import unittest

import FreeCAD as App
from femexamples.constraint_section_print import setup
from femtools.ccxtools import FemToolsCcx


class StockSectionEquilibrium(unittest.TestCase):
    def test_unchanged_stock_example_equilibrium(self):
        root = Path(os.environ["FREECAD_9BP_OUTPUT"])
        root.mkdir(parents=True, exist_ok=False)
        solver_dir = root / "solver"
        solver_dir.mkdir()
        doc = setup(test_mode=True)
        prefs = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/General")
        overwrite = prefs.GetBool("OverwriteSolverWorkingDirectory", True)
        try:
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
            force_moment = values("total surface force")
            center_normal = values("center of gravity and mean normal")
            area = values("area, normal force")[0]
            report = {
                "runtime": App.Version(), "gui_up": App.GuiUp,
                "stock_setup_unmodified": True, "shipped_mesh": True,
                "solver_test_mode": False,
                "expected_force_N": list(expected_force),
                "expected_origin_moment_Nmm": list(expected_moment),
                "reported_force_moment": force_moment,
                "cad_area_mm2": section.Area, "reported_area_mm2": area,
                "cad_normal": list(normal), "reported_center_normal": center_normal,
                "relative_force_residual": (App.Vector(*force_moment[:3])-expected_force).Length
                                           / expected_force.Length,
                "raw_solver_dat": data,
                "building_design_accepted": False,
            }
            (root / "report.json").write_text(json.dumps(report, indent=2))
            doc.saveAs(str(root / "stock.FCStd"))
            self.assertAlmostEqual(area, section.Area, delta=section.Area*1e-6)
            for actual, expected in zip(center_normal[3:], normal):
                self.assertAlmostEqual(actual, expected, delta=1e-6)
            for actual, expected in zip(force_moment[:3], expected_force):
                self.assertAlmostEqual(actual, expected, delta=expected_force.Length*1e-6)
            for actual, expected in zip(force_moment[3:], expected_moment):
                self.assertAlmostEqual(actual, expected, delta=expected_moment.Length*1e-6)
        finally:
            prefs.SetBool("OverwriteSolverWorkingDirectory", overwrite)
            App.closeDocument(doc.Name)
