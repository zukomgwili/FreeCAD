# SPDX-License-Identifier: LGPL-2.1-or-later
"""Retain disposable Linux build outputs; diagnose one failed ARM native capture.

Neither command qualifies or promotes a runtime. Diagnostic GDB execution uses
the failed launch's runtime selections, fresh configs/output and the current
Xvfb authorization. GDB itself keeps its tool environment; ``set environment``
changes only the inferior, as documented by GNU GDB.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import resource
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import threading
from types import SimpleNamespace

import reuse_linux_qt_qualification as reuse

# GNUInstallDirs places copied native resources in share on the Linux builds.
OUTPUT_DIRS = ("bin", "lib", "Mod", "Ext", "data", "share")
REQUIRED_RESOURCES = {
    "share/Mod/TechDraw/Templates/Default_Template_A4_Landscape.svg",
    "share/Mod/TechDraw/Resources/fonts/osifont-lgpl3fe.ttf",
    "share/Mod/TechDraw/LineGroup/LineGroup.csv",
}
SCRATCH_NAMES = {"CMakeFiles", ".git", "__pycache__"}
MAX_BYTES = 8 * 1024**3
MAX_FILES = 60000
MAX_LOG = 64 * 1024**2
MACRO = "tests/src/Mod/TechDraw/Gui/QtPdfStroker/native-freecad.FCMacro"
ENVIRONMENT_KEYS = {
    "PATH",
    "DISPLAY",
    "PYTHONHOME",
    "PYTHONDONTWRITEBYTECODE",
    "PYTHONNOUSERSITE",
    "LD_LIBRARY_PATH",
    "QT_PDF_BUILD_RUN",
    "QT_PDF_TARGET",
    "QT_QPA_PLATFORM_PLUGIN_PATH",
    "QT_PLUGIN_PATH",
    "QT_QPA_PLATFORM",
    "TD_NATIVE_DISPOSABLE",
    "TD_NATIVE_EXPECTED_QT_VERSION",
    "TD_NATIVE_OUTPUT",
    "TD_NATIVE_BYPASS_MODULE",
    "TD_NATIVE_MACRO_PATH",
    "TD_NATIVE_MACRO_SHA256",
    "TD_NATIVE_QT_LIB",
    "TD_NATIVE_QT_PREFIX",
    "TD_NATIVE_PLUGIN_ROOT",
}
GDB_DOCS = {
    "modes": "https://sourceware.org/gdb/current/onlinedocs/gdb.html/Mode-Options.html",
    "environment": "https://sourceware.org/gdb/current/onlinedocs/gdb.html/Environment.html",
    "threads": "https://sourceware.org/gdb/current/onlinedocs/gdb.html/Threads.html",
    "backtrace": "https://sourceware.org/gdb/current/onlinedocs/gdb.html/Backtrace.html",
    "working_directory": "https://sourceware.org/gdb/current/onlinedocs/gdb.html/Working-Directory.html",
}
require, digest, physical, read_json = (
    reuse.require,
    reuse.digest,
    reuse.physical,
    reuse.read_json,
)


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n")


def scope():
    return {
        "schema_version": 1,
        "diagnostic_only": True,
        "qualified": False,
        "native_freecad_qualified": False,
        "distribution_promoted": False,
        "helper_sha256": digest(Path(__file__).resolve()),
    }


def git(source, *arguments):
    return subprocess.check_output(
        ["git", "-C", str(source), *arguments], stderr=subprocess.PIPE, env=git_environment()
    )


def git_environment():
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_TERMINAL_PROMPT="0",
        GIT_OPTIONAL_LOCKS="0",
    )
    return environment


def source_inventory(source, head):
    """Hash every tracked blob and authenticate each initialized gitlink."""
    require(re.fullmatch(r"[0-9a-f]{40}", head) is not None, "Expected exact source commit")
    files, repositories = {}, {}

    def visit(root, expected):
        require(git(root, "rev-parse", "HEAD").decode().strip() == expected, "Source HEAD differs")
        require(
            subprocess.run(
                ["git", "-C", str(root), "diff", "--quiet", "HEAD", "--"],
                check=False,
                env=git_environment(),
            ).returncode
            == 0,
            "Tracked source differs from HEAD",
        )
        relative_root = str(root.relative_to(source))
        repositories[relative_root] = {
            "head": expected,
            "tree": git(root, "rev-parse", "HEAD^{tree}").decode().strip(),
        }
        for entry in git(root, "ls-tree", "-r", "-z", "HEAD").split(b"\0"):
            if not entry:
                continue
            metadata, name = entry.split(b"\t", 1)
            mode, kind, blob = metadata.decode().split()
            relative = reuse.safe_name(os.fsdecode(name))
            path = root / relative
            key = str(path.relative_to(source))
            if kind == "commit":
                if (path / ".git").exists():
                    visit(physical(path), blob)
                else:
                    repositories[key] = {"head": blob, "initialized": False}
                continue
            require(kind == "blob" and mode in ("100644", "100755", "120000"), "Source mode")
            raw = (
                os.fsencode(os.readlink(path)) if mode == "120000" else physical(path).read_bytes()
            )
            actual = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
            require(actual == blob, f"Tracked source bytes differ: {key}")
            require(key not in files, "Duplicate source path")
            files[key] = {
                "git_blob": blob,
                "mode": mode,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size": len(raw),
            }

    visit(source, head)
    return {"repositories": repositories, "files": files}


def validated_proof(proof):
    proof = physical(proof)
    old = read_json(proof / "validation.json")
    arguments = SimpleNamespace(
        proof_dir=proof,
        baseline_prefix=Path(old["native_runtime"]["baseline"]["prefix"]),
        patched_prefix=Path(old["native_runtime"]["patched"]["prefix"]),
        package_build_json=Path(old["package_evidence"]["build_json"]),
        qt_source_archive=Path(old["qt_source_archive"]),
    )
    require(reuse.validation_data(arguments) == old, "Installed reuse validation changed")
    return old


def fresh_root(path, protected):
    path = reuse.fresh_work(path)
    temporary = physical(Path(os.environ["RUNNER_TEMP"]))
    require(path.is_relative_to(temporary) and path != temporary, "Use fresh RUNNER_TEMP child")
    for root in protected:
        root = root.resolve()
        require(
            not path.is_relative_to(root) and not root.is_relative_to(path),
            "Diagnostic work overlaps protected input",
        )
    return path


def emit_owned(key, path):
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
            stream.write(f"{key}={path}\n")


def output_inventory(build, source, tracked):
    """Dereference only selected build outputs or exact tracked source resources."""
    files, directories, missing, excluded = {}, {}, [], []
    total = 0
    selected = [build / name for name in OUTPUT_DIRS]

    def walk(path, name, ancestors):
        nonlocal total
        reuse.safe_name(name)
        if path.name in SCRATCH_NAMES:
            require(not path.is_symlink(), f"Linked compile/Git scratch: {path}")
            require(
                path.is_dir() or (path.name == ".git" and path.is_file()),
                f"Unexpected compile/Git/cache scratch type: {path}",
            )
            excluded.append({"path": name, "reason": "compile/Git/Python-cache scratch"})
            return
        target = path.resolve(strict=True)
        in_build = any(target.is_relative_to(root) for root in selected)
        require(
            in_build or target.is_relative_to(source),
            f"External output link/target: {path} -> {target}",
        )
        if not in_build and target.is_file():
            record = tracked["files"].get(str(target.relative_to(source)))
            require(
                record is not None
                and record["mode"] in ("100644", "100755")
                and digest(target) == record["sha256"],
                f"Output link target is not exact tracked HEAD: {path} -> {target}",
            )
        if target.is_dir():
            require(target not in ancestors, f"Cyclic output directory link: {path} -> {target}")
            directories[name] = {
                "source_path": str(path),
                "resolved_path": str(target),
                "symlink": os.readlink(path) if path.is_symlink() else None,
            }
            for child in sorted(path.iterdir()):
                walk(child, name + "/" + child.name, ancestors | {target})
            return
        info = target.stat()
        require(stat.S_ISREG(info.st_mode), f"Nonregular runtime output: {path}")
        require(target.suffix not in (".o", ".obj"), f"Compile object in runtime output: {path}")
        total += info.st_size
        require(
            total <= MAX_BYTES and len(files) < MAX_FILES, f"Runtime bundle exceeds bound: {path}"
        )
        files[name] = {
            "source_path": str(path),
            "resolved_path": str(target),
            "symlink": os.readlink(path) if path.is_symlink() else None,
            "size": info.st_size,
            "sha256": digest(target),
            "mode": stat.S_IMODE(info.st_mode),
        }

    for name in OUTPUT_DIRS:
        path = build / name
        if path.exists() or path.is_symlink():
            walk(path, name, set())
        else:
            missing.append(name)
    require(
        all(name not in missing for name in ("bin", "lib", "Mod", "Ext")), "Runtime dirs absent"
    )
    require("bin/FreeCAD" in files, "Native FreeCAD binary absent")
    require(
        {
            "Mod/Part/Part.so",
            "Mod/Part/PartGui.so",
            "Mod/TechDraw/TechDraw.so",
            "Mod/TechDraw/TechDrawGui.so",
        }
        <= files.keys(),
        "Scoped native modules absent",
    )
    require(REQUIRED_RESOURCES <= files.keys(), "Required TechDraw native resources absent")
    return {
        "files": files,
        "directories": directories,
        "missing_optional": missing,
        "excluded": excluded,
    }


def check_unchanged(inventory):
    for entry in inventory["directories"].values():
        path = Path(entry["source_path"])
        require(
            path.is_dir()
            and str(path.resolve(strict=True)) == entry["resolved_path"]
            and (os.readlink(path) if path.is_symlink() else None) == entry["symlink"],
            "Original runtime directory changed",
        )

    for entry in inventory["files"].values():
        path = Path(entry["source_path"])
        require(
            str(path.resolve(strict=True)) == entry["resolved_path"]
            and (os.readlink(path) if path.is_symlink() else None) == entry["symlink"]
            and path.stat().st_size == entry["size"]
            and stat.S_IMODE(path.stat().st_mode) == entry["mode"]
            and digest(path) == entry["sha256"],
            f"Original runtime output changed: {path}",
        )


def same_runtime_inventory(original, current):
    # Interpreter/build metadata may appear without changing any retained runtime bytes.
    return all(
        original[key] == current[key] for key in ("files", "directories", "missing_optional")
    )


def elf_machine(path):
    with path.open("rb") as stream:
        header = stream.read(20)
    require(
        header[:7] == b"\x7fELF\x02\x01\x01" and len(header) == 20, "Expected ELF64 native binary"
    )
    return int.from_bytes(header[18:20], "little")


def check_archive(archive, inventory):
    expected = {"runtime": None}
    expected.update({"runtime/" + name: None for name in inventory["directories"]})
    expected.update({"runtime/" + name: entry for name, entry in inventory["files"].items()})
    observed = set()
    with tarfile.open(archive, "r:gz") as stream:
        for member in stream:
            name = str(reuse.safe_name(member.name))
            require(
                name in expected and name not in observed, "Unexpected/duplicate runtime TAR path"
            )
            observed.add(name)
            record = expected[name]
            if record is None:
                require(member.isdir(), "Expected runtime directory")
            else:
                require(
                    member.isfile() and member.size == record["size"], "Runtime TAR file differs"
                )
                file = stream.extractfile(member)
                require(file is not None, "Unreadable runtime TAR file")
                sha = hashlib.sha256()
                while raw := file.read(1024 * 1024):
                    sha.update(raw)
                require(sha.hexdigest() == record["sha256"], "Runtime TAR bytes differ")
    require(observed == expected.keys(), "Incomplete runtime TAR")


def raw_output_inventory(build):
    """Inventory only physical output bytes; preserve, never follow, link text."""
    entries, excluded, total = {}, [], 0

    def walk(path, name):
        nonlocal total
        reuse.safe_name(name)
        if path.name in SCRATCH_NAMES:
            excluded.append(
                {"path": name, "reason": "compile/Git/Python-cache scratch; not traversed"}
            )
            return
        info = path.lstat()
        record = {"mode": stat.S_IMODE(info.st_mode), "size": 0}
        if stat.S_ISLNK(info.st_mode):
            record.update(type="symlink", link_target=os.readlink(path))
        elif stat.S_ISDIR(info.st_mode):
            record.update(type="directory")
        elif stat.S_ISREG(info.st_mode):
            physical(path)
            record.update(type="file", size=info.st_size, sha256=digest(path))
            total += info.st_size
        else:
            raise ValueError(f"Nonregular raw diagnostic output: {path}")
        require(
            len(entries) < MAX_FILES and total <= MAX_BYTES,
            f"Raw diagnostic bundle exceeds bound: {path}",
        )
        entries[name] = record
        if record["type"] == "directory":
            for child in sorted(path.iterdir()):
                walk(child, name + "/" + child.name)

    for name in OUTPUT_DIRS:
        path = build / name
        if path.exists() or path.is_symlink():
            walk(path, name)
    return {"entries": entries, "excluded": excluded, "physical_file_bytes": total}


def retain_raw_archive(build, root):
    inventory = raw_output_inventory(build)
    write_json(root / "raw-runtime-files.json", inventory)
    archive = root / "native-build-raw.tar.gz"
    with tarfile.open(archive, "w:gz", format=tarfile.PAX_FORMAT) as stream:
        for name, record in sorted(inventory["entries"].items()):
            member = tarfile.TarInfo("runtime/" + name)
            member.mode = record["mode"]
            if record["type"] == "symlink":
                member.type, member.linkname = tarfile.SYMTYPE, record["link_target"]
                stream.addfile(member)
            elif record["type"] == "directory":
                member.type = tarfile.DIRTYPE
                stream.addfile(member)
            else:
                member.size = record["size"]
                with physical(build / name).open("rb") as file:
                    stream.addfile(member, file)
    seen = set()
    with tarfile.open(archive, "r:gz") as stream:
        for member in stream:
            name = str(reuse.safe_name(member.name)).removeprefix("runtime/")
            require(
                name in inventory["entries"] and name not in seen, "Raw archive namespace differs"
            )
            seen.add(name)
            record = inventory["entries"][name]
            require(member.mode == record["mode"], f"Raw archive mode differs: {name}")
            if record["type"] == "symlink":
                require(
                    member.issym() and member.linkname == record["link_target"],
                    f"Raw archive link differs: {name}",
                )
            elif record["type"] == "directory":
                require(member.isdir(), f"Raw archive directory differs: {name}")
            else:
                require(
                    member.isfile() and member.size == record["size"],
                    f"Raw archive file differs: {name}",
                )
                sha = hashlib.sha256()
                with stream.extractfile(member) as file:
                    while data := file.read(1024 * 1024):
                        sha.update(data)
                require(sha.hexdigest() == record["sha256"], f"Raw archive bytes differ: {name}")
    require(seen == inventory["entries"].keys(), "Incomplete raw archive")
    require(
        raw_output_inventory(build) == inventory,
        "Physical output bytes changed during raw retention",
    )
    return {
        "name": archive.name,
        "size": archive.stat().st_size,
        "sha256": digest(archive),
        "inventory_sha256": digest(root / "raw-runtime-files.json"),
        "entries": len(inventory["entries"]),
        "physical_file_bytes": inventory["physical_file_bytes"],
        "symlinks_followed": False,
        "link_targets_validated": False,
        "restoration_validated": False,
        "scope": "raw unvalidated diagnostic bytes; separate review required before any restoration",
    }


def checked_bypass(source, build, module, tracked):
    bypass = read_json(physical(module.parent / "bypass-provenance.json"))
    require(
        bypass["mode"] == "ci-checkout"
        and bypass["original_build_outputs_unchanged"] is False
        and bypass["module"] == str(module)
        and bypass["compiled_module"] == str(build / "Mod/TechDraw/TechDrawGui.so")
        and digest(module) == bypass["module_sha256"],
        "Controlled module provenance differs",
    )
    substitutions = {
        "QGCustomPath.cpp": ("if (brush().style()", "if (false && brush().style()"),
        "QGCustomRect.cpp": ("if (rect().isNull())", "if (false && rect().isNull())"),
    }
    expected, protected = [], {}
    for name, (before, after) in substitutions.items():
        original = physical(source / "src/Mod/TechDraw/Gui" / name)
        copy = physical(module.parent / name)
        text = original.read_text()
        require(text.count(before) == 1, "Controlled bypass source seam changed")
        require(copy.read_bytes() == text.replace(before, after).encode(), "Bypass copy differs")
        sha = tracked["files"][str(original.relative_to(source))]["sha256"]
        require(digest(original) == sha, "Bypass original differs from HEAD")
        expected.append({"source": str(original), "copy": str(copy), "copy_sha256": digest(copy)})
        protected[str(original)] = sha
    require(
        bypass["sources"] == expected and bypass["protected_original_sha256"] == protected,
        "Bypass must describe exactly the two guarded source substitutions",
    )
    return bypass


def retain(args):
    source, build, proof, module = (
        physical(args.source_root),
        physical(args.build_root),
        physical(args.proof_dir),
        physical(args.bypass_module),
    )
    require(build == source / "build/release", "Use the scoped native build/release outputs")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        require(
            args.head_sha == os.environ["GITHUB_SHA"], "Source differs from actual workflow head"
        )
    validation = validated_proof(proof)
    reuse.native_host(validation["target"])
    tracked = source_inventory(source, args.head_sha)
    cache = physical(build / "CMakeCache.txt")
    homes = re.findall(r"^CMAKE_HOME_DIRECTORY:INTERNAL=(.*)$", cache.read_text(), re.MULTILINE)
    require(homes == [str(source)], "Build source differs or is ambiguous")
    bypass = checked_bypass(source, build, module, tracked)
    require(
        bypass["mode"] == "ci-checkout"
        and bypass["original_build_outputs_unchanged"] is False
        and bypass["module"] == str(module)
        and digest(module) == bypass["module_sha256"]
        and digest(physical(build / "Mod/TechDraw/TechDrawGui.so")) == digest(module),
        "Controlled module differs from compiled native module",
    )
    require(
        elf_machine(physical(build / "bin/FreeCAD"))
        == elf_machine(module)
        == reuse.TARGETS[validation["target"]]["elf_machine"],
        "Native app/module architecture differs",
    )
    require(os.access(build / "bin/FreeCAD", os.X_OK), "Native FreeCAD is not executable")
    root = fresh_root(args.work_dir, [source, build, proof, module.parent])
    root.mkdir()
    emit_owned("native_build_dir", root)
    receipt = {
        **scope(),
        "status": "retaining",
        "source_root": str(source),
        "build_root": str(build),
        "head_sha": args.head_sha,
    }
    try:
        for filename, origin in {
            "CMakeCache.txt": cache,
            "TechDrawGui.so": module,
            "bypass-provenance.json": module.parent / "bypass-provenance.json",
            "reuse-validation.json": proof / "validation.json",
            "reuse-recovery.json": proof / "recovery.json",
            **{Path(entry["copy"]).name: Path(entry["copy"]) for entry in bypass["sources"]},
        }.items():
            shutil.copyfile(origin, root / filename)
        write_json(root / "source-files.json", tracked)
        receipt.update(
            target=validation["target"],
            source_inventory_sha256=digest(root / "source-files.json"),
            cmake_cache_sha256=digest(cache),
            validation_sha256=digest(proof / "validation.json"),
            recovery_sha256=digest(proof / "recovery.json"),
            bypass_module_sha256=digest(module),
            bypass_provenance_sha256=digest(module.parent / "bypass-provenance.json"),
            macro_sha256=tracked["files"][MACRO]["sha256"],
            package_sha256=validation["package_evidence"]["package_sha256"],
            runtime_prefix_bytes_bundled=False,
        )
        receipt["raw_archive"] = retain_raw_archive(build, root)
        receipt.update(status="raw-diagnostic-retained", strict_runtime_selection_passed=False)
        write_json(root / "native-build.json", receipt)
        inventory = output_inventory(build, source, tracked)
        write_json(root / "runtime-files.json", inventory)
        payload = root / "runtime"
        payload.mkdir()
        for directory in inventory["directories"]:
            (payload / directory).mkdir(parents=True, exist_ok=True)
        for name, entry in inventory["files"].items():
            destination = payload / name
            shutil.copyfile(entry["resolved_path"], destination)
            destination.chmod(entry["mode"])
            require(digest(destination) == entry["sha256"], "Copied runtime differs")
        archive = root / "native-build.tar.gz"
        with tarfile.open(archive, "w:gz", format=tarfile.PAX_FORMAT) as stream:
            # File copies contain no symlinks; tar adds only finite selected output paths.
            stream.add(payload, arcname="runtime", recursive=True)
        check_archive(archive, inventory)
        check_unchanged(inventory)
        require(
            same_runtime_inventory(inventory, output_inventory(build, source, tracked)),
            "Build namespace changed during copy",
        )
        require(
            source_inventory(source, args.head_sha) == tracked, "Source changed during retention"
        )
        require(digest(cache) == digest(root / "CMakeCache.txt"), "Cache changed during retention")
        require(
            checked_bypass(source, build, module, tracked) == bypass, "Bypass changed during copy"
        )
        # Remove the temporary dereferenced tree; retain the strict and raw archives.
        shutil.rmtree(payload)
        receipt.update(
            status="retained",
            strict_runtime_selection_passed=True,
            target=validation["target"],
            build_inventory_sha256=digest(root / "runtime-files.json"),
            source_inventory_sha256=digest(root / "source-files.json"),
            cmake_cache_sha256=digest(cache),
            validation_sha256=digest(proof / "validation.json"),
            recovery_sha256=digest(proof / "recovery.json"),
            bypass_module_sha256=digest(module),
            bypass_provenance_sha256=digest(module.parent / "bypass-provenance.json"),
            macro_sha256=tracked["files"][MACRO]["sha256"],
            package_sha256=validation["package_evidence"]["package_sha256"],
            runtime_prefix_bytes_bundled=False,
            output_files=len(inventory["files"]),
            output_bytes=sum(entry["size"] for entry in inventory["files"].values()),
            original_source_outputs_unchanged=True,
            archive={
                "name": archive.name,
                "size": archive.stat().st_size,
                "sha256": digest(archive),
            },
        )
    except Exception as error:
        receipt.update(status="failed", error=str(error))
        write_json(root / "native-build.json", receipt)
        raise
    write_json(root / "native-build.json", receipt)
    return {"native_build_dir": str(root), "qualified": False}


def checked_bundle(bundle, validation):
    bundle = physical(bundle)
    report = read_json(bundle / "native-build.json")
    require(
        report["status"] == "retained"
        and report["strict_runtime_selection_passed"] is True
        and report["diagnostic_only"] is True
        and report["qualified"] is False
        and report["target"] == "linux-aarch64"
        and report["helper_sha256"] == digest(Path(__file__).resolve()),
        "Require this helper's retained ARM diagnostic bundle",
    )
    require(
        digest(bundle / "reuse-validation.json") == report["validation_sha256"], "Bundle validation"
    )
    require(read_json(bundle / "reuse-validation.json") == validation, "Current validation differs")
    for name, key in {
        "runtime-files.json": "build_inventory_sha256",
        "source-files.json": "source_inventory_sha256",
        "CMakeCache.txt": "cmake_cache_sha256",
        "TechDrawGui.so": "bypass_module_sha256",
        "bypass-provenance.json": "bypass_provenance_sha256",
        "reuse-recovery.json": "recovery_sha256",
    }.items():
        require(digest(physical(bundle / name)) == report[key], "Retained bundle receipt differs")
    archive = physical(bundle / report["archive"]["name"])
    require(
        archive.name == "native-build.tar.gz"
        and archive.stat().st_size == report["archive"]["size"]
        and digest(archive) == report["archive"]["sha256"],
        "Retained runtime archive changed",
    )
    inventory = read_json(bundle / "runtime-files.json")
    check_archive(archive, inventory)
    check_unchanged(inventory)
    source = physical(Path(report["source_root"]))
    tracked = read_json(bundle / "source-files.json")
    require(
        source_inventory(source, report["head_sha"]) == tracked,
        "Current source differs from retained build",
    )
    require(
        same_runtime_inventory(
            inventory, output_inventory(physical(Path(report["build_root"])), source, tracked)
        ),
        "Current build namespace differs from retained outputs",
    )
    bypass = checked_bypass(
        source,
        physical(Path(report["build_root"])),
        physical(Path(read_json(bundle / "bypass-provenance.json")["module"])),
        tracked,
    )
    require(
        bypass == read_json(bundle / "bypass-provenance.json"), "Current bypass differs from bundle"
    )
    for entry in bypass["sources"]:
        require(
            digest(physical(bundle / Path(entry["copy"]).name)) == entry["copy_sha256"],
            "Bundle bypass source differs",
        )
    return report, inventory


def diagnostic_plan(args):
    require(
        sys.platform == "linux" and platform.machine() == "aarch64", "ARM Linux diagnostics only"
    )
    failed, native_report, proof = (
        physical(args.failed_results),
        physical(args.native_report),
        physical(args.proof_dir),
    )
    validation = validated_proof(proof)
    require(validation["target"] == "linux-aarch64", "Require ARM reused proof")
    bundle, inventory = checked_bundle(args.build_bundle, validation)
    require(not (failed / "patched").exists(), "Only a baseline-only failure can be replayed")
    baseline = physical(failed / "baseline")
    names = {path.name for path in baseline.iterdir()}
    require(
        {"launch.json", "macro.log", "runtime.log"} <= names
        and not any(name.endswith((".pdf", ".png")) for name in names)
        and "native-provenance.json" not in names
        and "manifest.json" not in names,
        "Require failed startup before any native export/provenance",
    )
    launch = read_json(physical(baseline / "launch.json"))
    report = read_json(native_report)
    require(
        report["passed"] is False
        and len(report["failures"]) == 1
        and "Signals.SIGSEGV: 11" in report["failures"][0],
        "Only the recorded ARM SIGSEGV failure is diagnostic input",
    )
    source, build = physical(Path(bundle["source_root"])), physical(Path(bundle["build_root"]))
    command = launch["command"]
    require(
        command
        == [
            str(build / "bin/FreeCAD"),
            "--hidden",
            "--user-cfg",
            str(baseline / "user.cfg"),
            "--system-cfg",
            str(baseline / "system.cfg"),
            str(source / MACRO),
        ],
        "Unexpected failed launch command",
    )
    environment = launch["environment_overrides"].copy()
    require(environment.keys() <= ENVIRONMENT_KEYS, "Unreviewed failed-launch environment key")
    require(
        all(
            isinstance(value, str)
            and value == value.strip()
            and not any(ord(c) < 32 for c in value)
            for value in environment.values()
        ),
        "Unsafe GDB environment value",
    )
    prefix = validation["native_runtime"]["baseline"]["prefix"]
    expected = {
        "QT_PDF_TARGET": "linux-aarch64",
        "QT_PDF_BUILD_RUN": str(reuse.PACKAGE_RUN),
        "QT_QPA_PLATFORM": "xcb",
        "PYTHONHOME": prefix,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "TD_NATIVE_DISPOSABLE": "1",
        "TD_NATIVE_EXPECTED_QT_VERSION": "6.11.2",
        "TD_NATIVE_QT_PREFIX": prefix,
        "TD_NATIVE_QT_LIB": str(Path(prefix) / "lib"),
        "TD_NATIVE_MACRO_PATH": str(source / MACRO),
        "TD_NATIVE_MACRO_SHA256": bundle["macro_sha256"],
        "TD_NATIVE_OUTPUT": str(baseline),
    }
    require(
        all(environment.get(key) == value for key, value in expected.items()),
        "Runtime launch binding differs",
    )
    require(
        environment["LD_LIBRARY_PATH"].split(os.pathsep)[:2] == [str(Path(prefix) / "lib")] * 2,
        "Baseline loader selection differs",
    )
    plugin = physical(Path(environment["TD_NATIVE_PLUGIN_ROOT"]))
    require(plugin.is_relative_to(Path(prefix)), "QPA plugins outside baseline prefix")
    require(
        environment["QT_PLUGIN_PATH"] == str(plugin)
        and environment["QT_QPA_PLATFORM_PLUGIN_PATH"] == str(plugin / "platforms"),
        "QPA launch differs",
    )
    module = physical(Path(environment["TD_NATIVE_BYPASS_MODULE"]))
    require(digest(module) == bundle["bypass_module_sha256"], "Scratch module changed")
    require(
        digest(build / "bin/FreeCAD") == inventory["files"]["bin/FreeCAD"]["sha256"],
        "Native app changed",
    )
    gdb = physical(args.gdb)
    require(
        gdb.is_file() and os.access(gdb, os.X_OK) and gdb.name == "gdb",
        "Require resolved GDB executable",
    )
    display = os.environ.get("DISPLAY", "")
    require(re.fullmatch(r":\d+(?:\.\d+)?", display), "Current live Xvfb DISPLAY required")
    authority = physical(Path(os.environ["XAUTHORITY"]))
    require(authority.is_file(), "Current live Xvfb authorization required")
    require(30 <= args.timeout <= 180, "Diagnostic timeout must be 30–180 seconds")
    root = fresh_root(
        args.work_dir,
        [
            failed,
            native_report,
            source,
            build,
            proof,
            Path(args.build_bundle),
            module.parent,
            Path(prefix),
            Path(validation["native_runtime"]["patched"]["prefix"]),
        ],
    )
    command[3], command[5] = str(root / "capture/user.cfg"), str(root / "capture/system.cfg")
    replacements = {
        "TD_NATIVE_OUTPUT": str(root / "capture"),
        "DISPLAY": display,
        "XAUTHORITY": str(authority),
    }
    environment.update(replacements)
    safe_gdb_environment(environment)
    original_hashes = {
        str(path): digest(physical(path))
        for path in (
            baseline / "launch.json",
            baseline / "macro.log",
            baseline / "runtime.log",
            native_report,
        )
    }
    return root, command, environment, original_hashes, bundle, gdb, replacements


def safe_gdb_environment(environment):
    require(
        environment.keys() <= ENVIRONMENT_KEYS | {"XAUTHORITY"}, "Unreviewed inferior environment"
    )
    require(
        all(
            isinstance(value, str)
            and value == value.strip()
            and not any(ord(character) < 32 for character in value)
            for value in environment.values()
        ),
        "Unsafe GDB inferior environment value",
    )


def gdb_script(environment, source):
    safe_gdb_environment(environment)
    require(
        not any(character in source for character in "*?[]~\n\r"), "Unsafe GDB working directory"
    )
    commands = [
        "set pagination off",
        "set confirm off",
        "set startup-with-shell off",
        f"set cwd {source}",
        "set auto-load off",
        "set debuginfod enabled off",
        "set print elements 30",
        "set print frame-arguments none",
        "set backtrace limit 40",
        "handle SIGSEGV stop print pass",
    ]
    # The tool's Python/Qt/loader variables must not leak into the inferior.
    for key in sorted(set(os.environ) | ENVIRONMENT_KEYS | {"XAUTHORITY"}):
        if key.startswith(("QT_", "TD_NATIVE_", "DYLD_", "PYTHON")) or key in (
            "LD_LIBRARY_PATH",
            "LD_PRELOAD",
        ):
            require(
                re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", key), "Unsafe inherited environment key"
            )
            commands.append(f"unset environment {key}")
    commands.extend(
        f"set environment {key} = {value}" for key, value in sorted(environment.items())
    )
    commands += [
        "run",
        "echo \\nTD_NATIVE_DIAGNOSTIC_STOP\\n",
        "if $_isvoid($_exitcode) && $_isvoid($_exitsignal)",
        "info threads",
        "thread apply all -c backtrace 40",
        "info sharedlibrary",
        "info proc mappings",
        "p $_siginfo",
        "continue",
        "end",
    ]
    return "\n".join(commands) + "\n"


def terminate_tree(process):
    """Stop only this helper's GDB and descendants, even with separate job groups."""
    children = []

    def visit(pid):
        try:
            values = Path(f"/proc/{pid}/task/{pid}/children").read_text().split()
        except (FileNotFoundError, ProcessLookupError):
            return
        for value in values:
            child = int(value)
            visit(child)
            children.append(child)

    visit(process.pid)
    for pid in children:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=10)


def run_gdb(command, root, timeout):
    exceeded = threading.Event()
    with (root / "gdb.log").open("wb") as output:

        def no_core():
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

        process = subprocess.Popen(
            command,
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            preexec_fn=no_core,
        )

        def copy_output():
            count = 0
            while raw := process.stdout.read(65536):
                available = max(0, MAX_LOG - count)
                output.write(raw[:available])
                output.flush()
                count += len(raw)
                if count > MAX_LOG:
                    exceeded.set()
                    terminate_tree(process)
                    break

        reader = threading.Thread(target=copy_output, daemon=True)
        reader.start()
        timed_out = False
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            # Interrupt first so batch GDB can report the stopped threads/loader.
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                terminate_tree(process)
        reader.join(timeout=5)
        require(not reader.is_alive(), "GDB output did not close after bounded termination")
    return {
        "returncode": process.returncode,
        "timeout": timed_out,
        "log_limit_exceeded": exceeded.is_set(),
    }


def diagnose(args):
    root, inferior, environment, originals, bundle, gdb, replacements = diagnostic_plan(args)
    root.mkdir()
    emit_owned("crash_diagnostics_dir", root)
    (root / "capture").mkdir()
    script = root / "gdb.commands"
    script.write_text(gdb_script(environment, bundle["source_root"]))
    command = [
        str(gdb),
        "--batch",
        "--nx",
        "--return-child-result",
        "-iex",
        "set auto-load off",
        "-iex",
        "set debuginfod enabled off",
        "-x",
        str(script),
        "--args",
        *inferior,
    ]
    receipt = {
        **scope(),
        "status": "prepared",
        "target": "linux-aarch64",
        "original_failure": "baseline process SIGSEGV11 before native exports",
        "original_evidence_sha256": originals,
        "inferior_working_directory": bundle["source_root"],
        "working_directory_basis": "Workflow GITHUB_WORKSPACE / authenticated CMake source root",
        "retained_build_json_sha256": digest(Path(args.build_bundle) / "native-build.json"),
        "head_sha": bundle["head_sha"],
        "gdb_executable": str(gdb),
        "gdb_executable_sha256": digest(gdb),
        "command": command,
        "inferior_environment_overrides": environment,
        "explicit_replacements": replacements,
        "xauthority_sha256": digest(Path(replacements["XAUTHORITY"])),
        "gdb_documentation": GDB_DOCS,
        "maximum_debugger_seconds_including_teardown": args.timeout + 20,
        "core_dumps_disabled": True,
        "maximum_gdb_log_bytes": MAX_LOG,
        "original_native_gate_remains_failed": True,
        "qt_fixture_upstream_reinvoked": False,
    }
    write_json(root / "diagnostic.json", receipt)
    try:
        version = subprocess.run(
            [str(gdb), "--version"], check=True, capture_output=True, timeout=15
        )
        require(
            len(version.stdout) < 65536 and len(version.stderr) < 65536,
            "Unexpected GDB version output",
        )
        (root / "gdb-version.txt").write_bytes(version.stdout + version.stderr)
        outcome = run_gdb(command, root, args.timeout)
        current_validation = validated_proof(args.proof_dir)
        require(
            current_validation == read_json(Path(args.build_bundle) / "reuse-validation.json"),
            "Installed runtime/proof changed during diagnostic",
        )
        checked_bundle(args.build_bundle, current_validation)
        require(
            all(digest(Path(path)) == sha for path, sha in originals.items()),
            "Original failure evidence changed",
        )
        receipt.update(
            status="diagnostic-completed",
            gdb_result=outcome,
            original_evidence_unchanged=True,
            gdb_log_sha256=digest(root / "gdb.log"),
            gdb_version_sha256=digest(root / "gdb-version.txt"),
        )
    except Exception as error:
        receipt.update(status="failed", error=str(error))
        write_json(root / "diagnostic.json", receipt)
        raise
    write_json(root / "diagnostic.json", receipt)
    # A debugger return code or normal rerun never converts the original failed gate.
    return {"crash_diagnostics_dir": str(root), "qualified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    retain_parser = commands.add_parser("retain")
    for name in ("build-root", "source-root", "bypass-module", "proof-dir", "work-dir"):
        retain_parser.add_argument("--" + name, type=Path, required=True)
    retain_parser.add_argument("--head-sha", required=True)
    diagnosis = commands.add_parser("diagnose")
    for name in ("failed-results", "native-report", "build-bundle", "proof-dir", "work-dir", "gdb"):
        diagnosis.add_argument("--" + name, type=Path, required=True)
    diagnosis.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    try:
        print(json.dumps(retain(args) if args.command == "retain" else diagnose(args)))
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Native diagnostic setup/retention failed: {error}\n")


if __name__ == "__main__":
    main()
