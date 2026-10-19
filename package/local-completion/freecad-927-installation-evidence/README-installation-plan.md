# FreeCAD-927 host-local installation bundle

This bundle is preparation only. Its scripts have not been run. The root agent
must read this complete bundle and obtain independent plan review before launch.
No source, application, dependency prefix, user profile or original retained
Oomakhi fixture was changed by bundle preparation.

The clean source/build identity is
f0c43f0a9368eaab7d469d825d1a3e75bff90903, 49261 +213 (Git).
The installed baseline is 5591e8e388bf3506450cb407f784b89064804ddc,
49261 +205 (Git). Replacement remains
/Applications/FreeCAD-27.1.0.app; rollback is the unique
/Users/zukomgwili/Applications/FreeCAD Backups/FreeCAD-27.1.0-before-927-5591e8e388.app.

## Staging boundary

The first approved command is below. It captures all 16 critical file lstat/hash
identities immediately before running CMake with a private DESTDIR. These are
pixi.toml, pixi.lock, CMakeCache.txt, the patched Cocoa plugin, ordinary ccx, and
the 11 external freecad namespace files. They are checked again in every
finally path. The configured CMAKE_INSTALL_PREFIX remains the app Resources
path; DESTDIR redirects every payload output to this private directory.

    pixi run --frozen python /private/tmp/freecad-927-install.O8eMXG/run_step.py payload

An optional explicit separate pre-DESTDIR capture is available by running
critical_pins.py capture with the same Pixi/Python prefix. Do not repeat capture
after staging. Existing receipts and logs are never overwritten. Each invocation
is bounded, monitors its owned process descendants, cleans up only its own PID
identities/process group, and requires no live FreeCAD.

After independent read-only payload review, staging is:

    pixi run --frozen python /private/tmp/freecad-927-install.O8eMXG/run_step.py stage

This copies the signed baseline literally, preserves dependency symlinks,
overlays only private DESTDIR output, verifies the external namespace unchanged,
signs with original QuickLook sandbox entitlements, restores the exact already
qualified signed accounting solver leaf, and seals Resources read-only/cache-free.
Fem.so and FemGui.so receive build/payload/app code-body and load-command parity
checks with only signature bookkeeping and install-time LC_RPATH normalization;
payload/app RPATH lists must be identical. Materials/MatGui parity remains.
The 37 compiled-input hashes include the native FEM adapter/workbench sources,
registrations, scripts/tests, Version.h, CMakeCache and actual FEM/material modules.

## Per-location qualification

All following commands are invoked separately through run_step.py, in the same
serial session and only after the root agent has read/reviewed their implementation.
The step argument is shown; each line means the prefix
pixi run --frozen python /private/tmp/freecad-927-install.O8eMXG/run_step.py.

    stage:sequence
    stage:native-cmd
    stage:native-gui
    stage:4jb-cmd
    stage:4jb-gui
    stage:analytic
    stage:disjoint
    stage:typed-compile
    stage:typed-gui
    stage:typed-cold

The sequence first runs InstalledIdentity plus actual TestFemApp (373 tests), then
the ten existing generic lifecycle/CLI/GUI/feature/equilibrium/mixed/area gates
and both actual-process exit-status suites. GUI includes actual TestFemGui
(7 tests) in addition to TechDraw/Materials. Discovery requires the exact
4 observation, 14 source, 10 native, 9 movement, 6 mesh-to-VTK and 15 owned-probe
tests; each must actually execute without skipping. The 4 observation GUI IDs
must likewise execute without skipping. All production/test imports must come
from the app being tested, never source/build fallback. Fem/FemGui loaded image
paths and hashes are explicitly checked.

The native observation tests create fresh unrelated CAD/Gmsh/writer/CalculiX
sources, exercise missing-owner refusal and PointSide selectors, and perform
actual separate-process cold historical restore and a fresh native rerun.
They do not re-solve the retained original engineering fixture or calculate
gap/slip engineering acceptance.

## Replacement and post-move qualification

After all stage gates pass and the independent stage/custody reviews pass:

    pixi run --frozen python /private/tmp/freecad-927-install.O8eMXG/run_step.py swap

The old app moves to the unique backup and the sealed stage moves to Applications
on the same filesystem. Failures during swap restore the original app. No
dependency helper/namespace swap or profile migration is performed.

The following ten distinct steps use the installed path and new isolated
installed profiles; no saved stage data is copied into them:

    installed:sequence
    installed:native-cmd
    installed:native-gui
    installed:4jb-cmd
    installed:4jb-gui
    installed:analytic
    installed:disjoint
    installed:typed-compile
    installed:typed-gui
    installed:typed-cold

AccountingData binds the exact executable path and signed hash. Therefore staged
saved observations remain historical evidence after the move; they are never
path-rewritten/rebound or reused as installed-current proof. The installed
TestFemApp invocation must create fresh native sources and save/cold checks.

Final read-only audit is:

    pixi run --frozen python /private/tmp/freecad-927-install.O8eMXG/run_step.py final-audit

The final audit retains the existing independent receipt contracts:
independent-payload-audit.json must contain passed/commit/payload_native_count;
independent-stage-audit.json must contain passed/source_commit/native_payload_parity_count;
independent-stage-custody.json must contain passed/compiled_commit.
Those independent reviews are not manufactured by this bundle and must bind
the current commit. The final audit additionally checks both app locations'
fresh FEM/GUI evidence, all legacy/native/typed gates, exact rollback baseline,
literal namespace/dependency identities, original profiles and signatures.
An installed test failure stops completion; the original signed backup remains
recoverable. No automatic engineering acceptance or upstream publication occurs.

## Static preparation check

All 19 Python scripts were parsed with ast.parse only: no installer module was
imported and no native app or solver was launched. bundle-manifest.json records
the final private source/custody hashes and their derivation from the proven 3sc
installer. The root agent owns actual execution and installation decisions.
