# SPDX-License-Identifier: LGPL-2.1-or-later
"""V3 ordinary/partial support composition on the frozen native RED fixture."""

import json
import math
import os
from pathlib import Path
import re
import traceback
import unittest

import FreeCAD as App
from femtools.ccxtools import FemToolsCcx

from YwuMovingPortWitness import plain, sha, write_json
from YwuOrdinarySupports import make_fixture, properties


def stock_constraints(deck):
    """Read the real unmodified stock deck, not a writer/accounting helper."""
    sets = {}
    boundaries = []
    loads = []
    section = None
    current_set = None
    generated = False
    for raw in deck.splitlines():
        line = raw.strip()
        if not line or line.startswith("**"):
            continue
        if line.startswith("*"):
            fields = [field.strip() for field in line.upper().split(",")]
            section = fields[0]
            if section == "*NSET":
                names = [field.split("=", 1)[1] for field in fields[1:] if field.startswith("NSET=")]
                if len(names) != 1:
                    raise ValueError("Ambiguous literal stock NSET header")
                current_set = names[0]
                generated = "GENERATE" in fields[1:]
                sets.setdefault(current_set, [])
            continue
        fields = [field.strip() for field in line.split(",") if field.strip()]
        if section == "*NSET":
            if generated:
                if len(fields) not in (2, 3):
                    raise ValueError("Invalid generated native node set")
                start, stop = (int(value) for value in fields[:2])
                stride = int(fields[2]) if len(fields) == 3 else 1
                sets[current_set].extend(range(start, stop + 1, stride))
            else:
                sets[current_set].extend(int(value) if value.isdigit() else value.upper() for value in fields)
        elif section == "*BOUNDARY":
            if not 2 <= len(fields) <= 4:
                raise ValueError("Invalid literal native boundary row")
            node = int(fields[0]) if fields[0].isdigit() else fields[0].upper()
            first = int(fields[1])
            last = int(fields[2]) if len(fields) >= 3 else first
            value = float(fields[3]) if len(fields) == 4 else 0.0
            boundaries.append((node, first, last, value))
        elif section == "*CLOAD":
            if len(fields) != 3:
                raise ValueError("Unexpected literal CLOAD row")
            loads.append((int(fields[0]), int(fields[1]), float(fields[2])))

    def resolve(name, visited=()):
        if isinstance(name, int):
            return {name}
        if name in visited:
            raise ValueError("Cyclic literal native node sets")
        return set().union(*(resolve(value, visited + (name,)) for value in sets[name]))

    expanded = []
    for node_or_set, first, last, value in boundaries:
        expanded.extend((node, direction, value) for node in resolve(node_or_set)
                        for direction in range(first, last + 1))
    return {name: sorted(resolve(name)) for name in sets}, expanded, loads


def request_spc_supports(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    result = {}
    for index, line in enumerate(lines):
        words = line.split()
        if words[0] != "SPC_SUPPORT":
            continue
        if len(words) != 3 or words[1] in result:
            raise ValueError("Ambiguous literal SPC_SUPPORT header")
        count = int(words[2])
        if count <= 0 or index + count >= len(lines):
            raise ValueError("Incomplete literal SPC_SUPPORT terms")
        terms = []
        for row in lines[index + 1:index + count + 1]:
            fields = row.split()
            if len(fields) != 2:
                raise ValueError("Invalid literal SPC_SUPPORT term")
            terms.append(tuple(int(value) for value in fields))
        if len(set(terms)) != count:
            raise ValueError("Repeated literal SPC_SUPPORT term")
        result[words[1]] = terms
    return result


class OrdinaryGreenWitness(unittest.TestCase):
    def test_native_fixed_partial_supports_and_moving_face_ports(self):
        output = Path(os.environ["YWU_OUTPUT"]) / "witness"
        output.mkdir()
        for directory in ("mesh", "stock-off", "native"):
            (output / directory).mkdir()
        oracle = Path(__file__).resolve().parent / "ordinary-oracle.json"
        checks = []
        receipt = {"passed": False, "schema": "FreeCAD-ywu-native-ordinary-support-green-v1",
                   "frozen_independent_oracle": str(oracle), "oracle_sha256": sha(oracle),
                   "frozen_fixture_source": str(Path(__file__).resolve().parent / "YwuOrdinarySupports.py"),
                   "frozen_fixture_source_sha256": sha(Path(__file__).resolve().parent / "YwuOrdinarySupports.py"),
                   "only_public_native_interfaces": True, "no_deck_patches_or_mocks": True,
                   "Oomakhi_opened_or_solved": False, "force_and_moment_limit": 0.01,
                   "zero_force_scale": 12, "zero_moment_scale": math.sqrt(1908),
                   "no_individual_patch_reaction_magnitude_targets": True, "checks": checks}
        doc = App.newDocument("YwuOrdinaryGreen")
        try:
            model = make_fixture(self, doc, output)
            model.solver.NativeForceAccounting = True
            for cut in model.cuts:
                cut.NativeEquilibriumCut = True
            self.assertEqual(list(model.solver.NativeAccountingSupports), model.supports)
            self.assertFalse(model.supports[1].xFree)
            self.assertTrue(model.supports[1].yFree)
            self.assertTrue(model.supports[1].zFree)
            self.assertEqual([body.Name for body in model.bodies], ["MovingPortA", "MovingPortB"])
            self.assertFalse(any(item.Name == "ExternalSupport" for item in doc.Objects))
            native_properties = properties(model)
            write_json(output / "native-properties.json", native_properties)
            mesh = model.mesh.FemMesh
            physical_nodes = {node: App.Vector(point) for node, point in mesh.Nodes.items()}
            groups = {mesh.getGroupName(group): set(mesh.getGroupElements(group)) for group in mesh.Groups}
            write_json(output / "mesh-membership.json", {
                "selected_face_nodes": model.memberships, "face_keys": model.faces,
                "cut_owner_solid_keys": model.solids, "end_edge_loads": model.end_edges,
                "actual_geometry_solid_count": len(model.geometry.Shape.Solids),
                "actual_geometry_volume_mm3": model.geometry.Shape.Volume,
                "conforming_continuum_membership_proof": model.continuum_membership_proof,
                "native_groups": {name: sorted(elements) for name, elements in groups.items()},
                "nodes": {str(node): plain(point) for node, point in physical_nodes.items()},
                "volume_connectivity": {str(element): list(mesh.getElementNodes(element)) for element in mesh.Volumes}})
            doc.recompute()
            doc.saveAs(str(output / "ordinary-supports-before-solve.FCStd"))
            fea = FemToolsCcx(analysis=model.analysis, solver=model.solver)
            fea.update_objects()
            fea.setup_working_dir(str(output / "native"))
            fea.write_inp_file()
            deck = Path(fea.inp_file_name)
            request = deck.with_suffix(".accounting")
            original_deck = deck.read_text()
            receipt["deck"] = str(deck)
            receipt["deck_sha256_before_solve"] = sha(deck)
            receipt["request_sha256_before_solve"] = sha(request)
            sets, boundary_rows, cloads = stock_constraints(original_deck)
            expected_pairs = {
                "FixedPatch": {(node, direction) for node in model.memberships["fixed"] for direction in (1, 2, 3)},
                "PartialAxialPatch": {(node, 1) for node in model.memberships["partial"]},
            }
            expected_all = set().union(*expected_pairs.values())
            actual_physical_rows = [(node, direction, value) for node, direction, value in boundary_rows
                                    if node in physical_nodes]
            self.assertEqual(len(actual_physical_rows), len(expected_all))
            self.assertEqual({(node, direction) for node, direction, _ in actual_physical_rows}, expected_all)
            self.assertTrue(all(value == 0 for _, _, value in actual_physical_rows))
            for name, key in (("FixedPatch", "fixed"), ("PartialAxialPatch", "partial")):
                self.assertEqual(set(sets[name.upper()]), set(model.memberships[key]))
            native_terms = request_spc_supports(request.read_text())
            self.assertEqual(set(native_terms), set(expected_pairs))
            for name, wanted in expected_pairs.items():
                self.assertEqual(set(native_terms[name]), wanted, name)
                self.assertTrue(all(node in physical_nodes and direction in (1, 2, 3)
                                    for node, direction in native_terms[name]))
            helper_rows = [(node, direction, value) for node, direction, value in boundary_rows
                           if node not in physical_nodes]
            self.assertTrue(helper_rows)
            self.assertFalse({(node, direction) for node, direction, _ in helper_rows} & expected_all)
            self.assertEqual(request.read_text().splitlines()[0], "CCX_FORCE_ACCOUNTING_V3")
            self.assertNotRegex(request.read_text(), r"(?m)^SUPPORT\s")

            rbe_ids = {}
            for name in ("MovingPortA", "MovingPortB"):
                rows = re.findall(r"^\*RIGID BODY, NSET=" + re.escape(name)
                                  + r", REF NODE=(\d+), ROT NODE=(\d+)\s*$", original_deck, re.M | re.I)
                self.assertEqual(len(rows), 1, name)
                rbe_ids[name] = [int(value) for value in rows[0]]
            self.assertEqual(len(set(sum(rbe_ids.values(), []))), 4)
            self.assertGreater(min(sum(rbe_ids.values(), [])), max(physical_nodes))
            self.assertFalse(set(sum(rbe_ids.values(), [])) & {node for node, _ in expected_all})

            def vector_check(name, actual, reference, zero_scale):
                self.assertEqual(len(actual), 3)
                self.assertTrue(all(math.isfinite(value) for value in actual))
                error = math.sqrt(sum((value - target) ** 2 for value, target in zip(actual, reference)))
                norm = math.sqrt(sum(value ** 2 for value in reference))
                scale = norm if norm else zero_scale
                row = {"name": name, "actual": list(actual), "reference": list(reference),
                       "error_norm": error, "reference_norm": norm, "scale": scale,
                       "relative_error": error / scale, "limit": 0.01, "passed": error <= 0.01 * scale}
                checks.append(row)
                self.assertTrue(row["passed"], row)

            right_solids = [f"Solid{index}" for index, solid in enumerate(model.geometry.Shape.Solids, 1)
                            if abs(solid.CenterOfMass.x - 27.5) < 1e-8]
            self.assertEqual(len(right_solids), 1)
            right_nodes = {node for element in groups[right_solids[0]] for node in mesh.getElementNodes(element)}
            applied_force, applied_moment = App.Vector(), App.Vector()
            nonzero_cloads = [(node, direction, value) for node, direction, value in cloads if value != 0]
            self.assertTrue(nonzero_cloads)
            for node, direction, value in nonzero_cloads:
                self.assertIn(node, right_nodes)
                self.assertAlmostEqual(physical_nodes[node].x, 30, places=9)
                self.assertIn(direction, (1, 2, 3))
                component = [0.0, 0.0, 0.0]
                component[direction - 1] = value
                force = App.Vector(*component)
                applied_force += force
                applied_moment += physical_nodes[node].cross(force)
            vector_check("literal-stock-CLOAD/whole-force", plain(applied_force), [12, 0, 0], 12)
            vector_check("literal-stock-CLOAD/original-origin-moment", plain(applied_moment), [6, 36, -24], math.sqrt(1908))
            write_json(output / "stock-boundary-request-binding.json", {
                "physical_boundary_rows": actual_physical_rows, "helper_boundary_rows_not_supports": helper_rows,
                "expected_selected_physical_terms": {name: sorted(terms) for name, terms in expected_pairs.items()},
                "literal_request_SPC_SUPPORT_terms": native_terms,
                "original_deck_rbe_reference_rotation_ids": rbe_ids,
                "all_nonzero_CLOAD_on_B_right_external_x30": nonzero_cloads,
                "literal_CLOAD_wrench_original_origin": plain(applied_force) + plain(applied_moment)})
            code = fea.ccx_run()
            (output / "native.stdout").write_text(fea.ccx_stdout)
            (output / "native.stderr").write_text(fea.ccx_stderr)
            receipt["solver_returncode"] = code
            receipt["actual_binary"] = str(fea.ccx_binary)
            receipt["actual_binary_sha256"] = sha(fea.ccx_binary)
            self.assertEqual(code, 0)
            self.assertEqual(sha(deck), receipt["deck_sha256_before_solve"])
            self.assertEqual(sha(request), receipt["request_sha256_before_solve"])
            wire_output = deck.with_suffix(".accounting.out")
            self.assertEqual(wire_output.read_text().splitlines()[0], "CCX_FORCE_ACCOUNTING_V3")
            reports = [item for item in model.analysis.Group
                       if getattr(getattr(item, "Proxy", None), "Type", None) == "Fem::NativeForceAccountingResult"]
            self.assertEqual(len(reports), 1)
            report = reports[0]
            self.assertTrue(report.Status.startswith("Current"), report.Status)
            native_literal = report.AccountingData
            (output / "native-accounting-data.json").write_text(native_literal)
            data = json.loads(native_literal)
            self.assertEqual(data["schema"], "CCX_FORCE_ACCOUNTING_V3")
            self.assertEqual(data["movement_source"]["status"], "BOUND")
            self.assertEqual(data["binary"], str(fea.ccx_binary))
            wrenches = data["wrenches"]
            self.assertEqual(set(wrenches), {"SUPPORT", "CUT", "LOAD", "CONTACT", "MPC"})
            self.assertEqual(set(wrenches["SUPPORT"]), {"FixedPatch", "PartialAxialPatch"})
            for value in wrenches["SUPPORT"].values():
                self.assertEqual(len(value), 6)
                self.assertTrue(all(math.isfinite(component) for component in value))
            total_support = [sum(values[index] for values in wrenches["SUPPORT"].values()) for index in range(6)]
            vector_check("aggregate-ordinary-SUPPORT/force", total_support[:3], [-12, 0, 0], 12)
            vector_check("aggregate-ordinary-SUPPORT/moment", total_support[3:], [-6, -36, 24], math.sqrt(1908))
            partial = wrenches["SUPPORT"]["PartialAxialPatch"]
            self.assertEqual([partial[index] for index in (1, 2, 3)], [0, 0, 0])
            self.assertGreater(abs(partial[0]), 1e-9, "The genuine partial-Ux patch must actually participate")
            receipt["observed_partial_support_wrench_not_a_fitted_target"] = partial
            expected = {
                "CUT": {"CutARight": [-12, 0, 0, -6, -36, 24], "CutBLeft": [12, 0, 0, 6, 36, -24]},
                "LOAD": {"CutARight": [0, 0, 0, 0, 0, 0], "CutBLeft": [0, 0, 0, 0, 0, 0]},
                "CONTACT": {"CutARight": [0, 0, 0, 0, 0, 0], "CutBLeft": [0, 0, 0, 0, 0, 0]},
                "MPC": {"CutARight": [12, 0, 0, 6, 36, -24], "CutBLeft": [-12, 0, 0, -6, -36, 24]},
            }
            for kind, targets in expected.items():
                self.assertEqual(set(wrenches[kind]), set(targets), kind)
                for name, reference in targets.items():
                    actual = wrenches[kind][name]
                    self.assertEqual(len(actual), 6)
                    vector_check(kind + "/" + name + "/force", actual[:3], reference[:3], 12)
                    vector_check(kind + "/" + name + "/moment", actual[3:], reference[3:], math.sqrt(1908))
            for name in ("CutARight", "CutBLeft"):
                balance = [sum(wrenches[kind][name][index] for kind in ("CUT", "LOAD", "CONTACT", "MPC"))
                           for index in range(6)]
                vector_check(name + "/body-balance/force", balance[:3], [0, 0, 0], 12)
                vector_check(name + "/body-balance/moment", balance[3:], [0, 0, 0], math.sqrt(1908))

            dat_text = deck.with_suffix(".dat").read_text()
            motion = {}
            for body_name in ("MovingPortA", "MovingPortB"):
                motion[body_name] = {}
                for index, suffix in enumerate(("RefNode", "RotNode")):
                    set_name = body_name + "_" + suffix
                    rows = re.findall(r"displacements \(vx,vy,vz\) for set " + re.escape(set_name)
                                      + r" and time\s+([^\s]+)\s*\n\s*\n\s*([^\n]+)", dat_text, re.I)
                    self.assertEqual(len(rows), 1, set_name)
                    time, row = rows[0]
                    fields = row.split()
                    self.assertEqual(len(fields), 4)
                    self.assertEqual(int(fields[0]), rbe_ids[body_name][index])
                    self.assertAlmostEqual(float(time), 1, places=12)
                    value = [float(component) for component in fields[1:]]
                    self.assertTrue(all(math.isfinite(component) for component in value))
                    self.assertGreater(value[0], 1e-9, (set_name, value))
                    motion[body_name][suffix] = {"set": set_name, "node": int(fields[0]),
                                               "time": float(time), "value": value}
            delta_ux = motion["MovingPortB"]["RefNode"]["value"][0] - motion["MovingPortA"]["RefNode"]["value"][0]
            delta_rx = motion["MovingPortB"]["RotNode"]["value"][0] - motion["MovingPortA"]["RotNode"]["value"][0]
            vector_check("scalar-TX-k-times-delta", [1200 * delta_ux, 0, 0], [12, 0, 0], 12)
            vector_check("scalar-RX-k-times-delta", [6000 * delta_rx, 0, 0], [6, 0, 0], 6)
            receipt["physical_moving_face_port_motion_from_original_dat_sets"] = motion
            receipt["relative_ux"] = delta_ux
            receipt["relative_rx_radians"] = delta_rx
            write_json(output / "motion-from-stock-dat.json", motion)
            fea.load_results()
            self.assertTrue(fea.results_present)
            results = [item for item in model.analysis.Group if item.isDerivedFrom("Fem::FemResultObject")]
            self.assertTrue(results)
            receipt["fem_result_objects"] = [item.Name for item in results]
            self.assertTrue(report.Status.startswith("Current"), report.Status)
            self.assertEqual(report.AccountingData, native_literal)
            resultants = plain(list(report.Resultants))
            doc.recompute()
            saved = output / "ordinary-supports-native-v3.FCStd"
            doc.saveAs(str(saved))
            self.assertEqual(report.AccountingData, native_literal)
            paths = {"deck": deck, "request": request, "native_output": wire_output,
                     "frd": deck.with_suffix(".frd"), "dat": deck.with_suffix(".dat")}
            cold = {
                "schema": "FreeCAD-ywu-native-cold-case-v1", "document": str(saved), "document_sha256": sha(saved),
                "report_name": report.Name, "analysis_name": model.analysis.Name, "solver_name": model.solver.Name,
                "mesh_name": model.mesh.Name, "accounting_data_literal": native_literal,
                "resultants_literal": resultants, "saved_status_literal": report.Status,
                "movement_source_literal": data["movement_source"], "binary": data["binary"],
                "binary_sha256": sha(data["binary"]),
                "source_files": {name: {"path": str(path), "sha256": sha(path)} for name, path in paths.items()},
                "explicit_supports": [item.Name for item in model.solver.NativeAccountingSupports],
                "saved_references": {item.Name: plain(item.References) for item in model.supports + model.bodies + model.cuts},
                "saved_native_properties": native_properties, "no_cold_restore_performed_yet": True,
                "no_history_or_provenance_repair": True,
            }
            write_json(output / "cold-case.json", cold)
            receipt["cold_manifest"] = str(output / "cold-case.json")
            receipt["cold_manifest_sha256"] = sha(output / "cold-case.json")
            receipt["current_native_report"] = {"name": report.Name, "status": report.Status,
                                                 "schema": data["schema"], "movement_status": data["movement_source"]["status"]}
            receipt["passed"] = True
        except BaseException as error:
            receipt["witness_error"] = {"type": type(error).__name__, "message": str(error),
                                        "traceback": traceback.format_exc()}
            raise
        finally:
            receipt["retained_files"] = {
                str(path.relative_to(output)): {"bytes": path.stat().st_size, "sha256": sha(path)}
                for path in sorted(output.rglob("*")) if path.is_file()}
            write_json(output / "witness-receipt.json", receipt)
            print("YWU_ORDINARY_SUPPORTS_GREEN=" + str(output), flush=True)
            if doc.Name in App.listDocuments():
                App.closeDocument(doc.Name)
