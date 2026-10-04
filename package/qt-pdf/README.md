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

Sources: [pinned upstream recipe](https://github.com/conda-forge/qt-main-feedstock/blob/5cd1156d41526330a116b6b441611b47357ec568/recipe/recipe.yaml),
[retained Qt qualification patch](../../tests/src/Mod/TechDraw/Gui/QtPdfStroker/empty-outline.patch),
[rattler-build CLI](https://rattler-build.prefix.dev/latest/reference/cli/rattler-build/build/).
Runner SDK inventories: [Intel](https://github.com/actions/runner-images/blob/6d942e630479cd99a93dadfc766af11242bfa402/images/macos/macos-15-Readme.md),
[ARM](https://github.com/actions/runner-images/blob/6d942e630479cd99a93dadfc766af11242bfa402/images/macos/macos-15-arm64-Readme.md).
