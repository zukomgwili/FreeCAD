# SPDX-License-Identifier: LGPL-2.1-or-later
"""Capture native Qt 6.11.1 candidate tests and inspect transported PDF pairs.

Qt-only checks do not qualify a FreeCAD distribution. The native producer uses
the authenticated Qt-only build and unchanged released baseline; the inspector
checks their retained origins before comparing operators and exact RGBA pixels.
"""

import argparse
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import subprocess
import sys

import build_libpack_backport as adapter
import prepare_libpack_host_tools as host_tools


def json_file(path):
    return json.loads(path.read_text(encoding="utf-8"))


def run_environment(environment, sdk):
    return {
        **environment,
        "PATH": str(sdk / "bin") + os.pathsep + environment["PATH"],
        "QT_PLUGIN_PATH": str(sdk / "plugins"),
        "QT_QPA_PLATFORM_PLUGIN_PATH": str(sdk / "plugins/platforms"),
        "QT_QPA_PLATFORM": "offscreen",
    }


def evidence_files(evidence, helper, excluded):
    return {
        name: entry["sha256"]
        for name, entry in helper.inventory(evidence)["files"].items()
        if name not in excluded
    }


def verify_evidence(evidence, receipt, helper, excluded):
    adapter.require(
        receipt == evidence_files(evidence, helper, excluded),
        "Transported evidence inventory/hash differs",
    )


def validate_host_tools(path, sdk, tools, compiler, host, helper, physical=False):
    """Keep a new test-host admission separate from historical Qt compilation."""
    report = json_file(path)
    adapter.require(
        report["helper_sha256"] == adapter.digest(Path(host_tools.__file__)),
        "Host-tool admission helper bytes differ",
    )
    profile = host_tools.validate_report(report, sdk, tools, compiler, host)
    if physical:
        adapter.require(
            report["producer"] == host_tools.producer_context(),
            "Host-tool admission belongs to another runner/source",
        )
        if profile != "historical-tools":
            adapter.require(
                host_tools.qualification_files(helper) == report["qualification_files_after"],
                "Actual qualification launchers/implementations changed",
            )
        git = host_tools.git_identity(
            host_tools.PROFILES[sdk["architecture"]], sdk["architecture"], helper
        )
        adapter.require(
            git == report["git_distribution"], "Actual original Git distribution changed"
        )
    return report, profile


def installation_admission(evidence, helper, transported=False):
    """Read successful builds or the explicitly pinned failed-install recovery."""
    prefix = "candidate-" if transported else ""
    original = json_file(evidence / (prefix + "build.json"))
    preparation = json_file(evidence / (prefix + "preparation.json"))
    recovery_path = evidence / (prefix + "installation-recovery.json")
    if not recovery_path.exists():
        adapter.require(
            original.get("status") == "built"
            and preparation["helper_sha256"] == adapter.digest(Path(adapter.__file__)),
            "Require a successful current build or explicit authenticated install recovery",
        )
        return original, preparation, None
    recovery = json_file(recovery_path)
    restorer = adapter.load_module(
        "libpack_failed_install_admission",
        Path(__file__).with_name("restore_libpack_failed_install.py"),
    )
    sdk = helper.sdk_identity(original["sdk"]["key"])
    admission = restorer.validate_receipt(recovery, preparation, original, sdk)
    adapter.require(
        adapter.digest(evidence / (prefix + "build.json"))
        == recovery["immutable_original"]["build_sha256"]
        and adapter.digest(evidence / (prefix + "preparation.json"))
        == recovery["immutable_original"]["preparation_sha256"],
        "Historical failed build/preparation bytes differ",
    )
    return admission, preparation, recovery


def admitted_paths(build, evidence, inventory, transported=False):
    """Check the separate finite install(CODE) companion before admission."""
    manifest = set(build["admitted_qt_paths"])
    companions = set(build["admitted_companion_alias_paths"])
    proof = adapter.ownership()["proof"]
    initialized = set(build["source"]["repositories"]) - {"."}
    for field, name in (
        ("qt_install_manifest_receipt", "qt-install-manifest.json"),
        ("qt_finite_install_receipt", "qt-finite-install.json"),
    ):
        path = evidence / name
        adapter.require(
            adapter.digest(path) == build[field + "_sha256"],
            "Finite manifest/source receipt bytes differ",
        )
    raw = json_file(evidence / "qt-install-manifest.json")
    adapter.require(
        raw["schema_version"] == 1
        and raw["qualified"] is False
        and raw["manifest_sha256"] == build["qt_install_manifest_sha256"]
        and raw["unique_paths"] == len(manifest)
        and raw["raw_entries"] == len(manifest) + raw["duplicate_entries"]
        and raw["duplicate_entries"] == len(raw["identical_raw_repetitions"])
        and all(
            count == 2 and name in manifest
            for name, count in raw["identical_raw_repetitions"].items()
        ),
        "Finite raw-manifest repetition receipt differs",
    )
    literal = json_file(evidence / "qt-finite-install.json")
    expected = manifest & set(proof["finite_manifest_paths"])
    entries = {entry["path"]: entry for entry in literal["entries"]}
    bindings = {
        key: proof["finite_install_sources"][key]["sha256"]
        for name in expected
        for key in proof["finite_manifest_paths"][name]["bindings"]
    }
    checkout = proof["finite_windows_checkout_sources"]
    checkout_bindings = {
        key: {"sha256": entry["checkout_sha256"], "size": entry["checkout_size"]}
        for key, entry in checkout["files"].items()
    }
    attribute = checkout["attributes"]
    adapter.require(
        literal["schema_version"] == 1
        and literal["qualified"] is False
        and literal["ownership_proof_sha256"] == adapter.OWNERSHIP_SHA
        and literal["source_bindings"] == bindings
        and literal["source_checkout_bindings"] == checkout_bindings
        and literal["checkout_attribute_sha256"]
        == (attribute["sha256"] if checkout_bindings else None)
        and len(entries) == len(literal["entries"])
        and set(entries) == expected
        and all(
            entry["owner"] == proof["finite_manifest_paths"][name]["owner"]
            and entry["owner"] in initialized
            and entry["kind"] == proof["finite_manifest_paths"][name]["kind"]
            and entry["sha256"] == inventory["files"][name]["sha256"]
            and entry["size"] == inventory["files"][name]["size"]
            for name, entry in entries.items()
        ),
        "Finite installed output/source binding differs",
    )
    if transported and checkout_bindings:
        root = evidence / "qt-checkout-proof"
        expected_checkout = {
            **checkout_bindings,
            attribute["source_path"]: {"sha256": attribute["sha256"], "size": attribute["size"]},
        }
        actual_checkout = adapter.baseline_helper().inventory(root)["files"]
        adapter.require(
            set(actual_checkout) == set(expected_checkout)
            and all(
                actual_checkout[name]["sha256"] == entry["sha256"]
                and actual_checkout[name]["size"] == entry["size"]
                for name, entry in expected_checkout.items()
            ),
            "Finite Windows checkout source/attribute proof differs",
        )
    receipt_path = evidence / "qt-versioned-aliases.json"
    receipt = json_file(receipt_path)
    adapter.require(
        adapter.digest(receipt_path) == build["qt_companion_alias_receipt_sha256"]
        and receipt["qualified"] is False
        and receipt["ownership_proof_sha256"]
        == build["ownership_proof_sha256"]
        == adapter.OWNERSHIP_SHA
        and receipt["factory_sha256"] == proof["versioned_alias_factory"]["source_sha256"],
        "Versioned-tool companion source/receipt differs",
    )
    pairs = {
        entry["stem"]: entry
        for entry in proof["output_aliases"]
        if entry["rule"] == "INSTALL_VERSIONED_LINK plus PROJECT_VERSION_MAJOR=6"
    }
    seen = set()
    for entry in receipt["entries"]:
        alias, base = entry["alias"], entry["manifest_base"]
        alias_path, base_path = adapter.safe_relative(alias), adapter.safe_relative(base)
        pair = pairs.get(alias_path.stem)
        adapter.require(
            alias not in seen
            and base in manifest
            and pair
            and pair["owner"] == entry["owner"]
            and pair["owner"] in initialized
            and base_path.stem == pair["target"]
            and alias_path.parent == base_path.parent
            and alias_path.suffix == base_path.suffix == ".exe"
            and adapter.qt_owned(alias, initialized),
            "Unowned/ambiguous versioned-tool companion",
        )
        seen.add(alias)
        for name in (alias, base):
            adapter.require(
                inventory["files"][name]["sha256"] == entry["sha256"]
                and inventory["files"][name]["size"] == entry["size"],
                "Versioned-tool bytes differ from the manifest base/receipt",
            )
        fragment = adapter.alias_fragment(base, alias)
        adapter.require(
            hashlib.sha256(fragment.encode()).hexdigest() == entry["fragment_sha256"],
            "Versioned-tool generated CODE fragment differs",
        )
    adapter.require(
        seen - manifest == companions,
        "Companion admission differs from its separate install(CODE) entries",
    )
    spdx = set(build.get("admitted_companion_spdx_paths", []))
    if spdx or proof["spdx_companions"]:
        spdx_path = evidence / "qt-spdx-companions.json"
        adapter.require(
            adapter.digest(spdx_path) == build["qt_companion_spdx_receipt_sha256"]
            and adapter.validate_spdx_receipt(
                json_file(spdx_path),
                inventory,
                initialized,
                evidence / "qt-spdx-proof" if transported else None,
            )
            == spdx
            and not spdx & (manifest | companions),
            "Finite SPDX companion receipt differs",
        )
    return manifest | companions | spdx


def retain_spdx_proof(build_root, candidate, source, evidence, receipt, helper):
    """Retain the finite source, generated CODE, log and installed SPDX bytes."""
    proof = evidence / "qt-spdx-proof"
    proof.mkdir()
    names = set()
    for name in receipt["source_bindings"]:
        names.add(("source", name))
    names.add(("build", "build_log.txt"))
    for entry in receipt["entries"]:
        owner = entry["owner"]
        names.update(
            {
                ("build", entry["generated_script"]),
                ("build", owner + "/qt_sbom/assemble_sbom.cmake"),
                ("build", owner + "/qt_sbom/staging-" + owner + ".spdx.in"),
                ("installed", entry["path"]),
            }
        )
    roots = {"source": source, "build": build_root, "installed": candidate}
    for kind, name in sorted(names):
        relative = adapter.safe_relative(name)
        original = helper.real_path(roots[kind] / relative)
        adapter.require(original.is_relative_to(roots[kind]), "SPDX proof escaped its owned root")
        retained = proof / kind / relative
        retained.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, retained)


def retain_checkout_proof(source, evidence, receipt, helper):
    """Retain the six exact Windows checkout templates and their pinned rule."""
    entries = dict(receipt["source_checkout_bindings"])
    if not entries:
        return
    attribute = adapter.ownership()["proof"]["finite_windows_checkout_sources"]["attributes"]
    entries[attribute["source_path"]] = {"sha256": attribute["sha256"], "size": attribute["size"]}
    proof = evidence / "qt-checkout-proof"
    proof.mkdir()
    for name, entry in entries.items():
        relative = adapter.safe_relative(name)
        original = helper.real_path(source / relative)
        adapter.require(
            original.is_relative_to(source)
            and adapter.digest(original) == entry["sha256"]
            and original.stat().st_size == entry["size"],
            "Finite Windows checkout proof changed before retention",
        )
        retained = proof / relative
        retained.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, retained)


def test_sources(source, destination, git, evidence, environment, helper):
    relative = "tests/auto/gui/painting/qpdfwriter"
    adapter.require(
        adapter.command(
            [git, "rev-parse", "HEAD"],
            evidence,
            "upstream-head",
            source,
            environment=environment,
        )
        == adapter.QTBASE_COMMIT,
        "Upstream test repository differs",
    )
    destination.mkdir()
    files = {}
    for name in ("CMakeLists.txt", "tst_qpdfwriter.cpp"):
        original = helper.real_path(source / relative / name)
        committed = subprocess.run(
            [git, "show", "HEAD:" + relative + "/" + name],
            cwd=source,
            env=environment,
            capture_output=True,
            check=True,
        ).stdout
        adapter.require(
            original.read_bytes() == committed and b"SPDX-License-Identifier:" in committed,
            "Upstream test source changed or lacks its original license",
        )
        shutil.copy2(original, destination / name)
        files[name] = adapter.digest(original)
    return {"qtbase_commit": adapter.QTBASE_COMMIT, "files": files}


def capture(args, helper):
    work = helper.real_path(args.build_work_dir)
    build_evidence = helper.real_path(work / "evidence")
    helper.inventory(build_evidence)
    build, preparation, recovery = installation_admission(build_evidence, helper)
    if recovery is not None:
        restorer = adapter.load_module(
            "libpack_failed_install_readback",
            Path(__file__).with_name("restore_libpack_failed_install.py"),
        )
        actual_build, actual_preparation = restorer.validate_restored(work, helper)
        adapter.require(
            (actual_build, actual_preparation) == (build, preparation),
            "Recovered physical SDK admission differs",
        )
    sdk = helper.sdk_identity(build["sdk"]["key"])
    adapter.require(
        build.get("status") in ("built", "installation-revalidated")
        and build.get("qualified") is False
        and build.get("build_only") is True
        and build.get("baseline_unchanged") is True
        and build.get("original_baseline_unchanged") is True
        and build.get("non_qt_preserved") is True
        and build["sdk"] == preparation["sdk"] == sdk
        and (
            recovery is not None
            or preparation["helper_sha256"] == adapter.digest(Path(adapter.__file__))
        )
        and preparation["baseline_helper_sha256"] == adapter.digest(Path(helper.__file__))
        and build["source"]["patch_sha256"] == adapter.PATCH_SHA
        and build["source"]["patched_qpdf_sha256"] == adapter.QPDF_PATCHED,
        "Require a successful authenticated Qt-only candidate build",
    )
    host = helper.native_machine()
    adapter.require(
        host == preparation["host"]
        and host["native_machine"] == helper.MACHINES[sdk["architecture"]]
        and host["python_process_machine"] == 0,
        "Capture requires the original matching native Windows host/Python",
    )
    original, baseline_inventory = adapter.baseline_input(
        Path(preparation["original_baseline"]["evidence"]),
        sdk,
        helper,
    )
    baseline_evidence = Path(original["evidence"])
    baseline = json_file(baseline_evidence / "generation.json")
    candidate = helper.real_path(work / "candidate")
    adapter.require(
        not any(
            Path(sys.executable).resolve().is_relative_to(root)
            for root in (candidate, work / "baseline", Path(original["root"]))
        ),
        "Use a separate tool Python outside every protected SDK",
    )
    before = helper.inventory(candidate)
    adapter.require(
        before == json_file(build_evidence / "candidate-after.json")
        and adapter.digest(build_evidence / "candidate-after.json")
        == build["candidate_inventory_sha256"]
        and helper.inventory(work / "baseline") == baseline_inventory,
        "Built candidate or protected baseline changed",
    )
    initialized = set(build["source"]["repositories"]) - {"."}
    installed = admitted_paths(build, build_evidence, before)
    adapter.preserved_sdk(
        baseline_inventory,
        before,
        installed,
        initialized,
        set(build.get("admitted_companion_spdx_paths", [])),
    )
    adapter.require(
        before["files"]["bin/Qt6Gui.dll"]["sha256"]
        == build["installed_qt_modules"]["Qt6Gui.dll"]["sha256"]
        != baseline_inventory["files"]["bin/Qt6Gui.dll"]["sha256"],
        "Candidate QtGui is unchanged or differs from its completed build receipt",
    )
    destination = helper.real_path(args.work_dir)
    adapter.require(
        not any(char in str(destination) for char in '\r\n"%&|<>^'),
        "Unsafe native test work path",
    )
    for protected in (work, Path(original["root"]), baseline_evidence):
        adapter.separate_path(destination, protected)
    destination = helper.fresh_work(destination)
    evidence = destination / "evidence"
    evidence.mkdir()
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write(f"evidence_dir={evidence}\n")
    report = {
        "schema_version": 1,
        "status": "failed",
        "qualified": False,
        "native_freecad_tested": False,
        "promotion_allowed": False,
        "sdk": sdk,
        "host": host,
        "candidate_sdk": str(candidate),
        "helper_sha256": adapter.digest(Path(__file__)),
        "adapter_sha256": adapter.digest(Path(adapter.__file__)),
        "baseline_helper_sha256": adapter.digest(Path(helper.__file__)),
        "source": build["source"],
        "build_report_sha256": adapter.digest(build_evidence / "build.json"),
        "installation_recovery_sha256": (
            adapter.digest(build_evidence / "installation-recovery.json") if recovery else None
        ),
        "baseline_unchanged": False,
        "candidate_unchanged": False,
    }
    try:
        environment, compiler = helper.compiler_environment(
            destination,
            evidence,
            sdk["architecture"],
        )
        adapter.require(
            compiler["compiler_sha256"] == build["compiler"]["compiler_sha256"]
            and compiler["tools_version"] == build["compiler"]["tools_version"],
            "Test compiler differs from the native candidate build",
        )
        environment = adapter.native_environment(environment, compiler, helper)
        tools = adapter.tool_receipts(
            environment,
            [candidate, work / "baseline", Path(original["root"])],
            helper,
        )
        report["tools"] = tools
        admission_path = getattr(args, "host_tools_report", None)
        if admission_path is None:
            adapter.require(tools == preparation["tools"], "Test build-tool identity changed")
        else:
            admission_path = helper.real_path(admission_path)
            admission, profile = validate_host_tools(
                admission_path, sdk, tools, compiler, host, helper, physical=True
            )
            adapter.require(
                preparation["tools"] == host_tools.PROFILES[sdk["architecture"]]["tools"]
                and adapter.digest(build_evidence / "preparation.json")
                == admission["historical_preparation"]["preparation_sha256"],
                "Host-tool admission historical compilation identity differs",
            )
            shutil.copy2(admission_path, evidence / "host-tools.json")
            report["host_tools_sha256"] = adapter.digest(evidence / "host-tools.json")
            report["host_tools_profile"] = profile
            report["producer"] = admission["producer"]
        report["compiler"] = compiler
        adapter.require(
            adapter.qt_repositories(
                work / "qt", evidence, tools["git"]["path"], environment=environment
            )
            == build["source"]["repositories"],
            "Candidate corresponding source Git identities changed",
        )
        adapter.clean_tracked(
            work / "qt",
            build["source"]["repositories"],
            evidence,
            tools["git"]["path"],
            patched=True,
            environment=environment,
        )
        adapter.require(
            adapter.digest(work / "qt/qtbase/src/gui/painting/qpdf.cpp") == adapter.QPDF_PATCHED,
            "Candidate patched source changed",
        )
        shutil.copytree(baseline_evidence, evidence / "baseline", copy_function=shutil.copy2)
        adapter.write_json(evidence / "candidate-before.json", before)
        for name in ("build.json", "preparation.json"):
            shutil.copy2(build_evidence / name, evidence / ("candidate-" + name))
        if recovery is not None:
            shutil.copy2(
                build_evidence / "installation-recovery.json",
                evidence / "candidate-installation-recovery.json",
            )
        shutil.copy2(
            build_evidence / "qt-versioned-aliases.json", evidence / "qt-versioned-aliases.json"
        )
        for name in ("qt-install-manifest.json", "qt-finite-install.json"):
            shutil.copy2(build_evidence / name, evidence / name)
        install_manifest = helper.real_path(work / "b/r/install_manifest.txt")
        adapter.require(
            adapter.digest(install_manifest) == build["qt_install_manifest_sha256"],
            "Actual Qt install manifest changed",
        )
        manifest_receipt = {}
        adapter.require(
            adapter.install_paths(
                install_manifest, candidate, helper, initialized, manifest_receipt
            )
            == set(build["admitted_qt_paths"])
            and manifest_receipt == json_file(build_evidence / "qt-install-manifest.json")
            and adapter.finite_installation(
                work / "b/r",
                candidate,
                work / "qt",
                set(build["admitted_qt_paths"]),
                initialized,
                helper,
            )
            == json_file(build_evidence / "qt-finite-install.json"),
            "Actual manifest admission differs",
        )
        retain_checkout_proof(
            work / "qt", evidence, json_file(build_evidence / "qt-finite-install.json"), helper
        )
        aliases, alias_receipt = adapter.companion_aliases(
            work / "b/r",
            candidate,
            work / "qt",
            set(build["admitted_qt_paths"]),
            initialized,
            helper,
        )
        adapter.require(
            alias_receipt == json_file(build_evidence / "qt-versioned-aliases.json")
            and aliases - set(build["admitted_qt_paths"])
            == set(build["admitted_companion_alias_paths"]),
            "Actual generated/logged companion install evidence changed",
        )
        if build.get("admitted_companion_spdx_paths"):
            spdx, spdx_receipt = adapter.companion_spdx(
                work / "b/r",
                candidate,
                work / "qt",
                initialized,
                helper,
            )
            adapter.require(
                spdx == set(build["admitted_companion_spdx_paths"])
                and spdx_receipt == json_file(build_evidence / "qt-spdx-companions.json"),
                "Actual generated SPDX companion evidence changed",
            )
            shutil.copy2(
                build_evidence / "qt-spdx-companions.json", evidence / "qt-spdx-companions.json"
            )
            retain_spdx_proof(work / "b/r", candidate, work / "qt", evidence, spdx_receipt, helper)
            adapter.validate_spdx_receipt(
                spdx_receipt, before, initialized, evidence / "qt-spdx-proof"
            )
        shutil.copy2(install_manifest, evidence / "qt-install-manifest.txt")
        shutil.copy2(work / "b/r/build_log.txt", evidence / "qt-install.log")
        for entry in alias_receipt["entries"]:
            relative = adapter.safe_relative(entry["generated_script"])
            original_script = helper.real_path(work / "b/r" / relative)
            retained_script = evidence / "qt-install-scripts" / relative
            retained_script.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original_script, retained_script)
        report["sources"] = baseline["sources"]
        for name, sha in report["sources"].items():
            adapter.require(adapter.digest(helper.FIXTURE / name) == sha, "Fixture source changed")
            shutil.copy2(helper.FIXTURE / name, evidence / name)
        fixture_build = destination / "fixture-build"
        helper.command(
            [
                tools["cmake"]["path"],
                "-S",
                str(helper.FIXTURE),
                "-B",
                str(fixture_build),
                "-G",
                "Ninja",
                "-DCMAKE_BUILD_TYPE=Release",
                "-DWITH_QPRINTER=ON",
                "-DCMAKE_PREFIX_PATH=" + str(candidate),
                "-DQt6_DIR=" + str(candidate / "lib/cmake/Qt6"),
                "-DCMAKE_CXX_COMPILER=" + compiler["compiler"],
            ],
            evidence,
            "fixture-configure",
            environment,
        )
        helper.command(
            [tools["cmake"]["path"], "--build", str(fixture_build), "--parallel", "2"],
            evidence,
            "fixture-build",
            environment,
        )
        executable = helper.real_path(fixture_build / "qt_pdf_stroker_fixture.exe")
        adapter.require(
            not any(fixture_build.glob("*.dll"))
            and helper.pe_machine(executable) == helper.MACHINES[sdk["architecture"]],
            "Fixture architecture differs or application-local DLLs mask SDK origins",
        )
        report["fixture_sha256"] = adapter.digest(executable)
        report["fixture_pe_machine"] = helper.pe_machine(executable)
        runtime_environment = run_environment(environment, candidate)
        pdfs = evidence / "candidate-pdfs"
        helper.command(
            [str(executable), "--output", str(pdfs), "--device", "both"],
            evidence,
            "candidate-generate",
            runtime_environment,
        )
        runtime, manifest = json_file(pdfs / "runtime.json"), json_file(pdfs / "manifest.json")
        adapter.require(
            manifest == json_file(baseline_evidence / "pdfs/manifest.json")
            and len(manifest["cases"]) == 66,
            "Candidate must use the exact paired baseline cases",
        )
        report["modules"] = [
            {
                "path": entry["path"],
                "sdk_relative_path": PureWindowsPath(entry["path"])
                .relative_to(PureWindowsPath(candidate))
                .as_posix(),
                "sha256": adapter.digest(helper.real_path(Path(entry["path"]))),
                "pe_machine": helper.pe_machine(Path(entry["path"])),
                "file_version": helper.file_version(Path(entry["path"])),
            }
            for entry in runtime["qt_modules"]
        ]
        helper.verify_runtime(
            runtime, manifest, str(candidate), before, sdk["architecture"], report["modules"]
        )
        upstream_source = evidence / "upstream-source"
        report["upstream_sources"] = test_sources(
            work / "qt/qtbase",
            upstream_source,
            tools["git"]["path"],
            evidence,
            environment,
            helper,
        )
        upstream_build = destination / "upstream-build"
        helper.command(
            [
                tools["cmake"]["path"],
                "-S",
                str(upstream_source),
                "-B",
                str(upstream_build),
                "-G",
                "Ninja",
                "-DCMAKE_BUILD_TYPE=Release",
                "-DCMAKE_PREFIX_PATH=" + str(candidate),
                "-DCMAKE_CXX_COMPILER=" + compiler["compiler"],
                *[
                    "-D" + component + "_DIR=" + str(candidate / "lib/cmake" / component)
                    for component in ("Qt6", "Qt6Core", "Qt6Gui", "Qt6Test", "Qt6BuildInternals")
                ],
            ],
            evidence,
            "upstream-configure",
            environment,
        )
        helper.command(
            [tools["cmake"]["path"], "--build", str(upstream_build), "--parallel", "2"],
            evidence,
            "upstream-build",
            environment,
        )
        test = helper.real_path(upstream_build / "tst_qpdfwriter.exe")
        adapter.require(
            not any(upstream_build.glob("*.dll"))
            and helper.pe_machine(test) == helper.MACHINES[sdk["architecture"]],
            "Upstream test has unexpected local DLLs/architecture",
        )
        test_environment = adapter.load_module(
            "qt_pdf_qtest_logging", Path(__file__).with_name("qtest_logging.py")
        ).qtest_child_environment(runtime_environment)
        suite = adapter.command(
            [str(test)],
            evidence,
            "upstream-tests",
            cwd=destination,
            environment=test_environment,
        )
        adapter.require(
            re.search(r"Totals:\s+10 passed,\s+0 failed,\s+0 skipped,\s+0 blacklisted", suite)
            and "QtTest library 6.11.1, Qt 6.11.1" in suite,
            "Complete upstream Qt 6.11.1 suite did not pass all ten cases",
        )
        report["upstream_suite"] = {
            "passed": True,
            "test_cases": 10,
            "executable_sha256": adapter.digest(test),
            "log_sha256": adapter.digest(evidence / "upstream-tests.log"),
        }
        report["status"] = "captured"
    except BaseException as error:
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        report["candidate_unchanged"] = helper.inventory(candidate) == before
        report["baseline_unchanged"] = (
            helper.inventory(Path(original["root"])) == baseline_inventory
            and helper.inventory(work / "baseline") == baseline_inventory
        )
        if not report["candidate_unchanged"] or not report["baseline_unchanged"]:
            report["status"] = "failed"
        report["evidence_sha256"] = evidence_files(evidence, helper, {"capture.json"})
        adapter.write_json(evidence / "capture.json", report)
    adapter.require(report["status"] == "captured", "Candidate capture/preservation failed")
    return report


def inspect(args, helper):
    evidence = helper.real_path(args.evidence_dir)
    capture_report = json_file(evidence / "capture.json")
    destination = helper.real_path(args.report)
    renders = helper.real_path(destination.with_suffix(".renders"))
    adapter.require(
        destination.parent.is_dir() and not destination.exists() and not renders.exists(),
        "Inspection report/renders must be fresh with an existing parent",
    )
    baseline = json_file(evidence / "baseline/generation.json")
    for output in (destination, renders):
        for sdk_root in (baseline["sdk_root"], capture_report["candidate_sdk"]):
            helper.check_output_location(output, evidence, sdk_root)
    report = {
        "schema_version": 1,
        "status": "failed",
        "qualified": False,
        "qt_only_passed": False,
        "native_freecad_tested": False,
        "promotion_allowed": False,
        "runtime_proof_scope": "Native DLL origins/hashes/PE/version receipts verified against "
        "retained native inventories; SDK/DLL bytes are not rehosted on this inspection host.",
    }
    try:
        adapter.require(
            capture_report["status"] == "captured"
            and capture_report["qualified"] is False
            and capture_report["baseline_unchanged"] is True
            and capture_report["candidate_unchanged"] is True
            and capture_report["helper_sha256"] == adapter.digest(Path(__file__))
            and capture_report["adapter_sha256"] == adapter.digest(Path(adapter.__file__))
            and capture_report["baseline_helper_sha256"] == adapter.digest(Path(helper.__file__)),
            "Native capture/helper/preservation proof differs",
        )
        verify_evidence(evidence, capture_report["evidence_sha256"], helper, {"capture.json"})
        verify_evidence(
            evidence / "baseline", baseline["evidence_sha256"], helper, {"generation.json"}
        )
        sdk = helper.sdk_identity(capture_report["sdk"]["key"])
        adapter.require(
            capture_report["sdk"] == baseline["sdk"] == sdk
            and baseline["status"] == "generated"
            and baseline["baseline_only"] is True
            and baseline["qualified"] is False
            and baseline["sdk_unchanged"] is True
            and baseline["archive_sha256_verified"] is True
            and baseline["candidate_sdk"] is None
            and PureWindowsPath(baseline["sdk_root"]).name == sdk["directory"],
            "Released baseline capture identity differs",
        )
        architecture = helper.MACHINES[sdk["architecture"]]
        for native_report in (baseline, capture_report):
            adapter.require(
                native_report["host"]["native_machine"] == architecture
                and native_report["host"]["python_process_machine"] == 0
                and native_report["fixture_pe_machine"] == architecture,
                "Native host/fixture architecture differs",
            )
        adapter.require(
            capture_report["compiler"]["compiler_sha256"] == baseline["compiler"]["compiler_sha256"]
            and capture_report["compiler"]["tools_version"] == baseline["compiler"]["tools_version"]
            and re.fullmatch(r"14\.4\d\.\d+", baseline["compiler"]["tools_version"]),
            "Baseline/candidate compiler receipts differ",
        )
        before = json_file(evidence / "baseline/sdk-before.json")
        candidate = json_file(evidence / "candidate-before.json")
        adapter.require(
            before == json_file(evidence / "baseline/sdk-after.json"),
            "Baseline before/after inventories differ",
        )
        build, preparation, recovery = installation_admission(evidence, helper, transported=True)
        if capture_report.get("host_tools_sha256"):
            admission_path = evidence / "host-tools.json"
            adapter.require(
                adapter.digest(admission_path) == capture_report["host_tools_sha256"],
                "Retained test-host admission changed",
            )
            admission, profile = validate_host_tools(
                admission_path,
                sdk,
                capture_report["tools"],
                capture_report["compiler"],
                capture_report["host"],
                helper,
            )
            adapter.require(
                capture_report["host_tools_profile"] == profile
                and capture_report["producer"] == admission["producer"]
                and preparation["tools"] == host_tools.PROFILES[sdk["architecture"]]["tools"]
                and adapter.digest(evidence / "candidate-preparation.json")
                == admission["historical_preparation"]["preparation_sha256"],
                "Test-host admission differs from retained historical compilation",
            )
        else:
            adapter.require(
                capture_report["tools"] == preparation["tools"],
                "Unadmitted test-host tools differ from historical compilation",
            )
        adapter.require(
            capture_report.get("installation_recovery_sha256")
            == (
                adapter.digest(evidence / "candidate-installation-recovery.json")
                if recovery
                else None
            ),
            "Capture/recovery receipt binding differs",
        )
        adapter.require(
            adapter.digest(evidence / "candidate-build.json")
            == capture_report["build_report_sha256"]
            and build["status"] in ("built", "installation-revalidated")
            and build["qualified"] is False
            and build["baseline_unchanged"]
            and build["original_baseline_unchanged"]
            and build["non_qt_preserved"]
            and build["sdk"] == preparation["sdk"] == sdk
            and (
                recovery is not None
                or preparation["helper_sha256"] == adapter.digest(Path(adapter.__file__))
            )
            and preparation["source_pin"] == adapter.SOURCES[sdk["release"]]
            and preparation["qt_commit"] == adapter.QT_COMMIT
            and build["source_commit"] == adapter.SOURCES[sdk["release"]]["commit"]
            and build["source"] == capture_report["source"]
            and build["source"]["patch_sha256"] == adapter.PATCH_SHA
            and build["source"]["original_qpdf_sha256"] == adapter.QPDF_ORIGINAL
            and build["source"]["patched_qpdf_sha256"] == adapter.QPDF_PATCHED,
            "Captured Qt-only build/patched source proof differs",
        )
        repositories = build["source"]["repositories"]
        owner_gitlinks = adapter.ownership()["proof"]["owner_repository_gitlinks"]
        adapter.require(
            repositories.get(".") == adapter.QT_COMMIT
            and repositories.get("qtbase") == adapter.QTBASE_COMMIT
            and adapter.SELECTED_MODULES <= set(repositories)
            and all(
                repositories[owner] == sha
                for owner, sha in owner_gitlinks.items()
                if owner in repositories
            ),
            "Captured selected/conditional ownership Git identities differ",
        )
        adapter.require(
            adapter.digest(evidence / "candidate-before.json")
            == build["candidate_inventory_sha256"],
            "Candidate inventory differs from its completed build receipt",
        )
        initialized = set(build["source"]["repositories"]) - {"."}
        installed = admitted_paths(build, evidence, candidate, transported=True)
        adapter.preserved_sdk(
            before,
            candidate,
            installed,
            initialized,
            set(build.get("admitted_companion_spdx_paths", [])),
        )
        receipt = json_file(evidence / "qt-versioned-aliases.json")
        adapter.require(
            adapter.digest(evidence / "qt-install-manifest.txt")
            == build["qt_install_manifest_sha256"]
            and adapter.digest(evidence / "qt-install.log") == receipt["actual_install_log_sha256"],
            "Transported actual installation manifest/log differs",
        )
        for entry in receipt["entries"]:
            script = (
                evidence / "qt-install-scripts" / adapter.safe_relative(entry["generated_script"])
            )
            adapter.require(
                adapter.digest(script) == entry["generated_script_sha256"]
                and script.read_text().count(
                    adapter.alias_fragment(entry["manifest_base"], entry["alias"])
                )
                == 1
                and entry["actual_install_log_line"]
                in (evidence / "qt-install.log").read_text().splitlines(),
                "Transported generated/logged install(CODE) companion differs",
            )
        adapter.require(
            candidate["files"]["bin/Qt6Gui.dll"]["sha256"]
            == build["installed_qt_modules"]["Qt6Gui.dll"]["sha256"]
            != before["files"]["bin/Qt6Gui.dll"]["sha256"],
            "Candidate QtGui is unchanged or differs from the completed build",
        )
        adapter.require(
            capture_report["upstream_suite"]["passed"] is True
            and capture_report["upstream_suite"]["test_cases"] == 10
            and capture_report["upstream_sources"]["qtbase_commit"] == adapter.QTBASE_COMMIT
            and set(capture_report["upstream_sources"]["files"])
            == {"CMakeLists.txt", "tst_qpdfwriter.cpp"},
            "Incomplete upstream suite/source receipts",
        )
        for name, sha in capture_report["upstream_sources"]["files"].items():
            adapter.require(
                adapter.digest(evidence / "upstream-source" / name) == sha,
                "Retained upstream test source differs",
            )
        suite = (evidence / "upstream-tests.log").read_text()
        adapter.require(
            adapter.digest(evidence / "upstream-tests.log")
            == capture_report["upstream_suite"]["log_sha256"]
            and re.search(r"Totals:\s+10 passed,\s+0 failed,\s+0 skipped,\s+0 blacklisted", suite)
            and "QtTest library 6.11.1, Qt 6.11.1" in suite,
            "Upstream test log differs or is incomplete",
        )
        adapter.require(
            capture_report["sources"] == baseline["sources"]
            and set(baseline["sources"]) == {"generator.cpp", "CMakeLists.txt", "compare.py"},
            "Fixture source receipts differ",
        )
        for name, sha in baseline["sources"].items():
            adapter.require(
                adapter.digest(evidence / name)
                == adapter.digest(evidence / "baseline" / name)
                == adapter.digest(helper.FIXTURE / name)
                == sha,
                "Fixture source differs from the inspection checkout",
            )
        directories = {
            "baseline": evidence / "baseline/pdfs",
            "patched": evidence / "candidate-pdfs",
        }
        runtimes = {}
        for side, native, inventory, root in (
            ("baseline", baseline, before, baseline["sdk_root"]),
            ("patched", capture_report, candidate, capture_report["candidate_sdk"]),
        ):
            manifest = json_file(directories[side] / "manifest.json")
            runtime = json_file(directories[side] / "runtime.json")
            adapter.require(
                len(manifest["cases"]) == 66 and manifest["raster_dpi"] == 100,
                "Expected the complete 66-case matrix at100dpi",
            )
            helper.verify_runtime(
                runtime, manifest, root, inventory, sdk["architecture"], native["modules"]
            )
            runtimes[directories[side]] = {
                **runtime,
                "digests_verified": False,
                "native_receipts_verified": True,
                "expected_native_sdk": root,
            }
        renders.mkdir()
        copied = {}
        for side, directory in directories.items():
            copied[side] = renders / side
            shutil.copytree(directory, copied[side], copy_function=shutil.copy2)
            runtimes[copied[side]] = runtimes[directory]
        comparison = adapter.load_module(
            "libpack_portable_comparison", helper.FIXTURE / "compare.py"
        )

        def transported_runtime(directory, manifest, prefix=None, plugin_dir=None, required=False):
            # Native receipts above replace on-disk DLL reads on this Linux host.
            adapter.require(
                directory in runtimes and prefix is None and plugin_dir is None and required,
                "Unexpected portable runtime inspection request",
            )
            adapter.require(
                json_file(directory / "manifest.json") == manifest,
                "Compared manifest differs from the validated native capture",
            )
            return runtimes[directory]

        comparison.inspect_runtime = transported_runtime
        pdftoppm = shutil.which("pdftoppm")
        adapter.require(pdftoppm, "Poppler pdftoppm is required")
        result = comparison.compare(
            copied["baseline"], copied["patched"], pdftoppm, require_runtime=True
        )
        adapter.require(
            set(result["baseline_reproduced_by_device"]) == {"qpdfwriter", "qprinter"}
            and len(result["cases"]) == 66,
            "Both complete PDF devices are required",
        )
        report.update(
            {
                "sdk": sdk,
                "native_capture_sha256": adapter.digest(evidence / "capture.json"),
                "inspection_helper_sha256": adapter.digest(Path(__file__)),
                "comparison": result,
                "upstream_suite": capture_report["upstream_suite"],
                "checking_versions": {
                    "python": sys.version,
                    "pypdf": version("pypdf"),
                    "Pillow": version("Pillow"),
                },
                "qt_only_passed": result["passed"],
                "status": "passed" if result["passed"] else "failed",
            }
        )
    except (OSError, ValueError, KeyError) as error:
        report["error"] = str(error)
    adapter.write_json(destination, report)
    adapter.require(report["qt_only_passed"], report.get("error", "PDF comparison failed"))
    return report


def main():
    sys.dont_write_bytecode = True
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    producer = actions.add_parser("capture")
    producer.add_argument("--build-work-dir", type=Path, required=True)
    producer.add_argument("--work-dir", type=Path, required=True)
    producer.add_argument("--host-tools-report", type=Path)
    inspector = actions.add_parser("inspect")
    inspector.add_argument("--evidence-dir", type=Path, required=True)
    inspector.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    helper = adapter.baseline_helper()
    try:
        result = capture(args, helper) if args.action == "capture" else inspect(args, helper)
        print(json.dumps({"status": result["status"], "qualified": False}))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
