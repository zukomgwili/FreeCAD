# SPDX-License-Identifier: LGPL-2.1-or-later
"""Qualify a built Qt package's QPdfWriter/QPrinter PDF behavior in isolation.

The candidate must already be installed in a fresh prefix. This helper neither
installs packages nor edits either runtime. It validates the package build and
preparation evidence, compiles the actual standalone fixture against candidate
development files, and checks both loaded runtimes, PDF operators and pixels.

Requires CMake, a C++17 compiler, pypdf, Pillow and Poppler's pdftoppm. A passing
report has qualification_scope='qt-only'; native FreeCAD exports with its guard
bypassed remain a separate qualification gate.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests/src/Mod/TechDraw/Gui/QtPdfStroker"
QT_SOURCE_MD5 = "669c1f3a41c37fdda389094882044d7a"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def load_module(name, path):
    specification = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def read_json(path):
    require(
        path.is_file() and not path.is_symlink(),
        f"Missing or linked evidence file: {path}",
    )
    return json.loads(path.read_text())


def option_value(command, option):
    require(
        isinstance(command, list) and command.count(option) == 1,
        f"Expected one package build option {option}",
    )
    index = command.index(option) + 1
    require(index < len(command), f"Missing package build option value {option}")
    return command[index]


def build_evidence(build_json, backport, relocated_sdk=None):
    """Validate retained build inputs before any candidate installation begins."""
    require(not build_json.is_symlink(), "Package build evidence must not be linked")
    build_json = build_json.resolve(strict=True)
    root = build_json.parent
    record = read_json(build_json)
    preparation = read_json(root / "provenance.json")
    target = preparation["target_platform"]
    require(
        target == backport.native_platform(),
        "Package qualification requires the matching native host",
    )
    require((root / "feedstock.tar.gz").is_file(), "Retained feedstock archive is required")
    require(
        not (root / "feedstock.tar.gz").is_symlink(),
        "Retained archive must not be linked",
    )
    sdk = preparation.get("macos_sdk")
    if sdk is not None:
        sdk_path = relocated_sdk or Path(sdk["path"])
        verified_sdk = backport.macos_sdk(sdk_path, target)
        require(
            verified_sdk["metadata_file"] == sdk["metadata_file"]
            and verified_sdk["metadata_sha256"] == sdk["metadata_sha256"],
            "macOS SDK metadata differs from the recorded build input",
        )
    else:
        require(
            relocated_sdk is None,
            "The package build did not record a macOS SDK override",
        )
    files, recipe_diff, expected = backport.expected_materialization(root, target, sdk)
    require(preparation == expected, "Preparation provenance differs from reviewed inputs")
    backport.verify_tree(root / "feedstock", files)
    require(
        (root / "recipe.diff").read_text() == recipe_diff,
        "Recipe diff differs from reviewed edits",
    )
    require(
        (root / "build-scripts.diff").read_text() == expected["build_script_diff"],
        "Build-script scheduling diff differs from reviewed edits",
    )
    require(
        record.get("status") == "built" and record.get("exit_code") == 0,
        "Package build did not complete successfully",
    )
    require(
        record.get("rattler_build_version") == "rattler-build 0.76.1",
        "Expected the reviewed rattler-build 0.76.1 tool version",
    )
    require(
        record.get("macos_sdk") == sdk,
        "Package build SDK differs from preparation provenance",
    )
    command = record["command"]
    for option, value in (
        ("--target-platform", target),
        ("--build-platform", target),
        ("--package-format", "conda"),
        ("--test", "native"),
    ):
        require(
            option_value(command, option) == value,
            f"Unexpected package build option {option}",
        )
    recorded_recipe = Path(option_value(command, "--recipe"))
    require(
        recorded_recipe.is_absolute() and len(recorded_recipe.parents) >= 3,
        "Recorded recipe must be an absolute path",
    )
    recorded_root = recorded_recipe.parents[2]
    for option, relative in (
        ("--recipe", Path("feedstock/recipe/recipe.yaml")),
        ("--variant-config", Path("feedstock") / backport.VARIANTS[target]),
        ("--output-dir", Path("output")),
    ):
        require(
            Path(option_value(command, option)) == recorded_root / relative,
            f"Unexpected recorded relative build path {option}",
        )
    if sdk is not None:
        require(
            option_value(command, "--variant") == f"CONDA_BUILD_SYSROOT={sdk['path']}",
            "Package build command does not use the recorded SDK",
        )
    else:
        require("--variant" not in command, "Unrecorded package variant override")
    relative = Path(record["package"])
    require(
        not relative.is_absolute() and ".." not in relative.parts,
        "Unexpected retained package path",
    )
    package = root / relative
    require(
        package.is_file() and not package.is_symlink(),
        "Built package must be a real file",
    )
    package = package.resolve(strict=True)
    require(
        package.is_relative_to(root),
        "Package must remain inside its recorded build work directory",
    )
    require(
        package.name.startswith("qt6-main-6.11.2-") and package.name.endswith("_1.conda"),
        "Expected the reviewed Qt 6.11.2 build-1 package",
    )
    package_sha = digest(package)
    require(
        package_sha == record["package_sha256"],
        "Built package SHA-256 differs from build evidence",
    )
    return {
        "build_json": str(build_json),
        "build_json_sha256": digest(build_json),
        "preparation": preparation,
        "package": str(package),
        "package_sha256": package_sha,
        "rattler_build_version": record["rattler_build_version"],
        "original_build_command": command,
        "original_build_root": str(recorded_root),
        "build_root": str(root),
        "verified_sdk": verified_sdk if sdk is not None else None,
    }


def package_evidence(build_json, candidate, backport, relocated_sdk=None):
    evidence = build_evidence(build_json, backport, relocated_sdk)
    package = Path(evidence["package"])
    package_sha = evidence["package_sha256"]
    target = evidence["preparation"]["target_platform"]
    metadata = candidate / "conda-meta"
    require(
        metadata.is_dir() and not metadata.is_symlink(),
        "Candidate needs real conda metadata",
    )
    metadata_files = list(metadata.glob("qt6-main-6.11.2-*.json"))
    require(
        len(metadata_files) == 1,
        "Candidate prefix must contain exactly one installed Qt 6.11.2 package",
    )
    installed = read_json(metadata_files[0])
    require(
        installed.get("name") == "qt6-main"
        and installed.get("version") == "6.11.2"
        and installed.get("build_number") == 1
        and installed.get("build") == package.name[len("qt6-main-6.11.2-") : -len(".conda")]
        and installed.get("subdir") == target,
        "Candidate installation identity differs from the reviewed package",
    )
    require(
        installed.get("sha256") == package_sha,
        "Candidate conda metadata does not identify the exact built package SHA-256",
    )
    return {
        **evidence,
        "installed_metadata": str(metadata_files[0]),
        "installed_metadata_sha256": digest(metadata_files[0]),
    }


def work_directory(path, baseline, candidate):
    path = path.expanduser().resolve()
    require(
        path != Path(path.anchor) and path != REPO_ROOT,
        "Use a separate qualification work directory",
    )
    require(
        not path.is_relative_to(baseline) and not path.is_relative_to(candidate),
        "Qualification work directory must be outside both runtime prefixes",
    )
    for ancestor in (path, *path.parents):
        require(
            not (ancestor / "conda-meta").is_dir(),
            "Work directory is inside an installed conda environment",
        )
    path.mkdir(parents=True, exist_ok=True)
    allowed = {
        "inputs.json",
        "fixture-build",
        "generated",
        "cmake-configure.log",
        "cmake-build.log",
        "comparison.json",
        "qualification.json",
        "upstream-test-source",
        "upstream-test-build",
        "upstream-test-configure.log",
        "upstream-test-build.log",
        "upstream-test.log",
    }
    for child in path.iterdir():
        require(
            child.name in allowed and not child.is_symlink(),
            f"Unrelated or linked qualification artifact: {child}",
        )
    return path


def command_result(command, environment=None, cwd=None, log=None):
    completed = subprocess.run(
        command, env=environment, cwd=cwd, capture_output=True, text=True, check=False
    )
    output = completed.stdout + completed.stderr
    if log:
        log.write_text(output)
    require(
        completed.returncode == 0,
        f"Command failed ({completed.returncode}): {command}; {output[-4000:]}",
    )
    return output.strip()


def fixture_configuration(prefix):
    for cmake_root in (
        prefix / "lib/cmake",
        prefix / "Library/lib/cmake",
        prefix / "lib64/cmake",
    ):
        if (cmake_root / "Qt6/Qt6Config.cmake").is_file():
            return cmake_root
    raise ValueError(f"Cannot find candidate Qt development CMake files in {prefix}")


def extract_upstream_test(archive_path, destination):
    archive_path = archive_path.resolve(strict=True)
    md5 = hashlib.md5()
    sha256 = hashlib.sha256()
    with archive_path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            md5.update(block)
            sha256.update(block)
    require(
        md5.hexdigest() == QT_SOURCE_MD5,
        "Qt source archive differs from the recipe MD5",
    )
    prefix = "qt-everywhere-src-6.11.2/qtbase/tests/auto/gui/painting/qpdfwriter/"
    wanted = {prefix + name: name for name in ("CMakeLists.txt", "tst_qpdfwriter.cpp")}
    files = {}
    with tarfile.open(archive_path, "r:xz") as archive:
        for member in archive:
            if member.name not in wanted:
                continue
            require(
                member.name not in files,
                f"Duplicate upstream test source: {member.name}",
            )
            require(
                member.isfile() and member.size <= 1024 * 1024,
                f"Invalid upstream test source: {member.name}",
            )
            with archive.extractfile(member) as file:
                files[member.name] = file.read()
    require(
        set(files) == set(wanted),
        "Expected exactly two upstream QPdfWriter test sources",
    )
    destination.mkdir(parents=True, exist_ok=True)
    sources = {}
    for member, name in wanted.items():
        data = files[member]
        require(b"SPDX-License-Identifier:" in data, f"Missing original Qt SPDX: {member}")
        path = destination / name
        require(not path.is_symlink(), f"Linked upstream test output: {path}")
        if path.exists():
            require(path.read_bytes() == data, f"Upstream test source changed: {path}")
        else:
            path.write_bytes(data)
        sources[name] = {
            "archive_member": member,
            "path": str(path),
            "sha256": digest(path),
        }
    return {
        "path": str(archive_path),
        "recipe_md5": QT_SOURCE_MD5,
        "sha256": sha256.hexdigest(),
        "sources": sources,
    }


def build_upstream_test(candidate, work, cmake, sources, comparison, cmake_args=()):
    environment = comparison.package_environment(candidate)
    cmake_root = fixture_configuration(candidate)
    configure = [
        cmake,
        "-S",
        str(sources),
        "-B",
        str(work / "upstream-test-build"),
        "-DCMAKE_BUILD_TYPE=Release",
        f"-DCMAKE_PREFIX_PATH={candidate};{candidate / 'Library'}",
    ]
    for component in ("Qt6", "Qt6Core", "Qt6Gui", "Qt6Test", "Qt6BuildInternals"):
        configure.append(f"-D{component}_DIR={cmake_root / component}")
    if sys.platform == "darwin":
        configure.append("-DCMAKE_OSX_DEPLOYMENT_TARGET=14.0")
    configure.extend(cmake_args)
    build = [
        cmake,
        "--build",
        str(work / "upstream-test-build"),
        "--config",
        "Release",
        "--parallel",
        "2",
    ]
    command_result(configure, environment, log=work / "upstream-test-configure.log")
    command_result(build, environment, log=work / "upstream-test-build.log")
    name = "tst_qpdfwriter.exe" if sys.platform == "win32" else "tst_qpdfwriter"
    executable = next(
        (
            path
            for path in (
                work / "upstream-test-build/Release" / name,
                work / "upstream-test-build" / name,
            )
            if path.is_file()
        ),
        None,
    )
    require(executable is not None, "Upstream QPdfWriter test executable was not built")
    output = command_result(
        [str(executable)], environment, cwd=work, log=work / "upstream-test.log"
    )
    require(
        re.search(r"Totals:\s+10 passed,\s+0 failed,\s+0 skipped,\s+0 blacklisted", output),
        "The complete upstream QPdfWriter suite did not pass all 10 cases",
    )
    require(
        "QtTest library 6.11.2, Qt 6.11.2" in output,
        "Upstream tests did not report the expected Qt/Testlib version",
    )
    return {
        "passed": True,
        "test_cases": 10,
        "configure_command": configure,
        "build_command": build,
        "run_command": [str(executable)],
        "executable_sha256": digest(executable),
        "log": str(work / "upstream-test.log"),
    }


def build_and_compare(baseline, candidate, work, cmake, pdftoppm, comparison, cmake_args=()):
    """Run actual Qt binaries; package identity is validated separately above."""
    candidate_environment = comparison.package_environment(candidate)
    baseline_environment = comparison.package_environment(baseline)
    cmake_root = fixture_configuration(candidate)
    configure = [
        cmake,
        "-S",
        str(FIXTURE),
        "-B",
        str(work / "fixture-build"),
        "-DWITH_QPRINTER=ON",
        "-DCMAKE_BUILD_TYPE=Release",
        f"-DCMAKE_PREFIX_PATH={candidate};{candidate / 'Library'}",
    ]
    for component in ("Qt6", "Qt6Core", "Qt6Gui", "Qt6Widgets", "Qt6PrintSupport"):
        configure.append(f"-D{component}_DIR={cmake_root / component}")
    if sys.platform == "darwin":
        configure.append("-DCMAKE_OSX_DEPLOYMENT_TARGET=14.0")
    configure.extend(cmake_args)
    build = [
        cmake,
        "--build",
        str(work / "fixture-build"),
        "--config",
        "Release",
        "--parallel",
        "2",
    ]
    command_result(configure, candidate_environment, log=work / "cmake-configure.log")
    command_result(build, candidate_environment, log=work / "cmake-build.log")
    executable_name = (
        "qt_pdf_stroker_fixture.exe" if sys.platform == "win32" else "qt_pdf_stroker_fixture"
    )
    executables = [
        work / "fixture-build" / "Release" / executable_name,
        work / "fixture-build" / executable_name,
    ]
    executable = next((path for path in executables if path.is_file()), None)
    require(executable is not None, "Fixture executable was not built")
    baseline_output = comparison.generate(
        executable, work / "generated/baseline", "both", baseline_environment
    )
    patched_output = comparison.generate(
        executable, work / "generated/patched", "both", candidate_environment
    )
    report = comparison.compare(
        baseline_output,
        patched_output,
        pdftoppm,
        {"baseline": baseline, "patched": candidate},
        require_runtime=True,
    )
    require(
        set(report["baseline_reproduced_by_device"]) == {"qpdfwriter", "qprinter"},
        "Both actual PDF devices must be exercised",
    )
    require(len(report["cases"]) == 66, "Expected all 33 cases on each PDF device")
    (work / "comparison.json").write_text(json.dumps(report, indent=2) + "\n")
    cache = (work / "fixture-build/CMakeCache.txt").read_text()
    compiler_entries = [
        line.partition("=")[2]
        for line in cache.splitlines()
        if line.startswith("CMAKE_CXX_COMPILER:FILEPATH=")
    ]
    require(len(compiler_entries) == 1, "Cannot identify the fixture compiler")
    compiler = compiler_entries[0]
    compiler_command = (
        [compiler] if Path(compiler).name.lower() == "cl.exe" else [compiler, "--version"]
    )
    compiler_version = subprocess.run(compiler_command, capture_output=True, text=True, check=False)
    versions = {
        "python": sys.version,
        "cmake": command_result([cmake, "--version"]),
        "compiler": compiler_version.stdout + compiler_version.stderr,
        "poppler": command_result([pdftoppm, "-v"]),
    }
    import PIL
    import pypdf

    versions.update({"pypdf": pypdf.__version__, "Pillow": PIL.__version__})
    return {
        "configure_command": configure,
        "build_command": build,
        "fixture_executable": str(executable),
        "fixture_executable_sha256": digest(executable),
        "tool_versions": versions,
        "comparison": report,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-prefix", type=Path, required=True)
    parser.add_argument("--patched-prefix", type=Path, required=True)
    parser.add_argument("--package-build-json", type=Path, required=True)
    parser.add_argument(
        "--qt-source-archive",
        type=Path,
        required=True,
        help="Actual built qt-everywhere6.11.2 tar.xz from the recipe source cache",
    )
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--cmake", default=shutil.which("cmake"))
    parser.add_argument("--pdftoppm", default=shutil.which("pdftoppm"))
    parser.add_argument("--macos-sdk", type=Path, help="Relocated copy of the recorded build SDK")
    parser.add_argument(
        "--cmake-arg",
        action="append",
        default=[],
        help="Additional explicit fixture configuration argument",
    )
    args = parser.parse_args()
    if not args.cmake or not args.pdftoppm:
        parser.error("CMake and pdftoppm must be available")
    report = {
        "schema_version": 1,
        "qualification_scope": "qt-only",
        "qualified": False,
        "native_freecad_qualified": False,
    }
    work = None
    try:
        baseline = args.baseline_prefix.resolve(strict=True)
        candidate = args.patched_prefix.resolve(strict=True)
        require(baseline != candidate, "Baseline and candidate prefixes must be distinct")
        backport = load_module("qt_pdf_backport", Path(__file__).with_name("build_backport.py"))
        comparison = load_module("qt_pdf_comparison", FIXTURE / "compare.py")
        work = work_directory(args.work_dir, baseline, candidate)
        evidence = package_evidence(args.package_build_json, candidate, backport, args.macos_sdk)
        sources = {
            name: digest(FIXTURE / name)
            for name in ("generator.cpp", "CMakeLists.txt", "compare.py")
        }
        inputs = {
            "baseline_prefix": str(baseline),
            "patched_prefix": str(candidate),
            "package_sha256": evidence["package_sha256"],
            "fixture_sources": sources,
            "cmake_arguments": args.cmake_arg,
            "qt_source_archive_sha256": digest(args.qt_source_archive),
        }
        if (work / "inputs.json").exists():
            require(
                read_json(work / "inputs.json") == inputs,
                "Qualification inputs changed; use a fresh work directory",
            )
        else:
            (work / "inputs.json").write_text(json.dumps(inputs, indent=2) + "\n")
        report.update({"inputs": inputs, "package_evidence": evidence})
        report.update(
            build_and_compare(
                baseline,
                candidate,
                work,
                args.cmake,
                args.pdftoppm,
                comparison,
                args.cmake_arg,
            )
        )
        report["upstream_source"] = extract_upstream_test(
            args.qt_source_archive, work / "upstream-test-source"
        )
        report["upstream_suite"] = build_upstream_test(
            candidate,
            work,
            args.cmake,
            work / "upstream-test-source",
            comparison,
            args.cmake_arg,
        )
        report["qualified"] = report["comparison"]["passed"] and report["upstream_suite"]["passed"]
    except (
        OSError,
        ValueError,
        KeyError,
        ImportError,
        subprocess.SubprocessError,
    ) as error:
        report["error"] = str(error)
    if work:
        (work / "qualification.json").write_text(json.dumps(report, indent=2) + "\n")
    if not report["qualified"]:
        print(
            report.get("error", "Qt-only package PDF comparison failed"),
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {
                "qualified": True,
                "qualification_scope": "qt-only",
                "cases": 66,
                "report": str(work / "qualification.json"),
                "native_freecad_qualified": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
