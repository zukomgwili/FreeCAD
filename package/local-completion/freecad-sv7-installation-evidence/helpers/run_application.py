"""Bounded literal bundle tests with private profiles and exact custody."""

import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

sys.dont_write_bytecode = True
import critical_pins
import run_gate
import stage_install as install

ROOT = Path(__file__).resolve().parent
COUNTS = {"cmd": 31, "gui": 6, "cold": 1}


def sha(path):
    return install.digest(Path(path))


def profiles():
    critical_pins.verify()
    return {str(p): install.canonical_sha(install.inventory(p)) for p in install.PROFILES}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("location", choices=("stage", "installed"))
    parser.add_argument("mode", choices=tuple(COUNTS))
    args = parser.parse_args()
    run_gate.serial()
    install.compiled_identity()
    application = install.STAGE if args.location == "stage" else install.APP
    assert application.resolve(strict=True) == application and not application.is_symlink()
    sealed_path = ROOT / "stage-inventory.json"
    sealed = json.loads(sealed_path.read_text())
    assert install.inventory(application) == sealed
    install.verify(application)
    original = install.canonical_sha(install.inventory(install.APP))
    before_profiles = profiles()
    run = ROOT / (args.location + "-" + args.mode)
    run.mkdir()
    temporary = run / "dotted.parent"
    temporary.mkdir()
    environment = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(
            ("FREECAD_", "CCX_", "DYLD_", "LD_", "APPQA_", "ISV7_", "I960_", "B960_", "SV7_")
        )
        and k
        not in (
            "PYTHONPATH",
            "PYTHONHOME",
            "XDG_CONFIG_HOME",
            "XDG_DATA_HOME",
            "XDG_CACHE_HOME",
            "TMPDIR",
            "TMP",
            "TEMP",
            "DESTDIR",
        )
    }
    for key in (
        "FREECAD_USER_HOME",
        "FREECAD_USER_DATA",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
    ):
        path = run / key.lower()
        path.mkdir()
        environment[key] = str(path)
    environment.update(
        TMPDIR=str(temporary) + "/",
        TMP=str(temporary),
        TEMP=str(temporary),
        FREECAD_USER_TEMP=str(temporary),
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONNOUSERSITE="1",
        OMP_NUM_THREADS="2",
        ISV7_APP=str(application),
        ISV7_MODE=args.mode,
        ISV7_IDENTITY=str(ROOT / "identity.json"),
        B960_WITNESS_ROOT=str(run),
        SV7_CASE_ROOT=str(run / "coupled"),
        SV7_WITNESS_ROOT=str(run / "coupled"),
    )
    extra = [sealed_path, ROOT / "identity.json"]
    if args.mode == "cold":
        priors = {mode: ROOT / (args.location + "-" + mode) for mode in ("cmd", "gui")}
        for mode, prior in priors.items():
            proof = json.loads((prior / "execution.json").read_text())
            assert proof["passed"] is True and proof["application"] == str(application)
            assert proof["mode"] == mode and proof["location"] == args.location
            assert proof["source_commit"] == install.COMMIT
            assert (
                proof["revision"] == install.REVISION
                and proof["native_sha256"] == install.NATIVE_SHA
            )
            extra += [prior / "execution.json", prior / "regression.json"]
        legacy = (
            priors["gui"]
            / "test_visible_solver_write_and_run_saves_current_native_beam_end_actions"
        )
        v2 = (
            priors["cmd"]
            / "coupled/test_series_beam_ground_spring_and_restraints_share_one_owned_frame"
        )
        v3 = (
            priors["cmd"]
            / "coupled/test_hybrid_actions_solid_patch_and_native_beam_component_control"
        )
        cases = []
        for schema, folder, document_name, literal_name, literal_bytes_match in (
            ("CCX_BEAM_SECTION_V1", legacy, "native-beam-gui.FCStd", "saved-output.json", True),
            ("CCX_BEAM_SECTION_V2", v2, "series.FCStd", "observed.json", False),
            ("CCX_BEAM_SECTION_V3", v3, "hybrid.FCStd", "observed.json", False),
        ):
            document = folder / document_name
            literal = folder / literal_name
            assert document.is_file() and literal.is_file()
            assert not document.is_symlink() and not literal.is_symlink()
            extra += [document, literal]
            cases.append(
                {
                    "schema": schema,
                    "document": str(document),
                    "document_sha256": sha(document),
                    "literal": str(literal),
                    "literal_sha256": sha(literal),
                    "literal_bytes_match": literal_bytes_match,
                }
            )
        environment["ISV7_COLD_CASES"] = json.dumps(cases, sort_keys=True)
    resources = application / "Contents/Resources"
    extra += [install.REPO / name for name in install.SOURCES]
    extra += [resources / name for name in install.SOURCES.values()]
    extra += [
        resources / name
        for name in ("bin/FreeCAD", "bin/FreeCADCmd", "data/NativeSolvers/ccx-force-accounting")
    ]

    def inputs():
        return {str(p): sha(p) for p in sorted(set(extra) | set(ROOT.glob("*.py")))}

    before = inputs()
    executable = "FreeCAD" if args.mode == "gui" else "FreeCADCmd"
    module = "ColdBeamSv7" if args.mode == "cold" else "AppBeamSv7"
    command = [
        str(application / "Contents/MacOS" / executable),
        "-u",
        str(run / "user.cfg"),
        "-s",
        str(run / "system.cfg"),
        "-P",
        str(ROOT),
        "-t",
        module,
    ]
    report = {
        "schema": "FreeCAD-sv7-literal-application-gate-v1",
        "passed": False,
        "application": str(application),
        "location": args.location,
        "mode": args.mode,
        "source_commit": install.COMMIT,
        "revision": install.REVISION,
        "native_sha256": install.NATIVE_SHA,
        "expected_tests": COUNTS[args.mode],
        "command": command,
        "inputs_before": before,
        "source_or_build_import_override": False,
        "native_solver_override": False,
    }
    started = time.monotonic()
    timed_out = False
    child = None
    try:
        with (run / "run.log").open("xb") as output:
            child = subprocess.Popen(
                command,
                cwd=run,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                child.wait(timeout=900)
            except subprocess.TimeoutExpired:
                timed_out = True
            finally:
                for number in (signal.SIGTERM, signal.SIGKILL):
                    if child.poll() is None or run_gate.group_exists(child.pid):
                        try:
                            os.killpg(child.pid, number)
                        except ProcessLookupError:
                            pass
                        try:
                            child.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            pass
        text = (run / "run.log").read_text(errors="replace")
        counts = re.findall(r"^Ran (\d+) tests? in [0-9.]+s$", text, re.M)
        skipped = re.findall(r"^.*\.\.\. skipped.*$", text, re.M)
        reg_path = run / "regression.json"
        reg = json.loads(reg_path.read_text()) if reg_path.exists() else {}
        valid = (
            counts == [str(COUNTS[args.mode])]
            and len(re.findall(r"^OK$", text, re.M)) == 1
            and not skipped
            and not re.search(r"^(?:FAILED|FAIL:|ERROR:|UNEXPECTED SUCCESS)", text, re.M)
            and reg.get("passed") is True
            and reg.get("application") == str(application)
            and reg.get("commit") == install.COMMIT
            and reg.get("mode") == args.mode
            and reg.get("schema") == "FreeCAD-sv7-installation-regression-v1"
            and reg.get("revision") == install.REVISION
            and reg.get("gui") is (args.mode == "gui")
            and reg.get("skipped") == reg.get("failures") == reg.get("errors") == []
            and set(reg.get("selected_test_ids", [])) == install.expected_ids(args.mode)
            and reg.get("expected_tests") == reg.get("executed_tests") == COUNTS[args.mode]
            and reg.get("native_sha256") == install.NATIVE_SHA
        )
        after = inputs()
        current = install.inventory(application)
        install.verify(application)
        install.compiled_identity()
        run_gate.serial()
        report.update(
            returncode=child.returncode,
            timed_out=timed_out,
            child_reaped=child.poll() is not None,
            process_group_gone=not run_gate.group_exists(child.pid),
            executed_tests=int(counts[0]) if len(counts) == 1 else 0,
            skipped_lines=skipped,
            inputs_after=after,
            inputs_unchanged=before == after,
            application_unchanged=current == sealed,
            application_inventory_sha256=install.canonical_sha(current),
            profiles_and_dependencies_unchanged=before_profiles == profiles(),
            original_app_unchanged=original
            == install.canonical_sha(install.inventory(install.APP)),
            strict_signature_verified=True,
            log_sha256=sha(run / "run.log"),
            regression_sha256=sha(reg_path) if reg_path.exists() else None,
            semantic_tests_passed=valid,
        )
        report["passed"] = bool(
            child.returncode == 0
            and not timed_out
            and valid
            and all(
                report[key]
                for key in (
                    "child_reaped",
                    "process_group_gone",
                    "inputs_unchanged",
                    "application_unchanged",
                    "profiles_and_dependencies_unchanged",
                    "original_app_unchanged",
                    "strict_signature_verified",
                )
            )
        )
    except BaseException as error:
        report["supervisor_error"] = repr(error)
        raise
    finally:
        report["elapsed_seconds"] = time.monotonic() - started
        install.write_json(run / "execution.json", report)
        print(
            json.dumps(
                {k: v for k, v in report.items() if k not in ("inputs_before", "inputs_after")},
                indent=2,
            )
        )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
