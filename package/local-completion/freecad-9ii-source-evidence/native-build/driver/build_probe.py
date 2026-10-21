# SPDX-License-Identifier: LGPL-2.1-or-later
"""Rebuild the experimental 9zt probe without changing an installed solver.

Requires the pinned original source archive and installed conda build-8 recipe.
Both are read-only inputs; all generated material lives in a new work directory.
This is a diagnostic build, not a production installer or a qualified channel.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile


SOURCE_SHA256 = "9c88385c10fb04f5dc6c4e98027a51bebdd8aee3920e05190d6c1dd08357d6e7"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(command, directory, log, environment=None):
    with log.open("w") as stream:
        subprocess.run(
            command,
            cwd=directory,
            env=environment,
            stdout=stream,
            stderr=subprocess.STDOUT,
            check=True,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-archive", type=Path, required=True)
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--patch", type=Path)
    parser.add_argument("--extra-source", type=Path)
    parser.add_argument("--contact-source", type=Path)
    parser.add_argument("--runtime-prefix", type=Path)
    args = parser.parse_args()
    if args.baseline and (args.patch or args.extra_source or args.contact_source):
        parser.error("baseline builds cannot contain a source extension")
    if args.contact_source and (
        not args.extra_source or args.contact_source.name != "contactstate.c"
    ):
        parser.error("contactstate.c requires the declared forceaccounting.c overlay")
    here = Path(__file__).resolve().parent
    recipe = args.recipe.resolve()
    archive = args.source_archive.resolve()
    target = args.workdir.resolve()
    if digest(archive) != SOURCE_SHA256:
        parser.error("source archive SHA256 does not match CalculiX 2.23")
    pins = json.loads((here / "recipe-pins.json").read_text())
    for relative, expected in pins.items():
        if digest(recipe / relative) != expected:
            parser.error(f"recipe input changed: {relative}")
    # Refuse to merge into a previous checkout, even after a failed attempt.
    target.mkdir(parents=False, exist_ok=False)
    for name in ("pixi.toml", "pixi.lock"):
        shutil.copyfile(here / name, target / name)
    with tarfile.open(archive) as source:
        source.extractall(target, filter="data")
    root = target / "CalculiX"
    src = root / "ccx_2.23" / "src"
    recipe_text = (recipe / "recipe.yaml").read_text().split("\nbuild:", 1)[0]
    patches = re.findall(r"(?:- |then: )(patches/[^\s]+\.patch)", recipe_text)
    # The sole Windows-only patch is not part of the installed macOS build.
    patches = [name for name in patches if name != "patches/fix-win-locale.patch"]
    for index, name in enumerate(patches):
        run(
            ["patch", "-p1", "--batch", "--forward", "-i", str(recipe / name)],
            root,
            target / f"recipe-patch-{index:02}.log",
        )
    if not args.baseline:
        selected_patch = (
            args.patch.resolve()
            if args.patch
            else here / "experimental-accounting.patch"
        )
        run(
            [
                "patch",
                "-p1",
                "--batch",
                "--forward",
                "-i",
                str(selected_patch),
            ],
            root,
            target / "accounting-patch.log",
        )
    if args.extra_source:
        if args.extra_source.name != "forceaccounting.c":
            parser.error(
                "only the declared forceaccounting.c source overlay is supported"
            )
        shutil.copyfile(args.extra_source, src / args.extra_source.name)
    if args.contact_source:
        shutil.copyfile(args.contact_source, src / args.contact_source.name)
    manifest = target / "pixi.toml"
    run(
        ["pixi", "install", "--locked", "--manifest-path", str(manifest)],
        target,
        target / "environment.log",
    )
    prefix = target / ".pixi" / "envs" / "default"
    environment = dict(os.environ)
    environment.pop("CCX_9ZT_DIAGNOSTIC", None)
    environment["PKG_VERSION"] = "2.23"
    environment["CFLAGS"] = (
        f"-I{prefix}/include -Wno-error=implicit-function-declaration"
    )
    environment["FFLAGS"] = "-fallow-argument-mismatch"
    runtime_prefix = args.runtime_prefix.resolve() if args.runtime_prefix else prefix
    environment["LDFLAGS"] = f"-L{prefix}/lib -Wl,-rpath,{runtime_prefix}/lib"
    base = ["pixi", "run", "--manifest-path", str(manifest)]
    run(base + ["perl", str(recipe / "date.pl")], src, target / "date.log", environment)
    run(
        base
        + [
            "make",
            "-f",
            str(recipe / "Makefile_MT"),
            "CC=arm64-apple-darwin20.0.0-clang",
            "FC=arm64-apple-darwin20.0.0-gfortran",
            "VERSION=2.23",
            f"SPOOLES_INCLUDE_DIR={prefix}/include/spooles",
            f"LIB_DIR={prefix}/lib",
            "-j6",
        ],
        src,
        target / "build.log",
        environment,
    )
    binary = src / "ccx_2.23_conda"
    if args.runtime_prefix:
        listing = subprocess.check_output(["otool", "-l", str(binary)], text=True)
        paths = re.findall(
            r"cmd LC_RPATH\n\s+cmdsize \d+\n\s+path (.*?) \(offset", listing
        )
        for path in set(paths):
            if path.startswith(str(target)):
                subprocess.run(
                    ["install_name_tool", "-delete_rpath", path, str(binary)],
                    check=True,
                )
        subprocess.run(["codesign", "--force", "--sign", "-", str(binary)], check=True)
    tests = target / "functional-tests"
    tests.mkdir()
    for name in pins:
        if "/" not in name and (
            name.endswith((".inp", ".ref")) or name == "run_test.py"
        ):
            shutil.copyfile(recipe / name, tests / name)
    bin_dir = target / "bin"
    bin_dir.mkdir()
    (bin_dir / "ccx").symlink_to(binary)
    environment["PATH"] = str(bin_dir) + os.pathsep + environment["PATH"]
    run(
        [sys.executable, "run_test.py"],
        tests,
        target / "functional-tests.log",
        environment,
    )
    receipt = {
        "installed": False,
        "channel": (
            subprocess.check_output(
                [str(binary), "--freecad-force-accounting-version"],
                env=environment,
                text=True,
                timeout=10,
            ).strip()
            if args.extra_source
            else "experimental 9zt probe"
        ),
        "baseline": args.baseline,
        "source_sha256": SOURCE_SHA256,
        "recipe_pins_sha256": digest(here / "recipe-pins.json"),
        "probe_patch_sha256": digest(selected_patch) if not args.baseline else None,
        "extra_source_sha256": digest(args.extra_source) if args.extra_source else None,
        "contact_source_sha256": digest(args.contact_source) if args.contact_source else None,
        "toolchain_lock_sha256": digest(here / "pixi.lock"),
        "binary": str(binary),
        "binary_sha256": digest(binary),
        "dependency_functional_tests_passed": True,
        "physical_duty_qualified": False,
    }
    (target / "build-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
