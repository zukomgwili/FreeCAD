"""Bounded one-step installer supervisor. Nothing runs on import.

Root must review this complete private bundle before invoking any step.
DESTDIR is mandatory for payload generation: no direct live-prefix install.
All app tests run serially, with exact per-location fresh result generation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import signal
import subprocess
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
REPO = Path("/Users/zukomgwili/src/FreeCAD")
from harness_config import COMMIT, REVISION
import critical_pins

S = runpy.run_path(str(ROOT / "stage_install.py"))
APP, STAGE = S["APP"], S["STAGE"]
PYTHON = sys.executable


def command_for(step):
    if step == "payload":
        return ["pixi", "run", "--frozen", "cmake", "--install",
                str(REPO / "build/release"), "--config", "Release"], 600
    if step in ("stage", "swap"):
        return [PYTHON, str(ROOT / "stage_install.py"), step], 600
    if step in ("audit-payload", "audit-stage", "audit-custody"):
        return [PYTHON, str(ROOT / "audit_payload_stage.py"), step.split("-", 1)[1]], 180
    if step == "audit-installed":
        return [PYTHON, str(ROOT / "final_audit.py")], 240
    raise ValueError(step)


def processes():
    output = subprocess.check_output(
        ["ps", "-axo", "pid=,ppid=,pgid=,lstart="], text=True,
        env=dict(os.environ, LC_ALL="C"), timeout=10)
    result = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) == 8:
            pid, parent, group = map(int, parts[:3])
            result[pid] = {"parent": parent, "group": group, "started": " ".join(parts[3:])}
    return result


def discover(root_pid, known):
    rows = processes()
    descendants = {root_pid}
    changed = True
    while changed:
        prior = len(descendants)
        descendants.update(pid for pid, row in rows.items() if row["parent"] in descendants)
        changed = len(descendants) != prior
    for pid in descendants:
        if pid in rows and pid != os.getpid():
            known.setdefault(pid, rows[pid])
    return rows


def alive_owned(known):
    rows = processes()
    return {pid: row for pid, row in rows.items() if pid in known
            and row["started"] == known[pid]["started"]}


def cleanup(process, known):
    # PID start times prevent signaling a recycled PID. Never target a broad
    # process-name match, user session or unrelated app process group.
    discover(process.pid, known)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        rows = alive_owned(known)
        for pid in reversed(list(rows)):
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass
        if process.poll() is None:
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and alive_owned(known):
            time.sleep(0.1)
        if not alive_owned(known):
            break
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        raise RuntimeError("Owned child was not reaped after bounded cleanup")
    remaining = alive_owned(known)
    assert not remaining, f"Owned processes remain after cleanup: {remaining}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step")
    args = parser.parse_args()
    command, timeout = command_for(args.step)
    assert args.step in ("payload", "stage", "swap", "audit-payload", "audit-stage", "audit-custody", "audit-installed")
    S["compiled_identity"]()
    for app in (APP, STAGE):
        S["HELPER"]["no_live_app"](app)
    if args.step == "payload":
        assert not (ROOT / "payload").exists()
        if not critical_pins.RECEIPT.exists():
            critical_pins.capture()
    critical_pins.verify()
    receipt = ROOT / ("step-" + args.step.replace(":", "-") + ".json")
    log_path = ROOT / ("step-" + args.step.replace(":", "-") + ".log")
    assert not receipt.exists() and not log_path.exists()
    environment = dict(os.environ)
    for key in list(environment):
        if key.startswith(("FREECAD_", "CCX_", "APPQA_", "YWU_", "FIVEAR_")) or key in (
                "PYTHONPATH", "PYTHONHOME", "DESTDIR"):
            environment.pop(key, None)
    environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1",
                       OMP_NUM_THREADS="2", EXPECTED_COMMIT=COMMIT, EXPECTED_REVISION=REVISION,
                       FREECAD_4JB_WITNESS_PATH=str(REPO / "package/local-completion/FreeCAD4jbWitness.py"),
                       FREECAD_4JB_WITNESS_TEST_COUNT="1", FREECAD_4JB_WITNESS_TIMEOUT="180")
    if args.step == "payload":
        environment["DESTDIR"] = str(ROOT / "payload")
    report = {"passed": False, "step": args.step, "command": command,
              "timeout_seconds": timeout, "compiled_commit": COMMIT, "compiled_revision": REVISION,
              "critical_before_DESTDIR_sha256": critical_pins.sha(critical_pins.RECEIPT),
              "supervisor_sha256": critical_pins.sha(Path(__file__)),
              "timed_out": False, "process_reaped": False}
    helper_paths = [ROOT / name for name in (
        "run_step.py", "stage_install.py", "critical_pins.py", "harness_config.py",
        "audit_payload_stage.py", "final_audit.py", "process_control.py", "LOCAL-INSTALL.txt")]
    report["helper_inputs_before"] = {str(path): critical_pins.sha(path) for path in helper_paths}
    started, process, known = time.monotonic(), None, {}
    try:
        with log_path.open("xb") as output:
            process = subprocess.Popen(command, cwd=REPO, env=environment,
                                       stdout=output, stderr=subprocess.STDOUT,
                                       start_new_session=True)
            report["pid"] = process.pid
            while True:
                discover(process.pid, known)
                status = process.poll()
                if status is not None:
                    break
                if time.monotonic() - started >= timeout:
                    report["timed_out"] = True
                    raise TimeoutError(f"Step exceeded {timeout}s: {args.step}")
                time.sleep(0.1)
            report["exit_code"] = process.wait(timeout=5)
            assert status == 0, f"Step failed ({status}); see {log_path}"
        assert not alive_owned(known), "Owned children outlived their step supervisor"
        critical_pins.verify()
        S["compiled_identity"]()
        profile_receipt = ROOT / "profile-inventories.json"
        if profile_receipt.exists():
            for path, expected in json.loads(profile_receipt.read_text()).items():
                assert S["inventory"](Path(path)) == expected, path
        report["passed"] = True
    except BaseException as error:
        report["error"] = repr(error)
        raise
    finally:
        try:
            if process is not None:
                cleanup(process, known)
                report["process_reaped"] = process.poll() is not None
                report["owned_processes_remaining"] = alive_owned(known)
            critical_pins.verify()
            report["critical_pins_unchanged"] = True
            report["helper_inputs_after"] = {
                str(path): critical_pins.sha(path) for path in helper_paths}
            assert report["helper_inputs_after"] == report["helper_inputs_before"]
            for app in (APP, STAGE):
                S["HELPER"]["no_live_app"](app)
        except BaseException as error:
            report.update(passed=False, cleanup_or_custody_error=repr(error))
            raise
        finally:
            report["elapsed_seconds"] = round(time.monotonic() - started, 3)
            with receipt.open("x") as output:
                output.write(json.dumps(report, indent=2) + "\n")
            print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    def interrupted(signum, frame):
        raise InterruptedError(f"Interrupted by signal {signum}")
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    main()
