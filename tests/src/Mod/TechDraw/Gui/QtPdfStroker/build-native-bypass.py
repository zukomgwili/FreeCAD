# SPDX-License-Identifier: LGPL-2.1-or-later
"""Relink a scratch TechDrawGui with its two PDF mitigations disabled.

The local qualification helper uses an existing macOS Ninja FreeCAD build. It copies
two sources, compiles them with that build's actual commands and relinks against
all other unchanged objects. It never writes the source tree, build objects or
installed runtime. A separately gated --ci-checkout mode temporarily changes
only the two guards in a disposable GitHub Actions checkout and restores their
source bytes after compilation. Its CI build outputs deliberately change.
The output is suitable only for a disposable test process.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_ci_checkout(args, source, build, output):
    """Build a bypass only in an explicitly disposable GitHub Actions checkout."""
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("CI") != "true":
        raise ValueError("--ci-checkout requires GITHUB_ACTIONS=true and CI=true")
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    temporary = Path(os.environ["RUNNER_TEMP"]).resolve()
    if source != workspace or not output.is_relative_to(temporary):
        raise ValueError("CI source must be GITHUB_WORKSPACE and output must be under RUNNER_TEMP")
    # Keep the guard expressions parsed so their internal helpers remain used under
    # Clang's -Werror,-Wunneeded-internal-declaration. Short-circuiting still
    # bypasses both mitigations, as in the scratch relink mode below.
    substitutions = {
        "QGCustomPath.cpp": (
            "if (brush().style()",
            "if (false && brush().style()",
        ),
        "QGCustomRect.cpp": (
            "if (rect().isNull())",
            "if (false && rect().isNull())",
        ),
    }
    originals = {}
    protected = {}
    entries = []
    for filename, (before, after) in substitutions.items():
        original = source / "src/Mod/TechDraw/Gui" / filename
        data = original.read_bytes()
        text = data.decode()
        if text.count(before) != 1:
            raise ValueError(f"Guard seam changed in {original}")
        originals[original] = data
        protected[str(original)] = digest(original)
        copy = output / filename
        copy.write_bytes(text.replace(before, after).encode())
        entries.append({"source": str(original), "copy": str(copy), "copy_sha256": digest(copy)})
    command = [
        args.cmake,
        "--build",
        str(build),
        "--target",
        "TechDrawGui",
        "--config",
        args.config,
        "--parallel",
        str(args.parallel),
    ]
    try:
        for entry in entries:
            Path(entry["source"]).write_bytes(Path(entry["copy"]).read_bytes())
        subprocess.run(command, check=True)
        candidates = [
            path for path in build.rglob("TechDrawGui.*") if path.suffix in (".so", ".pyd")
        ]
        if args.module:
            compiled_module = args.module.resolve()
            if not compiled_module.is_relative_to(build) or not compiled_module.is_file():
                raise ValueError("--module must identify the compiled module under --build")
        elif len(candidates) == 1:
            compiled_module = candidates[0].resolve()
        else:
            raise ValueError(
                "Specify --module when the build contains multiple TechDrawGui modules"
            )
        module = output / compiled_module.name
        shutil.copy2(compiled_module, module)
    finally:
        for original, data in originals.items():
            original.write_bytes(data)
    if {str(path): digest(path) for path in originals} != protected:
        raise ValueError("CI source restoration did not preserve original bytes")
    provenance = {
        "schema_version": 1,
        "mode": "ci-checkout",
        "purpose": "Disposable CI qualification: both guards bypassed; build outputs changed",
        "module": str(module),
        "module_sha256": digest(module),
        "sources": entries,
        "build_command": command,
        "compiled_module": str(compiled_module),
        "original_build_outputs_unchanged": False,
        "protected_original_sha256": protected,
    }
    (output / "bypass-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print(json.dumps({"module": str(module), "sha256": digest(module), "mode": "ci-checkout"}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ninja", default="ninja")
    parser.add_argument("--ci-checkout", action="store_true")
    parser.add_argument("--cmake", default="cmake")
    parser.add_argument("--config", default="Release")
    parser.add_argument("--parallel", type=int, default=2)
    parser.add_argument("--module", type=Path, help="CI compiled module if discovery is ambiguous")
    args = parser.parse_args()
    source, build, output = (path.resolve() for path in (args.source, args.build, args.output))
    if output.is_relative_to(source) or output.is_relative_to(build):
        parser.error("--output must be outside the original source/build trees")
    output.mkdir(parents=True, exist_ok=False)
    if args.ci_checkout:
        build_ci_checkout(args, source, build, output)
        return
    module = output / "TechDrawGui.so"
    commands = json.loads((build / "compile_commands.json").read_text())
    substitutions = {
        "QGCustomPath.cpp": ("if (brush().style()", "if (false && brush().style()"),
        "QGCustomRect.cpp": ("if (rect().isNull())", "if (false && rect().isNull())"),
    }
    replacements = {}
    protected = {build / "Mod/TechDraw/TechDrawGui.so"}
    entries = []
    for filename, (before, after) in substitutions.items():
        original = source / "src/Mod/TechDraw/Gui" / filename
        matches = [
            command
            for command in commands
            if Path(command["file"]).resolve() == original
            and "CMakeFiles/TechDrawGui.dir/" in command["command"]
        ]
        if len(matches) != 1:
            raise ValueError(f"Expected one TechDrawGui compile command for {filename}")
        command = matches[0]
        original_object = Path(command["output"]).resolve()
        protected.update((original, original_object))
        text = original.read_text()
        if text.count(before) != 1:
            raise ValueError(f"Guard seam changed in {original}")
        copy = output / filename
        copy.write_bytes(text.replace(before, after).encode())
        object_copy = output / (filename + ".o")
        argv = shlex.split(command["command"])
        argv[argv.index("-o") + 1] = str(object_copy)
        argv[argv.index("-c") + 1] = str(copy)
        replacements[str(original_object)] = str(object_copy)
        entries.append({"source": str(original), "copy": str(copy), "compile": argv})
    protected_before = {str(path): digest(path) for path in protected}
    for entry in entries:
        subprocess.run(entry["compile"], cwd=build, check=True)
    result = subprocess.run(
        [args.ninja, "-C", str(build), "-t", "commands", "Mod/TechDraw/TechDrawGui.so"],
        capture_output=True,
        text=True,
        check=True,
    )
    link = result.stdout.splitlines()[-1]
    if not link.startswith(": && ") or not link.endswith(" && :"):
        raise ValueError("Expected the macOS CMake shared-library link command")
    argv = shlex.split(link[5:-5])
    if argv[argv.index("-o") + 1] != "Mod/TechDraw/TechDrawGui.so":
        raise ValueError("Unexpected native module link output")
    argv[argv.index("-o") + 1] = str(module)
    replaced = set()
    unchanged_objects = {}
    for index, argument in enumerate(argv):
        if argument.endswith(".o"):
            original = (build / argument).resolve()
            if str(original) in replacements:
                argv[index] = replacements[str(original)]
                replaced.add(str(original))
            else:
                unchanged_objects[str(original)] = digest(original)
    if replaced != set(replacements):
        raise ValueError("Link command did not contain both replacement objects")
    subprocess.run(argv, cwd=build, check=True)
    protected_after = {str(path): digest(path) for path in protected}
    if protected_after != protected_before:
        raise ValueError("Original source, object or module changed during scratch build")
    provenance = {
        "schema_version": 1,
        "mode": "scratch-relink",
        "purpose": "Qualification only: both QGCustomPath/QGCustomRect guards bypassed",
        "module": str(module),
        "module_sha256": digest(module),
        "sources": [{**entry, "copy_sha256": digest(Path(entry["copy"]))} for entry in entries],
        "link_command": argv,
        "unchanged_objects": unchanged_objects,
        "protected_original_sha256": protected_after,
        "original_build_outputs_unchanged": True,
    }
    (output / "bypass-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print(json.dumps({"module": str(module), "sha256": digest(module)}))


if __name__ == "__main__":
    main()
