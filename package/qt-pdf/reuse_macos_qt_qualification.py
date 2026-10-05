# SPDX-License-Identifier: LGPL-2.1-or-later
"""Reuse the authenticated passed macOS Intel Qt stage before fresh native capture.

This finite adapter reads existing Qt PDF/PNG and upstream-test evidence; it
never runs the Qt fixtures, tests, FreeCAD, a renderer, compiler or installer.
The original native failure remains failed. Available native module digests come
from authenticated managed inventories, not from a nonexistent old native map.
"""

import argparse
import ctypes
import errno
import json
import os
from pathlib import Path
import platform
import re
import struct
import subprocess
import sys
import zipfile

import reuse_linux_qt_qualification as common

installer = common.installer
qualifier = common.qualifier
require = common.require
digest = common.digest
read_json = common.read_json
physical = common.physical
fresh_work = common.fresh_work
safe_name = common.safe_name
zip_inventory = common.zip_inventory
check_tree = common.check_tree
api = common.api
current_corpus = common.current_corpus
module_map = common.module_map
retained_pdf = common.retained_pdf
write_json = common.write_json
REPOSITORY = common.REPOSITORY
PACKAGE_RUN = common.PACKAGE_RUN
PACKAGE_HEAD = common.PACKAGE_HEAD
SOURCE_SHA = common.SOURCE_SHA
SOURCE_MD5 = common.SOURCE_MD5
FIXTURE_SOURCES = common.FIXTURE_SOURCES
PASSED_STEP = common.PASSED_STEP
FAILED_STEP = common.FAILED_STEP
DEVICE_ROOT = common.DEVICE_ROOT
INSTALL_ROOT = common.INSTALL_ROOT
HEAD = "fad5154281bede3144c71820933e5b05812161fb"
TARGETS = {
    "osx-64": {
        "run": 37248191467,
        "job": 111570214009,
        "artifact": 11323656361,
        "size": 13993780,
        "zip_sha256": "5236af18b437128de7b15b43dbdecb3488685938b8c7008a39f9bf1087bfb5d6",
        "package": "qt6-main-6.11.2-pl5321h7c35b53_1.conda",
        "package_sha256": "a8bb9b5c836e8e0bea9359158e5eac59f35755bb4fde39d987f2530549c45631",
        "build_json_sha256": "85469bfacd14cc6251a70e988084e750939a168571deea2a37cdebbd77ad19c6",
    }
}
REQUIRED_LIBRARIES = {
    "lib/libQt6" + family + ".6.11.2.dylib" for family in ("Core", "Gui", "Widgets", "PrintSupport")
}
COCOA = "lib/qt6/plugins/platforms/libqcocoa.dylib"
SDK = {
    "path": "/Applications/Xcode_16.4.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk",
    "metadata_file": "SDKSettings.json",
    "metadata_sha256": "58a133735f0a55a624a1703067059f6e78925e51725ec6e1f966072e142c9c42",
}


def translated_process():
    # Apple's native Rosetta check; ENOENT means the flag is unavailable on Intel.
    # https://developer.apple.com/documentation/apple-silicon/about-the-rosetta-translation-environment
    value, size = ctypes.c_int(), ctypes.c_size_t(ctypes.sizeof(ctypes.c_int))
    function = ctypes.CDLL(None, use_errno=True).sysctlbyname
    function.argtypes = [
        ctypes.c_char_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_size_t),
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    function.restype = ctypes.c_int
    status = function(b"sysctl.proc_translated", ctypes.byref(value), ctypes.byref(size), None, 0)
    if status:
        require(ctypes.get_errno() == errno.ENOENT, "Cannot verify native Intel execution")
        return False
    require(
        size.value == ctypes.sizeof(value) and value.value in (0, 1), "Invalid translation flag"
    )
    return bool(value.value)


def native_host(target):
    require(
        target == "osx-64" and sys.platform == "darwin" and platform.machine() == "x86_64",
        "Require the native macOS Intel host",
    )
    require(not translated_process(), "Rosetta execution is not native Intel qualification")


def helper_sources():
    return {
        path.name: digest(path)
        for path in (
            Path(__file__).resolve(),
            Path(common.__file__).resolve(),
            Path(installer.__file__).resolve(),
            Path(qualifier.__file__).resolve(),
        )
    }


def macho_x86_64(path, file_types=(2,)):
    """Inspect one thin Mach-O header and its bounded load-command table."""
    path = physical(path)
    require(path.is_file(), "Mach-O input must be a physical regular file")
    with path.open("rb") as stream:
        header = stream.read(32)
        require(len(header) == 32, "Short Mach-O header")
        magic, cpu, subtype, kind, count, size, flags, reserved = struct.unpack("<8I", header)
        require(
            magic == 0xFEEDFACF
            and cpu == 0x01000007
            and kind in file_types
            and 0 < count <= 4096
            and count * 8 <= size <= 16 * 1024**2
            and 32 + size <= path.stat().st_size,
            "Require a bounded thin x86_64 Mach-O",
        )
        commands = stream.read(size)
    offset = 0
    for _ in range(count):
        require(offset + 8 <= size, "Short Mach-O load command")
        command, length = struct.unpack_from("<II", commands, offset)
        require(
            length >= 8 and length % 8 == 0 and offset + length <= size,
            "Invalid Mach-O load command",
        )
        offset += length
    require(offset == size, "Mach-O load-command size differs")
    return {"architecture": "x86_64", "cpu_type": cpu, "file_type": kind, "sha256": digest(path)}


def available_maps(root, installation):
    """Select finite canonical regular Qt paths; never use symlink-text digests."""
    baseline_path = root / INSTALL_ROOT / "baseline-before.json"
    metadata_dir = root / INSTALL_ROOT / "candidate-conda-meta"
    metadata_files = list(metadata_dir.glob("qt6-main-6.11.2-*.json"))
    require(len(metadata_files) == 1, "Require one retained installed Qt metadata file")
    metadata = read_json(metadata_files[0])
    expected = TARGETS["osx-64"]
    require(
        installer.identity({"qt6-main": metadata})["qt6-main"]
        == installation["candidate_packages"]["qt6-main"]
        and metadata["sha256"] == expected["package_sha256"]
        and metadata["subdir"] == "osx-64",
        "Retained candidate Qt metadata identity differs",
    )
    baseline = read_json(baseline_path)["qt_files"]
    candidate, metadata_hashes = {}, {}
    for path in sorted(metadata_dir.glob("*.json")):
        record = read_json(path)
        if not record["name"].startswith(("qt", "pyside", "shiboken")):
            continue
        require(
            installer.identity({record["name"]: record})[record["name"]]
            == installation["candidate_packages"][record["name"]],
            "Retained Qt-related installed package identity differs",
        )
        metadata_hashes[path.name] = digest(path)
        for entry in record["paths_data"]["paths"]:
            name = entry["_path"]
            safe_name(name)
            require(name not in candidate, "Duplicate candidate installed path")
            candidate[name] = entry
    maps = {}
    for side, entries in (("baseline", baseline), ("patched", candidate)):
        selected = {"qt_libraries": [], "qt_plugins": []}
        for name, entry in entries.items():
            safe_name(name)
            library = bool(re.fullmatch(r"lib/libQt6[A-Za-z0-9_]+\.6\.11\.2\.dylib", name))
            plugin = bool(re.fullmatch(r"lib/qt6/plugins/[A-Za-z0-9_/-]+\.dylib", name))
            if not library and not plugin:
                continue
            regular = (
                entry["symlink"] is None if side == "baseline" else entry["path_type"] == "hardlink"
            )
            if not regular:
                continue
            sha = entry["sha256"] if side == "baseline" else entry["sha256_in_prefix"]
            require(
                isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha),
                "Missing installed module digest",
            )
            selected["qt_libraries" if library else "qt_plugins"].append(
                {"relative_path": name, "sha256": sha}
            )
        for kind in selected:
            selected[kind].sort(key=lambda entry: entry["relative_path"])
        require(
            REQUIRED_LIBRARIES.issubset({e["relative_path"] for e in selected["qt_libraries"]})
            and sum(e["relative_path"] == COCOA for e in selected["qt_plugins"]) == 1,
            "Incomplete managed Cocoa runtime inventory",
        )
        maps[side] = {"qpa_platform": "cocoa", **selected}
    return maps, {
        "baseline_snapshot_sha256": digest(baseline_path),
        "candidate_installed_metadata_sha256": digest(metadata_files[0]),
        "candidate_qt_related_metadata_sha256": metadata_hashes,
        "basis": "authenticated retained baseline byte inventory and candidate sha256_in_prefix for canonical regular files; not an old native loaded map",
    }


def require_observed(entries, available, prefix, path_key):
    observed = module_map(entries, prefix, path_key)
    expected = {entry["relative_path"]: entry["sha256"] for entry in available}
    require(
        all(expected.get(entry["relative_path"]) == entry["sha256"] for entry in observed),
        "Observed Qt module is outside or differs from the authenticated managed inventory",
    )
    return observed


def bind_modules(entries, prefix):
    for entry in entries:
        path = physical(prefix / safe_name(entry["relative_path"]))
        require(
            path.is_relative_to(prefix) and path.is_file() and digest(path) == entry["sha256"],
            f"Fresh canonical Qt module differs: {path}",
        )
        macho_x86_64(path, (6, 8))
    return entries


def check_api(target, run, artifact, jobs, package_run):
    expected = TARGETS[target]
    require(
        run["id"] == expected["run"]
        and run["repository"]["full_name"] == REPOSITORY
        and run["head_sha"] == HEAD
        and run["path"] == ".github/workflows/qt_pdf_qualify.yml"
        and run["status"] == "completed"
        and run["conclusion"] == "failure",
        "Prior workflow identity/conclusion differs",
    )
    require(
        artifact["id"] == expected["artifact"]
        and artifact["name"] == f"qt-pdf-qualification-{target}"
        and artifact["size_in_bytes"] == expected["size"]
        and artifact["digest"] == "sha256:" + expected["zip_sha256"]
        and artifact["workflow_run"]["id"] == expected["run"]
        and artifact["workflow_run"]["head_sha"] == HEAD,
        "Prior artifact identity differs",
    )
    require(jobs["total_count"] <= 100, "Paginated job evidence unsupported")
    selected = [job for job in jobs["jobs"] if job["id"] == expected["job"]]
    require(
        len(selected) == 1 and selected[0]["conclusion"] == "failure", "Prior native job differs"
    )
    for name, conclusion in ((PASSED_STEP, "success"), (FAILED_STEP, "failure")):
        steps = [step for step in selected[0]["steps"] if step["name"] == name]
        require(
            len(steps) == 1 and steps[0]["conclusion"] == conclusion, "Prior step scope differs"
        )
    require(
        package_run["id"] == PACKAGE_RUN
        and package_run["head_sha"] == PACKAGE_HEAD
        and package_run["repository"]["full_name"] == REPOSITORY
        and package_run["path"] == ".github/workflows/qt_pdf_backport.yml"
        and package_run["status"] == "completed"
        and package_run["conclusion"] == "success",
        "Original package build run differs",
    )


def read_passed_proof(root, target):
    """Re-read the authenticated old results without new rendering or execution."""
    expected = TARGETS[target]
    results = root / DEVICE_ROOT
    report = read_json(results / "qualification.json")
    comparison = read_json(results / "comparison.json")
    installation = read_json(root / INSTALL_ROOT / "installation.json")
    require(
        report["schema_version"] == 1
        and report["qualification_scope"] == "qt-only"
        and report["qualified"] is True
        and report["native_freecad_qualified"] is False
        and report["comparison"] == comparison
        and comparison["passed"] is True
        and not comparison["failures"]
        and comparison["qt_version"] == "6.11.2"
        and comparison["require_device_pixel_parity"] is True
        and comparison["device_pair_count"] == 66
        and len(comparison["device_pairs"]) == 66
        and all(pair["pair_present"] and pair["same_pixels"] for pair in comparison["device_pairs"])
        and comparison["baseline_reproduced_cases"] == 26
        and comparison["baseline_reproduced_by_device"] == {"qpdfwriter": 13, "qprinter": 13},
        "Incomplete passed 66-case Qt proof",
    )
    require(
        report["inputs"]["fixture_sources"] == FIXTURE_SOURCES
        and report["inputs"]["qt_source_archive_sha256"] == SOURCE_SHA
        and report["package_evidence"]["package_sha256"] == expected["package_sha256"]
        and report["package_evidence"]["build_json_sha256"] == expected["build_json_sha256"]
        and Path(report["package_evidence"]["package"]).name == expected["package"]
        and report["package_evidence"]["preparation"]["target_platform"] == target
        and report["package_evidence"]["preparation"]["macos_sdk"] == SDK
        and installation["status"] == "installed"
        and installation["baseline_unchanged"] is True
        and installation["package_sha256"] == expected["package_sha256"]
        and installation["package_build_json_sha256"] == expected["build_json_sha256"]
        and read_json(root / INSTALL_ROOT / "baseline-before.json")
        == read_json(root / INSTALL_ROOT / "baseline-after.json"),
        "Original package/source/installation identity differs",
    )
    require(
        installation["baseline_packages"].keys() == installation["candidate_packages"].keys()
        and all(
            value == installation["candidate_packages"][name]
            for name, value in installation["baseline_packages"].items()
            if name != "qt6-main"
        ),
        "Original non-Qt package inventories differ",
    )
    comparison_module = qualifier.load_module("reused_qt_compare", qualifier.FIXTURE / "compare.py")
    native, map_evidence = available_maps(root, installation)
    manifests, case_records, fixture_runtime = {}, {}, {}
    for side in ("baseline", "patched"):
        directory = results / "generated" / side
        manifest = comparison_module.load_manifest(directory)
        require(
            manifest["schema_version"] == 2
            and manifest["qt_version"] == "6.11.2"
            and len(manifest["cases"]) == 66,
            "Incomplete paired manifest",
        )
        manifests[side] = {case["name"]: case for case in manifest["cases"]}
        runtime = read_json(directory / "runtime.json")
        require(
            runtime["qt_version"] == "6.11.2"
            and runtime["platform"] == "darwin"
            and runtime["architecture"] == "x86_64"
            and runtime["platform_plugin"] == "offscreen"
            and comparison["runtime"][side]["digests_verified"] is True
            and all(runtime[key] == comparison["runtime"][side][key] for key in runtime),
            "Fixture runtime receipt differs",
        )
        old_prefix = report["inputs"][side + "_prefix"]
        fixture_runtime[side] = module_map(runtime["qt_modules"], old_prefix, "path")
        libraries = [entry for entry in runtime["qt_modules"] if entry["kind"] == "library"]
        plugins = [entry for entry in runtime["qt_modules"] if entry["kind"] == "plugin"]
        require(len(libraries) == 6 and len(plugins) == 12, "Incomplete old fixture runtime map")
        require_observed(libraries, native[side]["qt_libraries"], old_prefix, "path")
        observed_plugins = require_observed(plugins, native[side]["qt_plugins"], old_prefix, "path")
        require(
            sum(
                entry["relative_path"] == "lib/qt6/plugins/platforms/libqoffscreen.dylib"
                for entry in observed_plugins
            )
            == 1,
            "Old fixture offscreen origin differs",
        )
        for case in manifest["cases"]:
            pdf = directory / case["pdf"]
            png = pdf.with_suffix(".png")
            case_records.setdefault(case["name"], {})[side] = retained_pdf(pdf, comparison_module)
    require(manifests["baseline"] == manifests["patched"], "Paired manifests changed")
    rows = {case["name"]: case for case in comparison["cases"]}
    require(
        len(rows) == len(comparison["cases"]) == 66 and rows.keys() == case_records.keys(),
        "Incomplete case comparison",
    )
    require(
        {case["device"] for case in rows.values()} == {"qpdfwriter", "qprinter"}
        and all(
            sum(case["device"] == device for case in rows.values()) == 33
            for device in ("qpdfwriter", "qprinter")
        ),
        "Both PDF devices are required",
    )
    invalid_total = 0
    for name, sides in case_records.items():
        row = rows[name]
        require(
            not row["failures"]
            and all(
                row[key] is True
                for key in ("same_coordinates", "same_normalized_operations", "same_pixels")
            ),
            "Failed original case",
        )
        for side, (operators, normalized, coordinates, pixels) in sides.items():
            recorded = row[side]
            require(
                all(recorded[key] == value for key, value in {**operators, **pixels}.items()),
                "Retained PDF/PNG differs from comparison",
            )
            closes = manifests[side][name]["baseline_invalid_closes"] if side == "baseline" else 0
            require(
                operators["invalid_close_count"] == closes
                and not operators["path_errors"]
                and recorded["poppler_status"] == 0
                and recorded["closepath_warnings"] == closes
                and recorded["poppler_stderr"].count(comparison_module.WARNING) == closes
                and all(
                    comparison_module.WARNING in line
                    for line in recorded["poppler_stderr"].splitlines()
                )
                and bool(pixels["ink_pixels"]) == manifests[side][name]["expect_ink"]
                and (
                    not manifests[side][name]["expected_color"]
                    or pixels[manifests[side][name]["expected_color"] + "_pixels"] > 0
                )
                and (side != "patched" or recorded["poppler_stderr"] == ""),
                "Original operator/Poppler gate differs",
            )
            invalid_total += closes if side == "baseline" else 0
        require(
            sides["baseline"][1:] == sides["patched"][1:],
            "Original operator/coordinate/pixel equality differs",
        )
    pairs = []
    for side in ("baseline", "patched"):
        scenarios = {}
        for name, case in manifests[side].items():
            scenarios.setdefault(case["scenario"], {})[case["device"]] = case_records[name][side][3]
        for scenario, devices in scenarios.items():
            require(
                set(devices) == {"qpdfwriter", "qprinter"}
                and devices["qpdfwriter"] == devices["qprinter"],
                "Original cross-device pixels differ",
            )
            pairs.append(
                {"side": side, "scenario": scenario, "pair_present": True, "same_pixels": True}
            )
    require(comparison["device_pairs"] == pairs, "Original cross-device aggregate differs")
    require(invalid_total == 30, "Original baseline reproduction count differs")
    suite = report["upstream_suite"]
    transcript = (results / "upstream-test.log").read_text()
    require(
        suite["passed"] is True
        and suite["test_cases"] == 10
        and len(
            re.findall(r"Totals:\s+10 passed,\s+0 failed,\s+0 skipped,\s+0 blacklisted", transcript)
        )
        == 1
        and "QtTest library 6.11.2, Qt 6.11.2" in transcript
        and len(re.findall(r"^PASS\s+: tst_QPdfWriter::", transcript, re.MULTILINE)) == 10,
        "Incomplete upstream ten-test transcript",
    )
    require(
        report["upstream_source"]["sha256"] == SOURCE_SHA
        and report["upstream_source"]["recipe_md5"] == SOURCE_MD5,
        "Upstream archive receipt differs",
    )
    for name, evidence in report["upstream_source"]["sources"].items():
        require(
            digest(results / "upstream-test-source" / safe_name(name)) == evidence["sha256"],
            "Upstream test source changed",
        )
    for relative, sha in (
        ("fixture-build/qt_pdf_stroker_fixture", report["fixture_executable_sha256"]),
        ("upstream-test-build/tst_qpdfwriter", suite["executable_sha256"]),
    ):
        path = results / relative
        require(digest(path) == sha, "Retained Qt executable changed")
        macho_x86_64(path)
    old_native = read_json(root / "_temp/qt-pdf-native-report.json")
    require(
        old_native["passed"] is False and old_native["failures"],
        "Original native failure must remain a failure",
    )
    return {
        "qt_cases": 66,
        "upstream_test_cases": 10,
        "baseline_invalid_closes": 30,
        "original_native_passed": False,
        "original_native_failures": old_native["failures"],
        "native_runtime": native,
        "managed_map_evidence": map_evidence,
        "original_prefixes": {
            side: report["inputs"][side + "_prefix"] for side in ("baseline", "patched")
        },
        "fixture_runtime": fixture_runtime,
        "baseline_packages": installation["baseline_packages"],
        "candidate_packages": installation["candidate_packages"],
        "original_package_evidence": report["package_evidence"],
    }


def missing_native_inventory(root, inventory):
    binaries = []
    for name, entry in inventory.items():
        path = root / name
        with path.open("rb") as stream:
            magic = stream.read(4)
        if magic == b"\xcf\xfa\xed\xfe":
            header = macho_x86_64(path, (1, 2, 6, 8))
            binaries.append({"path": name, "file_type": header["file_type"], **entry})
    native = [
        entry for entry in binaries if entry["path"].startswith("_temp/qt-pdf-native-module/")
    ]
    require(
        [entry["path"] for entry in native] == ["_temp/qt-pdf-native-module/TechDrawGui.so"],
        "Unexpected retained native module set",
    )
    require(
        not any(
            Path(entry["path"]).name
            in (
                "FreeCAD",
                "libFreeCADApp.dylib",
                "libFreeCADGui.dylib",
                "Part.so",
                "PartGui.so",
                "Sketcher.so",
                "SketcherGui.so",
                "TechDraw.so",
            )
            for entry in binaries
        ),
        "Unexpected retained complete native build",
    )
    require(
        not list((root / "_temp/qt-pdf-native-results").rglob("*.pdf"))
        and not list((root / "_temp/qt-pdf-native-results").rglob("native-provenance.json")),
        "Original failed native capture unexpectedly has completed evidence",
    )
    return {
        "reason": "Original FreeCAD main/App/Gui/other module binaries and resources were not uploaded; only the bypass TechDrawGui.so survives. A fresh scoped native build and prospective exports are required; passed Qt executables need no rerun.",
        "retained_macho_files": binaries,
        "missing_native_targets": [
            "FreeCADMain",
            "FreeCADApp",
            "FreeCADGui",
            "Part",
            "PartGui",
            "PartDesign",
            "PartDesignGui",
            "Sketcher",
            "SketcherGui",
            "TechDraw",
            "pivy",
        ],
        "missing_native_resources_and_runtime_prefixes": True,
        "source_sha256": {
            name: digest(qualifier.REPO_ROOT / name)
            for name in (
                "src/Main/CMakeLists.txt",
                "src/App/CMakeLists.txt",
                "src/Gui/CMakeLists.txt",
                "src/Mod/Part/App/CMakeLists.txt",
                "src/Mod/Part/Gui/CMakeLists.txt",
                "src/Mod/TechDraw/CMakeLists.txt",
            )
        },
        "original_baseline_launch_sha256": digest(
            root / "_temp/qt-pdf-native-results/baseline/launch.json"
        ),
        "original_cmake_cache_sha256": digest(
            root / "FreeCAD/FreeCAD/build/release/CMakeCache.txt"
        ),
        "original_native_exports": 0,
        "original_native_runtime_map_available": False,
    }


def recovery_record(work, target, inventory, passed):
    expected = TARGETS[target]
    return {
        "schema_version": 1,
        "scope": "reused passed macOS Intel Qt-only stage; native recapture required",
        "target": target,
        "prior_run_id": expected["run"],
        "prior_head_sha": HEAD,
        "original_run_conclusion": "failure",
        "passed_step": PASSED_STEP,
        "original_failed_step": FAILED_STEP,
        "package_build_run_id": PACKAGE_RUN,
        "artifact_id": expected["artifact"],
        "artifact_size": expected["size"],
        "artifact_zip_sha256": expected["zip_sha256"],
        "artifact_files": inventory,
        "corpus": current_corpus(),
        "helper_sha256": digest(Path(__file__).resolve()),
        "helper_sources": helper_sources(),
        **passed,
        "missing_native_binaries": missing_native_inventory(work / "artifact", inventory),
        "executables_invoked": False,
        "pdfs_rerendered": False,
        "native_freecad_qualified": False,
        "qualified": False,
        "qt_only_passed_reused": True,
    }


def recover(args):
    native_host(args.target)
    expected = TARGETS[args.target]
    require(args.prior_run_id == expected["run"], "Only the exact reviewed prior run is supported")
    work = fresh_work(args.work_dir)
    run = api(f"actions/runs/{expected['run']}")
    artifact = api(f"actions/artifacts/{expected['artifact']}")
    jobs = api(f"actions/runs/{expected['run']}/jobs?per_page=100")
    package_run = api(f"actions/runs/{PACKAGE_RUN}")
    check_api(args.target, run, artifact, jobs, package_run)
    require(not artifact["expired"], "Prior artifact expired")
    current_corpus()
    work.mkdir(parents=True)
    for name, value in (
        ("run", run),
        ("artifact-api", artifact),
        ("jobs", jobs),
        ("package-run", package_run),
    ):
        write_json(work / (name + ".json"), value)
    archive = work / "artifact.zip"
    with archive.open("xb") as output:
        process = subprocess.run(
            ["gh", "api", f"repos/{REPOSITORY}/actions/artifacts/{expected['artifact']}/zip"],
            stdout=output,
            stderr=subprocess.PIPE,
        )
    require(process.returncode == 0, "Authenticated artifact download failed")
    require(
        archive.stat().st_size == expected["size"] and digest(archive) == expected["zip_sha256"],
        "Whole artifact size/SHA differs",
    )
    inventory = zip_inventory(archive, work / "artifact")
    check_tree(work / "artifact", inventory)
    passed = read_passed_proof(work / "artifact", args.target)
    report = recovery_record(work, args.target, inventory, passed)
    write_json(work / "recovery.json", report)
    return {
        "proof_dir": str(work),
        "recovery_json": str(work / "recovery.json"),
        "qualified": False,
    }


def load_recovery(work):
    work = physical(work)
    report = read_json(work / "recovery.json")
    target = report["target"]
    require(target in TARGETS, "Unsupported proof target")
    expected = TARGETS[target]
    check_api(
        target,
        read_json(work / "run.json"),
        read_json(work / "artifact-api.json"),
        read_json(work / "jobs.json"),
        read_json(work / "package-run.json"),
    )
    archive = physical(work / "artifact.zip")
    require(
        digest(archive) == expected["zip_sha256"] and archive.stat().st_size == expected["size"],
        "Recovered whole ZIP changed",
    )
    inventory = zip_inventory(archive)
    require(report["artifact_files"] == inventory, "Recovered ZIP index changed")
    check_tree(work / "artifact", inventory)
    passed = read_passed_proof(work / "artifact", target)
    require(
        report == recovery_record(work, target, inventory, passed),
        "Recovered Qt receipt/scope/helper changed",
    )
    return report


def validation_data(args):
    work = physical(args.proof_dir)
    report = load_recovery(work)
    target = report["target"]
    native_host(target)
    baseline, candidate = physical(args.baseline_prefix), physical(args.patched_prefix)
    require(
        not baseline.is_relative_to(candidate) and not candidate.is_relative_to(baseline),
        "Runtime prefixes overlap",
    )
    require(
        not work.is_relative_to(baseline) and not work.is_relative_to(candidate),
        "Proof is inside a runtime prefix",
    )
    expected = TARGETS[target]
    build_json = physical(args.package_build_json)
    require(
        digest(build_json) == expected["build_json_sha256"], "Fresh package build record differs"
    )
    backport = qualifier.load_module(
        "reused_backport", qualifier.REPO_ROOT / "package/qt-pdf/build_backport.py"
    )
    package = qualifier.package_evidence(build_json, candidate, backport)
    require(
        package["package_sha256"] == expected["package_sha256"]
        and package["preparation"] == report["original_package_evidence"]["preparation"],
        "Fresh package provenance differs",
    )
    source = physical(args.qt_source_archive)
    require(digest(source) == SOURCE_SHA, "Fresh actual Qt source archive differs")
    native, snapshots = {}, {}
    require(
        all(
            str(prefix) == report["original_prefixes"][side]
            for side, prefix in (("baseline", baseline), ("patched", candidate))
        ),
        "Fresh runtime prefixes differ from the original relocated installation",
    )
    for side, prefix, key in (
        ("baseline", baseline, "baseline_packages"),
        ("patched", candidate, "candidate_packages"),
    ):
        records = installer.managed_records(prefix)
        require(
            installer.identity(records) == report[key],
            f"Fresh {side} managed package inventory differs",
        )
        snapshots[side] = {"package_count": len(records), "packages": installer.identity(records)}
        native[side] = {
            "prefix": str(prefix),
            "qpa_platform": "cocoa",
            **{
                kind: bind_modules(report["native_runtime"][side][kind], prefix)
                for kind in ("qt_libraries", "qt_plugins")
            },
        }
        bind_modules(report["fixture_runtime"][side], prefix)
    validation = {
        "schema_version": 1,
        "scope": "exact macOS Intel passed Qt-stage reuse before new native capture",
        "target": target,
        "qt_only_passed_reused": True,
        "prior_run_id": expected["run"],
        "prior_head_sha": HEAD,
        "prior_run_conclusion": "failure",
        "passed_step": PASSED_STEP,
        "original_native_passed": False,
        "native_freecad_qualified": False,
        "qualified": False,
        "proof_dir": str(work),
        "proof_recovery_sha256": digest(work / "recovery.json"),
        "artifact_id": expected["artifact"],
        "artifact_zip_sha256": expected["zip_sha256"],
        "proof_files": {
            str(work / name): digest(work / name)
            for name in (
                "recovery.json",
                "artifact.zip",
                "run.json",
                "artifact-api.json",
                "jobs.json",
                "package-run.json",
            )
        },
        "package_build_run_id": PACKAGE_RUN,
        "package_evidence": package,
        "qt_source_archive": str(source),
        "qt_source_archive_sha256": SOURCE_SHA,
        "qt_cases": 66,
        "upstream_test_cases": 10,
        "corpus": current_corpus(),
        "helper_sha256": digest(Path(__file__).resolve()),
        "helper_sources": helper_sources(),
        "managed_map_evidence": report["managed_map_evidence"],
        "native_runtime": native,
        "installed_inventories": snapshots,
        "executables_invoked": False,
        "pdfs_rerendered": False,
        "missing_native_binaries": report["missing_native_binaries"],
    }
    return validation


def validate(args):
    data = validation_data(args)
    destination = physical(args.proof_dir) / "validation.json"
    write_json(destination, data)
    return {"validation_json": str(destination), "qt_only_passed_reused": True, "qualified": False}


def check_native_pixel_controls(device_pixels):
    """Recheck stock visible controls from the already-read retained RGBA bytes."""
    for side, scenarios in device_pixels.items():
        for device in ("qpdfwriter", "qprinter"):
            pixels = {scenario: devices[device] for scenario, devices in scenarios.items()}
            require(
                pixels["short-gap"] == pixels["box-only"]
                and pixels["short-gap-opaque"] == pixels["box-only"],
                f"{side}/{device}: dash-gap control contributed visible ink",
            )
            for scenario in (
                "short-solid",
                "long-dashed",
                "distance",
                "zero-width-translucent",
                "zero-width-opaque",
                "zero-width-archival",
            ):
                require(
                    pixels[scenario] != pixels["box-only"],
                    f"{side}/{device}: {scenario} control lost visible ink",
                )
            require(
                pixels["theoretical-exact"] != pixels["distance"],
                f"{side}/{device}: theoretical frame control lost visible ink",
            )
            require(
                pixels["area-and-theoretical-exact"]
                != pixels["area-relocated-and-theoretical-exact"],
                f"{side}/{device}: Area relocation control lost its visible distinction",
            )


def verify_native(args):
    work = physical(args.proof_dir)
    validation = read_json(work / "validation.json")
    # Reconstruct the validation from authenticated inputs, not caller-supplied maps.
    current = validation_data(
        argparse.Namespace(
            proof_dir=work,
            baseline_prefix=Path(validation["native_runtime"]["baseline"]["prefix"]),
            patched_prefix=Path(validation["native_runtime"]["patched"]["prefix"]),
            package_build_json=Path(validation["package_evidence"]["build_json"]),
            qt_source_archive=Path(validation["qt_source_archive"]),
        )
    )
    require(current == validation, "Passed-stage validation changed before native acceptance")
    results, report_path = physical(args.native_results), physical(args.native_report)
    require(
        not results.is_relative_to(work) and not work.is_relative_to(results),
        "Native/proof evidence overlaps",
    )
    native_module = qualifier.load_module(
        "reused_native_compare", qualifier.FIXTURE / "native_compare.py"
    )
    provenance = native_module.check_provenance(results / "baseline", results / "patched")
    report = read_json(report_path)
    require(
        report["passed"] is True
        and not report["failures"]
        and report["qt_version"] == "6.11.2"
        and report["native_runtime_provenance"] == provenance
        and report["require_device_pixel_parity"] is False
        and len(report["cases"]) == 24
        and report["baseline_reproduced_cases"] > 0
        and report["device_pair_count"] == 24
        and Path(report["baseline_dir"]).resolve() == results / "baseline"
        and Path(report["patched_dir"]).resolve() == results / "patched",
        "New complete native report did not pass",
    )
    comparison_module = qualifier.load_module("reused_native_pdf", qualifier.FIXTURE / "compare.py")
    rows = {case["name"]: case for case in report["cases"]}
    require(len(rows) == 24, "Duplicated native cases")
    files = {str(report_path): digest(report_path)}
    paired, device_pixels = {}, {"baseline": {}, "patched": {}}
    reproduced = {"qpdfwriter": 0, "qprinter": 0}
    for side in ("baseline", "patched"):
        directory = results / side
        receipt = read_json(directory / "native-provenance.json")
        expected = validation["native_runtime"][side]
        require(
            receipt["qpa_platform"] == expected["qpa_platform"]
            and receipt["expected_qt_prefix"] == expected["prefix"]
            and "macro_source" in receipt
            and len(provenance[side]["pre_export_expectations"]) == 24,
            "New source-bound prospective native evidence is required",
        )
        for kind in ("qt_libraries", "qt_plugins"):
            observed = require_observed(
                receipt[kind], expected[kind], expected["prefix"], "real_path"
            )
            paths = {entry["relative_path"] for entry in observed}
            require(
                REQUIRED_LIBRARIES.issubset(paths) if kind == "qt_libraries" else COCOA in paths,
                "New native Cocoa/core capture is incomplete",
            )
            for entry in observed:
                macho_x86_64(Path(expected["prefix"]) / entry["relative_path"], (6, 8))
        manifest = comparison_module.load_manifest(directory)
        require(
            {case["name"] for case in manifest["cases"]} == rows.keys(),
            "New native report/case set differs",
        )
        for case in manifest["cases"]:
            row = rows[case["name"]]
            require(
                not row["failures"]
                and all(
                    row[key] is True
                    for key in ("same_coordinates", "same_normalized_operations", "same_pixels")
                ),
                "New native case did not preserve output",
            )
            pdf = directory / case["pdf"]
            operators, normalized, coordinates, pixels = retained_pdf(pdf, comparison_module)
            recorded = row[side]
            require(
                row["device"] == case["device"]
                and row["scenario"] == case["scenario"]
                and all(recorded[key] == value for key, value in {**operators, **pixels}.items())
                and not operators["path_errors"],
                "New native PDF/pixels differ from passed report",
            )
            paired.setdefault(case["name"], {})[side] = (normalized, coordinates, pixels)
            device_pixels[side].setdefault(case["scenario"], {})[case["device"]] = (
                pixels["size"],
                pixels["rgba_sha256"],
            )
            closes = case["baseline_invalid_closes"] if side == "baseline" else 0
            require(
                operators["invalid_close_count"] == closes
                and recorded["closepath_warnings"] == closes
                and recorded["poppler_status"] == 0
                and recorded["poppler_stderr"].count(comparison_module.WARNING) == closes
                and all(
                    comparison_module.WARNING in line
                    for line in recorded["poppler_stderr"].splitlines()
                )
                and bool(pixels["ink_pixels"]) == case["expect_ink"]
                and (not case["expected_color"] or pixels[case["expected_color"] + "_pixels"] > 0),
                "New native Poppler/visible-ink gate differs",
            )
            if side == "baseline" and closes:
                reproduced[case["device"]] += 1
        for path in directory.rglob("*"):
            require(not path.is_symlink(), "Linked native evidence")
            if path.is_file():
                files[str(path)] = digest(path)
    pairs = []
    for side, scenarios in device_pixels.items():
        for scenario, devices in scenarios.items():
            require(set(devices) == {"qpdfwriter", "qprinter"}, "Incomplete native device pair")
            pairs.append(
                {
                    "side": side,
                    "scenario": scenario,
                    "pair_present": True,
                    "same_pixels": devices["qpdfwriter"] == devices["qprinter"],
                }
            )
    require(
        report["device_pairs"] == pairs
        and report["device_pair_count"] == len(pairs) == 24
        and report["baseline_reproduced_by_device"] == reproduced
        and report["baseline_reproduced_cases"] == sum(reproduced.values())
        and all(reproduced.values())
        and all(value["baseline"] == value["patched"] for value in paired.values()),
        "New native operators/pixels/device-pair/reproduction aggregates differ",
    )
    check_native_pixel_controls(device_pixels)
    result = {
        "schema_version": 1,
        "scope": "macOS Intel exact reused Qt stage plus newly passed prospective native stage",
        "target": validation["target"],
        "qt_only_passed_reused": True,
        "prior_run_id": validation["prior_run_id"],
        "prior_run_conclusion": "failure",
        "original_native_passed": False,
        "qt_cases": 66,
        "upstream_test_cases": 10,
        "native_cases": 24,
        "gui_test_cases_per_side": 11,
        "validation_sha256": digest(work / "validation.json"),
        "native_evidence_sha256": files,
        "current_native_comparison_passed": True,
        "new_native_harness_sha256": {
            name: digest(qualifier.FIXTURE / name)
            for name in ("native_compare.py", "native-freecad.FCMacro")
        },
        "native_freecad_qualified": True,
        "qualified": True,
        "qualification_scope": "exact macOS Intel package Qt and native PDF gates",
        "distribution_promoted": False,
    }
    destination = work / "native-reuse-qualification.json"
    write_json(destination, result)
    return {"native_reuse_qualification_json": str(destination), "qualified": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    recovery = commands.add_parser("recover")
    recovery.add_argument("--target", choices=TARGETS, required=True)
    recovery.add_argument("--prior-run-id", type=int, required=True)
    recovery.add_argument("--work-dir", type=Path, required=True)
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
        result = {"recover": recover, "validate": validate, "verify-native": verify_native}[
            args.command
        ](args)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
        zipfile.BadZipFile,
    ) as error:
        print(f"macOS Intel Qt proof reuse rejected: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
