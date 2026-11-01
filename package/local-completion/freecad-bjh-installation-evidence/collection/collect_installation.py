"""Publish exact bjh deployment receipts after all installed-bundle checks.

Executed receipts and selected observations are copied byte-for-byte. Bulk
application/profile inventories stay private; independent peer reviews have
separately named public derivatives with explicit original/input hashes.
"""

import sys

sys.dont_write_bytecode = True

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
REPO = Path("/Users/zukomgwili/src/FreeCAD")
DEST = REPO / "package/local-completion/freecad-bjh-installation-evidence"
SUMMARY = REPO / "package/local-completion/freecad-bjh-installation.json"
COMMIT = "f87fabb9340177691d4bcea22f6014cab692bde7"
REVISION = "49261 +245 (Git)"
NATIVE_SHA = "b6a356e8635a35cef2621db7bd80145566dc1f671683edb405ab927cb415b353"
COUNTS = {"cmd": 61, "gui": 9, "cold": 1}
CAPABILITIES = {
    "CCX_FORCE_ACCOUNTING_V3",
    "CCX_CONTACT_STATE_V1",
    "CCX_BEAM_SECTION_V1",
    "CCX_BEAM_SECTION_V2",
    "CCX_BEAM_SECTION_V3",
    "CCX_BEAM_SECTION_V4",
    "CCX_BEAM_SECTION_V5",
}
COLD_NAMES = ["v1", "v2", "v3", "v4", "v5-ground", "v5-connected", "v5-fork"]
COLD_SCHEMAS = ["CCX_BEAM_SECTION_V" + str(i) for i in (1, 2, 3, 4, 5, 5, 5)]
COLD_SAMPLES = [10, 10, 4, 4, 18, 36, 54]
SOURCE_QUALIFICATIONS = (
    "package/local-completion/freecad-9rc-validation.json",
    "package/local-completion/freecad-bjh-validation.json",
)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def unique(pairs):
    result = {}
    for key, value in pairs:
        assert key not in result, "Duplicate JSON member: " + key
        result[key] = value
    return result


def nonfinite(value):
    raise ValueError("Nonfinite JSON constant: " + value)


def read(path):
    return json.loads(Path(path).read_text(), object_pairs_hook=unique, parse_constant=nonfinite)


def copy(source, target):
    assert source.is_file() and not source.is_symlink(), source
    target.parent.mkdir(parents=True, exist_ok=True)
    assert not target.exists(), target
    shutil.copyfile(source, target)
    assert sha(source) == sha(target), target


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def review_derivative(path, proof):
    """Create a labelled publication, preserving the private executed report."""
    inputs = proof["inputs"]
    assert isinstance(inputs, dict)
    public = {key: value for key, value in proof.items() if key not in ("schema", "inputs")}
    return {
        "schema": "FreeCAD-bjh-public-independent-review-derivative-v1",
        "original_schema": proof["schema"],
        "original_private_path": str(path),
        "original_sha256": sha(path),
        "input_record_count": len(inputs),
        "inputs_canonical_sha256": canonical(inputs),
        "private_original_retained_unchanged": True,
        "bulk_inputs_omitted": True,
        "publication_is_new_review_or_reexecution": False,
        **public,
    }


def copy_reference(path, expected):
    assert path.is_relative_to(ROOT) and path.suffix == ".json", path
    assert sha(path) == expected, path
    target = DEST / path.relative_to(ROOT)
    if target.exists():
        assert sha(target) == expected, target
    else:
        copy(path, target)


def validate_cold(proof):
    assert proof["passed"] is True
    assert proof["analysis_solver_rerun"] is False
    assert proof["source_inputs_rebound_or_history_promoted_current"] is False
    cases = proof["cases"]
    assert [row["name"] for row in cases] == COLD_NAMES
    assert [row["schema"] for row in cases] == COLD_SCHEMAS
    assert [row["samples"] for row in cases] == COLD_SAMPLES
    for row in cases:
        assert row["completed_run"] is False
        assert row["status"].startswith(("Historical", "Stale")), row["status"]
    v4 = cases[3]["mechanical_results"]
    assert v4["mechanical_partition_preserved"] is True
    assert v4["paired_history_promoted_current"] is False
    for row, components, owners, sources, spring_ends in zip(
        cases[4:], (1, 2, 3), (1, 2, 2), (2, 4, 6), (1, 3, 5)
    ):
        saved = row["mechanical_results"]
        assert saved["components"] == components
        reference = Path(row["reference"]["path"])
        assert reference.is_relative_to(ROOT) and reference.suffix == ".json"
        assert sha(reference) == row["reference"]["sha256"]
        literal = read(reference)
        coupling = literal["provenance"]["coupling"]
        assert len(coupling["materials"]) == len(coupling["sections"]) == owners
        assert len(saved["source_owners"]) == sources
        assert len(saved["support_owners"]) == components
        assert saved["spring_ends"] == spring_ends
        assert type(saved["native_knot_algebraic_rows"]) is int
        assert saved["native_knot_algebraic_rows"] > 0
        assert saved["native_knot_algebraic_rows"] == len(
            literal["frames"][-1]["native_actions"]["knot_algebraic_spcs"]
        )
        assert saved["saved_physical_parameters_preserved"] is True
        assert saved["mechanical_displacement_only_preserved"] is True
    return cases


def historical_helper_snapshot(path, wanted):
    """Resolve a superseded helper input without changing its old receipt."""
    matches = [
        candidate
        for candidate in sorted((ROOT / "review-history").rglob("*.py"))
        if candidate.is_file() and not candidate.is_symlink() and sha(candidate) == wanted
    ]
    assert matches, (path, wanted)
    snapshot = matches[0]
    return {
        "original_input_path": str(path),
        "required_sha256": wanted,
        "retained_private_snapshot": str(snapshot),
        "published_snapshot": "review-history/"
        + str(snapshot.relative_to(ROOT / "review-history")),
    }


def safe_history_file(path):
    """Admit selected evidence, never an archived profile or model subtree."""
    private_parts = {
        "freecad_user_home",
        "freecad_user_data",
        "xdg_config_home",
        "xdg_data_home",
        "xdg_cache_home",
        "dotted.parent",
        "__pycache__",
        "profiles",
        "payload",
    }
    if any(part.lower() in private_parts or part.lower().endswith(".app") for part in path.parts):
        return False, "Private profile/cache/application/dependency subtree"
    if path.is_symlink():
        return False, "Symlink body remains private"
    if path.suffix == ".py" or path.suffix in (".log", ".png"):
        return True, "Selected review helper, literal log or analytical screenshot"
    if path.suffix == ".txt" and (
        path.name in {"stdout.txt", "stderr.txt", "ccx_stdout.txt", "ccx_stderr.txt"}
        or "error" in path.name.lower()
        or "traceback" in path.name.lower()
    ):
        return True, "Selected native log or review error text"
    allowed_json = {
        "classification.json",
        "execution.json",
        "regression.json",
        "identity-observation.json",
        "cold-observation.json",
        "independent-stage-attempt-r01.json",
        "stage-independent-review.json",
        "final-independent-review.json",
        "section-data.json",
        "contact-data.json",
        "observed.json",
        "observed-beam.json",
        "observed-contact.json",
        "saved-output.json",
        "comparison.json",
    }
    if path.suffix == ".json" and path.name in allowed_json:
        return True, "Selected original receipt, review or native observation JSON"
    return False, "CAD/configuration/raw solver/other private body omitted"


assert __debug__
assert not DEST.exists() and not SUMMARY.exists()
sys.path.insert(0, str(ROOT))
import stage_install as install
import critical_pins
import audit_payload_stage as audit

install.no_live_app()
install.compiled_identity()
assert (install.COMMIT, install.REVISION, install.NATIVE_SHA) == (COMMIT, REVISION, NATIVE_SHA)
sealed = read(ROOT / "stage-inventory.json")
baseline = read(ROOT / "baseline-inventory.json")
assert install.inventory(install.APP) == sealed
assert install.inventory(install.BACKUP) == baseline
assert not install.STAGE.exists()
profile_inventories = read(ROOT / "profile-inventories.json")
assert len(profile_inventories) == 3
for path, expected in profile_inventories.items():
    assert install.inventory(Path(path)) == expected, path
critical = critical_pins.verify()
assert len(critical["files"]) == 17
namespace = read(ROOT / "namespace-plan.json")
assert len(namespace) == 11
install.check_namespace(namespace)
install.verify(install.APP)
install.verify(install.BACKUP)
install.source_equal(install.APP / "Contents/Resources")
for label, mode in (("build-latest", "build"), ("ctest-latest", "ctest")):
    install.source_gate(label, mode)
for mode in COUNTS:
    install.application_gate(install.APP, mode)
source_qualifications = []
for relative in SOURCE_QUALIFICATIONS:
    proof = read(REPO / relative)
    assert proof["all_required_gates_passed"] is True, relative
    source_qualifications.append({"path": relative, "sha256": sha(REPO / relative)})
assert read(REPO / SOURCE_QUALIFICATIONS[1])["native_binary_sha256"] == NATIVE_SHA

reviews = {}
for name in ("stage-independent-review.json", "final-independent-review.json"):
    path = ROOT / name
    proof = read(path)
    assert proof["passed"] is True, name
    stage = name.startswith("stage-")
    helper = (
        ROOT
        / "review"
        / ("independent_stage_review.py" if stage else "independent_final_review.py")
    )
    assert proof["schema"] == (
        "FreeCAD-bjh-independent-stage-review-v1"
        if stage
        else "FreeCAD-bjh-independent-installed-review-v1"
    )
    assert proof["compiled_commit"] == COMMIT
    assert proof["revision"] == REVISION and proof["native_sha256"] == NATIVE_SHA
    assert proof["helper_sha256"] == sha(helper) and proof["findings"] == []
    assert isinstance(proof["inputs"], dict)
    for input_path, expected in proof["inputs"].items():
        assert sha(Path(input_path)) == expected, (name, input_path)
    if stage:
        assert proof["stage_inventory_sha256"] == canonical(sealed)
        assert proof["baseline_inventory_sha256"] == canonical(baseline)
    else:
        assert proof["installed_inventory_sha256"] == canonical(sealed)
        assert proof["backup_inventory_sha256"] == canonical(baseline)
        assert proof["stage_review_sha256"] == sha(ROOT / "stage-independent-review.json")
    reviews[name] = review_derivative(path, proof)

reports = {}
for mode, name in (
    ("payload", "independent-payload-audit.json"),
    ("stage", "independent-stage-audit.json"),
    ("custody", "independent-stage-custody.json"),
):
    proof = read(ROOT / name)
    audit.admit_producer(proof, mode, commit=COMMIT, revision=REVISION)
    reports[mode] = proof
assert reports["stage"]["sealed_stage_inventory_sha256"] == canonical(sealed)
ctest = (ROOT / "ctest-latest/run.log").read_text()
assert len(re.findall(r"^\s*\d+/\d+ Test\s+#.*\bPassed\s+[0-9.]+ sec", ctest, re.M)) == 2267
assert "100% tests passed" in ctest
assert len(re.findall(r"^\s*\d+ - \S+ \(Skipped\)$", ctest, re.M)) == 2
assert len(re.findall(r"^\s*\d+ - \S+ \(Disabled\)$", ctest, re.M)) == 8

phases, cold_cases, historical_snapshots = [], {}, {}
for path in sorted(ROOT.glob("*/execution.json")):
    proof, run = read(path), path.parent
    assert proof["passed"] is True and proof["returncode"] == 0
    assert proof["timed_out"] is False
    assert proof["child_reaped"] is True and proof["process_group_gone"] is True
    assert sha(run / "run.log") == proof["log_sha256"], run
    assert proof["source_commit"] == COMMIT, run
    for prefix in ("source_inputs", "inputs"):
        if prefix + "_before" in proof:
            assert proof[prefix + "_before"] == proof[prefix + "_after"], run
            for name, wanted in proof[prefix + "_before"].items():
                original = Path(name)
                if original.parent == ROOT and original.suffix == ".py" and sha(original) != wanted:
                    historical_snapshots[(name, wanted)] = historical_helper_snapshot(
                        original, wanted
                    )
    if run.name.startswith(("stage-", "installed-")):
        regression, mode = read(run / "regression.json"), proof["mode"]
        assert regression["passed"] is True
        assert regression["expected_tests"] == regression["executed_tests"] == COUNTS[mode]
        assert len(regression["selected_test_ids"]) == len(set(regression["selected_test_ids"]))
        assert set(regression["selected_test_ids"]) == install.expected_ids(mode)
        assert regression["skipped"] == regression["failures"] == regression["errors"] == []
        assert sha(run / "regression.json") == proof["regression_sha256"]
        assert proof["application_inventory_sha256"] == canonical(sealed)
        assert regression["source_or_build_import_override"] is False
        assert regression["native_solver_override"] is False
        identity = read(run / "identity-observation.json")
        assert identity["runtime"][-1] == COMMIT and identity["runtime"][3] == REVISION
        assert identity["candidate"]["sha256"] == NATIVE_SHA
        assert identity["candidate"]["override"] is False
        assert set(identity["candidate"]["capabilities"].values()) == CAPABILITIES
        assert len(identity["candidate"]["capabilities"]) == 7
        if mode == "cold":
            cold_cases[run.name] = validate_cold(read(run / "cold-observation.json"))
    phases.append(
        {
            "label": run.name,
            "classification": "QUALIFYING_PASS",
            "execution_sha256": sha(path),
            "log_sha256": proof["log_sha256"],
        }
    )
assert len(phases) == 15, len(phases)
assert set(cold_cases) == {"stage-cold", "installed-cold"}
assert sum(COUNTS.values()) * 2 == 142

DEST.mkdir()
(DEST / ".gitattributes").write_text(
    "# Preserve exact executed receipts, logs and helpers.\n* -whitespace\n"
)
for path in sorted(ROOT.glob("*.py")):
    copy(path, DEST / "helpers" / path.name)
copy(Path(__file__), DEST / "collection" / "collect_installation.py")
for path in sorted((ROOT / "review").glob("*.py")):
    copy(path, DEST / "review" / path.name)
history_files, history_attempts, omitted_history, historical_phases = [], [], {}, []
for path in sorted((ROOT / "review-history").rglob("*")):
    if not path.is_file() and not path.is_symlink():
        continue
    allowed, reason = safe_history_file(path)
    if not allowed:
        if path.is_symlink():
            body = {"kind": "symlink", "target": str(path.readlink()), "reason": reason}
            body["identity_sha256"] = canonical(body)
        else:
            body = {"sha256": sha(path), "bytes": path.stat().st_size, "reason": reason}
        omitted_history[str(path)] = body
        continue
    relative = path.relative_to(ROOT / "review-history")
    history = read(path) if path.suffix == ".json" else None
    if path.name == "execution.json":
        assert type(history["passed"]) is bool
        historical_phases.append(
            {
                "label": path.parent.name,
                "original_private_path": str(path),
                "execution_sha256": sha(path),
                "passed": history["passed"],
            }
        )
    if history is not None and history.get("classification") == "NONQUALIFYING_REVIEW_HELPER_ERROR":
        assert history["schema"] == "FreeCAD-bjh-nonqualifying-review-helper-attempt-v1"
        assert history["native_execution"] is False
        assert history["native_or_staged_application_failure_claimed"] is False
        helper = ROOT / history["helper"]
        assert helper.is_relative_to(ROOT / "review-history")
        assert sha(helper) == history["helper_sha256"]
        history_attempts.append(
            {
                "classification": history["classification"],
                "original_private_path": str(path),
                "original_sha256": sha(path),
                "helper": history["helper"],
                "helper_sha256": history["helper_sha256"],
            }
        )
    elif (
        history is not None
        and history.get("classification") == "NONQUALIFYING_COLD_HARNESS_API_ERROR"
    ):
        helper = path.parent / "ColdBeamBjh.py"
        assert sha(helper) == history["old_helper_sha256"]
        assert history["executed_receipts_and_cases_preserved_byte_for_byte"] is True
        assert history["current_app_and_profiles_unchanged"] is True
        failed_path = path.parent / history["failed_phase"] / "execution.json"
        failed = read(failed_path)
        assert failed["passed"] is False
        assert read(failed_path.parent / "regression.json")["passed"] is False
        supporting = []
        for label in history["supporting_superseded_phases"]:
            receipt = path.parent / label / "execution.json"
            assert read(receipt)["passed"] is True
            supporting.append({"label": label, "execution_sha256": sha(receipt), "passed": True})
        old_review = path.parent / history["supporting_superseded_review"]
        assert read(old_review)["passed"] is True
        history_attempts.append(
            {
                "classification": history["classification"],
                "original_private_path": str(path),
                "original_sha256": sha(path),
                "helper": str(helper.relative_to(ROOT)),
                "helper_sha256": history["old_helper_sha256"],
                "failed_phase": {
                    "label": history["failed_phase"],
                    "execution_sha256": sha(failed_path),
                    "passed": False,
                },
                "supporting_superseded_passes": supporting,
                "supporting_superseded_review": {
                    "original_private_path": str(old_review),
                    "sha256": sha(old_review),
                    "passed": True,
                },
            }
        )
    if history is not None and "inputs" in history:
        target = DEST / "review-history" / relative.with_name(relative.stem + "-public.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        write(target, review_derivative(path, history))
    else:
        target = DEST / "review-history" / relative
        copy(path, target)
    history_files.append(
        {
            "original_private_path": str(path),
            "original_sha256": sha(path),
            "publication": str(target.relative_to(DEST)),
            "published_sha256": sha(target),
            "labelled_derivative": history is not None and "inputs" in history,
        }
    )
omissions_path = ROOT / "collection" / "review-history-omitted-files.json"
write(omissions_path, omitted_history)
for snapshot in historical_snapshots.values():
    assert sha(DEST / snapshot["published_snapshot"]) == snapshot["required_sha256"]
for cases in cold_cases.values():
    for case in cases:
        reference = Path(case["reference"]["path"])
        copy_reference(reference, case["reference"]["sha256"])
        if case["schema"] == "CCX_BEAM_SECTION_V4":
            copy_reference(
                reference.with_name("contact-data.json"),
                case["mechanical_results"]["paired_contact_literal_sha256"],
            )
for name in (
    "identity.json",
    "build-identity.json",
    "test-plan.json",
    "namespace-plan.json",
    "LOCAL-INSTALL.txt",
    "independent-payload-audit.json",
    "independent-stage-audit.json",
    "independent-stage-custody.json",
):
    copy(ROOT / name, DEST / name)
for name, proof in reviews.items():
    write(DEST / name.replace(".json", "-public.json"), proof)
for name in install.EXTENSIONS:
    copy(ROOT / (name + ".plist"), DEST / (name + ".plist"))
for phase in phases:
    directory = ROOT / phase["label"]
    for name in (
        "execution.json",
        "run.log",
        "regression.json",
        "identity-observation.json",
        "cold-observation.json",
    ):
        source = directory / name
        if source.exists():
            copy(source, DEST / directory.name / name)
    for source in sorted(directory.rglob("*.png")):
        copy(source, DEST / directory.name / source.relative_to(directory))
copy(install.BUILD / "install_manifest.txt", DEST / "install_manifest.txt")
index = {
    str(path.relative_to(DEST)): {"sha256": sha(path), "bytes": path.stat().st_size}
    for path in sorted(DEST.rglob("*"))
    if path.is_file()
}
write(DEST / "index.json", index)
summary = {
    "schema": "FreeCAD-bjh-installation-validation-v1",
    "passed": True,
    "application": str(install.APP),
    "source_commit": COMMIT,
    "revision": REVISION,
    "native_sha256": NATIVE_SHA,
    "native_capabilities": sorted(CAPABILITIES),
    "fix_bead": "FreeCAD-bjh",
    "deployment_bead": "FreeCAD-4bu",
    "date": datetime.now(ZoneInfo("Europe/London")).isoformat(),
    "timezone": "Europe/London",
    "modified_local_time": datetime.fromtimestamp(
        install.APP.stat().st_mtime, ZoneInfo("Europe/London")
    ).isoformat(),
    "rollback_backup": str(install.BACKUP),
    "runtime_dependency": str(install.PREFIX),
    "self_contained": False,
    "notarized": False,
    "ad_hoc_signed": True,
    "build": {"full_incremental_Release": True, "clean_from_scratch_claimed": False},
    "application_tests": {
        "stage": COUNTS,
        "installed": COUNTS,
        "total_executed": 142,
        "skipped": [],
        "cold_cases_per_location": COLD_NAMES,
        "cold_schemas_per_location": COLD_SCHEMAS,
        "cold_member_end_counts_per_location": COLD_SAMPLES,
        "source_or_build_import_override": False,
        "native_solver_override": False,
    },
    "ctest": {"catalogue": 2277, "passed": 2267, "skipped": 2, "disabled": 8, "failed": 0},
    "payload": {
        "native_images": reports["payload"]["payload_native_count"],
        "sealed_stage_and_installed_inventory_sha256": canonical(sealed),
        "exact_backup_inventory_sha256": canonical(baseline),
        "full_DESTDIR_leaf_set_audited": True,
        "strict_signatures_QuickLook_entitlements_readonly_cachefree": True,
    },
    "preservation": {
        "profiles_unchanged": 3,
        "selected_critical_files_unchanged": 17,
        "external_namespace_files_unchanged": 11,
        "whole_dependency_environment_inventory_claimed": False,
    },
    "scope": {
        "deployment": "Current fork application with the qualified V1–V5 beam observation routes.",
        "interfaces": "Ordinary geometry, constraints, loads, stock writer, real bundled solver, result import and public result getters.",
        "mechanics": "No substituted beam/contact mechanics, Python force/stress recovery or manual changes to geometry, loads or solver-deck physics.",
        "lifecycle_process_instrumentation": "A shipped lifecycle test wraps Popen and calls its retained original Popen for real child execution; no claim that every test is free of mocks.",
        "building": "No original project or Oomakhi model opened, changed, solved or accepted; software qualification is not building-design acceptance.",
    },
    "source_qualification": source_qualifications,
    "review_history_files": history_files,
    "review_history_omitted_bodies": {
        "original_private_path": str(omissions_path),
        "original_sha256": sha(omissions_path),
        "record_count": len(omitted_history),
        "records_canonical_sha256": canonical(omitted_history),
        "body_or_bulk_record_publication": False,
    },
    "historical_helper_input_snapshots": list(historical_snapshots.values()),
    "nonqualifying_review_harness_attempts": len(history_attempts),
    "nonqualifying_review_harness_history": history_attempts,
    "qualifying_pipeline_phase_count": len(phases),
    "nonqualifying_pipeline_phases": sum(not row["passed"] for row in historical_phases),
    "archived_failed_pipeline_phases": [row for row in historical_phases if not row["passed"]],
    "archived_superseded_passed_pipeline_phases": [
        row for row in historical_phases if row["passed"]
    ],
    "metadata_note": "Later deployment-tracking commits do not change the compiled f87fabb934/+245 application identity.",
    "privacy": {
        "bulk_app_and_profile_inventories_published": False,
        "native_executables_CAD_config_profiles_or_archives_published": False,
        "independent_review_publications_are_labelled_derivatives": True,
        "original_absolute_provenance_preserved": True,
        "original_executed_receipts_rewritten": False,
    },
    "evidence": {
        "directory": str(DEST.relative_to(REPO)),
        "private_directory": str(ROOT),
        "files": len(index),
        "index_sha256": sha(DEST / "index.json"),
    },
    "phases": phases,
}
assert install.inventory(install.APP) == sealed and install.inventory(install.BACKUP) == baseline
critical_pins.verify()
install.no_live_app()
write(SUMMARY, summary)
print(
    json.dumps(
        {"passed": True, "summary": str(SUMMARY), "files": len(index), "revision": REVISION},
        indent=2,
    )
)
