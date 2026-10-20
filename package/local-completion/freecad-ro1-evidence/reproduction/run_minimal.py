"""Bounded isolated native test wrapper; each label is exclusive evidence."""
import sys
sys.dont_write_bytecode = True
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time
ROOT = Path(__file__).resolve().parent
assert len(sys.argv) == 2 and sys.argv[1] in ("red-minimal-1", "red-minimal-2", "red-minimal-3", "green-minimal")
run = ROOT / sys.argv[1]
run.mkdir()
environment = dict(os.environ)
for key in ("PYTHONPATH", "PYTHONHOME", "FREECAD_9ZT_CCX", "FREECAD_9ZT_PRODUCTION_CCX",
            "CCX_FORCE_ACCOUNTING_REQUEST", "CCX_9ZT_DIAGNOSTIC"):
    environment.pop(key, None)
for key in ("FREECAD_USER_HOME", "FREECAD_USER_DATA", "FREECAD_USER_TEMP",
            "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME"):
    path = run / key.lower()
    path.mkdir()
    environment[key] = str(path)
environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1", OMP_NUM_THREADS="2",
                   TMPDIR=environment["FREECAD_USER_TEMP"], FREECAD_RO1_OUTPUT=str(run))
command = ["pixi", "run", "--frozen", "/Applications/FreeCAD-27.1.0.app/Contents/MacOS/FreeCADCmd",
           "-u", str(run / "user.cfg"), "-s", str(run / "system.cfg"),
           "-P", str(ROOT), "-t", "MinimalTieOwnership"]
receipt = {"command": command, "timed_out": False,
           "harness_sha256": hashlib.sha256((ROOT / "MinimalTieOwnership.py").read_bytes()).hexdigest()}
start = time.monotonic()
with (run / "run.log").open("xb") as log:
    process = subprocess.Popen(command, cwd="/Users/zukomgwili/src/FreeCAD", env=environment,
                               stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        code = process.wait(timeout=120)
    except subprocess.TimeoutExpired:
        receipt["timed_out"] = True
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        code = process.returncode
receipt.update(exit_code=code, elapsed_seconds=time.monotonic() - start,
               process_reaped=process.poll() is not None)
(run / "execution.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps(receipt, indent=2))
print((run / "run.log").read_text(errors="replace")[-8000:])
raise SystemExit(code)
