"""One real stock-deck comparison of previous and candidate native mechanics.

Export-precision comparison only. This does not change the independent fixed
equilibrium tolerances or establish engineering acceptance.
"""

import sys

sys.dont_write_bytecode = True

import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import unittest

import FreeCAD as App
from feminout.importCcxFrdResults import read_frd_result
from femtools import force_accounting
from femtools.ccxtools import FemToolsCcx

ROOT = Path("/private/tmp/freecad-e4k-tsd27fAG")
FIXTURE = Path(
    "/Users/zukomgwili/src/FreeCAD/src/Mod/Fem/femtest/app/test_staged_selfweight_native.py"
)
BASELINE = Path(
    "/Users/zukomgwili/src/FreeCAD/build/native-solvers/"
    "beam-network-b6a356e8635a/ccx-force-accounting"
)
BASELINE_SHA = "b6a356e8635a35cef2621db7bd80145566dc1f671683edb405ab927cb415b353"
# Frozen before either native run. The 1e-6 relative budgets reflect FRD's
# seven-digit fields. The absolute near-zero budgets retain the physical units.
BUDGETS = {
    "disp": {"unit": "mm", "absolute": 1e-10, "relative": 1e-6},
    "stress": {"unit": "MPa", "absolute": 1e-9, "relative": 1e-6},
    "strain": {"unit": "strain", "absolute": 1e-15, "relative": 1e-6},
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def plain(value):
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return [plain(item) for item in value]


class TestMechanicalE4k(unittest.TestCase):
    def test_previous_and_candidate_keep_ordinary_U_S_E_on_the_identical_stock_step_deck(self):
        self.assertTrue(BASELINE.is_file())
        self.assertEqual(sha(BASELINE), BASELINE_SHA)
        spec = importlib.util.spec_from_file_location("e4k_mechanical_fixture", FIXTURE)
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        case = fixture.TestStagedSelfweightNative(methodName="runTest")
        case.setUp()
        self.addCleanup(case.tearDown)
        model = case.make_case()
        model.solver.NativeForceAccounting = False
        model.lower.NativeEquilibriumCut = False
        model.upper.NativeEquilibriumCut = False
        model.solver.TimePeriod = "1 s"
        self.assertEqual(model.solver.StaticStepAmplitude, "Step")
        self.assertEqual(list(model.solver.NativeContactOutputs), [model.contact])
        self.assertEqual(list(model.load.AmplitudeValues), fixture.HISTORY)
        for key in ("CCX_FORCE_ACCOUNTING_REQUEST", "CCX_BEAM_SECTION_REQUEST"):
            self.assertNotIn(key, os.environ)
        # These are documented native worker controls, not result substitutions.
        keys = ("CCX_NPROC_RESULTS", "CCX_NPROC_STIFFNESS", "CCX_NPROC_EQUATION_SOLVER")
        previous = {key: os.environ.get(key) for key in keys}

        def restore_workers():
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.addCleanup(restore_workers)
        for key in keys:
            os.environ[key] = "1"

        report = {
            "schema": "FreeCAD-e4k-native-mechanical-preservation-v1",
            "passed": False,
            "fixture": str(FIXTURE),
            "fixture_sha256": sha(FIXTURE),
            "helper_sha256": sha(__file__),
            "budgets_frozen_before_runs": BUDGETS,
            "one_authoring_and_mesh_for_both_runs": True,
            "native_accounting_enabled": False,
            "native_equilibrium_cuts_enabled": False,
            "native_contact_diagnostics_enabled": True,
            "mechanical_solver_controls": {key: os.environ[key] for key in keys},
            "engineering_equilibrium_tolerance_changed": False,
            "manual_deck_changes": False,
            "deck_comparison_metadata_exclusion": "Exactly one stock write_footer.py line "
            "beginning '**   written on    --> '; all remaining deck bytes must match. "
            "Executed raw decks remain unedited and separately hashed.",
            "engineering_acceptance": False,
            "runs": {},
        }
        fields = {}
        decks = {}
        for label, selection in (("previous-b6", str(BASELINE)), ("candidate-default", "")):
            with self.subTest(binary=label):
                directory = case.root / label
                directory.mkdir()
                model.solver.NativeAccountingSolver = selection
                case.doc.recompute()
                binary = Path(force_accounting.solver_binary(model.solver)).resolve(strict=True)
                if label == "previous-b6":
                    self.assertEqual(binary, BASELINE)
                else:
                    self.assertNotEqual(sha(binary), BASELINE_SHA)
                    self.assertEqual(model.solver.NativeAccountingSolver, "")
                fea = FemToolsCcx(analysis=model.analysis, solver=model.solver)
                fea.update_objects()
                fea.setup_working_dir(str(directory))
                self.assertFalse(fea.write_inp_file())
                path = Path(fea.inp_file_name)
                decks[label] = path.read_bytes()
                self.assertIn(b"*STEP, INC=2000, AMPLITUDE=STEP\n", decks[label])
                self.assertIn(b"Eall,GRAV,9806.65,0,0,-1\n", decks[label])
                self.assertIn("\n".join(fixture.HISTORY).encode(), decks[label])
                deck_before = sha(path)
                returncode = fea.ccx_run()
                (directory / "solver.stdout").write_text(fea.ccx_stdout)
                (directory / "solver.stderr").write_text(fea.ccx_stderr)
                receipt = {
                    "selection": selection,
                    "default_candidate_selected": selection == "",
                    "binary": str(binary),
                    "binary_sha256": sha(binary),
                    "deck": str(path),
                    "deck_sha256": deck_before,
                    "returncode": returncode,
                    "deck_unchanged": sha(path) == deck_before,
                    "stdout_sha256": sha(directory / "solver.stdout"),
                    "stderr_sha256": sha(directory / "solver.stderr"),
                }
                (directory / "solver-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
                self.assertEqual(returncode, 0, fea.ccx_stdout + fea.ccx_stderr)
                self.assertTrue(receipt["deck_unchanged"])
                self.assertEqual(Path(fea.ccx_binary).resolve(strict=True), binary)
                for suffix in (".frd", ".dat"):
                    output = path.with_suffix(suffix)
                    self.assertTrue(output.is_file())
                    receipt[suffix[1:] + "_sha256"] = sha(output)
                self.assertFalse(path.with_suffix(".accounting.out").exists())
                fea.load_results()
                self.assertTrue(
                    any(obj.isDerivedFrom("Fem::FemResultObject") for obj in model.analysis.Group)
                )
                contact = [
                    obj
                    for obj in model.analysis.Group
                    if getattr(getattr(obj, "Proxy", None), "Type", "") == "Fem::ContactStateResult"
                    and obj.Status.startswith("Current")
                ]
                self.assertEqual(len(contact), 1)
                observed = contact[0].Proxy.getContactStates(contact[0])
                self.assertAlmostEqual(observed["frames"][-1]["time"], 1.0, delta=1e-10)
                parsed = read_frd_result(str(path.with_suffix(".frd")))
                fields[label] = parsed
                receipt["native_mechanical_import_performed"] = True
                receipt["parsed_result_frames"] = len(parsed["Results"])
                report["runs"][label] = receipt
                (directory / "solver-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
                data = {
                    "time": [row["time"] for row in parsed["Results"]],
                    "fields": [
                        {key: plain(row[key]) for key in BUDGETS} for row in parsed["Results"]
                    ],
                }
                (directory / "ordinary-native-fields.json").write_text(
                    json.dumps(data, indent=2, allow_nan=False) + "\n"
                )

        self.assertEqual(set(fields), {"previous-b6", "candidate-default"})

        def without_timestamp(literal):
            lines = literal.splitlines(keepends=True)
            removed = [line for line in lines if line.startswith(b"**   written on    --> ")]
            self.assertEqual(len(removed), 1)
            return b"".join(line for line in lines if line not in removed)

        normalized = {label: without_timestamp(data) for label, data in decks.items()}
        self.assertEqual(normalized["previous-b6"], normalized["candidate-default"])
        report["stock_decks_raw_byte_equal"] = decks["previous-b6"] == decks["candidate-default"]
        report["stock_decks_equal_except_one_generated_timestamp_comment"] = True
        report["timestamp_excluded_deck_sha256"] = hashlib.sha256(
            normalized["previous-b6"]
        ).hexdigest()
        original, candidate = fields["previous-b6"], fields["candidate-default"]
        self.assertEqual(set(original), set(candidate))
        mesh_keys = set(original) - {"Results"}
        for key in sorted(mesh_keys):
            self.assertEqual(plain(original[key]), plain(candidate[key]), key)
        report["parsed_native_mesh_exactly_equal"] = True
        self.assertEqual(len(original["Results"]), len(candidate["Results"]))
        self.assertGreater(len(original["Results"]), 1)
        failures = []
        comparisons = []
        for index, (first, second) in enumerate(zip(original["Results"], candidate["Results"])):
            self.assertEqual(first["time"], second["time"])
            frame = {"frame": index, "time": first["time"], "channels": {}}
            for key, budget in BUDGETS.items():
                self.assertIn(key, first)
                self.assertIn(key, second)
                self.assertTrue(first[key], (index, key))
                self.assertEqual(set(first[key]), set(second[key]))
                compared, exact, maximum, worst_ratio, worst = 0, True, 0.0, 0.0, None
                for node in sorted(first[key]):
                    a, b = tuple(first[key][node]), tuple(second[key][node])
                    self.assertEqual(len(a), len(b))
                    for component, (reference, value) in enumerate(zip(a, b)):
                        self.assertTrue(math.isfinite(reference) and math.isfinite(value))
                        difference = abs(value - reference)
                        allowed = max(budget["absolute"], budget["relative"] * abs(reference))
                        ratio = difference / allowed
                        compared += 1
                        exact = exact and value == reference
                        maximum = max(maximum, difference)
                        if worst is None or ratio > worst_ratio:
                            worst_ratio = ratio
                            worst = {
                                "native_node": node,
                                "component": component,
                                "baseline": reference,
                                "candidate": value,
                                "absolute_difference": difference,
                                "allowed": allowed,
                            }
                        if difference > allowed:
                            failures.append(
                                {
                                    "frame": index,
                                    "channel": key,
                                    "native_node": node,
                                    "component": component,
                                    "baseline": reference,
                                    "candidate": value,
                                    "absolute_difference": difference,
                                    "allowed": allowed,
                                }
                            )
                frame["channels"][key] = {
                    "components": compared,
                    "exactly_equal": exact,
                    "maximum_absolute_difference": maximum,
                    "worst_budget_ratio": worst_ratio,
                    "worst": worst,
                }
            comparisons.append(frame)
        report["comparisons"] = comparisons
        report["failures"] = failures
        report["passed"] = not failures
        report["parsed_U_S_E_exactly_equal"] = all(
            channel["exactly_equal"]
            for frame in comparisons
            for channel in frame["channels"].values()
        )
        destination = Path(os.environ["E4K_RUN"]) / "mechanical-preservation.json"
        destination.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        self.assertFalse(failures, json.dumps(failures[:5], indent=2))


def suite():
    return unittest.defaultTestLoader.loadTestsFromTestCase(TestMechanicalE4k)
