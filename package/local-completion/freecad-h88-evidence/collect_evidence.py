"""Root-reviewed, root-executed local h88 evidence retention; never installs.

No FreeCAD, GUI, kernel, solver, build or test process is launched here. Only
explicit nonmutating formatting/diff checks run. Original manifests/receipts
are copied verbatim; withheld snapshots get a separate index, not edited input
manifests. Geometry payloads and private parameter catalogues are not retained.
"""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path("/private/tmp/freecad-h88-cZ2yvMA9")
REPO = Path("/Users/zukomgwili/src/FreeCAD")
DESTINATION = REPO / "package/local-completion/freecad-h88-evidence"
PRODUCT_COMMIT = "a41994aa70f20397ef4f56503a1ecbe01ac5bb9b"
ORIGINAL = Path(
    "/Users/zukomgwili/src/oomakhi/artifacts/Fire-Access-Integration/r01/review/"
    "en2-complete-r01/complete-native-p01-p02-r67/native/recovery-r02/"
    "EN2-failed-recovery-r02.FCStd"
)
ORIGINAL_SHA = "570e7ffd62c4dfb95c7b0bcbb1eafab69f11c5d54152bf9fd840ad0464402a33"
PRODUCT_SHA = {
    "src/Mod/BIM/ArchComponent.py": "62bbd91946639b2b3c473d6d07d53159bf122958f4a425c0c17ba5dad07ca962",
    "src/Mod/BIM/CMakeLists.txt": "9be9588db55025cf163cc94a5d36caad08be474852c8eecb2685f9958ca2c137",
    "src/Mod/BIM/TestArch.py": "fcf4b21e5d6452ffa0e51a39cbdceae5044b8da101edcc4d549bee4027504af0",
    "src/Mod/BIM/bimtests/TestArchShapeCleanup.py": "43744b847cc28f5a86c9664619f2ef80589dfb30e84ff42bbf2df14b06a27cb4",
}
FINAL_LABELS = (
    "committed-release-build-r01", "committed-focused-r01", "committed-original-r01",
    "committed-checkpoint-save-r01", "committed-checkpoint-reopen-r01",
    "committed-bim-r01", "committed-ctest-r01",
)
REVIEW_NAMES = (
    "evidence-review.json", "oracle-review.json", "boundary-review.json", "controls-review.json",
    "standards-final-review.json", "spec-final-review.json", "original-final-custody.json",
)
REVIEW_PINS = {"original-final-custody.json": "678f1bc4ea2dee6ea82b66072941fa49ec53d0c7821b80eea08cd8ae34f0c7e9"}
SAFE_OBSERVATIONS = {
    "observation.json", "imported-observation.json", "operation-observation.json",
    "cold-observation.json", "generic-regression.json", "tiny-primitive-observation.json",
    "channel-corner-observations.json", "lean-corner-observations.json",
}
CODE_SUFFIXES = {".py", ".h", ".txt", ".toml", ".lock"}
HISTORICAL_EXCLUSIONS = {
    "source-build-controls-r01": "harness-error: source/supervisor changed during build; not accepted",
    "installed-operations-red-r01": "harness-error: BREP cache-byte equality is not a material oracle",
    "source-imported-green-r01": "unqualified source import/origin attempt; not accepted as GREEN",
}


def require(condition, explanation):
    if not condition:
        raise RuntimeError(explanation)


def sha(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as output:
        json.dump(value, output, indent=2, sort_keys=True)
        output.write("\n")


def copy_exact(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as output:
        output.write(source.read_bytes())


def deterministic_gzip(data, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, filename="", mode="wb", compresslevel=9, mtime=0) as output:
        output.write(data)
    with destination.open("xb") as output:
        output.write(buffer.getvalue())


def unittest_count(log):
    matches = list(re.finditer(r"(?m)^Ran (\d+) tests? in ([0-9.]+)s\s*$", log))
    require(len(matches) == 1, "Expected one unambiguous unittest total in final log")
    tail = log[matches[0].end():]
    status = re.search(r"(?m)^OK(?: \(([^\n]*)\))?\s*$", tail)
    require(status is not None, "Final unittest log has no OK summary")
    details = status.group(1) or ""
    skipped = re.search(r"\bskipped=(\d+)", details)
    expected = re.search(r"\bexpected failures=(\d+)", details)
    run_count = int(matches[0].group(1))
    skipped_count = int(skipped.group(1)) if skipped else 0
    expected_count = int(expected.group(1)) if expected else 0
    return {"tests_run": run_count, "elapsed_seconds": float(matches[0].group(2)),
            "skipped": skipped_count, "expected_failures": expected_count,
            "passed_without_skip_or_expected_failure": run_count - skipped_count - expected_count,
            "summary": status.group(0).strip()}


def ctest_count(log):
    found = re.findall(r"(?m)^(\d+)% tests passed(?:, (\d+) tests failed)? out of (\d+)\s*$", log)
    require(len(found) == 1, "Expected one actual CTest total in final log")
    percentage, failed, total = found[0]
    percentage, failed, total = int(percentage), int(failed or 0), int(total)
    require(percentage == 100 and failed == 0 and total > 0, "Final CTest did not pass")
    skipped = re.findall(r"(?m)^\s*\d+\s+-\s+.+\((?:Not Run|Skipped)\)\s*$", log)
    disabled = re.findall(r"(?m)^\s*\d+\s+-\s+.+\(Disabled\)\s*$", log)
    return {"tests_total": total, "tests_failed": failed, "passed_percentage": percentage,
            "not_run_or_skipped_entries": len(skipped), "disabled_entries": len(disabled),
            "catalogued_including_disabled": total + len(disabled),
            "passed_without_skip": total - len(skipped),
            "count_source": "actual CTest run.log summary"}


def validate_runs():
    runs = {}
    for receipt_path in sorted(ROOT.glob("*/execution.json")):
        label = receipt_path.parent.name
        receipt = load_json(receipt_path)
        log_path = receipt_path.parent / "run.log"
        require(log_path.is_file(), f"Missing run.log: {label}")
        require(sha(log_path) == receipt.get("log_sha256"), f"run.log SHA mismatch: {label}")
        protected = receipt.get("protected_before")
        require(bool(protected) and protected == receipt.get("protected_after"), f"Protected tree changed: {label}")
        require(receipt.get("app_and_three_profiles_unchanged") is True, f"Protected receipt false: {label}")
        require(receipt.get("timed_out") is False, f"Timeout in retained run: {label}")
        require(receipt.get("child_reaped") is True and receipt.get("process_group_gone") is True,
                f"Unreaped retained process: {label}")
        require(receipt.get("installation_performed") is False, f"Unexpected installation: {label}")
        before, after = receipt.get("source_inputs_before", {}), receipt.get("source_inputs_after", {})
        require(before.get(str(ORIGINAL)) == ORIGINAL_SHA and after.get(str(ORIGINAL)) == ORIGINAL_SHA,
                f"Original source custody missing or changed: {label}")
        if label in FINAL_LABELS:
            require(receipt.get("passed") is True and receipt.get("returncode") == 0, f"Final gate failed: {label}")
            require(receipt.get("source_commit") == PRODUCT_COMMIT, f"Final product commit mismatch: {label}")
            require(receipt.get("source_and_supervisor_unchanged") is True and before == after,
                    f"Final source/supervisor custody failed: {label}")
            for relative, expected in PRODUCT_SHA.items():
                require(before.get(str(REPO / relative)) == expected, f"Final source SHA mismatch: {label}/{relative}")
        runs[label] = receipt
    require(set(FINAL_LABELS).issubset(runs), "Missing final committed receipt(s): " + ", ".join(sorted(set(FINAL_LABELS) - runs.keys())))
    require(sha(ORIGINAL) == ORIGINAL_SHA, "Original project SHA has changed")
    for relative, expected in PRODUCT_SHA.items():
        require(sha(REPO / relative) == expected, f"Current product source differs from reviewed commit: {relative}")
    counts = {
        "focused": unittest_count((ROOT / "committed-focused-r01/run.log").read_text(errors="replace")),
        "BIM": unittest_count((ROOT / "committed-bim-r01/run.log").read_text(errors="replace")),
        "CTest": ctest_count((ROOT / "committed-ctest-r01/run.log").read_text(errors="replace")),
    }
    require(counts["focused"]["tests_run"] == 7 and counts["focused"]["skipped"] == 0
            and counts["focused"]["expected_failures"] == 0, "Unexpected focused test inventory")
    require(counts["BIM"]["tests_run"] == 350 and counts["BIM"]["skipped"] == 2
            and counts["BIM"]["expected_failures"] == 1, "Unexpected full BIM test inventory")
    return runs, counts


def retain_runs(destination, runs):
    index = {}
    for label, receipt in runs.items():
        source = ROOT / label
        copy_exact(source / "execution.json", destination / "runs" / label / "execution.json")
        deterministic_gzip((source / "run.log").read_bytes(), destination / "runs" / label / "run.log.gz")
        classification = ("accepted-final-committed-gate" if label in FINAL_LABELS else
                          HISTORICAL_EXCLUSIONS.get(label, "historical evidence; not a final committed gate"))
        index[label] = {"receipt_sha256": sha(source / "execution.json"), "run_log_sha256": receipt["log_sha256"],
                        "recorded_passed": receipt.get("passed"), "recorded_returncode": receipt.get("returncode"),
                        "source_custody_recorded": receipt.get("source_and_supervisor_unchanged"),
                        "classification": classification}
        for name in sorted(SAFE_OBSERVATIONS):
            observation = source / name
            if observation.is_file():
                value = load_json(observation)
                require(not any(key in json.dumps(value) for key in ('"primitive_parameters"', '"best_primitive_parameters"')),
                        f"Private parameter catalogue in nominally safe observation: {label}/{name}")
                copy_exact(observation, destination / "runs" / label / name)
        delta = source / "delta-summary.json"
        if delta.is_file():
            value = load_json(delta)
            accepted = [row for row in value.get("attempts", []) if row.get("accepts_invalid_cleanup_predicate") is True]
            best = min(accepted, key=lambda row: row.get("input_count", 10**9)) if accepted else {}
            source_files = {delta.name: sha(delta)}
            trace = source / "delta-observations.jsonl"
            if trace.is_file():
                source_files[trace.name] = sha(trace)
            redacted = {"schema": "FreeCAD-h88-redacted-minimization-v1", "source_files_sha256": source_files,
                        "attempt_count": len(value.get("attempts", [])), "accepted_attempt_count": len(accepted),
                        "found_natural_invalid_cleanup": value.get("found_natural_invalid_cleanup"),
                        "best_input_count": best.get("input_count"), "best_base_health": best.get("base"),
                        "best_native_candidate_health": best.get("native_cleanup_candidate"),
                        "source_checkpoint_sha256": value.get("source_checkpoint_sha256"),
                        "source_checkpoint_unchanged": value.get("source_checkpoint_unchanged"),
                        "withheld": "Private primitive parameters and original summary/JSONL payload; this summary omits object names, while immutable logs retain logged names and shape-health facts"}
            write_json(destination / "runs" / label / "minimization-redacted.json", redacted)
    write_json(destination / "run-index.json", index)


def retain_input_manifests(destination):
    index = {}
    archived = set()
    for original in sorted((ROOT / "as-run").glob("*/inputs.json")):
        label = original.parent.name
        copy_exact(original, destination / "as-run" / label / "inputs.json")
        rows = []
        for source_name, record in load_json(original).items():
            row = {"original_source": source_name, "original_record": record}
            snapshot = record.get("snapshot")
            if snapshot is None:
                row.update(status="WITHHELD", reason="No text snapshot; binary/geometry custody retained by original SHA only")
            else:
                require(Path(snapshot).name == snapshot, f"Unsafe snapshot path in {original}")
                path = original.parent / snapshot
                require(path.is_file() and sha(path) == record.get("sha256"), f"Snapshot SHA mismatch: {path}")
                require(path.stat().st_size == record.get("bytes"), f"Snapshot size mismatch: {path}")
                if Path(source_name).suffix.lower() not in CODE_SUFFIXES:
                    row.update(status="WITHHELD", reason="Non-code, binary, geometry, XML or JSON fixture/catalogue snapshot")
                else:
                    raw = path.read_bytes()
                    require(b"\x00" not in raw, f"Binary payload disguised as code: {path}")
                    raw.decode("utf-8")
                    digest = record["sha256"]
                    retained = "code-snapshots/" + digest + ".gz"
                    if digest not in archived:
                        deterministic_gzip(raw, destination / retained)
                        archived.add(digest)
                    row.update(status="ARCHIVED-CODE", retained_path=retained)
            rows.append(row)
        index[label] = {"original_manifest_sha256": sha(original), "entries": rows}
    # The first RED predates automatic manifests. Its four manual snapshots
    # still bind byte-for-byte to hashes in the unchanged execution receipt.
    legacy_label = "installed-original-red-r01"
    legacy = ROOT / "as-run" / legacy_label
    if legacy.is_dir() and not (legacy / "inputs.json").exists():
        receipt = load_json(ROOT / legacy_label / "execution.json")
        admitted = set(receipt["source_inputs_before"].values())
        rows = []
        for name in ("run_gate.py", "H88OriginalCheckpoint.py", "ArchComponent.py", "ArchStructure.py"):
            path = legacy / name
            digest = sha(path)
            require(digest in admitted, "Manual first-RED snapshot differs from executed input: " + name)
            retained = "code-snapshots/" + digest + ".gz"
            if digest not in archived:
                deterministic_gzip(path.read_bytes(), destination / retained)
                archived.add(digest)
            rows.append({"manual_snapshot": name, "sha256": digest, "retained_path": retained})
        index[legacy_label] = {"provenance": "Manual as-run snapshots; receipt input SHA matches verified",
                               "entries": rows}
    write_json(destination / "snapshot-index.json", index)


def run_nonmutating_checks(destination):
    before = {name: sha(REPO / name) for name in PRODUCT_SHA}
    discovery = {name: (REPO / name).is_file() for name in ("Gemfile", "config/importmap.rb", "bin/rails", "bin/Rails", "package.json")}
    lint_scripts = {}
    if discovery["package.json"]:
        lint_scripts = {key: value for key, value in load_json(REPO / "package.json").get("scripts", {}).items()
                        if key == "lint" or key.startswith("lint:")}
    require(not any(discovery[name] for name in ("Gemfile", "config/importmap.rb", "bin/rails", "bin/Rails")) and not lint_scripts,
            "Unexpected Rails/root lint markers: N/A classification requires review")
    commands = {
        "black": ["/Users/zukomgwili/.local/bin/uv", "tool", "run", "--from", "black==26.5.1", "black", "--check", "--line-length", "100",
                  "src/Mod/BIM/ArchComponent.py", "src/Mod/BIM/TestArch.py", "src/Mod/BIM/bimtests/TestArchShapeCleanup.py"],
        "git-diff-check": ["git", "diff", "--check"],
    }
    receipt = {"schema": "FreeCAD-h88-nonmutating-quality-checks-v1", "cwd": str(REPO), "commands": {},
               "source_before": before, "Rails": {"status": "SKIPPED", "classification": "N/A",
                   "reason": "FreeCAD C++/Python work; no root Rails/importmap or package lint task",
                   "discovery": discovery, "package_lint_scripts": lint_scripts}}
    for name, argv in commands.items():
        try:
            result = subprocess.run(argv, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180, check=False)
            output, returncode, error = result.stdout, result.returncode, None
        except (OSError, subprocess.TimeoutExpired) as exception:
            output = getattr(exception, "stdout", None) or b""
            if isinstance(output, str):
                output = output.encode()
            returncode, error = None, repr(exception)
        log_name = "checks/" + name + ".log.gz"
        deterministic_gzip(output, destination / log_name)
        receipt["commands"][name] = {"argv": argv, "returncode": returncode, "error": error,
                                     "stdout_and_stderr_path": log_name,
                                     "uncompressed_output_sha256": hashlib.sha256(output).hexdigest()}
    receipt["source_after"] = {name: sha(REPO / name) for name in PRODUCT_SHA}
    receipt["source_unchanged"] = receipt["source_before"] == receipt["source_after"] == PRODUCT_SHA
    receipt["passed"] = receipt["source_unchanged"] and all(row["returncode"] == 0 for row in receipt["commands"].values())
    write_json(destination / "formatting-and-discovery-receipt.json", receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    arguments = parser.parse_args()
    require(arguments.destination.is_absolute() and arguments.destination == DESTINATION,
            "Destination must be the explicit new package/local-completion/freecad-h88-evidence folder")
    require(not DESTINATION.exists() and DESTINATION.parent.is_dir(), "Evidence destination must not exist; parent must exist")
    runs, counts = validate_runs()
    for name in REVIEW_NAMES:
        require((ROOT / name).is_file(), "Missing static review: " + name)
        if name in REVIEW_PINS:
            require(sha(ROOT / name) == REVIEW_PINS[name], "Static custody review SHA mismatch: " + name)
    DESTINATION.mkdir()
    # Run/assert the nonmutating final quality gates before copying any source
    # evidence. If these fail, their truthful receipt/logs remain, but there is
    # no completion claim and no source evidence is copied into a false finish.
    checks = run_nonmutating_checks(DESTINATION)
    require(checks["passed"], "Nonmutating final quality check failed; receipt/logs retained, no completion asserted")
    copy_exact(Path(__file__).resolve(), DESTINATION / "collect_evidence.py")
    retain_runs(DESTINATION, runs)
    retain_input_manifests(DESTINATION)
    for name in REVIEW_NAMES:
        copy_exact(ROOT / name, DESTINATION / "reviews" / name)
    completion = {"schema": "FreeCAD-h88-local-completion-v1", "issue": "FreeCAD-h88", "product_commit": PRODUCT_COMMIT,
                  "product_source_sha256": PRODUCT_SHA, "original_project_sha256": ORIGINAL_SHA,
                  "required_final_labels": list(FINAL_LABELS), "final_receipts_all_passed": True,
                  "all_run_logs_verified": True, "all_runs_protected_before_after_equal": True,
                  "all_runs_reaped_without_timeout": True, "actual_test_counts": counts,
                  "nonmutating_checks_passed": checks["passed"], "completed": checks["passed"],
                  "completion_scope": "Source-fix qualification only; not deployment or Git publication",
                  "publication_at_collection": "Session-final Bead closure and Git push are recorded separately",
                  "installation_performed": False, "original_project_mutated": False,
                  "remeshing_or_solving_performed": False, "engineering_or_house_acceptance_claimed": False,
                  "historical_exclusions": HISTORICAL_EXCLUSIONS,
                  "collector_attempt_notes": "Initial preflight and collection refused the newer CTest success-summary syntax before destination creation; parser then qualified against the actual immutable log",
                  "limitations": ["Native Part refinement/deeper cause remains separate follow-up FreeCAD-ajj",
                      "Wrapper health guard is not a universal material-equivalence proof for valid cleanup candidates",
                      "Stage-one reviews retain their original scope; final committed native gates provide final qualification"],
                  "retention_policy": "No FCStd/BREP/XML or private parameter catalogue payload retained; original input manifests unmodified"}
    write_json(DESTINATION / "completion.json", completion)
    manifest = {str(path.relative_to(DESTINATION)): {"sha256": sha(path), "bytes": path.stat().st_size}
                for path in sorted(DESTINATION.rglob("*")) if path.is_file()}
    write_json(DESTINATION / "manifest.json", {"schema": "FreeCAD-h88-evidence-manifest-v1", "algorithm": "SHA256",
               "manifest_itself_excluded_to_avoid_self_reference": True, "files": manifest})
    print(json.dumps({"destination": str(DESTINATION), "completed": completion["completed"],
                      "retained_files": len(manifest), "manifest_sha256": sha(DESTINATION / "manifest.json")}, sort_keys=True))
    return 0 if checks["passed"] else 1


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    raise SystemExit(main())
