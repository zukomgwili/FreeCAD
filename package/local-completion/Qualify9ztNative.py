# SPDX-License-Identifier: LGPL-2.1-or-later
"""Qualify the V1 native contact/cut method against analytic synthetic fixtures."""

import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys

from FreeCAD9ztContactWitness import write_case


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ccx", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    root = args.evidence.resolve()
    root.mkdir(exist_ok=False)
    witness = Path(__file__).with_name("FreeCAD9ztContactWitness.py")
    cases = []
    for threads, quadratic, transformed, shear in itertools.product(
        (1, 2, 4), (False, True), (False, True), (False, True)
    ):
        name = f"t{threads}-q{int(quadratic)}-r{int(transformed)}-s{int(shear)}"
        command = [
            sys.executable,
            str(witness),
            "--ccx",
            str(args.ccx.resolve()),
            "--evidence",
            str(root / name),
            "--threads",
            str(threads),
        ]
        for flag, enabled in (
            ("--quadratic", quadratic),
            ("--transformed", transformed),
            ("--shear", shear),
        ):
            if enabled:
                command.append(flag)
        run = subprocess.run(command, capture_output=True, text=True, timeout=180)
        (root / (name + ".log")).write_text(run.stdout + run.stderr)
        if run.returncode:
            raise AssertionError(f"native analytic qualification failed: {name}")
        for side in ("slave-upper", "master-upper"):
            errors = json.loads((root / name / side / "qualification.json").read_text())
            cases.append(
                {"case": name + "/" + side, "relative_force_moment_errors": errors}
            )
    rejected = []
    for name in (
        "nlgeom",
        "missing-cut-node",
        "duplicate-support",
        "oversized-integer",
        "cut-point-load",
        "cut-mpc",
    ):
        directory = root / name
        directory.mkdir()
        write_case(directory)
        deck = directory / "contact.inp"
        request = directory / "contact.accounting"
        text = request.read_text()
        expected = "*ERROR CCX force accounting V1:"
        if name == "nlgeom":
            deck.write_text(deck.read_text().replace("*STEP\n", "*STEP,NLGEOM\n"))
            expected += " requires one small-displacement"
        elif name == "missing-cut-node":
            request.write_text(
                text.replace("BODY Lower 6 4", "BODY Lower 6 3").replace(
                    "13 14 15 16\nBODY Upper", "13 14 15\nBODY Upper"
                )
            )
            expected += " body has an undeclared"
        elif name == "duplicate-support":
            request.write_text(text.replace("END\n", "SUPPORT Duplicate 21 22\nEND\n"))
            expected += " support identities or ports overlap"
        elif name == "oversized-integer":
            request.write_text(
                text.replace("Support 21 22", "Support 9223372036854775808 22")
            )
            expected += " invalid integer field"
        elif name == "cut-point-load":
            deck.write_text(
                deck.read_text().replace(
                    "*NODE PRINT,NSET=REF", "*CLOAD\n13,1,1\n*NODE PRINT,NSET=REF"
                )
            )
            expected += " point load on cut has ambiguous body ownership"
        elif name == "cut-mpc":
            deck.write_text(
                deck.read_text().replace(
                    "*BOUNDARY", "*EQUATION\n2\n13,1,1,17,1,-1\n*BOUNDARY"
                )
            )
            expected += " cut body intersects an MPC"
        environment = dict(
            os.environ, CCX_FORCE_ACCOUNTING_REQUEST=str(request), OMP_NUM_THREADS="2"
        )
        environment.pop("CCX_9ZT_DIAGNOSTIC", None)
        run = subprocess.run(
            [str(args.ccx.resolve()), "-i", "contact"],
            cwd=directory,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )
        (directory / "solver.log").write_text(run.stdout + run.stderr)
        if run.returncode != 201 or expected not in run.stderr:
            raise AssertionError(
                f"native rejection was not established: {name}: {run.returncode} {run.stderr}"
            )
        rejected.append(
            {"case": name, "exit_code": run.returncode, "diagnostic": expected}
        )
    receipt = {
        "schema": "CCX_FORCE_ACCOUNTING_V1",
        "binary": str(args.ccx.resolve()),
        "binary_sha256": hashlib.sha256(args.ccx.read_bytes()).hexdigest(),
        "analytic_cases": cases,
        "rejections": rejected,
        "passed": True,
        "original_project_replayed": False,
        "design_accepted": False,
    }
    (root / "qualification.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(
        f"PASS {len(cases)} analytic native contact/cut cases, {len(rejected)} fail-closed cases"
    )


if __name__ == "__main__":
    main()
