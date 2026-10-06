# SPDX-License-Identifier: LGPL-2.1-or-later
"""Prepare explicitly pinned host tools before a retained LibPack recovery.

The original compiler/CMake and complete original Git remain mandatory. A
separate finite Windows image profile admits two authenticated current
Chocolatey launchers and their complete published backends. Historical build
receipts remain immutable; this report does not qualify an SDK or its tests.
"""

import argparse
import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import subprocess
import sys
import urllib.request

import build_libpack_backport as adapter

GIT_ROOT = r"C:\Program Files\Git"
GIT_VERSION = "git version 2.55.0.windows.5"
ORIGINAL_RUN = 37254793061
ORIGINAL_HEAD = "ba37708eecef736d9caafdbae5f07618887d675b"
ORIGINAL_ADAPTER = "fc28ad59cda3dd02be48cb70ddb8dc80b186f891805e4fad73a82572d83d72d4"
PREPARATIONS = {
    "3.5.3-x64": "a578b3efac9aa102a5b883c71af57572359e56adfd25fdb34b07fa129f520bca",
    "3.5.5-x64": "126c16a7dbaf3fea03fe2dcf7c09e033c2c80ec73fc1cd1095133bc245788225",
    "3.5.5-arm64": "a5450f234fb7a551226100745275539889131d1872f79ccfd8f69ffc1e955fdc",
}
# These fields are literal readbacks of the three SHA-pinned original preparations.
PROFILES = {
    "x64": {
        "host": {"native_machine": 34404, "python_process_machine": 0},
        "compiler": {
            "compiler": r"C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Tools\MSVC\14.44.35207\bin\HostX64\x64\cl.exe",
            "compiler_sha256": "fe251ef50a1545b1b0835ee17b1e785459712b38d79e45b5c1d3d28970a36619",
            "tools_version": "14.44.35207",
            "initialization": r"C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvars64.bat",
        },
        "tools": {
            "cmake": {
                "path": r"C:\Program Files\CMake\bin\cmake.exe",
                "sha256": "3fe22eb02e1c6184ec207366ed21a6f2f9c3828c1e9f3324546befadfb362be3",
            },
            "ninja": {
                "path": r"C:\ProgramData\chocolatey\bin\ninja.exe",
                "sha256": "b28222007c60aec66bb734ef43c0802e43aaa4a1028b41b29058970d7b7df745",
            },
            "git": {
                "path": GIT_ROOT + r"\bin\git.exe",
                "sha256": "78211c7ed73988da93a6d8a33d47ec6187f464d7ea2a9a00c182bbd7a1ecf30f",
            },
            "7z": {
                "path": r"C:\ProgramData\chocolatey\bin\7z.exe",
                "sha256": "e15da91c1223cf22f52c71519137b0f8ce04842ac334909e6596282f7e5807b2",
            },
        },
    },
    "arm64": {
        "host": {"native_machine": 43620, "python_process_machine": 0},
        "compiler": {
            "compiler": r"C:\Program Files\Microsoft Visual Studio\18\Enterprise\VC\Tools\MSVC\14.44.35207\bin\HostARM64\ARM64\cl.exe",
            "compiler_sha256": "47b1e067b8f81a52eddd5a623675bd50126567b1dd1118cde4d52b9e550eb149",
            "tools_version": "14.44.35207",
            "initialization": r"C:\Program Files\Microsoft Visual Studio\18\Enterprise\VC\Auxiliary\Build\vcvarsarm64.bat",
        },
        "tools": {
            "cmake": {
                "path": r"C:\Program Files\CMake\bin\cmake.exe",
                "sha256": "a32ae68e4b8b030a9df26a27c4094fca8eb0f3083cd0c3a9db348c9c4cdab54b",
            },
            "ninja": {
                "path": r"C:\Tools\Ninja\ninja.exe",
                "sha256": "7f519afd93cd1d1dce67c9644990b5d3b40b458e547cb39df608d8f352a6ad79",
            },
            "git": {
                "path": GIT_ROOT + r"\bin\git.exe",
                "sha256": "84cef31be1641a8177a354f433e6511c6bb33cade924997dd5321e72367a184f",
            },
            "7z": {
                "path": r"C:\ProgramData\chocolatey\bin\7z.exe",
                "sha256": "c96cd0e1a9526a552129aaade0bc82d201d2f3fda03445f63a6a05dd1467d7f9",
            },
        },
    },
}
INSTALLERS = {
    "x64": {
        "filename": "Git-2.55.0.5-64-bit.exe",
        "asset_id": 522489680,
        "size": 65343712,
        "sha256": "d065a4e23c3d9a6b5073d609b5be0830227ec3ca053c083ba385061ddfaf94c6",
    },
    "arm64": {
        "filename": "Git-2.55.0.5-arm64.exe",
        "asset_id": 522489954,
        "size": 63259960,
        "sha256": "c955de342b1465bc637f0e71fddf4e28e8d0b829668ec1866ab32a839303e8e3",
    },
}
# Main executables read from the authenticated official PortableGit 2.55.0.5
# payloads, independently of the historical preparations' launcher-only fields.
GIT_IMPLEMENTATIONS = {
    "x64": {
        "relative": "mingw64/bin/git.exe",
        "size": 4378456,
        "sha256": "d1b62b94aa15e5c3bbcdd6440d5f716f78daa2736a951b0f1fad11d38c5f16da",
    },
    "arm64": {
        "relative": "clangarm64/bin/git.exe",
        "size": 3917000,
        "sha256": "9c6c0042a64c8b24ae9e0c0fd1090acacd25334745a265115dc48d3a7f127295",
    },
}
GIT_LAUNCHER_SIZES = {"x64": 43352, "arm64": 43208}
ADAPTER_SHA = "2c3d8b69ae2c6403b047dc976cdb6cfc857b8282c4f1fa6d9e0cbdb0c6c4cc72"
BASELINE_HELPER_SHA = "b397fed4470e0f1e171f1829e9074d9005178d614cf0e0488852c0a8e4a44621"

# These current launcher bytes were retained by our native diagnostic run. Their
# native implementations match the complete official release/package payloads.
# This is a new qualification profile, never a claim of historical byte equality.
CURRENT_FILES = {
    "7z": {
        "path": r"C:\ProgramData\chocolatey\bin\7z.exe",
        "size": 391680,
        "sha256": "885c29df4b20d00efd1789e2cf43f904284d42938e2b0fa8cb48cbcddf0064e7",
        "pe_machine": 332,
    },
    "ninja": {
        "path": r"C:\ProgramData\chocolatey\bin\ninja.exe",
        "size": 392704,
        "sha256": "da34e513472816e1f509a2c705d6408c337e024bdd78fc40e6cda9c9ef7f0842",
        "pe_machine": 332,
    },
    "7z-backend": {
        "path": r"C:\Program Files\7-Zip\7z.exe",
        "size": 577536,
        "sha256": "6ee3c0ed0b27663c1b948ae85a7c0bb073aed1498983182f3f0df1f6a8c30b2f",
        "pe_machine": 34404,
    },
    "7z-library": {
        "path": r"C:\Program Files\7-Zip\7z.dll",
        "size": 1906688,
        "sha256": "65e4c1f855f9ef6e8f0f5df8e3f27d9eb5f07311408639da0a1ca0b8f4871b0d",
        "pe_machine": 34404,
    },
    "ninja-backend": {
        "path": r"C:\ProgramData\chocolatey\lib\ninja\tools\ninja.exe",
        "size": 603648,
        "sha256": "e52a7ad9538d9618c67a0bd777964e2eec8a30f68b810a2f6adce1f2daf847b8",
        "pe_machine": 34404,
    },
    "shimgen": {
        "path": r"C:\ProgramData\chocolatey\tools\shimgen.exe",
        "size": 568928,
        "sha256": "50a349f3c15353bb9033c4e9d4660ebd9677667d6d3cd2951cf7429c4fb6084f",
        "pe_machine": 332,
    },
}
CURRENT_PROFILE = {
    "id": "windows2022-20261004.326.1-chocolatey-2.7.4",
    "image_os": "win22",
    "image_version": "20261004.326.1",
    "sdk_keys": ["3.5.3-x64", "3.5.5-x64"],
    "historical_tool_bytes_equal": False,
    "source": {
        "image_commit": "0244f69125833bd64b8693b385b80b2ca026a862",
        "image_url": "https://github.com/actions/runner-images/releases/tag/win22/20261004.326",
        "diagnostic_transport_sha256": "76b5eed19c6d1c6708655cb9aa65676f452dc58243731aa1a606f8bac007e2f9",
        "static_review_sha256": "00f09b1e00a02322c056ef89e8a25380e22fef9c27021c89b047dfbb36ec3a5c",
        "diagnostic": {
            "run_id": 37476327222,
            "run_attempt": 1,
            "head_sha": "d7e31ad941ce9a2605f337efdeceda24952c4919",
            "job_id": 112312622258,
            "artifact_id": 11418783725,
            "artifact_size": 55169,
            "artifact_sha256": "4fb233d45530a8b90bb7db95579b0ef26fc164460ecf466689afa06774159914",
        },
        "7zip_installer": {
            "url": "https://github.com/ip7z/7zip/releases/download/26.03/7z2603-x64.exe",
            "size": 1661239,
            "sha256": "0859c524b8a63551848f0c246abddcb1d0b7b656b0fbfe879f8d85e61a9e6edd",
        },
        "ninja_archive": {
            "url": "https://github.com/ninja-build/ninja/releases/download/v1.13.2/ninja-win.zip",
            "size": 291570,
            "sha256": "07fc8261b42b20e71d1720b39068c2e14ffcee6396b76fb7a795fb460b78dc65",
        },
        "chocolatey_package": {
            "url": "https://community.chocolatey.org/api/v2/package/chocolatey/2.7.4",
            "size": 5713666,
            "sha256": "aec2dbd6ce91b7378eb4a0c21524e748d30332ea856e898404999f77328bd504",
        },
    },
}


def producer_context():
    """Record only the explicit public CI identity fields needed by consumers."""
    return {
        "repository": os.environ.get("GITHUB_REPOSITORY"),
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "head_sha": os.environ.get("GITHUB_SHA"),
        "image_os": os.environ.get("ImageOS"),
        "image_version": os.environ.get("ImageVersion"),
    }


def validate_producer(producer):
    adapter.require(
        set(producer)
        == {"repository", "run_id", "run_attempt", "head_sha", "image_os", "image_version"}
        and producer["repository"] == "zukomgwili/FreeCAD"
        and re.fullmatch(r"[1-9]\d*", producer["run_id"] or "")
        and re.fullmatch(r"[1-9]\d*", producer["run_attempt"] or "")
        and re.fullmatch(r"[0-9a-f]{40}", producer["head_sha"] or "")
        and re.fullmatch(r"[a-z0-9-]+", producer["image_os"] or "")
        and re.fullmatch(r"\d{8}\.\d+\.\d+", producer["image_version"] or ""),
        "Host-tool producer identity/image metadata differs",
    )


def selected_profile(sdk, tools, producer):
    """Select only the literal original tools or the finite current-image pair."""
    original = PROFILES[sdk["architecture"]]
    current_pair = all(
        tools.get(name) == {key: CURRENT_FILES[name][key] for key in ("path", "sha256")}
        for name in ("7z", "ninja")
    )
    if not current_pair:
        return original, None
    adapter.require(
        sdk["key"] in CURRENT_PROFILE["sdk_keys"]
        and producer["image_os"] == CURRENT_PROFILE["image_os"]
        and producer["image_version"] == CURRENT_PROFILE["image_version"],
        "Current Chocolatey launchers require their exact qualified native image",
    )
    tools = {
        **original["tools"],
        **{
            name: {key: CURRENT_FILES[name][key] for key in ("path", "sha256")}
            for name in ("7z", "ninja")
        },
    }
    return {**original, "tools": tools}, CURRENT_PROFILE


def qualification_files(helper):
    """Read the complete finite implementations before any system installation."""
    files = {}
    for name, expected in CURRENT_FILES.items():
        path = Path(expected["path"])
        resolved = helper.real_path(path)
        info = resolved.lstat()
        adapter.require(
            str(resolved) == expected["path"]
            and stat.S_ISREG(info.st_mode)
            and info.st_nlink == 1
            and not getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT,
            "Qualified current host tool is linked/noncanonical",
        )
        files[name] = {
            "path": str(resolved),
            "size": info.st_size,
            "sha256": adapter.digest(resolved),
            "pe_machine": helper.pe_machine(resolved),
        }
    adapter.require(files == CURRENT_FILES, "Qualified current host-tool implementation differs")
    return files


def observe(work, evidence, architecture, helper):
    host = helper.native_machine()
    environment, compiler = helper.compiler_environment(work, evidence, architecture)
    tools = adapter.tool_receipts(environment, [work], helper)
    return environment, {
        "host": host,
        "compiler": compiler,
        "compiler_pe_machine": helper.pe_machine(Path(compiler["compiler"])),
        "tools": tools,
    }


def validate(observation, profile, allow_git_drift=False):
    adapter.require(observation["host"] == profile["host"], "Original native host/Python differs")
    adapter.require(
        observation["compiler_pe_machine"] == profile["host"]["native_machine"]
        and all(
            observation["compiler"].get(name) == value
            for name, value in profile["compiler"].items()
        ),
        "Original native compiler path/hash/version differs",
    )
    tools = observation["tools"]
    adapter.require(set(tools) == set(profile["tools"]), "Original tool set differs")
    changes = {}
    for name, expected in profile["tools"].items():
        actual = tools[name]
        adapter.require(
            set(actual) == {"path", "sha256"} and re.fullmatch(r"[0-9a-f]{64}", actual["sha256"]),
            "Host-tool raw identity receipt differs",
        )
        same_path = actual.get("path") == expected["path"]
        same_hash = actual.get("sha256") == expected["sha256"]
        if not same_path or (not same_hash and not (allow_git_drift and name == "git")):
            changes[name] = {"expected": expected, "actual": actual}
    adapter.require(
        not changes,
        "Original build-tool identity differs: " + json.dumps(changes, sort_keys=True),
    )


def retain_drift_diagnostics(observation, profile, evidence, helper):
    changed = [
        name for name in ("7z", "ninja") if observation["tools"].get(name) != profile["tools"][name]
    ]
    if not changed:
        return {}
    sources = {
        name: (Path(profile["tools"][name]["path"]), True)
        for name in changed
        if observation["tools"].get(name, {}).get("path") == profile["tools"][name]["path"]
    }
    sources.update(
        {
            "shimgen": (Path(r"C:\ProgramData\chocolatey\tools\shimgen.exe"), False),
            "ninja-backend": (Path(r"C:\ProgramData\chocolatey\lib\ninja\tools\ninja.exe"), False),
            "7z-backend": (Path(r"C:\Program Files\7-Zip\7z.exe"), False),
            "7z-library": (Path(r"C:\Program Files\7-Zip\7z.dll"), False),
        }
    )
    receipt = {}
    for name, (path, retain) in sources.items():
        try:
            resolved = helper.real_path(path)
            info = resolved.lstat()
            adapter.require(
                str(resolved) == str(path)
                and stat.S_ISREG(info.st_mode)
                and info.st_nlink == 1
                and not getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                and 0 < info.st_size <= (1024 * 1024 if retain else 16 * 1024 * 1024),
                "Diagnostic tool is linked, noncanonical or outside its size bound",
            )
            sha = adapter.digest(resolved)
            entry = {
                "path": str(resolved),
                "size": info.st_size,
                "sha256": sha,
                "pe_machine": helper.pe_machine(resolved),
                "retained": retain,
            }
            if retain:
                adapter.require(
                    sha == observation["tools"][name]["sha256"], "Observed tool changed"
                )
                destination = evidence / "tool-binaries" / (name + ".exe")
                destination.parent.mkdir(exist_ok=True)
                adapter.require(not destination.exists(), "Diagnostic destination already exists")
                with resolved.open("rb") as source, destination.open("xb") as output:
                    data = source.read(info.st_size + 1)
                    adapter.require(len(data) == info.st_size, "Diagnostic tool size changed")
                    output.write(data)
                adapter.require(
                    adapter.digest(destination) == adapter.digest(resolved) == sha
                    and destination.stat().st_size == info.st_size,
                    "Diagnostic tool copy differs",
                )
                entry["evidence_file"] = str(destination.relative_to(evidence))
            receipt[name] = entry
        except (OSError, ValueError, KeyError) as error:
            receipt[name] = {"path": str(path), "error": str(error)[:512], "retained": False}
    adapter.write_json(
        evidence / "host-tool-diagnostics.json",
        {
            "schema_version": 1,
            "qualified": False,
            "executed": False,
            "files": receipt,
        },
    )
    return receipt


def download_installer(asset, destination):
    url = (
        "https://github.com/git-for-windows/git/releases/download/"
        "v2.55.0.windows.5/" + asset["filename"]
    )
    request = urllib.request.Request(url, headers={"User-Agent": "FreeCAD pinned Git recovery"})
    received = 0
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("xb") as output:
        while block := response.read(1024 * 1024):
            received += len(block)
            adapter.require(received <= asset["size"], "Official Git installer exceeds pinned size")
            output.write(block)
    adapter.require(
        received == asset["size"] and adapter.digest(destination) == asset["sha256"],
        "Official Git installer size/hash differs",
    )
    return {
        **asset,
        "url": url,
        "path": str(destination),
        "whole_asset_authenticated": True,
    }


def install_git(installer, evidence, environment):
    log = evidence / "git-installer.log"
    arguments = [
        str(installer),
        "/VERYSILENT",
        "/NORESTART",
        "/NOCANCEL",
        "/SP-",
        "/SUPPRESSMSGBOXES",
        "/ALLOWDOWNGRADE=1",
        "/DIR=" + GIT_ROOT,
        "/LOG=" + str(log),
    ]
    result = subprocess.run(
        arguments,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=300,
    )
    receipt = {"argv": arguments, "returncode": result.returncode}
    adapter.write_json(evidence / "git-installer-execution.json", receipt)
    adapter.require(result.returncode == 0, "Pinned Git installer failed")
    adapter.require(
        log.is_file() and log.stat().st_size <= 2 * 1024 * 1024, "Installer log missing/large"
    )
    return {**receipt, "log_sha256": adapter.digest(log), "log_size": log.stat().st_size}


def git_identity(profile, architecture, helper):
    paths = {
        "launcher": Path(profile["tools"]["git"]["path"]),
        "implementation": Path(GIT_ROOT) / GIT_IMPLEMENTATIONS[architecture]["relative"],
    }
    return {
        name: {
            "path": str(helper.real_path(path)),
            "size": path.stat().st_size,
            "sha256": adapter.digest(path),
            "pe_machine": helper.pe_machine(path),
        }
        for name, path in paths.items()
    }


def validate_git(identity, profile, architecture):
    implementation = GIT_IMPLEMENTATIONS[architecture]
    adapter.require(
        identity["launcher"]["path"] == profile["tools"]["git"]["path"]
        and identity["launcher"]["sha256"] == profile["tools"]["git"]["sha256"]
        and identity["launcher"]["size"] == GIT_LAUNCHER_SIZES[architecture]
        and identity["implementation"]["path"]
        == str(PureWindowsPath(GIT_ROOT) / implementation["relative"])
        and identity["implementation"]["sha256"] == implementation["sha256"]
        and identity["implementation"]["size"] == implementation["size"]
        and all(
            entry["pe_machine"] == profile["host"]["native_machine"] for entry in identity.values()
        ),
        "Original complete Git launcher/implementation identity differs",
    )


def validate_report(report, sdk, tools, compiler, host):
    """Validate a portable admission and its actual consumer identities, with no I/O.

    The caller must also bind report.helper_sha256 to this helper's physical
    source bytes and retain the report under its evidence inventory/hash gate.
    Historical preparation bytes remain a separate authenticated input.
    """
    adapter.require(
        report["schema_version"] == 1
        and report["status"] == "prepared"
        and "error" not in report
        and all(
            report[field] is False
            for field in (
                "qualified",
                "sdk_tested",
                "qt_tested",
                "native_freecad_tested",
                "promotion_allowed",
            )
        )
        and report["sdk"] == sdk
        and sdk["key"] in PREPARATIONS
        and sdk["key"].rsplit("-", 1) == [sdk["release"], sdk["architecture"]]
        and re.fullmatch(r"[0-9a-f]{64}", report["helper_sha256"])
        and report["adapter_sha256"] == ADAPTER_SHA
        and report["baseline_helper_sha256"] == BASELINE_HELPER_SHA
        and report["historical_preparation"]
        == {
            "run_id": ORIGINAL_RUN,
            "head_sha": ORIGINAL_HEAD,
            "preparation_sha256": PREPARATIONS[sdk["key"]],
            "preparation_adapter_sha256": ORIGINAL_ADAPTER,
            "source_pin": adapter.SOURCES[sdk["release"]],
        }
        and report["expected"] == PROFILES[sdk["architecture"]],
        "Host-tool admission source/historical preparation/scope differs",
    )
    validate_producer(report["producer"])
    profile, qualification = selected_profile(sdk, report["after"]["tools"], report["producer"])
    adapter.require(
        report["qualification_profile"] == qualification
        and report["qualification_files_before"] == (CURRENT_FILES if qualification else {})
        and report["qualification_files_after"] == (CURRENT_FILES if qualification else {}),
        "Finite current-image qualification metadata/implementation differs",
    )
    validate(report["before"], profile, allow_git_drift=True)
    validate(report["after"], profile)
    adapter.require(
        report["after"]["tools"] == tools == profile["tools"]
        and report["after"]["host"] == host == profile["host"]
        and all(compiler.get(name) == value for name, value in profile["compiler"].items())
        and all(
            report["after"]["compiler"].get(name) == compiler.get(name)
            for name in profile["compiler"]
        ),
        "Actual consumer host/compiler/tools differ from their admitted profile",
    )
    validate_git(report["git_distribution"], profile, sdk["architecture"])
    adapter.require(
        report["git_version"]["argv"] == [profile["tools"]["git"]["path"], "--version"]
        and report["git_version"]["returncode"] == 0
        and report["git_version"]["stdout"] == GIT_VERSION,
        "Original complete Git version proof differs",
    )
    if report["action"] == "already-matched":
        adapter.require(
            report["installer_executed"] is False
            and report["before"] == report["after"]
            and "installer" not in report
            and "installer_execution" not in report,
            "Matching host-tool route claims an installation/change",
        )
    else:
        asset = INSTALLERS[sdk["architecture"]]
        installer = report["installer"]
        execution = report["installer_execution"]
        arguments = execution["argv"]
        adapter.require(
            report["action"] == "git-restored"
            and report["installer_executed"] is True
            and report["before"]["tools"]["git"] != profile["tools"]["git"]
            and all(installer.get(name) == value for name, value in asset.items())
            and installer["url"]
            == "https://github.com/git-for-windows/git/releases/download/"
            + "v2.55.0.windows.5/"
            + asset["filename"]
            and installer["whole_asset_authenticated"] is True
            and PureWindowsPath(installer["path"]).name == asset["filename"]
            and arguments[:-1]
            == [
                installer["path"],
                "/VERYSILENT",
                "/NORESTART",
                "/NOCANCEL",
                "/SP-",
                "/SUPPRESSMSGBOXES",
                "/ALLOWDOWNGRADE=1",
                "/DIR=" + GIT_ROOT,
            ]
            and arguments[-1].startswith("/LOG=")
            and PureWindowsPath(arguments[-1][5:])
            == PureWindowsPath(installer["path"]).parent / "evidence/git-installer.log"
            and execution["returncode"] == 0
            and re.fullmatch(r"[0-9a-f]{64}", execution["log_sha256"])
            and 0 <= execution["log_size"] <= 2 * 1024 * 1024,
            "Complete original Git installer authentication/execution differs",
        )
    return qualification["id"] if qualification else "historical-tools"


def prepare(args, helper):
    sdk = helper.sdk_identity(args.sdk)
    adapter.require(args.sdk in PREPARATIONS, "Unpinned original tool preparation")
    temporary = helper.real_path(Path(os.environ["RUNNER_TEMP"]))
    destination = helper.real_path(args.work_dir)
    adapter.require(
        temporary.is_dir()
        and destination != temporary
        and destination.is_relative_to(temporary)
        and not any(char in str(destination) for char in '\r\n"%&|<>^'),
        "Use a fresh safe work directory under RUNNER_TEMP",
    )
    work = helper.fresh_work(destination)
    evidence = work / "evidence"
    evidence.mkdir()
    report = {
        "schema_version": 1,
        "status": "failed",
        "qualified": False,
        "sdk_tested": False,
        "qt_tested": False,
        "native_freecad_tested": False,
        "promotion_allowed": False,
        "sdk": sdk,
        "helper_sha256": adapter.digest(Path(__file__)),
        "adapter_sha256": adapter.digest(Path(adapter.__file__)),
        "baseline_helper_sha256": adapter.digest(Path(helper.__file__)),
        "historical_preparation": {
            "run_id": ORIGINAL_RUN,
            "head_sha": ORIGINAL_HEAD,
            "preparation_sha256": PREPARATIONS[args.sdk],
            "preparation_adapter_sha256": ORIGINAL_ADAPTER,
            "source_pin": adapter.SOURCES[sdk["release"]],
        },
        "installer_executed": False,
        "work_dir": str(work),
        "producer": producer_context(),
        "qualification_profile": None,
        "qualification_files_before": {},
        "qualification_files_after": {},
    }
    adapter.write_json(
        evidence / "bootstrap-source.json",
        {
            "helper_sha256": report["helper_sha256"],
            "historical_preparation": report["historical_preparation"],
            "qualified": False,
        },
    )
    try:
        adapter.require(
            os.environ.get("GITHUB_ACTIONS") == "true"
            and os.environ.get("GITHUB_REPOSITORY") == "zukomgwili/FreeCAD",
            "Original tool restoration requires this repository's disposable Actions runner",
        )
        adapter.require(sys.platform == "win32", "Original tools require a native Windows runner")
        validate_producer(report["producer"])
        original = PROFILES[sdk["architecture"]]
        report["expected"] = original
        environment, report["before"] = observe(work, evidence, sdk["architecture"], helper)
        report["host_tool_diagnostics"] = retain_drift_diagnostics(
            report["before"], original, evidence, helper
        )
        profile, report["qualification_profile"] = selected_profile(
            sdk, report["before"]["tools"], report["producer"]
        )
        validate(report["before"], profile, allow_git_drift=True)
        if report["qualification_profile"]:
            report["qualification_files_before"] = qualification_files(helper)
        environment = adapter.native_environment(environment, report["before"]["compiler"], helper)
        if report["before"]["tools"]["git"] == profile["tools"]["git"]:
            report["action"] = "already-matched"
            report["after"] = report["before"]
        else:
            # Restore the full distribution; bin/git.exe is only a small launcher.
            asset = INSTALLERS[sdk["architecture"]]
            installer = work / asset["filename"]
            report["installer"] = download_installer(asset, installer)
            report["installer_executed"] = True
            report["installer_execution"] = install_git(installer, evidence, environment)
            environment, report["after"] = observe(work, evidence, sdk["architecture"], helper)
            validate(report["after"], profile)
            environment = adapter.native_environment(
                environment, report["after"]["compiler"], helper
            )
            report["action"] = "git-restored"
        validate(report["after"], profile)
        if report["qualification_profile"]:
            report["qualification_files_after"] = qualification_files(helper)
        report["git_distribution"] = git_identity(profile, sdk["architecture"], helper)
        validate_git(report["git_distribution"], profile, sdk["architecture"])
        version = helper.command(
            [profile["tools"]["git"]["path"], "--version"],
            evidence,
            "git-version",
            environment,
        )
        report["git_version"] = version
        adapter.require(version["stdout"] == GIT_VERSION, "Original Git version differs")
        report["status"] = "prepared"
        validate_report(
            report,
            sdk,
            report["after"]["tools"],
            report["after"]["compiler"],
            report["after"]["host"],
        )
    except BaseException as error:
        report["status"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"[:4096]
        raise
    finally:
        report["evidence_sha256"] = {
            name: entry["sha256"] for name, entry in helper.inventory(evidence)["files"].items()
        }
        adapter.write_json(work / "host-tools.json", report)
    return report


def main():
    sys.dont_write_bytecode = True
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", choices=PREPARATIONS, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare(args, adapter.baseline_helper())
        print(
            json.dumps({"status": result["status"], "action": result["action"], "qualified": False})
        )
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
