"""Serial isolated movement diagnostic; retains all original force RED evidence.

Usage: pixi run --frozen python -B /private/tmp/freecad-5ar-wYCAxF/run_native_movement_probe.py LABEL
Reuses only the previously reviewed custody and owned-process cleanup helpers;
does not execute or modify the force probe or its supervisor.
"""

import sys
sys.dont_write_bytecode = True

import argparse
import json
import os
from pathlib import Path
import re
import selectors
import subprocess
import time

import run_native_tie_probe as custody


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "force-green-1/analytical-tie.FCStd"


def snapshots():
    state = custody.snapshots()
    additional = [ROOT / "NativeTieMovementProbe.py", ROOT / "run_native_movement_probe.py", SOURCE]
    for relative in ("femobjects/result_contact_observation.py",
                     "femresult/contact_observation_source.py", "femresult/owned_probe.py"):
        original = custody.REPOSITORY / "src/Mod/Fem" / relative
        copied = custody.BUILD / "Mod/Fem" / relative
        if custody.digest(original) != custody.digest(copied):
            raise RuntimeError(f"Build is not current for {relative}; build before testing")
        additional.extend((original, copied))
    state.update({str(path): custody.digest(path) for path in additional})
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("label")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", args.label):
        parser.error("LABEL must contain only alphanumerics, hyphens and underscores")
    if not 1 <= args.timeout <= 180:
        parser.error("Timeout must be 1..180 seconds")
    custody.native_preflight()
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
    command = ["pixi", "run", "--frozen", str(custody.BUILD / "bin/FreeCADCmd"),
               "-u", str(run / "user.cfg"), "-s", str(run / "system.cfg"),
               "-P", str(ROOT), "-t", "NativeTieMovementProbe"]
    log_path = run / "run.log"
    report = {"passed": False, "label": args.label, "command": command,
              "cwd": str(custody.REPOSITORY), "timeout_seconds": args.timeout,
              "inputs_before": before, "timed_out": False, "process_reaped": False,
              "log": str(log_path), "separate_movement_control_not_force_acceptance": True}
    started = time.monotonic()
    child = None
    try:
        print(json.dumps({"status": "starting", "command": command}), flush=True)
        with log_path.open("xb") as log:
            child = subprocess.Popen(command, cwd=custody.REPOSITORY, env=environment,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     start_new_session=True)
            report["pid"] = child.pid
            selector = selectors.DefaultSelector()
            selector.register(child.stdout, selectors.EVENT_READ)
            while selector.get_map():
                if time.monotonic() - started >= args.timeout:
                    report["timed_out"] = True
                    custody.stop_owned_group(child, report)
                    raise RuntimeError("Native movement timeout; owned child group terminated")
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
        probe = json.loads((run / "probe.json").read_text())
        report["probe_passed"] = probe["passed"]
        report["capability_error"] = probe.get("error")
        report["last_checkpoint"] = probe["checkpoints"][-1] if probe["checkpoints"] else None
        report["original_input_unchanged"] = probe["original_input_unchanged"]
        log = log_path.read_text(errors="replace")
        counts = re.findall(r"^Ran (\d+) tests? in ([\d.]+)s\s*$", log, re.M)
        if len(counts) != 1 or counts[0][0] != "1":
            raise RuntimeError("Missing or unexpected normal unittest count")
        report["unittest"] = {"count": int(counts[0][0]), "seconds": float(counts[0][1]),
                              "normal_failure": bool(re.search(r"^FAILED \(", log, re.M))}
        if report["exit_code"] != 0 or not probe["passed"]:
            raise RuntimeError(f"Native movement capability not achieved: exit {report['exit_code']}; {probe.get('error')}")
        if not re.search(r"^OK\s*$", log, re.M):
            raise RuntimeError("Missing normal unittest success")
        if not probe["original_input_unchanged"]:
            raise RuntimeError("Original force fixture changed")
        report["passed"] = True
    except BaseException as error:
        report["error"] = repr(error)
    finally:
        if child is not None:
            if child.poll() is None or custody.group_exists(child):
                custody.stop_owned_group(child, report)
            report["process_reaped"] = child.poll() is not None
            report["owned_group_gone"] = not custody.group_exists(child)
        try:
            report["inputs_after"] = snapshots()
            report["source_build_solver_harness_and_original_fixture_unchanged"] = report["inputs_after"] == before
            if not report["source_build_solver_harness_and_original_fixture_unchanged"]:
                raise RuntimeError("Protected inputs changed during native movement test")
        except BaseException as error:
            report["passed"] = False
            report["input_check_error"] = repr(error)
        if not report["process_reaped"] or not report.get("owned_group_gone") or report.get("cleanup_failed"):
            report["passed"] = False
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        if log_path.exists():
            report["log_sha256"] = custody.digest(log_path)
        if (run / "probe.json").exists():
            report["probe_sha256"] = custody.digest(run / "probe.json")
        with (run / "execution.json").open("x") as handle:
            handle.write(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
