#!/usr/bin/env python3
"""Root-executed compile/run supervisor for ARTIFICIAL algebra component units.

No finite-element solve, physical fixture or engineering acceptance is claimed.
The C unit includes the unchanged-in-test actual production source, authentic
candidate4 CalculiX.h and actual strcmp1.o; there are no native-function stubs.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


BASE = Path("/private/tmp/freecad-5ar-wYCAxF")
SOURCE = Path("/Users/zukomgwili/src/FreeCAD/package/calculix/force-accounting/forceaccounting.c")
UNIT = BASE / "NativeMpcComponentUnit.c"
NATIVE = BASE / "native-build-4/CalculiX/ccx_2.23/src"
HEADER = NATIVE / "CalculiX.h"
OBJECT = NATIVE / "strcmp1.o"
HEADER_SHA256 = "4958e6cff73f48e3e0a2a57eb5ca86e667192dc2abc3ee780bc2e6ffdb50f7ce"
OBJECT_SHA256 = "37cd6dc390bb79f0b89b3c503970c53ba6b9184073479f27a1cdf902418271b1"
CASES = (
    ("chain-wrong-order", None),
    ("chain-forward", None),
    ("chain-scaled", None),
    ("chain-dependent-external", None),
    ("zero-edge-not-cycle", None),
    ("branch-permuted", None),
    ("branch-scaled", None),
    ("duplicate-edge", None),
    ("reject-cycle", "native MPC dependency graph contains a nonzero cycle"),
    ("reject-self", "native MPC dependency graph contains a self-reference"),
    ("reject-repeated-pivot", "MPC dependent degrees of freedom are not uniquely active"),
    ("reject-linked-list-cycle", "native MPC term lists overlap or contain a cycle"),
    ("reject-nonfinite-pivot", "unsupported MPC dependent coefficient"),
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def serial_guard():
    state = subprocess.run(["ps", "-axo", "pid=,comm="], check=True, text=True, capture_output=True)
    names = {"FreeCAD", "FreeCADCmd", "ctest", "ccx", "ccx_2.23_conda", "ccx-force-accounting", "NativeMpcComponentUnit"}
    for line in state.stdout.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) == 2 and Path(fields[1]).name in names:
            raise RuntimeError("Serial guard: existing native process " + line.strip())


def group_exists(identifier):
    try:
        os.killpg(identifier, 0)
        return True
    except ProcessLookupError:
        return False


def bounded(command, log, timeout, cwd):
    started = time.monotonic()
    timed_out = False
    with log.open("xb") as output:
        child = subprocess.Popen(command, cwd=cwd, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=2)
        if group_exists(child.pid):
            os.killpg(child.pid, signal.SIGTERM)
            until = time.monotonic() + 2
            while group_exists(child.pid) and time.monotonic() < until:
                time.sleep(0.05)
            if group_exists(child.pid):
                os.killpg(child.pid, signal.SIGKILL)
    return {
        "command": command, "returncode": child.returncode, "timed_out": timed_out,
        "pid": child.pid, "process_group": child.pid,
        "reaped": child.poll() is not None, "process_group_gone": not group_exists(child.pid),
        "elapsed_seconds": time.monotonic() - started, "log_sha256": sha(log),
    }


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expected-production-sha256", required=True)
    args = parser.parse_args()
    protected = {"production": SOURCE, "unit": UNIT, "supervisor": Path(__file__), "header": HEADER, "strcmp1_object": OBJECT}
    before = {name: sha(path) for name, path in protected.items()}
    if before["production"] != args.expected_production_sha256:
        raise ValueError("Production C differs from root's explicitly reviewed pin")
    if before["header"] != HEADER_SHA256 or before["strcmp1_object"] != OBJECT_SHA256:
        raise ValueError("Authentic native header/object custody failed")
    serial_guard()
    output = args.output.resolve()
    output.mkdir(parents=False, exist_ok=False)
    binary = output / "NativeMpcComponentUnit"
    command = [
        "/usr/bin/clang", "-std=c11", "-O0", "-Wall", "-Wextra", "-DARCH=Linux",
        '-DFREECAD_FORCE_ACCOUNTING_SOURCE="' + str(SOURCE) + '"',
        "-I" + str(NATIVE), str(UNIT), str(OBJECT), "-lm", "-o", str(binary),
    ]
    build = bounded(command, output / "compile.log", 60, output)
    build["protected_before"] = before
    build["protected_after"] = {name: sha(path) for name, path in protected.items()}
    build["passed"] = (
        build["returncode"] == 0 and not build["timed_out"] and build["reaped"]
        and build["process_group_gone"] and build["protected_after"] == before
    )
    write_json(output / "build-receipt.json", build)
    if not build["passed"]:
        print(json.dumps({"build_passed": False}), flush=True)
        return 1
    binary_hash = sha(binary)
    reports = []
    for name, expected_rejection in CASES:
        serial_guard()
        directory = output / name
        directory.mkdir()
        request = directory / "ARTIFICIAL_COMPONENT_OUTPUT_NOT_SOLVER_REQUEST"
        report = bounded([str(binary), name, str(request)], directory / "unit.log", 10, directory)
        report.update(case=name, expected_rejection=expected_rejection, binary_sha256=binary_hash)
        text = (directory / "unit.log").read_text()
        report["passed"] = not report["timed_out"] and report["reaped"] and report["process_group_gone"]
        native_output = Path(str(request) + ".out")
        if expected_rejection:
            report["passed"] = report["passed"] and report["returncode"] == 201
            report["passed"] = report["passed"] and (
                "*ERROR CCX force accounting V2: " + expected_rejection in text
                and not native_output.exists()
            )
        else:
            try:
                data = json.loads(text.strip())
                report["component_result"] = data
                report["passed"] = (
                    report["passed"] and report["returncode"] == 0 and data["passed"]
                    and data["scope"] == "ARTIFICIAL_NATIVE_C_COMPONENT_UNIT_NOT_PHYSICAL_QUALIFICATION"
                    and native_output.exists()
                )
            except (ValueError, KeyError):
                report["passed"] = False
        report["protected_after"] = {key: sha(path) for key, path in protected.items()}
        report["protected_unchanged"] = report["protected_after"] == before and sha(binary) == binary_hash
        report["passed"] = report["passed"] and report["protected_unchanged"]
        report["native_component_output_sha256"] = sha(native_output) if native_output.exists() else None
        write_json(directory / "execution.json", report)
        reports.append(report)
        print(json.dumps({"case": name, "passed": report["passed"]}), flush=True)
        if not report["passed"]:
            break
    summary = {
        "scope": "ARTIFICIAL_NATIVE_C_COMPONENT_UNITS_NOT_SOLVER_OR_PHYSICAL_QUALIFICATION",
        "protected_before": before, "binary_sha256": binary_hash,
        "build": build, "cases": reports,
        "all_passed": len(reports) == len(CASES) and all(row["passed"] for row in reports),
        "real_mixed_contact_integration_covered": False,
        "physical_software_qualification_or_engineering_acceptance": False,
    }
    write_json(output / "summary.json", summary)
    return 0 if summary["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
