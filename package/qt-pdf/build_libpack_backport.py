# SPDX-License-Identifier: LGPL-2.1-or-later AND BSD-3-Clause
"""Prepare/build an isolated Qt-only LibPack candidate; never qualify a runtime.

Use an authenticated, already generated native LibPack baseline. Both SDK copies,
the pinned corresponding sources, build tree and evidence remain in a fresh short
work directory. Only Compiler.build_qt is invoked. Unknown Qt installation paths
fail admission rather than expanding ownership implicitly.
"""

import argparse
from functools import cache
import hashlib
import importlib.util
from importlib.metadata import version
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import subprocess
import sys
import urllib.request

REPO = Path(__file__).resolve().parents[2]
PATCH = REPO / "tests/src/Mod/TechDraw/Gui/QtPdfStroker/empty-outline.patch"
PATCH_SHA = "c8de71a3bf25cc408ba351a3de4dfe63cccf3a857d4bc44589a8fd20188bebe3"
QT_COMMIT = "bfde7b892add48396756dc44a3e3fa03d98c5710"
QTBASE_COMMIT = "59c81a3c2247b821b9b84b4eb8d939b77e07e276"
QPDF_ORIGINAL = "ccd12fea8fc9824d0a3f7a676abace2e27d9eeebdb427c409b1b153ebba4bd30"
QPDF_PATCHED = "e898d324f423d8eb7b288efca815ee0ebc360ad9752635abe963c5becee6a19a"
LICENSE_SHA = "20c17d8b8c48a600800dfd14f95d5cb9ff47066a9641ddeab48dc54aec96e331"
SOURCES = {
    "3.5.3": {
        "commit": "94cda1f16a388b0a70b814d0f8d684301787f4da",
        "compile_all.py": "936bb96c3f061ce5f436c8101bad03840fee1d59f6aaafc730f299312917f4cb",
        "config.json": "6128f565ca295351e6b308524e552c388ead578627884b485b761d6d4602827b",
    },
    "3.5.5": {
        "commit": "6641ccccc9f6dd3541acaf0d5f53a89cde3ecf59",
        "compile_all.py": "f7f59220d72404f104bbdfec63205cb3ce2556d58b93b1a83ccb9d6cfb697a4e",
        "config.json": "1b6425f4a2091d2feb95994e05dba185a65aab1589def5e51994351e9ce51c3e",
    },
}
SELECTED_MODULES = {"qtbase", "qtsvg", "qtdeclarative", "qttools", "qtremoteobjects"}

# The finite namespaces come from pinned CMake target/export definitions retained
# beside this helper. Conditional namespaces also need their actual owner gitlink.
OWNERSHIP = Path(__file__).with_name("libpack-qt-ownership.json")
OWNERSHIP_SHA = "5b4b3d69690d4bee48e385bf83e6681b0456968d1da70ead3e7f1a1a70d68db2"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def baseline_helper():
    return load_module("libpack_baseline_adapter", REPO / "package/qt-pdf/libpack_baseline.py")


def write_json(path, value):
    require(not path.is_symlink(), f"Linked evidence file is forbidden: {path}")
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def safe_relative(value):
    path = PurePosixPath(value)
    require(
        value
        and not path.is_absolute()
        and "\\" not in value
        and ":" not in value
        and all(part not in ("", ".", "..") for part in value.split("/")),
        f"Unsafe relative path: {value}",
    )
    return path


def command(argv, evidence, label, cwd=None, environment=None):
    result = subprocess.run(
        argv, cwd=cwd, env=environment, capture_output=True, text=True, errors="replace"
    )
    (evidence / (label + ".log")).write_text(result.stdout + result.stderr, encoding="utf-8")
    require(result.returncode == 0, f"Command failed; inspect {label}.log")
    # Submodule status uses a leading space as an authenticated clean-state marker.
    return result.stdout.rstrip("\r\n")


def tree_receipt(root, helper):
    return helper.inventory(helper.real_path(root))


def independent_files(root, inventory):
    require(
        all((root / path).stat().st_nlink == 1 for path in inventory["files"]),
        "SDK files must be independent physical copies",
    )


def tool_receipts(environment, protected, helper):
    tools = {}
    for name in ("cmake", "ninja", "git", "7z"):
        selected = shutil.which(name, path=environment["PATH"])
        require(selected is not None, f"Missing build tool: {name}")
        path = helper.real_path(Path(selected))
        require(
            not any(path.is_relative_to(root) for root in protected), "SDK build-tool shadowing"
        )
        tools[name] = {"path": str(path), "sha256": digest(path)}
    return tools


def baseline_input(evidence, sdk, helper):
    evidence = helper.real_path(evidence)
    evidence_inventory = helper.inventory(evidence)
    report = json.loads(helper.real_path(evidence / "generation.json").read_text())
    require(
        report.get("status") == "generated"
        and report.get("baseline_only") is True
        and report.get("sdk_unchanged") is True
        and report.get("archive_sha256_verified") is True
        and report.get("sdk") == sdk
        and report.get("qualified") is False
        and report.get("candidate_sdk") is None,
        "Require the authentic successful baseline generation for this SDK",
    )
    require(
        set(report["evidence_sha256"]) == set(evidence_inventory["files"]) - {"generation.json"}
        and {"sdk-before.json", "sdk-after.json", "qtcoreversion.h"}
        <= set(report["evidence_sha256"]),
        "Baseline evidence inventory is incomplete or contains unexpected files",
    )
    for name, expected in report["evidence_sha256"].items():
        path = helper.real_path(evidence / safe_relative(name))
        require(
            path.is_relative_to(evidence) and digest(path) == expected, "Baseline evidence changed"
        )
    root = helper.real_path(Path(report["sdk_root"]))
    require(root.name == sdk["directory"], "Unexpected released SDK root")
    archive = helper.real_path(root.parent / sdk["filename"])
    require(
        archive.stat().st_size == sdk["size"] and digest(archive) == sdk["sha256"],
        "Baseline release archive differs from its pinned asset",
    )
    before = json.loads((evidence / "sdk-before.json").read_text())
    require(
        before == json.loads((evidence / "sdk-after.json").read_text())
        and helper.inventory(root) == before,
        "Released SDK inventory differs from its untouched baseline",
    )
    require(
        report["host"]["native_machine"] == helper.MACHINES[sdk["architecture"]]
        and report["host"]["python_process_machine"] == 0
        and report["fixture_pe_machine"] == helper.MACHINES[sdk["architecture"]]
        and report["header_sha256"] == before["files"]["include/QtCore/qtcoreversion.h"]["sha256"]
        and digest(evidence / "qtcoreversion.h") == report["header_sha256"]
        and re.search(
            r'#define\s+QTCORE_VERSION_STR\s+"6\.11\.1"', (evidence / "qtcoreversion.h").read_text()
        ),
        "Baseline native architecture/header proof differs",
    )
    runtime = json.loads((evidence / "pdfs/runtime.json").read_text())
    manifest = json.loads((evidence / "pdfs/manifest.json").read_text())
    helper.verify_runtime(
        runtime, manifest, str(root), before, sdk["architecture"], report["modules"]
    )
    require(
        len(manifest["cases"]) == 66
        and {case["device"] for case in manifest["cases"]} == {"qprinter", "qpdfwriter"},
        "Require the complete native baseline PDF fixture receipts",
    )
    return {
        "evidence": str(evidence),
        "root": str(root),
        "archive": str(archive),
        "generation_sha256": digest(evidence / "generation.json"),
        "compiler": report["compiler"],
        "runtime_sha256": digest(evidence / "pdfs/runtime.json"),
        "runtime_origins_verified": True,
    }, before


def verify_sources(directory, release, helper):
    directory = helper.real_path(directory)
    require(
        set(path.name for path in directory.iterdir())
        == {"compile_all.py", "config.json", "LICENSE"},
        "Unexpected pinned LibPack source entry",
    )
    expected = SOURCES[release]
    for name, sha in {**expected, "LICENSE": LICENSE_SHA}.items():
        if name != "commit":
            require(
                digest(helper.real_path(directory / name)) == sha, f"Pinned LibPack {name} differs"
            )
    config = json.loads((directory / "config.json").read_text())
    require(config["LibPack-version"] == release, "Unexpected LibPack configuration version")
    options = [item for item in config["content"] if item.get("name") == "qt"]
    require(
        len(options) == 1
        and options[0]
        == {
            "name": "qt",
            "git-repo": "https://code.qt.io/qt/qt5.git",
            "git-ref": "v6.11.1",
            "fallback-build-dir": "G:\\temp",
        },
        "Upstream Qt configuration differs",
    )
    return config, options[0]


def qt_repositories(source, evidence, git, require_selected=True, environment=None):
    require(
        command([git, "rev-parse", "HEAD"], evidence, "qt-head", source, environment) == QT_COMMIT,
        "Qt superproject commit differs",
    )
    status = command(
        [git, "submodule", "status", "--recursive"], evidence, "qt-submodules", source, environment
    )
    repositories = {".": QT_COMMIT}
    initialized = set()
    for number, line in enumerate(status.splitlines()):
        if line.startswith("-"):
            continue
        require(line.startswith(" ") and len(line.split()) >= 2, "Dirty/ambiguous Qt gitlink")
        sha, relative = line.split()[:2]
        safe_relative(relative)
        require(re.fullmatch(r"[A-Za-z0-9_./-]+", relative), "Unexpected Qt submodule name")
        path = source / relative
        parent = Path(
            command(
                [git, "rev-parse", "--show-toplevel"],
                evidence,
                f"qt-parent-{number}",
                path.parent,
                environment,
            )
        ).resolve()
        require(parent.is_relative_to(source), "Qt submodule parent is outside owned source")
        leaf = path.relative_to(parent).as_posix()
        entry = command(
            [git, "ls-tree", "HEAD", "--", leaf],
            evidence,
            f"qt-gitlink-{number}",
            parent,
            environment,
        ).split()
        require(
            len(entry) == 4 and entry[:2] == ["160000", "commit"] and entry[2] == sha,
            "Initialized Qt gitlink differs from its authenticated parent",
        )
        require(
            command([git, "rev-parse", "HEAD"], evidence, f"qt-module-{number}", path, environment)
            == sha,
            "Qt submodule HEAD differs",
        )
        initialized.add(relative)
        repositories[relative] = sha
    if require_selected:
        require(SELECTED_MODULES <= initialized, "A selected Qt submodule was not initialized")
        require(repositories.get("qtbase") == QTBASE_COMMIT, "QtBase commit differs")
    return repositories


def clean_tracked(source, repositories, evidence, git, patched=False, environment=None):
    for number, relative in enumerate(repositories):
        output = command(
            [git, "diff", "HEAD", "--name-only", "--ignore-submodules=all"],
            evidence,
            f"tracked-diff-{number}",
            source / relative,
            environment,
        )
        expected = "src/gui/painting/qpdf.cpp" if patched and relative == "qtbase" else ""
        require(output == expected, f"Unexpected tracked source edits in {relative}")


def apply_outline(source, patch, evidence, git, environment=None):
    require(digest(patch) == PATCH_SHA, "Retained unified patch differs")
    repositories = qt_repositories(source, evidence, git, environment=environment)
    clean_tracked(source, repositories, evidence, git, environment=environment)
    qpdf = source / "qtbase/src/gui/painting/qpdf.cpp"
    require(digest(qpdf) == QPDF_ORIGINAL, "QPdf source is not the pinned unpatched input")
    command(
        [git, "apply", "--check", "-p1", str(patch)], evidence, "patch-check", source, environment
    )
    command([git, "apply", "-p1", str(patch)], evidence, "patch-apply", source, environment)
    require(digest(qpdf) == QPDF_PATCHED, "Patched QPdf source differs")
    clean_tracked(source, repositories, evidence, git, patched=True, environment=environment)
    return {
        "repositories": repositories,
        "patch_sha256": PATCH_SHA,
        "original_qpdf_sha256": QPDF_ORIGINAL,
        "patched_qpdf_sha256": QPDF_PATCHED,
    }


@cache
def ownership():
    require(
        not OWNERSHIP.is_symlink() and digest(OWNERSHIP) == OWNERSHIP_SHA,
        "Retained finite ownership/source proof differs",
    )
    proof = json.loads(OWNERSHIP.read_text())
    require(
        proof["schema_version"] == 1
        and proof["qualified"] is False
        and proof["qt_superproject_commit"] == QT_COMMIT
        and set(proof["directly_selected_owners"]) == SELECTED_MODULES,
        "Ownership proof identity differs",
    )
    names = {}
    for name, entries in proof["declared_targets"].items():
        owners = {entry["owner"] for entry in entries}
        require(len(owners) == 1, "Ambiguous declared Qt target owner")
        owner = owners.pop()
        canonical = name.removesuffix("Private")
        for alias in (name, canonical, canonical + "Private"):
            require(alias not in names or names[alias] == owner, "Ambiguous Qt interface owner")
            names[alias] = owner
    cmake = {name[3:]: value["owner"] for name, value in proof["observed_cmake_namespaces"].items()}
    for name, owner in names.items():
        for alias in (name, name + "Tools"):
            require(alias not in cmake or cmake[alias] == owner, "Ambiguous Qt CMake export owner")
            cmake[alias] = owner
    plugins, tools = {}, {}
    for kind, destination in (("plugins", plugins), ("tools", tools)):
        for entry in proof[kind] + (proof["output_aliases"] if kind == "tools" else []):
            key = (entry["plugin_type"], entry["stem"]) if kind == "plugins" else entry["stem"]
            require(
                key not in destination or destination[key] == entry["owner"],
                "Ambiguous installed Qt plugin/tool owner",
            )
            destination[key] = entry["owner"]
    return {"proof": proof, "modules": names, "cmake": cmake, "plugins": plugins, "tools": tools}


def qt_owned(relative, initialized=SELECTED_MODULES):
    parts = safe_relative(relative).parts
    owners = ownership()
    literal = owners["proof"]["finite_manifest_paths"].get(relative)
    if literal:
        return literal["owner"] in initialized
    module_names = {name for name, owner in owners["modules"].items() if owner in initialized}
    cmake_names = {name for name, owner in owners["cmake"].items() if owner in initialized}
    if len(parts) >= 3 and parts[0] == "include" and parts[1].startswith("Qt"):
        return parts[1][2:] in module_names
    if len(parts) >= 4 and parts[:2] == ("lib", "cmake") and parts[2].startswith("Qt6"):
        return parts[2][3:] in cmake_names
    if len(parts) >= 2 and parts[0] == "mkspecs":
        return "qtbase" in initialized
    if parts[0] == "qml":
        if len(parts) == 2 and parts[1] in {"builtins.qmltypes", "jsroot.qmltypes"}:
            return "qtdeclarative" in initialized
        qml_owner = {
            "Qt": "qtdeclarative",
            "QML": "qtdeclarative",
            "QmlTime": "qtdeclarative",
            "QtQml": "qtdeclarative",
            "QtQuick": "qtdeclarative",
            "QtTest": "qtdeclarative",
            "QtLabs": "qtdeclarative",
            "QtCore": "qtdeclarative",
            "QtNetwork": "qtdeclarative",
            "QtRemoteObjects": "qtremoteobjects",
        }
        return len(parts) >= 3 and qml_owner.get(parts[1]) in initialized
    name = Path(parts[-1])
    if len(parts) == 2 and parts[0] in {"bin", "lib", "libexec"}:
        if name.stem.startswith("Qt6") and name.suffix in {".dll", ".lib", ".prl", ".pdb"}:
            return name.stem[3:] in module_names
        return owners["tools"].get(name.stem) in initialized and name.suffix in {".exe", ".pdb"}
    if len(parts) == 3 and parts[0] == "plugins":
        return (
            name.suffix in {".dll", ".pdb"}
            and owners["plugins"].get((parts[1], name.stem)) in initialized
        )
    if len(parts) == 3 and parts[:2] == ("lib", "pkgconfig"):
        return (
            name.suffix == ".pc" and name.stem.startswith("Qt6") and name.stem[3:] in module_names
        )
    if len(parts) == 2 and parts[0] == "metatypes":
        return any(
            re.fullmatch(r"qt6" + module.lower() + r"(?:_release)?_metatypes\.json", parts[1])
            for module in module_names
        )
    if len(parts) == 2 and parts[0] == "translations":
        return "qttranslations" in initialized and bool(
            re.fullmatch(
                r"(?:qt|qtbase|qtdeclarative|assistant|designer|linguist|qt_help)_[A-Za-z0-9_]+\.(?:qm|ts)",
                parts[1],
            )
        )
    return False


def install_paths(manifest, candidate, helper, initialized=SELECTED_MODULES, receipt=None):
    manifest = helper.real_path(manifest)
    candidate = helper.real_path(candidate)
    require(manifest.is_file(), "Missing actual Qt install manifest")
    names = set()
    folded, raw_entries, repetitions = {}, {}, {}
    duplicate_paths = dict(ownership()["proof"]["identical_manifest_repetitions"])
    conditional = ownership()["proof"]["conditional_identical_manifest_repetitions"]
    if conditional:
        cache_values = parse_cmake_cache(helper.real_path(manifest.parent / "CMakeCache.txt"))
        for name, contract in conditional.items():
            if (
                contract["owner"] in initialized
                and cache_values.get(contract["cache_key"]) == contract["cache_value"]
            ):
                duplicate_paths[name] = contract["count"]
    for line in manifest.read_text().splitlines():
        require(line and Path(line).is_absolute(), "Nonabsolute install manifest entry")
        path = helper.real_path(Path(line))
        require(
            path.is_relative_to(candidate) and path.is_file(), "Install entry outside candidate"
        )
        relative = path.relative_to(candidate).as_posix()
        require(qt_owned(relative, initialized), f"Unknown/ambiguous Qt ownership: {relative}")
        if relative.casefold() in folded:
            require(
                folded[relative.casefold()] == relative
                and raw_entries[relative] == line
                and duplicate_paths.get(relative) == 2
                and repetitions.get(relative, 1) == 1,
                "Different spelling/case or unreviewed duplicate install entry",
            )
            repetitions[relative] = 2
            continue
        names.add(relative)
        folded[relative.casefold()] = relative
        raw_entries[relative] = line
    require(names, "Qt install manifest is empty")
    if receipt is not None:
        receipt.update(
            schema_version=1,
            qualified=False,
            manifest_sha256=digest(manifest),
            raw_entries=len(manifest.read_text().splitlines()),
            unique_paths=len(names),
            identical_raw_repetitions=repetitions,
            duplicate_entries=sum(count - 1 for count in repetitions.values()),
        )
    return names


def preserved_sdk(before, after, installed, initialized=SELECTED_MODULES, spdx_paths=frozenset()):
    require(
        all(
            name in ownership()["proof"]["spdx_companions"]
            and ownership()["proof"]["spdx_companions"][name]["owner"] in initialized
            for name in spdx_paths
        ),
        "Unknown/uninitialized SPDX companion owner",
    )
    require(set(before["files"]) <= set(after["files"]), "SDK installation removed baseline files")
    changes = {name for name, value in after["files"].items() if before["files"].get(name) != value}
    require(changes <= installed, f"Unadmitted SDK changes: {sorted(changes - installed)[:10]}")
    require(
        all(qt_owned(name, initialized) or name in spdx_paths for name in changes),
        "Non-Qt SDK bytes/metadata changed",
    )
    require(set(before["directories"]) <= set(after["directories"]), "SDK directories removed")
    for directory in set(after["directories"]) - set(before["directories"]):
        require(
            any(name.startswith(directory + "/") for name in installed), "Unknown new SDK directory"
        )
    return sorted(changes)


# The installer fragment below derives from QtInstallHelpers.cmake.
# Copyright (C) 2022 The Qt Company Ltd. SPDX-License-Identifier: BSD-3-Clause.
# Its full notice, conditions and disclaimer are retained in libpack-qt-ownership.json.
def alias_fragment(base, alias):
    """Exact Windows CODE generated by the authenticated Qt install-link factory."""
    source = "${qt_full_install_prefix}/" + base
    destination = "${qt_full_install_prefix}/" + alias
    return "\n".join(
        [
            '  set(qt_full_install_prefix "${CMAKE_INSTALL_PREFIX}")',
            '  if(NOT "$ENV{DESTDIR}" STREQUAL "")',
            '    if(qt_full_install_prefix MATCHES "^[a-zA-Z]:")',
            '        string(SUBSTRING "${qt_full_install_prefix}" 2 -1 qt_full_install_prefix)',
            "    endif()",
            '    string(PREPEND qt_full_install_prefix "$ENV{DESTDIR}")',
            "  endif()",
            f'  message(STATUS "Creating hard link {source} -> {destination}")',
            f'  file(CREATE_LINK "{source}" "{destination}" COPY_ON_ERROR)',
        ]
    )


def companion_aliases(build_root, candidate, source, installed, initialized, helper):
    """Admit source-backed versioned links actually created during this install.

    Qt emits these via install(CODE), so these remain separate from CMake's literal
    install_manifest paths. An unrelated/unlogged changed file remains rejected by
    the complete SDK inventory comparison.
    """
    proof = ownership()["proof"]
    factory = proof["versioned_alias_factory"]
    require(factory["owner"] in initialized, "Qt versioned-link factory owner is not initialized")
    factory_path = helper.real_path(
        source / factory["owner"] / safe_relative(factory["source_path"])
    )
    require(
        digest(factory_path) == factory["source_sha256"], "Versioned-link factory source changed"
    )
    pairs = {
        entry["stem"]: entry
        for entry in proof["output_aliases"]
        if entry["rule"] == "INSTALL_VERSIONED_LINK plus PROJECT_VERSION_MAJOR=6"
    }
    log = helper.real_path(build_root / "build_log.txt")
    log_text = log.read_text(encoding="utf-8", errors="replace")
    scripts = []
    for path in sorted(build_root.rglob("cmake_install.cmake")):
        physical = helper.real_path(path)
        require(physical.is_relative_to(build_root), "Generated install script escaped owned build")
        scripts.append((physical, physical.read_text(encoding="utf-8")))
    entries, names = [], set()
    for line in log_text.splitlines():
        match = re.fullmatch(r"-- Creating hard link (.+) -> (.+)", line)
        if not match:
            continue
        base = helper.real_path(Path(match[1]))
        alias = helper.real_path(Path(match[2]))
        require(
            base.is_relative_to(candidate)
            and alias.is_relative_to(candidate)
            and base.is_file()
            and alias.is_file(),
            "Versioned link is outside owned candidate",
        )
        pair = pairs.get(alias.stem)
        require(
            pair
            and pair["owner"] in initialized
            and base.stem == pair["target"]
            and base.suffix == alias.suffix == ".exe"
            and base.parent == alias.parent,
            "Unknown/uninitialized Qt versioned-tool pair",
        )
        base_name = base.relative_to(candidate).as_posix()
        alias_name = alias.relative_to(candidate).as_posix()
        require(base_name in installed, "Versioned alias base is absent from actual CMake manifest")
        require(qt_owned(alias_name, initialized), "Versioned alias lacks finite source ownership")
        require(alias_name not in names, "Duplicate versioned-tool install receipt")
        names.add(alias_name)
        fragment = alias_fragment(base_name, alias_name)
        occurrences = [(path, text, text.count(fragment)) for path, text in scripts]
        require(
            sum(count for _, _, count in occurrences) == 1,
            "Missing/ambiguous generated versioned-tool install CODE",
        )
        script, script_text, _ = next(entry for entry in occurrences if entry[2])
        base_sha, alias_sha = digest(base), digest(alias)
        require(
            base.stat().st_size == alias.stat().st_size and base_sha == alias_sha,
            "Installed versioned alias bytes differ from its manifest base",
        )
        entries.append(
            {
                "alias": alias_name,
                "manifest_base": base_name,
                "owner": pair["owner"],
                "same_file_identity": base.samefile(alias),
                "sha256": alias_sha,
                "size": alias.stat().st_size,
                "base_nlink": base.stat().st_nlink,
                "alias_nlink": alias.stat().st_nlink,
                "generated_script": script.relative_to(build_root).as_posix(),
                "generated_script_sha256": digest(script),
                "fragment_sha256": hashlib.sha256(fragment.encode()).hexdigest(),
                "fragment_line": script_text[: script_text.index(fragment)].count("\n") + 1,
                "actual_install_log_line": line,
            }
        )
    return names, {
        "schema_version": 1,
        "qualified": False,
        "scope": "Companion Qt install(CODE) evidence; aliases are not claimed as CMake manifest entries",
        "factory_sha256": factory["source_sha256"],
        "ownership_proof_sha256": OWNERSHIP_SHA,
        "actual_install_log_sha256": digest(log),
        "entries": entries,
    }


def finite_installation(build_root, candidate, source, installed, initialized, helper):
    """Bind each extra literal manifest path to its source and actual output."""
    proof = ownership()["proof"]
    bindings, checkout_bindings, entries = {}, {}, []
    checkout = proof["finite_windows_checkout_sources"]
    attributes = checkout["attributes"]
    attribute = helper.real_path(source / safe_relative(attributes["source_path"]))
    require(
        attribute.is_relative_to(source)
        and attributes["owner"] in initialized
        and digest(attribute) == attributes["sha256"]
        and attribute.stat().st_size == attributes["size"],
        "Finite Qt checkout attributes changed",
    )
    for key, windows in checkout["files"].items():
        bound = proof["finite_install_sources"][key]
        path = helper.real_path(source / safe_relative(key))
        require(
            bound["owner"] in initialized
            and windows["git_sha256"] == bound["sha256"]
            and windows["git_blob_sha1"] == bound["git_blob_sha1"],
            "Finite checkout/Git source identity differs",
        )
        require(
            path.is_relative_to(source)
            and path.stat().st_size == windows["checkout_size"]
            and digest(path) == windows["checkout_sha256"],
            f"Literal Qt checkout source changed: {key}",
        )
        checkout_bindings[key] = {
            "sha256": windows["checkout_sha256"],
            "size": windows["checkout_size"],
        }
    cache_values = parse_cmake_cache(helper.real_path(build_root / "CMakeCache.txt"))
    require(
        cache_values.get("INSTALL_BINDIR") == cache_values.get("INSTALL_LIBEXECDIR") == "bin"
        and cache_values.get("INSTALL_DESCRIPTIONSDIR") == "modules",
        "Finite Windows install-directory contract differs",
    )
    for name in sorted(installed & set(proof["finite_manifest_paths"])):
        contract = proof["finite_manifest_paths"][name]
        require(contract["owner"] in initialized, "Literal Qt output owner is not initialized")
        for key in contract["bindings"]:
            if key in bindings:
                continue
            bound = proof["finite_install_sources"][key]
            require(bound["owner"] in initialized, "Literal Qt factory owner is not initialized")
            path = helper.real_path(source / safe_relative(key))
            expected_sha = (
                checkout_bindings[key]["sha256"] if key in checkout_bindings else bound["sha256"]
            )
            require(
                path.is_relative_to(source) and digest(path) == expected_sha,
                f"Literal Qt source changed: {key}",
            )
            bindings[key] = bound["sha256"]
        output = helper.real_path(candidate / safe_relative(name))
        kind = contract["kind"]
        if "copy_source" in contract:
            original = helper.real_path(source / contract["owner"] / contract["copy_source"])
            require(output.read_bytes() == original.read_bytes(), "Static Qt output bytes differ")
        elif kind == "wrapper":
            values = dict(contract["configured_values"])
            if "CMAKE_COMMAND" in values:
                values["CMAKE_COMMAND"] = cache_values["CMAKE_COMMAND"]
            if "__qt_cmake_extra" in values and values["__qt_cmake_extra"]:
                values["__qt_cmake_extra"] = (
                    f'-G"{cache_values["CMAKE_GENERATOR"]}" -DQT_USE_ORIGINAL_COMPILER=ON'
                )
            if "__qt_configured_configs" in values:
                values["__qt_configured_configs"] = cache_values["CMAKE_BUILD_TYPE"]
            template = helper.real_path(source / "qtbase" / contract["template"]).read_text()
            require(
                set(re.findall(r"@([A-Za-z0-9_]+)@", template)) <= set(values),
                "Unknown Qt wrapper template substitution",
            )
            expected = re.sub(r"@([A-Za-z0-9_]+)@", lambda match: values[match[1]], template)
            require(
                output.read_bytes() == expected.replace("\n", "\r\n").encode(),
                "Generated Qt wrapper bytes differ from pinned template/cache",
            )
        elif kind == "module_description":
            require(
                contract["target"] in proof["declared_targets"]
                and all(
                    entry["owner"] == contract["owner"]
                    for entry in proof["declared_targets"][contract["target"]]
                ),
                "Module description is not an exact declared target",
            )
            generated = helper.real_path(build_root / "qtbase/modules" / output.name)
            require(
                output.read_bytes() == generated.read_bytes(), "Module JSON install bytes differ"
            )
            data = json.loads(output.read_text())
            require(
                data.get("schema_version") == 3
                and data.get("name") == contract["target"]
                and data.get("repository") == contract["owner"]
                and data.get("version") == "6.11.1",
                "Module JSON schema/name/owner/version differs",
            )
        elif kind == "activeqt_header":
            generated = helper.real_path(build_root / contract["generated_path"])
            require(
                output.read_bytes() == generated.read_bytes(), "ActiveQt generated bytes differ"
            )
        elif kind == "resource_object":
            initializer = helper.real_path(build_root / contract["initializer"])
            template = helper.real_path(source / "qtbase/src/corelib/Qt6CoreResourceInit.in.cpp")
            require(
                initializer.read_text()
                == template.read_text().replace("@RESOURCE_NAME@", contract["resource_name"]),
                "Resource initializer differs from pinned name/template",
            )
        else:
            require(False, "Unknown literal Qt install contract")
        entries.append(
            {
                "path": name,
                "owner": contract["owner"],
                "kind": kind,
                "sha256": digest(output),
                "size": output.stat().st_size,
            }
        )
    return {
        "schema_version": 1,
        "qualified": False,
        "ownership_proof_sha256": OWNERSHIP_SHA,
        "source_bindings": bindings,
        "source_checkout_bindings": checkout_bindings,
        "checkout_attribute_sha256": attributes["sha256"],
        "entries": entries,
    }


def spdx_install_fragment(factory, build_root, owner):
    """Expand the pinned SPDX install(CODE) factory without executing CMake."""
    # Copyright (C) 2025 The Qt Company Ltd. SPDX-License-Identifier: BSD-3-Clause.
    # The full notice/conditions/disclaimer are retained in the ownership proof.
    body = re.search(
        r'    set\(assemble_sbom_install "(.*?)"\)\n\n    install\(CODE', factory, re.S
    )
    require(body is not None, "Pinned SPDX install factory body is missing")
    base = (build_root / owner / "qt_sbom").as_posix()
    name = f"sbom/{owner}-6.11.1"
    values = {
        "suffix": "_spdx",
        "arg_EXTRA_CODE_BEGIN": "",
        "arg_EXTRA_CODE_INNER_END": "",
        "arg_SBOM_INSTALL_OUTPUT_DIR": "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/sbom",
        "arg_SBOM_INSTALL_OUTPUT_PATH": "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/" + name + ".spdx",
        "arg_SBOM_INSTALL_OUTPUT_PATH_WITHOUT_EXT": "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/" + name,
        "arg_ASSEMBLE_SBOM_INCLUDE_PATH": base + "/assemble_sbom.cmake",
        "arg_BEFORE_CHECKSUM_INCLUDES": "",
        "arg_AFTER_CHECKSUM_INCLUDES": "",
        "process_verification_codes": f'\n            include("{base}/process_verification_codes.cmake")\n',
        "final_message": "Finalizing SBOM generation in install dir",
        "staging_area_file": base + f"/staging-{owner}.spdx.in",
        "arg_POST_GENERATION_INCLUDES": "",
        "arg_VERIFY_INCLUDES": "",
    }
    require(
        set(re.findall(r"(?<!\\)\$\{([A-Za-z_]+)\}", body[1])) <= set(values),
        "Unknown SPDX install factory substitution",
    )
    expanded = re.sub(r"(?<!\\)\$\{([A-Za-z_]+)\}", lambda match: values[match[1]], body[1])
    return expanded.replace('\\"', '"').replace("\\$", "$").strip("\n")


def spdx_staging_matches(staging, installed):
    """Require every literal staging byte, with only Qt's three finite substitutions."""
    pattern, position = [], 0
    for match in re.finditer(r"\$\{([^}]+)\}", staging):
        pattern.append(re.escape(staging[position : match.start()]))
        variable = match[1]
        if variable == "QT_SBOM_EXTERNAL_DOC_REFS":
            pattern.append(r"(?:\nExternalDocumentRef: [^\r\n]+ SHA1: [0-9a-f]{40})*")
        elif variable.startswith("QT_SBOM_VERIFICATION_CODE_SPDXRef-"):
            pattern.append(r"(?:\nPackageVerificationCode: [0-9a-f]{40})?")
        elif variable.startswith("QT_SBOM_PACKAGE_HAS_FILES_SPDXRef-"):
            pattern.append(r"(?:true|false)")
        else:
            require(False, "Unknown SPDX staging substitution")
        position = match.end()
    pattern.append(re.escape(staging[position:]))
    require(
        re.fullmatch("".join(pattern), installed) is not None, "Installed SPDX staging bytes differ"
    )


def companion_spdx(build_root, candidate, source, initialized, helper):
    """Admit only the nine source/version-bound SPDX install(CODE) companions."""
    proof = ownership()["proof"]
    source_bindings = {}
    for key in proof["spdx_factory_sources"]:
        bound = proof["finite_install_sources"][key]
        require(bound["owner"] in initialized, "SPDX factory owner is not initialized")
        path = helper.real_path(source / safe_relative(key))
        require(
            path.is_relative_to(source) and digest(path) == bound["sha256"],
            "SPDX factory source changed",
        )
        source_bindings[key] = bound["sha256"]
    cache_values = parse_cmake_cache(helper.real_path(build_root / "CMakeCache.txt"))
    require(
        cache_values.get("CMAKE_PROJECT_VERSION") == "6.11.1"
        and cache_values.get("INSTALL_SBOMDIR") == "sbom"
        and cache_values.get("QT_GENERATE_SBOM")
        == cache_values.get("QT_SBOM_GENERATE_SPDX_V2")
        == "ON",
        "SPDX source/version/feature/directory contract differs",
    )
    factory = (source / "qtbase/cmake/QtPublicSbomCommonGenerationHelpers.cmake").read_text()
    log = helper.real_path(build_root / "build_log.txt")
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    entries, names = [], set()
    for name, contract in sorted(proof["spdx_companions"].items()):
        output = candidate / safe_relative(name)
        owner = contract["owner"]
        if owner not in initialized and not output.exists():
            continue
        require(owner in initialized, "SPDX companion owner is not initialized")
        output = helper.real_path(output)
        require(
            output.is_relative_to(candidate) and output.is_file(),
            "SPDX companion outside candidate",
        )
        script = helper.real_path(build_root / owner / "cmake_install.cmake")
        text = script.read_text()
        fragment = spdx_install_fragment(factory, build_root, owner)
        require(
            text.count(fragment) == 2
            and text.count(
                'if(CMAKE_INSTALL_COMPONENT STREQUAL "sbom" OR NOT CMAKE_INSTALL_COMPONENT)'
            )
            == 1
            and text.count(f'if(CMAKE_INSTALL_COMPONENT STREQUAL "sbom_{owner}")') == 1,
            "Missing/ambiguous generated SPDX install CODE",
        )
        staging = helper.real_path(build_root / owner / "qt_sbom" / f"staging-{owner}.spdx.in")
        assemble = helper.real_path(build_root / owner / "qt_sbom/assemble_sbom.cmake")
        start = f"-- Starting SPDX SBOM generation in build dir: {staging.as_posix()}"
        final = f"-- Finalizing SBOM generation in install dir: {output.as_posix()}"
        require(
            lines.count(start) == lines.count(final) == 1
            and lines.index(start) < lines.index(final),
            "Missing/ambiguous/out-of-order SPDX install log",
        )
        installed = output.read_text()
        spdx_staging_matches(staging.read_text(), installed)
        expected = {
            "SPDXVersion": "SPDX-2.3",
            "DataLicense": "CC0-1.0",
            "DocumentName": owner + "-6.11.1",
            "PackageName": owner,
            "PackageVersion": "6.11.1",
            "PackageDownloadLocation": f'git://code.qt.io/qt/{owner}.git@{contract["repository_commit"]}',
        }
        fields = {}
        for key, value in expected.items():
            match = re.search(r"^" + key + r": ([^\r\n]*)$", installed, re.M)
            require(
                match is not None and match[1] == value, "SPDX root/source/version field differs"
            )
            fields[key] = match[1]
        names.add(name)
        entries.append(
            {
                "path": name,
                "owner": owner,
                "sha256": digest(output),
                "size": output.stat().st_size,
                "installed_root_fields": fields,
                "generated_script_sha256": digest(script),
                "generated_script": script.relative_to(build_root).as_posix(),
                "fragment_sha256": hashlib.sha256(fragment.encode()).hexdigest(),
                "fragment_occurrences": 2,
                "assemble_sha256": digest(assemble),
                "staging_sha256": digest(staging),
                "staging_substitutions_verified": True,
                "start_log_line": lines.index(start) + 1,
                "final_log_line": lines.index(final) + 1,
                "start_log_text": start,
                "final_log_text": final,
            }
        )
    return names, {
        "schema_version": 1,
        "qualified": False,
        "scope": "Finite generated SPDX companions; not CMake manifest entries or license qualification",
        "ownership_proof_sha256": OWNERSHIP_SHA,
        "build_root": build_root.as_posix(),
        "candidate_root": candidate.as_posix(),
        "source_bindings": source_bindings,
        "actual_install_log_sha256": digest(log),
        "entries": entries,
    }


def validate_spdx_receipt(receipt, inventory, initialized, evidence_dir=None):
    """Check finite receipts, optionally their portable source/build/installed proof.

    A portable proof directory contains source/<repository>/<path>,
    build/<owner>/cmake_install.cmake, build/<owner>/qt_sbom/{assemble_sbom.cmake,
    staging-<owner>.spdx.in}, build/build_log.txt and installed/sbom/<filename>.
    Inspection can verify original Windows path substitutions on another OS.
    """
    proof = ownership()["proof"]
    expected_sources = {
        key: proof["finite_install_sources"][key]["sha256"] for key in proof["spdx_factory_sources"]
    }
    require(
        receipt.get("schema_version") == 1
        and receipt.get("qualified") is False
        and receipt.get("ownership_proof_sha256") == OWNERSHIP_SHA
        and receipt.get("source_bindings") == expected_sources,
        "SPDX receipt identity/source binding differs",
    )
    if isinstance(initialized, dict):
        require(
            all(
                initialized[owner] == sha
                for owner, sha in proof["owner_repository_gitlinks"].items()
                if owner in initialized
            ),
            "SPDX initialized owner gitlink differs",
        )
    expected_names = {
        name
        for name, contract in proof["spdx_companions"].items()
        if contract["owner"] in initialized
    }
    entries = receipt["entries"]
    names = {entry["path"] for entry in entries}
    require(
        names == expected_names and len(entries) == len(names),
        "SPDX receipt finite path set differs",
    )
    build_name, candidate_name = receipt["build_root"], receipt["candidate_root"]
    path_type = PureWindowsPath if re.match(r"^[A-Za-z]:/", build_name) else PurePosixPath
    build_root, candidate = path_type(build_name), path_type(candidate_name)
    require(
        build_root.is_absolute() and candidate.is_absolute(), "SPDX receipt roots are not absolute"
    )
    require(
        re.fullmatch(r"[0-9a-f]{64}", receipt["actual_install_log_sha256"]) is not None,
        "SPDX log digest differs",
    )

    def physical(relative):
        root = Path(evidence_dir).resolve()
        path = root / safe_relative(relative)
        require(
            path.is_file() and path.resolve().is_relative_to(root) and not path.is_symlink(),
            "SPDX portable proof file is missing/linked",
        )
        require(
            all(not (root / parent).is_symlink() for parent in path.relative_to(root).parents),
            "SPDX portable proof parent is linked",
        )
        return path

    factory, log_lines = None, None
    if evidence_dir is not None:
        for key, sha in expected_sources.items():
            require(digest(physical("source/" + key)) == sha, "SPDX portable factory bytes differ")
        factory = physical(
            "source/qtbase/cmake/QtPublicSbomCommonGenerationHelpers.cmake"
        ).read_text()
        log = physical("build/build_log.txt")
        require(
            digest(log) == receipt["actual_install_log_sha256"], "SPDX portable log bytes differ"
        )
        log_lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    for entry in entries:
        name = entry["path"]
        contract = proof["spdx_companions"][name]
        owner = contract["owner"]
        fields = {
            "SPDXVersion": "SPDX-2.3",
            "DataLicense": "CC0-1.0",
            "DocumentName": owner + "-6.11.1",
            "PackageName": owner,
            "PackageVersion": "6.11.1",
            "PackageDownloadLocation": f'git://code.qt.io/qt/{owner}.git@{contract["repository_commit"]}',
        }
        staging_name = f"{owner}/qt_sbom/staging-{owner}.spdx.in"
        expected_start = (
            "-- Starting SPDX SBOM generation in build dir: "
            + (build_root / staging_name).as_posix()
        )
        expected_final = (
            "-- Finalizing SBOM generation in install dir: " + (candidate / name).as_posix()
        )
        require(
            entry["owner"] == owner
            and entry["installed_root_fields"] == fields
            and entry["generated_script"] == f"{owner}/cmake_install.cmake"
            and entry["fragment_occurrences"] == 2
            and entry["staging_substitutions_verified"] is True
            and isinstance(entry["start_log_line"], int)
            and isinstance(entry["final_log_line"], int)
            and 0 < entry["start_log_line"] < entry["final_log_line"]
            and entry["start_log_text"] == expected_start
            and entry["final_log_text"] == expected_final
            and {key: inventory["files"][name][key] for key in ("sha256", "size")}
            == {key: entry[key] for key in ("sha256", "size")},
            "SPDX finite owner/version/path/generation/log/inventory receipt differs",
        )
        for key in (
            "sha256",
            "generated_script_sha256",
            "fragment_sha256",
            "assemble_sha256",
            "staging_sha256",
        ):
            require(
                re.fullmatch(r"[0-9a-f]{64}", entry[key]) is not None, "SPDX proof digest differs"
            )
        if evidence_dir is None:
            continue
        script = physical("build/" + entry["generated_script"])
        staging = physical("build/" + staging_name)
        assemble = physical(f"build/{owner}/qt_sbom/assemble_sbom.cmake")
        output = physical("installed/" + name)
        require(
            digest(script) == entry["generated_script_sha256"]
            and digest(staging) == entry["staging_sha256"]
            and digest(assemble) == entry["assemble_sha256"]
            and digest(output) == entry["sha256"]
            and output.stat().st_size == entry["size"],
            "SPDX portable generation/installed bytes differ",
        )
        fragment = spdx_install_fragment(factory, build_root, owner)
        text = script.read_text()
        require(
            hashlib.sha256(fragment.encode()).hexdigest() == entry["fragment_sha256"]
            and text.count(fragment) == 2
            and text.count(
                'if(CMAKE_INSTALL_COMPONENT STREQUAL "sbom" OR NOT CMAKE_INSTALL_COMPONENT)'
            )
            == 1
            and text.count(f'if(CMAKE_INSTALL_COMPONENT STREQUAL "sbom_{owner}")') == 1,
            "SPDX portable install CODE differs",
        )
        require(
            log_lines.count(expected_start) == log_lines.count(expected_final) == 1
            and log_lines[entry["start_log_line"] - 1] == expected_start
            and log_lines[entry["final_log_line"] - 1] == expected_final,
            "SPDX portable install log differs",
        )
        spdx_staging_matches(staging.read_text(), output.read_text())
        for key, value in fields.items():
            match = re.search(r"^" + key + r": ([^\r\n]*)$", output.read_text(), re.M)
            require(match is not None and match[1] == value, "SPDX portable root field differs")
    return names


def admit_installation(build_root, candidate, source, before, repositories, helper):
    """Recheck installation evidence after build or authenticated physical recovery."""
    initialized = set(repositories)
    proof = ownership()["proof"]
    require(
        SELECTED_MODULES <= initialized
        and all(
            repositories[owner] == sha
            for owner, sha in proof["owner_repository_gitlinks"].items()
            if owner in initialized
        ),
        "Initialized ownership source gitlink differs",
    )
    manifest = build_root / "install_manifest.txt"
    manifest_receipt = {}
    installed = install_paths(manifest, candidate, helper, initialized, manifest_receipt)
    literal_receipt = finite_installation(
        build_root, candidate, source, installed, initialized, helper
    )
    aliases, alias_receipt = companion_aliases(
        build_root, candidate, source, installed, initialized, helper
    )
    spdx, spdx_receipt = companion_spdx(build_root, candidate, source, initialized, helper)
    require(not (spdx & installed), "SPDX companions must remain outside the ordinary manifest")
    after = helper.inventory(candidate)
    require(
        validate_spdx_receipt(spdx_receipt, after, repositories) == spdx, "SPDX admission differs"
    )
    changes = preserved_sdk(before, after, installed | aliases | spdx, initialized, spdx)
    return {
        "qt_install_manifest_sha256": digest(manifest),
        "qt_install_manifest_receipt": manifest_receipt,
        "qt_finite_install_receipt": literal_receipt,
        "admitted_qt_paths": sorted(installed),
        "admitted_companion_alias_paths": sorted(aliases - installed),
        "qt_companion_alias_receipt": alias_receipt,
        "admitted_companion_spdx_paths": sorted(spdx),
        "qt_companion_spdx_receipt": spdx_receipt,
        "changed_qt_paths": changes,
        "ownership_proof_sha256": OWNERSHIP_SHA,
        "non_qt_preserved": True,
    }, after


def compiler_adapter(
    upstream, source, build_root, patch, evidence, git, result, verify_config=None
):
    """Intercept only the post-configure build seam of the authenticated compiler."""

    class QtOnlyCompiler(upstream.Compiler):
        hook_calls = 0

        def _cmake_build(self, parallel=True):
            require(
                self.hook_calls == 0 and Path.cwd().resolve() == build_root,
                "Unexpected/repeated post-configure hook",
            )
            self.hook_calls += 1
            if verify_config:
                result["configure"] = verify_config()
            result["source"] = apply_outline(source, patch, evidence, git)
            return super()._cmake_build(parallel=parallel)

    return QtOnlyCompiler


def separate_path(path, protected):
    require(
        not path.is_relative_to(protected) and not protected.is_relative_to(path),
        "Owned work overlaps a protected baseline/evidence path",
    )


def source_environment(environment):
    # Scope the checkout policy to this process and its Qt init-submodule children.
    # Reject inherited Git redirection rather than allowing it to select other trees.
    require(
        not any(name.startswith("GIT_") for name in environment),
        "Use a tool environment without inherited Git overrides",
    )
    return {
        **environment,
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.autocrlf",
        "GIT_CONFIG_VALUE_0": "false",
    }


def native_environment(environment, compiler, helper):
    # Match upstream create_libpack.py: vcvars must be able to find vswhere when
    # its original initialization command is invoked again for configure/build.
    require(
        not environment.get("DESTDIR") and not environment.get("CMAKE_INSTALL_MODE"),
        "Use the standard owned-prefix installation without destination/mode overrides",
    )
    vswhere = helper.real_path(Path(compiler["vswhere"]["argv"][0]))
    paths = environment["PATH"].split(os.pathsep)
    if str(vswhere.parent) not in paths:
        environment = {
            **environment,
            "PATH": str(vswhere.parent) + os.pathsep + environment["PATH"],
        }
    return source_environment(environment)


def parse_cmake_cache(path):
    """Read complete CMake cache keys, including quoted names containing colons."""
    values = {}
    for line in path.read_text().splitlines():
        line = line.lstrip()
        if not line or line.startswith(("#", "//")):
            continue
        # CMake's cache writer quotes keys such as ICU::data. The type
        # separator follows the closing quote rather than the first colon.
        match = re.fullmatch(r'(?:"([^"]+)"|([^":=]+)):([^=]+)=(.*)', line)
        require(match is not None, "Malformed CMake cache entry")
        key = match[1] if match[1] is not None else match[2]
        require(key not in values, "Duplicate CMake cache key")
        values[key] = match[4]
    return values


def configured_cache(build_root, candidate, compiler, helper):
    cache = helper.real_path(build_root / "CMakeCache.txt")
    values = parse_cmake_cache(cache)
    require(values.get("CMAKE_BUILD_TYPE") == "Release", "Upstream Qt release mode changed")
    require(
        helper.real_path(Path(values["CMAKE_INSTALL_PREFIX"])) == candidate,
        "Configured installation prefix differs from owned candidate",
    )
    for name in ("CMAKE_C_COMPILER", "CMAKE_CXX_COMPILER"):
        selected = helper.real_path(Path(values[name]))
        require(
            selected == helper.real_path(Path(compiler["compiler"]))
            and digest(selected) == compiler["compiler_sha256"],
            "Configured compiler differs from actual baseline MSVC",
        )
    require(
        all(
            values.get(name) == "ON"
            for name in ("QT_FEATURE_opengl", "QT_FEATURE_opengl_desktop", "QT_FEATURE_zstd")
        ),
        "Pinned upstream OpenGL/zstd feature inputs changed",
    )
    require(
        helper.real_path(Path(values["zstd_DIR"])) == candidate / "lib/cmake/zstd",
        "Configured zstd directory is outside candidate",
    )
    return {
        "cache_sha256": digest(cache),
        "validated_cache_inputs": {
            name: values[name]
            for name in (
                "CMAKE_BUILD_TYPE",
                "CMAKE_INSTALL_PREFIX",
                "CMAKE_C_COMPILER",
                "CMAKE_CXX_COMPILER",
                "QT_FEATURE_opengl",
                "QT_FEATURE_opengl_desktop",
                "QT_FEATURE_zstd",
                "zstd_DIR",
            )
        },
    }


def prepared_paths(work, sdk, helper):
    expected = {
        "evidence",
        "baseline",
        "candidate",
        "libpack",
        "qt",
        "compiler.cmd",
        sdk["filename"],
        "empty-outline.patch",
        "libpack-qt-ownership.json",
    }
    require(set(path.name for path in work.iterdir()) == expected, "Unexpected prepared work entry")
    for name in expected:
        helper.real_path(work / name)


def prepare(args, helper):
    helper.real_path(OWNERSHIP)
    ownership.cache_clear()
    ownership()
    sdk = helper.sdk_identity(args.sdk)
    host = helper.native_machine()
    require(
        host["native_machine"] == helper.MACHINES[sdk["architecture"]]
        and host["python_process_machine"] == 0,
        "Require matching native Windows/Python",
    )
    original, before = baseline_input(args.baseline_evidence_dir, sdk, helper)
    independent_files(Path(original["root"]), before)
    work = helper.real_path(args.work_dir)
    require(
        len(str(work)) <= 12 and not any(c in str(work) for c in '\r\n"%&|<>^'),
        "Use a safe fresh short Windows work root (at most 12 characters)",
    )
    for protected in (Path(original["root"]), Path(original["evidence"])):
        separate_path(work, protected)
    work = helper.fresh_work(work)
    evidence = work / "evidence"
    evidence.mkdir()
    environment, compiler = helper.compiler_environment(work, evidence, sdk["architecture"])
    require(
        compiler["compiler_sha256"] == original["compiler"]["compiler_sha256"]
        and compiler["tools_version"] == original["compiler"]["tools_version"],
        "Compiler differs from actual baseline generation",
    )
    require(
        helper.pe_machine(Path(compiler["compiler"])) == helper.MACHINES[sdk["architecture"]],
        "Compiler process architecture is not native",
    )
    environment = native_environment(environment, compiler, helper)
    tools = tool_receipts(environment, [Path(original["root"])], helper)
    require(
        not any(
            f"bin/{name}.exe".casefold() in {path.casefold() for path in before["files"]}
            for name in ("cmake", "ninja", "git", "7z", "cl")
        ),
        "SDK runtime directory would shadow compiler/build tools",
    )
    archive = work / sdk["filename"]
    shutil.copy2(original["archive"], archive)
    require(digest(archive) == sdk["sha256"], "Copied release archive differs")
    for name in ("baseline", "candidate"):
        shutil.copytree(original["root"], work / name, copy_function=shutil.copy2)
        require(helper.inventory(work / name) == before, "Physical SDK copy differs")
        independent_files(work / name, before)
    sources = work / "libpack"
    sources.mkdir()
    source_pin = SOURCES[sdk["release"]]
    for name, sha in {**source_pin, "LICENSE": LICENSE_SHA}.items():
        if name == "commit":
            continue
        url = f"https://raw.githubusercontent.com/FreeCAD/FreeCAD-LibPack/{source_pin['commit']}/{name}"
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read(120000)
        require(hashlib.sha256(data).hexdigest() == sha, f"Downloaded source differs: {name}")
        (sources / name).write_bytes(data)
    verify_sources(sources, sdk["release"], helper)
    require(digest(PATCH) == PATCH_SHA, "Retained repository patch differs")
    shutil.copy2(PATCH, work / "empty-outline.patch")
    shutil.copy2(OWNERSHIP, work / "libpack-qt-ownership.json")
    git = tools["git"]["path"]
    command(
        [
            git,
            "-c",
            "core.autocrlf=false",
            "clone",
            "--branch",
            "v6.11.1",
            "--depth",
            "1",
            "https://code.qt.io/qt/qt5.git",
            str(work / "qt"),
        ],
        evidence,
        "qt-clone",
        environment=environment,
    )
    require(
        command([git, "rev-parse", "HEAD"], evidence, "qt-initial-head", work / "qt", environment)
        == QT_COMMIT,
        "Cloned Qt superproject differs",
    )
    command(
        [git, "config", "--local", "core.autocrlf", "false"],
        evidence,
        "qt-line-endings",
        work / "qt",
        environment,
    )
    repositories = qt_repositories(
        work / "qt", evidence, git, require_selected=False, environment=environment
    )
    require(repositories == {".": QT_COMMIT}, "Unexpected initially initialized Qt module")
    clean_tracked(work / "qt", repositories, evidence, git, environment=environment)
    require(helper.inventory(Path(original["root"])) == before, "Original baseline changed")
    write_json(evidence / "sdk-before.json", before)
    write_json(evidence / "qt-before.json", tree_receipt(work / "qt", helper))
    report = {
        "schema_version": 1,
        "status": "prepared",
        "qualified": False,
        "sdk": sdk,
        "host": host,
        "original_baseline": original,
        "compiler": compiler,
        "work": str(work),
        "helper_sha256": digest(Path(__file__)),
        "baseline_helper_sha256": digest(Path(helper.__file__)),
        "tools": tools,
        "sdk_inventory_sha256": digest(evidence / "sdk-before.json"),
        "qt_inventory_sha256": digest(evidence / "qt-before.json"),
        "source_pin": source_pin,
        "patch_sha256": PATCH_SHA,
        "qt_commit": QT_COMMIT,
        "ownership_proof_sha256": OWNERSHIP_SHA,
    }
    report["preparation_files"] = {
        name: value["sha256"] for name, value in tree_receipt(evidence, helper)["files"].items()
    }
    write_json(evidence / "preparation.json", report)
    return report


def build(args, helper):
    work = helper.real_path(args.work_dir)
    evidence = helper.real_path(work / "evidence")
    evidence_inventory = tree_receipt(evidence, helper)
    report = json.loads((evidence / "preparation.json").read_text())
    require(
        report["status"] == "prepared"
        and report["work"] == str(work)
        and report["helper_sha256"] == digest(Path(__file__))
        and report["baseline_helper_sha256"] == digest(Path(helper.__file__)),
        "Preparation/helper changed",
    )
    require(
        set(evidence_inventory["files"]) == set(report["preparation_files"]) | {"preparation.json"},
        "Build is single-use; preparation evidence differs",
    )
    require(
        all(
            evidence_inventory["files"][name]["sha256"] == sha
            for name, sha in report["preparation_files"].items()
        ),
        "Preparation evidence changed",
    )
    sdk = helper.sdk_identity(report["sdk"]["key"])
    require(
        sdk == report["sdk"]
        and report["source_pin"] == SOURCES[sdk["release"]]
        and report["patch_sha256"] == PATCH_SHA
        and report["qt_commit"] == QT_COMMIT,
        "Preparation pins differ",
    )
    prepared_paths(work, sdk, helper)
    helper.real_path(OWNERSHIP)
    ownership.cache_clear()
    ownership()
    require(
        report["ownership_proof_sha256"] == OWNERSHIP_SHA
        and digest(work / "libpack-qt-ownership.json") == OWNERSHIP_SHA,
        "Owned finite ownership/source proof changed",
    )
    original, before = baseline_input(Path(report["original_baseline"]["evidence"]), sdk, helper)
    require(
        original == report["original_baseline"]
        and helper.inventory(work / "baseline") == before
        and helper.inventory(work / "candidate") == before,
        "Baseline/candidate preparation changed",
    )
    for root in (work / "baseline", work / "candidate", Path(original["root"])):
        independent_files(root, before)
    require(
        digest(evidence / "sdk-before.json") == report["sdk_inventory_sha256"], "Inventory changed"
    )
    require(digest(work / sdk["filename"]) == sdk["sha256"], "Retained SDK archive changed")
    require(
        digest(evidence / "qt-before.json") == report["qt_inventory_sha256"]
        and tree_receipt(work / "qt", helper)
        == json.loads((evidence / "qt-before.json").read_text()),
        "Prepared Qt source tree changed",
    )
    config, options = verify_sources(work / "libpack", sdk["release"], helper)
    require(digest(work / "empty-outline.patch") == PATCH_SHA, "Retained patch changed")
    host = helper.native_machine()
    require(host == report["host"], "Native build host architecture changed")
    environment, compiler = helper.compiler_environment(work, evidence, sdk["architecture"])
    require(
        compiler["compiler_sha256"] == report["compiler"]["compiler_sha256"]
        and compiler["tools_version"] == report["compiler"]["tools_version"],
        "Compiler changed",
    )
    require(
        helper.pe_machine(Path(compiler["compiler"])) == helper.MACHINES[sdk["architecture"]],
        "Compiler process architecture is not native",
    )
    environment = native_environment(environment, compiler, helper)
    candidate = work / "candidate"
    require(
        not Path(sys.executable).resolve().is_relative_to(candidate)
        and not Path(sys.executable).resolve().is_relative_to(work / "baseline")
        and not Path(sys.executable).resolve().is_relative_to(Path(original["root"])),
        "Use separate tool Python",
    )
    tools = tool_receipts(
        environment, [candidate, work / "baseline", Path(original["root"])], helper
    )
    require(tools == report["tools"], "Build-tool executable identity changed")
    git = tools["git"]["path"]
    diff_package = importlib.util.find_spec("diff_match_patch")
    require(diff_package and diff_package.origin, "Separate tool Python requires diff-match-patch")
    diff_origin = helper.real_path(Path(diff_package.origin))
    require(
        not any(
            diff_origin.is_relative_to(root)
            for root in (candidate, work / "baseline", Path(original["root"]))
        ),
        "Tool Python imports from a protected SDK",
    )
    upstream = load_module("pinned_libpack_compiler", work / "libpack/compile_all.py")
    source = work / "qt"
    build_root = work / "b/r"
    require(not (work / "b").exists(), "Short build root must be fresh")
    result = {
        "schema_version": 1,
        "status": "failed",
        "qualified": False,
        "build_only": True,
        "sdk": sdk,
        "source_commit": SOURCES[sdk["release"]]["commit"],
        "compiler": compiler,
        "tool_python": {
            "executable": str(Path(sys.executable).resolve()),
            "version": sys.version,
            "diff_match_patch_version": version("diff-match-patch"),
            "diff_match_patch_origin": str(diff_origin),
            "diff_match_patch_sha256": digest(diff_origin),
        },
        "baseline_unchanged": False,
        "non_qt_preserved": False,
    }

    QtOnlyCompiler = compiler_adapter(
        upstream,
        source,
        build_root,
        work / "empty-outline.patch",
        evidence,
        git,
        result,
        lambda: configured_cache(build_root, candidate, compiler, helper),
    )
    write_json(evidence / "build.json", {**result, "status": "running"})

    saved_environment, saved_cwd = dict(os.environ), Path.cwd()
    try:
        os.environ.clear()
        os.environ.update(environment)
        os.environ["PYTHONNOUSERSITE"] = "1"
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
        os.chdir(source)
        compiler_instance = QtOnlyCompiler(
            config, bison_path="", skip_existing=False, mode=upstream.BuildMode.RELEASE
        )
        compiler_instance.install_dir = str(candidate)
        compiler_instance.init_script = [compiler["initialization"], "-vcvars_ver=14.4"]
        compiler_instance.msvc_tools_version = compiler["tools_version"]
        options = {**options, "fallback-build-dir": str(work / "b")}
        compiler_instance.build_qt(options)
        require(compiler_instance.hook_calls == 1, "Qt patch hook was not reached exactly once")
        admission, after = admit_installation(
            build_root, candidate, source, before, result["source"]["repositories"], helper
        )
        for field, filename in (
            ("qt_install_manifest_receipt", "qt-install-manifest.json"),
            ("qt_finite_install_receipt", "qt-finite-install.json"),
            ("qt_companion_alias_receipt", "qt-versioned-aliases.json"),
            ("qt_companion_spdx_receipt", "qt-spdx-companions.json"),
        ):
            write_json(evidence / filename, admission.pop(field))
            admission[field + "_sha256"] = digest(evidence / filename)
        result.update(admission)
        installed = set(result["admitted_qt_paths"])
        write_json(evidence / "candidate-after.json", after)
        result["build_cache_sha256"] = digest(build_root / "CMakeCache.txt")
        clean_tracked(source, result["source"]["repositories"], evidence, git, patched=True)
        require(
            digest(source / "qtbase/src/gui/painting/qpdf.cpp") == QPDF_PATCHED,
            "Patched source changed during build",
        )
        result["installed_qt_modules"] = {}
        for name in ("Qt6Core.dll", "Qt6Gui.dll", "Qt6PrintSupport.dll"):
            require(
                f"bin/{name}" in installed, "Required Qt module was not installed by this build"
            )
            module = candidate / "bin" / name
            require(
                helper.pe_machine(module) == helper.MACHINES[sdk["architecture"]],
                "Candidate Qt DLL architecture differs",
            )
            module_version = helper.file_version(module)
            require(module_version[:3] == [6, 11, 1], "Installed Qt module version differs")
            result["installed_qt_modules"][name] = {
                "sha256": digest(module),
                "file_version": module_version,
                "pe_machine": helper.MACHINES[sdk["architecture"]],
            }
        require(
            result["installed_qt_modules"]["Qt6Gui.dll"]["sha256"]
            != before["files"]["bin/Qt6Gui.dll"]["sha256"],
            "Installed QtGui is still the baseline",
        )
        result["candidate_inventory_sha256"] = digest(evidence / "candidate-after.json")
        result["status"] = "built"
    except BaseException as error:
        result["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        os.chdir(saved_cwd)
        os.environ.clear()
        os.environ.update(saved_environment)
        try:
            result["baseline_unchanged"] = helper.inventory(work / "baseline") == before
            result["original_baseline_unchanged"] = (
                helper.inventory(Path(original["root"])) == before
            )
            independent_files(work / "baseline", before)
            independent_files(Path(original["root"]), before)
            require(
                result["baseline_unchanged"] and result["original_baseline_unchanged"],
                "Protected baseline changed during Qt build",
            )
        except BaseException as error:
            result["status"] = "failed"
            result["baseline_error"] = str(error)
        try:
            write_json(evidence / "candidate-after.json", helper.inventory(candidate))
            result["candidate_inventory_sha256"] = digest(evidence / "candidate-after.json")
        except BaseException as error:
            result["status"] = "failed"
            result["candidate_inventory_error"] = str(error)
        result["corresponding_sources"] = {
            "qt": str(source),
            "libpack": str(work / "libpack"),
            "patch": str(work / "empty-outline.patch"),
            "finite_ownership_proof": str(work / "libpack-qt-ownership.json"),
        }
        result["build_tree"] = str(build_root)
        write_json(evidence / "build.json", result)
    require(
        result["status"] == "built"
        and result["baseline_unchanged"]
        and result["original_baseline_unchanged"],
        "Build/preservation failed",
    )
    return result


def main():
    sys.dont_write_bytecode = True
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    prepare_parser = actions.add_parser("prepare")
    prepare_parser.add_argument(
        "--sdk", choices=["3.5.3-x64", "3.5.5-x64", "3.5.5-arm64"], required=True
    )
    prepare_parser.add_argument("--baseline-evidence-dir", type=Path, required=True)
    prepare_parser.add_argument("--work-dir", type=Path, required=True)
    build_parser = actions.add_parser("build")
    build_parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    helper = baseline_helper()
    try:
        result = prepare(args, helper) if args.action == "prepare" else build(args, helper)
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "qualified": False,
                    "evidence": str(args.work_dir / "evidence"),
                }
            )
        )
    except (OSError, ValueError, KeyError, ImportError, subprocess.SubprocessError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
