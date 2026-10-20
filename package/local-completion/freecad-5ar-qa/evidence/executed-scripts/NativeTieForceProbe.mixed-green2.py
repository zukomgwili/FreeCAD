# SPDX-License-Identifier: LGPL-2.1-or-later
"""One native analytical Tie/free-body capability probe, not a building solve.

Invoked only by run_native_tie_probe.py.  Uses existing public native objects,
the unmodified stock writer/runner and the bundled accounting solver.  The
current production refusal is intentionally a failing test, not a passed test
that expects the capability to be absent.
"""

import sys
sys.dont_write_bytecode = True

import ctypes
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import traceback
import unittest

import FreeCAD as App
import Fem
import ObjectsFem
import Part
from BOPTools.SplitAPI import booleanFragments
from femmesh import gmshtools
from femtools.ccxtools import FemToolsCcx
from femtools import force_accounting


REPOSITORY = Path("/Users/zukomgwili/src/FreeCAD")
BUILD = REPOSITORY / "build/release"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class NativeTieForceProbe(unittest.TestCase):
    def test_ordinary_tie_participating_body_produces_physical_cut(self):
        output = Path(os.environ["FIVEAR_RUN"])
        receipt = {
            "passed": False,
            "scope": "small analytical native Tie force capability only",
            "Oomakhi_opened_or_solved": False,
            "target_force_relative_limit": 0.01,
            "target_origin_moment_relative_limit": 0.01,
            "checkpoints": [],
        }
        doc = None

        def checkpoint(name, **values):
            receipt["checkpoints"].append({"name": name, **values})
            (output / "checkpoint.json").write_text(json.dumps(receipt, indent=2) + "\n")
            print("FIVEAR_CHECKPOINT=" + json.dumps({"name": name, **values}), flush=True)

        try:
            self.assertFalse(App.GuiUp)
            self.assertEqual(Path(App.getHomePath()).resolve(), BUILD.resolve())
            self.assertTrue(__import__("sys").dont_write_bytecode)
            header = (BUILD / "src/Build/Version.h").read_text()
            for macro, actual in (("FCRevision", App.Version()[3]),
                                  ("FCRepositoryHash", App.Version()[-1])):
                match = re.search(r'^#define\s+' + macro + r'\s+"([^\"]+)"', header, re.M)
                self.assertIsNotNone(match, macro)
                self.assertEqual(actual, match.group(1), macro)
            modules = {
                "ObjectsFem": "ObjectsFem.py",
                "femmesh.meshsetsgetter": "femmesh/meshsetsgetter.py",
                "femmesh.meshtools": "femmesh/meshtools.py",
                "femmesh.ownership_context": "femmesh/ownership_context.py",
                "femmesh.gmshtools": "femmesh/gmshtools.py",
                "femsolver.calculix.write_constraint_tie":
                    "femsolver/calculix/write_constraint_tie.py",
                "femtools.ccxtools": "femtools/ccxtools.py",
                "femtools.force_accounting": "femtools/force_accounting.py",
            }
            receipt["modules"] = {}
            for name, relative in modules.items():
                module = importlib.import_module(name)
                source = REPOSITORY / "src/Mod/Fem" / relative
                actual = Path(module.__file__).resolve()
                self.assertEqual(actual, (BUILD / "Mod/Fem" / relative).resolve(), name)
                self.assertEqual(digest(actual), digest(source), name)
                receipt["modules"][name] = {"path": str(actual), "sha256": digest(actual)}
            dyld = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
            dyld._NSGetExecutablePath.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
            dyld._NSGetExecutablePath.restype = ctypes.c_int
            size = ctypes.c_uint32(4096)
            buffer = ctypes.create_string_buffer(size.value)
            self.assertEqual(dyld._NSGetExecutablePath(buffer, ctypes.byref(size)), 0)
            executable = Path(os.fsdecode(buffer.value)).resolve()
            self.assertEqual(executable, (BUILD / "bin/FreeCADCmd").resolve())
            dyld._dyld_image_count.restype = ctypes.c_uint32
            dyld._dyld_get_image_name.argtypes = [ctypes.c_uint32]
            dyld._dyld_get_image_name.restype = ctypes.c_char_p
            images = [Path(os.fsdecode(dyld._dyld_get_image_name(index))).resolve()
                      for index in range(dyld._dyld_image_count())]
            expected_native = [BUILD / "Mod/Fem/Fem.so", BUILD / "Mod/Part/Part.so",
                               BUILD / "lib/libFreeCADApp.dylib"]
            for path in expected_native:
                self.assertTrue(path.resolve() in images, str(path))
            self.assertEqual(Path(Fem.__file__).resolve(), expected_native[0].resolve())
            self.assertEqual(Path(Part.__file__).resolve(), expected_native[1].resolve())
            # FreeCADCmd embeds App; it need not load the optional FreeCAD.so
            # extension. Bind App to its actual loaded library, executable and
            # compiled version above, not to an image this process never uses.
            receipt["app_module_file"] = getattr(App, "__file__", None)
            receipt["runtime"] = App.Version()
            receipt["executable"] = {"path": str(executable), "sha256": digest(executable)}
            receipt["native_images"] = [{"path": str(path), "sha256": digest(path)}
                                         for path in expected_native]
            checkpoint("native-identity-confirmed")

            doc = App.newDocument("AnalyticalOrdinaryTieForce")
            geometry = doc.addObject("Part::Feature", "ThreeBodies")
            base = Part.makeBox(10, 10, 10)
            rear = Part.makeBox(10, 10, 10, App.Vector(0, 0, 10))
            front = Part.makeBox(10, 10, 10, App.Vector(0, 0, 20))
            sidepad = Part.makeBox(10, 10, 10, App.Vector(10, 0, 10))
            geometry.Shape = Part.makeCompound(
                [base, booleanFragments([rear, front], "CompSolid"), sidepad]
            )
            doc.recompute()
            self.assertEqual(len(geometry.Shape.Solids), 4)

            def solid_at(z):
                matches = [index for index, solid in enumerate(geometry.Shape.Solids, 1)
                           if abs(solid.CenterOfMass.z - z) < 1e-7
                           and abs(solid.CenterOfMass.x - 5) < 1e-7]
                self.assertEqual(len(matches), 1)
                return f"Solid{matches[0]}"

            def face_at(z, normal):
                matches = [index for index, face in enumerate(geometry.Shape.Faces, 1)
                           if abs(face.CenterOfMass.z - z) < 1e-7
                           and abs(face.CenterOfMass.x - 5) < 1e-7
                           and face.normalAt(0, 0).z * normal > 0.99]
                self.assertEqual(len(matches), 1, (z, normal, matches))
                return f"Face{matches[0]}"

            base_solid, rear_solid = solid_at(5), solid_at(15)
            slave_face, master_face = face_at(10, -1), face_at(10, 1)
            cut_face, loaded_face = face_at(20, 1), face_at(30, 1)
            slave_shape = geometry.Shape.getElement(slave_face)
            master_shape = geometry.Shape.getElement(master_face)
            self.assertAlmostEqual(slave_shape.distToShape(master_shape)[0], 0, places=10)
            self.assertAlmostEqual(slave_shape.Area, 100, places=10)
            self.assertAlmostEqual(master_shape.Area, 100, places=10)

            analysis = ObjectsFem.makeAnalysis(doc)
            solver = ObjectsFem.makeSolverCalculiXCcxTools(doc)
            solver.NativeForceAccounting = True
            # Empty selects the shipped qualified solver by the existing interface.
            solver.NativeAccountingSolver = ""
            analysis.addObject(solver)
            material = ObjectsFem.makeMaterialSolid(doc)
            material.Material = {"Name": "Steel", "YoungsModulus": "200000 MPa",
                                 "PoissonRatio": "0.3", "Density": "7900 kg/m^3"}
            analysis.addObject(material)
            support = ObjectsFem.makeConstraintRigidBody(doc, "BaseSupport")
            support.References = [(geometry, [base_solid])]
            support.ReferenceNode = App.Vector(-5, -5, -5)
            for kind in ("Translational", "Rotational"):
                for axis in "XYZ":
                    setattr(support, kind + "Mode" + axis, "Constraint")
            analysis.addObject(support)
            tie = ObjectsFem.makeConstraintTie(doc, "RearOrdinaryTie")
            tie.References = [(geometry, [slave_face]), (geometry, [master_face])]
            tie.Tolerance = 0
            analysis.addObject(tie)
            def x_face(x, normal):
                matches = [index for index, face in enumerate(geometry.Shape.Faces, 1)
                           if abs(face.CenterOfMass.x - x) < 1e-7
                           and abs(face.CenterOfMass.z - 15) < 1e-7
                           and face.normalAt(0, 0).x * normal > 0.99]
                self.assertEqual(len(matches), 1, (x, normal, matches))
                return f"Face{matches[0]}"
            contact = ObjectsFem.makeConstraintContact(doc, "SidepadContact")
            contact.References = [(geometry, [x_face(10, -1)]),
                                  (geometry, [x_face(10, 1)])]
            contact.Slope = "1000000 MPa/mm"
            contact.StickSlope = "1000000 MPa/mm"
            contact.Friction = True
            contact.FrictionCoefficient = 0.3
            contact.SurfaceBehavior = "Tied"
            contact.Adjust = "0 mm"
            analysis.addObject(contact)
            side_pressure = ObjectsFem.makeConstraintPressure(doc, "SidePressure")
            side_pressure.References = [(geometry, [x_face(20, 1)])]
            side_pressure.Pressure = "1 MPa"
            analysis.addObject(side_pressure)
            pressure = ObjectsFem.makeConstraintPressure(doc)
            pressure.References = [(geometry, [loaded_face])]
            pressure.Pressure = "1 MPa"
            analysis.addObject(pressure)
            gravity = ObjectsFem.makeConstraintSelfWeight(doc)
            analysis.addObject(gravity)
            section = ObjectsFem.makeConstraintSectionPrint(doc, "RearCut")
            section.References = [(geometry, [cut_face])]
            section.NativeEquilibriumCut = True
            section.AccountingBody = [(geometry, [rear_solid])]
            analysis.addObject(section)
            mesh = ObjectsFem.makeMeshGmsh(doc, "Mesh")
            mesh.Shape = geometry
            mesh.ElementOrder = "2nd"
            mesh.SecondOrderLinear = False
            mesh.CoherenceMesh = False
            mesh.CharacteristicLengthMax = 4
            mesh.CharacteristicLengthMin = 2
            mesh.WorkingDirectory = str(output)
            analysis.addObject(mesh)
            doc.recompute()
            receipt["native_references"] = {
                "support": base_solid, "tie_slave": slave_face, "tie_master": master_face,
                "rear_body": rear_solid, "cut": cut_face, "pressure": loaded_face}
            checkpoint("native-four-body-fixture-authored-without-extra-support")
            mesher = gmshtools.GmshTools(mesh)
            mesher.create_mesh()
            self.assertEqual(mesher.process.exitCode(), 0)
            self.assertEqual(mesher.process.exitStatus(), mesher.process.ExitStatus.NormalExit)
            self.assertGreater(mesh.FemMesh.VolumeCount, 0)
            checkpoint("native-gmsh-complete", nodes=mesh.FemMesh.NodeCount,
                       volumes=mesh.FemMesh.VolumeCount)
            saved = output / "analytical-tie.FCStd"
            doc.saveAs(str(saved))
            receipt["saved_model"] = {"path": str(saved), "sha256": digest(saved)}
            fea = FemToolsCcx(analysis=analysis, solver=solver)
            fea.update_objects()
            fea.setup_working_dir(str(output))
            checkpoint("before-stock-writer")
            fea.write_inp_file()
            deck = Path(fea.inp_file_name)
            text = deck.read_text()
            self.assertIn("ADJUST=NO", text)
            self.assertIn("*TIE", text.upper())
            receipt["stock_deck"] = {"path": str(deck), "sha256": digest(deck)}
            checkpoint("stock-writer-complete")
            try:
                code = fea.ccx_run()
            finally:
                (output / "solver.stdout").write_text(getattr(fea, "ccx_stdout", ""))
                (output / "solver.stderr").write_text(getattr(fea, "ccx_stderr", ""))
                receipt["actual_solver"] = str(getattr(fea, "ccx_binary", ""))
                receipt["actual_solver_sha256"] = digest(fea.ccx_binary)
            self.assertEqual(code, 0)
            checkpoint("stock-runner-complete", exit_code=code)
            result = next(obj for obj in analysis.Group
                          if isinstance(getattr(obj, "Proxy", None), force_accounting.AccountingResult))
            self.assertTrue(result.Status.startswith("Current"), result.Status)
            data = json.loads(result.AccountingData)
            weight = (1000 * 1e-9 * 7900
                      * gravity.GravityAcceleration.getValueAs("m/s^2").Value)
            receipt["analytic_weight_each_N"] = weight
            receipt["analytic_checks"] = []
            for kind, name, wanted in (
                    ("SUPPORT", support.Name,
                     [100, 0, 100 + 4 * weight,
                      500 + 20 * weight, 1000 - 30 * weight, -500]),
                    ("CUT", section.Name,
                     [0, 0, -100 - weight, -500 - 5 * weight, 500 + 5 * weight, 0]),
                    ("LOAD", section.Name,
                     [0, 0, -weight, -5 * weight, 5 * weight, 0]),
                    ("CONTACT", section.Name,
                     [-100, 0, -weight, -5 * weight, -1500 + 15 * weight, 500]),
                    ("MPC", section.Name,
                     [100, 0, 100 + 3 * weight,
                      500 + 15 * weight, 1000 - 25 * weight, -500])):
                values = data["wrenches"][kind][name]
                wanted_force = App.Vector(*wanted[:3])
                wanted_moment = App.Vector(*wanted[3:])
                self.assertGreater(wanted_moment.Length, 0)
                force_error = (App.Vector(*values[:3]) - wanted_force).Length / max(wanted_force.Length, 1)
                moment_error = (App.Vector(*values[3:]) - wanted_moment).Length / max(wanted_moment.Length, 1)
                receipt["analytic_checks"].append({"kind": kind, "name": name,
                    "expected": list(wanted_force) + list(wanted_moment), "actual": values,
                    "force_relative_error": force_error, "origin_moment_relative_error": moment_error})
                self.assertLessEqual(force_error, 0.01)
                self.assertLessEqual(moment_error, 0.01)
            (output / "native-accounting.json").write_text(json.dumps(data, indent=2) + "\n")
            receipt["passed"] = True
            checkpoint("physical-force-and-origin-moment-passed")
        except BaseException as error:
            receipt["error"] = repr(error)
            receipt["traceback"] = traceback.format_exc()
            print("FIVEAR_CAPABILITY_FAILURE=" + repr(error), flush=True)
            raise
        finally:
            if doc is not None:
                App.closeDocument(doc.Name)
            (output / "probe.json").write_text(json.dumps(receipt, indent=2) + "\n")
