"""Bounded app-only cold check, with exact manifest SHA supplied by root.

Usage: pixi run --frozen python -B run_app_cold.py APPLICATION LABEL MANIFEST SHA256
Only a private fixture copy is opened. No native writer, solve or save runs.
The identity observer's executable capability query is not a physical solve.
"""

import sys
sys.dont_write_bytecode = True

import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time

import run_app_tests as appqa


ROOT = Path(__file__).resolve().parent


def record(path):
    path = Path(path)
    if not path.exists() and not path.is_symlink():
        return {"exists": False}
    info = path.lstat()
    result = {"exists": True, "device": info.st_dev, "inode": info.st_ino,
              "mode": info.st_mode, "bytes": info.st_size,
              "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns}
    if stat.S_ISLNK(info.st_mode):
        result.update(kind="symlink", target=os.readlink(path), sha256=appqa.digest(path))
    elif stat.S_ISREG(info.st_mode):
        result.update(kind="file", sha256=appqa.digest(path))
    else:
        raise RuntimeError("Unexpected critical prefix/profile entry: " + str(path))
    return result


def critical_snapshot():
    repository = appqa.REPOSITORY
    prefix = repository / ".pixi/envs/default"
    paths = [repository / "pixi.toml", repository / "pixi.lock", prefix / "bin/ccx",
             prefix / "lib/qt6/plugins/platforms/libqcocoa.dylib"]
    namespace = prefix / "lib/python3.13/site-packages/freecad"
    paths.extend(namespace / name for name in (
        "UiTools.py", "__init__.py", "deprecation.py", "freecad_doc.py", "module_io.py",
        "part.py", "partdesign.py", "project_utility.py", "sketcher.py", "utils.py",
        "utils_zip.py"))
    preferences = Path("/Users/zukomgwili/Library/Preferences/FreeCAD")
    profiles = set(preferences.rglob("*.cfg"))
    profiles.update((preferences / "user.cfg", preferences / "system.cfg"))
    paths.extend(sorted(profiles))
    return {str(path): record(path) for path in paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("application", type=Path)
    parser.add_argument("label")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("manifest_sha256")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", args.label):
        parser.error("LABEL must contain only alphanumerics, hyphens and underscores")
    if not re.fullmatch(r"[0-9a-f]{64}", args.manifest_sha256):
        parser.error("Expected manifest SHA256 must be explicit lowercase hexadecimal")
    if not 1 <= args.timeout <= 180:
        parser.error("Timeout must be 1..180 seconds")
    application = args.application.resolve(strict=True)
    manifest = args.manifest.resolve(strict=True)
    if appqa.digest(manifest) != args.manifest_sha256:
        raise RuntimeError("Cold manifest differs from root's exact captured SHA256")
    wrapper = application / "Contents/MacOS/FreeCADCmd"
    if not wrapper.is_file() or not os.access(wrapper, os.X_OK):
        raise RuntimeError("Native application command wrapper is unavailable")
    appqa.serial_guard()
    source_before = appqa.source_snapshot()
    app_before = appqa.application_snapshot(application)
    critical_before = critical_snapshot()
    extra_paths = [Path(__file__), ROOT / "NativeAppColdReopen.py", manifest]
    extra_before = {str(path): appqa.digest(path) for path in extra_paths}
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
                        "APPQA_APPLICATION": str(application), "APPQA_MODE": "cmd",
                        "APPQA_REPORT": str(identity_path), "APPQA_SUITES": "[]",
                        "APPQA_COLD_OUTPUT": str(run), "APPQA_COLD_MANIFEST": str(manifest),
                        "APPQA_COLD_MANIFEST_SHA256": args.manifest_sha256})
    command = [str(wrapper), "-u", str(run / "user.cfg"), "-s", str(run / "system.cfg"),
               "-P", str(ROOT), "-t", "AppNativeIdentity", "-t", "NativeAppColdReopen"]
    report = {"passed": False, "application": str(application), "command": command,
              "source_before": source_before, "app_before": app_before,
              "critical_before": critical_before, "extra_before": extra_before,
              "manifest": str(manifest), "manifest_sha256": args.manifest_sha256,
              "timeout_seconds": args.timeout, "timed_out": False,
              "writer_solve_save_or_rebinding_performed": False}
    child = None
    started = time.monotonic()
    try:
        appqa.serial_guard()
        print(json.dumps({"status": "starting", "command": command, "log": str(log_path)}),
              flush=True)
        with log_path.open("xb") as log:
            child = subprocess.Popen(command, cwd=appqa.REPOSITORY, env=environment,
                                     stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            report["pid"] = child.pid
            try:
                report["exit_code"] = child.wait(timeout=args.timeout)
            except subprocess.TimeoutExpired:
                report["timed_out"] = True
                appqa.cleanup(child, report)
                report["exit_code"] = child.returncode
                raise RuntimeError("Cold application QA timed out; owned group terminated")
        if report["exit_code"] != 0:
            raise RuntimeError("Native cold application check exited " + str(report["exit_code"]))
        log = log_path.read_text(errors="replace")
        counts = re.findall(r"^Ran (\d+) tests? in ([\d.]+)s\s*$", log, re.M)
        if len(counts) != 1 or counts[0][0] != "2" or not re.search(r"^OK\s*$", log, re.M):
            raise RuntimeError("Missing normal identity + cold-witness two-test success")
        if re.search(r"^(?:FAILED\b|FAIL:|ERROR:|UNEXPECTED SUCCESS:)", log, re.M):
            raise RuntimeError("Native cold check contains a failed normal unittest result")
        if re.search(r"\.\.\. skipped", log):
            raise RuntimeError("Cold identity/history check must not be skipped")
        identity = json.loads(identity_path.read_text())
        probe = json.loads((run / "probe.json").read_text())
        if not identity["passed"] or not probe["passed"]:
            raise RuntimeError("Application identity or cold-history witness did not pass")
        report["unittest"] = {"count": 2, "seconds": float(counts[0][1]), "skipped_lines": []}
        report["runtime"] = identity["runtime"]
        report["probe"] = probe
        report["passed"] = True
    except BaseException as error:
        report["error"] = repr(error)
    finally:
        if child is not None:
            if child.poll() is None or appqa.group_exists(child):
                appqa.cleanup(child, report)
            report["process_reaped"] = child.poll() is not None
            report["owned_group_gone"] = not appqa.group_exists(child)
        try:
            report["source_after"] = appqa.source_snapshot()
            report["app_after"] = appqa.application_snapshot(application)
            report["critical_after"] = critical_snapshot()
            report["extra_after"] = {str(path): appqa.digest(path) for path in extra_paths}
            report["all_protected_inputs_unchanged"] = (
                report["source_after"] == source_before and report["app_after"] == app_before
                and report["critical_after"] == critical_before
                and report["extra_after"] == extra_before)
            if not report["all_protected_inputs_unchanged"]:
                raise RuntimeError("App/source/critical prefix/profile/input custody changed")
        except BaseException as error:
            report["passed"] = False
            report["custody_error"] = repr(error)
        if (not report.get("process_reaped") or not report.get("owned_group_gone")
                or report.get("cleanup_failed")):
            report["passed"] = False
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        if log_path.exists():
            report["log_sha256"] = appqa.digest(log_path)
        if identity_path.exists():
            report["identity_sha256"] = appqa.digest(identity_path)
        if (run / "probe.json").exists():
            report["probe_sha256"] = appqa.digest(run / "probe.json")
        with (run / "execution.json").open("x") as handle:
            handle.write(json.dumps(report, indent=2) + "\n")
        omitted = {"source_before", "source_after", "app_before", "app_after",
                   "critical_before", "critical_after", "extra_before", "extra_after"}
        print(json.dumps({key: value for key, value in report.items() if key not in omitted},
                         indent=2), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
