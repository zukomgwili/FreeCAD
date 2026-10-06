# SPDX-License-Identifier: LGPL-2.1-or-later
"""Restore two pinned unfinished FreeCAD builds and their completed Qt evidence.

The historical jobs remain failed and unqualified. This transport admits only
their indexed build bytes at the original native paths, with authenticated file
timestamps, for a subsequent scoped CMake reconfiguration. It neither restores
SDKs nor executes Qt, FreeCAD, compilers or PDF inspection tools.
"""

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import stat
import zipfile

import build_libpack_backport as adapter
import qualify_libpack_backport as qt_checks
import restore_libpack_candidate as transport

RUN_ID = 37465187347
HEAD = "6e8306a4d0c2e377411e3cb554a1081955c2bf61"
QT_HELPER = "3d2c29683af2c2e3c683ef9109779cd2c1d34dcdc8e5f86ae5a631b345881815"
NATIVE_HELPER = "9d5c5acd7152fac0c4faba35c7e2a121a2569f27df1825e1988eae3fc3c15623"
ADAPTER = "2c3d8b69ae2c6403b047dc976cdb6cfc857b8282c4f1fa6d9e0cbdb0c6c4cc72"
PINS = {
    "3.5.3-x64": {
        "job_id": 112274384366,
        "runner": "windows-2022",
        "drive": "D:",
        "native_capture_sha256": "2534b89b8d80c9cacfdee619a06a158929eabbf56f8cb839d1f39ac33900a2ea",
        "retention_sha256": "3ce3df2fe3c5426cbd762ddbe71d3691157c7632a6a56c41da8243604f214ef4",
        "build_index_sha256": "a5fe0e83aac16f635c8a346388123f7b44b39b9bb39621c8a218136a5c81012a",
        "qt_capture_sha256": "8a3161709957a56bac854c5ebd10acd16fd67c28b00f092995c128beb0d21fac",
        "qt_passed_inspection_sha256": "b1db81079f826cba2266d82fc2cb0e6683df48180f2e4bcd67cd9202b23d7d78",
        "build_files": 3315,
        "build_directories": 945,
        "compiler_receipt_sha256": "7cde236da947ac54f388646fbcb8cbb8aabaf89ab55cd6d60ce8e65d11b493e7",
        "tools_receipt_sha256": "4fcb5de31b6270e57d97835fb28bffad849dfec92404eed5c6380c9478e4eefe",
        "freecad_source_receipt_sha256": "f1779e659456d907481c85d292323234f0d02ae6388343d70d625a2717f7857c",
        "artifacts": {
            "result": (
                11418547429,
                26026242,
                "b89889747320890bbfc30cb4199ba181597f3341883353939a53cc833bd81515",
            ),
            "native-build": (
                11418682338,
                250703710,
                "ceae3c4fc64579eecc4b02c0446729ff7add35d3361fb9889a856a6969912a41",
            ),
        },
    },
    "3.5.5-arm64": {
        "job_id": 112274384432,
        "runner": "windows-11-arm",
        "drive": "C:",
        "native_capture_sha256": "44f2bc5a0751235401c473fd7b42b480574c99ea0cda653d1f18c9cb685af6b6",
        "retention_sha256": "9d5de54d8bfb3a0d335646209f8cbc946d6f848aa2a18ac1de245eae3ff2978c",
        "build_index_sha256": "3beb0d1636c52ffa7bc70bcc3bceb3e0d3322e3f75b7d3df106390bf61e4f7e4",
        "qt_capture_sha256": "ac715b41179bf98f03a81c9f7939c324ab6281b0c7208954cfae7bcf3c192641",
        "qt_passed_inspection_sha256": "2a623ae9911304815cb391d75a976308243bd33c2a38597a7f658ab17e4fd555",
        "build_files": 3241,
        "build_directories": 941,
        "compiler_receipt_sha256": "757a7041e3be30b6c08b85a39ad37cf0211117a848c46966e77dbe9c923d1304",
        "tools_receipt_sha256": "1092e19ba26662009e129039813c274b4f12994b1271ecd526762c4221de8cc4",
        "freecad_source_receipt_sha256": "89b015f5ebdde8641ce2c46e9967ec3d82441a96c5d881c2ef11130490d7e5dc",
        "artifacts": {
            "result": (
                11419701390,
                25255667,
                "d2ca952246b80713bb08c12b737a5b83537ce1cac165b092ac1fe48618aab84f",
            ),
            "native-build": (
                11419847142,
                275239310,
                "3fe0a0bcfe0add9b48f43eabc7678a4e5108dca7c2af0df7673726e4a548586c",
            ),
        },
    },
}
RESULT_ROOTS = {
    "libpack-installation-restoration",
    "libpack-native",
    "libpack-qt-capture",
    "libpack-qt-inspection.json",
    "libpack-qt-inspection.renders",
    "libpack-recovery-inputs",
}
BUILD_ROOTS = {"b", "b.files.json", "native-build-retention.json"}


def expected_artifacts(sdk):
    adapter.require(sdk in PINS, "Unpinned native-cache SDK")
    names = {
        "result": "recovered-qualification",
        "native-build": "unqualified-native-build",
    }
    return {
        kind: {
            "id": pin[0],
            "name": f"qt-pdf-libpack-{names[kind]}-{sdk}",
            "size": pin[1],
            "sha256": pin[2],
        }
        for kind, pin in PINS[sdk]["artifacts"].items()
    }


def authenticated_metadata(sdk):
    receipts = expected_artifacts(sdk)
    pin = PINS[sdk]
    run = transport.api(f"actions/runs/{RUN_ID}")
    adapter.require(
        run["id"] == RUN_ID
        and run["repository"]["full_name"] == transport.REPOSITORY
        and run["path"] == ".github/workflows/qt_pdf_backport.yml"
        and run["event"] == "workflow_dispatch"
        and run["run_attempt"] == 1
        and run["head_sha"] == HEAD
        and run["status"] == "completed"
        and run["conclusion"] == "failure",
        "Original failed native workflow identity differs",
    )
    job = transport.api(f"actions/jobs/{pin['job_id']}")
    adapter.require(
        job["id"] == pin["job_id"]
        and job["run_id"] == RUN_ID
        and job["run_attempt"] == 1
        and job["head_sha"] == HEAD
        and job["name"]
        == f"libpack-install-recovery / recover ({sdk}, {pin['runner']}, {sdk.rsplit('-', 1)[1]})"
        and job["labels"] == [pin["runner"]]
        and job["status"] == "completed"
        and job["conclusion"] == "failure",
        "Original failed native job identity differs",
    )
    stages = {
        "Authenticate and recover the compiled SDK without Qt compilation": "success",
        "Capture pending candidate Qt66 and upstream10 using the retained baseline": "success",
        "Require strict Qt66 and upstream10 before building FreeCAD": "success",
        "Build scoped FreeCAD and capture the pending stock native PDF routes": "failure",
        "Inspect native24 and stock GUI routes using the already passed Qt inspection": "skipped",
        "Index unfinished native build bytes for a focused follow-up": "success",
        "Retain unfinished scoped FreeCAD build without a qualification claim": "success",
        "Retain new installation, Qt, native and failure evidence": "success",
    }
    for name, outcome in stages.items():
        matches = [step for step in job["steps"] if step["name"] == name]
        adapter.require(
            len(matches) == 1
            and matches[0]["status"] == "completed"
            and matches[0]["conclusion"] == outcome,
            f"Original native-cache stage differs: {name}",
        )
    artifacts = transport.api(f"actions/runs/{RUN_ID}/artifacts?per_page=100")
    adapter.require(artifacts["total_count"] <= 100, "Paginated artifacts unsupported")
    for expected in receipts.values():
        matches = [item for item in artifacts["artifacts"] if item["name"] == expected["name"]]
        adapter.require(len(matches) == 1, "Missing/ambiguous original native-cache artifact")
        item = matches[0]
        adapter.require(
            item["id"] == expected["id"]
            and item["size_in_bytes"] == expected["size"]
            and item["digest"] == "sha256:" + expected["sha256"]
            and item["expired"] is False
            and item["workflow_run"]["id"] == RUN_ID
            and item["workflow_run"]["head_sha"] == HEAD,
            "Original native-cache artifact API identity differs",
        )
    return receipts


def verify_zips(inputs, receipts):
    adapter.require(set(inputs) == set(receipts), "Incomplete native-cache ZIP selection")
    for kind, path in inputs.items():
        expected = receipts[kind]
        adapter.require(
            path.is_file()
            and path.stat().st_nlink == 1
            and path.stat().st_size == expected["size"]
            and adapter.digest(path) == expected["sha256"],
            "Original native-cache whole-ZIP bytes differ",
        )


def extract_zip(archive, destination, roots):
    """Read CRC-checked regular members, retaining original ZIP timestamps."""
    destination.mkdir()
    names, spelling, total = set(), {}, 0
    with zipfile.ZipFile(archive) as stream:
        adapter.require(len(stream.infolist()) <= 50000, "Excess native-cache ZIP members")
        for entry in stream.infolist():
            name = transport.member_name(entry.filename)
            mode = stat.S_IFMT(entry.external_attr >> 16)
            adapter.require(
                name.parts[0] in roots
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
            adapter.require(total <= 3 * 1024**3, "Oversized native-cache ZIP content")
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


def restore_index(root, index, helper):
    """Recreate indexed empty directories and exact authenticated file mtimes."""
    adapter.require(set(index) == {"directories", "files"}, "Native build index shape differs")
    names = list(index["files"]) + index["directories"]
    adapter.require(
        len(names) == len({name.casefold() for name in names}),
        "Duplicate/case-colliding native build index",
    )
    for name in names:
        transport.member_name(name)
    for name in index["directories"]:
        (root / adapter.safe_relative(name)).mkdir(parents=True, exist_ok=True)
    transport.exact_times(root, index, helper)
    adapter.independent_files(root, index)


def validate_payload(result, build, sdk, helper, native_build=None):
    """Read back immutable historical failures, Qt evidence and indexed b bytes."""
    key = sdk["key"]
    root = PureWindowsPath(PINS[key]["drive"] + "\\a\\_temp\\libpack-native")
    source = PureWindowsPath(PINS[key]["drive"] + "\\a\\FreeCAD\\FreeCAD")
    native_evidence = result / "libpack-native/evidence"
    qt_evidence = result / "libpack-qt-capture/evidence"
    original = transport.read_json(native_evidence / "native-capture.json")
    retention = transport.read_json(build / "native-build-retention.json")
    capture = transport.read_json(qt_evidence / "capture.json")
    inspection = transport.read_json(result / "libpack-qt-inspection.json")
    index = transport.read_json(build / "b.files.json")
    for name, path in {
        "native_capture_sha256": native_evidence / "native-capture.json",
        "retention_sha256": build / "native-build-retention.json",
        "build_index_sha256": build / "b.files.json",
        "qt_capture_sha256": qt_evidence / "capture.json",
        "qt_passed_inspection_sha256": result / "libpack-qt-inspection.json",
    }.items():
        adapter.require(
            adapter.digest(path) == PINS[key][name], "Pinned native-cache receipt differs"
        )
    adapter.require(
        {path.name for path in build.iterdir()}
        == (BUILD_ROOTS if native_build is None else BUILD_ROOTS - {"b"})
        and retention["schema_version"] == original["schema_version"] == 1
        and retention["status"] == "unqualified-diagnostic-build"
        and str(retention["run_id"]) == str(RUN_ID)
        and str(retention["attempt"]) == "1"
        and retention["checkout_sha"] == HEAD
        and retention["sdk"] == original["sdk"] == capture["sdk"] == inspection["sdk"] == sdk
        and retention["qualified"] is original["qualified"] is False
        and retention["promotion_allowed"] is original["promotion_allowed"] is False
        and retention["native_capture_sha256"]
        == adapter.digest(native_evidence / "native-capture.json")
        and retention["original_physical_root"] == original["work_dir"] == str(root)
        and retention["archives"]
        == {"b": {"index": "b.files.json", "index_sha256": adapter.digest(build / "b.files.json")}}
        and original["status"] == "failed"
        and original["error"] == "ValueError: Command failed; inspect freecad-build.log"
        and original["helper_sha256"] == NATIVE_HELPER
        and original["freecad_source"]["commit"] == HEAD
        and original["freecad_source"]["root"] == str(source)
        and original["baseline_unchanged"] is original["candidate_unchanged"] is True
        and original["qt_capture_sha256"] == adapter.digest(qt_evidence / "capture.json")
        and original["qt_passed_inspection_sha256"]
        == adapter.digest(result / "libpack-qt-inspection.json")
        == adapter.digest(native_evidence / "qt-passed-inspection.json"),
        "Original unfinished native build/retention binding differs",
    )
    qt_checks.verify_evidence(
        native_evidence, original["evidence_sha256"], helper, {"native-capture.json"}
    )
    qt_checks.verify_evidence(qt_evidence, capture["evidence_sha256"], helper, {"capture.json"})
    adapter.require(
        helper.inventory(qt_evidence)["files"].keys()
        == helper.inventory(native_evidence / "qt-capture")["files"].keys()
        and all(
            adapter.digest(native_evidence / "qt-capture" / adapter.safe_relative(name)) == sha
            for name, sha in {
                **capture["evidence_sha256"],
                "capture.json": original["qt_capture_sha256"],
            }.items()
        )
        and capture["status"] == "captured"
        and capture["qualified"] is capture["native_freecad_tested"] is False
        and capture["promotion_allowed"] is False
        and capture["candidate_unchanged"] is capture["baseline_unchanged"] is True
        and capture["helper_sha256"] == inspection["inspection_helper_sha256"] == QT_HELPER
        and capture["adapter_sha256"] == ADAPTER
        and capture["candidate_sdk"]
        == original["candidate_sdk"]
        == str(PureWindowsPath(PINS[key]["drive"] + "\\c\\candidate"))
        and original["baseline_sdk"]
        == str(PureWindowsPath(PINS[key]["drive"] + "\\l") / sdk["directory"])
        and original["compiler"] == capture["compiler"]
        and original["tools"] == capture["tools"]
        and inspection["status"] == "passed"
        and inspection["qt_only_passed"] is True
        and inspection["qualified"] is inspection["native_freecad_tested"] is False
        and inspection["promotion_allowed"] is False
        and inspection["native_capture_sha256"] == original["qt_capture_sha256"]
        and inspection["upstream_suite"] == capture["upstream_suite"]
        and capture["upstream_suite"]["passed"] is True
        and capture["upstream_suite"]["test_cases"] == 10
        and inspection["comparison"]["passed"] is True
        and inspection["comparison"]["failures"] == []
        and len(inspection["comparison"]["cases"]) == 66,
        "Original completed Qt inspection/capture binding differs",
    )
    native_build = native_build if native_build is not None else build / "b"
    adapter.require(
        helper.inventory(native_build) == index, "Indexed native build bytes/times differ"
    )
    adapter.independent_files(native_build, index)
    values = adapter.parse_cmake_cache(native_build / "CMakeCache.txt")
    wanted = {
        "CMAKE_HOME_DIRECTORY": source,
        "CMAKE_CACHEFILE_DIR": root / "b",
        "CMAKE_COMMAND": PureWindowsPath(original["tools"]["cmake"]["path"]),
        "CMAKE_MAKE_PROGRAM": PureWindowsPath(original["tools"]["ninja"]["path"]),
        "CMAKE_C_COMPILER": PureWindowsPath(original["compiler"]["compiler"]),
        "CMAKE_CXX_COMPILER": PureWindowsPath(original["compiler"]["compiler"]),
        "FREECAD_LIBPACK_DIR": PureWindowsPath(original["baseline_sdk"]),
    }
    adapter.require(
        all(PureWindowsPath(values[name]) == path for name, path in wanted.items())
        and values["CMAKE_GENERATOR"] == "Ninja"
        and values["FREECAD_LIBPACK_USE"] == "ON"
        and values["BUILD_WITH_CONDA"] == "OFF"
        and all(
            values[name] == "ON" for name in ("BUILD_GUI", "BUILD_TEST", "ENABLE_DEVELOPER_TESTS")
        ),
        "Original unfinished FreeCAD CMake source/compiler/SDK paths differ",
    )
    return original, retention, capture, inspection, index


def historical_fields(original, retention, build):
    return {
        "native_capture_sha256": retention["native_capture_sha256"],
        "native_capture_status": original["status"],
        "native_capture_error": original["error"],
        "native_helper_sha256": NATIVE_HELPER,
        "retention_sha256": adapter.digest(build / "native-build-retention.json"),
        "build_index_sha256": adapter.digest(build / "b.files.json"),
        "qt_capture_sha256": original["qt_capture_sha256"],
        "qt_passed_inspection_sha256": original["qt_passed_inspection_sha256"],
        "qt_helper_sha256": QT_HELPER,
        "qt_adapter_sha256": ADAPTER,
        "freecad_source": original["freecad_source"],
        "compiler": original["compiler"],
        "tools": original["tools"],
        "baseline_sdk": original["baseline_sdk"],
        "candidate_sdk": original["candidate_sdk"],
    }


def validate_receipt(report, sdk):
    """Portable scope/pin gate; native reuse additionally calls validate_cache."""
    pin = PINS[sdk["key"]]
    original = report["immutable_original"]
    root = PureWindowsPath(pin["drive"] + "\\a\\_temp\\libpack-native")
    work = PureWindowsPath(report["work_dir"])
    source = PureWindowsPath(pin["drive"] + "\\a\\FreeCAD\\FreeCAD")
    adapter.require(
        report["schema_version"] == 1
        and report["status"] == "native-cache-restored"
        and all(
            report[name] is False
            for name in (
                "qualified",
                "promotion_allowed",
                "native_freecad_tested",
                "qt_recompiled",
                "qt_recaptured",
                "qt_rerastered",
                "baseline_regenerated",
            )
        )
        and report["sdk"] == sdk
        and report["original_run_id"] == RUN_ID
        and report["original_run_attempt"] == 1
        and report["original_head_sha"] == HEAD
        and report["original_job_id"] == pin["job_id"]
        and report["artifact_api_receipts"] == expected_artifacts(sdk["key"])
        and report["restorer_sha256"] == adapter.digest(Path(__file__))
        and all(
            hashlib.sha256(
                json.dumps(original[name], sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            == pin[name + "_receipt_sha256"]
            for name in ("compiler", "tools", "freecad_source")
        )
        and report["original_zips_unchanged_sha256"] is True
        and report["indexed_build_bytes_and_mtimes_restored"] is True
        and report["build_files"] == pin["build_files"]
        and report["build_directories"] == pin["build_directories"]
        and original["native_capture_status"] == "failed"
        and original["native_capture_error"]
        == "ValueError: Command failed; inspect freecad-build.log"
        and original["native_helper_sha256"] == NATIVE_HELPER
        and original["qt_helper_sha256"] == QT_HELPER
        and original["qt_adapter_sha256"] == ADAPTER
        and all(
            original[name] == pin[name]
            for name in (
                "native_capture_sha256",
                "retention_sha256",
                "build_index_sha256",
                "qt_capture_sha256",
                "qt_passed_inspection_sha256",
            )
        )
        and original["freecad_source"]["commit"] == HEAD
        and original["freecad_source"]["root"] == str(source)
        and original["candidate_sdk"] == str(PureWindowsPath(pin["drive"] + "\\c\\candidate"))
        and original["baseline_sdk"]
        == str(PureWindowsPath(pin["drive"] + "\\l") / sdk["directory"])
        and work != root.parent
        and work.is_relative_to(root.parent)
        and not work.is_relative_to(root)
        and not root.is_relative_to(work)
        and report["original_native_root"] == str(root)
        and report["native_build_dir"] == str(root / "b")
        and report["build_index"] == str(work / "native-build/b.files.json")
        and report["retained_native_evidence"] == str(work / "result/libpack-native/evidence")
        and report["qt_evidence"] == str(work / "result/libpack-qt-capture/evidence")
        and report["qt_only_report"] == str(work / "result/libpack-qt-inspection.json"),
        "Pinned unfinished-native cache admission differs",
    )
    return report


def validate_cache(report_path, helper):
    """Authenticate actual restored cache bytes without changing any timestamp."""
    report_path = helper.real_path(report_path)
    report = transport.read_json(report_path)
    sdk = helper.sdk_identity(report["sdk"]["key"])
    validate_receipt(report, sdk)
    work = helper.real_path(Path(report["work_dir"]))
    root = helper.real_path(Path(report["original_native_root"]))
    adapter.require(
        report_path == work / "native-cache-recovery.json"
        and {path.name for path in root.iterdir()} == {"b"},
        "Native cache physical scope differs before reconfiguration",
    )
    original, retention, _, _, _ = validate_payload(
        work / "result", work / "native-build", sdk, helper, root / "b"
    )
    adapter.require(
        report["immutable_original"]
        == historical_fields(original, retention, work / "native-build"),
        "Immutable native cache readback differs",
    )
    return report


def restore(args, helper):
    adapter.require(
        os.environ.get("GITHUB_ACTIONS") == "true" and os.name == "nt",
        "Native build cache requires a disposable Windows CI job",
    )
    sdk = helper.sdk_identity(args.sdk)
    temporary = helper.real_path(Path(os.environ["RUNNER_TEMP"]))
    work = helper.real_path(args.work_dir)
    root = helper.real_path(temporary / "libpack-native")
    expected_root = Path(PINS[args.sdk]["drive"] + "\\a\\_temp\\libpack-native")
    adapter.require(
        work.is_relative_to(temporary)
        and root == expected_root
        and not root.exists()
        and not work.exists(),
        "Native cache transport/original native root must be fresh under RUNNER_TEMP",
    )
    inputs = {
        "result": helper.real_path(args.result_zip),
        "native-build": helper.real_path(args.native_build_zip),
    }
    for path in inputs.values():
        for output in (work, root):
            adapter.separate_path(output, path)
    adapter.separate_path(work, root)
    receipts = authenticated_metadata(args.sdk)
    verify_zips(inputs, receipts)
    work = helper.fresh_work(work)
    report = {
        "schema_version": 1,
        "status": "failed",
        "qualified": False,
        "promotion_allowed": False,
        "native_freecad_tested": False,
        "qt_recompiled": False,
        "qt_recaptured": False,
        "qt_rerastered": False,
        "baseline_regenerated": False,
        "sdk": sdk,
        "original_run_id": RUN_ID,
        "original_run_attempt": 1,
        "original_head_sha": HEAD,
        "original_job_id": PINS[args.sdk]["job_id"],
        "artifact_api_receipts": receipts,
        "restorer_sha256": adapter.digest(Path(__file__)),
        "work_dir": str(work),
        "original_native_root": str(root),
    }
    try:
        extract_zip(inputs["result"], work / "result", RESULT_ROOTS)
        extract_zip(inputs["native-build"], work / "native-build", BUILD_ROOTS)
        restore_index(
            work / "native-build/b", transport.read_json(work / "native-build/b.files.json"), helper
        )
        original, retention, capture, inspection, index = validate_payload(
            work / "result", work / "native-build", sdk, helper
        )
        verify_zips(inputs, receipts)
        root = helper.fresh_work(root)
        shutil.move(str(work / "native-build/b"), str(root / "b"))
        adapter.require(
            helper.inventory(root / "b") == index, "Moved native cache readback differs"
        )
        report.update(
            {
                "status": "native-cache-restored",
                "original_zips_unchanged_sha256": True,
                "immutable_original": historical_fields(original, retention, work / "native-build"),
                "native_build_dir": str(root / "b"),
                "build_index": str(work / "native-build/b.files.json"),
                "retained_native_evidence": str(work / "result/libpack-native/evidence"),
                "qt_evidence": str(work / "result/libpack-qt-capture/evidence"),
                "qt_only_report": str(work / "result/libpack-qt-inspection.json"),
                "build_files": len(index["files"]),
                "build_directories": len(index["directories"]),
                "indexed_build_bytes_and_mtimes_restored": True,
                "inspection_reuse_scope": "Authenticated completed historical Qt66/upstream10 only; current SDK/source/compiler checks remain mandatory before native execution",
            }
        )
        validate_receipt(report, sdk)
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
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
