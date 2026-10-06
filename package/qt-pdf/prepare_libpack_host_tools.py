# SPDX-License-Identifier: LGPL-2.1-or-later
"""Restore the original Git distribution before a pinned LibPack recovery.

The current native host, compiler and all non-Git tools must already match the
historical preparation. Only a changed Git hash at its original path permits
the complete, authenticated official installer. This does not qualify an SDK,
alter historical receipts, or relax any later capture/tool identity checks.
"""

import argparse
import json
import os
from pathlib import Path
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
        same_path = actual.get("path") == expected["path"]
        same_hash = actual.get("sha256") == expected["sha256"]
        if not same_path or (not same_hash and not (allow_git_drift and name == "git")):
            changes[name] = {"expected": expected, "actual": actual}
    adapter.require(
        not changes,
        "Original build-tool identity differs: " + json.dumps(changes, sort_keys=True),
    )


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
        and identity["implementation"]["path"] == str(Path(GIT_ROOT) / implementation["relative"])
        and identity["implementation"]["sha256"] == implementation["sha256"]
        and identity["implementation"]["size"] == implementation["size"]
        and all(
            entry["pe_machine"] == profile["host"]["native_machine"] for entry in identity.values()
        ),
        "Original complete Git launcher/implementation identity differs",
    )


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
        profile = PROFILES[sdk["architecture"]]
        report["expected"] = profile
        environment, report["before"] = observe(work, evidence, sdk["architecture"], helper)
        validate(report["before"], profile, allow_git_drift=True)
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
    except BaseException as error:
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
