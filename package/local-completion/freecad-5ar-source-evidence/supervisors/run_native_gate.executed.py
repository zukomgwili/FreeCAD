"""Bounded, serial, isolated-profile native Tie capability supervisor.

Usage: pixi run --frozen python -B /private/tmp/freecad-5ar-wYCAxF/run_native_tie_probe.py LABEL
Fresh LABEL only.  A genuine missing capability exits nonzero with retained
normal native unittest failure.  No source, installation or user profile edits.
"""

import sys
sys.dont_write_bytecode = True

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import time


ROOT = Path(__file__).resolve().parent
REPOSITORY = Path("/Users/zukomgwili/src/FreeCAD")
BUILD = REPOSITORY / "build/release"
FEM_INPUTS = (
    "femtest/app/test_force_accounting.py", "ObjectsFem.py", "femmesh/gmshtools.py", "femmesh/meshsetsgetter.py",
    "femmesh/meshtools.py", "femmesh/ownership_context.py", "femtools/ccxtools.py",
    "femtools/force_accounting.py", "femresult/contact_observation.py",
    "femtools/femutils.py", "femtools/membertools.py",
    "femsolver/calculix/writer.py", "femsolver/calculix/write_constraint_tie.py",
    "femsolver/calculix/write_constraint_sectionprint.py",
)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshots():
    paths = [Path(__file__).resolve(),
             REPOSITORY / "package/local-completion/FreeCAD9ztProductionWitness.py",
             REPOSITORY / "package/calculix/force-accounting/contract.json",
             
             BUILD / "src/Build/Version.h", BUILD / "bin/FreeCADCmd",
             BUILD / "Mod/Fem/Fem.so", BUILD / "Mod/Part/Part.so",
             BUILD / "lib/FreeCAD.so", BUILD / "lib/libFreeCADApp.dylib",
             BUILD / "data/NativeSolvers/ccx-force-accounting"]
    for relative in FEM_INPUTS:
        original = REPOSITORY / "src/Mod/Fem" / relative
        copied = BUILD / "Mod/Fem" / relative
        if digest(original) != digest(copied):
            raise RuntimeError(f"Build is not current for {relative}; build before testing")
        paths.extend((original, copied))
    return {str(path): digest(path) for path in paths}


def native_preflight():
    result = subprocess.run(["/bin/ps", "-axo", "pid=,comm="], check=True,
                            capture_output=True, text=True, timeout=10)
    conflicts = []
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) != 2:
            continue
        name = Path(fields[1]).name
        if name in ("FreeCAD", "FreeCADCmd", "ctest", "ccx", "ccx-force-accounting") or name.startswith("ccx_"):
            conflicts.append(line.strip())
    if conflicts:
        raise RuntimeError("Run serially; existing native/test/solver processes: " + repr(conflicts))


def group_exists(child):
    try:
        os.killpg(child.pid, 0)
        return True
    except ProcessLookupError:
        return False


def stop_owned_group(child, report):
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
        while group_exists(child) and time.monotonic() < deadline:
            time.sleep(0.05)
        if child.poll() is not None and not group_exists(child):
            return
    report["cleanup_failed"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("label")
    parser.add_argument("--module", required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", args.label):
        parser.error("LABEL must contain only alphanumerics, hyphens and underscores")
    if not 1 <= args.timeout <= 180:
        parser.error("Timeout must be 1..180 seconds")
    native_preflight()
    before = snapshots()
    run = ROOT / args.label
    run.mkdir(exist_ok=False)
    environment = dict(os.environ)
    for key in list(environment):
        if key.startswith(("FREECAD_", "FIVEAR_", "RO1_", "CCX_FORCE_ACCOUNTING_", "CCX_9ZT_")) or key in (
                "PYTHONPATH", "PYTHONHOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME"):
            environment.pop(key, None)
    for key in ("FREECAD_USER_HOME", "FREECAD_USER_DATA", "FREECAD_USER_TEMP",
                "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME"):
        private = run / key.lower()
        private.mkdir()
        environment[key] = str(private)
    environment.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
                        "OMP_NUM_THREADS": "2", "TMPDIR": environment["FREECAD_USER_TEMP"],
                        "FIVEAR_RUN": str(run)})
    command = ["pixi", "run", "--frozen", str(BUILD / "bin/FreeCADCmd"),
               "-u", str(run / "user.cfg"), "-s", str(run / "system.cfg"),
               "-P", str(ROOT), "-t", args.module]
    log_path = run / "run.log"
    report = {"passed": False, "label": args.label, "command": command,
              "cwd": str(REPOSITORY), "timeout_seconds": args.timeout, "inputs_before": before,
              "timed_out": False, "process_reaped": False, "log": str(log_path)}
    started = time.monotonic()
    child = None
    try:
        print(json.dumps({"status": "starting", "command": command}), flush=True)
        with log_path.open("xb") as log:
            child = subprocess.Popen(command, cwd=REPOSITORY, env=environment,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     start_new_session=True)
            report["pid"] = child.pid
            selector = selectors.DefaultSelector()
            selector.register(child.stdout, selectors.EVENT_READ)
            while selector.get_map():
                if time.monotonic() - started >= args.timeout:
                    report["timed_out"] = True
                    stop_owned_group(child, report)
                    raise RuntimeError("Native capability timeout; owned child group terminated")
                for key, _ in selector.select(timeout=0.2):
                    block = os.read(key.fd, 65536)
                    if not block:
                        selector.unregister(key.fileobj)
                        continue
                    log.write(block)
                    log.flush()
                    sys.stdout.write(block.decode(errors="replace"))
                    sys.stdout.flush()
            selector.close()
            child.stdout.close()
            report["exit_code"] = child.wait(timeout=max(0.01, args.timeout - (time.monotonic() - started)))
        probe = (json.loads((run / "probe.json").read_text())
                 if (run / "probe.json").exists() else {"passed": report["exit_code"] == 0})
        report["probe_passed"] = probe["passed"]
        report["capability_error"] = probe.get("error")
        log = log_path.read_text(errors="replace")
        counts = re.findall(r"^Ran (\d+) tests? in ([\d.]+)s\s*$", log, re.M)
        if len(counts) != 1 or int(counts[0][0]) != args.count:
            raise RuntimeError("Missing or unexpected normal unittest count")
        report["unittest"] = {"count": int(counts[0][0]), "seconds": float(counts[0][1]),
                              "normal_failure": bool(re.search(r"^FAILED \(", log, re.M))}
        if report["exit_code"] != 0 or not probe["passed"]:
            raise RuntimeError(f"Native capability not achieved: exit {report['exit_code']}; {probe.get('error')}")
        if not re.search(r"^OK\s*$", log, re.M):
            raise RuntimeError("Missing normal unittest success")
        report["passed"] = True
    except BaseException as error:
        report["error"] = repr(error)
    finally:
        if child is not None:
            if child.poll() is None or group_exists(child):
                stop_owned_group(child, report)
            report["process_reaped"] = child.poll() is not None
            report["owned_group_gone"] = not group_exists(child)
        try:
            report["inputs_after"] = snapshots()
            report["source_build_solver_harness_unchanged"] = report["inputs_after"] == before
            if not report["source_build_solver_harness_unchanged"]:
                raise RuntimeError("Protected inputs changed during native test")
        except BaseException as error:
            report["passed"] = False
            report["input_check_error"] = repr(error)
        if not report["process_reaped"] or not report.get("owned_group_gone") or report.get("cleanup_failed"):
            report["passed"] = False
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        if log_path.exists():
            report["log_sha256"] = digest(log_path)
        if (run / "probe.json").exists():
            report["probe_sha256"] = digest(run / "probe.json")
        with (run / "execution.json").open("x") as handle:
            handle.write(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
