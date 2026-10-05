# SPDX-License-Identifier: LGPL-2.1-or-later
"""Reuse the exact Windows Qt corpus; execute its outstanding upstream/native gates.

recover/validate read authenticated old evidence and installed bytes only. The old
run passed 66 fixture cases, but its empty upstream transcript was rejected and
native FreeCAD never ran. run-upstream executes that retained test PE before the
new scoped FreeCAD build. verify-native admits only fresh prospective stock
captures. Neither an old exit code nor a prepared Windows UI branch is a pass.
"""

import argparse
import ctypes
import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import struct
import subprocess
import sys

import reuse_linux_qt_qualification as common
from reuse_macos_qt_qualification import check_native_pixel_controls
from qtest_logging import qtest_child_environment

installer = common.installer
qualifier = common.qualifier
require = common.require
digest = common.digest
read_json = common.read_json
write_json = common.write_json
REPOSITORY = common.REPOSITORY
PACKAGE_RUN = common.PACKAGE_RUN
HEAD = "a0e3bdf8a89495e95c6d97ce5f30f93c35909b12"
TARGET = "win-64"
PRIOR = {
    "run": 37250196345,
    "job": 111576115668,
    "artifact": 11323427780,
    "size": 12606036,
    "zip_sha256": "c06ec9b2e0dee94b5e1895835c99373abc5fa8b95758edd053514ccc829cf62a",
    "package": "qt6-main-6.11.2-pl5321h17b71ab_1.conda",
    "package_sha256": "780380351ff8977de29cf34e186579d0aac04ab37adf362b260b5405b9abea73",
    "build_json_sha256": "fd4da3eca45b4d971b876df2fe207060f6d9f40f2ae75329bdeb78a5293f143c",
}
PREFIXES = {
    "baseline": r"D:\a\FreeCAD\FreeCAD\.pixi\envs\default",
    "patched": r"D:\a\_temp\qt-pdf-candidate",
}
REQUIRED_LIBRARIES = {
    f"Library/bin/Qt6{family}.dll" for family in ("Core", "Gui", "Widgets", "PrintSupport", "Test")
}
WINDOWS = "Library/lib/qt6/plugins/platforms/qwindows.dll"
OFFSCREEN = "Library/lib/qt6/plugins/platforms/qoffscreen.dll"
UPSTREAM = "upstream-test-build/Release/tst_qpdfwriter.exe"
UPSTREAM_SHA = "bf4373491cbb0ccda76f9005800e90e2f3c4d01612c6f88e2a5f57eb81f76e84"
UPSTREAM_SOURCES = {
    "CMakeLists.txt": "ecfc1d5ddcec6f08270ff61de7c15b664be1bfac8e3a8523a1c09d35c128d7a6",
    "tst_qpdfwriter.cpp": "b058a9fa9343229337beb9ff3965af6eb1eb32cd416f1434b5b2687129fa6245",
}


def physical(path, existing=True):
    """Reject symlinks, junctions and all Windows reparse points before traversal."""
    path = Path(path).expanduser().absolute()
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        require(
            not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400,
            f"Linked/reparse path: {part}",
        )
    if existing:
        require(path.exists(), f"Missing path: {path}")
    require(path.resolve() == path, "Use a canonical physical path")
    return path


def fresh_work(path):
    path = physical(path, existing=False)
    require(not path.exists() and path != Path(path.anchor), "Work directory must be new")
    require(not path.is_relative_to(qualifier.REPO_ROOT), "Work must be outside the checkout")
    for ancestor in path.parents:
        require(not (ancestor / "conda-meta").exists(), "Work is inside an installed runtime")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        require(
            path.is_relative_to(physical(Path(os.environ["RUNNER_TEMP"]))),
            "Work must be under owned RUNNER_TEMP",
        )
    return path


def native_host(target=TARGET):
    require(
        target == TARGET and sys.platform == "win32" and ctypes.sizeof(ctypes.c_void_p) == 8,
        "Require native Windows x64 Python",
    )
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    kernel.IsWow64Process2.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ushort),
        ctypes.POINTER(ctypes.c_ushort),
    ]
    kernel.IsWow64Process2.restype = ctypes.c_int
    process, native = ctypes.c_ushort(), ctypes.c_ushort()
    require(
        kernel.IsWow64Process2(
            kernel.GetCurrentProcess(), ctypes.byref(process), ctypes.byref(native)
        ),
        "IsWow64Process2 failed",
    )
    require(
        native.value == 0x8664 and process.value == 0,
        "Require native AMD64, not emulated Windows qualification",
    )
    return {"native_machine": native.value, "python_process_machine": process.value}


def pe_x64(path, dll=None):
    path = physical(path)
    require(path.is_file(), "PE must be a physical regular file")
    size = path.stat().st_size
    with path.open("rb") as stream:
        dos = stream.read(64)
        require(len(dos) == 64 and dos[:2] == b"MZ", "Missing PE DOS header")
        offset = struct.unpack_from("<I", dos, 60)[0]
        require(64 <= offset <= min(1024 * 1024, size - 24), "Unbounded PE header offset")
        stream.seek(offset)
        header = stream.read(24)
        require(len(header) == 24 and header[:4] == b"PE\0\0", "Missing PE signature")
        machine, sections, _, _, _, optional_size, characteristics = struct.unpack(
            "<HHIIIHH", header[4:]
        )
        require(
            machine == 0x8664
            and 1 <= sections <= 96
            and 112 <= optional_size <= 4096
            and offset + 24 + optional_size + 40 * sections <= size,
            "Require bounded AMD64 PE32+ headers",
        )
        optional = stream.read(optional_size)
        require(
            struct.unpack_from("<H", optional)[0] == 0x20B and characteristics & 2,
            "Require executable PE32+",
        )
        if dll is not None:
            require(bool(characteristics & 0x2000) is dll, "PE executable/DLL type differs")
    return {"machine": machine, "optional_magic": 0x20B, "dll": bool(characteristics & 0x2000)}


def helper_sources():
    from qtest_logging import __file__ as logging_source

    return {
        path.name: digest(path)
        for path in (
            Path(__file__).resolve(),
            Path(common.__file__).resolve(),
            Path(installer.__file__).resolve(),
            Path(qualifier.__file__).resolve(),
            Path(logging_source).resolve(),
            Path(sys.modules[check_native_pixel_controls.__module__].__file__).resolve(),
        )
    }


def module_map(entries, prefix, path_key):
    prefix = PureWindowsPath(prefix)
    require(prefix.is_absolute(), "Recorded Windows prefix must be absolute")
    result, seen = [], set()
    for entry in entries:
        path = PureWindowsPath(entry[path_key])
        require(
            path.is_absolute() and ".." not in path.parts and path.is_relative_to(prefix),
            "Recorded module escapes Windows prefix",
        )
        name = path.relative_to(prefix).as_posix()
        common.safe_name(name)
        require(
            name.casefold() not in seen and re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]),
            "Duplicate/bad Windows module proof",
        )
        seen.add(name.casefold())
        result.append({"relative_path": name, "sha256": entry["sha256"]})
    require(result, "Empty Windows runtime proof")
    return sorted(result, key=lambda item: item["relative_path"])


def require_observed(entries, available, prefix, key):
    observed = module_map(entries, prefix, key)
    expected = {item["relative_path"]: item["sha256"] for item in available}
    require(
        all(expected.get(item["relative_path"]) == item["sha256"] for item in observed),
        "Observed Windows Qt module is outside authenticated managed inventory",
    )
    return observed


def available_maps(root, installation):
    """Finite regular-file DLL/plugin owners, not a fabricated old native map."""
    baseline = read_json(root / common.INSTALL_ROOT / "baseline-before.json")["qt_files"]
    metadata_root = root / common.INSTALL_ROOT / "candidate-conda-meta"
    candidate, owners = {}, {}
    for path in sorted(metadata_root.glob("*.json")):
        physical(path)
        record = read_json(path)
        if not record["name"].startswith(("qt", "pyside", "shiboken")):
            continue
        require(
            installer.identity({record["name"]: record})[record["name"]]
            == installation["candidate_packages"][record["name"]],
            "Retained managed Qt-related package identity differs",
        )
        for entry in record["paths_data"]["paths"]:
            name = entry["_path"]
            common.safe_name(name)
            require(name.casefold() not in owners, "Duplicate managed Windows Qt path")
            owners[name.casefold()] = record["name"]
            candidate[name] = entry
    maps = {}
    for side, entries in (("baseline", baseline), ("patched", candidate)):
        selected = {"qt_libraries": [], "qt_plugins": []}
        for name, entry in entries.items():
            common.safe_name(name)
            library = bool(re.fullmatch(r"Library/bin/Qt6[A-Za-z0-9_]+\.dll", name))
            plugin = bool(re.fullmatch(r"Library/lib/qt6/plugins/[A-Za-z0-9_/-]+\.dll", name))
            if not library and not plugin:
                continue
            require(
                (
                    entry["symlink"] is None
                    if side == "baseline"
                    else entry["path_type"] == "hardlink"
                ),
                "Selected Windows Qt module is not a regular managed file",
            )
            sha = entry["sha256"] if side == "baseline" else entry["sha256_in_prefix"]
            require(
                isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha),
                "Missing managed Windows module digest",
            )
            selected["qt_libraries" if library else "qt_plugins"].append(
                {"relative_path": name, "sha256": sha}
            )
        for kind in selected:
            selected[kind].sort(key=lambda item: item["relative_path"])
        require(
            REQUIRED_LIBRARIES.issubset(
                {item["relative_path"] for item in selected["qt_libraries"]}
            )
            and {WINDOWS, OFFSCREEN}.issubset(
                {item["relative_path"] for item in selected["qt_plugins"]}
            ),
            "Incomplete managed Windows Qt/Test/QPA map",
        )
        maps[side] = {"qpa_platform": "windows", **selected}
    return maps


def check_api(run, artifact, jobs, package_run):
    require(
        run["id"] == PRIOR["run"]
        and run["repository"]["full_name"] == REPOSITORY
        and run["head_sha"] == HEAD
        and run["path"] == ".github/workflows/qt_pdf_qualify.yml"
        and run["status"] == "completed"
        and run["conclusion"] == "failure",
        "Original Windows run identity/conclusion differs",
    )
    require(
        artifact["id"] == PRIOR["artifact"]
        and artifact["name"] == "qt-pdf-qualification-win-64"
        and artifact["size_in_bytes"] == PRIOR["size"]
        and artifact["digest"] == "sha256:" + PRIOR["zip_sha256"]
        and artifact["workflow_run"]["id"] == PRIOR["run"]
        and artifact["workflow_run"]["head_sha"] == HEAD,
        "Original Windows artifact differs",
    )
    require(jobs["total_count"] <= 100, "Paginated jobs unsupported")
    selected = [job for job in jobs["jobs"] if job["id"] == PRIOR["job"]]
    require(
        len(selected) == 1
        and selected[0]["run_id"] == PRIOR["run"]
        and selected[0]["head_sha"] == HEAD
        and selected[0]["conclusion"] == "failure",
        "Original Windows job differs",
    )
    for name, conclusion in (
        ("Configure and build native FreeCAD against locked baseline", "success"),
        ("Compile the controlled mitigation bypass in this disposable checkout", "success"),
        ("Install the exact package in an isolated candidate runtime", "success"),
        (common.PASSED_STEP, "failure"),
        (common.FAILED_STEP, "skipped"),
    ):
        steps = [step for step in selected[0]["steps"] if step["name"] == name]
        require(
            len(steps) == 1 and steps[0]["conclusion"] == conclusion,
            "Original Windows step scope differs",
        )
    require(
        package_run["id"] == PACKAGE_RUN
        and package_run["head_sha"] == common.PACKAGE_HEAD
        and package_run["repository"]["full_name"] == REPOSITORY
        and package_run["path"] == ".github/workflows/qt_pdf_backport.yml"
        and package_run["status"] == "completed"
        and package_run["conclusion"] == "success",
        "Original package build run differs",
    )


def paired_pdf_proof(results, report, native=False):
    """Read already rendered PNGs and PDF operations; do not invoke a renderer."""
    compare = qualifier.load_module("windows_reused_pdf", qualifier.FIXTURE / "compare.py")
    count = 24 if native else 66
    rows = {row["name"]: row for row in report["cases"]}
    require(
        len(rows) == len(report["cases"]) == count
        and report["passed"] is True
        and not report["failures"]
        and report["qt_version"] == "6.11.2"
        and report["require_device_pixel_parity"] is (not native),
        "Incomplete strict paired PDF report",
    )
    paired, device_pixels, reproduced, total = (
        {},
        {"baseline": {}, "patched": {}},
        {"qpdfwriter": 0, "qprinter": 0},
        0,
    )
    manifests = {}
    for side in ("baseline", "patched"):
        directory = results / side if native else results / "generated" / side
        manifest = compare.load_manifest(directory)
        manifests[side] = manifest
        require(
            manifest["schema_version"] == 2
            and manifest["qt_version"] == "6.11.2"
            and len(manifest["cases"]) == count
            and {case["name"] for case in manifest["cases"]} == rows.keys(),
            "Paired manifest differs",
        )
        for case in manifest["cases"]:
            row = rows[case["name"]]
            require(
                row["device"] == case["device"]
                and row["scenario"] == case["scenario"]
                and not row["failures"]
                and all(
                    row[key] is True
                    for key in ("same_coordinates", "same_normalized_operations", "same_pixels")
                ),
                "Failed paired PDF case",
            )
            operators, normalized, coordinates, pixels = common.retained_pdf(
                directory / case["pdf"], compare
            )
            recorded = row[side]
            closes = case["baseline_invalid_closes"] if side == "baseline" else 0
            require(
                all(recorded[key] == value for key, value in {**operators, **pixels}.items())
                and not operators["path_errors"]
                and operators["invalid_close_count"] == closes
                and recorded["poppler_status"] == 0
                and recorded["closepath_warnings"] == closes
                and recorded["poppler_stderr"].count(compare.WARNING) == closes
                and all(compare.WARNING in line for line in recorded["poppler_stderr"].splitlines())
                and bool(pixels["ink_pixels"]) == case["expect_ink"]
                and (not case["expected_color"] or pixels[case["expected_color"] + "_pixels"] > 0),
                "Paired PDF/PNG/Poppler/visible-ink gate differs",
            )
            paired.setdefault(case["name"], {})[side] = (normalized, coordinates, pixels)
            device_pixels[side].setdefault(case["scenario"], {})[case["device"]] = (
                pixels["size"],
                pixels["rgba_sha256"],
            )
            if side == "baseline":
                total += closes
                reproduced[case["device"]] += bool(closes)
    pairs = []
    for side, scenarios in device_pixels.items():
        for scenario, devices in scenarios.items():
            require(set(devices) == {"qpdfwriter", "qprinter"}, "Incomplete PDF device pair")
            same = devices["qpdfwriter"] == devices["qprinter"]
            require(native or same, "Reused fixture cross-device pixels differ")
            pairs.append(
                {"side": side, "scenario": scenario, "pair_present": True, "same_pixels": same}
            )
    require(
        manifests["baseline"] == manifests["patched"]
        and report["device_pairs"] == pairs
        and report["device_pair_count"] == len(pairs) == count
        and report["baseline_reproduced_by_device"] == reproduced
        and report["baseline_reproduced_cases"] == sum(reproduced.values())
        and all(value["baseline"] == value["patched"] for value in paired.values()),
        "Paired aggregates/remaining operations/coordinates/RGBA differ",
    )
    if native:
        require(all(reproduced.values()), "Both native PDF routes must reproduce the defect")
        check_native_pixel_controls(device_pixels)
    else:
        require(
            total == 30 and reproduced == {"qpdfwriter": 13, "qprinter": 13},
            "Reused fixture reproduction differs",
        )
    return {
        "case_count": count,
        "baseline_invalid_closes": total,
        "reproduced_by_device": reproduced,
    }


def read_passed_proof(root):
    results = root / common.DEVICE_ROOT
    report, comparison = read_json(results / "qualification.json"), read_json(
        results / "comparison.json"
    )
    installation = read_json(root / common.INSTALL_ROOT / "installation.json")
    require(
        report["schema_version"] == 1
        and report["qualification_scope"] == "qt-only"
        and report["qualified"] is False
        and report["native_freecad_qualified"] is False
        and report["error"] == "The complete upstream QPdfWriter suite did not pass all 10 cases"
        and "upstream_suite" not in report
        and report["comparison"] == comparison
        and (results / "upstream-test.log").read_bytes() == b"",
        "Original partial-stage failure changed",
    )
    require(
        report["inputs"]["fixture_sources"] == common.FIXTURE_SOURCES
        and report["inputs"]["qt_source_archive_sha256"] == common.SOURCE_SHA
        and report["package_evidence"]["package_sha256"] == PRIOR["package_sha256"]
        and report["package_evidence"]["build_json_sha256"] == PRIOR["build_json_sha256"]
        and PureWindowsPath(report["package_evidence"]["package"]).name == PRIOR["package"]
        and report["package_evidence"]["preparation"]["target_platform"] == TARGET
        and installation["status"] == "installed"
        and installation["baseline_unchanged"] is True
        and installation["package_sha256"] == PRIOR["package_sha256"]
        and installation["package_build_json_sha256"] == PRIOR["build_json_sha256"]
        and read_json(root / common.INSTALL_ROOT / "baseline-before.json")
        == read_json(root / common.INSTALL_ROOT / "baseline-after.json"),
        "Original package/source/installation differs",
    )
    for side in PREFIXES:
        require(
            PureWindowsPath(report["inputs"][side + "_prefix"]) == PureWindowsPath(PREFIXES[side]),
            "Original prefix differs",
        )
    maps, fixture_runtime = available_maps(root, installation), {}
    for side in PREFIXES:
        runtime = read_json(results / "generated" / side / "runtime.json")
        require(
            runtime["qt_version"] == "6.11.2"
            and runtime["platform"] == "winnt"
            and runtime["architecture"] == "x86_64"
            and runtime["platform_plugin"] == "offscreen"
            and comparison["runtime"][side]["digests_verified"] is True
            and all(runtime[key] == comparison["runtime"][side][key] for key in runtime),
            "Old fixture runtime differs",
        )
        libraries = [entry for entry in runtime["qt_modules"] if entry["kind"] == "library"]
        plugins = [entry for entry in runtime["qt_modules"] if entry["kind"] == "plugin"]
        require(len(libraries) == 5 and len(plugins) == 10, "Incomplete fixture DLL/plugin proof")
        require_observed(libraries, maps[side]["qt_libraries"], PREFIXES[side], "path")
        observed = require_observed(plugins, maps[side]["qt_plugins"], PREFIXES[side], "path")
        require(
            sum(entry["relative_path"] == OFFSCREEN for entry in observed) == 1,
            "Old offscreen origin differs",
        )
        fixture_runtime[side] = module_map(runtime["qt_modules"], PREFIXES[side], "path")
    executable = physical(results / UPSTREAM)
    require(digest(executable) == UPSTREAM_SHA, "Original upstream PE bytes changed")
    pe = pe_x64(executable, dll=False)
    for name, sha in UPSTREAM_SOURCES.items():
        require(
            digest(results / "upstream-test-source" / name) == sha
            and report["upstream_source"]["sources"][name]["sha256"] == sha,
            "Retained upstream source differs",
        )
    require(
        not (root / "_temp/qt-pdf-native-results").exists()
        and not (root / "_temp/qt-pdf-native-report.json").exists(),
        "Original native stage must remain unrun",
    )
    return {
        "qt66": paired_pdf_proof(results, comparison),
        "fixture_runtime": fixture_runtime,
        "native_runtime": maps,
        "original_package_evidence": report["package_evidence"],
        "baseline_packages": installation["baseline_packages"],
        "candidate_packages": installation["candidate_packages"],
        "original_prefixes": PREFIXES,
        "retained_upstream_PE": {
            "relative_path": common.DEVICE_ROOT + "/" + UPSTREAM,
            "sha256": UPSTREAM_SHA,
            **pe,
        },
        "original_upstream_passed": False,
        "original_native_passed": False,
        "native_build_missing": True,
        "missing_native_reason": "Only CMakeCache and TechDrawGui.pyd were retained; app/core/resources require a fresh scoped build.",
    }


def recovery_record(work, inventory, proof):
    return {
        "schema_version": 1,
        "scope": "Exact Windows Qt66 reuse only; upstream/native outstanding",
        "target": TARGET,
        "prior_run_id": PRIOR["run"],
        "prior_head_sha": HEAD,
        "original_run_conclusion": "failure",
        "package_build_run_id": PACKAGE_RUN,
        "artifact_id": PRIOR["artifact"],
        "artifact_zip_sha256": PRIOR["zip_sha256"],
        "artifact_files": inventory,
        "helper_sources": helper_sources(),
        "corpus": common.current_corpus(),
        **proof,
        "qt66_passed_reused": True,
        "upstream_tests_invoked": False,
        "native_freecad_qualified": False,
        "qualified": False,
    }


def guard_tree(root):
    """Reject every reparse entry before descending, including diagnostic outputs."""
    pending = [physical(root)]
    count = 0
    while pending:
        for path in pending.pop().iterdir():
            physical(path)
            count += 1
            require(count <= common.MAX_MEMBERS, "Oversized evidence tree")
            if path.is_dir():
                pending.append(path)


def check_tree(root, inventory):
    guard_tree(root)
    common.check_tree(root, inventory)


def recover(args):
    native_host(args.target)
    require(args.prior_run_id == PRIOR["run"], "Only the exact reviewed Windows run is admitted")
    work = fresh_work(args.work_dir)
    records = {
        "run": common.api(f"actions/runs/{PRIOR['run']}"),
        "artifact-api": common.api(f"actions/artifacts/{PRIOR['artifact']}"),
        "jobs": common.api(f"actions/runs/{PRIOR['run']}/jobs?per_page=100"),
        "package-run": common.api(f"actions/runs/{PACKAGE_RUN}"),
    }
    check_api(records["run"], records["artifact-api"], records["jobs"], records["package-run"])
    require(not records["artifact-api"]["expired"], "Original artifact expired")
    common.current_corpus()
    work.mkdir(parents=True)
    for name, record in records.items():
        write_json(work / (name + ".json"), record)
    archive = work / "artifact.zip"
    with archive.open("xb") as output:
        process = subprocess.run(
            ["gh", "api", f"repos/{REPOSITORY}/actions/artifacts/{PRIOR['artifact']}/zip"],
            stdout=output,
            stderr=subprocess.PIPE,
        )
    require(
        process.returncode == 0
        and archive.stat().st_size == PRIOR["size"]
        and digest(archive) == PRIOR["zip_sha256"],
        "Whole Windows ZIP download/size/SHA differs",
    )
    inventory = common.zip_inventory(archive, work / "artifact")
    check_tree(work / "artifact", inventory)
    write_json(
        work / "recovery.json",
        recovery_record(work, inventory, read_passed_proof(work / "artifact")),
    )
    return {
        "proof_dir": str(work),
        "recovery_json": str(work / "recovery.json"),
        "qualified": False,
    }


def load_recovery(work):
    work = physical(work)
    check_api(
        *(
            read_json(work / name)
            for name in ("run.json", "artifact-api.json", "jobs.json", "package-run.json")
        )
    )
    archive = physical(work / "artifact.zip")
    require(
        archive.stat().st_size == PRIOR["size"] and digest(archive) == PRIOR["zip_sha256"],
        "Recovered whole ZIP changed",
    )
    inventory = common.zip_inventory(archive)
    check_tree(work / "artifact", inventory)
    proof = read_passed_proof(work / "artifact")
    report = read_json(work / "recovery.json")
    require(
        report == recovery_record(work, inventory, proof), "Recovered partial-stage receipt changed"
    )
    return report


def bind_modules(entries, prefix):
    for entry in entries:
        path = physical(prefix / common.safe_name(entry["relative_path"]))
        require(
            path.is_file() and digest(path) == entry["sha256"], "Fresh managed DLL/plugin differs"
        )
        pe_x64(path, dll=True)
    return entries


def validation_data(args):
    host = native_host()
    work = physical(args.proof_dir)
    report = load_recovery(work)
    prefixes = {
        "baseline": physical(args.baseline_prefix),
        "patched": physical(args.patched_prefix),
    }
    require(
        not any(
            work.is_relative_to(prefix) or prefix.is_relative_to(work)
            for prefix in prefixes.values()
        )
        and not prefixes["baseline"].is_relative_to(prefixes["patched"])
        and not prefixes["patched"].is_relative_to(prefixes["baseline"]),
        "Runtime/proof prefixes overlap",
    )
    build, source = physical(args.package_build_json), physical(args.qt_source_archive)
    require(
        digest(build) == PRIOR["build_json_sha256"] and digest(source) == common.SOURCE_SHA,
        "Fresh package/source record differs",
    )
    backport = qualifier.load_module(
        "windows_reused_backport", qualifier.REPO_ROOT / "package/qt-pdf/build_backport.py"
    )
    package = qualifier.package_evidence(build, prefixes["patched"], backport)
    require(
        package["package_sha256"] == PRIOR["package_sha256"]
        and package["preparation"] == report["original_package_evidence"]["preparation"],
        "Fresh package provenance differs",
    )
    maps, snapshots = {}, {}
    for side, prefix in prefixes.items():
        require(
            PureWindowsPath(prefix) == PureWindowsPath(PREFIXES[side]),
            "Fresh physical Windows prefix differs",
        )
        records = installer.managed_records(prefix)
        identity = installer.identity(records)
        require(
            identity == report["baseline_packages" if side == "baseline" else "candidate_packages"],
            "Fresh exact managed package identity differs",
        )
        snapshots[side] = {"package_count": len(records), "packages": identity}
        maps[side] = {
            "prefix": str(prefix),
            "qpa_platform": "windows",
            **{
                kind: bind_modules(report["native_runtime"][side][kind], prefix)
                for kind in ("qt_libraries", "qt_plugins")
            },
        }
        bind_modules(report["fixture_runtime"][side], prefix)
    return {
        "schema_version": 1,
        "scope": "Exact Windows Qt66 reuse before new upstream/native",
        "target": TARGET,
        "host": host,
        "prior_run_id": PRIOR["run"],
        "prior_head_sha": HEAD,
        "original_upstream_passed": False,
        "original_native_passed": False,
        "qt66_passed_reused": True,
        "qt_cases": 66,
        "upstream_test_cases": 0,
        "proof_dir": str(work),
        "proof_recovery_sha256": digest(work / "recovery.json"),
        "package_evidence": package,
        "package_build_run_id": PACKAGE_RUN,
        "qt_source_archive": str(source),
        "qt_source_archive_sha256": common.SOURCE_SHA,
        "installed_inventories": snapshots,
        "native_runtime": maps,
        "qualified": False,
    }


def validate(args):
    report = validation_data(args)
    destination = physical(args.proof_dir) / "validation.json"
    write_json(destination, report)
    return {"validation_json": str(destination), "qt66_passed_reused": True, "qualified": False}


def current_validation(work):
    report = read_json(work / "validation.json")
    current = validation_data(
        argparse.Namespace(
            proof_dir=work,
            baseline_prefix=Path(report["native_runtime"]["baseline"]["prefix"]),
            patched_prefix=Path(report["native_runtime"]["patched"]["prefix"]),
            package_build_json=Path(report["package_evidence"]["build_json"]),
            qt_source_archive=Path(report["qt_source_archive"]),
        )
    )
    require(current == report, "Exact installed reuse validation changed")
    return report


def upstream_passed(output):
    return bool(
        re.search(r"Totals:\s+10 passed,\s+0 failed,\s+0 skipped,\s+0 blacklisted", output)
        and "QtTest library 6.11.2, Qt 6.11.2" in output
    )


def run_upstream(args):
    work = physical(args.proof_dir)
    validation = current_validation(work)
    run_dir = work / "upstream-check"
    require(not run_dir.exists(), "Upstream paired probe is single-use")
    executable = physical(work / "artifact" / common.DEVICE_ROOT / UPSTREAM)
    require(
        digest(executable) == UPSTREAM_SHA and not list(executable.parent.glob("Qt6*.dll")),
        "Retained upstream PE changed or has app-directory Qt DLLs",
    )
    pe = pe_x64(executable, dll=False)
    compare = qualifier.load_module(
        "windows_upstream_environment", qualifier.FIXTURE / "compare.py"
    )
    environment = compare.package_environment(
        Path(validation["native_runtime"]["patched"]["prefix"])
    )
    old = {
        key: value for key, value in environment.items() if key.upper() != "QT_FORCE_STDERR_LOGGING"
    }
    forced = qtest_child_environment(old, platform="win32")
    require(
        forced == {**old, "QT_FORCE_STDERR_LOGGING": "1"},
        "QTest child environment changed unrelated keys",
    )
    run_dir.mkdir()
    runs = {}
    for label, child in (("old-routing", old), ("forced-stderr", forced)):
        output = subprocess.run(
            [str(executable)],
            env=child,
            cwd=run_dir,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        text = output.stdout + output.stderr
        require(len(text.encode()) <= 16 * 1024**2, "Oversized upstream transcript")
        log = run_dir / (label + ".log")
        log.write_text(text)
        runs[label] = {
            "command": [str(executable)],
            "returncode": output.returncode,
            "log": str(log),
            "log_sha256": digest(log),
            "QT_FORCE_STDERR_LOGGING": child.get("QT_FORCE_STDERR_LOGGING"),
            "transcript_has_complete_10_version": upstream_passed(text),
        }
    result = {
        "schema_version": 1,
        "scope": "New actual Windows upstream paired logging run; old routing may also pass",
        "validation_sha256": digest(work / "validation.json"),
        "executable_sha256": UPSTREAM_SHA,
        "executable_PE": pe,
        "runs": runs,
        "test_cases": 10,
        "original_upstream_passed": False,
        "original_native_passed": False,
        "passed": runs["forced-stderr"]["returncode"] == 0
        and runs["forced-stderr"]["transcript_has_complete_10_version"],
        "native_freecad_qualified": False,
        "qualified": False,
    }
    require(current_validation(work) == validation, "Managed runtime changed during upstream run")
    write_json(run_dir / "upstream.json", result)
    require(
        result["passed"] is True, "Fresh Windows upstream suite did not pass strict10/version gate"
    )
    return {
        "upstream_json": str(run_dir / "upstream.json"),
        "upstream_passed": True,
        "qualified": False,
    }


def load_upstream(work):
    result = read_json(work / "upstream-check/upstream.json")
    require(
        result["passed"] is True
        and result["test_cases"] == 10
        and result["original_upstream_passed"] is False
        and result["original_native_passed"] is False
        and result["validation_sha256"] == digest(work / "validation.json")
        and result["executable_sha256"] == UPSTREAM_SHA,
        "Fresh upstream receipt differs",
    )
    executable = physical(work / "artifact" / common.DEVICE_ROOT / UPSTREAM)
    require(
        digest(executable) == UPSTREAM_SHA
        and result["executable_PE"] == pe_x64(executable, dll=False),
        "Upstream executable changed",
    )
    require(
        set(result["runs"]) == {"old-routing", "forced-stderr"}, "Incomplete paired logging record"
    )
    for label, flag in (("old-routing", None), ("forced-stderr", "1")):
        run = result["runs"][label]
        log = physical(work / "upstream-check" / (label + ".log"))
        text = log.read_text()
        require(
            run["command"] == [str(executable)]
            and run["log"] == str(log)
            and run["log_sha256"] == digest(log)
            and run["QT_FORCE_STDERR_LOGGING"] == flag
            and type(run["returncode"]) is int
            and run["transcript_has_complete_10_version"] is upstream_passed(text),
            "Upstream command/transcript proof changed",
        )
        if label == "forced-stderr":
            require(
                run["returncode"] == 0 and upstream_passed(text),
                "Fresh strict upstream gate failed",
            )
    return result


def check_windows_dialogs(receipt, directory):
    """Read back the owned filename/Print admission already enforced by the macro."""
    process_threads = set()
    for record in receipt["records"]:
        if "device" not in record:
            continue
        if record["device"] == "qpdfwriter":
            states = record["file_dialog_states"]
            require(
                [state["stage"] for state in states] == ["directory", "filename", "accept"]
                and all(state["class"] == "Gui::FileDialog" for state in states),
                "Incomplete owned Windows filename staging",
            )
            pdf = PureWindowsPath(directory) / (record["name"] + ".pdf")
            require(
                all(
                    PureWindowsPath(state["directory"]) == PureWindowsPath(directory)
                    for state in states
                )
                and all(
                    [PureWindowsPath(path) for path in state["selected_files"]] == [pdf]
                    for state in states[1:]
                )
                and states[1]["filename_has_focus"] is False
                and [
                    [PureWindowsPath(path) for path in paths] for paths in record["selected_files"]
                ]
                == [[pdf]],
                "Owned Windows filename selection changed",
            )
        else:
            ui = record["native_ui_settings"]
            require(
                len(ui) == 1
                and type(ui[0]["format"]) is int
                and ui[0]["format"] == 0
                and ui[0]["dialog_class"] == "#32770"
                and type(ui[0]["button_id"]) is int
                and ui[0]["button_id"] == 1
                and type(ui[0]["button_label"]) is str
                and ui[0]["button_label"].replace("&", "").casefold() == "print"
                and all(
                    type(ui[0][key]) is int and 0 < ui[0][key] < 2**64
                    for key in ("process_id", "thread_id", "dialog_handle")
                ),
                "Missing owned process/thread Print property-sheet proof",
            )
            process_threads.add((ui[0]["process_id"], ui[0]["thread_id"]))
            require(
                record["native_panel_acceptance"] == "EnumThreadWindows/owned Print BM_CLICK",
                "Stock Windows Print acceptance route changed",
            )
            states = record["panel_states"]
            require(
                [state["stage"] for state in states]
                == [
                    "initial printer configured",
                    "accepted printer configured",
                    "stock print command returned",
                ]
                and states[0]["visible_qt_dialogs"] == ["QPrintDialog"]
                and all(state["visible_qt_dialogs"] == [] for state in states[1:])
                and read_json(
                    Path(directory) / ("qprinter-" + record["name"] + "-diagnostics.json")
                )
                == states,
                "Windows Print modal/readback/accepted ordering changed",
            )
    require(len(process_threads) == 1, "Print callbacks do not share one owned process/thread")


def verify_native(args):
    work = physical(args.proof_dir)
    validation, upstream = current_validation(work), load_upstream(work)
    results, report_path = physical(args.native_results), physical(args.native_report)
    require(
        not results.is_relative_to(work)
        and not work.is_relative_to(results)
        and not report_path.is_relative_to(work),
        "Native evidence overlaps reused inputs",
    )
    guard_tree(results)
    native = qualifier.load_module("windows_reused_native", qualifier.FIXTURE / "native_compare.py")
    provenance = native.check_provenance(results / "baseline", results / "patched")
    report = read_json(report_path)
    require(
        report["native_runtime_provenance"] == provenance
        and Path(report["baseline_dir"]).resolve() == results / "baseline"
        and Path(report["patched_dir"]).resolve() == results / "patched",
        "Fresh native report/provenance paths differ",
    )
    evidence = {str(report_path): digest(report_path)}
    for side in PREFIXES:
        directory = results / side
        receipt = read_json(directory / "native-provenance.json")
        expected = validation["native_runtime"][side]
        require(
            receipt["qpa_platform"] == "windows"
            and receipt["expected_qt_prefix"] == expected["prefix"]
            and "macro_source" in receipt
            and receipt["macro_source"]["sha256"]
            == digest(qualifier.FIXTURE / "native-freecad.FCMacro")
            and len(provenance[side]["pre_export_expectations"]) == 24,
            "Fresh source-bound Windows prospective stock captures required",
        )
        check_windows_dialogs(receipt, directory)
        for kind in ("qt_libraries", "qt_plugins"):
            observed = require_observed(
                receipt[kind], expected[kind], expected["prefix"], "real_path"
            )
            paths = {entry["relative_path"] for entry in observed}
            require(
                (
                    (REQUIRED_LIBRARIES - {"Library/bin/Qt6Test.dll"}).issubset(paths)
                    if kind == "qt_libraries"
                    else WINDOWS in paths
                ),
                "Incomplete live Windows Qt/QPA origins",
            )
            bind_modules(observed, Path(expected["prefix"]))
        for path in directory.rglob("*"):
            physical(path)
            if path.is_file():
                evidence[str(path)] = digest(path)
    proof = paired_pdf_proof(results, report, native=True)
    require(
        current_validation(work) == validation and load_upstream(work) == upstream,
        "Runtime/upstream evidence changed before final acceptance",
    )
    result = {
        "schema_version": 1,
        "scope": "Exact Windows conda reused Qt66 plus newly passed upstream10 and prospective native",
        "target": TARGET,
        "prior_run_id": PRIOR["run"],
        "prior_head_sha": HEAD,
        "original_run_conclusion": "failure",
        "original_upstream_passed": False,
        "original_native_passed": False,
        "qt66_passed_reused": True,
        "qt_cases": 66,
        "upstream_test_cases": 10,
        "upstream_newly_passed": True,
        "native_cases": 24,
        "gui_test_cases_per_side": 11,
        "validation_sha256": digest(work / "validation.json"),
        "upstream_receipt_sha256": digest(work / "upstream-check/upstream.json"),
        "native_evidence_sha256": evidence,
        "native_pdf_summary": proof,
        "new_native_harness_sha256": {
            name: digest(qualifier.FIXTURE / name)
            for name in ("native_compare.py", "native-freecad.FCMacro")
        },
        "native_freecad_qualified": True,
        "qualified": True,
        "distribution_promoted": False,
    }
    destination = work / "native-reuse-qualification.json"
    write_json(destination, result)
    return {"native_reuse_qualification_json": str(destination), "qualified": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    recovery = commands.add_parser("recover")
    recovery.add_argument("--target", choices=(TARGET,), required=True)
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
    upstream = commands.add_parser("run-upstream")
    upstream.add_argument("--proof-dir", type=Path, required=True)
    native = commands.add_parser("verify-native")
    for name in ("proof-dir", "native-results", "native-report"):
        native.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        result = {
            "recover": recover,
            "validate": validate,
            "run-upstream": run_upstream,
            "verify-native": verify_native,
        }[args.command](args)
        print(json.dumps(result))
    except (OSError, ValueError, KeyError, ImportError, subprocess.SubprocessError) as error:
        print(f"Windows partial Qt reuse rejected: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
