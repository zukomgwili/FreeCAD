"""Publish exact 960 deployment evidence after successful installed-app gates.

Authoring/imports do not execute a native application. Root alone invokes main
serially after installation; verification calls are read-only. Private CAD,
native executables, live environment and bulk app/profile inventories stay
outside the publication. Original receipt paths and bytes are never rebound.
"""

import sys

sys.dont_write_bytecode = True

from datetime import datetime
import hashlib
import importlib
import json
from pathlib import Path
import plistlib
import re
import shutil
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
REPO = Path("/Users/zukomgwili/src/FreeCAD")
DEST = REPO / "package/local-completion/freecad-960-installation-evidence"
SUMMARY = REPO / "package/local-completion/freecad-960-installation.json"
COMMIT = "64e6da94ac9e5d693f7dafb8495679983a68bb46"
REVISION = "49261 +240 (Git)"
NATIVE_SHA = "3fdd2b7f7cc3198e7fd1a5dc89a71e0cfacbd1f6ee3e21b106e2171ed6b52d7a"
AUDITOR_SHA = "82f9e5ba571599b06a6df87811bb9384a28f3661c9e563820e93e11988ccf3e3"
COUNTS = {"cmd": 20, "gui": 4, "cold": 1}
STEP_MODES = {
    "step-capture-qualified": "capture",
    "step-payload": "payload",
    "step-audit-payload": "audit-payload",
    "step-stage": "stage",
    "step-audit-stage": "audit-stage",
    "step-audit-custody": "audit-custody",
    "step-swap": "swap",
}
EXPECTED_SKIPPED = {
    "BackupPolicyTest.StandardWithZeroFilesDeletesExisting",
    "BackupPolicyTest.TimestampWithZeroFilesDeletesExisting",
}
EXPECTED_DISABLED = {
    "BackupPolicyTest.TimestampWithInvalidFormatStringThrows",
    "BackupPolicyTest.TimestampWithAbsurdlyLongFormatStringThrows",
    "DocumentObserverTest.hasSubObject",
    "DocumentObserverTest.hasSubElement",
    "DocumentObserverTest.normalize",
    "DocumentObserverTest.normalized",
    "ExpressionParserTest.expressionsParseAsPyObjectWrapper",
    "CrashReporterTests.DeliberateSegfaultRoundTrip",
}


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical_sha(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def nonfinite(value):
    raise ValueError("Nonfinite JSON constant: " + value)


def read(path):
    path = Path(path)
    assert path.is_file() and not path.is_symlink(), path
    return json.loads(path.read_text(), object_pairs_hook=unique, parse_constant=nonfinite)


def copy_exact(source, target):
    source, target = Path(source), Path(target)
    assert source.is_file() and not source.is_symlink(), source
    target.parent.mkdir(parents=True, exist_ok=True)
    assert not target.exists() and not target.is_symlink(), target
    shutil.copyfile(source, target)
    assert sha(target) == sha(source), target


def write_json(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def public_independent_review(path, proof):
    """A labelled derivative, never a replacement for the private original."""
    inputs = proof["inputs"]
    assert isinstance(inputs, dict), path
    summary = {key: value for key, value in proof.items() if key not in {"inputs", "schema"}}

    def leaves(value):
        if isinstance(value, dict):
            return sum(leaves(item) for item in value.values())
        if isinstance(value, list):
            return sum(leaves(item) for item in value)
        return 1

    # An unexpected second inventory map must not silently become public.
    assert leaves(summary) <= 2000, "Unexpected bulk independent-review summary: " + str(path)
    return {
        **summary,
        "schema": "FreeCAD-960-public-independent-review-derivative-v1",
        "original_schema": proof["schema"],
        "original_private_path": str(path),
        "original_sha256": sha(path),
        "input_record_count": len(inputs),
        "inputs_canonical_sha256": canonical_sha(inputs),
        "private_original_retained_unchanged": True,
        "publication_is_new_review_or_reexecution": False,
        "derivative_note": (
            "Public derivative of the named private original. The bulk inputs map is omitted; "
            "its record count and canonical SHA256 bind that withheld map. Other summary "
            "fields, including passed, are verbatim original claims. These derivative bytes "
            "are not the original review report and do not constitute a new review."
        ),
    }


def check_log(directory, proof):
    assert sha(directory / "run.log") == proof["log_sha256"], directory
    assert type(proof["returncode"]) is int and proof["returncode"] == 0
    assert proof["passed"] is True and proof["timed_out"] is False
    assert proof["child_reaped"] is True and proof["process_group_gone"] is True
    assert proof["source_commit"] == COMMIT


def check_step(label, mode):
    directory = ROOT / label
    proof = read(directory / "execution.json")
    check_log(directory, proof)
    assert proof["schema"] == "FreeCAD-8rk-install-step-v1" and proof["mode"] == mode
    assert proof["inputs_before"] == proof["inputs_after"]
    assert proof["inputs_unchanged"] is True and proof["protected_unchanged"] is True
    if mode == "swap":
        assert proof["expected_sealed_install_and_exact_backup"] is True
    else:
        assert proof["protected_before"] == proof["protected_after"]
    return proof


def check_application(install, location, mode, sealed_sha):
    """Admit historical stage records without pretending STAGE still exists."""
    directory = ROOT / (location + "-" + mode)
    proof = read(directory / "execution.json")
    regression = read(directory / "regression.json")
    check_log(directory, proof)
    application = install.STAGE if location == "stage" else install.APP
    assert proof["schema"] == "FreeCAD-960-literal-application-gate-v1"
    assert proof["application"] == str(application)
    assert proof["location"] == location and proof["mode"] == mode
    assert proof["revision"] == REVISION and proof["native_sha256"] == NATIVE_SHA
    assert proof["inputs_before"] == proof["inputs_after"]
    for key in (
        "inputs_unchanged",
        "application_unchanged",
        "profiles_and_dependencies_unchanged",
        "original_app_unchanged",
        "strict_signature_verified",
        "semantic_tests_passed",
    ):
        assert proof[key] is True, (location, mode, key)
    assert proof["application_inventory_sha256"] == sealed_sha
    assert proof["skipped_lines"] == [] and proof["executed_tests"] == COUNTS[mode]
    assert proof["source_or_build_import_override"] is False
    assert proof["native_solver_override"] is False
    assert sha(directory / "regression.json") == proof["regression_sha256"]
    assert regression["schema"] == "FreeCAD-960-installation-regression-v1"
    assert regression["passed"] is True and regression["application"] == str(application)
    assert regression["commit"] == COMMIT and regression["revision"] == REVISION
    assert regression["native_sha256"] == NATIVE_SHA and regression["mode"] == mode
    assert regression["gui"] is (mode == "gui")
    assert regression["expected_tests"] == regression["executed_tests"] == COUNTS[mode]
    assert regression["skipped"] == regression["failures"] == regression["errors"] == []
    assert regression["source_or_build_import_override"] is False
    assert regression["native_solver_override"] is False
    assert regression["only_public_native_interfaces"] is True
    assert regression["original_project_opened_changed_or_solved"] is False
    ids = regression["selected_test_ids"]
    assert len(ids) == len(set(ids)) == COUNTS[mode]
    assert set(ids) == install.expected_ids(mode)
    text = (directory / "run.log").read_text(errors="replace")
    assert re.findall(r"^Ran (\d+) tests? in [0-9.]+s$", text, re.M) == [str(COUNTS[mode])]
    assert len(re.findall(r"^OK$", text, re.M)) == 1
    assert not re.search(r"^(?:FAILED|FAIL:|ERROR:|UNEXPECTED SUCCESS)|\.\.\. skipped", text, re.M)
    identity = read(directory / "identity-observation.json")
    assert identity["schema"] == "FreeCAD-960-literal-application-identity-v1"
    assert identity["application"] == str(application)
    assert identity["runtime"][3] == REVISION and identity["runtime"][-1] == COMMIT
    assert identity["GuiUp"] is (mode == "gui")
    assert identity["source_or_build_import_override"] is False
    candidate = identity["candidate"]
    assert candidate["path"] == str(
        application / "Contents/Resources/data/NativeSolvers/ccx-force-accounting"
    )
    assert candidate["sha256"] == NATIVE_SHA and candidate["override"] is False
    assert candidate["capabilities"] == {
        "--freecad-force-accounting-version": "CCX_FORCE_ACCOUNTING_V3",
        "--freecad-contact-state-version": "CCX_CONTACT_STATE_V1",
        "--freecad-beam-section-version": "CCX_BEAM_SECTION_V1",
    }
    if mode == "cold":
        observation = read(directory / "cold-observation.json")
        assert observation["passed"] is True
        assert observation["application"] == str(application)
        assert observation["analysis_solver_rerun"] is False
        assert observation["source_inputs_rebound_or_history_promoted_current"] is False
        assert observation["completed_run"] is False and not observation["status"].startswith(
            "Current"
        )
        assert observation["input_unchanged"] is True
        saved = (
            ROOT
            / (location + "-gui")
            / ("test_visible_solver_write_and_run_saves_current_native_beam_end_actions")
        )
        assert observation["document"] == {
            "path": str(saved / "native-beam-gui.FCStd"),
            "sha256": sha(saved / "native-beam-gui.FCStd"),
        }
        assert observation["literal"] == {
            "path": str(saved / "saved-output.json"),
            "sha256": sha(saved / "saved-output.json"),
        }
    # Current installed gates can additionally re-enter their original live
    # admission function. Historical stage locations remain literal records.
    if location == "installed":
        install.application_gate(install.APP, mode)
    return proof


def ctest_counts():
    text = (ROOT / "ctest-latest/run.log").read_text(errors="replace")
    catalogue = {int(value) for value in re.findall(r"^\s*\d+/(\d+) Test #", text, re.M)}
    passed = len(re.findall(r"^\s*\d+/\d+ Test #.*\bPassed\s+[0-9.]+ sec", text, re.M))
    skipped = set(re.findall(r"^\s*\d+ - (\S+) \(Skipped\)$", text, re.M))
    disabled = set(re.findall(r"^\s*\d+ - (\S+) \(Disabled\)$", text, re.M))
    assert catalogue == {2277} and passed == 2267, (catalogue, passed)
    assert skipped == EXPECTED_SKIPPED and disabled == EXPECTED_DISABLED
    assert "100% tests passed" in text
    return {
        "catalogue": 2277,
        "passed": passed,
        "failed": 0,
        "existing_skipped": sorted(skipped),
        "existing_disabled": sorted(disabled),
        "excluded": [],
        "genuinely_dotted_TMPDIR": True,
        "elapsed_seconds": read(ROOT / "ctest-latest/execution.json")["elapsed_seconds"],
    }


def collect():
    assert __debug__ and not sys.flags.optimize
    assert not DEST.exists() and not SUMMARY.exists(), "Publish once; preserve existing evidence"
    sys.path.insert(0, str(ROOT))
    install = importlib.import_module("stage_install")
    critical = importlib.import_module("critical_pins")
    install.no_live_app()
    install.compiled_identity()
    assert install.COMMIT == COMMIT and install.REVISION == REVISION
    assert install.NATIVE_SHA == NATIVE_SHA
    assert sha(ROOT / "audit_payload_stage.py") == AUDITOR_SHA
    sealed = read(ROOT / "stage-inventory.json")
    baseline = read(ROOT / "baseline-inventory.json")
    sealed_sha, baseline_sha = canonical_sha(sealed), canonical_sha(baseline)
    assert install.inventory(install.APP) == sealed
    assert install.inventory(install.BACKUP) == baseline
    assert not install.STAGE.exists(), "Stage must have been renamed, not copied/relabelled"
    profiles = read(ROOT / "profile-inventories.json")
    assert set(profiles) == {str(path) for path in install.PROFILES} and len(profiles) == 3
    for path, wanted in profiles.items():
        assert install.inventory(Path(path)) == wanted, path
    critical_proof = critical.verify()
    assert len(critical_proof["files"]) == 17
    namespace = read(ROOT / "namespace-plan.json")
    install.check_namespace(namespace)
    assert len(namespace) == 11
    for application in (install.APP, install.BACKUP):
        install.verify(application)
        for name in install.EXTENSIONS:
            wanted = plistlib.loads((ROOT / (name + ".plist")).read_bytes())
            assert install.entitlements(application / "Contents/Resources/PlugIns" / name) == wanted
    resources = install.APP / "Contents/Resources"
    assert not list(resources.rglob("*.pyc")) and not list(resources.rglob("__pycache__"))
    assert all(
        row["kind"] == "link" or not row["mode"] & 0o222
        for row in install.inventory(resources).values()
    )
    install.source_equal(resources)
    install.source_gate("build-latest", "build")
    install.source_gate("ctest-latest", "ctest")
    for label, mode in STEP_MODES.items():
        check_step(label, mode)
    initial = check_step("step-capture", "capture")
    assert initial["passed"] is True
    preserved = read(ROOT / "initial-capture-recovery/preserved.json")
    for name, wanted in preserved["files"].items():
        assert sha(ROOT / "initial-capture-recovery" / name) == wanted
        assert sha(ROOT / name) == wanted, "Qualifying capture changed baseline facts: " + name
    auditor = importlib.import_module("audit_payload_stage")
    audits = {}
    for mode, filename in (
        ("payload", "independent-payload-audit.json"),
        ("stage", "independent-stage-audit.json"),
        ("custody", "independent-stage-custody.json"),
    ):
        proof = read(ROOT / filename)
        audits[mode] = auditor.admit_producer(proof, mode, commit=COMMIT, revision=REVISION)
    assert audits["stage"]["payload_audit_sha256"] == sha(ROOT / "independent-payload-audit.json")
    assert audits["custody"]["payload_audit_sha256"] == sha(ROOT / "independent-payload-audit.json")
    assert audits["custody"]["stage_audit_sha256"] == sha(ROOT / "independent-stage-audit.json")
    assert audits["stage"]["sealed_stage_inventory_sha256"] == sealed_sha
    assert audits["stage"]["baseline_inventory_sha256"] == baseline_sha
    assert audits["payload"]["baseline_inventory_sha256"] == baseline_sha
    assert audits["custody"]["profiles_inventory_receipt_sha256"] == sha(
        ROOT / "profile-inventories.json"
    )
    assert audits["custody"]["critical_receipt_sha256"] == sha(
        ROOT / "critical-before-DESTDIR.json"
    )
    assert audits["custody"]["profiles_exact_unchanged_count"] == 3
    assert audits["custody"]["namespace_unchanged_count"] == 11
    assert audits["custody"]["selected_critical_files_unchanged_count"] == 17
    native = {row["relative"] for row in audits["payload"]["native"]}
    assert native and native == {row["relative"] for row in audits["stage"]["native"]}
    for proof in audits.values():
        assert proof["native_complete_relative_set_sha256"] == canonical_sha(sorted(native))
    assert len(native) == audits["payload"]["payload_native_count"]
    assert len(native) == audits["stage"]["native_payload_parity_count"]
    assert len(native) == audits["custody"]["native_payload_count"]
    auditor._load_settings()
    auditor._bind_payload(audits["payload"])
    for location in ("stage", "installed"):
        for mode in COUNTS:
            check_application(install, location, mode, sealed_sha)
    independent_reviews = {}
    for filename in ("stage-independent-review.json", "final-independent-review.json"):
        proof = read(ROOT / filename)
        assert proof.get("passed") is True, filename
        independent_reviews[filename] = public_independent_review(ROOT / filename, proof)
    counts = ctest_counts()

    # All admissibility checks precede publication. Copy captured bytes only.
    DEST.mkdir()
    (DEST / ".gitattributes").write_text(
        "# Preserve exact executed receipts, logs and historical source snapshots.\n* -whitespace\n"
    )
    for source in sorted(ROOT.glob("*.py")):
        copy_exact(source, DEST / "helpers" / source.name)
    copy_exact(Path(__file__), DEST / "collection" / Path(__file__).name)
    for source in sorted((ROOT / "review").rglob("*.py")):
        copy_exact(source, DEST / "review" / source.relative_to(ROOT / "review"))
    public_json = (
        "identity.json",
        "build-identity.json",
        "namespace-plan.json",
        "independent-payload-audit.json",
        "independent-stage-audit.json",
        "independent-stage-custody.json",
    )
    for name in public_json:
        copy_exact(ROOT / name, DEST / name)
    for name, derivative in independent_reviews.items():
        assert sha(ROOT / name) == derivative["original_sha256"], name
        write_json(DEST / name.replace(".json", "-public.json"), derivative)
    copy_exact(ROOT / "LOCAL-INSTALL.txt", DEST / "LOCAL-INSTALL.txt")
    for name in install.EXTENSIONS:
        copy_exact(ROOT / (name + ".plist"), DEST / (name + ".plist"))
    for source in sorted((ROOT / "code-blobs").iterdir()):
        assert re.fullmatch(r"[0-9a-f]{64}\.py", source.name), source
        assert sha(source) == source.stem, source
        copy_exact(source, DEST / "code-blobs" / source.name)
    copy_exact(
        ROOT / "initial-capture-recovery/preserved.json",
        DEST / "initial-capture-recovery/preserved.json",
    )
    phases = []
    for directory in sorted(path.parent for path in ROOT.glob("*/execution.json")):
        proof = read(directory / "execution.json")
        assert proof["passed"] is True, directory
        classification = (
            "SUPERSEDED_READ_ONLY_INITIAL_CAPTURE"
            if directory.name == "step-capture"
            else "QUALIFYING_PASS"
        )
        for name in (
            "execution.json",
            "run.log",
            "regression.json",
            "identity-observation.json",
            "cold-observation.json",
            "input-snapshots.json",
        ):
            source = directory / name
            if source.exists():
                copy_exact(source, DEST / directory.name / name)
        phases.append(
            {
                "label": directory.name,
                "classification": classification,
                "execution_sha256": sha(directory / "execution.json"),
                "log_sha256": sha(directory / "run.log"),
            }
        )
    assert len(phases) == 16, phases
    for location in ("stage", "installed"):
        screenshot = (
            ROOT
            / (location + "-gui")
            / (
                "test_visible_solver_write_and_run_saves_current_native_beam_end_actions/inspector.png"
            )
        )
        if screenshot.exists():
            copy_exact(screenshot, DEST / (location + "-gui") / "inspector.png")
    index = {
        str(path.relative_to(DEST)): {"sha256": sha(path), "bytes": path.stat().st_size}
        for path in sorted(DEST.rglob("*"))
        if path.is_file()
    }
    write_json(DEST / "index.json", index)
    modified = datetime.fromtimestamp(install.APP.stat().st_mtime, ZoneInfo("Europe/London"))
    summary = {
        "schema": "FreeCAD-960-installation-validation-v1",
        "passed": True,
        "date": datetime.now(ZoneInfo("Europe/London")).date().isoformat(),
        "timezone": "Europe/London",
        "deployment_bead": "FreeCAD-xgx",
        "fix_bead": "FreeCAD-960",
        "application": str(install.APP),
        "rollback_backup": str(install.BACKUP),
        "source_commit": COMMIT,
        "revision": REVISION,
        "native_sha256": NATIVE_SHA,
        "modified_local_time": modified.isoformat(),
        "build": {"full_incremental_Release": True, "clean_from_scratch_claimed": False},
        "ctest": counts,
        "application_tests": {
            "stage": COUNTS,
            "installed": COUNTS,
            "stage_total": 25,
            "installed_total": 25,
            "total_executed": 50,
            "identity_checks_included_in_counts": True,
            "separate_process_cold_restore_per_location": True,
            "skipped": [],
            "source_or_build_import_override": False,
            "native_solver_override": False,
        },
        "payload": {
            "complete_native_images": len(native),
            "non_native_payload_matches": audits["stage"]["non_native_payload_matches"],
            "selected_source_matches": audits["stage"]["selected_source_matches"],
            "full_DESTDIR_manifest_leaf_set_verified": True,
            "stage_and_installed_exact_sealed_inventory_sha256": sealed_sha,
            "old_backup_exact_inventory_sha256": baseline_sha,
            "strict_signatures_and_QuickLook_entitlements_verified": True,
            "resources_readonly_and_cachefree": True,
        },
        "preservation": {
            "profiles_unchanged": 3,
            "external_namespace_files_unchanged": 11,
            "selected_critical_dependency_files_unchanged": 17,
            "whole_dependency_environment_inventory_claimed": False,
        },
        "phases": phases,
        "initial_capture": "Read-only baseline capture predates helper admission hardening; exact helpers and original inventories remain retained. It was superseded by step-capture-qualified before DESTDIR, not relabelled as its admission proof.",
        "privacy": {
            "private_CAD_or_BREP_bytes_retained": False,
            "bulk_app_and_profile_inventory_bodies_published": False,
            "native_binaries_or_private_environment_published": False,
            "original_absolute_provenance_preserved": True,
            "stage_histories_rebound_or_relabelled_Current": False,
            "bulk_independent_review_inputs_maps_published": False,
            "independent_review_publications_are_labelled_derivatives": True,
        },
        "source_qualification": {
            "record": "package/local-completion/freecad-960-validation.json",
            "six_equilibrium_fixtures_limit": 0.01,
            "new_deployment_engineering_acceptance_claimed": False,
            "meaning": "Installed shipped tests repeat software checks; this is no new original-project or building acceptance.",
        },
        "runtime_dependency": str(install.PREFIX),
        "self_contained": False,
        "notarized": False,
        "scope": "Current fork software deployment only. No original project opened, changed, meshed, solved or accepted. Historical stage records and saved provenance remain literal.",
        "evidence": {
            "directory": str(DEST.relative_to(REPO)),
            "files": len(index),
            "index_sha256": sha(DEST / "index.json"),
            "private_directory": str(ROOT),
            "independent_review_derivatives": {
                name.replace(".json", "-public.json"): {
                    "original_sha256": derivative["original_sha256"],
                    "input_record_count": derivative["input_record_count"],
                    "inputs_canonical_sha256": derivative["inputs_canonical_sha256"],
                }
                for name, derivative in independent_reviews.items()
            },
        },
        "metadata_note": "Later tracking/evidence commits do not change the exact compiled 64e6/+240 application identity.",
    }
    write_json(SUMMARY, summary)
    assert install.inventory(install.APP) == sealed
    assert install.inventory(install.BACKUP) == baseline
    for path, wanted in profiles.items():
        assert install.inventory(Path(path)) == wanted, path
    critical.verify()
    install.no_live_app()
    print(
        json.dumps(
            {
                "passed": True,
                "summary": str(SUMMARY),
                "summary_sha256": sha(SUMMARY),
                "files": len(index),
                "compiled_commit": COMMIT,
                "revision": REVISION,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    collect()
