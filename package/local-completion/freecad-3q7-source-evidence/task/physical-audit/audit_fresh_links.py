"""Independent read-only native witness/cold/capsule literal-file link audit."""

import hashlib
import json
from pathlib import Path

TASK = Path("/private/tmp/freecad-3q7-Pq3Byy")
RUN = TASK / "source-qa/capacity-native-r01"
COLD = TASK / "cold-qa/cold-native-r01"
SEEN = {}


def raw(path):
    path = Path(path)
    assert path.is_file() and not any(item.is_symlink() for item in (path, *path.parents))
    data = path.read_bytes()
    value = {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    assert SEEN.setdefault(str(path), value) == value
    return data


def load(path):
    return json.loads(raw(path))


def audit():
    approval = load(TASK / "collection/generic-case-approval-r01.json")
    custody = load(TASK / "collection/generic-case-custody-r01.json")
    assert approval["root_approved"] is True and custody["passed"] is True
    assert custody["files"] == approval["files"] and len(custody["files"]) == 20
    assert custody["copies_exact"] is True and custody["originals_unchanged"] is True
    for key in ("source_run_execution", "source_run_log", "source_run_manifest", "exact_approval"):
        value = custody[key]
        raw(value["path"])
        assert SEEN[value["path"]] == value
    assert custody["source_run_execution"]["path"] == str(RUN / "execution.json")
    assert custody["source_run_execution"]["sha256"] == "a9fa9985472073573fe5efd924eab65456fbbdfba762726db72aa1c9626b54de"
    source, capsule = Path(custody["source_witness_directory"]), Path(custody["copy_directory"])
    assert source == RUN / "freecad_user_temp/freecad-moving-port-capacity-native-kgd8rdbk/witness"
    assert capsule == TASK / "generic-case-capsule-r01"
    witness = load(source / "witness-receipt.json")
    assert witness["passed"] is True and witness["physical_check_count"] == 3566
    assert len(witness["checks"]) == len({row["name"] for row in witness["checks"]}) == 3566
    paths, total = set(), 0
    for row in custody["files"]:
        assert row["path"] not in paths and row["source"] == str(source / row["path"])
        paths.add(row["path"])
        original, copied = raw(row["source"]), raw(capsule / row["path"])
        assert original == copied
        assert len(original) == row["bytes"] and hashlib.sha256(original).hexdigest() == row["sha256"]
        if row["path"] != "witness-receipt.json":
            assert witness["retained_files"][row["path"]] == {"sha256": row["sha256"], "bytes": row["bytes"]}
        total += len(original)
    assert total == 161677232
    assert {str(path.relative_to(capsule)) for path in capsule.rglob("*") if path.is_file()} == paths
    case = load(source / "cold-case.json")
    assert witness["cold_manifest"] == str(source / "cold-case.json")
    assert witness["cold_manifest_sha256"] == SEEN[str(source / "cold-case.json")]["sha256"]
    assert case["schema"] == "FreeCAD-native-coupled-port-coupled-cold-case-v1" and case["case"] == "capacity"
    raw(case["document"])
    assert case["document"] == str(source / "coupled-native-current.FCStd")
    assert case["document_sha256"] == SEEN[case["document"]]["sha256"]
    assert raw(source / "native-accounting-data.json").decode() == case["accounting_data_literal"]
    for key, filename in (("deck", "Mesh.inp"), ("request", "Mesh.accounting"), ("native_output", "Mesh.accounting.out"),
                          ("dat", "Mesh.dat"), ("frd", "Mesh.frd")):
        proof = case["source_files"][key]
        assert proof["path"] == str(source / "native" / filename)
        raw(proof["path"])
        assert proof["sha256"] == SEEN[proof["path"]]["sha256"]
    execution, manifest, receipt = (load(COLD / (name + ".json")) for name in ("execution", "manifest", "cold-receipt"))
    assert execution["passed"] is True and execution["returncode"] == 0 and execution["timed_out"] is False
    assert execution["runtime"][-1] == "6605b582911c320418951abaa415fa947237c4c8"
    assert execution["runtime"][3] == "49261 +228 (Git)"
    for name in ("reaped", "child_reaped", "process_group_gone", "inputs_unchanged", "app_and_profiles_unchanged",
                 "selected_critical_dependencies_unchanged", "literal_cold_receipt_passed", "captured_log_matches_process_receipt",
                 "output_bytes_endfenced", "manifest_endfenced", "final_inputs_endfenced", "private_receipt_bytes_endfenced"):
        assert execution[name] is True
    assert len(execution["unittest_counts"]) == 1 and execution["unittest_counts"][0][0] == "2"
    assert not execution["skipped_lines"] and not execution["missing_repeated_or_skipped_ids"]
    assert manifest["cold_manifest"] == {"path": str(source / "cold-case.json"), "sha256": witness["cold_manifest_sha256"]}
    assert manifest["expected_ids"] == ["YzkPortableColdRestore.PortableColdRestore.test_saved_full_graph_remains_literal_historical_data"]
    assert execution["manifest_sha256"] == SEEN[str(COLD / "manifest.json")]["sha256"]
    assert receipt["passed"] is True and receipt["status"].startswith("Stale after restore")
    for name in ("no_native_solve", "no_save", "no_history_or_provenance_repair"):
        assert receipt[name] is True
    assert receipt["manifest"] == str(source / "cold-case.json") and receipt["manifest_sha256"] == witness["cold_manifest_sha256"]
    assert receipt["accounting_data_sha256"] == hashlib.sha256(case["accounting_data_literal"].encode()).hexdigest()
    assert receipt["supports"] == case["explicit_supports"] == ["BackboneFixed"]
    for path, proof in execution["captured_outputs"].items():
        data = raw(path)
        assert proof == {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    for path, proof in SEEN.copy().items():
        raw(path)
        assert SEEN[path] == proof
    return {"schema": "FreeCAD-3q7-fresh-native-cold-capsule-literal-link-independent-audit-v1", "passed": True,
            "source_witness": str(source), "capsule": str(capsule), "capsule_files": 20, "capsule_bytes": total,
            "actual_source_execution": custody["source_run_execution"], "actual_cold_execution": SEEN[str(COLD / "execution.json")],
            "actual_cold_receipt": SEEN[str(COLD / "cold-receipt.json")],
            "all_selected_original_copied_and_producer_hashes_sizes_exact": True,
            "saved_literal_FCStd_native5_source_and_accounting_history_links_exact": True,
            "separate_native_cold_assertions_and_no_solve_save_repair_receipt_verified": True,
            "native_Cold_execution_performed_by_this_auditor": False,
            "authorship": "Auditor authored some mutation guards and the independent numerical auditor, not native producer/cold/retention helpers.",
            "all_read_file_end_fences": True, "evidence": SEEN}


if __name__ == "__main__":
    result = audit()
    output = TASK / "physical-audit/fresh-native-cold-capsule-link-audit-r01.json"
    with output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"passed": True, "report": str(output), "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}))
