"""Bounded private GUI producer with supervisor and native-image custody."""
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
label, executable, bridge_argument = sys.argv[1:]
assert Path(label).name == label and label not in ("", ".", "..")
bridge = Path(bridge_argument).resolve()
assert bridge.parent == root and bridge.is_file()
out = root / label
out.mkdir()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


protected = [Path(__file__).resolve(), root / "run_cold_restore.py",
             root / "NativeMixedGuiPersistenceWitness.py", root / "NativeMixedGuiColdRestore.py",
             root / "NativeMixedGuiGreenWitness.py", root / "NativeMixedGuiWitness.py",
             root / "GuiMaterialReadBridge.cpp", root / "GuiMaterialReadBridge.so", bridge,
             root / "compile_green_bridge.py"]
before = {str(path): sha(path) for path in protected}
for path in protected:
    shutil.copy2(path, out / path.name)
environment = dict(os.environ)
for name in ("PYTHONPATH", "PYTHONHOME"):
    environment.pop(name, None)
for name in ("FREECAD_USER_HOME", "FREECAD_USER_DATA", "FREECAD_USER_TEMP",
             "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
    path = out / name.lower()
    path.mkdir()
    environment[name] = str(path)
environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1",
                   FREECAD_3SC_OUTPUT=str(out), FREECAD_3SC_BRIDGE=str(bridge),
                   FREECAD_3SC_CHECK_PERSISTENCE="1",
                   FREECAD_3SC_SUPERVISOR=str(Path(__file__).resolve()))
command = ["pixi", "run", "--frozen", executable, "-u", str(out / "user.cfg"),
           "-s", str(out / "system.cfg"), "-P", str(root),
           "-t", "NativeMixedGuiPersistenceWitness"]
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
receipt = out / "green-witness.json"
result = json.loads(receipt.read_text()) if receipt.is_file() else {}
passed = (not timed_out and code == 0 and before == after
          and result.get("verdict") == "PASS"
          and result.get("persistence", {}).get("verdict") == "PASS")
report = {"verdict": "PASS" if passed else "FAIL", "command": command,
          "exit_code": code, "process_reaped": process.poll() is not None,
          "elapsed_seconds": time.monotonic() - start, "timed_out": timed_out,
          "owned_process_group": process.pid,
          "supervisor_sha256_before": before[str(Path(__file__).resolve())],
          "supervisor_sha256_after": after[str(Path(__file__).resolve())],
          "protected_sha256_before": before, "protected_sha256_after": after,
          "native_witness_receipt": str(receipt),
          "native_witness_sha256": sha(receipt) if receipt.is_file() else None}
(out / "execution.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
print((out / "run.log").read_text(errors="replace"))
sys.exit(0 if passed else 1)
