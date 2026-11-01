"""Collect verified e4k deployment evidence; root executes after installed QA.

Original receipts retain their original locations, input pins and verdicts.
Logs and selected native outputs use deterministic, lossless gzip transport.
No application, payload, profile, configuration, CAD or executable body is
published. Collection never launches FreeCAD, a mechanical solver or compiler.
"""

import sys

sys.dont_write_bytecode = True

from collections import Counter
from datetime import datetime
import gzip
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import re
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
REPO = Path("/Users/zukomgwili/src/FreeCAD")
DEST = REPO / "package/local-completion/freecad-e4k-installation-evidence"
SUMMARY = REPO / "package/local-completion/freecad-e4k-installation.json"
COMMIT = "f164295f1a4d2e154f5f53bf1ec434c8e13ad2da"
REVISION = "49261 +247 (Git)"
NATIVE_SHA = "d4970161eb4ec8ea4af7e222d2a1c6dc54f960df33f0f0b0aff00195f1b37959"
LEGACY_COUNTS = {"cmd": 61, "gui": 9, "cold": 1}
E4K_COUNTS = {"cmd": 22, "gui": 1, "cold": 1}
CAPABILITIES = {
    "CCX_FORCE_ACCOUNTING_V3",
    "CCX_CONTACT_STATE_V1",
    *{"CCX_BEAM_SECTION_V" + str(i) for i in range(1, 6)},
}
LOCATIONS = ("stage", "installed")
MODES = ("cmd", "gui", "cold")
PRIVATE_DIRS = {
    "payload",
    "stage-cache",
    "freecad_user_home",
    "freecad_user_data",
    "xdg_config_home",
    "xdg_data_home",
    "xdg_cache_home",
    "__pycache__",
    "dotted.parent",
    ".pixi",
}
PRIVATE_FILES = {
    "baseline-inventory.json",
    "stage-inventory.json",
    "profile-inventories.json",
    "private-custody-before.json",
    "private-custody-after.json",
    "private-application-before.json",
    "private-application-after.json",
    "user.cfg",
    "system.cfg",
}


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


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def validate_legacy_cold(proof):
    """Retain the previous collector's seven independent native history checks."""
    assert proof["passed"] is True
    assert proof["analysis_solver_rerun"] is False
    assert proof["source_inputs_rebound_or_history_promoted_current"] is False
    cases = proof["cases"]
    assert [row["name"] for row in cases] == [
        "v1",
        "v2",
        "v3",
        "v4",
        "v5-ground",
        "v5-connected",
        "v5-fork",
    ]
    assert [row["schema"] for row in cases] == [
        "CCX_BEAM_SECTION_V" + str(i) for i in (1, 2, 3, 4, 5, 5, 5)
    ]
    assert [row["samples"] for row in cases] == [10, 10, 4, 4, 18, 36, 54]
    for row in cases:
        assert row["completed_run"] is False
        assert row["status"].startswith(("Historical", "Stale"))
    v4 = cases[3]["mechanical_results"]
    assert v4["mechanical_partition_preserved"] is True
    assert v4["paired_history_promoted_current"] is False
    for row, components, owners, sources, ends in zip(
        cases[4:], (1, 2, 3), (1, 2, 2), (2, 4, 6), (1, 3, 5)
    ):
        saved = row["mechanical_results"]
        assert saved["components"] == components
        reference = Path(row["reference"]["path"])
        assert reference.is_relative_to(ROOT) and sha(reference) == row["reference"]["sha256"]
        literal = read(reference)
        coupling = literal["provenance"]["coupling"]
        assert len(coupling["materials"]) == len(coupling["sections"]) == owners
        assert len(saved["source_owners"]) == sources and len(saved["support_owners"]) == components
        assert saved["spring_ends"] == ends
        assert type(saved["native_knot_algebraic_rows"]) is int
        assert saved["native_knot_algebraic_rows"] > 0
        assert saved["native_knot_algebraic_rows"] == len(
            literal["frames"][-1]["native_actions"]["knot_algebraic_spcs"]
        )
        assert saved["saved_physical_parameters_preserved"] is True
        assert saved["mechanical_displacement_only_preserved"] is True
    return cases


def main():
    assert __debug__ and not DEST.exists() and not SUMMARY.exists()
    sys.path.insert(0, str(ROOT))
    install = importlib.import_module("stage_install")
    critical = importlib.import_module("critical_pins")
    audit = importlib.import_module("audit_payload_stage")
    e4k = importlib.import_module("run_e4k_application")
    install.no_live_app()
    install.compiled_identity()
    assert (install.COMMIT, install.REVISION, install.NATIVE_SHA) == (COMMIT, REVISION, NATIVE_SHA)
    sealed, baseline = read(ROOT / "stage-inventory.json"), read(ROOT / "baseline-inventory.json")
    assert (
        install.inventory(install.APP) == sealed and install.inventory(install.BACKUP) == baseline
    )
    assert not install.STAGE.exists()
    profiles = read(ROOT / "profile-inventories.json")
    assert len(profiles) == 3
    for name, wanted in profiles.items():
        assert install.inventory(Path(name)) == wanted
    critical_proof = critical.verify()
    assert len(critical_proof["files"]) == 17
    namespace = read(ROOT / "namespace-plan.json")
    assert len(namespace) == 11
    install.check_namespace(namespace)
    for app in (install.APP, install.BACKUP):
        install.verify(app)
        for extension in install.EXTENSIONS:
            assert install.entitlements(
                app / "Contents/Resources/PlugIns" / extension
            ) == install.plistlib.loads((ROOT / (extension + ".plist")).read_bytes())
    for source, relative in install.SOURCES.items():
        assert sha(install.APP / "Contents/Resources" / relative) == sha(REPO / source)
    for label, mode in (("build-latest", "build"), ("ctest-latest", "ctest")):
        install.source_gate(label, mode)
    for mode in MODES:
        install.application_gate(install.APP, mode)
        e4k.admit_application_gate(install.APP, mode)
    plan = read(ROOT / "e4k-test-plan.json")
    assert plan["counts"] == E4K_COUNTS
    assert read(ROOT / "identity.json")["test_plan"]["counts"] == LEGACY_COUNTS

    # The stage bundle was atomically moved to APP. This verifies its identical
    # sealed bytes at their current location; it does not rewrite/rebind any
    # original stage command, receipt, source pin, identity or observation.
    transported_verifications = []

    def verify_pin(name, wanted):
        path = Path(name)
        if path.is_relative_to(install.STAGE):
            current = install.APP / path.relative_to(install.STAGE)
            assert sha(current) == wanted, (path, current)
            transported_verifications.append(
                {
                    "original_stage_input": str(path),
                    "current_identical_sealed_leaf": str(current),
                    "sha256": wanted,
                }
            )
        elif path.is_file() and sha(path) == wanted:
            return
        else:
            matches = [
                p
                for p in (ROOT / "review-history").rglob("*")
                if p.is_file()
                and not p.is_symlink()
                and p.name.endswith((".py", ".py.pending"))
                and sha(p) == wanted
            ]
            assert matches, (name, wanted, "Exact historical helper body unavailable")

    def frame_identity(identity, application):
        assert identity["application"] == str(application)
        assert identity["runtime"][3] == REVISION and identity["runtime"][-1] == COMMIT
        candidate = identity["candidate"]
        assert candidate["sha256"] == NATIVE_SHA and candidate["override"] is False
        assert (
            Path(candidate["path"])
            == application / "Contents/Resources/data/NativeSolvers/ccx-force-accounting"
        )
        assert (
            set(candidate["capabilities"].values()) == CAPABILITIES
            and len(candidate["capabilities"]) == 7
        )
        assert identity["source_or_build_import_override"] is False

    def application_receipt(label, *, new, location, mode):
        directory = ROOT / label
        proof, reg = read(directory / "execution.json"), read(directory / "regression.json")
        application = install.STAGE if location == "stage" else install.APP
        expected = E4K_COUNTS[mode] if new else LEGACY_COUNTS[mode]
        schema = "FreeCAD-e4k" if new else "FreeCAD-bjh"
        assert proof["schema"] == schema + "-literal-application-gate-v1"
        assert reg["schema"] == schema + "-installation-regression-v1"
        assert proof["application"] == reg["application"] == str(application)
        assert proof["location"] == location and proof["mode"] == reg["mode"] == mode
        assert proof["source_commit"] == reg["commit"] == COMMIT
        assert proof["revision"] == reg["revision"] == REVISION
        assert proof["native_sha256"] == reg["native_sha256"] == NATIVE_SHA
        assert proof["passed"] is reg["passed"] is True
        assert proof["returncode"] == 0 and proof["timed_out"] is False
        for key in (
            "child_reaped",
            "process_group_gone",
            "inputs_unchanged",
            "application_unchanged",
            "profiles_and_dependencies_unchanged",
            "original_app_unchanged",
            "strict_signature_verified",
            "semantic_tests_passed",
        ):
            assert proof[key] is True, (label, key)
        assert proof["inputs_before"] == proof["inputs_after"]
        for name, wanted in proof["inputs_after"].items():
            verify_pin(name, wanted)
        assert sha(directory / "run.log") == proof["log_sha256"]
        assert sha(directory / "regression.json") == proof["regression_sha256"]
        assert proof["executed_tests"] == reg["expected_tests"] == reg["executed_tests"] == expected
        ids = reg["selected_test_ids"]
        assert len(ids) == len(set(ids)) == expected
        assert set(ids) == (set(plan["expected_ids"][mode]) if new else install.expected_ids(mode))
        assert proof["skipped_lines"] == reg["skipped"] == reg["failures"] == reg["errors"] == []
        assert reg["gui"] is (mode == "gui")
        for record in (proof, reg):
            assert (
                record["source_or_build_import_override"]
                is record["native_solver_override"]
                is False
            )
        assert reg["original_project_opened_changed_or_solved"] is False
        assert proof["application_inventory_sha256"] == canonical(sealed)
        text = (directory / "run.log").read_text(errors="replace")
        assert re.findall(r"^Ran (\d+) tests? in [0-9.]+s$", text, re.M) == [str(expected)]
        assert len(re.findall(r"^OK$", text, re.M)) == 1
        assert not re.search(
            r"^(FAILED|FAIL:|ERROR:|UNEXPECTED SUCCESS)|\.\.\. skipped", text, re.M
        )
        identity = read(directory / "identity-observation.json")
        frame_identity(identity, application)
        if new:
            assert proof["command"] == e4k.expected_command(application, mode, directory)
            assert reg["identity_sha256"] == sha(ROOT / "identity.json")
            assert reg["test_plan_sha256"] == sha(ROOT / "e4k-test-plan.json")
            assert reg["identity"] == identity
            assert proof["protected_profiles_before"] == proof["protected_profiles_after"]
            for name, wanted in proof["protected_profiles_after"].items():
                assert canonical(install.inventory(Path(name))) == wanted
            for row in reg["final_module_origins"].values():
                assert Path(row["path"]).is_relative_to(application / "Contents/Resources/Mod/Fem")
                verify_pin(row["path"], row["sha256"])
            if mode == "cmd":
                saved = reg["saved_case"]
                assert (
                    saved["source_application"] == str(application)
                    and saved["source_commit"] == COMMIT
                )
                assert saved["native_sha256"] == NATIVE_SHA
                for name in ("document", "literal"):
                    path = Path(saved[name])
                    assert path.is_relative_to(directory) and not path.is_symlink()
                    assert sha(path) == saved[name + "_sha256"]
                equations = list(directory.glob("staged-selfweight-*/run-*/equilibrium.json"))
                assert len(equations) == plan["native_solve_endpoints"] == 15
                for path in equations:
                    assert read(path)["binary_sha256"] == NATIVE_SHA
            elif mode == "gui":
                gui = read(directory / "gui-receipt.json")
                assert gui["passed"] is True and gui["binary_sha256"] == NATIVE_SHA
                assert (
                    gui["executed_deck_unchanged"] is True
                    and gui["source_and_current_frame_bound"] is True
                )
                assert sha(gui["deck"]) == gui["deck_sha256"]
            else:
                cold = read(directory / "cold.json")
                assert cold["passed"] is True
                assert type(cold["CompletedRun"]) is bool
                assert type(cold["completed_run_before"]) is bool
                assert cold["CompletedRun"] == cold["completed_run_before"]
                for key in ("solve_performed", "save_performed", "repair_or_rebind_performed"):
                    assert cold[key] is False
                for key in (
                    "solver_controls_preserved",
                    "material_and_cut_ownership_preserved",
                    "units_and_full_history_preserved",
                ):
                    assert cold[key] is True
                assert all(
                    status.startswith(("Historical", "Stale")) and not status.startswith("Current")
                    for status in cold["availability_before"] + cold["availability_after"]
                )
                saved = read(ROOT / ("e4k-" + location + "-cmd") / "regression.json")["saved_case"]
                assert cold["document"] == saved["document"]
                assert cold["document_sha256"] == saved["document_sha256"]
                literals = read(saved["literal"])
                assert (
                    cold["accounting_sha256"]
                    == hashlib.sha256(literals["accounting"].encode()).hexdigest()
                )
                assert (
                    cold["contact_sha256"]
                    == hashlib.sha256(literals["contact"].encode()).hexdigest()
                )
        elif mode == "cold":
            validate_legacy_cold(read(directory / "cold-observation.json"))
        return {
            "label": label,
            "tests": expected,
            "kind": "e4k" if new else "legacy",
            "location": location,
            "mode": mode,
            "execution_sha256": sha(directory / "execution.json"),
            "regression_sha256": sha(directory / "regression.json"),
            "log_sha256": proof["log_sha256"],
            "passed": True,
        }

    app_phases = [
        application_receipt(
            ("e4k-" if new else "") + location + "-" + mode, new=new, location=location, mode=mode
        )
        for new in (False, True)
        for location in LOCATIONS
        for mode in MODES
    ]
    assert len(app_phases) == 12 and sum(row["tests"] for row in app_phases) == 190
    reports = {}
    for mode, name in (
        ("payload", "independent-payload-audit.json"),
        ("stage", "independent-stage-audit.json"),
        ("custody", "independent-stage-custody.json"),
    ):
        report = read(ROOT / name)
        audit.admit_producer(report, mode, commit=COMMIT, revision=REVISION)
        reports[mode] = report
    assert reports["stage"]["payload_audit_sha256"] == sha(ROOT / "independent-payload-audit.json")
    assert reports["stage"]["sealed_stage_inventory_sha256"] == canonical(sealed)
    assert reports["stage"]["baseline_inventory_sha256"] == canonical(baseline)
    assert reports["custody"]["stage_audit_sha256"] == sha(ROOT / "independent-stage-audit.json")
    assert reports["custody"]["payload_audit_sha256"] == sha(
        ROOT / "independent-payload-audit.json"
    )
    assert reports["custody"]["critical_receipt_sha256"] == sha(
        ROOT / "critical-before-DESTDIR.json"
    )
    assert reports["custody"]["profiles_exact_unchanged_count"] == 3
    assert reports["custody"]["namespace_unchanged_count"] == 11
    assert reports["custody"]["selected_critical_files_unchanged_count"] == 17
    for row in reports["stage"]["native"]:
        actual = install.macho_identity(install.APP / "Contents/Resources" / row["relative"])
        assert actual["sha256"] == row["stage_sha256"]
        assert (
            actual["normalized_sha256"] == row["normalized_sha256"]
            and actual["rpaths"] == row["rpaths"]
        )
    reviews = {}
    for name in ("stage-independent-review.json", "final-independent-review.json"):
        path, report = ROOT / name, read(ROOT / name)
        stage = name.startswith("stage-")
        assert report["schema"] == (
            "FreeCAD-e4k-independent-stage-review-v1"
            if stage
            else "FreeCAD-e4k-independent-installed-review-v1"
        )
        assert report["passed"] is True and report["findings"] == []
        assert (
            report["compiled_commit"] == COMMIT
            and report["revision"] == REVISION
            and report["native_sha256"] == NATIVE_SHA
        )
        helper = (
            ROOT
            / "review"
            / ("independent_stage_review.py" if stage else "independent_final_review.py")
        )
        assert sha(helper) == report["helper_sha256"]
        for source, wanted in report["inputs"].items():
            verify_pin(source, wanted)
        if stage:
            assert report["stage_inventory_sha256"] == canonical(sealed) and report[
                "baseline_inventory_sha256"
            ] == canonical(baseline)
        else:
            assert report["installed_inventory_sha256"] == canonical(sealed) and report[
                "backup_inventory_sha256"
            ] == canonical(baseline)
            assert report["stage_review_sha256"] == sha(ROOT / "stage-independent-review.json")
        reviews[name] = report
    expected_steps = {
        "step-capture-qualified": "capture",
        "step-payload": "payload",
        "step-audit-payload": "audit-payload",
        "step-stage": "stage",
        "step-audit-stage": "audit-stage",
        "step-audit-custody": "audit-custody",
        "step-swap": "swap",
    }
    for label, mode in expected_steps.items():
        path = ROOT / label / "execution.json"
        proof = read(path)
        assert proof["schema"] == "FreeCAD-8rk-install-step-v1" and proof["mode"] == mode
        assert proof["passed"] is True and proof["returncode"] == 0 and proof["timed_out"] is False
        assert proof["source_commit"] == COMMIT
        for key in (
            "child_reaped",
            "process_group_gone",
            "inputs_unchanged",
            "protected_unchanged",
        ):
            assert proof[key] is True
        assert proof["inputs_before"] == proof["inputs_after"]
        for source, wanted in proof["inputs_after"].items():
            verify_pin(source, wanted)
        assert sha(path.parent / "run.log") == proof["log_sha256"]
        if mode == "swap":
            assert proof["expected_sealed_install_and_exact_backup"] is True
        else:
            assert proof["protected_before"] == proof["protected_after"]
    ctest = (ROOT / "ctest-latest/run.log").read_text()
    assert len(re.findall(r"^\s*\d+/\d+ Test\s+#.*\bPassed\s+[0-9.]+ sec", ctest, re.M)) == 2267
    assert "100% tests passed" in ctest
    assert len(re.findall(r"^\s*\d+ - \S+ \(Skipped\)$", ctest, re.M)) == 2
    assert len(re.findall(r"^\s*\d+ - \S+ \(Disabled\)$", ctest, re.M)) == 8
    source_qualifications = []
    for name in (
        "freecad-9rc-validation.json",
        "freecad-bjh-validation.json",
        "freecad-e4k-validation.json",
    ):
        path = REPO / "package/local-completion" / name
        report = read(path)
        assert report.get("passed", report.get("all_required_gates_passed")) is True
        if name == "freecad-e4k-validation.json":
            assert report["native_solver_sha256"] == NATIVE_SHA
        source_qualifications.append({"path": str(path.relative_to(REPO)), "sha256": sha(path)})

    # Decide all public bodies before writing a new repository directory.
    selected_pressure = set()
    for location in LOCATIONS:
        run = ROOT / f"e4k-{location}-cmd"
        candidates = []
        for path in run.glob("staged-selfweight-*/run-*/equilibrium.json"):
            row = read(path)
            deck = next(path.parent.glob("*.inp"))
            text = deck.read_bytes().upper()
            steps = [
                line.replace(b" ", b"")
                for line in text.splitlines()
                if line.split(b",", 1)[0].strip() == b"*STEP"
            ]
            if (
                row["time"] == 1.0
                and row["binary_sha256"] == NATIVE_SHA
                and len(steps) == 1
                and b"AMPLITUDE=STEP" in steps[0].split(b",")
                and b"AMPLITUDE=VARIABLEQPRESSURE" in text
            ):
                candidates.append(path.parent)
        assert len(candidates) == 1, (location, candidates)
        selected_pressure.add(candidates[0])
    assets, omissions, protocols, history = [], [], [], []
    excluded_directories = []

    def omit(path, reason):
        omissions.append(
            {
                "source": str(path),
                "sha256": sha(path),
                "bytes": path.stat().st_size,
                "reason": reason,
            }
        )

    for directory, directories, files in os.walk(ROOT, followlinks=False):
        base = Path(directory)
        keep = []
        for name in sorted(directories):
            path = base / name
            if path.is_symlink() or name in PRIVATE_DIRS or name.lower().endswith(".app"):
                excluded_directories.append(
                    {
                        "source": str(path),
                        "reason": "Private application, payload, profile, dependency or cache subtree; not traversed",
                    }
                )
            else:
                keep.append(name)
        directories[:] = keep
        for name in sorted(files):
            path = base / name
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(ROOT)
            if path.name in PRIVATE_FILES or path.name.startswith(
                ("private-custody-", "private-application-")
            ):
                continue
            suffix = path.suffix.lower()
            if (
                suffix
                in {".cfg", ".o", ".a", ".so", ".dylib", ".pyc", ".zip", ".gz", ".bz2", ".pdf"}
                or suffix.startswith(".fcstd")
                or suffix in {".brep", ".geo", ".msh", ".vtk", ".vtu"}
            ):
                if suffix not in {".cfg", ".pyc"}:
                    omit(path, "Private CAD/native/archive/geometry/mesh body omitted")
                continue
            if ".contact-state" in name and name.endswith(".out"):
                try:
                    body = read(path)
                except (ValueError, KeyError, TypeError) as error:
                    omit(
                        path,
                        "Unparseable failed/partial native contact output; original failure receipts/logs retained: "
                        + type(error).__name__,
                    )
                    continue
                protocols.append(
                    {
                        "source": str(path),
                        "bytes": path.stat().st_size,
                        "sha256": sha(path),
                        "schema": body["schema"],
                        "request": body["request"],
                        "complete": body["complete"],
                        "units": body["units"],
                        "inventory_scope": body.get("inventory_scope"),
                        "frames": [
                            {
                                "step": frame["step"],
                                "increment": frame["increment"],
                                "time": frame["time"],
                                "complete": frame["complete"],
                                "sample_count": len(frame["samples"]),
                                "catalogue_samples": len(frame.get("sample_inventory", [])),
                                "faces": len(frame.get("face_inventory", [])),
                                "availability": dict(
                                    Counter(row["availability"] for row in frame["samples"])
                                ),
                            }
                            for frame in body["frames"]
                        ],
                    }
                )
                if path.parent in selected_pressure:
                    assets.append((path, relative, "gzip"))
                else:
                    omit(
                        path,
                        "Heavy native contact catalogue; full protocol hash/frame summary and dedicated full-pressure body retained",
                    )
            elif ".contact-state" in name and name.endswith(".out.tmp"):
                omit(path, "Unpublished native contact temporary output")
            elif suffix in {".frd", ".dat"}:
                if path.parent in selected_pressure:
                    assets.append((path, relative, "gzip"))
                else:
                    omit(
                        path,
                        "Other private native FRD/DAT bulk; full-pressure counterparts retained",
                    )
            elif name == "saved-literals.json":
                omit(
                    path,
                    "Duplicate full saved literals remain private; exact cold hash checks and native protocol bodies/summaries retained",
                )
            elif suffix == ".log":
                assets.append((path, relative, "gzip"))
            elif (
                suffix
                in {
                    ".json",
                    ".py",
                    ".png",
                    ".plist",
                    ".inp",
                    ".accounting",
                    ".contact-state",
                    ".stdout",
                    ".stderr",
                }
                or name.endswith(".py.pending")
                or name == "LOCAL-INSTALL.txt"
                or re.fullmatch(r".+\.(?:accounting|contact-state)\.run-[0-9a-f]{32}", name)
            ):
                if path.suffix == ".json" and "review" in name and "inputs" in read(path):
                    # Private peer input maps may name bulk inventories. Publish
                    # an explicitly labelled derivative, never a fake rerun.
                    original = read(path)
                    derivative = {key: value for key, value in original.items() if key != "inputs"}
                    derivative.update(
                        publication_is_derivative=True,
                        original_private_path=str(path),
                        original_sha256=sha(path),
                        input_record_count=len(original["inputs"]),
                        inputs_canonical_sha256=canonical(original["inputs"]),
                        original_retained_unchanged=True,
                        publication_is_new_review_or_reexecution=False,
                    )
                    assets.append(
                        (path, relative.with_name(path.stem + "-public.json"), encoded(derivative))
                    )
                else:
                    assets.append((path, relative, "exact"))
            elif suffix == ".txt" and any(
                word in name.lower() for word in ("stdout", "stderr", "error", "traceback")
            ):
                assets.append((path, relative, "gzip"))
            else:
                omit(path, "Unselected private native auxiliary body")
            if name == "execution.json":
                proof = read(path)
                history.append(
                    {
                        "source": str(path),
                        "sha256": sha(path),
                        "passed": proof.get("passed"),
                        "returncode": proof.get("returncode"),
                        "schema": proof.get("schema"),
                    }
                )
    # Include CMake's exact manifest without copying the application payload.
    assets.append((install.BUILD / "install_manifest.txt", Path("install_manifest.txt"), "exact"))
    DEST.mkdir()
    index = []
    attributes = DEST / ".gitattributes"
    attributes.write_bytes(
        b"# Exact evidence bodies and deterministic gzip transport.\n* -text -whitespace\n"
    )
    index.append(
        {
            "path": ".gitattributes",
            "sha256": sha(attributes),
            "bytes": attributes.stat().st_size,
            "kind": "collector-generated-policy",
            "source": str(Path(__file__)),
        }
    )
    for source, relative, transport in assets:
        raw = source.read_bytes()
        original_sha = hashlib.sha256(raw).hexdigest()
        if transport == "gzip":
            target = DEST / relative.with_name(relative.name + ".gz")
            out = io.BytesIO()
            with gzip.GzipFile(fileobj=out, mode="wb", filename="", mtime=0) as stream:
                stream.write(raw)
            body, kind = out.getvalue(), "lossless-gzip-original"
            assert hashlib.sha256(gzip.decompress(body)).hexdigest() == original_sha
        elif transport == "exact":
            target, body, kind = DEST / relative, raw, "exact-original"
        else:
            target, body, kind = DEST / relative, transport, "labelled-public-review-derivative"
        assert not target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(body)
        assert sha(source) == original_sha
        index.append(
            {
                "path": str(target.relative_to(DEST)),
                "sha256": sha(target),
                "bytes": len(body),
                "source": str(source),
                "source_sha256": original_sha,
                "source_bytes": len(raw),
                "kind": kind,
            }
        )
    generated = {
        "native-protocol-bindings.json": {
            "schema": "FreeCAD-e4k-installed-native-protocol-bindings-v1",
            "protocols": protocols,
            "selected_full_pressure_directories": sorted(map(str, selected_pressure)),
            "native_sha256": NATIVE_SHA,
        },
        "omitted-private-bulk.json": {
            "schema": "FreeCAD-e4k-installation-omitted-private-bulk-v1",
            "files": omissions,
            "excluded_directory_policy": excluded_directories,
        },
        "sealed-stage-transport-verification.json": {
            "schema": "FreeCAD-e4k-sealed-stage-transport-v1",
            "original_receipts_rewritten": False,
            "stage_outputs_reexecuted_or_rebound": False,
            "actual_installed_inventory_sha256": canonical(sealed),
            "identical_moved_leaf_verifications": transported_verifications,
        },
    }
    for name, data in generated.items():
        path = DEST / name
        with path.open("xb") as stream:
            stream.write(encoded(data))
        index.append(
            {
                "path": name,
                "sha256": sha(path),
                "bytes": path.stat().st_size,
                "kind": "collector-derived-manifest",
                "source": str(Path(__file__)),
            }
        )
    index_path = DEST / "index.json"
    with index_path.open("xb") as stream:
        stream.write(
            encoded(
                {
                    "schema": "FreeCAD-e4k-installation-artifact-index-v1",
                    "artifacts": index,
                    "self_hash_policy": "Index excludes its own recursive hash; summary records its external digest.",
                }
            )
        )
    summary = {
        "schema": "FreeCAD-e4k-installation-validation-v1",
        "passed": True,
        "source_commit": COMMIT,
        "revision": REVISION,
        "native_sha256": NATIVE_SHA,
        "native_capabilities": sorted(CAPABILITIES),
        "fix_bead": "FreeCAD-e4k",
        "deployment_bead": "FreeCAD-vk6",
        "application": str(install.APP),
        "rollback_backup": str(install.BACKUP),
        "runtime_dependency": str(install.PREFIX),
        "self_contained": False,
        "notarized": False,
        "ad_hoc_signed": True,
        "date": datetime.now(ZoneInfo("Europe/London")).isoformat(),
        "timezone": "Europe/London",
        "modified_local_time": datetime.fromtimestamp(
            install.APP.stat().st_mtime, ZoneInfo("Europe/London")
        ).isoformat(),
        "build": {"full_incremental_Release": True, "clean_from_scratch_claimed": False},
        "application_tests": {
            "legacy_per_location": LEGACY_COUNTS,
            "e4k_per_location": E4K_COUNTS,
            "locations": list(LOCATIONS),
            "total_executed": sum(row["tests"] for row in app_phases),
            "skipped": [],
            "phases": app_phases,
            "native_solver_override": False,
            "source_or_build_import_override": False,
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
        "source_qualification": source_qualifications,
        "peer_reviews": {
            name: {
                "original_private_path": str(ROOT / name),
                "sha256": sha(ROOT / name),
                "passed": report["passed"],
                "findings": report["findings"],
            }
            for name, report in reviews.items()
        },
        "qualifying_pipeline_phase_count": 2 + len(expected_steps) + len(app_phases),
        "original_execution_history": history,
        "scope": {
            "deployment": "Latest fork with staged density-based gravity and independent same-step Q histories; prior fixes retained.",
            "original_project_opened_changed_or_solved": False,
            "engineering_acceptance": False,
            "original_1percent_equilibrium_and_5percent_sensitivity_limits_changed": False,
            "lifecycle_process_instrumentation": "A shipped lifecycle test wraps Popen and invokes its retained original for actual native child execution; no blanket no-mocks claim.",
        },
        "privacy": {
            "bulk_app_and_profile_inventories_published": False,
            "native_executables_CAD_config_profiles_or_archives_published": False,
            "original_absolute_provenance_preserved": True,
            "original_executed_receipts_rewritten": False,
            "logs_losslessly_gzip_encoded": True,
        },
        "metadata_note": "Later deployment-tracking commits do not change compiled f164295f1a/+247 identity.",
        "evidence": {
            "directory": str(DEST.relative_to(REPO)),
            "private_directory": str(ROOT),
            "files_excluding_index": len(index),
            "index_sha256": sha(index_path),
            "omitted_bulk_records": len(omissions),
        },
    }
    assert (
        summary["application_tests"]["total_executed"] == 190
        and summary["qualifying_pipeline_phase_count"] == 21
    )
    assert (
        install.inventory(install.APP) == sealed and install.inventory(install.BACKUP) == baseline
    )
    critical.verify()
    install.check_namespace(namespace)
    install.no_live_app()
    with SUMMARY.open("xb") as stream:
        stream.write(encoded(summary))
    print(
        json.dumps(
            {
                "passed": True,
                "summary": str(SUMMARY),
                "files_excluding_index": len(index),
                "index_sha256": sha(index_path),
                "revision": REVISION,
                "tests": 190,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
