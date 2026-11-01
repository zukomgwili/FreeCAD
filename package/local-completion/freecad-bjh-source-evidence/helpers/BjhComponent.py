"""Independent prescribed-root V1 component control; no force recovery."""

import json
import math
import os
from pathlib import Path
import unittest

import FreeCAD as App
from femtest.app.beam_network_fixtures import make_grounded_tree
from femtools.ccxtools import FemToolsCcx
from feminout.importCcxFrdResults import read_frd_result


class TestNativeComponentControl(unittest.TestCase):
    def test_prescribed_root_reproduces_native_component_without_fitting(self):
        source = Path(os.environ["BJH_COMPONENT_SOURCE"])
        original = json.loads((source / "section-data.json").read_text())
        directory = Path(os.environ["BJH_CASE_ROOT"])
        directory.mkdir()
        doc = App.newDocument("IndependentNativeBeamComponent")
        try:
            model = make_grounded_tree(doc)
            doc.removeObject(model.spring.Name)
            model.guide.xFree = False
            model.guide.xDisplacement = "0.0005 mm"
            if os.environ.get("BJH_TEST_SOLVER"):
                model.solver.NativeAccountingSolver = os.environ["BJH_TEST_SOLVER"]
            doc.recompute()
            fea = FemToolsCcx(analysis=model.analysis, solver=model.solver)
            fea.update_objects()
            fea.setup_working_dir(str(directory))
            self.assertFalse(fea.check_prerequisites())
            self.assertFalse(fea.write_inp_file())
            deck = Path(fea.inp_file_name).read_bytes()
            self.assertNotIn(b"TYPE=SPRING", deck.upper())
            code = fea.ccx_run()
            (directory / "ccx-stdout.txt").write_text(fea.ccx_stdout)
            (directory / "ccx-stderr.txt").write_text(fea.ccx_stderr)
            self.assertEqual(code, 0, fea.ccx_stdout + fea.ccx_stderr)
            self.assertEqual(Path(fea.inp_file_name).read_bytes(), deck)
            fea.load_results()
            result = next(
                o
                for o in model.analysis.Group
                if getattr(getattr(o, "Proxy", None), "Type", "") == "Fem::BeamSectionForceResult"
            )
            control = result.Proxy.getSectionForces(result)
            self.assertEqual(control["schema"], "CCX_BEAM_SECTION_V1")
            (directory / "observed-control.json").write_text(json.dumps(control, indent=2))
            self.assertEqual(
                original["provenance"]["binary_sha256"], control["provenance"]["binary_sha256"]
            )

            def rows(data):
                return {
                    (r["element"], r["node"], r["end"]): r for r in data["frames"][0]["samples"]
                }

            first, second = rows(original), rows(control)
            self.assertEqual(set(first), set(second))
            maximum = {
                "force_N": 0.0,
                "moment_Nmm": 0.0,
                "position_mm": 0.0,
                "basis": 0.0,
                "displacement_mm": 0.0,
            }
            for key in first:
                a, b = first[key], second[key]
                for field, budget, label in (
                    ("force_global", 1e-6, "force_N"),
                    ("moment_global", 1e-4, "moment_Nmm"),
                    ("position", 1e-8, "position_mm"),
                ):
                    for x, y in zip(a[field], b[field]):
                        maximum[label] = max(maximum[label], abs(x - y))
                        self.assertLessEqual(abs(x - y), budget)
                for axis in ("e1", "e2", "normal"):
                    for x, y in zip(a["basis"][axis], b["basis"][axis]):
                        maximum["basis"] = max(maximum["basis"], abs(x - y))
                        self.assertLessEqual(abs(x - y), 1e-8)

            def displacement(data):
                parsed = read_frd_result(data["provenance"]["frd"]["path"])
                return parsed["Results"][0]["disp"]

            first_u, second_u = displacement(original), displacement(control)
            self.assertEqual(set(first_u), set(second_u))

            def rounding(v):
                return (
                    0.5 * 10 ** (math.floor(math.log10(abs(v))) - 5) + abs(v) * 2**-24 if v else 0.0
                )

            for node in first_u:
                for a, b in zip(first_u[node], second_u[node]):
                    delta = abs(a - b)
                    maximum["displacement_mm"] = max(maximum["displacement_mm"], delta)
                    self.assertLessEqual(delta, 1e-7 + rounding(a) + rounding(b))
            (directory / "component-equivalence.json").write_text(
                json.dumps(
                    {
                        "root_ux_mm": 0.0005,
                        "root_value_source": "Independent equilibrium 5N / 10000N/mm, never fitted",
                        "maximum_differences": maximum,
                        "control": "Separate ordinary native V1 component",
                        "frd_hashes": [
                            original["provenance"]["frd"]["sha256"],
                            control["provenance"]["frd"]["sha256"],
                        ],
                    },
                    indent=2,
                )
            )
            doc.saveAs(str(directory / "component-control.FCStd"))
        finally:
            App.closeDocument(doc.Name)
