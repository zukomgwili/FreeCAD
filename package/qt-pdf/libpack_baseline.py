# SPDX-License-Identifier: LGPL-2.1-or-later
"""Capture a released Windows LibPack baseline; inspect its PDFs separately.

generate uses only standard Python, CMake, Ninja, MSVC v143 and 7-Zip. inspect
requires pypdf, Pillow and Poppler on its checking host. No SDK DLLs are uploaded,
no candidate is built, and neither command qualifies a fix or native FreeCAD.
"""

import argparse
import ctypes
import hashlib
import importlib.util
from importlib.metadata import version
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import stat
import struct
import subprocess
import sys
import urllib.request

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests/src/Mod/TechDraw/Gui/QtPdfStroker"
QT_VERSION = "6.11.1"
MACHINES = {"x64": 0x8664, "arm64": 0xAA64}
SDK_KEYS = {
    "3.5.3-x64": (
        483596555,
        651481450,
        "dcaa2d21f61b0607cf06b6e98f6e7525dc266c04c20e7b4d7b2c77bec24366e7",
        "94cda1f16a388b0a70b814d0f8d684301787f4da",
    ),
    "3.5.5-x64": (
        525903581,
        652754768,
        "f7638af6be3a2ea75995dbc74a5cd1408e6d20aefda45a11be1f343e910eeedb",
        "6641ccccc9f6dd3541acaf0d5f53a89cde3ecf59",
    ),
    "3.5.5-arm64": (
        526419780,
        516933454,
        "f64f8e730d66a1f6edf911ca9a86e562cbde5e45a2b23179acb3883ceb734f94",
        "6641ccccc9f6dd3541acaf0d5f53a89cde3ecf59",
    ),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sdk_identity(key):
    asset, size, sha, commit = SDK_KEYS[key]
    release, architecture = key.rsplit("-", 1)
    label = "ARM64" if architecture == "arm64" else "x64"
    stem = f"LibPack-26.3.0-v{release}-{label}-Release"
    return {
        "key": key,
        "release": release,
        "architecture": architecture,
        "experimental": release == "3.5.5",
        "asset_id": asset,
        "size": size,
        "sha256": sha,
        "filename": stem + ".7z",
        "directory": stem,
        "url": f"https://github.com/FreeCAD/FreeCAD-LibPack/releases/download/{release}/{stem}.7z",
        "asset_api": f"https://api.github.com/repos/FreeCAD/FreeCAD-LibPack/releases/assets/{asset}",
        "source_commit": commit,
        "source_url": f"https://github.com/FreeCAD/FreeCAD-LibPack/tree/{commit}",
    }


def real_path(path):
    """Reject links/junctions rather than accepting their resolved destinations."""
    path = path.absolute()
    for entry in (path, *path.parents):
        try:
            attributes = entry.lstat()
        except FileNotFoundError:
            continue
        else:
            require(
                not stat.S_ISLNK(attributes.st_mode)
                and not getattr(attributes, "st_file_attributes", 0)
                & stat.FILE_ATTRIBUTE_REPARSE_POINT,
                f"Linked/reparse path is forbidden: {entry}",
            )
    return path.resolve()


def fresh_work(path):
    path = real_path(path)
    require(not path.exists(), "Work directory must be fresh")
    require(path.parent.is_dir(), "Work parent must exist")
    require(
        path != Path(path.anchor)
        and not path.is_relative_to(REPO)
        and not path.is_relative_to(Path.home().resolve()),
        "Work directory must be outside the repository, user home and filesystem root",
    )
    for ancestor in path.parents:
        require(not (ancestor / "conda-meta").exists(), "Work directory is in an installed SDK")
    path.mkdir(exist_ok=False)
    return path


def traversal_error(error):
    raise error


def inventory(root):
    files = {}
    directories = []
    for parent, dirs, names in os.walk(root, followlinks=False, onerror=traversal_error):
        for name in dirs + names:
            path = Path(parent) / name
            real_path(path)
            relative = path.relative_to(root).as_posix()
            if path.is_dir():
                directories.append(relative)
            else:
                require(path.is_file(), f"Non-regular SDK entry: {path}")
                info = path.stat()
                files[relative] = {
                    "size": info.st_size,
                    "mtime_ns": info.st_mtime_ns,
                    "sha256": digest(path),
                }
    require(files, "SDK inventory is empty")
    require(len({name.casefold() for name in files}) == len(files), "Case-colliding SDK files")
    return {"files": files, "directories": sorted(directories)}


def archive_members(text, directory):
    """Validate 7z's UTF-8 technical listing before extraction."""
    require("----------\n" in text, "Missing 7z member listing")
    names = set()
    for block in text.split("----------\n", 1)[1].strip().split("\n\n"):
        fields = dict(line.split(" = ", 1) for line in block.splitlines() if " = " in line)
        name = fields.get("Path", "")
        path = PureWindowsPath(name)
        require(
            name
            and not path.drive
            and not path.root
            and path.parts[0] == directory
            and all(part not in (".", "..") and ":" not in part for part in path.parts)
            and all(part not in (".", "..") for part in name.replace("\\", "/").split("/"))
            and not any(
                "link" in field.casefold() or "reparse" in field.casefold() for field in fields
            ),
            f"Unsafe archive member: {name}",
        )
        normalized = str(path).casefold()
        require(normalized not in names, f"Duplicate archive member: {name}")
        names.add(normalized)
    require(names, "Archive has no members")
    return len(names)


def native_machine():
    require(sys.platform == "win32", "Generation requires native Windows")
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
    return {"native_machine": native.value, "python_process_machine": process.value}


def pe_machine(path):
    with Path(path).open("rb") as source:
        header = source.read(64)
        require(len(header) == 64 and header[:2] == b"MZ", f"Not a PE executable: {path}")
        source.seek(struct.unpack_from("<I", header, 60)[0])
        pe = source.read(6)
        require(pe[:4] == b"PE\0\0" and len(pe) == 6, f"Invalid PE header: {path}")
        return struct.unpack_from("<H", pe, 4)[0]


def file_version(path):
    """Record native version resources; some plugins do not supply one."""
    library = ctypes.WinDLL("version", use_last_error=True)
    library.GetFileVersionInfoSizeW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
    library.GetFileVersionInfoSizeW.restype = ctypes.c_ulong
    library.GetFileVersionInfoW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_void_p,
    ]
    library.VerQueryValueW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_uint),
    ]
    ignored = ctypes.c_ulong()
    size = library.GetFileVersionInfoSizeW(str(path), ctypes.byref(ignored))
    if not size:
        return None
    buffer = ctypes.create_string_buffer(size)
    require(library.GetFileVersionInfoW(str(path), 0, size, buffer), "Version resource read failed")
    pointer, length = ctypes.c_void_p(), ctypes.c_uint()
    require(
        library.VerQueryValueW(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)),
        "Version resource query failed",
    )
    require(length.value >= 52, "Short version resource")
    words = struct.unpack("<13I", ctypes.string_at(pointer, 52))
    require(words[0] == 0xFEEF04BD, "Invalid version resource signature")
    return [words[2] >> 16, words[2] & 65535, words[3] >> 16, words[3] & 65535]


def command(argv, evidence, label, environment=None, check=True):
    result = subprocess.run(
        argv, capture_output=True, text=True, encoding="utf-8", errors="replace", env=environment
    )
    (evidence / (label + ".log")).write_text(result.stdout + result.stderr, encoding="utf-8")
    require(not check or result.returncode == 0, f"{label} failed ({result.returncode})")
    return {
        "argv": [str(item) for item in argv],
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
    }


def parse_environment(output):
    return {
        line.split("=", 1)[0].upper(): line.split("=", 1)[1]
        for line in output.splitlines()
        if "=" in line and not line.startswith("=")
    }


def compiler_environment(work, evidence, architecture):
    vswhere = (
        Path(os.environ["ProgramFiles(x86)"]) / "Microsoft Visual Studio/Installer/vswhere.exe"
    )
    query = command(
        [
            str(vswhere),
            "-latest",
            "-products",
            "*",
            "-requires",
            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
            "-property",
            "installationPath",
        ],
        evidence,
        "vswhere",
    )
    installation = query["stdout"]
    require(
        installation and not any(char in installation for char in '\r\n"%&|<>^'),
        "Invalid Visual Studio location",
    )
    batch = (
        Path(installation)
        / "VC/Auxiliary/Build"
        / ("vcvarsarm64.bat" if architecture == "arm64" else "vcvars64.bat")
    )
    require(batch.is_file(), "Matching native MSVC initialization is unavailable")
    # A fixed script avoids command-string interpolation through user arguments.
    script = work / "compiler.cmd"
    script.write_text(
        f'@echo off\nset VSCMD_DEBUG=0\ncall "{batch}" -vcvars_ver=14.4 >nul\nif errorlevel 1 exit /b 1\nset\n',
        encoding="utf-8",
    )
    # `set` includes inherited credentials. Parse privately; never persist stdout.
    result = subprocess.run(
        [os.environ["COMSPEC"], "/d", "/c", str(script)],
        capture_output=True,
        text=True,
        errors="replace",
    )
    (evidence / "compiler-initialization.log").write_text(result.stderr, encoding="utf-8")
    require(result.returncode == 0, "MSVC initialization failed")
    environment = parse_environment(result.stdout)
    version = environment.get("VCTOOLSVERSION", "")
    require(re.fullmatch(r"14\.4\d\.\d+\\?", version), "MSVC v143 (14.4x) toolset is unavailable")
    compiler = shutil.which("cl.exe", path=environment.get("PATH"))
    require(
        compiler and version.rstrip("\\") in Path(compiler).parts,
        "Compiler is outside the recorded v143 toolset",
    )
    banner = command([compiler], evidence, "cl-version", environment, check=False)
    return environment, {
        "tools_version": version.rstrip("\\"),
        "compiler": compiler,
        "compiler_sha256": digest(compiler),
        "banner": banner,
        "vswhere": query,
        "initialization": str(batch),
    }


def verify_runtime(runtime, manifest, sdk, sdk_inventory, architecture, module_receipts):
    require(
        runtime.get("schema_version") == 1 and manifest.get("schema_version") == 2,
        "Unsupported runtime/manifest schema",
    )
    require(
        runtime["qt_version"] == manifest["qt_version"] == QT_VERSION, "Expected actual Qt 6.11.1"
    )
    require(
        runtime["platform"] == "winnt" and runtime["platform_plugin"] == "offscreen",
        "Expected Windows/offscreen runtime",
    )
    expected_arch = "arm64" if architecture == "arm64" else "x86_64"
    require(runtime["architecture"] == expected_arch, "Qt runtime architecture differs from target")
    require(
        runtime["build_abi"].startswith(expected_arch + "-"), "Qt build ABI differs from target"
    )
    root = PureWindowsPath(sdk)
    require(root.is_absolute(), "Expected an absolute native SDK root")
    found, plugin, paths = set(), False, set()
    receipts = {entry["path"]: entry for entry in module_receipts}
    require(len(receipts) == len(module_receipts), "Duplicated module receipts")
    for module in runtime["qt_modules"]:
        path = PureWindowsPath(module["path"])
        require(
            path.is_absolute() and path not in paths and ".." not in path.parts,
            "Invalid loaded module path",
        )
        paths.add(path)
        relative = path.relative_to(root).as_posix()
        require(
            relative in sdk_inventory["files"], "Loaded Qt module is absent from the SDK inventory"
        )
        require(
            module["sha256"] == sdk_inventory["files"][relative]["sha256"],
            "Loaded Qt hash differs from SDK inventory",
        )
        receipt = receipts.pop(module["path"], None)
        require(
            receipt
            and receipt["sdk_relative_path"] == relative
            and receipt["sha256"] == module["sha256"],
            "Module transport mapping differs",
        )
        require(
            receipt["pe_machine"] == MACHINES[architecture], "Loaded module PE architecture differs"
        )
        version = receipt["file_version"]
        require(version is None or version[:3] == [6, 11, 1], "Loaded DLL version resource differs")
        if module["kind"] == "library":
            require(path.parent == root / "bin", "Qt DLL did not load from SDK bin")
            match = re.fullmatch(r"Qt6(.+)\.dll", path.name, re.IGNORECASE)
            require(match, "Unexpected Qt DLL name")
            found.add(match[1].casefold())
        else:
            require(
                module["kind"] == "plugin" and path.is_relative_to(root / "plugins"),
                "Qt plugin came from another directory",
            )
            plugin |= path == root / "plugins/platforms/qoffscreen.dll"
    require(not receipts, "Unexpected module receipts")
    require(
        {"core", "gui", "widgets", "printsupport"}.issubset(found) and plugin,
        "Required Qt DLLs/offscreen plugin were not captured",
    )


def generate(args):
    sdk = sdk_identity(args.sdk)
    host = native_machine()
    require(
        host["native_machine"] == MACHINES[sdk["architecture"]],
        "SDK requires a matching native Windows host",
    )
    work = fresh_work(args.work_dir)
    evidence = work / "evidence"
    evidence.mkdir()
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write(f"evidence_dir={evidence}\n")
    report = {
        "schema_version": 1,
        "baseline_only": True,
        "qualified": False,
        "candidate_sdk": None,
        "native_freecad_tested": False,
        "sdk": sdk,
        "host": host,
        "sdk_root": str(work / sdk["directory"]),
        "status": "failed",
        "sdk_unchanged": False,
        "helper_sha256": digest(Path(__file__)),
    }
    before = None
    try:
        require(not any(char in str(work) for char in '\r\n"%&|<>^'), "Unsafe Windows command path")
        environment, report["compiler"] = compiler_environment(work, evidence, sdk["architecture"])
        report["tools"] = {
            name: command([name, flag], evidence, name + "-version", environment)
            for name, flag in [("cmake", "--version"), ("ninja", "--version"), ("7z", "i")]
        }
        archive = work / sdk["filename"]
        request = urllib.request.Request(
            sdk["url"], headers={"User-Agent": "FreeCAD-LibPack-baseline"}
        )
        with urllib.request.urlopen(request, timeout=60) as response, archive.open(
            "xb"
        ) as destination:
            length = 0
            for block in iter(lambda: response.read(1024 * 1024), b""):
                length += len(block)
                require(length <= sdk["size"], "SDK download exceeded its pinned size")
                destination.write(block)
        require(
            archive.stat().st_size == sdk["size"] and digest(archive) == sdk["sha256"],
            "SDK archive size/SHA differs from pinned release",
        )
        report["archive_sha256_verified"] = True
        listing = command(
            ["7z", "l", "-slt", "-sccUTF-8", str(archive)], evidence, "archive-list", environment
        )
        report["archive_members"] = archive_members(
            listing["stdout"].replace("\r\n", "\n"), sdk["directory"]
        )
        command(["7z", "x", "-y", str(archive), "-o" + str(work)], evidence, "extract", environment)
        root = work / sdk["directory"]
        before = inventory(root)
        write_json(evidence / "sdk-before.json", before)
        header = (root / "include/QtCore/qtcoreversion.h").read_text(encoding="utf-8")
        require(
            re.search(r'#define\s+QTCORE_VERSION_STR\s+"6\.11\.1"', header),
            "SDK Qt header is not 6.11.1",
        )
        report["header_sha256"] = digest(root / "include/QtCore/qtcoreversion.h")
        shutil.copyfile(root / "include/QtCore/qtcoreversion.h", evidence / "qtcoreversion.h")
        report["sources"] = {
            name: digest(FIXTURE / name)
            for name in ("generator.cpp", "CMakeLists.txt", "compare.py")
        }
        for name in report["sources"]:
            shutil.copyfile(FIXTURE / name, evidence / name)
        build = work / "build"
        report["configure"] = command(
            [
                "cmake",
                "-S",
                str(FIXTURE),
                "-B",
                str(build),
                "-G",
                "Ninja",
                "-DCMAKE_BUILD_TYPE=Release",
                "-DWITH_QPRINTER=ON",
                "-DCMAKE_PREFIX_PATH=" + str(root),
                "-DQt6_DIR=" + str(root / "lib/cmake/Qt6"),
                "-DCMAKE_CXX_COMPILER=" + report["compiler"]["compiler"],
            ],
            evidence,
            "configure",
            environment,
        )
        report["build"] = command(
            [
                "cmake",
                "--build",
                str(build),
                "--target",
                "qt_pdf_stroker_fixture",
                "--parallel",
                "2",
            ],
            evidence,
            "build",
            environment,
        )
        executable = build / "qt_pdf_stroker_fixture.exe"
        report["fixture_pe_machine"] = pe_machine(executable)
        require(
            report["fixture_pe_machine"] == MACHINES[sdk["architecture"]],
            "Fixture executable architecture differs",
        )
        report["fixture_sha256"] = digest(executable)
        run_environment = environment.copy()
        run_environment.update(
            {
                "PATH": str(root / "bin") + os.pathsep + environment["PATH"],
                "QT_PLUGIN_PATH": str(root / "plugins"),
                "QT_QPA_PLATFORM_PLUGIN_PATH": str(root / "plugins/platforms"),
                "QT_QPA_PLATFORM": "offscreen",
            }
        )
        pdfs = evidence / "pdfs"
        report["generation"] = command(
            [str(executable), "--output", str(pdfs), "--device", "both"],
            evidence,
            "generate",
            run_environment,
        )
        runtime = json.loads((pdfs / "runtime.json").read_text())
        manifest = json.loads((pdfs / "manifest.json").read_text())
        report["modules"] = [
            {
                "path": entry["path"],
                "sdk_relative_path": PureWindowsPath(entry["path"])
                .relative_to(PureWindowsPath(root))
                .as_posix(),
                "sha256": digest(Path(entry["path"])),
                "pe_machine": pe_machine(Path(entry["path"])),
                "file_version": file_version(Path(entry["path"])),
            }
            for entry in runtime["qt_modules"]
        ]
        verify_runtime(runtime, manifest, str(root), before, sdk["architecture"], report["modules"])
        report["status"] = "generated"
    except Exception as error:
        report["error"] = str(error)
    finally:
        if before is not None:
            try:
                after = inventory(work / sdk["directory"])
                write_json(evidence / "sdk-after.json", after)
                report["sdk_unchanged"] = before == after
                require(report["sdk_unchanged"], "Released SDK changed during baseline generation")
            except Exception as error:
                report["status"] = "failed"
                report["error"] = str(error)
        report["evidence_sha256"] = {
            path.relative_to(evidence).as_posix(): digest(path)
            for path in evidence.rglob("*")
            if path.is_file()
        }
        report["ci"] = {
            key: os.environ.get(key)
            for key in (
                "GITHUB_SHA",
                "GITHUB_RUN_ID",
                "GITHUB_REPOSITORY",
                "RUNNER_OS",
                "RUNNER_ARCH",
            )
        }
        write_json(evidence / "generation.json", report)
    require(
        report["status"] == "generated" and report["sdk_unchanged"],
        report.get("error", "Generation failed"),
    )
    return {"evidence_dir": str(evidence), "baseline_only": True, "qualified": False}


def check_output_location(destination, evidence, sdk_root):
    require(not destination.is_relative_to(evidence), "Output must be outside input evidence")
    # Compare Windows roots lexically on Linux; never resolve them on this host.
    require(
        not PureWindowsPath(str(destination)).is_relative_to(PureWindowsPath(sdk_root)),
        "Output must be outside the recorded SDK",
    )


def inspect(args):
    evidence = real_path(args.evidence_dir)
    destination = real_path(args.report)
    require(
        destination.parent.is_dir() and not destination.exists(),
        "Report path must be fresh with an existing parent",
    )
    generation = json.loads((evidence / "generation.json").read_text())
    renders = real_path(destination.with_suffix(".renders"))
    # These checks stay outside the caught-error/report writer below.
    check_output_location(destination, evidence, generation["sdk_root"])
    check_output_location(renders, evidence, generation["sdk_root"])
    report = {
        "schema_version": 1,
        "baseline_only": True,
        "qualified": False,
        "candidate_sdk": None,
        "native_freecad_tested": False,
        "failures": [],
    }
    try:
        require(
            generation["helper_sha256"] == digest(Path(__file__)),
            "Native generation helper differs from inspection checkout",
        )
        sdk = sdk_identity(generation["sdk"]["key"])
        require(generation["sdk"] == sdk, "SDK identity differs from pinned release")
        require(
            PureWindowsPath(generation["sdk_root"]).name == sdk["directory"],
            "Native SDK directory differs from selected release",
        )
        require(
            generation["status"] == "generated"
            and generation["baseline_only"]
            and not generation["qualified"]
            and generation["candidate_sdk"] is None
            and generation["sdk_unchanged"]
            and generation["archive_sha256_verified"],
            "Native baseline generation was not complete",
        )
        require(
            generation["host"]["native_machine"] == MACHINES[sdk["architecture"]],
            "Native Windows host does not match SDK",
        )
        require(
            generation["fixture_pe_machine"] == MACHINES[sdk["architecture"]],
            "Fixture PE architecture does not match SDK",
        )
        require(
            re.fullmatch(r"14\.4\d\.\d+", generation["compiler"]["tools_version"]),
            "Expected recorded MSVC v143 toolset",
        )
        actual_files = {
            path.relative_to(evidence).as_posix()
            for path in evidence.rglob("*")
            if path.is_file() and path != evidence / "generation.json"
        }
        require(
            set(generation["evidence_sha256"]) == actual_files,
            "Evidence inventory is incomplete or has extra files",
        )
        for relative, expected in generation["evidence_sha256"].items():
            relative_path = PureWindowsPath(relative)
            require(
                not relative_path.drive
                and not relative_path.root
                and ".." not in relative_path.parts
                and relative_path.as_posix() == relative,
                "Unsafe evidence mapping",
            )
            require(
                digest(real_path(evidence / relative)) == expected,
                f"Transported evidence changed: {relative}",
            )
        before = json.loads((evidence / "sdk-before.json").read_text())
        after = json.loads((evidence / "sdk-after.json").read_text())
        require(before == after, "SDK before/after inventories differ")
        require(
            before["files"]["include/QtCore/qtcoreversion.h"]["sha256"]
            == generation["header_sha256"],
            "Header proof differs from inventory",
        )
        require(
            digest(evidence / "qtcoreversion.h") == generation["header_sha256"]
            and re.search(
                r'#define\s+QTCORE_VERSION_STR\s+"6\.11\.1"',
                (evidence / "qtcoreversion.h").read_text(),
            ),
            "Transported header is not authenticated Qt 6.11.1",
        )
        require(
            set(generation["sources"]) == {"generator.cpp", "CMakeLists.txt", "compare.py"},
            "Incomplete fixture source proof",
        )
        for name, expected in generation["sources"].items():
            require(
                digest(FIXTURE / name) == digest(evidence / name) == expected,
                "Fixture source differs from inspection checkout",
            )
        specification = importlib.util.spec_from_file_location(
            "qt_pdf_baseline_comparison", FIXTURE / "compare.py"
        )
        comparison = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(comparison)
        pdfs = evidence / "pdfs"
        manifest = comparison.load_manifest(pdfs)
        runtime = json.loads((pdfs / "runtime.json").read_text())
        verify_runtime(
            runtime,
            manifest,
            generation["sdk_root"],
            before,
            sdk["architecture"],
            generation["modules"],
        )
        require(len(manifest["cases"]) == 66, "Expected 33 cases for each PDF device")
        require(manifest["raster_dpi"] == 100, "Unexpected raster resolution")
        require(
            not renders.exists() and not renders.is_symlink(), "Raster destination must be fresh"
        )
        renders.mkdir()
        paired = {}
        report.update(
            {
                "sdk": sdk,
                "native_generation_sha256": digest(evidence / "generation.json"),
                "runtime": runtime,
                "sdk_unchanged": True,
                "cases": [],
                "device_pairs": [],
                "runtime_proof_scope": "Native Windows hash/origin/PE checks; transported receipts checked on this host. SDK/DLL bytes are not rehosted.",
            }
        )
        pdftoppm = shutil.which("pdftoppm")
        require(pdftoppm, "Poppler pdftoppm is required")
        report["poppler_version"] = subprocess.run(
            [pdftoppm, "-v"], capture_output=True, text=True, check=False
        ).stderr.strip()
        report["checking_versions"] = {
            "python": sys.version,
            "pypdf": version("pypdf"),
            "Pillow": version("Pillow"),
        }
        for case in manifest["cases"]:
            pdf = pdfs / case["pdf"]
            operators, _, _ = comparison.inspect_operators(pdf)
            copied = renders / case["pdf"]
            shutil.copyfile(pdf, copied)
            raster, _ = comparison.rasterize(copied, manifest["raster_dpi"], pdftoppm)
            failures = list(operators["path_errors"])
            if operators["invalid_close_count"] != raster["closepath_warnings"]:
                failures.append("Invalid close operators and Poppler warnings differ")
            if any(
                comparison.WARNING not in line for line in raster["poppler_stderr"].splitlines()
            ):
                failures.append("Unexpected Poppler diagnostics")
            if bool(raster["ink_pixels"]) != case["expect_ink"]:
                failures.append("Visible ink control differs")
            if case["expected_color"] and not raster[case["expected_color"] + "_pixels"]:
                failures.append("Required colored ink is absent")
            paired.setdefault(case["scenario"], {})[case["device"]] = (
                raster["size"],
                raster["rgba_sha256"],
            )
            report["cases"].append(
                {
                    "name": case["name"],
                    "device": case["device"],
                    **operators,
                    **raster,
                    "expected_source_baseline_closes": case["baseline_invalid_closes"],
                    "matches_source_baseline_close_count": operators["invalid_close_count"]
                    == case["baseline_invalid_closes"],
                    "failures": failures,
                }
            )
            report["failures"].extend(case["name"] + ": " + failure for failure in failures)
        require(len(paired) == 33, "Expected 33 distinct paired scenarios")
        for scenario, devices in paired.items():
            require(set(devices) == {"qpdfwriter", "qprinter"}, "A PDF device is missing")
            equal = devices["qpdfwriter"] == devices["qprinter"]
            report["device_pairs"].append({"scenario": scenario, "same_pixels": equal})
            if not equal:
                report["failures"].append(scenario + ": PDF device pixels differ")
        report["invalid_close_count"] = sum(case["invalid_close_count"] for case in report["cases"])
        report["defective_cases"] = sum(
            bool(case["invalid_close_count"]) for case in report["cases"]
        )
        report["diagnostics_complete"] = not report["failures"]
    except Exception as error:
        report["failures"].append(str(error))
        report["diagnostics_complete"] = False
    write_json(destination, report)
    require(report["diagnostics_complete"], "Baseline inspection failed; see " + str(destination))
    return {"report": str(destination), "baseline_only": True, "qualified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    generate_parser = commands.add_parser("generate")
    generate_parser.add_argument("--sdk", choices=SDK_KEYS, required=True)
    generate_parser.add_argument("--work-dir", type=Path, required=True)
    inspect_parser = commands.add_parser("inspect")
    inspect_parser.add_argument("--evidence-dir", type=Path, required=True)
    inspect_parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(generate(args) if args.command == "generate" else inspect(args)))
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
