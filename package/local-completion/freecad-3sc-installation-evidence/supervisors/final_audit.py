"""Read-only post-install 3sc audit; run only after both locations' gates finish.

Writes one new private report. Historical stage module paths are checked
against the sealed-stage inventory and the renamed installed app; the former
stage directory is never expected to exist after the reversible swap.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
S = runpy.run_path(str(ROOT / "stage_install.py"))
APP, STAGE, BACKUP = S["APP"], S["STAGE"], S["BACKUP"]
COMMIT, REVISION = S["COMMIT"], S["REVISION"]
digest, inventory = S["digest"], S["inventory"]
from harness_config import (
    FEM_TEST_COUNT, MATERIAL_APP_TEST_COUNT, MATERIAL_GUI_TEST_COUNT,
    OLD_COMMIT, OLD_REVISION, OLD_NATIVE_SHA256, REGRESSION_COUNTS,
)

assert COMMIT == "5591e8e388bf3506450cb407f784b89064804ddc"
assert REVISION == "49261 +205 (Git)"
BASELINE = json.loads((ROOT / "baseline-inventory.json").read_text())
SEALED = json.loads((ROOT / "stage-inventory.json").read_text())
RESOURCES = APP / "Contents/Resources"
RECEIPT_HASHES = {}


def read(path):
    path = Path(path)
    result = json.loads(path.read_text())
    RECEIPT_HASHES[str(path)] = digest(path)
    return result


def mapped(path):
    path = Path(path)
    if path.is_relative_to(STAGE):
        return APP / path.relative_to(STAGE)
    return path


def bind_file(path, required):
    """Bind a historical stage file without reading its vanished old path."""
    path = Path(path)
    if path.is_relative_to(STAGE):
        relative = str(path.relative_to(STAGE))
        assert SEALED[relative]["kind"] == "file", path
        assert SEALED[relative]["sha256"] == required, path
    actual = mapped(path)
    assert actual.is_file() and digest(actual) == required, actual
    return actual


def equal_hash_maps(before, after):
    assert before == after
    for path, required in before.items():
        bind_file(path, required)


def normal_log(path, tests, outcome=None):
    path = Path(path)
    text = path.read_text(errors="replace")
    assert re.findall(r"^Ran (\d+) tests? in ", text, re.M) == [str(tests)], path
    summaries = re.findall(r"^OK(?: \(([^\n]*)\))?\s*$", text, re.M)
    assert len(summaries) == 1, path
    if outcome is not None:
        assert summaries == [outcome], path
    assert not re.search(r"^(?:FAILED\b|FAIL:|ERROR:|UNEXPECTED SUCCESS:)", text, re.M), path
    RECEIPT_HASHES[str(path)] = digest(path)


def application_for(label):
    return STAGE if label == "stage" else APP


def identity(path, label, gui=None):
    proof = read(path)
    root = application_for(label) / "Contents/Resources"
    assert proof["passed"]
    assert proof["runtime"][-1] == proof["expected_commit"] == COMMIT
    assert proof["runtime"][3] == proof["expected_revision"] == REVISION
    assert Path(proof["root"]) == root
    if gui is not None:
        assert bool(proof["gui_up"]) == gui
    assert proof["TestFemApp_count"] == FEM_TEST_COUNT
    for key, count in REGRESSION_COUNTS.items():
        assert len(proof["regressions_discovered"][key]) == count
    assert proof["configured_test_count"] == sum(proof["configured_suite_counts"].values())
    for module, path_string in proof["modules"].items():
        path = Path(path_string)
        assert path.is_relative_to(root), path
        bind_file(path, proof["module_sha256"][module])
    material_images = proof["loaded_material_images"]
    expected_names = {"Materials.so", "MatGui.so"} if proof["gui_up"] else {"Materials.so"}
    assert {Path(row["path"]).name for row in material_images} == expected_names
    assert len(material_images) == len(expected_names)
    for row in material_images:
        assert Path(row["path"]).parent == root / "lib"
        bind_file(row["path"], row["sha256"])
    for name, required in (("TestMaterialsApp", MATERIAL_APP_TEST_COUNT),
                           ("TestMaterialsGui", MATERIAL_GUI_TEST_COUNT)):
        if name in proof["configured_suite_counts"]:
            assert proof["configured_suite_counts"][name] == required
    if proof["gui_up"]:
        assert Path(proof["cocoa_plugin"]) == S["PREFIX"] / "lib/qt6/plugins/platforms/libqcocoa.dylib"
        bind_file(proof["cocoa_plugin"], proof["cocoa_sha256"])
    return proof


def generic_gates(label):
    app = application_for(label)
    sequence = read(ROOT / f"{label}-sequence-result.json")
    assert sequence["passed"] and Path(sequence["application"]) == app
    assert len(sequence["gates"]) == 10
    assert {row["mode"] for row in sequence["gates"]} == set(S["GATES"])
    equal_hash_maps(sequence["runner_sha256_before"], sequence["runner_sha256_after"])
    counts = {}
    for mode in S["GATES"]:
        directory = ROOT / f"{label}-{mode}"
        summary = read(directory / "summary.json")
        assert summary["passed"] and summary["exit_code"] == 0
        assert summary["process_reaped"] and not summary["timed_out"]
        assert summary["expected_commit"] == COMMIT and summary["expected_revision"] == REVISION
        assert Path(summary["application"]) == app
        proof = identity(directory / "identity.json", label)
        count = proof["configured_test_count"]
        assert summary["unittest"]["run"] == count
        assert summary["unittest"]["outcome"] == "OK"
        assert summary["configured_suite_counts"] == proof["configured_suite_counts"]
        if mode == "cli":
            assert proof["configured_suite_counts"]["TestMaterialsApp"] == MATERIAL_APP_TEST_COUNT
        if mode == "gui":
            assert proof["configured_suite_counts"]["TestMaterialsGui"] == MATERIAL_GUI_TEST_COUNT
        normal_log(directory / "run.log", count)
        assert summary["harness_sha256_before"] == summary["harness_sha256_after"]
        harness = S["REPO"] / "tests/src/Mod/Fem/NativeContactOwnership.py"
        bind_file(harness, summary["harness_sha256_before"])
        equal_hash_maps(summary["additional_observer_sha256_before"],
                        summary["additional_observer_sha256_after"])
        equal_hash_maps(summary["cold_inputs_sha256_before"], summary["cold_inputs_sha256_after"])
        if "extra_harness_sha256_before" in summary:
            assert summary["extra_harness_sha256_before"] == summary["extra_harness_sha256_after"]
            for name, required in summary["extra_harness_sha256_before"].items():
                assert Path(name).name == name
                bind_file(harness.parent / name, required)
        for key in ("native_report", "equilibrium_report"):
            if key in summary:
                product = read(summary[key])
                # Some existing diagnostic contracts express success through
                # specific fields, not a universal top-level passed flag.
                if "passed" in product:
                    assert product["passed"]
        counts[mode] = {"tests": count, "seconds": summary["unittest"]["seconds"]}
    exit_path = ROOT / f"{label}-exit-status/summary.json"
    assert sequence["exit_status_report"] == str(exit_path)
    status = read(exit_path)
    assert status["passed"] and status["app_inventory_unchanged"]
    assert status["expected_commit"] == COMMIT and status["expected_revision"] == REVISION
    assert Path(status["application"]) == app
    for name, path in (("driver", S["EXIT_DRIVER"]), ("fixture", S["EXIT_FIXTURE"])):
        assert status[f"{name}_sha256_before"] == status[f"{name}_sha256_after"]
        bind_file(path, status[f"{name}_sha256_before"])
    assert {row["mode"] for row in status["gates"]} == {"cmd", "gui"}
    assert len(status["gates"]) == 2
    for gate in status["gates"]:
        assert gate["passed"] and gate["exit_code"] == 0
        assert gate["process_reaped"] and not gate["timed_out"]
        assert gate["tests_run"] == 15 and gate["timeout_seconds"] == 510
        assert gate["skipped"] == (4 if gate["mode"] == "cmd" else 0)
        normal_log(gate["log"], 15, "skipped=4" if gate["mode"] == "cmd" else "")
    return {"passed": True, "gates": counts, "exit_status_cmd_gui": True,
            "elapsed_seconds": sequence["elapsed_seconds"]}


def native_gates(label):
    app = application_for(label)
    result = {}
    for mode in ("cmd", "gui"):
        for family, witness in (("native", "FreeCAD9ztProductionWitness"),
                                ("4jb", "FreeCAD4jbWitness")):
            directory = ROOT / f"{label}-{family}-{mode}"
            summary = read(directory / "summary.json")
            assert summary["passed"] and summary["exit_code"] == 0
            assert summary["process_reaped"] and not summary["timed_out"]
            assert summary["expected_commit"] == COMMIT and summary["expected_revision"] == REVISION
            assert Path(summary["application"]) == app
            assert summary["native_binary_sha256"] == OLD_NATIVE_SHA256
            observer = S["REPO"] / "package/local-completion" / f"{witness}.py"
            assert summary["observer_sha256"] == digest(observer)
            proof = identity(directory / "identity.json", label, mode == "gui")
            assert proof["configured_suite_counts"] == {"InstalledIdentity": 1, witness: 1}
            assert proof["configured_test_count"] == 2
            normal_log(directory / "run.log", 2, "")
            if family == "native":
                receipt = read(summary["pipeline_receipt"])
                assert Path(receipt["binary"]) == app / "Contents/Resources/data/NativeSolvers/ccx-force-accounting"
                assert receipt["binary_sha256"] == OLD_NATIVE_SHA256
            else:
                assert summary["witness_tests"] == 1 and summary["unittest_tests"] == 2
            result[f"{family}-{mode}"] = {"passed": True, "seconds": summary["elapsed_seconds"]}
    analytic = read(ROOT / f"{label}-native-analytic/qualification.json")
    assert analytic["passed"] and len(analytic["analytic_cases"]) == 48
    assert Path(analytic["binary"]) == app / "Contents/Resources/data/NativeSolvers/ccx-force-accounting"
    assert analytic["binary_sha256"] == OLD_NATIVE_SHA256
    assert len(analytic["rejections"]) == 6
    assert {row["case"] for row in analytic["rejections"]} == {
        "nlgeom", "missing-cut-node", "duplicate-support", "oversized-integer", "cut-point-load", "cut-mpc"}
    assert all(row["exit_code"] == 201 and row["diagnostic"].startswith("*ERROR CCX force accounting V1:")
               for row in analytic["rejections"])
    assert not analytic["original_project_replayed"] and not analytic["design_accepted"]
    disjoint = read(ROOT / f"{label}-native-disjoint/qualification.json")
    assert disjoint["passed"]
    result.update(analytic_cases=48, rejections=6, disjoint_passed=True)
    return result


def typed_gates(label):
    app = application_for(label)
    work = ROOT / "typed" / label
    manifest = read(work / "runtime.json")
    assert manifest["commit"] == COMMIT and manifest["revision"] == REVISION
    assert manifest["phase"] == label and Path(manifest["application"]) == app
    for path, required in manifest["protected_sha256"].items():
        bind_file(path, required)
    for path in manifest["module_paths"].values():
        assert Path(path).is_relative_to(app / "Contents/Resources")
    gui_dir = ROOT / "typed" / f"{label}-3sc-gui"
    cold_dir = ROOT / "typed" / f"{label}-3sc-cold"
    native_reports = {}
    for mode, directory, filename in (("gui", gui_dir, "green-witness.json"),
                                       ("cold", cold_dir, "cold-restore-report.json")):
        execution = read(directory / "execution.json")
        native_path = directory / filename
        native = read(native_path)
        assert execution["verdict"] == native["verdict"] == "PASS"
        assert execution["passed"] and execution["normal_test_pass"]
        assert execution["expected_commit"] == COMMIT and execution["expected_revision"] == REVISION
        assert Path(execution["application"]) == app
        assert execution["exit_code"] == 0 and execution["process_reaped"] and not execution["timed_out"]
        assert execution["native_witness_sha256"] == digest(native_path)
        assert execution["runtime_manifest_sha256"] == digest(work / "runtime.json")
        assert native["runtime"][-1] == COMMIT and native["runtime"][3] == REVISION
        equal_hash_maps(execution["protected_sha256_before"], execution["protected_sha256_after"])
        assert execution["supervisor_sha256_before"] == execution["supervisor_sha256_after"]
        equal_hash_maps(native["protected_sha256_before"], native["protected_sha256_after"])
        module = native["Materials_module"]
        assert Path(module["path"]) == app / "Contents/Resources/lib/Materials.so"
        bind_file(module["path"], module["sha256"])
        images = native.get("loaded_material_images_after_bridge_gui", native["loaded_material_images"])
        materials = [row for row in images if Path(row["path"]).name == "Materials.so"]
        assert len(materials) == 1 and materials[0]["path"] == module["path"]
        for row in images:
            assert Path(row["path"]).is_relative_to(app / "Contents/Resources")
            bind_file(row["path"], row["sha256"])
        for key in ("runtime_identity_start", "runtime_identity_final"):
            runtime = native[key]
            assert Path(runtime["application"]) == app and runtime["phase"] == label
            assert runtime["version"][-1] == COMMIT and runtime["version"][3] == REVISION
            assert runtime["manifest_sha256"] == digest(work / "runtime.json")
            for row in runtime["module_images"]:
                assert Path(row["path"]).is_relative_to(app / "Contents/Resources")
                bind_file(row["path"], row["sha256"])
        normal_log(directory / "run.log", 1, "")
        native_reports[mode] = native
    gui, cold = native_reports["gui"], native_reports["cold"]
    persistence = gui["persistence"]
    assert persistence["verdict"] == "PASS"
    for key in ("public_manager_save_refresh_exact", "same_process_fcstd_uuid_library_restore_exact",
                "same_process_fem_hashes_exact"):
        assert persistence[key]
    equal_hash_maps(persistence["producer_sha256_before"], persistence["producer_sha256_after"])
    assert gui["readonly_copies"] >= 64 and gui["fem_hash_read_repeatability"]
    assert len(gui["mutations"]) == 2
    previous = gui["initial_fem_hashes"]
    for mutation in gui["mutations"]:
        for key in ("model_digest", "quality_input_fingerprint"):
            assert mutation["hashes"][key] != previous[key]
        previous = mutation["hashes"]
    for key in ("user_library", "user_app_data_dir"):
        path = Path(persistence["actual_scope"][key]).resolve()
        assert path != gui_dir.resolve() and path.is_relative_to(gui_dir.resolve())
    expected_path = gui_dir / "cold-restore-expected.json"
    expected = read(expected_path)
    assert cold["expected_receipt_sha256"] == digest(expected_path)
    assert set(cold["cases"]) == {"gui_material", "public_api_null_material"}
    for name in cold["cases"]:
        case = expected[name]
        assert cold["cases"][name]["exact_material_identity"]
        assert cold["cases"][name]["uuid"] == case["uuid"]
        for file_key in ("card", "document"):
            path = Path(case[file_key]).resolve()
            assert path.is_relative_to(gui_dir.resolve())
            bind_file(path, case[file_key + "_sha256"])
    equal_hash_maps(expected["producer_sha256"], persistence["producer_sha256_after"])
    for path in (gui_dir / "native-array-green.png", gui_dir / "native-material-editor-green.png"):
        assert path.is_file() and path.stat().st_size > 10000
        RECEIPT_HASHES[str(path)] = digest(path)
    return {"passed": True, "native_gui_producer": True, "separate_cmd_cold_restore": True,
            "exact_full_material_and_fem_identities": True, "retained_initial_copies": gui["readonly_copies"],
            "genuine_float_mutations": 2, "null_fixture_origin": persistence["null_fixture_origin"],
            "fcstd_semantics": persistence["fcstd_semantics"]}


def main():
    assert not STAGE.exists() and not STAGE.is_symlink(), "Audit only after the actual replacement"
    assert APP.is_dir() and BACKUP.is_dir() and not APP.is_symlink() and not BACKUP.is_symlink()
    assert inventory(APP) == SEALED and inventory(BACKUP) == BASELINE
    S["compiled_identity"]()
    original_note = (BACKUP / "Contents/Resources/LOCAL-INSTALL.txt").read_text()
    assert OLD_COMMIT in original_note and OLD_REVISION.replace(" +", "+") in original_note
    new_note = (RESOURCES / "LOCAL-INSTALL.txt").read_text()
    assert COMMIT in new_note and REVISION.replace(" +", "+") in new_note and "FreeCAD-3sc" in new_note
    for app in (APP, BACKUP):
        S["verify"](app)
        for name in S["EXTENSIONS"]:
            assert S["entitlements"](app / "Contents/Resources/PlugIns" / name) == S["plistlib"].loads(
                (ROOT / (name + ".plist")).read_bytes())
    assert not list(RESOURCES.rglob("*.pyc")) and not list(RESOURCES.rglob("__pycache__"))
    assert all(row["kind"] == "link" or not row["mode"] & 0o222 for row in inventory(RESOURCES).values())
    for source, target in S["SOURCES"].items():
        actual = RESOURCES / target
        assert actual.is_file() and not actual.is_symlink()
        assert actual.read_bytes() == (S["REPO"] / source).read_bytes(), source
    parity = S["material_native_parity"](RESOURCES)
    original_parity = read(ROOT / "stage-material-native-parity.json")
    assert original_parity["passed"] and original_parity["compiled_commit"] == COMMIT
    for name in parity["modules"]:
        old = original_parity["modules"][name]
        current = parity["modules"][name]
        assert old["application"]["normalized"] == current["application"]["normalized"]
        assert old["application"]["sha256"] == current["application"]["sha256"]
    assert digest(RESOURCES / "data/NativeSolvers/ccx-force-accounting") == OLD_NATIVE_SHA256
    assert digest(BACKUP / "Contents/Resources/data/NativeSolvers/ccx-force-accounting") == OLD_NATIVE_SHA256
    assert S["native_code_id"](RESOURCES / "data/NativeSolvers/ccx-force-accounting") == S["NATIVE_CODE_ID"]
    assert (APP / "Contents/MacOS/FreeCAD").read_bytes()[:34240] == (BACKUP / "Contents/MacOS/FreeCAD").read_bytes()[:34240]
    assert (APP / "Contents/MacOS/FreeCADCmd").read_bytes() == (BACKUP / "Contents/MacOS/FreeCADCmd").read_bytes()
    S["check_namespace"](read(ROOT / "namespace-plan.json"))
    profiles = read(ROOT / "profile-inventories.json")
    for path, expected in profiles.items():
        assert inventory(Path(path)) == expected, path
    expected_pins = {
        "pixi.toml": "119ea10b858e6926f16a014b3245b3f301a3624500bf6b5b8c6c98010c55352b",
        "pixi.lock": "730693309df0ef3afd2c35ea7becf1dc4cd097bfd4b287a459449ca1a1b81ad7",
        ".pixi/envs/default/lib/qt6/plugins/platforms/libqcocoa.dylib": "b5929d48bec6a97ce61f6792a866daf5c3ea6badb9d58d98bc0eeaf75ed3e704",
        ".pixi/envs/default/bin/ccx": S["ORDINARY_CCX_SHA256"],
    }
    for relative, required in expected_pins.items():
        assert digest(S["REPO"] / relative) == required
    payload_audit = read(ROOT / "independent-payload-audit.json")
    stage_audit = read(ROOT / "independent-stage-audit.json")
    custody_audit = read(ROOT / "independent-stage-custody.json")
    assert payload_audit["passed"] and payload_audit["commit"] == COMMIT
    assert stage_audit["passed"] and stage_audit["source_commit"] == COMMIT
    assert custody_audit["passed"] and custody_audit["compiled_commit"] == COMMIT
    assert stage_audit["native_payload_parity_count"] == payload_audit["payload_native_count"] == 61
    all_gates = {label: {"generic": generic_gates(label), "native": native_gates(label),
                         "typed_3sc": typed_gates(label)} for label in ("stage", "installed")}
    assert inventory(APP) == SEALED and inventory(BACKUP) == BASELINE
    for path, expected in profiles.items():
        assert inventory(Path(path)) == expected, path
    S["check_namespace"](read(ROOT / "namespace-plan.json"))
    live = {str(app): S["HELPER"]["live_app_processes"](app) for app in (APP, BACKUP, STAGE)}
    assert not any(live.values()), live
    report = {
        "passed": True, "compiled_commit": COMMIT, "compiled_revision": REVISION,
        "installed_application": str(APP), "rollback_backup": str(BACKUP),
        "installed_equals_sealed_stage": True, "backup_equals_original_202": True,
        "installed_inventory_entries": len(SEALED), "backup_inventory_entries": len(BASELINE),
        "signatures_quicklook_readonly_cachefree_source_and_native_payload_parity": True,
        "material_native_parity": parity, "external_namespace_unchanged_files": 11,
        "profiles_exact_unchanged": list(profiles), "dependency_pins_unchanged": expected_pins,
        "signed_bundled_solver_unchanged_sha256": OLD_NATIVE_SHA256,
        "locations": all_gates, "receipt_and_log_sha256": RECEIPT_HASHES,
        "final_audit_source_sha256": digest(Path(__file__)), "native_app_processes": live,
        "historical_stage_paths_verified_against_sealed_inventory_and_current_app": True,
        "large_original_4jb_retained_replay_claimed_for_this_install": False,
        "engineering_design_accepted": False,
        "limits": [
            "Source-bug/native value/persistence/runtime/lifecycle qualification only, not engineering acceptance.",
            "FCStd restores saved materials by UUID from the available private User library, not unsaved embedding.",
            "The null fixture uses documented public native dimension setters, not GUI-authored null cells.",
            "Disjoint-support receipt records its own pass; native binary identity is bound by analytic/pipeline receipts.",
            "This is a read-only software custody audit, not independent engineering review."],
    }
    output = ROOT / "final-audit.json"
    with output.open("x") as stream:
        stream.write(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items()
                      if key not in ("material_native_parity", "receipt_and_log_sha256")}, indent=2))
    print("REPORT", output, digest(output))


if __name__ == "__main__":
    main()
