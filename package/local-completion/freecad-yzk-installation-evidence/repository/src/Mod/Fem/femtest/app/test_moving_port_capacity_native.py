# SPDX-License-Identifier: LGPL-2.1-or-later
"""Expensive dedicated native capacity qualification, not default TestFemApp.

Run explicitly with FreeCADCmd -t femtest.app.test_moving_port_capacity_native.
The complete 132-bay/264-port analytical graph uses untouched stock interfaces.
This is software regression coverage, not engineering or building acceptance.
Separate-process cold qualification is an external serial gate; this test only
claims literal save and in-process close/reopen historical behavior.
"""

import json
import math
import os
import re
import shutil
import tempfile
import time
import traceback
import unittest
from pathlib import Path
from unittest.mock import patch

import FreeCAD as App

import Fem
import ObjectsFem

from feminout.importCcxFrdResults import read_frd_result
from femtest.app.coupled_port_audit import audit_export
from femtest.app.coupled_port_audit import parse_port_motion
from femtest.app.coupled_port_fixture import DATA
from femtest.app.coupled_port_fixture import FROZEN
from femtest.app.coupled_port_fixture import make_fixture
from femtest.app.coupled_port_fixture import mesh_membership
from femtest.app.coupled_port_fixture import model_properties
from femtest.app.coupled_port_fixture import plain
from femtest.app.coupled_port_fixture import sha
from femtest.app.coupled_port_fixture import write_json
from femtools import force_accounting
from femtools.ccxtools import FemToolsCcx
from femtools.femutils import is_of_type

ROOT = Path(__file__).resolve().parent


def input_pins():
    names = (
        "coupled_port_fixture.py",
        "coupled_port_audit.py",
        "test_moving_port_capacity_native.py",
    )
    paths = [*(ROOT / name for name in names), *(DATA / name for name in FROZEN)]
    return {str(path): sha(path) for path in paths}


def vector_check(checks, name, actual, reference, zero_scale, limit):
    actual, reference = list(actual), list(reference)
    if (
        len(actual) != 3
        or len(reference) != 3
        or not all(math.isfinite(v) for v in actual + reference)
    ):
        raise AssertionError("Nonfinite or non-vector comparison: " + name)
    norm, error = math.hypot(*reference), math.dist(actual, reference)
    scale = norm if norm else zero_scale
    if not math.isfinite(scale) or scale <= 0:
        raise AssertionError("Undeclared/nonpositive comparison scale: " + name)
    row = {
        "name": name,
        "actual": actual,
        "reference": reference,
        "reference_norm": norm,
        "error_norm": error,
        "scale": scale,
        "relative_error": error / scale,
        "limit": limit,
        "passed": error <= limit * scale,
    }
    checks.append(row)
    if not row["passed"]:
        raise AssertionError(row)


def wrench_checks(checks, name, actual, reference, force_scale, moment_scale):
    if len(actual) != 6 or len(reference) != 6:
        raise AssertionError("Not a six-component original-origin wrench: " + name)
    vector_check(checks, name + "/force", actual[:3], reference[:3], force_scale, 0.01)
    vector_check(
        checks, name + "/original-origin-moment", actual[3:], reference[3:], moment_scale, 0.01
    )


@unittest.skipUnless(shutil.which("gmsh"), "Native Gmsh executable required")
class TestMovingPortCapacityNative(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("MovingPortCapacityNative")
        self.document_name = self.doc.Name
        self.addCleanup(self._close_document)
        try:
            Fem.FemMesh().toVTK()
        except NotImplementedError:
            self.skipTest("Native VTK Python wrappers are unavailable in this build")
        probe = ObjectsFem.makeSolverCalculiXCcxTools(self.doc, "SolverAvailability")
        self.native_override = os.environ.get("FREECAD_9ZT_PRODUCTION_CCX")
        if self.native_override:
            probe.NativeAccountingSolver = self.native_override
        binary = Path(force_accounting.solver_binary(probe))
        if not binary.is_file() or not os.access(binary, os.X_OK):
            self.skipTest("Qualified native force-accounting solver is unavailable")
        force_accounting.require_capability(binary)
        self.doc.removeObject(probe.Name)
        self.output = Path(tempfile.mkdtemp(prefix="freecad-moving-port-capacity-native-"))
        App.Console.PrintMessage("Native capacity evidence: " + str(self.output) + "\n")

    def _close_document(self):
        if self.document_name in App.listDocuments():
            App.closeDocument(self.document_name)

    def test_complete_132_bay_graph_obeys_the_native_declaration_budget(self):
        with patch.dict(os.environ, {"CCX_FORCE_ACCOUNTING_MAX_DECLARATIONS": "2113"}):
            self._run_capacity_case()

    def _run_capacity_case(self):
        case, rows_y, columns_z = "capacity", 11, 12
        output = self.output / "witness"
        checks = []
        receipt = {
            "schema": "FreeCAD-native-coupled-port-coupled-native-witness-v1",
            "passed": False,
            "case": case,
            "rows_y": rows_y,
            "columns_z": columns_z,
            "only_public_native_interfaces": True,
            "no_deck_patches_or_mocks": True,
            "engineering_project_accessed_or_solved": False,
            "engineering_or_BIM_accepted": False,
            "frozen_oracle_sha256": FROZEN,
            "inputs_before": input_pins(),
            "checks": checks,
            "force_and_original_origin_moment_limit": 0.01,
            "scalar_response_limit": 0.05,
            "local_generalized_force_and_couple_limit": 0.01,
            "phase": "before-fixture",
        }
        doc, fixture = self.doc, None
        try:
            fixture = make_fixture(doc, output, rows_y=rows_y, columns_z=columns_z)
            receipt["phase"] = "fixture-and-physical-mesh-proved"
            candidate = self.native_override
            if candidate:
                fixture.solver.NativeAccountingSolver = candidate
            receipt["explicit_candidate_override"] = candidate
            properties = model_properties(fixture.analysis, fixture.mesh)
            write_json(output / "export-properties.json", properties)
            doc.recompute()
            before_document = output / "coupled-before-export.FCStd"
            doc.saveAs(str(before_document))
            receipt["before_export_document_sha256"] = sha(before_document)

            fea = FemToolsCcx(analysis=fixture.analysis, solver=fixture.solver)
            fea.update_objects()
            fea.setup_working_dir(str(output / "native"))
            required = {"supports": 1, "bodies": 264, "ports": 264, "angles": 792, "springs": 792}
            before_refusal = model_properties(fixture.analysis, fixture.mesh)
            with patch.dict(os.environ, {"CCX_FORCE_ACCOUNTING_MAX_DECLARATIONS": "2112"}):
                with self.assertRaisesRegex(ValueError, "capacity exceeded") as caught:
                    fea.write_inp_file()
            diagnostic = str(caught.exception)
            for kind, count in required.items():
                self.assertIn(f"{kind} required {count}; supported 2112", diagnostic)
            self.assertIn("total required 2113; supported 2112", diagnostic)
            self.assertEqual(list((output / "native").iterdir()), [])
            self.assertEqual(model_properties(fixture.analysis, fixture.mesh), before_refusal)
            self.assertEqual(mesh_membership(fixture), fixture.membership)
            self.assertFalse(any(hasattr(obj, "AccountingData") for obj in fixture.analysis.Group))
            receipt["one_below_capacity_refusal"] = {
                "budget": 2112,
                "required": required,
                "total": 2113,
                "diagnostic": diagnostic,
                "export_directory_untouched": True,
                "selected_properties_and_public_mesh_membership_unchanged": True,
                "no_FE_solve": True,
            }
            receipt["phase"] = "stock-writer-started"
            export_started = time.perf_counter()
            fea.write_inp_file()
            receipt["stock_write_inp_file_seconds"] = time.perf_counter() - export_started
            receipt["export_timing_scope"] = (
                "Whole accepted stock API call: mesh sets, writer, request and capacity checks. "
                "Excludes fixture creation and the earlier refusal; diagnostic only, no SLA."
            )
            deck = Path(fea.inp_file_name)
            request = deck.with_suffix(".accounting")
            original_hashes = {"deck": sha(deck), "request": sha(request)}
            receipt["deck"], receipt["request"] = str(deck), str(request)
            receipt["original_native_input_sha256"] = original_hashes
            receipt["phase"] = "stock-writer-finished"
            export = audit_export(fixture, deck, request, deck.with_suffix(".accounting.out"))
            self.assertTrue(export["passed"])
            write_json(output / "independent-export-audit.json", export)
            receipt["export_audit_sha256"] = sha(output / "independent-export-audit.json")
            receipt["phase"] = "complete-native-input-graph-proved"
            code = fea.ccx_run()
            (output / "native.stdout").write_text(fea.ccx_stdout)
            (output / "native.stderr").write_text(fea.ccx_stderr)
            receipt.update(
                solver_returncode=code,
                actual_binary=str(fea.ccx_binary),
                actual_binary_sha256=sha(fea.ccx_binary),
                phase="native-process-returned",
            )
            self.assertEqual(code, 0, fea.ccx_stdout + fea.ccx_stderr)
            self.assertEqual({"deck": sha(deck), "request": sha(request)}, original_hashes)
            wire = deck.with_suffix(".accounting.out")
            lines = wire.read_text().splitlines()
            self.assertEqual(lines[0], "CCX_FORCE_ACCOUNTING_V3")
            self.assertEqual(lines[-1], "END")
            reports = [
                item
                for item in fixture.analysis.Group
                if is_of_type(item, "Fem::NativeForceAccountingResult")
            ]
            self.assertEqual(len(reports), 1)
            report = reports[0]
            self.assertTrue(report.Status.startswith("Current"), report.Status)
            literal = report.AccountingData
            data = json.loads(literal)
            self.assertEqual(data["schema"], "CCX_FORCE_ACCOUNTING_V3")
            self.assertEqual(data["capacity"]["required"], required)
            self.assertEqual(data["capacity"]["total"], 2113)
            self.assertEqual(data["capacity"]["supported"]["total_records"], 2113)
            self.assertEqual(
                data["capacity_applied"],
                {
                    "budget": 2113,
                    "counts": required,
                    "total": 2113,
                },
            )
            self.assertEqual(data["movement_source"]["status"], "BOUND")
            self.assertEqual(data["binary"], str(fea.ccx_binary))
            self.assertEqual(data["binary_sha256"], sha(fea.ccx_binary))
            self.assertEqual(data["analysis"], fixture.analysis.Name)
            self.assertEqual(data["mesh"], fixture.mesh.Name)
            self.assertEqual(data["deck_sha256"], original_hashes["deck"])
            self.assertEqual(data["request_sha256"], original_hashes["request"])
            self.assertEqual(data["output_sha256"], sha(wire))
            self.assertEqual(data["end_time"], 1.0)
            self.assertRegex(data["model_digest"], r"^[0-9a-f]{64}$")
            self.assertEqual(len(data["expected"]), len(fixture.cuts) + 1)
            self.assertEqual(
                {tuple(item) for item in data["expected"]},
                {("SUPPORT", fixture.fixed.Name), *(("CUT", cut.Name) for cut in fixture.cuts)},
            )
            source = data["movement_source"]
            self.assertEqual(source["schema"], "FREECAD_MOVEMENT_SOURCE_V1")
            self.assertEqual(source["path"], str(deck.with_suffix(".frd")))
            self.assertEqual(source["sha256"], sha(deck.with_suffix(".frd")))
            self.assertEqual(source["deck"], str(deck))
            self.assertEqual(source["request"], str(request))
            self.assertEqual(source["binary"], str(fea.ccx_binary))
            self.assertEqual(source["deck_sha256"], original_hashes["deck"])
            self.assertEqual(source["request_sha256"], original_hashes["request"])
            self.assertEqual(source["binary_sha256"], sha(fea.ccx_binary))
            self.assertEqual(source["model_digest"], data["model_digest"])
            self.assertEqual(source["requested_end_time"], 1.0)
            (output / "native-accounting-data.json").write_text(literal)
            channels = data["wrenches"]
            self.assertEqual(set(channels), {"SUPPORT", "CUT", "LOAD", "CONTACT", "MPC"})
            self.assertEqual(set(channels["SUPPORT"]), {fixture.fixed.Name})
            body_names = {cut.Name for cut in fixture.cuts}
            for kind in ("CUT", "LOAD", "CONTACT", "MPC"):
                self.assertEqual(set(channels[kind]), body_names)
            oracle = json.loads((DATA / "coupled_port_capacity_oracle.json").read_text())
            expected_case = oracle["tracer_1_by_1" if case == "tracer" else "capacity_11_by_12"]
            total = expected_case["whole_applied_wrench"]
            support = expected_case["physical_external_SUPPORT"]
            force_scale, moment_scale = math.hypot(*total[:3]), math.hypot(*total[3:])
            wrench_checks(
                checks,
                "SUPPORT/" + fixture.fixed.Name,
                channels["SUPPORT"][fixture.fixed.Name],
                support,
                force_scale,
                moment_scale,
            )
            for branch in fixture.branches:
                # Independently frozen load statics, not a calculation from
                # accounting output or any target writer/solver force helper.
                w = [12, 0, 0, 6, 12 * branch["z"], -12 * branch["y"]]
                scale_m = math.hypot(*w[3:])
                expected = {
                    "Left": {"CUT": w, "LOAD": [0] * 6, "CONTACT": [0] * 6, "MPC": [-v for v in w]},
                    "Right": {
                        "CUT": [-v for v in w],
                        "LOAD": w,
                        "CONTACT": [0] * 6,
                        "MPC": [0] * 6,
                    },
                }
                for side in ("Left", "Right"):
                    name = branch["cuts"][side].Name
                    for kind in ("CUT", "LOAD", "CONTACT", "MPC"):
                        wrench_checks(
                            checks,
                            kind + "/" + name,
                            channels[kind][name],
                            expected[side][kind],
                            12,
                            scale_m,
                        )
                    balance = [
                        sum(
                            channels[kind][name][axis] for kind in ("CUT", "LOAD", "CONTACT", "MPC")
                        )
                        for axis in range(6)
                    ]
                    wrench_checks(checks, name + "/body-equilibrium", balance, [0] * 6, 12, scale_m)
                paired = [
                    sum(
                        channels["CUT"][branch["cuts"][side].Name][axis]
                        for side in ("Left", "Right")
                    )
                    for axis in range(6)
                ]
                wrench_checks(
                    checks, branch["name"] + "/paired-cut-sum", paired, [0] * 6, 12, scale_m
                )

            motion = parse_port_motion(deck.with_suffix(".dat"), export["rbe_ids"])
            self.assertTrue(motion["passed"])
            write_json(output / "motion-from-original-dat.json", motion)
            # Verify the original FRD's actual displacement state independently
            # of the requested-time provenance claim before using its field.
            frd_state, displacement_times = None, []
            for line in deck.with_suffix(".frd").read_text().splitlines():
                if re.match(r"^\s*100CL\s", line):
                    fields = line.split()
                    self.assertGreaterEqual(len(fields), 3)
                    frd_state = float(fields[2])
                    self.assertTrue(math.isfinite(frd_state))
                elif re.match(r"^\s*-4\s+DISP\b", line):
                    self.assertIsNotNone(frd_state)
                    displacement_times.append(frd_state)
            self.assertTrue(displacement_times)
            self.assertTrue(all(0 <= value <= 1 for value in displacement_times))
            self.assertEqual(displacement_times[-1], 1.0)
            receipt["observed_FRD_displacement_times"] = displacement_times
            displacement = read_frd_result(str(deck.with_suffix(".frd")))["Results"][-1]["disp"]
            coordinates = fixture.mesh.FemMesh.Nodes
            physical_proof, host_work = {}, 0.0
            for port in fixture.ports:
                port_motion = motion["ports"][port.Name]
                translation, rotation = App.Vector(*port_motion["translation_mm"]), App.Vector(
                    *port_motion["rotation_rad"]
                )
                errors, nonzero = [], False
                for node in fixture.membership["moving_face_nodes"][port.Name]:
                    actual = App.Vector(*displacement[node])
                    predicted = translation + rotation.cross(coordinates[node] - port.ReferenceNode)
                    denominator = predicted.Length if predicted.Length else 0.01
                    error = (actual - predicted).Length / denominator
                    self.assertTrue(math.isfinite(error))
                    self.assertLessEqual(error, 0.05, (port.Name, node, actual, predicted))
                    errors.append(error)
                    nonzero |= actual.Length > 0
                physical_proof[port.Name] = {
                    "nodes": len(errors),
                    "maximum_relative_kinematic_error": max(errors),
                    "finite_physical_face_has_nonzero_motion": bool(nonzero),
                }
            for branch in fixture.branches:
                a, b = (motion["ports"][branch["ports"][side].Name] for side in ("A", "B"))
                du = [y - x for x, y in zip(a["translation_mm"], b["translation_mm"])]
                dr = [y - x for x, y in zip(a["rotation_rad"], b["rotation_rad"])]
                vector_check(
                    checks,
                    branch["name"] + "/differential-translation",
                    du,
                    [0.01, 0, 0],
                    0.01,
                    0.05,
                )
                vector_check(
                    checks,
                    branch["name"] + "/differential-rotation",
                    dr,
                    [0.001, 0, 0],
                    0.001,
                    0.05,
                )
                vector_check(
                    checks,
                    branch["name"] + "/local-generalized-force",
                    [1200 * v for v in du],
                    [12, 0, 0],
                    12,
                    0.01,
                )
                vector_check(
                    checks,
                    branch["name"] + "/local-generalized-couple",
                    [6000 * v for v in dr],
                    [6, 0, 0],
                    6,
                    0.01,
                )
                vector_check(
                    checks,
                    branch["name"] + "/explicit-local-X-torque",
                    [6000 * dr[0], 0, 0],
                    [6, 0, 0],
                    6,
                    0.01,
                )
                host_work += 12 * a["translation_mm"][0] + 6 * a["rotation_rad"][0]
            self.assertTrue(
                math.isfinite(host_work) and host_work > 0,
                "Finite backbone under nonzero port loads has no positive observable elastic work",
            )
            self.assertTrue(
                any(
                    physical_proof[branch["ports"]["A"].Name][
                        "finite_physical_face_has_nonzero_motion"
                    ]
                    for branch in fixture.branches
                )
            )
            self.assertTrue(
                all(
                    physical_proof[branch["ports"]["B"].Name][
                        "finite_physical_face_has_nonzero_motion"
                    ]
                    for branch in fixture.branches
                )
            )
            write_json(output / "physical-face-motion-proof.json", physical_proof)
            receipt["host_positive_generalized_load_work_N_mm"] = host_work
            receipt["phase"] = "independent-physical-equilibrium-and-response-proved"

            fea.load_results()
            self.assertTrue(fea.results_present)
            fem_results = [
                item
                for item in fixture.analysis.Group
                if item.isDerivedFrom("Fem::FemResultObject")
            ]
            self.assertTrue(fem_results)
            receipt["fem_result_objects"] = [item.Name for item in fem_results]
            self.assertTrue(report.Status.startswith("Current"), report.Status)
            self.assertEqual(report.AccountingData, literal)
            resultants = plain(list(report.Resultants))
            doc.recompute()
            self.assertTrue(report.Status.startswith("Current"), report.Status)
            saved = output / "coupled-native-current.FCStd"
            doc.saveAs(str(saved))
            self.assertEqual(report.AccountingData, literal)
            self.assertTrue(report.Status.startswith("Current"), report.Status)
            self.assertEqual({"deck": sha(deck), "request": sha(request)}, original_hashes)
            self.assertEqual(sha(wire), data["output_sha256"])
            self.assertEqual(sha(deck.with_suffix(".frd")), source["sha256"])
            self.assertEqual(sha(fea.ccx_binary), data["binary_sha256"])
            source_files = {
                "deck": deck,
                "request": request,
                "native_output": wire,
                "dat": deck.with_suffix(".dat"),
                "frd": deck.with_suffix(".frd"),
            }
            cold = {
                "schema": "FreeCAD-native-coupled-port-coupled-cold-case-v1",
                "case": case,
                "document": str(saved),
                "document_sha256": sha(saved),
                "report_name": report.Name,
                "analysis_name": fixture.analysis.Name,
                "solver_name": fixture.solver.Name,
                "mesh_name": fixture.mesh.Name,
                "accounting_data_literal": literal,
                "resultants_literal": resultants,
                "saved_status_literal": report.Status,
                "movement_source_literal": data["movement_source"],
                "binary": str(fea.ccx_binary),
                "binary_sha256": sha(fea.ccx_binary),
                "source_files": {
                    name: {"path": str(path), "sha256": sha(path)}
                    for name, path in source_files.items()
                },
                "explicit_supports": [obj.Name for obj in fixture.solver.NativeAccountingSupports],
                "saved_references": {
                    obj.Name: plain(obj.References)
                    for obj in [*fixture.ports, *fixture.cuts, fixture.fixed]
                },
                "saved_native_properties": properties,
                "frozen_oracle_sha256": FROZEN,
                "no_cold_restore_performed_yet": True,
                "no_history_or_provenance_repair": True,
            }
            write_json(output / "cold-case.json", cold)
            App.closeDocument(doc.Name)
            doc = App.openDocument(str(saved))
            self.doc = doc
            self.document_name = doc.Name
            restored = doc.getObject(cold["report_name"])
            self.assertTrue(restored.Status.startswith("Stale"), restored.Status)
            self.assertEqual(restored.AccountingData, literal)
            self.assertEqual(plain(list(restored.Resultants)), resultants)
            doc.recompute()
            self.assertTrue(restored.Status.startswith("Stale"), restored.Status)
            self.assertEqual(restored.AccountingData, literal)
            self.assertEqual(plain(list(restored.Resultants)), resultants)
            self.assertEqual(sha(saved), cold["document_sha256"])
            receipt["in_process_historical_reopen"] = {
                "passed": True,
                "status": restored.Status,
                "literal_accounting_unchanged": True,
                "source_document_bytes_unchanged": True,
                "separate_process_cold_claimed": False,
            }
            receipt.update(
                passed=True,
                phase="normal-import-save-inprocess-reopen-complete",
                cold_manifest=str(output / "cold-case.json"),
                cold_manifest_sha256=sha(output / "cold-case.json"),
                physical_check_count=len(checks),
                current_native_report={
                    "name": cold["report_name"],
                    "status": cold["saved_status_literal"],
                    "schema": data["schema"],
                    "movement_status": data["movement_source"]["status"],
                },
            )
        except BaseException as error:
            receipt["passed"] = False
            receipt["witness_error"] = {
                "type": type(error).__name__,
                "message": str(error),
                "traceback": traceback.format_exc(),
            }
            raise
        finally:
            output.mkdir(parents=True, exist_ok=True)
            receipt["inputs_after"] = input_pins()
            receipt["protected_inputs_unchanged"] = (
                receipt["inputs_before"] == receipt["inputs_after"]
            )
            receipt["passed"] &= receipt["protected_inputs_unchanged"]
            receipt["retained_files"] = {
                str(path.relative_to(output)): {"sha256": sha(path), "bytes": path.stat().st_size}
                for path in sorted(output.rglob("*"))
                if path.is_file()
            }
            write_json(output / "witness-receipt.json", receipt)
            self._close_document()
        self.assertTrue(receipt["passed"])
