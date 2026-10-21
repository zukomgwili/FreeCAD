"""Independent read-only installation packet byte/privacy/semantic-link audit.

Stdlib only. No product imports, collector calls, native processes, tests,
builds, app probes or installs. Reads only explicit published/current original
and capsule files; never reads live app/profile inventories or runtime binaries.
The only write is a new private collection report outside the sealed packet.
"""

import argparse
import ast
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path("/private/tmp/freecad-3q7-install-W35DLJ")
REPO = Path("/Users/zukomgwili/src/FreeCAD")
PACKET = REPO / "package/local-completion/freecad-3q7-installation-evidence"
SUMMARY = REPO / "package/local-completion/freecad-3q7-installation.json"
COMMIT = "6a0ed157b1063fa21407dc8f3cdfa3aef9484d8d"
REVISION = "49261 +229 (Git)"
NATIVE = "6c02452a896727af6cb4578fd3fb6bbfbdd48e3fb887c1c04fa2d8b171976c66"
FINAL_SHA = "f6c1c05d7c81c9bb0d9623d10d8fcc1b58fc051d81b49e4bbc8e02c76d91b755"
PHYSICAL_SHA = "7c61cc60814c00cbe62164c9204a66a9a65b5579b5692a93651f14e09374711d"
RAW = {"environment", "environ", "profiles", "inventory", "profile_inventory", "profile_inventories",
       "app_inventory", "application_inventory", "critical_before", "critical_after", "password", "api_key",
       "apikey", "secret", "access_token", "refresh_token", "authorization", "cookie"}
DENIED = {".git", ".beads", ".pixi", "__pycache__", "CMakeFiles", "CalculiX", "profiles", "module-cache",
          "freecad_user_home", "freecad_user_data", "freecad_user_temp", "xdg_config_home", "xdg_data_home", "xdg_cache_home"}
READS = {}


def sha(body):
    return hashlib.sha256(body).hexdigest()


def read(path, original=False):
    path = Path(path)
    assert path.is_absolute() and ".." not in path.parts and path.is_file()
    assert not any(item.is_symlink() for item in (path, *path.parents))
    if original:
        assert path.is_relative_to(ROOT) or path.is_relative_to(REPO)
        assert not path.is_relative_to(REPO / ".pixi")
        if path.is_relative_to(REPO / "build"):
            assert path in {REPO / "build/release/src/Build/Version.h",
                            REPO / "build/release/install_manifest.txt"}
    body = path.read_bytes()
    row = {"path": str(path), "sha256": sha(body), "bytes": len(body)}
    assert READS.setdefault(str(path), row) == row
    return body


def pairs(items):
    result = {}
    for key, value in items:
        assert key not in result
        result[key] = value
    return result


def parse(body):
    return json.loads(body, object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(AssertionError(value)))


def privacy(value):
    if isinstance(value, dict):
        keys = {str(key).lower() for key in value}
        assert not keys & RAW
        assert not (isinstance(value.get("."), dict) and value["."].get("kind") == "dir")
        assert not {"dev", "inode", "mtime_ns", "ctime_ns"} <= keys
        for child in value.values():
            privacy(child)
    elif isinstance(value, list):
        for child in value:
            privacy(child)
    elif isinstance(value, float):
        assert math.isfinite(value)


def audit(args):
    read(Path(__file__))
    plan_body, index_body, summary_body = read(args.plan, True), read(PACKET / "index.json"), read(SUMMARY)
    assert (sha(plan_body), sha(index_body), sha(summary_body)) == (args.plan_sha256, args.index_sha256, args.summary_sha256)
    plan, index, summary = map(parse, (plan_body, index_body, summary_body))
    for value in (plan, index, summary):
        privacy(value)
    assert plan["root_approved"] is True and plan["pending_roles"] == []
    assert plan["approved_limits"] == {"per_file_bytes": 134217728, "packet_uncompressed_bytes": 536870912}
    rows = {row["original_path"]: row for row in plan["files"]}
    indexed = {row["original_path"]: row for row in index["files"]}
    assert len(rows) == len(plan["files"]) and len(indexed) == len(index["files"]) == len(rows) + 1
    assert set(indexed) == set(rows) | {str(args.plan)}
    actual_files = set()
    for path in PACKET.rglob("*"):
        assert not path.is_symlink() and (path.is_dir() or path.is_file())
        if path.is_file():
            actual_files.add(str(path.relative_to(PACKET)))
    assert actual_files == {row["file"] for row in index["files"]} | {"index.json"}
    raw, values, payload_bytes, stored_bytes, gzip_count, json_count, python_count = {}, {}, 0, 0, 0, 0, 0
    for original, row in indexed.items():
        relative = Path(row["file"])
        assert not relative.is_absolute() and ".." not in relative.parts and "\\" not in str(relative)
        assert not DENIED.intersection(relative.parts)
        stored = read(PACKET / relative)
        assert row["encoding"] in {"identity", "gzip"}
        body = gzip.decompress(stored) if row["encoding"] == "gzip" else stored
        assert body == read(row["capture_path"], True) == read(original, True)
        assert row["stored_sha256"] == sha(stored) and row["stored_bytes"] == len(stored)
        assert row["original_sha256"] == row["decoded_sha256"] == sha(body)
        assert row["original_bytes"] == row["decoded_bytes"] == len(body) <= 134217728
        if original == str(args.plan):
            assert row["file"] == "approved-plan.json" and body == plan_body
        else:
            selected = rows[original]
            assert row["capture_path"] == selected["capture_path"]
            assert row["original_sha256"] == selected["sha256"] and row["original_bytes"] == selected["bytes"]
            assert row["kind"] == selected["kind"] and row["classification"] == selected["classification"]
            assert row["file"] == selected["destination"] + (".gz" if row["encoding"] == "gzip" else "")
        assert not body.startswith((b"MZ", b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xce", b"\x7fELF"))
        if row["kind"] == "json":
            values[original] = parse(body)
            privacy(values[original])
            json_count += 1
        elif row["kind"] == "source":
            ast.parse(body, filename=original)
            python_count += 1
        elif row["kind"] == "synthetic-fixture":
            assert body.startswith(b"PK\x03\x04")
        if row["encoding"] == "gzip":
            assert len(body) >= 65536 and stored[4:8] == bytes(4)
            gzip_count += 1
        else:
            assert original == str(args.plan) or len(body) < 65536
        raw[original] = body
        payload_bytes += len(body)
        stored_bytes += len(stored)
    total = payload_bytes + len(index_body) + len(summary_body)
    assert total <= 536870912
    assert index["semantic_review"] == plan["semantic_review"] and index["capsule_custody"] == plan["capsule_custody"]
    assert summary["passed"] is True and summary["source_identity"] == {"commit": COMMIT, "revision": REVISION, "native_sha256": NATIVE}
    assert summary["independent_publication_audit_required"] is True and summary["independent_publication_audit_completed_by_collector"] is False
    assert summary["evidence"]["index_sha256"] == args.index_sha256 and summary["evidence"]["plan_sha256"] == args.plan_sha256
    assert summary["evidence"]["indexed_files"] == index["indexed_files"] == len(indexed)
    final_ref = plan["semantic_review"]
    assert final_ref["sha256"] == FINAL_SHA and sha(raw[final_ref["path"]]) == FINAL_SHA
    final = values[final_ref["path"]]
    assert final["passed"] is True and final["pending_roles"] == [] and len(final["roles"]) == 17
    role_values = {}
    for name, desc in final["roles"].items():
        assert sha(raw[desc["path"]]) == desc["sha256"] and len(raw[desc["path"]]) == desc["bytes"]
        role_values[name] = values[desc["path"]]
        assert role_values[name]["passed"] is True
    assert final["roles"]["installed_physical_audit"]["sha256"] == PHYSICAL_SHA
    for name, total_count in (("stage_fem", 419), ("stage_gui", 9), ("stage_native", 9),
            ("installed_fem", 419), ("installed_gui", 9), ("installed_native", 9), ("installed_capacity", 2), ("installed_cold", 2)):
        execution = role_values[name]
        run = Path(final["roles"][name]["path"]).parent
        identity, manifest = values[str(run / "identity.json")], values[str(run / "manifest.json")]
        log = raw[str(run / "run.log")].decode()
        assert sha(raw[str(run / "identity.json")]) == execution["identity_sha256"]
        assert sha(raw[str(run / "manifest.json")]) == execution["manifest_sha256"] == identity["manifest_sha256"]
        assert sha(raw[str(run / "run.log")]) == execution["log_sha256"]
        assert identity["runtime"][3] == REVISION and identity["runtime"][-1] == COMMIT
        assert manifest["expected_count"] == total_count and identity["selected_suite"]["count"] == total_count - 1
        assert re.findall(r"^Ran (\d+) tests? in [\d.]+s$", log, re.M) == [str(total_count)]
        assert len(re.findall(r"^OK$", log, re.M)) == 1 and execution["skipped_lines"] == []
        for test_id in identity["selected_suite"]["ids"]:
            hits = re.findall("^" + re.escape(test_id.rsplit(".", 1)[-1]) + r" \(" + re.escape(test_id) + r"\)([^\n]*)$", log, re.M)
            assert len(hits) == 1 and "skipped" not in hits[0]
    capsule = values[plan["capsule_custody"]["path"]]
    source_root, copy_root = Path(capsule["source_witness_directory"]), Path(capsule["copy_directory"])
    assert capsule["passed"] is True and capsule["copies_exact"] is True and capsule["originals_unchanged"] is True
    assert len(capsule["files"]) == 20 and capsule["files"] == plan["synthetic_file_approvals"]
    capacity = role_values["installed_capacity"]
    capacity_run = Path(final["roles"]["installed_capacity"]["path"]).parent
    prefixes = re.findall(r"^Native capacity evidence: ([^\r\n]+)$", raw[str(capacity_run / "run.log")].decode(), re.M)
    assert len(prefixes) == 1 and Path(prefixes[0]).is_relative_to(ROOT / "installed-capacity/freecad_user_temp")
    assert source_root == Path(prefixes[0]) / "witness" and capacity["capacity_witness"]["directory"] == str(source_root)
    witness = role_values["installed_witness"]
    assert capacity["capacity_witness"]["witness_receipt_sha256"] == final["roles"]["installed_witness"]["sha256"]
    for leaf in capsule["files"]:
        source, copy = str(source_root / leaf["path"]), str(copy_root / leaf["path"])
        assert leaf["source"] == source and source in rows and rows[source]["capture_path"] == copy
        assert sha(raw[source]) == leaf["sha256"] and len(raw[source]) == leaf["bytes"]
        if leaf["path"] != "witness-receipt.json":
            assert witness["retained_files"][leaf["path"]] == {key: leaf[key] for key in ("sha256", "bytes")}
    omitted = capsule["omitted_witness_files"]
    selected_names, omitted_names = {row["path"] for row in capsule["files"]}, {row["path"] for row in omitted}
    assert len(omitted) == len(omitted_names) == 7 and selected_names.isdisjoint(omitted_names)
    assert set(witness["retained_files"]) == (selected_names - {"witness-receipt.json"}) | omitted_names
    assert index["whole_witness_retention_claimed"] is False
    assert index["omitted_witness_files"] == [{"original_path": str(source_root / row["path"]), **row} for row in sorted(omitted, key=lambda row: str(source_root / row["path"]))]
    for leaf in omitted:
        path = source_root / leaf["path"]
        assert leaf["scope"] and str(path) not in rows
        assert witness["retained_files"][leaf["path"]] == {key: leaf[key] for key in ("sha256", "bytes")}
        body = read(path, True)
        assert sha(body) == leaf["sha256"] and len(body) == leaf["bytes"]
    cold_run = Path(final["roles"]["installed_cold"]["path"]).parent
    cold, literal = role_values["installed_cold_receipt"], values[str(source_root / "cold-case.json")]
    cold_manifest = values[str(cold_run / "manifest.json")]
    assert cold["manifest"] == cold_manifest["cold_manifest"] == str(source_root / "cold-case.json")
    assert cold["manifest_sha256"] == cold_manifest["cold_manifest_sha256"] == sha(raw[cold["manifest"]])
    assert cold["status"].startswith("Stale") and all(cold[key] is True for key in ("no_native_solve", "no_save", "no_history_or_provenance_repair"))
    assert sha(raw[literal["document"]]) == literal["document_sha256"]
    for desc in literal["source_files"].values():
        assert sha(raw[desc["path"]]) == desc["sha256"]
    assert witness["physical_check_count"] == len(witness["checks"]) == len({row["name"] for row in witness["checks"]}) == 3566
    for check in witness["checks"]:
        error = math.dist(check["actual"], check["reference"])
        assert check["passed"] is True and check["limit"] in (.01, .05)
        assert math.isclose(error, check["error_norm"], rel_tol=1e-12, abs_tol=1e-12)
        assert error <= check["limit"] * check["scale"]
    for path in READS.copy():
        read(path)
    final_files = set()
    for path in PACKET.rglob("*"):
        assert not path.is_symlink() and (path.is_dir() or path.is_file())
        if path.is_file():
            final_files.add(str(path.relative_to(PACKET)))
    assert final_files == actual_files
    return {"schema": "FreeCAD-3q7-installation-independent-published-packet-file-audit-v1", "passed": True,
        "plan": READS[str(args.plan)], "index": READS[str(PACKET / "index.json")], "summary": READS[str(SUMMARY)],
        "indexed_files": len(indexed), "selected_originals": len(rows), "strict_JSON_privacy_bodies": json_count,
        "Python_AST_bodies": python_count, "gzip_bodies": gzip_count, "uncompressed_packet_bytes": total,
        "stored_payload_bytes": stored_bytes, "all_original_capture_stored_decoded_bytes_and_end_fences_exact": True,
        "all17_actual_role_descriptors_and8_raw_app_test_counts_checked": True,
        "exact20_case_copies_and7_hash_only_omissions": True, "fresh_installed_witness_and_separate_cold_literal_links": True,
        "stage132_or_new_performance_or_engineering_acceptance_claimed": False,
        "live_app_profile_inventory_or_runtime_binary_read": False,
        "scope": "Independent artifact/publication audit, not new runtime qualification or another native solve. Full independent physical graph/DAT/FRD/numerical audit is retained as exact7c61cc... role.",
        "authorship": "Reviewer authored deployment adapters/final file auditors and some source mutation guards, not collector/preparer/immutable staging core/native producer/frozen oracle.",
        "input_descriptors": READS}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("plan", "report"):
        parser.add_argument("--" + flag, type=Path, required=True)
    for flag in ("plan-sha256", "index-sha256", "summary-sha256"):
        parser.add_argument("--" + flag, required=True)
    args = parser.parse_args()
    assert not sys.flags.optimize and args.report.parent == ROOT / "collection" and not args.report.exists()
    assert args.plan.parent == ROOT / "collection"
    result = audit(args)
    with args.report.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"passed": True, "report": str(args.report), "sha256": sha(args.report.read_bytes()), "indexed_files": result["indexed_files"]}))
