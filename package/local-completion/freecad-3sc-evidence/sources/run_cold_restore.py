"""Bounded Cmd reader using the producer's actual private library/profile."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

root = Path(__file__).resolve().parent
label, executable, expected_argument = sys.argv[1:]
assert Path(label).name == label and label not in ("", ".", "..")
expected_path = Path(expected_argument).resolve()
expected = json.loads(expected_path.read_text())
producer = expected_path.parent
assert producer.is_relative_to(root) and producer != root
out = root / label
out.mkdir()
def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

protected = [Path(__file__).resolve(), root / "NativeMixedGuiColdRestore.py", expected_path]
protected.extend(Path(expected[name][key]) for name in ("gui_material", "public_api_null_material")
                 for key in ("card", "document"))
before = {str(path): sha(path) for path in protected}
for path in protected:
    if path.parent == root:
        shutil.copy2(path, out / path.name)
environment = dict(os.environ)
for name in ("PYTHONPATH", "PYTHONHOME"):
    environment.pop(name, None)
for name, value in expected["scope"]["private_environment"].items():
    path = Path(value).resolve()
    assert path.is_relative_to(producer) and path != producer
    environment[name] = str(path)
environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1",
                   FREECAD_3SC_OUTPUT=str(out), FREECAD_3SC_EXPECTED=str(expected_path),
                   FREECAD_3SC_SUPERVISOR=str(Path(__file__).resolve()))
command = ["pixi", "run", "--frozen", executable,
           "-u", str(producer / "user.cfg"), "-s", str(producer / "system.cfg"),
           "-P", str(root), "-t", "NativeMixedGuiColdRestore"]
start = time.monotonic()
timed_out = False
with (out / "run.log").open("xb") as log:
    process = subprocess.Popen(command, env=environment, stdout=log,
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
            process.wait()
        code = process.returncode
after = {str(path): sha(path) for path in protected}
report = {"command": command, "exit_code": code, "process_reaped": process.poll() is not None,
          "elapsed_seconds": time.monotonic() - start, "timed_out": timed_out,
          "owned_process_group": process.pid,
          "supervisor_sha256_before": before[str(Path(__file__).resolve())],
          "supervisor_sha256_after": after[str(Path(__file__).resolve())],
          "protected_sha256_before": before, "protected_sha256_after": after}
(out / "execution.json").write_text(json.dumps(report, indent=2) + "\n")
receipt = out / "cold-restore-report.json"
passed = (not timed_out and code == 0 and before == after and receipt.is_file()
          and json.loads(receipt.read_text()).get("verdict") == "PASS")
report["verdict"] = "PASS" if passed else "FAIL"
report["native_witness_receipt"] = str(receipt)
report["native_witness_sha256"] = sha(receipt) if receipt.is_file() else None
(out / "execution.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
print((out / "run.log").read_text(errors="replace"))
sys.exit(0 if passed else 1)
