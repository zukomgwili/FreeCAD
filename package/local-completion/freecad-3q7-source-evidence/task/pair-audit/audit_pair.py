#!/usr/bin/env python3
"""Independent stdlib file-only audit of the completed r02 matched export pair.

Never imports product modules or executes native code/tests/builds. Recorded
runtime pins are audited as historical run evidence; a later build may be active.
"""

import argparse
import hashlib
import json
import marshal
import math
from pathlib import Path
import re


TASK = Path("/private/tmp/freecad-3q7-Pq3Byy")
EXECUTIONS = {
    "baseline": "fd97c389e80593076fe035573fb357ae4836bd955aca7aad72541cae9fd14a36",
    "candidate": "df10f37e56e1ff2c91d5bb735c5b60e48bbb876e6911e4a72c1a1b9f6c887da6",
}
OUTPUTS = {
    "identity.json", "export-profile.json", "run.log", "whole-public-write.prof",
    "profile-cumulative.txt", "native/Mesh.inp", "native/Mesh.accounting",
    "native/Mesh.accounting.json", "mesh-before.json", "mesh-after.json",
}
COUNTS = {"PORT": 264, "BODY": 264, "ANGLE": 792, "SPRING": 792,
          "SPC_SUPPORT": 1, "CCX_FORCE_ACCOUNTING_V3": 1, "END": 1}
REQUIRED = {"supports": 1, "bodies": 264, "ports": 264, "angles": 792, "springs": 792}
STAMP = re.compile(rb"^\*\*   written on    --> [^\r\n]+$", re.M)
READS = {}


def need(condition, message):
    if not condition:
        raise AssertionError(message)


def descriptor(path):
    path = Path(path)
    need(path.is_file() and not path.is_symlink(), f"Missing or symlink artifact: {path}")
    size, digest = 0, hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return {"path": str(path), "sha256": digest.hexdigest(), "bytes": size}


def pin(path):
    value = descriptor(path)
    previous = READS.setdefault(str(path), value)
    need(previous == value, f"Artifact changed while auditing: {path}")
    return value


def raw(path):
    before = pin(path)
    value = Path(path).read_bytes()
    need(hashlib.sha256(value).hexdigest() == before["sha256"], "Read differs from pinned bytes")
    return value


def pairs(items):
    result = {}
    for key, value in items:
        need(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def load(path):
    return json.loads(raw(path), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(AssertionError(value)))


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                                    separators=(",", ":")).encode()).hexdigest()


def named(snapshot):
    groups, seen, handles = {}, set(), []
    for group in snapshot["groups"]:
        need(set(group) == {"id", "name", "element_type", "elements"}, "Group field set differs")
        key = (group["name"], group["element_type"])
        need(key not in groups and group["id"] not in seen, "Duplicate native handle/name/type")
        seen.add(group["id"])
        handles.append(group["id"])
        groups[key] = group["elements"]
    return {key: value for key, value in snapshot.items() if key != "groups"}, handles, groups


def profile_rows(path):
    pin(path)
    with path.open("rb") as handle:
        table = marshal.load(handle)
        need(handle.read() == b"", "Trailing profile bytes")
    need(type(table) is dict, "Not a cProfile stats dictionary")
    rows = []
    for key, record in table.items():
        need(type(key) is tuple and len(key) == 3 and type(record) is tuple and len(record) == 5,
             "Malformed cProfile record")
        filename, line, function = key
        primitive, total, self_time, cumulative, callers = record
        need(type(filename) is str and type(line) is int and type(function) is str
             and type(primitive) is int and type(total) is int and type(callers) is dict,
             "Invalid profile record field type")
        need(0 <= primitive <= total and math.isfinite(self_time) and math.isfinite(cumulative)
             and self_time >= 0 and cumulative >= 0, "Invalid profile count/time")
        rows.append({"filename": filename, "line": line, "function": function,
                     "primitive_calls": primitive, "total_calls": total,
                     "self_seconds": self_time, "cumulative_seconds": cumulative})
    return sorted(rows, key=lambda row: (-row["cumulative_seconds"], row["filename"], row["line"]))


def leg(role):
    folder = TASK / ("large-" + role + "-r02")
    execution = load(folder / "execution.json")
    need(pin(folder / "execution.json")["sha256"] == EXECUTIONS[role], "Unexpected execution receipt")
    need(execution["passed"] is True and execution["role"] == role and not execution["guard_errors"], "Failed execution")
    for field in ("child_reaped", "reaped", "process_group_gone", "source_and_supervisor_unchanged",
                  "compiled_native_runtime_unchanged", "python_copy_parity_unchanged", "manifest_unchanged",
                  "application_and_three_profiles_unchanged", "sixteen_selected_dependencies_unchanged",
                  "serial_post_guard_passed", "produced_outputs_unchanged_after_capture", "stdin_is_DEVNULL",
                  "no_solver_mesher_save_recompute_build_copy_or_install"):
        need(execution[field] is True, f"Missing {role} execution fence: {field}")
    need(execution["returncode"] == 0 and execution["timed_out"] is False, "Failed/timed-out native run")
    need(len(execution["unittest_counts"]) == 1 and execution["unittest_counts"][0][0] == "2", "Not exactly2 tests")
    need(execution["inputs_before"] == execution["inputs_after"], "Input receipt end fence differs")
    need(set(execution["produced_outputs"]) == OUTPUTS, "Not exactly all10 produced outputs")
    for name, expected in execution["produced_outputs"].items():
        need(expected == pin(folder / name), f"Produced output binding differs: {name}")
    manifest, identity, profile = (load(folder / (name + ".json")) for name in ("manifest", "identity", "export-profile"))
    need(pin(folder / "manifest.json")["sha256"] == execution["manifest_sha256"], "Manifest binding differs")
    need(manifest["inputs"] == execution["inputs_before"] and manifest["role"] == role, "Manifest input/role differs")
    need(manifest["compiled_native_pins"] == execution["compiled_native_pins"] == identity["compiled_native_pins"]
         == profile["same_compiled_runtime_pins"] and len(manifest["compiled_native_pins"]) == 63,
         "Recorded63 runtime pins differ")
    need(manifest["python_source_runtime_parity"] == execution["python_source_runtime_parity"], "Copy parity binding differs")
    for name, sha in manifest["python_source_runtime_parity"].items():
        for root in ("/Users/zukomgwili/src/FreeCAD/src/Mod/Fem", "/Users/zukomgwili/src/FreeCAD/build/release/Mod/Fem"):
            need(manifest["inputs"][str(Path(root) / name)] == sha, "Recorded source/runtime copy parity differs")
    need(identity["passed"] is True and profile["passed"] is True and profile["role"] == role, "Producer/identity failure")
    need(profile["manifest"] == pin(folder / "manifest.json") and identity["manifest"] == {
             "path": str(folder / "manifest.json"), "sha256": execution["manifest_sha256"]}, "Producer manifest binding differs")
    need(profile["actual_runtime"] == identity["runtime"] and profile["actual_write_inp_file_calls"] == 1,
         "Wrong runtime or number of whole public calls")
    need(profile["source_HEAD"] == manifest["source_HEAD"] == execution["source_HEAD"] == identity["runtime"][-1]
         == "5b11849843232fdffa4c9c08e2821a6f7c99dee3", "Measured common source/runtime origin differs")
    need(identity["runtime"][3] == manifest["revision"] == "49261 +226 (Git)", "Measured common revision differs")
    module = profile["public_entrypoint_module"]
    need(module == identity["sources"]["femtools.ccxtools"]
         and manifest["inputs"][module["path"]] == module["sha256"], "Public entrypoint source binding differs")
    for field in ("no_timing_SLA_asserted", "one_whole_public_write_inp_file_call_intended",
                  "cumulative_profile_times_overlap_and_are_not_additive_partitions",
                  "no_solver_mesher_save_recompute_or_physical_model_edit_by_harness",
                  "original_fixture_and_native_evidence_unchanged"):
        need(profile[field] is True, f"Profile scope/fence differs: {field}")
    need(profile["inputs_before"] == profile["inputs_after"], "Original physical fixture receipt fence differs")
    need(profile["old_physical_qualification_inherited_by_this_export"] is False
         and profile["engineering_or_BIM_accepted"] is False and profile["Oomakhi_accessed_or_solved"] is False,
         "Unexpected physical/engineering qualification claim")
    for stem in ("private-custody", "private-critical"):
        before, after = (folder / (stem + suffix + ".json") for suffix in ("-before", "-after"))
        for path in (before, after):
            need(pin(path)["sha256"] == execution[path.name + "_sha256"], "Private inventory hash binding differs")
        need(load(before) == load(after), f"{role} app/profile/dependency inventory changed")
    log = raw(folder / "run.log").decode()
    need(pin(folder / "run.log")["sha256"] == execution["log_sha256"], "Log receipt binding differs")
    need(re.findall(r"^Ran (\d+) tests? in ([\d.]+)s$", log, re.M) == execution["unittest_counts"]
         or [list(row) for row in re.findall(r"^Ran (\d+) tests? in ([\d.]+)s$", log, re.M)] == execution["unittest_counts"], "Actual unittest log counts differ")
    need(len(re.findall(r"^OK$", log, re.M)) == 1 and not re.search(r"^(FAILED|FAIL:|ERROR:|UNEXPECTED SUCCESS)|\.\.\. skipped ", log, re.M), "Actual test error/skip")
    for method, full in (("test_common_build_runtime_manifest_and_selected_suite", "Q37LargeIdentity.TestQ37LargeIdentity.test_common_build_runtime_manifest_and_selected_suite"),
                         ("test_same_saved132_graph_whole_stock_export_profile", "Q37LargeProfile.WholePublicExportProfile.test_same_saved132_graph_whole_stock_export_profile")):
        need(len(re.findall("^" + re.escape(method) + r" \(" + re.escape(full) + r"\)", log, re.M)) == 1,
             "Missing/repeated actual selected test")
    mesh_before, mesh_after = load(folder / "mesh-before.json"), load(folder / "mesh-after.json")
    need(raw(folder / "mesh-before.json") == raw(folder / "mesh-after.json"),
         f"{role}: retained raw mesh snapshot bytes changed within leg")
    need(mesh_before == mesh_after, f"{role}: exact raw mesh/provenance/groups/analysis order changed within leg")
    for when, snapshot in (("before", mesh_before), ("after", mesh_after)):
        need(canonical(snapshot) == profile["mesh_" + when + "_sha256"], "Raw mesh canonical hash differs")
        need({name: canonical(value) for name, value in snapshot.items()} == profile["mesh_" + when + "_component_sha256"], "Mesh component hash differs")
    need(profile["model_before_sha256"] == profile["model_after_sha256"], "Selected physical-property digest changed")
    rows = profile_rows(folder / "whole-public-write.prof")
    need(rows == profile["profile_operation_rows"], "Recorded profile rows differ from actual cProfile blob")
    entry = [row for row in rows if row["filename"] == module["path"] and row["function"] == "write_inp_file"]
    need(len(entry) == 1 and entry[0]["primitive_calls"] == entry[0]["total_calls"] == 1,
         "Raw cProfile does not show exactly one whole public entrypoint call")
    request = raw(folder / "native/Mesh.accounting")
    counts, ports = {}, {}
    for line in request.decode().splitlines():
        tokens = line.split()
        if tokens and tokens[0][0].isalpha():
            counts[tokens[0]] = counts.get(tokens[0], 0) + 1
            if tokens[0] == "PORT":
                need(len(tokens) == 4 and tokens[1] not in ports, "Malformed/repeated request PORT")
                ports[tokens[1]] = list(map(int, tokens[2:]))
    need(counts == COUNTS == profile["request_declarations"] and ports == profile["native_PORT_IDs"], "Actual request counts/PORT IDs differ")
    metadata = load(folder / "native/Mesh.accounting.json")
    need(metadata["schema"] == "CCX_FORCE_ACCOUNTING_V3"
         and metadata["request_sha256"] == pin(folder / "native/Mesh.accounting")["sha256"]
         and metadata["deck_sha256"] == pin(folder / "native/Mesh.inp")["sha256"], "Actual export metadata hash binding differs")
    capacity = metadata["capacity"]
    need(capacity["required"] == REQUIRED and capacity["total"] == 2113
         and capacity["supported"]["total_records"] == 2113
         and capacity["supported"]["limits"] == dict.fromkeys(REQUIRED, 2113)
         and capacity["binary_sha256"] == identity["native"]["sha256"]
         == "6c02452a896727af6cb4578fd3fb6bbfbdd48e3fb887c1c04fa2d8b171976c66", "Actual2113/default6c export admission differs")
    binding = {"whole-public-write.prof": "output_profile_blob", "profile-cumulative.txt": "output_cumulative_text",
               "native/Mesh.inp": "output_deck", "native/Mesh.accounting": "output_request",
               "native/Mesh.accounting.json": "output_request_metadata", "mesh-before.json": "output_mesh_before",
               "mesh-after.json": "output_mesh_after"}
    for name, field in binding.items():
        need(profile[field] == execution["produced_outputs"][name], "Profile output descriptor differs")
    return {"folder": folder, "execution": execution, "manifest": manifest, "identity": identity,
            "profile": profile, "snapshot": mesh_before, "rows": rows, "request": request}


def audit():
    pin(Path(__file__))
    baseline, candidate = leg("baseline"), leg("candidate")
    a, b = (item["profile"] for item in (baseline, candidate))
    need(baseline["execution"]["compiled_native_pins"] == candidate["execution"]["compiled_native_pins"], "The63 recorded core pins differ across legs")
    need(a["actual_runtime"] == b["actual_runtime"] and a["inputs_before"] == b["inputs_before"], "Recorded runtime/immutable fixture inputs differ")
    reference = candidate["execution"]["baseline_reference"]
    need(reference == candidate["manifest"]["reference"] == b["baseline_reference"], "Candidate matched baseline reference differs")
    for item in reference.values():
        need(pin(item["path"]) == item, "Matched baseline reference file differs")
    need(reference["execution"] == pin(baseline["folder"] / "execution.json"), "Not the new r02 baseline")
    need(b["strict_matched_baseline_outputs_and_named_mesh_snapshots_equal"] is True, "Candidate did not complete strict output gate")
    one, ah, ag = named(baseline["snapshot"])
    two, bh, bg = named(candidate["snapshot"])
    need(one == two and ah == bh and ag == bg and len(ag) == len(bg) == 9531, "Cross-leg exact facts or narrow named-group bijection differ")
    reassigned = sum(left["name"] != right["name"] or left["element_type"] != right["element_type"]
                     for left, right in zip(baseline["snapshot"]["groups"], candidate["snapshot"]["groups"]))
    need(baseline["request"] == candidate["request"], "Accounting request is not byte-exact")
    decks = [raw(item["folder"] / "native/Mesh.inp") for item in (baseline, candidate)]
    need(all(len(STAMP.findall(value)) == 1 for value in decks), "Need exactly one permitted timestamp in each deck")
    normalized = [STAMP.sub(b"**   written on    --> <timestamp>", value) for value in decks]
    need(normalized[0] == normalized[1], "Deck differs beyond its one permitted timestamp comment")
    need(a["model_before_sha256"] == b["model_before_sha256"]
         and a["model_after_sha256"] == b["model_after_sha256"], "Selected physical-property digests differ across legs")
    amendment = TASK / "proposals/benchmark-native-group-handle-amendment-r01.json"
    need(pin(amendment)["sha256"] == "e5fe78f283685cf4169924629d560d92021222b2da02a8f3d8ba86c97898acf3", "Unreviewed comparison amendment")
    amendment_data = load(amendment)
    need(amendment_data["passed"] is True and amendment_data["old_failed_pair_reclassified"] is False, "Amendment scope differs")
    old = {role: load(TASK / ("large-" + role + "-r01") / "execution.json") for role in ("baseline", "candidate")}
    need(old["candidate"]["passed"] is False, "Original failed candidate was improperly promoted")
    metrics = {}
    for role, item in (("baseline", baseline), ("candidate", candidate)):
        wall = item["profile"]["profiled_stock_write_wall_seconds"]
        cpu = item["profile"]["profiled_stock_write_FreeCAD_process_CPU_seconds"]
        need(math.isfinite(wall) and wall > 0 and math.isfinite(cpu) and cpu > 0, "Invalid whole-call clock")
        methods = [row for row in item["rows"] if row["filename"] == "~" and "'Fem.FemMesh'" in row["function"]]
        focused = [row for row in item["rows"] if row["function"] in (
            "get_mesh_geometry_signature", "get_femnodes_by_owned_references", "_get_mesh_region_by_owned_references",
            "get_femelement_table", "write_inp_file", "_capture_native", "_capture", "_native_snapshot")]
        metrics[role] = {"whole_public_write_calls": 1, "whole_profiled_wall_seconds": wall,
                         "whole_profiled_FreeCAD_process_CPU_seconds": cpu,
                         "supervisor_elapsed_seconds_not_the_write_clock": item["execution"]["elapsed_seconds"],
                         "native_mesh_method_counts_and_individual_profile_times": methods,
                         "focused_individual_profile_rows": focused}
    speedup = metrics["baseline"]["whole_profiled_wall_seconds"] / metrics["candidate"]["whole_profiled_wall_seconds"]
    before, after = baseline["manifest"]["inputs"], candidate["manifest"]["inputs"]
    changed = {path: {"baseline": before[path], "candidate": after[path]} for path in before.keys() & after.keys() if before[path] != after[path]}
    for path, value in READS.copy().items():
        need(descriptor(path) == value, f"Final pair artifact fence changed: {path}")
    return {"schema": "FreeCAD-3q7-independent-completed-r02-pair-file-audit-v1", "passed": True,
            "executions": {role: pin(TASK / ("large-" + role + "-r02") / "execution.json") for role in EXECUTIONS},
            "same_recorded_native_core": {"count": 63, "pins": baseline["execution"]["compiled_native_pins"],
                                          "runtime": a["actual_runtime"], "live_current_build_revalidated": False},
            "outputs": {"all10_per_leg_hashes_and_sizes_verified": True, "all_source_supervisor_native_app_profile_dependency_recorded_fences_verified": True,
                        "actual_two_unskipped_tests_and_one_whole_public_call_per_leg": True,
                        "raw_within_leg_mesh_before_after_exact": True,
                        "non_group_snapshot_fields_cross_leg_exact": sorted(one),
                        "ordered_native_handle_lists_cross_leg_exact": True,
                        "unique_named_typed_group_ordered_membership_bijection": 9531,
                        "handle_to_name_type_assignments_different": reassigned,
                        "raw_cross_leg_group_records_identical": baseline["snapshot"]["groups"] == candidate["snapshot"]["groups"],
                        "narrow_amendment": pin(amendment), "request_bytes_exact": True,
                        "deck_only_single_exact_written_on_comment_may_differ": True,
                        "normalized_deck_sha256": hashlib.sha256(normalized[0]).hexdigest(),
                        "original_timestamp_comments": [STAMP.findall(value)[0].decode() for value in decks]},
            "timing_and_calls": metrics, "observed_profiled_wall_speedup_ratio_this_pair_only": speedup,
            "observed_profiled_wall_reduction_percent_this_pair_only": 100 * (1 - 1 / speedup),
            "timing_limits": "One matched, profiled whole public write per leg, same63 compiled native bodies and fixed restored fixture. Individual cumulative profile times overlap and were not summed. FreeCAD process CPU excludes child CPU. No universal speedup/SLA and no comparison to old unprofiled timings.",
            "changed_common_run_input_hashes": changed,
            "prior_r01": {"candidate_still_failed": True, "promoted_to_accepted_pair": False,
                          "execution_descriptors": {role: pin(TASK / ("large-" + role + "-r01") / "execution.json") for role in old}},
            "fresh_physics_or_cold_qualified_by_this_pair": False, "installation_performed": False,
            "engineering_or_BIM_accepted": False, "Oomakhi_accessed_or_solved": False,
            "authorship": "Auditor did not author this benchmark harness or product fix; authored separate mutation guards and reviewed the candidate. Private stdlib file-only arithmetic/parsing; no native/product execution.",
            "evidence_sha256_and_bytes": READS}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    need(args.report.is_absolute() and args.report.parent.resolve().is_relative_to((TASK / "pair-audit").resolve())
         and not args.report.exists(), "New-only private report required")
    report = audit()
    with args.report.open("x") as handle:
        json.dump(report, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"passed": True, "report": str(args.report), "sha256": descriptor(args.report)["sha256"],
                      "wall_speedup_this_pair": report["observed_profiled_wall_speedup_ratio_this_pair_only"]}))


if __name__ == "__main__":
    main()
