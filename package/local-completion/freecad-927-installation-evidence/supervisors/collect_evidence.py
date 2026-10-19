"""Archive an explicit public-safe 927 installation evidence set, privately.

Run only after root confirms final-audit PASS. No native launch, build, install,
beads mutation, source edit, repo write or broad recursive copy is performed.
The fresh destination is inside this private installation directory. Publication
to the repository is a separate root-owned decision after archive review.

Full build/CTest logs are preserved exactly. CLI logs use byte-exact bounded
tails with complete-file hashes. Full FEM/GUI logs contain only product-suite
software fixtures. Logs with inherited whitespace are lossless UTF-8 JSON text
wrappers, never trimmed or normalized; decoded bytes retain their exact hashes.
No original NativeContactOwnership result body/log, original
Oomakhi response, CAD/card/config/deck, profile/whole-app inventory, binary or
compiled bridge is copied. Native pipeline/analytic JSON is synthetic only.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
DESTINATION = ROOT / "public-safe-evidence"
APP = Path("/Applications/FreeCAD-27.1.0.app")
from harness_config import COMMIT, REVISION, FEM_TEST_COUNT, FEM_GUI_TEST_COUNT

GATES = ("create", "reopen", "cli", "features", "gui", "equilibrium",
         "mixed-create", "mixed-reopen", "area-create", "area-reopen")
SUPERVISORS = (
    "stage_install.py", "harness_config.py", "run_step.py", "critical_pins.py",
    "run_gate_sequence.py", "validate_install.py", "InstalledIdentity.py",
    "verify_exit_status.py", "InstalledExitWitness.py", "validate_native_accounting.py",
    "validate_4jb.py", "final_audit.py", "audit_payload_stage.py", "collect_evidence.py",
)
TYPED_SOURCES = (
    "RuntimeIdentity.py", "NativeMixedGuiWitness.py", "NativeMixedGuiGreenWitness.py",
    "NativeMixedGuiPersistenceWitness.py", "NativeMixedGuiColdRestore.py",
    "TypedMaterialReadBridge.cpp", "compile_bridge.py", "run_typed.py",
)
FULL_LOG_HASHES = {
    "build.log": "6cef413b4d815d6d9f7b7c4de7c53911e2fc6b69570e671e56a5e9dc4564c260",
    "ctest.log": "2d4710bf4c2bd3473d77981a66417b51f49b06b41521e3d0f105d510d812aeb9",
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def raw(path):
    path = Path(path)
    assert path.is_file() and not path.is_symlink(), path
    return path.read_bytes()


def read_json(path):
    data = raw(path)
    value = json.loads(data)
    assert isinstance(value, dict), path
    return data, value


def successful(path, value):
    markers = [value[key] for key in ("passed", "verdict") if key in value]
    assert markers and all(marker is True or marker == "PASS" for marker in markers), path


def classification(label):
    assert label in ("stage", "installed")
    return ("Historical sealed-stage execution before app rename; not current installed source"
            if label == "stage" else
            "Fresh installed /Applications execution; no staged metadata rebinding")


def preserve_utf8(item, log=False):
    """Wrap whitespace-sensitive content without changing any original byte."""
    data = item["data"]
    text = data.decode("utf-8", errors="strict")
    assert text.encode("utf-8") == data
    lines = data.splitlines(keepends=True)
    blank_eof = bool(lines and not lines[-1].rstrip(b"\r\n"))
    needs_wrapper = blank_eof or any(
        line.rstrip(b"\r\n").rstrip(b" \t") != line.rstrip(b"\r\n") for line in lines)
    if needs_wrapper:
        schema = ("FreeCAD.lossless-utf8-log-snapshot.v1" if log else
                  "FreeCAD.lossless-utf8-source-snapshot.v1")
        wrapper = {"schema": schema, "source": str(item["source"]), "encoding": "UTF-8",
                   "raw_bytes": len(data), "raw_sha256": sha(data),
                   "preserved_form": item["kind"], "text": text}
        item.update(kind="lossless_utf8_json_wrapper", unwrapped_kind=item["kind"], raw_data=data,
                    relative=Path(str(item["relative"]) + ".json"),
                    data=(json.dumps(wrapper, indent=2, ensure_ascii=True) + "\n").encode())
    return item


def add(plan, source, destination, category, scope, receipt=False, source_snapshot=False):
    source, relative = Path(source), Path(destination)
    assert not relative.is_absolute() and ".." not in relative.parts
    assert source.is_relative_to(ROOT) or source == APP / "Contents/Resources/LOCAL-INSTALL.txt"
    if source.is_relative_to(ROOT):
        components = source.relative_to(ROOT).parts
        assert not any(part in ("user", "data", "freecad_user_data", "freecad_user_home",
                                "xdg_data_home", "__pycache__", "payload", "staged-cache")
                       for part in components), source
    assert source.suffix in (".json", ".py", ".cpp", ".txt", ".md", ".log"), source
    assert not source.name.endswith((".FCStd", ".FCMat", ".cfg", ".so", ".dylib", ".inp", ".frd")), source
    data = raw(source)
    if receipt:
        successful(source, json.loads(data))
    item = {"source": source, "relative": relative, "data": data,
            "category": category, "scope": scope, "kind": "byte_exact_copy"}
    if source_snapshot or source.suffix == ".log":
        preserve_utf8(item, log=source.suffix == ".log")
    plan.append(item)


def cli_tail(plan, label):
    path = ROOT / f"{label}-cli/run.log"
    data = raw(path)
    text = data.decode("utf-8", errors="replace")
    counts = re.findall(r"^Ran (\d+) tests? in ([\d.]+)s\s*$", text, re.M)
    outcomes = re.findall(r"^OK(?: \(([^\n]*)\))?\s*$", text, re.M)
    assert len(counts) == len(outcomes) == 1
    assert not re.search(r"^(?:FAILED\b|FAIL:|ERROR:|UNEXPECTED SUCCESS:)", text, re.M)
    lines = data.splitlines(keepends=True)
    tail = b"".join(lines[-70:])
    item = {"source": path, "relative": Path(f"logs/{label}-cli.tail.log"), "data": tail,
            "category": "bounded_cli_log_tail", "scope": classification(label),
            "kind": "exact_complete_line_suffix",
            "full_log_binding": {"sha256": sha(data), "bytes": len(data),
                                 "line_count": len(lines), "tail_byte_offset": len(data)-len(tail),
                                 "tail_line_count": min(70, len(lines)),
                                 "tests": int(counts[0][0]), "seconds": float(counts[0][1]),
                                 "outcome": "OK", "details": outcomes[0]}}
    plan.append(preserve_utf8(item, log=True))


def make_plan(audit):
    plan = []
    _, payload = read_json(ROOT / "independent-payload-audit.json")
    _, stage = read_json(ROOT / "independent-stage-audit.json")
    _, custody = read_json(ROOT / "independent-stage-custody.json")
    assert payload["commit"] == stage["source_commit"] == custody["compiled_commit"] == COMMIT
    assert payload["payload_native_count"] == stage["native_payload_parity_count"] == custody["native_payload_count"] == 61
    native_sets = [{row["relative"] for row in value["native"]} for value in (payload, stage)]
    assert len(payload["native"]) == len(stage["native"]) == 61
    assert len(native_sets[0]) == 61 and native_sets[0] == native_sets[1]
    assert (payload["native_complete_relative_set_sha256"]
            == stage["native_complete_relative_set_sha256"]
            == custody["native_complete_relative_set_sha256"])
    for name in ("final-audit.json", "independent-payload-audit.json",
                 "independent-stage-audit.json", "independent-stage-custody.json",
                 "stage-material-native-parity.json", "stage-fem-native-parity.json"):
        add(plan, ROOT / name, name, "software_installation_custody",
            "Success receipts including complete 61-native-module correspondence", receipt=True)
    for name in ("compiled-inputs.json", "bundle-manifest.json"):
        add(plan, ROOT / name, name, "source_hash_custody", "Hash references only, not native bodies")
    for name in ("build.log", "ctest.log"):
        data = raw(ROOT / name)
        assert sha(data) == FULL_LOG_HASHES[name], name
        if name == "ctest.log":
            text = data.decode("utf-8", errors="replace")
            assert len(re.findall(r"^100% tests passed out of \d+\s*$", text, re.M)) == 1
            assert not re.search(r"^The following tests FAILED:", text, re.M)
        add(plan, ROOT / name, "logs/" + name, "complete_exact_build_or_ctest_log",
            "Full unmodified software build/test output; not a tail or rewritten summary")
    step_names = ["payload", "stage", "swap", "final-audit"]
    step_names += [label + "-" + action for label in ("stage", "installed") for action in (
        "sequence", "native-cmd", "native-gui", "4jb-cmd", "4jb-gui", "analytic",
        "disjoint", "typed-compile", "typed-gui", "typed-cold")]
    for step in step_names:
        path = ROOT / f"step-{step}.json"
        _, receipt = read_json(path)
        assert receipt["compiled_commit"] == COMMIT and receipt["compiled_revision"] == REVISION
        assert receipt["process_reaped"] and not receipt["timed_out"]
        assert receipt["critical_pins_unchanged"] and not receipt["owned_processes_remaining"]
        add(plan, path, f"bounded-steps/{path.name}", "bounded_process_and_selected_critical_file_custody",
            "16 selected critical files only; no whole dependency-prefix inventory claim", receipt=True)
    for label in ("stage", "installed"):
        scope = classification(label)
        add(plan, ROOT / f"{label}-sequence-result.json", f"{label}/sequence.json",
            "fresh_location_sequence", scope, receipt=True)
        for mode in ("fem",) + GATES:
            directory = ROOT / f"{label}-{mode}"
            for name in ("summary.json", "identity.json"):
                add(plan, directory / name, f"{label}/generic/{mode}/{name}",
                    "product_runtime_receipt", scope, receipt=True)
            if mode in ("fem", "gui"):
                _, summary = read_json(directory / "summary.json")
                expected = FEM_TEST_COUNT if mode == "fem" else FEM_GUI_TEST_COUNT
                key = "TestFemApp" if mode == "fem" else "TestFemGui"
                assert summary["configured_suite_counts"][key] == expected
                add(plan, directory / "run.log", f"logs/{label}-{mode}.log",
                    "complete_product_software_fixture_log", scope)
        add(plan, ROOT / f"{label}-exit-status/summary.json", f"{label}/exit-status.json",
            "real_process_exit_status", scope, receipt=True)
        for family in ("native", "4jb"):
            for mode in ("cmd", "gui"):
                directory = ROOT / f"{label}-{family}-{mode}"
                for name in ("summary.json", "identity.json"):
                    add(plan, directory / name, f"{label}/{family}-{mode}/{name}",
                        "synthetic_native_product_pipeline", scope, receipt=True)
                pipelines = list(directory.glob("native-accounting-*/pipeline-receipt.json"))
                assert len(pipelines) == 1, directory
                add(plan, pipelines[0], f"{label}/{family}-{mode}/pipeline-receipt.json",
                    "synthetic_native_pipeline_wrenches", scope)
        for family in ("analytic", "disjoint"):
            add(plan, ROOT / f"{label}-native-{family}/qualification.json",
                f"{label}/native-{family}.json", "synthetic_native_qualification", scope, receipt=True)
        for mode, filename in (("gui", "green-witness.json"), ("cold", "cold-restore-report.json")):
            directory = ROOT / "typed" / f"{label}-3sc-{mode}"
            for name in ("execution.json", filename):
                add(plan, directory / name, f"{label}/typed-{mode}/{name}",
                    "synthetic_typed_material_gui_or_cold_receipt", scope, receipt=True)
        add(plan, ROOT / "typed" / label / "runtime.json", f"{label}/typed-runtime.json",
            "typed_runtime_hash_manifest", scope)
        cli_tail(plan, label)
    for name in SUPERVISORS:
        add(plan, ROOT / name, f"supervisors/{name}", "private_installer_source_snapshot",
            "Literal source; UTF-8 JSON wrapper only if needed to preserve inherited whitespace",
            source_snapshot=True)
    for name in TYPED_SOURCES:
        add(plan, ROOT / "typed" / name, f"supervisors/typed/{name}",
            "private_typed_supervisor_source_snapshot", "Source only, never compiled bridge",
            source_snapshot=True)
    add(plan, ROOT / "README.md", "README-installation-plan.md",
        "reviewed_preparation_document", "The exact prepared plan, not a claim it already executed")
    add(plan, APP / "Contents/Resources/LOCAL-INSTALL.txt", "LOCAL-INSTALL.txt",
        "installed_instructions", classification("installed"))
    assert len({str(row["relative"]) for row in plan}) == len(plan)
    for row in plan:
        required = audit["receipt_and_log_sha256"].get(str(row["source"]))
        if required is not None:
            actual = row.get("full_log_binding", {}).get("sha256", sha(row.get("raw_data", row["data"])))
            assert required == actual, row["source"]
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-final-audit-pass", action="store_true")
    args = parser.parse_args()
    assert args.confirm_final_audit_pass, "Root must first confirm final-audit PASS"
    assert ROOT == Path("/private/tmp/freecad-927-install.O8eMXG")
    assert not DESTINATION.exists() and not DESTINATION.is_symlink()
    audit_bytes, audit = read_json(ROOT / "final-audit.json")
    assert audit["passed"] and audit["compiled_commit"] == COMMIT
    assert audit["compiled_revision"] == REVISION
    assert audit["installed_application"] == str(APP)
    assert audit["installed_equals_sealed_stage"] and audit["backup_equals_original_205"]
    assert audit["historical_stage_paths_verified_against_sealed_inventory_and_current_app"]
    assert audit["installed_927_evidence_is_fresh_not_rebound_stage_history"]
    assert not audit["staged_accounting_observation_metadata_rewritten"]
    assert not audit["engineering_design_accepted"]
    assert not audit["original_927_retained_fixture_resolved_during_install"]
    assert sha(raw(ROOT / "final_audit.py")) == audit["final_audit_source_sha256"]
    assert not (ROOT / APP.name).exists()
    plan = make_plan(audit)
    items, copied, source_hashes = [], set(), {}
    for row in plan:
        source = row["source"]
        original = raw(source)
        preserved = row.get("raw_data", row["data"])
        if "full_log_binding" in row:
            binding = row["full_log_binding"]
            assert sha(original) == binding["sha256"]
            assert len(original) == binding["bytes"]
            assert original[binding["tail_byte_offset"]:] == preserved
        else:
            assert original == preserved
        if row["kind"] == "lossless_utf8_json_wrapper":
            wrapper = json.loads(row["data"])
            assert wrapper["text"].encode("utf-8") == preserved
            assert wrapper["raw_sha256"] == sha(preserved)
            assert wrapper["raw_bytes"] == len(preserved)
            assert wrapper["preserved_form"] == row["unwrapped_kind"]
        item = {"path": str(row["relative"]), "sha256": sha(row["data"]), "bytes": len(row["data"]),
                "source": str(source), "category": row["category"], "classification": row["scope"],
                "preservation": row["kind"]}
        if "raw_data" in row:
            item.update(decoded_raw_sha256=sha(preserved), decoded_raw_bytes=len(preserved),
                        decoded_preservation=row["unwrapped_kind"])
        if "full_log_binding" in row:
            item["full_log_binding"] = row["full_log_binding"]
        items.append(item)
        copied.add(str(source))
        if "source_snapshot" in row["category"]:
            source_hashes[str(source)] = sha(original)
    index = {"schema": "FreeCAD.local-installation-evidence.v2", "issue": "FreeCAD-927",
             "compiled_commit": COMMIT, "compiled_revision": REVISION,
             "installed_application": str(APP), "rollback_backup": audit["rollback_backup"],
             "final_audit_json_sha256": sha(audit_bytes),
             "collector_source_sha256": sha(raw(Path(__file__))),
             "files": items, "file_count_excluding_index": len(items),
             "bytes_excluding_index": sum(row["bytes"] for row in items),
             "source_snapshot_raw_sha256": source_hashes,
             "hash_only_audit_bindings_not_archived": {
                 path: required for path, required in audit["receipt_and_log_sha256"].items()
                 if path not in copied},
             "private_destination_only": True, "repository_publication_performed": False,
             "stage_results_are_historical_only": True,
             "installed_observations_use_fresh_sources_not_path_rebound_stage_metadata": True,
             "complete_build_and_ctest_logs_preserved": True,
             "engineering_design_accepted": False,
             "exclusions": [
                 "No original NativeContactOwnership result bodies/logs or original Oomakhi geometry/vectors.",
                 "No profile/whole-app inventory bodies, user/system config, CAD/FCStd/FCMat/library card.",
                 "No solver deck/FRD, native/application/compiled bridge binary, or dependency-prefix copy.",
                 "No source qualification/retained engineering response report or new retained-fixture solve.",
                 "CLI logs use exact bounded tails plus full hashes; build/CTest/FEM/GUI logs are complete.",
                 "Whitespace-sensitive logs are lossless UTF-8 JSON text wrappers, not normalized log copies.",
             ]}
    index_bytes = (json.dumps(index, indent=2, ensure_ascii=True) + "\n").encode()
    DESTINATION.mkdir()
    for row in plan:
        target = DESTINATION / row["relative"]
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(row["data"])
        assert raw(target) == row["data"]
    with (DESTINATION / "index.json").open("xb") as stream:
        stream.write(index_bytes)
    actual = {str(path.relative_to(DESTINATION)) for path in DESTINATION.rglob("*") if path.is_file()}
    assert actual == {row["path"] for row in items} | {"index.json"}
    assert not any(path.is_symlink() for path in DESTINATION.rglob("*"))
    print(json.dumps({"passed": True, "destination": str(DESTINATION), "files": len(items),
                      "bytes": index["bytes_excluding_index"], "index_sha256": sha(index_bytes)}, indent=2))


if __name__ == "__main__":
    main()
