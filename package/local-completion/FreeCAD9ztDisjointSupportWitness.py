# SPDX-License-Identifier: LGPL-2.1-or-later
"""Two disjoint fully prescribed native RBEs under exact unit-cube GRAV loads."""
import argparse
import json
import math
import os
from pathlib import Path
import subprocess

from FreeCAD9ztContactWitness import TETS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ccx", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    root = args.evidence.resolve()
    root.mkdir(exist_ok=False)
    lines = ["*NODE"]
    for block, (x, y) in enumerate(((2, 3), (-4, 7))):
        for offset, point in enumerate(
            (
                (x, y, 0),
                (x + 1, y, 0),
                (x + 1, y + 1, 0),
                (x, y + 1, 0),
                (x, y, 1),
                (x + 1, y, 1),
                (x + 1, y + 1, 1),
                (x, y + 1, 1),
            ),
            1,
        ):
            lines.append(f"{8*block+offset}," + ",".join(map(str, point)))
    lines += [
        "17,-1,-2,-3",
        "18,-1,-2,-3",
        "19,-7,1,-2",
        "20,-7,1,-2",
        "*ELEMENT,TYPE=C3D4,ELSET=ALL",
    ]
    for block in range(2):
        for offset, tet in enumerate(TETS, 1):
            lines.append(
                str(6 * block + offset)
                + ","
                + ",".join(str(8 * block + node + 1) for node in tet)
            )
    lines += [
        "*NSET,NSET=A",
        "1,2,3,4,5,6,7,8",
        "*NSET,NSET=B",
        "9,10,11,12,13,14,15,16",
        "*NSET,NSET=PORTS",
        "17,18,19,20",
        "*RIGID BODY,NSET=A,REF NODE=17,ROT NODE=18",
        "*RIGID BODY,NSET=B,REF NODE=19,ROT NODE=20",
        "*MATERIAL,NAME=M",
        "*ELASTIC",
        "1000000,.25",
        "*DENSITY",
        "2",
        "*SOLID SECTION,ELSET=ALL,MATERIAL=M",
        "*BOUNDARY",
        "17,1,3,0",
        "18,1,3,0",
        "19,1,3,0",
        "20,1,3,0",
        "*STEP",
        "*STATIC",
        "1,1",
        "*DLOAD",
        "ALL,GRAV,3,0,0,-1",
        "*NODE PRINT,NSET=PORTS",
        "RF",
        "*END STEP",
    ]
    (root / "supports.inp").write_text("\n".join(lines) + "\n")
    request = root / "supports.accounting"
    request.write_text(
        "CCX_FORCE_ACCOUNTING_V1\nSUPPORT A 17 18\nSUPPORT B 19 20\nEND\n"
    )
    environment = dict(
        os.environ, CCX_FORCE_ACCOUNTING_REQUEST=str(request), OMP_NUM_THREADS="2"
    )
    run = subprocess.run(
        [str(args.ccx.resolve()), "-i", "supports"],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    (root / "solver.log").write_text(run.stdout + run.stderr)
    if run.returncode:
        raise AssertionError(run.stderr)
    rows = {
        row[1]: list(map(float, row[2:]))
        for line in Path(str(request) + ".out").read_text().splitlines()
        if (row := line.split()) and row[0] == "SUPPORT"
    }
    expected = {"A": [0, 0, 6, 21, -15, 0], "B": [0, 0, 6, 45, 21, 0]}
    for name, wanted in expected.items():
        assert math.dist(rows[name][:3], wanted[:3]) <= 0.01 * math.hypot(*wanted[:3])
        assert math.dist(rows[name][3:], wanted[3:]) <= 0.01 * math.hypot(*wanted[3:])
    (root / "qualification.json").write_text(
        json.dumps({"passed": True, "expected": expected, "actual": rows}, indent=2)
        + "\n"
    )
    print("PASS two disjoint support force/origin-moment wrenches")


if __name__ == "__main__":
    main()
