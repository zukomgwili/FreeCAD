# SPDX-License-Identifier: LGPL-2.1-or-later
"""Check relocated SDK Python/PySide/Qt origins on native Windows.

Run after install_delivered_libpack.py has verified the complete SDK. This
focused probe uses the selected bin/python.exe, isolated imports, disabled
bytecode writes and the selected offscreen plugin directory. The default mode
does not preload Qt DLLs. Explicit --qt-first emulates a Qt-linked C++ host by
loading four authenticated SDK/bin DLLs before Python bindings. Both modes
require actual patched SDK/bin mappings, rather than PySide's preserved private
copies. No PDFs or FreeCAD builds are produced, and this receipt does not replace
the original qualification.
"""

import argparse
import ctypes
from ctypes import wintypes
import importlib.util
import json
import os
from pathlib import Path, PureWindowsPath
import re
import struct
import subprocess
import sys
import tempfile

INSTALLER_PATH = Path(__file__).with_name("install_delivered_libpack.py")
SPEC = importlib.util.spec_from_file_location("delivered_libpack", INSTALLER_PATH)
delivered = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(delivered)
IMPORTS = {
    "PySide6": "bin/Lib/site-packages/PySide6/__init__.py",
    "PySide6.QtCore": "bin/Lib/site-packages/PySide6/QtCore.pyd",
    "PySide6.QtGui": "bin/Lib/site-packages/PySide6/QtGui.pyd",
    "PySide6.QtWidgets": "bin/Lib/site-packages/PySide6/QtWidgets.pyd",
    "PySide6.QtPrintSupport": "bin/Lib/site-packages/PySide6/QtPrintSupport.pyd",
    "shiboken6": "bin/Lib/site-packages/shiboken6/__init__.py",
    "shiboken6.Shiboken": "bin/Lib/site-packages/shiboken6/Shiboken.pyd",
}
BINDINGS = {
    "python314.dll": "bin/python314.dll",
    "python3.dll": "bin/python3.dll",
    "pyside6.abi3.dll": "bin/Lib/site-packages/PySide6/pyside6.abi3.dll",
    "shiboken6.abi3.dll": "bin/Lib/site-packages/shiboken6/shiboken6.abi3.dll",
    "pyside6qml.abi3.dll": "bin/Lib/site-packages/PySide6/pyside6qml.abi3.dll",
}
REQUIRED_BINDINGS = {"python314.dll", "pyside6.abi3.dll", "shiboken6.abi3.dll"}
REQUIRED_QT = {"qt6core.dll", "qt6gui.dll", "qt6widgets.dll", "qt6printsupport.dll"}
QT_FIRST = ["bin/Qt6Core.dll", "bin/Qt6Gui.dll", "bin/Qt6Widgets.dll", "bin/Qt6PrintSupport.dll"]
SCOPE = "relocated-sdk-python-pyside-qt-origins-only"
MAX_REPORT_BYTES = 1024 * 1024


def machine(sdk):
    delivered.require(sdk in delivered.PINS, "Unknown delivered SDK")
    return 43620 if sdk.endswith("arm64") else 34404


def pe_machine(path):
    with path.open("rb") as stream:
        header = stream.read(64)
        delivered.require(len(header) == 64 and header[:2] == b"MZ", "Not a PE image")
        offset = struct.unpack_from("<I", header, 60)[0]
        delivered.require(64 <= offset <= path.stat().st_size - 6, "Invalid PE header offset")
        stream.seek(offset)
        header = stream.read(6)
    delivered.require(header[:4] == b"PE\0\0" and len(header) == 6, "Invalid PE header")
    return struct.unpack_from("<H", header, 4)[0]


def native_machine():
    delivered.require(sys.platform == "win32", "Origin probe requires native Windows")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    kernel.IsWow64Process2.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ushort),
        ctypes.POINTER(ctypes.c_ushort),
    ]
    kernel.IsWow64Process2.restype = wintypes.BOOL
    process, native = ctypes.c_ushort(), ctypes.c_ushort()
    delivered.require(
        kernel.IsWow64Process2(
            kernel.GetCurrentProcess(), ctypes.byref(process), ctypes.byref(native)
        ),
        "IsWow64Process2 failed",
    )
    return {"native_machine": native.value, "python_process_machine": process.value}


def loaded_images():
    """Read actual current-process modules using the Windows Toolhelp API."""

    class ModuleEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("th32ModuleID", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("GlblcntUsage", wintypes.DWORD),
            ("ProccntUsage", wintypes.DWORD),
            ("modBaseAddr", ctypes.c_void_p),
            ("modBaseSize", wintypes.DWORD),
            ("hModule", wintypes.HMODULE),
            ("szModule", wintypes.WCHAR * 256),
            ("szExePath", wintypes.WCHAR * 260),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for function in (kernel.Module32FirstW, kernel.Module32NextW):
        function.argtypes = [wintypes.HANDLE, ctypes.POINTER(ModuleEntry)]
        function.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateToolhelp32Snapshot(0x8 | 0x10, os.getpid())
    delivered.require(handle != ctypes.c_void_p(-1).value, "Module snapshot failed")
    result = []
    try:
        entry = ModuleEntry()
        entry.dwSize = ctypes.sizeof(entry)
        delivered.require(kernel.Module32FirstW(handle, ctypes.byref(entry)), "First module failed")
        while True:
            delivered.require(
                len(result) < 4096 and len(entry.szExePath) < 259, "Excess/truncated modules"
            )
            result.append(entry.szExePath)
            if not kernel.Module32NextW(handle, ctypes.byref(entry)):
                delivered.require(ctypes.get_last_error() == 18, "Module iteration failed")
                break
    finally:
        delivered.require(kernel.CloseHandle(handle), "Module snapshot close failed")
    delivered.require(
        len(result) == len(set(path.casefold() for path in result)), "Duplicated module path"
    )
    return sorted(result)


def file_record(path):
    path = delivered.physical(path)
    before = delivered.archive_identity(path)
    result = {
        "path": str(path),
        "size": path.stat().st_size,
        "sha256": delivered.digest(path),
        "pe_machine": (
            pe_machine(path) if path.suffix.casefold() in (".exe", ".dll", ".pyd") else None
        ),
    }
    delivered.require(
        delivered.archive_identity(path) == before, "Runtime input changed during readback"
    )
    return result


def validate_file(record, root, name, index, architecture, *, executable=True):
    delivered.require(
        isinstance(record, dict) and name in index["files"], "Missing runtime image record/index"
    )
    path = PureWindowsPath(record.get("path", ""))
    expected = index["files"][name]
    delivered.require(
        path.is_absolute()
        and ".." not in path.parts
        and path == root / name
        and delivered.integer(record.get("size"))
        and record["size"] == expected["size"]
        and record.get("sha256") == expected["sha256"]
        and (
            delivered.integer(record.get("pe_machine")) and record["pe_machine"] == architecture
            if executable
            else record.get("pe_machine") is None
        ),
        f"Runtime origin/hash/size/PE differs: {name}",
    )


def validate_observation(report, sdk, prefix, index, *, qt_first=False):
    """Portable strict consumer of the actual native observations."""
    delivered.require(
        isinstance(report, dict) and isinstance(qt_first, bool), "Invalid runtime observation/mode"
    )
    root, architecture = PureWindowsPath(prefix), machine(sdk)
    delivered.require(root.is_absolute() and ".." not in root.parts, "Invalid SDK prefix")
    delivered.require(
        report.get("schema_version") == 1
        and delivered.integer(report["schema_version"])
        and report.get("scope") == SCOPE
        and report.get("sdk") == sdk
        and PureWindowsPath(report.get("prefix", "")) == root
        and report.get("platform") == "win32"
        and "error" not in report
        and report.get("host") == {"native_machine": architecture, "python_process_machine": 0}
        and all(delivered.integer(value) for value in report["host"].values())
        and report.get("qt_preloaded") is qt_first
        and report.get("loader_configuration")
        == {
            "mode": "authenticated-sdk-bin-qt-first" if qt_first else "unpreloaded-sdk-python",
            "dll_directories": [str(root / "bin")] if qt_first else [],
            "preloaded": QT_FIRST if qt_first else [],
        }
        and report.get("bytecode_disabled") is True
        and report.get("isolated_python") is True
        and report.get("versions") == {"qt": "6.11.1", "pyside": "6.11.1", "shiboken": "6.11.1"}
        and report.get("qpa_platform") == "offscreen",
        "Relocated runtime scope/architecture/versions/platform differs",
    )
    python = report["python"]
    delivered.require(
        PureWindowsPath(python["prefix"]) == PureWindowsPath(python["base_prefix"]) == root / "bin"
        and isinstance(python["version"], list)
        and len(python["version"]) == 3
        and all(delivered.integer(number) for number in python["version"])
        and python["version"][:2] == [3, 14]
        and isinstance(python["path"], list)
        and 0 < len(python["path"]) <= 32
        and all(
            PureWindowsPath(path).is_absolute()
            and ".." not in PureWindowsPath(path).parts
            and PureWindowsPath(path).is_relative_to(root / "bin")
            for path in python["path"]
        ),
        "SDK Python prefix/version/import search differs",
    )
    validate_file(python["executable"], root, "bin/python.exe", index, architecture)
    imports = report["imports"]
    delivered.require(
        isinstance(imports, dict) and set(imports) == set(IMPORTS), "Runtime imports differ"
    )
    for module, name in IMPORTS.items():
        validate_file(
            imports[module], root, name, index, architecture, executable=name.endswith(".pyd")
        )
    images = report["images"]
    delivered.require(
        isinstance(images, list) and 0 < len(images) <= 4096, "Runtime module evidence differs"
    )
    seen, qt, bindings, extensions, offscreen = set(), set(), set(), set(), []
    indexed_names = {name.casefold(): name for name in index["files"]}
    for record in images:
        path = PureWindowsPath(record["path"])
        delivered.require(path.is_absolute() and ".." not in path.parts, "Invalid module origin")
        delivered.require(str(path).casefold() not in seen, "Duplicated runtime module")
        seen.add(str(path).casefold())
        stem, kind = path.name.casefold(), record.get("kind")
        if kind == "qt":
            delivered.require(re.fullmatch(r"qt6.+\.dll", stem), "Unexpected Qt image")
            name = indexed_names.get(path.relative_to(root).as_posix().casefold())
            delivered.require(
                path.parent == root / "bin", "Qt DLL loaded from private/foreign directory"
            )
            qt.add(stem)
        elif kind == "binding":
            name = BINDINGS.get(stem)
            delivered.require(name, "Unknown Python/binding DLL")
            bindings.add(stem)
        elif kind == "extension":
            name = next(
                (
                    name
                    for name in IMPORTS.values()
                    if root / name == path and name.endswith(".pyd")
                ),
                None,
            )
            delivered.require(name, "Unknown binding extension")
            extensions.add(name)
        else:
            delivered.require(
                kind == "plugin" and path.is_relative_to(root / "plugins"), "Foreign Qt plugin"
            )
            name = indexed_names.get(path.relative_to(root).as_posix().casefold())
            delivered.require(
                isinstance(record.get("plugin_iid"), str) and record["plugin_iid"],
                "Missing plugin metadata",
            )
            if path == root / "plugins/platforms/qoffscreen.dll":
                delivered.require(
                    record["plugin_iid"]
                    == "org.qt-project.Qt.QPA.QPlatformIntegrationFactoryInterface.5.3",
                    "Offscreen plugin interface differs",
                )
                offscreen.append(path)
        validate_file(record, root, name, index, architecture)
    delivered.require(
        REQUIRED_QT <= qt
        and REQUIRED_BINDINGS <= bindings
        and extensions == {name for name in IMPORTS.values() if name.endswith(".pyd")}
        and len(offscreen) == 1,
        "Incomplete actual SDK Qt/Python/binding/extension/QPA origins",
    )


def observe(sdk, prefix, index, *, qt_first=False):
    """Probe in the SDK Python process, retaining observations before validation."""
    host = native_machine()
    report = {
        "schema_version": 1,
        "scope": SCOPE,
        "sdk": sdk,
        "prefix": str(prefix),
        "platform": sys.platform,
        "host": host,
        "qt_preloaded": qt_first,
        "loader_configuration": {
            "mode": "authenticated-sdk-bin-qt-first" if qt_first else "unpreloaded-sdk-python",
            "dll_directories": [str(prefix / "bin")] if qt_first else [],
            "preloaded": QT_FIRST if qt_first else [],
        },
        "bytecode_disabled": bool(sys.dont_write_bytecode),
        "isolated_python": sys.flags.isolated == 1,
        "python": {
            "executable": file_record(Path(sys.executable)),
            "prefix": sys.prefix,
            "base_prefix": sys.base_prefix,
            "version": list(sys.version_info[:3]),
            "path": list(sys.path),
        },
    }
    try:
        dll_directory, loaded_qt = None, []
        if qt_first:
            # Authenticate every image before LoadLibrary; keep both directory
            # cookie and handles alive until all actual mappings are observed.
            for name in QT_FIRST:
                validate_file(
                    file_record(prefix / name), PureWindowsPath(prefix), name, index, machine(sdk)
                )
            dll_directory = os.add_dll_directory(str(prefix / "bin"))
            loaded_qt = [
                ctypes.WinDLL(str(prefix / name), winmode=0x100 | 0x1000) for name in QT_FIRST
            ]
        import PySide6
        from PySide6 import QtCore, QtGui, QtWidgets, QtPrintSupport
        import shiboken6
        from shiboken6 import Shiboken

        QtCore.QCoreApplication.setLibraryPaths([str(prefix / "plugins")])
        app = QtWidgets.QApplication(["FreeCAD-LibPack-relocation"])
        app.processEvents()
        report["versions"] = {
            "qt": QtCore.qVersion(),
            "pyside": PySide6.__version__,
            "shiboken": shiboken6.__version__,
        }
        report["qpa_platform"] = QtGui.QGuiApplication.platformName()
        report["imports"] = {
            module.__name__: file_record(Path(module.__file__))
            for module in (PySide6, QtCore, QtGui, QtWidgets, QtPrintSupport, shiboken6, Shiboken)
        }
        extensions = {
            PureWindowsPath(item["path"])
            for item in report["imports"].values()
            if item["path"].casefold().endswith(".pyd")
        }
        records = []
        for name in loaded_images():
            path = Path(name)
            stem = path.name.casefold()
            kind, plugin = None, None
            if re.fullmatch(r"qt6.+\.dll", stem):
                kind = "qt"
            elif re.fullmatch(r"(?:python[0-9]+|pyside6.*|shiboken6.*)\.dll", stem):
                kind = "binding"
            elif PureWindowsPath(name) in extensions:
                kind = "extension"
            elif path.suffix.casefold() == ".dll":
                plugin = QtCore.QPluginLoader(str(path)).metaData()
                if plugin:
                    kind = "plugin"
            if kind:
                records.append(
                    {
                        **file_record(path),
                        "kind": kind,
                        **({"plugin_iid": plugin.get("IID")} if plugin else {}),
                    }
                )
        report["images"] = records
        app.quit()
        if dll_directory is not None:
            dll_directory.close()
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"[:2000]
    return report


def write_report(path, report):
    raw = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
    delivered.require(len(raw) <= MAX_REPORT_BYTES, "Oversized runtime report")
    with path.open("xb") as stream:
        stream.write(raw)


def run(args):
    prefix = delivered.physical(args.prefix, directory=True)
    receipt = delivered.physical(args.receipt, exists=False)
    delivered.physical(receipt.parent, directory=True)
    delivered.separate(prefix, receipt)
    delivered.require(not receipt.exists(), "Runtime receipt must be fresh")
    delivery, index, bindings = delivered.load_delivery(args.sdk)
    report = {
        "schema_version": 1,
        "scope": SCOPE,
        "sdk": args.sdk,
        "prefix": str(prefix),
        "helper_sha256": delivered.digest(Path(__file__)),
        "installer_sha256": delivered.digest(INSTALLER_PATH),
        **bindings,
        "sdk_archive_sha256": delivery["sha256"],
        "qt_compiled": False,
        "pdf_tested": False,
        "freecad_built": False,
    }
    try:
        delivered.require(
            native_machine() == {"native_machine": machine(args.sdk), "python_process_machine": 0},
            "Use the SDK native Windows architecture",
        )
        python = file_record(prefix / "bin/python.exe")
        validate_file(python, PureWindowsPath(prefix), "bin/python.exe", index, machine(args.sdk))
        if args.probe:
            observation = observe(args.sdk, prefix, index, qt_first=args.qt_first)
            report["observation"] = observation
            validate_observation(observation, args.sdk, str(prefix), index, qt_first=args.qt_first)
        else:
            environment = {
                key: value
                for key, value in os.environ.items()
                if not key.upper().startswith(("PYTHON", "QT_", "PYSIDE", "SHIBOKEN"))
            }
            environment.update(
                {
                    "PATH": os.pathsep.join(
                        [
                            str(prefix / "bin"),
                            str(Path(os.environ["SystemRoot"]) / "System32"),
                            os.environ["SystemRoot"],
                        ]
                    ),
                    "QT_QPA_PLATFORM": "offscreen",
                    "QT_PLUGIN_PATH": str(prefix / "plugins"),
                    "QT_QPA_PLATFORM_PLUGIN_PATH": str(prefix / "plugins/platforms"),
                }
            )
            with tempfile.TemporaryDirectory(
                prefix="libpack-relocation-", dir=receipt.parent
            ) as temporary:
                work = Path(temporary)
                child_receipt = work / "probe.json"
                command = [
                    str(prefix / "bin/python.exe"),
                    "-I",
                    "-B",
                    str(Path(__file__).resolve()),
                    "--sdk",
                    args.sdk,
                    "--prefix",
                    str(prefix),
                    "--receipt",
                    str(child_receipt),
                    "--probe",
                ]
                if args.qt_first:
                    command.append("--qt-first")
                process = subprocess.run(
                    command,
                    cwd=work,
                    env=environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=120,
                    check=False,
                )
                delivered.require(
                    len(process.stdout) <= MAX_REPORT_BYTES, "Oversized runtime output"
                )
                report["process"] = {
                    "returncode": process.returncode,
                    "output": process.stdout.decode("utf-8", errors="replace"),
                }
                if child_receipt.exists():
                    delivered.physical(child_receipt)
                    delivered.require(
                        child_receipt.stat().st_size <= MAX_REPORT_BYTES, "Oversized probe receipt"
                    )
                    child = delivered.json_bytes(child_receipt.read_bytes())
                    report["probe"] = child
                    for field in (
                        "helper_sha256",
                        "installer_sha256",
                        "catalog_sha256",
                        "index_sha256",
                        "index_content_sha256",
                        "sdk_archive_sha256",
                        "sdk",
                        "scope",
                    ):
                        delivered.require(
                            child.get(field) == report[field], f"Child runtime {field} differs"
                        )
                    validate_observation(
                        child["observation"], args.sdk, str(prefix), index, qt_first=args.qt_first
                    )
                    delivered.require(child.get("status") == "passed", "Child origin probe failed")
                delivered.require(
                    process.returncode == 0 and "probe" in report, "SDK Python origin probe failed"
                )
        report["status"] = "passed"
    except Exception as error:
        report["status"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"[:2000]
    write_report(receipt, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", choices=sorted(delivered.PINS), required=True)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument(
        "--qt-first",
        action="store_true",
        help="Emulate a Qt-linked C++ host with four authenticated SDK/bin DLLs",
    )
    parser.add_argument("--probe", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        report = run(args)
    except (OSError, ValueError) as error:
        parser.exit(1, f"LibPack runtime check failed: {error}\n")
    print(json.dumps({"status": report["status"], "sdk": args.sdk, "receipt": str(args.receipt)}))
    if report["status"] != "passed":
        parser.exit(1, f"LibPack runtime check failed: {report['error']}\n")


if __name__ == "__main__":
    main()
