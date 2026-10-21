"""Independent stdlib-only audit of an actual, completed 3q7 evidence packet.

This file is a proposal until explicitly run against a root-approved actual plan
and existing publication. It never imports the collector/product, starts a
process, unmarshals profiles, writes the repository, or reads live build/core.
Only an explicit new private report is written after every check passes.
"""

import argparse
import ast
import hashlib
import json
import math
from pathlib import Path
import re
import zlib


TASK = Path("/private/tmp/freecad-3q7-Pq3Byy")
REPO = Path("/Users/zukomgwili/src/FreeCAD")
BUILD = REPO / "build/release"
NATIVE = "6c02452a896727af6cb4578fd3fb6bbfbdd48e3fb887c1c04fa2d8b171976c66"
PER_FILE, PACKET = 128 * 1024 * 1024, 512 * 1024 * 1024
CAP_AMENDMENT = TASK / "collection/explicit-packet-cap-amendment-r01.json"
CAP_AMENDMENT_SHA = "1499b421b47cff371c25e968bc0f6a47fa3ef218d2481a0e6a325cc754929fdc"
REQUIRED = {"tiny_red_first": False, "tiny_red_second": False, "rejected_large_pair": False,
            "restore_first": True, "restore_second": True, "group_handle_amendment": True,
            "paired_baseline": True, "paired_candidate": True, "full_graph_execution": True,
            "full_graph_witness": True, "cold_execution": True, "cold_receipt": True,
            "fem": True, "gui": True, "guards": True, "ctest": True,
            "source_build": True, "final_review": True}
COUNT_FIELDS = {
    "FreeCAD-yzk-source-run-manifest-v3": "expected_count",
    "FreeCAD-3q7-large-common-runtime-manifest-v1": "selected_tests_including_identity",
    "FreeCAD-3q7-large-common-runtime-manifest-v2": "selected_tests_including_identity",
}
FROZEN = {"coupled_port_capacity_fixture.json": "9142f5aa4d149aa1f0d518a592a78638f9489fb3e245af67ea4fd463e5b8ae22",
          "coupled_port_capacity_oracle.json": "42fa6289fd9e1f80efa56db27c02c06a5454ed9880f7ca61bfd80992dfb251b8"}
DENIED = {".git", ".beads", ".pixi", "__pycache__", "CMakeFiles", "CalculiX", "profiles",
          "module-cache", "freecad_user_home", "freecad_user_data", "freecad_user_temp",
          "xdg_config_home", "xdg_data_home", "xdg_cache_home"}
SUFFIXES = {".cfg", ".pyc", ".pyo", ".so", ".dylib", ".o", ".a", ".exe"}
RAW_KEYS = {"environment", "environ", "profiles", "profile_inventories", "profile_inventory",
            "app_inventory", "application_inventory", "inventory", "critical_before", "critical_after"}
SECRET_KEYS = {"password", "api_key", "apikey", "secret", "access_token", "refresh_token", "authorization", "cookie"}
KINDS = {"json", "source", "text", "native-input", "native-output", "mesh-snapshot", "profile-data", "synthetic-fixture"}
MAGIC = {b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xce",
         b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca", b"\x7fELF"}
CASE_REQUIRED = {"coupled-before-export.FCStd", "coupled-native-current.FCStd", "witness-receipt.json",
                 "cold-case.json", "native-accounting-data.json", "native/Mesh.inp", "native/Mesh.accounting",
                 "native/Mesh.accounting.out", "native/Mesh.dat", "native/Mesh.frd"}
CASE_ALLOWED = CASE_REQUIRED | {"independent-export-audit.json", "physical-face-motion-proof.json",
    "motion-from-original-dat.json", "geometry-contract.json", "export-properties.json", "native-properties.json",
    "mesh-membership.json", "native.stdout", "native.stderr", "native/Mesh.accounting.json"}
READS = {}


def need(value, message):
    if not value:
        raise AssertionError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def describe(raw):
    return {"sha256": digest(raw), "bytes": len(raw)}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def unique(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, "Duplicate JSON key: " + key)
        result[key] = value
    return result


def parse(raw):
    return json.loads(raw, object_pairs_hook=unique, parse_constant=lambda value: (_ for _ in ()).throw(
        AssertionError("Nonfinite JSON constant: " + value)))


def safe_file(path, copied=False):
    path = Path(path)
    need(path.is_absolute() and ".." not in path.parts and not path.is_relative_to(BUILD),
         "Noncanonical path or forbidden live build/core read: " + str(path))
    roots = [root for root in (TASK, REPO) if path.is_relative_to(root)]
    need(len(roots) == 1, "Read outside private task/repository evidence: " + str(path))
    cursor = path
    while cursor != roots[0]:
        need(not cursor.is_symlink(), "Symlink in file ancestry: " + str(cursor))
        cursor = cursor.parent
    need(path.is_file(), "Missing regular evidence file: " + str(path))
    if copied:
        need(not DENIED.intersection(path.relative_to(roots[0]).parts)
             and not path.name.startswith("private-") and path.name not in {".env", "user.cfg", "system.cfg"}
             and path.suffix.lower() not in SUFFIXES, "Forbidden copied payload path: " + str(path))
    return path


def read(path, copied=False):
    path = safe_file(path, copied)
    raw = path.read_bytes()
    need(READS.setdefault(str(path), describe(raw)) == describe(raw), "Read bytes changed: " + str(path))
    return raw


def descriptor(ref):
    need(type(ref) is dict and set(ref) == {"path", "sha256", "bytes"}
         and type(ref["path"]) is str and type(ref["bytes"]) is int and ref["bytes"] >= 0
         and type(ref["sha256"]) is str and re.fullmatch("[0-9a-f]{64}", ref["sha256"]), "Bad exact descriptor")


def bound(raw, ref):
    descriptor(ref)
    need(ref["path"] in raw and describe(raw[ref["path"]]) == {key: ref[key] for key in ("sha256", "bytes")},
         "Reference not bound to exact indexed bytes: " + ref["path"])
    return raw[ref["path"]]


def privacy(value):
    if type(value) is dict:
        keys = {str(key).lower() for key in value}
        need(not (RAW_KEYS | SECRET_KEYS).intersection(keys), "Raw inventory/environment/secret key")
        need(not (type(value.get(".")) is dict and value["."].get("kind") == "dir"), "Raw profile/app tree")
        need(not {"dev", "inode", "mtime_ns", "ctime_ns"} <= keys, "Raw dependency stat inventory")
        need(not {"sha256", "mode", "size", "mtime_ns", "target"} <= keys, "Raw dependency inventory")
        for item in value.values():
            privacy(item)
    elif type(value) is list:
        for item in value:
            privacy(item)


def pointer(value, path):
    need(type(path) is str and path.startswith("/") and path != "/", "Bad explicit JSON pointer")
    for token in path[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if type(value) is list:
            need(re.fullmatch("0|[1-9][0-9]*", token), "Bad list pointer")
            value = value[int(token)]
        else:
            need(type(value) is dict and token in value, "Missing pointer component: " + path)
            value = value[token]
    return value


def profile_bindings(raw):
    bindings = set()
    def visit(value):
        if type(value) is dict:
            if set(value) == {"path", "sha256", "bytes"} and type(value.get("path")) is str:
                if Path(value["path"]).name in {"whole-public-write.prof", "whole-write.prof"}:
                    descriptor(value)
                    bindings.add((value["path"], value["sha256"], value["bytes"]))
            for item in value.values():
                visit(item)
        elif type(value) is list:
            for item in value:
                visit(item)
    for name, data in raw.items():
        if Path(name).name in {"execution.json", "observation.json", "export-profile.json"}:
            visit(parse(data))
    return bindings


def scope_and_roles(plan, summary, raw, implementation_commit, final_product_commit):
    qualified = parse(bound(raw, plan["qualification_receipt"]))
    need(qualified["schema"] == "FreeCAD-3q7-source-qualification-v1" and qualified["passed"] is True
         and qualified["pending_roles"] == [], "Qualification is incomplete or prospective")
    need(canonical(summary["qualification"]) == canonical(qualified), "Summary qualification differs")
    identity = qualified["source_identity"]
    need(identity["implementation_commit"] == implementation_commit
         and identity["final_product_commit"] == final_product_commit
         and identity["diagnostic_only_followup_commit"] == final_product_commit
         and identity["default_native_sha256"] == NATIVE
         and type(identity["compiled_revision"]) is str and identity["compiled_revision"], "Actual source/native identity differs")
    scope = qualified["scope"]
    expected_scope = {"source_only": True, "installation_performed": False, "Oomakhi_accessed_or_solved": False,
        "engineering_or_BIM_accepted": False, "R49_R51_acceptance_claimed": False,
        "no_timing_SLA_or_universal_scaling_claim": True, "historical_failed_pair_remains_failed": True,
        "force_original_origin_moment_limit": .01, "scalar_response_limit": .05}
    for key, expected in expected_scope.items():
        need(type(scope[key]) is type(expected) and scope[key] == expected, "Scope changed: " + key)
    roles, expectations, checks = (qualified[key] for key in ("roles", "role_expectations", "role_checks"))
    need(REQUIRED.keys() <= roles.keys() and roles.keys() == expectations.keys() == checks.keys(), "Role sets incomplete")
    need(all(expectations[key] is expected for key, expected in REQUIRED.items()), "Historical/final outcome changed")
    case_custody = parse(bound(raw, plan["synthetic_capsule"]))
    values, counts = {}, {}
    for name, ref in roles.items():
        value = parse(bound(raw, ref))
        need(type(expectations[name]) is bool and value["passed"] is expectations[name], "Role verdict differs: " + name)
        need(type(checks[name]) is list and checks[name], "Missing explicit semantic checks: " + name)
        for check in checks[name]:
            need(set(check) == {"pointer", "equals"}, "Bad semantic check")
            actual = pointer(value, check["pointer"])
            need(type(actual) is type(check["equals"]) and canonical(actual) == canonical(check["equals"]),
                 "Role semantic assertion differs: " + name + check["pointer"])
        for ref_output in value.get("produced_outputs", {}).values():
            bound(raw, ref_output)
        if expectations[name] and "returncode" in value:
            need(value["returncode"] == 0 and value["timed_out"] is False
                 and value["child_reaped"] is True and value["process_group_gone"] is True, "Role process failed: " + name)
        manifest = None
        if "manifest_sha256" in value:
            if value.get("schema") == "FreeCAD-yzk-portable-cold-receipt-v1":
                need(value["manifest"] == str(Path(case_custody["source_witness_directory"]) / "cold-case.json"),
                     "Literal cold-receipt manifest path differs")
                manifest_path = str(Path(case_custody["copy_directory"]) / "cold-case.json")
            else:
                manifest_path = str(Path(ref["path"]).parent / "manifest.json")
            need(manifest_path in raw and value["manifest_sha256"] == digest(raw[manifest_path]),
                 "Gate manifest binding differs: " + name)
            manifest = parse(raw[manifest_path])
        if "unittest_counts" in value:
            need(len(value["unittest_counts"]) == 1, "Ambiguous unittest count: " + name)
            reported = value["unittest_counts"][0][0]
            actual_count = int(reported)
            need(manifest is not None and manifest.get("schema") in COUNT_FIELDS,
                 "Unknown or absent unittest-count manifest schema: " + name)
            count_field = COUNT_FIELDS[manifest["schema"]]
            expected_count = manifest[count_field]
            need(type(expected_count) is int and expected_count > 0
                 and (count_field != "selected_tests_including_identity" or expected_count == 2),
                 "Bad schema-specific expected test count: " + name)
            counts[name] = {"reported_actual": reported, "actual": actual_count,
                            "manifest_expected": expected_count, "expected_outcome": expectations[name],
                            "manifest_schema": manifest["schema"], "manifest_count_field": count_field,
                            "actual_outcome": value["passed"], "matched_expected_count": actual_count == expected_count}
            if expectations[name]:
                need(manifest is not None and actual_count == expected_count, "Successful gate count differs: " + name)
            else:
                # A truthful rejected selection may have run nine tests when
                # its manifest expected two. Retain both facts; the explicit
                # root semantic assertion, never a relabelled PASS, binds it.
                need(any(check["pointer"] == "/unittest_counts/0/0"
                         and type(check["equals"]) is type(reported) and check["equals"] == reported
                         for check in checks[name]), "Historical negative count lacks an exact root assertion: " + name)
        values[name] = value
    return qualified, values, counts


def capsule_links(plan, qualified, values, raw):
    custody = parse(bound(raw, plan["synthetic_capsule"]))
    need(custody["schema"] == "FreeCAD-3q7-exact-generic-case-capsule-v1" and custody["passed"] is True
         and custody["copies_exact"] is True and custody["originals_unchanged"] is True
         and custody["engineering_project_accessed_or_solved"] is False
         and custody["source_run_execution"] == qualified["roles"]["full_graph_execution"], "Wrong capsule/run")
    source, copied = Path(custody["source_witness_directory"]), Path(custody["copy_directory"])
    need(source.is_relative_to(TASK) and copied.is_relative_to(TASK) and source != copied, "Bad capsule roots")
    rows = custody["files"]
    by_name = {row["path"]: row for row in rows}
    approved = {row["path"]: row for row in plan["synthetic_file_approvals"]}
    need(len(by_name) == len(rows) == len(approved) == len(plan["synthetic_file_approvals"])
         and CASE_REQUIRED <= by_name.keys() <= CASE_ALLOWED and canonical(by_name) == canonical(approved), "Capsule approvals differ")
    witness = values["full_graph_witness"]
    allowed = set()
    for name, row in by_name.items():
        need(set(row) == {"source", "path", "sha256", "bytes"} and row["source"] == str(source / name), "Bad capsule leaf")
        copy_path = str(copied / name)
        need(copy_path in raw and describe(raw[copy_path]) == {key: row[key] for key in ("sha256", "bytes")}
             and read(source / name) == raw[copy_path], "Capsule/original byte mismatch: " + name)
        if name != "witness-receipt.json":
            need(witness["retained_files"][name] == {key: row[key] for key in ("sha256", "bytes")}, "Unbound native leaf")
        allowed.add(copy_path)
    need(bound(raw, qualified["roles"]["full_graph_witness"]) == raw[str(copied / "witness-receipt.json")], "Qualified witness is another copy")
    need(witness["case"] == "capacity" and witness["frozen_oracle_sha256"] == FROZEN
         and witness["rows_y"] == 11 and witness["columns_z"] == 12 and witness["physical_check_count"] == 3566
         and len(witness["checks"]) == 3566 and len({row["name"] for row in witness["checks"]}) == 3566
         and witness["actual_binary_sha256"] == NATIVE and witness["solver_returncode"] == 0, "Wrong complete fresh witness")
    for row in witness["checks"]:
        actual, target = row["actual"], row["reference"]
        need(len(actual) == len(target) == 3 and all(type(v) in (int, float) and math.isfinite(v) for v in actual + target), "Invalid physical vector")
        norm, error, scale = math.hypot(*target), math.dist(actual, target), row["scale"]
        limit = .05 if row["name"].endswith(("/differential-translation", "/differential-rotation")) else .01
        need(type(scale) in (int, float) and math.isfinite(scale) and scale > 0
             and row["limit"] == limit and row["passed"] is True and error <= limit * scale
             and math.isclose(norm, row["reference_norm"], rel_tol=2e-12, abs_tol=1e-15)
             and (not norm or math.isclose(scale, norm, rel_tol=2e-12, abs_tol=1e-15))
             and math.isclose(error, row["error_norm"], rel_tol=2e-12, abs_tol=1e-15)
             and math.isclose(error / scale, row["relative_error"], rel_tol=2e-12, abs_tol=1e-15), "Physical arithmetic differs")
    run_root = Path(qualified["roles"]["full_graph_execution"]["path"]).parent
    log = raw[str(run_root / "run.log")]
    need(digest(log) == values["full_graph_execution"]["log_sha256"], "Fresh physical log binding differs")
    prefixes = re.findall(rb"Native capacity evidence: ([^\r\n]+)", log)
    need(len(prefixes) == 1 and Path(prefixes[0].decode().strip()) / "witness" == source
         and source.is_relative_to(run_root / "freecad_user_temp"), "Qualified witness is not fresh physical run output")
    cold = parse(raw[str(copied / "cold-case.json")])
    receipt = values["cold_receipt"]
    need(receipt["manifest"] == str(source / "cold-case.json") and receipt["manifest_sha256"] == by_name["cold-case.json"]["sha256"]
         and cold["document"] == str(source / "coupled-native-current.FCStd")
         and cold["document_sha256"] == by_name["coupled-native-current.FCStd"]["sha256"]
         and receipt["status"].startswith("Stale")
         and all(receipt[key] is True for key in ("no_native_solve", "no_save", "no_history_or_provenance_repair")), "Cold literal history differs")
    cold_root = Path(qualified["roles"]["cold_execution"]["path"]).parent
    cold_manifest = parse(raw[str(cold_root / "manifest.json")])
    need(cold_manifest["cold_manifest"] == {"path": receipt["manifest"], "sha256": receipt["manifest_sha256"]}
         and values["cold_execution"]["manifest_sha256"] == digest(raw[str(cold_root / "manifest.json")]), "Cold execution used another manifest")
    need(set(cold["source_files"]) == {"dat", "deck", "frd", "native_output", "request"}, "Wrong literal native source set")
    for key, leaf in {"dat": "Mesh.dat", "deck": "Mesh.inp", "frd": "Mesh.frd", "native_output": "Mesh.accounting.out", "request": "Mesh.accounting"}.items():
        need(cold["source_files"][key] == {"path": str(source / "native" / leaf), "sha256": by_name["native/" + leaf]["sha256"]}, "Cold native path/hash rebound")
    return allowed, len(rows)


def audit(args):
    read(Path(__file__))
    cap_raw = read(CAP_AMENDMENT, copied=True)
    amendment = parse(cap_raw)
    need(digest(cap_raw) == CAP_AMENDMENT_SHA
         and amendment["schema"] == "FreeCAD-3q7-explicit-evidence-packet-cap-amendment-v1"
         and amendment["root_approved"] is True and amendment["passed"] is True
         and amendment["old_packet_cap_bytes"] == 256 * 1024 * 1024
         and amendment["new_packet_cap_bytes"] == PACKET
         and amendment["per_file_bytes_unchanged"] == PER_FILE
         and amendment["final_plan_approved_by_this_amendment"] is False, "Packet-cap amendment differs")
    need(re.fullmatch("[0-9a-f]{40}", args.implementation_commit)
         and re.fullmatch("[0-9a-f]{40}", args.final_product_commit)
         and re.fullmatch("[0-9a-f]{64}", args.plan_sha256), "Exact approval hashes required")
    need(args.plan.parent == TASK / "collection", "Only an explicit private collection plan may qualify")
    plan_raw = read(args.plan, copied=True)
    need(digest(plan_raw) == args.plan_sha256, "Approved plan bytes changed")
    plan = parse(plan_raw)
    need(plan["schema"] == "FreeCAD-3q7-approved-source-evidence-plan-v1" and plan["root_approved"] is True
         and plan["approved_limits"] == {"per_file_bytes": PER_FILE, "packet_uncompressed_bytes": PACKET}, "Plan not approved at fixed caps")
    packet = Path(args.packet)
    need(packet == REPO / "package/local-completion/freecad-3q7-source-evidence"
         and Path(args.summary) == REPO / "package/local-completion/freecad-3q7-validation.json", "Wrong actual publication paths")
    index_raw, summary_raw = read(packet / "index.json", copied=True), read(args.summary, copied=True)
    index, summary = parse(index_raw), parse(summary_raw)
    need(index["schema"] == "FreeCAD-3q7-source-evidence-index-v1" and summary["schema"] == "FreeCAD-3q7-source-validation-v1"
         and summary["passed"] is True and summary["evidence"]["index_sha256"] == digest(index_raw)
         and summary["evidence"]["plan_sha256"] == args.plan_sha256, "Actual summary/index binding differs")
    rows = plan["files"]
    need(len(rows) == len({row["path"] for row in rows}) == len({row["destination"] for row in rows}), "Duplicate plan paths")
    expected = {row["destination"] + (".gz" if row["bytes"] >= 65536 else ""): row for row in rows}
    need(len(expected) == len(rows) and "approved-plan.json" not in expected and "index.json" not in expected, "Transformed collisions")
    indexed = index["files"]
    need(len(indexed) == index["indexed_files"] == summary["evidence"]["indexed_files"] == len(rows) + 1
         and [row["file"] for row in indexed] == sorted({row["file"] for row in indexed}), "Index count/order duplicates")
    need({row["file"] for row in indexed} == set(expected) | {"approved-plan.json"}, "Index/plan coverage differs")
    initial_paths = {str(path.relative_to(packet)) for path in packet.rglob("*") if path.is_file()}
    need(initial_paths == set(expected) | {"approved-plan.json", "index.json"}
         and not any(path.is_symlink() for path in packet.rglob("*")), "Packet coverage/symlinks differ")
    raw, gzip_count = {}, 0
    for row in indexed:
        target = Path(row["file"])
        need(not target.is_absolute() and ".." not in target.parts and target.as_posix() == row["file"]
             and "\\" not in row["file"] and not DENIED.intersection(target.parts), "Unsafe indexed name")
        original = str(args.plan) if row["file"] == "approved-plan.json" else expected[row["file"]]["path"]
        need(row["original_path"] == original and row["transformation"] == "exact bytes"
             and type(row["original_bytes"]) is int and 0 <= row["original_bytes"] <= PER_FILE, "Bad indexed original")
        stored = read(packet / row["file"], copied=True)
        need(describe(stored) == {"sha256": row["stored_sha256"], "bytes": row["stored_bytes"]}, "Stored bytes differ")
        need(row["encoding"] == ("identity" if row["file"] == "approved-plan.json" or row["original_bytes"] < 65536 else "gzip"), "Unexpected encoding")
        if row["encoding"] == "gzip":
            need(stored[:4] == b"\x1f\x8b\x08\x00" and stored[4:8] == b"\x00" * 4, "Gzip is not nameless mtime0")
            decoder = zlib.decompressobj(31)
            decoded = decoder.decompress(stored, row["original_bytes"] + 1)
            need(decoder.eof and not decoder.unconsumed_tail and not decoder.unused_data, "Incomplete/multiple/oversize gzip stream")
            gzip_count += 1
        else:
            decoded = stored
        need(describe(decoded) == {"sha256": row["original_sha256"], "bytes": row["original_bytes"]}
             == {"sha256": row["decoded_sha256"], "bytes": row["decoded_bytes"]}
             and read(original, copied=True) == decoded, "Original/stored/decoded bytes differ")
        if row["file"] != "approved-plan.json":
            planned = expected[row["file"]]
            need(set(planned) == {"path", "destination", "sha256", "bytes", "kind", "classification"}
                 and row["kind"] == planned["kind"] in KINDS and row["classification"] == planned["classification"]
                 and type(row["classification"]) is str and row["classification"]
                 and row["original_sha256"] == planned["sha256"] and row["original_bytes"] == planned["bytes"], "Index/plan descriptor differs")
        raw[original] = decoded
    requested = sum(len(value) for value in raw.values())
    need(requested == index["uncompressed_payload_bytes"] == summary["evidence"]["uncompressed_payload_bytes"]
         and requested + len(index_raw) + len(summary_raw) <= PACKET, "Payload/whole-packet cap accounting differs")
    need(index["qualification_receipt"] == plan["qualification_receipt"]
         and canonical(index["hash_only_references"]) == canonical(plan["hash_only_references"]), "Plan reference declarations differ")
    hash_only = plan["hash_only_references"]
    need(len(hash_only) == len({row["path"] for row in hash_only}), "Duplicate hash-only references")
    for ref in hash_only:
        need(set(ref) == {"path", "sha256", "bytes", "scope"} and type(ref["scope"]) is str and ref["scope"], "Unscoped hash-only reference")
        descriptor({key: ref[key] for key in ("path", "sha256", "bytes")})
        need(Path(ref["path"]).is_absolute() and ".." not in Path(ref["path"]).parts, "Bad hash-only declaration path")
    qualified, values, counts = scope_and_roles(
        plan, summary, raw, args.implementation_commit, args.final_product_commit)
    allowed, capsule_count = capsule_links(plan, qualified, values, raw)
    bindings = profile_bindings(raw)
    for row in indexed:
        path, data = Path(row["original_path"]), raw[row["original_path"]]
        need(data[:4] not in MAGIC and not data.startswith(b"MZ"), "Runtime binary payload")
        if path.suffix.lower() == ".fcstd":
            need(str(path) in allowed and row["kind"] == "synthetic-fixture" and data.startswith(b"PK\x03\x04"), "Unapproved synthetic archive")
        elif row["kind"] == "profile-data":
            need((str(path), digest(data), len(data)) in bindings, "Unbound opaque profile")
        else:
            if path.suffix.lower() == ".frd":
                need(str(path) in allowed, "Unapproved FRD")
            text = data.decode("utf-8")
            need("\x00" not in text and not re.search(r"(?im)^(?:OPENAI_API_KEY|GITHUB_TOKEN|GH_TOKEN|AWS_SECRET_ACCESS_KEY|PASSWORD|ACCESS_TOKEN|REFRESH_TOKEN)\s*=\s*\S+", text), "Credential/environment text payload")
            if path.suffix == ".json":
                privacy(parse(data))
            elif path.suffix == ".py":
                ast.parse(data, filename=str(path))
    privacy(plan)
    privacy(index)
    privacy(summary)
    for name, wanted in READS.items():
        need(describe(safe_file(name).read_bytes()) == wanted, "Final input/stored-byte fence differs: " + name)
    need(initial_paths == {str(path.relative_to(packet)) for path in packet.rglob("*") if path.is_file()}
         and not any(path.is_symlink() for path in packet.rglob("*")), "Final packet inventory changed")
    return {"schema": "FreeCAD-3q7-independent-published-packet-file-audit-v1", "passed": True,
        "plan": {"path": str(args.plan), **describe(plan_raw)}, "index": describe(index_raw), "summary": describe(summary_raw),
        "indexed_files": len(indexed), "gzip_files": gzip_count, "uncompressed_payload_bytes": requested,
        "uncompressed_packet_bytes": requested + len(index_raw) + len(summary_raw), "capsule_leaves": capsule_count,
        "role_outcomes": qualified["role_expectations"],
        "actual_unittest_counts": {name: row["actual"] for name, row in counts.items()},
        "unittest_count_observations": counts,
        "packet_cap_amendment": {"path": str(CAP_AMENDMENT), **describe(cap_raw)},
        "per_file_cap_bytes": PER_FILE, "packet_cap_bytes": PACKET,
        "source_identity": qualified["source_identity"], "all_original_stored_decoded_bytes_and_final_inventory_fenced": True,
        "all_actual_role_pointer_assertions_type_checked": True, "fresh_physical_and_literal_cold_links_checked": True,
        "privacy": "Explicit selected payload/path/magic/structured-key/credential-pattern checks; synthetic FCStd bytes approved and exact, not a universal secrets scanner",
        "hash_only_reference_files_rehashed": False, "live_build_core_or_installed_runtime_read": False,
        "runtime_qualification_claimed_by_this_file_audit": False, "engineering_acceptance_claimed": False,
        "authorship": "Independent auditor author did not author collector/product/physical producer; authored separate private pair comparator and static reviews",
        "input_descriptors": READS}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--implementation-commit", required=True)
    parser.add_argument("--final-product-commit", required=True)
    parser.add_argument("--packet", type=Path, default=REPO / "package/local-completion/freecad-3q7-source-evidence")
    parser.add_argument("--summary", type=Path, default=REPO / "package/local-completion/freecad-3q7-validation.json")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    need(args.report.is_absolute() and args.report.parent.resolve().is_relative_to((TASK / "publication-audit").resolve())
         and not args.report.exists() and not args.report.is_symlink(), "Report must be new and private")
    report = audit(args)
    with args.report.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"passed": True, "report": str(args.report), "sha256": digest(args.report.read_bytes()),
                      "indexed_files": report["indexed_files"], "uncompressed_packet_bytes": report["uncompressed_packet_bytes"]}, sort_keys=True))


if __name__ == "__main__":
    main()
