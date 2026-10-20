"""Private serial Release build / CTest gates; never install or solve.

Usage: pixi run --frozen python -B run_build_gate.py NEW_LABEL {build,ctest}
Only the two fixed commands below are permitted. Evidence and isolated profiles
are created under a fresh label beside this script; existing logs are untouched.
"""

import sys
sys.dont_write_bytecode = True

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parent
REPOSITORY = Path("/Users/zukomgwili/src/FreeCAD")
BUILD = REPOSITORY / "build/release"
TIMEOUT = 600
COMMANDS = {
    "build": ["pixi", "run", "--frozen", "cmake", "--build", "build/release", "--parallel", "8"],
    "ctest": ["pixi", "run", "--frozen", "ctest", "--test-dir", "build/release",
              "--output-on-failure", "--parallel", "8", "--timeout", "60"],
}
FEM_INPUTS = (
    "ObjectsFem.py", "TestFemApp.py", "TestFemGui.py",
    "femtools/force_accounting.py", "femtest/app/test_force_accounting.py",
    "femresult/contact_observation.py", "femresult/contact_observation_source.py",
    "femobjects/result_contact_observation.py", "femcommands/commands.py",
    "femtest/app/test_tie_accounting_native.py", "femtest/gui/test_contact_observation.py",
    "femtest/app/test_movement_provenance.py",
    "femmesh/meshsetsgetter.py", "femmesh/meshtools.py", "femmesh/ownership_context.py",
    "femsolver/calculix/calculixutils.py", "femsolver/calculix/writer.py",
    "femsolver/writerbase.py", "femsolver/calculix/write_constraint_tie.py",
    "femsolver/calculix/write_constraint_contact.py", "femtools/ccxtools.py",
    "femtools/femutils.py", "femtools/membertools.py",
    "femtest/app/test_tie_ownership.py", "femtest/app/test_contact_ownership.py",
    "femtest/app/test_rigid_region_ownership.py",
    "femtest/app/test_moving_port_accounting_native.py",
    "femobjects/solver_ccxtools.py",
    "femsolver/calculix/write_constraint_elastic_connector.py",
)
TEMPORARY = BUILD / "Testing/Temporary"


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def source_snapshot():
    paths = [Path(__file__).resolve(), REPOSITORY / "CMakeLists.txt",
             REPOSITORY / "src/Mod/Fem/CMakeLists.txt",
             REPOSITORY / "package/calculix/force-accounting/forceaccounting.c",
             REPOSITORY / "package/calculix/force-accounting/hooks.patch",
             REPOSITORY / "package/calculix/force-accounting/contract.json",
             REPOSITORY / "package/local-completion/calculix-9zt-probe/build_probe.py"]
    paths += [REPOSITORY / "src/Mod/Fem" / relative for relative in FEM_INPUTS]
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPOSITORY,
                          check=True, capture_output=True, text=True, timeout=10).stdout.strip()
    return {"git_head": head, "files": {str(path): digest(path) for path in paths}}


def build_snapshot(require_current):
    paths = [BUILD / "src/Build/Version.h", BUILD / "bin/FreeCADCmd", BUILD / "bin/FreeCAD",
             BUILD / "Mod/Fem/Fem.so", BUILD / "Mod/Fem/FemGui.so",
             BUILD / "data/NativeSolvers/ccx-force-accounting"]
    paths += [BUILD / "Mod/Fem" / relative for relative in FEM_INPUTS]
    files = {str(path): digest(path) for path in paths if path.is_file()}
    if require_current:
        if len(files) != len(paths):
            raise RuntimeError("Required Release build files are missing")
        for relative in FEM_INPUTS:
            if digest(REPOSITORY / "src/Mod/Fem" / relative) != digest(BUILD / "Mod/Fem" / relative):
                raise RuntimeError("Build copy differs from source: " + relative)
    header = BUILD / "src/Build/Version.h"
    macros = {}
    if header.is_file():
        macros = dict(re.findall(r'^#define\s+(FC\w+)\s+"([^"\n]*)"', header.read_text(), re.M))
    return {"files": files, "version_header": macros}


def file_observation(path):
    path = Path(path)
    if not path.is_file():
        return {"exists": False}
    stat = path.stat()
    return {"exists": True, "sha256": digest(path), "bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns, "inode": stat.st_ino}


def serial_guard():
    result = subprocess.run(["/bin/ps", "-axo", "pid=,comm="], check=True,
                            capture_output=True, text=True, timeout=10)
    names = {"FreeCAD", "FreeCADCmd", "ctest", "ccx", "ccx-force-accounting",
             "ninja", "make", "gmake"}
    conflicts = []
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) == 2 and (Path(fields[1]).name in names
                                 or Path(fields[1]).name.startswith("ccx_")):
            conflicts.append(line.strip())
    if conflicts:
        raise RuntimeError("Run serially; native/build/test/solver process active: " + repr(conflicts))


def group_exists(child):
    try:
        os.killpg(child.pid, 0)
        return True
    except ProcessLookupError:
        return False


def cleanup(child, report):
    # Signal only this supervisor's new session, never a name-matched process.
    for sig in (signal.SIGTERM, signal.SIGKILL):
        deadline = time.monotonic() + 5
        try:
            os.killpg(child.pid, sig)
        except ProcessLookupError:
            pass
        try:
            child.wait(timeout=max(0.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            report.setdefault("cleanup_timeouts", []).append(int(sig))
        while group_exists(child) and time.monotonic() < deadline:
            time.sleep(0.05)
        if child.poll() is not None and not group_exists(child):
            return
    report["cleanup_failed"] = True


def ctest_summary(log):
    rows = []
    for match in re.finditer(r'^\s*(\d+)/(\d+)\s+Test\s+#(\d+):[^\r\n]*$', log, re.M):
        line = match.group(0).strip()
        if "***Not Run (Disabled)" in line:
            status = "disabled"
        elif "***Skipped" in line:
            status = "skipped"
        elif re.search(r'\bPassed\s+[\d.]+\s+sec\s*$', line):
            status = "passed"
        else:
            status = "failed_or_unknown"
        rows.append({"ordinal": int(match[1]), "catalogue": int(match[2]),
                     "test_number": int(match[3]), "status": status, "line": line})
    if not rows or len({row["catalogue"] for row in rows}) != 1:
        raise RuntimeError("Missing or inconsistent CTest catalogue rows")
    count = rows[0]["catalogue"]
    expected = set(range(1, count + 1))
    if (len(rows) != count or {row["ordinal"] for row in rows} != expected
            or {row["test_number"] for row in rows} != expected):
        raise RuntimeError("CTest log does not contain one complete, unique catalogue")
    summaries = re.findall(
        r'^(\d+)% tests passed(?:, (\d+) tests failed)? out of (\d+)\s*$', log, re.M)
    elapsed = re.findall(r'^Total Test time \(real\) =\s*([\d.]+) sec\s*$', log, re.M)
    if len(summaries) != 1 or len(elapsed) != 1:
        raise RuntimeError("Missing or duplicate terminal CTest result")
    totals = {status: sum(row["status"] == status for row in rows)
              for status in ("passed", "skipped", "disabled", "failed_or_unknown")}
    percent, failures, enabled = (int(value or 0) for value in summaries[0])
    if (percent != 100 or failures != 0 or totals["failed_or_unknown"]
            or enabled != count - totals["disabled"]
            or totals["passed"] + totals["skipped"] != enabled):
        raise RuntimeError("CTest terminal summary and complete per-test outcomes do not agree/pass")
    return {"catalogue": count, "enabled": enabled, "executed_passing": totals["passed"],
            "skipped": totals["skipped"], "disabled": totals["disabled"], "failed": failures,
            "real_seconds": float(elapsed[0]), "complete_catalogue_verified": True,
            "skipped_rows": [row for row in rows if row["status"] == "skipped"],
            "disabled_rows": [row for row in rows if row["status"] == "disabled"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("label")
    parser.add_argument("mode", choices=tuple(COMMANDS))
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", args.label):
        parser.error("Labels must contain only alphanumerics, hyphens and underscores")
    with (ROOT / "build-gate-serial.lock").open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        serial_guard()
        source_before = source_snapshot()
        build_before = build_snapshot(args.mode == "ctest")
        prior_logs = {name: file_observation(TEMPORARY / name) for name in
                      ("LastTest.log", "LastTestsFailed.log", "LastTestsDisabled.log")}
        run = ROOT / args.label
        run.mkdir(exist_ok=False)
        environment = dict(os.environ)
        for key in list(environment):
            if key.startswith(("FREECAD_", "RO1_", "CCX_FORCE_ACCOUNTING_", "CCX_9ZT_")) or key in (
                    "PYTHONPATH", "PYTHONHOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME"):
                environment.pop(key, None)
        for key in ("FREECAD_USER_HOME", "FREECAD_USER_DATA", "FREECAD_USER_TEMP",
                    "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME"):
            directory = run / key.lower()
            directory.mkdir()
            environment[key] = str(directory)
        environment.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
                            "OMP_NUM_THREADS": "2", "TMPDIR": environment["FREECAD_USER_TEMP"]})
        dot_free_temp = None
        if args.mode == "ctest":
            # A separately tracked Base::FileInfo extension bug misparses an
            # extensionless filename beneath any dotted ancestor directory.
            # Preserve the two failed dotted runs; do not change product code
            # or omit tests. Use an explicitly reported private dot-free root.
            dot_free_temp = tempfile.mkdtemp(prefix="freecad-ywu-ctest-", dir="/private/tmp")
            if "." in dot_free_temp:
                raise RuntimeError("CTest temporary root must be dot-free")
            environment["TMPDIR"] = dot_free_temp
            environment["FREECAD_USER_TEMP"] = dot_free_temp
        command = COMMANDS[args.mode]
        log_path = run / "run.log"
        report = {"passed": False, "mode": args.mode, "command": command,
                  "cwd": str(REPOSITORY), "timeout_seconds": TIMEOUT, "timed_out": False,
                  "source_before": source_before, "build_before": build_before,
                  "prior_ctest_logs": prior_logs, "log": str(log_path), "installation_performed": False}
        report["private_dot_free_temporary_root"] = dot_free_temp
        report["dotted_temporary_directory_product_bug_fixed"] = False
        child = None
        started, wall_started_ns = time.monotonic(), time.time_ns()
        try:
            serial_guard()
            print(json.dumps({"status": "starting", "command": command, "log": str(log_path)}), flush=True)
            with log_path.open("xb") as output:
                child = subprocess.Popen(command, cwd=REPOSITORY, env=environment,
                                         stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
                report["pid"] = child.pid
                try:
                    report["exit_code"] = child.wait(timeout=TIMEOUT)
                except subprocess.TimeoutExpired:
                    report["timed_out"] = True
                    cleanup(child, report)
                    report["exit_code"] = child.returncode
                    raise RuntimeError("Bounded gate timed out; owned process group terminated")
            if report["exit_code"] != 0:
                raise RuntimeError("Gate exited " + str(report["exit_code"]))
            if args.mode == "ctest":
                report["ctest"] = ctest_summary(log_path.read_text(errors="replace"))
                report["ctest_logs_after"] = {}
                for name, before in prior_logs.items():
                    path = TEMPORARY / name
                    after = file_observation(path)
                    fresh = (after.get("exists", False) and after != before
                             and after["mtime_ns"] >= wall_started_ns)
                    report["ctest_logs_after"][name] = {**after, "fresh_for_this_run": fresh,
                        "classification": "fresh" if fresh else "absent_or_stale_not_current_evidence"}
                    if fresh:
                        text = path.read_text(errors="replace")
                        with (run / name).open("x") as output:
                            output.write(text)
                        if name == "LastTestsFailed.log" and text.strip():
                            raise RuntimeError("Fresh LastTestsFailed log contradicts successful current result")
                if not report["ctest_logs_after"]["LastTest.log"]["fresh_for_this_run"]:
                    raise RuntimeError("CTest did not generate a fresh LastTest log")
            report["build_after"] = build_snapshot(True)
            if args.mode == "ctest" and report["build_after"] != build_before:
                raise RuntimeError("Build/native identity changed during CTest")
            report["passed"] = True
        except BaseException as error:
            report["error"] = repr(error)
        finally:
            if child is not None:
                if child.poll() is None or group_exists(child):
                    cleanup(child, report)
                report["process_reaped"] = child.poll() is not None
                report["owned_group_gone"] = not group_exists(child)
            try:
                report["source_after"] = source_snapshot()
                report["source_and_supervisor_unchanged"] = report["source_after"] == source_before
                if not report["source_and_supervisor_unchanged"]:
                    raise RuntimeError("Source, commit or supervisor changed during the gate")
            except BaseException as error:
                report["passed"] = False
                report["source_fence_error"] = repr(error)
            if (not report.get("process_reaped") or not report.get("owned_group_gone")
                    or report.get("cleanup_failed")):
                report["passed"] = False
            report["elapsed_seconds"] = round(time.monotonic() - started, 3)
            if log_path.is_file():
                report["log_sha256"] = digest(log_path)
            with (run / "execution.json").open("x") as output:
                output.write(json.dumps(report, indent=2) + "\n")
            print(json.dumps(report, indent=2), flush=True)
        return 0 if report["passed"] else 1


if __name__ == "__main__":
    def interrupted(signum, _frame):
        raise InterruptedError("Build gate interrupted by signal " + str(signum))

    for watched in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(watched, interrupted)
    raise SystemExit(main())
