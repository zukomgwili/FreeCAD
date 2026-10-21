"""Read-only final deployment receipt/count/byte/custody audit.

No product imports, subprocesses, native tests, solves, builds or installation.
Uses only stdlib file reads/arithmetic. The sole write is a new report in
collection/, outside all frozen literal-app inputs and retained witnesses.
"""

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import sys

ROOT = Path("/private/tmp/freecad-3q7-install-W35DLJ")
REPO = Path("/Users/zukomgwili/src/FreeCAD")
APP = Path("/Applications/FreeCAD-27.1.0.app")
BACKUP = Path("/Users/zukomgwili/Applications/FreeCAD Backups/FreeCAD-27.1.0-before-3q7-7667033a14.app")
RESOURCES = APP / "Contents/Resources"
PAYLOAD = ROOT / "payload" / APP.relative_to("/") / "Contents/Resources"
COMMIT = "6a0ed157b1063fa21407dc8f3cdfa3aef9484d8d"
REVISION = "49261 +229 (Git)"
NATIVE = "6c02452a896727af6cb4578fd3fb6bbfbdd48e3fb887c1c04fa2d8b171976c66"
FINAL_SOURCES = (
    "femmesh/meshsetsgetter.py", "femmesh/meshtools.py", "femmesh/ownership_context.py",
    "femsolver/calculix/write_constraint_elastic_connector.py", "femsolver/calculix/writer.py",
    "femtools/elastic_connector.py", "femtools/force_accounting.py", "femtools/rigid_body.py",
    "femtest/app/support_utils.py", "femtest/app/test_elastic_connector.py",
    "femtest/app/test_moving_port_accounting_native.py", "femtest/app/test_rigid_region_ownership.py")
READS = {}


def need(value, message):
    if not value:
        raise AssertionError(message)


def pin(path):
    path = Path(path)
    need(path.is_file() and not path.is_symlink(), "Missing/linked file: " + str(path))
    with path.open("rb") as stream:
        value = {"path": str(path), "sha256": hashlib.file_digest(stream, "sha256").hexdigest(), "bytes": path.stat().st_size}
    need(READS.setdefault(str(path), value) == value, "Read end fence changed: " + str(path))
    return value


def text(path):
    before = pin(path)
    body = Path(path).read_bytes()
    need(len(body) == before["bytes"] and hashlib.sha256(body).hexdigest() == before["sha256"], "Read bytes changed")
    return body.decode()


def pairs(items):
    result = {}
    for key, value in items:
        need(key not in result, "Duplicate JSON key")
        result[key] = value
    return result


def load(path):
    return json.loads(text(path), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(AssertionError(value)))


def inventory(root):
    need(root.is_dir() and not root.is_symlink(), "Missing/linked inventory root")
    result = {".": {"kind": "dir", "mode": stat.S_IMODE(root.lstat().st_mode)}}
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in sorted(dirs + files):
            path = Path(directory) / name
            mode = path.lstat().st_mode
            row = {"mode": stat.S_IMODE(mode)}
            if stat.S_ISLNK(mode):
                row.update(kind="link", target=os.readlink(path))
            elif stat.S_ISDIR(mode):
                row.update(kind="dir")
            else:
                need(stat.S_ISREG(mode), "Nonregular inventory leaf")
                # Full app/profile inventory bodies stay private/in-memory.
                # Do not publish an exhaustive live-file descriptor list.
                with path.open("rb") as stream:
                    row.update(kind="file", sha256=hashlib.file_digest(stream, "sha256").hexdigest())
            result[str(path.relative_to(root))] = row
    return result


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def critical_record(path):
    target = Path(path)
    info = target.lstat()
    observed = {"dev": info.st_dev, "inode": info.st_ino, "mode": info.st_mode, "size": info.st_size,
                "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns}
    if stat.S_ISLNK(info.st_mode):
        observed.update(kind="link", target=os.readlink(target), resolved=str(target.resolve(strict=True)),
                        resolved_sha256=hashlib.sha256(target.read_bytes()).hexdigest())
    else:
        observed.update(kind="file", sha256=pin(target)["sha256"])
    return observed


def native_leaves(root):
    found = set()
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [name for name in dirs if not (Path(directory) / name).is_symlink()]
        for name in files:
            path = Path(directory) / name
            if path.is_symlink():
                continue
            need(path.is_file(), "Nonregular native scan leaf")
            with path.open("rb") as stream:
                magic = stream.read(4)
            if magic == b"\xcf\xfa\xed\xfe":
                found.add(str(path.relative_to(root)))
    return found


def native_identity_function():
    helper = REPO / "package/local-completion/freecad-ywu-installation-evidence/private/stage_install.py"
    need(pin(helper)["sha256"] == "cca627502a56b6c9b4aefa4a970172c51e42e2dde834000decca65fd44ab46d9", "Immutable Mach-O parser changed")
    tree = ast.parse(text(helper), filename=str(helper))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in {"digest", "macho_identity"}]
    need({node.name for node in functions} == {"digest", "macho_identity"}, "Missing exact Mach-O functions")
    namespace = {"Path": Path, "hashlib": hashlib, "json": json, "struct": struct}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(helper), "exec"), namespace)
    return namespace["macho_identity"]


def literal_constants(path):
    result = {}
    for node in ast.parse(text(path), filename=str(path)).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            result[node.targets[0].id] = ast.literal_eval(node.value)
    return result


def methods(relative, class_name):
    tree = ast.parse(text(REPO / "src/Mod/Fem" / relative))
    cls = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name]
    need(len(cls) == 1, "Missing exact native class")
    prefix = relative.removesuffix(".py").replace("/", ".") + "." + class_name + "."
    return sorted(prefix + node.name for node in cls[0].body if isinstance(node, ast.FunctionDef) and node.name.startswith("test"))


def app_gate(label, module, total, gui, sealed, native_ids):
    run = ROOT / label
    report, manifest, identity = (load(run / (name + ".json")) for name in ("execution", "manifest", "identity"))
    application = str(ROOT / APP.name) if label.startswith("stage-") else str(APP)
    log = text(run / "run.log")
    for key in ("passed", "child_reaped", "process_group_gone", "source_build_harness_unchanged", "app_and_profiles_unchanged",
                "application_unchanged", "critical_dependency_pins_unchanged", "manifest_unchanged", "stdin_is_DEVNULL", "post_run_serial_guard_passed"):
        need(report[key] is True, label + ": " + key)
    need(report["application"] == manifest["application"] == identity["application"] == application, "Gate location rebound")
    need(report["returncode"] == 0 and report["timed_out"] is False and report["skipped_lines"] == [], "Gate failed/skipped")
    need(report["module"] == manifest["module"] == module and manifest["expected_count"] == total, "Gate module/count differs")
    need(report["manifest_sha256"] == identity["manifest_sha256"] == pin(run / "manifest.json")["sha256"], "Gate manifest binding differs")
    need(report["identity_sha256"] == pin(run / "identity.json")["sha256"] and report["log_sha256"] == pin(run / "run.log")["sha256"], "Gate receipt binding differs")
    need(manifest["schema"] == "FreeCAD-yzk-application-run-manifest-v1"
         and manifest["commit"] == identity["runtime"][-1] == COMMIT
         and manifest["revision"] == identity["runtime"][3] == REVISION, "Actual compiled identity differs")
    need(identity["passed"] is True and identity["gui_up"] is gui and identity["source_or_build_import_override"] is False, "Identity/import mode differs")
    candidate = {"path": application + "/Contents/Resources/data/NativeSolvers/ccx-force-accounting",
                 "sha256": NATIVE, "capability": "CCX_FORCE_ACCOUNTING_V3", "override": False}
    need(identity["candidate"] == candidate and manifest["candidate_sha256"] == NATIVE, "App candidate differs")
    need(identity["TestFemApp_count"] == 418 and len(identity["registered_native_ids"]) == len(set(identity["registered_native_ids"])) == 12
         and set(identity["registered_native_ids"]) == set(native_ids), "Actual registered native catalogue differs")
    if gui:
        need(identity["TestFemGui_count"] == 8, "GUI discovery differs")
    suite = identity["selected_suite"]
    need(suite["name"] == module and suite["count"] == total - 1
         and len(suite["ids"]) == len(set(suite["ids"])) == total - 1, "Selected catalogue differs")
    if module == "TestFemApp":
        need(set(native_ids) <= set(suite["ids"]), "Native methods omitted from FEM")
    if module == "femtest.app.test_moving_port_accounting_native":
        need(set(suite["ids"]) == {item for item in native_ids if ".TestMovingPortAccountingNative." in item}, "Moving catalogue differs")
    counts = re.findall(r"^Ran (\d+) tests? in ([\d.]+)s\s*$", log, re.M)
    need(counts == [tuple(row) for row in report["unittest_counts"]] and len(counts) == 1 and int(counts[0][0]) == total, "Executed count differs")
    need(len(re.findall(r"^OK$", log, re.M)) == 1 and not re.search(r"^(FAILED\b|FAIL:|ERROR:|UNEXPECTED SUCCESS:)", log, re.M), "Log is not clean")
    for item in suite["ids"]:
        hits = re.findall("^" + re.escape(item.rsplit(".", 1)[-1]) + r" \(" + re.escape(item) + r"\)([^\n]*)$", log, re.M)
        need(len(hits) == 1 and "skipped" not in hits[0], "Missing/repeated/skipped actual selected ID")
    need(report["inputs_before"] == report["inputs_after"] == manifest["inputs"]["files"], "Gate input fences differ")
    for path, wanted in report["inputs_after"].items():
        need(pin(path)["sha256"] == wanted, "Actual current input changed")
    for stem, field in (("application", "application_inventory"), ("custody", "custody")):
        before, after = (run / ("private-" + stem + "-" + when + ".json") for when in ("before", "after"))
        need(pin(before)["sha256"] == report[field + "_before_sha256"] and pin(after)["sha256"] == report[field + "_after_sha256"], "Private gate custody hash differs")
        need(load(before) == load(after), "Gate custody changed")
        if stem == "application":
            need(load(before) == sealed, "Gate app not exact sealed image")
    need(report["critical_before_DESTDIR_sha256"] == pin(ROOT / "critical-before-DESTDIR.json")["sha256"], "Wrong critical baseline")
    for table in (identity["copied_modules"], identity["loaded_fem_python"]):
        for row in table.values():
            source = Path(row["source"])
            need(source.is_relative_to(REPO / "src/Mod/Fem"), "Bad source origin")
            current = RESOURCES / "Mod/Fem" / source.relative_to(REPO / "src/Mod/Fem")
            need(pin(source)["sha256"] == pin(current)["sha256"] == row["sha256"], "Installed copied Python differs")
    return {"path": str(run / "execution.json"), **{key: pin(run / "execution.json")[key] for key in ("sha256", "bytes")}}


def audit():
    pin(Path(__file__))
    config = literal_constants(ROOT / "harness_config.py")
    need((config["COMMIT"], config["REVISION"], config["NATIVE_SHA"]) == (COMMIT, REVISION, NATIVE), "Config differs")
    tie = methods("femtest/app/test_tie_accounting_native.py", "TestTieAccountingNative")
    moving = methods("femtest/app/test_moving_port_accounting_native.py", "TestMovingPortAccountingNative")
    need(tuple(tie) == config["NATIVE_TIE_IDS"] and tuple(moving) == config["NATIVE_MOVING_IDS"]
         and len(tie) == 4 and len(moving) == 8, "Source-derived native IDs differ")
    header = text(REPO / "build/release/src/Build/Version.h")
    macros = dict(re.findall(r'^#define\s+(FC\w+)\s+"([^"\n]*)"', header, re.M))
    need(macros["FCRepositoryHash"] == COMMIT and macros["FCRevision"] == REVISION, "Build header differs")
    sealed = load(ROOT / "stage-inventory.json")
    baseline = load(ROOT / "baseline-inventory.json")
    need(baseline == load(ROOT / "private-baseline-app.json"), "Original app captures differ")
    need(inventory(APP) == sealed and inventory(BACKUP) == baseline, "Installed/rollback whole tree differs")
    need(not (ROOT / APP.name).exists() and not (ROOT / APP.name).is_symlink(), "Stage was not moved")
    profiles = load(ROOT / "profile-inventories.json")
    need(profiles == load(ROOT / "private-baseline-profiles.json") and len(profiles) == 3, "Protected profile catalogue differs")
    for path, before in profiles.items():
        need(inventory(Path(path)) == before, "Protected profile changed")
    critical = load(ROOT / "critical-before-DESTDIR.json")
    need(critical["passed"] is True and len(critical["files"]) == 16, "Critical capture differs")
    for path, wanted in critical["files"].items():
        need(critical_record(path) == wanted, "Critical prefix/dependency input changed")
    namespace = load(ROOT / "namespace-plan.json")
    need(len(namespace) == 11, "External namespace catalogue differs")
    prefix = REPO / ".pixi/envs/default"
    for relative, wanted in namespace.items():
        target = prefix / relative
        need(pin(target)["sha256"] == wanted["before"] == wanted["after"]
             and stat.S_IMODE(target.stat().st_mode) == wanted["mode"], "External namespace changed")
    resources_inventory = inventory(RESOURCES)
    need(not any(path.endswith(".pyc") or "__pycache__" in Path(path).parts for path in resources_inventory), "Installed app has caches")
    need(all(row["kind"] == "link" or not row["mode"] & 0o222 for row in resources_inventory.values()), "Installed resources writable")
    source_pins = {}
    for relative in FINAL_SOURCES:
        source, installed = REPO / "src/Mod/Fem" / relative, RESOURCES / "Mod/Fem" / relative
        need(pin(source)["sha256"] == pin(installed)["sha256"], "Missing final3q7 source equality")
        source_pins[relative] = pin(source)["sha256"]
    need(pin(RESOURCES / "data/NativeSolvers/ccx-force-accounting")["sha256"] == NATIVE, "Installed native binary differs")
    roles = {}
    fixed_roles = {"source_build": "build-latest/execution.json", "ctest": "ctest-latest/execution.json",
        "payload_audit": "independent-payload-audit.json", "stage_audit": "independent-stage-audit.json",
        "custody_audit": "independent-stage-custody.json", "swap": "step-swap/execution.json"}
    for role, relative in fixed_roles.items():
        path = ROOT / relative
        need(load(path)["passed"] is True, "Pending/failed role: " + role)
        roles[role] = pin(path)
    build = load(ROOT / fixed_roles["source_build"])
    need(build["source_and_supervisor_unchanged"] is True and build["app_profiles_selected_dependencies_unchanged"] is True
         and build["source_after"]["git_head"] == COMMIT and build["process_reaped"] is True
         and build["owned_group_gone"] is True and build["timed_out"] is False and build["exit_code"] == 0, "Source build failed/fences differ")
    for key in ("source_after", "build_after"):
        for path, wanted in build[key]["files"].items():
            need(pin(path)["sha256"] == wanted, "Final build/source input differs")
    ctest = load(ROOT / fixed_roles["ctest"])
    need(ctest["source_and_supervisor_unchanged"] is True and ctest["app_profiles_selected_dependencies_unchanged"] is True
         and ctest["build_before"] == ctest["build_after"] == build["build_after"]
         and ctest["process_reaped"] is True and ctest["owned_group_gone"] is True
         and ctest["timed_out"] is False and ctest["exit_code"] == 0, "CTest fences differ")
    ctest_log = text(ROOT / "ctest-latest/run.log")
    outcomes = re.findall(r"^\s*(\d+)/(\d+)\s+Test\s+#(\d+):([^\r\n]*)$", ctest_log, re.M)
    need(len(outcomes) == 2274 and {int(row[0]) for row in outcomes} == {int(row[2]) for row in outcomes} == set(range(1, 2275))
         and {row[1] for row in outcomes} == {"2274"}, "Incomplete CTest catalogue")
    counts = {"passed": 0, "skipped": 0, "disabled": 0}
    for row in outcomes:
        line = row[3]
        kind = "disabled" if "***Not Run (Disabled)" in line else "skipped" if "***Skipped" in line else "passed" if re.search(r"\bPassed\s+[\d.]+\s+sec\s*$", line) else None
        need(kind is not None, "Unknown/failed CTest result")
        counts[kind] += 1
    need((counts["passed"], counts["skipped"], counts["disabled"]) == (2264, 2, 8), "Actual CTest outcome counts differ")
    need(ctest["ctest"]["executed_passing"] == 2264 and ctest["ctest"]["skipped"] == 2
         and ctest["ctest"]["disabled"] == 8 and ctest["ctest"]["failed"] == 0, "CTest receipt count differs")
    need(ctest["log_sha256"] == pin(ROOT / "ctest-latest/run.log")["sha256"], "CTest log changed")
    for name, row in ctest["ctest_logs_after"].items():
        if row["fresh_for_this_run"]:
            need(pin(ROOT / "ctest-latest" / name)["sha256"] == row["sha256"], "Fresh CTest body differs")
    payload, stage, custody = (load(ROOT / fixed_roles[role]) for role in ("payload_audit", "stage_audit", "custody_audit"))
    native_set = {row["relative"] for row in payload["native"]}
    need(native_leaves(PAYLOAD) == native_set
         and len(native_set) == payload["payload_native_count"] == stage["native_payload_parity_count"] == custody["native_payload_count"] == 61, "Complete native count differs")
    need(payload["commit"] == stage["source_commit"] == custody["compiled_commit"] == COMMIT
         and custody["compiled_revision"] == REVISION, "Payload/stage/custody source identity differs")
    need(stage["sealed_stage_inventory_sha256"] == canonical(sealed)
         and stage["payload_audit_sha256"] == roles["payload_audit"]["sha256"]
         and custody["stage_audit_sha256"] == roles["stage_audit"]["sha256"], "Audit image bindings differ")
    need({row["relative"] for row in stage["native"]} == native_set
         and payload["native_complete_relative_set_sha256"] == stage["native_complete_relative_set_sha256"]
         == custody["native_complete_relative_set_sha256"] == canonical(sorted(native_set)), "Native catalogue hashes differ")
    native_identity = native_identity_function()
    stage_by_native = {row["relative"]: row for row in stage["native"]}
    for row in payload["native"]:
        need(pin(PAYLOAD / row["relative"])["sha256"] == row["payload_sha256"], "Payload native bytes changed")
        original = native_identity(PAYLOAD / row["relative"])
        installed = native_identity(RESOURCES / row["relative"])
        need(original["normalized"] == installed["normalized"]
             and original["rpaths"] == installed["rpaths"]
             and original["normalized_sha256"] == row["normalized_sha256"]
             == stage_by_native[row["relative"]]["normalized_sha256"], "Native normalized code/RPATH parity differs")
        need(row["build_matches"], "No build-native match")
        for match in row["build_matches"]:
            relative = Path(match["path"])
            need(not relative.is_absolute() and ".." not in relative.parts, "Nonlocal build-native match")
            candidate = REPO / "build/release" / relative
            need(pin(candidate)["sha256"] == match["sha256"], "Build-native match changed")
            actual = native_identity(candidate)
            need(actual["normalized"] == original["normalized"] and actual["rpaths"] == match["rpaths"], "Build-native identity differs")
    for row in stage["native"]:
        need(pin(RESOURCES / row["relative"])["sha256"] == row["stage_sha256"], "Sealed installed native bytes changed")
    payload_in_app = {str(Path("Contents/Resources") / relative) for relative in native_set}
    installed_native, backup_native = native_leaves(APP), native_leaves(BACKUP)
    inherited_set = installed_native - payload_in_app
    need(installed_native == payload_in_app | (backup_native - payload_in_app)
         and inherited_set == {row["relative"] for row in stage["additional_inherited_native"]}, "Inherited native catalogue differs")
    for row in stage["additional_inherited_native"]:
        old, new = BACKUP / row["relative"], APP / row["relative"]
        need(pin(old)["sha256"] == row["old_sha256"] and pin(new)["sha256"] == row["stage_sha256"], "Inherited native leaf changed")
        left, right = native_identity(old), native_identity(new)
        need(left["normalized"] == right["normalized"] and left["rpaths"] == right["rpaths"]
             and right["normalized_sha256"] == row["normalized_sha256"], "Inherited native code/RPATH differs")
    swap = load(ROOT / fixed_roles["swap"])
    need(swap["source_commit"] == COMMIT and swap["compiled_revision"] == REVISION
         and swap["installation_replacement"] is True and swap["protected_profiles_and_selected_inputs_unchanged"] is True
         and swap["returncode"] == 0 and swap["child_reaped"] is True and swap["process_group_gone"] is True
         and swap["timed_out"] is False, "Swap receipt incomplete")
    for location in ("stage", "installed"):
        for suffix, module, total, gui in (("fem", "TestFemApp", 419, False), ("gui", "TestFemGui", 9, True),
                                         ("native", "femtest.app.test_moving_port_accounting_native", 9, False)):
            roles[location + "_" + suffix] = app_gate(location + "-" + suffix, module, total, gui, sealed, tie + moving)
    cap_module = "femtest.app.test_moving_port_capacity_native"
    roles["installed_capacity"] = app_gate("installed-capacity", cap_module, 2, False, sealed, tie + moving)
    cap_log = text(ROOT / "installed-capacity/run.log")
    prefixes = re.findall(r"^Native capacity evidence: ([^\r\n]+)$", cap_log, re.M)
    need(len(prefixes) == 1, "Missing/repeated fresh installed witness")
    witness = Path(prefixes[0]) / "witness"
    need(witness.is_relative_to(ROOT / "installed-capacity/freecad_user_temp") and not witness.is_symlink(), "Not this installed run's fresh witness")
    roles["installed_witness"] = pin(witness / "witness-receipt.json")
    physical_path = ROOT / "collection/installed-physical-independent-audit-r01.json"
    physical = load(physical_path)
    need(physical["passed"] is True and physical["fresh_run"] == str(ROOT / "installed-capacity")
         and physical["witness"] == str(witness) and physical["application"] == str(APP)
         and physical["acceptance"]["unique_recomputed_checks"] == 3566
         and physical["acceptance"]["limits_unchanged"] is True
         and physical["stage_132_run_claimed"] is False and physical["new_performance_measurement_claimed"] is False,
         "Pending/different installed numerical audit")
    for path, desc in physical["evidence_sha256_and_bytes"].items():
        need({key: pin(path)[key] for key in ("sha256", "bytes")} == desc, "Physical audit evidence changed")
    roles["installed_physical_audit"] = pin(physical_path)
    roles["installed_cold"] = app_gate("installed-cold", "YzkPortableColdRestore", 2, False, sealed, tie + moving)
    cold_path = ROOT / "installed-cold/cold-receipt.json"
    cold = load(cold_path)
    literal_path = witness / "cold-case.json"
    literal = load(literal_path)
    witness_receipt = load(witness / "witness-receipt.json")
    need(cold["passed"] is True and cold["status"].startswith("Stale") and cold["manifest"] == str(literal_path)
         and cold["manifest_sha256"] == pin(literal_path)["sha256"] == witness_receipt["cold_manifest_sha256"]
         and cold["no_native_solve"] is True and cold["no_save"] is True
         and cold["no_history_or_provenance_repair"] is True, "Separate cold verification incomplete")
    cold_manifest = load(ROOT / "installed-cold/manifest.json")
    need(cold_manifest["cold_manifest"] == str(literal_path)
         and cold_manifest["cold_manifest_sha256"] == pin(literal_path)["sha256"], "Cold supervisor literal binding differs")
    need(cold["supports"] == literal["explicit_supports"] == ["BackboneFixed"]
         and cold["accounting_data_sha256"] == hashlib.sha256(literal["accounting_data_literal"].encode()).hexdigest(), "Cold literal data/supports differ")
    need(pin(literal["document"])["sha256"] == literal["document_sha256"], "Cold saved app case changed")
    for row in literal["source_files"].values():
        need(pin(row["path"])["sha256"] == row["sha256"], "Cold literal native source changed")
    roles["installed_cold_receipt"] = pin(cold_path)
    note = text(RESOURCES / "LOCAL-INSTALL.txt")
    need(COMMIT in note and "49261+229" in note and str(BACKUP) in note, "Installed note differs")
    need(inventory(APP) == sealed and inventory(BACKUP) == baseline, "Final app/backup whole-tree end fence changed")
    for path, before in profiles.items():
        need(inventory(Path(path)) == before, "Final protected profile end fence changed")
    for path, wanted in critical["files"].items():
        need(critical_record(path) == wanted, "Final critical stat/bytes/link end fence changed")
    for relative, wanted in namespace.items():
        target = prefix / relative
        need(pin(target)["sha256"] == wanted["before"] == wanted["after"]
             and stat.S_IMODE(target.stat().st_mode) == wanted["mode"], "Final external namespace end fence changed")
    for path, before in READS.copy().items():
        need(pin(path) == before, "Final selected read changed")
    return {"schema": "FreeCAD-3q7-installation-final-gates-independent-review-v1", "passed": True, "pending_roles": [],
        "source_identity": {"commit": COMMIT, "revision": REVISION, "native_sha256": NATIVE}, "roles": roles,
        "actual_unittest_counts_including_identity": {"stage_fem": 419, "stage_gui": 9, "stage_native": 9,
            "installed_fem": 419, "installed_gui": 9, "installed_native": 9, "installed_capacity": 2, "installed_cold": 2},
        "ctest": {"catalogue": 2274, "enabled": 2266, "executed_passing": 2264, "skipped": 2, "disabled": 8, "failed": 0},
        "fresh_installed_physical_checks": 3566, "all12_final_source_copies": source_pins,
        "complete_native_payload_count": 61, "protected_profile_count": 3, "critical_dependency_files": 16, "external_namespace_files": 11,
        "all61_native_payload_build_installed_code_and_RPATH_parity_recomputed": True,
        "MachO_primitive_reuse_scope": "Exact immutable reviewed core digest/macho_identity definitions only, compiled from AST in stdlib namespace; no deployment/product module imported or native process invoked.",
        "installed_app_equals_sealed_image_and_exact_rollback_backup_retained": True,
        "separate_cold_no_solve_save_or_provenance_repair": True, "stage132_run_claimed": False,
        "historical_source_speedup_is_not_a_new_performance_measurement": True,
        "signature_scope": "Completed payload/stage/custody native/signature checks cross-bound; file auditor does not invoke codesign or launch any app.",
        "engineering_acceptance_claimed": False, "engineering_projects_accessed_or_solved": False,
        "authorship": "Reviewer adapted deployment helpers and authored some source mutation guards/file auditors, not product fix/native physical producer/frozen oracle or immutable staging core.",
        "file_only_audit": True, "input_descriptors": READS}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    need(not sys.flags.optimize and args.report.parent == ROOT / "collection"
         and not args.report.exists() and not args.report.is_symlink(), "Explicit new-only collection report required")
    result = audit()
    with args.report.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"passed": True, "report": str(args.report), "sha256": pin(args.report)["sha256"], "roles": len(result["roles"])}))
