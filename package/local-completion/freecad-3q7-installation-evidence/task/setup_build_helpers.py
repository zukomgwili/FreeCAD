"""Root-only new-file setup of immutable deployment build/custody helpers.

Copies only the four exact retained Python helper bodies listed below. It does
not import those helpers or execute a build, native process, probe or install.
Existing destinations refuse, and retained source files are end-fenced.
"""

import ast
import hashlib
import json
from pathlib import Path

ROOT = Path("/private/tmp/freecad-3q7-install-W35DLJ")
SOURCE = Path("/Users/zukomgwili/src/FreeCAD/package/local-completion/freecad-yzk-installation-evidence/private")
PINS = {
    "run_build_gate.py": "9407dccd67c7bf2416585a1101d351fc01da2e44c4ff8e10cab6147af87ac8ec",
    "preservation.py": "30fb49829d4f017ca99d82f7d2e169ec244d691150cb0f5c5f1ea00b73ff3989",
    "process_control_devnull.py": "aa917661632196ef95578ea21424ccbe630f88a285c8e05fa73aa0a6811a6463",
    "process_control.py": "5199c733fdc18a2c6f78d03ea2a3281e236419365219d7b9f33b5ecca0aa733d",
}


def main():
    assert ROOT.is_dir() and not ROOT.is_symlink()
    bodies = {}
    for name, wanted in PINS.items():
        source, target = SOURCE / name, ROOT / name
        assert source.is_file() and not source.is_symlink()
        assert not target.exists() and not target.is_symlink()
        body = source.read_bytes()
        assert hashlib.sha256(body).hexdigest() == wanted
        ast.parse(body, filename=str(source))
        bodies[name] = body
    for name, body in bodies.items():
        with (ROOT / name).open("xb") as stream:
            stream.write(body)
    for name, body in bodies.items():
        assert (SOURCE / name).read_bytes() == (ROOT / name).read_bytes() == body
    print(json.dumps({"passed": True, "copies": PINS, "native_execution_performed": False}))


if __name__ == "__main__":
    main()
