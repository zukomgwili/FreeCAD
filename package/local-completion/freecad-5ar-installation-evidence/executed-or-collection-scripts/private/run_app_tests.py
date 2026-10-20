"""Serial macOS application QA with fresh evidence at each app location.

Usage: pixi run --frozen python -B run_app_tests.py APPLICATION LABEL {cmd,gui} [SUITES...]
Default cmd=TestFemApp, gui=TestFemGui. No install, source override or output
rebinding is performed. App wrappers are launched, not build-tree executables.
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
import stat
import subprocess
import time


ROOT = Path(__file__).resolve().parent
REPOSITORY = Path("/Users/zukomgwili/src/FreeCAD")
PINNED_COMMIT = "b6b9e216c4ee2ca1bbc73db70076a6c99b2b1ab5"
PINNED_SOLVER = "31fc5615d1753ccbb7b53d5a47175ac1122f18d5cb13060cec272462bb0bd03d"


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def application_snapshot(application):
    result = {}
    for directory, subdirectories, names in os.walk(application, followlinks=False):
        for name in sorted(subdirectories + names):
            path = Path(directory) / name
            relative = str(path.relative_to(application))
            mode = path.lstat().st_mode
            if name == "__pycache__" or path.suffix in (".pyc", ".pyo"):
                raise RuntimeError("Bytecode/cache in application payload: " + relative)
            if stat.S_ISLNK(mode):
                result[relative] = {"kind": "symlink", "target": os.readlink(path),
                                    "mode": stat.S_IMODE(mode)}
            elif stat.S_ISDIR(mode):
                result[relative] = {"kind": "directory", "mode": stat.S_IMODE(mode)}
            elif stat.S_ISREG(mode):
                result[relative] = {"kind": "file", "mode": stat.S_IMODE(mode),
                                    "sha256": digest(path), "bytes": path.stat().st_size}
            else:
                raise RuntimeError("Unexpected application filesystem entry: " + relative)
    if not result:
        raise RuntimeError("Empty application inventory")
    return result


def source_snapshot():
    fem = REPOSITORY / "src/Mod/Fem"
    paths = sorted(path for path in fem.rglob("*.py") if path.is_file())
    paths.extend((fem / "CMakeLists.txt", REPOSITORY / "build/release/src/Build/Version.h",
                  REPOSITORY / "package/calculix/force-accounting/forceaccounting.c",
                  REPOSITORY / "package/calculix/force-accounting/hooks.patch",
                  REPOSITORY / "package/calculix/force-accounting/contract.json",
                  ROOT / "AppNativeIdentity.py", ROOT / "run_app_tests.py"))
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPOSITORY,
                          capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    if head != PINNED_COMMIT:
        raise RuntimeError("Source HEAD changed from the authorized compiled commit")
    return {"git_head": head, "files": {str(path): digest(path) for path in paths}}


def serial_guard():
    result = subprocess.run(["/bin/ps", "-axo", "pid=,comm="], capture_output=True,
                            text=True, check=True, timeout=10)
    conflicts = []
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) != 2:
            continue
        name = Path(fields[1]).name
        if name in ("FreeCAD", "FreeCADCmd", "ctest", "ccx", "ccx-force-accounting",
                    "ninja", "make", "gmake") or name.startswith("ccx_"):
            conflicts.append(line.strip())
    if conflicts:
        raise RuntimeError("Run serially; existing native/build/solver process: " + repr(conflicts))


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
    parser.add_argument("application", type=Path)
    parser.add_argument("label")
    parser.add_argument("mode", choices=("cmd", "gui"))
    parser.add_argument("suites", nargs="*")
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", args.label):
        parser.error("LABEL must contain only alphanumerics, hyphens and underscores")
    if not 1 <= args.timeout <= 600:
        parser.error("Timeout must be 1..600 seconds")
    suites = args.suites or (["TestFemGui"] if args.mode == "gui" else ["TestFemApp"])
    if len(suites) != len(set(suites)) or "AppNativeIdentity" in suites:
        parser.error("Duplicate suites or explicit identity suite are not allowed")
    if any(not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", suite) for suite in suites):
        parser.error("Suites must be dotted product Python test names")
    application = args.application.resolve(strict=True)
    resources = application / "Contents/Resources"
    wrapper = application / "Contents/MacOS" / ("FreeCAD" if args.mode == "gui" else "FreeCADCmd")
    if not wrapper.is_file() or not os.access(wrapper, os.X_OK):
        raise RuntimeError("Application native wrapper is unavailable: " + str(wrapper))
    if digest(resources / "data/NativeSolvers/ccx-force-accounting") != PINNED_SOLVER:
        raise RuntimeError("Bundled V2 solver differs from the qualified exact leaf")
    serial_guard()
    source_before = source_snapshot()
    app_before = application_snapshot(application)
    run = ROOT / args.label
    run.mkdir(exist_ok=False)
    environment = dict(os.environ)
    for key in list(environment):
        if key.startswith(("FREECAD_", "RO1_", "FIVEAR_", "APPQA_", "CCX_FORCE_ACCOUNTING_",
                           "CCX_9ZT_")) or key in (
                "PYTHONPATH", "PYTHONHOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME"):
            environment.pop(key, None)
    for key in ("FREECAD_USER_HOME", "FREECAD_USER_DATA", "FREECAD_USER_TEMP",
                "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME"):
        directory = run / key.lower()
        directory.mkdir()
        environment[key] = str(directory)
    identity_path = run / "identity.json"
    log_path = run / "run.log"
    environment.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
                        "OMP_NUM_THREADS": "2", "TMPDIR": environment["FREECAD_USER_TEMP"],
                        "APPQA_APPLICATION": str(application), "APPQA_MODE": args.mode,
                        "APPQA_REPORT": str(identity_path), "APPQA_SUITES": json.dumps(suites)})
    command = [str(wrapper), "-u", str(run / "user.cfg"), "-s", str(run / "system.cfg"),
               "-P", str(ROOT), "-t", "AppNativeIdentity"]
    for suite in suites:
        command += ["-t", suite]
    report = {"passed": False, "application": str(application), "mode": args.mode,
              "command": command, "cwd": str(REPOSITORY), "suites": suites,
              "timeout_seconds": args.timeout, "timed_out": False,
              "source_before": source_before, "app_before": app_before,
              "log": str(log_path), "identity_report": str(identity_path),
              "rebound_or_reused_stage_outputs": False}
    child = None
    started = time.monotonic()
    try:
        serial_guard()
        print(json.dumps({"status": "starting", "command": command, "log": str(log_path)}),
              flush=True)
        with log_path.open("xb") as log:
            child = subprocess.Popen(command, cwd=REPOSITORY, env=environment,
                                     stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            report["pid"] = child.pid
            try:
                report["exit_code"] = child.wait(timeout=args.timeout)
            except subprocess.TimeoutExpired:
                report["timed_out"] = True
                cleanup(child, report)
                report["exit_code"] = child.returncode
                raise RuntimeError("Application QA timed out; own process group terminated")
        if report["exit_code"] != 0:
            raise RuntimeError("Application native launcher exited " + str(report["exit_code"]))
        log = log_path.read_text(errors="replace")
        counts = re.findall(r"^Ran (\d+) tests? in ([\d.]+)s\s*$", log, re.M)
        outcomes = re.findall(r"^OK(?: \(([^\n]*)\))?\s*$", log, re.M)
        if len(counts) != 1 or len(outcomes) != 1 or re.search(
                r"^(?:FAILED\b|FAIL:|ERROR:|UNEXPECTED SUCCESS:)", log, re.M):
            raise RuntimeError("Missing, duplicate or failed normal unittest result")
        identity = json.loads(identity_path.read_text())
        if not identity["passed"] or bool(identity["gui_up"]) != (args.mode == "gui"):
            raise RuntimeError("Application identity observer failed")
        count, seconds = counts[0]
        if int(count) != identity["expected_total_count"]:
            raise RuntimeError("Discovered and executed test counts differ")
        skipped = re.findall(r"^([^\n]+) \.\.\. skipped ([^\n]+)$", log, re.M)
        report["unittest"] = {"count": int(count), "seconds": float(seconds), "outcome": "OK",
                              "details": outcomes[0], "skipped_lines": skipped}
        required = set(identity["registered_native_tie_ids"])
        for suite in identity["configured_suites"].values():
            for test_id in suite["ids"]:
                if test_id not in required:
                    continue
                method = test_id.rsplit(".", 1)[-1]
                entry = r"^" + re.escape(method) + r" \(" + re.escape(test_id) + r"\) \.\.\.(.*)$"
                matches = re.findall(entry, log, re.M)
                if len(matches) != 1 or "skipped" in matches[0]:
                    raise RuntimeError("Missing, repeated or skipped Tie accounting test: "
                                       + test_id)
        report["runtime"] = identity["runtime"]
        report["configured_suite_counts"] = {name: suite["count"] for name, suite in
                                               identity["configured_suites"].items()}
        report["tie_cold_cases"] = []
        for filename in re.findall(r"TIE_ACCOUNTING_COLD_CASE=([^\r\n]+)", log):
            manifest = Path(filename.strip()).resolve(strict=True)
            if not manifest.is_relative_to(run):
                raise RuntimeError("Tie persistence manifest is not from this fresh app run")
            case = json.loads(manifest.read_text())
            document = Path(case["document"]).resolve(strict=True)
            frd = Path(case["frd"]["path"]).resolve(strict=True)
            binary = Path(case["movement_source"]["binary"]).resolve(strict=True)
            if not document.is_relative_to(run) or not frd.is_relative_to(run):
                raise RuntimeError("Tie persistence document/field is not fresh in this QA run")
            if (digest(document) != case["document_sha256"] or digest(frd) != case["frd"]["sha256"]
                    or case["version"] != identity["runtime"]
                    or case["movement_source"]["binary_sha256"] != PINNED_SOLVER
                    or binary != (resources / "data/NativeSolvers/ccx-force-accounting").resolve()):
                raise RuntimeError("Tie persistence artifact does not bind this actual application")
            report["tie_cold_cases"].append({
                "path": str(manifest), "sha256": digest(manifest),
                "document": str(document), "document_sha256": case["document_sha256"],
                "frd": str(frd), "frd_sha256": case["frd"]["sha256"],
                "binary": str(binary), "binary_sha256": case["movement_source"]["binary_sha256"],
            })
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
            report["source_and_harness_unchanged"] = report["source_after"] == source_before
            report["app_after"] = application_snapshot(application)
            report["application_unchanged"] = report["app_after"] == app_before
            if not report["source_and_harness_unchanged"] or not report["application_unchanged"]:
                raise RuntimeError("Application, source, header or harness changed during QA")
        except BaseException as error:
            report["passed"] = False
            report["custody_error"] = repr(error)
        if (not report.get("process_reaped") or not report.get("owned_group_gone")
                or report.get("cleanup_failed")):
            report["passed"] = False
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        if log_path.exists():
            report["log_sha256"] = digest(log_path)
        if identity_path.exists():
            report["identity_sha256"] = digest(identity_path)
        with (run / "execution.json").open("x") as handle:
            handle.write(json.dumps(report, indent=2) + "\n")
        print(json.dumps({key: value for key, value in report.items()
                          if key not in ("source_before", "source_after",
                                         "app_before", "app_after")},
                         indent=2), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
