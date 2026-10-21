"""Root-executed exact-byte publication of the completed 9ii deployment.

No frozen helper/receipt or absolute solver provenance is rewritten. Stage
history is validated as history after the sealed bundle's deliberate rename.
Raw application/profile inventory bodies and native executables stay private.
"""

import datetime
import gzip
import hashlib
import io
import json
import os
import re
import stat
import sys
import tarfile
from pathlib import Path
from zoneinfo import ZoneInfo

sys.dont_write_bytecode = True
COLLECTION = Path(__file__).resolve().parent
ROOT = COLLECTION.parent
sys.path.insert(0, str(ROOT))

import critical_pins
import run_gate
import stage_install as install

DEST = install.REPO / "package/local-completion/freecad-9ii-installation-evidence"
SUMMARY = install.REPO / "package/local-completion/freecad-9ii-installation.json"
PHASES = {
    "build-latest": "build",
    "ctest-latest": "ctest",
    "step-admission-self-test": "admission-self-test",
    "step-capture": "capture",
    "step-payload": "payload",
    "step-audit-payload": "audit-payload",
    "step-stage": "stage",
    "step-audit-stage": "audit-stage",
    "step-audit-custody": "audit-custody",
    "stage-cmd": "cmd",
    "stage-gui": "gui",
    "stage-cold": "cold",
    "step-swap": "swap",
    "installed-cmd": "cmd",
    "installed-gui": "gui",
    "installed-cold": "cold",
}
NATIVE_MAGIC = {
    b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce",
    b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",
    b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca", b"\x7fELF",
}
CAPTURED = {}
FIXTURES = {}
RELOCATIONS = {}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def identity(info):
    return (
        info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
        info.st_mtime_ns, info.st_ctime_ns,
    )


def regular_bytes(path):
    path = Path(path)
    before = path.lstat()
    assert stat.S_ISREG(before.st_mode) and not path.is_symlink(), path
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        assert identity(os.fstat(stream.fileno())) == identity(before), path
        data = stream.read()
        assert identity(os.fstat(stream.fileno())) == identity(before), path
    assert identity(path.lstat()) == identity(before), path
    return data


def capture(relative):
    path = ROOT / relative
    data = regular_bytes(path)
    if relative in CAPTURED:
        assert CAPTURED[relative] == data, relative
    CAPTURED[relative] = data
    return data


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        assert key not in result, "Duplicate receipt member: " + key
        result[key] = value
    return result


def nonfinite(value):
    raise ValueError("Nonfinite receipt constant: " + value)


def parsed(relative):
    return json.loads(
        capture(relative), object_pairs_hook=unique_pairs, parse_constant=nonfinite,
    )


def native_bytes(data):
    return data[:4] in NATIVE_MAGIC or data[:2] == b"MZ"


def same_input(name, wanted, manifest=None):
    """Only declared immutable stage native inputs may relocate to installed."""
    path = Path(name)
    assert path.is_absolute()
    if path.is_relative_to(install.STAGE):
        assert manifest is not None and name in manifest["expected_native_files"], name
        assert manifest["expected_native_files"][name] == wanted
        relative = path.relative_to(install.STAGE)
        assert SEALED[str(relative)]["kind"] == "file"
        assert SEALED[str(relative)]["sha256"] == wanted
        current = install.APP / relative
        data = regular_bytes(current)
        assert sha(data) == wanted and native_bytes(data)
        RELOCATIONS[name] = {
            "historical_path": name, "current_exact_byte_location": str(current),
            "sha256": wanted, "reason": "Sealed bundle rename; immutable native input only",
            "original_receipt_or_solver_provenance_rewritten": False,
        }
    else:
        assert sha(regular_bytes(path)) == wanted, name


def common_phase(label, mode):
    proof = parsed(label + "/execution.json")
    log = capture(label + "/run.log")
    assert proof["mode"] == mode and proof["source_commit"] == install.COMMIT
    assert proof["passed"] is True and type(proof["returncode"]) is int
    assert proof["returncode"] == 0 and proof["timed_out"] is False
    assert proof["child_reaped"] is True and proof["process_group_gone"] is True
    assert proof["log_sha256"] == sha(log)
    if label in ("build-latest", "ctest-latest"):
        assert proof["schema"] == "FreeCAD-8rk-isolated-native-gate-v1"
        assert proof["source_and_supervisor_unchanged"] is True
        assert proof["app_and_three_profiles_unchanged"] is True
        assert proof["source_inputs_before"] == proof["source_inputs_after"]
        assert proof["protected_before"] == proof["protected_after"]
        for name, wanted in proof["source_inputs_after"].items():
            same_input(name, wanted)
    elif label.startswith("step-"):
        assert proof["schema"] == "FreeCAD-8rk-install-step-v1"
        assert proof["inputs_unchanged"] is True and proof["protected_unchanged"] is True
        assert proof["inputs_before"] == proof["inputs_after"]
        for name, wanted in proof["inputs_after"].items():
            same_input(name, wanted)
        if mode == "swap":
            assert proof["expected_sealed_install_and_exact_backup"] is True
            for profile in install.PROFILES:
                assert proof["protected_before"][str(profile)] == proof["protected_after"][str(profile)]
            assert proof["protected_before"][str(install.APP)] == install.canonical_sha(BASELINE)
            assert proof["protected_after"][str(install.APP)] == install.canonical_sha(SEALED)
        else:
            assert proof["protected_before"] == proof["protected_after"]
    else:
        assert proof["schema"] == install.APPLICATION_SCHEMA
    return proof


def sealed_claim(path, wanted, application):
    path = Path(path)
    assert path.is_relative_to(application / "Contents/Resources"), path
    row = SEALED[str(path.relative_to(application))]
    assert row["kind"] == "file" and row["sha256"] == wanted, path


def historical_stage(mode, proof):
    """Verify original literal stage records without rebinding them as Current."""
    label = "stage-" + mode
    count = install.COUNTS[mode]
    manifest = parsed(label + "/manifest.json")
    regression = parsed(label + "/regression.json")
    assert manifest["schema"] == "FreeCAD-9ii-literal-application-manifest-v1"
    assert proof["location"] == manifest["location"] == regression["location"] == "stage"
    assert proof["application"] == manifest["application"] == regression["application"] == str(install.STAGE)
    assert manifest["mode"] == regression["mode"] == mode
    assert proof["revision"] == manifest["revision"] == regression["revision"] == install.REVISION
    assert manifest["commit"] == regression["commit"] == install.COMMIT
    assert proof["native_sha256"] == manifest["native_sha256"] == regression["native_sha256"] == install.NATIVE_SHA
    assert proof["expected_tests"] == proof["executed_tests"] == count
    assert manifest["expected_tests"] == regression["test_count"] == count
    assert regression["schema"] == install.REGRESSION_SCHEMA and regression["passed"] is True
    for field in (
        "application_unchanged", "profiles_and_dependencies_unchanged", "inputs_unchanged",
        "strict_signature_verified", "original_app_unchanged", "semantic_tests_passed",
    ):
        assert proof[field] is True, (label, field)
    assert proof["source_or_build_import_override"] is False
    assert proof["native_solver_override"] is False
    assert regression["source_or_build_import_override"] is False
    assert regression["only_public_native_interfaces"] is True
    assert regression["Oomakhi_opened_or_solved"] is False
    assert regression["gui"] is (mode == "gui")
    assert proof["inputs_before"] == proof["inputs_after"]
    for name, wanted in proof["inputs_after"].items():
        same_input(name, wanted, manifest)
    assert proof["application_inventory_sha256"] == install.canonical_sha(SEALED)
    assert proof["regression_sha256"] == sha(CAPTURED[label + "/regression.json"])
    assert regression["manifest_sha256"] == sha(CAPTURED[label + "/manifest.json"])
    assert regression["module_sha256"] == sha(capture("App9iiIdentity.py"))
    ids = regression["selected_test_ids"]
    assert len(ids) == len(set(ids)) == count
    log = CAPTURED[label + "/run.log"].decode(errors="replace")
    assert re.findall(r"^Ran (\d+) tests? in [0-9.]+s$", log, re.M) == [str(count)]
    assert len(re.findall(r"^OK$", log, re.M)) == 1
    assert not re.search(r"^(?:FAILED|FAIL:|ERROR:|UNEXPECTED SUCCESS)|\.\.\. skipped", log, re.M)
    for path, wanted in manifest["expected_native_files"].items():
        sealed_claim(path, wanted, install.STAGE)
    expected_source = {target: install.digest(install.REPO / name) for name, target in install.SOURCES.items()}
    assert manifest["expected_source_files"] == expected_source
    for relative, wanted in expected_source.items():
        sealed_claim(install.STAGE / "Contents/Resources" / relative, wanted, install.STAGE)
    identity_proof = regression["identity"]
    assert identity_proof["runtime"][3] == install.REVISION
    assert identity_proof["runtime"][-1] == install.COMMIT
    assert identity_proof["source_or_build_import_override"] is False
    candidate = identity_proof["candidate"]
    assert candidate["override"] is False and candidate["sha256"] == install.NATIVE_SHA
    assert candidate["path"] == str(install.STAGE / "Contents/Resources/data/NativeSolvers/ccx-force-accounting")
    assert candidate["capabilities"] == {
        "--freecad-force-accounting-version": "CCX_FORCE_ACCOUNTING_V3",
        "--freecad-contact-state-version": "CCX_CONTACT_STATE_V1",
    }
    origins = [identity_proof["process_executable"]]
    origins += [row for row in identity_proof["native_origins"].values() if "path" in row]
    origins += list(identity_proof["initial_module_origins"].values())
    origins += list(regression["final_module_origins"].values())
    for origin in origins:
        sealed_claim(origin["path"], origin["sha256"], install.STAGE)
    if mode == "cold":
        cold = regression["cold_restore"]
        case = manifest["cold_case"]
        for field in ("no_native_solve", "no_history_or_provenance_repair", "literal_original_raw_labels_preserved"):
            assert cold[field] is True, field
        assert cold["initial_status"].startswith("Historical")
        assert cold["refresh_status"].startswith("Unavailable")
        assert cold["document"] == case["document"]
        assert cold["saved_contact_hash"] == case["contact_hash_literal"]
        assert sha(case["contact_data_literal"].encode()) == case["contact_hash_literal"]
        files = {row["path"]: row["sha256"] for row in case["source_files"]}
        assert cold["source_files_before"] == cold["source_files_after"] == files
        for name, wanted in files.items():
            same_input(name, wanted, manifest)
        witness = PHASE_PROOFS["stage-cmd"]["cold_witness_documents"]
        assert len(witness) == 1 and witness[0]["path"] == case["document"]
        assert witness[0]["sha256"] == files[case["document"]]
    else:
        verify_backup(label, regression)
    return regression


def verify_backup(label, regression):
    backup = regression["backup_regression"]
    for field in ("backups_contain_exact_previous_target_bytes", "no_escape_or_temporary_leftovers", "only_public_native_interfaces"):
        assert backup[field] is True, field
    assert [row["marker"] for row in backup["same_process_native_reopen"]] == ["third", "first", "second"]
    for name, wanted in backup["file_sha256"].items():
        path = Path(name)
        assert path.is_relative_to(ROOT / label / "witness")
        assert sha(regular_bytes(path)) == wanted
        add_fixture(path)


def add_fixture(path):
    path = Path(path)
    assert path.is_relative_to(ROOT) and path.resolve(strict=True) == path, path
    data = regular_bytes(path)
    assert not native_bytes(data), "A native executable cannot be published as a fixture"
    if path in FIXTURES:
        assert FIXTURES[path] == data
    FIXTURES[path] = data


def fixture_archive():
    skipped = []
    for label in ("stage-cmd", "stage-gui", "installed-cmd", "installed-gui"):
        directory = ROOT / label / "dotted.parent"
        assert directory.is_dir() and not directory.is_symlink()
        for current, dirs, files in os.walk(directory, followlinks=False):
            for name in list(dirs):
                path = Path(current) / name
                if path.is_symlink():
                    skipped.append({"path": str(path), "reason": "Directory symlink; not followed"})
                    dirs.remove(name)
            for name in sorted(files):
                path = Path(current) / name
                if path.is_symlink():
                    skipped.append({"path": str(path), "reason": "Symlink; not dereferenced"})
                    continue
                data = regular_bytes(path)
                if native_bytes(data):
                    skipped.append({"path": str(path), "reason": "Native executable excluded", "sha256": sha(data)})
                    continue
                add_fixture(path)
    for location in ("stage", "installed"):
        label = location + "-cold"
        case = parsed(label + "/manifest.json")["cold_case"]
        for row in case["source_files"]:
            path = Path(row["path"])
            if path.is_relative_to(install.STAGE) or path.is_relative_to(install.APP):
                # Product executables are bound by seals and original metadata,
                # not copied into a fixture archive or rebased in saved history.
                assert row["sha256"] == install.NATIVE_SHA
                continue
            assert sha(regular_bytes(path)) == row["sha256"]
            add_fixture(path)
        assert Path(case["document"]) in FIXTURES
    mapping = []
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for path, data in sorted(FIXTURES.items()):
            relative = "fixtures/" + str(path.relative_to(ROOT))
            info = tarfile.TarInfo(relative)
            info.size = len(data)
            info.mode = stat.S_IMODE(path.lstat().st_mode)
            info.mtime = 0
            archive.addfile(info, io.BytesIO(data))
            mapping.append({"original_path": str(path), "archive_member": relative,
                            "bytes": len(data), "sha256": sha(data)})
    report = {
        "schema": "FreeCAD-9ii-unmodified-fixture-archive-v1", "files": mapping,
        "excluded": skipped, "file_count": len(mapping),
        "absolute_provenance_rewritten": False, "Current_status_rebound": False,
        "stage_history": "Original staged binary paths no longer exist after swap; historical evidence only",
        "scope": "Analytical deployment fixtures only; no engineering/Oomakhi files",
    }
    return gzip.compress(buffer.getvalue(), mtime=0), report


def ctest_summary():
    text = CAPTURED["ctest-latest/run.log"].decode()
    rows = re.findall(r"^\s*(\d+)/(\d+) Test\s+#(\d+):\s+(\S+)\s+\.{2,}\s*(.*)$", text, re.M)
    assert len(rows) == 2277 and {int(row[1]) for row in rows} == {2277}
    assert {int(row[0]) for row in rows} == {int(row[2]) for row in rows} == set(range(1, 2278))
    assert len({row[3] for row in rows}) == 2277
    passed = [row[3] for row in rows if row[4].startswith("Passed")]
    skipped = [row[3] for row in rows if row[4].startswith("***Skipped")]
    disabled = [row[3] for row in rows if row[4].startswith("***Not Run (Disabled)")]
    assert (len(passed), len(skipped), len(disabled)) == (2267, 2, 8)
    assert set(skipped) == {"BackupPolicyTest.StandardWithZeroFilesDeletesExisting", "BackupPolicyTest.TimestampWithZeroFilesDeletesExisting"}
    assert set(disabled) == {
        "BackupPolicyTest.TimestampWithInvalidFormatStringThrows",
        "BackupPolicyTest.TimestampWithAbsurdlyLongFormatStringThrows", "DocumentObserverTest.hasSubObject",
        "DocumentObserverTest.hasSubElement", "DocumentObserverTest.normalize", "DocumentObserverTest.normalized",
        "ExpressionParserTest.expressionsParseAsPyObjectWrapper", "CrashReporterTests.DeliberateSegfaultRoundTrip",
    }
    assert "100% tests passed out of 2269" in text
    return {"catalogue": 2277, "passed": 2267, "failed": 0, "existing_skipped": skipped,
            "existing_disabled": disabled, "excluded": [], "genuinely_dotted_TMPDIR": True,
            "elapsed_seconds": PHASE_PROOFS["ctest-latest"]["elapsed_seconds"]}


def final_custody():
    run_gate.serial()
    install.compiled_identity()
    critical = critical_pins.verify()
    assert len(critical["files"]) == 17
    assert install.inventory(install.APP) == SEALED
    assert install.inventory(install.BACKUP) == BASELINE
    assert not install.STAGE.exists()
    profiles = install.read(ROOT / "profile-inventories.json")
    assert set(profiles) == {str(path) for path in install.PROFILES} and len(profiles) == 3
    for name, wanted in profiles.items():
        assert install.inventory(Path(name)) == wanted, name
    namespace = install.read(ROOT / "namespace-plan.json")
    assert len(namespace) == 11
    install.check_namespace(namespace)
    for application in (install.APP, install.BACKUP):
        install.verify(application)
        for name in install.EXTENSIONS:
            expected = install.plistlib.loads(regular_bytes(ROOT / (name + ".plist")))
            assert install.entitlements(application / "Contents/Resources/PlugIns" / name) == expected
    resources = install.APP / "Contents/Resources"
    assert not list(resources.rglob("*.pyc")) and not list(resources.rglob("__pycache__"))
    assert all(row["kind"] == "link" or not row["mode"] & 0o222 for row in install.inventory(resources).values())
    return critical


def main():
    global SEALED, BASELINE, PHASE_PROOFS
    assert __debug__ and not sys.flags.optimize and not sys.argv[1:]
    assert not DEST.exists() and not SUMMARY.exists()
    SEALED = install.read(ROOT / "stage-inventory.json")
    BASELINE = install.read(ROOT / "baseline-inventory.json")
    critical = final_custody()
    PHASE_PROOFS = {label: common_phase(label, mode) for label, mode in PHASES.items()}
    assert len(PHASE_PROOFS) == 16
    regressions = {}
    for mode, count in install.COUNTS.items():
        regressions["stage-" + mode] = historical_stage(mode, PHASE_PROOFS["stage-" + mode])
        install.application_gate(install.APP, "installed-" + mode, count)
        regressions["installed-" + mode] = parsed("installed-" + mode + "/regression.json")
        parsed("installed-" + mode + "/manifest.json")
        if mode != "cold":
            verify_backup("installed-" + mode, regressions["installed-" + mode])
    ctest = ctest_summary()
    admission = json.loads(CAPTURED["step-admission-self-test/run.log"])
    assert admission["schema"] == "FreeCAD.LOCAL_INSTALL_PRODUCER_ADMISSION_SELF_TEST_V1"
    assert admission["passed"] is True and admission["helper_sha256"] == install.AUDITOR_SHA
    assert admission["accepted_count"] == len(admission["accepted"]) == 3
    assert admission["rejected_count"] == len(admission["rejected"]) == 64
    assert set(admission["accepted"]) == {"valid-payload", "valid-stage", "valid-custody"}
    assert len(set(admission["rejected"])) == 64
    assert sum(":substituted-" in name for name in admission["rejected"]) == 6
    assert admission["native_build_app_solver_or_signature_execution"] is False
    assert admission["production_app_profile_or_existing_evidence_writes"] is False
    audits = {}
    for mode, filename in (("payload", "independent-payload-audit.json"),
                           ("stage", "independent-stage-audit.json"),
                           ("custody", "independent-stage-custody.json")):
        audits[mode] = install.admit_audit(parsed(filename), mode)
    payload, stage, custody = (audits[mode] for mode in ("payload", "stage", "custody"))
    assert stage["payload_audit_sha256"] == custody["payload_audit_sha256"] == sha(CAPTURED["independent-payload-audit.json"])
    assert custody["stage_audit_sha256"] == sha(CAPTURED["independent-stage-audit.json"])
    assert custody["profiles_inventory_receipt_sha256"] == install.digest(ROOT / "profile-inventories.json")
    assert custody["critical_receipt_sha256"] == sha(capture("critical-before-DESTDIR.json"))
    assert stage["sealed_stage_inventory_sha256"] == install.canonical_sha(SEALED)
    assert payload["baseline_inventory_sha256"] == stage["baseline_inventory_sha256"] == install.canonical_sha(BASELINE)
    assert payload["payload_inventory_sha256"] == install.canonical_sha(install.inventory(ROOT / "payload"))
    assert payload["payload_native_count"] == stage["native_payload_parity_count"] == custody["native_payload_count"] == 61
    assert stage["non_native_payload_matches"] == 3850 and stage["selected_source_matches"] == 52
    assert payload["native_complete_relative_set_sha256"] == stage["native_complete_relative_set_sha256"] == custody["native_complete_relative_set_sha256"]
    native = {row["relative"] for row in payload["native"]}
    assert len(native) == len(payload["native"]) == len(stage["native"]) == 61
    assert native == {row["relative"] for row in stage["native"]}
    assert install.canonical_sha(sorted(native)) == payload["native_complete_relative_set_sha256"]
    for row in stage["native"]:
        sealed_claim(
            install.APP / "Contents/Resources" / row["relative"],
            row["stage_sha256"], install.APP,
        )
    static = parsed("deployment-static-review.json")
    assert static["schema"] == "FreeCAD-9ii-deployment-static-review-v1"
    assert static["unresolved_material_findings"] == [] and static["source_commit"] == install.COMMIT
    for name, wanted in static["reviewed_current_files_sha256"].items():
        assert sha(capture(name)) == wanted, name
    for path in sorted(ROOT.glob("*.py")):
        capture(path.name)
    for name in ("build-identity.json", "namespace-plan.json", "LOCAL-INSTALL.txt"):
        capture(name)
    for name in install.EXTENSIONS:
        capture(name + ".plist")
    capture(str(Path(__file__).relative_to(ROOT)))
    archive, mapping = fixture_archive()
    historical = []
    for directory in sorted(ROOT.iterdir()):
        if directory.name in PHASES or not directory.is_dir() or directory.is_symlink():
            continue
        if (directory / "execution.json").is_file():
            row = parsed(directory.name + "/execution.json")
            log = capture(directory.name + "/run.log")
            assert row["log_sha256"] == sha(log)
            for name in ("manifest.json", "regression.json"):
                if (directory / name).is_file():
                    capture(directory.name + "/" + name)
            historical.append({"label": directory.name, "passed": row.get("passed"),
                               "returncode": row.get("returncode"), "qualifying": False})
    for relative, data in CAPTURED.items():
        assert regular_bytes(ROOT / relative) == data, relative
    for path, data in FIXTURES.items():
        assert regular_bytes(path) == data, path
    final_custody()
    DEST.mkdir()
    index = {}

    def publish(name, data, original=None):
        path = DEST / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(data)
        index[name] = {"bytes": len(data), "sha256": sha(data)}
        if original is not None:
            index[name]["uncompressed_sha256"] = sha(original)

    for relative, data in sorted(CAPTURED.items()):
        compressed = relative.endswith("run.log")
        publish(relative + ".gz" if compressed else relative,
                gzip.compress(data, mtime=0) if compressed else data,
                data if compressed else None)
    manifest = regular_bytes(install.BUILD / "install_manifest.txt")
    publish("install_manifest.txt.gz", gzip.compress(manifest, mtime=0), manifest)
    publish("native-fixtures.tar.gz", archive)
    publish("native-fixture-paths.json", (json.dumps(mapping, indent=2) + "\n").encode())
    publish("historical-stage-native-input-relocations.json", (json.dumps({
        "schema": "FreeCAD-9ii-historical-stage-rename-proof-v1", "entries": RELOCATIONS,
        "original_receipts_and_absolute_provenance_unchanged": True,
        "history_requalified_as_Current": False,
    }, indent=2) + "\n").encode())
    install.write_json(DEST / "index.json", {
        "schema": "FreeCAD-9ii-installation-evidence-index-v1", "source_commit": install.COMMIT,
        "files": index, "raw_app_or_profile_inventory_bodies_retained": False,
        "native_executables_retained": False,
    })
    final_custody()
    london = ZoneInfo("Europe/London")
    installed_time = datetime.datetime.fromtimestamp(install.APP.stat().st_mtime, london)
    summary = {
        "schema": "FreeCAD-9ii-installation-validation-v1", "passed": True,
        "date": datetime.datetime.now(london).date().isoformat(), "timezone": "Europe/London",
        "deployment_bead": "FreeCAD-amg", "fix_bead": "FreeCAD-9ii",
        "application": str(install.APP), "rollback_backup": str(install.BACKUP),
        "source_commit": install.COMMIT, "revision": install.REVISION,
        "native_sha256": install.NATIVE_SHA, "modified_local_time": installed_time.isoformat(),
        "build": {"full_incremental_Release": True, "clean_from_scratch_claimed": False,
                  "nonfatal_Pivy_stub_warning_tracked_separately": "FreeCAD-szc"},
        "ctest": ctest,
        "admission_self_test": {"valid_accepted": 3, "invalid_rejected": 64},
        "application_tests": {
            "stage": dict(install.COUNTS), "installed": dict(install.COUNTS),
            "stage_total": 148, "installed_total": 148, "total_executed": 296,
            "source_feature_qualification_135_added_to_deployment_total": False,
            "separate_process_cold_restore_per_location": True,
        },
        "payload": {
            "complete_native_images": 61, "non_native_payload_matches": 3850,
            "selected_source_matches": 52, "full_DESTDIR_manifest_leaf_set_verified": True,
            "stage_and_installed_exact_sealed_inventory_sha256": install.canonical_sha(SEALED),
            "old_backup_exact_inventory_sha256": install.canonical_sha(BASELINE),
            "strict_signatures_and_QuickLook_entitlements_verified": True,
            "resources_readonly_and_cachefree": True,
        },
        "preservation": {"profiles_unchanged": 3, "external_namespace_files_unchanged": 11,
                         "selected_critical_dependency_files_unchanged": len(critical["files"]),
                         "whole_dependency_environment_inventory_claimed": False},
        "phases": {"qualifying_passed": len(PHASES), "historical_other_attempts": historical},
        "fixture_preservation": {
            "regular_files": mapping["file_count"], "archive_sha256": sha(archive),
            "original_absolute_provenance_preserved": True,
            "stage_histories_rebound_or_relabelled_Current": False,
            "native_binaries_and_symlinks_excluded": True,
        },
        "runtime_dependency": str(install.PREFIX), "self_contained": False, "notarized": False,
        "scope": "Current fork software deployment only; no Oomakhi opening/solve or engineering acceptance.",
        "evidence": {"directory": str(DEST.relative_to(install.REPO)), "files": len(index),
                     "index_sha256": install.digest(DEST / "index.json"), "private_directory": str(ROOT)},
        "final_independent_audit": "Published separately after collection; not claimed by this collector.",
        "metadata_note": "Later evidence/tracking commits do not change the exact compiled d15/+235 identity.",
    }
    install.write_json(SUMMARY, summary)
    print(json.dumps({"passed": True, "application": str(install.APP), "revision": install.REVISION,
                      "evidence_files": len(index), "fixture_files": mapping["file_count"],
                      "total_deployment_tests": 296, "summary": str(SUMMARY)}, indent=2))


if __name__ == "__main__":
    main()
