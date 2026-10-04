<!-- SPDX-License-Identifier: LGPL-2.1-or-later -->

# Qt PDF 6.11.2 package backport

`build_backport.py` materializes the complete conda-forge Qt 6.11.2 feedstock
recipe at commit `5cd1156d41526330a116b6b441611b47357ec568`. The archive SHA-256
is `30a20fe87b59ef0709e4785e8a28a8fcb7ef5f7776b8ac71daf8b2a823ec104a`.
It preserves upstream build logic, variants, source checksums, existing
patches, package contents, tests and licensing. The only recipe edits append
the retained Qt PDF patch and change the build number from 0 to 1. A readable
recipe diff and provenance with every materialized file's digest accompany
the prepared tree. Separate scheduling edits make the Unix and Windows CMake
build commands consume `CPU_COUNT` through `--parallel`; their exact upstream
anchors are asserted and the changes are retained in `build-scripts.diff`.
Rattler-build forwards `CPU_COUNT` into its strict build environment. This
sets build concurrency without changing compiler, dependency or Qt feature pins.

Use Python 3 and an isolated work directory outside installed conda environments:

```sh
python package/qt-pdf/build_backport.py --prepare \
  --work-dir /absolute/path/qt-pdf-osx-arm64 --platform osx-arm64
python package/qt-pdf/build_backport.py --build \
  --work-dir /absolute/path/qt-pdf-osx-arm64 --platform osx-arm64
```

Preparation may run on any host. Building requires the matching native host
and `rattler-build` on PATH; `--rattler-build` can select its absolute path.
The supported targets are `linux-64`, `linux-aarch64`, `osx-64`, `osx-arm64`
and `win-64`, using their pinned `.ci_support` variants. The compiler and
dependencies come from conda-forge into rattler-build's isolated environments.
The upstream macOS variants request SDK 14.5. `--macos-sdk /absolute/path/to/SDK`
can explicitly select an available SDK through the `CONDA_BUILD_SYSROOT` build
variant; pass the same value to preparation and building. The SDK path and
settings-file digest are recorded, while the original variant files,
deployment target 11.0 and clang 19 pins remain unchanged. GitHub's macOS 15
Intel and ARM image inventories lack SDK 14.5; both list Xcode 16.4 with SDK
15.5. The workflow may explicitly select that Xcode and record its SDK path as
a controlled qualification input. No installed Qt or active FreeCAD pin is edited.

The helper verifies the pinned archive/recipe/retained patch, rejects archive
links and unexpected paths, and verifies the complete prepared tree again
before invoking the build. Repeating preparation validates existing contents;
it never repairs or overwrites a modified materialization. Use a fresh work
directory after an intentional input change. The archive, `feedstock/`,
`recipe.diff`, `build-scripts.diff`, `provenance.json`, `build.json` and `output/` provide reviewable
build evidence. A completed package build remains `qualified: false`.

The workflow must separately install each resulting package in a fresh runtime,
prove its loaded library/plugin paths and digests, and pass QPdfWriter,
QPrinter and native FreeCAD PDF controls with the mitigation bypassed. Package
builds and prepared scripts alone cannot establish five-platform qualification.
The helper performs no publication or upload, and needs no signing/upload
secrets. Keep Qt's original source SPDX and corresponding modified source,
recipe, patch and runtime evidence with any later distributed package.

## Isolated package installation and qualification

`install_candidate.py` validates the complete retained build evidence before
creating anything. It clones the locked FreeCAD baseline with micromamba
2.9.0's copy mode, then installs the exact candidate from a private indexed
channel. The solver must preserve every other package's name, version, build
and archive checksum. An incompatible candidate fails rather than relaxing
that baseline. Qt/PySide/Shiboken managed files and baseline metadata are
hashed before and after; the original prefix must remain unchanged. A direct
package-file installation would skip dependency solving and is unsuitable here.

```sh
python package/qt-pdf/install_candidate.py \
  --baseline-prefix /absolute/path/locked-baseline \
  --package-build-json /absolute/path/package-evidence/build.json \
  --candidate-prefix /absolute/path/fresh-candidate
python package/qt-pdf/qualify_package.py \
  --baseline-prefix /absolute/path/locked-baseline \
  --patched-prefix /absolute/path/fresh-candidate \
  --package-build-json /absolute/path/package-evidence/build.json \
  --qt-source-archive /absolute/path/qt-everywhere-src-6.11.2.tar.xz \
  --work-dir /absolute/path/device-results
```

The qualifier requires the native target, successful recipe tests, original
preparation/diff checksums and the installed candidate's exact package identity.
It compiles the paired standalone fixture against candidate development files,
proves loaded Qt/QPA origins on both sides, and checks all 66 PDFs with strict
parsing, Poppler stderr, operator equality, rendered pixels and cross-device
pixel equality. It authenticates the retained official Qt source archive
against the recipe checksum, extracts the original two QPdfWriter test sources
with their SPDX notices and requires all ten upstream tests to pass.
Its report is explicitly scoped to Qt; native FreeCAD remains a separate gate.

The personal-fork workflows perform the complete recipe build on each native
host and the separate package/native qualification. Build dispatch can select
one target or all five; qualification dispatch accepts the build run ID and an
optional separate Windows run ID. Artifacts retain corresponding source,
package hashes, build logs, loaded runtime inventories, native documents/PDFs
and test reports. They expire after 30 days, so a promoted distribution needs
a durable source/evidence archive. No workflow publishes a release or changes
the active dependency pins.

## Artifact transport recovery

The first build runs used GitHub's default exclusion of hidden files. Their
retained public feedstock archive can reconstruct the missing hidden inputs,
but the downloaded evidence must remain untouched. `restore_evidence.py`
authenticates that pinned archive, both recorded diffs and every present input;
only the known hidden upstream paths may be absent. It creates a fresh sibling
materialization and copies the actual package and raw recipe source archives
with checksum verification. Its report inventories the original cache and
explicitly excludes derived extraction trees, indexes and locks. Those trees
are unnecessary for qualification; the authenticated original archives retain
the complete corresponding source. Modified, linked, unknown or
missing visible feedstock inputs and linked raw archives fail. This step
establishes intact transport evidence, not a qualification result.

```sh
python package/qt-pdf/restore_evidence.py \
  --artifact-work-dir /absolute/path/download/qt-pdf-package \
  --recovered-work-dir /absolute/path/qt-pdf-recovered
```

Use the recovered `build.json` for installation and qualification. Future
build uploads explicitly include hidden files and still pass the same checks.

## Remaining dependency paths

The five native package targets cover FreeCAD's locked conda Qt 6.11.2 path.
General source/CMake builds must explicitly select a qualified Qt installation
and prove the libraries used by their executable. A CMake build alone does not
patch a system Qt or establish that its runtime uses this corrected package.

The repository's ordinary Windows build uses LibPack 3.5.3; the experimental
release defaults to 3.5.5, including its ARM64 override. Both pinned LibPack
recipes declare Qt and PySide 6.11.1, and neither applies this PDF correction.
QtBase 6.11.1 retains the same unconditional serializer write. These recipe and
source facts do not measure the shipped DLLs. LibPack needs an independently
reviewed Qt 6.11.1 backport or an intentional coordinated Qt/PySide replacement,
actual x64/ARM64 binaries, and the corresponding standalone/native tests.
Application-local DLLs must be handled in a disposable application tree so
their precedence cannot mask the candidate runtime. Keep both FreeCAD guards
until every intended distribution path has qualified corrected dependencies.

Source-only validation confirms the pinned QtBase 6.11.1 `qpdf.cpp` is
byte-identical to the tested 6.11.2 file: SHA-256
`ccd12fea8fc9824d0a3f7a676abace2e27d9eeebdb427c409b1b153ebba4bd30`.
The retained unified patch applies cleanly with `-p1` at the Qt superproject
root or `-p2` at the QtBase root. This establishes source compatibility only.
LibPack's generic config patch hook runs before QtBase initialization and
expects its own `@@@ filename @@@`/diff-match-patch format. Apply and verify
the retained patch in a dedicated `build_qt` step after successful
configuration/submodule initialization and before `_cmake_build()` instead.
Use a fresh build or `--rebuild qt` so existing-build shortcuts cannot bypass
that step. The current native/package qualification helpers require Qt 6.11.2;
a LibPack 6.11.1 mode needs separate review and actual execution.
The [source compatibility receipt](libpack-source-compatibility.json) retains
the pinned identities, parser rejection, successful patch checks and seam.

Pinned LibPack sources: [3.5.3](https://github.com/FreeCAD/FreeCAD-LibPack/blob/94cda1f16a388b0a70b814d0f8d684301787f4da/config.json),
[3.5.5 configuration](https://github.com/FreeCAD/FreeCAD-LibPack/blob/6641ccccc9f6dd3541acaf0d5f53a89cde3ecf59/config.json#L126),
[Qt build procedure](https://github.com/FreeCAD/FreeCAD-LibPack/blob/6641ccccc9f6dd3541acaf0d5f53a89cde3ecf59/compile_all.py#L1124),
[patch initialization](https://github.com/FreeCAD/FreeCAD-LibPack/blob/6641ccccc9f6dd3541acaf0d5f53a89cde3ecf59/create_libpack.py#L184),
[generic patch parser](https://github.com/FreeCAD/FreeCAD-LibPack/blob/6641ccccc9f6dd3541acaf0d5f53a89cde3ecf59/compile_all.py#L202),
[QtBase 6.11.1 serializer](https://github.com/qt/qtbase/blob/59c81a3c2247b821b9b84b4eb8d939b77e07e276/src/gui/painting/qpdf.cpp#L657).

Sources: [pinned upstream recipe](https://github.com/conda-forge/qt-main-feedstock/blob/5cd1156d41526330a116b6b441611b47357ec568/recipe/recipe.yaml),
[retained Qt qualification patch](../../tests/src/Mod/TechDraw/Gui/QtPdfStroker/empty-outline.patch),
[rattler-build CLI](https://rattler-build.prefix.dev/latest/reference/cli/rattler-build/build/).
Runner SDK inventories: [Intel](https://github.com/actions/runner-images/blob/6d942e630479cd99a93dadfc766af11242bfa402/images/macos/macos-15-Readme.md),
[ARM](https://github.com/actions/runner-images/blob/6d942e630479cd99a93dadfc766af11242bfa402/images/macos/macos-15-arm64-Readme.md).
