# FreeCAD fork sync and upstream contribution assessment

Checked **7 October 2026**. This is AI-assisted research for the fork owner's review, not an upstream PR description or a certification of personal responsibility. The assessment is tracked as `FreeCAD-bm8`; one discovered packaging follow-up is `FreeCAD-a04`.

## Recommendation

Preserve the customized fork and prepare focused contribution branches from current upstream main. Select only the relevant source and regression tests. A full fork-main PR or an unfiltered cherry-pick would carry unrelated tracking, dependency delivery and machine-local evidence. Begin with the small MoveProperty test-isolation fix; BIM restoration is another strong candidate. The two TechDraw mitigations deserve their own maintainer review. These are suitability recommendations, not an acceptance guarantee.

## Frozen comparison and the sync conflict

The audit used [fork main `2d9ef80eff`](https://github.com/zukomgwili/FreeCAD/commit/2d9ef80eff9c343f3e98cd0aed393337bc27b41a), [upstream main `876271d660`](https://github.com/FreeCAD/FreeCAD/commit/876271d6605a47805742e34c88cf31993398bdf9), and merge base `171a7c1f521664bd88f02d75509f37b6a9bcd901`. Fork history is **94 commits ahead and 7 behind**: 80 fork-only non-merge commits and 14 merge commits. Its change from the merge base is 128 paths, 106,549 added lines and 337 deleted lines, including substantial qualification evidence.

An in-memory `git merge-tree` simulation found exactly one conflict, in `.github/workflows/sub_releaseWindowsLibpack.yml`. Both sides alter the CMake selection:

| Side | Setting |
|---|---|
| Common base | `cmake-version: '3.31.6'` |
| Fork | `cmake-version: ${{ inputs.arch == 'arm64' && '4.4.3' || '3.31.6' }}` |
| Upstream | `cmake-version: '4.4.3'` |

Upstream changed this in [commit `a5889ea6c4`](https://github.com/FreeCAD/FreeCAD/commit/a5889ea6c4cbcaa82dd8ba8840bedf3ca7f3bdf5); the fork changed the line in `b1a1a340ec1f9edaa7a2a4734eb272f933889cab`. The merge simulation changed no branch, working files or real index.

GitHub documents a resolution-PR prompt when Sync fork encounters conflicts. This does not require contributing all fork changes upstream. A local merge of upstream into the customized fork can resolve synchronization independently. Check the base repository/branch: it receives changes. A contribution targets `FreeCAD/FreeCAD:main`; updating your fork targets your fork. The exact dialog the user saw was not observed. [GitHub fork synchronization](https://docs.github.com/en/pull-requests/how-tos/work-with-forks/syncing-a-fork), [fork PR direction](https://docs.github.com/en/pull-requests/how-tos/create-pull-requests/creating-a-pull-request-from-a-fork)

Keep the fork's conditional version until its x64/ARM rationale is reviewed, or deliberately adopt upstream's common version and validate that integration. This report does not select a resolution or claim the automatically merged tree works. Avoid a forced sync/reset: it overwrites fork-main work unless that work has first been preserved elsewhere. Synchronization and contribution are separate decisions.

## Focused contribution candidates

All listed fixes remain absent from the pinned upstream source. Every original implementation commit also modifies `.beads/issues.jsonl`, so none is suitable for a whole-commit cherry-pick without cleanup. The companion JSON gives exact source/test allowlists.

| Contribution | Original commit | Preparation notes |
|---|---|---|
| Parallel MoveProperty persistence-test file isolation | [`dda6f9c7d7`](https://github.com/zukomgwili/FreeCAD/commit/dda6f9c7d74a8ac8d7d673fd2a9dcf61ae943cbb) / fork PR #8 | Smallest initial candidate: two test files, existing TempDirectory helper, no application behavior change. |
| BIM Structure proxy-state restoration | [`cc7240952a`](https://github.com/zukomgwili/FreeCAD/commit/cc7240952a5100b4bea009dcc3d49f40a754b58e) / #1 | Source plus serialization/FCStd tests; add truthful assistance disclosure. |
| BIM Wall/Stairs proxy-state restoration | [`a098b92403`](https://github.com/zukomgwili/FreeCAD/commit/a098b9240328c765083f5403513905bb6611da0f) / #2 | Related serialization problem; no hard dependency on #1; review legacy-state differences if combining. |
| TechDraw null dimension-frame PDF guard | [`fbf129bf96`](https://github.com/zukomgwili/FreeCAD/commit/fbf129bf964a056a07fa671f5a2c024baf899121) / #3 | Guard, paint tests and reproducer; explain behavior for other painting devices/rectangle cases. |
| TechDraw empty dashed-gap PDF guard | [`8ff248985a`](https://github.com/zukomgwili/FreeCAD/commit/8ff248985a7ced2d8903f393bfb3a7cf596f1344) / #4 | More intricate PDF emulation guard; its test CMake hunk depends on #3's Gui test directory/wiring. |
| Draft endpoint-expression documentation and regression tests | [`f081899bbc`](https://github.com/zukomgwili/FreeCAD/commit/f081899bbcf502ed92e0b5fb143811f160e0780b) / #7 | Documents existing recompute/placement contract; does not change constructor behavior. |
| PyCXX include precedence | [`2b90ac8904`](https://github.com/zukomgwili/FreeCAD/commit/2b90ac89046ac6cc76bb3284f8a27a49bb82c58c) / #6 subset | Extract only `src/Base/CMakeLists.txt`; mixed commit contains seven other paths. Review header warnings and both internal/external PyCXX modes. |

Seven source/test subsets passed textual `git apply --cached --check` against the pinned upstream tree in private temporary indexes. The dashed-gap subset was checked with the selected null-frame subset already applied to its temporary index. This proves patch application only: no candidate branch was checked out or built, and no tests/workflows were run.

A bounded upstream issue/PR search found no exact duplicate in the inspected results. That is not an exhaustive absence claim. [Merged PR #23841](https://github.com/FreeCAD/FreeCAD/pull/23841) supplies MoveProperty context. [Merged PR #28708](https://github.com/FreeCAD/FreeCAD/pull/28708) and [issue #30210](https://github.com/FreeCAD/FreeCAD/issues/30210) explain external-PyCXX support/compatibility, which the include fix must preserve. Related BIM search hits concerned different bugs. No upstream PR by `zukomgwili` was returned in the current author search.

## Material to keep in the fork

Exclude `.beads`, local `AGENTS.md`, machine installation/diagnostic receipts, and bulk qualification archives from ordinary source-fix PRs. Fork PR #6 alone has 68 commits, 89 paths and 101,742 added lines. Its Qt pins and LibPack catalogue use personal-fork release URLs; workflows and recovery tools bind repository names, run IDs and historical runtime identities. Sustainable upstream hosting/ownership and workflow scope require maintainer agreement before that infrastructure is proposed.

The underlying serializer correction in `tests/src/Mod/TechDraw/Gui/QtPdfStroker/empty-outline.patch` modifies QtBase, rather than FreeCAD production source. Route that focused fix and a Qt-owned regression through Qt, then coordinate dependency backports. [Inspected Qt dev source](https://github.com/qt/qtbase/blob/eb7095e03e7b09ac0469050c78fb9df06a2605d3/src/gui/painting/qpdf.cpp#L614) still has the unconditional close/fill route. This is a source observation, not qualification of Qt dev binaries or an assessment of Qt's contribution requirements.

An unrelated deletion needs review: [housekeeping commit `b236ed4bff`](https://github.com/zukomgwili/FreeCAD/commit/b236ed4bffb18716773e7a5e18a8b764de9a8e05) removes the macOS app template's Info.plist, three icons and qt.conf. [Upstream retains the template](https://github.com/FreeCAD/FreeCAD/tree/876271d6605a47805742e34c88cf31993398bdf9/src/MacAppBundle/FreeCAD.app/Contents), and [bundle setup copies it](https://github.com/FreeCAD/FreeCAD/blob/876271d6605a47805742e34c88cf31993398bdf9/cMake/FreeCAD_Helpers/InitializeFreeCADBuildOptions.cmake#L125). The commit does not explain why. `FreeCAD-a04` tracks intent/restore review; these deletions should be excluded from feature contributions. The currently installed app was assembled separately with this bundle option off and was not modified here.

## Contribution compliance assessment

The current process favors one identified, agreed problem per PR and concise logical history. It requires compatible licensing/style, independently compiling commits, project self-tests across target platforms, proper author attribution, and presentation of GUI changes. Checkpoint history should be squashed. These rules describe submission readiness; passing historical fork tests alone does not establish a new upstream branch's integration result. The process also notes its transition/guideline status. [Contribution process](https://github.com/FreeCAD/FreeCAD/blob/876271d6605a47805742e34c88cf31993398bdf9/CONTRIBUTING.md)

The AI policy requires human understanding, review/testing and communication, with disclosure in commit trailers and PR prose. It rejects clearly AI-generated code, commit messages, descriptions and reviewer responses. A trailer alone is insufficient. You must personally review the selected patch, write upstream communication/commit text, explain it to maintainers and affirm the responsibility checkbox. [AI policy](https://github.com/FreeCAD/FreeCAD/blob/876271d6605a47805742e34c88cf31993398bdf9/AI_POLICY.md), [PR template](https://github.com/FreeCAD/FreeCAD/blob/876271d6605a47805742e34c88cf31993398bdf9/.github/pull_request_template.md)

Of 80 non-merge fork commits, 75 contain `Assisted-by:`. The two BIM implementation commits lack it; three other missing trailers belong to local housekeeping/build notes. Fork PRs #3–5 disclose assistance and leave the human checkbox unchecked; #1–2 and #6–10 lack explicit disclosure/checkbox text. These personal-fork observations do not establish an already rejected upstream submission. Prepared AI-assisted candidate commits need accurate disclosure; rewriting the preserved fork history is unnecessary.

Use module-focused imperative commit subjects, the actual current pre-commit configuration and surrounding-code formatting; avoid unrelated reformatting. Check licensing/SPDX headers and third-party provenance. [Code review guidance](https://freecad.github.io/DevelopersHandbook/bestpractices/codereview.html), [formatting guidance](https://freecad.github.io/DevelopersHandbook/codeformatting/), [pinned pre-commit configuration](https://github.com/FreeCAD/FreeCAD/blob/876271d6605a47805742e34c88cf31993398bdf9/.pre-commit-config.yaml)

Remove `[skip ci]` from prepared upstream HEAD commit messages. It suppresses push/pull_request workflows, and skipped required checks can remain pending. The marker served a different purpose in evidence-only fork commits. Allow the required checks for the actual final source branch; this assessment did not rerun existing qualification workflows. [GitHub skipped-workflow rules](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/skip-workflow-runs)

## How to prepare without losing fork work

Use a separate checkout/worktree rooted at current upstream main for each logical contribution. Keep the installed app's existing `.pixi/envs/default` runtime prefix intact. Extract the allowlisted source/test hunks rather than fork merge commits; preserve truthful original authorship. For example, the MoveProperty subset is the diff of `dda6f9c7d7^..dda6f9c7d7` restricted to `tests/src/App/Property.cpp` and `tests/src/App/Property.h`. The assessment has checked this subset's application, but has not created the contribution branch.

Then review the final patch personally, write the commit/PR explanation and accurate disclosure in your own words, identify the upstream problem and relevant maintainer discussion, include focused regression evidence and GUI images where applicable, and run the required checks on that new branch. Start with MoveProperty and BIM; discuss the more involved TechDraw, PyCXX and dependency-delivery work separately. Maintainers determine acceptance.

The source-linked assessment and [machine-readable evidence](upstream-contribution-assessment-2026-10-07.json) are recorded on a separate documentation branch in the personal fork. Existing fork main and upstream branches are unchanged. No upstream issue/PR/comment or responsibility affirmation was made. No real sync/merge/reset, build, app change or workflow/test rerun was performed.
