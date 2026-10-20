"""Serial bounded retained rear Tie source witness; no build/install/solver.

Usage (from repository, after root review):
  pixi run --frozen python /private/tmp/freecad-ro1.VmcpuR/run_retained.py LABEL create
  pixi run --frozen python /private/tmp/freecad-ro1.VmcpuR/run_retained.py LABEL cold --previous PRIOR_LABEL

Every label must be new. Cold opens a fresh byte-identical private copy of the
prior saved witness. The original project and all earlier evidence are retained.
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
import shutil
import signal
import subprocess
import time

ROOT = Path(__file__).resolve().parent
REPOSITORY = Path("/Users/zukomgwili/src/FreeCAD")
BUILD = REPOSITORY / "build/release"
ORIGINAL = Path("/Users/zukomgwili/src/oomakhi/artifacts/Fire-Access-Integration/r01/review/en2-complete-r01/native-contact-observation-continuation-r46/adopted-inputs/retained-native-source.FCStd")
ORIGINAL_SHA = "56bbd2b7760e270337c506088cf8717605201555d2eb65e60780afcfd1e660e5"
INPUTS = ("ObjectsFem.py", "femmesh/meshsetsgetter.py", "femmesh/meshtools.py",
          "femmesh/ownership_context.py", "femtools/ccxtools.py",
          "femtools/femutils.py", "femtools/membertools.py",
          "femsolver/calculix/write_constraint_tie.py", "femsolver/calculix/writer.py",
          "femsolver/writerbase.py", "femsolver/calculix/calculixutils.py")


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def snapshot():
    paths = [ROOT / "RetainedRearTieWitness.py", ROOT / "run_retained.py",
             BUILD / "bin/FreeCADCmd", BUILD / "Mod/Fem/Fem.so", BUILD / "src/Build/Version.h",
             ORIGINAL]
    for relative in INPUTS:
        source = REPOSITORY / "src/Mod/Fem" / relative
        copied = BUILD / "Mod/Fem" / relative
        if sha(source) != sha(copied):
            raise RuntimeError("Build source differs: " + relative)
        paths.extend((source, copied))
    return {str(path): sha(path) for path in paths}


def serial_guard():
    completed = subprocess.run(["/bin/ps", "-axo", "pid=,comm="], check=True,
                               capture_output=True, text=True, timeout=10)
    conflicts = []
    for line in completed.stdout.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) == 2 and (Path(fields[1]).name in ("FreeCAD", "FreeCADCmd", "ctest", "ccx", "ccx-force-accounting")):
            conflicts.append(line.strip())
    if conflicts:
        raise RuntimeError("Native/test/solver process is already active: " + repr(conflicts))


def group_exists(child):
    try:
        os.killpg(child.pid, 0)
        return True
    except ProcessLookupError:
        return False


def cleanup(child, report):
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("label")
    parser.add_argument("phase", choices=("create", "cold"))
    parser.add_argument("--previous")
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()
    for label in (args.label, args.previous):
        if label is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", label):
            parser.error("Labels must be plain alphanumeric/hyphen/underscore names")
    if not 1 <= args.timeout <= 900:
        parser.error("Timeout must be1..900seconds")
    if bool(args.previous) != (args.phase == "cold"):
        parser.error("--previous is required only for cold")
    lock_path = ROOT / "retained-serial.lock"
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        serial_guard()
        before = snapshot()
        if before[str(ORIGINAL)] != ORIGINAL_SHA:
            raise RuntimeError("Original retained source hash changed")
        source, source_sha, previous_report = ORIGINAL, ORIGINAL_SHA, None
        previous_fences = {}
        if args.previous:
            previous = ROOT / args.previous
            previous_report = previous / "report.json"
            execution = json.loads((previous / "execution.json").read_text())
            previous_data = json.loads(previous_report.read_text())
            if not execution["passed"] or not previous_data["passed"]:
                raise RuntimeError("Previous phase did not pass")
            source = Path(previous_data["saved_witness"]["path"]).resolve()
            if source != (previous / "witness.FCStd").resolve():
                raise RuntimeError("Previous witness path escaped its private phase")
            source_sha = previous_data["saved_witness"]["sha256"]
            if sha(source) != source_sha:
                raise RuntimeError("Saved prior witness changed")
            previous_fences = {str(path): sha(path) for path in
                               (previous_report, previous / "execution.json", source)}
        run = ROOT / args.label
        run.mkdir(exist_ok=False)
        copied = run / "input.FCStd"
        with copied.open("xb") as target, source.open("rb") as original:
            shutil.copyfileobj(original, target)
        if sha(copied) != source_sha:
            raise RuntimeError("Private input copy differs")
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
        environment.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "OMP_NUM_THREADS": "2",
            "TMPDIR": environment["FREECAD_USER_TEMP"], "RO1_RETAINED_RUN": str(run),
            "RO1_RETAINED_PHASE": args.phase, "RO1_RETAINED_INPUT": str(source),
            "RO1_RETAINED_INPUT_SHA256": source_sha})
        if previous_report:
            environment["RO1_RETAINED_PREVIOUS_REPORT"] = str(previous_report)
        command = ["pixi", "run", "--frozen", str(BUILD / "bin/FreeCADCmd"),
                   "-u", str(run / "user.cfg"), "-s", str(run / "system.cfg"),
                   "-P", str(ROOT), "-t", "RetainedRearTieWitness"]
        report = {"passed": False, "phase": args.phase, "command": command, "cwd": str(REPOSITORY),
                  "timeout_seconds": args.timeout, "source": str(source), "source_sha256": source_sha,
                  "inputs_before": before, "timed_out": False, "solves": 0}
        report["previous_phase_inputs"] = previous_fences
        child = None
        started = time.monotonic()
        log_path = run / "run.log"
        try:
            serial_guard()  # Recheck immediately before creating this owned native process.
            print(json.dumps({"status": "starting", "phase": args.phase, "log": str(log_path)}), flush=True)
            with log_path.open("xb") as output:
                child = subprocess.Popen(command, cwd=REPOSITORY, env=environment,
                                         stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
                report["pid"] = child.pid
                try:
                    report["exit_code"] = child.wait(timeout=args.timeout)
                except subprocess.TimeoutExpired:
                    report["timed_out"] = True
                    cleanup(child, report)
                    report["exit_code"] = child.returncode
                    raise RuntimeError("Retained native witness exceeded bounded timeout")
            if report["exit_code"] != 0:
                raise RuntimeError("Native launcher failed")
            text = log_path.read_text(errors="replace")
            if len(re.findall(r"^Ran 1 test in [\d.]+s\s*$", text, re.M)) != 1 or len(re.findall(r"^OK\s*$", text, re.M)) != 1:
                raise RuntimeError("Missing unique successful one-test result")
            if re.search(r"^(?:FAILED\b|FAIL:|ERROR:|UNEXPECTED SUCCESS:)", text, re.M):
                raise RuntimeError("Native unittest reported failure")
            result_path = run / "report.json"
            result = json.loads(result_path.read_text())
            if not result["passed"] or result["phase"] != args.phase or len(result["written_sides"]) != 48:
                raise RuntimeError("Retained native proof did not pass")
            if not result["source_and_private_input_unchanged"]:
                raise RuntimeError("Source/input fence failed")
            report["native_report_sha256"] = sha(result_path)
            report["saved_witness"] = result["saved_witness"]
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
                report["inputs_after"] = snapshot()
                report["source_build_harness_unchanged"] = report["inputs_after"] == before
                report["input_and_previous_witness_unchanged"] = sha(source) == source_sha and sha(copied) == source_sha
                report["previous_phase_evidence_unchanged"] = all(sha(path) == expected for path, expected in previous_fences.items())
                if (not report["source_build_harness_unchanged"]
                        or not report["input_and_previous_witness_unchanged"]
                        or not report["previous_phase_evidence_unchanged"]):
                    raise RuntimeError("Source/build/harness/input fence failed")
            except BaseException as error:
                report["passed"] = False
                report["fence_error"] = repr(error)
            if not report.get("process_reaped") or not report.get("owned_group_gone") or report.get("cleanup_failed"):
                report["passed"] = False
            report["seconds"] = round(time.monotonic() - started, 3)
            if log_path.exists():
                report["log_sha256"] = sha(log_path)
            with (run / "execution.json").open("x") as output:
                output.write(json.dumps(report, indent=2) + "\n")
            print(json.dumps(report, indent=2), flush=True)
        return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
