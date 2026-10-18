# SPDX-License-Identifier: LGPL-2.1-or-later

"""Characterize the unresolved FreeCAD-9zt output contract, not a passing fix.

Run with FreeCADCmd -P package/local-completion -t FreeCAD9ztSupportWitness.
Only a small stock native box is generated; no original project is opened.
FREECAD_9ZT_OUTPUT optionally selects an existing evidence parent directory.
"""

import json
import os
from pathlib import Path
import re
import tempfile
import unittest

import FreeCAD as App
import ObjectsFem
from femmesh import gmshtools
from femtools.ccxtools import FemToolsCcx


class SupportGravityWitness(unittest.TestCase):
    def test_native_gravity_rigid_support_output_contract(self):
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
            body.References = [(shape, ["Solid1"])]
            body.ReferenceNode = App.Vector(-5, -5, -5)
            for axis in "XYZ":
                setattr(body, "TranslationalMode" + axis, "Constraint")
                setattr(body, "RotationalMode" + axis, "Constraint")
            analysis.addObject(body)
            gravity = ObjectsFem.makeConstraintSelfWeight(doc)
            analysis.addObject(gravity)
            mesh = ObjectsFem.makeMeshGmsh(doc, "Mesh")
            mesh.Shape = shape
            mesh.ElementOrder = "1st"
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
            fea.write_inp_file()
            code = fea.ccx_run()
            (output / "ccx.stdout").write_text(fea.ccx_stdout)
            (output / "ccx.stderr").write_text(fea.ccx_stderr)
            dat = (output / "Mesh.dat").read_text() if (output / "Mesh.dat").exists() else ""
            print("NATIVE_OUTPUT=", str(output), "EXIT=", code, flush=True)
            print("NATIVE_DAT=", dat, flush=True)
            doc.saveAs(str(output / "native.FCStd"))
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
                "raw_ref_rot_RF": printed["SUPPORT_REFNODE"] + printed["SUPPORT_ROTNODE"],
                "cad_volume_mm3": shape.Shape.Volume,
                "native_mesh_volume_mm3": mesh.FemMesh.Volume.Value,
                "directory": str(output),
                "stock_deck_unedited": True,
            }
            (output / "characterization.json").write_text(json.dumps(report, indent=2))
        finally:
            App.closeDocument(doc.Name)
