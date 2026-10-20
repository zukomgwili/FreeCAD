"""Root-executed bounded native-C units and capacity CLI checks, not physics QA.

Nothing runs on import. This supervisor never launches an application, mesh,
finite-element solve, installer or build system. Root explicitly invokes it to
compile the actual-source artificial C unit and run fresh private cases. Native
CLI executions use only the early capacity switch, never an input job.
"""

import sys

sys.dont_write_bytecode = True

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent.parent
REPO = Path("/Users/zukomgwili/src/FreeCAD")
SOURCE = REPO / "package/calculix/force-accounting/forceaccounting.c"
HOOKS = REPO / "package/calculix/force-accounting/hooks.patch"
UNIT = ROOT / "NativeCapacityMaskUnit.c"
NATIVE = ROOT / "native-capacity-r01/native/CalculiX/ccx_2.23/src"
BUDGET = "CCX_FORCE_ACCOUNTING_MAX_DECLARATIONS"
MARKER = "CCX_FORCE_ACCOUNTING_CAPACITY_APPLIED_V1 "
SCOPE = "ARTIFICIAL_NATIVE_CAPACITY_MASK_UNIT_NOT_PHYSICAL_QUALIFICATION"
PINS = {
    "production": (SOURCE, "8c51e06abecf4c2b1537b1e6f4ef4606ea8481a4a180d465cbff00d63329f2a4"),
    "hooks": (HOOKS, "e500c46cc9cd26fc4e63508a51375bd09ebdc0973638375df14cffd036c9bfa7"),
    "unit": (UNIT, "df373bdeeb867d06e03ec84334bc54b0c3b8aa497f1e7a0c1eda1bfd797d8102"),
    "process_control": (ROOT / "process_control.py", "5199c733fdc18a2c6f78d03ea2a3281e236419365219d7b9f33b5ecca0aa733d"),
    "native_header": (NATIVE / "CalculiX.h", "5823971798be5b478945b29151559e79eacab09e7f5c7f98fd7cf5e62ba44351"),
    "strcmp1_object": (NATIVE / "strcmp1.o", "37cd6dc390bb79f0b89b3c503970c53ba6b9184073479f27a1cdf902418271b1"),
    "native_copy": (NATIVE / "forceaccounting.c", "8c51e06abecf4c2b1537b1e6f4ef4606ea8481a4a180d465cbff00d63329f2a4"),
    "candidate": (NATIVE / "ccx_2.23_conda", "6c02452a896727af6cb4578fd3fb6bbfbdd48e3fb887c1c04fa2d8b171976c66"),
}
INVALID = ("", "0", "-1", "+1", " 1", "1 ", "01", "1.0", "1x", "1\n", "2147483648", "9" * 100)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), f"Not a regular input: {path}")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, value):
    with Path(path).open("x") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def snapshot(paths):
    # Runtime aliases are retained as aliases as well as content: retargeting
    # libblas/liblapack must not escape the before/after fence.
    return {name: {"path": str(path), "resolved": str(path.resolve(strict=True)),
                   "symlink": os.readlink(path) if path.is_symlink() else None,
                   "sha256": sha(path.resolve(strict=True))} for name, path in paths.items()}


def serial():
    assert_serial(("NativeCapacityMaskUnit", "NativeCapacityMaskUnitSanitized", "ninja", "make", "gmake"))


@contextmanager
def null_stdin():
    """The shared exact supervisor inherits FD0; isolate it for the child only."""
    original = os.dup(0)
    try:
        with open(os.devnull, "rb") as empty:
            os.dup2(empty.fileno(), 0)
            yield
    finally:
        os.dup2(original, 0)
        os.close(original)


def environment(directory, budget):
    result = dict(os.environ)
    for key in tuple(result):
        if key.startswith(("CCX_", "FREECAD_", "YWU_", "YZK_", "APPQA_", "DYLD_", "LD_")) or key in (
            "PYTHONPATH", "PYTHONHOME", "ASAN_OPTIONS", "UBSAN_OPTIONS", "CPATH",
            "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH", "OBJC_INCLUDE_PATH", "LIBRARY_PATH",
            "COMPILER_PATH", "SDKROOT", "DEVELOPER_DIR", "CFLAGS", "CPPFLAGS", "LDFLAGS",
        ):
            result.pop(key)
    result.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1", TMPDIR=str(directory),
                  CLANG_MODULE_CACHE_PATH=str(directory / "module-cache"), OMP_NUM_THREADS="1",
                  LC_ALL="C", LANG="C")
    if budget is not None:
        result[BUDGET] = budget
    return result


def expected_capacity(budget):
    return {
        "schema": "CCX_FORCE_ACCOUNTING_CAPACITY_V1",
        "request_schema": "CCX_FORCE_ACCOUNTING_V3",
        "allocation": "dynamic",
        "counting_policy": "top-level-declarations-v1",
        "total_records": budget,
        "limits": {kind: budget for kind in ("supports", "bodies", "ports", "angles", "springs")},
    }


def expected_applied(case, budget):
    counts = {kind: 0 for kind in ("supports", "bodies", "ports", "angles", "springs")}
    counts["supports" if case == "zero-body-spc" else "bodies"] = 1 if case == "zero-body-spc" else 264
    return {"budget": budget, "counts": counts, "total": sum(counts.values())}


def expected_result(case):
    result = {"scope": SCOPE, "case": case, "passed": True}
    if case == "zero-body-spc":
        result.update(bodies=0, supports=1, owner_words=1, actual_prepare_reset_emit=True)
    else:
        version = 3 if case == "multiword" else int(case[-1])
        result.update(schema_version=version, bodies=264 if version == 3 else 64,
                      owner_words=5 if version == 3 else 1,
                      actual_prepare_contact_point_reset_emit=True,
                      actual_element_callback=version == 3)
    return result


def unit_specs():
    result = [
        ("multiword-default", "multiword", None, None),
        ("multiword-exact", "multiword", "264", None),
        ("multiword-one-below", "multiword", "263", "declaration capacity exceeded: bodies required 264; total required 264; configured total 263"),
        ("zero-body-default", "zero-body-spc", None, None),
        ("zero-body-exact", "zero-body-spc", "1", None),
    ]
    for version in (1, 2):
        for suffix, budget in (("default", None), ("budget-one-ignored", "1"), ("bad-config-ignored", "not-a-number")):
            result.append((f"legacy-v{version}-{suffix}", f"legacy-v{version}", budget, None))
    for suffix, budget in (("zero", "0"), ("negative", "-1"), ("overflow", "2147483648"), ("noncanonical", "+1")):
        result.append((f"multiword-invalid-{suffix}", "multiword", budget,
                       "CCX_FORCE_ACCOUNTING_MAX_DECLARATIONS requires a canonical integer in 1..2147483647"))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("label")
    parser.add_argument("--compiler", type=Path)
    parser.add_argument("--sanitize", action="store_true", help="Also compile/run ASan+UBSan; an explicitly requested sanitizer failure is not skipped")
    args = parser.parse_args()
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", args.label), "Unsafe fresh output label")
    require(not sys.flags.optimize, "Do not optimize away QA conditions")
    # Use the real reviewed Apple toolchain, not the /usr/bin selection shim.
    compiler = (args.compiler or Path("/Library/Developer/CommandLineTools/usr/bin/clang")).resolve(strict=True)
    paths = {name: path for name, (path, _) in PINS.items()}
    paths.update(supervisor=Path(__file__).resolve(), compiler=compiler,
                 python=Path(sys.executable).resolve(strict=True), native_build_receipt=NATIVE.parents[2] / "build-receipt.json",
                 pixi_lock=REPO / "pixi.lock",
                 native_toolchain_lock=REPO / "package/local-completion/calculix-9zt-probe/pixi.lock")
    for name in ("libarpack.2.dylib", "libblas.3.dylib", "liblapack.3.dylib", "libopenblas.0.dylib",
                 "libgfortran.5.dylib", "libomp.dylib", "libquadmath.0.dylib", "libgcc_s.1.1.dylib"):
        paths["candidate_runtime_" + name] = REPO / ".pixi/envs/default/lib" / name
    if args.sanitize:
        require(compiler == Path("/Library/Developer/CommandLineTools/usr/bin/clang"),
                "Sanitizer-runtime fence is qualified only for the reviewed Apple compiler")
        for name in ("asan", "ubsan"):
            paths["compiler_runtime_" + name] = Path("/Library/Developer/CommandLineTools/usr/lib/clang/21/lib/darwin") / ("libclang_rt." + name + "_osx_dynamic.dylib")
    for name, (path, wanted) in PINS.items():
        require(sha(path) == wanted, f"Root-reviewed {name} pin differs")
    build_receipt = json.loads(paths["native_build_receipt"].read_text())
    require(build_receipt["binary_sha256"] == PINS["candidate"][1] and
            build_receipt["extra_source_sha256"] == PINS["production"][1] and
            build_receipt["probe_patch_sha256"] == PINS["hooks"][1] and
            build_receipt["toolchain_lock_sha256"] == sha(paths["native_toolchain_lock"]) and
            build_receipt["binary"] == str(PINS["candidate"][0]) and
            build_receipt["channel"] == "CCX_FORCE_ACCOUNTING_V3" and
            not build_receipt["physical_duty_qualified"] and
            build_receipt["dependency_functional_tests_passed"] and not build_receipt["installed"],
            "Qualified candidate build receipt differs")
    # Verify the exact shared supervisor before importing it. No unreviewed
    # replacement module can run merely because it shares a search-path name.
    sys.path.insert(0, str(ROOT))
    global assert_serial, run_bounded
    from process_control import assert_serial, run_bounded
    serial()
    before = snapshot(paths)
    output = ROOT / args.label
    output.mkdir()
    specs = unit_specs()
    query_specs = [("query-default", None, 65536), ("query-one", "1", 1),
                   ("query-intended-graph", "2113", 2113), ("query-intmax", "2147483647", 2147483647)]
    query_specs += [(f"query-invalid-{index:02d}", value, None) for index, value in enumerate(INVALID)]
    manifest = {"schema": "FreeCAD-yzk-artificial-native-capacity-plan-v1", "scope": SCOPE,
                "protected_inputs": before, "unit_cases": specs, "query_cases": query_specs,
                "sanitizers_requested": args.sanitize, "no_FE_solve_or_engineering_acceptance": True}
    write(output / "manifest.json", manifest)
    manifest_sha = sha(output / "manifest.json")
    reports, builds, attempts = [], [], []
    overall = {"passed": False, "scope": SCOPE, "manifest_sha256": manifest_sha,
               "builds": builds, "cases": reports, "process_attempts": attempts, "protected_before": before,
               "no_application_mesh_FE_solve_or_installation": True,
               "physical_or_engineering_qualification": False}

    def run(label, command, budget=None, *, timeout=20, sanitized=False):
        serial()
        require(snapshot(paths) == before and sha(output / "manifest.json") == manifest_sha, "Input fence changed before child")
        directory = output / label
        directory.mkdir()
        env = environment(directory, budget)
        if sanitized:
            # Darwin ASan/UBSan are exercised; LeakSanitizer is not claimed.
            env.update(ASAN_OPTIONS="detect_leaks=0:halt_on_error=1", UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
        record = {"label": label, "scope": SCOPE, "budget_setting": budget,
                  "protected_before": before, "passed": False}
        attempts.append(record)
        try:
            with null_stdin():
                record.update(run_bounded(command(directory), cwd=directory, log=directory / "run.log",
                                          timeout=timeout, environment=env))
        except BaseException as error:
            record["supervisor_error"] = repr(error)
            raise
        finally:
            try:
                record["protected_after"] = snapshot(paths)
                record["inputs_unchanged"] = record["protected_after"] == before
                record["manifest_unchanged"] = sha(output / "manifest.json") == manifest_sha
            except BaseException as error:
                record["fence_error"] = repr(error)
                record["inputs_unchanged"] = False
                record["manifest_unchanged"] = False
            if (directory / "run.log").is_file():
                record["retained_log_sha256"] = sha(directory / "run.log")
            # Preserve the owned attempt even if later schema, fence, cleanup
            # or output checks fail before an execution receipt can be written.
            process_record = {key: value for key, value in record.items() if key != "passed"}
            process_record["output_validation_not_yet_performed"] = True
            write(directory / "process.json", process_record)
        require(record["inputs_unchanged"] and record["manifest_unchanged"], "Child changed reviewed inputs")
        require(record.get("child_reaped") and record.get("process_group_gone") and not record.get("timed_out"), "Child cleanup/time bound failed")
        return directory, record

    try:
        for sanitized in ((False, True) if args.sanitize else (False,)):
            binary = output / ("NativeCapacityMaskUnitSanitized" if sanitized else "NativeCapacityMaskUnit")
            flags = ["-std=c11", "-O0", "-g", "-Wall", "-Wextra", "-Werror", "-fno-modules", "-DARCH=1"]
            if sanitized:
                flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
            command = [str(compiler), *flags, '-DFREECAD_FORCE_ACCOUNTING_SOURCE="' + str(SOURCE) + '"',
                       "-I" + str(NATIVE), str(UNIT), str(NATIVE / "strcmp1.o"), "-lm", "-o", str(binary)]
            label = "compile-sanitized" if sanitized else "compile"
            directory, record = run(label, lambda _: command, timeout=90)
            record["passed"] = record["returncode"] == 0 and binary.is_file()
            if record["passed"]:
                record["binary_sha256"] = sha(binary)
            builds.append(record)
            write(directory / "execution.json", record)
            require(record["passed"], "Actual-source artificial unit compilation failed")
            binary_sha = sha(binary)
            for label, case, budget, refusal in specs:
                actual_label = ("sanitized-" if sanitized else "") + label
                require(sha(binary) == binary_sha, "Unit executable changed before execution")
                directory, record = run(actual_label, lambda directory, case=case: [str(binary), case, str(directory / "ARTIFICIAL_REQUEST_NOT_FE_INPUT")],
                                        budget, sanitized=sanitized)
                log = (directory / "run.log").read_text()
                request = directory / "ARTIFICIAL_REQUEST_NOT_FE_INPUT"
                native_output = Path(str(request) + ".out")
                record.update(case=case, expected_refusal=refusal, binary_sha256=binary_sha,
                              request_sha256=sha(request) if request.is_file() else None,
                              native_output_sha256=sha(native_output) if native_output.is_file() else None)
                require(sha(binary) == binary_sha, "Unit executable changed during execution")
                if refusal:
                    record["passed"] = record["returncode"] == 201 and refusal in log and not native_output.exists() and MARKER not in log
                else:
                    lines = log.splitlines()
                    result = json.loads(lines[-1])
                    applied = [json.loads(line[len(MARKER):]) for line in lines if line.startswith(MARKER)]
                    legacy = case.startswith("legacy-")
                    require(applied == ([] if legacy else [expected_applied(case, int(budget) if budget is not None else 65536)]), "Actual native applied-capacity marker differs")
                    record["component_result"] = result
                    record["applied_capacity"] = applied
                    record["passed"] = record["returncode"] == 0 and result == expected_result(case) and native_output.is_file()
                expected_files = ["ARTIFICIAL_REQUEST_NOT_FE_INPUT", "process.json", "run.log"]
                if not refusal:
                    expected_files.append("ARTIFICIAL_REQUEST_NOT_FE_INPUT.out")
                record["only_expected_unit_artifacts_created"] = sorted(path.name for path in directory.iterdir()) == sorted(expected_files)
                record["passed"] = record["passed"] and record["only_expected_unit_artifacts_created"]
                reports.append(record)
                write(directory / "execution.json", record)
                print(json.dumps({"case": actual_label, "passed": record["passed"]}), flush=True)
                require(record["passed"], "Artificial native capacity case failed")
        for label, budget, expected in query_specs:
            directory, record = run(label, lambda _: [str(PINS["candidate"][0]), "--freecad-force-accounting-capacity"], budget, timeout=10)
            log = (directory / "run.log").read_text()
            if expected is None:
                record["passed"] = record["returncode"] == 201 and "*ERROR CCX force accounting V3: CCX_FORCE_ACCOUNTING_MAX_DECLARATIONS requires a canonical integer in 1..2147483647" in log
            else:
                record["query"] = json.loads(log)
                record["passed"] = record["returncode"] == 0 and record["query"] == expected_capacity(expected)
            record["only_query_log_created"] = sorted(path.name for path in directory.iterdir()) == ["process.json", "run.log"]
            record["passed"] = record["passed"] and record["only_query_log_created"]
            reports.append(record)
            write(directory / "execution.json", record)
            print(json.dumps({"case": label, "passed": record["passed"]}), flush=True)
            require(record["passed"], "Native capacity CLI query failed")
        overall["passed"] = len(reports) == len(specs) * len(builds) + len(query_specs) and all(row["passed"] for row in reports + builds)
    except BaseException as error:
        overall["error"] = repr(error)
    finally:
        try:
            overall["protected_after"] = snapshot(paths)
            overall["inputs_unchanged"] = overall["protected_after"] == before
            overall["manifest_unchanged"] = sha(output / "manifest.json") == manifest_sha
        except BaseException as error:
            overall["fence_error"] = repr(error)
            overall["inputs_unchanged"] = False
            overall["manifest_unchanged"] = False
        overall["passed"] = overall["passed"] and overall["inputs_unchanged"] and overall["manifest_unchanged"]
        write(output / "summary.json", overall)
        print(json.dumps({"passed": overall["passed"], "cases": len(reports), "builds": len(builds),
                          "summary": str(output / "summary.json"), "scope": SCOPE}), flush=True)
    serial()
    return 0 if overall["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
