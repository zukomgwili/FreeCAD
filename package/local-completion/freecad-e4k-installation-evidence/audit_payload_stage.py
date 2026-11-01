"""Root-executed complete-set deployment audits with strict producer admission.

Only a new private report is written by an audit invocation. The module does
not launch FreeCAD or a solver. Root alone executes the audit/signature checks.
Importing admit_producer does not import the deployment adapter or run checks.
Frozen earlier deployment helpers and evidence are never edited.
"""

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import runpy
import stat
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
SCHEMA = "FreeCAD.LOCAL_INSTALL_INDEPENDENT_AUDIT_V2"
MODES = ("payload", "stage", "custody")
REPORTS = {
    "payload": ROOT / "independent-payload-audit.json",
    "stage": ROOT / "independent-stage-audit.json",
    "custody": ROOT / "independent-stage-custody.json",
}
RESOURCES = Path("Contents/Resources")
MACHO = b"\xcf\xfa\xed\xfe"
OTHER_MACHO = {
    b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf",
    b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf",
    b"\xbf\xba\xfe\xca",
}
S = None


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical_sha(value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        assert key not in result, "Duplicate JSON member: " + key
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError("Nonfinite JSON constant: " + value)


def read(path):
    return json.loads(Path(path).read_text(), object_pairs_hook=_unique_pairs,
                      parse_constant=_nonfinite)


def admit_producer(proof, mode, *, commit, revision):
    """Admit only this exact producer, expected role, identity and strict flags.

    This is the shared interface for predecessor, staging, swap and collection
    consumers. It checks producer claims, not actual payload bytes: consumers
    must additionally rebind inventories, source/native parity and hash chains.
    """
    assert mode in MODES, mode
    assert isinstance(proof, dict), "Producer receipt must be an object"
    assert proof.get("schema") == SCHEMA, "Unexpected producer schema"
    assert proof.get("mode") == mode, "Wrong producer role"
    assert proof.get("passed") is True, "Producer did not explicitly pass"
    assert proof.get("helper_sha256") == sha(__file__), "Wrong producer helper"
    if mode == "payload":
        assert proof.get("commit") == commit, "Wrong payload commit"
        assert proof.get("read_only_payload_and_app_unchanged") is True
    elif mode == "stage":
        assert proof.get("source_commit") == commit, "Wrong stage commit"
        assert proof.get("stage_signature_verified") is True
    else:
        assert proof.get("compiled_commit") == commit, "Wrong custody commit"
        assert proof.get("compiled_revision") == revision, "Wrong custody revision"
        for key in ("baseline_and_stage_exact", "strict_signatures_quicklook_readonly_cachefree",
                    "no_live_app"):
            assert proof.get(key) is True, "Missing or false strict flag: " + key
    return proof


def _load_settings():
    global S, REPO, APP, STAGE, PREFIX, BUILD, PAYLOAD_ROOT, PAYLOAD, MANIFEST
    assert S is None, "Deployment settings already loaded"
    S = runpy.run_path(str(ROOT / "stage_install.py"))
    REPO, APP, STAGE, PREFIX = (S[key] for key in ("REPO", "APP", "STAGE", "PREFIX"))
    BUILD = REPO / "build/release"
    PAYLOAD_ROOT = ROOT / "payload"
    PAYLOAD = PAYLOAD_ROOT / APP.relative_to("/") / RESOURCES
    MANIFEST = BUILD / "install_manifest.txt"


def _producer(mode):
    return admit_producer(read(REPORTS[mode]), mode, commit=S["COMMIT"],
                          revision=S["REVISION"])


def regular(path):
    assert stat.S_ISREG(path.lstat().st_mode), path


def native_set(root):
    """Inspect every regular leaf, never follow a directory symlink."""
    result = set()
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [name for name in dirs if not (Path(directory) / name).is_symlink()]
        for name in files:
            path = Path(directory) / name
            if path.is_symlink():
                continue
            regular(path)
            with path.open("rb") as stream:
                magic = stream.read(4)
            assert magic not in OTHER_MACHO, f"Unsupported native format: {path}"
            if magic == MACHO:
                result.add(str(path.relative_to(root)))
    return result


def leaf_set(inventory):
    return {relative for relative, proof in inventory.items() if proof["kind"] != "dir"}


def check_manifest(inventory):
    """The complete DESTDIR leaf set equals the deduplicated install manifest."""
    expected = set()
    allowed_namespace = {PREFIX / relative for relative in S["NAMESPACE_FILES"]}
    for line in MANIFEST.read_text().splitlines():
        path = Path(line)
        assert path.is_absolute() and ".." not in path.parts, line
        assert path.is_relative_to(APP / RESOURCES) or path in allowed_namespace, line
        expected.add(str(path.relative_to("/")))
    assert expected == leaf_set(inventory), {
        "missing": sorted(expected - leaf_set(inventory)),
        "extra": sorted(leaf_set(inventory) - expected),
    }
    return {"path": str(MANIFEST), "sha256": sha(MANIFEST), "unique_leaf_count": len(expected)}


def check_namespace():
    source = PAYLOAD_ROOT / PREFIX.relative_to("/")
    actual = S["inventory"](source)
    assert leaf_set(actual) == S["NAMESPACE_FILES"]
    rows = {}
    for relative in sorted(S["NAMESPACE_FILES"]):
        incoming, live = source / relative, PREFIX / relative
        regular(incoming)
        regular(live)
        parent = live.parent
        while parent != PREFIX:
            assert parent.is_dir() and not parent.is_symlink(), parent
            parent = parent.parent
        assert sha(incoming) == sha(live), relative
        rows[relative] = sha(live)
    return rows


def same_native(left, right, exact_rpaths):
    a, b = S["macho_identity"](left), S["macho_identity"](right)
    assert a["normalized"] == b["normalized"], (left, right)
    if exact_rpaths:
        assert a["rpaths"] == b["rpaths"], (left, right)
    return a, b


def build_candidates(names):
    result = {name: [] for name in names}
    for directory, dirs, files in os.walk(BUILD, followlinks=False):
        dirs[:] = [name for name in dirs if name != "CMakeFiles"
                   and not (Path(directory) / name).is_symlink()]
        for name in set(files).intersection(names):
            path = Path(directory) / name
            if path.is_symlink():
                continue
            regular(path)
            with path.open("rb") as stream:
                if stream.read(4) == MACHO:
                    result[name].append(path)
    return result


def payload_audit():
    before_payload, before_app = S["inventory"](PAYLOAD_ROOT), S["inventory"](APP)
    manifest = check_manifest(before_payload)
    namespace = check_namespace()
    native = native_set(PAYLOAD)
    assert native and "bin/FreeCAD" in native and "bin/FreeCADCmd" in native
    assert "data/NativeSolvers/ccx-force-accounting" in native, sorted(native)
    candidates = build_candidates({Path(relative).name for relative in native})
    rows = []
    for relative in sorted(native):
        path = PAYLOAD / relative
        proof = S["macho_identity"](path)
        matches = []
        for candidate in candidates[path.name]:
            source = S["macho_identity"](candidate)
            if source["normalized"] == proof["normalized"]:
                matches.append({"path": str(candidate.relative_to(BUILD)),
                                "sha256": source["sha256"], "rpaths": source["rpaths"]})
        assert matches, f"No exact normalized build-native match: {relative}"
        rows.append({"relative": relative, "payload_sha256": proof["sha256"],
                     "normalized_sha256": proof["normalized_sha256"],
                     "payload_rpaths": proof["rpaths"], "build_matches": matches})
    for relative, proof in S["inventory"](PAYLOAD).items():
        target = APP / RESOURCES / relative
        parent = target.parent
        while parent != APP:
            assert not parent.is_symlink(), parent
            parent = parent.parent
        if target.is_symlink():
            assert proof["kind"] == "link" and proof["target"] == os.readlink(target), target
    assert S["inventory"](PAYLOAD_ROOT) == before_payload
    assert S["inventory"](APP) == before_app
    assert sha(MANIFEST) == manifest["sha256"]
    return {"commit": S["COMMIT"], "payload_native_count": len(native), "native": rows,
            "native_complete_relative_set_sha256": canonical_sha(sorted(native)),
            "install_manifest": manifest, "payload_inventory_sha256": canonical_sha(before_payload),
            "payload_inventory_entries": len(before_payload),
            "baseline_inventory_sha256": canonical_sha(before_app),
            "external_namespace_sha256": namespace,
            "read_only_payload_and_app_unchanged": True}


def _bind_payload(proof):
    actual = S["inventory"](PAYLOAD_ROOT)
    assert canonical_sha(actual) == proof["payload_inventory_sha256"]
    assert len(actual) == proof["payload_inventory_entries"]
    assert check_manifest(actual) == proof["install_manifest"]
    assert check_namespace() == proof["external_namespace_sha256"]
    native = native_set(PAYLOAD)
    rows = proof["native"]
    assert isinstance(rows, list) and len(rows) == len(native) == proof["payload_native_count"]
    assert native == {row["relative"] for row in rows} and native
    assert canonical_sha(sorted(native)) == proof["native_complete_relative_set_sha256"]
    for row in rows:
        actual_native = S["macho_identity"](PAYLOAD / row["relative"])
        assert actual_native["sha256"] == row["payload_sha256"]
        assert actual_native["normalized_sha256"] == row["normalized_sha256"]
        assert actual_native["rpaths"] == row["payload_rpaths"]
    return actual, native


def cache_or_signature(relative):
    parts = Path(relative).parts
    return "__pycache__" in parts or relative.endswith(".pyc") or "_CodeSignature" in parts


def stage_audit():
    payload_proof = _producer("payload")
    payload_inventory, native = _bind_payload(payload_proof)
    baseline = read(ROOT / "baseline-inventory.json")
    sealed = read(ROOT / "stage-inventory.json")
    assert canonical_sha(baseline) == payload_proof["baseline_inventory_sha256"]
    assert S["inventory"](APP) == baseline and S["inventory"](STAGE) == sealed
    rows = []
    matched_non_native = 0
    for relative in sorted(native):
        before, after = same_native(PAYLOAD / relative, STAGE / RESOURCES / relative, True)
        rows.append({"relative": relative, "payload_sha256": before["sha256"],
                     "stage_sha256": after["sha256"],
                     "normalized_sha256": after["normalized_sha256"], "rpaths": after["rpaths"]})
    for relative, proof in S["inventory"](PAYLOAD).items():
        if proof["kind"] == "dir" or relative in native or cache_or_signature(relative):
            continue
        actual = sealed[str(RESOURCES / relative)]
        assert actual["kind"] == proof["kind"], relative
        expected_mode = proof["mode"] if proof["kind"] == "link" else proof["mode"] & ~0o222
        assert actual["mode"] == expected_mode, relative
        key = "target" if proof["kind"] == "link" else "sha256"
        assert actual[key] == proof[key], relative
        matched_non_native += 1
    stage_native, old_native = native_set(STAGE), native_set(APP)
    payload_in_app = {str(RESOURCES / relative) for relative in native}
    assert stage_native == payload_in_app | (old_native - payload_in_app)
    inherited = []
    for relative in sorted(stage_native - payload_in_app):
        old, new = same_native(APP / relative, STAGE / relative, True)
        inherited.append({"relative": relative, "old_sha256": old["sha256"],
                          "stage_sha256": new["sha256"],
                          "normalized_sha256": new["normalized_sha256"]})
    for source, target in S["SOURCES"].items():
        actual = STAGE / RESOURCES / target
        regular(actual)
        assert sha(actual) == sha(REPO / source), target
    S["verify"](STAGE)
    assert S["inventory"](APP) == baseline and S["inventory"](STAGE) == sealed
    assert S["inventory"](PAYLOAD_ROOT) == payload_inventory
    return {"source_commit": S["COMMIT"], "native_payload_parity_count": len(rows),
            "native": rows, "native_complete_relative_set_sha256": canonical_sha(sorted(native)),
            "additional_inherited_native": inherited, "non_native_payload_matches": matched_non_native,
            "selected_source_matches": len(S["SOURCES"]),
            "payload_audit_sha256": sha(REPORTS["payload"]),
            "sealed_stage_inventory_sha256": canonical_sha(sealed),
            "baseline_inventory_sha256": canonical_sha(baseline), "stage_signature_verified": True}


def custody_audit():
    import critical_pins
    payload = _producer("payload")
    proof = _producer("stage")
    assert proof["payload_audit_sha256"] == sha(REPORTS["payload"])
    _bind_payload(payload)
    # Recompute all stage semantics; a passed label and hash link alone are not
    # an admission substitute for the producer's actual payload/stage claims.
    recomputed = stage_audit()
    for key, value in recomputed.items():
        assert proof[key] == value, key
    baseline, sealed = read(ROOT / "baseline-inventory.json"), read(ROOT / "stage-inventory.json")
    assert canonical_sha(sealed) == proof["sealed_stage_inventory_sha256"]
    assert S["inventory"](APP) == baseline and S["inventory"](STAGE) == sealed
    profiles = read(ROOT / "profile-inventories.json")
    assert set(profiles) == {str(path) for path in S["PROFILES"]}
    for path, expected in profiles.items():
        assert S["inventory"](Path(path)) == expected, path
    S["check_namespace"](read(ROOT / "namespace-plan.json"))
    critical = critical_pins.verify()
    for application in (APP, STAGE):
        S["HELPER"]["no_live_app"](application)
        S["verify"](application)
        for name in S["EXTENSIONS"]:
            assert S["entitlements"](application / RESOURCES / "PlugIns" / name) == S["plistlib"].loads(
                (ROOT / (name + ".plist")).read_bytes())
    resources = STAGE / RESOURCES
    assert not list(resources.rglob("*.pyc")) and not list(resources.rglob("__pycache__"))
    assert all(row["kind"] == "link" or not row["mode"] & 0o222
               for row in S["inventory"](resources).values())
    assert S["inventory"](APP) == baseline and S["inventory"](STAGE) == sealed
    return {"compiled_commit": S["COMMIT"], "compiled_revision": S["REVISION"],
            "stage_audit_sha256": sha(REPORTS["stage"]),
            "payload_audit_sha256": sha(REPORTS["payload"]),
            "native_payload_count": proof["native_payload_parity_count"],
            "native_complete_relative_set_sha256": proof["native_complete_relative_set_sha256"],
            "baseline_and_stage_exact": True, "profiles_exact_unchanged_count": len(profiles),
            "profiles_inventory_receipt_sha256": sha(ROOT / "profile-inventories.json"),
            "namespace_unchanged_count": len(S["NAMESPACE_FILES"]),
            "selected_critical_files_unchanged_count": len(critical["files"]),
            "critical_receipt_sha256": sha(critical_pins.RECEIPT),
            "strict_signatures_quicklook_readonly_cachefree": True, "no_live_app": True}


def admission_self_test():
    """Pure receipt-substitution negatives; never load the deployment adapter."""
    commit, revision = "self-test-commit", "self-test-revision"
    fixtures = {}
    for mode in MODES:
        row = {"schema": SCHEMA, "mode": mode, "passed": True, "helper_sha256": sha(__file__)}
        if mode == "payload":
            row.update(commit=commit, read_only_payload_and_app_unchanged=True)
        elif mode == "stage":
            row.update(source_commit=commit, stage_signature_verified=True)
        else:
            row.update(compiled_commit=commit, compiled_revision=revision, baseline_and_stage_exact=True,
                       strict_signatures_quicklook_readonly_cachefree=True, no_live_app=True)
        fixtures[mode] = row
    accepted, rejected = [], []
    for mode, original in fixtures.items():
        assert admit_producer(copy.deepcopy(original), mode, commit=commit, revision=revision) == original
        accepted.append("valid-" + mode)
        mutations = [
            ("wrong-schema", "schema", "FreeCAD.LOCAL_INSTALL_INDEPENDENT_AUDIT_V1"),
            ("wrong-role", "mode", MODES[(MODES.index(mode) + 1) % len(MODES)]),
            ("wrong-helper", "helper_sha256", "0" * 64),
        ]
        for key in original:
            mutations.append(("missing-" + key, key, None))
            if original[key] is True:
                for label, value in (("false", False), ("integer", 1), ("string", "true")):
                    mutations.append((label + "-" + key, key, value))
        identity = "commit" if mode == "payload" else "source_commit" if mode == "stage" else "compiled_commit"
        mutations.append(("wrong-commit", identity, "unrelated-commit"))
        if mode == "custody":
            mutations.append(("wrong-revision", "compiled_revision", "unrelated-revision"))
        for label, key, value in mutations:
            changed = copy.deepcopy(original)
            if label.startswith("missing-"):
                changed.pop(key)
            else:
                changed[key] = value
            try:
                admit_producer(changed, mode, commit=commit, revision=revision)
            except AssertionError:
                rejected.append(mode + ":" + label)
            else:
                raise AssertionError("Admitted invalid producer: " + mode + ":" + label)
        for other in MODES:
            if other == mode:
                continue
            try:
                admit_producer(copy.deepcopy(fixtures[other]), mode, commit=commit, revision=revision)
            except AssertionError:
                rejected.append(mode + ":substituted-" + other)
            else:
                raise AssertionError("Admitted substituted producer: " + mode + ":" + other)
    assert S is None, "Admission self-test loaded deployment state"
    return {"schema": "FreeCAD.LOCAL_INSTALL_PRODUCER_ADMISSION_SELF_TEST_V1", "passed": True,
            "helper_sha256": sha(__file__), "accepted_count": len(accepted), "accepted": accepted,
            "rejected_count": len(rejected), "rejected": rejected,
            "native_build_app_solver_or_signature_execution": False,
            "production_app_profile_or_existing_evidence_writes": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=(*MODES, "admission-self-test"))
    args = parser.parse_args()
    assert __debug__, "Audit assertions must remain enabled"
    if args.mode == "admission-self-test":
        print(json.dumps(admission_self_test(), indent=2))
        return
    _load_settings()
    output = REPORTS[args.mode]
    assert not output.exists(), output
    report = {"schema": SCHEMA, "mode": args.mode, "passed": False, "helper_sha256": sha(__file__),
              "limits": ["Software payload/custody only; not engineering acceptance.",
                         "Mach-O normalization excludes only RPATH and signature bookkeeping; stage RPATH is exact.",
                         "Selected critical-prefix pins are not a whole-environment inventory.",
                         "Full private user/app inventory bodies are not included in this report."]}
    try:
        S["compiled_identity"]()
        import critical_pins
        critical_pins.verify()
        report.update({"payload": payload_audit, "stage": stage_audit, "custody": custody_audit}[args.mode]())
        S["compiled_identity"]()
        critical_pins.verify()
        report["passed"] = True
        admit_producer(report, args.mode, commit=S["COMMIT"], revision=S["REVISION"])
    except BaseException as error:
        report["passed"] = False
        report["error"] = repr(error)
        raise
    finally:
        with output.open("x") as stream:
            stream.write(json.dumps(report, indent=2) + "\n")
        print(json.dumps({key: value for key, value in report.items() if key != "native"}, indent=2))


if __name__ == "__main__":
    main()
