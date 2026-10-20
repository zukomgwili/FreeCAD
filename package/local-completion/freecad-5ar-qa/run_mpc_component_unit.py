#!/usr/bin/env python3
"""Root-executed compile/run supervisor for ARTIFICIAL algebra component units.

No finite-element solve, physical fixture or engineering acceptance is claimed.
The C unit includes the unchanged-in-test actual production source, authentic
candidate4 CalculiX.h and actual strcmp1.o; there are no native-function stubs.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys


sys.dont_write_bytecode = True


BASE = Path(__file__).resolve().parent
SOURCE = BASE.parents[2] / "package/calculix/force-accounting/forceaccounting.c"
UNIT = BASE / "NativeMpcComponentUnit.c"
PROCESS_CONTROL = BASE / "process_control.py"
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
    from process_control import assert_serial

    assert_serial()


def bounded(command, log, timeout, cwd):
    from process_control import run_bounded

    return run_bounded(command, cwd=cwd, log=log, timeout=timeout)


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expected-production-sha256", required=True)
    parser.add_argument("--native-source-dir", required=True, type=Path)
    parser.add_argument("--expected-header-sha256", required=True)
    parser.add_argument("--expected-strcmp1-sha256", required=True)
    parser.add_argument("--compiler", type=Path)
    args = parser.parse_args()
    native = args.native_source_dir.resolve(strict=True)
    header, strcmp_object = native / "CalculiX.h", native / "strcmp1.o"
    compiler_name = args.compiler or shutil.which("clang") or shutil.which("cc")
    if not compiler_name:
        raise ValueError("Specify an available native C compiler")
    compiler = Path(compiler_name).resolve(strict=True)
    protected = {
        "production": SOURCE, "unit": UNIT, "supervisor": Path(__file__),
        "process_control": PROCESS_CONTROL, "header": header,
        "strcmp1_object": strcmp_object, "compiler": compiler,
    }
    before = {name: sha(path) for name, path in protected.items()}
    if before["production"] != args.expected_production_sha256:
        raise ValueError("Production C differs from root's explicitly reviewed pin")
    if (
        before["header"] != args.expected_header_sha256
        or before["strcmp1_object"] != args.expected_strcmp1_sha256
    ):
        raise ValueError("Authentic native header/object custody failed")
    serial_guard()
    output = args.output.resolve()
    output.mkdir(parents=False, exist_ok=False)
    binary = output / "NativeMpcComponentUnit"
    command = [
        str(compiler), "-std=c11", "-O0", "-Wall", "-Wextra", "-DARCH=Linux",
        '-DFREECAD_FORCE_ACCOUNTING_SOURCE="' + str(SOURCE) + '"',
        "-I" + str(native), str(UNIT), str(strcmp_object), "-lm", "-o", str(binary),
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
