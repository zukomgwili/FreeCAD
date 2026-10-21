"""Fresh 9ii admission adapter over immutable staging/signing/rollback code.

Imports define helpers only. Root alone may invoke the explicit stage/swap
actions. No prior installation receipt is qualifying evidence for this image.
"""

import hashlib
import importlib.util
import json
import re
import signal
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
TASK = Path(__file__).resolve().parent
sys.path.insert(0, str(TASK))

import run_gate

ORIGINAL = Path(
    "/Users/zukomgwili/src/FreeCAD/package/local-completion/"
    "freecad-ywu-installation-evidence/private/stage_install.py"
)
CORE_SHA = "cca627502a56b6c9b4aefa4a970172c51e42e2dde834000decca65fd44ab46d9"
AUDITOR_SHA = "82f9e5ba571599b06a6df87811bb9384a28f3661c9e563820e93e11988ccf3e3"
AUDIT_SCHEMA = "FreeCAD.LOCAL_INSTALL_INDEPENDENT_AUDIT_V2"
APPLICATION_SCHEMA = "FreeCAD-9ii-literal-application-gate-v1"
REGRESSION_SCHEMA = "FreeCAD-9ii-installation-regression-v1"
COUNTS = {"cmd": 132, "gui": 14, "cold": 2}
assert __debug__ and not sys.flags.optimize
assert hashlib.sha256(ORIGINAL.read_bytes()).hexdigest() == CORE_SHA
spec = importlib.util.spec_from_file_location("_immutable_9ii_install_core", ORIGINAL)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
core.ROOT = TASK
core.STAGE = TASK / core.APP.name
core.BACKUP = Path(
    "/Users/zukomgwili/Applications/FreeCAD Backups/"
    "FreeCAD-27.1.0-before-9ii-4eb8f43362.app"
)
core.COMMIT = "d15a59e8ff39d610337b02ca290fe477d24d065c"
core.REVISION = "49261 +235 (Git)"
core.NATIVE_SHA = "0c2a86318df9c7cc9d921e5068ae52f1d53e27b7b16747e00a74ccc8fe37c6cc"

# Retain every selected source equality from the previous deployed 8rk image,
# then add all new 9ii product modules, public native tests and native observer.
for relative in (
    "femtools/elastic_connector.py",
    "femsolver/calculix/writer.py",
    "femtools/rigid_body.py",
    "femtest/app/support_utils.py",
    "femtest/app/test_rigid_region_ownership.py",
    "femsolver/calculix/write_constraint_rigidbody.py",
    "femsolver/calculix/write_constraint_rigidbody_step.py",
    "femtest/app/test_elastic_connector.py",
    "femtest/app/coupled_port_fixture.py",
    "femtest/app/coupled_port_audit.py",
    "femtest/app/test_moving_port_capacity_native.py",
    "femtest/data/calculix/coupled_port_capacity_fixture.json",
    "femtest/data/calculix/coupled_port_capacity_oracle.json",
    "femmesh/quality.py",
    "femsolver/calculix/write_step_output.py",
    "femtaskpanels/task_solver_ccxtools.py",
    "femtest/app/test_contact_state_interfaces.py",
    "femtest/app/test_contact_state_native.py",
    "femtest/app/test_input_fingerprint.py",
    "femtest/gui/test_contact_state.py",
    "femtools/contact_state.py",
    "femtools/native_properties.py",
    "femviewprovider/view_contact_state.py",
):
    core.SOURCES["src/Mod/Fem/" + relative] = "Mod/Fem/" + relative
core.SOURCES["package/calculix/force-accounting/contactstate.c"] = (
    "data/NativeSolvers/source/contactstate.c"
)


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        assert key not in result, "Duplicate receipt member: " + key
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError("Nonfinite receipt constant: " + value)


def read(path):
    return json.loads(
        Path(path).read_text(), object_pairs_hook=_unique_pairs, parse_constant=_nonfinite
    )


def source_gate(label, mode):
    directory = TASK / label
    proof = read(directory / "execution.json")
    assert proof["schema"] == "FreeCAD-8rk-isolated-native-gate-v1"
    assert proof["mode"] == mode and proof["source_commit"] == core.COMMIT
    assert proof["passed"] is True and type(proof["returncode"]) is int
    assert proof["returncode"] == 0 and proof["timed_out"] is False
    for field in (
        "child_reaped",
        "process_group_gone",
        "source_and_supervisor_unchanged",
        "app_and_three_profiles_unchanged",
    ):
        assert proof[field] is True, (label, field)
    assert proof["source_inputs_before"] == proof["source_inputs_after"]
    assert proof["source_inputs_after"]
    for name, wanted in proof["source_inputs_after"].items():
        assert core.digest(name) == wanted, name
    assert proof["protected_before"] == proof["protected_after"]
    assert core.digest(directory / "run.log") == proof["log_sha256"]
    return proof


def compiled_identity():
    assert hashlib.sha256(ORIGINAL.read_bytes()).hexdigest() == CORE_SHA
    assert subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=core.REPO, text=True, timeout=10
    ).strip() == core.COMMIT
    subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", "src", "tests/src", "package/calculix"],
        cwd=core.REPO,
        check=True,
        timeout=10,
    )
    values = dict(
        re.findall(
            r'^#define\s+(\w+)\s+"([^"]*)"',
            (core.BUILD / "src/Build/Version.h").read_text(),
            re.M,
        )
    )
    assert values["FCRepositoryHash"] == core.COMMIT
    assert values["FCRevision"] == core.REVISION
    source_gate("build-latest", "build")
    assert core.digest(core.BUILD / "data/NativeSolvers/ccx-force-accounting") == core.NATIVE_SHA
    if (TASK / "build-identity.json").exists():
        for name, wanted in read(TASK / "build-identity.json").items():
            assert core.digest(name) == wanted, name
    return values


_original_source_equal = core.source_equal


def source_equal(resources):
    _original_source_equal(resources)
    candidate = resources / "data/NativeSolvers/ccx-force-accounting"
    assert subprocess.check_output(
        [str(candidate), "--freecad-contact-state-version"], text=True, timeout=10
    ).strip() == "CCX_CONTACT_STATE_V1"


def admit_audit(proof, mode):
    helper = TASK / "audit_payload_stage.py"
    assert re.fullmatch(r"[0-9a-f]{64}", AUDITOR_SHA), "Auditor is not frozen"
    assert core.digest(helper) == AUDITOR_SHA
    assert proof["schema"] == AUDIT_SCHEMA and proof["mode"] == mode
    assert proof["passed"] is True and proof["helper_sha256"] == AUDITOR_SHA
    from audit_payload_stage import admit_producer

    return admit_producer(proof, mode, commit=core.COMMIT, revision=core.REVISION)


def application_gate(application, label, count):
    location = "stage" if application == core.STAGE else "installed"
    assert application in (core.STAGE, core.APP)
    mode = label.removeprefix(location + "-")
    assert label == location + "-" + mode and COUNTS[mode] == count
    directory = TASK / label
    proof = read(directory / "execution.json")
    assert proof["schema"] == APPLICATION_SCHEMA
    assert proof["mode"] == mode and proof["location"] == location
    assert proof["application"] == str(application)
    assert proof["source_commit"] == core.COMMIT and proof["revision"] == core.REVISION
    assert proof["native_sha256"] == core.NATIVE_SHA
    assert proof["passed"] is True and type(proof["returncode"]) is int
    assert proof["returncode"] == 0 and proof["timed_out"] is False
    for field in (
        "child_reaped",
        "process_group_gone",
        "application_unchanged",
        "profiles_and_dependencies_unchanged",
        "inputs_unchanged",
        "strict_signature_verified",
        "original_app_unchanged",
        "semantic_tests_passed",
    ):
        assert proof[field] is True, (label, field)
    assert proof["source_or_build_import_override"] is False
    assert proof["native_solver_override"] is False
    assert proof["expected_tests"] == proof["executed_tests"] == count
    assert proof["inputs_before"] == proof["inputs_after"] and proof["inputs_after"]
    for name, wanted in proof["inputs_after"].items():
        assert core.digest(name) == wanted, name
    sealed = read(TASK / "stage-inventory.json")
    assert proof["application_inventory_sha256"] == core.canonical_sha(sealed)
    assert core.inventory(application) == sealed
    assert core.digest(directory / "run.log") == proof["log_sha256"]
    assert core.digest(directory / "regression.json") == proof["regression_sha256"]
    regression = read(directory / "regression.json")
    assert regression["schema"] == REGRESSION_SCHEMA and regression["passed"] is True
    assert regression["application"] == str(application)
    assert regression["commit"] == core.COMMIT and regression["revision"] == core.REVISION
    assert regression["location"] == location and regression["mode"] == mode
    assert regression["gui"] is (mode == "gui")
    assert regression["native_sha256"] == core.NATIVE_SHA
    assert regression["test_count"] == count
    ids = regression["selected_test_ids"]
    assert len(ids) == len(set(ids)) == count
    assert regression["only_public_native_interfaces"] is True
    assert regression["Oomakhi_opened_or_solved"] is False
    assert regression["source_or_build_import_override"] is False
    assert regression["manifest_sha256"] == core.digest(directory / "manifest.json")
    assert regression["module_sha256"] == core.digest(TASK / "App9iiIdentity.py")
    identity = regression["identity"]
    assert identity["runtime"][3] == core.REVISION and identity["runtime"][-1] == core.COMMIT
    assert identity["source_or_build_import_override"] is False
    assert identity["candidate"]["override"] is False
    assert identity["candidate"] == {
        "path": str(application / "Contents/Resources/data/NativeSolvers/ccx-force-accounting"),
        "sha256": core.NATIVE_SHA,
        "override": False,
        "capabilities": {
            "--freecad-force-accounting-version": "CCX_FORCE_ACCOUNTING_V3",
            "--freecad-contact-state-version": "CCX_CONTACT_STATE_V1",
        },
    }
    log = (directory / "run.log").read_text(errors="replace")
    assert re.findall(r"^Ran (\d+) tests? in [0-9.]+s$", log, re.M) == [str(count)]
    assert len(re.findall(r"^OK$", log, re.M)) == 1
    assert not re.search(r"^(?:FAILED|FAIL:|ERROR:|UNEXPECTED SUCCESS)|\.\.\. skipped", log, re.M)
    if mode == "cold":
        cold = regression["cold_restore"]
        for field in (
            "no_native_solve",
            "no_history_or_provenance_repair",
            "literal_original_raw_labels_preserved",
        ):
            assert cold[field] is True, field
        assert cold["initial_status"].startswith("Historical")
        assert cold["refresh_status"].startswith("Unavailable")
        assert cold["source_files_before"] == cold["source_files_after"]
        witnesses = read(TASK / (location + "-cmd/execution.json"))["cold_witness_documents"]
        assert len(witnesses) == 1 and witnesses[0]["path"] == cold["document"]
        assert core.digest(cold["document"]) == witnesses[0]["sha256"]
    else:
        backup = regression["backup_regression"]
        assert backup["backups_contain_exact_previous_target_bytes"] is True
        assert backup["no_escape_or_temporary_leftovers"] is True
        assert backup["only_public_native_interfaces"] is True
        assert [row["marker"] for row in backup["same_process_native_reopen"]] == [
            "third", "first", "second"
        ]
        for name, wanted in backup["file_sha256"].items():
            assert Path(name).is_relative_to(directory / "witness")
            assert core.digest(name) == wanted, name
    return proof


def check_stage_receipts(sealed):
    import critical_pins

    compiled_identity()
    source_gate("ctest-latest", "ctest")
    critical_pins.verify()
    assert core.inventory(core.STAGE) == sealed
    rows = {}
    for mode, name in (
        ("payload", "independent-payload-audit.json"),
        ("stage", "independent-stage-audit.json"),
        ("custody", "independent-stage-custody.json"),
    ):
        rows[mode] = admit_audit(read(TASK / name), mode)
    payload, stage, custody = (rows[mode] for mode in ("payload", "stage", "custody"))
    native = {row["relative"] for row in payload["native"]}
    assert native and len(native) == len(payload["native"])
    assert native == {row["relative"] for row in stage["native"]}
    assert len(stage["native"]) == len(native)
    assert len(native) == payload["payload_native_count"]
    assert len(native) == stage["native_payload_parity_count"] == custody["native_payload_count"]
    native_sha = core.canonical_sha(sorted(native))
    for proof in (payload, stage, custody):
        assert proof["native_complete_relative_set_sha256"] == native_sha
    assert stage["sealed_stage_inventory_sha256"] == core.canonical_sha(sealed)
    assert stage["payload_audit_sha256"] == core.digest(TASK / "independent-payload-audit.json")
    assert custody["payload_audit_sha256"] == core.digest(TASK / "independent-payload-audit.json")
    assert custody["stage_audit_sha256"] == core.digest(TASK / "independent-stage-audit.json")
    assert custody["profiles_inventory_receipt_sha256"] == core.digest(
        TASK / "profile-inventories.json"
    )
    assert custody["critical_receipt_sha256"] == core.digest(TASK / "critical-before-DESTDIR.json")
    baseline_sha = core.canonical_sha(read(TASK / "baseline-inventory.json"))
    assert payload["baseline_inventory_sha256"] == baseline_sha
    assert stage["baseline_inventory_sha256"] == baseline_sha
    assert payload["payload_inventory_sha256"] == core.canonical_sha(
        core.inventory(TASK / "payload")
    )
    assert custody["profiles_exact_unchanged_count"] == len(core.PROFILES)
    assert custody["namespace_unchanged_count"] == len(core.NAMESPACE_FILES)
    assert custody["baseline_and_stage_exact"] is True
    assert custody["strict_signatures_quicklook_readonly_cachefree"] is True
    for mode, count in COUNTS.items():
        application_gate(core.STAGE, "stage-" + mode, count)


_original_stage = core.stage


def stage():
    admit_audit(read(TASK / "independent-payload-audit.json"), "payload")
    return _original_stage()


def reject_historical_validator(*_args, **_kwargs):
    raise RuntimeError("Historical installation gates are not qualifying evidence for 9ii")


core.compiled_identity = compiled_identity
core.source_equal = source_equal
core.no_live_app = run_gate.serial
core.HELPER = {"no_live_app": lambda *_: run_gate.serial()}
core.check_stage_receipts = check_stage_receipts
core.check_app_receipts = reject_historical_validator
core.stage = stage
globals().update({key: value for key, value in vars(core).items() if not key.startswith("__")})

if __name__ == "__main__":
    assert __debug__ and not sys.flags.optimize
    assert sys.argv[1:] in (["stage"], ["swap"])
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, core.interrupted)
    {"stage": core.stage, "swap": core.swap}[sys.argv[1]]()
