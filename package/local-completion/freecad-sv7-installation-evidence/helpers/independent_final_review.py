"""Independent offline installed-image and rollback audit; no native execution."""

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path("/private/tmp/freecad-sv7-install-o698f09g")
HELPER = ROOT / "independent_stage_review.py"
assert hashlib.sha256(HELPER.read_bytes()).hexdigest() == "5e98a43f1bfeb73fa06296e2cd22b12818aaa07db89a91b649465d969f4abc43"
spec = importlib.util.spec_from_file_location("_independent_offline_sv7_stage", HELPER)
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)
sha, read, canonical = common.sha, common.read, common.canonical
APP, RES, REPO, PREFIX = common.APP, common.RES, common.REPO, common.PREFIX
COMMIT, NATIVE = common.COMMIT, common.NATIVE
BACKUP = Path(
    "/Users/zukomgwili/Applications/FreeCAD Backups/FreeCAD-27.1.0-before-sv7-o698f09g.app"
)


def main():
    sha(HELPER)
    stage_report = ROOT / "stage-independent-review.json"
    assert len(sys.argv) == 2 and re.fullmatch(r"[0-9a-f]{64}", sys.argv[1])
    assert sha(stage_report) == sys.argv[1]
    prior = read(stage_report)
    assert prior["passed"] is True and prior["findings"] == []
    baseline, sealed = read(ROOT / "baseline-inventory.json"), read(ROOT / "stage-inventory.json")
    assert common.inventory(APP) == sealed and common.inventory(BACKUP) == baseline
    assert not common.STAGE.exists(), "Swap must not leave a second staged app"
    assert (
        canonical(baseline)
        == prior["baseline_inventory_sha256"]
        == "35421d224265349faebeb8ab974ec69e77452e0c44cb7b758709985292d86081"
    )
    assert canonical(sealed) == prior["stage_inventory_sha256"]
    identity = read(ROOT / "identity.json")
    assert (
        identity["commit"] == COMMIT
        and identity["revision"] == "49261 +242 (Git)"
        and identity["native_sha256"] == NATIVE
    )
    swap = read(ROOT / "step-swap/execution.json")
    assert swap["schema"] == "FreeCAD-8rk-install-step-v1" and swap["mode"] == "swap"
    assert swap["source_commit"] == COMMIT and swap["passed"] is True
    assert (
        type(swap["returncode"]) is int and swap["returncode"] == 0 and swap["timed_out"] is False
    )
    for field in (
        "child_reaped",
        "process_group_gone",
        "inputs_unchanged",
        "protected_unchanged",
        "expected_sealed_install_and_exact_backup",
    ):
        assert swap[field] is True, field
    assert swap["inputs_before"] == swap["inputs_after"]
    for path, expected in swap["inputs_after"].items():
        assert sha(path) == expected, path
    assert swap["protected_before"][str(APP)] == canonical(baseline)
    assert swap["protected_after"][str(APP)] == canonical(sealed)
    assert sha(ROOT / "step-swap/run.log") == swap["log_sha256"]
    p, s, c = [
        read(ROOT / name)
        for name in (
            "independent-payload-audit.json",
            "independent-stage-audit.json",
            "independent-stage-custody.json",
        )
    ]
    assert (
        s["payload_audit_sha256"]
        == c["payload_audit_sha256"]
        == sha(ROOT / "independent-payload-audit.json")
    )
    assert c["stage_audit_sha256"] == sha(ROOT / "independent-stage-audit.json")
    assert (
        common.native_set(common.PAY)
        == {row["relative"] for row in p["native"]}
        == {row["relative"] for row in s["native"]}
    )
    assert common.canonical(common.inventory(common.PAYROOT)) == p["payload_inventory_sha256"]
    native = {row["relative"]: row for row in s["native"]}
    prows = {row["relative"]: row for row in p["native"]}
    assert len(native) == prior["payload_native_images"]
    for relative, row in native.items():
        installed = common.macho(APP / RES / relative)
        incoming = common.macho(common.PAY / relative)
        assert installed["sha256"] == row["stage_sha256"]
        assert incoming["sha256"] == row["payload_sha256"] == prows[relative]["payload_sha256"]
        assert installed["normalized"] == incoming["normalized"]
        assert (
            installed["normalized_sha256"]
            == row["normalized_sha256"]
            == prows[relative]["normalized_sha256"]
        )
        assert installed["rpaths"] == incoming["rpaths"] == row["rpaths"]
    for row in s["additional_inherited_native"]:
        original, installed = common.macho(BACKUP / row["relative"]), common.macho(
            APP / row["relative"]
        )
        assert (
            original["sha256"] == row["old_sha256"] and installed["sha256"] == row["stage_sha256"]
        )
        assert (
            original["normalized"] == installed["normalized"]
            and original["rpaths"] == installed["rpaths"]
        )
    assert common.native_set(APP) == {str(RES / name) for name in native} | (
        common.native_set(BACKUP) - {str(RES / name) for name in native}
    )
    sources = common.source_map()
    assert len(sources) == prior["selected_source_matches"]
    for source, target in sources.items():
        assert sha(REPO / source) == sha(APP / RES / target), source
    assert sha(APP / RES / "data/NativeSolvers/ccx-force-accounting") == NATIVE
    resources = common.inventory(APP / RES)
    assert all(row["kind"] == "link" or not row["mode"] & 0o222 for row in resources.values())
    assert not any("__pycache__" in Path(name).parts or name.endswith(".pyc") for name in resources)
    profiles = read(ROOT / "profile-inventories.json")
    assert len(profiles) == 3
    for path, expected in profiles.items():
        assert common.inventory(Path(path)) == expected
        assert (
            swap["protected_before"][path] == swap["protected_after"][path] == canonical(expected)
        )
    critical = read(ROOT / "critical-before-DESTDIR.json")
    assert len(critical["files"]) == 17
    for path, expected in critical["files"].items():
        assert common.dependency_record(Path(path)) == expected
    namespace = read(ROOT / "namespace-plan.json")
    assert len(namespace) == 11
    for relative, proof in namespace.items():
        assert (
            sha(PREFIX / relative)
            == sha(APP / RES / "Ext/freecad" / Path(relative).name)
            == proof["before"]
            == proof["after"]
        )
    for name, expected in prior["quicklook_embedded_entitlements"].items():
        assert common.embedded_entitlements(APP / RES / "PlugIns" / name) == expected
        assert common.embedded_entitlements(BACKUP / RES / "PlugIns" / name) == expected
    applications = {}
    for mode, count in (("cmd", 31), ("gui", 6), ("cold", 1)):
        directory = ROOT / ("installed-" + mode)
        execution, regression = read(directory / "execution.json"), read(
            directory / "regression.json"
        )
        assert execution["schema"] == "FreeCAD-sv7-literal-application-gate-v1"
        assert execution["passed"] is True and execution["application"] == str(APP)
        assert execution["mode"] == mode and execution["location"] == "installed"
        assert (
            execution["source_commit"] == COMMIT
            and execution["revision"] == identity["revision"]
            and execution["native_sha256"] == NATIVE
        )
        assert (
            type(execution["returncode"]) is int
            and execution["returncode"] == 0
            and execution["timed_out"] is False
        )
        for key in (
            "child_reaped",
            "process_group_gone",
            "application_unchanged",
            "profiles_and_dependencies_unchanged",
            "inputs_unchanged",
            "strict_signature_verified",
            "semantic_tests_passed",
            "original_app_unchanged",
        ):
            assert execution[key] is True, (mode, key)
        assert execution["inputs_before"] == execution["inputs_after"]
        for path, expected in execution["inputs_after"].items():
            assert sha(path) == expected, path
        assert sha(directory / "run.log") == execution["log_sha256"]
        assert sha(directory / "regression.json") == execution["regression_sha256"]
        text = (directory / "run.log").read_text()
        assert re.findall(r"^Ran (\d+) tests? in [0-9.]+s$", text, re.M) == [str(count)]
        assert len(re.findall(r"^OK$", text, re.M)) == 1
        assert (
            regression["schema"] == "FreeCAD-sv7-installation-regression-v1"
            and regression["passed"] is True
        )
        assert (
            regression["application"] == str(APP)
            and regression["commit"] == COMMIT
            and regression["revision"] == identity["revision"]
            and regression["native_sha256"] == NATIVE
        )
        assert (
            regression["expected_tests"]
            == regression["executed_tests"]
            == execution["executed_tests"]
            == count
        )
        assert (
            set(regression["selected_test_ids"]) == common.expected_ids(mode)
            and len(regression["selected_test_ids"]) == count
        )
        assert regression["skipped"] == regression["failures"] == regression[
            "errors"
        ] == [] and regression["gui"] is (mode == "gui")
        for key in (
            "source_or_build_import_override",
            "native_solver_override",
            "original_project_opened_changed_or_solved",
        ):
            assert regression[key] is False
        assert regression["identity_sha256"] == sha(ROOT / "identity.json")
        for row in regression["final_module_origins"].values():
            path = Path(row["path"])
            assert path.is_relative_to(APP / RES / "Mod/Fem") and sha(path) == row["sha256"]
            assert (
                sha(REPO / "src/Mod/Fem" / path.relative_to(APP / RES / "Mod/Fem")) == row["sha256"]
            )
        observed = read(directory / "identity-observation.json")
        assert (
            observed["application"] == str(APP)
            and observed["runtime"][-1] == COMMIT
            and observed["runtime"][3] == identity["revision"]
        )
        assert (
            observed["GuiUp"] is (mode == "gui")
            and Path(observed["home_path"]).resolve() == APP / RES
        )
        assert observed["candidate"] == {
            "path": str(APP / RES / "data/NativeSolvers/ccx-force-accounting"),
            "sha256": NATIVE,
            "override": False,
            "capabilities": {
                "--freecad-force-accounting-version": "CCX_FORCE_ACCOUNTING_V3",
                "--freecad-contact-state-version": "CCX_CONTACT_STATE_V1",
                "--freecad-beam-section-version": "CCX_BEAM_SECTION_V1",
                "--freecad-beam-coupling-version": "CCX_BEAM_SECTION_V2",
                "--freecad-beam-solid-version": "CCX_BEAM_SECTION_V3",
            },
        }
        for group in ("native_origins", "python_origins"):
            for row in observed[group].values():
                if "path" in row:
                    path = Path(row["path"])
                    assert path.is_relative_to(APP / RES) and sha(path) == row["sha256"]
        executable = Path(observed["process_executable"]["path"])
        assert executable == APP / RES / "bin" / ("FreeCAD" if mode == "gui" else "FreeCADCmd")
        assert sha(executable) == observed["process_executable"]["sha256"]
        applications[mode] = {
            "tests": count,
            "receipt_sha256": sha(directory / "execution.json"),
            "regression_sha256": sha(directory / "regression.json"),
            "identity_sha256": sha(directory / "identity-observation.json"),
        }
    cold_domains = common.cold_audit("installed", APP)
    historical_domains = common.cold_audit("stage", common.STAGE)
    assert historical_domains == prior["cold_domains"]
    for row in historical_domains:
        for role in ("document", "reference"):
            assert sha(row[role]["path"]) == prior["inputs"][row[role]["path"]]
    assert {row["schema"] for row in cold_domains} == {row["schema"] for row in historical_domains}
    assert common.inventory(APP) == sealed and common.inventory(BACKUP) == baseline
    for path, expected in profiles.items():
        assert common.inventory(Path(path)) == expected
    for path, expected in tuple(common.inputs.items()):
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected, path
    report = {
        "schema": "FreeCAD-sv7-independent-installed-review-v1",
        "passed": True,
        "reviewer": "/root/sv7_install_audit",
        "compiled_commit": COMMIT,
        "revision": identity["revision"],
        "application": str(APP),
        "rollback_backup": str(BACKUP),
        "native_sha256": NATIVE,
        "installed_inventory_sha256": canonical(sealed),
        "backup_inventory_sha256": canonical(baseline),
        "native_payload_images": len(native),
        "inherited_native_images": len(s["additional_inherited_native"]),
        "selected_source_matches": len(sources),
        "profiles_unchanged": 3,
        "namespace_files_unchanged": 11,
        "selected_critical_files_unchanged": 17,
        "readonly_cachefree_resources": True,
        "stage_history_preserved_without_rebinding": True,
        "stage_review_sha256": sha(stage_report),
        "application_gates": applications,
        "cold_domains": cold_domains,
        "findings": [],
        "inputs": common.inputs,
        "scope": "Independent read/hash/parse only; actual installed and backup file inventories, Mach-O body/RPATH/embedded QuickLook entitlement parity, source equality and fresh literal installed runtime/cold-history chains verified. Native signature commands and FreeCAD/solver execution were performed only by root; cryptographic signature success is bound to frozen root-produced reports, not independently rerun here. Input maps remain private. No engineering acceptance.",
        "helper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    with (ROOT / "final-independent-review.json").open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({key: value for key, value in report.items() if key != "inputs"}, indent=2))


if __name__ == "__main__":
    main()
