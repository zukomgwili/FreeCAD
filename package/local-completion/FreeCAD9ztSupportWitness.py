# SPDX-License-Identifier: LGPL-2.1-or-later

"""Characterize the unresolved FreeCAD-9zt output contract, not a passing fix.

Run with FreeCADCmd -P package/local-completion -t FreeCAD9ztSupportWitness.
Only a small stock native box is generated; no original project is opened.
FREECAD_9ZT_OUTPUT optionally selects an existing evidence parent directory.
FREECAD_9ZT_REQUIRE_PHYSICAL_RF=1 asserts the physical support duty rather
than merely recording the stock RF channel. This is expected to fail on 2.23.
"""

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import FreeCAD as App
import ObjectsFem
from femmesh import gmshtools
from femtools.ccxtools import FemToolsCcx


class SupportGravityWitness(unittest.TestCase):
    def test_native_gravity_rigid_support_output_contract(self):
        self._run_witness("Solid1", "1st", App.Vector(-5, -5, -5))

    @unittest.skipUnless(
        os.environ.get("FREECAD_9ZT_CCX")
        or os.environ.get("FREECAD_9ZT_PRODUCTION_CCX"),
        "accounting solver not selected",
    )
    def test_native_diagnostic_projection_variants(self):
        for selection in ("Solid1", "Face1"):
            for order in ("1st", "2nd"):
                for reference in (App.Vector(0, 0, 0), App.Vector(13, -7, 19)):
                    with self.subTest(
                        selection=selection, order=order, reference=reference
                    ):
                        self._run_witness(selection, order, reference)

    @unittest.skipUnless(
        os.environ.get("FREECAD_9ZT_CCX")
        or os.environ.get("FREECAD_9ZT_PRODUCTION_CCX"),
        "accounting solver not selected",
    )
    def test_native_diagnostic_rejects_unqualified_nlgeom(self):
        self._run_witness("Face1", "1st", App.Vector(0, 0, 0), nonlinear=True)

    def _run_witness(self, selection, order, reference, nonlinear=False):
        output = Path(
            tempfile.mkdtemp(
                prefix="support-gravity-",
                dir=os.environ.get("FREECAD_9ZT_OUTPUT", tempfile.gettempdir()),
            )
        )
        doc = App.newDocument("SupportGravityWitness")
        try:
            shape = doc.addObject("Part::Box", "Box")
            analysis = ObjectsFem.makeAnalysis(doc)
            solver = ObjectsFem.makeSolverCalculiXCcxTools(doc)
            solver.GeometricalNonlinearity = nonlinear
            production = os.environ.get("FREECAD_9ZT_PRODUCTION_CCX")
            if production:
                solver.NativeForceAccounting = True
                solver.NativeAccountingSolver = production
            analysis.addObject(solver)
            material = ObjectsFem.makeMaterialSolid(doc)
            material.Material = {
                "Name": "Gravity witness",
                "YoungsModulus": "200000 MPa",
                "PoissonRatio": "0.3",
                "Density": "7900 kg/m^3",
            }
            analysis.addObject(material)
            body = ObjectsFem.makeConstraintRigidBody(doc, "Support")
            body.References = [(shape, [selection])]
            body.ReferenceNode = reference
            for axis in "XYZ":
                setattr(body, "TranslationalMode" + axis, "Constraint")
                setattr(body, "RotationalMode" + axis, "Constraint")
            analysis.addObject(body)
            gravity = ObjectsFem.makeConstraintSelfWeight(doc)
            analysis.addObject(gravity)
            mesh = ObjectsFem.makeMeshGmsh(doc, "Mesh")
            mesh.Shape = shape
            mesh.ElementOrder = order
            mesh.CharacteristicLengthMax = 4
            mesh.CharacteristicLengthMin = 2
            mesh.WorkingDirectory = str(output)
            analysis.addObject(mesh)
            doc.recompute()
            tool = gmshtools.GmshTools(mesh)
            tool.create_mesh()
            self.assertEqual(tool.process.exitCode(), 0)
            fea = FemToolsCcx(analysis=analysis, solver=solver)
            fea.update_objects()
            fea.setup_working_dir(str(output))
            if nonlinear and production:
                with self.assertRaisesRegex(ValueError, "small-displacement"):
                    fea.write_inp_file()
                return
            fea.write_inp_file()
            candidate = os.environ.get("FREECAD_9ZT_CCX")
            if candidate:
                # Explicit subprocess selection leaves both user preferences
                # and the installed/default solver unchanged.
                environment = dict(os.environ)
                environment["CCX_9ZT_DIAGNOSTIC"] = str(
                    output / "native-accounting.txt"
                )
                completed = subprocess.run(
                    [candidate, "-i", "Mesh"],
                    cwd=output,
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                )
                code = completed.returncode
                stdout, stderr = completed.stdout, completed.stderr
            else:
                code = fea.ccx_run()
                stdout, stderr = fea.ccx_stdout, fea.ccx_stderr
            (output / "ccx.stdout").write_text(stdout)
            (output / "ccx.stderr").write_text(stderr)
            dat = (
                (output / "Mesh.dat").read_text()
                if (output / "Mesh.dat").exists()
                else ""
            )
            print("NATIVE_OUTPUT=", str(output), "EXIT=", code, flush=True)
            print("NATIVE_DAT=", dat, flush=True)
            doc.saveAs(str(output / "native.FCStd"))
            if nonlinear:
                self.assertEqual(code, 201)
                self.assertIn("9zt experimental probe: unsupported analysis", stderr)
                self.assertFalse((output / "native-accounting.txt").exists())
                return
            # Use the actual native gravity (default 9.80665 m/s2), not an
            # assumed9.81. This is analytic free-body statics, not a nodal load
            # reconstruction or correction of the solver's printed values.
            mass_kg = shape.Shape.Volume * 1e-9 * 7900
            acceleration = gravity.GravityAcceleration.getValueAs("m/s^2").Value
            required = gravity.GravityDirection * (-mass_kg * acceleration)
            moment = shape.Shape.CenterOfMass.cross(required)
            printed = {
                name: [float(value) for value in row.split()]
                for name, row in re.findall(
                    r"total force[^\n]*for set (\S+)[^\n]*\n\s*\n([^\n]+)", dat
                )
            }
            self.assertIn("SUPPORT_REFNODE", printed)
            self.assertIn("SUPPORT_ROTNODE", printed)
            report = {
                "version": list(App.Version()),
                "exit_code": code,
                "required_support_force_N": list(required),
                "required_global_origin_moment_Nmm": list(moment),
                "native_gravity_m_s2": acceleration,
                "raw_ref_rot_RF": printed["SUPPORT_REFNODE"]
                + printed["SUPPORT_ROTNODE"],
                "cad_volume_mm3": shape.Shape.Volume,
                "native_mesh_volume_mm3": mesh.FemMesh.Volume.Value,
                "directory": str(output),
                "stock_deck_unedited": True,
                "selection": selection,
                "element_order": order,
                "reference_node_mm": list(reference),
                "experimental_solver": candidate,
            }
            if candidate:
                # Native probe rows already contain assembled/projected forces;
                # this observer performs no numerical load reconstruction.
                rows = (output / "native-accounting.txt").read_text().splitlines()
                self.assertEqual(
                    rows[0], "CCX9ZT_DIAGNOSTIC_V0 node dof internal external residual"
                )
                values = {
                    (int(row[0]), int(row[1])): float(row[4])
                    for line in rows[1:]
                    if (row := line.split())
                }
                deck = (output / "Mesh.inp").read_text()
                identity = re.search(r"REF NODE=(\d+), ROT NODE=(\d+)", deck)
                self.assertIsNotNone(identity)
                ref_node, rot_node = map(int, identity.groups())
                force = App.Vector(*(values[(ref_node, axis)] for axis in (1, 2, 3)))
                couple = App.Vector(*(values[(rot_node, axis)] for axis in (1, 2, 3)))
                origin_moment = couple + reference.cross(force)
                report["experimental_support_force_N"] = list(force)
                report["experimental_origin_moment_Nmm"] = list(origin_moment)
                report["experimental_force_relative_error"] = (
                    force - required
                ).Length / required.Length
                report["experimental_moment_relative_error"] = (
                    origin_moment - moment
                ).Length / moment.Length
            (output / "characterization.json").write_text(json.dumps(report, indent=2))
            self.assertEqual(code, 0)
            if production:
                from femtools import force_accounting

                results = [
                    obj
                    for obj in analysis.Group
                    if isinstance(
                        getattr(obj, "Proxy", None), force_accounting.AccountingResult
                    )
                ]
                self.assertEqual(len(results), 1)
                self.assertTrue(results[0].Status.startswith("Current"))
                physical = json.loads(results[0].AccountingData)["wrenches"]["SUPPORT"][
                    "Support"
                ]
                self.assertLessEqual(
                    (App.Vector(*physical[:3]) - required).Length,
                    required.Length * 0.01,
                )
                self.assertLessEqual(
                    (App.Vector(*physical[3:]) - moment).Length, moment.Length * 0.01
                )
                doc.saveAs(str(output / "native.FCStd"))
            if candidate:
                self.assertLessEqual(report["experimental_force_relative_error"], 0.01)
                self.assertLessEqual(report["experimental_moment_relative_error"], 0.01)
            if os.environ.get("FREECAD_9ZT_REQUIRE_PHYSICAL_RF") == "1":
                force = App.Vector(*printed["SUPPORT_REFNODE"])
                reference_couple = App.Vector(*printed["SUPPORT_ROTNODE"])
                origin_moment = reference_couple + body.ReferenceNode.cross(force)
                # A deliberately loose 1% physical-duty check, not an exactness
                # requirement or a correction of the native output.
                self.assertLessEqual((force - required).Length, required.Length * 0.01)
                self.assertLessEqual(
                    (origin_moment - moment).Length, moment.Length * 0.01
                )
        finally:
            App.closeDocument(doc.Name)
