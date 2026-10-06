# SPDX-License-Identifier: LGPL-2.1-or-later
"""Verify an explicitly selected, reviewed Conda Qt distribution.

The delivery catalogue is the trust input. Installed metadata never supplies
an expected binary hash. These builds have no binary prefix replacements;
only catalogue-retained text templates may replace their literal placeholder.
Python loading is optional, uses the current selected interpreter, and proves
actual mapped libraries. This is dependency selection, not a repeat of PDF
qualification or verification of a signed/rewritten application bundle.
"""

import argparse
import base64
import ctypes
from ctypes import wintypes
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import sys
import unicodedata

PLATFORMS = {
    "linux-64": ("linux", "elf", 62),
    "linux-aarch64": ("linux", "elf", 183),
    "osx-64": ("darwin", "mach-o", 0x1000007),
    "osx-arm64": ("darwin", "mach-o", 0x100000C),
    "win-64": ("win32", "pe", 0x8664),
}
COMPONENTS = ("Core", "Gui", "Widgets", "PrintSupport")
IDENTITY = ("name", "version", "build", "build_number", "subdir", "sha256")
ROLES = {
    "qt.library",
    "qt.importlib",
    "pyside.library",
    "shiboken.library",
    "pyside.importlib",
    "shiboken.importlib",
    "pyside.extension",
    "shiboken.extension",
    "binding.python",
    "cmake",
    "qt.conf",
}
MAX_CATALOG_BYTES = 1024 * 1024
SOURCE_SHA256 = "6dcfbca271d76a6502741a2c0dc6fc98ef7dd0b7b4cfd0abcebb285a86a26f33"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def unique_keys(items):
    result = {}
    for key, value in items:
        require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path):
    path = Path(path)
    require(
        path.is_file() and not path.is_symlink() and path.stat().st_size <= 16 * 1024 * 1024,
        f"Missing, linked or oversized JSON: {path}",
    )
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_keys)


def relative_path(value):
    require(isinstance(value, str) and value, "Missing catalogue path")
    parts = PurePosixPath(value)
    require(
        not parts.is_absolute()
        and value == parts.as_posix()
        and not any(part in ("", ".", "..") for part in parts.parts)
        and not any(character in value for character in "\\:\r\n\t\0")
        and all(not part.endswith((".", " ")) for part in parts.parts)
        and not any(ord(character) < 32 for character in value)
        and unicodedata.normalize("NFC", value) == value,
        f"Unsafe catalogue path: {value!r}",
    )
    return value


def regular_file(prefix, relative):
    path = prefix / relative_path(relative)
    require(
        stat.S_ISREG(path.lstat().st_mode) and path.resolve(strict=True) == path,
        f"Critical file must be regular and at its catalogue path: {path}",
    )
    return path


def checked_digest(path, expected_sha, expected_size):
    before = path.stat()
    require(
        before.st_size == expected_size and digest(path) == expected_sha,
        f"Critical file bytes differ: {path}",
    )
    after = path.lstat()
    require(
        stat.S_ISREG(after.st_mode)
        and all(
            getattr(before, field) == getattr(after, field)
            for field in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        ),
        f"Critical file changed during verification: {path}",
    )


def binary_machine(path):
    with path.open("rb") as stream:
        header = stream.read(64)
        if header.startswith(b"\x7fELF"):
            require(header[4:6] == b"\x02\x01", f"Expected little-endian ELF64: {path}")
            return "elf", struct.unpack_from("<H", header, 18)[0]
        if header[:4] == b"\xcf\xfa\xed\xfe":
            return "mach-o", struct.unpack_from("<I", header, 4)[0]
        require(header[:2] == b"MZ" and len(header) == 64, f"Unknown native binary: {path}")
        offset = struct.unpack_from("<I", header, 60)[0]
        require(64 <= offset < path.stat().st_size - 6, f"Invalid PE header: {path}")
        stream.seek(offset)
        pe = stream.read(6)
        require(pe[:4] == b"PE\0\0", f"Invalid PE signature: {path}")
        return "pe", struct.unpack_from("<H", pe, 4)[0]


def installed_records(prefix):
    metadata = prefix / "conda-meta"
    require(metadata.is_dir() and not metadata.is_symlink(), "Selected prefix needs conda-meta")
    records = {}
    for path in sorted(metadata.glob("*.json")):
        record = read_json(path)
        name = record.get("name")
        require(
            isinstance(name, str) and re.fullmatch(r"[a-z0-9_.-]+", name),
            f"Invalid installed package name: {path}",
        )
        require(name not in records, f"Duplicate installed package: {name}")
        records[name] = (record, path)
    return records


def expected_file(specification, prefix):
    raw_sha = specification.get("sha256")
    require(
        isinstance(raw_sha, str) and re.fullmatch(r"[0-9a-f]{64}", raw_sha),
        "Missing original file SHA-256",
    )
    size = specification.get("size")
    require(type(size) is int and 0 < size <= 128 * 1024 * 1024, "Invalid critical file size")
    placeholder = specification.get("prefix_placeholder")
    if placeholder is None:
        require(
            "file_mode" not in specification and "source_base64" not in specification,
            "Unexpected relocation fields",
        )
        return raw_sha, size
    require(
        specification.get("file_mode") == "text"
        and specification.get("role") in ("cmake", "qt.conf")
        and isinstance(placeholder, str)
        and placeholder,
        "Only retained CMake/Qt configuration text may relocate",
    )
    original = base64.b64decode(specification["source_base64"], validate=True)
    require(
        len(original) == size
        and hashlib.sha256(original).hexdigest() == raw_sha
        and placeholder.encode("utf-8") in original
        and b"\0" not in original,
        "Retained relocation template differs from its original package file",
    )
    relocated = original.replace(
        placeholder.encode("utf-8"), str(prefix).replace("\\", "/").encode("utf-8")
    )
    return hashlib.sha256(relocated).hexdigest(), len(relocated)


def selected_distribution(prefix, catalogue, platform):
    require(platform in PLATFORMS, "Unsupported qualified Conda platform")
    requested = Path(prefix).expanduser().absolute()
    require(
        requested.is_dir() and not requested.is_symlink(),
        "Selected prefix must be a real directory",
    )
    prefix = requested.resolve(strict=True)
    require(
        type(catalogue.get("schema_version")) is int and catalogue["schema_version"] == 1,
        "Unsupported delivery catalogue",
    )
    entry = catalogue["conda"][platform]
    require(
        entry.get("qt_version") == "6.11.2"
        and type(entry.get("build_number")) is int
        and entry["build_number"] == 1
        and entry.get("subdir") == platform
        and entry.get("source_sha256") == SOURCE_SHA256
        and entry.get("license") == "LGPL-3.0-only",
        "Expected the reviewed Qt 6.11.2 build-1/source distribution",
    )
    required_bindings = {"pyside6", "python"}
    if platform.startswith("linux"):
        required_bindings.add("qt6-wayland")
    require(
        isinstance(entry.get("bindings"), dict) and set(entry["bindings"]) == required_bindings,
        "Unexpected or missing reviewed binding package",
    )
    identities = {
        "qt6-main": {**entry, "name": "qt6-main", "version": entry["qt_version"]},
        **entry["bindings"],
    }
    require(
        {"pyside6", "python"}.issubset(identities)
        and identities["pyside6"]["version"] == "6.11.2"
        and identities["python"]["version"].startswith("3.13."),
        "Expected unchanged Python 3.13/PySide6 6.11.2 identities",
    )
    records = installed_records(prefix)
    checked_metadata = {}
    for name, identity in identities.items():
        require(
            all(
                isinstance(identity.get(key), str) and identity[key]
                for key in IDENTITY
                if key != "build_number"
            )
            and type(identity.get("build_number")) is int
            and identity["build_number"] >= 0
            and re.fullmatch(r"[0-9a-f]{64}", identity["sha256"]),
            f"Invalid reviewed package identity: {name}",
        )
        record, path = records[name]
        require(
            all(record.get(key) == identity.get(key) for key in IDENTITY)
            and identity.get("name") == name
            and identity.get("subdir") == platform,
            f"Installed package differs from reviewed identity: {name}",
        )
        checked_metadata[name] = {
            **{key: record[key] for key in IDENTITY},
            "metadata_sha256": digest(path),
        }
    files = entry["verification_files"]
    require(isinstance(files, dict) and files, "Missing finite file verification catalogue")
    require(
        len({relative_path(path).casefold() for path in files}) == len(files),
        "Case-colliding catalogue files",
    )
    indexed = {}
    for name in identities:
        paths = records[name][0].get("paths_data", {}).get("paths", [])
        require(isinstance(paths, list), f"Missing installed paths metadata: {name}")
        indexed[name] = {item["_path"]: item for item in paths}
        require(len(indexed[name]) == len(paths), f"Duplicate installed path metadata: {name}")
    verified = {}
    for relative, specification in files.items():
        owner = specification["package"]
        role = specification["role"]
        require(
            role in ROLES or re.fullmatch(r"qpa\.[a-z0-9]+", role), f"Unknown file role: {role}"
        )
        require(
            owner in identities and specification.get("path_type") == "hardlink",
            "Unknown critical file owner/type",
        )
        original = indexed[owner][relative]
        file_sha, file_size = expected_file(specification, prefix)
        require(
            original.get("path_type") == "hardlink"
            and original.get("sha256") == specification["sha256"]
            and type(original.get("size_in_bytes")) is int
            # Installers retain either the source size or the relocated text size.
            and original["size_in_bytes"] in (specification["size"], file_size),
            f"Installed source file metadata differs: {relative}",
        )
        if "sha256_in_prefix" in original:
            require(
                original["sha256_in_prefix"] == file_sha,
                f"Installed relocation metadata differs: {relative}",
            )
        path = regular_file(prefix, relative)
        checked_digest(path, file_sha, file_size)
        proof = {"package": owner, "role": role, "sha256": file_sha, "size": file_size}
        if role.endswith((".library", ".extension")) or role.startswith("qpa."):
            machine = binary_machine(path)
            require(machine == PLATFORMS[platform][1:], f"Native architecture differs: {relative}")
            proof["machine"] = {"format": machine[0], "architecture": machine[1]}
        verified[relative] = proof
    for component in COMPONENTS:
        pattern = rf"(?:lib)?Qt6{component}(?:\.|$)"
        require(
            any(
                proof["role"] == "qt.library" and re.match(pattern, Path(path).name)
                for path, proof in verified.items()
            ),
            f"Missing reviewed Qt {component} binary",
        )
    require(
        any(proof["role"].startswith("qpa.") for proof in verified.values()),
        "Missing reviewed QPA plugin",
    )
    dirs = entry["cmake_dirs"]
    required_dirs = {"Qt6", *("Qt6" + name for name in COMPONENTS), "PySide6", "Shiboken6"}
    require(required_dirs.issubset(dirs), "Missing reviewed Qt/bindings CMake directories")
    for name, relative in dirs.items():
        require(
            re.fullmatch(r"(?:Qt6|PySide6|Shiboken6)[A-Za-z0-9_]*", name),
            "Invalid CMake package name",
        )
        config = relative_path(relative) + "/" + name + "Config.cmake"
        require(
            config in verified and verified[config]["role"] == "cmake",
            f"Unverified CMake config: {config}",
        )
    return (
        prefix,
        entry,
        {
            "schema_version": 1,
            "scope": "Explicit reviewed Conda Qt selection; signed/rewritten bundles are outside this proof",
            "platform": platform,
            "prefix": str(prefix),
            "package_sha256": entry["sha256"],
            "source_sha256": entry["source_sha256"],
            "qt_version": entry["qt_version"],
            "packages": checked_metadata,
            "files": verified,
            "cmake_dirs": {name: str(prefix / relative) for name, relative in dirs.items()},
            "runtime_verified": False,
            "pdf_qualification_repeated": False,
            "application_bundle_qualified": False,
        },
    )


def verify_targets(prefix, files, targets):
    require(
        isinstance(targets, dict) and "Qt6::Core" in targets, "Imported Qt Core target is required"
    )
    result = {}
    for name, values in targets.items():
        if re.fullmatch(r"Qt6::[A-Za-z0-9_]+", name):
            component = name.split("::", 1)[1]
            library_role, import_role = "qt.library", "qt.importlib"
            pattern = rf"(?:lib)?Qt6{component}d?(?:\.|$)"
        elif name in ("PySide6::pyside6", "PySide6::pyside6qml"):
            library_role, import_role = "pyside.library", "pyside.importlib"
            pattern = rf"(?:lib)?{name.split('::')[1]}(?:\.|$)"
        else:
            require(name == "Shiboken6::libshiboken", f"Unknown imported target: {name}")
            library_role, import_role = "shiboken.library", "shiboken.importlib"
            pattern = r"(?:lib)?shiboken6(?:\.|$)"
        require(
            isinstance(values, dict) and values.get("locations"),
            f"Missing imported location: {name}",
        )
        result[name] = {}
        for field, role in (("locations", library_role), ("import_libraries", import_role)):
            observed = []
            for value in values.get(field, []):
                path = Path(value).resolve(strict=True)
                require(
                    path.is_relative_to(prefix),
                    f"Imported target is outside selected prefix: {name}",
                )
                relative = path.relative_to(prefix).as_posix()
                require(
                    relative in files
                    and files[relative]["role"] == role
                    and re.match(pattern, path.name),
                    f"Imported target differs from verified binary: {name}",
                )
                checked_digest(path, files[relative]["sha256"], files[relative]["size"])
                observed.append(str(path))
            result[name][field] = sorted(set(observed))
    return result


def loaded_images():
    if sys.platform == "darwin":
        dyld = ctypes.CDLL(None)
        count = dyld._dyld_image_count
        count.restype = ctypes.c_uint32
        name = dyld._dyld_get_image_name
        name.argtypes = [ctypes.c_uint32]
        name.restype = ctypes.c_char_p
        return sorted({os.fsdecode(name(index)) for index in range(count())})
    if sys.platform.startswith("linux"):
        return sorted(
            {
                fields[5]
                for line in Path("/proc/self/maps").read_text().splitlines()
                if len(fields := line.split(maxsplit=5)) == 6 and fields[5].startswith("/")
            }
        )
    require(sys.platform == "win32", "Loaded-image proof is unsupported on this host")

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
    snapshot = kernel.CreateToolhelp32Snapshot
    snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    snapshot.restype = wintypes.HANDLE
    first, next_module = kernel.Module32FirstW, kernel.Module32NextW
    for function in (first, next_module):
        function.argtypes = [wintypes.HANDLE, ctypes.POINTER(ModuleEntry)]
        function.restype = wintypes.BOOL
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    handle = snapshot(0x8 | 0x10, os.getpid())
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    names = []
    try:
        entry = ModuleEntry()
        entry.dwSize = ctypes.sizeof(entry)
        if not first(handle, ctypes.byref(entry)):
            raise ctypes.WinError(ctypes.get_last_error())
        while True:
            names.append(entry.szExePath)
            if not next_module(handle, ctypes.byref(entry)):
                require(ctypes.get_last_error() == 18, "Failed loaded-module enumeration")
                break
    finally:
        close(handle)
    return sorted(set(names))


def verify_loaded(prefix, files, images, plugin_name, extensions):
    selected = {}
    for value in images:
        path = Path(value)
        native = re.match(r"(?:lib)?(?:Qt6|pyside6|shiboken6)", path.name, re.IGNORECASE)
        qpa = (
            re.match(r"(?:lib)?q[a-z0-9]+\.(?:so|dylib|dll)$", path.name, re.IGNORECASE)
            and "platforms" in path.parts
        )
        extension = any(
            Path(value).resolve() == Path(item).resolve() for item in extensions.values()
        )
        if not (native or qpa or extension):
            continue
        path = path.resolve(strict=True)
        require(
            path.is_relative_to(prefix),
            f"Loaded Qt/binding module is outside selected prefix: {value}",
        )
        relative = path.relative_to(prefix).as_posix()
        require(
            relative in files
            and (
                files[relative]["role"].endswith((".library", ".extension"))
                or files[relative]["role"].startswith("qpa.")
            ),
            f"Loaded Qt/binding module is not in finite catalogue: {relative}",
        )
        checked_digest(path, files[relative]["sha256"], files[relative]["size"])
        selected[relative] = {"path": str(path), **files[relative]}
    for component in COMPONENTS:
        require(
            sum(
                proof["role"] == "qt.library"
                and re.match(rf"(?:lib)?Qt6{component}(?:\.|$)", Path(path).name) is not None
                for path, proof in selected.items()
            )
            == 1,
            f"Expected exactly one loaded Qt {component} binary",
        )
    require(
        any(proof["role"] == "qpa." + plugin_name for proof in selected.values()),
        "Actual QPA plugin is not the selected loaded plugin",
    )
    for role in ("pyside.library", "shiboken.library"):
        require(any(proof["role"] == role for proof in selected.values()), f"Missing loaded {role}")
    for name, value in extensions.items():
        path = Path(value).resolve(strict=True)
        require(
            path.is_relative_to(prefix) and path.relative_to(prefix).as_posix() in selected,
            f"Imported extension is not actually mapped: {name}",
        )
    return selected


def load_python(prefix, entry, files):
    require(
        sys.platform.startswith(PLATFORMS[entry["subdir"]][0]),
        "Python load requires the selected native platform",
    )
    require(
        Path(sys.prefix).resolve() == prefix
        and Path(sys.executable).resolve().is_relative_to(prefix),
        "Run load mode with the selected prefix's Python interpreter",
    )
    require(
        tuple(map(int, entry["bindings"]["python"]["version"].split("."))) == sys.version_info[:3],
        "Actual Python version differs from selected package",
    )
    require(
        binary_machine(Path(sys.executable).resolve()) == PLATFORMS[entry["subdir"]][1:],
        "Python process architecture differs",
    )
    for name in ("PySide6", "shiboken6"):
        spec = importlib.util.find_spec(name)
        require(
            spec is not None and spec.origin, f"Missing selected bindings Python package: {name}"
        )
        path = Path(spec.origin).resolve(strict=True)
        require(
            path.is_relative_to(prefix),
            f"Bindings Python package is outside selected prefix: {name}",
        )
        relative = path.relative_to(prefix).as_posix()
        require(
            relative in files and files[relative]["role"] == "binding.python",
            f"Unverified bindings Python package: {name}",
        )
        checked_digest(path, files[relative]["sha256"], files[relative]["size"])
    modules = {
        name: importlib.import_module(name)
        for name in (
            "PySide6",
            "shiboken6",
            *("PySide6.Qt" + name for name in COMPONENTS),
            "shiboken6.Shiboken",
        )
    }
    require(
        modules["PySide6"].__version__ == modules["shiboken6"].__version__ == entry["qt_version"],
        "Actual bindings versions differ",
    )
    require(
        modules["PySide6.QtCore"].qVersion() == entry["qt_version"],
        "Actual loaded Qt version differs",
    )
    widgets = modules["PySide6.QtWidgets"]
    application = widgets.QApplication.instance() or widgets.QApplication([])
    plugin = application.platformName().lower()
    extensions = {
        name: str(Path(module.__file__).resolve(strict=True))
        for name, module in modules.items()
        if name not in ("PySide6", "shiboken6")
    }
    for name in ("PySide6", "shiboken6"):
        path = Path(modules[name].__file__).resolve(strict=True)
        require(
            path.is_relative_to(prefix),
            f"Bindings Python package is outside selected prefix: {name}",
        )
        relative = path.relative_to(prefix).as_posix()
        require(
            relative in files
            and files[relative]["role"] == "binding.python"
            and digest(path) == files[relative]["sha256"],
            f"Bindings Python package bytes differ: {name}",
        )
    return {
        "python_executable": str(Path(sys.executable).resolve()),
        "qpa": plugin,
        "extensions": extensions,
        "modules": verify_loaded(prefix, files, loaded_images(), plugin, extensions),
    }


def verify(prefix, catalogue, platform, targets=None, python_load=False):
    prefix, entry, report = selected_distribution(prefix, catalogue, platform)
    if targets is not None:
        report["imported_targets"] = verify_targets(prefix, report["files"], targets)
    if python_load:
        report["runtime"] = load_python(prefix, entry, report["files"])
        report["runtime_verified"] = True
    report["status"] = "selected"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--platform", choices=PLATFORMS, required=True)
    parser.add_argument("--load-python", action="store_true")
    parser.add_argument("--cmake-targets", type=Path)
    parser.add_argument("--target", action="append", nargs=2, default=[])
    parser.add_argument("--import-library", action="append", nargs=2, default=[])
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        require(args.catalog.stat().st_size <= MAX_CATALOG_BYTES, "Oversized delivery catalogue")
        require(
            not (args.cmake_targets and (args.target or args.import_library)),
            "Choose one imported-target input format",
        )
        targets = read_json(args.cmake_targets) if args.cmake_targets else None
        if args.target or args.import_library:
            targets = {}
            for field, values in (
                ("locations", args.target),
                ("import_libraries", args.import_library),
            ):
                for name, path in values:
                    targets.setdefault(name, {}).setdefault(field, []).append(path)
        report = verify(
            args.prefix, read_json(args.catalog), args.platform, targets, args.load_python
        )
        report.update(
            {"catalog_sha256": digest(args.catalog), "helper_sha256": digest(Path(__file__))}
        )
    except (OSError, ValueError, KeyError, TypeError, ImportError) as error:
        report = {
            "schema_version": 1,
            "status": "rejected",
            "runtime_verified": False,
            "error": str(error),
        }
    output = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        report_path = args.report.absolute()
        prefix_path = args.prefix.absolute().resolve()
        require(
            report_path.parent.resolve(strict=True) == report_path.parent
            and not report_path.resolve().is_relative_to(prefix_path),
            "Report must be at a physical path outside selected prefix",
        )
        with report_path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(output)
    print(output, end="")
    return 0 if report["status"] == "selected" else 1


if __name__ == "__main__":
    raise SystemExit(main())
