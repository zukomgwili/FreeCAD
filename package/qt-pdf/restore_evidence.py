# SPDX-License-Identifier: LGPL-2.1-or-later
"""Recover authenticated hidden feedstock files omitted by artifact transport.

The original artifact is read-only. A new sibling directory contains the exact
pinned materialization plus copied package/source evidence. Only missing known
hidden feedstock paths are recoverable; altered, unknown, linked or missing
visible evidence inputs fail. Derived source-cache entries, including links,
are inventoried without following links and excluded from recovery. Only raw
recipe archives are copied. Recovery does not qualify or install a runtime.
"""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path, algorithm="sha256"):
    result = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def read_json(path):
    require(path.is_file() and not path.is_symlink(), f"Missing or linked evidence: {path}")
    return json.loads(path.read_text())


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MESA_SOURCE_SHA256 = "2a0d2f92c60e0962ef5f6039d3793424c6f39e49ba27ac04a5b21ca4ae012e15"
QT_SOURCE_NAME = "qt-everywhere-src-6.11.2.tar.xz"
MESA_SOURCE_NAME = "opengl32sw-64-mesa_12_0_rc2.7z"


def inventory(directory, link_prefix=None):
    require(
        directory.is_dir() and not directory.is_symlink(), f"Missing or linked tree: {directory}"
    )
    files, directories, links, derived_metadata = {}, set(), {}, {}

    def raise_walk_error(error):
        raise error

    for root, child_dirs, child_files in os.walk(
        directory, followlinks=False, onerror=raise_walk_error
    ):
        for child in sorted(child_dirs + child_files):
            path = Path(root) / child
            name = path.relative_to(directory).as_posix()
            if path.is_symlink():
                require(
                    link_prefix is not None and name.startswith(link_prefix),
                    f"Linked artifact input: {path}",
                )
                # Derived cache links are recorded as text and never followed or copied.
                links[name] = os.readlink(path)
            elif path.is_dir():
                directories.add(name)
            else:
                require(path.is_file(), f"Unsupported artifact entry: {path}")
                cache_name = name.removeprefix(link_prefix) if link_prefix is not None else None
                raw_archive = (
                    cache_name is not None
                    and "/" not in cache_name
                    and cache_name.endswith((".tar.xz", ".7z"))
                )
                if link_prefix is not None and name.startswith(link_prefix) and not raw_archive:
                    stat = path.stat()
                    derived_metadata[name] = {
                        "kind": "file",
                        "bytes": stat.st_size,
                        "mtime_ns": stat.st_mtime_ns,
                    }
                else:
                    files[name] = digest(path)
    return files, directories, links, derived_metadata


def copy_verified(source, destination, expected):
    require(source.is_file() and not source.is_symlink(), f"Missing or linked source: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    require(
        not destination.exists() and not destination.is_symlink(), f"Existing output: {destination}"
    )
    shutil.copy2(source, destination)
    require(
        digest(source) == expected and digest(destination) == expected,
        f"Copy changed bytes: {source}",
    )


def restore(artifact, recovered):
    artifact = artifact.expanduser().absolute()
    require(artifact.is_dir() and not artifact.is_symlink(), "Artifact work directory must be real")
    artifact = artifact.resolve()
    recovered = recovered.expanduser().absolute()
    require(
        not recovered.exists() and not recovered.is_symlink(),
        "Recovered work directory must be new",
    )
    recovered = recovered.resolve()
    require(
        recovered.parent == artifact.parent and recovered != artifact,
        "Recovery requires a fresh sibling work directory",
    )
    backport = load_module("qt_pdf_backport", Path(__file__).with_name("build_backport.py"))
    qualifier = load_module("qt_pdf_qualifier", Path(__file__).with_name("qualify_package.py"))
    require(
        not recovered.is_relative_to(backport.REPO_ROOT), "Recovery must be outside the repository"
    )
    for ancestor in (artifact, *artifact.parents, recovered, *recovered.parents):
        require(
            not (ancestor / "conda-meta").is_dir(), "Recovery must stay outside installed runtimes"
        )
    allowed = {
        "feedstock.tar.gz",
        "feedstock",
        "provenance.json",
        "recipe.diff",
        "build-scripts.diff",
        "build.json",
        "output",
    }
    require(
        {path.name for path in artifact.iterdir()} == allowed,
        "Artifact work directory has missing or unrelated inputs",
    )
    original_files, original_directories, original_links, original_derived_metadata = inventory(
        artifact, link_prefix="output/src_cache/"
    )
    preparation = read_json(artifact / "provenance.json")
    target = preparation["target_platform"]
    require(target == backport.native_platform(), "Recovery requires the matching native platform")
    sdk = preparation.get("macos_sdk")
    if sdk is not None:
        require(
            backport.macos_sdk(Path(sdk["path"]), target) == sdk,
            "Recorded SDK metadata differs from this runner",
        )
    require((artifact / "feedstock.tar.gz").is_file(), "Pinned feedstock archive is required")
    files, recipe_diff, expected = backport.expected_materialization(artifact, target, sdk)
    require(preparation == expected, "Original preparation differs from the reviewed manifest")
    require((artifact / "recipe.diff").read_text() == recipe_diff, "Original recipe diff changed")
    require(
        (artifact / "build-scripts.diff").read_text() == expected["build_script_diff"],
        "Original scheduling diff changed",
    )
    actual, directories, _, _ = inventory(artifact / "feedstock")
    expected_files = {name: backport.sha256(data) for name, data in files.items()}
    known_directories = {
        parent.as_posix()
        for name in files
        for parent in PurePosixPath(name).parents
        if parent.as_posix() != "."
    }
    require(directories <= known_directories, "Unknown materialized feedstock directory")
    require(actual.keys() <= expected_files.keys(), "Unknown materialized feedstock file")
    require(
        all(expected_files[name] == value for name, value in actual.items()),
        "Retained feedstock file changed",
    )
    hidden = {
        name for name in files if any(part.startswith(".") for part in PurePosixPath(name).parts)
    }
    require(len(hidden) == 21, "Pinned hidden-path set changed")
    missing = expected_files.keys() - actual.keys()
    require(missing <= hidden, "Missing visible feedstock file cannot be recovered")
    build = read_json(artifact / "build.json")
    require(
        build.get("status") == "built" and build.get("exit_code") == 0,
        "Original package build did not succeed",
    )
    relative_package = Path(build["package"])
    require(
        not relative_package.is_absolute() and ".." not in relative_package.parts,
        "Unexpected recorded package path",
    )
    package_name = relative_package.as_posix()
    require(package_name in original_files, "Recorded package is absent from artifact")
    require(
        original_files[package_name] == build["package_sha256"], "Original package SHA-256 changed"
    )
    source_root = artifact / "output/src_cache"
    require(source_root.is_dir() and not source_root.is_symlink(), "Linked or missing source cache")
    archives = [path for path in source_root.iterdir() if path.name.endswith(".tar.xz")]
    require(len(archives) == 1, "Expected one retained Qt source archive")
    source_archive = archives[0]
    require(
        source_archive.is_file()
        and not source_archive.is_symlink()
        and source_archive.name.endswith(QT_SOURCE_NAME),
        "Qt raw source archive must be the expected regular nonlinked file",
    )
    require(
        digest(source_archive, "md5") == qualifier.QT_SOURCE_MD5,
        "Qt source archive differs from recipe checksum",
    )
    sources = {source_archive.name: original_files["output/src_cache/" + source_archive.name]}
    mesa_archives = [path for path in source_root.iterdir() if path.name.endswith(".7z")]
    require(len(mesa_archives) <= 1, "Expected at most one retained Mesa source archive")
    require(
        target != "win-64" or len(mesa_archives) == 1,
        "Windows recovery requires the retained Mesa recipe source archive",
    )
    if mesa_archives:
        mesa_archive = mesa_archives[0]
        require(
            mesa_archive.is_file()
            and not mesa_archive.is_symlink()
            and mesa_archive.name.endswith(MESA_SOURCE_NAME),
            "Mesa raw source archive must be the expected regular nonlinked file",
        )
        require(digest(mesa_archive) == MESA_SOURCE_SHA256, "Mesa source recipe checksum changed")
        sources[mesa_archive.name] = MESA_SOURCE_SHA256
    retained_files = {
        name: value
        for name, value in original_files.items()
        if not name.startswith("output/src_cache/")
        or name.removeprefix("output/src_cache/") in sources
    }
    require(
        {
            name
            for name in original_files
            if name.startswith("output/") and not name.startswith("output/src_cache/")
        }
        == {package_name},
        "Unrelated files in artifact output tree",
    )
    allowed_output_dirs = {
        "output",
        "output/src_cache",
        *{
            parent.as_posix()
            for parent in PurePosixPath(package_name).parents
            if parent.as_posix() != "."
        },
    }
    require(
        {
            name
            for name in original_directories
            if name.startswith("output") and not name.startswith("output/src_cache/")
        }
        <= allowed_output_dirs,
        "Unrelated directory in artifact output tree",
    )
    excluded_cache = dict(original_derived_metadata)
    excluded_cache.update(
        {
            name: {"kind": "directory"}
            for name in original_directories
            if name.startswith("output/src_cache/")
        }
    )
    excluded_cache.update(
        {name: {"kind": "symlink", "target": target} for name, target in original_links.items()}
    )
    recovered.mkdir(parents=True, exist_ok=False)
    report = {
        "schema_version": 1,
        "purpose": "Authenticated artifact transport recovery",
        "artifact_work_dir": str(artifact),
        "recovered_work_dir": str(recovered),
        "recovered_hidden_paths": sorted(missing),
        "original_file_sha256": original_files,
        "original_link_metadata": original_links,
        "copied_source_archive_sha256": sources,
        "excluded_derived_source_cache": excluded_cache,
        "original_snapshot_method": {
            "authenticated_inputs": "SHA-256 of retained inputs and raw recipe archives",
            "excluded_derived_files": "Size and modification time only; content not authenticated",
            "excluded_links": "Link target text only; never followed",
            "directories": "Relative path names",
        },
        "qt_source_recipe_md5": qualifier.QT_SOURCE_MD5,
        "mesa_source_recipe_sha256": MESA_SOURCE_SHA256 if mesa_archives else None,
        "qualified": False,
        "status": "running",
    }
    try:
        copy_verified(
            artifact / "feedstock.tar.gz", recovered / "feedstock.tar.gz", backport.ARCHIVE_SHA256
        )
        rebuilt = backport.prepare(recovered, target, sdk)
        require(rebuilt == preparation, "Rebuilt preparation differs from original manifest")
        copy_verified(
            artifact / "build.json", recovered / "build.json", original_files["build.json"]
        )
        copy_verified(artifact / package_name, recovered / package_name, build["package_sha256"])
        for name, expected_sha in sources.items():
            copy_verified(source_root / name, recovered / "output/src_cache" / name, expected_sha)
        report["build_evidence"] = qualifier.build_evidence(recovered / "build.json", backport)
        recovered_files, _, _, _ = inventory(recovered)
        for name, value in retained_files.items():
            require(
                recovered_files.get(name) == value,
                f"Recovery changed retained artifact bytes: {name}",
            )
        report["recovered_file_sha256"] = recovered_files
        report["status"] = "recovered"
    except (OSError, ValueError, KeyError) as error:
        report["status"] = "failed"
        report["error"] = str(error)
    finally:
        try:
            after, after_directories, after_links, after_derived_metadata = inventory(
                artifact, link_prefix="output/src_cache/"
            )
            report["authenticated_original_inputs_unchanged"] = after == original_files
            report["derived_metadata_unchanged"] = (
                after_directories == original_directories
                and after_links == original_links
                and after_derived_metadata == original_derived_metadata
            )
            report["original_unchanged"] = (
                report["authenticated_original_inputs_unchanged"]
                and report["derived_metadata_unchanged"]
            )
        except (OSError, ValueError) as error:
            report["original_unchanged"] = False
            report["original_snapshot_error"] = str(error)
        if not report["original_unchanged"]:
            report["status"] = "failed"
            report["error"] = "Original artifact changed during recovery"
        (recovered / "transport-recovery.json").write_text(json.dumps(report, indent=2) + "\n")
    require(report["status"] == "recovered", report.get("error", "Artifact recovery failed"))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-work-dir", type=Path, required=True)
    parser.add_argument("--recovered-work-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = restore(args.artifact_work_dir, args.recovered_work_dir)
    except (OSError, ValueError, KeyError, ImportError) as error:
        print(f"Artifact recovery failed: {error}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "recovered",
                "recovered_hidden_paths": len(report["recovered_hidden_paths"]),
                "recovered_work_dir": report["recovered_work_dir"],
                "qualified": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
