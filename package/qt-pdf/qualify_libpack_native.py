# SPDX-License-Identifier: LGPL-2.1-or-later
"""Capture a same-host LibPack FreeCAD pair and inspect it on a PDF-tool host.

Capture requires the authenticated actual Qt-only candidate capture and retained
SDK bytes. It builds a disposable baseline-linked FreeCAD once, disables the two
mitigations only through the existing CI bypass helper, and runs both stock GUI
PDF routes under each SDK. Capture never qualifies a result. Inspection first
reruns the matching Qt-only inspection, authenticates the native DLL receipts,
then checks all24 exports, GUI11, operators, exact per-device RGBA and visible ink.
Neither operation promotes a package or changes a protected SDK.
"""

import argparse
from contextlib import nullcontext
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import sys
from types import SimpleNamespace

import build_libpack_backport as adapter
import qualify_libpack_backport as qt_checks
import libpack_readonly_sdk as sdk_protection

FIXTURE = adapter.REPO / "tests/src/Mod/TechDraw/Gui/QtPdfStroker"
NATIVE_SOURCES = (
    "native_compare.py",
    "native-freecad.FCMacro",
    "build-native-bypass.py",
    "compare.py",
)
TARGETS = (
    "src/Main/all",
    "src/Gui/all",
    "src/Mod/Part/all",
    "src/Mod/PartDesign/all",
    "src/Mod/Sketcher/all",
    "src/Mod/TechDraw/all",
    "src/Mod/Material/all",
    "src/Mod/Test/all",
    "pivy",
)
COPY_OPTIONS = (
    "FREECAD_COPY_DEPEND_DIRS_TO_BUILD",
    "FREECAD_COPY_LIBPACK_BIN_TO_BUILD",
    "FREECAD_COPY_PLUGINS_BIN_TO_BUILD",
    "FREECAD_INSTALL_DEPEND_DIRS",
)
CORE_NAMES = {
    "freecad.exe",
    "freecadapp.dll",
    "freecadbase.dll",
    "freecadgui.dll",
    "techdrawgui.pyd",
}
BINDING_NAMES = {"python314.dll", "pyside6.abi3.dll", "shiboken6.abi3.dll"}


def json_file(path):
    return json.loads(path.read_text(encoding="utf-8"))


def native_helper():
    # Capture needs only the stdlib launch/record checks, never PDF-tool imports.
    return adapter.load_module("libpack_native_controls", FIXTURE / "native_compare.py")


def source_receipts():
    return {name: adapter.digest(FIXTURE / name) for name in NATIVE_SOURCES}


def cache_values(path):
    return adapter.parse_cmake_cache(path)


def configured_python(values, sdk, inventory):
    """Authenticate LibPack Python3.14's actual CMake selections, not host Python."""
    wanted = {
        "executable": ("bin/python.exe", ("Python3_EXECUTABLE", "_Python3_EXECUTABLE")),
        "library": (
            "bin/libs/python314.lib",
            ("Python3_LIBRARY_RELEASE", "_Python3_LIBRARY_RELEASE"),
        ),
        "include": ("bin/Include", ("Python3_INCLUDE_DIR", "_Python3_INCLUDE_DIR")),
    }
    selected = {}
    root = PureWindowsPath(sdk)
    for role, (relative, keys) in wanted.items():
        candidates = {PureWindowsPath(values[key]) for key in keys if values.get(key)}
        adapter.require(candidates == {root / relative}, f"Configured SDK Python {role} differs")
        member = relative + "/Python.h" if role == "include" else relative
        adapter.require(member in inventory["files"], f"Missing SDK Python {role} bytes")
        selected[role] = {
            "path": str(root / relative),
            "sha256": inventory["files"][member]["sha256"],
        }
    return selected


def validate_readonly_preflight(directory, expected_root):
    """Read back the shared real Windows denial contract without executing it."""
    report = json_file(directory / "preflight.json")
    protection = directory / "evidence/sdk-readonly.json"
    sdk_protection.validate_preflight_report(report, protection)
    sdk_protection.validate_evidence(protection, roots=[str(expected_root)], purpose="preflight")
    return report


def native_cache_admission(report, sdk):
    """Only finitely pinned historical builds can carry their passed Qt proof."""
    filename = {
        "native-cache-restored": "restore_libpack_native_failed.py",
        "native-completed-restored": "restore_libpack_native_completed.py",
    }.get(report.get("status"))
    adapter.require(filename is not None, "Unsupported native cache admission")
    restorer = adapter.load_module(
        "libpack_native_cache_admission",
        Path(__file__).with_name(filename),
    )
    restorer.validate_receipt(report, sdk)
    return restorer


def passed_qt_report(path, evidence, helper, cache=None):
    """Reuse a completed strict inspection bound to unchanged capture bytes."""
    result = json_file(path)
    capture = json_file(evidence / "capture.json")
    qt_checks.verify_evidence(evidence, capture["evidence_sha256"], helper, {"capture.json"})
    comparison = result["comparison"]
    manifest = json_file(evidence / "baseline/pdfs/manifest.json")
    expected = {case["name"]: case for case in manifest["cases"]}
    scenarios = {case["scenario"] for case in manifest["cases"]}
    expected_pairs = {
        (side, scenario) for side in ("baseline", "patched") for scenario in scenarios
    }
    expected_helper = adapter.digest(Path(qt_checks.__file__))
    if cache is not None:
        sdk = helper.sdk_identity(capture["sdk"]["key"])
        restorer = native_cache_admission(cache, sdk)
        adapter.require(
            adapter.digest(path) == cache["immutable_original"]["qt_passed_inspection_sha256"]
            and adapter.digest(evidence / "capture.json")
            == cache["immutable_original"]["qt_capture_sha256"],
            "Cached Qt inspection/capture differs from the pinned original result",
        )
        expected_helper = cache["immutable_original"]["qt_helper_sha256"]
    adapter.require(
        result["schema_version"] == 1
        and result["status"] == "passed"
        and result["qt_only_passed"] is True
        and result["qualified"] is False
        and result["native_freecad_tested"] is False
        and result["promotion_allowed"] is False
        and result["sdk"] == capture["sdk"]
        and result["native_capture_sha256"] == adapter.digest(evidence / "capture.json")
        and result["inspection_helper_sha256"] == expected_helper
        and result["upstream_suite"] == capture["upstream_suite"]
        and result["upstream_suite"]["passed"] is True
        and result["upstream_suite"]["test_cases"] == 10
        and comparison["passed"] is True
        and comparison["failures"] == []
        and comparison["qt_version"] == manifest["qt_version"] == "6.11.1"
        and comparison["raster_dpi"] == manifest["raster_dpi"] == 100
        and manifest["schema_version"] == 2
        and manifest == json_file(evidence / "candidate-pdfs/manifest.json")
        and comparison["require_device_pixel_parity"] is True
        and len(comparison["cases"]) == 66
        and len(manifest["cases"]) == 66
        and len(expected) == 66
        and len(scenarios) == 33
        and {(case["device"], case["scenario"]) for case in manifest["cases"]}
        == {(device, scenario) for device in ("qpdfwriter", "qprinter") for scenario in scenarios}
        and {case["name"] for case in comparison["cases"]} == set(expected)
        and comparison["device_pair_count"] == len(comparison["device_pairs"]) == 66
        and {(pair["side"], pair["scenario"]) for pair in comparison["device_pairs"]}
        == expected_pairs,
        "Require the matching completed strict Qt66/upstream10 inspection",
    )
    warning = "No current point in closepath"
    reproduced = {device: 0 for device in ("qpdfwriter", "qprinter")}
    pixels = {}
    for case in comparison["cases"]:
        contract = expected[case["name"]]
        adapter.require(
            case["device"] == contract["device"]
            and case["scenario"] == contract["scenario"]
            and case["same_coordinates"] is True
            and case["same_normalized_operations"] is True
            and case["same_pixels"] is True
            and case["failures"] == [],
            "Retained case/device/operator comparison differs",
        )
        for side in ("baseline", "patched"):
            actual = case[side]
            closes = contract["baseline_invalid_closes"] if side == "baseline" else 0
            size = actual["size"]
            adapter.require(
                actual["invalid_close_count"] == len(actual["invalid_close_indices"]) == closes
                and all(
                    type(actual[field]) is int and actual[field] >= 0
                    for field in ("operation_count", "coordinate_count")
                )
                and actual["invalid_close_indices"] == sorted(set(actual["invalid_close_indices"]))
                and all(
                    type(index) is int and 0 <= index < actual["operation_count"] - 1
                    for index in actual["invalid_close_indices"]
                )
                and actual["path_errors"] == []
                and actual["poppler_status"] == 0
                and actual["closepath_warnings"]
                == actual["poppler_stderr"].count(warning)
                == closes
                and all(warning in line for line in actual["poppler_stderr"].splitlines())
                and len(size) == 2
                and all(type(value) is int and value > 0 for value in size)
                and re.fullmatch(r"[0-9a-f]{64}", actual["rgba_sha256"])
                and all(
                    type(actual[field]) is int and 0 <= actual[field] <= size[0] * size[1]
                    for field in ("ink_pixels", "red_pixels", "blue_pixels")
                )
                and bool(actual["ink_pixels"]) == contract["expect_ink"]
                and (
                    not contract["expected_color"]
                    or actual[contract["expected_color"] + "_pixels"] > 0
                ),
                "Retained Poppler/operator/visible-control result differs",
            )
            pixels[(side, case["scenario"], case["device"])] = (size, actual["rgba_sha256"])
        baseline, patched = case["baseline"], case["patched"]
        adapter.require(
            baseline["size"] == patched["size"]
            and baseline["rgba_sha256"] == patched["rgba_sha256"]
            and all(
                baseline[field] == patched[field]
                for field in ("ink_pixels", "red_pixels", "blue_pixels")
            )
            and baseline["coordinate_count"] == patched["coordinate_count"]
            and baseline["operation_count"] - patched["operation_count"]
            == 2 * contract["baseline_invalid_closes"],
            "Retained RGBA/coordinate/bare h/f comparison differs",
        )
        if contract["baseline_invalid_closes"]:
            reproduced[case["device"]] += 1
    adapter.require(
        all(reproduced.values())
        and comparison["baseline_reproduced_by_device"] == reproduced
        and comparison["baseline_reproduced_cases"] == sum(reproduced.values())
        and all(
            pair["pair_present"] is True
            and pair["same_pixels"] is True
            and pixels[(pair["side"], pair["scenario"], "qpdfwriter")]
            == pixels[(pair["side"], pair["scenario"], "qprinter")]
            for pair in comparison["device_pairs"]
        ),
        "Retained complete paired-device/reproduction proof differs",
    )
    return result


def validate_qt_capture(evidence, work, helper, cache=None):
    """Require the intact actual native66/Qt10 capture before any FreeCAD build."""
    capture = json_file(evidence / "capture.json")
    baseline = json_file(evidence / "baseline/generation.json")
    build, preparation, recovery = qt_checks.installation_admission(work / "evidence", helper)
    sdk = helper.sdk_identity(capture["sdk"]["key"])
    expected_helper = adapter.digest(Path(qt_checks.__file__))
    if cache is not None:
        restorer = native_cache_admission(cache, sdk)
        adapter.require(
            adapter.digest(evidence / "capture.json")
            == cache["immutable_original"]["qt_capture_sha256"]
            and helper.real_path(evidence) == helper.real_path(Path(cache["qt_evidence"])),
            "Native cache belongs to different historical Qt evidence",
        )
        expected_helper = cache["immutable_original"]["qt_helper_sha256"]
    adapter.require(
        capture.get("status") == "captured"
        and capture.get("qualified") is False
        and capture.get("baseline_unchanged") is True
        and capture.get("candidate_unchanged") is True
        and capture["helper_sha256"] == expected_helper
        and capture["adapter_sha256"] == adapter.digest(Path(adapter.__file__))
        and capture["baseline_helper_sha256"] == adapter.digest(Path(helper.__file__))
        and capture["sdk"] == baseline["sdk"] == build["sdk"] == preparation["sdk"] == sdk
        and build.get("status") in ("built", "installation-revalidated")
        and build.get("qualified") is False
        and build.get("baseline_unchanged") is True
        and build.get("original_baseline_unchanged") is True
        and build.get("non_qt_preserved") is True
        and adapter.digest(work / "evidence/build.json") == capture["build_report_sha256"]
        and capture["source"] == build["source"]
        and build["source"]["patch_sha256"] == adapter.PATCH_SHA
        and build["source"]["original_qpdf_sha256"] == adapter.QPDF_ORIGINAL
        and build["source"]["patched_qpdf_sha256"] == adapter.QPDF_PATCHED,
        "Require the matching authenticated actual Qt candidate capture/build",
    )
    adapter.require(
        capture.get("installation_recovery_sha256")
        == (adapter.digest(work / "evidence/installation-recovery.json") if recovery else None)
        and (
            not recovery
            or adapter.digest(evidence / "candidate-installation-recovery.json")
            == capture["installation_recovery_sha256"]
        ),
        "Native capture/recovered installation binding differs",
    )
    qt_checks.verify_evidence(evidence, capture["evidence_sha256"], helper, {"capture.json"})
    qt_checks.verify_evidence(
        evidence / "baseline", baseline["evidence_sha256"], helper, {"generation.json"}
    )
    host = helper.native_machine()
    adapter.require(
        host == capture["host"] == preparation["host"]
        and host["native_machine"] == helper.MACHINES[sdk["architecture"]]
        and host["python_process_machine"] == 0,
        "Use the same matching native Windows host/Python",
    )
    original, before = adapter.baseline_input(
        Path(preparation["original_baseline"]["evidence"]), sdk, helper
    )
    candidate = helper.real_path(work / "candidate")
    adapter.require(
        helper.real_path(Path(capture["candidate_sdk"])) == candidate, "Candidate SDK root differs"
    )
    candidate_inventory = helper.inventory(candidate)
    adapter.require(
        candidate_inventory
        == json_file(evidence / "candidate-before.json")
        == json_file(work / "evidence/candidate-after.json")
        and helper.inventory(work / "baseline") == before,
        "Retained SDK snapshots changed",
    )
    for side, native, inventory, root in (
        ("baseline", baseline, before, original["root"]),
        ("candidate", capture, candidate_inventory, str(candidate)),
    ):
        directory = evidence / ("baseline/pdfs" if side == "baseline" else "candidate-pdfs")
        manifest = json_file(directory / "manifest.json")
        adapter.require(len(manifest["cases"]) == 66, "Require the complete actual66 matrix")
        helper.verify_runtime(
            json_file(directory / "runtime.json"),
            manifest,
            root,
            inventory,
            sdk["architecture"],
            native["modules"],
        )
    suite = (evidence / "upstream-tests.log").read_text()
    adapter.require(
        capture["upstream_suite"]["passed"] is True
        and capture["upstream_suite"]["test_cases"] == 10
        and adapter.digest(evidence / "upstream-tests.log")
        == capture["upstream_suite"]["log_sha256"]
        and re.search(r"Totals:\s+10 passed,\s+0 failed,\s+0 skipped,\s+0 blacklisted", suite)
        and "QtTest library 6.11.1, Qt 6.11.1" in suite,
        "Require all ten actual upstream Qt tests",
    )
    return capture, sdk, original, before, candidate, candidate_inventory


def native_runtime_receipts(
    provenance, sdk_root, inventory, architecture, binaries, helper, capture=False
):
    """Strict SDK/bin Qt DLLs and exact native core/Python/binding origins."""
    root = PureWindowsPath(sdk_root)
    modules = []
    entries = provenance["qt_libraries"] + provenance["qt_plugins"]
    if capture:
        for entry in entries:
            path = helper.real_path(Path(entry["real_path"]))
            modules.append(
                {
                    "path": str(path),
                    "sha256": adapter.digest(path),
                    "pe_machine": helper.pe_machine(path),
                    "file_version": helper.file_version(path),
                }
            )
    else:
        modules = provenance["sdk_module_receipts"]
    receipts = {PureWindowsPath(entry["path"]): entry for entry in modules}
    adapter.require(len(receipts) == len(modules), "Duplicated Qt module receipts")
    families, qpa = set(), []
    for entry in entries:
        path = PureWindowsPath(entry["real_path"])
        adapter.require(path.is_absolute() and ".." not in path.parts, "Invalid Qt module origin")
        relative = path.relative_to(root).as_posix()
        receipt = receipts.pop(path, None)
        adapter.require(
            relative in inventory["files"]
            and receipt
            and entry["sha256"] == receipt["sha256"] == inventory["files"][relative]["sha256"]
            and receipt["pe_machine"] == helper.MACHINES[architecture]
            and (receipt["file_version"] is None or receipt["file_version"][:3] == [6, 11, 1]),
            "Qt DLL inventory/hash/PE/version proof differs",
        )
        if entry in provenance["qt_libraries"]:
            match = re.fullmatch(r"Qt6(.+)\.dll", path.name, re.IGNORECASE)
            adapter.require(
                match and path.parent == root / "bin", "Qt DLL did not load from selected SDK/bin"
            )
            families.add(match[1].casefold())
        else:
            adapter.require(
                path.is_relative_to(root / "plugins"), "Qt plugin came from another SDK directory"
            )
            if path == root / "plugins/platforms/qwindows.dll":
                qpa.append(path)
    adapter.require(
        not receipts
        and {"core", "gui", "widgets", "printsupport"} <= families
        and len(qpa) == 1
        and provenance["qpa_platform"] == "windows",
        "Incomplete strict Windows Qt/QPA origins",
    )
    core = []
    seen = set()
    sdk_names = {
        "python314.dll": "bin/python314.dll",
        "python3.dll": "bin/python3.dll",
        "pyside6.abi3.dll": "bin/Lib/site-packages/PySide6/pyside6.abi3.dll",
        "shiboken6.abi3.dll": "bin/Lib/site-packages/shiboken6/shiboken6.abi3.dll",
        "pyside6qml.abi3.dll": "bin/Lib/site-packages/PySide6/pyside6qml.abi3.dll",
    }
    for entry in provenance["native_runtime_images"]:
        path = PureWindowsPath(entry["real_path"])
        name = path.name.casefold()
        adapter.require(
            name not in seen and path.is_absolute() and ".." not in path.parts,
            "Duplicated/invalid native core origin",
        )
        seen.add(name)
        if name in CORE_NAMES:
            expected = binaries[name]
            adapter.require(
                path == PureWindowsPath(expected["native_path"])
                and entry["sha256"] == expected["sha256"],
                "Native FreeCAD core/module origin differs",
            )
            receipt = expected
        else:
            relative = sdk_names.get(name)
            adapter.require(
                relative
                and path == root / relative
                and entry["sha256"] == inventory["files"][relative]["sha256"],
                "SDK Python/binding DLL origin differs",
            )
            receipt = {"native_path": str(path), "sha256": entry["sha256"]}
        if capture:
            receipt = {**receipt, "pe_machine": helper.pe_machine(Path(entry["real_path"]))}
        else:
            expected = next(
                item
                for item in provenance["core_module_receipts"]
                if PureWindowsPath(item["native_path"]) == path
            )
            adapter.require(
                expected["sha256"] == receipt["sha256"], "Native core transported hash differs"
            )
            receipt = expected
        adapter.require(
            receipt["pe_machine"] == helper.MACHINES[architecture],
            "Native core/Python PE architecture differs",
        )
        core.append(receipt)
    adapter.require(
        CORE_NAMES | BINDING_NAMES <= seen, "Missing native core/Python/binding origin proofs"
    )
    if not capture:
        adapter.require(
            len(core) == len(provenance["core_module_receipts"]), "Unexpected core receipts"
        )
    return modules, core


def capture(args, helper):
    adapter.require(
        os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("CI") == "true",
        "Native capture requires a disposable GitHub Actions job",
    )
    work = helper.real_path(args.build_work_dir)
    qt_evidence = helper.real_path(args.qt_evidence_dir)
    source = helper.real_path(args.source)
    adapter.require(
        source == helper.real_path(Path(os.environ["GITHUB_WORKSPACE"])),
        "Source must be the disposable reviewed checkout",
    )
    cache_path = getattr(args, "native_cache_report", None)
    cache = None
    if cache_path is not None:
        cache_path = helper.real_path(cache_path)
        cache = json_file(cache_path)
        selected_sdk = helper.sdk_identity(json_file(qt_evidence / "capture.json")["sdk"]["key"])
        restorer = native_cache_admission(cache, selected_sdk)
        restorer.validate_cache(cache_path, helper)
        adapter.require(
            source == helper.real_path(Path(cache["immutable_original"]["freecad_source"]["root"])),
            "Cached FreeCAD source must resume at its original physical path",
        )
    qt_capture, sdk, original, before, candidate, candidate_before = validate_qt_capture(
        qt_evidence, work, helper, cache=cache
    )
    passed_report = getattr(args, "qt_only_report", None)
    if passed_report is not None:
        passed_report = helper.real_path(passed_report)
        passed_qt_report(passed_report, qt_evidence, helper, cache=cache)
    adapter.require(
        cache is None or passed_report is not None, "Cached Qt proof requires its passed inspection"
    )
    baseline = helper.real_path(Path(original["root"]))
    destination = helper.real_path(args.work_dir)
    adapter.require(
        destination.is_relative_to(helper.real_path(Path(os.environ["RUNNER_TEMP"]))),
        "Native work must be under RUNNER_TEMP",
    )
    for protected in (work, qt_evidence, source, baseline):
        adapter.separate_path(destination, protected)
    adapter.require(
        not any(Path(sys.executable).resolve().is_relative_to(root) for root in (work, baseline)),
        "Use separate tool Python outside SDKs",
    )
    if cache is None:
        destination = helper.fresh_work(destination)
    else:
        adapter.require(
            destination == helper.real_path(Path(cache["original_native_root"]))
            and {path.name for path in destination.iterdir()}
            == ({"b", "module"} if cache["status"] == "native-completed-restored" else {"b"}),
            "Cached native root must contain only the authenticated unfinished build",
        )
    completed = cache is not None and cache["status"] == "native-completed-restored"
    evidence = destination / "evidence"
    evidence.mkdir()
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write(f"native_evidence_dir={evidence}\n")
    report = {
        "schema_version": 1,
        "status": "failed",
        "qualified": False,
        "promotion_allowed": False,
        "sdk": sdk,
        "host": qt_capture["host"],
        "helper_sha256": adapter.digest(Path(__file__)),
        "sources": source_receipts(),
        "work_dir": str(destination),
        "baseline_sdk": str(baseline),
        "candidate_sdk": str(candidate),
        "baseline_unchanged": False,
        "candidate_unchanged": False,
        "qt_capture_sha256": adapter.digest(qt_evidence / "capture.json"),
    }
    saved_environment = os.environ.copy()
    try:
        environment, compiler = helper.compiler_environment(
            destination, evidence, sdk["architecture"]
        )
        adapter.require(
            compiler["compiler_sha256"] == qt_capture["compiler"]["compiler_sha256"]
            and compiler["tools_version"] == qt_capture["compiler"]["tools_version"],
            "Native FreeCAD compiler differs from Qt capture",
        )
        environment = {
            **adapter.native_environment(environment, compiler, helper),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
        }
        tools = adapter.tool_receipts(environment, (baseline, candidate), helper)
        report["compiler"], report["tools"] = compiler, tools
        admission_path = getattr(args, "host_tools_report", None)
        if admission_path is None:
            adapter.require(tools == qt_capture["tools"], "Unadmitted native build tools changed")
        else:
            admission_path = helper.real_path(admission_path)
            admission, profile = qt_checks.validate_host_tools(
                admission_path, sdk, tools, compiler, helper.native_machine(), helper, physical=True
            )
            shutil.copy2(admission_path, evidence / "host-tools.json")
            report["host_tools_sha256"] = adapter.digest(evidence / "host-tools.json")
            report["host_tools_profile"] = profile
            report["producer"] = admission["producer"]
        if cache is not None:
            shutil.copy2(cache_path, evidence / "native-cache-recovery.json")
            report["native_cache_recovery_sha256"] = adapter.digest(cache_path)
            report["native_build_reused"] = True
            report["qt_inspection_reused"] = True
        git = tools["git"]["path"]
        adapter.require(
            not adapter.command(
                [git, "status", "--porcelain", "--untracked-files=no"],
                evidence,
                "source-before",
                source,
                environment,
            ),
            "Require clean tracked FreeCAD source",
        )
        commit = adapter.command(
            [git, "rev-parse", "HEAD"], evidence, "source-head", source, environment
        )
        adapter.require(
            commit == os.environ["GITHUB_SHA"],
            "FreeCAD source differs from the dispatched revision",
        )
        adapter.command(
            [git, "submodule", "update", "--init", "--recursive"],
            evidence,
            "source-submodules",
            source,
            environment,
        )
        submodules = adapter.command(
            [git, "submodule", "status", "--recursive"],
            evidence,
            "source-gitlinks",
            source,
            environment,
        )
        adapter.require(
            all(line.startswith(" ") for line in submodules.splitlines()),
            "Dirty/uninitialized FreeCAD Git links",
        )
        report["freecad_source"] = {"root": str(source), "commit": commit, "submodules": submodules}
        if completed:
            preflight = helper.real_path(
                Path(os.environ["RUNNER_TEMP"]) / "libpack-readonly-preflight"
            )
            retained_preflight = evidence / "sdk-readonly-preflight"
            shutil.copytree(
                preflight / "evidence", retained_preflight / "evidence", copy_function=shutil.copy2
            )
            shutil.copy2(preflight / "preflight.json", retained_preflight / "preflight.json")
            validate_readonly_preflight(retained_preflight, preflight / "input")
            adapter.require(
                submodules == cache["immutable_original"]["freecad_source"]["submodules"],
                "Completed native build Git links changed",
            )
            report["completed_build_source"] = restorer.source_equivalence(
                source, evidence, environment, cache["immutable_original"]
            )
            report["freecad_recompiled"] = report["bypass_recompiled"] = False
        shutil.copytree(qt_evidence, evidence / "qt-capture", copy_function=shutil.copy2)
        if passed_report is not None:
            shutil.copy2(passed_report, evidence / "qt-passed-inspection.json")
            report["qt_passed_inspection_sha256"] = adapter.digest(passed_report)
        for name in NATIVE_SOURCES:
            shutil.copy2(FIXTURE / name, evidence / name)
        build = destination / "b"
        runtime_env = {
            **environment,
            "PATH": os.pathsep.join(
                (
                    str(baseline / "bin"),
                    str(baseline / "bin/Lib/site-packages/PySide6"),
                    str(baseline / "bin/Lib/site-packages/shiboken6"),
                    str(baseline / "lib"),
                    environment["PATH"],
                )
            ),
        }
        if completed:
            configure = cache["immutable_original"]["configure_command"]
        else:
            configure = [
                tools["cmake"]["path"],
                "-S",
                str(source),
                "-B",
                str(build),
                "--preset",
                "release",
                "-G",
                "Ninja",
                "-DCMAKE_C_COMPILER=" + compiler["compiler"],
                "-DCMAKE_CXX_COMPILER=" + compiler["compiler"],
                "-DFREECAD_LIBPACK_USE=ON",
                "-DFREECAD_LIBPACK_DIR=" + str(baseline),
                "-DBUILD_WITH_CONDA=OFF",
                "-DBUILD_GUI=ON",
                "-DBUILD_TEST=ON",
                "-DENABLE_DEVELOPER_TESTS=ON",
                "-DFREECAD_USE_PCH=OFF",
                "-DFREECAD_RELEASE_PDB=OFF",
                "-DCMAKE_INSTALL_PREFIX=" + str(destination / "unused-staging"),
                *("-D" + option + "=OFF" for option in COPY_OPTIONS),
            ]
            adapter.command(configure, evidence, "freecad-configure", source, runtime_env)
        values = cache_values(build / "CMakeCache.txt")
        adapter.require(
            all(values.get(option) == "OFF" for option in COPY_OPTIONS)
            and values.get("FREECAD_LIBPACK_USE") == "ON"
            and values.get("BUILD_WITH_CONDA") == "OFF"
            and values.get("CMAKE_GENERATOR") == "Ninja"
            and values.get("CMAKE_BUILD_TYPE") == "Release",
            "Configured FreeCAD copy/build mode differs",
        )
        report["python"] = configured_python(values, baseline, before)
        for family in ("Qt6", "Qt6Core", "Qt6Gui", "Qt6Widgets", "Qt6PrintSupport"):
            adapter.require(
                PureWindowsPath(values[family + "_DIR"]).is_relative_to(
                    PureWindowsPath(baseline / "lib/cmake")
                ),
                "FreeCAD configured Qt outside baseline SDK",
            )
        report["configure_command"] = configure
        report["build_command"] = [
            tools["cmake"]["path"],
            "--build",
            str(build),
            "--target",
            *TARGETS,
            "--parallel",
            "2",
        ]
        if completed:
            adapter.require(
                report["build_command"] == cache["immutable_original"]["build_command"],
                "Completed native target selection changed",
            )
        else:
            adapter.command(report["build_command"], evidence, "freecad-build", source, runtime_env)
        shutil.copy2(build / "CMakeCache.txt", evidence / "FreeCAD-CMakeCache.txt")
        adapter.require(
            not list(build.rglob("Qt6*.dll")) and not (build / "bin/qt.conf").exists(),
            "Build-local Qt DLLs/config mask SDK origins",
        )
        native = native_helper()
        bypass = destination / "module"
        if not completed:
            adapter.command(
                [
                    sys.executable,
                    "-B",
                    str(FIXTURE / "build-native-bypass.py"),
                    "--ci-checkout",
                    "--source",
                    str(source),
                    "--build",
                    str(build),
                    "--output",
                    str(bypass),
                    "--cmake",
                    tools["cmake"]["path"],
                    "--parallel",
                    "2",
                ],
                evidence,
                "freecad-bypass",
                source,
                runtime_env,
            )
        module = helper.real_path(Path(json_file(bypass / "bypass-provenance.json")["module"]))
        binaries = {}
        retained = evidence / "native-binaries"
        retained.mkdir()
        for name in CORE_NAMES:
            matches = (
                [module]
                if name == "techdrawgui.pyd"
                else [path for path in build.rglob("*") if path.name.casefold() == name]
            )
            adapter.require(len(matches) == 1, "Ambiguous/missing native FreeCAD binary: " + name)
            path = helper.real_path(matches[0])
            adapter.require(
                helper.pe_machine(path) == helper.MACHINES[sdk["architecture"]],
                "Native FreeCAD PE architecture differs",
            )
            shutil.copy2(path, retained / path.name)
            binaries[name] = {
                "native_path": str(path),
                "sha256": adapter.digest(path),
                "pe_machine": helper.pe_machine(path),
                "retained": "native-binaries/" + path.name,
            }
        report["binaries"] = binaries
        originals = evidence / "protected-sources"
        originals.mkdir()
        bypass_report = json_file(bypass / "bypass-provenance.json")
        for original_path, sha in bypass_report["protected_original_sha256"].items():
            original_path = helper.real_path(Path(original_path))
            adapter.require(adapter.digest(original_path) == sha, "Protected original changed")
            shutil.copy2(original_path, originals / original_path.name)
        shutil.copytree(bypass, evidence / "native-module", copy_function=shutil.copy2)
        pair = evidence / "pair"
        os.environ.clear()
        os.environ.update(environment)
        launch = SimpleNamespace(
            freecad=Path(binaries["freecad.exe"]["native_path"]),
            bypass_module=module,
            output=pair,
            python_runtime=None,
            expected_qt_version="6.11.1",
        )
        protection = (
            sdk_protection.protect((baseline, candidate), evidence / "sdk-readonly", helper)
            if completed
            else nullcontext(None)
        )
        with protection as policy:
            for side, root in (("baseline", baseline), ("patched", candidate)):
                for key, value in {
                    "qt_prefix": root,
                    "qt_lib": root / "bin",
                    "plugin_dir": root / "plugins",
                    "python_runtime": root / "bin",
                    "runtime_dll_dirs": (
                        root / "lib",
                        root / "bin/Lib/site-packages/PySide6",
                        root / "bin/Lib/site-packages/shiboken6",
                    ),
                }.items():
                    setattr(launch, side + "_" + key, value)
                directory = native.launch(launch, side)
                if policy is not None:
                    policy.snapshot(side + "-finished")
                provenance = json_file(directory / "native-provenance.json")
                native.check_stock_records(
                    provenance,
                    json_file(directory / "manifest.json"),
                    directory,
                    "6.11.1",
                    side=side,
                    require_prospective=True,
                )
                modules, core = native_runtime_receipts(
                    provenance,
                    root,
                    before if side == "baseline" else candidate_before,
                    sdk["architecture"],
                    binaries,
                    helper,
                    capture=True,
                )
                provenance["sdk_module_receipts"], provenance["core_module_receipts"] = (
                    modules,
                    core,
                )
                adapter.write_json(directory / "native-provenance.json", provenance)
        if completed:
            protection_path = evidence / "sdk-readonly/sdk-readonly.json"
            sdk_protection.validate_evidence(
                protection_path,
                roots=[str(baseline), str(candidate)],
                inventories=[before, candidate_before],
            )
            report["sdk_runtime_protection_sha256"] = adapter.digest(protection_path)
            report["sdk_runtime_protection_helper_sha256"] = adapter.digest(
                Path(sdk_protection.__file__)
            )
        native.check_provenance(pair / "baseline", pair / "patched", expected_qt_version="6.11.1")
        adapter.require(
            all(
                adapter.digest(Path(entry["native_path"])) == entry["sha256"]
                for entry in binaries.values()
            ),
            "FreeCAD binaries changed during capture",
        )
        adapter.require(
            not adapter.command(
                [git, "status", "--porcelain", "--untracked-files=no"],
                evidence,
                "source-after",
                source,
                environment,
            ),
            "Tracked FreeCAD source changed",
        )
        report["status"] = "captured"
    except BaseException as error:
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        os.environ.clear()
        os.environ.update(saved_environment)
        baseline_after = helper.inventory(baseline)
        clone_after = helper.inventory(work / "baseline")
        candidate_after = helper.inventory(candidate)
        for name, actual, expected in (
            ("baseline", baseline_after, before),
            ("baseline-clone", clone_after, before),
            ("candidate", candidate_after, candidate_before),
        ):
            adapter.write_json(evidence / (name + "-after.json"), actual)
            adapter.write_json(
                evidence / (name + "-delta.json"), sdk_protection.inventory_delta(expected, actual)
            )
        report["baseline_unchanged"] = baseline_after == before and clone_after == before
        report["candidate_unchanged"] = candidate_after == candidate_before
        if not report["baseline_unchanged"] or not report["candidate_unchanged"]:
            report["status"] = "failed"
        report["evidence_sha256"] = qt_checks.evidence_files(
            evidence, helper, {"native-capture.json"}
        )
        adapter.write_json(evidence / "native-capture.json", report)
    adapter.require(report["status"] == "captured", "Native capture/preservation failed")
    return report


def inspect(args, helper):
    evidence = helper.real_path(args.evidence_dir)
    capture_report = json_file(evidence / "native-capture.json")
    destination = helper.real_path(args.report)
    renders = helper.real_path(destination.with_suffix(".renders"))
    qt_report = helper.real_path(destination.with_suffix(".qt.json"))
    qt_renders = qt_report.with_suffix(".renders")
    protected = [
        capture_report["baseline_sdk"],
        capture_report["candidate_sdk"],
        capture_report["work_dir"],
        capture_report.get("freecad_source", {}).get("root", ""),
    ]
    for output in (destination, renders, qt_report, qt_renders):
        adapter.require(
            output.parent.is_dir() and not output.exists(),
            "Native inspection outputs must be fresh",
        )
        for root in protected:
            if root:
                helper.check_output_location(output, evidence, root)
    report = {
        "schema_version": 1,
        "status": "failed",
        "qualified": False,
        "promotion_allowed": False,
        "native_freecad_passed": False,
        "scope": "Selected native Windows LibPack SDK/source/stock TechDraw pair only; receipt-backed DLL proof, no SDK DLL bytes rehosted on the inspection host",
    }
    try:
        adapter.require(
            capture_report["status"] == "captured"
            and capture_report["qualified"] is False
            and capture_report["baseline_unchanged"] is True
            and capture_report["candidate_unchanged"] is True
            and capture_report["helper_sha256"] == adapter.digest(Path(__file__))
            and capture_report["sources"] == source_receipts(),
            "Native capture/source/preservation proof differs",
        )
        qt_checks.verify_evidence(
            evidence, capture_report["evidence_sha256"], helper, {"native-capture.json"}
        )
        for name, sha in capture_report["sources"].items():
            adapter.require(
                adapter.digest(evidence / name) == sha, "Retained native harness differs"
            )
        qt_evidence = evidence / "qt-capture"
        adapter.require(
            adapter.digest(qt_evidence / "capture.json") == capture_report["qt_capture_sha256"],
            "Native pair references a different Qt candidate capture",
        )
        cache = None
        if capture_report.get("qt_passed_inspection_sha256"):
            retained_report = evidence / "qt-passed-inspection.json"
            adapter.require(
                adapter.digest(retained_report) == capture_report["qt_passed_inspection_sha256"],
                "Retained strict Qt inspection changed",
            )
            if capture_report.get("native_cache_recovery_sha256"):
                cache_path = evidence / "native-cache-recovery.json"
                adapter.require(
                    adapter.digest(cache_path) == capture_report["native_cache_recovery_sha256"],
                    "Retained native-cache admission changed",
                )
                cache = json_file(cache_path)
                native_cache_admission(cache, helper.sdk_identity(capture_report["sdk"]["key"]))
                adapter.require(
                    capture_report["native_build_reused"] is True
                    and capture_report["qt_inspection_reused"] is True
                    and PureWindowsPath(capture_report["work_dir"])
                    == PureWindowsPath(cache["original_native_root"])
                    and PureWindowsPath(capture_report["freecad_source"]["root"])
                    == PureWindowsPath(cache["immutable_original"]["freecad_source"]["root"]),
                    "Cached native source/root reuse binding differs",
                )
            qt_result = passed_qt_report(retained_report, qt_evidence, helper, cache=cache)
            shutil.copy2(retained_report, qt_report)
        else:
            qt_result = qt_checks.inspect(
                SimpleNamespace(evidence_dir=qt_evidence, report=qt_report), helper
            )
        qt_capture = json_file(qt_evidence / "capture.json")
        adapter.require(
            qt_result["qt_only_passed"] is True
            and capture_report["sdk"] == qt_capture["sdk"]
            and capture_report["host"] == qt_capture["host"]
            and capture_report["compiler"]["compiler_sha256"]
            == qt_capture["compiler"]["compiler_sha256"],
            "Matching actual Qt-only qualification must pass first",
        )
        qt_baseline = json_file(qt_evidence / "baseline/generation.json")
        adapter.require(
            PureWindowsPath(capture_report["baseline_sdk"])
            == PureWindowsPath(qt_baseline["sdk_root"])
            and PureWindowsPath(capture_report["candidate_sdk"])
            == PureWindowsPath(qt_capture["candidate_sdk"])
            and capture_report["compiler"]["tools_version"]
            == qt_capture["compiler"]["tools_version"],
            "Native and Qt-only selected SDK/compiler identities differ",
        )
        sdk = helper.sdk_identity(capture_report["sdk"]["key"])
        if capture_report.get("host_tools_sha256"):
            admission_path = evidence / "host-tools.json"
            adapter.require(
                adapter.digest(admission_path) == capture_report["host_tools_sha256"],
                "Retained native host-tool admission changed",
            )
            admission, profile = qt_checks.validate_host_tools(
                admission_path,
                sdk,
                capture_report["tools"],
                capture_report["compiler"],
                capture_report["host"],
                helper,
            )
            adapter.require(
                capture_report["host_tools_profile"] == profile
                and capture_report["producer"] == admission["producer"]
                and capture_report["freecad_source"]["commit"] == admission["producer"]["head_sha"],
                "Native host-tool profile/source producer differs",
            )
        else:
            adapter.require(
                capture_report["tools"] == qt_capture["tools"], "Unadmitted native tools changed"
            )
        inventories = {
            "baseline": json_file(qt_evidence / "baseline/sdk-before.json"),
            "patched": json_file(qt_evidence / "candidate-before.json"),
        }
        if cache is not None and cache["status"] == "native-completed-restored":
            original = cache["immutable_original"]
            restorer = native_cache_admission(cache, sdk)
            adapter.require(
                capture_report["completed_build_source"]
                == {
                    "binary_source_commit": original["freecad_source"]["commit"],
                    "qualification_source_commit": capture_report["freecad_source"]["commit"],
                    "selected_paths": list(restorer.SOURCE_PATHS),
                    "compiled_tracked_inputs_equal": True,
                    "source_timestamps_modified": False,
                    "freecad_recompiled": False,
                    "bypass_recompiled": False,
                }
                and capture_report["freecad_recompiled"]
                is capture_report["bypass_recompiled"]
                is False
                and capture_report["binaries"] == original["binaries"]
                and capture_report["freecad_source"]["submodules"]
                == original["freecad_source"]["submodules"]
                and not (evidence / "completed-source-diff.log").read_text(encoding="utf-8")
                and capture_report["sdk_runtime_protection_helper_sha256"]
                == adapter.digest(Path(sdk_protection.__file__)),
                "Completed native source/binary/protection binding differs",
            )
            protection_path = evidence / "sdk-readonly/sdk-readonly.json"
            adapter.require(
                adapter.digest(protection_path) == capture_report["sdk_runtime_protection_sha256"],
                "Runtime SDK protection receipt differs",
            )
            sdk_protection.validate_evidence(
                protection_path,
                roots=[capture_report["baseline_sdk"], capture_report["candidate_sdk"]],
                inventories=[inventories["baseline"], inventories["patched"]],
            )
            validate_readonly_preflight(
                evidence / "sdk-readonly-preflight",
                PureWindowsPath(capture_report["work_dir"]).parent
                / "libpack-readonly-preflight/input",
            )
        configured_python(
            cache_values(evidence / "FreeCAD-CMakeCache.txt"),
            capture_report["baseline_sdk"],
            inventories["baseline"],
        )
        binaries = capture_report["binaries"]
        adapter.require(set(binaries) == CORE_NAMES, "Incomplete native FreeCAD binary receipts")
        for name, entry in binaries.items():
            path = evidence / adapter.safe_relative(entry["retained"])
            adapter.require(
                adapter.digest(path) == entry["sha256"]
                and helper.pe_machine(path)
                == entry["pe_machine"]
                == helper.MACHINES[sdk["architecture"]],
                "Retained FreeCAD core byte/PE proof differs",
            )
        native = native_helper()
        gui_hashes = []
        modules = []
        prospective_inputs = []
        for side, root in (
            ("baseline", capture_report["baseline_sdk"]),
            ("patched", capture_report["candidate_sdk"]),
        ):
            directory = evidence / "pair" / side
            provenance = json_file(directory / "native-provenance.json")
            manifest = json_file(directory / "manifest.json")
            adapter.require(
                manifest["schema_version"] == 2 and manifest["raster_dpi"] == 150,
                "Native manifest format/DPI differs",
            )
            prospective_inputs.append(
                native.check_stock_records(
                    provenance,
                    manifest,
                    PureWindowsPath(
                        json_file(directory / "launch.json")["environment_overrides"][
                            "TD_NATIVE_OUTPUT"
                        ]
                    ),
                    "6.11.1",
                    PureWindowsPath,
                    side,
                    require_prospective=True,
                )
            )
            launch_record = json_file(directory / "launch.json")
            macro_source = provenance["macro_source"]
            adapter.require(
                len(prospective_inputs[-1]) == 24
                and macro_source["sha256"]
                == capture_report["sources"]["native-freecad.FCMacro"]
                == launch_record["environment_overrides"]["TD_NATIVE_MACRO_SHA256"]
                and PureWindowsPath(macro_source["path"])
                == PureWindowsPath(launch_record["environment_overrides"]["TD_NATIVE_MACRO_PATH"])
                == PureWindowsPath(launch_record["command"][-1]),
                "Native prospective input/source launch binding differs",
            )
            adapter.require(
                PureWindowsPath(provenance["expected_qt_prefix"]) == PureWindowsPath(root)
                and PureWindowsPath(provenance["expected_qt_lib"]) == PureWindowsPath(root) / "bin"
                and PureWindowsPath(provenance["expected_plugin_dir"])
                == PureWindowsPath(root) / "plugins",
                "Recorded native selected SDK paths differ",
            )
            native_runtime_receipts(
                provenance, root, inventories[side], sdk["architecture"], binaries, helper
            )
            adapter.require(
                provenance["module_sha256"]
                == binaries["techdrawgui.pyd"]["sha256"]
                == provenance["bypass_provenance"]["module_sha256"],
                "Different mitigation bypass was loaded",
            )
            bypass = json_file(evidence / "native-module/bypass-provenance.json")
            adapter.require(
                bypass == provenance["bypass_provenance"]
                and bypass["mode"] == "ci-checkout"
                and bypass["original_build_outputs_unchanged"] is False,
                "Native bypass provenance differs",
            )
            for original_path, sha in bypass["protected_original_sha256"].items():
                name = PureWindowsPath(original_path).name
                adapter.require(
                    name in ("QGCustomPath.cpp", "QGCustomRect.cpp"), "Unexpected protected source"
                )
                adapter.require(
                    adapter.digest(evidence / "protected-sources" / name) == sha,
                    "Protected source transport differs",
                )
            for entry in bypass["sources"]:
                retained = evidence / "native-module" / PureWindowsPath(entry["copy"]).name
                adapter.require(
                    adapter.digest(retained) == entry["copy_sha256"],
                    "Retained bypass source differs",
                )
            gui_hashes.append(
                next(
                    entry["sha256"]
                    for entry in provenance["qt_libraries"]
                    if PureWindowsPath(entry["real_path"]).name.casefold() == "qt6gui.dll"
                )
            )
            modules.append(provenance)
        adapter.require(
            gui_hashes[0] != gui_hashes[1], "Native pair did not load different actual QtGui bytes"
        )
        adapter.require(
            prospective_inputs[0] == prospective_inputs[1],
            "Prospective native scene inputs differ between runtimes",
        )
        renders.mkdir()
        for side in ("baseline", "patched"):
            shutil.copytree(evidence / "pair" / side, renders / side, copy_function=shutil.copy2)
        pdftoppm = shutil.which("pdftoppm")
        adapter.require(pdftoppm, "Poppler pdftoppm is required")
        sys.path.insert(0, str(FIXTURE))
        try:
            result = native.compare(
                renders / "baseline",
                renders / "patched",
                pdftoppm,
                require_device_pixel_parity=False,
            )
            adapter.require(
                len(result["cases"]) == 24
                and set(result["baseline_reproduced_by_device"]) == {"qpdfwriter", "qprinter"}
                and result["passed"],
                "All24 per-device native PDF gates must pass",
            )
            for side in ("baseline", "patched"):
                for device in ("qpdfwriter", "qprinter"):
                    native.check_visible_controls(
                        renders / side, result["raster_dpi"], pdftoppm, device
                    )
        finally:
            sys.path.pop(0)
        report.update(
            {
                "status": "passed",
                "native_freecad_passed": True,
                "sdk": sdk,
                "native_capture_sha256": adapter.digest(evidence / "native-capture.json"),
                "qt_only_report_sha256": adapter.digest(qt_report),
                "comparison": result,
                "stock_device_rounding": "Stock QPrinter uses rounded QPageLayout pixels; cross-device pixel parity is informational. Each device retains exact baseline/patched operators and RGBA.",
                "native_runtime_provenance": modules,
            }
        )
    except (OSError, ValueError, KeyError) as error:
        report["error"] = str(error)
    adapter.write_json(destination, report)
    adapter.require(
        report["native_freecad_passed"], report.get("error", "Native PDF comparison failed")
    )
    return report


def main():
    sys.dont_write_bytecode = True
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    producer = commands.add_parser("capture")
    for name in ("build-work-dir", "qt-evidence-dir", "source", "work-dir"):
        producer.add_argument("--" + name, type=Path, required=True)
    producer.add_argument("--qt-only-report", type=Path)
    producer.add_argument("--host-tools-report", type=Path)
    producer.add_argument("--native-cache-report", type=Path)
    inspector = commands.add_parser("inspect")
    inspector.add_argument("--evidence-dir", type=Path, required=True)
    inspector.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = (
            capture(args, adapter.baseline_helper())
            if args.action == "capture"
            else inspect(args, adapter.baseline_helper())
        )
        print(json.dumps({"status": result["status"], "qualified": False}))
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
