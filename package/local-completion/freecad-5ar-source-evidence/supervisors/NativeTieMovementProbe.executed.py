# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native ordinary-Tie observation boundary with a genuine current source.

This separate diagnostic disables the analytical fixture's native cut request
only, preserving its AccountingBody selection, ordinary Tie, actual sidepad
contact, geometry, mesh, materials and loads.  It does NOT satisfy or waive the
required Tie-participating-body force test, whose failing evidence is separate.
No Oomakhi document is opened, changed, solved or accepted.
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
import shutil
import traceback
import unittest

import FreeCAD as App
import Fem
import ObjectsFem
import Part
from femtools import force_accounting
from femtools.ccxtools import FemToolsCcx


REPOSITORY = Path("/Users/zukomgwili/src/FreeCAD")
BUILD = REPOSITORY / "build/release"
SOURCE = Path("/private/tmp/freecad-5ar-wYCAxF/force-green-1/analytical-tie.FCStd")
SOURCE_SHA256 = "85a145e1121428bfa3d55ad2d8f3bc23abeb7901aff401117ebc1ba2cd25ead1"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class NativeTieMovementProbe(unittest.TestCase):
    def test_actual_ordinary_tie_is_available_to_native_side_observation(self):
        output = Path(os.environ["FIVEAR_RUN"])
        report = {
            "passed": False,
            "scope": "ordinary Tie observation capability with current native movement source",
            "Oomakhi_opened_or_solved": False,
            "required_cut_body_force_capability_satisfied": False,
            "native_body_requests_disabled_only_for_this_movement_control": True,
            "checkpoints": [],
        }
        doc = None

        def checkpoint(name, **values):
            report["checkpoints"].append({"name": name, **values})
            (output / "checkpoint.json").write_text(json.dumps(report, indent=2) + "\n")
            print("FIVEAR_CHECKPOINT=" + json.dumps({"name": name, **values}), flush=True)

        try:
            self.assertFalse(App.GuiUp)
            self.assertTrue(sys.dont_write_bytecode)
            self.assertEqual(Path(App.getHomePath()).resolve(), BUILD.resolve())
            header = (BUILD / "src/Build/Version.h").read_text()
            for macro, actual in (("FCRevision", App.Version()[3]),
                                  ("FCRepositoryHash", App.Version()[-1])):
                match = re.search(r'^#define\s+' + macro + r'\s+"([^\"]+)"', header, re.M)
                self.assertIsNotNone(match, macro)
                self.assertEqual(actual, match.group(1), macro)
            report["runtime"] = App.Version()
            report["modules"] = {}
            for name, relative in {
                "ObjectsFem": "ObjectsFem.py",
                "femmesh.meshsetsgetter": "femmesh/meshsetsgetter.py",
                "femmesh.meshtools": "femmesh/meshtools.py",
                "femtools.ccxtools": "femtools/ccxtools.py",
                "femtools.force_accounting": "femtools/force_accounting.py",
                "femobjects.result_contact_observation": "femobjects/result_contact_observation.py",
                "femresult.contact_observation": "femresult/contact_observation.py",
            }.items():
                actual = Path(importlib.import_module(name).__file__).resolve()
                source = REPOSITORY / "src/Mod/Fem" / relative
                self.assertEqual(actual, (BUILD / "Mod/Fem" / relative).resolve(), name)
                self.assertEqual(digest(actual), digest(source), name)
                report["modules"][name] = {"path": str(actual), "sha256": digest(actual)}
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
            expected = [BUILD / "Mod/Fem/Fem.so", BUILD / "Mod/Part/Part.so",
                        BUILD / "lib/libFreeCADApp.dylib"]
            for path in expected:
                self.assertTrue(path.resolve() in images, str(path))
            self.assertEqual(Path(Fem.__file__).resolve(), expected[0].resolve())
            self.assertEqual(Path(Part.__file__).resolve(), expected[1].resolve())
            report["native_images"] = [{"path": str(path), "sha256": digest(path)}
                                       for path in expected]
            report["executable"] = {"path": str(executable), "sha256": digest(executable)}
            checkpoint("native-identity-confirmed")

            self.assertEqual(digest(SOURCE), SOURCE_SHA256)
            private_source = output / "movement-input.FCStd"
            shutil.copy2(SOURCE, private_source)
            self.assertEqual(digest(private_source), SOURCE_SHA256)
            report["original_input"] = {"path": str(SOURCE), "sha256": SOURCE_SHA256}
            doc = App.openDocument(str(private_source))
            analysis = doc.getObject("Analysis")
            # Public factory default names from the saved native force fixture.
            # Resolve by native object properties only if its analysis was renamed.
            if analysis is None:
                candidates = [obj for obj in doc.Objects if obj.isDerivedFrom("Fem::FemAnalysis")]
                self.assertEqual(len(candidates), 1)
                analysis = candidates[0]
            solver = next(obj for obj in analysis.Group if hasattr(obj, "NativeForceAccounting"))
            mesh = next(obj for obj in analysis.Group if obj.isDerivedFrom("Fem::FemMeshObject"))
            tie = doc.getObject("RearOrdinaryTie")
            contact = doc.getObject("SidepadContact")
            section = doc.getObject("RearCut")
            self.assertIsNotNone(tie)
            self.assertIsNotNone(contact)
            self.assertIsNotNone(section)
            self.assertIn(tie, analysis.Group)
            self.assertIn(contact, analysis.Group)
            # PropertyLinkSubList may combine repeated object links on restore;
            # the two explicit native face identities, not list slots, matter.
            self.assertEqual(sum(len(subs) for obj, subs in tie.References), 2)
            self.assertEqual(sum(len(subs) for obj, subs in contact.References), 2)
            self.assertEqual(len(mesh.Shape.Shape.Solids), 4)
            body_before = [(obj.Name, list(subs)) for obj, subs in section.AccountingBody]
            tie_before = [(obj.Name, list(subs)) for obj, subs in tie.References]
            contact_before = [(obj.Name, list(subs)) for obj, subs in contact.References]
            section.NativeEquilibriumCut = False
            self.assertEqual([(obj.Name, list(subs)) for obj, subs in section.AccountingBody], body_before)
            self.assertTrue(solver.NativeForceAccounting)
            self.assertEqual(solver.NativeAccountingSolver, "")
            checkpoint("cold-native-fixture-opened-cut-request-disabled",
                       nodes=mesh.FemMesh.NodeCount, volumes=mesh.FemMesh.VolumeCount,
                       retained_AccountingBody=body_before, actual_tie=tie.Name, actual_contact=contact.Name)

            fea = FemToolsCcx(analysis=analysis, solver=solver)
            fea.update_objects()
            fea.setup_working_dir(str(output))
            fea.write_inp_file()
            deck = Path(fea.inp_file_name)
            text = deck.read_text()
            self.assertIn("*TIE", text.upper())
            self.assertIn("ADJUST=NO", text)
            self.assertIn("*CONTACT PAIR", text.upper())
            request = deck.with_suffix(".accounting")
            self.assertFalse(any(line.startswith("BODY ") for line in request.read_text().splitlines()))
            report["stock_deck"] = {"path": str(deck), "sha256": digest(deck)}
            report["stock_request"] = {"path": str(request), "sha256": digest(request)}
            checkpoint("stock-support-only-writer-complete")
            try:
                code = fea.ccx_run()
            finally:
                (output / "solver.stdout").write_text(getattr(fea, "ccx_stdout", ""))
                (output / "solver.stderr").write_text(getattr(fea, "ccx_stderr", ""))
                binary = Path(getattr(fea, "ccx_binary", ""))
                report["actual_solver"] = {"path": str(binary)}
                if binary.is_file():
                    report["actual_solver"]["sha256"] = digest(binary)
            self.assertEqual(code, 0, fea.ccx_stdout + fea.ccx_stderr)
            accounting = next(obj for obj in analysis.Group
                              if isinstance(getattr(obj, "Proxy", None), force_accounting.AccountingResult))
            self.assertTrue(accounting.Status.startswith("Current"), accounting.Status)
            report["accounting_status"] = accounting.Status
            report["current_accounting"] = json.loads(accounting.AccountingData)
            self.assertEqual([(obj.Name, list(subs)) for obj, subs in tie.References], tie_before)
            self.assertEqual([(obj.Name, list(subs)) for obj, subs in contact.References], contact_before)
            checkpoint("genuine-current-native-movement-source-established")

            result = ObjectsFem.makeResultContactObservation(
                doc, analysis, accounting, [tie], "ActualOrdinaryTieObservation")
            result.Proxy.refresh(result)
            report["tie_observation_status"] = result.Status
            checkpoint("actual-tie-observation-refreshed", status=result.Status)
            # The desired capability must be available.  Do not turn an explicit
            # unsupported-object refusal into a passing assertRaises regression.
            data = result.Proxy.getObservations(result)
            self.assertTrue(result.Status.startswith("Available"), result.Status)
            report["tie_observation"] = data
            control = ObjectsFem.makeResultContactObservation(
                doc, analysis, accounting, [contact], "ActualContactPositiveControl")
            control.Proxy.refresh(control)
            report["positive_contact_status"] = control.Status
            control_data = control.Proxy.getObservations(control)
            self.assertTrue(control.Status.startswith("Available"), control.Status)
            report["positive_contact_observation"] = control_data
            checkpoint("actual-contact-observation-positive-control-passed")
            report["passed"] = True
            checkpoint("ordinary-tie-observation-available")
        except BaseException as error:
            report["error"] = repr(error)
            report["traceback"] = traceback.format_exc()
            print("FIVEAR_CAPABILITY_FAILURE=" + repr(error), flush=True)
            raise
        finally:
            if doc is not None:
                App.closeDocument(doc.Name)
            report["original_input_unchanged"] = digest(SOURCE) == SOURCE_SHA256
            if not report["original_input_unchanged"]:
                report["passed"] = False
            (output / "probe.json").write_text(json.dumps(report, indent=2) + "\n")
