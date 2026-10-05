# SPDX-License-Identifier: LGPL-2.1-or-later
"""Restore authenticated successful LibPack build artifacts into fresh native roots.

The caller downloads the three whole ZIPs from the selected GitHub run. This
helper queries only fixed-repository API metadata, checks their whole-ZIP SHA256,
and restores the original c/l paths without running a Qt build or promoting it.
Passed, capture-bound Linux Qt diagnostics are mandatory. Native FreeCAD checks
must still run separately against the restored SDKs.
"""

import argparse
import json
import ntpath
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tarfile
import urllib.request
import zipfile

import build_libpack_backport as adapter
import qualify_libpack_backport as checks
import qualify_libpack_native as native

REPOSITORY = "zukomgwili/FreeCAD"
MAX_BYTES = 48 * 1024**3
MAX_MEMBERS = 1_000_000
ARCHIVES = {
    "candidate-sdk.tar.gz": {"candidate"},
    "corresponding-sources.tar.gz": {
        "qt",
        "libpack",
        "empty-outline.patch",
        "libpack-qt-ownership.json",
    },
    "build-evidence.tar.gz": {"b"},
    "native-evidence.tar.gz": {"evidence", "compiler.cmd"},
}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def api(endpoint):
    result = subprocess.run(
        ["gh", "api", f"repos/{REPOSITORY}/{endpoint}"], capture_output=True, check=True
    )
    adapter.require(len(result.stdout) < 4 * 1024**2, "Oversized API metadata")
    return json.loads(result.stdout)


def authenticated_artifacts(run_id, sdk, inputs):
    adapter.require(run_id > 0, "Invalid run ID")
    run = api(f"actions/runs/{run_id}")
    adapter.require(
        run["repository"]["full_name"] == REPOSITORY
        and run["path"]
        in (
            ".github/workflows/qt_pdf_libpack_backport.yml",
            ".github/workflows/qt_pdf_backport.yml",
        )
        and run["status"] == "completed"
        and re.fullmatch(r"[0-9a-f]{40}", run["head_sha"]),
        "Require a completed matching SDK workflow run",
    )
    artifacts = api(f"actions/runs/{run_id}/artifacts?per_page=100")
    adapter.require(artifacts["total_count"] <= 100, "Paginated artifact inventory unsupported")
    receipts = {}
    for kind, path in inputs.items():
        name = f"qt-pdf-libpack-{kind}-{sdk}"
        matches = [item for item in artifacts["artifacts"] if item["name"] == name]
        adapter.require(len(matches) == 1, f"Missing/ambiguous artifact: {name}")
        item = matches[0]
        expected = item.get("digest", "")
        adapter.require(
            not item["expired"]
            and item["workflow_run"]["id"] == run_id
            and item["workflow_run"]["head_sha"] == run["head_sha"]
            and re.fullmatch(r"sha256:[0-9a-f]{64}", expected)
            and path.is_file()
            and adapter.digest(path) == expected.removeprefix("sha256:"),
            f"API/whole-ZIP authentication differs: {name}",
        )
        receipts[kind] = {"id": item["id"], "name": name, "sha256": expected[7:]}
    return run, receipts


def member_name(value):
    path = adapter.safe_relative(value.removesuffix("/"))
    adapter.require(not ntpath.isreserved(str(path)), "Unsafe Windows archive path")
    return path


def extract_zip(archive, destination):
    destination.mkdir()
    names, total = set(), 0
    with zipfile.ZipFile(archive) as stream:
        adapter.require(len(stream.infolist()) <= MAX_MEMBERS, "Too many ZIP members")
        for entry in stream.infolist():
            name = member_name(entry.filename)
            normalized = str(name).casefold()
            mode = stat.S_IFMT(entry.external_attr >> 16)
            adapter.require(
                normalized not in names
                and mode in (0, stat.S_IFREG, stat.S_IFDIR)
                and not entry.flag_bits & 1,
                "Duplicate/linked/special/encrypted ZIP member",
            )
            names.add(normalized)
            total += entry.file_size
            adapter.require(total <= MAX_BYTES, "Oversized ZIP content")
            output = destination / name
            if entry.is_dir():
                adapter.require(mode != stat.S_IFREG, "Inconsistent ZIP directory")
                output.mkdir(parents=True, exist_ok=True)
            else:
                adapter.require(mode != stat.S_IFDIR, "Inconsistent ZIP file")
                output.parent.mkdir(parents=True, exist_ok=True)
                with stream.open(entry) as source, output.open("xb") as target:
                    shutil.copyfileobj(source, target, 1024 * 1024)
                adapter.require(output.stat().st_size == entry.file_size, "Short ZIP member")


def extract_tar(archive, destination, index, roots):
    """Materialize only regular files/directories and earlier regular-file links."""
    seen, regular, actual, total = set(), {}, {}, 0
    with tarfile.open(archive, "r:gz") as stream:
        for count, entry in enumerate(stream):
            name = member_name(entry.name)
            key = str(name)
            adapter.require(
                count < MAX_MEMBERS and key.casefold() not in seen and name.parts[0] in roots,
                "Duplicate/excess/out-of-scope TAR member",
            )
            seen.add(key.casefold())
            output = destination / name
            if entry.isdir():
                output.mkdir(parents=True, exist_ok=True)
                continue
            adapter.require(entry.isreg() or entry.islnk(), "Linked/device/special TAR member")
            adapter.require(key in index, "Unindexed TAR file")
            adapter.require(not output.exists(), "TAR file collides with existing restored content")
            output.parent.mkdir(parents=True, exist_ok=True)
            if entry.islnk():
                target = str(member_name(entry.linkname))
                adapter.require(target in regular, "Hardlink must name an earlier regular file")
                total += regular[target].stat().st_size
                adapter.require(total <= MAX_BYTES, "Oversized TAR content")
                shutil.copy2(regular[target], output)
            else:
                adapter.require(entry.size >= 0, "Negative TAR file size")
                total += entry.size
                adapter.require(total <= MAX_BYTES, "Oversized TAR content")
                with stream.extractfile(entry) as source, output.open("xb") as target:
                    shutil.copyfileobj(source, target, 1024 * 1024)
                regular[key] = output
            actual[key] = {"size": output.stat().st_size, "sha256": adapter.digest(output)}
            adapter.require(actual[key] == index[key], "TAR file bytes differ from index")
    adapter.require(actual == index, "Incomplete TAR file index")


def exact_times(root, inventory, helper):
    actual = helper.inventory(root)
    adapter.require(
        actual["directories"] == inventory["directories"]
        and set(actual["files"]) == set(inventory["files"]),
        "SDK membership differs",
    )
    for name, expected in inventory["files"].items():
        path = root / adapter.safe_relative(name)
        adapter.require(
            all(actual["files"][name][key] == expected[key] for key in ("size", "sha256")),
            "SDK bytes differ before restoring authenticated timestamps",
        )
        os.utime(path, ns=(path.stat().st_atime_ns, expected["mtime_ns"]))
    adapter.require(helper.inventory(root) == inventory, "Exact restored SDK inventory differs")


def restore(args, helper):
    adapter.require(os.environ.get("GITHUB_ACTIONS") == "true", "Use a disposable native CI job")
    environment = {
        **adapter.source_environment(os.environ.copy()),
        "GIT_OPTIONAL_LOCKS": "0",
    }
    work, transport = helper.real_path(args.work_dir), helper.real_path(args.transport_work_dir)
    adapter.require(
        work == Path(work.anchor) / "c" and not work.exists(),
        "Original c root must be fresh",
    )
    inputs = {
        "candidate": helper.real_path(args.candidate_zip),
        "capture": helper.real_path(args.capture_zip),
        "candidate-diagnostics": helper.real_path(args.diagnostics_zip),
    }
    run, artifacts = authenticated_artifacts(args.run_id, args.sdk, inputs)
    for path in inputs.values():
        adapter.require(path.stat().st_nlink == 1, "Artifact ZIP must be an independent file")
        adapter.separate_path(work, path)
        adapter.separate_path(transport, path)
    adapter.separate_path(work, transport)
    adapter.require(
        transport.is_relative_to(helper.real_path(Path(os.environ["RUNNER_TEMP"]))),
        "Transport must be fresh under RUNNER_TEMP",
    )
    transport = helper.fresh_work(transport)
    for kind, path in inputs.items():
        extract_zip(path, transport / kind)
    payload, capture = transport / "candidate", transport / "capture"
    retention = read_json(payload / "retention.json")
    diagnosis = read_json(transport / "candidate-diagnostics/libpack-candidate-diagnostics.json")
    captured = read_json(capture / "capture.json")
    preparation = read_json(capture / "candidate-preparation.json")
    sdk = helper.sdk_identity(args.sdk)
    baseline_work = helper.real_path(Path(preparation["original_baseline"]["root"]).parent)
    adapter.require(
        retention["commit"] == run["head_sha"]
        and retention["run_url"] == f"https://github.com/{REPOSITORY}/actions/runs/{args.run_id}"
        and retention["sdk"] == args.sdk
        and retention["qualified"] is False
        and retention["promotion"] is False
        and retention["build_only"] is True
        and retention["build_status"] == "built"
        and retention["candidate_capture_outcome"] == "success"
        and retention["candidate_pdf_tested"] is True
        and diagnosis["status"] == "passed"
        and diagnosis["qt_only_passed"] is True
        and diagnosis["qualified"] is False
        and diagnosis["comparison"]["passed"] is True
        and len(diagnosis["comparison"]["cases"]) == 66
        and set(diagnosis["comparison"]["baseline_reproduced_by_device"])
        == {"qprinter", "qpdfwriter"}
        and diagnosis["sdk"] == sdk
        and diagnosis["native_capture_sha256"] == adapter.digest(capture / "capture.json")
        and captured["status"] == "captured"
        and captured["helper_sha256"] == adapter.digest(Path(checks.__file__))
        and captured["adapter_sha256"] == adapter.digest(Path(adapter.__file__))
        and captured["baseline_helper_sha256"] == adapter.digest(Path(helper.__file__))
        and captured["sdk"] == preparation["sdk"] == sdk
        and retention["physical_work_dir"] == preparation["work"] == str(work)
        and work == Path(work.anchor) / "c"
        and baseline_work == Path(work.anchor) / "l"
        and helper.native_machine() == preparation["host"],
        "Run/diagnostics/capture/original native roots differ",
    )
    adapter.separate_path(transport, baseline_work)
    adapter.require(not work.exists() and not baseline_work.exists(), "SDK roots must be fresh")
    adapter.require(set(retention["archives"]) == set(ARCHIVES), "Incomplete archive inventory")
    expected_files = {"retention.json"}
    for name, receipt in retention["archives"].items():
        expected_files |= {name, receipt["file_index"]}
        archive, index = payload / name, payload / adapter.safe_relative(receipt["file_index"])
        adapter.require(
            archive.stat().st_size == receipt["size"]
            and adapter.digest(archive) == receipt["sha256"]
            and adapter.digest(index) == receipt["file_index_sha256"],
            "Retained archive/index differs",
        )
    adapter.require(
        {path.relative_to(payload).as_posix() for path in payload.rglob("*") if path.is_file()}
        == expected_files,
        "Unknown archive payload file",
    )
    work = helper.fresh_work(work)
    for name, roots in ARCHIVES.items():
        receipt = retention["archives"][name]
        index = read_json(payload / receipt["file_index"])
        adapter.require(len(index) == receipt["file_count"], "Archive count differs")
        extract_tar(payload / name, work, index, roots)
    before, candidate = read_json(work / "evidence/sdk-before.json"), read_json(
        work / "evidence/candidate-after.json"
    )
    exact_times(work / "candidate", candidate, helper)
    baseline_work = helper.fresh_work(baseline_work)
    shutil.copytree(capture / "baseline", baseline_work / "evidence", copy_function=shutil.copy2)
    archive = baseline_work / sdk["filename"]
    request = urllib.request.Request(sdk["url"], headers={"User-Agent": "FreeCAD-SDK-restore"})
    with urllib.request.urlopen(request, timeout=60) as source, archive.open("xb") as target:
        length = 0
        for block in iter(lambda: source.read(1024 * 1024), b""):
            length += len(block)
            adapter.require(length <= sdk["size"], "Oversized official SDK archive")
            target.write(block)
    adapter.require(
        archive.stat().st_size == sdk["size"] and adapter.digest(archive) == sdk["sha256"],
        "Official SDK archive differs",
    )
    listing = helper.command(["7z", "l", "-slt", "-sccUTF-8", str(archive)], transport, "sdk-list")
    helper.archive_members(listing["stdout"].replace("\r\n", "\n"), sdk["directory"])
    helper.command(
        ["7z", "x", "-y", str(archive), "-o" + str(baseline_work)], transport, "sdk-extract"
    )
    baseline = baseline_work / sdk["directory"]
    adapter.require(
        helper.inventory(baseline) == before, "Reextracted official SDK inventory differs"
    )
    shutil.copytree(baseline, work / "baseline", copy_function=shutil.copy2)
    shutil.copy2(archive, work / sdk["filename"])
    native.validate_qt_capture(capture, work, helper)
    build = read_json(work / "evidence/build.json")
    initialized = set(build["source"]["repositories"]) - {"."}
    installed = adapter.install_paths(
        work / "b/r/install_manifest.txt", work / "candidate", helper, initialized
    )
    aliases, alias_receipt = adapter.companion_aliases(
        work / "b/r", work / "candidate", installed, initialized, helper
    )
    recorded_aliases = read_json(work / "evidence/qt-versioned-aliases.json")
    # Transported hardlinks become independent copies; every source/log/byte
    # proof remains identical, while only their physical identity can change.
    for receipt in (alias_receipt, recorded_aliases):
        for entry in receipt["entries"]:
            for key in ("same_file_identity", "base_nlink", "alias_nlink"):
                entry.pop(key)
    adapter.require(alias_receipt == recorded_aliases, "Restored install(CODE) proof differs")
    adapter.require(
        installed == set(build["admitted_qt_paths"])
        and aliases == set(build["admitted_companion_alias_paths"]),
        "Actual restored installation admission differs",
    )
    adapter.require(
        adapter.digest(work / "b/r/CMakeCache.txt") == build["build_cache_sha256"]
        and adapter.digest(work / "b/r/install_manifest.txt")
        == build["qt_install_manifest_sha256"],
        "Actual restored cache/manifest differs",
    )
    admitted = checks.admitted_paths(build, work / "evidence", candidate)
    adapter.require(
        adapter.preserved_sdk(before, candidate, admitted, initialized)
        == build["changed_qt_paths"],
        "Restored Qt-only changes differ from the original build",
    )
    adapter.verify_sources(work / "libpack", sdk["release"], helper)
    adapter.require(
        adapter.digest(work / "empty-outline.patch") == adapter.PATCH_SHA
        and adapter.digest(work / "libpack-qt-ownership.json") == adapter.OWNERSHIP_SHA
        and adapter.digest(work / "qt/qtbase/src/gui/painting/qpdf.cpp") == adapter.QPDF_PATCHED,
        "Restored retained source pins differ",
    )
    repositories = adapter.qt_repositories(work / "qt", transport, "git", environment=environment)
    adapter.require(
        repositories == build["source"]["repositories"], "Restored source Git identities differ"
    )
    adapter.clean_tracked(
        work / "qt", repositories, transport, "git", patched=True, environment=environment
    )
    source_receipt = retention["archives"]["corresponding-sources.tar.gz"]
    for name, expected in read_json(payload / source_receipt["file_index"]).items():
        path = helper.real_path(work / adapter.safe_relative(name))
        adapter.require(
            path.stat().st_size == expected["size"] and adapter.digest(path) == expected["sha256"],
            "Restored corresponding source changed during read-only validation",
        )
    adapter.require(
        all(adapter.digest(path) == artifacts[kind]["sha256"] for kind, path in inputs.items()),
        "Original artifact ZIP changed during restoration",
    )
    report = {
        "status": "restored",
        "qualified": False,
        "native_freecad_tested": False,
        "sdk": sdk,
        "run_id": args.run_id,
        "head_sha": run["head_sha"],
        "artifact_api_receipts": artifacts,
        "original_zips_unchanged_sha256": True,
        "retention_sha256": adapter.digest(payload / "retention.json"),
        "qt_capture_sha256": adapter.digest(capture / "capture.json"),
        "qt_diagnostics_sha256": adapter.digest(
            transport / "candidate-diagnostics/libpack-candidate-diagnostics.json"
        ),
        "api_scope": "Fixed-repository GitHub metadata and SHA256 of caller-downloaded complete ZIPs",
        "work_dir": str(work),
        "qt_evidence_dir": str(capture),
        "baseline_work_dir": str(baseline_work),
        "candidate_timestamps": "Restored from authenticated exact mtime_ns after content checks",
        "companion_aliases_materialized_as_copies": sorted(aliases),
        "helper_sha256": adapter.digest(Path(__file__)),
    }
    adapter.write_json(transport / "restoration.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--sdk", choices=adapter.baseline_helper().SDK_KEYS, required=True)
    for name in (
        "candidate-zip",
        "capture-zip",
        "diagnostics-zip",
        "work-dir",
        "transport-work-dir",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(restore(args, adapter.baseline_helper())))
    except (
        OSError,
        ValueError,
        KeyError,
        subprocess.SubprocessError,
        tarfile.TarError,
        zipfile.BadZipFile,
    ) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
