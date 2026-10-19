"""Bounded signed-app GUI producer and separate cold-reader supervisor."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time

from RuntimeIdentity import COMMIT, PROFILE_KEYS, REVISION, sha

ROOT = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("phase", choices=("stage", "installed"))
parser.add_argument("mode", choices=("gui", "cold"))
args = parser.parse_args()
work = ROOT / args.phase
manifest_path = work / "runtime.json"
identity = json.loads(manifest_path.read_text())
assert identity["phase"] == args.phase and identity["commit"] == COMMIT
assert identity["revision"] == REVISION
app = Path(identity["application"]).resolve(strict=True)
expected_app = ROOT.parent / "FreeCAD-27.1.0.app" if args.phase == "stage" else Path("/Applications/FreeCAD-27.1.0.app")
assert app == expected_app.resolve(strict=True)
producer = ROOT / f"{args.phase}-3sc-gui"
out = ROOT / f"{args.phase}-3sc-{args.mode}"
out.mkdir()
protected = list(identity["protected_sha256"])
protected += [str(manifest_path), str(Path(__file__).resolve())]
environment = dict(os.environ)
for name in list(environment):
    if name.startswith("FREECAD_3SC_"):
        environment.pop(name)
for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH"):
    environment.pop(name, None)
environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1",
                   FREECAD_3SC_OUTPUT=str(out), FREECAD_3SC_BRIDGE=identity["bridge"],
                   FREECAD_3SC_RUNTIME_MANIFEST=str(manifest_path),
                   FREECAD_3SC_SUPERVISOR=str(Path(__file__).resolve()))
if args.mode == "gui":
    for name in PROFILE_KEYS:
        path = out / name.lower()
        path.mkdir()
        environment[name] = str(path)
    environment["FREECAD_3SC_CHECK_PERSISTENCE"] = "1"
    executable = app / "Contents/MacOS/FreeCAD"
    module = "NativeMixedGuiPersistenceWitness"
    config_root = out
else:
    expected_path = producer / "cold-restore-expected.json"
    expected = json.loads(expected_path.read_text())
    assert expected["runtime"][-1] == COMMIT and expected["runtime"][3] == REVISION
    assert expected["runtime_identity"]["application"] == str(app)
    for name, value in expected["scope"]["private_environment"].items():
        assert name in PROFILE_KEYS
        path = Path(value).resolve(strict=True)
        assert path.is_relative_to(producer) and path != producer
        environment[name] = str(path)
    environment["FREECAD_3SC_EXPECTED"] = str(expected_path)
    protected += [str(expected_path), str(producer / "green-witness.json"), str(producer / "execution.json")]
    protected += [expected[name][key] for name in ("gui_material", "public_api_null_material")
                  for key in ("card", "document")]
    executable = app / "Contents/MacOS/FreeCADCmd"
    module = "NativeMixedGuiColdRestore"
    config_root = producer
for name in PROFILE_KEYS:
    assert Path(environment[name]).resolve().is_relative_to(producer if args.mode == "cold" else out)
for path, digest in identity["protected_sha256"].items():
    assert sha(path) == digest, path
before = {path: sha(path) for path in dict.fromkeys(protected)}
for path in work.iterdir():
    if path.is_file():
        shutil.copy2(path, out / path.name)
command = [str(executable), "-u", str(config_root / "user.cfg"), "-s", str(config_root / "system.cfg"),
           "-P", str(work), "-t", module]
start = time.monotonic()
timed_out = False
with (out / "run.log").open("xb") as log:
    process = subprocess.Popen(command, cwd=work, env=environment, stdout=log,
                               stderr=subprocess.STDOUT, start_new_session=True)
    try:
        code = process.wait(timeout=180)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        code = process.returncode
after = {path: sha(path) for path in before}
receipt = out / ("green-witness.json" if args.mode == "gui" else "cold-restore-report.json")
native = json.loads(receipt.read_text()) if receipt.is_file() else {}
log_text = (out / "run.log").read_text(errors="replace")
test_count = re.findall(r"Ran (\d+) test(?:s)? in ([0-9.]+)s", log_text)
normal_test_pass = len(test_count) == 1 and test_count[0][0] == "1"
normal_test_pass = normal_test_pass and bool(re.search(r"\nOK\s*(?:\n|$)", log_text))
normal_test_pass = normal_test_pass and not re.search(r"FAILED \(|Traceback|^ERROR:|^FAIL:", log_text, re.MULTILINE)
passed = (not timed_out and code == 0 and process.poll() is not None and before == after
          and normal_test_pass and native.get("verdict") == "PASS"
          and (args.mode != "gui" or native.get("persistence", {}).get("verdict") == "PASS"))
report = {"verdict": "PASS" if passed else "FAIL", "passed": passed, "phase": args.phase,
          "mode": args.mode, "application": str(app), "expected_commit": COMMIT,
          "expected_revision": REVISION, "command": command, "exit_code": code,
          "process_reaped": process.poll() is not None, "owned_process_group": process.pid,
          "elapsed_seconds": time.monotonic() - start, "timed_out": timed_out,
          "normal_test_pass": normal_test_pass, "test_counts_seconds": test_count,
          "protected_sha256_before": before, "protected_sha256_after": after,
          "supervisor_sha256_before": before[str(Path(__file__).resolve())],
          "supervisor_sha256_after": after[str(Path(__file__).resolve())],
          "runtime_manifest": str(manifest_path), "runtime_manifest_sha256": sha(manifest_path),
          "native_witness_receipt": str(receipt),
          "native_witness_sha256": sha(receipt) if receipt.is_file() else None}
(out / "execution.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
print(log_text)
raise SystemExit(0 if passed else 1)
