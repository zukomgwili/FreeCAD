"""Mechanically preserve an explicit public-safe 3sc installation receipt set.

Run only after the root confirms final-audit PASS. This does not launch FreeCAD,
build, install, change beads, or edit the top-level installation receipt. The
only repository write is a fresh, dedicated installation-evidence directory.
The destination must not already exist. Copies retain their original bytes;
two source snapshots with inherited EOF blank lines use lossless UTF-8 JSON
wrappers instead, recording both raw source and stored wrapper hashes.
large build/CTest/CLI logs are represented by actual bounded tail bytes, full
SHA256 bindings and mechanically extracted summary fields, not rewritten logs.

No CAD, FCMat cards, user configuration, user/profile inventories, native
binaries, solver decks, or original-building geometry/vector reports are copied.
Native pipeline/analytic/disjoint JSON is the small synthetic product fixture,
not the original Oomakhi fixture. Historical stage paths in receipts are kept
literal and classified as historical; they are not rewritten to installed paths.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent
REPO = Path("/Users/zukomgwili/src/FreeCAD")
DESTINATION = REPO / "package/local-completion/freecad-3sc-installation-evidence"
APP = Path("/Applications/FreeCAD-27.1.0.app")
COMMIT = "5591e8e388bf3506450cb407f784b89064804ddc"
REVISION = "49261 +205 (Git)"
SOURCE_QUALIFICATION = "455ff652d2755fdc1ae29921318a054e758c26b6"
GATES = ("create", "reopen", "cli", "features", "gui", "equilibrium",
         "mixed-create", "mixed-reopen", "area-create", "area-reopen")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def regular_bytes(path):
    path = Path(path)
    assert path.is_file() and not path.is_symlink(), path
    return path.read_bytes()


def json_bytes(path):
    data = regular_bytes(path)
    value = json.loads(data)
    assert isinstance(value, dict), path
    return data, value


def classification(label):
    assert label in ("stage", "installed")
    return ("historical signed-stage execution before reversible rename; target now absent"
            if label == "stage" else
            "current installed /Applications application execution after replacement")


def validate_receipt(path, value):
    """Require a success marker without inventing one for schemas without it."""
    markers = [value[key] for key in ("passed", "verdict") if key in value]
    assert markers, (path, "No recognized top-level success marker")
    assert all(marker is True or marker == "PASS" for marker in markers), path


def plan_copy(plan, source, destination, category, scope, receipt=True, utf8_wrapper=False):
    source = Path(source)
    relative = Path(destination)
    assert not relative.is_absolute() and ".." not in relative.parts
    assert source.suffix in (".json", ".png", ".py", ".cpp", ".txt"), source
    assert source.suffix.lower() not in (".fcstd", ".fcmat", ".cfg", ".so", ".dylib")
    data = regular_bytes(source)
    if source.suffix == ".json":
        value = json.loads(data)
        if receipt:
            validate_receipt(source, value)
    if source.suffix == ".png":
        assert data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) > 10000, source
    row = {"source": source, "relative": relative, "data": data,
           "category": category, "scope": scope, "kind": "byte_exact_copy"}
    if utf8_wrapper:
        assert source.name in ("harness_config.py", "stage_install.py")
        assert category == "private_installer_source_snapshot"
        assert str(relative).endswith(".py.json")
        text = data.decode("utf-8", errors="strict")
        assert text.encode("utf-8") == data, source
        wrapper = {"schema": "FreeCAD.lossless-utf8-source-snapshot.v1",
                   "source": str(source), "encoding": "UTF-8",
                   "raw_bytes": len(data), "raw_sha256": digest(data), "text": text}
        row.update(raw_data=data, kind="lossless_utf8_json_wrapper",
                   data=(json.dumps(wrapper, indent=2, ensure_ascii=True) + "\n").encode("utf-8"))
    plan.append(row)


def log_tail(plan, source, destination, kind, max_lines):
    """Capture exact complete final lines and bind the full unmodified input."""
    source = Path(source)
    data = regular_bytes(source)
    text = data.decode("utf-8", errors="replace")
    summary = {"kind": kind, "complete_log_sha256": digest(data),
               "complete_log_bytes": len(data), "source": str(source)}
    if kind == "ctest":
        successes = re.findall(r"^100% tests passed out of (\d+)\s*$", text, re.M)
        seconds = re.findall(r"^Total Test time \(real\) =\s+([\d.]+) sec\s*$", text, re.M)
        assert len(successes) == len(seconds) == 1, source
        summary.update(reported_enabled_tests=int(successes[0]),
                       reported_wall_seconds=float(seconds[0]),
                       skipped=re.findall(r"^\s*\d+ - (.*?) \(Skipped\)\s*$", text, re.M),
                       disabled=re.findall(r"^\s*\d+ - (.*?) \(Disabled\)\s*$", text, re.M))
        assert not re.search(r"^The following tests FAILED:", text, re.M), source
    elif kind == "cli":
        counts = re.findall(r"^Ran (\d+) tests? in ([\d.]+)s\s*$", text, re.M)
        outcomes = re.findall(r"^OK(?: \(([^\n]*)\))?\s*$", text, re.M)
        assert len(counts) == len(outcomes) == 1, source
        assert not re.search(r"^(?:FAILED\b|FAIL:|ERROR:|UNEXPECTED SUCCESS:)", text, re.M), source
        summary.update(reported_tests=int(counts[0][0]),
                       reported_test_seconds=float(counts[0][1]),
                       reported_outcome="OK", reported_details=outcomes[0])
    elif kind == "build":
        # This is a literal log tail and binding, not a claim that Ninja emitted
        # a success marker, that this was from-empty, or that it was warning-free.
        summary["build_scope"] = "incremental latest-source build; process success is recorded by root"
    else:
        raise AssertionError(kind)
    lines = data.splitlines(keepends=True)
    tail = b"".join(lines[-max_lines:])
    summary.update(actual_tail_line_count=min(len(lines), max_lines),
                   complete_log_line_count=len(lines),
                   tail_is_entire_log=len(lines) <= max_lines,
                   tail_byte_offset=len(data) - len(tail),
                   tail_sha256=digest(tail))
    plan.append({"source": source, "relative": Path(destination), "data": tail,
                 "category": "bounded_actual_log_tail", "scope": kind,
                 "kind": "exact_complete_line_suffix", "log_summary": summary})


def make_plan(audit):
    plan = []
    for name in ("final-audit.json", "independent-payload-audit.json",
                 "independent-stage-audit.json", "independent-stage-custody.json",
                 "stage-material-native-parity.json"):
        plan_copy(plan, ROOT / name, name, "installation_custody_audit",
                  "signed-stage/build correspondence and final installed custody")
    for label in ("stage", "installed"):
        scope = classification(label)
        plan_copy(plan, ROOT / f"{label}-sequence-result.json",
                  f"{label}/sequence.json", "ten_generic_gates", scope)
        for mode in GATES:
            for name in ("summary.json", "identity.json"):
                plan_copy(plan, ROOT / f"{label}-{mode}" / name,
                          f"{label}/generic/{mode}/{name}", "generic_gate_runtime_receipt", scope)
        plan_copy(plan, ROOT / f"{label}-exit-status/summary.json",
                  f"{label}/exit-status.json", "real_process_exit_status", scope)
        for family in ("native", "4jb"):
            for mode in ("cmd", "gui"):
                directory = ROOT / f"{label}-{family}-{mode}"
                for name in ("summary.json", "identity.json"):
                    plan_copy(plan, directory / name,
                              f"{label}/{family}-{mode}/{name}", "native_product_pipeline", scope)
                # Exactly one synthetic pipeline receipt is produced by both
                # witnesses; never discover/copy a general native-contact report.
                pipelines = list(directory.glob("native-accounting-*/pipeline-receipt.json"))
                assert len(pipelines) == 1, directory
                plan_copy(plan, pipelines[0], f"{label}/{family}-{mode}/pipeline-receipt.json",
                          "synthetic_native_pipeline_wrenches", scope, receipt=False)
        for family in ("analytic", "disjoint"):
            plan_copy(plan, ROOT / f"{label}-native-{family}/qualification.json",
                      f"{label}/native-{family}.json", "synthetic_native_qualification", scope)
        for mode, filename in (("gui", "green-witness.json"),
                               ("cold", "cold-restore-report.json")):
            directory = ROOT / "typed" / f"{label}-3sc-{mode}"
            for name in ("execution.json", filename):
                plan_copy(plan, directory / name, f"{label}/typed-{mode}/{name}",
                          "3sc_actual_gui_or_cold_native_receipt", scope)
        plan_copy(plan, ROOT / "typed" / label / "runtime.json",
                  f"{label}/typed-runtime.json", "3sc_target_runtime_manifest", scope, receipt=False)
        plan_copy(plan, ROOT / "typed" / f"{label}-3sc-gui/native-array-green.png",
                  f"{label}/typed-native-array.png", "synthetic_native_array_gui_screenshot", scope)
        log_tail(plan, ROOT / f"{label}-cli/run.log", f"logs/{label}-cli.tail.log", "cli", 70)
    plan_copy(plan, APP / "Contents/Resources/LOCAL-INSTALL.txt", "LOCAL-INSTALL.txt",
              "current_installed_instructions", classification("installed"), receipt=False)
    log_tail(plan, ROOT / "build.log", "logs/build.tail.log", "build", 70)
    log_tail(plan, ROOT / "ctest.log", "logs/ctest.tail.log", "ctest", 75)
    for name in ("stage_install.py", "harness_config.py", "run_gate_sequence.py",
                 "validate_install.py", "InstalledIdentity.py", "verify_exit_status.py",
                 "InstalledExitWitness.py", "validate_native_accounting.py", "validate_4jb.py",
                 "final_audit.py", "collect_evidence.py"):
        wrap = name in ("harness_config.py", "stage_install.py")
        target = f"supervisors/{name}" + (".json" if wrap else "")
        scope = ("lossless current source in UTF-8 JSON wrapper; original EOF bytes retained"
                 if wrap else
                 "literal current source; historical external dependencies remain hash-bound")
        plan_copy(plan, ROOT / name, target, "private_installer_source_snapshot",
                  scope, receipt=False, utf8_wrapper=wrap)
    for name in ("RuntimeIdentity.py", "NativeMixedGuiWitness.py", "NativeMixedGuiGreenWitness.py",
                 "NativeMixedGuiPersistenceWitness.py", "NativeMixedGuiColdRestore.py",
                 "TypedMaterialReadBridge.cpp", "compile_bridge.py", "run_typed.py"):
        plan_copy(plan, ROOT / "typed" / name, f"supervisors/typed/{name}",
                  "private_3sc_producer_source_snapshot", "literal current source, not compiled bridge binary",
                  receipt=False)
    assert len({str(row["relative"]) for row in plan}) == len(plan), "Duplicate destination"
    # Ensure the complete source set exists, succeeds and is safe before creating
    # anything in the repository. No recursive copying is used anywhere.
    for row in plan:
        source = row["source"]
        assert source.is_relative_to(ROOT) or source == APP / "Contents/Resources/LOCAL-INSTALL.txt"
        if source.is_relative_to(ROOT):
            assert not any(part in ("user", "data", "freecad_user_data", "freecad_user_home",
                                    "xdg_data_home", "__pycache__")
                           for part in source.relative_to(ROOT).parts), source
        required = audit["receipt_and_log_sha256"].get(str(source))
        if "log_summary" in row and required is not None:
            assert required == row["log_summary"]["complete_log_sha256"], source
        if row["category"] not in ("bounded_actual_log_tail", "private_installer_source_snapshot",
                                   "private_3sc_producer_source_snapshot"):
            if required is not None:
                assert required == digest(row["data"]), source
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-final-audit-pass", action="store_true",
                        help="Required root authorization after final_audit.json is PASS")
    args = parser.parse_args()
    assert args.confirm_final_audit_pass, "Hold until root confirms final-audit PASS"
    assert ROOT == Path("/private/tmp/freecad-3sc-install.NqfZNl")
    assert not DESTINATION.exists() and not DESTINATION.is_symlink(), DESTINATION
    assert DESTINATION.parent.is_dir() and not DESTINATION.parent.is_symlink()
    audit_bytes, audit = json_bytes(ROOT / "final-audit.json")
    assert audit["passed"] and audit["compiled_commit"] == COMMIT
    assert audit["compiled_revision"] == REVISION and audit["installed_application"] == str(APP)
    assert audit["installed_equals_sealed_stage"] and audit["backup_equals_original_202"]
    assert audit["historical_stage_paths_verified_against_sealed_inventory_and_current_app"]
    assert not audit["engineering_design_accepted"]
    assert not audit["large_original_4jb_retained_replay_claimed_for_this_install"]
    assert digest(regular_bytes(ROOT / "final_audit.py")) == audit["final_audit_source_sha256"]
    assert not (ROOT / "FreeCAD-27.1.0.app").exists(), "Stage must already have been renamed"
    plan = make_plan(audit)
    inventory = []
    source_snapshots = {}
    copied_sources = set()
    for row in plan:
        data, source = row["data"], row["source"]
        if row["kind"] == "byte_exact_copy":
            assert regular_bytes(source) == data, source
        elif row["kind"] == "lossless_utf8_json_wrapper":
            raw = row["raw_data"]
            wrapper = json.loads(data)
            assert regular_bytes(source) == raw, source
            assert wrapper["text"].encode("utf-8") == raw, source
            assert wrapper["raw_sha256"] == digest(raw) and wrapper["raw_bytes"] == len(raw), source
        else:
            assert digest(regular_bytes(source)) == row["log_summary"]["complete_log_sha256"], source
        item = {"path": str(row["relative"]), "sha256": digest(data), "bytes": len(data),
                "source": str(source), "category": row["category"],
                "classification": row["scope"], "preservation": row["kind"]}
        if "log_summary" in row:
            item["complete_log_binding_and_summary"] = row["log_summary"]
        if "raw_data" in row:
            item.update(decoded_raw_sha256=digest(row["raw_data"]),
                        decoded_raw_bytes=len(row["raw_data"]),
                        wrapper_sha256=digest(data),
                        wrapper_encoding="UTF-8 JSON text field; decode and re-encode UTF-8 losslessly")
        inventory.append(item)
        if row["kind"] in ("byte_exact_copy", "lossless_utf8_json_wrapper"):
            copied_sources.add(str(source))
        if "source_snapshot" in row["category"]:
            source_snapshots[str(source)] = digest(row.get("raw_data", data))
    index = {
        "schema": "FreeCAD.local-installation-evidence.v1", "issue": "FreeCAD-3sc",
        "compiled_commit": COMMIT, "compiled_revision": REVISION,
        "prior_source_qualification_commit": SOURCE_QUALIFICATION,
        "installed_application": str(APP), "rollback_backup": audit["rollback_backup"],
        "final_audit_source_sha256": audit["final_audit_source_sha256"],
        "final_audit_json_sha256": digest(audit_bytes),
        "collector_source_sha256": digest(regular_bytes(Path(__file__))),
        "files": inventory, "preserved_file_count_excluding_index": len(inventory),
        "preserved_bytes_excluding_index": sum(row["bytes"] for row in inventory),
        "supervisor_source_sha256": source_snapshots,
        "audit_bindings_not_copied_in_full": {
            path: required for path, required in audit["receipt_and_log_sha256"].items()
            if path not in copied_sources},
        "classification": {
            "stage": classification("stage"), "installed": classification("installed"),
            "source_snapshots": "Current private supervisors, not a claim of new execution; two .py.json wrappers retain raw UTF-8 text, bytes and SHA; supervisor_source_sha256 always hashes decoded raw source",
            "log_tails": "Exact bounded suffixes only; complete source SHA/bytes and actual summary fields retained",
            "native_vectors": "Only small synthetic native product/analytic/disjoint fixtures, never original-building reports",
        },
        "exclusions": [
            "No original NativeContactOwnership create/reopen result body or original-building vectors/geometry.",
            "No CAD/FCStd, user/system config, FCMat/library card, profile inventory, deck, compiled bridge or app binary.",
            "No historical red attempts or large original Oomakhi retained replay evidence copied or claimed rerun.",
            "Full build/CTest/CLI logs stay private; byte-exact tails and complete SHA256 bindings are retained.",
        ],
        "scope_limits": [
            "Software build/value/persistence/provenance/lifecycle qualification, not engineering acceptance.",
            "FCStd restoration uses saved material UUIDs from the available private User library, not unsaved embedding.",
            "Null fixture uses public native dimensions; it is not described as GUI-authored null data.",
            "FEM fingerprints preserve Python-semantic values, not raw QVariant metatype-width identity.",
            "This host-local application still requires the pinned external Pixi environment.",
        ],
        "engineering_design_accepted": False,
    }
    index_bytes = (json.dumps(index, indent=2, ensure_ascii=True) + "\n").encode("utf-8")
    DESTINATION.mkdir()
    for row in plan:
        target = DESTINATION / row["relative"]
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(row["data"])
        assert regular_bytes(target) == row["data"], target
    with (DESTINATION / "index.json").open("xb") as stream:
        stream.write(index_bytes)
    actual = {str(path.relative_to(DESTINATION)) for path in DESTINATION.rglob("*") if path.is_file()}
    assert actual == {row["path"] for row in inventory} | {"index.json"}
    assert not any(path.is_symlink() for path in DESTINATION.rglob("*"))
    print(json.dumps({"destination": str(DESTINATION), "files_excluding_index": len(inventory),
                      "bytes_excluding_index": index["preserved_bytes_excluding_index"],
                      "index_sha256": digest(index_bytes), "passed": True}, indent=2))


if __name__ == "__main__":
    main()
