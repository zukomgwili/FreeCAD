#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Install a built Cocoa correction in the existing host-local FreeCAD app.

Requires native macOS arm64, a successful build_plugin.py receipt, the unchanged
reviewed external Qt prefix and the original local source installation. No app
may be running. Both wrappers are rebuilt with Apple Clang for macOS 11.0; native
FreeCAD binaries, resources, profiles and the external prefix are preserved.

The original app is retained at BACKUP_DIR/<app-name>. All work is staged before
replacement; failures after replacement restore that original bundle. BACKUP_DIR
must be new, on the app's filesystem. RECEIPT must be new and outside the checkout,
app and external prefix. The historical installation receipt is never updated.
Replacing an existing overlay additionally requires --replace-overlay-receipt
pointing at its prior successful installation receipt. The prior app/overlay is
authenticated and backed up intact; only qt-cocoa and the wrappers are replaced.
This installs/signs/verifies files; it does not launch FreeCAD or qualify PDF.

Example:
  python3 package/qt-cocoa/install_overlay.py \
    --app /Applications/FreeCAD-27.1.0.app --prefix /path/to/pixi/prefix \
    --build-receipt /tmp/cocoa-build/build-receipt.json \
    --backup-dir '/Users/me/Applications/FreeCAD Backups/cocoa-correction' \
    --receipt /tmp/cocoa-overlay-installation.json

For reversal, quit FreeCAD, move the corrected app aside, then move the retained
original bundle back to the app path. The backup includes complete file/mode
inventories, installer logs and the original signed bundle.
"""

import argparse
import base64
import ctypes
import datetime
import gzip
import importlib.util
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import signal
import stat
import subprocess
import sys
import uuid


SCRIPT_DIR = Path(__file__).resolve().parent
CHECKOUT = SCRIPT_DIR.parent.parent
HISTORICAL_RECEIPT = SCRIPT_DIR.parent / "qt-pdf" / "macarm-local-installation.json"
LEGACY_BUILDER = {
    "sha256": "d9ddefd03e86f55229b8e33705269a57389e6a845043bfcd4c90a96275f8f335",
    "size": 22571,
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load_builder():
    spec = importlib.util.spec_from_file_location("cocoa_overlay_builder", SCRIPT_DIR / "build_plugin.py")
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def unique_keys(items):
    result = {}
    for key, value in items:
        require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path):
    require(path.is_file() and not path.is_symlink(), f"Missing or linked JSON: {path}")
    require(path.stat().st_size <= 16 * 1024 * 1024, f"Oversized JSON: {path}")
    return json.loads(path.read_text(), object_pairs_hook=unique_keys)


def tree(path, builder):
    """Include modes and literal links; never follow a bundle symlink."""
    result = {}
    for directory, dirs, files in os.walk(path, followlinks=False):
        for name in sorted(dirs + files):
            child = Path(directory) / name
            mode = child.lstat().st_mode
            proof = {"mode": stat.S_IMODE(mode)}
            if stat.S_ISLNK(mode):
                proof.update({"kind": "symlink", "target": os.readlink(child)})
            elif stat.S_ISDIR(mode):
                proof["kind"] = "directory"
            else:
                require(stat.S_ISREG(mode), f"Unsupported bundle file: {child}")
                proof.update({"kind": "file", **builder.identity(child)})
            result[child.relative_to(path).as_posix()] = proof
    result["."] = {"kind": "directory", "mode": stat.S_IMODE(path.stat().st_mode)}
    return result


def readonly(snapshot):
    return all(item["kind"] == "symlink" or not item["mode"] & 0o222 for item in snapshot.values())


def outside_overlay(snapshot):
    return {path: proof for path, proof in snapshot.items()
            if path != "qt-cocoa" and not path.startswith("qt-cocoa/")}


def resource_modes(resources, snapshot, writable):
    # Skip links so an external dependency can never be chmod'ed through one.
    for relative, item in sorted(snapshot.items(), key=lambda pair: len(Path(pair[0]).parts), reverse=not writable):
        if item["kind"] == "symlink":
            continue
        path = resources if relative == "." else resources / relative
        require(not path.is_symlink(), f"Resource was replaced by a link: {path}")
        path.chmod(item["mode"] | 0o200 if writable else item["mode"])


def freeze_new_resources(directory):
    for path in sorted(directory.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        require(not path.is_symlink(), f"Overlay must not contain links: {path}")
        path.chmod(stat.S_IMODE(path.stat().st_mode) & ~0o222)
    directory.chmod(stat.S_IMODE(directory.stat().st_mode) & ~0o222)


def live_app_processes(app):
    # proc_pidpath supplies executable paths, unlike ps command-line substring
    # matching, which would also match this installer's --app argument.
    library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    library.proc_listallpids.argtypes = [ctypes.c_void_p, ctypes.c_int]
    library.proc_listallpids.restype = ctypes.c_int
    library.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    library.proc_pidpath.restype = ctypes.c_int
    count = library.proc_listallpids(None, 0)
    require(count > 0, "Cannot enumerate processes for live-app preflight")
    pids = (ctypes.c_int * (count + 1024))()
    actual = library.proc_listallpids(pids, ctypes.sizeof(pids))
    require(0 < actual <= len(pids), "Cannot obtain complete process list")
    live = []
    for pid in pids[:actual]:
        if pid <= 0 or pid == os.getpid():
            continue
        buffer = ctypes.create_string_buffer(4096)
        if library.proc_pidpath(pid, buffer, len(buffer)) > 0:
            executable = Path(os.fsdecode(buffer.value)).resolve()
            if executable.is_relative_to(app):
                live.append({"pid": pid, "executable": str(executable)})
    return live


def no_live_app(app):
    require(not live_app_processes(app), f"Quit all processes launched from {app} before installing")


def historical_app(app, prefix, builder, allow_overlay=False):
    record = read_json(HISTORICAL_RECEIPT)
    require(record.get("schema_version") == 2 and record.get("status") == "installed-and-verified",
            "Expected the retained original local installation receipt")
    require(record["dependencies"]["prefix"] == str(prefix), "Historical installation uses a different dependency prefix")
    require(record["compiled_source_commit"] == "4d7b98067a6474f88e9f21c4cea75a34d7939dcf",
            "Wrong native FreeCAD source identity")
    info = app / "Contents" / "Info.plist"
    metadata = plistlib.loads(info.read_bytes())
    require(metadata.get("CFBundleIdentifier") == record["application"]["bundle_identifier"]
            and metadata.get("CFBundleExecutable") == "FreeCAD"
            and metadata.get("CFBundleShortVersionString") == record["application"]["version"].removesuffix("dev"),
            "Wrong FreeCAD app identity")
    evidence_path = HISTORICAL_RECEIPT.parent / Path(record["evidence"]["path"]).name
    require(builder.digest(evidence_path) == record["evidence"]["sha256"], "Historical installation evidence differs")
    evidence = json.loads(gzip.decompress(evidence_path.read_bytes()), object_pairs_hook=unique_keys)
    members = [item for item in evidence["files"] if item["path"] == "final-stage/relocation-review.json"]
    require(len(members) == 1, "Missing retained native core review")
    member = members[0]
    data = base64.b64decode(member["data"], validate=True)
    import hashlib
    require(hashlib.sha256(data).hexdigest() == member["sha256"], "Retained native core review bytes differ")
    review = json.loads(data, object_pairs_hook=unique_keys)
    require(review.get("success") is True and review["compiled_source_commit"] == record["compiled_source_commit"],
            "Original native installation was not reviewed")
    native = {}
    for name, expected_sha in record["application"]["native_binary_sha256"].items():
        path = app / "Contents" / "Resources" / "bin" / name
        proof = builder.identity(path)
        require(proof["sha256"] == expected_sha, f"Native FreeCAD executable differs: {name}")
        native[path.relative_to(app).as_posix()] = proof
    require(set(review["current_native_core"]) == {"libFreeCADApp.dylib", "libFreeCADBase.dylib", "libFreeCADGui.dylib"},
            "Unexpected native core identity set")
    for name, expected in review["current_native_core"].items():
        path = app / "Contents" / "Resources" / "lib" / name
        proof = builder.identity(path)
        require(proof["sha256"] == expected["sha256"], f"Native FreeCAD core differs: {name}")
        native[path.relative_to(app).as_posix()] = proof
    for name in ("FreeCAD", "FreeCADCmd"):
        builder.macho_identity(app / "Contents" / "MacOS" / name)
    overlay = app / "Contents" / "Resources" / "qt-cocoa"
    require(allow_overlay or not (overlay.exists() or overlay.is_symlink()),
            "App already contains an overlay; supply its prior successful --replace-overlay-receipt")
    return {"receipt": {"path": str(HISTORICAL_RECEIPT), **builder.identity(HISTORICAL_RECEIPT)},
            "evidence": builder.identity(evidence_path), "compiled_source_commit": record["compiled_source_commit"],
            "info_plist": builder.identity(info), "native_files": native}


def verified_existing_overlay(receipt_path, app, prefix, historical, builder):
    previous = read_json(receipt_path)
    require(previous.get("schema_version") == 1
            and previous.get("kind") == "freecad.qt-cocoa-overlay-installation"
            and previous.get("status") == "installed-and-verified"
            and previous.get("signature_verified") is True
            and previous.get("original_resource_bytes_preserved") is True
            and previous.get("resources_readonly") is True,
            "Expected a prior successful, verified overlay installation receipt")
    require(previous["application"] == str(app) and previous["external_prefix"] == str(prefix),
            "Prior overlay receipt describes a different app or external prefix")
    require(previous["historical_installation"] == historical, "Prior overlay has a different native installation identity")
    overlay = app / "Contents" / "Resources" / "qt-cocoa"
    require(overlay.is_dir() and not overlay.is_symlink(), "Prior overlay directory is missing or linked")
    require(tree(overlay, builder) == previous["overlay_files"], "Existing overlay bytes, modes or links differ from prior receipt")
    manifest_file = overlay / "provenance.json"
    require(builder.identity(manifest_file) == previous["overlay_manifest_identity"], "Existing overlay manifest hash differs")
    manifest = read_json(manifest_file)
    require(manifest == previous["overlay_manifest"], "Existing overlay manifest content differs")
    require(manifest.get("schema_version") == 1 and manifest.get("kind") == "freecad.qt-cocoa-overlay-delivery"
            and manifest["qt_version"] == builder.QT_VERSION and manifest["qt_identity"] == builder.QT_IDENTITY
            and manifest["external_prefix"] == str(prefix)
            and manifest["native_source_commit"] == historical["compiled_source_commit"],
            "Existing overlay source/prefix identity differs")
    plugin = overlay / "platforms" / "libqcocoa.dylib"
    require(manifest["plugin"]["relative_path"] == "platforms/libqcocoa.dylib"
            and builder.identity(plugin) == manifest["plugin"]["installed_identity"]
            and builder.macho_identity(plugin) == manifest["plugin"]["mach_o"],
            "Existing overlay plugin differs from its manifest identity")
    require(set(previous["installed_wrappers"]) == {"FreeCAD", "FreeCADCmd"}, "Unexpected prior wrapper identity set")
    for name, expected in previous["installed_wrappers"].items():
        require(builder.identity(app / "Contents" / "MacOS" / name) == expected, f"Existing wrapper differs: {name}")
    expected_resources = {".": previous["original_app_inventory"]["Contents/Resources"]}
    resource_prefix = "Contents/Resources/"
    for path, proof in previous["original_app_inventory"].items():
        if path.startswith(resource_prefix):
            expected_resources[path[len(resource_prefix):]] = proof
    current_resources = tree(app / "Contents" / "Resources", builder)
    require(readonly(current_resources)
            and outside_overlay(current_resources) == outside_overlay(expected_resources),
            "A resource outside the prior overlay differs from its preserved native installation")
    return previous


def verified_build(receipt_path, prefix, builder):
    receipt = read_json(receipt_path)
    require(receipt.get("schema_version") == 1 and receipt.get("kind") == "freecad.qt-cocoa-overlay-build"
            and receipt.get("status") == "built" and receipt.get("qt_version") == builder.QT_VERSION,
            "Expected a successful Cocoa-only build receipt")
    work = builder.safe_path(Path(receipt["work_directory"]))
    require(receipt_path == work / "build-receipt.json", "Build receipt must be at its recorded work path")
    source = work / "source"
    require(builder.inventory(source) == receipt["inputs"]["prepared_files"], "Prepared build sources differ from receipt")
    patch = receipt["inputs"]["patch"]
    choice = receipt.get("ownership_fix", patch.get("ownership_fix", "parent-managed"))
    require(choice in builder.OWNERSHIP_FIXES and patch.get("ownership_fix", choice) == choice,
            "Unknown or contradictory Cocoa ownership choice")
    selected = builder.OWNERSHIP_FIXES[choice]
    builder_identity = builder.identity(source / "build_plugin.py")
    require((builder_identity == builder.identity(SCRIPT_DIR / "build_plugin.py")
             or (choice == "parent-managed" and builder_identity == LEGACY_BUILDER))
            and builder.identity(source / "CMakeLists.txt") == builder.identity(SCRIPT_DIR / "CMakeLists.txt"),
            "Build used unreviewed builder/CMake sources")
    expected_patch_files = {
        builder.HEADER_TARGET: {"original_sha256": builder.HEADER_ORIGINAL_SHA256,
                                "patched_sha256": selected["header_sha256"]},
        builder.PATCH_TARGET: {"original_sha256": builder.ORIGINAL_SHA256,
                               "patched_sha256": selected["element_sha256"]},
    }
    require(patch["file"] == selected["file"] and patch["sha256"] == selected["sha256"]
            and patch["target"] == builder.PATCH_TARGET and patch["original_sha256"] == builder.ORIGINAL_SHA256
            and patch["patched_sha256"] == selected["element_sha256"],
            "Wrong Cocoa correction source identity")
    require((choice == "parent-managed" and "files" not in patch) or patch.get("files") == expected_patch_files,
            "Wrong per-file Cocoa correction proof")
    require(patch.get("upstream_proposal") == selected.get("upstream_proposal"), "Wrong upstream proposal provenance")
    require(builder.digest(source / selected["file"]) == selected["sha256"]
            and builder.digest(source / "cocoa" / Path(builder.PATCH_TARGET).name) == selected["element_sha256"]
            and builder.digest(source / "cocoa" / Path(builder.HEADER_TARGET).name) == selected["header_sha256"],
            "Cocoa correction source bytes differ")
    require(receipt["source"]["archive_sha256"] == builder.SOURCE_SHA256 and receipt["source"]["url"] == builder.SOURCE_URL,
            "Wrong official Qt source pin")
    original_files = builder.authenticated_source(builder.safe_path(Path(receipt["source"]["directory"])),
                                                  builder.safe_path(Path(receipt["source"]["archive"])))
    require(original_files == receipt["inputs"]["original_files"], "Original Qt source proof differs")
    require(builder.baseline(prefix, SCRIPT_DIR) == receipt["baseline"], "External Qt prefix differs from build inputs")
    dependencies = builder.inventory(work / "dependencies" / "include")
    require(dependencies == receipt["inputs"]["dependency_headers"]["files"]
            and builder.inventory_digest(dependencies) == builder.DEPENDENCY_HEADERS_SHA256,
            "Pinned dependency headers differ")
    plugin = work / "build" / "platforms" / "libqcocoa.dylib"
    require(receipt["output"]["path"] == str(plugin)
            and builder.identity(plugin) == {key: receipt["output"][key] for key in ("sha256", "size")}
            and builder.macho_identity(plugin) == receipt["output"]["mach_o"], "Plugin differs from successful build receipt")
    require(receipt["toolchain"]["deployment_target"] == "11.0" and receipt["toolchain"]["architecture"] == "arm64",
            "Wrong plugin build platform")
    require(receipt["commands"] and all(item.get("returncode") == 0 for item in receipt["commands"]),
            "Build command failed or was incomplete")
    for item in receipt["commands"]:
        require(builder.identity(work / item["log"]) == item["log_identity"], "Build log differs from receipt")
    require(builder.identity(work / "build" / "CMakeCache.txt") == receipt["cmake_cache"]
            and builder.identity(work / "build" / "compile_commands.json") == receipt["compile_commands"],
            "Build configuration provenance differs")
    return receipt, work, plugin


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--build-receipt", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--replace-overlay-receipt", type=Path,
                        help="Explicitly replace an existing overlay only after authenticating its prior successful installation receipt")
    parser.add_argument("--sdk", type=Path, help="Defaults to the exact SDK recorded by the plugin build")
    parser.add_argument("--compiler", default="/usr/bin/clang", help="Apple Clang C compiler for both wrappers")
    args = parser.parse_args()
    require(sys.platform == "darwin" and platform.machine() == "arm64", "Native macOS arm64 is required")
    builder = load_builder()
    app, prefix, build_receipt, backup, output_receipt = map(builder.safe_path,
        (args.app, args.prefix, args.build_receipt, args.backup_dir, args.receipt))
    require(not args.app.is_symlink() and app.is_dir() and app.suffix == ".app", "Select the real installed .app directory")
    require(not backup.exists() and not output_receipt.exists(), "Backup directory and output receipt must be new")
    require(not args.backup_dir.is_symlink() and not args.receipt.is_symlink(), "Output paths must not be links")
    for protected in (app, prefix, CHECKOUT, build_receipt.parent):
        require(not backup.is_relative_to(protected) and not protected.is_relative_to(backup), "Backup must be outside input trees")
        require(not output_receipt.is_relative_to(protected), "Receipt must be outside input trees and checkout")
    require(backup.parent.is_dir(), "Backup parent directory must already exist")
    require(backup.parent.stat().st_dev == app.parent.stat().st_dev, "Backup and app must share a filesystem for reversible atomic moves")
    no_live_app(app)
    build, work, plugin = verified_build(build_receipt, prefix, builder)
    prior_receipt = builder.safe_path(args.replace_overlay_receipt) if args.replace_overlay_receipt else None
    historical = historical_app(app, prefix, builder, allow_overlay=prior_receipt is not None)
    previous_overlay = verified_existing_overlay(prior_receipt, app, prefix, historical, builder) if prior_receipt else None
    sdk = builder.safe_path(args.sdk or Path(build["toolchain"]["sdk"]["path"]))
    require(builder.identity(sdk / "SDKSettings.json") == build["toolchain"]["sdk"]["settings"], "Wrapper SDK differs from reviewed build SDK")
    require((sdk / "usr" / "include" / "errno.h").is_file(), "Selected SDK lacks C headers")
    compiler = builder.tool_path(args.compiler)
    original = tree(app, builder)
    resources_original = tree(app / "Contents" / "Resources", builder)
    require(readonly(resources_original), "Original installed resources must retain their readonly protection")
    resources_protected = outside_overlay(resources_original)
    token = uuid.uuid4().hex
    staged = app.with_name("." + app.stem + "-cocoa-" + token + ".app")
    lock = app.with_name("." + app.name + ".cocoa-install.lock")
    lock_created = False
    lock_fd = None
    old_moved = False
    corrected_moved = False
    backup_app = backup / app.name
    receipt = {"schema_version": 1, "kind": "freecad.qt-cocoa-overlay-installation", "status": "preparing",
               "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
               "application": str(app), "backup_application": str(backup_app), "external_prefix": str(prefix),
               "historical_installation": historical, "build_receipt": {"path": str(build_receipt), **builder.identity(build_receipt)},
               "original_app_inventory": original, "commands": [],
               "scope": "Host-local Cocoa overlay and wrappers only; no Qt prefix changes, FreeCAD rebuild, app launch or PDF requalification"}
    if previous_overlay:
        receipt["superseded_overlay"] = {
            "receipt": {"path": str(prior_receipt), **builder.identity(prior_receipt)},
            "manifest_identity": previous_overlay["overlay_manifest_identity"],
            "plugin_identity": previous_overlay["overlay_manifest"]["plugin"]["installed_identity"],
            "scope": "Verified old qt-cocoa subtree and both wrappers replaced; complete prior app backed up; prior receipt/evidence unchanged",
        }
    def save():
        output_receipt.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_receipt.with_name(output_receipt.name + "." + token + ".tmp")
        temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        os.replace(temporary, output_receipt)
    def run(command, label):
        completed = subprocess.run(list(map(str, command)), capture_output=True, text=True)
        log = backup / (label + ".log")
        log.write_text(completed.stdout + completed.stderr)
        receipt["commands"].append({"argv": list(map(str, command)), "returncode": completed.returncode,
                                    "log": str(log), "log_identity": builder.identity(log)})
        save()
        require(completed.returncode == 0, f"{label} failed; see {log}")
        return completed.stdout + completed.stderr
    previous_handlers = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}
    def interrupted(number, frame):
        raise KeyboardInterrupt(f"Interrupted by signal {number}")
    try:
        lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        lock_created = True
        os.write(lock_fd, str(os.getpid()).encode())
        os.close(lock_fd)
        lock_fd = None
        for number in previous_handlers:
            signal.signal(number, interrupted)
        backup.mkdir(mode=0o700)
        save()
        version = run([compiler, "--version"], "wrapper-compiler-version")
        require("Apple clang version" in version, "Wrappers require Apple Clang")
        backend = re.search(r"^InstalledDir: (.+)$", version, re.MULTILINE)
        receipt["wrapper_toolchain"] = {"compiler": {"path": str(compiler), **builder.identity(compiler)},
                                         "sdk": {"path": str(sdk), **builder.identity(sdk / "SDKSettings.json")},
                                         "deployment_target": "11.0", "architecture": "arm64"}
        if backend:
            actual_compiler = (Path(backend.group(1)) / compiler.name).resolve(strict=True)
            receipt["wrapper_toolchain"]["backend"] = {"path": str(actual_compiler), **builder.identity(actual_compiler)}
        run(["/usr/bin/codesign", "--verify", "--deep", "--strict", "--verbose=2", app], "original-signature-verify")
        run(["/usr/bin/ditto", "--rsrc", "--extattr", app, staged], "stage-original-app")
        require(tree(staged, builder) == original, "Staged app copy differs from original")
        resources = staged / "Contents" / "Resources"
        resource_modes(resources, resources_protected, True)
        overlay = resources / "qt-cocoa"
        if previous_overlay:
            require(tree(overlay, builder) == previous_overlay["overlay_files"], "Staged prior overlay differs before replacement")
            resource_modes(overlay, previous_overlay["overlay_files"], True)
            shutil.rmtree(overlay)
        (overlay / "platforms").mkdir(parents=True)
        shutil.copy2(plugin, overlay / "platforms" / "libqcocoa.dylib")
        shutil.copytree(work / "source", overlay / "source")
        shutil.copytree(work / "dependencies", overlay / "dependencies")
        shutil.copy2(build_receipt, overlay / "build-receipt.json")
        shutil.copy2(SCRIPT_DIR / "FreeCADLocalLauncher.c", overlay / "FreeCADLocalLauncher.c")
        shutil.copy2(SCRIPT_DIR / "install_overlay.py", overlay / "install_overlay.py")
        receipt["wrapper_source"] = builder.identity(overlay / "FreeCADLocalLauncher.c")
        wrappers = {}
        for name in ("FreeCAD", "FreeCADCmd"):
            target = staged / "Contents" / "MacOS" / name
            command = [compiler, "-O2", "-Wall", "-Wextra", "-Werror", "-arch", "arm64",
                       "-mmacosx-version-min=11.0", "-isysroot", sdk,
                       "-DAPP_DEPENDENCY_PREFIX=" + json.dumps(str(prefix)), "-DAPP_BINARY_NAME=" + json.dumps(name),
                       overlay / "FreeCADLocalLauncher.c", "-o", target]
            run(command, "compile-wrapper-" + name)
            target.chmod(0o755)
            wrappers[name] = builder.macho_identity(target)
        run(["/usr/bin/codesign", "--force", "--deep", "--sign", "-", staged], "stage-deep-adhoc-sign")
        installed_plugin = overlay / "platforms" / "libqcocoa.dylib"
        manifest = {"schema_version": 1, "kind": "freecad.qt-cocoa-overlay-delivery",
                    "qt_version": builder.QT_VERSION, "external_prefix": str(prefix), "qt_identity": builder.QT_IDENTITY,
                    "ownership_fix": build.get("ownership_fix", "parent-managed"),
                    "native_source_commit": historical["compiled_source_commit"],
                    "build_receipt": builder.identity(overlay / "build-receipt.json"),
                    "source_files": builder.inventory(overlay / "source"),
                    "dependency_headers": builder.inventory(overlay / "dependencies" / "include"),
                    "plugin": {"relative_path": "platforms/libqcocoa.dylib",
                               "build_identity": builder.identity(plugin), "installed_identity": builder.identity(installed_plugin),
                               "mach_o": builder.macho_identity(installed_plugin)},
                    "wrapper_source": builder.identity(overlay / "FreeCADLocalLauncher.c"),
                    "installer_source": builder.identity(overlay / "install_overlay.py"),
                    # The main wrapper's final CodeDirectory seals this manifest;
                    # its complete signed hash belongs in the external receipt.
                    "wrappers": {name: {"mach_o": wrappers[name]}
                                 for name in ("FreeCAD", "FreeCADCmd")},
                    "signing": "Local ad-hoc; no notarization or distribution promotion"}
        (overlay / "provenance.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        resource_modes(resources, resources_protected, False)
        freeze_new_resources(overlay)
        after_resources = tree(resources, builder)
        require(readonly(after_resources), "Staged resources are not readonly")
        require(outside_overlay(after_resources) == resources_protected,
                "Deep signing or staging changed an original installed resource")
        # Record the manifest and restored resource seal after nested signing.
        run(["/usr/bin/codesign", "--force", "--sign", "-", staged], "stage-final-adhoc-sign")
        run(["/usr/bin/codesign", "--verify", "--deep", "--strict", "--verbose=2", staged], "stage-signature-verify")
        require(builder.identity(installed_plugin) == manifest["plugin"]["installed_identity"], "Final signing changed the recorded overlay plugin")
        require(tree(app, builder) == original, "Original app changed while preparing installation")
        no_live_app(app)
        require(builder.baseline(prefix, SCRIPT_DIR) == build["baseline"], "External prefix changed before replacement")
        receipt.update({"status": "staged-and-verified", "overlay_manifest": manifest,
                        "overlay_manifest_identity": builder.identity(overlay / "provenance.json")})
        save()
        require(not backup_app.exists(), "Backup target appeared during staging")
        os.rename(app, backup_app)
        old_moved = True
        os.rename(staged, app)
        corrected_moved = True
        run(["/usr/bin/codesign", "--verify", "--deep", "--strict", "--verbose=2", app], "installed-signature-verify")
        require(tree(backup_app, builder) == original, "Retained original backup differs")
        final_overlay = app / "Contents" / "Resources" / "qt-cocoa"
        require(builder.identity(final_overlay / "provenance.json") == receipt["overlay_manifest_identity"], "Installed overlay manifest differs")
        require(builder.identity(final_overlay / "platforms" / "libqcocoa.dylib") == manifest["plugin"]["installed_identity"], "Installed overlay plugin differs")
        final_resources = tree(app / "Contents" / "Resources", builder)
        require(readonly(final_resources) and outside_overlay(final_resources) == resources_protected,
                "Installed original resources or protections differ")
        require(builder.baseline(prefix, SCRIPT_DIR) == build["baseline"], "External prefix changed during installation")
        receipt.update({"status": "installed-and-verified", "finished_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        "overlay_files": tree(final_overlay, builder), "installed_wrappers": {
                            name: builder.identity(app / "Contents" / "MacOS" / name) for name in ("FreeCAD", "FreeCADCmd")},
                        "signature_verified": True, "original_resource_bytes_preserved": True, "resources_readonly": True})
        save()
        print(output_receipt)
    except BaseException as error:
        receipt.update({"status": "failed", "error": str(error)})
        try:
            if corrected_moved:
                failed = backup / "failed-overlay.app"
                require(not failed.exists(), "Failed-overlay preservation path is occupied")
                os.rename(app, failed)
            if old_moved:
                require(not app.exists(), "Cannot restore original into an occupied app path")
                os.rename(backup_app, app)
                require(tree(app, builder) == original, "Restored original app differs")
                receipt["rollback"] = "original signed app restored and complete inventory verified"
            else:
                receipt["rollback"] = "original app never replaced"
        except BaseException as restore_error:
            receipt.update({"status": "rollback-failed", "rollback_error": str(restore_error)})
        save()
        raise
    finally:
        for number, handler in previous_handlers.items():
            signal.signal(number, handler)
        if lock_fd is not None:
            os.close(lock_fd)
        if lock_created:
            lock.unlink(missing_ok=True)
        if staged.exists():
            # Only remove our uniquely named staging bundle, never the backup.
            for directory, dirs, files in os.walk(staged, followlinks=False):
                path = Path(directory)
                if not path.is_symlink():
                    path.chmod(stat.S_IMODE(path.stat().st_mode) | 0o700)
            shutil.rmtree(staged)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        print(f"Cocoa overlay installation failed: {error}", file=sys.stderr)
        sys.exit(1)
