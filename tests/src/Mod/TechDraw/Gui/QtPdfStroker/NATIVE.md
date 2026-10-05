<!-- SPDX-License-Identifier: LGPL-2.1-or-later -->

# Native FreeCAD qualification

The standalone corpus can exercise both `QPdfWriter` and `QPrinter` with
`-DWITH_QPRINTER=ON` and `--device both`. This companion harness exercises real
TechDraw models through `Gui.runCommand("TechDraw_ExportPagePDF")`, its standard
file dialog and the stock `PagePrinter` implementation. No scene item or private
pen is injected. Each export starts with ScreenMode enabled and asserts that the
command restores it after temporarily selecting physical print widths.

The printer route uses `Std_Print`, its actual `QPrintDialog` and that dialog's
public `printer()` setters. It requires PdfFormat, a unique scratch filename,
1200 dpi and the chosen PDF version after acceptance, before stock C++ printing.
macOS and Linux also verify those settings before acceptance. A failed
accepted callback terminates the disposable process before C++ printing can
continue. On macOS Qt always opens a native NSPrintPanel; the harness completes
that existing panel after AppKit reports an active visible modal NSPanel titled
Print in this process's own window inventory. Qt wrapper visibility can precede
the native modal session, so polling continues until that owned English panel
exists; its identity is checked again before completion. Bounded state records
and watchdog diagnostics are retained beside each printer PDF. Completion uses AppKit's public
[stopModal(withCode:) API](https://developer.apple.com/documentation/appkit/nsapplication/stopmodal%28withcode%3A%29).
Linux accepts the QPrintDialog directly. Windows Qt caches its native engine
while `PrintDlgEx` reads back the UI settings, so replacing that engine before
acceptance would invalidate its cached pointers. The Windows branch keeps
NativeFormat only for that dialog, identifies the unique visible native Print
property sheet owned by the disposable process and its current thread, and
clicks its English Print button through the documented
[BM_CLICK API](https://learn.microsoft.com/en-us/windows/win32/controls/bm-click).
The accepted callback then selects and verifies PdfFormat before `PagePrinter`
receives the printer. Missing or ambiguous dialog/button identification fails
the process. This prepared Windows branch needs successful runner execution
before it qualifies that platform.
`Std_Print` does not switch
ScreenMode itself, so the harness explicitly selects physical print mode for
that command and restores the preference afterward. This is recorded separately
from the PDF export command's own preference restoration.

The FreeCAD guards would otherwise hide the Qt defect. `build-native-bypass.py`
creates a qualification-only `TechDrawGui.so`: it copies `QGCustomPath.cpp` and
`QGCustomRect.cpp`, disables their guards in those copies, compiles them using an
existing macOS Ninja build's actual flags and relinks all other unchanged
objects. It verifies that the original sources, objects and module retain their
hashes. Its provenance records copied sources, commands, unchanged object
digests and the resulting module digest. Never install this module.

Use absolute physical paths for `fc_source`, `fc_build`, `native_work` and
`ninja`. `native_work` must be outside the original source/build trees, and its
module output must not already exist:

```sh
python "$fixture/build-native-bypass.py" \
    --source "$fc_source" --build "$fc_build" \
    --output "$native_work/module" --ninja "$ninja"
```

Prepare baseline and patched Qt 6.11.2 shared builds separately from the user
runtime, preserving the baseline libraries and plugins before applying the Qt
patch. A native FreeCAD process needs Widgets, PrintSupport, OpenGL,
OpenGLWidgets and the Cocoa platform plugin in addition to Core/Gui. Its other
dependencies include Network and XML. QtUiTools and QtSvg are separate Qt
modules; reusing installed binaries of the exact same Qt version must be
identified in the loaded-library inventory and proven by successful execution.
QtCore must retain the resource-compression features used by that FreeCAD build;
the local source smoke required zstd to resolve FreeCAD's compiled-resource
feature symbol. Both phases use the same rebuilt Core binary.
The reduced Core/Gui build described in README.md cannot run FreeCAD.

The native launcher uses process-local `DYLD_LIBRARY_PATH` on macOS,
`LD_LIBRARY_PATH` on Linux and `PATH` on Windows, with the selected runtime's
Cocoa, xcb or Windows platform plugin respectively. Linux needs a display
server with OpenGL support; a CI Xvfb/Mesa display is suitable. The launcher
creates fresh user/system configurations under a new output directory outside
the executable and selected runtime prefixes; preexisting outputs are rejected.
Report writes are also rejected inside either phase's input evidence, selected
runtime prefixes, scratch module evidence or protected source/build files.
Pre-generated comparisons retain `launch.json` with `native-provenance.json`
so the same report boundary checks can verify the recorded Python prefix.
`python_runtime` is FreeCAD's configured Python
environment, independent of the Python interpreter running the PDF checker.
Use `--baseline-python-runtime` and `--patched-python-runtime` to select the
corresponding Python prefixes in package qualification. `--python-runtime`
remains a shared fallback for source-build smoke tests.
The PDF checker requires pypdf, Pillow and Poppler. Run both phases with one command:

```sh
python "$fixture/native_compare.py" \
    --freecad "$fc_build/bin/FreeCAD" --python-runtime "$python_runtime" \
    --bypass-module "$native_work/module/TechDrawGui.so" \
    --baseline-qt-lib "$qt_work/baseline/lib" \
    --patched-qt-lib "$qt_build/lib" \
    --output "$native_work/qualification" \
    --report "$native_work/native-comparison.json"
```

On Windows the module suffix is `.pyd`. Explicit `--baseline-plugin-dir` and
`--patched-plugin-dir` can select plugin roots when the package layout differs
from the automatically detected `plugins` or `lib/qt6/plugins` layouts. The
process must actually load QtGui from the selected directory; for example,
an older DLL beside a Windows executable would fail that assertion.
The conda preset disables LibPack copying; other Windows builds that copy Qt
DLLs beside the executable need a separate disposable application tree or must
fail qualification. Changing PATH does not replace an application-local DLL.

The macro verifies the loaded scratch module path and digest, enumerates actual
loaded Qt libraries through dyld, Linux process maps or Windows ToolHelp,
verifies QtGui came from the selected runtime and records its digest. Every
loaded Qt library and plugin is hashed and checked against the selected runtime
prefix, including the active QPA plugin. External Qt origins are rejected by
default. A local source build can explicitly allow
`--allow-external-qt-module Svg`, `SvgWidgets` or `UiTools`; those external paths
and hashes must be identical across phases. Core, Gui, Widgets and PrintSupport
can never be allowed outside the selected prefix. Candidate package
qualification should use the strict default with no external allowance.
The comparison requires the same bypassed FreeCAD
module on both sides and different verified QtGui digests. `runtime.log` also
retains dyld's library loading trace. No installed Qt binary or user
configuration is overwritten.

Each phase runs all 11 existing `TestTechDrawGui` tests, creates editable FCStd
documents and exports twelve scenarios through both stock devices, producing
24 PDFs. The short ASME dash gap must reproduce one invalid close/fill pair and
one Poppler warning per baseline device. The dimension-frame expectations also
depend on Qt's actual text palette: the unused origin-label frames keep the
`QGraphicsTextItem` constructor's text colour. Cocoa's observed alpha 216 takes
the translucent PDF stroker route; Linux xcb's observed alpha 255 takes the
opaque route and contributes no invalid close. The harness requires exactly
one visible null origin frame for Distance and theoretical-exact Distance,
and two for Area and relocated Area combined with theoretical-exact Distance.
Before each stock command it records the application/class/default-text palette
and the actual frame rectangle, pen, brush, opacity and affine transform. The
baseline warning count is one per proven translucent null frame, plus the
short-gap count. Thus the observed Cocoa baseline totals seven per device,
while the observed Linux baseline totals one. The patched counts remain zero.
Box,
opaque-gap, short-solid and long-dashed controls must be clean. Additional
public ASME zero-width controls cover translucent, opaque and PDF/A output,
with visible ink and no syntax warnings.

Both phases verify Area measures 100 mm² and exercise the public area leader
point relocation. The PDF comparison retains every coordinate and remaining
operator, removes only invalid bare `h f` pairs from the baseline and requires
identical RGBA pixels at 150 dpi for each device across baseline and patched
Qt. The stock routes have an existing target-size difference: QPdfWriter
computes pixels from exact template millimetres, whereas QPrinter uses rounded
page points through `QPageLayout.fullRectPixels`. Cross-device pixel equality is
therefore recorded but not required by this native harness. The standalone
paired fixture still requires its cross-device pixels to match exactly.
Additional checks require the invisible gap
to match the box-only page, visible solid/dashed strokes and a visible
theoretical-exact frame. The saved cosmetic edge preserves editable RGB/style
data but FCStd currently omits its alpha; the macro reconstructs alpha through
the public model API rather than treating reload as equivalent runtime state.
General graphics-item values remain diagnostic snapshots taken after
PagePrinter refreshes the scene following export. A refreshed path item's pen
can remain at its default before its next paint; those values do not establish
its effective export pen. The null origin-label frames have a separate
prospective contract: their constructor pen is source-backed, their input
snapshots are persisted before either stock command, and the same complete
frame state must remain afterward. The launcher binds the exact executed macro
path and digest to those snapshots. The checker independently validates the
palette, known frame counts and supported pen/brush/transform branch before
using its predicted baseline count; it never derives that count from PDF output.
The same prospective inputs are required on both Qt runtimes. Acceptance still
requires the public model controls and exact emitted operators and pixels.
Old post-export-only captures cannot supply this new prospective evidence.

For GitHub Actions, `build-native-bypass.py --ci-checkout` provides a portable
alternative to the macOS scratch relinker. It requires `GITHUB_ACTIONS=true`,
`CI=true`, source equal to `GITHUB_WORKSPACE`, and output under `RUNNER_TEMP`.
It temporarily replaces the two guards in that disposable checkout, builds
the `TechDrawGui` target and copies its module to the output directory. The
original source bytes are restored in `finally`; build objects and the original
CI build module are deliberately changed and the provenance records that fact.
This mode does not claim the build outputs were preserved. `--module` identifies
the compiled module if automatic discovery finds multiple candidates. Use
`--cmake`, `--parallel` and `--config` for the configured CI build as needed.

The local scratch relinker remains specific to macOS Ninja builds. The portable
launcher and CI mode require successful native execution on each platform
before claiming package coverage. This does not update dependency
pins, replace the user runtime or qualify all supported FreeCAD distributions.

The package qualification workflow keeps the normal conda CMake configuration
and builds the following Ninja directory aggregates:

```sh
pixi run build-release --target \
    src/Main/all src/Gui/all \
    src/Mod/Part/all src/Mod/PartDesign/all src/Mod/Sketcher/all \
    src/Mod/TechDraw/all src/Mod/Material/all src/Mod/Test/all pivy
```

The full aggregates retain core initialization, Python shims, normal default
PartDesign startup with Sketcher, Material assets, bundled Pivy, TechDraw tools,
templates, line definitions and the complete TDTest package. Linked App/Gui
dependencies are built automatically. This builds the application needed for
the unchanged 24-PDF and eleven-test native gates; unrelated workbenches and
broad C++ test executables are outside this qualification build scope.

For the two reviewed Linux retries, the workflow's `stage=native` option reuses
the authenticated passed Qt checks from run 37252425998 (`linux-64`) or
37252439637 (`linux-aarch64`) and package build 37238935749. The bounded
`reuse_linux_qt_qualification.py` helper verifies the complete artifact transport,
66-case result, ten-test transcript, source and binary identities, then binds
the newly installed prefixes and newly loaded native Qt binaries to that proof.
It does not execute the standalone fixture or upstream test again. Those old
runs retain their failed native outcome. Their artifacts omitted the FreeCAD
executable, core modules and native resources, so a scoped FreeCAD build is
necessary to capture the new prospective inputs. Select one Linux target and
its matching `reuse_run`; the workflow rejects other native-stage selections
before scheduling a build. The default `stage=all` retains the complete checks.

Linux native retries also retain the application binaries, native modules and
resources after the controlled bypass build, together with their source,
CMake-cache and reused-runtime bindings. This is diagnostic build evidence,
not a distribution or a qualification result. Any future restoration must
authenticate the entire bundle and the exact installed dependency prefixes.
Objects and unrelated build directories are omitted.

Diagnostic retention is optional and cannot skip the ordinary native gates.
Before strict resource-link validation, it retains a bounded diagnostic archive
of physical runtime outputs with symlinks preserved as links. This fallback is
unvalidated build evidence; its links must not be followed or restored without
separate authentication and review. A failed strict retention step is recorded
and skips GDB replay, while native PDF and GUI qualification proceeds normally.

If the ARM native process crashes, a separate bounded GDB run uses its recorded
baseline command and runtime bindings with fresh configurations, output and
Xvfb display. It records all-thread backtraces and loader information while
preserving the original failed artifacts. A successful diagnostic execution
does not change the failed qualification result. All 24 native PDF comparisons,
both eleven-test GUI suites and the final reused-Qt binding still have to pass
in the ordinary native stage.
