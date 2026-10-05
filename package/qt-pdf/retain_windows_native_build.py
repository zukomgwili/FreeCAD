# SPDX-License-Identifier: LGPL-2.1-or-later
"""Retain bounded physical Windows build files for diagnosis only.

No runtime prefixes, link targets or compile scratch are bundled. The ZIP and
its receipts do not validate restoration, native qualification or distribution.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import zipfile

import reuse_windows_qt_qualification as reuse

OUTPUT_DIRS = ("bin", "lib", "Mod", "Ext", "data", "share")
SCRATCH_DIRS = {"CMakeFiles", ".git", "__pycache__"}
SOURCE_PATHS = ("src", "cMake", "CMakeLists.txt", "CMakePresets.json", "pixi.toml", "pixi.lock")
MAX_FILES = 60000
MAX_BYTES = 8 * 1024**3
require, physical, digest, read_json = reuse.require, reuse.physical, reuse.digest, reuse.read_json


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def git(source, *arguments):
    environment = {
        key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")
    }
    environment.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_TERMINAL_PROMPT="0",
        GIT_OPTIONAL_LOCKS="0",
    )
    return subprocess.check_output(
        ["git", "-C", str(source), *arguments], env=environment, stderr=subprocess.PIPE
    )


def source_inventory(source, head):
    """Bind selected tracked worktree bytes and initialized submodule heads."""
    require(re.fullmatch(r"[0-9a-f]{40}", head), "Use an exact source commit")
    require(git(source, "rev-parse", "HEAD").decode().strip() == head, "Source HEAD differs")
    require(not git(source, "diff", "HEAD", "--", *SOURCE_PATHS), "Selected tracked source differs")
    files, submodules = {}, {}
    for entry in git(source, "ls-tree", "-r", "-z", "HEAD", "--", *SOURCE_PATHS).split(b"\0"):
        if not entry:
            continue
        metadata, raw_name = entry.split(b"\t", 1)
        mode, kind, blob = metadata.decode().split()
        name = raw_name.decode("utf-8")
        require(
            "\\" not in name
            and ":" not in name
            and all(part not in ("", ".", "..") for part in name.split("/")),
            f"Unsafe source name: {name}",
        )
        path = source / name
        if kind == "commit":
            initialized = (path / ".git").exists()
            submodules[name] = {"gitlink": blob, "initialized": initialized}
            if initialized:
                physical(path)
                require(
                    git(path, "rev-parse", "HEAD").decode().strip() == blob,
                    f"Gitlink HEAD differs: {name}",
                )
                require(not git(path, "diff", "HEAD"), f"Tracked submodule differs: {name}")
            continue
        require(kind == "blob" and mode in ("100644", "100755"), f"Nonregular source: {name}")
        path = physical(path)
        require(path.is_file(), f"Missing selected source file: {name}")
        require(name not in files, f"Duplicate source name: {name}")
        files[name] = {"git_blob": blob, "sha256": digest(path), "size": path.stat().st_size}
    require(files and len(files) <= MAX_FILES, "Selected source inventory is empty or unbounded")
    return {
        "head": head,
        "tree": git(source, "rev-parse", "HEAD^{tree}").decode().strip(),
        "selected_paths": list(SOURCE_PATHS),
        "scope": "Git-clean selected tracked trees plus physical worktree hashes; initialized submodule HEAD/clean state only",
        "raw_worktree_equals_git_blob_bytes_claimed": False,
        "submodule_file_bytes_inventoried": False,
        "files": files,
        "submodules": submodules,
    }


def checked_bypass(source, build, module, tracked):
    compiled = physical(build / "Mod/TechDraw/TechDrawGui.pyd")
    report = read_json(physical(module.parent / "bypass-provenance.json"))
    require(
        report["mode"] == "ci-checkout"
        and report["original_build_outputs_unchanged"] is False
        and report["module"] == str(module)
        and report["compiled_module"] == str(compiled)
        and digest(module) == report["module_sha256"] == digest(compiled),
        "Compiled/scratch bypass identity differs",
    )
    substitutions = {
        "QGCustomPath.cpp": ("if (brush().style()", "if (false && brush().style()"),
        "QGCustomRect.cpp": ("if (rect().isNull())", "if (false && rect().isNull())"),
    }
    sources, protected = [], {}
    for name, (before, after) in substitutions.items():
        original = physical(source / "src/Mod/TechDraw/Gui" / name)
        copied = physical(module.parent / name)
        text = original.read_text()
        require(text.count(before) == 1, f"Bypass guard seam differs: {name}")
        require(
            copied.read_bytes() == text.replace(before, after).encode(),
            f"Bypass copy differs: {name}",
        )
        sha = tracked["files"][original.relative_to(source).as_posix()]["sha256"]
        require(digest(original) == sha, f"Original guarded source changed: {name}")
        protected[str(original)] = sha
        sources.append(
            {"source": str(original), "copy": str(copied), "copy_sha256": digest(copied)}
        )
    require(
        report["sources"] == sources and report["protected_original_sha256"] == protected,
        "Bypass must bind exactly the two restored guard sources",
    )
    return report


def output_inventory(build):
    files, directories, excluded, names = {}, {}, [], set()
    total = 0

    def visit(path):
        nonlocal total
        path = physical(path)
        name = path.relative_to(build).as_posix()
        require(name.casefold() not in names, f"Duplicate/case-colliding output: {name}")
        names.add(name.casefold())
        require(len(names) <= MAX_FILES, f"Too many runtime output entries: {name}")
        info = path.lstat()
        mode = stat.S_IMODE(info.st_mode)
        if stat.S_ISDIR(info.st_mode):
            if path.name in SCRATCH_DIRS:
                excluded.append({"relative_path": name, "reason": path.name})
                return
            directories[name] = {"mode": mode}
            for child in sorted(path.iterdir(), key=lambda item: item.name.casefold()):
                visit(child)
        else:
            require(stat.S_ISREG(info.st_mode), f"Special runtime output: {name}")
            require(
                path.suffix.lower() not in (".o", ".obj", ".a"),
                f"Compile object in runtime outputs: {name}",
            )
            total += info.st_size
            require(total <= MAX_BYTES, f"Runtime output bytes exceed bound: {name}")
            files[name] = {"mode": mode, "size": info.st_size, "sha256": digest(path)}

    for name in OUTPUT_DIRS:
        path = build / name
        if path.exists() or path.is_symlink():
            visit(path)
    require(files, "Runtime outputs are empty")
    return {
        "files": files,
        "directories": directories,
        "excluded": excluded,
        "physical_bytes": total,
    }


def check_archive(archive, inventory):
    expected = {
        **{name + "/": value for name, value in inventory["directories"].items()},
        **inventory["files"],
    }
    with zipfile.ZipFile(physical(archive)) as zipped:
        entries = zipped.infolist()
        require(len(entries) == len(expected), "Runtime ZIP member count differs")
        seen = set()
        for entry in entries:
            name = entry.filename
            require(
                name in expected and name not in seen, f"Unexpected/duplicate ZIP member: {name}"
            )
            seen.add(name)
            value = expected[name]
            require(not entry.flag_bits & 1, f"Encrypted runtime ZIP member: {name}")
            mode = entry.external_attr >> 16
            require(stat.S_IMODE(mode) == value["mode"], f"Runtime ZIP mode differs: {name}")
            require(
                stat.S_ISDIR(mode) if name.endswith("/") else stat.S_ISREG(mode),
                f"Runtime ZIP type differs: {name}",
            )
            if name.endswith("/"):
                require(entry.file_size == 0, f"Nonempty ZIP directory: {name}")
                continue
            require(entry.file_size == value["size"], f"Runtime ZIP size differs: {name}")
            sha = hashlib.sha256()
            with zipped.open(entry) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    sha.update(block)
            require(sha.hexdigest() == value["sha256"], f"Runtime ZIP bytes/CRC differ: {name}")
        require(seen == set(expected), "Runtime ZIP namespace differs")


def archive_outputs(build, root):
    inventory = output_inventory(build)
    archive = root / "native-build.zip"
    with zipfile.ZipFile(
        archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True
    ) as zipped:
        for name, entry in inventory["directories"].items():
            physical(build / name)
            metadata = zipfile.ZipInfo(name + "/")
            metadata.create_system = 3
            metadata.external_attr = (stat.S_IFDIR | entry["mode"]) << 16
            zipped.writestr(metadata, b"")
        for name, entry in inventory["files"].items():
            origin = physical(build / name)
            metadata = zipfile.ZipInfo(name)
            metadata.create_system = 3
            metadata.compress_type = zipfile.ZIP_DEFLATED
            metadata.external_attr = (stat.S_IFREG | entry["mode"]) << 16
            copied = 0
            with origin.open("rb") as stream, zipped.open(
                metadata, "w", force_zip64=True
            ) as destination:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    copied += len(block)
                    require(copied <= entry["size"], f"Runtime file grew during copy: {name}")
                    destination.write(block)
            require(copied == entry["size"], f"Runtime file shrank during copy: {name}")
    require(output_inventory(build) == inventory, "Runtime outputs changed during retention")
    check_archive(archive, inventory)
    write_json(root / "native-output-files.json", inventory)
    return {
        "path": str(archive),
        "sha256": digest(archive),
        "size": archive.stat().st_size,
        "manifest_sha256": digest(root / "native-output-files.json"),
        "file_count": len(inventory["files"]),
        "directory_count": len(inventory["directories"]),
        "physical_bytes": inventory["physical_bytes"],
        "excluded": inventory["excluded"],
        "links_admitted": False,
        "restoration_validated": False,
    }


def fresh_root(path, protected):
    root = physical(path, existing=False)
    temporary = physical(Path(os.environ["RUNNER_TEMP"]))
    require(
        root != temporary and root.is_relative_to(temporary),
        "Retention must be inside owned RUNNER_TEMP",
    )
    require(not root.exists(), "Retention directory must be fresh")
    for origin in protected:
        origin = physical(origin)
        require(
            not root.is_relative_to(origin) and not origin.is_relative_to(root),
            f"Retention overlaps protected input: {origin}",
        )
    physical(root.parent)
    return root


def emit_owned(root):
    destination = os.environ.get("GITHUB_OUTPUT")
    if destination:
        path = physical(Path(destination))
        require(
            path.is_file() and "\n" not in str(root) and "\r" not in str(root),
            "Invalid workflow output path",
        )
        with path.open("a", encoding="utf-8") as file:
            file.write("windows_native_build_dir=" + str(root) + "\n")


def retain(args):
    host = reuse.native_host()
    source, build, proof, module = map(
        physical, (args.source_root, args.build_root, args.proof_dir, args.bypass_module)
    )
    require(build == source / "build/release", "Use the actual scoped build/release tree")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        require(
            source == physical(Path(os.environ["GITHUB_WORKSPACE"]))
            and args.head_sha == os.environ["GITHUB_SHA"],
            "Workflow source/head differs",
        )
    validation = reuse.current_validation(proof)
    tracked = source_inventory(source, args.head_sha)
    cache = physical(build / "CMakeCache.txt")
    homes = re.findall(r"^CMAKE_HOME_DIRECTORY:INTERNAL=(.*)$", cache.read_text(), re.MULTILINE)
    require(
        len(homes) == 1 and physical(Path(homes[0])) == source,
        "Actual CMake source differs or is ambiguous",
    )
    bypass = checked_bypass(source, build, module, tracked)
    pe_paths = {
        "bin/FreeCAD.exe": False,
        "bin/FreeCADApp.dll": True,
        "bin/FreeCADGui.dll": True,
        "Mod/TechDraw/TechDrawGui.pyd": True,
    }
    identities = {
        name: {**reuse.pe_x64(build / name, dll=dll), "sha256": digest(build / name)}
        for name, dll in pe_paths.items()
    }
    protected = [
        source,
        build,
        proof,
        module.parent,
        *[Path(validation["native_runtime"][side]["prefix"]) for side in ("baseline", "patched")],
        Path(validation["package_evidence"]["build_json"]).parent,
        Path(validation["qt_source_archive"]).parent,
    ]
    root = fresh_root(args.work_dir, protected)
    root.mkdir()
    emit_owned(root)
    receipt = {
        "schema_version": 1,
        "scope": "Bounded physical native Windows build diagnostic files only",
        "diagnostic_only": True,
        "qualified": False,
        "native_freecad_qualified": False,
        "distribution_promoted": False,
        "restoration_validated": False,
        "runtime_prefix_bytes_bundled": False,
        "status": "retaining",
        "target": "win-64",
        "host": host,
        "head_sha": args.head_sha,
        "source_root": str(source),
        "build_root": str(build),
        "helper_sha256": digest(Path(__file__).resolve()),
        "reuse_helper_sha256": digest(Path(reuse.__file__).resolve()),
        "native_pe": identities,
    }
    try:
        inputs = {
            "CMakeCache.txt": cache,
            "bypass-provenance.json": module.parent / "bypass-provenance.json",
            "reuse-validation.json": proof / "validation.json",
            "reuse-recovery.json": proof / "recovery.json",
            **{Path(entry["copy"]).name: Path(entry["copy"]) for entry in bypass["sources"]},
        }
        input_hashes = {name: digest(physical(origin)) for name, origin in inputs.items()}
        for name, origin in inputs.items():
            require(
                origin.stat().st_size <= 16 * 1024**2, f"Unbounded retained proof input: {name}"
            )
            (root / name).write_bytes(physical(origin).read_bytes())
            require(digest(root / name) == input_hashes[name], f"Retained input differs: {name}")
        write_json(root / "source-files.json", tracked)
        receipt["input_sha256"] = input_hashes
        receipt["source_inventory_sha256"] = digest(root / "source-files.json")
        receipt["raw_archive"] = archive_outputs(build, root)
        require(
            source_inventory(source, args.head_sha) == tracked,
            "Selected source changed during retention",
        )
        require(
            checked_bypass(source, build, module, tracked) == bypass,
            "Bypass changed during retention",
        )
        require(
            reuse.current_validation(proof) == validation,
            "Selected runtime/reuse proof changed during retention",
        )
        for name, origin in inputs.items():
            require(
                digest(physical(origin)) == input_hashes[name], f"Protected input changed: {name}"
            )
        receipt.update(status="raw-diagnostic-retained", protected_inputs_unchanged=True)
    except Exception as error:
        receipt.update(status="failed", error=str(error))
        write_json(root / "native-build.json", receipt)
        raise
    write_json(root / "native-build.json", receipt)
    return {"windows_native_build_dir": str(root), "qualified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source-root", "build-root", "proof-dir", "bypass-module", "work-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--head-sha", required=True)
    try:
        print(json.dumps(retain(parser.parse_args())))
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Windows diagnostic retention failed: {error}\n")


if __name__ == "__main__":
    main()
