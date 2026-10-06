# SPDX-License-Identifier: LGPL-2.1-or-later
"""Reuse two authenticated passed Linux Qt stages before new native FreeCAD capture.

recover downloads/verifies a complete GitHub artifact and reads its existing PDF,
PNG and test evidence. validate binds fresh managed prefixes and the actual built
package/source archive to those bytes. Neither stage runs a fixture, QTest,
FreeCAD, Poppler, a compiler or an installer. The original runs remain failed;
only their passed 66-case Qt comparison and ten upstream tests are reused.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import stat
import subprocess
import sys
import zipfile

import install_candidate as installer
import qualify_package as qualifier

REPOSITORY = "zukomgwili/FreeCAD"
HEAD = "19abecfd53ec03798fbdf2bdfbe9450626e96699"
PACKAGE_RUN = 37238935749
PACKAGE_HEAD = "1e2bf68f7f74a4a63a41990c4402f9f411386c53"
LOCK_SHA = "e6978ba46f11304148ab5acf7b4a432d0ffea26518e36a27092b3a24b3384644"
SOURCE_SHA = "6dcfbca271d76a6502741a2c0dc6fc98ef7dd0b7b4cfd0abcebb285a86a26f33"
SOURCE_MD5 = "669c1f3a41c37fdda389094882044d7a"
FIXTURE_SOURCES = {
    "generator.cpp": "b09883682af8b0290d0e62805951974c25032d3eed8be37e70b4f4ee01694772",
    "CMakeLists.txt": "ef1301c04a6f32fa3955e18fdbe72d58547bfd3893dfe1f46219419295d4a4fb",
    "compare.py": "e3cf4909c7c1781a3d56a34b981346a1b4c72d44275c48d63289d1cb2a1e0d85",
}
PASSED_STEP = "Qualify both Qt PDF devices and Qt's own writer tests"
FAILED_STEP = "Qualify stock native exports with both guards bypassed"
TARGETS = {
    "linux-64": {
        "run": 37252425998,
        "job": 111582645297,
        "artifact": 11323981287,
        "size": 13893385,
        "zip_sha256": "310212a0d01c6e3fb866e3bcd082fb4ece2f4b2c58c7147c9d46e0f9adc9c657",
        "machine": "x86_64",
        "runtime_architecture": "x86_64",
        "elf_machine": 62,
        "package": "qt6-main-6.11.2-pl5321h23691f9_1.conda",
        "package_sha256": "a5ec19b2367f45020d98aa08be0a1d3a6370f2d8a2eace03fa47cef68880947b",
        "build_json_sha256": "eec63a85d62dfa21706fdb38bb8064c6987069475d27c5a6167814d3d197bab2",
    },
    "linux-aarch64": {
        "run": 37252439637,
        "job": 111582682241,
        "artifact": 11323681303,
        "size": 13785581,
        "zip_sha256": "be0fa75d4300b8fb0225a0f7b84899aabb4550b636388f71c6c5c627590320b8",
        "machine": "aarch64",
        "runtime_architecture": "arm64",
        "elf_machine": 183,
        "package": "qt6-main-6.11.2-pl5321h8194227_1.conda",
        "package_sha256": "5ae1dfcaa15ea86aca72d36190b0b82c12d044ce02d6c20d5c56dbf36fd6d24b",
        "build_json_sha256": "2e424174cb25edf710dbfe159e9153f83cff252ced403340fead895f9870800e",
    },
}
DEVICE_ROOT = "_temp/qt-pdf-device-results"
INSTALL_ROOT = "_temp/qt-pdf-candidate.install-evidence"
MAX_CONTENT = 512 * 1024**2
MAX_MEMBERS = 5000
require = installer.require
digest = installer.digest
read_json = installer.read_json


def physical(path, existing=True):
    path = path.expanduser().absolute()
    for part in (path, *path.parents):
        require(not part.is_symlink(), f"Linked path: {part}")
    if existing:
        require(path.exists(), f"Missing path: {path}")
    require(path.resolve() == path, "Use a canonical physical path")
    return path


def native_host(target):
    require(
        sys.platform == "linux" and platform.machine() == TARGETS[target]["machine"],
        "Require the matching native Linux host",
    )


def fresh_work(path):
    path = physical(path, existing=False)
    require(not path.exists() and path != Path(path.anchor), "Proof work directory must be new")
    require(not path.is_relative_to(qualifier.REPO_ROOT), "Proof must be outside the checkout")
    for ancestor in path.parents:
        require(not (ancestor / "conda-meta").exists(), "Proof is inside an installed runtime")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        temporary = physical(Path(os.environ["RUNNER_TEMP"]))
        require(path.is_relative_to(temporary), "Proof must be under owned RUNNER_TEMP")
    return path


def safe_name(value):
    name = PurePosixPath(value.removesuffix("/"))
    require(
        bool(value)
        and not name.is_absolute()
        and all(part not in ("", ".", "..") for part in value.removesuffix("/").split("/"))
        and "\\" not in value
        and ":" not in value
        and not any(ord(character) < 32 for character in value),
        "Unsafe ZIP member name",
    )
    return name


def zip_inventory(archive, destination=None):
    """Read every member to verify CRC, optionally into a new owned directory."""
    inventory, names, total = {}, set(), 0
    with zipfile.ZipFile(archive) as stream:
        entries = stream.infolist()
        require(len(entries) <= MAX_MEMBERS, "Too many ZIP members")
        # Validate the complete namespace before any extraction.
        for entry in entries:
            name = safe_name(entry.filename)
            mode = stat.S_IFMT(entry.external_attr >> 16)
            key = str(name).casefold()
            require(
                key not in names
                and mode in (0, stat.S_IFREG, stat.S_IFDIR)
                and not entry.flag_bits & 1
                and entry.file_size >= 0,
                "Duplicate/linked/special/encrypted ZIP member",
            )
            require(entry.is_dir() == (mode == stat.S_IFDIR) or mode == 0, "ZIP mode differs")
            names.add(key)
            total += entry.file_size
            require(total <= MAX_CONTENT, "Oversized ZIP content")
        files = {str(safe_name(entry.filename)) for entry in entries if not entry.is_dir()}
        require(
            all(
                not any(str(parent) in files for parent in PurePosixPath(name).parents)
                for name in files
            ),
            "ZIP file/directory collision",
        )
        if destination is not None:
            destination.mkdir()
        for entry in entries:
            name = safe_name(entry.filename)
            if entry.is_dir():
                continue
            hasher, size = hashlib.sha256(), 0
            output = None
            if destination is not None:
                path = destination / name
                path.parent.mkdir(parents=True, exist_ok=True)
                output = path.open("xb")
            try:
                with stream.open(entry) as source:
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        hasher.update(block)
                        size += len(block)
                        if output is not None:
                            output.write(block)
            finally:
                if output is not None:
                    output.close()
            require(size == entry.file_size, "Short ZIP member")
            inventory[str(name)] = {"size": size, "sha256": hasher.hexdigest()}
    return inventory


def check_tree(root, inventory):
    root = physical(root)
    actual = {}
    for path in sorted(root.rglob("*")):
        require(not path.is_symlink(), "Linked extracted evidence")
        if path.is_dir():
            continue
        require(
            path.is_file() and path.stat().st_nlink == 1, "Special/hardlinked extracted evidence"
        )
        actual[path.relative_to(root).as_posix()] = {
            "size": path.stat().st_size,
            "sha256": digest(path),
        }
    require(actual == inventory, "Extracted artifact differs from authenticated ZIP")


def api(endpoint):
    process = subprocess.run(
        ["gh", "api", f"repos/{REPOSITORY}/{endpoint}"], capture_output=True, check=True
    )
    require(len(process.stdout) < 8 * 1024**2, "Oversized API metadata")
    return json.loads(process.stdout)


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


def current_corpus():
    require(digest(qualifier.REPO_ROOT / "pixi.lock") == LOCK_SHA, "Locked environments changed")
    for name, expected in FIXTURE_SOURCES.items():
        require(
            digest(qualifier.FIXTURE / name) == expected, f"Passed fixture corpus changed: {name}"
        )
    return {"pixi.lock": LOCK_SHA, **FIXTURE_SOURCES}


def relative_module(path, prefix):
    path, prefix = PurePosixPath(path), PurePosixPath(prefix)
    require(path.is_absolute() and prefix.is_absolute(), "Runtime origin must be absolute")
    name = path.relative_to(prefix).as_posix()
    safe_name(name)
    return name


def module_map(entries, prefix, path_key):
    result = []
    seen = set()
    for entry in entries:
        name = relative_module(entry[path_key], prefix)
        require(
            name not in seen and re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]),
            "Duplicate/bad module proof",
        )
        seen.add(name)
        result.append({"relative_path": name, "sha256": entry["sha256"]})
    require(result, "Empty runtime module proof")
    return sorted(result, key=lambda item: item["relative_path"])


def retained_pdf(pdf, comparison_module):
    from PIL import Image

    operators, normalized, coordinates = comparison_module.inspect_operators(pdf)
    with Image.open(pdf.with_suffix(".png")) as image:
        rgba = image.convert("RGBA")
        pixels, size = rgba.tobytes(), list(rgba.size)
    ink = red = blue = 0
    for r, g, b in zip(pixels[0::4], pixels[1::4], pixels[2::4]):
        ink += (r, g, b) != (255, 255, 255)
        red += r > g and r > b
        blue += b > r and b > g
    return (
        operators,
        normalized,
        coordinates,
        {
            "size": size,
            "rgba_sha256": hashlib.sha256(pixels).hexdigest(),
            "ink_pixels": ink,
            "red_pixels": red,
            "blue_pixels": blue,
        },
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
    manifests, case_records, native, fixture_runtime = {}, {}, {}, {}
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
            and runtime["platform"] == "linux"
            and runtime["architecture"] == expected["runtime_architecture"]
            and runtime["platform_plugin"] == "offscreen"
            and comparison["runtime"][side]["digests_verified"] is True
            and all(runtime[key] == comparison["runtime"][side][key] for key in runtime),
            "Fixture runtime receipt differs",
        )
        old_prefix = report["inputs"][side + "_prefix"]
        fixture_runtime[side] = module_map(runtime["qt_modules"], old_prefix, "path")
        provenance = read_json(root / f"_temp/qt-pdf-native-results/{side}/native-provenance.json")
        require(
            provenance["qt_version"] == "6.11.2"
            and provenance["expected_qt_prefix"] == old_prefix
            and provenance["qpa_platform"] == "xcb",
            "Original native Qt origin differs",
        )
        native[side] = {
            "qpa_platform": "xcb",
            "qt_libraries": module_map(provenance["qt_libraries"], old_prefix, "real_path"),
            "qt_plugins": module_map(provenance["qt_plugins"], old_prefix, "real_path"),
        }
        require(
            len(native[side]["qt_libraries"]) == 14
            and sum(
                item["relative_path"].endswith("/platforms/libqxcb.so")
                for item in native[side]["qt_plugins"]
            )
            == 1,
            "Incomplete original native Qt/QPA map",
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
                and (side != "patched" or recorded["poppler_stderr"] == ""),
                "Original operator/Poppler gate differs",
            )
            invalid_total += closes if side == "baseline" else 0
        require(
            sides["baseline"][1:] == sides["patched"][1:],
            "Original operator/coordinate/pixel equality differs",
        )
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
        policy = qualifier.test_loader_policy(path, path.parent, platform="linux")
        require(
            policy["machine"] == expected["elf_machine"],
            "Retained Qt executable architecture differs",
        )
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
        "fixture_runtime": fixture_runtime,
        "baseline_packages": installation["baseline_packages"],
        "candidate_packages": installation["candidate_packages"],
        "original_package_evidence": report["package_evidence"],
    }


def missing_native_inventory(root, inventory):
    # Uploaded files include the bypassed module, not the original native build.
    elf = []
    for name in inventory:
        path = root / name
        with path.open("rb") as stream:
            if stream.read(4) == b"\x7fELF":
                elf.append({"path": name, **inventory[name]})
    native = [entry for entry in elf if entry["path"].startswith("_temp/qt-pdf-native-module/")]
    require(
        [entry["path"] for entry in native] == ["_temp/qt-pdf-native-module/TechDrawGui.so"],
        "Unexpected retained native binaries",
    )
    require(
        not any(
            Path(entry["path"]).name
            in (
                "FreeCAD",
                "libFreeCADApp.so",
                "libFreeCADGui.so",
                "Part.so",
                "PartGui.so",
                "Sketcher.so",
                "SketcherGui.so",
                "TechDraw.so",
            )
            for entry in elf
        ),
        "Unexpected retained native build",
    )
    sources = [
        "src/Main/CMakeLists.txt",
        "src/App/CMakeLists.txt",
        "src/Gui/CMakeLists.txt",
        "src/Mod/Part/App/CMakeLists.txt",
        "src/Mod/Part/Gui/CMakeLists.txt",
        "src/Mod/TechDraw/CMakeLists.txt",
    ]
    return {
        "reason": "Original FreeCAD main/App/Gui/other module binaries, resources and runtime prefixes were not uploaded. New pre-export native capture requires a fresh scoped FreeCAD build; passed Qt executables need no rerun.",
        "retained_elf_files": elf,
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
        "source_sha256": {name: digest(qualifier.REPO_ROOT / name) for name in sources},
        "original_launch_sha256": {
            side: digest(root / f"_temp/qt-pdf-native-results/{side}/launch.json")
            for side in ("baseline", "patched")
        },
        "original_cmake_cache_sha256": digest(
            root / "FreeCAD/FreeCAD/build/release/CMakeCache.txt"
        ),
    }


def write_json(path, data):
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(data, indent=2) + "\n")


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
    report = {
        "schema_version": 1,
        "scope": "reused passed Linux Qt-only stage; native recapture required",
        "target": args.target,
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
        **passed,
        "missing_native_binaries": missing_native_inventory(work / "artifact", inventory),
        "executables_invoked": False,
        "pdfs_rerendered": False,
        "native_freecad_qualified": False,
        "qualified": False,
        "qt_only_passed_reused": True,
    }
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
        all(report[key] == value for key, value in passed.items()), "Recovered Qt receipt changed"
    )
    require(
        report["corpus"] == current_corpus()
        and report["original_run_conclusion"] == "failure"
        and report["qualified"] is False
        and report["helper_sha256"] == digest(Path(__file__).resolve()),
        "Reuse scope/corpus/helper changed",
    )
    return report


def bind_modules(entries, prefix):
    bound = []
    for entry in entries:
        path = prefix / safe_name(entry["relative_path"])
        require(
            path.is_file() and path.resolve(strict=True).is_relative_to(prefix),
            "Missing/external runtime module",
        )
        require(digest(path) == entry["sha256"], f"Fresh runtime module differs: {path}")
        bound.append(entry)
    return bound


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
            "qpa_platform": "xcb",
            **{
                kind: bind_modules(report["native_runtime"][side][kind], prefix)
                for kind in ("qt_libraries", "qt_plugins")
            },
        }
        bind_modules(report["fixture_runtime"][side], prefix)
    validation = {
        "schema_version": 1,
        "scope": "exact Linux passed Qt-stage reuse before new native capture",
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
            require(
                module_map(receipt[kind], expected["prefix"], "real_path") == expected[kind],
                "New live native Qt/QPA map differs from passed Qt stage",
            )
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
    result = {
        "schema_version": 1,
        "scope": "Linux exact reused Qt stage plus newly passed prospective native stage",
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
        "qualification_scope": "exact Linux package Qt and native PDF gates",
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
        print(f"Linux Qt proof reuse rejected: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
