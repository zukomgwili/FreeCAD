# SPDX-License-Identifier: LGPL-2.1-or-later
"""Exercise stock CAD/Gmsh/writer/runner/native accounting/import/cold restore."""

import json
import os
from pathlib import Path
import tempfile
import unittest

import FreeCAD as App
import ObjectsFem
import Part
from BOPTools.SplitAPI import booleanFragments
from femmesh import gmshtools
from femtools.ccxtools import FemToolsCcx
from femtools import force_accounting


class ProductionAccountingWitness(unittest.TestCase):
    def test_native_contact_cut_pipeline(self):
        output = Path(
            tempfile.mkdtemp(
                prefix="native-accounting-",
                dir=os.environ.get("FREECAD_9ZT_OUTPUT", tempfile.gettempdir()),
            )
        )
        doc = App.newDocument("NativeAccountingPipeline")
        try:
            geometry = doc.addObject("Part::Feature", "Geometry")
            base = Part.makeBox(10, 10, 10)
            lower = Part.makeBox(10, 10, 10, App.Vector(0, 0, 10.01))
            upper = Part.makeBox(10, 10, 10, App.Vector(0, 0, 20.01))
            geometry.Shape = Part.makeCompound(
                [base, booleanFragments([lower, upper], "CompSolid")]
            )
            doc.recompute()
            analysis = ObjectsFem.makeAnalysis(doc)
            solver = ObjectsFem.makeSolverCalculiXCcxTools(doc)
            solver.NativeForceAccounting = True
            candidate = os.environ.get("FREECAD_9ZT_PRODUCTION_CCX")
            if candidate:
                solver.NativeAccountingSolver = candidate
            analysis.addObject(solver)
            material = ObjectsFem.makeMaterialSolid(doc)
            material.Material = {
                "Name": "Steel",
                "YoungsModulus": "200000 MPa",
                "PoissonRatio": "0.3",
                "Density": "7900 kg/m^3",
            }
            analysis.addObject(material)
            rigid = ObjectsFem.makeConstraintRigidBody(doc, "Support")
            base_id = next(
                index
                for index, solid in enumerate(geometry.Shape.Solids, 1)
                if abs(solid.CenterOfMass.z - 5) < 1e-7
            )
            lower_id = next(
                index
                for index, solid in enumerate(geometry.Shape.Solids, 1)
                if abs(solid.CenterOfMass.z - 15.01) < 1e-7
            )
            rigid.References = [(geometry, [f"Solid{base_id}"])]
            rigid.ReferenceNode = App.Vector(-5, -5, -5)
            for kind in ("Translational", "Rotational"):
                for axis in "XYZ":
                    setattr(rigid, kind + "Mode" + axis, "Constraint")
            analysis.addObject(rigid)

            def face_at(z, normal):
                return next(
                    f"Face{index}"
                    for index, face in enumerate(geometry.Shape.Faces, 1)
                    if abs(face.CenterOfMass.z - z) < 1e-7
                    and face.normalAt(0, 0).z * normal > 0.99
                )

            contact = ObjectsFem.makeConstraintContact(doc)
            contact.References = [
                (geometry, [face_at(10.01, -1)]),
                (geometry, [face_at(10, 1)]),
            ]
            contact.Slope = "1000000 MPa/mm"
            # Close the deliberately separate CAD/mesh contact sides initially.
            # The lateral guide removes free rigid modes, not vertical load.
            contact.Adjust = "0.02 mm"
            analysis.addObject(contact)
            guide = ObjectsFem.makeConstraintDisplacement(doc, "LateralGuide")
            guide.References = [(geometry, [face_at(30.01, 1)])]
            guide.xFree = False
            guide.yFree = False
            guide.zFree = True
            analysis.addObject(guide)
            pressure = ObjectsFem.makeConstraintPressure(doc)
            pressure.References = [(geometry, [face_at(30.01, 1)])]
            pressure.Pressure = "1 MPa"
            analysis.addObject(pressure)
            gravity = ObjectsFem.makeConstraintSelfWeight(doc)
            analysis.addObject(gravity)
            section = ObjectsFem.makeConstraintSectionPrint(doc)
            section.References = [(geometry, [face_at(20.01, 1)])]
            section.NativeEquilibriumCut = True
            section.AccountingBody = [(geometry, [f"Solid{lower_id}"])]
            analysis.addObject(section)
            mesh = ObjectsFem.makeMeshGmsh(doc, "Mesh")
            mesh.Shape = geometry
            mesh.ElementOrder = "2nd"
            mesh.SecondOrderLinear = False
            mesh.CharacteristicLengthMax = 4
            mesh.CharacteristicLengthMin = 2
            mesh.WorkingDirectory = str(output)
            analysis.addObject(mesh)
            doc.recompute()
            mesher = gmshtools.GmshTools(mesh)
            mesher.create_mesh()
            self.assertEqual(mesher.process.exitCode(), 0)
            fea = FemToolsCcx(analysis=analysis, solver=solver)
            fea.update_objects()
            fea.setup_working_dir(str(output))
            fea.write_inp_file()
            code = fea.ccx_run()
            (output / "solver.stdout").write_text(fea.ccx_stdout)
            (output / "solver.stderr").write_text(fea.ccx_stderr)
            self.assertEqual(code, 0)
            result = next(
                obj
                for obj in analysis.Group
                if isinstance(
                    getattr(obj, "Proxy", None), force_accounting.AccountingResult
                )
            )
            self.assertTrue(result.Status.startswith("Current"))
            data = json.loads(result.AccountingData)
            weight = (
                1000
                * 1e-9
                * 7900
                * gravity.GravityAcceleration.getValueAs("m/s^2").Value
            )
            for kind, name, force in (
                ("SUPPORT", rigid.Name, 100 + 3 * weight),
                ("CUT", section.Name, -100 - weight),
            ):
                values = data["wrenches"][kind][name]
                wanted_force = App.Vector(0, 0, force)
                wanted_moment = App.Vector(5, 5, 0).cross(wanted_force)
                self.assertLessEqual(
                    (App.Vector(*values[:3]) - wanted_force).Length, abs(force) * 0.01
                )
                self.assertLessEqual(
                    (App.Vector(*values[3:]) - wanted_moment).Length,
                    wanted_moment.Length * 0.01,
                )
            self.assertGreater(abs(data["wrenches"]["CONTACT"][section.Name][2]), 100)
            (output / "pipeline-receipt.json").write_text(json.dumps(data, indent=2))
            for path in (
                Path(fea.inp_file_name),
                Path(fea.inp_file_name).with_suffix(".accounting"),
            ):
                original = path.read_bytes()
                try:
                    path.write_bytes(original + b"\n")
                    with self.assertRaisesRegex(ValueError, "inputs changed"):
                        force_accounting.run_context(fea, fea.ccx_binary)
                finally:
                    path.write_bytes(original)
            old_material = dict(material.Material)
            changed = dict(old_material, Density="7901 kg/m^3")
            material.Material = changed
            self.assertTrue(result.Status.startswith("Stale"))
            with self.assertRaisesRegex(ValueError, "inputs changed"):
                force_accounting.run_context(fea, fea.ccx_binary)
            material.Material = old_material
            self.assertTrue(result.Status.startswith("Stale"))
            saved = output / "native-accounting.FCStd"
            doc.recompute()
            doc.saveAs(str(saved))
            name = result.Name
            analysis_name, solver_name = analysis.Name, solver.Name
            App.closeDocument(doc.Name)
            doc = App.openDocument(str(saved))
            result = doc.getObject(name)
            self.assertTrue(result.Status.startswith("Stale"))
            self.assertEqual(
                json.loads(result.AccountingData)["output_sha256"],
                data["output_sha256"],
            )
            # Historical reports must not become current on restore or prevent
            # an ordinary second write/solve/import of the same native model.
            analysis = doc.getObject(analysis_name)
            solver = doc.getObject(solver_name)
            fea = FemToolsCcx(analysis=analysis, solver=solver)
            fea.update_objects()
            fea.setup_working_dir(str(output))
            fea.write_inp_file()
            self.assertEqual(fea.ccx_run(), 0)
            reports = [
                obj
                for obj in analysis.Group
                if isinstance(
                    getattr(obj, "Proxy", None), force_accounting.AccountingResult
                )
            ]
            self.assertEqual(len(reports), 2)
            self.assertEqual(
                sum(obj.Status.startswith("Current") for obj in reports), 1
            )
            if App.GuiUp:
                import FreeCADGui as Gui

                current = next(
                    obj for obj in reports if obj.Status.startswith("Current")
                )
                Gui.activateWorkbench("FemWorkbench")
                Gui.Selection.clearSelection()
                Gui.Selection.addSelection(current)
                Gui.activeDocument().activeView().viewAxonometric()
                Gui.activeDocument().activeView().fitAll()
                Gui.updateGui()
                Gui.getMainWindow().grab().save(
                    str(output / "native-accounting-ui.png")
                )
            doc.recompute()
            doc.saveAs(str(saved))
            print("NATIVE_ACCOUNTING_EVIDENCE=" + str(output), flush=True)
        finally:
            App.closeDocument(doc.Name)
