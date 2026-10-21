"""Independent stdlib-only post-publication byte/privacy/container review.

No FreeCAD/product imports, native execution, test execution or collector calls.
All evidence bodies and originals are read-only; the report is new-only and
outside the immutable published packet.
"""

import gzip
import hashlib
import json
from pathlib import Path

TASK = Path("/private/tmp/freecad-3q7-Pq3Byy")
REPO = Path("/Users/zukomgwili/src/FreeCAD")
PACKET = REPO / "package/local-completion/freecad-3q7-source-evidence"
SUMMARY = REPO / "package/local-completion/freecad-3q7-validation.json"
PLAN = TASK / "collection/final-approved-plan-r03.json"
INDEX_SHA = "fab31e33436e371cf8f78d88da4710b8d189c553708f0f8c2a6e146f93f98c82"
SUMMARY_SHA = "7fc21961b3035fc0f9ea99c39946f808f60ffb6b9bc928111dc0764cee55386c"
PLAN_SHA = "bbb68ac688c60b8777ee746bc29b7c5e35d546b3c547d013429cd10bddb2216d"
SEEN = {}
RAW_KEYS = {"environment", "environ", "profiles", "profile_inventories", "profile_inventory",
            "app_inventory", "application_inventory", "inventory", "critical_before", "critical_after"}
SECRETS = {"password", "api_key", "apikey", "secret", "access_token", "refresh_token", "authorization", "cookie"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    path = Path(path)
    assert path.is_file() and not any(part.is_symlink() for part in (path, *path.parents)), path
    data = path.read_bytes()
    desc = {"path": str(path), "bytes": len(data), "sha256": sha(data)}
    assert SEEN.setdefault(str(path), desc) == desc, path
    return data


def pairs(items):
    value = {}
    for key, child in items:
        assert key not in value
        value[key] = child
    return value


def parse(data):
    return json.loads(data, object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(AssertionError(value)))


def privacy(value):
    if isinstance(value, dict):
        keys = {str(key).lower() for key in value}
        assert not keys & (RAW_KEYS | SECRETS)
        assert not (isinstance(value.get("."), dict) and value["."].get("kind") == "dir")
        assert not {"dev", "inode", "mtime_ns", "ctime_ns"} <= keys
        assert not {"sha256", "mode", "size", "mtime_ns", "target"} <= keys
        for child in value.values():
            privacy(child)
    elif isinstance(value, list):
        for child in value:
            privacy(child)


def audit():
    plan_bytes = read(PLAN)
    index_bytes = read(PACKET / "index.json")
    summary_bytes = read(SUMMARY)
    assert (sha(plan_bytes), sha(index_bytes), sha(summary_bytes)) == (PLAN_SHA, INDEX_SHA, SUMMARY_SHA)
    plan, index, summary = map(parse, (plan_bytes, index_bytes, summary_bytes))
    for value in (plan, index, summary):
        privacy(value)
    assert plan["root_approved"] is True
    assert plan["approved_limits"] == {"packet_uncompressed_bytes": 536870912, "per_file_bytes": 134217728}
    assert summary["passed"] is True and summary["publication"] == {
        "independent_audit_required": True, "independent_audit_completed_by_collector": False}
    assert index["indexed_files"] == summary["evidence"]["indexed_files"] == len(index["files"]) == 308
    assert summary["evidence"]["index_sha256"] == INDEX_SHA
    assert summary["evidence"]["plan_sha256"] == PLAN_SHA
    assert summary["evidence"]["directory"] == str(PACKET.relative_to(REPO))
    rows = {row["path"]: row for row in plan["files"]}
    indexed = {row["original_path"]: row for row in index["files"]}
    assert len(rows) == 307 and len(indexed) == 308 and set(indexed) == set(rows) | {str(PLAN)}
    assert len({row["file"] for row in index["files"]}) == 308
    actual_paths = set()
    for path in PACKET.rglob("*"):
        assert not path.is_symlink()
        assert path.is_file() or path.is_dir()
        if path.is_file():
            actual_paths.add(str(path.relative_to(PACKET)))
    assert actual_paths == {row["file"] for row in index["files"]} | {"index.json"}
    values, payload, stored, json_count, gzip_count = {}, 0, 0, 0, 0
    for original, row in indexed.items():
        relative = Path(row["file"])
        assert not relative.is_absolute() and ".." not in relative.parts and "\\" not in row["file"]
        encoded = read(PACKET / relative)
        assert row["encoding"] in {"gzip", "identity"}
        decoded = gzip.decompress(encoded) if row["encoding"] == "gzip" else encoded
        source = read(original)
        assert source == decoded
        assert row["stored_sha256"] == sha(encoded) and row["stored_bytes"] == len(encoded)
        assert row["original_sha256"] == row["decoded_sha256"] == sha(decoded)
        assert row["original_bytes"] == row["decoded_bytes"] == len(decoded) <= 134217728
        assert row["transformation"] == "exact bytes"
        if original == str(PLAN):
            assert row["file"] == "approved-plan.json" and decoded == plan_bytes
        else:
            planned = rows[original]
            assert row["kind"] == planned["kind"] and row["classification"] == planned["classification"]
            assert row["original_sha256"] == planned["sha256"] and row["original_bytes"] == planned["bytes"]
            assert row["file"] == planned["destination"] + (".gz" if row["encoding"] == "gzip" else "")
        if row["kind"] == "json":
            value = parse(decoded)
            privacy(value)
            values[original] = value
            json_count += 1
        if row["encoding"] == "gzip":
            gzip_count += 1
            assert len(decoded) >= 65536 and encoded[4:8] == bytes(4)
        else:
            assert original == str(PLAN) or len(decoded) < 65536
        payload += len(decoded)
        stored += len(encoded)
    assert payload == index["uncompressed_payload_bytes"] == summary["evidence"]["uncompressed_payload_bytes"] == 379854055
    total = payload + len(index_bytes) + len(summary_bytes)
    assert total == 380114772 < 536870912
    assert index["hash_only_references"] == plan["hash_only_references"] and len(plan["hash_only_references"]) == 3
    for reference in plan["hash_only_references"]:
        assert reference["path"] not in indexed and reference["scope"]
        original = read(reference["path"])
        assert sha(original) == reference["sha256"] and len(original) == reference["bytes"]
    assert index["qualification_receipt"] == plan["qualification_receipt"]
    qualified = values[plan["qualification_receipt"]["path"]]
    assert summary["qualification"] == qualified
    assert qualified["passed"] is True and qualified["pending_roles"] == []
    assert len(qualified["roles"]) == 30
    assertions = 0
    for role, desc in qualified["roles"].items():
        assert {key: indexed[desc["path"]]["original_" + key] for key in ("bytes", "sha256")} == {
            key: desc[key] for key in ("bytes", "sha256")}
        value = values[desc["path"]]
        assert value["passed"] is qualified["role_expectations"][role]
        for check in qualified["role_checks"][role]:
            actual = value
            for part in check["pointer"][1:].split("/"):
                part = part.replace("~1", "/").replace("~0", "~")
                actual = actual[int(part)] if isinstance(actual, list) else actual[part]
            assert type(actual) is type(check["equals"]) and actual == check["equals"]
            assertions += 1
    assert assertions == 248
    for path in SEEN.copy():
        read(path)
    return {"schema": "FreeCAD-3q7-independent-parent-published-container-review-v1", "passed": True,
            "plan": SEEN[str(PLAN)], "index": SEEN[str(PACKET / "index.json")], "summary": SEEN[str(SUMMARY)],
            "indexed_files": 308, "selected_originals": 307, "all_packet_tree_entries_exact": True,
            "all_stored_decoded_original_bytes_and_current_end_fences_exact": True,
            "strict_JSON_privacy_bodies": json_count, "gzip_bodies": gzip_count,
            "all30_role_outcomes_and248_typed_pointers": True,
            "uncompressed_payload_bytes": payload, "uncompressed_packet_bytes": total,
            "stored_payload_bytes": stored, "hash_only_original_references": 3,
            "scope": "Actual published source-only packet, no installation/Oomakhi/engineering qualification. This is a byte/privacy/role-map review, complementary to the independent semantic/numerical r05 audit, not a new native run.",
            "authorship": "Reviewer authored some mutation guards and file auditors, not product implementation, collector, selection generator or native physical producer.",
            "fenced_descriptors": SEEN}


if __name__ == "__main__":
    report = audit()
    output = TASK / "proposals/published-container-parent-review-r01.json"
    with output.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"passed": True, "report": str(output), "sha256": sha(output.read_bytes())}))
