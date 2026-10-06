# SPDX-License-Identifier: LGPL-2.1-or-later
"""Materialize and build the reviewed Qt 6.11.2 feedstock backport in isolation."""

import argparse
import difflib
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

FEEDSTOCK_COMMIT = "5cd1156d41526330a116b6b441611b47357ec568"
ARCHIVE_URL = (
    "https://github.com/conda-forge/qt-main-feedstock/archive/" f"{FEEDSTOCK_COMMIT}.tar.gz"
)
ARCHIVE_SHA256 = "30a20fe87b59ef0709e4785e8a28a8fcb7ef5f7776b8ac71daf8b2a823ec104a"
RECIPE_SHA256 = "2cd9dc4831840960f1d44cfb7753ba1a0315ea5ccc77796d771e612c186cb9c0"
PATCH_SHA256 = "c8de71a3bf25cc408ba351a3de4dfe63cccf3a857d4bc44589a8fd20188bebe3"
PATCH_DESTINATION = "recipe/patches/0050-pdf-empty-outline.patch"
REPO_ROOT = Path(__file__).resolve().parents[2]
PATCH_SOURCE = REPO_ROOT / "tests/src/Mod/TechDraw/Gui/QtPdfStroker/empty-outline.patch"
VARIANTS = {
    "linux-64": ".ci_support/linux_64_.yaml",
    "linux-aarch64": ".ci_support/linux_aarch64_.yaml",
    "osx-64": ".ci_support/osx_64_.yaml",
    "osx-arm64": ".ci_support/osx_arm64_.yaml",
    "win-64": ".ci_support/win_64_.yaml",
}
# Bare historical host requirements otherwise select newer ABI dependencies
# than FreeCAD's locked runtime. Keep these choices explicit in the evidence.
DEPENDENCY_VARIANTS = {"harfbuzz": "14.4.0", "libpng": "1.6.58"}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def archive_files(data):
    """Decode a pinned archive without extracting links or untrusted paths."""
    require(
        sha256(data) == ARCHIVE_SHA256, "Feedstock archive checksum differs from the reviewed pin"
    )
    prefix = f"qt-main-feedstock-{FEEDSTOCK_COMMIT}"
    files = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive.getmembers():
            parts = PurePosixPath(member.name).parts
            require(
                parts and parts[0] == prefix and ".." not in parts and "\\" not in member.name,
                f"Unexpected archive path: {member.name}",
            )
            require(member.isdir() or member.isfile(), f"Unsupported archive entry: {member.name}")
            if member.isdir():
                continue
            path = PurePosixPath(*parts[1:]).as_posix()
            require(
                path and path not in files, f"Duplicate or empty archive filename: {member.name}"
            )
            with archive.extractfile(member) as stream:
                files[path] = stream.read()
    require(
        sha256(files.get("recipe/recipe.yaml", b"")) == RECIPE_SHA256, "Unexpected upstream recipe"
    )
    for target, variant in VARIANTS.items():
        require(variant in files, f"Missing pinned variant: {variant}")
        require(
            f"target_platform:\n- {target}\n".encode() in files[variant],
            f"Unexpected target in variant: {variant}",
        )
    return files


def backport_files(upstream):
    patch = PATCH_SOURCE.read_bytes()
    require(sha256(patch) == PATCH_SHA256, "Retained Qt patch differs from the reviewed patch")
    original = upstream["recipe/recipe.yaml"].decode("utf-8")
    require('version: "6.11.2"\n' in original, "Unexpected Qt version")
    require("md5: 669c1f3a41c37fdda389094882044d7a\n" in original, "Unexpected Qt source checksum")
    build = "build:\n  number: 0\n"
    anchor = "      - patches/0003-qtbase-use-better-clang-optimize-size.patch\n"
    require(
        original.count(build) == 1 and original.count(anchor) == 1,
        "Unexpected recipe edit locations",
    )
    require(PATCH_DESTINATION not in upstream, "Backport patch already exists upstream")
    modified = original.replace(build, "build:\n  number: 1\n", 1).replace(
        anchor, anchor + "      - patches/0050-pdf-empty-outline.patch\n", 1
    )
    files = dict(upstream)
    files["recipe/recipe.yaml"] = modified.encode("utf-8")
    files[PATCH_DESTINATION] = patch
    diff = "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            modified.splitlines(keepends=True),
            fromfile="upstream/recipe/recipe.yaml",
            tofile="backport/recipe/recipe.yaml",
        )
    )
    scheduling_diff = ""
    for name, anchor, replacement in (
        (
            "recipe/build.sh",
            "cmake --build build --target install\n",
            'cmake --build build --target install --parallel "${CPU_COUNT}"\n',
        ),
        (
            "recipe/build.bat",
            "cmake --build build --target install --config Release\n",
            'cmake --build build --target install --config Release --parallel "%CPU_COUNT%"\n',
        ),
    ):
        script = upstream[name].decode("utf-8")
        require(script.count(anchor) == 1, f"Unexpected scheduling edit location: {name}")
        scheduled = script.replace(anchor, replacement, 1)
        files[name] = scheduled.encode("utf-8")
        scheduling_diff += "".join(
            difflib.unified_diff(
                script.splitlines(keepends=True),
                scheduled.splitlines(keepends=True),
                fromfile=f"upstream/{name}",
                tofile=f"backport/{name}",
            )
        )
    return files, diff, scheduling_diff


def work_directory(path):
    path = path.expanduser().resolve()
    require(path != REPO_ROOT and path != Path(path.anchor), "Use a separate build work directory")
    for ancestor in (path, *path.parents):
        require(
            not (ancestor / "conda-meta").is_dir(),
            "Work directory must be outside installed conda environments",
        )
    path.mkdir(parents=True, exist_ok=True)
    allowed = {
        "feedstock.tar.gz",
        "feedstock",
        "provenance.json",
        "recipe.diff",
        "build-scripts.diff",
        "output",
        "build.json",
    }
    for child in path.iterdir():
        require(not child.is_symlink(), f"Unexpected linked work artifact: {child}")
        require(child.name in allowed, "Work directory contains unrelated files")
    return path


def macos_sdk(path, target):
    if path is None:
        return None
    require(target.startswith("osx-"), "--macos-sdk is only valid for macOS targets")
    path = path.expanduser().resolve()
    require(path.is_dir(), f"Missing macOS SDK directory: {path}")
    settings = next(
        (
            path / name
            for name in ("SDKSettings.json", "SDKSettings.plist")
            if (path / name).is_file()
        ),
        None,
    )
    require(settings is not None, f"SDK directory has no SDKSettings metadata: {path}")
    return {
        "path": str(path),
        "metadata_file": settings.name,
        "metadata_sha256": sha256(settings.read_bytes()),
    }


def build_variants(sdk=None):
    variants = [f"{name}={version}" for name, version in DEPENDENCY_VARIANTS.items()]
    if sdk is not None:
        variants.append(f"CONDA_BUILD_SYSROOT={sdk['path']}")
    return variants


def build_command(executable, work, target, sdk=None):
    command = [
        executable,
        "build",
        "--recipe",
        str(work / "feedstock/recipe/recipe.yaml"),
        "--variant-config",
        str(work / "feedstock" / VARIANTS[target]),
        "--target-platform",
        target,
        "--build-platform",
        target,
        "--package-format",
        "conda",
        "--test",
        "native",
        "--output-dir",
        str(work / "output"),
    ]
    for variant in build_variants(sdk):
        command.extend(["--variant", variant])
    return command


def expected_materialization(work, target, sdk=None):
    archive = work / "feedstock.tar.gz"
    if archive.exists():
        data = archive.read_bytes()
    else:
        request = urllib.request.Request(
            ARCHIVE_URL, headers={"User-Agent": "FreeCAD-Qt-PDF-backport"}
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read(1024 * 1024 + 1)
        require(len(data) <= 1024 * 1024, "Feedstock archive exceeds the expected size bound")
    upstream = archive_files(data)
    files, diff, scheduling_diff = backport_files(upstream)
    if not archive.exists():
        archive.write_bytes(data)
    manifest = {
        "schema_version": 1,
        "qt_version": "6.11.2",
        "build_number": 1,
        "feedstock_commit": FEEDSTOCK_COMMIT,
        "feedstock_archive_url": ARCHIVE_URL,
        "feedstock_archive_sha256": ARCHIVE_SHA256,
        "upstream_recipe_sha256": RECIPE_SHA256,
        "retained_patch": str(PATCH_SOURCE.relative_to(REPO_ROOT)),
        "retained_patch_sha256": PATCH_SHA256,
        "target_platform": target,
        "variant": VARIANTS[target],
        "dependency_variants": dict(DEPENDENCY_VARIANTS),
        "macos_sdk": sdk,
        "build_script_diff": scheduling_diff,
        "files": {name: sha256(data) for name, data in sorted(files.items())},
        "qualified": False,
    }
    return files, diff, manifest


def verify_tree(directory, files):
    require(
        directory.is_dir() and not directory.is_symlink(),
        "Missing or linked materialized feedstock",
    )
    actual = {}
    for path in directory.rglob("*"):
        require(not path.is_symlink(), f"Unexpected symlink in materialized feedstock: {path}")
        if path.is_file():
            actual[path.relative_to(directory).as_posix()] = sha256(path.read_bytes())
    expected = {name: sha256(data) for name, data in files.items()}
    require(actual == expected, "Materialized feedstock was modified; use a fresh work directory")


def prepare(work, target, sdk=None):
    files, diff, manifest = expected_materialization(work, target, sdk)
    destination = work / "feedstock"
    if destination.exists():
        verify_tree(destination, files)
        require(
            json.loads((work / "provenance.json").read_text()) == manifest,
            "Unexpected preparation provenance",
        )
        require((work / "recipe.diff").read_text() == diff, "Unexpected recipe diff")
        require(
            (work / "build-scripts.diff").read_text() == manifest["build_script_diff"],
            "Unexpected build scheduling diff",
        )
        return manifest
    require(
        not (work / "provenance.json").exists(),
        "Incomplete materialization; use a fresh work directory",
    )
    with tempfile.TemporaryDirectory(prefix="prepare-", dir=work) as temporary:
        staged = Path(temporary) / "feedstock"
        staged.mkdir()
        for name, data in files.items():
            path = staged / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        staged.rename(destination)
    (work / "recipe.diff").write_text(diff)
    (work / "build-scripts.diff").write_text(manifest["build_script_diff"])
    (work / "provenance.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def native_platform():
    system = platform.system()
    machine = platform.machine().lower()
    architecture = {"amd64": "64", "x86_64": "64", "aarch64": "arm64", "arm64": "arm64"}.get(
        machine
    )
    if system == "Linux":
        return {"64": "linux-64", "arm64": "linux-aarch64"}.get(architecture)
    if system == "Darwin":
        return {"64": "osx-64", "arm64": "osx-arm64"}.get(architecture)
    if system == "Windows" and architecture == "64":
        return "win-64"
    return None


def build(work, target, executable, sdk=None):
    require(
        native_platform() == target, f"Native host is {native_platform()}, not requested {target}"
    )
    files, diff, manifest = expected_materialization(work, target, sdk)
    verify_tree(work / "feedstock", files)
    require(
        json.loads((work / "provenance.json").read_text()) == manifest,
        "Unexpected preparation provenance",
    )
    require((work / "recipe.diff").read_text() == diff, "Unexpected recipe diff")
    require(
        (work / "build-scripts.diff").read_text() == manifest["build_script_diff"],
        "Unexpected build scheduling diff",
    )
    tool = shutil.which(executable)
    require(tool is not None, f"Cannot find rattler-build executable: {executable}")
    version = subprocess.run(
        [tool, "--version"], check=True, capture_output=True, text=True
    ).stdout.strip()
    command = build_command(tool, work, target, sdk)
    record = {
        "schema_version": 1,
        "command": command,
        "rattler_build_version": version,
        "macos_sdk": sdk,
        "status": "running",
    }
    (work / "build.json").write_text(json.dumps(record, indent=2) + "\n")
    completed = subprocess.run(command, cwd=work / "feedstock", check=False)
    record["exit_code"] = completed.returncode
    record["status"] = "failed" if completed.returncode else "built"
    if not completed.returncode:
        packages = list((work / "output" / target).glob("qt6-main-6.11.2-*_1.conda"))
        require(len(packages) == 1, "Expected exactly one Qt 6.11.2 build-1 package")
        record["package"] = str(packages[0].relative_to(work))
        record["package_sha256"] = sha256(packages[0].read_bytes())
        record["qualified"] = False
    (work / "build.json").write_text(json.dumps(record, indent=2) + "\n")
    require(completed.returncode == 0, f"rattler-build failed with status {completed.returncode}")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--prepare", action="store_true")
    action.add_argument("--build", action="store_true")
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--platform", choices=VARIANTS, required=True)
    parser.add_argument(
        "--rattler-build",
        default="rattler-build",
        help="rattler-build executable on PATH or absolute path",
    )
    parser.add_argument(
        "--macos-sdk",
        type=Path,
        help="Explicit macOS SDK sysroot; pass the same value to prepare and build",
    )
    args = parser.parse_args()
    try:
        sdk = macos_sdk(args.macos_sdk, args.platform)
        work = work_directory(args.work_dir)
        if args.prepare:
            prepare(work, args.platform, sdk)
        else:
            build(work, args.platform, args.rattler_build, sdk)
    except (OSError, ValueError, tarfile.TarError, subprocess.SubprocessError) as error:
        print(f"Backport preparation/build failed: {error}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "work_dir": str(work),
                "platform": args.platform,
                "stage": "prepared" if args.prepare else "built",
                "qualified": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
