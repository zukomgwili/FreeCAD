<!-- SPDX-License-Identifier: LGPL-2.1-or-later -->

# TechDraw PDF mitigation decision

**Retain both production guards unchanged.** `FreeCAD-t8a.8` completes the
separate retention review required by `FreeCAD-t8a`; deleting either guard is
unsupported by the current coverage. The exact eight delivered dependency
routes are qualified, and ordinary source builds can still select unpatched Qt.
The [decision receipt](mitigation-review.json) binds this review to starting
commit `29004fbd85825273205861375a3e243ca189f119`, source hashes and accepted evidence.

## Supported dependency evidence

The [catalogue](distribution.json), [qualification](distribution-qualification.json)
and [delivery receipt](delivery-verification.json) authenticate these exact routes:

| Delivered route | Corrected Qt | Accepted gates per route |
| --- | --- | --- |
| linux-64, linux-aarch64, osx-64, osx-arm64, win-64 conda | 6.11.2 build 1 | 66 standalone PDF pairs, 10 upstream tests, 24 native PDF pairs, 11 GUI tests per runtime |
| LibPack 3.5.3 x64, 3.5.5 x64, 3.5.5 ARM64 | 6.11.1 | The same four gates, with SDK ownership and preservation evidence |

The standalone matrix has 33 paint callbacks on each of `QPdfWriter` and
`QPrinter`. Native qualification has 12 stock TechDraw scenarios on each device.
Both production guards are bypassed in the same native module for the baseline
and corrected Qt phases. The comparisons require preservation of remaining
operators, coordinates and RGBA output for each device; native cross-device
pixel rounding is informational. They establish corrected dependency behavior,
without a guard-on versus guard-off comparison on corrected Qt.

| Control family | Accepted evidence and preservation scope |
| --- | --- |
| Empty outlines, dash gaps, null rectangles | Standalone empty/move/coincident/gap/null cases; native short gap and stock dimension frames. Only the unmatched bare close/fill operations disappear. |
| Visible geometry | Standalone visible dashes, solid lines, round/square caps, curves, multi-call paths, horizontal/vertical rectangles and clipping; native box, short solid, long dashed, Distance, theoretical-exact and Area/relocated Area controls. |
| Opaque and PDF/A | Standalone opaque-native-clamp and archival-native-clamp; native opaque gap and translucent/opaque/archival zero-width exports. Intentionally visible ink remains. |
| Fill and background | Standalone three visible-fill cases and opaque-background case preserve their blue/red ink. This is chiefly standalone coverage. |
| Transforms and pen widths | Standalone cosmetic scaling, zero width, tiny normalized width, minimum real width and perspective cases. Native zero-width controls supplement this; the full matrix is not exhaustive native coverage. |

Palette-dependent null-frame expectations remain specific to each recorded
runtime. The SDK x64 text pen has alpha 255; ARM64 has alpha 228. ARM64 records
five affected cases and seven bare close/fill pairs per device, which are
different counts. Opaque palettes do not demonstrate translucent-frame failure.
Historical Cocoa receipts retain their older capture schema; later prospective
or Windows face-readiness fields are not retrofitted.

## Decision for each guard

`QGCustomPath` omits only an empty public-stroker outline with no fill, a
nonopaque solid-pattern dashed noncosmetic pen (including fully transparent)
of width at least `0.0001`,
transparent background, an affine transform and a known non-PDF/A
`QPdfWriter`/`QPrinter` PDF engine. It delegates the other paint paths. Keeping
this restricted behavior protects builds using unpatched Qt while preserving
its existing fill, opaque/PDF-A, background, transform and width exclusions.

`QGCustomRect` omits `rect().isNull()`: both dimensions are zero, including a
translated null rectangle. It delegates horizontal, vertical, negative and
ordinary rectangles, with the existing selection-state adjustment. The class
also paints outside PDF dimension frames. The PDF qualification cannot justify
global deletion across every painting engine, style and brush.

The recording-engine C++ tests in `QGCustomPath.cpp` and `QGCustomRect.cpp` were
inspected as source contracts. They were not rerun here. The accepted 11
`TestTechDrawGui` Python tests per runtime are a separate test suite. Native
prospective `item.pen()` capture is also not an exhaustive paint-time material
snapshot: `QGIPrimPath` applies its effective pen and brush before delegation.
No exhaustive guard-on/off equivalence is claimed.

## Why removal remains unsupported

`FREECAD_QUALIFIED_QT_PREFIX` provides an authenticated selection path when
explicitly configured. Without it, ordinary CMake discovery can select another
Qt installation; generic LibPack discovery likewise does not authenticate all
catalogued library origins. The fixed packages preserve Qt versions, including
unpatched and corrected 6.11.2. A compile-time version threshold or `qVersion()`
check cannot distinguish these binaries.

The delivery admits the recorded dependencies and native PDF routes. It does
not admit arbitrary system Qt, ambient Python/private PySide Qt copies, or a
subsequently signed/repackaged application. SDK runtime evidence applies to the
documented Qt-first host; bare SDK Python retains its private Qt DLLs. Keeping
both guards introduces no new claim about all null-rectangle painting behavior.
Historical failed runs and stage-specific promotion flags remain unchanged.

Any future removal decision needs a defined scope with authenticated corrected
runtime origins and a concrete reviewed change, including appropriate visible,
opaque/PDF-A, fill/background, transform and zero/tiny-width preservation
controls. Accepted evidence remains reusable unless changed inputs invalidate it.
Retention satisfies this child without making optional deletion or arbitrary Qt
qualification a new outstanding task.

## Review and validation

Independent [Standards/path](mitigation-reviews/standards-evidence.json),
[Spec/evidence](mitigation-reviews/spec-evidence.json) and
[control-mapping](mitigation-reviews/control-mapping.json) reviews recommend
retention of both guards. The [final admission review](mitigation-admission-review.json)
records the completed Standards and Spec checks of this decision. Production guard bytes, dependency pins,
selection helpers and workflows remain unchanged from the starting commit.
This review reused the accepted evidence: no workflow, build, PDF/GUI suite,
rasterization, large payload download or large archive hash was repeated.
