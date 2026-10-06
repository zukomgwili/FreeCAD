# SPDX-License-Identifier: LGPL-2.1-or-later
"""Restore one pinned failed LibPack install and revalidate its finite ownership.

The original Qt compilation/install completed, but post-install ownership failed.
This distinct route preserves that failure and every historical source/receipt;
it writes a separate current installation admission. It never compiles Qt,
regenerates passed baseline diagnostics, or claims pending runtime tests passed.
Complete caller-downloaded ZIPs and native physical roots are mandatory.
"""

import argparse
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile

import build_libpack_backport as adapter
import restore_libpack_candidate as transport

RUN_ID = 37254793061
HEAD = "ba37708eecef736d9caafdbae5f07618887d675b"
ERROR = "ValueError: Unknown/ambiguous Qt ownership: bin/qt-cmake.bat"
OLD_ADAPTER = "fc28ad59cda3dd02be48cb70ddb8dc80b186f891805e4fad73a82572d83d72d4"
OLD_OWNERSHIP = "c0a7fab7a2d0646e00044c0c5b554db0b977e2ebc265403fe91ce88f22992212"
BASELINE_HELPER = "b397fed4470e0f1e171f1829e9074d9005178d614cf0e0488852c0a8e4a44621"
PREPARATION_LOG_UPDATE = {
    "path": "qt-submodules.log",
    "initial_sha256": "5d53175e4412c3b70d189e81dfd5798bdbb25a594da9b4496735ab7a8bd38844",
    "retained_sha256": "ddd618b9be64d2419edaf1c361f7812fa208126c48a32955664fad3834f93a35",
    "reason": "Original patch hook refreshes Git status after nested submodule initialization",
}
PINS = {
    "3.5.3-x64": {
        "job_id": 111589467044,
        "runner": "windows-2022",
        "drive": "D:",
        "build_sha256": "57cfaad7d161579e12b1f5062cbb9776c203680b533c03af78b9b0776dd2c7c6",
        "cache_sha256": "785eced84a276e49cb9dcbae6b903348dc8c877d34338b426aab1d0c3538add5",
        "retention_sha256": "17f5789a0c8d1bd7bb01ec6649c28277ef47d9fe61a0f358b926dd474ceaab9d",
        "preparation_sha256": "a578b3efac9aa102a5b883c71af57572359e56adfd25fdb34b07fa129f520bca",
        "install_sha256": "95573323365166e82451e04d435088176511661b3ffe004bba585a5896f5e002",
        "source_index_sha256": "4f72d701cacb1230928dfd3853241c9b85fe3029e392a3ee97e98d359ac01cc0",
        "artifacts": {
            "candidate": (
                11324361949,
                2374302347,
                "448ff6afcca354f34e6615fd1082aef90937e49a4403127b35bfa4e9930cf5b8",
            ),
            "baseline": (
                11323934407,
                7732352,
                "2ffba579500233d1506a07d168bf3d4e38cbd6f3521fabe2be5f67a9ee6d0f08",
            ),
            "build-evidence": (
                11324203314,
                6333834,
                "bd52c8b992c032929d5989c8f4f229eecab1803833ca28cb93abcb690caf5ce5",
            ),
        },
    },
    "3.5.5-x64": {
        "job_id": 111589467052,
        "runner": "windows-2022",
        "drive": "D:",
        "build_sha256": "2d7da1804968db077babadeebbf9edd24e0acee43f9958fbefb1d8fe59c67038",
        "cache_sha256": "50136764cde0bda55eac660ae340f8db7b26b94d2eff1b010fdcab950d743567",
        "retention_sha256": "84c68decf1fde23fbbcbc6c1c49c8ee8b4943cbad2fa9c1f474d0d72bcd85176",
        "preparation_sha256": "126c16a7dbaf3fea03fe2dcf7c09e033c2c80ec73fc1cd1095133bc245788225",
        "install_sha256": "95573323365166e82451e04d435088176511661b3ffe004bba585a5896f5e002",
        "source_index_sha256": "22f9fdabb2235124dd503057cc7e8f411fd0ba6770e049f9fd123f23ea1fb885",
        "artifacts": {
            "candidate": (
                11325108220,
                2376500968,
                "0ec421e244b7fbb4f4fbd9b88010f7a1d893830c8d3014fd01ce6ff01eb16c61",
            ),
            "baseline": (
                11325302109,
                7592252,
                "f51a3fde33c61c1ab6ff9a2d0df615601441b8a130f1cab45c88cd6bd6876bd5",
            ),
            "build-evidence": (
                11325366821,
                6249454,
                "5f23eef68ce4eb1ced824fe15d3a9d9cdaa1a6b19e4ecd69f1e527c8b64b725f",
            ),
        },
    },
    "3.5.5-arm64": {
        "job_id": 111589467098,
        "runner": "windows-11-arm",
        "drive": "C:",
        "build_sha256": "134e648cf05ce35be332a13c4f654f9f1af1ccd32ad560843cb74889cbb99b7b",
        "cache_sha256": "fe67ff841f034d0461e51da14679a54d2c4aab0663bff1031e1ac7620a1b2ec5",
        "retention_sha256": "cf31001fb077ef56b5c34b2857344b34262e7ba2efe198ee72a675912a506451",
        "preparation_sha256": "a5450f234fb7a551226100745275539889131d1872f79ccfd8f69ffc1e955fdc",
        "install_sha256": "757851934913c63090b85b1ca80b56bed17292d2c09ffc729af17df5ae43fa26",
        "source_index_sha256": "975994f7ef2400cfc7bed54bb58926dcc6b313dbfe3a34d35bf13e4d3cfbd0b3",
        "artifacts": {
            "candidate": (
                11325161080,
                2279324116,
                "c3a607e585ba5b957e3a8ecdcf9e6e968c7317a108f3b295e10755ff70ea8f9e",
            ),
            "baseline": (
                11325055751,
                7426541,
                "c1c4efcf812185ff26a24c54e65d4cc6d0bd1d7c8f5eda67675561db919f2512",
            ),
            "build-evidence": (
                11325010827,
                6142867,
                "a5c9c842f125532391030e357547bcc132a0ed7d5992177597703ac749658129",
            ),
        },
    },
}
MANIFESTS = {
    "candidate_inventory": ("native-evidence.tar.gz", "evidence/candidate-after.json"),
    "baseline_inventory": ("native-evidence.tar.gz", "evidence/sdk-before.json"),
    "preparation": ("native-evidence.tar.gz", "evidence/preparation.json"),
    "build": ("native-evidence.tar.gz", "evidence/build.json"),
    "ownership": ("corresponding-sources.tar.gz", "libpack-qt-ownership.json"),
    "cache": ("build-evidence.tar.gz", "b/r/CMakeCache.txt"),
    "install": ("build-evidence.tar.gz", "b/r/install_manifest.txt"),
}


def expected_artifacts(sdk):
    return {
        kind: {
            "id": pin[0],
            "name": f"qt-pdf-libpack-{kind}-{sdk}",
            "size": pin[1],
            "sha256": pin[2],
        }
        for kind, pin in PINS[sdk]["artifacts"].items()
    }


def authenticated_metadata(run_id, sdk):
    adapter.require(run_id == RUN_ID and sdk in PINS, "Unpinned failed-install recovery")
    run = transport.api(f"actions/runs/{run_id}")
    adapter.require(
        run["id"] == RUN_ID
        and run["repository"]["full_name"] == transport.REPOSITORY
        and run["path"] == ".github/workflows/qt_pdf_backport.yml"
        and run["event"] == "workflow_dispatch"
        and run["run_attempt"] == 1
        and run["head_sha"] == HEAD
        and run["status"] == "completed"
        and run["conclusion"] == "failure",
        "Original failed workflow identity differs",
    )
    pin = PINS[sdk]
    job = transport.api(f"actions/jobs/{pin['job_id']}")
    adapter.require(
        job["id"] == pin["job_id"]
        and job["run_id"] == RUN_ID
        and job["run_attempt"] == 1
        and job["head_sha"] == HEAD
        and job["name"]
        == f"libpack-candidate / build ({sdk}, {pin['runner']}, {sdk.rsplit('-', 1)[1]})"
        and job["labels"] == [pin["runner"]]
        and job["status"] == "completed"
        and job["conclusion"] == "failure",
        "Original native failed job identity differs",
    )
    stages = {
        "Generate the authenticated baseline and retain its SDK on this runner": "success",
        "Prepare independent baseline and candidate copies with pinned sources": "success",
        "Build the Qt-only candidate without runtime qualification or promotion": "failure",
        "Capture both candidate PDF devices and the upstream Qt writer suite": "skipped",
        "Retain owned candidate PDFs and native capture receipts": "skipped",
        "Retain the owned native baseline evidence": "success",
        "Stage owned candidate receipts under one physical upload root": "success",
        "Retain owned candidate receipts before archiving": "success",
        "Archive the complete candidate and corresponding source with bounded build evidence": "success",
        "Retain the candidate SDK, complete corresponding source and archive hash receipts": "success",
    }
    for name, outcome in stages.items():
        matches = [step for step in job["steps"] if step["name"] == name]
        adapter.require(
            len(matches) == 1
            and matches[0]["status"] == "completed"
            and matches[0]["conclusion"] == outcome,
            f"Original stage differs: {name}",
        )
    artifacts = transport.api(f"actions/runs/{run_id}/artifacts?per_page=100")
    adapter.require(artifacts["total_count"] <= 100, "Paginated artifacts unsupported")
    receipts = expected_artifacts(sdk)
    for kind, expected in receipts.items():
        matches = [item for item in artifacts["artifacts"] if item["name"] == expected["name"]]
        adapter.require(len(matches) == 1, "Missing/ambiguous original artifact")
        item = matches[0]
        adapter.require(
            item["id"] == expected["id"]
            and item["size_in_bytes"] == expected["size"]
            and item["digest"] == "sha256:" + expected["sha256"]
            and item["expired"] is False
            and item["workflow_run"]["id"] == RUN_ID
            and item["workflow_run"]["head_sha"] == HEAD,
            "Pinned original artifact API identity differs",
        )
    return receipts


def authenticated_artifacts(run_id, sdk, inputs):
    receipts = authenticated_metadata(run_id, sdk)
    adapter.require(set(inputs) == set(receipts), "Incomplete original ZIP selection")
    for kind, expected in receipts.items():
        path = inputs[kind]
        adapter.require(
            path.is_file()
            and path.stat().st_size == expected["size"]
            and adapter.digest(path) == expected["sha256"],
            "Pinned original whole-ZIP bytes differ",
        )
    return receipts


def validate_original(preparation, build, sdk):
    """Portable validation of the authenticated historical failure, never a pass."""
    key, pin = sdk["key"], PINS[sdk["key"]]
    root = PureWindowsPath(pin["drive"] + "\\c")
    baseline = PureWindowsPath(pin["drive"] + "\\l")
    adapter.require(
        preparation["status"] == "prepared"
        and preparation["qualified"] is False
        and preparation["sdk"] == build["sdk"] == sdk
        and preparation["helper_sha256"] == OLD_ADAPTER
        and preparation["baseline_helper_sha256"] == BASELINE_HELPER
        and preparation["ownership_proof_sha256"] == OLD_OWNERSHIP
        and preparation["source_pin"] == adapter.SOURCES[sdk["release"]]
        and preparation["patch_sha256"] == adapter.PATCH_SHA
        and preparation["qt_commit"] == adapter.QT_COMMIT
        and preparation["work"] == str(root)
        and preparation["original_baseline"]["evidence"] == str(baseline / "evidence")
        and preparation["original_baseline"]["root"] == str(baseline / sdk["directory"])
        and preparation["original_baseline"]["archive"] == str(baseline / sdk["filename"])
        and build["status"] == "failed"
        and build["error"] == ERROR
        and build["qualified"] is False
        and build["build_only"] is True
        and build["non_qt_preserved"] is False
        and build["baseline_unchanged"] is True
        and build["original_baseline_unchanged"] is True
        and build["source_commit"] == adapter.SOURCES[sdk["release"]]["commit"]
        and build["source"]["repositories"]["."] == adapter.QT_COMMIT
        and build["source"]["repositories"]["qtbase"] == adapter.QTBASE_COMMIT
        and build["source"]["original_qpdf_sha256"] == adapter.QPDF_ORIGINAL
        and build["source"]["patched_qpdf_sha256"] == adapter.QPDF_PATCHED
        and build["source"]["patch_sha256"] == adapter.PATCH_SHA
        and build["configure"]["cache_sha256"] == pin["cache_sha256"]
        and build["compiler"] == preparation["compiler"]
        and build["build_tree"] == str(root / "b/r")
        and build["corresponding_sources"]
        == {
            "qt": str(root / "qt"),
            "libpack": str(root / "libpack"),
            "patch": str(root / "empty-outline.patch"),
            "finite_ownership_proof": str(root / "libpack-qt-ownership.json"),
        },
        f"Historical preparation/failed install differs: {key}",
    )


def validate_receipt(report, preparation, failed_build, sdk):
    """Portable receipt gate; callers additionally hash the actual original files."""
    validate_original(preparation, failed_build, sdk)
    original, current, admission = (
        report["immutable_original"],
        report["current_inputs"],
        report["build_admission"],
    )
    adapter.require(
        report["schema_version"] == 1
        and report["status"] == "installation-revalidated"
        and report["restored"] is True
        and report["post_install_revalidated"] is True
        and all(
            report[name] is False
            for name in (
                "qualified",
                "candidate_pdf_tested",
                "upstream_qt_tested",
                "native_freecad_tested",
                "promotion",
                "qt_recompiled",
                "baseline_regenerated",
            )
        )
        and report["sdk"] == sdk
        and report["run_id"] == RUN_ID
        and report["run_attempt"] == 1
        and report["head_sha"] == HEAD
        and report["job_id"] == PINS[sdk["key"]]["job_id"]
        and report["artifact_api_receipts"] == expected_artifacts(sdk["key"])
        and report["original_zips_unchanged_sha256"] is True
        and original["build_sha256"] == PINS[sdk["key"]]["build_sha256"]
        and original["retention_sha256"] == PINS[sdk["key"]]["retention_sha256"]
        and original["preparation_sha256"] == PINS[sdk["key"]]["preparation_sha256"]
        and original["source_index_sha256"] == PINS[sdk["key"]]["source_index_sha256"]
        and original["build_status"] == "failed"
        and original["build_error"] == ERROR
        and original["ownership_proof_sha256"] == OLD_OWNERSHIP
        and original["compiled_source"] == failed_build["source"]
        and original["historical_preparation_log_updates"] == [PREPARATION_LOG_UPDATE]
        and original["archive_manifest_sha256s"]
        == {
            "build": PINS[sdk["key"]]["build_sha256"],
            "preparation": PINS[sdk["key"]]["preparation_sha256"],
            "ownership": OLD_OWNERSHIP,
            "cache": PINS[sdk["key"]]["cache_sha256"],
            "install": PINS[sdk["key"]]["install_sha256"],
            "candidate_inventory": failed_build["candidate_inventory_sha256"],
            "baseline_inventory": preparation["sdk_inventory_sha256"],
        }
        and current["restorer_sha256"] == adapter.digest(Path(__file__))
        and current["adapter_sha256"] == adapter.digest(Path(adapter.__file__))
        and current["ownership_proof_sha256"] == adapter.OWNERSHIP_SHA
        and current["baseline_helper_sha256"] == BASELINE_HELPER
        and report["work_dir"] == preparation["work"]
        and report["original_baseline_work_dir"]
        == str(PureWindowsPath(preparation["original_baseline"]["root"]).parent)
        and admission["status"] == "installation-revalidated"
        and admission["qualified"] is False
        and admission["build_only"] is True
        and admission["baseline_unchanged"] is True
        and admission["original_baseline_unchanged"] is True
        and admission["non_qt_preserved"] is True
        and admission["original_failed_build_sha256"] == original["build_sha256"]
        and admission["sdk"] == sdk
        and admission["source"] == failed_build["source"]
        and admission["compiler"] == failed_build["compiler"]
        and admission["configure"] == failed_build["configure"]
        and admission["candidate_inventory_sha256"] == failed_build["candidate_inventory_sha256"]
        and admission["build_cache_sha256"] == PINS[sdk["key"]]["cache_sha256"]
        and admission["qt_install_manifest_sha256"] == PINS[sdk["key"]]["install_sha256"]
        and admission["ownership_proof_sha256"] == adapter.OWNERSHIP_SHA,
        "Current installation recovery receipt differs",
    )
    return admission


def archive_indices(payload, retention):
    adapter.require(set(retention["archives"]) == set(transport.ARCHIVES), "Missing TAR archive")
    expected, indices = {"retention.json"}, {}
    for name, receipt in retention["archives"].items():
        adapter.require(receipt["file_index"] == name + ".files.json", "Unexpected index name")
        expected |= {name, receipt["file_index"]}
        archive, index = payload / name, payload / receipt["file_index"]
        adapter.require(
            archive.stat().st_size == receipt["size"]
            and adapter.digest(archive) == receipt["sha256"]
            and adapter.digest(index) == receipt["file_index_sha256"],
            "Retained archive/index bytes differ",
        )
        entries = transport.read_json(index)
        adapter.require(len(entries) == receipt["file_count"], "Archive index count differs")
        for path, value in entries.items():
            relative = transport.member_name(path)
            adapter.require(
                relative.parts[0] in transport.ARCHIVES[name]
                and set(value) == {"size", "sha256"}
                and type(value["size"]) is int
                and 0 <= value["size"] <= transport.MAX_BYTES
                and re.fullmatch(r"[0-9a-f]{64}", value["sha256"]),
                "Unsafe/out-of-scope/malformed archive index",
            )
        adapter.require(
            len({name.casefold() for name in entries}) == len(entries), "Case collision"
        )
        indices[name] = entries
    adapter.require(
        {path.relative_to(payload).as_posix() for path in payload.rglob("*") if path.is_file()}
        == expected,
        "Unknown retained payload file",
    )
    adapter.require(set(retention["manifests"]) == set(MANIFESTS), "Missing retained manifest")
    for name, (archive, member) in MANIFESTS.items():
        adapter.require(
            retention["manifests"][name]
            == {"archive": archive, "member": member, **indices[archive][member]},
            "Manifest/index binding differs",
        )
    suffixes = {
        ".obj",
        ".o",
        ".a",
        ".lib",
        ".dll",
        ".exe",
        ".pdb",
        ".ilk",
        ".exp",
        ".res",
        ".pch",
        ".idb",
        ".ipch",
        ".so",
        ".dylib",
    }
    adapter.require(
        retention["excluded_build_suffixes"] == sorted(suffixes)
        and retention["build_exclusion_policy"]
        == "Only listed compiled-artifact suffixes in b/r; source and SDK trees are complete.",
        "Original filtered-build policy differs",
    )
    for name, entry in retention["excluded_build_files"].items():
        path = transport.member_name(name)
        adapter.require(
            path.parts[:2] == ("b", "r")
            and path.suffix.casefold() in suffixes
            and ".git" not in path.parts
            and not path.name.casefold().startswith(("license", "copying"))
            and set(entry) == {"size"}
            and type(entry["size"]) is int
            and entry["size"] >= 0
            and name not in indices["build-evidence.tar.gz"],
            "Noncompiled/source/SDK content excluded from retained build tree",
        )
    return indices


def unchanged_index(work, index, helper, stage="read-only revalidation"):
    for name, expected in index.items():
        path = helper.real_path(work / adapter.safe_relative(name))
        actual = (
            {"size": path.stat().st_size, "sha256": adapter.digest(path)}
            if path.is_file()
            else None
        )
        adapter.require(
            actual == expected,
            f"Retained original bytes changed during {stage}: {name}; "
            f"expected size={expected['size']}, sha256={expected['sha256']}; "
            + (
                f"actual size={actual['size']}, sha256={actual['sha256']}"
                if actual is not None
                else "actual file missing or non-regular"
            ),
        )


def preparation_log_updates(preparation, evidence):
    """The original build refreshes one status log; retain both authentic hashes."""
    changed = []
    for name, expected in preparation["preparation_files"].items():
        path = evidence / adapter.safe_relative(name)
        actual = adapter.digest(path)
        if actual != expected:
            adapter.require(
                name == PREPARATION_LOG_UPDATE["path"]
                and expected == PREPARATION_LOG_UPDATE["initial_sha256"]
                and actual == PREPARATION_LOG_UPDATE["retained_sha256"],
                "Unknown historical preparation log change",
            )
            changed.append(PREPARATION_LOG_UPDATE)
    adapter.require(changed == [PREPARATION_LOG_UPDATE], "Historical log refresh differs")
    return changed


def restore_baseline(work, destination, sdk, before, helper):
    destination = helper.fresh_work(destination)
    shutil.copytree(work / "baseline", destination / "evidence", copy_function=shutil.copy2)
    archive = destination / sdk["filename"]
    request = urllib.request.Request(sdk["url"], headers={"User-Agent": "FreeCAD-SDK-restore"})
    with urllib.request.urlopen(request, timeout=60) as source, archive.open("xb") as target:
        length = 0
        for block in iter(lambda: source.read(1024 * 1024), b""):
            length += len(block)
            adapter.require(length <= sdk["size"], "Oversized official baseline archive")
            target.write(block)
    adapter.require(
        archive.stat().st_size == sdk["size"] and adapter.digest(archive) == sdk["sha256"],
        "Official baseline archive differs",
    )
    listing = helper.command(["7z", "l", "-slt", "-sccUTF-8", str(archive)], work, "sdk-list")
    helper.archive_members(listing["stdout"].replace("\r\n", "\n"), sdk["directory"])
    helper.command(["7z", "x", "-y", str(archive), "-o" + str(destination)], work, "sdk-extract")
    root = destination / sdk["directory"]
    adapter.require(
        helper.inventory(root) == before, "Released baseline physical inventory differs"
    )
    return root


def validate_restored(work, helper):
    """Read back physical native SDK/source/cache and the separate admission."""
    work = helper.real_path(work)
    evidence = work / "evidence"
    report = transport.read_json(evidence / "installation-recovery.json")
    preparation, failed = (
        transport.read_json(evidence / name) for name in ("preparation.json", "build.json")
    )
    sdk = helper.sdk_identity(preparation["sdk"]["key"])
    admission = validate_receipt(report, preparation, failed, sdk)
    original = report["immutable_original"]
    adapter.require(
        str(work) == preparation["work"]
        and helper.native_machine() == preparation["host"]
        and adapter.digest(Path(helper.__file__)) == BASELINE_HELPER
        and adapter.digest(evidence / "build.json") == original["build_sha256"]
        and adapter.digest(evidence / "preparation.json") == original["preparation_sha256"]
        and adapter.digest(evidence / "candidate-after.json")
        == admission["candidate_inventory_sha256"],
        "Original physical native receipts/host differ",
    )
    adapter.require(
        preparation_log_updates(preparation, evidence)
        == original["historical_preparation_log_updates"],
        "Historical preparation readback differs",
    )
    before, candidate = (
        transport.read_json(evidence / name) for name in ("sdk-before.json", "candidate-after.json")
    )
    adapter.require(helper.inventory(work / "candidate") == candidate, "Restored candidate changed")
    adapter.require(helper.inventory(work / "baseline") == before, "Protected baseline changed")
    baseline, fresh_before = adapter.baseline_input(
        Path(preparation["original_baseline"]["evidence"]), sdk, helper
    )
    adapter.require(
        baseline == preparation["original_baseline"] and fresh_before == before,
        "Original baseline evidence differs",
    )
    cache = adapter.configured_cache(work / "b/r", work / "candidate", failed["compiler"], helper)
    adapter.require(cache == failed["configure"], "Restored exact compiler/cache admission differs")
    source_index = helper.real_path(Path(report["source_index"]))
    temporary = helper.real_path(Path(report["transport_work_dir"]))
    adapter.require(
        source_index == temporary / "candidate/corresponding-sources.tar.gz.files.json"
        and temporary.is_relative_to(helper.real_path(Path(os.environ["RUNNER_TEMP"]))),
        "Restored source index escaped authenticated transport",
    )
    index = transport.read_json(source_index)
    adapter.require(
        adapter.digest(source_index) == original["source_index_sha256"],
        "Source index changed",
    )
    unchanged_index(work, index, helper, stage="restored source readback")
    adapter.require(
        adapter.digest(work / "b/r/install_manifest.txt")
        == admission["qt_install_manifest_sha256"],
        "Restored install manifest changed",
    )
    fields, after = adapter.admit_installation(
        work / "b/r",
        work / "candidate",
        work / "qt",
        before,
        failed["source"]["repositories"],
        helper,
    )
    adapter.require(after == candidate, "Readback changed candidate")
    for field, name in (
        ("qt_install_manifest_receipt", "qt-install-manifest.json"),
        ("qt_finite_install_receipt", "qt-finite-install.json"),
        ("qt_companion_alias_receipt", "qt-versioned-aliases.json"),
        ("qt_companion_spdx_receipt", "qt-spdx-companions.json"),
    ):
        adapter.require(
            fields.pop(field) == transport.read_json(evidence / name)
            and adapter.digest(evidence / name) == admission[field + "_sha256"],
            "Post-install companion/source receipt readback differs",
        )
    adapter.require(
        all(admission[name] == value for name, value in fields.items()),
        "Post-install admission readback differs",
    )
    return admission, preparation


def restore(args, helper):
    adapter.require(
        os.environ.get("GITHUB_ACTIONS") == "true" and os.name == "nt",
        "Use a disposable native Windows CI job",
    )
    sdk = helper.sdk_identity(args.sdk)
    pin = PINS[args.sdk]
    work, temporary = helper.real_path(args.work_dir), helper.real_path(args.transport_work_dir)
    baseline_work = helper.real_path(Path(pin["drive"] + "\\l"))
    adapter.require(
        work == Path(pin["drive"] + "\\c") and not work.exists() and not baseline_work.exists(),
        "Original c/l roots must be fresh",
    )
    adapter.require(
        temporary.is_relative_to(helper.real_path(Path(os.environ["RUNNER_TEMP"]))),
        "Transport must be below RUNNER_TEMP",
    )
    inputs = {
        kind: helper.real_path(getattr(args, kind.replace("-", "_") + "_zip"))
        for kind in PINS[args.sdk]["artifacts"]
    }
    for path in inputs.values():
        adapter.require(path.stat().st_nlink == 1, "Artifact ZIP must be independent")
        adapter.separate_path(work, path)
        adapter.separate_path(baseline_work, path)
        adapter.separate_path(temporary, path)
    adapter.separate_path(work, temporary)
    adapter.separate_path(baseline_work, temporary)
    receipts = authenticated_artifacts(args.run_id, args.sdk, inputs)
    temporary = helper.fresh_work(temporary)
    for kind, path in inputs.items():
        transport.extract_zip(path, temporary / kind)
    payload = temporary / "candidate"
    retention = transport.read_json(payload / "retention.json")
    adapter.require(
        adapter.digest(payload / "retention.json") == pin["retention_sha256"]
        and retention["commit"] == HEAD
        and retention["run_url"]
        == f"https://github.com/{transport.REPOSITORY}/actions/runs/{RUN_ID}"
        and retention["sdk"] == args.sdk
        and retention["physical_work_dir"] == str(work)
        and retention["build_status"] == "failed"
        and retention["candidate_capture_outcome"] == "skipped"
        and retention["build_only"] is True
        and all(
            retention[name] is False
            for name in ("qualified", "native_freecad_tested", "candidate_pdf_tested", "promotion")
        ),
        "Original failed retention scope differs",
    )
    indices = archive_indices(payload, retention)
    work = helper.fresh_work(work)
    for name, roots in transport.ARCHIVES.items():
        transport.extract_tar(payload / name, work, indices[name], roots)
    evidence = work / "evidence"
    preparation, failed = (
        transport.read_json(evidence / name) for name in ("preparation.json", "build.json")
    )
    validate_original(preparation, failed, sdk)
    log_updates = preparation_log_updates(preparation, evidence)
    adapter.require(
        adapter.digest(evidence / "build.json") == pin["build_sha256"]
        and adapter.digest(evidence / "preparation.json") == pin["preparation_sha256"]
        and adapter.digest(Path(helper.__file__)) == BASELINE_HELPER
        and helper.native_machine() == preparation["host"]
        and preparation["host"]["native_machine"] == helper.MACHINES[sdk["architecture"]]
        and preparation["host"]["python_process_machine"] == 0,
        "Historical receipt/current native helper or host differs",
    )
    staged = temporary / "build-evidence/candidate-evidence"
    adapter.require(
        {
            p.relative_to(staged).as_posix(): {
                "size": p.stat().st_size,
                "sha256": adapter.digest(p),
            }
            for p in staged.rglob("*")
            if p.is_file()
        }
        == {
            name.removeprefix("evidence/"): value
            for name, value in indices["native-evidence.tar.gz"].items()
            if name.startswith("evidence/")
        },
        "Independent original build-evidence ZIP differs from retained native evidence",
    )
    before, candidate = (
        transport.read_json(evidence / name) for name in ("sdk-before.json", "candidate-after.json")
    )
    adapter.require(
        adapter.digest(evidence / "candidate-after.json") == failed["candidate_inventory_sha256"],
        "Historical candidate inventory binding differs",
    )
    transport.exact_times(work / "candidate", candidate, helper)
    baseline_root = restore_baseline(temporary, baseline_work, sdk, before, helper)
    # Only the original baseline evidence is copied; no diagnostic executor runs.
    shutil.copytree(baseline_root, work / "baseline", copy_function=shutil.copy2)
    shutil.copy2(baseline_work / sdk["filename"], work / sdk["filename"])
    original, actual_before = adapter.baseline_input(baseline_work / "evidence", sdk, helper)
    adapter.require(
        original == preparation["original_baseline"] and actual_before == before,
        "Authenticated baseline generation differs",
    )
    adapter.verify_sources(work / "libpack", sdk["release"], helper)
    adapter.require(
        adapter.digest(work / "empty-outline.patch") == adapter.PATCH_SHA
        and adapter.digest(work / "libpack-qt-ownership.json") == OLD_OWNERSHIP
        and adapter.digest(work / "qt/qtbase/src/gui/painting/qpdf.cpp") == adapter.QPDF_PATCHED,
        "Historical corresponding source/patch/catalogue changed",
    )
    environment = {**adapter.source_environment(os.environ.copy()), "GIT_OPTIONAL_LOCKS": "0"}
    repositories = adapter.qt_repositories(work / "qt", temporary, "git", environment=environment)
    adapter.require(
        repositories == failed["source"]["repositories"], "Restored Git identities differ"
    )
    adapter.clean_tracked(
        work / "qt", repositories, temporary, "git", patched=True, environment=environment
    )
    adapter.require(
        adapter.configured_cache(work / "b/r", work / "candidate", failed["compiler"], helper)
        == failed["configure"],
        "Restored cache/compiler identities differ",
    )
    fields, after = adapter.admit_installation(
        work / "b/r", work / "candidate", work / "qt", before, repositories, helper
    )
    adapter.require(after == candidate, "Read-only post-install admission changed candidate")
    for field, name in (
        ("qt_install_manifest_receipt", "qt-install-manifest.json"),
        ("qt_finite_install_receipt", "qt-finite-install.json"),
        ("qt_companion_alias_receipt", "qt-versioned-aliases.json"),
        ("qt_companion_spdx_receipt", "qt-spdx-companions.json"),
    ):
        adapter.require(
            not (evidence / name).exists(), "New admission receipt collides with original evidence"
        )
        adapter.write_json(evidence / name, fields.pop(field))
        fields[field + "_sha256"] = adapter.digest(evidence / name)
    modules = {}
    for name in ("Qt6Core.dll", "Qt6Gui.dll", "Qt6PrintSupport.dll"):
        path = work / "candidate/bin" / name
        machine, version = helper.pe_machine(path), helper.file_version(path)
        adapter.require(
            machine == helper.MACHINES[sdk["architecture"]]
            and version[:3] == [6, 11, 1]
            and "bin/" + name in fields["admitted_qt_paths"],
            "Actual installed Qt architecture/version/admission differs",
        )
        modules[name] = {
            "sha256": adapter.digest(path),
            "file_version": version,
            "pe_machine": machine,
        }
    adapter.require(
        modules["Qt6Gui.dll"]["sha256"] != before["files"]["bin/Qt6Gui.dll"]["sha256"],
        "Candidate QtGui is still baseline",
    )
    for name, index in indices.items():
        unchanged_index(work, index, helper, stage=f"{name} post-install readback")
    adapter.require(
        all(adapter.digest(path) == receipts[kind]["sha256"] for kind, path in inputs.items()),
        "Original ZIP changed",
    )
    admission = {
        **failed,
        **fields,
        "status": "installation-revalidated",
        "error": ERROR,
        "original_failed_build_sha256": pin["build_sha256"],
        "build_cache_sha256": pin["cache_sha256"],
        "installed_qt_modules": modules,
    }
    report = {
        "schema_version": 1,
        "status": "installation-revalidated",
        "restored": True,
        "post_install_revalidated": True,
        "qualified": False,
        "candidate_pdf_tested": False,
        "upstream_qt_tested": False,
        "native_freecad_tested": False,
        "promotion": False,
        "qt_recompiled": False,
        "baseline_regenerated": False,
        "sdk": sdk,
        "run_id": RUN_ID,
        "run_attempt": 1,
        "head_sha": HEAD,
        "job_id": pin["job_id"],
        "artifact_api_receipts": receipts,
        "original_zips_unchanged_sha256": True,
        "immutable_original": {
            "retention_sha256": adapter.digest(payload / "retention.json"),
            "preparation_sha256": adapter.digest(evidence / "preparation.json"),
            "build_sha256": pin["build_sha256"],
            "build_status": "failed",
            "build_error": ERROR,
            "ownership_proof_sha256": OLD_OWNERSHIP,
            "compiled_source": failed["source"],
            "historical_preparation_log_updates": log_updates,
            "source_index_sha256": retention["archives"]["corresponding-sources.tar.gz"][
                "file_index_sha256"
            ],
            "archive_manifest_sha256s": {
                name: value["sha256"] for name, value in retention["manifests"].items()
            },
        },
        "current_inputs": {
            "restorer_sha256": adapter.digest(Path(__file__)),
            "adapter_sha256": adapter.digest(Path(adapter.__file__)),
            "ownership_proof_sha256": adapter.OWNERSHIP_SHA,
            "baseline_helper_sha256": adapter.digest(Path(helper.__file__)),
        },
        "work_dir": str(work),
        "transport_work_dir": str(temporary),
        "original_baseline_work_dir": str(baseline_work),
        "source_index": str(
            payload / retention["archives"]["corresponding-sources.tar.gz"]["file_index"]
        ),
        "transported_hardlinks": "Only earlier indexed regular targets, materialized as independent copies",
        "build_admission": admission,
    }
    validate_receipt(report, preparation, failed, sdk)
    adapter.write_json(evidence / "installation-recovery.json", report)
    validate_restored(work, helper)
    adapter.write_json(temporary / "installation-recovery.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--sdk", choices=PINS, required=True)
    for name in (
        "candidate-zip",
        "baseline-zip",
        "build-evidence-zip",
        "work-dir",
        "transport-work-dir",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        report = restore(args, adapter.baseline_helper())
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "sdk": report["sdk"]["key"],
                    "report": str(Path(report["work_dir"]) / "evidence/installation-recovery.json"),
                    "qualified": False,
                    "qt_recompiled": False,
                }
            )
        )
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
