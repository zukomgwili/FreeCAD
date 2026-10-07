#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Build an isolated macOS arm64 Cocoa overlay for reviewed Qt 6.11.2 build 1.

The official Qt archive authenticates the copied source. Its upstream copyright,
SPDX notices and LICENSES are retained. --ownership-fix selects exactly one
authenticated Cocoa ownership patch. The default retains the original 24t
parent-managed guard; native-interfaces applies the source-only changes from
Qt Gerrit 772484 patch set 3 (unmerged at review on 2026-10-07).
Public/private headers and libraries come from the selected installed
Conda Qt package, not a second Qt build. This does not install anything or repeat
PDF qualification. build-receipt.json records build provenance; separate overlay
delivery verification and native runtime evidence remain required.

Example (all work is outside the selected prefix and checkout):
  python3 package/qt-cocoa/build_plugin.py --qt-source /tmp/qtbase-6.11.2 \
    --qt-source-archive /tmp/qtbase-v6.11.2.tar.gz --prefix /path/to/prefix \
    --dependency-include /tmp/cocoa-build-deps/include --work-dir /tmp/cocoa-build \
    --sdk /Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk
"""

import argparse
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys
import tarfile


QT_VERSION = "6.11.2"
SOURCE_URL = "https://github.com/qt/qtbase/archive/refs/tags/v6.11.2.tar.gz"
SOURCE_SHA256 = "06cd7aa6b3ab19cb5a1664a2891ef0df960f78c97fa31b80b1d6d7ee70688414"
PATCH_SHA256 = "39f79210a3648e4073664b5c0768479fa2be5ca6866e08166c81ea628ab2302f"
PATCH_TARGET = "src/plugins/platforms/cocoa/qcocoaaccessibilityelement.mm"
ORIGINAL_SHA256 = "1e1c3699f9de098a0c4979128ce8f43779976416ef3d41ca875073a2a4b26f27"
PATCHED_SHA256 = "b1ccd069d6a9f5be5a0b8de3ff76d7bcc2af655e998e47bd6584e6c02a2b7812"
HEADER_TARGET = "src/plugins/platforms/cocoa/qcocoaaccessibilityelement.h"
HEADER_ORIGINAL_SHA256 = "3ab7fe5168e8a50d988938fd34dd323e628d143cb89b803103b74bafdbd1dbae"
NATIVE_PATCH_SHA256 = "934fa3283419fa4bb3c218275caa6344c5bafc31eeba5155621ef4a47385ef70"
NATIVE_HEADER_SHA256 = "99185a8e33a3b9838e1e24c71b48e52125d1d4090c8d0ea98dcf9fd58163f301"
NATIVE_ELEMENT_SHA256 = "59323153a0475637cd4170f9af205e8217a02a8ddbb7cb0ade8f49cc491275df"
OWNERSHIP_FIXES = {
    "parent-managed": {
        "file": "parent-managed-elements.patch", "sha256": PATCH_SHA256,
        "header_sha256": HEADER_ORIGINAL_SHA256, "element_sha256": PATCHED_SHA256,
    },
    "native-interfaces": {
        "file": "native-interface-ownership.patch", "sha256": NATIVE_PATCH_SHA256,
        "header_sha256": NATIVE_HEADER_SHA256, "element_sha256": NATIVE_ELEMENT_SHA256,
        "upstream_proposal": {
            "url": "https://codereview.qt-project.org/c/qt/qtbase/+/772484",
            "revision": "de050555112940ed643dfa7bd9ed16470adc5a09", "patch_set": 3,
            "complete_patch_sha256": "b2ef8d37a293566657c0052d4d64d9ab8b204c0f44ff45d5253d9b306db1e024",
            "review_date": "2026-10-07", "status_at_review": "NEW",
            "scope": "Exact Cocoa header/implementation hunks; upstream test hunk omitted",
        },
    },
}
DEPENDENCY_HEADERS_SHA256 = "c52c8e94cb0556ea236beb3416f1a8b1a4156164a363c2c20267cd89bdc88331"
DEPENDENCY_ARCHIVES = {
    "libvulkan-headers-1.4.357.0-hfbe1efa_1.conda":
        "7afc3f437badead8210795a051ec1bb5149840589347e839197fc1bd096e1f41",
    "moltenvk-1.4.2-h407b865_0.conda":
        "8e489cff52952e7599b8bc20fbe4530a97780224aad882be7d16b1ade8511fb2",
}
QT_IDENTITY = {
    "name": "qt6-main", "version": QT_VERSION, "build": "pl5321h5ab96b3_1",
    "build_number": 1, "subdir": "osx-arm64",
    "sha256": "618519456ca1dbf1d4c7c492222010214f47274aa3c2bb2148452cdc942ccf99",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def identity(path):
    require(path.is_file() and not path.is_symlink(), f"Expected regular file: {path}")
    return {"sha256": digest(path), "size": path.stat().st_size}


def inventory(directory):
    require(directory.is_dir(), f"Missing input directory: {directory}")
    files = {}
    for path in sorted(directory.rglob("*")):
        require(not path.is_symlink(), f"Linked input is not allowed: {path}")
        if path.is_file():
            files[path.relative_to(directory).as_posix()] = identity(path)
        else:
            require(path.is_dir(), f"Unsupported input type: {path}")
    return files


def inventory_digest(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def safe_path(value):
    path = value.expanduser().resolve()
    require(not any(c in str(path) for c in '\\";\n\r\0'), f"Unsupported path: {path}")
    return path


def tool_path(value):
    found = shutil.which(value)
    require(found is not None, f"Missing executable: {value}")
    return safe_path(Path(found))


def baseline(prefix, script_dir):
    """Read-only use of the original catalogue verifier, with no Python/Qt load."""
    helper = script_dir.parent / "qt-pdf" / "verify_delivered_qt.py"
    catalog = helper.with_name("distribution.json")
    spec = importlib.util.spec_from_file_location("cocoa_baseline_verifier", helper)
    module = importlib.util.module_from_spec(spec)
    bytecode_setting = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = bytecode_setting
    report = module.verify(prefix, module.read_json(catalog), "osx-arm64", python_load=False)
    metadata = prefix / "conda-meta" / (QT_IDENTITY["name"] + "-" + QT_VERSION + "-" + QT_IDENTITY["build"] + ".json")
    installed = module.read_json(metadata)
    require(all(installed.get(k) == v for k, v in QT_IDENTITY.items()), "Wrong Qt package identity")
    # The catalogue covers delivered binaries/configuration. Supplement it with
    # every installed QtCore/QtGui header, including versioned private headers.
    headers = {}
    package_paths = {item["_path"]: item for item in installed["paths_data"]["paths"]}
    for component in ("QtCore", "QtGui"):
        directory = prefix / "include" / "qt6" / component
        for relative, proof in inventory(directory).items():
            installed_relative = (directory.relative_to(prefix) / relative).as_posix()
            original = package_paths.get(installed_relative, {})
            require(
                original.get("path_type") == "hardlink"
                and original.get("sha256") == proof["sha256"]
                and original.get("size_in_bytes") == proof["size"]
                and not original.get("prefix_placeholder"),
                f"Qt header differs from its installed package: {installed_relative}",
            )
            headers[installed_relative] = proof
        require((directory / QT_VERSION / component / "private").is_dir(), f"Missing exact private headers: {component}")
    configs = {}
    for component in ("Qt6CorePrivate", "Qt6GuiPrivate", "Qt6CoreTools", "Qt6GuiTools"):
        directory = prefix / "lib" / "cmake" / component
        for relative, proof in inventory(directory).items():
            configs[(directory.relative_to(prefix) / relative).as_posix()] = proof
    return {"prefix": str(prefix), "identity": QT_IDENTITY, "catalog": identity(catalog),
            "verifier": identity(helper), "verification": report,
            "headers": headers, "private_and_tool_cmake": configs,
            "metadata": identity(metadata)}


def authenticated_source(source, archive):
    require(identity(archive)["sha256"] == SOURCE_SHA256, "Official Qt source archive SHA-256 differs")
    version = source / ".cmake.conf"
    require(re.search(r'set\(QT_REPO_MODULE_VERSION "6\.11\.2"\)', version.read_text()), "Source must be Qt 6.11.2")
    cocoa = inventory(source / "src" / "plugins" / "platforms" / "cocoa")
    licenses = inventory(source / "LICENSES")
    expected = {"src/plugins/platforms/cocoa/" + p: proof for p, proof in cocoa.items()}
    expected.update({"LICENSES/" + p: proof for p, proof in licenses.items()})
    expected[".cmake.conf"] = identity(version)
    with tarfile.open(archive, "r:gz") as stream:
        members = {m.name.removeprefix("qtbase-6.11.2/"): m for m in stream.getmembers()}
        archive_files = {p for p, m in members.items() if m.isfile() and
                         (p.startswith("src/plugins/platforms/cocoa/") or p.startswith("LICENSES/"))}
        require(archive_files == set(expected) - {".cmake.conf"}, "Qt Cocoa/license input set differs from official source")
        for relative, proof in expected.items():
            member = members.get(relative)
            require(member is not None and member.isfile(), f"Missing official source input: {relative}")
            original = stream.extractfile(member).read()
            require(len(original) == proof["size"] and hashlib.sha256(original).hexdigest() == proof["sha256"],
                    f"Qt source input differs from pinned archive: {relative}")
    return expected


def apply_native_patch(destination, patch):
    """Apply the pinned proposal's two source diffs at their exact line offsets."""
    sections = patch.read_text().split("diff --git ")[1:]
    expected_targets = {HEADER_TARGET, PATCH_TARGET}
    seen = set()
    for section in sections:
        lines = section.splitlines(keepends=True)
        names = lines[0].strip().split()
        require(len(names) == 2 and names[0] == "a/" + names[1][2:], "Unexpected patch file header")
        target = names[1][2:]
        require(target in expected_targets and target not in seen, "Unexpected or repeated native patch target")
        seen.add(target)
        path = destination / "cocoa" / Path(target).name
        original = path.read_text().splitlines(keepends=True)
        output = []
        cursor = 0
        line_number = 0
        while line_number < len(lines):
            match = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", lines[line_number])
            if not match:
                line_number += 1
                continue
            start = int(match.group(1)) - 1
            require(cursor <= start <= len(original), "Invalid or overlapping native patch hunk")
            output.extend(original[cursor:start])
            cursor = start
            old_count = new_count = 0
            line_number += 1
            while line_number < len(lines) and lines[line_number][:1] in (" ", "+", "-"):
                kind, text = lines[line_number][0], lines[line_number][1:]
                if kind in (" ", "-"):
                    require(cursor < len(original) and original[cursor] == text,
                            f"Native patch context differs: {target}:{cursor + 1}")
                    cursor += 1
                    old_count += 1
                if kind in (" ", "+"):
                    output.append(text)
                    new_count += 1
                line_number += 1
            require(old_count == int(match.group(2) or 1) and new_count == int(match.group(4) or 1),
                    "Native patch hunk line count differs")
        output.extend(original[cursor:])
        path.write_text("".join(output))
    require(seen == expected_targets, "Native patch must change exactly its Cocoa header and implementation")


def prepare(source, archive, dependency_include, work, script_dir, ownership_fix="parent-managed"):
    require(ownership_fix in OWNERSHIP_FIXES, "Unknown Cocoa ownership correction")
    selected = OWNERSHIP_FIXES[ownership_fix]
    originals = authenticated_source(source, archive)
    dependency_files = inventory(dependency_include)
    require(inventory_digest(dependency_files) == DEPENDENCY_HEADERS_SHA256, "Vulkan/MoltenVK header set differs from pinned build inputs")
    destination = work / "source"
    destination.mkdir()
    shutil.copytree(source / "src/plugins/platforms/cocoa", destination / "cocoa")
    shutil.copytree(source / "LICENSES", destination / "LICENSES")
    shutil.copytree(dependency_include, work / "dependencies" / "include")
    copied = {"src/plugins/platforms/cocoa/" + p: proof for p, proof in inventory(destination / "cocoa").items()}
    copied.update({"LICENSES/" + p: proof for p, proof in inventory(destination / "LICENSES").items()})
    require(copied == {p: proof for p, proof in originals.items() if p != ".cmake.conf"},
            "Source inputs changed while being copied")
    require(inventory(work / "dependencies" / "include") == dependency_files,
            "Dependency inputs changed while being copied")
    for name in ("CMakeLists.txt", selected["file"], "build_plugin.py"):
        shutil.copy2(script_dir / name, destination / name)
    patch = destination / selected["file"]
    require(digest(patch) == selected["sha256"], "Reviewed patch SHA-256 differs")
    target = destination / "cocoa" / Path(PATCH_TARGET).name
    header = destination / "cocoa" / Path(HEADER_TARGET).name
    require(digest(target) == ORIGINAL_SHA256, "Unpatched Cocoa accessibility file SHA-256 differs")
    require(digest(header) == HEADER_ORIGINAL_SHA256, "Unpatched Cocoa accessibility header SHA-256 differs")
    # Exact byte substitutions implement the two reviewed hunks. Hashes guard
    # both the patch file and complete before/after file, so there is no fuzz.
    text = target.read_bytes()
    replacements = (
        (b"        if (cell->axid) { // it's a proper cell, remove from cache",
         b"        if (cell->axid && !cell.isManagedByParent) {\n            // Synthesized elements share their parent table interface."),
        (b"    QAccessibleCache::instance()->deleteInterface(axid);\n    [super dealloc];",
         b"    if (axid && !self.isManagedByParent)\n        QAccessibleCache::instance()->deleteInterface(axid);\n    [super dealloc];"),
    )
    if ownership_fix == "parent-managed":
        for before, after in replacements:
            require(text.count(before) == 1, "Reviewed patch context is not unique")
            text = text.replace(before, after)
        target.write_bytes(text)
    else:
        apply_native_patch(destination, patch)
    require(digest(target) == selected["element_sha256"], "Patched Cocoa accessibility file SHA-256 differs")
    require(digest(header) == selected["header_sha256"], "Patched Cocoa accessibility header SHA-256 differs")
    qrc = '<RCC><qresource prefix="/qt-project.org/mac/cursors">'
    for name in ("sizeallcursor.png", "spincursor.png", "waitcursor.png"):
        qrc += f'<file alias="images/{name}">cocoa/images/{name}</file>'
    (destination / "qcocoaresources.qrc").write_text(qrc + "</qresource></RCC>\n")
    archives = {}
    for name, expected_sha in DEPENDENCY_ARCHIVES.items():
        path = dependency_include.parent / name
        actual = identity(path) if path.exists() else None
        require(actual is None or actual["sha256"] == expected_sha, f"Dependency archive SHA-256 differs: {name}")
        archives[name] = {"url": "https://conda.anaconda.org/conda-forge/osx-arm64/" + name,
                          "expected_sha256": expected_sha, "local_archive": actual}
    return {"original_files": originals, "prepared_files": inventory(destination),
            "patch": {"file": patch.name, "sha256": selected["sha256"], "target": PATCH_TARGET,
                      "ownership_fix": ownership_fix,
                      "original_sha256": ORIGINAL_SHA256, "patched_sha256": selected["element_sha256"],
                      "files": {
                          HEADER_TARGET: {"original_sha256": HEADER_ORIGINAL_SHA256,
                                          "patched_sha256": selected["header_sha256"]},
                          PATCH_TARGET: {"original_sha256": ORIGINAL_SHA256,
                                         "patched_sha256": selected["element_sha256"]},
                      },
                      "upstream_proposal": selected.get("upstream_proposal"),
                      "application": ("exact two-hunk byte substitution; no fuzz" if ownership_fix == "parent-managed"
                                      else "exact proposal source hunks and line offsets; no fuzz")},
            "dependency_headers": {"input_directory": str(dependency_include),
                                   "inventory_sha256": DEPENDENCY_HEADERS_SHA256,
                                   "files": dependency_files, "archives": archives}}


def macho_identity(path):
    """Inspect the output without loading it; runtime verification is separate."""
    data = path.read_bytes()
    require(data[:4] == b"\xcf\xfa\xed\xfe", "Output is not little-endian Mach-O 64")
    require(struct.unpack_from("<I", data, 4)[0] == 0x100000C, "Output is not arm64")
    count, size = struct.unpack_from("<II", data, 16)
    require(32 + size <= len(data), "Invalid Mach-O command area")
    result = {"architecture": "arm64", "dylib_loads": [], "rpaths": []}
    offset = 32
    for _ in range(count):
        command, length = struct.unpack_from("<II", data, offset)
        require(length >= 8 and offset + length <= 32 + size, "Invalid Mach-O command")
        if command in (0xC, 0x80000018, 0x8000001F, 0x8000001C):
            name_offset = struct.unpack_from("<I", data, offset + 8)[0]
            require(8 <= name_offset < length, "Invalid Mach-O load string")
            value = data[offset + name_offset:offset + length].split(b"\0", 1)[0].decode()
            result["rpaths" if command == 0x8000001C else "dylib_loads"].append(value)
        if command in (0x32, 0x24):
            version_offset = 12 if command == 0x32 else 8
            minimum, sdk = struct.unpack_from("<II", data, offset + version_offset)
            def version(value):
                return f"{value >> 16}.{(value >> 8) & 255}.{value & 255}"
            result.update({"minimum_macos": version(minimum), "compiled_sdk": version(sdk)})
        offset += length
    require(result.get("minimum_macos") == "11.0.0", "Output deployment target differs from 11.0")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--qt-source", type=Path, required=True)
    parser.add_argument("--ownership-fix", choices=sorted(OWNERSHIP_FIXES), default="parent-managed",
                        help="Retain the 24t parent guard (default), or apply Qt proposal 772484 native interface ownership")
    parser.add_argument("--qt-source-archive", type=Path,
                        help="Pinned official archive (default: source sibling qtbase-v6.11.2.tar.gz)")
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--dependency-include", type=Path, required=True,
                        help="Pinned Vulkan/MoltenVK include tree; copied into the isolated work directory")
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--cxx-compiler", default="/usr/bin/clang++")
    parser.add_argument("--objcxx-compiler", default="/usr/bin/clang++")
    parser.add_argument("--cxx-flags", default="")
    parser.add_argument("--objcxx-flags", default="")
    parser.add_argument("--cmake", default="cmake")
    parser.add_argument("--ninja", default="ninja")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--prepare-only", action="store_true", help="Copy/verify inputs and record commands without invoking the compiler")
    args = parser.parse_args()
    require(sys.platform == "darwin" and platform.machine() == "arm64", "This overlay builder requires native macOS arm64")
    require(args.jobs > 0, "--jobs must be positive")
    script_dir = Path(__file__).resolve().parent
    source, prefix, work, sdk, include = map(safe_path,
        (args.qt_source, args.prefix, args.work_dir, args.sdk, args.dependency_include))
    archive = safe_path(args.qt_source_archive or source.parent / "qtbase-v6.11.2.tar.gz")
    checkout = script_dir.parent.parent
    for protected in (source, prefix, checkout, include):
        require(not work.is_relative_to(protected) and not protected.is_relative_to(work),
                f"Work directory must be isolated from input/check-out: {protected}")
    require(not work.exists() or (work.is_dir() and not any(work.iterdir())), "--work-dir must be fresh or empty")
    require(sdk.is_dir() and (sdk / "SDKSettings.json").is_file(), "Select an explicit macOS SDK with SDKSettings.json")
    work.mkdir(parents=True, exist_ok=True)
    receipt = {"schema_version": 1, "kind": "freecad.qt-cocoa-overlay-build", "status": "preparing",
               "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
               "work_directory": str(work), "qt_version": QT_VERSION,
               "ownership_fix": args.ownership_fix,
               "source": {"directory": str(source), "archive": str(archive), "url": SOURCE_URL,
                          "archive_sha256": SOURCE_SHA256},
               "commands": [], "toolchain": {}, "scope": "Cocoa plugin only; no prefix installation or PDF requalification"}
    report_path = work / "build-receipt.json"
    def save():
        report_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    save()
    try:
        receipt["baseline"] = baseline(prefix, script_dir)
        receipt["inputs"] = prepare(source, archive, include, work, script_dir, args.ownership_fix)
        cmake, ninja = tool_path(args.cmake), tool_path(args.ninja)
        cxx, objcxx = tool_path(args.cxx_compiler), tool_path(args.objcxx_compiler)
        environment = dict(os.environ)
        removed = {}
        for key in ("CC", "CXX", "CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS", "OBJCXXFLAGS",
                    "CPATH", "CPLUS_INCLUDE_PATH", "C_INCLUDE_PATH", "LIBRARY_PATH", "CMAKE_PREFIX_PATH",
                    "Qt6_DIR", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "DYLD_LIBRARY_PATH",
                    "DYLD_FRAMEWORK_PATH", "DYLD_INSERT_LIBRARIES"):
            if key in environment:
                removed[key] = environment.pop(key)
        environment["SDKROOT"] = str(sdk)
        receipt["toolchain"] = {"sdk": {"path": str(sdk), "settings": identity(sdk / "SDKSettings.json")},
                                "deployment_target": "11.0", "architecture": "arm64",
                                "removed_environment": removed,
                                "developer_dir": environment.get("DEVELOPER_DIR"),
                                "cxx_flags": args.cxx_flags, "objcxx_flags": args.objcxx_flags,
                                "executables": {name: {"path": str(path), **identity(path)} for name, path in
                                                (("cmake", cmake), ("ninja", ninja), ("cxx", cxx), ("objcxx", objcxx))}}
        def run(command, label):
            log = work / (label + ".log")
            entry = {"argv": list(map(str, command)), "cwd": str(work), "log": log.name}
            receipt["commands"].append(entry)
            save()
            with log.open("w") as stream:
                process = subprocess.run(entry["argv"], cwd=work, env=environment, stdout=stream, stderr=subprocess.STDOUT)
            entry.update({"returncode": process.returncode, "log_identity": identity(log)})
            save()
            require(process.returncode == 0, f"{label} failed; see {log}")
        configure = [str(cmake), "-S", str(work / "source"), "-B", str(work / "build"), "-G", "Ninja",
                     "-DCMAKE_BUILD_TYPE=RelWithDebInfo", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
                     "-DCMAKE_MAKE_PROGRAM=" + str(ninja), "-DCMAKE_PREFIX_PATH=" + str(prefix),
                     "-DFREECAD_COCOA_QT_PREFIX=" + str(prefix),
                     "-DFREECAD_COCOA_DEPENDENCY_INCLUDE=" + str(work / "dependencies" / "include"),
                     "-DCMAKE_CXX_COMPILER=" + str(cxx), "-DCMAKE_OBJCXX_COMPILER=" + str(objcxx),
                     "-DCMAKE_CXX_FLAGS=" + args.cxx_flags, "-DCMAKE_OBJCXX_FLAGS=" + args.objcxx_flags,
                     "-DCMAKE_OSX_SYSROOT=" + str(sdk), "-DCMAKE_OSX_DEPLOYMENT_TARGET=11.0",
                     "-DCMAKE_OSX_ARCHITECTURES=arm64"]
        build = [str(cmake), "--build", str(work / "build"), "--target", "QCocoaIntegrationPlugin", "--parallel", str(args.jobs)]
        receipt["planned_build_commands"] = [configure, build]
        if args.prepare_only:
            receipt["status"] = "prepared"
        else:
            for label, executable in (("cmake-version", cmake), ("ninja-version", ninja), ("cxx-version", cxx), ("objcxx-version", objcxx)):
                run([str(executable), "--version"], label)
            # Apple /usr/bin/clang can be a developer-tool shim. Retain the
            # selected backend identity as well as its complete version output.
            receipt["toolchain"]["compiler_backends"] = {}
            for label, executable in (("cxx", cxx), ("objcxx", objcxx)):
                text = (work / (label + "-version.log")).read_text()
                installed_dir = re.search(r"^InstalledDir: (.+)$", text, re.MULTILINE)
                if installed_dir:
                    backend = (Path(installed_dir.group(1)) / executable.name).resolve(strict=True)
                    receipt["toolchain"]["compiler_backends"][label] = {"path": str(backend), **identity(backend)}
            run(configure, "configure")
            targets_file = work / "build" / "qt-targets.json"
            targets = json.loads(targets_file.read_text())
            receipt["qt_imported_targets"] = {}
            for name, value in targets.items():
                path = Path(value).resolve(strict=True)
                require(path.is_relative_to(prefix), f"Imported Qt target escaped the selected prefix: {name}")
                receipt["qt_imported_targets"][name] = {"path": str(path), **identity(path)}
            for component in ("Core", "Gui"):
                expected = prefix / "lib" / f"libQt6{component}.6.11.2.dylib"
                require(targets["Qt6::" + component] == str(expected), f"Wrong Qt6::{component} imported library")
            run(build, "build")
            output = work / "build" / "platforms" / "libqcocoa.dylib"
            receipt["output"] = {"path": str(output), **identity(output), "mach_o": macho_identity(output)}
            receipt["cmake_cache"] = identity(work / "build" / "CMakeCache.txt")
            receipt["compile_commands"] = identity(work / "build" / "compile_commands.json")
            require(baseline(prefix, script_dir) == receipt["baseline"], "Selected baseline inputs changed during the build")
            require(inventory(work / "source") == receipt["inputs"]["prepared_files"], "Prepared source changed during build")
            require(inventory(work / "dependencies" / "include") == receipt["inputs"]["dependency_headers"]["files"], "Dependency headers changed during build")
            receipt["status"] = "built"
        receipt["finished_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        save()
        print(report_path)
    except Exception as error:
        receipt.update({"status": "failed", "error": str(error)})
        save()
        raise


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError, tarfile.TarError) as error:
        print(f"Cocoa overlay build failed: {error}", file=sys.stderr)
        sys.exit(1)
