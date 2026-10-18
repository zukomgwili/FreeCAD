# SPDX-License-Identifier: LGPL-2.1-or-later
"""Give FreeCADCmd's embedded unittest results a real process exit status."""

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freecad-cmd", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--require-physical-rf", action="store_true")
    parser.add_argument("--threads", type=int, choices=(1, 2, 4), default=2)
    args = parser.parse_args()
    root = args.evidence.resolve()
    root.mkdir(parents=False, exist_ok=False)
    environment = dict(os.environ)
    environment.pop("FREECAD_9ZT_CCX", None)
    environment.pop("FREECAD_9ZT_REQUIRE_PHYSICAL_RF", None)
    environment.pop("CCX_9ZT_DIAGNOSTIC", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["OMP_NUM_THREADS"] = str(args.threads)
    environment["FREECAD_9ZT_OUTPUT"] = str(root)
    if args.candidate:
        environment["FREECAD_9ZT_CCX"] = str(args.candidate.resolve())
    if args.require_physical_rf:
        environment["FREECAD_9ZT_REQUIRE_PHYSICAL_RF"] = "1"
    completed = subprocess.run(
        [
            str(args.freecad_cmd.resolve()),
            "-u",
            str(root / "user.cfg"),
            "-s",
            str(root / "system.cfg"),
            "-P",
            str(Path(__file__).resolve().parents[1]),
            "-t",
            "FreeCAD9ztSupportWitness",
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    text = completed.stdout + completed.stderr
    (root / "witness.log").write_text(text)
    match = re.search(r"Ran (\d+) tests? in [^\n]+\n\s*\n(OK[^\n]*|FAILED[^\n]*)", text)
    success = (
        completed.returncode == 0 and match is not None and match[2].startswith("OK")
    )
    print(match[0] if match else text[-4000:])
    print(f"Evidence: {root}")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
