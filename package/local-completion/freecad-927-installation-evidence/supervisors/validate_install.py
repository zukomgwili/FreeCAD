"""FreeCAD-3sc bounded isolated application verification; no install actions.

Required environment: EXPECTED_COMMIT (full Git hash), EXPECTED_REVISION (the
complete App.Version()[3], for example '49114 +176 (Git)').
Usage: python3 validate_install.py APP_PATH LABEL MODE
Modes: fem, cli, create, reopen, features, equilibrium, gui, mixed-create,
mixed-reopen, area-create, area-reopen. Use the same LABEL for each matched
create/reopen pair, which run in separate processes. Run
serially with native CTest and other GUI tests. Existing evidence is retained.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from harness_config import COMMIT, REVISION, REGRESSION_COUNTS


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
REPOSITORY = Path("/Users/zukomgwili/src/FreeCAD")
PINNED_COMMIT = COMMIT
PINNED_REVISION = REVISION
FIXTURE = Path("/Users/zukomgwili/src/oomakhi/artifacts/Fire-Access-Integration/r01/"
               "review/en2-complete-r01/native-fem-owned-regions-r27/runtime/owned.FCStd")
FIXTURE_SHA256 = "fcc5b43e2d0663f0b5222c98d81ffeeec669bad93d8b78d9321951489d377387"
HARNESS = REPOSITORY / "tests/src/Mod/Fem/NativeContactOwnership.py"
MIXED_HARNESS = REPOSITORY / "tests/src/Mod/Part/App/NativeMixedShapeHashers.py"
AREA_HARNESS = REPOSITORY / "tests/src/Mod/BIM/AreaDiagnosticsGui.py"
BROAD_CLI = ["BaseTests", "UnitTests", "Document", "TestArch", "TestDraft", "TestFemApp",
             "TestMaterialsApp",
             "TestPartApp", "TestSpreadsheet", "TestTechDrawApp", "StringHasher",
             "TestSketcherApp", "TestPartDesignApp"]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("application", type=Path)
    parser.add_argument("label")
    parser.add_argument("mode", choices=("fem", "cli", "create", "reopen",
                                       "features", "equilibrium", "gui", "mixed-create",
                                       "mixed-reopen", "area-create", "area-reopen"))
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", args.label):
        parser.error("LABEL must be a simple alphanumeric/hyphen/underscore identifier")
    commit = os.environ["EXPECTED_COMMIT"]
    revision = os.environ["EXPECTED_REVISION"]
    assert commit == PINNED_COMMIT, (commit, PINNED_COMMIT)
    assert revision == PINNED_REVISION, (revision, PINNED_REVISION)
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        parser.error("EXPECTED_COMMIT must be a full lowercase Git hash")
    if not re.fullmatch(r"\d+ \+\d+ \(Git\)", revision):
        parser.error("EXPECTED_REVISION must be the complete '+N (Git)' revision string")
    app = args.application.resolve(strict=True)
    resources = app / "Contents/Resources"
    gui = args.mode in ("create", "reopen", "features", "gui", "mixed-create",
                        "mixed-reopen", "area-create", "area-reopen")
    executable = app / "Contents/MacOS" / ("FreeCAD" if gui else "FreeCADCmd")
    assert app.name.endswith(".app") and resources.is_dir() and executable.is_file()
    evidence = ROOT / f"{args.label}-{args.mode}"
    evidence.mkdir(exist_ok=False)
    identity_path = evidence / "identity.json"
    log_path = evidence / "run.log"
    summary_path = evidence / "summary.json"
    environment = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME", "FREECAD_USER_HOME", "FREECAD_USER_DATA",
                "FREECAD_USER_TEMP", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME",
                "FREECAD_9ZT_CCX", "FREECAD_9ZT_PRODUCTION_CCX",
                "CCX_FORCE_ACCOUNTING_REQUEST", "CCX_9ZT_DIAGNOSTIC"):
        environment.pop(key, None)
    environment.update({
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "OMP_NUM_THREADS": "2",
        "EXPECTED_COMMIT": commit, "EXPECTED_REVISION": revision,
        "EXPECTED_RESOURCES": str(resources), "IDENTITY_REPORT": str(identity_path),
        "FREECAD_USER_HOME": str(evidence / "user"),
        "FREECAD_USER_DATA": str(evidence / "data"),
        "FREECAD_USER_TEMP": str(evidence / "temp"),
        "XDG_CONFIG_HOME": str(evidence / "xdg-config"),
        "XDG_CACHE_HOME": str(evidence / "xdg-cache"),
        "XDG_DATA_HOME": str(evidence / "xdg-data"),
        "TMPDIR": str(evidence / "temp"),
    })
    for path in ("user", "data", "temp", "xdg-config", "xdg-cache", "xdg-data"):
        (evidence / path).mkdir()
    tests = ["InstalledIdentity"]
    scratch_tests = ["NativeContactOwnership", "ElasticConnectorGui",
                     "OrthotropicMaterialGui", "StockSectionEquilibrium",
                     "NativeMixedShapeHashers", "AreaDiagnosticsGui"]
    observer_paths = []
    cold_inputs = {}
    if args.mode == "fem":
        tests += ["TestFemApp"]
    elif args.mode == "cli":
        tests += BROAD_CLI
    elif args.mode == "gui":
        tests += ["TestTechDrawGui", "TestMaterialsGui", "TestFemGui"]
    elif args.mode == "features":
        for key in ("FREECAD_J97_REOPEN", "FREECAD_CTQ_REOPEN", "FREECAD_J97_OUTPUT",
                    "FREECAD_CTQ_OUTPUT", "FREECAD_N1H_OUTPUT"):
            environment.pop(key, None)
        tests += ["ElasticConnectorGui", "OrthotropicMaterialGui"]
    elif args.mode == "equilibrium":
        for key in ("FREECAD_9BP_SECTION_SIZE", "FREECAD_9BP_REOPEN"):
            environment.pop(key, None)
        environment.update({
            "FREECAD_9BP_OUTPUT": str(evidence / "equilibrium"),
            "FREECAD_9BP_COMMIT": commit,
            "FREECAD_9BP_RESOURCES": str(resources),
        })
        tests += ["StockSectionEquilibrium"]
    elif args.mode.startswith("mixed-"):
        stage = args.mode.rsplit("-", 1)[1]
        mixed_directory = ROOT / f"{args.label}-mixed-native"
        for key in ("FREECAD_B9R_INPUT", "FREECAD_B9R_OUTPUT"):
            environment.pop(key, None)
        if stage == "create":
            mixed_directory.mkdir(exist_ok=False)
        else:
            assert not (mixed_directory / "reopen-result.json").exists()
            for name in ("mixed-hashers.FCStd", "expected.json"):
                path = mixed_directory / name
                cold_inputs[str(path)] = digest(path)
        environment.update({
            "FREECAD_B9R_DIRECTORY": str(mixed_directory),
            "FREECAD_B9R_STAGE": stage,
            "FREECAD_B9R_EXPECTED_COMMIT": commit,
        })
        tests += ["NativeMixedShapeHashers"]
        observer_paths += [MIXED_HARNESS]
    elif args.mode.startswith("area-"):
        stage = args.mode.rsplit("-", 1)[1]
        environment.pop("FREECAD_0O1_REOPEN", None)
        environment["FREECAD_0O1_OUTPUT"] = str(evidence / "area")
        if stage == "reopen":
            source = ROOT / f"{args.label}-area-create/area/optional-area.FCStd"
            cold_inputs[str(source)] = digest(source)
            environment["FREECAD_0O1_REOPEN"] = str(source)
        tests += ["AreaDiagnosticsGui"]
        observer_paths += [AREA_HARNESS]
    else:
        assert digest(FIXTURE) == FIXTURE_SHA256
        environment.update({
            "FREECAD_BT9_INPUT": str(FIXTURE),
            "FREECAD_BT9_DIRECTORY": str(ROOT / f"{args.label}-native"),
            "FREECAD_BT9_STAGE": args.mode,
            "FREECAD_BT9_EXPECTED_COMMIT": commit,
            "FREECAD_BT9_EXPECTED_RESOURCES": str(resources),
        })
        tests += ["NativeContactOwnership"]
    environment["CONFIGURED_TEST_SUITES"] = json.dumps(tests)
    environment["SCRATCH_TEST_SUITES"] = json.dumps(scratch_tests)
    command = ["pixi", "run", "--frozen", str(executable),
               "-u", str(evidence / "user.cfg"),
               "-s", str(evidence / "system.cfg"), "-P", str(ROOT)]
    if gui or args.mode == "equilibrium":
        command += ["-P", str(HARNESS.parent)]
    for directory in dict.fromkeys(path.parent for path in observer_paths):
        command += ["-P", str(directory)]
    for test in tests:
        command += ["-t", test]
    timeout = 900 if args.mode == "cli" else 180
    summary = {"application": str(app), "resources": str(resources), "mode": args.mode,
               "expected_commit": commit, "expected_revision": revision,
               "suites": tests, "command": command, "identity_report": str(identity_path),
               "log": str(log_path), "timeout_seconds": timeout, "passed": False,
               "timed_out": False, "process_reaped": False,
               "harness_sha256_before": digest(HARNESS)}
    summary["additional_observer_sha256_before"] = {
        str(path): digest(path) for path in observer_paths}
    summary["cold_inputs_sha256_before"] = cold_inputs
    extra_harnesses = []
    if args.mode in ("features", "equilibrium"):
        extra_harnesses = (["ElasticConnectorGui.py", "OrthotropicMaterialGui.py"]
                           if args.mode == "features" else ["StockSectionEquilibrium.py"])
        summary["extra_harness_sha256_before"] = {
            name: digest(HARNESS.parent / name) for name in extra_harnesses}
    print(json.dumps({"status": "starting", "log": str(log_path),
                      "summary": str(summary_path), "timeout_seconds": timeout,
                      "suites": tests}), flush=True)
    started = time.monotonic()
    try:
        with log_path.open("xb") as output:
            process = subprocess.Popen(command, cwd=REPOSITORY, env=environment,
                                       stdout=output, stderr=subprocess.STDOUT,
                                       start_new_session=True)
            summary["pid"] = process.pid
            try:
                status = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                summary["timed_out"] = True
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
                raise
            finally:
                summary["process_reaped"] = process.poll() is not None
        summary["exit_code"] = status
        assert status == 0, f"Launcher exited {status}; inspect {log_path}"
        log = log_path.read_text(errors="replace")
        counts = re.findall(r"^Ran (\d+) tests? in ([\d.]+)s\s*$", log, re.MULTILINE)
        successes = re.findall(r"^OK(?: \(([^\n]*)\))?\s*$", log, re.MULTILINE)
        assert len(counts) == 1 and len(successes) == 1, "Missing/duplicate unittest result"
        assert not re.search(r"^(?:FAILED\b|FAIL:|ERROR:|UNEXPECTED SUCCESS:)",
                             log, re.MULTILINE), "Unexpected unittest failure"
        count, seconds = counts[0]
        summary["unittest"] = {"run": int(count), "seconds": float(seconds),
                               "outcome": "OK", "details": successes[0]}
        summary["unittest"]["expected_failures"] = re.findall(
            r"^([^\n]+) \.\.\. expected failure\s*$", log, re.MULTILINE)
        summary["unittest"]["skips"] = re.findall(
            r"^([^\n]+) \.\.\. skipped ([^\n]+)$", log, re.MULTILINE)
        identity = json.loads(identity_path.read_text())
        assert identity["passed"] and identity["runtime"][-1] == commit
        assert identity["runtime"][3] == revision
        assert identity["root"] == str(resources)
        assert bool(identity["gui_up"]) == gui
        for key, required in REGRESSION_COUNTS.items():
            assert len(identity["regressions_discovered"][key]) == required
        expected_count = identity["configured_test_count"]
        assert int(count) == expected_count, (count, expected_count)
        summary["configured_suite_counts"] = identity["configured_suite_counts"]
        if args.mode in ("features", "equilibrium", "create", "reopen", "mixed-create",
                         "mixed-reopen", "area-create", "area-reopen"):
            assert not successes[0], "Acceptance witnesses must not skip/expect failures"
        if args.mode == "equilibrium":
            equilibrium_path = evidence / "equilibrium/report.json"
            equilibrium = json.loads(equilibrium_path.read_text())
            assert equilibrium["runtime"][-1] == commit
            assert not equilibrium["gui_up"]
            assert equilibrium["stock_setup_unmodified"] and equilibrium["shipped_mesh"]
            assert equilibrium["section_size_mm"] == 1.25
            assert equilibrium["volume_elements"] == 24001
            assert not equilibrium["cold_reopened"]
            assert not equilibrium["solver_test_mode"]
            assert not equilibrium["building_design_accepted"]
            assert equilibrium["example_relative_tolerance"] == 0.01
            for key in ("relative_force_residual", "relative_origin_moment_residual",
                        "relative_centroid_moment_residual"):
                assert 0 <= equilibrium[key] < 0.01, (key, equilibrium[key])
            for path in equilibrium["loaded_modules"].values():
                assert Path(path).resolve().is_relative_to(resources), path
            raw_dat = evidence / "equilibrium/solver/Mesh.dat"
            assert raw_dat.read_text() == equilibrium["raw_solver_dat"]
            summary["equilibrium_report"] = str(equilibrium_path)
            summary["equilibrium_residuals"] = {
                key: equilibrium[key] for key in ("relative_force_residual",
                                                 "relative_origin_moment_residual",
                                                 "relative_centroid_moment_residual")}
        elif args.mode in ("create", "reopen"):
            native_path = ROOT / f"{args.label}-native" / f"{args.mode}-result.json"
            native = json.loads(native_path.read_text())
            assert native["passed"] and native["semantic_contact_pass"], native.get("error")
            assert native["runtime"][-1] == commit
            assert Path(native["home"]).resolve() == resources
            assert native["source_unchanged"] and native["copied_input_unchanged"]
            assert native["cold_input_unchanged"] and not native["cleanup_errors"]
            assert int(count) == 2
            summary["native_report"] = str(native_path)
            assert digest(FIXTURE) == FIXTURE_SHA256
        elif args.mode.startswith("mixed-"):
            native_path = mixed_directory / f"{stage}-result.json"
            native = json.loads(native_path.read_text())
            assert native["passed"], native.get("error")
            assert native["version"][-1] == commit
            assert Path(native["home"]).resolve() == resources
            assert native["stage"] == stage and native["gui_up"]
            for key in ("part_module", "helper_module"):
                assert Path(native[key]).resolve().is_relative_to(resources), native[key]
            helper = REPOSITORY / "src/Mod/Part/parttests/TestMixedShapeHashers.py"
            assert digest(native["helper_module"]) == digest(helper)
            assert native["direct_semantic_control"]["physical_provenance_matches_shared_owner"]
            assert native["render_checks"]
            assert all(check["blue_samples"] > 100 for check in native["render_checks"])
            labels = {snapshot["label"] for snapshot in native["snapshots"]}
            if stage == "reopen":
                assert {"cold-reopen-before-recompute", "cold-forced-recompute",
                        "successor-reopen-before-recompute", "successor-forced-recompute"} <= labels
                assert native["input_sha256"] == cold_inputs[native["input"]]
            assert all(not shape["save_all"] for snapshot in native["snapshots"]
                       for shape in snapshot["shapes"].values())
            summary["native_report"] = str(native_path)
        elif args.mode.startswith("area-"):
            area_path = evidence / "area/report.json"
            area = json.loads(area_path.read_text())
            assert area["version"][-1] == commit
            assert Path(area["module"]).resolve().is_relative_to(resources)
            assert bool(area["cold_process"]) == (stage == "reopen")
            assert not area["area_quantities_unavailable"]
            assert not area["building_or_quantity_acceptance"]
            assert len(area["volumes_mm3"]) == 2 and all(v > 0 for v in area["volumes_mm3"])
            assert area["horizontal_area_mm2"] > 0 and area["outer_perimeter_mm"] > 0
            assert area["fixture_numerical_area_budget_mm2"] == 1e-3
            assert abs(area["horizontal_area_mm2"]
                       - area["native_volume_per_height_mm2"]) < 1e-3
            assert all("Invalid" not in state for key in ("covering_state", "union_state")
                       for state in area[key])
            summary["native_report"] = str(area_path)
        elif args.mode in ("fem", "cli"):
            for discovered in identity["regressions_discovered"].values():
                for test_id in discovered:
                    name = test_id.rsplit(".", 1)[-1]
                    assert re.search(r"^" + re.escape(name) + r" \(", log, re.MULTILINE), name
                    assert not re.search(r"^" + re.escape(name) + r" \([^\n]*skipped",
                                         log, re.MULTILINE), name
        if args.mode == "gui":
            self_ids = identity["gui_observation_regressions_discovered"]
            assert len(self_ids) == 4
            for test_id in self_ids:
                name = test_id.rsplit(".", 1)[-1]
                assert re.search(r"^" + re.escape(name) + r" \(", log, re.MULTILINE), name
                assert not re.search(r"^" + re.escape(name) + r" \([^\n]*skipped",
                                     log, re.MULTILINE), name
            assert identity["configured_suite_counts"]["TestFemGui"] == 7
        summary["harness_sha256_after"] = digest(HARNESS)
        assert summary["harness_sha256_before"] == summary["harness_sha256_after"]
        summary["additional_observer_sha256_after"] = {
            str(path): digest(path) for path in observer_paths}
        assert (summary["additional_observer_sha256_before"]
                == summary["additional_observer_sha256_after"])
        summary["cold_inputs_sha256_after"] = {path: digest(path) for path in cold_inputs}
        assert summary["cold_inputs_sha256_before"] == summary["cold_inputs_sha256_after"]
        if extra_harnesses:
            summary["extra_harness_sha256_after"] = {
                name: digest(HARNESS.parent / name) for name in extra_harnesses}
            assert (summary["extra_harness_sha256_before"]
                    == summary["extra_harness_sha256_after"])
        summary["passed"] = True
    except BaseException as error:
        summary["error"] = repr(error)
        raise
    finally:
        summary["elapsed_seconds"] = round(time.monotonic() - started, 3)
        with summary_path.open("x") as handle:
            handle.write(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
