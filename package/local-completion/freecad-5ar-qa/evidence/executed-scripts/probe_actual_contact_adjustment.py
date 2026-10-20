#!/usr/bin/env python3
"""Prepare or serially run an actual contact-coordinate-adjustment control.

The unchanged public cube generator supplies the entire native model. The only
declared changes are translating Lower/Upper nodes9..20 by +0.05 in Z, requesting
real penalty-contact ADJUST=0.1, and using accounting V2. There is no Tie, solve
result reference fitting, engineering model, or product-source modification.

``prepare`` never starts a native process. Root must review this file before
explicitly running ``run``. A successful solver plus changed native FRD reference
coordinates and completed V2 accounting is an intentional RED result (exit1),
not acceptance. A specific original-coordinate refusal is GREEN (exit0).
"""

import argparse
import importlib.util
import json
import math
from pathlib import Path
import sys


sys.dont_write_bytecode = True

HELPER = Path("/private/tmp/freecad-5ar-wYCAxF/qualify_native_v2_analytic.py")
HELPER_SHA256 = "d7a5a2b6fcd2260b14e2b9c4f3b3ee86fc71474be59a2e5a6ca3d8d6ade017ba"
GENERATOR = Path(
    "/Users/zukomgwili/src/FreeCAD/package/local-completion/FreeCAD9ztContactWitness.py"
)
GENERATOR_SHA256 = "2f82057efb43764c20bee8ba2b3b364c7c81cd90a192dd76b14f037bde63ba62"
CONTRACT = Path("/Users/zukomgwili/src/FreeCAD/package/calculix/force-accounting/contract.json")
SCHEMA = "CCX_FORCE_ACCOUNTING_V2"
SHIFT = 0.05
ADJUST = 0.1


def module_from(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def helper():
    import hashlib

    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    if digest(HELPER) != HELPER_SHA256 or digest(GENERATOR) != GENERATOR_SHA256:
        raise ValueError("Pinned generic fixture or bounded native supervisor changed")
    return module_from(HELPER, "contact_adjustment_supervisor")


def original_nodes(deck, utilities):
    return utilities.parse_native_fixture(utilities.blocks(deck.read_text()))[0]


def prepare(root, candidate):
    utilities = helper()
    candidate = candidate.resolve(strict=True)
    root.mkdir(parents=False, exist_ok=False)
    generator = module_from(GENERATOR, "unchanged_contact_adjustment_generator")
    generator.write_case(root, quadratic=False)
    deck, request = root / "contact.inp", root / "contact.accounting"
    baseline_nodes = original_nodes(deck, utilities)
    deck_blocks = utilities.blocks(deck.read_text())
    contact_count = 0
    for block in deck_blocks:
        if utilities.keyword(block) == "*NODE":
            for index, line in enumerate(block[1:], 1):
                fields = line.split(",")
                node = int(fields[0])
                if 9 <= node <= 20:
                    point = tuple(map(float, fields[1:4]))
                    block[index] = f"{node},{point[0]:.17g},{point[1]:.17g},{point[2]+SHIFT:.17g}"
        elif utilities.keyword(block) == "*CONTACT PAIR":
            if "ADJUST=" in block[0].upper():
                raise ValueError("Frozen generator unexpectedly already adjusts contact")
            block[0] += f",ADJUST={ADJUST:.17g}"
            contact_count += 1
    if contact_count != 1:
        raise ValueError("Control must retain exactly one actual penalty-contact law")
    if any(utilities.keyword(block) == "*TIE" for block in deck_blocks):
        raise ValueError("This coordinate control must not contain an ordinary Tie")
    deck.write_text("\n".join(line for block in deck_blocks for line in block) + "\n")
    nodes = {}
    for block in deck_blocks:
        if utilities.keyword(block) == "*NODE":
            for line in block[1:]:
                fields = line.split(",")
                nodes[int(fields[0])] = tuple(map(float, fields[1:4]))
    for node in baseline_nodes:
        wanted = list(baseline_nodes[node])
        if 9 <= node <= 20:
            wanted[2] += SHIFT
        if nodes[node] != tuple(wanted):
            raise ValueError("A coordinate change exceeded the predeclared Lower/Upper translation")
    for port in (21, 22):
        if nodes[port] != (-1, -2, -3):
            raise ValueError("Native support ports must not move")
    old_request = request.read_text()
    if not old_request.startswith("CCX_FORCE_ACCOUNTING_V1\n"):
        raise ValueError("Frozen generator protocol changed")
    request.write_text(SCHEMA + old_request[len("CCX_FORCE_ACCOUNTING_V1"):])
    snapshot = root / "original-deck-coordinates.json"
    utilities.write_json(snapshot, {str(node): point for node, point in sorted(nodes.items())})
    contract = json.loads(CONTRACT.read_text())
    manifest = {
        "schema": "FREECAD_5AR_ACTUAL_CONTACT_ADJUSTMENT_CONTROL_V1",
        "script": str(Path(__file__).resolve()),
        "script_sha256": utilities.sha256(__file__),
        "supervisor": str(HELPER),
        "supervisor_sha256": HELPER_SHA256,
        "generator": str(GENERATOR),
        "generator_sha256": GENERATOR_SHA256,
        "candidate": str(candidate),
        "candidate_sha256": utilities.sha256(candidate),
        "deck": str(deck),
        "deck_sha256": utilities.sha256(deck),
        "request": str(request),
        "request_sha256": utilities.sha256(request),
        "original_coordinates": str(snapshot),
        "original_coordinates_sha256": utilities.sha256(snapshot),
        "contract": str(CONTRACT),
        "contract_sha256": utilities.sha256(CONTRACT),
        "declared_output_frame": contract["interface"]["frame"],
        "translated_nodes": list(range(9, 21)),
        "unchanged_support_ports": [21, 22],
        "translation": [0, 0, SHIFT],
        "real_penalty_contact_adjust": ADJUST,
        "expected_coordinate_adjustment_nodes": list(range(9, 13)),
        "expected_adjusted_z": 1.0,
        "desired_outcome": "Nonzero solver exit with an explicit original-reference-coordinate-change refusal",
        "native_invocations": 0,
        "engineering_or_BIM_accepted": False,
    }
    utilities.write_json(root / "manifest.json", manifest)
    print(json.dumps({"prepared": str(root), "native_invocations": 0}))


def frd_reference_coordinates(path):
    coordinates, collecting = {}, False
    for line in path.read_text().splitlines():
        if not collecting:
            fields = line.split()
            if fields and fields[0] == "2C":
                collecting = True
            continue
        if line[:3] == " -3":
            break
        if line[:3] != " -1":
            raise ValueError("Unexpected native ASCII FRD coordinate record")
        node = int(line[3:13])
        point = tuple(float(line[13 + 12*i:25 + 12*i]) for i in range(3))
        if node in coordinates or not all(math.isfinite(value) for value in point):
            raise ValueError("Duplicate/nonfinite FRD reference coordinate")
        coordinates[node] = point
    if set(coordinates) != set(range(1, 21)):
        raise ValueError("FRD does not contain the frozen 20 structural node identities")
    return coordinates


def run(root, timeout):
    utilities = helper()
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if (root / "execution.json").exists() or (root / "solver.log").exists():
        raise ValueError("Control already executed; prepare a fresh exclusive root")
    names = ("script", "supervisor", "generator", "candidate", "deck", "request", "original_coordinates", "contract")
    paths = {name: Path(manifest[name]) for name in names}
    wanted = {name: manifest[name + "_sha256"] for name in names}
    if manifest["script"] != str(Path(__file__).resolve()) or wanted["script"] != utilities.sha256(__file__):
        raise ValueError("Prepared harness identity changed")
    if manifest["translation"] != [0, 0, SHIFT] or manifest["real_penalty_contact_adjust"] != ADJUST:
        raise ValueError("Predeclared coordinate operation changed")
    before = {name: utilities.sha256(path) for name, path in paths.items()}
    if before != wanted:
        raise ValueError("Protected native inputs, candidate, contract or harness changed")
    original = {int(node): tuple(point) for node, point in json.loads(paths["original_coordinates"].read_text()).items()}
    report = {
        "candidate": manifest["candidate"],
        "candidate_sha256": wanted["candidate"],
        "custody_before": before,
        "manifest_sha256": utilities.sha256(manifest_path),
        "native_invocations": 1,
        "bug_reproduced": False,
        "strict_coordinate_contract_passed": False,
        "engineering_or_BIM_accepted": False,
    }
    try:
        report.update(utilities.run_child(paths["candidate"], root, timeout))
        if report["timed_out"] or not report["child_reaped"] or not report["process_group_gone"]:
            raise ValueError("Bounded native invocation did not finish and reap cleanly")
        log = (root / "solver.log").read_text(errors="replace")
        output = root / "contact.accounting.out"
        if report["returncode"] != 0:
            if "CCX force accounting V2" in log and "coordinate" in log.lower() and "changed" in log.lower():
                if output.exists() and "\nEND\n" in output.read_text():
                    raise ValueError("Coordinate-refused run left completed accounting output")
                report["strict_coordinate_contract_passed"] = True
                report["outcome"] = "Explicit native reference-coordinate-change refusal"
            else:
                raise ValueError("Native failure did not establish the requested coordinate-change refusal")
        else:
            state, rows = utilities.parse_output(output)
            report.update(completed_v2_state=state, completed_v2_rows=rows)
            actual = frd_reference_coordinates(root / "contact.frd")
            changed = {
                node: {"original": original[node], "native_frd": point,
                       "delta": [b-a for a, b in zip(original[node], point)]}
                for node, point in actual.items()
                if any(abs(a-b) > 1e-8 for a, b in zip(original[node], point))
            }
            report["changed_reference_coordinates"] = changed
            proven = set(changed) == set(range(9, 13)) and all(
                math.isclose(actual[node][2], 1.0, rel_tol=0, abs_tol=1e-8)
                and math.isclose(original[node][2]-actual[node][2], SHIFT, rel_tol=0, abs_tol=1e-8)
                for node in range(9, 13)
            )
            report["actual_contact_coordinate_adjustment_proven"] = proven
            if not proven:
                raise ValueError("No exact frozen contact-side coordinate movement was established")
            report["bug_reproduced"] = True
            report["outcome"] = "Native co changed by 0.05 while V2 completed under the declared original-coordinate frame"
    except Exception as error:
        report["error"] = repr(error)
        report.setdefault("outcome", "Inconclusive setup/runtime failure; no coordinate bug claimed")
    report["custody_after"] = {name: utilities.sha256(path) for name, path in paths.items()}
    report["protected_inputs_unchanged"] = report["custody_after"] == wanted
    if not report["protected_inputs_unchanged"]:
        report["strict_coordinate_contract_passed"] = False
        report["bug_reproduced"] = False
        report["error"] = "Protected native inputs, source, contract or candidate changed"
    for name in ("solver.log", "contact.accounting.out", "contact.frd"):
        path = root / name
        report[name + "_sha256"] = utilities.sha256(path) if path.exists() else None
    utilities.write_json(root / "execution.json", report)
    print(json.dumps({key: report.get(key) for key in (
        "outcome", "returncode", "bug_reproduced", "strict_coordinate_contract_passed",
        "actual_contact_coordinate_adjustment_proven", "protected_inputs_unchanged", "error",
    )}, indent=2))
    return 0 if report["strict_coordinate_contract_passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "run"))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--ccx", type=Path)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 180:
        parser.error("Native timeout must be between 1 and 180 seconds")
    if args.mode == "prepare":
        if not args.ccx:
            parser.error("Prepare requires the explicit candidate to bind, but does not run it")
        prepare(args.root.resolve(), args.ccx)
        return 0
    if args.ccx:
        parser.error("Run uses only the candidate pinned by the fresh manifest")
    return run(args.root.resolve(), args.timeout)


if __name__ == "__main__":
    sys.exit(main())
