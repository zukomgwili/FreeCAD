"""Separate legacy compatibility fixture, not a receiving-face workaround."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

import FreeCAD as App
import ObjectsFem
import Part
from femmesh import gmshtools
from femtools import force_accounting
from femtools.ccxtools import FemToolsCcx
from YwuMovingPortWitness import plain, sha, write_json


class LegacyFixedPorts(unittest.TestCase):
    def test_legacy_fully_fixed_point_rbes_preserve_support_behavior(self):
        output = Path(os.environ["YWU_OUTPUT"]) / "witness"
        output.mkdir()
        for name in ("mesh", "native"):
            (output / name).mkdir()
        schema = force_accounting.SCHEMA
        old = schema == "CCX_FORCE_ACCOUNTING_V2"
        self.assertIn(schema, ("CCX_FORCE_ACCOUNTING_V2", "CCX_FORCE_ACCOUNTING_V3"))
        receipt = {"passed": False, "schema": schema, "runtime": App.Version(),
                   "case": "Separate regression of existing fixed-point RBE support selection",
                   "not_a_substitute_for_finite_moving_receiving_faces": True,
                   "Oomakhi_opened_or_solved": False, "no_deck_patches": True,
                   "three_noncollinear_fully_fixed_physical_points": True,
                   "analytical_support_wrench": [-12, 0, 0, 0, -36, 24]}
        doc = App.newDocument("YwuLegacyFixedPorts")
        try:
            if old:
                resources = Path("/Applications/FreeCAD-27.1.0.app/Contents/Resources")
                self.assertEqual(Path(App.getHomePath()).resolve(), resources)
                self.assertEqual(App.Version()[-1], "b6b9e216c4ee2ca1bbc73db70076a6c99b2b1ab5")
                self.assertEqual(App.Version()[3], "49261 +218 (Git)")
                pins = {}
                for name, module in list(sys.modules.items()):
                    path = getattr(module, "__file__", None)
                    if not name.startswith("fem") or not path:
                        continue
                    actual = Path(path).resolve()
                    self.assertTrue(actual.is_relative_to(resources / "Mod/Fem"), str(actual))
                    relative = actual.relative_to(resources / "Mod/Fem")
                    baseline = subprocess.run([
                        "git", "show", "b6b9e216c4ee2ca1bbc73db70076a6c99b2b1ab5:src/Mod/Fem/" + str(relative)],
                        cwd="/Users/zukomgwili/src/FreeCAD", check=True, capture_output=True).stdout
                    self.assertEqual(sha(actual), hashlib.sha256(baseline).hexdigest(), name)
                    pins[name] = {"path": str(actual), "sha256": sha(actual)}
                receipt["installed_fem_modules_match_historical_commit"] = pins
            analysis = ObjectsFem.makeAnalysis(doc)
            solver = ObjectsFem.makeSolverCalculiXCcxTools(doc)
            solver.NativeForceAccounting = True
            solver.SplitInputWriter = False
            analysis.addObject(solver)
            if not old:
                self.assertEqual(list(solver.NativeAccountingSupports), [])
            geometry = doc.addObject("Part::Feature", "Beam")
            geometry.Shape = Part.makeBox(10, 2, 2, App.Vector(0, 1, 2))
            material = ObjectsFem.makeMaterialSolid(doc)
            material.Material = {"Name": "Legacy synthetic material", "YoungsModulus": "20000 MPa",
                                 "PoissonRatio": "0.3", "Density": "1 kg/m^3"}
            analysis.addObject(material)
            supports = []
            for index, point in enumerate((App.Vector(0, 1, 2), App.Vector(0, 3, 2), App.Vector(0, 1, 4)), 1):
                vertices = [f"Vertex{number}" for number, vertex in enumerate(geometry.Shape.Vertexes, 1)
                            if (vertex.Point - point).Length < 1e-9]
                self.assertEqual(len(vertices), 1)
                support = ObjectsFem.makeConstraintRigidBody(doc, "FixedPoint" + str(index))
                support.References = [(geometry, vertices)]
                support.ReferenceNode = point
                for kind in ("Translational", "Rotational"):
                    for axis in "XYZ":
                        setattr(support, kind + "Mode" + axis, "Constraint")
                analysis.addObject(support)
                supports.append(support)
            faces = [f"Face{number}" for number, face in enumerate(geometry.Shape.Faces, 1)
                     if abs(face.CenterOfMass.x - 10) < 1e-9]
            self.assertEqual(len(faces), 1)
            direction = doc.addObject("Part::Feature", "LoadDirection")
            direction.Shape = Part.makeLine(App.Vector(), App.Vector(1, 0, 0))
            load = ObjectsFem.makeConstraintForce(doc)
            load.References = [(geometry, faces)]
            load.Force = "12 N"
            load.Direction = (direction, ["Edge1"])
            analysis.addObject(load)
            mesh = ObjectsFem.makeMeshGmsh(doc)
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
            doc.saveAs(str(output / "three-fixed-points.FCStd"))
            fea = FemToolsCcx(analysis=analysis, solver=solver)
            fea.update_objects()
            fea.setup_working_dir(str(output / "native"))
            fea.write_inp_file()
            deck = Path(fea.inp_file_name)
            receipt["deck_sha256"] = sha(deck)
            code = fea.ccx_run()
            receipt.update(returncode=code, binary=str(fea.ccx_binary), binary_sha256=sha(fea.ccx_binary))
            (output / "native.stdout").write_text(fea.ccx_stdout)
            (output / "native.stderr").write_text(fea.ccx_stderr)
            if old:
                self.assertEqual(receipt["binary_sha256"], "31fc5615d1753ccbb7b53d5a47175ac1122f18d5cb13060cec272462bb0bd03d")
            if not old and os.environ.get("YWU_LEGACY_RED") == "1":
                self.assertEqual(code, 201)
                self.assertIn("declared port is not a finite native RBE receiving region", fea.ccx_stdout)
                self.assertFalse(any(getattr(getattr(obj, "Proxy", None), "Type", None)
                                     == "Fem::NativeForceAccountingResult" for obj in analysis.Group))
                receipt["new_V3_legacy_regression_reproduced"] = True
            else:
                self.assertEqual(code, 0)
                reports = [obj for obj in analysis.Group if getattr(getattr(obj, "Proxy", None), "Type", None)
                           == "Fem::NativeForceAccountingResult"]
                self.assertEqual(len(reports), 1)
                self.assertTrue(reports[0].Status.startswith("Current"))
                values = json.loads(reports[0].AccountingData)["wrenches"]["SUPPORT"]
                self.assertEqual(set(values), {obj.Name for obj in supports})
                aggregate = [sum(row[index] for row in values.values()) for index in range(6)]
                for offset in (0, 3):
                    expected = receipt["analytical_support_wrench"][offset:offset + 3]
                    self.assertLessEqual((App.Vector(*aggregate[offset:offset + 3]) - App.Vector(*expected)).Length
                                         / App.Vector(*expected).Length, 0.01)
                receipt["actual_aggregate_support_wrench"] = aggregate
                receipt["literal_accounting_data"] = json.loads(reports[0].AccountingData)
            receipt["passed"] = True
        finally:
            write_json(output / "legacy-receipt.json", receipt)
            if doc.Name in App.listDocuments():
                App.closeDocument(doc.Name)
