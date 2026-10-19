"""Bounded isolated source-bug witness runner, never touches user profiles."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
label, executable, module = sys.argv[1:]
out = ROOT / label
out.mkdir()
environment = dict(os.environ)
for name in ("PYTHONPATH", "PYTHONHOME"):
    environment.pop(name, None)
for name in ("FREECAD_USER_HOME", "FREECAD_USER_DATA", "FREECAD_USER_TEMP",
             "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
    path = out / name.lower()
    path.mkdir()
    environment[name] = str(path)
environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1",
                   FREECAD_3SC_OUTPUT=str(out))
command = ["pixi", "run", "--frozen", executable, "-u", str(out / "user.cfg"),
           "-s", str(out / "system.cfg"), "-P", str(ROOT), "-t", module]
start = time.monotonic()
with (out / "run.log").open("xb") as log:
    process = subprocess.Popen(command, env=environment, stdout=log,
                               stderr=subprocess.STDOUT, start_new_session=True)
    try:
        code = process.wait(timeout=180)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        raise
report = dict(command=command, exit_code=code, process_reaped=process.poll() is not None,
              elapsed_seconds=time.monotonic() - start)
(out / "execution.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
print((out / "run.log").read_text(errors="replace"))
sys.exit(code)
