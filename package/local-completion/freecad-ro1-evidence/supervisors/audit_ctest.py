"""Read-only post-hoc validation of one preserved CTest execution, not a rerun.

Writes only a new exclusive audit.json beside the unchanged execution/run logs.
The original supervisor failure remains false: its terminal-summary parser did
not accept this installed CTest's successful summary without a failed clause.
"""

import sys
sys.dont_write_bytecode = True

import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parent
RUN = ROOT / "committed-ctest-dot-free"
REPOSITORY = Path("/Users/zukomgwili/src/FreeCAD")
BUILD = REPOSITORY / "build/release"
EXECUTION_SHA = "9ade8c519c304dc76594f3b1ed1012ea450f05308ff94ff9394f6d6ab67e7d35"
LOG_SHA = "8e07ee64b6b07eccee31b49ddf467255beef3855dc62551ea8bc8ea1509d6dd0"
HISTORICAL_SUPERVISOR_SHA = "22018b2d7ffca9b7c2aa8991900bbe4570321ff2b329a45a1bc393066e9feb97"


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def observe(path):
    if not path.is_file():
        return {"exists": False}
    stat = path.stat()
    return {"exists": True, "sha256": digest(path), "bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns, "inode": stat.st_ino}


def parse(log):
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
    require(len(rows) == 2274, "Expected all 2274 catalogue outcome rows")
    require({row["catalogue"] for row in rows} == {2274}, "Inconsistent catalogue denominator")
    require({row["ordinal"] for row in rows} == set(range(1, 2275)), "Incomplete/duplicate ordinals")
    require({row["test_number"] for row in rows} == set(range(1, 2275)), "Incomplete/duplicate test numbers")
    counts = {status: sum(row["status"] == status for row in rows)
              for status in ("passed", "skipped", "disabled", "failed_or_unknown")}
    require(counts == {"passed": 2264, "skipped": 2, "disabled": 8, "failed_or_unknown": 0},
            "Per-test results differ from expected passing catalogue")
    summaries = re.findall(r'^(\d+)% tests passed(?:, (\d+) tests failed)? out of (\d+)\s*$', log, re.M)
    require(len(summaries) == 1, "Missing or duplicate terminal summary")
    percent, failures, enabled = (int(value or 0) for value in summaries[0])
    require((percent, failures, enabled) == (100, 0, 2266), "Terminal summary is not a clean pass")
    times = re.findall(r'^Total Test time \(real\) =\s*([\d.]+) sec\s*$', log, re.M)
    require(len(times) == 1, "Missing/duplicate terminal elapsed time")
    footer = [(int(number), status.lower()) for number, _name, status in re.findall(
        r'^\s*(\d+)\s+-\s+([^\r\n]+) \((Skipped|Disabled)\)\s*$', log, re.M)]
    expected = {(row["test_number"], row["status"]) for row in rows if row["status"] != "passed"}
    require(len(footer) == 10 and set(footer) == expected, "Did-not-run footer disagrees with outcomes")
    require(not re.search(r'^The following tests FAILED:|^Errors while running CTest', log, re.M),
            "CTest failure marker present")
    return {"catalogue": 2274, "enabled": 2266, "executed_passing": 2264,
            "skipped": 2, "disabled": 8, "failed": 0, "real_seconds": float(times[0]),
            "complete_unique_catalogue_verified": True, "terminal_and_footer_verified": True,
            "skipped_rows": [row for row in rows if row["status"] == "skipped"],
            "disabled_rows": [row for row in rows if row["status"] == "disabled"]}, rows


def parse_detailed(detailed, rows):
    headers = list(re.finditer(r'^\s*(\d+)/2274 Testing: [^\r\n]+$', detailed, re.M))
    require(len(headers) == 2274 and {int(match[1]) for match in headers} == set(range(1, 2275)),
            "Fresh detailed log does not contain all 2274 unique test headers")
    nonempty_ids, empty_ids = set(), set()
    for index, match in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(detailed)
        commands = re.findall(r'^Command:([^\r\n]*)$', detailed[match.end():end], re.M)
        require(len(commands) == 1, "Detailed test block has missing/duplicate Command line")
        command = commands[0].strip()
        number = int(match[1])
        if command == '""':
            empty_ids.add(number)
        else:
            require(bool(command), "Unexpected blank detailed test command")
            nonempty_ids.add(number)
    enabled_ids = {row["test_number"] for row in rows if row["status"] != "disabled"}
    disabled_ids = {row["test_number"] for row in rows if row["status"] == "disabled"}
    require(len(nonempty_ids) == 2266 and nonempty_ids == enabled_ids,
            "Detailed nonempty-command test domain differs from raw enabled outcomes")
    require(len(empty_ids) == 8 and empty_ids == disabled_ids,
            "Detailed empty-command test domain differs from raw disabled outcomes")
    require(re.search(r'^End testing:', detailed, re.M), "Detailed CTest log is incomplete")
    return {"unique_headers": 2274, "nonempty_command_tests": 2266,
            "empty_command_disabled_tests": 8, "raw_and_detailed_ID_domains_match": True}


def main():
    output = RUN / "audit.json"
    require(not output.exists(), "audit.json already exists; never overwrite audit evidence")
    receipt_path, log_path = RUN / "execution.json", RUN / "run.log"
    require(digest(receipt_path) == EXECUTION_SHA, "Original execution receipt changed")
    require(digest(log_path) == LOG_SHA, "Original raw CTest log changed")
    original = json.loads(receipt_path.read_text())
    require(original["passed"] is False, "Original supervisor verdict was not preserved false")
    require(original["error"] == "RuntimeError('Missing or duplicate terminal CTest result')",
            "Not the reviewed terminal-format-only parser failure")
    require(original["mode"] == "ctest" and original["exit_code"] == 0,
            "Not a normal successful raw CTest execution")
    require(original["command"] == ["pixi", "run", "--frozen", "ctest", "--test-dir", "build/release",
            "--output-on-failure", "--parallel", "8", "--timeout", "60"], "Unexpected command")
    require(not original["timed_out"] and original["process_reaped"] and original["owned_group_gone"]
            and not original.get("cleanup_failed"), "Execution timeout/cleanup did not pass")
    require(original["source_and_supervisor_unchanged"]
            and original["source_before"] == original["source_after"], "Original source fence failed")
    historical = original["source_before"]["files"]
    supervisor = str(ROOT / "run_build_gate.py")
    require(historical.get(supervisor) == HISTORICAL_SUPERVISOR_SHA, "Historical supervisor identity differs")
    current_source = {}
    for name, expected in historical.items():
        if name == supervisor:
            continue  # Intentionally changed only after this execution to accept both summary formats.
        path = Path(name)
        require(path.is_relative_to(REPOSITORY), "Unexpected source-fence path")
        current_source[name] = digest(path)
        require(current_source[name] == expected, "Current production source differs: " + name)
    require(len(current_source) == 19, "Incomplete selected source/CMake/new-test inventory")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPOSITORY, check=True,
                          capture_output=True, text=True, timeout=10).stdout.strip()
    require(head == original["source_before"]["git_head"], "Current commit differs from executed commit")
    current_build = {}
    for name, expected in original["build_before"]["files"].items():
        require(Path(name).is_relative_to(BUILD), "Unexpected build-fence path")
        current_build[name] = digest(name)
        require(current_build[name] == expected, "Current build/native copy differs: " + name)
    require(len(current_build) == 22, "Incomplete native/build-copy/header inventory")
    summary, rows = parse(log_path.read_text(errors="strict"))
    temporary = BUILD / "Testing/Temporary"
    prior = original["prior_ctest_logs"]
    test_path = temporary / "LastTest.log"
    last_test = observe(test_path)
    require(last_test["exists"] and last_test != prior["LastTest.log"]
            and last_test["mtime_ns"] > prior["LastTest.log"]["mtime_ns"], "No fresh detailed CTest log")
    detailed = test_path.read_text(errors="strict")
    detailed_summary = parse_detailed(detailed, rows)
    failures_path = temporary / "LastTestsFailed.log"
    failures = observe(failures_path)
    require(failures == prior["LastTestsFailed.log"], "Failed-list file unexpectedly changed since this run")
    failures["classification"] = "unchanged_stale_prior_failure_list_not_current_evidence"
    require(digest(receipt_path) == EXECUTION_SHA and digest(log_path) == LOG_SHA,
            "Original evidence changed during post-hoc audit")
    require(all(digest(name) == expected for name, expected in current_source.items())
            and all(digest(name) == expected for name, expected in current_build.items()),
            "Source/build changed during post-hoc audit")
    audit = {"passed": True, "kind": "post_hoc_validation_not_a_rerun",
        "native_processes_launched": 0, "original_supervisor_verdict_retained": False,
        "original_execution_sha256": EXECUTION_SHA, "original_log_sha256": LOG_SHA,
        "historical_supervisor_sha256": HISTORICAL_SUPERVISOR_SHA,
        "parser_format_correction": "accept optional ', 0 tests failed' in successful terminal summary",
        "raw_exit_code": 0, "timed_out": False, "process_reaped": True, "owned_group_gone": True,
        "ctest": summary, "git_head": head, "source_before_after_equal_in_original_receipt": True,
        "current_selected_source_matches_execution": current_source,
        "current_build_matches_original_build_before": current_build,
        "original_build_after_receipt_present": "build_after" in original,
        "post_hoc_not_continuous_build_observation": True,
        "fresh_detailed_log": last_test, "detailed_log_corroboration": detailed_summary,
        "failed_list": failures,
        "audit_script_sha256": digest(Path(__file__)), "created_unix_seconds": time.time()}
    with output.open("x") as target:
        target.write(json.dumps(audit, indent=2) + "\n")
    require(digest(receipt_path) == EXECUTION_SHA and digest(log_path) == LOG_SHA,
            "Original evidence changed after exclusive audit output")
    print(json.dumps({"passed": True, "audit": str(output), "sha256": digest(output),
                      "ctest": summary}, indent=2), flush=True)


if __name__ == "__main__":
    main()
