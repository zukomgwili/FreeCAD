# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native, analytic contact/cut benchmark; never edits a project deck.

Three unit cubes, x=2..3, y=3..4, z=0..3. Bottom cube is rigidly
supported. Upper two cubes share a deformable cut at z=2 and contact the
bottom cube at z=1. Density=2, gravity=3, top pressure=4. Each cube weighs
6 native force units. Expected support Fz=22, contact=16, cut=10.
All reference wrenches are declared before solving, about global origin.
"""

import argparse
import json
import math
import os
from pathlib import Path
import subprocess


FACES = ((0, 1, 2), (0, 3, 1), (1, 3, 2), (2, 3, 0))
TETS = (
    (0, 1, 2, 6),
    (0, 2, 3, 6),
    (0, 3, 7, 6),
    (0, 7, 4, 6),
    (0, 4, 5, 6),
    (0, 5, 1, 6),
)


def rotate(vector):
    y, z = math.radians(35), math.radians(20)
    x1 = math.cos(y) * vector[0] + math.sin(y) * vector[2]
    z1 = -math.sin(y) * vector[0] + math.cos(y) * vector[2]
    return (
        math.cos(z) * x1 - math.sin(z) * vector[1],
        math.sin(z) * x1 + math.cos(z) * vector[1],
        z1,
    )


def cross(left, right):
    return [
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    ]


def write_case(
    directory, reverse=False, quadratic=False, transformed=False, shear=False
):
    nodes = {}
    for layer in range(2):
        for corner, (x, y) in enumerate(((2, 3), (3, 3), (3, 4), (2, 4))):
            nodes[1 + layer * 4 + corner] = (x, y, layer)
    for layer in range(3):
        for corner, (x, y) in enumerate(((2, 3), (3, 3), (3, 4), (2, 4))):
            nodes[9 + layer * 4 + corner] = (x, y, 1 + layer)
    nodes[21] = (-1, -2, -3)
    nodes[22] = (-1, -2, -3)
    elements = {}
    for block, ids in enumerate(
        (tuple(range(1, 9)), tuple(range(9, 17)), tuple(range(13, 21)))
    ):
        for offset, tet in enumerate(TETS):
            elements[1 + block * 6 + offset] = tuple(ids[index] for index in tet)
    if quadratic:
        edges = {}
        for element, corners in list(elements.items()):
            midsides = []
            for a, b in ((0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3)):
                edge = tuple(sorted((corners[a], corners[b])))
                if edge not in edges:
                    node = max(nodes) + 1
                    nodes[node] = tuple(
                        (x + y) / 2 for x, y in zip(nodes[edge[0]], nodes[edge[1]])
                    )
                    edges[edge] = node
                midsides.append(edges[edge])
            elements[element] += tuple(midsides)
    cut_nodes = sorted(
        {
            node
            for element in range(7, 13)
            for node in elements[element]
            if nodes[node][2] == 2
        }
    )
    base_nodes = sorted({node for element in range(1, 7) for node in elements[element]})

    def surface(element_ids, z):
        return [
            (element, face + 1)
            for element in element_ids
            for face, local in enumerate(FACES)
            if all(nodes[elements[element][index]][2] == z for index in local)
        ]

    bottom_contact = surface(range(1, 7), 1)
    upper_contact = surface(range(7, 13), 1)
    top = surface(range(13, 19), 3)
    if transformed:
        nodes = {
            node: tuple(
                value + offset for value, offset in zip(rotate(position), (11, -4, 7))
            )
            for node, position in nodes.items()
        }
    gravity = rotate((0, 0, -1)) if transformed else (0, 0, -1)
    lines = ["*HEADING", "FreeCAD-9zt native contact accounting witness", "*NODE"]
    lines += [f"{node},{x},{y},{z}" for node, (x, y, z) in nodes.items()]
    lines += ["*ELEMENT,TYPE=" + ("C3D10" if quadratic else "C3D4") + ",ELSET=ALL"]
    lines += [
        str(element) + "," + ",".join(map(str, ids))
        for element, ids in elements.items()
    ]
    lines += ["*NSET,NSET=BASE"]
    lines += [
        ",".join(map(str, base_nodes[index : index + 12]))
        for index in range(0, len(base_nodes), 12)
    ]
    lines += [
        "*NSET,NSET=REF",
        "21",
        "*NSET,NSET=ROT",
        "22",
        "*RIGID BODY,NSET=BASE,REF NODE=21,ROT NODE=22",
        "*MATERIAL,NAME=ELASTIC",
        "*ELASTIC",
        "1000000,.25",
        "*DENSITY",
        "2",
        "*SOLID SECTION,ELSET=ALL,MATERIAL=ELASTIC",
    ]
    for name, facets in (("BOTTOM", bottom_contact), ("UPPER", upper_contact)):
        lines += [f"*SURFACE,NAME={name},TYPE=ELEMENT"]
        lines += [f"{element},S{face}" for element, face in facets]
    lines += [
        "*SURFACE INTERACTION,NAME=I",
        "*SURFACE BEHAVIOR,PRESSURE-OVERCLOSURE=LINEAR",
        "1000000",
    ]
    if shear:
        lines += ["*FRICTION", ".5,1000000"]
    lines += [
        "*CONTACT PAIR,INTERACTION=I,TYPE=SURFACE TO SURFACE",
        "BOTTOM,UPPER" if reverse else "UPPER,BOTTOM",
        "*BOUNDARY",
        "21,1,3,0",
        "22,1,3,0",
        "*STEP",
        "*STATIC",
        "1,1",
        "*DLOAD",
        "ALL,GRAV,3," + ",".join(map(str, gravity)),
    ]
    lines += [f"{element},P{face},4" for element, face in top]
    if shear:
        vector = rotate((0.25, 0, 0)) if transformed else (0.25, 0, 0)
        lines += ["*CLOAD"]
        lines += [
            f"{node},{axis+1},{value}"
            for node in range(17, 21)
            for axis, value in enumerate(vector)
            if value != 0
        ]
    lines += [
        "*NODE PRINT,NSET=REF,TOTALS=ONLY",
        "RF",
        "*NODE PRINT,NSET=ROT,TOTALS=ONLY",
        "RF",
        "*NODE FILE",
        "U,RF",
        "*EL FILE",
        "S",
        "*END STEP",
    ]
    (directory / "contact.inp").write_text("\n".join(lines) + "\n")
    request = [
        "CCX_FORCE_ACCOUNTING_V1",
        "SUPPORT Support 21 22",
        f"BODY Lower 6 {len(cut_nodes)}",
        "7 8 9 10 11 12",
        " ".join(map(str, cut_nodes)),
        f"BODY Upper 6 {len(cut_nodes)}",
        "13 14 15 16 17 18",
        " ".join(map(str, cut_nodes)),
        "END",
    ]
    (directory / "contact.accounting").write_text("\n".join(request) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ccx", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--quadratic", action="store_true")
    parser.add_argument("--transformed", action="store_true")
    parser.add_argument("--shear", action="store_true")
    args = parser.parse_args()
    root = args.evidence.resolve()
    root.mkdir(exist_ok=False)
    for reverse in (False, True):
        directory = root / ("master-upper" if reverse else "slave-upper")
        directory.mkdir()
        write_case(directory, reverse, args.quadratic, args.transformed, args.shear)
        environment = dict(os.environ)
        environment.pop("CCX_9ZT_DIAGNOSTIC", None)
        environment["OMP_NUM_THREADS"] = str(args.threads)
        environment["CCX_FORCE_ACCOUNTING_REQUEST"] = str(
            directory / "contact.accounting"
        )
        run = subprocess.run(
            [str(args.ccx.resolve()), "-i", "contact"],
            cwd=directory,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )
        (directory / "solver.log").write_text(run.stdout + run.stderr)
        if run.returncode:
            raise AssertionError(
                f"native solver failed ({run.returncode}): {directory}"
            )
        output = directory / "contact.accounting.out"
        if not output.exists():
            raise AssertionError(f"native physical accounting output missing: {output}")
        expected = {
            ("SUPPORT", "Support"): [0, 0, 22, 77, -55, 0],
            ("CUT", "Lower"): [0, 0, -10, -35, 25, 0],
            ("CUT", "Upper"): [0, 0, 10, 35, -25, 0],
        }
        if args.shear:
            expected = {
                ("SUPPORT", "Support"): [-1, 0, 22, 77, -58, 3.5],
                ("CUT", "Lower"): [1, 0, -10, -35, 28, -3.5],
                ("CUT", "Upper"): [-1, 0, 10, 35, -28, 3.5],
            }
        if args.transformed:
            for identity, wrench in expected.items():
                force = rotate(wrench[:3])
                moment = [
                    a + b for a, b in zip(rotate(wrench[3:]), cross((11, -4, 7), force))
                ]
                expected[identity] = list(force) + moment
        rows = {
            tuple(row[:2]): list(map(float, row[2:8]))
            for line in output.read_text().splitlines()
            if (row := line.split()) and row[0] in ("SUPPORT", "CUT")
        }
        errors = {}
        for identity, wanted in expected.items():
            got = rows[identity]
            if not all(math.isfinite(value) for value in got):
                raise AssertionError(f"nonfinite wrench: {identity}")
            force_error = math.dist(got[:3], wanted[:3]) / math.hypot(*wanted[:3])
            moment_error = math.dist(got[3:], wanted[3:]) / math.hypot(*wanted[3:])
            errors["/".join(identity)] = [force_error, moment_error]
            if max(force_error, moment_error) > 0.01:
                raise AssertionError(
                    f"physical wrench mismatch {identity}: {got}, expected {wanted}"
                )
        (directory / "qualification.json").write_text(
            json.dumps(errors, indent=2) + "\n"
        )
    print(
        "PASS native support/contact/cut forces and global-origin moments, both owner directions"
    )


if __name__ == "__main__":
    main()
