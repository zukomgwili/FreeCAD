# SPDX-License-Identifier: LGPL-2.1-or-later
"""Retain owned Intel native build bytes without qualifying their restoration.

The bounded raw archive stores symlink text and never follows it. Retention is
optional diagnostic work; ordinary native acceptance is a separate gate.
"""

import argparse
import os
from pathlib import Path
import re
import shutil
from types import SimpleNamespace

import linux_native_diagnostics as archive_tools
import reuse_macos_qt_qualification as reuse

require, physical, digest, read_json = (
    reuse.require,
    reuse.physical,
    reuse.digest,
    reuse.read_json,
)


def retain(args):
    reuse.native_host("osx-64")
    source, build, proof, module = map(
        physical, (args.source_root, args.build_root, args.proof_dir, args.bypass_module)
    )
    require(build == source / "build/release", "Use the actual scoped build/release tree")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        require(args.head_sha == os.environ["GITHUB_SHA"], "Workflow source HEAD differs")
    validation = read_json(proof / "validation.json")
    current = reuse.validation_data(
        SimpleNamespace(
            proof_dir=proof,
            baseline_prefix=Path(validation["native_runtime"]["baseline"]["prefix"]),
            patched_prefix=Path(validation["native_runtime"]["patched"]["prefix"]),
            package_build_json=Path(validation["package_evidence"]["build_json"]),
            qt_source_archive=Path(validation["qt_source_archive"]),
        )
    )
    require(current == validation, "Installed passed-stage reuse proof changed")
    tracked = archive_tools.source_inventory(source, args.head_sha)
    cache = physical(build / "CMakeCache.txt")
    homes = re.findall(r"^CMAKE_HOME_DIRECTORY:INTERNAL=(.*)$", cache.read_text(), re.MULTILINE)
    require(homes == [str(source)], "Actual build source differs or is ambiguous")
    bypass = archive_tools.checked_bypass(source, build, module, tracked)
    compiled = physical(build / "Mod/TechDraw/TechDrawGui.so")
    require(digest(compiled) == digest(module), "Bypass differs from compiled native module")
    executable = physical(build / "bin/FreeCAD")
    require(os.access(executable, os.X_OK), "Native FreeCAD is not executable")
    identities = {
        "bin/FreeCAD": reuse.macho_x86_64(executable, file_types=(2,)),
        "Mod/TechDraw/TechDrawGui.so": reuse.macho_x86_64(compiled, file_types=(6, 8)),
    }
    protected = [
        source,
        build,
        proof,
        module.parent,
        Path(validation["native_runtime"]["baseline"]["prefix"]),
        Path(validation["native_runtime"]["patched"]["prefix"]),
        Path(validation["package_evidence"]["build_json"]).parent,
        Path(validation["qt_source_archive"]).parent,
    ]
    root = archive_tools.fresh_root(args.work_dir, protected)
    root.mkdir()
    archive_tools.emit_owned("macos_native_build_dir", root)
    receipt = {
        "schema_version": 1,
        "scope": "Owned Intel build diagnostic bytes; separate review required before restoration",
        "diagnostic_only": True,
        "qualified": False,
        "native_freecad_qualified": False,
        "distribution_promoted": False,
        "restoration_validated": False,
        "helper_sha256": digest(Path(__file__).resolve()),
        "archive_helper_sha256": digest(Path(archive_tools.__file__).resolve()),
        "reuse_helper_sha256": digest(Path(reuse.__file__).resolve()),
        "status": "retaining",
        "target": "osx-64",
        "source_root": str(source),
        "build_root": str(build),
        "head_sha": args.head_sha,
        "native_macho": identities,
        "runtime_prefix_bytes_bundled": False,
    }
    try:
        inputs = {
            "CMakeCache.txt": cache,
            "TechDrawGui.so": module,
            "bypass-provenance.json": module.parent / "bypass-provenance.json",
            "reuse-validation.json": proof / "validation.json",
            "reuse-recovery.json": proof / "recovery.json",
            **{Path(entry["copy"]).name: Path(entry["copy"]) for entry in bypass["sources"]},
        }
        for name, origin in inputs.items():
            shutil.copyfile(origin, root / name)
            require(digest(origin) == digest(root / name), f"Retained input changed: {name}")
        archive_tools.write_json(root / "source-files.json", tracked)
        receipt["input_sha256"] = {name: digest(root / name) for name in inputs}
        receipt["source_inventory_sha256"] = digest(root / "source-files.json")
        receipt["raw_archive"] = archive_tools.retain_raw_archive(build, root)
        require(
            archive_tools.source_inventory(source, args.head_sha) == tracked,
            "Tracked source changed during retention",
        )
        require(
            archive_tools.checked_bypass(source, build, module, tracked) == bypass,
            "Controlled bypass changed during retention",
        )
        for name, origin in inputs.items():
            require(digest(origin) == receipt["input_sha256"][name], f"Input changed: {name}")
        receipt.update(status="raw-diagnostic-retained", original_source_outputs_unchanged=True)
    except Exception as error:
        receipt.update(status="failed", error=str(error))
        archive_tools.write_json(root / "native-build.json", receipt)
        raise
    archive_tools.write_json(root / "native-build.json", receipt)
    return {"macos_native_build_dir": str(root), "qualified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source-root", "build-root", "proof-dir", "bypass-module", "work-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--head-sha", required=True)
    try:
        result = retain(parser.parse_args())
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"Intel native diagnostic retention failed: {error}\n")
    print(result)


if __name__ == "__main__":
    main()
