# SPDX-License-Identifier: LGPL-2.1-or-later
"""Restore finitely pinned completed app builds for fresh native capture only.

Their historical capture failures remain immutable and unqualified. Both the
ordinary build and mitigation-bypass module are restored at their original
physical paths, including authenticated file timestamps. This helper executes
no compiler, Qt test, GUI test or PDF inspector and restores no SDK bytes.
"""

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import stat
import unicodedata
import zipfile

import build_libpack_backport as adapter
import qualify_libpack_backport as qt_checks
import restore_libpack_candidate as transport
import restore_libpack_native_failed as unfinished

# Populated solely from whole-archive authenticated terminal failure artifacts.
PINS = {
    "3.5.5-x64": {
        "run_id": 37481334440,
        "head": "2b90ac89046ac6cc76bb3284f8a27a49bb82c58c",
        "job_id": 112329972989,
        "runner": "windows-2022",
        "job_name": "libpack-install-recovery / recover (3.5.5-x64, windows-2022, x64, " "false)",
        "drive": "D:",
        "stages": {
            "Require the explicit host-tool profile before downloading retained SDKs": "success",
            "Authenticate and recover the compiled SDK without Qt compilation": "success",
            "Recover the unfinished native build and already passed Qt evidence": "skipped",
            "Capture pending candidate Qt66 and upstream10 using the retained baseline": "success",
            "Require strict Qt66 and upstream10 before building FreeCAD": "success",
            "Build scoped FreeCAD and capture the pending stock native PDF routes": "failure",
            "Inspect native24 and stock GUI routes using the already passed Qt inspection": "skipped",
            "Index unfinished native build bytes for a focused follow-up": "success",
            "Retain unfinished scoped FreeCAD build without a qualification claim": "success",
            "Retain new installation, Qt, native and failure evidence": "success",
        },
        "immutable_original_sha256": "9781dbf241c04cda37cd3dba1fd626c343fdff027d563f24d081bc4039eee04d",
        "artifacts": {
            "result": (
                11427994820,
                47867211,
                "f239dc152660a9a8b6160456a61a154b37401be4c0cc4ca1d3693a59c9e67d79",
            ),
            "native-build": (
                11427779740,
                494043913,
                "4c44cbcd16599a73b8e87b356838d6f3bb8be476e2a4389ce7cf22891e02aec7",
            ),
        },
        "zip_content": {
            "result": {"member_count": 1029, "uncompressed_bytes": 243514109},
            "native-build": {"member_count": 6410, "uncompressed_bytes": 2837629680},
        },
        "historical_sdk_preservation": {"baseline_unchanged": False, "candidate_unchanged": False},
    },
    "3.5.3-x64": {
        "run_id": 37481334440,
        "head": "2b90ac89046ac6cc76bb3284f8a27a49bb82c58c",
        "job_id": 112329973789,
        "runner": "windows-2022",
        "job_name": "libpack-install-recovery / recover (3.5.3-x64, windows-2022, x64, " "true)",
        "drive": "D:",
        "stages": {
            "Require the explicit host-tool profile before downloading retained SDKs": "success",
            "Authenticate and recover the compiled SDK without Qt compilation": "success",
            "Recover the unfinished native build and already passed Qt evidence": "success",
            "Capture pending candidate Qt66 and upstream10 using the retained baseline": "skipped",
            "Require strict Qt66 and upstream10 before building FreeCAD": "skipped",
            "Build scoped FreeCAD and capture the pending stock native PDF routes": "failure",
            "Inspect native24 and stock GUI routes using the already passed Qt inspection": "skipped",
            "Index unfinished native build bytes for a focused follow-up": "success",
            "Retain unfinished scoped FreeCAD build without a qualification claim": "success",
            "Retain new installation, Qt, native and failure evidence": "success",
        },
        "immutable_original_sha256": "aa7f318658a16d9b2f84016ee35c71d2338e7faab8d7a963eace0c0dc3d4aecd",
        "artifacts": {
            "result": (
                11430275011,
                47785687,
                "c6072144b0593fa1bc7f75241c9770ab081f8bad0918c489eab1f4bf3eea32d0",
            ),
            "native-build": (
                11428809844,
                494260706,
                "b72bcc862d1cb8709fad5a30d96ffb85cf819e0d4df828e5be9214ec91399e41",
            ),
        },
        "zip_content": {
            "result": {"member_count": 701, "uncompressed_bytes": 242119460},
            "native-build": {"member_count": 6410, "uncompressed_bytes": 2839173598},
        },
        "historical_sdk_preservation": {"baseline_unchanged": False, "candidate_unchanged": False},
    },
    "3.5.5-arm64": {
        "run_id": 37488049364,
        "head": "44039b11d1c18549faa12026b542abf415ad4aaa",
        "job_id": 112353292942,
        "runner": "windows-11-arm",
        "job_name": "libpack-install-recovery / recover (3.5.5-arm64, windows-11-arm, "
        "arm64, true)",
        "drive": "C:",
        "stages": {
            "Require the explicit host-tool profile before downloading retained SDKs": "success",
            "Authenticate and recover the compiled SDK without Qt compilation": "success",
            "Recover the unfinished native build and already passed Qt evidence": "success",
            "Capture pending candidate Qt66 and upstream10 using the retained baseline": "skipped",
            "Require strict Qt66 and upstream10 before building FreeCAD": "skipped",
            "Build scoped FreeCAD and capture the pending stock native PDF routes": "failure",
            "Inspect native24 and stock GUI routes using the already passed Qt inspection": "skipped",
            "Index unfinished native build bytes for a focused follow-up": "success",
            "Retain unfinished scoped FreeCAD build without a qualification claim": "success",
            "Retain new installation, Qt, native and failure evidence": "success",
        },
        "immutable_original_sha256": "441e254ddafa4010219fbd001f3d6fec316827dcd7e48451be73c17ef70fa21b",
        "historical_sdk_preservation": {"baseline_unchanged": False, "candidate_unchanged": True},
        "artifacts": {
            "result": (
                11432078871,
                47157860,
                "9b2280bac5b8bc41c9cd66826fca79f7f462240c6561cd9b12d4c14955850c77",
            ),
            "native-build": (
                11433265282,
                542555043,
                "3ca75cb88f0ad20f1f85888904438053c1dabe24086a9f85ec1342bb8b943849",
            ),
        },
        "zip_content": {
            "result": {"member_count": 634, "uncompressed_bytes": 245040115},
            "native-build": {"member_count": 6412, "uncompressed_bytes": 3416040372},
        },
    },
}
RESULT_ROOTS = unfinished.RESULT_ROOTS | {
    "libpack-host-tools",
    "libpack-native-cache",
    "libpack-native-cache-inputs",
}
BUILD_ROOTS = unfinished.BUILD_ROOTS | {"module", "module.files.json"}
SOURCE_PATHS = (
    ".",
    ":(exclude).beads/issues.jsonl",
    ":(exclude).github/workflows/qt_pdf_libpack_recover.yml",
    ":(exclude)package/qt-pdf/README.md",
    ":(exclude)package/qt-pdf/prepare_libpack_host_tools.py",
    ":(exclude)package/qt-pdf/qualify_libpack_backport.py",
    ":(exclude)package/qt-pdf/qualify_libpack_native.py",
    ":(exclude)package/qt-pdf/restore_libpack_native_completed.py",
    ":(exclude)package/qt-pdf/libpack_readonly_sdk.py",
    ":(exclude)tests/src/Mod/TechDraw/Gui/QtPdfStroker/native-freecad.FCMacro",
    ":(exclude)tests/src/Mod/TechDraw/Gui/QtPdfStroker/native_compare.py",
)
CORE_NAMES = {
    "freecad.exe",
    "freecadapp.dll",
    "freecadbase.dll",
    "freecadgui.dll",
    "techdrawgui.pyd",
}
verify_zips = unfinished.verify_zips


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def expected_artifacts(sdk):
    pin = PINS[sdk]
    names = {"result": "recovered-qualification", "native-build": "unqualified-native-build"}
    return {
        kind: {
            "id": value[0],
            "size": value[1],
            "sha256": value[2],
            "name": f"qt-pdf-libpack-{names[kind]}-{sdk}",
        }
        for kind, value in pin["artifacts"].items()
    }


def extract_zip(archive, destination, sdk, kind):
    """Extract only a whole-authenticated completed archive with finite content size.

    These completed builds have different literal aggregate sizes from the
    earlier unfinished builds. Their shared extractor and its limit stay fixed.
    Every original member/path/CRC/mtime guard remains required here as well.
    """
    adapter.require(sdk in PINS and kind in ("result", "native-build"), "Unpinned completed ZIP")
    expected = PINS[sdk]["zip_content"][kind]
    verify_zips({kind: archive}, {kind: expected_artifacts(sdk)[kind]})
    roots = RESULT_ROOTS if kind == "result" else BUILD_ROOTS
    names, spelling, total = set(), {}, 0
    with zipfile.ZipFile(archive) as stream:
        entries = stream.infolist()
        adapter.require(
            len(entries) == expected["member_count"]
            and len(entries) <= 50000
            and sum(entry.file_size for entry in entries) == expected["uncompressed_bytes"],
            "Completed native-cache ZIP count/aggregate differs",
        )
        destination.mkdir()
        for entry in entries:
            name = transport.member_name(entry.filename)
            mode = stat.S_IFMT(entry.external_attr >> 16)
            adapter.require(
                name.parts[0] in roots
                and str(name) == unicodedata.normalize("NFC", str(name))
                and str(name).casefold() not in names
                and mode in (0, stat.S_IFREG, stat.S_IFDIR)
                and not entry.flag_bits & 1
                and entry.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                and 0 <= entry.file_size <= 64 * 1024**2,
                "Out-of-scope/duplicate/linked/special/encrypted native-cache member",
            )
            names.add(str(name).casefold())
            for count in range(1, len(name.parts) + 1):
                prefix = "/".join(name.parts[:count])
                adapter.require(
                    spelling.setdefault(prefix.casefold(), prefix) == prefix,
                    "Case-colliding native-cache directories",
                )
            total += entry.file_size
            adapter.require(
                total <= expected["uncompressed_bytes"],
                "Oversized completed native-cache ZIP content",
            )
            output = destination / name
            if entry.is_dir():
                adapter.require(mode != stat.S_IFREG, "Inconsistent native-cache directory")
                output.mkdir(parents=True, exist_ok=True)
            else:
                adapter.require(mode != stat.S_IFDIR, "Inconsistent native-cache file")
                output.parent.mkdir(parents=True, exist_ok=True)
                with stream.open(entry) as source, output.open("xb") as target:
                    shutil.copyfileobj(source, target, 1024 * 1024)
                adapter.require(
                    output.stat().st_size == entry.file_size, "Short native-cache member"
                )
                timestamp = datetime(*entry.date_time).timestamp()
                os.utime(output, (timestamp, timestamp))
        adapter.require(total == expected["uncompressed_bytes"], "Incomplete completed ZIP content")


def authenticated_metadata(sdk):
    pin = PINS[sdk]
    run = transport.api(f"actions/runs/{pin['run_id']}")
    adapter.require(
        run["repository"]["full_name"] == transport.REPOSITORY
        and run["id"] == pin["run_id"]
        and run["run_attempt"] == 1
        and run["head_sha"] == pin["head"]
        and run["event"] == "workflow_dispatch"
        and run["path"] == ".github/workflows/qt_pdf_backport.yml"
        and run["status"] == "completed"
        and run["conclusion"] == "failure",
        "Original completed-build workflow identity differs",
    )
    job = transport.api(f"actions/jobs/{pin['job_id']}")
    adapter.require(
        job["id"] == pin["job_id"]
        and job["run_id"] == pin["run_id"]
        and job["run_attempt"] == 1
        and job["head_sha"] == pin["head"]
        and job["labels"] == [pin["runner"]]
        and job["name"] == pin["job_name"]
        and job["status"] == "completed"
        and job["conclusion"] == "failure",
        "Original completed-build job identity differs",
    )
    for name, outcome in pin["stages"].items():
        matches = [step for step in job["steps"] if step["name"] == name]
        adapter.require(
            len(matches) == 1
            and matches[0]["status"] == "completed"
            and matches[0]["conclusion"] == outcome,
            "Original completed-build stage differs: " + name,
        )
    receipts = expected_artifacts(sdk)
    artifacts = transport.api(f"actions/runs/{pin['run_id']}/artifacts?per_page=100")
    adapter.require(
        artifacts["total_count"] <= 100 and len(artifacts["artifacts"]) == artifacts["total_count"],
        "Incomplete completed-build artifact inventory",
    )
    for expected in receipts.values():
        matches = [value for value in artifacts["artifacts"] if value["name"] == expected["name"]]
        adapter.require(len(matches) == 1, "Missing/ambiguous completed-build artifact")
        value = matches[0]
        adapter.require(
            value["id"] == expected["id"]
            and value["size_in_bytes"] == expected["size"]
            and value["digest"] == "sha256:" + expected["sha256"]
            and value["expired"] is False
            and value["workflow_run"]["id"] == pin["run_id"]
            and value["workflow_run"]["head_sha"] == pin["head"],
            "Completed-build artifact identity differs",
        )
    return receipts


def original_fields(capture, retention, build, qt):
    return {
        "native_capture_sha256": retention["native_capture_sha256"],
        "native_capture_status": capture["status"],
        "native_capture_error": capture.get("error"),
        "native_helper_sha256": capture["helper_sha256"],
        "baseline_unchanged": capture["baseline_unchanged"],
        "candidate_unchanged": capture["candidate_unchanged"],
        "retention_sha256": adapter.digest(build / "native-build-retention.json"),
        "build_index_sha256": adapter.digest(build / "b.files.json"),
        "module_index_sha256": adapter.digest(build / "module.files.json"),
        "qt_capture_sha256": capture["qt_capture_sha256"],
        "qt_passed_inspection_sha256": capture["qt_passed_inspection_sha256"],
        "qt_helper_sha256": qt["helper_sha256"],
        "qt_adapter_sha256": qt["adapter_sha256"],
        "freecad_source": capture["freecad_source"],
        "compiler": capture["compiler"],
        "tools": capture["tools"],
        "baseline_sdk": capture["baseline_sdk"],
        "candidate_sdk": capture["candidate_sdk"],
        "binaries": capture["binaries"],
        "bypass_helper_sha256": capture["sources"]["build-native-bypass.py"],
        "configure_command": capture["configure_command"],
        "build_command": capture["build_command"],
    }


def validate_payload(result, build, sdk, helper, native_root=None):
    pin = PINS[sdk["key"]]
    adapter.require(
        {path.name for path in build.iterdir()}
        == (BUILD_ROOTS if native_root is None else BUILD_ROOTS - {"b", "module"}),
        "Completed native build artifact membership differs",
    )
    native = result / "libpack-native/evidence"
    capture = transport.read_json(native / "native-capture.json")
    retention = transport.read_json(build / "native-build-retention.json")
    qt = transport.read_json(native / "qt-capture/capture.json")
    passed = transport.read_json(native / "qt-passed-inspection.json")
    original = original_fields(capture, retention, build, qt)
    adapter.require(
        fingerprint(original) == pin["immutable_original_sha256"],
        "Original completed app/Qt receipt binding differs",
    )
    root = PureWindowsPath(pin["drive"] + "\\a\\_temp\\libpack-native")
    source = PureWindowsPath(pin["drive"] + "\\a\\FreeCAD\\FreeCAD")
    adapter.require(
        retention["schema_version"] == capture["schema_version"] == 1
        and retention["status"] == "unqualified-diagnostic-build"
        and retention["qualified"] is capture["qualified"] is False
        and retention["promotion_allowed"] is capture["promotion_allowed"] is False
        and str(retention["run_id"]) == str(pin["run_id"])
        and str(retention["attempt"]) == "1"
        and retention["checkout_sha"] == capture["freecad_source"]["commit"] == pin["head"]
        and capture["freecad_source"]["root"] == str(source)
        and retention["original_physical_root"] == capture["work_dir"] == str(root)
        and retention["sdk"] == capture["sdk"] == qt["sdk"] == passed["sdk"] == sdk
        and capture["status"] == "failed"
        and all(
            capture[name] is value for name, value in pin["historical_sdk_preservation"].items()
        )
        and retention["native_capture_sha256"] == adapter.digest(native / "native-capture.json")
        and retention["archives"]
        == {
            name: {
                "index": name + ".files.json",
                "index_sha256": adapter.digest(build / (name + ".files.json")),
            }
            for name in ("b", "module")
        },
        "Historical completed native failure/retention differs",
    )
    qt_checks.verify_evidence(native, capture["evidence_sha256"], helper, {"native-capture.json"})
    qt_checks.verify_evidence(
        native / "qt-capture", qt["evidence_sha256"], helper, {"capture.json"}
    )
    adapter.require(
        capture["qt_capture_sha256"] == adapter.digest(native / "qt-capture/capture.json")
        and capture["qt_passed_inspection_sha256"]
        == adapter.digest(native / "qt-passed-inspection.json")
        and qt["status"] == "captured"
        and qt["baseline_unchanged"] is qt["candidate_unchanged"] is True
        and qt["qualified"] is qt["promotion_allowed"] is False
        and passed["status"] == "passed"
        and passed["qt_only_passed"] is True
        and passed["qualified"]
        is passed["native_freecad_tested"]
        is passed["promotion_allowed"]
        is False
        and passed["native_capture_sha256"] == capture["qt_capture_sha256"]
        and passed["inspection_helper_sha256"] == qt["helper_sha256"]
        and passed["upstream_suite"] == qt["upstream_suite"]
        and passed["upstream_suite"]["passed"] is True
        and passed["upstream_suite"]["test_cases"] == 10
        and passed["comparison"]["passed"] is True
        and passed["comparison"]["failures"] == []
        and len(passed["comparison"]["cases"]) == 66,
        "Completed historical Qt qualification differs",
    )
    runtime = native_root or build
    for name in ("b", "module"):
        index = transport.read_json(build / (name + ".files.json"))
        adapter.require(
            helper.inventory(runtime / name) == index, "Completed build bytes/times differ: " + name
        )
        adapter.independent_files(runtime / name, index)
    adapter.require(set(capture["binaries"]) == CORE_NAMES, "Incomplete completed native core")
    for name, record in capture["binaries"].items():
        path = runtime / (
            "module/TechDrawGui.pyd"
            if name == "techdrawgui.pyd"
            else "b/bin/" + PureWindowsPath(record["native_path"]).name
        )
        adapter.require(
            adapter.digest(path) == record["sha256"]
            and helper.pe_machine(path)
            == record["pe_machine"]
            == helper.MACHINES[sdk["architecture"]],
            "Retained completed core bytes/architecture differ",
        )
    adapter.require(
        not list((runtime / "b").rglob("Qt6*.dll")) and not (runtime / "b/bin/qt.conf").exists(),
        "Completed build masks SDK origins",
    )
    values = adapter.parse_cmake_cache(runtime / "b/CMakeCache.txt")
    for key, wanted in {
        "CMAKE_HOME_DIRECTORY": source,
        "CMAKE_CACHEFILE_DIR": root / "b",
        "FREECAD_LIBPACK_DIR": PureWindowsPath(capture["baseline_sdk"]),
        "CMAKE_COMMAND": PureWindowsPath(capture["tools"]["cmake"]["path"]),
        "CMAKE_MAKE_PROGRAM": PureWindowsPath(capture["tools"]["ninja"]["path"]),
        "CMAKE_C_COMPILER": PureWindowsPath(capture["compiler"]["compiler"]),
        "CMAKE_CXX_COMPILER": PureWindowsPath(capture["compiler"]["compiler"]),
    }.items():
        adapter.require(
            PureWindowsPath(values[key]) == wanted,
            "Completed build CMake selection differs: " + key,
        )
    adapter.require(
        values["CMAKE_GENERATOR"] == "Ninja"
        and values["CMAKE_BUILD_TYPE"] == "Release"
        and values["FREECAD_LIBPACK_USE"] == "ON"
        and values["BUILD_WITH_CONDA"] == "OFF"
        and all(
            values[key] == "ON" for key in ("BUILD_GUI", "BUILD_TEST", "ENABLE_DEVELOPER_TESTS")
        )
        and all(
            values[key] == "OFF"
            for key in (
                "FREECAD_COPY_DEPEND_DIRS_TO_BUILD",
                "FREECAD_COPY_LIBPACK_BIN_TO_BUILD",
                "FREECAD_COPY_PLUGINS_BIN_TO_BUILD",
                "FREECAD_INSTALL_DEPEND_DIRS",
            )
        ),
        "Completed build mode differs",
    )
    return original


def validate_receipt(report, sdk):
    pin = PINS[sdk["key"]]
    root = PureWindowsPath(pin["drive"] + "\\a\\_temp\\libpack-native")
    work = PureWindowsPath(report["work_dir"])
    adapter.require(
        report["schema_version"] == 1
        and report["status"] == "native-completed-restored"
        and report["sdk"] == sdk
        and report["original_run_id"] == pin["run_id"]
        and report["original_run_attempt"] == 1
        and report["original_head_sha"] == pin["head"]
        and report["original_job_id"] == pin["job_id"]
        and report["artifact_api_receipts"] == expected_artifacts(sdk["key"])
        and report["restorer_sha256"] == adapter.digest(Path(__file__))
        and fingerprint(report["immutable_original"]) == pin["immutable_original_sha256"]
        and all(
            report[key] is False
            for key in (
                "qualified",
                "promotion_allowed",
                "native_freecad_tested",
                "qt_recompiled",
                "qt_recaptured",
                "qt_rerastered",
                "baseline_regenerated",
                "freecad_recompiled",
                "bypass_recompiled",
            )
        )
        and report["original_zips_unchanged_sha256"] is True
        and report["indexed_build_bytes_and_mtimes_restored"] is True
        and work.is_relative_to(root.parent)
        and work != root.parent
        and not work.is_relative_to(root)
        and not root.is_relative_to(work)
        and report["original_native_root"] == str(root)
        and report["native_build_dir"] == str(root / "b")
        and report["native_module_dir"] == str(root / "module")
        and report["qt_evidence"] == str(work / "result/libpack-native/evidence/qt-capture")
        and report["qt_only_report"]
        == str(work / "result/libpack-native/evidence/qt-passed-inspection.json"),
        "Pinned completed-native restoration admission differs",
    )
    return report


def validate_cache(report_path, helper):
    report_path = helper.real_path(report_path)
    report = transport.read_json(report_path)
    sdk = helper.sdk_identity(report["sdk"]["key"])
    validate_receipt(report, sdk)
    work, root = helper.real_path(Path(report["work_dir"])), helper.real_path(
        Path(report["original_native_root"])
    )
    adapter.require(
        report_path == work / "native-cache-recovery.json"
        and {path.name for path in root.iterdir()} == {"b", "module"},
        "Completed native physical restoration scope differs",
    )
    original = validate_payload(work / "result", work / "native-build", sdk, helper, root)
    adapter.require(
        original == report["immutable_original"], "Completed native immutable readback differs"
    )
    return report


def source_equivalence(source, evidence, environment, original):
    """Compare compiled tracked inputs; never forge checkout/build timestamps."""
    git = original["tools"]["git"]["path"]
    old = original["freecad_source"]["commit"]
    adapter.command(
        [git, "fetch", "--no-tags", "--depth=1", "origin", old],
        evidence,
        "completed-source-fetch",
        source,
        environment,
    )
    changed = adapter.command(
        [git, "diff", "--name-only", old, "HEAD", "--", *SOURCE_PATHS],
        evidence,
        "completed-source-diff",
        source,
        environment,
    )
    adapter.require(
        not changed, "Compiled FreeCAD tracked inputs changed; completed binaries cannot be reused"
    )
    adapter.require(
        adapter.digest(
            adapter.REPO / "tests/src/Mod/TechDraw/Gui/QtPdfStroker/build-native-bypass.py"
        )
        == original["bypass_helper_sha256"],
        "Completed bypass producer changed",
    )
    return {
        "binary_source_commit": old,
        "qualification_source_commit": os.environ["GITHUB_SHA"],
        "selected_paths": list(SOURCE_PATHS),
        "compiled_tracked_inputs_equal": True,
        "source_timestamps_modified": False,
        "freecad_recompiled": False,
        "bypass_recompiled": False,
    }


def restore(args, helper):
    adapter.require(
        os.environ.get("GITHUB_ACTIONS") == "true" and os.name == "nt",
        "Completed native restoration requires disposable Windows CI",
    )
    sdk, pin = helper.sdk_identity(args.sdk), PINS[args.sdk]
    temporary, work = helper.real_path(Path(os.environ["RUNNER_TEMP"])), helper.real_path(
        args.work_dir
    )
    root = helper.real_path(temporary / "libpack-native")
    adapter.require(
        root == Path(pin["drive"] + "\\a\\_temp\\libpack-native")
        and work.is_relative_to(temporary)
        and not root.exists()
        and not work.exists(),
        "Completed native restoration requires fresh original native paths",
    )
    adapter.separate_path(work, root)
    inputs = {
        "result": helper.real_path(args.result_zip),
        "native-build": helper.real_path(args.native_build_zip),
    }
    for path in inputs.values():
        for destination in (work, root):
            adapter.separate_path(destination, path)
    receipts = authenticated_metadata(args.sdk)
    unfinished.verify_zips(inputs, receipts)
    work = helper.fresh_work(work)
    report = {
        "schema_version": 1,
        "status": "failed",
        "sdk": sdk,
        "original_run_id": pin["run_id"],
        "original_run_attempt": 1,
        "original_head_sha": pin["head"],
        "original_job_id": pin["job_id"],
        "artifact_api_receipts": receipts,
        "restorer_sha256": adapter.digest(Path(__file__)),
        "work_dir": str(work),
        "original_native_root": str(root),
    }
    report.update(
        {
            key: False
            for key in (
                "qualified",
                "promotion_allowed",
                "native_freecad_tested",
                "qt_recompiled",
                "qt_recaptured",
                "qt_rerastered",
                "baseline_regenerated",
                "freecad_recompiled",
                "bypass_recompiled",
            )
        }
    )
    try:
        extract_zip(inputs["result"], work / "result", args.sdk, "result")
        extract_zip(inputs["native-build"], work / "native-build", args.sdk, "native-build")
        for name in ("b", "module"):
            unfinished.restore_index(
                work / "native-build" / name,
                transport.read_json(work / "native-build" / (name + ".files.json")),
                helper,
            )
        original = validate_payload(work / "result", work / "native-build", sdk, helper)
        unfinished.verify_zips(inputs, receipts)
        root = helper.fresh_work(root)
        for name in ("b", "module"):
            shutil.move(str(work / "native-build" / name), str(root / name))
        report.update(
            status="native-completed-restored",
            immutable_original=original,
            original_zips_unchanged_sha256=True,
            indexed_build_bytes_and_mtimes_restored=True,
            native_build_dir=str(root / "b"),
            native_module_dir=str(root / "module"),
            qt_evidence=str(work / "result/libpack-native/evidence/qt-capture"),
            qt_only_report=str(work / "result/libpack-native/evidence/qt-passed-inspection.json"),
        )
        validate_receipt(report, sdk)
        adapter.require(
            validate_payload(work / "result", work / "native-build", sdk, helper, root) == original,
            "Moved completed native build readback differs",
        )
    except Exception as error:
        report["status"], report["error"] = "failed", f"{type(error).__name__}: {error}"
        raise
    finally:
        adapter.write_json(work / "native-cache-recovery.json", report)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            for name in ("native_build_dir", "qt_evidence", "qt_only_report"):
                output.write(f"{name}={report[name]}\n")
            output.write(f"cache_report={work / 'native-cache-recovery.json'}\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", choices=PINS, required=True)
    parser.add_argument("--result-zip", type=Path, required=True)
    parser.add_argument("--native-build-zip", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    restore(parser.parse_args(), adapter.baseline_helper())


if __name__ == "__main__":
    main()
