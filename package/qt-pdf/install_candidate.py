# SPDX-License-Identifier: LGPL-2.1-or-later
"""Install a built Qt backport in a fresh copy of a managed baseline runtime.

Requires micromamba 2.9.0. Its clone operation relinks exact baseline packages
with prefix relocation; --always-copy prevents links to baseline/cache files.
The replacement is solved through a private indexed channel, because direct
archive MatchSpecs do not expose package dependencies to micromamba's solver.
Every other baseline package is pinned exactly. Installation is not qualification.
"""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    result = hashlib.sha256()
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


def managed_records(prefix):
    metadata = prefix / "conda-meta"
    require(metadata.is_dir() and not metadata.is_symlink(), "Baseline needs real conda metadata")
    records = {}
    for path in sorted(metadata.glob("*.json")):
        record = read_json(path)
        name = record["name"]
        require(name not in records, f"Duplicate installed package: {name}")
        require(re.fullmatch(r"[a-z0-9_.-]+", name), f"Invalid package name: {name}")
        for key in ("version", "build"):
            require(
                re.fullmatch(r"[A-Za-z0-9_.+!-]+", record[key]),
                f"Cannot form an exact MatchSpec for {name} {key}",
            )
        require(record.get("url"), f"Clone requires the original package URL: {name}")
        require(record.get("sha256") or record.get("md5"), f"Missing package checksum: {name}")
        records[name] = record
    require(records, "No installed baseline packages")
    return records


def identity(records):
    # Clone metadata can omit a redundant MD5 when its URL carries SHA-256.
    # Compare archive identity, while retaining full metadata separately.
    keys = ("name", "version", "build", "subdir")
    return {
        name: {
            **{key: record.get(key) for key in keys},
            "checksum": (
                {"sha256": record["sha256"]} if record.get("sha256") else {"md5": record["md5"]}
            ),
        }
        for name, record in sorted(records.items())
    }


def baseline_snapshot(prefix, records):
    metadata = {}
    for path in sorted((prefix / "conda-meta").rglob("*")):
        require(not path.is_symlink(), f"Linked baseline metadata: {path}")
        if path.is_file():
            metadata[path.relative_to(prefix).as_posix()] = digest(path)
    qt_files = {}
    for name, record in records.items():
        if not name.startswith(("qt", "pyside", "shiboken")):
            continue
        for relative in record["files"]:
            parts = PurePosixPath(relative)
            require(
                not parts.is_absolute() and ".." not in parts.parts and "\\" not in relative,
                f"Unexpected Qt package path: {relative}",
            )
            path = prefix / relative
            require(
                path.resolve(strict=True).is_relative_to(prefix) and path.is_file(),
                f"Missing or external baseline Qt file: {path}",
            )
            qt_files[relative] = {
                "sha256": digest(path),
                "symlink": os.readlink(path) if path.is_symlink() else None,
            }
    require(qt_files, "No baseline Qt files to protect")
    return {"metadata": metadata, "qt_files": qt_files}


def fresh_paths(baseline, candidate):
    candidate = candidate.expanduser().absolute()
    require(not candidate.exists() and not candidate.is_symlink(), "Candidate prefix must be new")
    candidate = candidate.resolve()
    require(
        not candidate.is_relative_to(baseline) and not baseline.is_relative_to(candidate),
        "Candidate and baseline must be separate directory trees",
    )
    require(
        not candidate.is_relative_to(REPO_ROOT) and candidate != Path(candidate.anchor),
        "Candidate must be outside the repository and filesystem root",
    )
    for ancestor in candidate.parents:
        require(not (ancestor / "conda-meta").is_dir(), "Candidate is inside an installed runtime")
    evidence = candidate.with_name(candidate.name + ".install-evidence")
    require(
        not evidence.exists() and not evidence.is_symlink(), "Installation evidence must be new"
    )
    return candidate, evidence


def command_result(command, evidence, label):
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    (evidence / (label + ".log")).write_text(completed.stdout + completed.stderr)
    require(completed.returncode == 0, f"{label} failed; see {evidence / (label + '.log')}")
    return completed.stdout.strip()


def remove_private_directory(evidence, name):
    path = evidence / name
    require(not path.is_symlink(), f"Linked private installer directory: {path}")
    require(path.parent.resolve() == evidence, "Cleanup must remain inside installer evidence")
    if path.exists():
        require(path.is_dir(), f"Unexpected private installer artifact: {path}")
        shutil.rmtree(path)


def make_channel(tool, package, package_sha, target, evidence, common):
    unpacked = evidence / "unpacked"
    command = [tool, "package", "extract", str(package), str(unpacked), *common]
    command_result(command, evidence, "extract-package")
    index = read_json(unpacked / "info/index.json")
    require(
        index.get("name") == "qt6-main"
        and index.get("version") == "6.11.2"
        and index.get("build_number") == 1
        and index.get("subdir") == target
        and index.get("build") == package.name[len("qt6-main-6.11.2-") : -len(".conda")],
        "Built archive metadata differs from its recorded package identity",
    )
    require(
        isinstance(index.get("depends"), list)
        and index["depends"]
        and all(isinstance(value, str) for value in index["depends"]),
        "Qt package must expose its actual dependency declarations",
    )
    (evidence / "package-index.json").write_text(json.dumps(index, indent=2) + "\n")
    channel = evidence / "channel"
    directory = channel / target
    directory.mkdir(parents=True)
    copied = directory / package.name
    shutil.copyfile(package, copied)
    require(digest(copied) == package_sha, "Private channel copy checksum differs")
    index.update({"sha256": package_sha, "size": copied.stat().st_size})
    (directory / "repodata.json").write_text(
        json.dumps(
            {"info": {"subdir": target}, "packages": {}, "packages.conda": {copied.name: index}}
        )
        + "\n"
    )
    (channel / "noarch").mkdir()
    (channel / "noarch/repodata.json").write_text(
        json.dumps({"info": {"subdir": "noarch"}, "packages": {}, "packages.conda": {}}) + "\n"
    )
    remove_private_directory(evidence, "unpacked")
    return channel, index, command


def install(args):
    baseline = args.baseline_prefix.expanduser().resolve(strict=True)
    candidate, evidence = fresh_paths(baseline, args.candidate_prefix)
    records = managed_records(baseline)
    require(
        records.get("qt6-main", {}).get("version") == "6.11.2"
        and records["qt6-main"].get("build_number") == 0,
        "Baseline must contain the original Qt 6.11.2 build-0 package",
    )
    require(
        records.get("python", {}).get("version", "").startswith("3.13.")
        and records.get("pyside6", {}).get("version") == "6.11.2",
        "Baseline needs Python 3.13 and PySide6 6.11.2 for native FreeCAD qualification",
    )
    backport = load_module("qt_pdf_backport", Path(__file__).with_name("build_backport.py"))
    qualifier = load_module("qt_pdf_qualifier", Path(__file__).with_name("qualify_package.py"))
    build_evidence = qualifier.build_evidence(args.package_build_json, backport, args.macos_sdk)
    build_json = Path(build_evidence["build_json"])
    package = Path(build_evidence["package"])
    package_sha = build_evidence["package_sha256"]
    target = build_evidence["preparation"]["target_platform"]
    tool = shutil.which(args.micromamba)
    require(tool is not None, "Cannot find micromamba")
    version = subprocess.run(
        [tool, "--version"], check=True, capture_output=True, text=True
    ).stdout.strip()
    require(version == "2.9.0", "Expected the reviewed micromamba 2.9.0 CLI")
    before = baseline_snapshot(baseline, records)
    evidence.mkdir(parents=True, exist_ok=False)
    (evidence / "baseline-before.json").write_text(json.dumps(before, indent=2) + "\n")
    configuration = evidence / "mambarc.json"
    configuration.write_text(
        json.dumps({"pkgs_dirs": [str(evidence / "cache")], "envs_dirs": [str(evidence / "envs")]})
        + "\n"
    )
    common = ["--no-env", "--rc-file", str(configuration)]
    runtime = [*common, "--root-prefix", str(evidence / "root"), "--prefix", str(candidate)]
    report = {
        "schema_version": 1,
        "baseline_prefix": str(baseline),
        "candidate_prefix": str(candidate),
        "micromamba_version": version,
        "package_build_json": str(build_json),
        "package_build_json_sha256": digest(build_json),
        "package_sha256": package_sha,
        "build_evidence": build_evidence,
        "status": "running",
        "qualified": False,
        "commands": [],
        "baseline_packages": identity(records),
    }
    try:
        channel, index, extract_command = make_channel(
            tool, package, package_sha, target, evidence, common
        )
        report["commands"].append(extract_command)
        report["package_index"] = index
        clone = [
            tool,
            "create",
            *runtime,
            "--clone",
            str(baseline),
            "--always-copy",
            "--yes",
            "--json",
        ]
        report["commands"].append(clone)
        command_result(clone, evidence, "clone-baseline")
        require(
            identity(managed_records(candidate)) == identity(records),
            "Clone changed baseline package identities",
        )
        remove_private_directory(evidence, "cache")
        specs = evidence / "non-qt-specs.txt"
        specs.write_text(
            "".join(
                f"{name}=={r['version']}={r['build']}\n"
                for name, r in sorted(records.items())
                if name != "qt6-main"
            )
        )
        replacement = [
            tool,
            "install",
            *runtime,
            "--override-channels",
            "--channel",
            channel.as_uri(),
            "--channel",
            "conda-forge",
            "--strict-channel-priority",
            "--always-copy",
            "--yes",
            "--json",
            "--file",
            str(specs),
            f"{channel.as_uri()}::qt6-main==6.11.2={index['build']}",
        ]
        report["commands"].append(replacement)
        command_result(replacement, evidence, "install-candidate")
        remove_private_directory(evidence, "cache")
        installed = managed_records(candidate)
        unchanged = lambda values: {
            name: value for name, value in identity(values).items() if name != "qt6-main"
        }
        require(
            unchanged(installed) == unchanged(records),
            "Solver changed non-Qt baseline package identities",
        )
        require(digest(package) == package_sha, "Built package changed during installation")
        report["package_evidence"] = qualifier.package_evidence(
            build_json, candidate, backport, args.macos_sdk
        )
        report["candidate_packages"] = identity(installed)
        metadata = evidence / "candidate-conda-meta"
        metadata.mkdir()
        for path in (candidate / "conda-meta").iterdir():
            require(path.is_file() and not path.is_symlink(), "Unexpected candidate metadata entry")
            shutil.copyfile(path, metadata / path.name)
        report["status"] = "installed"
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        report["status"] = "failed"
        report["error"] = str(error)
    finally:
        try:
            for directory in ("cache", "unpacked"):
                remove_private_directory(evidence, directory)
            copied_package = evidence / "channel" / target / package.name
            require(not copied_package.is_symlink(), "Linked private package copy")
            if copied_package.exists():
                copied_package.unlink()
            report["private_package_copies_removed"] = True
        except (OSError, ValueError) as error:
            report["status"] = "failed"
            report["error"] = f"Private installer cleanup failed: {error}"
        try:
            after = baseline_snapshot(baseline, managed_records(baseline))
            (evidence / "baseline-after.json").write_text(json.dumps(after, indent=2) + "\n")
            report["baseline_unchanged"] = before == after
        except (OSError, ValueError, KeyError) as error:
            report["baseline_unchanged"] = False
            report["baseline_snapshot_error"] = str(error)
        if not report["baseline_unchanged"]:
            report["status"] = "failed"
            report["error"] = "Baseline metadata or Qt files changed during installation"
        (evidence / "installation.json").write_text(json.dumps(report, indent=2) + "\n")
    require(report["status"] == "installed", report.get("error", "Candidate installation failed"))
    return candidate, evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-prefix", type=Path, required=True)
    parser.add_argument("--package-build-json", type=Path, required=True)
    parser.add_argument("--candidate-prefix", type=Path, required=True)
    parser.add_argument("--micromamba", default="micromamba")
    parser.add_argument(
        "--macos-sdk", type=Path, help="Relocated SDK with the recorded metadata digest"
    )
    args = parser.parse_args()
    try:
        candidate, evidence = install(args)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f"Candidate installation failed: {error}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {"candidate_prefix": str(candidate), "evidence": str(evidence), "qualified": False}
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
