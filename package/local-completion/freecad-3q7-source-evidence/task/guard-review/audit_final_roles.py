"""Independent final qualification metadata/log audit; no product/native imports."""

import hashlib
import json
from pathlib import Path
import re

TASK = Path("/private/tmp/freecad-3q7-Pq3Byy")
FINAL = "6605b582911c320418951abaa415fa947237c4c8"
READS = {}


def raw(path):
    path = Path(path)
    assert path.is_file() and not path.is_symlink(), str(path)
    value = path.read_bytes()
    record = {"path": str(path), "sha256": hashlib.sha256(value).hexdigest(), "bytes": len(value)}
    assert READS.setdefault(str(path), record) == record, str(path)
    return value


def pairs(items):
    result = {}
    for key, value in items:
        assert key not in result
        result[key] = value
    return result


def load(path):
    return json.loads(raw(path), object_pairs_hook=pairs)


def pin(path):
    raw(path)
    return READS[str(path)]


def process(execution):
    assert execution["passed"] is True and execution["returncode"] == 0 and execution["timed_out"] is False
    for name in ("reaped", "child_reaped", "process_group_gone"):
        assert execution[name] is True


def inventories(folder, execution, prefixes=False):
    for kind in ("custody", "critical"):
        one, two = (folder / ("private-" + kind + "-" + when + ".json") for when in ("before", "after"))
        if prefixes:
            for when, path in (("before", one), ("after", two)):
                assert execution["private_" + kind + "_" + when + "_sha256"] == pin(path)["sha256"]
        assert load(one) == load(two)
        assert len(load(one)) == (4 if kind == "custody" else 15)


def source_role(label, count, module, gui=False, cold=False):
    folder = TASK / ("cold-qa" if cold else "source-qa") / label
    execution, manifest, identity = (load(folder / (name + ".json")) for name in ("execution", "manifest", "identity"))
    process(execution)
    assert execution["manifest_sha256"] == pin(folder / "manifest.json")["sha256"]
    assert execution["identity_sha256"] == pin(folder / "identity.json")["sha256"]
    assert execution["inputs_before"] == manifest["inputs"]
    assert execution["inputs_after"] == manifest["inputs"]["files"]
    assert manifest["inputs"]["git_head"] == FINAL
    assert manifest["module"] == module and manifest["expected_count"] == count
    assert manifest["gui"] is gui and manifest["discovery_only"] is False
    assert identity["passed"] is True and identity["selected_suite"]["count"] == count - 1
    assert identity["selected_suite"]["ids"] == manifest["expected_ids"]
    assert len(manifest["expected_ids"]) == len(set(manifest["expected_ids"])) == count - 1
    assert execution["runtime"] == identity["runtime"]
    assert identity["runtime"][-1] == FINAL and identity["runtime"][3] == "49261 +228 (Git)"
    assert manifest["version_header"]["FCRepositoryHash"] == FINAL
    assert manifest["version_header"]["FCRevision"] == "49261 +228 (Git)"
    for name in ("inputs_unchanged", "app_and_profiles_unchanged", "selected_critical_dependencies_unchanged"):
        assert execution[name] is True
    assert not execution["skipped_lines"] and not execution["missing_repeated_or_skipped_ids"]
    assert execution["installation_performed"] is False
    for name in ("fem_python_copy_parity", "fem_capacity_json_copy_parity"):
        assert manifest[name] == {"passed": True, "missing": [], "mismatched": []}
    assert manifest["candidate"] == identity["candidate"] and manifest["candidate"]["override"] is False
    assert manifest["candidate"]["sha256"] == "6c02452a896727af6cb4578fd3fb6bbfbdd48e3fb887c1c04fa2d8b171976c66"
    for stem, key in (("private-custody", "private_custody_before_sha256"), ("private-critical", "private_critical_before_sha256")):
        assert pin(folder / (stem + "-before.json"))["sha256"] == manifest[key]
    inventories(folder, execution, prefixes=cold)
    log = raw(folder / "run.log").decode()
    assert pin(folder / "run.log")["sha256"] == execution["log_sha256"]
    counts = [list(row) for row in re.findall(r"^Ran (\d+) tests? in ([\d.]+)s\s*$", log, re.M)]
    assert counts == execution["unittest_counts"] and len(counts) == 1 and int(counts[0][0]) == count
    assert len(re.findall(r"^OK\s*$", log, re.M)) == 1
    assert not re.search(r"^(FAILED\b|FAIL:|ERROR:|UNEXPECTED SUCCESS:)|\.\.\. skipped ", log, re.M)
    for test_id in manifest["expected_ids"]:
        pattern = "^" + re.escape(test_id.rsplit(".", 1)[-1]) + r" \(" + re.escape(test_id) + r"\)([^\n]*)$"
        hits = re.findall(pattern, log, re.M)
        assert len(hits) == 1 and "skipped" not in hits[0], test_id
    for row in source_identity["files"]:
        for root in ("/Users/zukomgwili/src/FreeCAD/", "/Users/zukomgwili/src/FreeCAD/build/release/Mod/Fem/"):
            path = (root + row["path"]) if root.endswith("FreeCAD/") else root + row["path"].removeprefix("src/Mod/Fem/")
            assert manifest["inputs"]["files"][path] == row["final_sha256"], path
    if cold:
        for name in ("literal_cold_receipt_passed", "captured_log_matches_process_receipt", "output_bytes_endfenced",
                     "manifest_endfenced", "final_inputs_endfenced", "private_receipt_bytes_endfenced", "post_run_serial_guard_passed"):
            assert execution[name] is True
        for path, value in execution["captured_outputs"].items():
            assert {key: pin(path)[key] for key in ("sha256", "bytes")} == value
    return {"execution": pin(folder / "execution.json"), "manifest": pin(folder / "manifest.json"),
            "identity": pin(folder / "identity.json"), "log": pin(folder / "run.log"),
            "count_including_identity": count, "feature_test_count": count - 1, "skipped": 0,
            "runtime": identity["runtime"], "all_expected_IDs_exactly_once": True,
            "recorded_input_end_fence_private_custody_parity_and_actual_logs_verified": True}


def ctest():
    folder = TASK / "ctest-qa/ctest-r01"
    execution = load(folder / "execution.json")
    process(execution)
    for name in ("source_build_supervisor_candidate_unchanged", "app_and_profiles_unchanged",
                 "selected_critical_dependencies_unchanged", "post_run_serial_guard_passed",
                 "retained_log_bytes_endfenced", "fresh_ctest_log_bytes_endfenced", "private_receipt_bytes_endfenced"):
        assert execution[name] is True
    assert execution["protected_inputs_before"] == execution["protected_inputs_after"]
    protected = execution["protected_inputs_before"]
    assert protected["source"]["git_head"] == FINAL
    assert protected["build"]["version_header"]["FCRepositoryHash"] == FINAL
    assert protected["build"]["version_header"]["FCRevision"] == "49261 +228 (Git)"
    inventories(folder, execution, prefixes=True)
    log = raw(folder / "run.log").decode()
    assert pin(folder / "run.log")["sha256"] == execution["log_sha256"]
    pattern = r"^\s*(\d+)/(\d+)\s+Test\s+#(\d+):\s+(.+?)\s+\.{2,}\s*(.*?)\s+([\d.]+)\s+sec\s*$"
    rows = re.findall(pattern, log, re.M)
    assert len(rows) == 2274 and {int(row[0]) for row in rows} == set(range(1, 2275))
    assert all(int(row[0]) == int(row[2]) and row[1] == "2274" for row in rows)
    outcomes = {"Passed": 0, "***Skipped": 0, "***Not Run (Disabled)": 0}
    special = {}
    for ordinal, _, _, name, status, _ in rows:
        assert status in outcomes, (ordinal, name, status)
        outcomes[status] += 1
        if status != "Passed":
            special[int(ordinal)] = {"name": name, "status": status}
    assert outcomes == {"Passed": 2264, "***Skipped": 2, "***Not Run (Disabled)": 8}
    for key, expected in (("catalogue", 2274), ("enabled", 2266), ("executed_passing", 2264), ("skipped", 2), ("disabled", 8), ("failed", 0)):
        assert execution["ctest"][key] == expected
    assert execution["ctest"]["complete_catalogue_verified"] is True
    for name, proof in execution["ctest_logs_after"].items():
        if proof["fresh_for_this_run"]:
            assert {key: pin(folder / name)[key] for key in ("sha256", "bytes")} == {key: proof[key] for key in ("sha256", "bytes")}
        else:
            assert name == "LastTestsFailed.log" and not (folder / name).exists()
    assert execution["ctest_parallel"] == 1 and execution["ctest_default_test_timeout_seconds"] == 60
    assert execution["existing_per_test_TIMEOUT_properties_overridden"] is False
    return {"execution": pin(folder / "execution.json"), "log": pin(folder / "run.log"),
            "catalogue": 2274, "enabled": 2266, "executed_passing": 2264, "skipped": 2, "disabled": 8, "failed": 0,
            "all_catalogue_rows_independently_parsed_exactly_once": True, "nonexecuted_rows": special,
            "fresh_LastTest_and_disabled_index_verified_stale_failure_index_not_current": True}


def build():
    folder = TASK / "diagnostic-build-r01"
    execution = load(folder / "execution.json")
    process(execution)
    assert execution["source_before"] == execution["source_after"]
    assert execution["source_after"]["git_head"] == FINAL
    for name in ("source_unchanged", "application_and_three_profiles_unchanged", "selected_dependencies_unchanged", "post_run_serial_guard_passed"):
        assert execution[name] is True
    assert execution["installation_performed"] is False
    assert execution["build_after"]["version_header"]["FCRepositoryHash"] == FINAL
    assert execution["build_after"]["version_header"]["FCRevision"] == "49261 +228 (Git)"
    for name in ("fem_python_copy_parity", "fem_capacity_json_copy_parity"):
        assert execution["build_after"][name] == {"passed": True, "missing": [], "mismatched": []}
    inventories(folder, execution, prefixes=True)
    assert pin(folder / "run.log")["sha256"] == execution["log_sha256"]
    return {"execution": pin(folder / "execution.json"), "log": pin(folder / "run.log"), "source_commit": FINAL,
            "revision": "49261 +228 (Git)", "normal_frozen_pixi_cmake_build_passed": True,
            "source_app_profiles_and_dependency_recorded_fences_verified": True}


source_identity = load(TASK / "pair-audit/final-source-byte-identity-r01.json")
assert source_identity["passed"] is True and source_identity["final_product_commit"] == FINAL
roles = {"normal_build": build(), "full_FEM": source_role("fem-full-r02", 419, "TestFemApp"),
         "GUI": source_role("gui-full-r01", 9, "TestFemGui", gui=True),
         "focused_native_guards": source_role("native-guards-r03", 13, "YzkQ37SelectedGuardsV2"),
         "fresh_complete132": source_role("capacity-native-r01", 2, "femtest.app.test_moving_port_capacity_native"),
         "separate_cold": source_role("cold-native-r01", 2, "YzkPortableColdRestore", cold=True), "CTest": ctest()}
for path, before in READS.copy().items():
    assert pin(path) == before
output = TASK / "guard-review/final-runtime-role-file-audit-r01.json"
report = {"schema": "FreeCAD-3q7-final-runtime-role-independent-file-audit-v1", "passed": True,
          "source_commit": FINAL, "revision": "49261 +228 (Git)", "roles": roles,
          "scope": "Independent recorded-input/parity/private-inventory/producer/log/source-byte bindings and complete actual catalogue counts; no product/native execution by reviewer.",
          "all_read_artifacts_end_fenced": True, "all12_final_source_hashes_in_every_python_role_verified": True,
          "pending_runtime_roles": [], "evidence": READS}
with output.open("x") as stream:
    json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
    stream.write("\n")
print(json.dumps({"passed": True, "report": str(output), "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}))
