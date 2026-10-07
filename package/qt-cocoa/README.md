# Local Cocoa accessibility fix

`FreeCAD-24t` reproduces a Qt 6.11.2 Cocoa accessibility ownership failure in stock
tree, list and table widgets. Creating synthetic native table cells can release
an earlier synthetic element. Those elements share the parent table's Qt
accessibility ID; their cleanup incorrectly deletes the live parent interface.
One selected item exposes the missing parent interface, and two selected items
can crash `accessibilitySelectedChildren`.

`parent-managed-elements.patch` keeps parent-managed elements from deleting that
shared interface in both cache cleanup and deallocation. Its guards follow
[Caleb Meadows' proposed Qt change 765434](https://codereview.qt-project.org/c/qt/qtbase/+/765434/1)
for [QTBUG-149612](https://bugreports.qt.io/browse/QTBUG-149612). The proposal was
unmerged when investigated on 7 October 2026. This is a locally validated
backport, not a claim that Qt has released the fix. Original FreeCAD crash
reports identify the same native method; their signal-handler registers do not
identify the original invalid pointer or exact child object.

The delivery is an **app-local arm64 Cocoa plugin overlay** for the existing
FreeCAD 27.1.0dev installation. FreeCAD native binaries, locked Qt Core/Gui
libraries, the Pixi prefix and the earlier PDF package catalogue are preserved.
The application still requires its recorded external dependency prefix. The
overlay has a separate build receipt, installation receipt and runtime evidence;
it does not pass through the original verifier's prefix-only QPA load rule.
Promotion into a dependency package or an accepted Qt release is tracked by
`FreeCAD-4fa`.

## Build

The builder requires native macOS arm64, the exact authenticated Qt 6.11.2
archive/source tree, the reviewed `qt6-main-6.11.2-pl5321h5ab96b3_1` prefix and
its pinned Vulkan/MoltenVK header inputs. Archive URLs and SHA-256 identities are
in `build_plugin.py`. The header tree is copied into the isolated work directory;
the selected prefix is verified read-only before and after compilation.

```sh
python3 package/qt-cocoa/build_plugin.py \
  --qt-source /path/to/qtbase-6.11.2 \
  --qt-source-archive /path/to/qtbase-v6.11.2.tar.gz \
  --prefix /path/to/FreeCAD/.pixi/envs/default \
  --dependency-include /path/to/cocoa-build-deps/include \
  --work-dir /path/to/fresh-cocoa-work \
  --sdk /Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk
```

The output is `build/platforms/libqcocoa.dylib`; `build-receipt.json` binds it to
the official source archive, exact two-hunk patch, public/private Qt headers,
imported libraries, build tools, compiler, SDK and commands. The plugin targets
macOS 11.0, but runtime checks in this investigation are on macOS 27.0.1 only.
The isolated source directory retains upstream copyright/SPDX notices and
`LICENSES`. No second Qt Core/Gui build is used.

## Native regression

The standalone test calls the real registered `QMacAccessibilityElement` factory
and selected-children method from the loaded Cocoa plugin. It records that
method's image path, checks live parent identity, compares selected cell titles
with actual Qt selection and exercises selection and model changes.

```sh
cmake -S tests/src/Gui/QtCocoaAccessibility -B /path/to/selector-build \
  -DCMAKE_PREFIX_PATH=/path/to/FreeCAD/.pixi/envs/default
cmake --build /path/to/selector-build --parallel 4
QT_PLUGIN_PATH=/path/to/fresh-cocoa-work/build:/path/to/prefix/lib/qt6/plugins \
  /path/to/selector-build/selector-repro tree 3 2
QT_PLUGIN_PATH=/path/to/fresh-cocoa-work/build:/path/to/prefix/lib/qt6/plugins \
  /path/to/selector-build/selector-repro table-lifecycle 20
```

`list` and `table` support the same arguments as `tree`; selected counts 0, 1
and 2 distinguish empty selection, parent invalidation and the crashing case.
`table-lifecycle` checks row selection, column growth/shrink and row shrink.
Confirm `native_selector_identified.implementation_image` in every run: setting
only `QT_QPA_PLATFORM_PLUGIN_PATH` did not override the stock plugin in the first
comparison attempt, so those earlier runs were excluded from rebuilt-plugin
evidence.

## Delivery and scope

`install_overlay.py --help` documents the guarded local installer. It requires a
successful build receipt and the original native installation identity, backs
up the full existing application, replaces the two native wrapper entrypoints,
adds the plugin and corresponding source/licenses, then signs and verifies the
bundle. Installation and post-launch runtime verification are separate stages.
Use the application bundle or `freecad-local`/`freecadcmd-local`; raw resource
executables and ordinary source-prefix launches do not select this overlay.

Targeted validation covers actual selected children, model lifecycle, the
original A501 stock redraw/accessibility route and an A302 stock Qt Save/PDF
export. The exact retained input was copied read-only and checked by hash;
neither the original model nor the user's normal profile was saved. Drawing
content is excluded from this repository's evidence. These checks do not accept
the underlying building drawings or close the separate drawing-production bead.
Already passed unrelated platform workflows and the full FreeCAD build were
not repeated.
