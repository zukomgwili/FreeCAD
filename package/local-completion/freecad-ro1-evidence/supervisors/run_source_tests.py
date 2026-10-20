"""Bounded private build-tree tests; never run alongside CTest or another native suite.

Usage: pixi run --frozen python /private/tmp/freecad-ro1.VmcpuR/run_source_tests.py
       LABEL {cmd,gui} [DOTTED_TEST_SUITE ...] [--timeout SECONDS]
Defaults: cmd=femtest.app.test_tie_ownership; gui=TestFemGui.
Each LABEL is exclusive and all profiles/evidence are created beneath this directory.
This does not build, install, alter source, or force-close any existing application.
"""

import sys
sys.dont_write_bytecode = True

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

ROOT = Path(__file__).resolve().parent
REPOSITORY = Path("/Users/zukomgwili/src/FreeCAD")
BUILD = REPOSITORY / "build/release"
FEM_INPUTS = (
    "ObjectsFem.py", "TestFemApp.py", "TestFemGui.py",
    "femmesh/meshsetsgetter.py", "femmesh/meshtools.py", "femmesh/ownership_context.py",
    "femsolver/calculix/write_constraint_tie.py", "femsolver/calculix/write_constraint_contact.py",
    "femtools/ccxtools.py", "femtest/app/test_tie_ownership.py",
    "femtools/femutils.py", "femtools/membertools.py",
    "femtest/app/test_contact_ownership.py", "femtest/app/test_rigid_region_ownership.py",
)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshots(gui):
    paths = [REPOSITORY / "src/Mod/Fem/CMakeLists.txt", BUILD / "src/Build/Version.h",
             ROOT / "SourceNativeIdentity.py", ROOT / "run_source_tests.py"]
    for relative in FEM_INPUTS:
        original = REPOSITORY / "src/Mod/Fem" / relative
        copied = BUILD / "Mod/Fem" / relative
        if digest(original) != digest(copied):
            raise RuntimeError(f"Build is not current for {relative}; build before testing")
        paths.extend((original, copied))
    paths += [BUILD / "Mod/Fem/Fem.so", BUILD / "bin/FreeCADCmd"]
    if gui:
        paths += [BUILD / "Mod/Fem/FemGui.so", BUILD / "bin/FreeCAD"]
    return {str(path): digest(path) for path in paths}


def native_preflight():
    result = subprocess.run(["/bin/ps", "-axo", "pid=,comm="], check=True,
                            capture_output=True, text=True, timeout=10)
    conflicts = []
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) == 2 and Path(fields[1]).name in ("FreeCAD", "FreeCADCmd", "ctest"):
            conflicts.append(line.strip())
    if conflicts:
        raise RuntimeError("Run serially; existing native/test processes: " + repr(conflicts))


def owned_group_exists(child):
    try:
        os.killpg(child.pid, 0)
        return True
    except ProcessLookupError:
        return False


def stop_owned_group(child, report):
    # Only a session created by this supervisor is signalled; no process-name kills.
    for sig, grace in ((signal.SIGTERM, 5), (signal.SIGKILL, 5)):
        deadline = time.monotonic() + grace
        try:
            os.killpg(child.pid, sig)
        except ProcessLookupError:
            pass
        try:
            child.wait(timeout=max(0.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            report.setdefault("cleanup_timeouts", []).append(int(sig))
        while owned_group_exists(child) and time.monotonic() < deadline:
            time.sleep(0.05)
        if child.poll() is not None and not owned_group_exists(child):
            return
    report["cleanup_failed"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("label")
    parser.add_argument("mode", choices=("cmd", "gui"))
    parser.add_argument("suites", nargs="*")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", args.label):
        parser.error("LABEL must contain only alphanumerics, hyphens and underscores")
    if not 1 <= args.timeout <= 180:
        parser.error("Timeout must be between 1 and 180 seconds")
    gui = args.mode == "gui"
    suites = args.suites or (["TestFemGui"] if gui else ["femtest.app.test_tie_ownership"])
    for suite in suites:
        if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", suite):
            parser.error("Suites must be dotted Python test names")
    if len(suites) != len(set(suites)) or "SourceNativeIdentity" in suites:
        parser.error("Duplicate suites or an explicit identity observer are not allowed")
    native_preflight()
    before = snapshots(gui)
    run = ROOT / args.label
    run.mkdir(exist_ok=False)
    environment = dict(os.environ)
    for key in list(environment):
        if key.startswith(("FREECAD_", "RO1_", "CCX_FORCE_ACCOUNTING_", "CCX_9ZT_")) or key in (
                "PYTHONPATH", "PYTHONHOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME"):
            environment.pop(key, None)
    for key in ("FREECAD_USER_HOME", "FREECAD_USER_DATA", "FREECAD_USER_TEMP",
                "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME"):
        path = run / key.lower()
        path.mkdir()
        environment[key] = str(path)
    identity_path = run / "identity.json"
    log_path = run / "run.log"
    environment.update({
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "OMP_NUM_THREADS": "2",
        "TMPDIR": environment["FREECAD_USER_TEMP"], "RO1_TEST_MODE": args.mode,
        "RO1_IDENTITY_REPORT": str(identity_path), "RO1_TEST_SUITES": json.dumps(suites),
    })
    executable = BUILD / "bin" / ("FreeCAD" if gui else "FreeCADCmd")
    command = ["pixi", "run", "--frozen", str(executable),
               "-u", str(run / "user.cfg"), "-s", str(run / "system.cfg"),
               "-P", str(ROOT), "-t", "SourceNativeIdentity"]
    for suite in suites:
        command += ["-t", suite]
    report = {"passed": False, "label": args.label, "mode": args.mode, "command": command,
              "cwd": str(REPOSITORY), "suites": suites, "timeout_seconds": args.timeout,
              "timed_out": False, "process_reaped": False, "inputs_before": before,
              "log": str(log_path), "identity_report": str(identity_path)}
    started = time.monotonic()
    child = None
    try:
        print(json.dumps({"status": "starting", "command": command, "log": str(log_path)}),
              flush=True)
        with log_path.open("xb") as output:
            child = subprocess.Popen(command, cwd=REPOSITORY, env=environment,
                                     stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            report["pid"] = child.pid
            try:
                report["exit_code"] = child.wait(timeout=args.timeout)
            except subprocess.TimeoutExpired:
                report["timed_out"] = True
                stop_owned_group(child, report)
                report["exit_code"] = child.returncode
                raise RuntimeError("Native test timeout; owned child group terminated")
        if report["exit_code"] != 0:
            raise RuntimeError(f"Native launcher exited {report['exit_code']}")
        log = log_path.read_text(errors="replace")
        counts = re.findall(r"^Ran (\d+) tests? in ([\d.]+)s\s*$", log, re.M)
        outcomes = re.findall(r"^OK(?: \(([^\n]*)\))?\s*$", log, re.M)
        if len(counts) != 1 or len(outcomes) != 1 or re.search(
                r"^(?:FAILED\b|FAIL:|ERROR:|UNEXPECTED SUCCESS:)", log, re.M):
            raise RuntimeError("Missing/duplicate/failed normal unittest result")
        identity = json.loads(identity_path.read_text())
        if not identity["passed"] or bool(identity["gui_up"]) != gui:
            raise RuntimeError("Build identity observer did not pass")
        count, seconds = counts[0]
        if int(count) != identity["expected_total_count"]:
            raise RuntimeError("Discovered/executed test counts differ")
        report["unittest"] = {"count": int(count), "seconds": float(seconds), "outcome": "OK",
                              "details": outcomes[0], "expected_count": identity["expected_total_count"]}
        report["unittest"]["skipped_lines"] = re.findall(
            r"^([^\n]+) \.\.\. skipped ([^\n]+)$", log, re.M)
        report["unittest"]["expected_failure_lines"] = re.findall(
            r"^([^\n]+) \.\.\. expected failure\s*$", log, re.M)
        for suite in identity["configured_suites"].values():
            for test_id in suite["ids"]:
                if ".TestTieOwnership." not in test_id:
                    continue
                method = test_id.rsplit(".", 1)[-1]
                if not re.search(r"^" + re.escape(method) + r" \(", log, re.M):
                    raise RuntimeError(f"Missing executed Tie regression {test_id}")
                if re.search(r"^" + re.escape(method) + r" \([^\n]*skipped", log, re.M):
                    raise RuntimeError(f"Skipped Tie regression {test_id}")
        report["configured_suite_counts"] = {
            name: suite["count"] for name, suite in identity["configured_suites"].items()}
        report["runtime"] = identity["runtime"]
        report["passed"] = True
    except BaseException as error:
        report["error"] = repr(error)
    finally:
        if child is not None:
            if child.poll() is None or owned_group_exists(child):
                stop_owned_group(child, report)
            report["process_reaped"] = child.poll() is not None
            report["owned_group_gone"] = not owned_group_exists(child)
        try:
            report["inputs_after"] = snapshots(gui)
            report["source_and_build_unchanged"] = report["inputs_after"] == before
            if not report["source_and_build_unchanged"]:
                raise RuntimeError("Source/build/native/harness inputs changed during test")
        except BaseException as error:
            report["passed"] = False
            report["input_check_error"] = repr(error)
        if (not report["process_reaped"] or not report.get("owned_group_gone", False)
                or report.get("cleanup_failed")):
            report["passed"] = False
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        if log_path.exists():
            report["log_sha256"] = digest(log_path)
        if identity_path.exists():
            report["identity_sha256"] = digest(identity_path)
        with (run / "execution.json").open("x") as handle:
            handle.write(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
