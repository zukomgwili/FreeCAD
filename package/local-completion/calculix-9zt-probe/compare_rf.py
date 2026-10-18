# SPDX-License-Identifier: LGPL-2.1-or-later
"""Compare unchanged standard RF against a separately built baseline solver."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


def totals(dat):
    return {
        name: [float(value) for value in row.split()]
        for name, row in re.findall(
            r"total force[^\n]*for set (\S+)[^\n]*\n\s*\n([^\n]+)", dat
        )
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    root = args.evidence.resolve()
    root.mkdir(parents=False, exist_ok=False)
    environment = dict(os.environ)
    environment.pop("CCX_9ZT_DIAGNOSTIC", None)
    environment["OMP_NUM_THREADS"] = "2"
    cases = []
    for path in sorted(args.cases.glob("support-gravity-*/characterization.json")):
        report = json.loads(path.read_text())
        if "experimental_support_force_N" not in report:
            continue
        target = root / path.parent.name
        target.mkdir()
        source = path.parent / "Mesh.inp"
        shutil.copyfile(source, target / source.name)
        completed = subprocess.run(
            [str(args.baseline.resolve()), "-i", "Mesh"],
            cwd=target,
            env=environment,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        (target / "solver.log").write_text(completed.stdout + completed.stderr)
        baseline = totals((target / "Mesh.dat").read_text())
        probe = totals((path.parent / "Mesh.dat").read_text())
        if baseline.keys() != probe.keys() or len(baseline) != 2:
            raise AssertionError(f"standard RF set identity changed: {path}")
        maximum_error = max(
            abs(left - right)
            for name in baseline
            for left, right in zip(baseline[name], probe[name], strict=True)
        )
        if maximum_error > 1e-12:
            raise AssertionError(f"standard RF changed: {path}: {maximum_error}")
        cases.append(
            {
                "source": str(path),
                "deck_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "max_standard_RF_difference": maximum_error,
            }
        )
    if len(cases) != 9:
        raise AssertionError(f"expected nine qualified small cases, found {len(cases)}")
    (root / "comparison.json").write_text(json.dumps(cases, indent=2) + "\n")
    print(f"Standard RF unchanged in {len(cases)} native cases")


if __name__ == "__main__":
    main()
