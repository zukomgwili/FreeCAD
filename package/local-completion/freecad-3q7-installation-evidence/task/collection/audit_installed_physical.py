"""Read-only stdlib audit of this deployment's fresh installed132 output.

The already reviewed exact81f numerical engine is reused without changing any
parser, graph/mesh check, arithmetic or acceptance. Its source-QA supervisor is
replaced only in this auditor's private function namespace by the application
receipt adapter below. This does not import or modify any product module.
No native/app/test/build/solver execution; only a new report may be written.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path("/private/tmp/freecad-3q7-install-W35DLJ")
REPO = Path("/Users/zukomgwili/src/FreeCAD")
RUN = ROOT / "installed-capacity"
APP = Path("/Applications/FreeCAD-27.1.0.app")
ENGINE = REPO / "package/local-completion/freecad-3q7-source-evidence/task/physical-audit/audit_capacity.py"
ENGINE_SHA = "81fdeb6a2fbf2c4fd36f60e0ca626987c21735e28f33b27453c8dee9970d01fc"
NATIVE_ATTESTATION = REPO / "package/local-completion/freecad-yzk-source-evidence/private/qa/native-capacity-r01-attestation-v2.json"
NATIVE_ATTESTATION_SHA = "e8727c950d2ca2d55712de4a0b3ddb37c5d7544bfccc5ccbf91ca6afe2b1b9a9"
COMMIT = "6a0ed157b1063fa21407dc8f3cdfa3aef9484d8d"
REVISION = "49261 +229 (Git)"
NATIVE = "6c02452a896727af6cb4578fd3fb6bbfbdd48e3fb887c1c04fa2d8b171976c66"
MODULE = "femtest.app.test_moving_port_capacity_native"
TEST = MODULE + ".TestMovingPortCapacityNative.test_complete_132_bay_graph_obeys_the_native_declaration_budget"


def app_supervisor(engine):
    load, pin, text, need = (engine[name] for name in ("load", "pin", "text", "require"))
    execution, manifest, identity = (load(RUN / (name + ".json")) for name in ("execution", "manifest", "identity"))
    log = text(RUN / "run.log")
    need(execution["application"] == manifest["application"] == identity["application"] == str(APP), "Not the installed application")
    need(execution["module"] == manifest["module"] == MODULE and manifest["expected_count"] == 2, "Wrong explicit physical module/count")
    need(manifest["schema"] == "FreeCAD-yzk-application-run-manifest-v1", "Wrong actual application manifest schema")
    need(manifest["commit"] == identity["runtime"][-1] == COMMIT
         and manifest["revision"] == identity["runtime"][3] == REVISION, "Wrong actual compiled source identity")
    for flag in ("passed", "child_reaped", "process_group_gone", "manifest_unchanged", "source_build_harness_unchanged",
                 "app_and_profiles_unchanged", "application_unchanged", "critical_dependency_pins_unchanged", "post_run_serial_guard_passed", "stdin_is_DEVNULL"):
        need(execution[flag] is True, "Application supervisor failed: " + flag)
    need(execution["returncode"] == 0 and execution["timed_out"] is False and execution["skipped_lines"] == [], "Physical gate failed/skipped/timed out")
    need(execution["manifest_sha256"] == identity["manifest_sha256"] == pin(RUN / "manifest.json")["sha256"], "Manifest binding differs")
    need(execution["identity_sha256"] == pin(RUN / "identity.json")["sha256"]
         and execution["log_sha256"] == pin(RUN / "run.log")["sha256"], "Identity/log binding differs")
    need(identity["passed"] is True and identity["gui_up"] is False
         and identity["source_or_build_import_override"] is False, "Identity is not literal installed CLI")
    resources = APP / "Contents/Resources"
    for table in (identity["copied_modules"], identity["loaded_fem_python"]):
        for row in table.values():
            origin, source = Path(row["origin"]), Path(row["source"])
            need(origin.is_relative_to(resources / "Mod/Fem")
                 and source.is_relative_to(REPO / "src/Mod/Fem")
                 and origin.relative_to(resources / "Mod/Fem") == source.relative_to(REPO / "src/Mod/Fem")
                 and pin(origin)["sha256"] == pin(source)["sha256"] == row["sha256"], "Actual app/source Python copy differs")
    for row in identity["capacity_json_copies"].values():
        need(pin(row["path"])["sha256"] == pin(row["source"])["sha256"] == row["sha256"], "Actual frozen JSON copy differs")
    need(identity["selected_suite"]["name"] == MODULE and identity["selected_suite"]["ids"] == [TEST]
         and identity["selected_suite"]["count"] == 1, "Physical selected ID differs")
    counts = re.findall(r"^Ran (\d+) tests? in ([\d.]+)s\s*$", log, re.M)
    need(len(counts) == 1 and counts == [tuple(row) for row in execution["unittest_counts"]]
         and counts[0][0] == "2", "Actual executed count differs")
    pattern = "^" + re.escape(TEST.rsplit(".", 1)[-1]) + r" \(" + re.escape(TEST) + r"\)([^\n]*)$"
    hits = re.findall(pattern, log, re.M)
    need(len(hits) == 1 and "skipped" not in hits[0] and len(re.findall(r"^OK$", log, re.M)) == 1
         and not re.search(r"^(FAILED\b|FAIL:|ERROR:|UNEXPECTED SUCCESS:)", log, re.M), "Native method was not executed exactly once/pass")
    inputs = manifest["inputs"]["files"]
    need(inputs == execution["inputs_before"] == execution["inputs_after"], "App input fences differ")
    for path, wanted in inputs.items():
        need(pin(path)["sha256"] == wanted, "Current actual input differs: " + path)
    critical = ROOT / "critical-before-DESTDIR.json"
    need(pin(critical)["sha256"] == execution["critical_before_DESTDIR_sha256"], "Critical baseline binding differs")
    sealed = load(ROOT / "stage-inventory.json")
    for stem, field in (("application", "application_inventory"), ("custody", "custody")):
        before, after = (RUN / ("private-" + stem + "-" + when + ".json") for when in ("before", "after"))
        need(pin(before)["sha256"] == execution[field + "_before_sha256"]
             and pin(after)["sha256"] == execution[field + "_after_sha256"], "Private actual custody binding differs")
        need(load(before) == load(after), "Private actual custody changed")
        if stem == "application":
            need(load(before) == sealed, "Installed app does not equal sealed image")
    candidate = {"path": str(APP / "Contents/Resources/data/NativeSolvers/ccx-force-accounting"),
                 "sha256": NATIVE, "capability": "CCX_FORCE_ACCOUNTING_V3", "override": False}
    need(identity["candidate"] == candidate and manifest["candidate_sha256"] == NATIVE
         and pin(candidate["path"])["sha256"] == NATIVE, "Default installed native candidate differs")
    need(pin(NATIVE_ATTESTATION)["sha256"] == NATIVE_ATTESTATION_SHA, "Inherited native compilation attestation differs")
    inherited = load(NATIVE_ATTESTATION)
    need(inherited["passed"] is True and inherited["candidate"]["sha256"] == NATIVE
         and inherited["derived_receipt"] is True and inherited["new_execution_performed"] is False
         and inherited["contract_compilation_claimed"] is False, "Inherited native scope differs")
    for name, wanted in inherited["compiled_sources_sha256"].items():
        need(name in {"forceaccounting.c", "hooks.patch"}
             and pin(REPO / "package/calculix/force-accounting" / name)["sha256"] == wanted, "Native source compilation pin differs")
    prefixes = re.findall(r"^Native capacity evidence: ([^\r\n]+)$", log, re.M)
    need(len(prefixes) == 1, "Not one actual fresh witness prefix")
    prefix = Path(prefixes[0])
    need(prefix.is_absolute() and prefix.is_relative_to(RUN / "freecad_user_temp")
         and prefix.name.startswith("freecad-moving-port-capacity-native-"), "Not this installed run's output")
    for path in (prefix, *prefix.parents):
        need(not path.is_symlink(), "Linked fresh prefix")
    context = {"candidate": candidate, "native_build_receipt": {
        "path": str(NATIVE_ATTESTATION), "sha256": NATIVE_ATTESTATION_SHA,
        "scope": "Inherited native6c compilation only, not this fresh installed physical execution"}}
    return prefix / "witness", context, execution, identity


def audit():
    body = ENGINE.read_bytes()
    assert hashlib.sha256(body).hexdigest() == ENGINE_SHA
    engine = {"__name__": "_reviewed_stdlib_capacity_math", "__file__": str(ENGINE)}
    exec(compile(body, str(ENGINE), "exec"), engine)
    engine["TASK"], engine["RUN"] = ROOT, RUN
    engine["pin"](ENGINE)
    engine["pin"](Path(__file__))
    engine["supervisor"] = lambda: app_supervisor(engine)
    result = engine["audit"]()
    result["schema"] = "FreeCAD-3q7-fresh-installed-capacity-independent-file-audit-v1"
    result["application"] = str(APP)
    result["application_manifest"] = {"path": str(RUN / "manifest.json"), **engine["pin"](RUN / "manifest.json")}
    result["reused_numerical_engine"] = {"path": str(ENGINE), "sha256": ENGINE_SHA,
        "scope": "All numerical/mesh/native parsers and audit body unchanged; explicit private application supervisor adapter replaces source-QA bindings"}
    result["supervisor"]["application_source_copy_parity"] = result["supervisor"].pop("source_build_copy_parity")
    result["new_performance_measurement_claimed"] = False
    result["stage_132_run_claimed"] = False
    for path, wanted in engine["READS"].copy().items():
        assert engine["descriptor"](path) == wanted
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    assert not sys.flags.optimize and args.report.is_absolute()
    assert args.report.parent == ROOT / "collection" and not args.report.exists() and not args.report.is_symlink()
    report = audit()
    with args.report.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"passed": True, "report": str(args.report),
        "sha256": hashlib.sha256(args.report.read_bytes()).hexdigest(),
        "recomputed_checks": report["acceptance"]["unique_recomputed_checks"]}))
