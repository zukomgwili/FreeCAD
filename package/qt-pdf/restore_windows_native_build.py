# SPDX-License-Identifier: LGPL-2.1-or-later
"""Restore one authenticated Windows build and reuse its passed Qt/upstream gates.

Only attempt 3 of run 37367983867 is admitted. Its native capture remains failed.
The original diagnostic/recovery/validation/upstream receipts are never rewritten.
Restoration admits physical bytes at the original paths; fresh native acceptance
still requires all stock exports, prospective inputs, GUI tests and live origins.
No retained executable, install script, compiler or upstream test is run here.
"""

import argparse
import ast
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import stat
import subprocess
import sys
import zipfile

import retain_windows_native_build as retained
import reuse_windows_qt_qualification as reuse

common = reuse.common
require, physical, digest, read_json = (
    reuse.require,
    reuse.physical,
    reuse.digest,
    reuse.read_json,
)
HEAD = "e5c5844f41c4a96d21dfbf21c7ae1d21c357be47"
PRIOR = {
    "run": 37367983867,
    "attempt": 3,
    "job": 112131196553,
    "artifact": 11399230772,
    "size": 81825695,
    "zip_sha256": "3358565d617818cf765c42c69dd7aeb7f21baddd2feac501fc3dc2c4e54ed69a",
}
BUILD_SHA = "e2f35ab9b4723c44d3c101ed1a6218c223574574c8699623364cebeeb72d17af"
SOURCE_SHA = "97a3b48c4e2181d1392579e4e329668da34f51b742b9cc5d2e47a8413ddc49c7"
VALIDATION_SHA = "4090839c89f5cd6e6b932b42e62ba2b6550751c205e87e44377660749b05f48d"
UPSTREAM_SHA = "6ddab194a500bc78077092043d2e27179661aabe4ccaa614e4a8bdf6a343b929"
MACRO_SHA = "2e5711956d8ff9b37a9dcc8e17e153d134fca770bfa486fea381991afbf44e01"
WORKSPACE = r"D:\a\FreeCAD\FreeCAD"
TEMPORARY = r"D:\a\_temp"
BUNDLE = "_temp/qt-pdf-windows-native-build"
OLD_PROOF = "_temp/qt-pdf-reused-qt"
OLD_MODULE = "_temp/qt-pdf-native-module"
RECEIPT = Path(__file__).with_name("windows-upstream-passed.json")
REQUIRED = {
    "bin/FreeCAD.exe",
    "bin/FreeCADBase.dll",
    "bin/FreeCADApp.dll",
    "bin/FreeCADGui.dll",
    "Mod/Part/Part.pyd",
    "Mod/PartDesign/_PartDesign.pyd",
    "Mod/Sketcher/Sketcher.pyd",
    "Mod/TechDraw/TechDraw.pyd",
    "Mod/TechDraw/TechDrawGui.pyd",
    "Mod/Test/QtUnitGui.pyd",
    "Mod/pivy/__init__.py",
    "Mod/pivy/coin.py",
    "Mod/pivy/_coin.pyd",
    "Ext/PySide/__init__.py",
    "Ext/PySide/QtCore.py",
    "Ext/PySide/QtGui.py",
    "Ext/PySide/QtWidgets.py",
    "data/Mod/TechDraw/Templates/Default_Template_A4_Landscape.svg",
    "data/Mod/TechDraw/Resources/fonts/osifont-lgpl3fe.ttf",
    "data/Mod/TechDraw/LineGroup/LineGroup.csv",
}
RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.IGNORECASE)


def write_json(path, value):
    require(not path.exists(), f"Receipt already exists: {path}")
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def safe_name(value):
    name = common.safe_name(value)
    require(
        all(
            not part.endswith((".", " "))
            and not RESERVED.match(part)
            and not any(character in '<>"|?*' for character in part)
            for part in name.parts
        ),
        "Reserved/ambiguous Windows archive name",
    )
    return name


def check_zip_names(archive):
    with zipfile.ZipFile(physical(archive)) as zipped:
        for entry in zipped.infolist():
            safe_name(entry.filename)


def checked_receipt():
    receipt = read_json(physical(RECEIPT))
    run, artifact = receipt["actual_run"], receipt["artifact"]
    require(
        run["run_id"] == PRIOR["run"]
        and run["run_attempt"] == PRIOR["attempt"]
        and run["job_id"] == PRIOR["job"]
        and run["head_sha"] == HEAD
        and run["repository"] == common.REPOSITORY
        and run["conclusion"] == "failure"
        and artifact["artifact_id"] == PRIOR["artifact"]
        and artifact["artifact_size"] == PRIOR["size"]
        and artifact["artifact_zip_sha256"] == PRIOR["zip_sha256"]
        and receipt["new_upstream"]["receipt_sha256"] == UPSTREAM_SHA
        and receipt["new_upstream"]["validation_sha256"] == VALIDATION_SHA
        and receipt["raw_build_retention"]["receipt_sha256"] == BUILD_SHA
        and receipt["raw_build_retention"]["source_inventory_sha256"] == SOURCE_SHA
        and receipt["qualified"] is False
        and receipt["upstream_passed"] is True
        and receipt["upstream_test_cases"] == 10,
        "Reviewed Windows passed-stage receipt differs",
    )
    return receipt


def check_api(run, artifact, jobs):
    require(
        run["id"] == PRIOR["run"]
        and run["run_attempt"] == PRIOR["attempt"]
        and run["head_sha"] == HEAD
        and run["repository"]["full_name"] == common.REPOSITORY
        and run["path"] == ".github/workflows/qt_pdf_qualify.yml"
        and run["event"] == "workflow_dispatch"
        and run["status"] == "completed"
        and run["conclusion"] == "failure",
        "Attempt 3 workflow identity differs",
    )
    require(
        artifact["id"] == PRIOR["artifact"]
        and artifact["name"] == "qt-pdf-qualification-win-64"
        and artifact["size_in_bytes"] == PRIOR["size"]
        and artifact["digest"] == "sha256:" + PRIOR["zip_sha256"]
        and artifact["workflow_run"]["id"] == PRIOR["run"]
        and artifact["workflow_run"]["head_sha"] == HEAD,
        "Attempt 3 artifact identity differs",
    )
    require(jobs["total_count"] <= 100, "Paginated attempt jobs unsupported")
    selected = [job for job in jobs["jobs"] if job["id"] == PRIOR["job"]]
    require(len(selected) == 1, "Missing/duplicate attempt 3 native job")
    job = selected[0]
    require(
        job["run_id"] == PRIOR["run"]
        and job["run_attempt"] == PRIOR["attempt"]
        and job["head_sha"] == HEAD
        and job["status"] == "completed"
        and job["conclusion"] == "failure"
        and job["name"] == "qualify (win-64, windows-2022)"
        and job["labels"] == ["windows-2022"],
        "Attempt 3 native Windows job differs",
    )
    for number, name, conclusion in (
        (
            15,
            "Capture the pending Windows upstream transcript before rebuilding FreeCAD",
            "success",
        ),
        (16, "Configure and build native FreeCAD against locked baseline", "success"),
        (
            17,
            "Compile the controlled mitigation bypass in this disposable checkout",
            "success",
        ),
        (20, "Retain the native build for a focused Windows retry", "success"),
        (22, common.FAILED_STEP, "failure"),
    ):
        steps = [step for step in job["steps"] if step["number"] == number and step["name"] == name]
        require(
            len(steps) == 1
            and steps[0]["status"] == "completed"
            and steps[0]["conclusion"] == conclusion,
            "Attempt 3 stage scope differs",
        )
    require(
        job["started_at"] <= artifact["created_at"] <= job["completed_at"],
        "Artifact timing is outside attempt 3 job",
    )


def native_paths():
    host = reuse.native_host()
    require(
        os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("CI") == "true"
        and os.environ.get("RUNNER_OS") == "Windows"
        and os.environ.get("ImageOS") == "win22",
        "Use a disposable native Windows 2022 job",
    )
    source = physical(Path(os.environ["GITHUB_WORKSPACE"]))
    temporary = physical(Path(os.environ["RUNNER_TEMP"]))
    require(
        PureWindowsPath(source) == PureWindowsPath(WORKSPACE)
        and PureWindowsPath(temporary) == PureWindowsPath(TEMPORARY),
        "Original physical Windows workspace/temporary roots required",
    )
    return host, source, temporary


def checked_bundle(bundle):
    """Data-only admission; independently testable without running a PE."""
    bundle = physical(bundle)
    require(digest(bundle / "native-build.json") == BUILD_SHA, "Raw build receipt changed")
    report = read_json(bundle / "native-build.json")
    require(
        report["head_sha"] == HEAD
        and report["target"] == "win-64"
        and report["status"] == "raw-diagnostic-retained"
        and report["diagnostic_only"] is True
        and report["qualified"] is False
        and report["native_freecad_qualified"] is False
        and report["distribution_promoted"] is False
        and report["restoration_validated"] is False
        and report["protected_inputs_unchanged"] is True
        and report["runtime_prefix_bytes_bundled"] is False
        and PureWindowsPath(report["source_root"]) == PureWindowsPath(WORKSPACE)
        and PureWindowsPath(report["build_root"]) == PureWindowsPath(WORKSPACE) / "build/release",
        "Raw diagnostic scope/source differs",
    )
    for name, sha in report["input_sha256"].items():
        require(
            digest(physical(bundle / safe_name(name))) == sha,
            "Raw retained input changed",
        )
    require(
        digest(bundle / "source-files.json") == report["source_inventory_sha256"] == SOURCE_SHA,
        "Raw source inventory changed",
    )
    archive, raw = bundle / "native-build.zip", report["raw_archive"]
    require(
        archive.stat().st_size == raw["size"] == 44375910
        and digest(archive)
        == raw["sha256"]
        == "bff02f1fb0c78a9c8e87b6390499d0c835677c3f7d349ae5aae367459b8d58d5"
        and raw["links_admitted"] is False
        and raw["restoration_validated"] is False,
        "Raw build ZIP changed",
    )
    require(
        digest(bundle / "native-output-files.json") == raw["manifest_sha256"],
        "Output manifest changed",
    )
    inventory = read_json(bundle / "native-output-files.json")
    require(
        len(inventory["files"]) == raw["file_count"] == 1457
        and len(inventory["directories"]) == raw["directory_count"] == 170
        and sum(entry["size"] for entry in inventory["files"].values())
        == inventory["physical_bytes"]
        == raw["physical_bytes"]
        == 109078605
        and REQUIRED.issubset(inventory["files"])
        and not any(
            re.fullmatch(r"bin/Qt6.*\.dll", name, re.IGNORECASE) for name in inventory["files"]
        ),
        "Incomplete native build/resources or app-directory Qt DLLs",
    )
    for name in (*inventory["files"], *inventory["directories"]):
        require(safe_name(name).parts[0] in retained.OUTPUT_DIRS, "Unexpected runtime root")
    check_zip_names(archive)
    retained.check_archive(archive, inventory)
    return report, inventory


def checked_evidence(root):
    receipt = checked_receipt()
    report, inventory = checked_bundle(root / BUNDLE)
    require(
        report["raw_archive"] == receipt["raw_build_retention"]["archive"],
        "Reviewed raw archive differs",
    )
    old = root / OLD_PROOF
    recovery = reuse.load_recovery(old)
    require(digest(old / "validation.json") == VALIDATION_SHA, "Recorded validation changed")
    validation = read_json(old / "validation.json")
    require(
        validation["native_runtime"] == receipt["managed_runtime"]["native_runtime"]
        and all(
            len(value["packages"]) == 361 for value in validation["installed_inventories"].values()
        )
        and all(
            len(value["qt_libraries"]) == 70 and len(value["qt_plugins"]) == 42
            for value in validation["native_runtime"].values()
        )
        and validation["proof_recovery_sha256"] == digest(old / "recovery.json"),
        "Recorded exact managed runtimes differ",
    )
    require(
        digest(old / "upstream-check/upstream.json") == UPSTREAM_SHA,
        "Passed upstream receipt changed",
    )
    upstream = read_json(old / "upstream-check/upstream.json")
    require(
        upstream["passed"] is True
        and upstream["test_cases"] == 10
        and upstream["validation_sha256"] == VALIDATION_SHA
        and upstream["executable_sha256"] == reuse.UPSTREAM_SHA,
        "Attempt 3 upstream binding differs",
    )
    for label, flag in (("old-routing", None), ("forced-stderr", "1")):
        run = upstream["runs"][label]
        log = old / "upstream-check" / (label + ".log")
        require(
            digest(log) == run["log_sha256"] == receipt["new_upstream"]["runs"][label]["sha256"]
            and run["QT_FORCE_STDERR_LOGGING"] == flag
            and run["transcript_has_complete_10_version"] is reuse.upstream_passed(log.read_text())
            and PureWindowsPath(run["log"])
            == PureWindowsPath(TEMPORARY) / "qt-pdf-reused-qt/upstream-check" / (label + ".log")
            and run["command"]
            == [
                str(
                    PureWindowsPath(TEMPORARY)
                    / "qt-pdf-reused-qt/artifact"
                    / common.DEVICE_ROOT
                    / reuse.UPSTREAM
                )
            ],
            "Passed upstream transcript/launch changed",
        )
        if label == "forced-stderr":
            require(
                run["returncode"] == 0 and reuse.upstream_passed(log.read_text()),
                "Strict upstream10 failed",
            )
    executable = old / "artifact" / common.DEVICE_ROOT / reuse.UPSTREAM
    require(
        digest(executable) == reuse.UPSTREAM_SHA
        and reuse.pe_x64(executable, dll=False) == upstream["executable_PE"],
        "Upstream PE changed",
    )
    bypass = read_json(root / OLD_MODULE / "bypass-provenance.json")
    require(
        bypass == read_json(root / BUNDLE / "bypass-provenance.json")
        and digest(root / OLD_MODULE / "TechDrawGui.pyd")
        == bypass["module_sha256"]
        == inventory["files"]["Mod/TechDraw/TechDrawGui.pyd"]["sha256"],
        "Actual compiled/scratch bypass changed",
    )
    return report, inventory, recovery, validation, upstream


def transport_data(work):
    work = physical(work)
    records = [read_json(work / name) for name in ("run.json", "artifact-api.json", "jobs.json")]
    check_api(*records)
    archive = physical(work / "artifact.zip")
    require(
        archive.stat().st_size == PRIOR["size"] and digest(archive) == PRIOR["zip_sha256"],
        "Whole attempt 3 ZIP changed",
    )
    check_zip_names(archive)
    inventory = common.zip_inventory(archive)
    reuse.check_tree(work / "artifact", inventory)
    checked_evidence(work / "artifact")
    return {
        "schema_version": 1,
        "prior_run_id": PRIOR["run"],
        "prior_attempt": PRIOR["attempt"],
        "prior_job_id": PRIOR["job"],
        "prior_head_sha": HEAD,
        "artifact_id": PRIOR["artifact"],
        "artifact_zip_sha256": PRIOR["zip_sha256"],
        "artifact_files": inventory,
        "reviewed_receipt_sha256": digest(RECEIPT),
        "helper_sha256": digest(Path(__file__).resolve()),
        "qt66_passed_reused": True,
        "upstream10_passed_reused": True,
        "upstream_tests_invoked": False,
        "native_freecad_qualified": False,
        "qualified": False,
    }


def load_transport(work):
    report = transport_data(work)
    require(
        report == read_json(work / "recovery.json"),
        "Native restoration recovery changed",
    )
    return report


def recover(args):
    native_paths()
    require(args.prior_run_id == PRIOR["run"], "Only reviewed Windows attempt 3 is admitted")
    work = reuse.fresh_work(args.work_dir)
    records = {
        "run": common.api(f"actions/runs/{PRIOR['run']}/attempts/{PRIOR['attempt']}"),
        "artifact-api": common.api(f"actions/artifacts/{PRIOR['artifact']}"),
        "jobs": common.api(
            f"actions/runs/{PRIOR['run']}/attempts/{PRIOR['attempt']}/jobs?per_page=100"
        ),
    }
    check_api(records["run"], records["artifact-api"], records["jobs"])
    require(not records["artifact-api"]["expired"], "Attempt 3 artifact expired")
    work.mkdir()
    for name, value in records.items():
        write_json(work / (name + ".json"), value)
    archive = work / "artifact.zip"
    with archive.open("xb") as output:
        subprocess.run(
            [
                "gh",
                "api",
                f"repos/{common.REPOSITORY}/actions/artifacts/{PRIOR['artifact']}/zip",
            ],
            stdout=output,
            check=True,
        )
    require(
        archive.stat().st_size == PRIOR["size"] and digest(archive) == PRIOR["zip_sha256"],
        "Whole attempt 3 download differs",
    )
    check_zip_names(archive)
    common.zip_inventory(archive, work / "artifact")
    write_json(work / "recovery.json", transport_data(work))
    return {"proof_dir": str(work), "qualified": False}


def checked_source(source, tracked):
    current_head = retained.git(source, "rev-parse", "HEAD").decode().strip()
    require(
        current_head == os.environ["GITHUB_SHA"],
        "Current checkout/workflow head differs",
    )
    current = retained.source_inventory(source, current_head)
    require(
        tracked["head"] == HEAD
        and current["selected_paths"] == tracked["selected_paths"]
        and current["files"] == tracked["files"]
        and current["submodules"] == tracked["submodules"],
        "Selected source blob IDs/worktree bytes/submodules differ from compiled build",
    )
    require(
        digest(reuse.qualifier.FIXTURE / "native-freecad.FCMacro") == MACRO_SHA,
        "Native macro changed",
    )
    # A reviewed launch correction may change launch(), while acceptance code stays exact.
    original = retained.git(
        source,
        "show",
        HEAD + ":tests/src/Mod/TechDraw/Gui/QtPdfStroker/native_compare.py",
    )

    def acceptance(raw):
        tree = ast.parse(raw)
        tree.body = [
            node
            for node in tree.body
            if not (isinstance(node, ast.FunctionDef) and node.name == "launch")
        ]
        return ast.dump(tree, include_attributes=False)

    require(
        acceptance(original)
        == acceptance((reuse.qualifier.FIXTURE / "native_compare.py").read_bytes()),
        "Native acceptance/comparison code changed outside launch",
    )
    return {
        "current_head_sha": current_head,
        "build_head_sha": HEAD,
        "selected_source_bytes_identical": True,
        "initialized_submodule_heads_identical": True,
        "submodule_file_bytes_inventoried": False,
    }


def tree_files(root):
    reuse.guard_tree(root)
    result = {}
    for path in root.rglob("*"):
        if path.is_file():
            require(path.stat().st_nlink == 1, "Linked restoration input")
            result[path.relative_to(root).as_posix()] = {
                "size": path.stat().st_size,
                "sha256": digest(path),
            }
    return result


def copy_tree(source, destination):
    inventory = tree_files(source)
    require(
        not physical(destination, existing=False).exists(),
        "Restoration destination must be fresh",
    )
    destination.mkdir()
    for name in inventory:
        path = physical(destination / safe_name(name), existing=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(physical(source / name), path)
    reuse.check_tree(destination, inventory)
    return inventory


def extract_runtime(archive, destination, inventory):
    """Validate the entire ZIP before writing and rehash every restored file."""
    check_zip_names(archive)
    retained.check_archive(archive, inventory)
    require(
        not physical(destination, existing=False).exists(),
        "Build restoration must be fresh",
    )
    destination.mkdir()
    for name, entry in inventory["directories"].items():
        path = physical(destination / safe_name(name), existing=False)
        path.mkdir()
        os.chmod(path, entry["mode"])
    with zipfile.ZipFile(archive) as zipped:
        for name, entry in inventory["files"].items():
            path = physical(destination / safe_name(name), existing=False)
            with zipped.open(name) as origin, path.open("xb") as output:
                shutil.copyfileobj(origin, output, 1024 * 1024)
            os.chmod(path, entry["mode"])
    checked_runtime(destination, inventory)


def checked_runtime(build, inventory):
    current = retained.output_inventory(build)
    require(
        all(current[key] == inventory[key] for key in ("files", "directories", "physical_bytes")),
        "Restored physical build inventory differs",
    )
    pe = {}
    for name, entry in inventory["files"].items():
        if Path(name).suffix.lower() in (".exe", ".dll", ".pyd"):
            pe[name] = {
                **reuse.pe_x64(build / name, dll=Path(name).suffix.lower() != ".exe"),
                "sha256": entry["sha256"],
            }
    require(len(pe) == 23, "Restored native PE inventory differs")
    return pe


def restore(args):
    host, source, temporary = native_paths()
    work = physical(args.proof_dir)
    load_transport(work)
    require(
        work.is_relative_to(temporary),
        "Restoration proof must remain under RUNNER_TEMP",
    )
    root, bundle = work / "artifact", work / "artifact" / BUNDLE
    report, inventory = checked_bundle(bundle)
    source_binding = checked_source(source, read_json(bundle / "source-files.json"))
    build, proof, module = (
        source / "build/release",
        temporary / "qt-pdf-reused-qt",
        temporary / "qt-pdf-native-module",
    )
    for path in (build, proof, module):
        require(
            not physical(path, existing=False).exists(),
            "Original restoration roots must be fresh",
        )
        require(
            not work.is_relative_to(path) and not path.is_relative_to(work),
            "Restoration/evidence overlap",
        )
    physical(build.parent, existing=False).mkdir(exist_ok=True)
    extract_runtime(bundle / "native-build.zip", build, inventory)
    shutil.copyfile(bundle / "CMakeCache.txt", build / "CMakeCache.txt")
    old_files = copy_tree(root / OLD_PROOF, proof)
    module_files = copy_tree(root / OLD_MODULE, module)
    tracked = read_json(bundle / "source-files.json")
    retained.checked_bypass(source, build, module / "TechDrawGui.pyd", tracked)
    require(
        digest(build / "CMakeCache.txt") == report["input_sha256"]["CMakeCache.txt"],
        "Restored cache changed",
    )
    require(
        reuse.load_upstream(proof) == read_json(root / OLD_PROOF / "upstream-check/upstream.json"),
        "Restored upstream proof differs",
    )
    receipt = {
        "schema_version": 1,
        "status": "restored",
        "restoration_validated": True,
        "scope": "Authenticated physical build readback at original native Windows paths; native acceptance outstanding",
        "host": host,
        "prior_run_id": PRIOR["run"],
        "prior_attempt": PRIOR["attempt"],
        "prior_job_id": PRIOR["job"],
        "build_head_sha": HEAD,
        "source_binding": source_binding,
        "build_root": str(build),
        "old_proof_dir": str(proof),
        "bypass_module": str(module / "TechDrawGui.pyd"),
        "old_proof_files": old_files,
        "bypass_files": module_files,
        "native_pe": checked_runtime(build, inventory),
        "raw_diagnostic_receipt_sha256": BUILD_SHA,
        "raw_receipt_unchanged": True,
        "raw_receipt_restoration_validated": False,
        "old_validation_sha256": VALIDATION_SHA,
        "upstream_receipt_sha256": UPSTREAM_SHA,
        "helper_sha256": digest(Path(__file__).resolve()),
        "qualified": False,
        "native_freecad_qualified": False,
        "distribution_promoted": False,
    }
    write_json(work / "restoration.json", receipt)
    return {
        "restoration_json": str(work / "restoration.json"),
        "freecad": str(build / "bin/FreeCAD.exe"),
        "bypass_module": str(module / "TechDrawGui.pyd"),
        "qualified": False,
    }


def current_restoration(work):
    _, source, temporary = native_paths()
    load_transport(work)
    receipt = read_json(work / "restoration.json")
    require(
        receipt["status"] == "restored"
        and receipt["restoration_validated"] is True
        and receipt["helper_sha256"] == digest(Path(__file__).resolve())
        and receipt["old_validation_sha256"] == VALIDATION_SHA
        and receipt["upstream_receipt_sha256"] == UPSTREAM_SHA,
        "Restoration receipt differs",
    )
    bundle = work / "artifact" / BUNDLE
    report, inventory = checked_bundle(bundle)
    source_binding = checked_source(source, read_json(bundle / "source-files.json"))
    require(source_binding == receipt["source_binding"], "Restored source changed")
    require(
        checked_runtime(source / "build/release", inventory) == receipt["native_pe"],
        "Restored PE changed",
    )
    require(
        digest(source / "build/release/CMakeCache.txt") == report["input_sha256"]["CMakeCache.txt"]
        and receipt["old_proof_files"] == tree_files(work / "artifact" / OLD_PROOF)
        and receipt["bypass_files"] == tree_files(work / "artifact" / OLD_MODULE),
        "Restored cache or original proof/module inventory binding changed",
    )
    for root, entries in (
        (temporary / "qt-pdf-reused-qt", receipt["old_proof_files"]),
        (temporary / "qt-pdf-native-module", receipt["bypass_files"]),
    ):
        reuse.guard_tree(root)
        for name, entry in entries.items():
            path = physical(root / safe_name(name))
            require(
                path.is_file()
                and path.stat().st_size == entry["size"]
                and digest(path) == entry["sha256"],
                "Immutable restored proof/module file changed",
            )
    return receipt


def binding_data(args):
    work = physical(args.proof_dir)
    receipt = current_restoration(work)
    _, _, temporary = native_paths()
    old = temporary / "qt-pdf-reused-qt"
    recorded = reuse.current_validation(old)
    require(
        physical(args.baseline_prefix)
        == physical(Path(recorded["native_runtime"]["baseline"]["prefix"]))
        and physical(args.patched_prefix)
        == physical(Path(recorded["native_runtime"]["patched"]["prefix"]))
        and physical(args.package_build_json)
        == physical(Path(recorded["package_evidence"]["build_json"]))
        and physical(args.qt_source_archive) == physical(Path(recorded["qt_source_archive"])),
        "Fresh package/source/runtime paths differ from immutable passed validation",
    )
    reuse.load_upstream(old)
    return {
        "schema_version": 1,
        "restoration_sha256": digest(work / "restoration.json"),
        "old_validation_sha256": digest(old / "validation.json"),
        "upstream_receipt_sha256": digest(old / "upstream-check/upstream.json"),
        "native_runtime": recorded["native_runtime"],
        "installed_inventories": recorded["installed_inventories"],
        "source_binding": receipt["source_binding"],
        "qt66_passed_reused": True,
        "qt_cases": 66,
        "upstream10_passed_reused": True,
        "upstream_test_cases": 10,
        "upstream_tests_invoked": False,
        "native_freecad_qualified": False,
        "qualified": False,
    }


def validate(args):
    work = physical(args.proof_dir)
    write_json(work / "fresh-binding.json", binding_data(args))
    return {"fresh_binding_json": str(work / "fresh-binding.json"), "qualified": False}


def verify_native(args):
    work = physical(args.proof_dir)
    current_restoration(work)
    _, _, temporary = native_paths()
    old = temporary / "qt-pdf-reused-qt"
    validation = read_json(old / "validation.json")
    current = binding_data(
        argparse.Namespace(
            proof_dir=work,
            baseline_prefix=Path(validation["native_runtime"]["baseline"]["prefix"]),
            patched_prefix=Path(validation["native_runtime"]["patched"]["prefix"]),
            package_build_json=Path(validation["package_evidence"]["build_json"]),
            qt_source_archive=Path(validation["qt_source_archive"]),
        )
    )
    require(
        current == read_json(work / "fresh-binding.json"),
        "Fresh runtime restoration binding changed",
    )
    require(
        not physical(args.native_results).is_relative_to(work)
        and not work.is_relative_to(physical(args.native_results))
        and not physical(args.native_report).is_relative_to(work),
        "Fresh native evidence overlaps authenticated attempt 3 inputs",
    )
    result = reuse.verify_native(
        argparse.Namespace(
            proof_dir=old,
            native_results=args.native_results,
            native_report=args.native_report,
        )
    )
    require(result["qualified"] is True, "Fresh native acceptance failed")
    accepted = old / "native-reuse-qualification.json"
    # The adapter's upstream_newly_passed label is relative to run 37250196345.
    # This wrapper identifies the already passed attempt-3 gate reused in this job.
    final = {
        "schema_version": 1,
        "scope": "Restored native build plus authenticated reused Qt66/upstream10 and fresh native24/GUI11 acceptance",
        "prior_run_id": PRIOR["run"],
        "prior_attempt": PRIOR["attempt"],
        "prior_job_id": PRIOR["job"],
        "prior_native_passed": False,
        "native_build_recompiled": False,
        "qt66_passed_reused": True,
        "upstream10_passed_reused": True,
        "upstream_tests_invoked": False,
        "qt_cases": 66,
        "upstream_test_cases": 10,
        "native_cases": 24,
        "gui_test_cases_per_side": 11,
        "restoration_sha256": digest(work / "restoration.json"),
        "fresh_binding_sha256": digest(work / "fresh-binding.json"),
        "strict_native_acceptance_sha256": digest(accepted),
        "upstream_receipt_sha256": UPSTREAM_SHA,
        "native_freecad_qualified": True,
        "qualified": True,
        "distribution_promoted": False,
    }
    current_restoration(work)
    write_json(work / "native-qualification.json", final)
    return {
        "native_qualification_json": str(work / "native-qualification.json"),
        "qualified": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    recovery = commands.add_parser("recover")
    recovery.add_argument("--prior-run-id", type=int, required=True)
    recovery.add_argument("--work-dir", type=Path, required=True)
    restoration = commands.add_parser("restore")
    restoration.add_argument("--proof-dir", type=Path, required=True)
    validation = commands.add_parser("validate")
    for name in (
        "proof-dir",
        "baseline-prefix",
        "patched-prefix",
        "package-build-json",
        "qt-source-archive",
    ):
        validation.add_argument("--" + name, type=Path, required=True)
    native = commands.add_parser("verify-native")
    for name in ("proof-dir", "native-results", "native-report"):
        native.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        result = {
            "recover": recover,
            "restore": restore,
            "validate": validate,
            "verify-native": verify_native,
        }[args.command](args)
        print(json.dumps(result))
    except (
        OSError,
        ValueError,
        KeyError,
        ImportError,
        subprocess.SubprocessError,
        zipfile.BadZipFile,
    ) as error:
        print(f"Windows native restoration rejected: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
