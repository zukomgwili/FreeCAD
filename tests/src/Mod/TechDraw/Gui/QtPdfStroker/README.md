<!-- SPDX-License-Identifier: LGPL-2.1-or-later -->

# Qt PDF empty-outline qualification

`QPdf::Stroker::strokePath` writes a terminal `h f` even when its stroker emits
no coordinates. Empty input and nonempty paths lying entirely in a dash gap
can consequently produce Poppler's `No current point in closepath` warning.
An input-path emptiness check cannot cover the latter case.

`empty-outline.patch` checks Qt's existing `first` flag after the actual stroke.
The move callback clears that flag when it writes a coordinate. Coordinated
outlines retain their terminal close/fill; an empty outline contributes none.
Pen normalization, transforms, dash processing, fills, backgrounds and native
PDF strokes keep their existing behavior. See the pinned
[Qt 6.11.2 implementation](https://github.com/qt/qtbase/blob/ef55f427f2c8b410d34f8a7681020a3000cf6866/src/gui/painting/qpdf.cpp#L649).

This directory is a standalone dependency qualification fixture. The FreeCAD
build does not apply the patch or run it against an arbitrary installed Qt.
The [completed delivery](../../../../../../package/qt-pdf/README.md) qualifies
eight exact dependency routes. The separate
[mitigation review](../../../../../../package/qt-pdf/MITIGATIONS.md) retains both
`QGCustomPath` and `QGCustomRect` guards because ordinary source builds can still
select unqualified Qt. The qualification below keeps its historical stage-specific
scope.

## Fixture

`generator.cpp` uses actual `QPdfWriter` painting and writes PDFs plus a manifest.
It uses neither FreeCAD nor a copied serializer. Its cases include empty,
move-only and coincident paths; dash gaps and visible strokes; cap styles;
visible fills and opaque backgrounds; cosmetic scaling; zero/tiny widths;
curves and multiple draw calls; perspective; rectangles and clipping; and
opaque/PDF-A native zero-dash controls.

The opaque and PDF/A controls intentionally contain visible ink. Qt's native
PDF dash clamping can produce ink even when a public stroked outline is empty.
The cosmetic scale and tiny-width controls also protect Qt-specific behavior.
Whole-item omission would lose the fill/background controls' ink.

### Paired PDF devices and package runtimes

Configure with `-DWITH_QPRINTER=ON` to link Qt PrintSupport and Widgets, then
run `qt_pdf_stroker_fixture --device both --output DIR`. Each of the 33 paint
callbacks runs through a real `QPdfWriter` and a `QPrinter` in `PdfFormat`,
producing 66 files. The default configuration retains the original 33
QPdfWriter-only cases and Core/Gui dependencies.

Each process also writes `runtime.json` using native loaded-module enumeration
and SHA-256 hashing. The comparator can launch one or two fixture executables
with separately selected package prefixes, library directories and platform
plugins. Require this proof and both devices for package qualification:

```sh
python compare.py --baseline-executable /absolute/path/fixture \
    --patched-executable /absolute/path/fixture --device both \
    --baseline-prefix /absolute/path/baseline \
    --patched-prefix /absolute/path/candidate \
    --require-runtime --require-both-devices \
    --output /absolute/path/fresh-results --report /absolute/path/comparison.json
```

`qualification-devices.json` records an actual isolated QtBase 6.11.2 source
build on macOS arm64 with Widgets, PrintSupport, OpenGL, Cocoa and zstd-enabled
Core. The 66-file baseline has 30 invalid closes across 26 failing outputs;
the patched runtime has zero, with identical remaining operators and RGBA
pixels. QPrinter and QPdfWriter pixels match within each runtime. Qt's own
QPdfWriter suite passes all 10 tests. This evidence covers the stated source
build and devices; full qt6-main packages and native FreeCAD exports require
their separate gates.

See [native stock-export qualification](NATIVE.md) and the
[complete package backport](../../../../../../package/qt-pdf/README.md) for
the separate delivery steps. Keep FreeCAD's mitigations and active pins until
the supported dependency paths have qualified fixed binaries.

`qualification-native.json` records the corresponding actual macOS arm64
FreeCAD source-build comparison: twelve stock TechDraw scenarios through
each device, with both FreeCAD guards bypassed in a scratch module. The 24-file
baseline has 14 invalid closes and warnings; the corrected Qt has zero, with
identical remaining operators, coordinates and pixels for each route. All 11
TechDraw GUI tests pass on both runtimes. Area and relocated-area dimensions,
the theoretical-exact frame and visible/opaque/PDF-A controls remain intact.
Three unchanged installed QtSvg/QtSvgWidgets/QtUiTools libraries are explicitly
identified because they are outside QtBase. This local evidence does not
qualify a complete package or another platform. Stock QPrinter page rounding
differs from Export PDF; its own baseline is the exact preservation reference.

`compare.py` requires a genuinely failing baseline and a clean patched result,
checks decoded PDF operators with strict pypdf parsing, checks Poppler stderr,
and compares rendered pixels and coordinate operators. It also asserts visible
ink, including red background and blue fill pixels. Poppler's exit status alone
does not detect this defect: it can return zero while printing syntax warnings.

Requirements: Qt 6 Core/Gui development files, CMake, a C++17 compiler, Python 3,
`pypdf`, Pillow, and `pdftoppm`. The fixture is separate from the FreeCAD CMake
project so it can reach the Qt defect even when FreeCAD's mitigation is enabled.

## Reproduce on an isolated Qt build

Use the official QtBase 6.11.2 source, resolved commit
`ef55f427f2c8b410d34f8a7681020a3000cf6866`. The
[source archive](https://github.com/qt/qtbase/archive/refs/tags/v6.11.2.tar.gz)
used here has SHA-256
`06cd7aa6b3ab19cb5a1664a2891ef0df960f78c97fa31b80b1d6d7ee70688414`;
the original `src/gui/painting/qpdf.cpp` has SHA-256
`ccd12fea8fc9824d0a3f7a676abace2e27d9eeebdb427c409b1b153ebba4bd30`.

Keep source and build directories separate from the installed Qt. Qt rejects
symlinked build paths, so use physical paths (`pwd -P`, including `/private/tmp`
on macOS). A minimal shared QtBase configuration needs Core, Gui/PDF and the
offscreen platform plugin. The qualification used Release, arm64, Clang 23.1.1,
SDK 26.5 and macOS deployment target 14.0, with Widgets, PrintSupport, Network,
DBus, SQL, XML, Testlib, OpenGL, Vulkan, ICU and zstd disabled. It used bundled
FreeType, HarfBuzz, PNG, JPEG and PCRE, and the SDK's zlib. This reduced library
supports the fixture; it is not a replacement FreeCAD runtime.

Set `qt_src`, `qt_build`, `qt_work` and `fixture` to absolute physical paths.
`fixture` is this directory; `qt_src` is the extracted QtBase source. With the
recorded Clang/CMake/Ninja toolchain on PATH, the effective minimal macOS
configuration can be recreated as follows (adjust the SDK path for the host):

```sh
cmake -S "$qt_src" -B "$qt_build" -G Ninja \
    -DCMAKE_C_COMPILER=clang-23 -DCMAKE_CXX_COMPILER=clang++-23 \
    -DCMAKE_OSX_SYSROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX26.5.sdk \
    -DCMAKE_OSX_DEPLOYMENT_TARGET=14.0 -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$qt_work/install" \
    -DQT_BUILD_EXAMPLES=OFF -DQT_BUILD_TESTS=OFF -DQT_FEATURE_framework=OFF \
    -DQT_FEATURE_gui=ON -DQT_FEATURE_widgets=OFF -DQT_FEATURE_network=OFF \
    -DQT_FEATURE_dbus=OFF -DQT_FEATURE_sql=OFF -DQT_FEATURE_xml=OFF \
    -DQT_FEATURE_testlib=OFF -DQT_FEATURE_printsupport=OFF \
    -DQT_FEATURE_opengl=OFF -DQT_FEATURE_vulkan=OFF \
    -DQT_FEATURE_icu=OFF -DQT_FEATURE_zstd=OFF \
    -DINPUT_freetype=qt -DINPUT_harfbuzz=qt -DINPUT_libpng=qt \
    -DINPUT_libjpeg=qt -DINPUT_pcre=qt -DQT_FEATURE_system_zlib=ON
```

Build the unpatched Qt and the fixture first:

```sh
cmake --build "$qt_build" --target Gui QOffscreenIntegrationPlugin --parallel 4
cmake -S "$fixture" -B "$qt_work/fixture-build" -G Ninja \
    -DCMAKE_PREFIX_PATH="$qt_build/lib/cmake"
cmake --build "$qt_work/fixture-build" --parallel 4
```

The following runtime isolation commands are for the qualified macOS shared
build. Preserve both Qt libraries and the offscreen plugin, including symlinks:

```sh
mkdir -p "$qt_work/baseline/lib" "$qt_work/baseline/plugins/platforms"
cp -a "$qt_build"/lib/libQt6Core*.dylib "$qt_build"/lib/libQt6Gui*.dylib \
    "$qt_work/baseline/lib/"
cp -a "$qt_build/plugins/platforms/libqoffscreen.dylib" \
    "$qt_work/baseline/plugins/platforms/"
env DYLD_LIBRARY_PATH="$qt_work/baseline/lib" DYLD_PRINT_LIBRARIES=1 \
    QT_QPA_PLATFORM=offscreen \
    QT_QPA_PLATFORM_PLUGIN_PATH="$qt_work/baseline/plugins/platforms" \
    "$qt_work/fixture-build/qt_pdf_stroker_fixture" \
    --output "$qt_work/output-baseline" > "$qt_work/runtime-baseline.log" 2>&1
```

Verify the runtime log names the preserved QtGui, QtCore and offscreen plugin.
Record their digests, source/configuration and fixture executable digest. Qt's
version string cannot distinguish a same-version patched library. Retain the
baseline PDFs and demonstrate the failing syntax checks before applying the
patch. Then change only the Qt source seam and rebuild:

```sh
patch --dry-run -p2 -d "$qt_src" < "$fixture/empty-outline.patch"
patch -p2 -d "$qt_src" < "$fixture/empty-outline.patch"
cmake --build "$qt_build" --target Gui QOffscreenIntegrationPlugin --parallel 4
env DYLD_LIBRARY_PATH="$qt_build/lib" DYLD_PRINT_LIBRARIES=1 \
    QT_QPA_PLATFORM=offscreen QT_QPA_PLATFORM_PLUGIN_PATH="$qt_build/plugins/platforms" \
    "$qt_work/fixture-build/qt_pdf_stroker_fixture" \
    --output "$qt_work/output-patched" > "$qt_work/runtime-patched.log" 2>&1
python "$fixture/compare.py" \
    --baseline-dir "$qt_work/output-baseline" --patched-dir "$qt_work/output-patched" \
    --report "$qt_work/comparison.json"
```

Use platform-appropriate process-local library loading on Linux/Windows and
prove the loaded QtGui path there as well. Cross-platform package validation is
still required before shipping a dependency change.

## Qualified result

The 2026-10-04 macOS arm64 Qt 6.11.2 QPdfWriter comparison passed all **33 cases**.
The unpatched library produced **15 invalid close/fill pairs in 13 cases**;
the patched library produced none, with clean Poppler feedback throughout.
Every coordinate operator, every remaining decoded page operator, and every
RGBA pixel matched at 100 dpi. Independent strict parsing, fresh Poppler/RGB
comparisons and visual inspection confirmed the results.

The patch rebuild compiled only `qpdf.cpp` and relinked QtGui. QtCore and the
offscreen plugin retained their original digests. Both runtime logs confirmed
the intended libraries were loaded. `qualification.json` retains source,
runtime and per-case result digests. This validates the serializer correction
on that build; it does not qualify other platforms, native QPrinter integration
or a patched Qt 6.8.3 runtime.

## Historical dependency delivery audit

Source and recipe audit performed on 2026-10-04, before the linked completed
delivery above:

- FreeCAD's `pixi.toml` requires `qt6-main >=6.11,<6.12`; its lock resolves
  6.11.2 build 0 on linux-64, linux-aarch64, osx-64, osx-arm64 and win-64.
  Linux Wayland uses the same range; PySide resolves to 6.11.2.
- The checked official Qt 6.8.3, 6.12.0 and dev snapshots have the same
  unconditional terminal write. Matching source establishes an edit location,
  not qualification of their patched binaries. See
  [6.8.3](https://github.com/qt/qtbase/blob/c07c2d5a527a644d36e7853d55132ae38921682f/src/gui/painting/qpdf.cpp),
  [6.12.0](https://github.com/qt/qtbase/blob/025bdad181de241e81bf853c8a2d7bf3d19261a9/src/gui/painting/qpdf.cpp),
  and the [dev snapshot](https://github.com/qt/qtbase/blob/f127f11fc11d3578fdfaa8d4a7597397a30cd1d6/src/gui/painting/qpdf.cpp).
- Prefer a verified official fixed Qt release. A same-version backport can use
  the conda-forge recipe's `source.patches` mechanism and increment its build
  number. This patch targets `qtbase/src/gui/painting/qpdf.cpp`, suitable for
  `-p1` in the recipe's qt-everywhere archive. Preserve Qt's source licensing.
  The [6.11.2 recipe](https://github.com/conda-forge/qt-main-feedstock/blob/5cd1156d41526330a116b6b441611b47357ec568/recipe/recipe.yaml)
  is pinned for that backport review.
- The feedstock's [current main recipe](https://github.com/conda-forge/qt-main-feedstock/blob/cd198b6ad449dd9b0428bec7805ea1f0e70e4ab9/recipe/recipe.yaml)
  has advanced to 6.12.0. No 6.11 maintenance branch was present in the checked
  branch inventory. A 6.11 backport needs maintainer agreement; a 6.12 delivery
  needs an intentional FreeCAD Qt/PySide/Wayland upgrade. See conda-forge's
  [release-branch workflow](https://conda-forge.org/docs/how-to/advanced/several-versions/).

Before updating pins, qualify actual packages on all five platforms, including
native FreeCAD QPdfWriter/QPrinter exports and existing Qt test coverage. Keep
the corresponding patch/source and runtime provenance available. Source/CMake
and LibPack installations also need a fixed dependency path. Keep the FreeCAD
guard until fixed dependencies cover those paths and exports pass with the
guard bypassed. No active dependency pin or installed user runtime is changed
by this qualification, and no external Qt/feedstock submission is made here.
