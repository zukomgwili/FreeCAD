#!/usr/bin/env python3
"""Independent, fixed-reference native force-accounting V2 qualification.

Prepare only by default. Root alone may explicitly execute ``run`` with a
candidate binary; this module never launches FreeCAD or opens an engineering
model. It derives generic fixture decks from the unchanged public 9zt cube
generator, not from the accounting implementation. No original file is edited.

The three unit cubes occupy x=2..3, y=3..4, z=0..3. The base is wholly RBE
supported at ports (-1,-2,-3); Lower and Upper share a material cut at z=2.
Density=2, gravity=3, top pressure=4: each cube weighs 6 force units. All
six-component references are about original global origin. They are declared
below before any result is read, with independent force/moment vector norms,
unchanged one-percent limits and unit floors. These are SOFTWARE fixtures,
not Oomakhi results, stress accuracy, anchorage or design acceptance.
"""

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys


sys.dont_write_bytecode = True


GENERATOR = Path(__file__).resolve().parents[1] / "FreeCAD9ztContactWitness.py"
PROCESS_CONTROL = Path(__file__).with_name("process_control.py").resolve()
GENERATOR_SHA256 = "2f82057efb43764c20bee8ba2b3b364c7c81cd90a192dd76b14f037bde63ba62"
SCHEMA = "CCX_FORCE_ACCOUNTING_V2"
LIMIT = 0.01
FIXTURE_NAME = "contact"

# Wrench order: Fx,Fy,Fz,Mx,My,Mz. No response-derived reference or fitted sign.
BASELINE = {
    "SUPPORT/Support": [0, 0, 22, 77, -55, 0],
    "CUT/Lower": [0, 0, -10, -35, 25, 0],
    "CUT/Upper": [0, 0, 10, 35, -25, 0],
    "LOAD/Lower": [0, 0, -6, -21, 15, 0],
    "LOAD/Upper": [0, 0, -10, -35, 25, 0],
    "CONTACT/Lower": [0, 0, 0, 0, 0, 0],
    "CONTACT/Upper": [0, 0, 0, 0, 0, 0],
    "MPC/Lower": [0, 0, 16, 56, -40, 0],
    "MPC/Upper": [0, 0, 0, 0, 0, 0],
}

# Extra physical force (1,-2,3) at Lower node9=(2,3,1) has wrench
# (1,-2,3,11,-5,-7). It is on a uniquely Lower-owned Tie/equation-dependent
# node, not on the shared cut. The two CUT references remain unchanged.
DEPENDENT_POINT = dict(
    BASELINE,
    **{
        "SUPPORT/Support": [-1, 2, 19, 66, -50, 7],
        "LOAD/Lower": [1, -2, -3, -10, 10, -7],
        "MPC/Lower": [-1, 2, 13, 45, -35, 7],
    },
)

CASE_SPECS = (
    {"name": "tie-tet4", "mode": "tie", "quadratic": False},
    {"name": "tie-tet10", "mode": "tie", "quadratic": True},
    {"name": "equation-unit-tet4", "mode": "equation", "scale": 1.0},
    {
        "name": "equation-negative-scale-reverse-tet4",
        "mode": "equation",
        "scale": -7.0,
        "reverse_rows": True,
    },
    {
        "name": "equation-quarter-scale-tet10",
        "mode": "equation",
        "scale": 0.25,
        "quadratic": True,
    },
    {
        "name": "equation-chain-reverse-tet4",
        "mode": "chain",
        "scale": -3.0,
        "reverse_rows": True,
    },
    {
        "name": "tie-dependent-point-tet4",
        "mode": "tie",
        "point_load": True,
    },
    {
        "name": "equation-chain-dependent-point-tet10",
        "mode": "chain",
        "quadratic": True,
        "scale": 0.5,
        "point_load": True,
    },
    {
        "name": "reject-shared-cut-mpc-tet4",
        "mode": "tie",
        "reject": "shared-cut-mpc",
    },
    {
        "name": "reject-body-spc-tet4",
        "mode": "tie",
        "reject": "body-spc",
    },
)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def blocks(text):
    result = []
    for line in text.splitlines():
        if line.startswith("*") and not line.startswith("**"):
            result.append([line])
        elif result:
            result[-1].append(line)
        elif line.strip():
            raise ValueError("Unexpected text before first deck keyword")
    return result


def keyword(block):
    return block[0].split(",", 1)[0].upper()


def parse_native_fixture(deck_blocks):
    nodes, elements = {}, {}
    for block in deck_blocks:
        if keyword(block) == "*NODE":
            for line in block[1:]:
                if not line.strip():
                    continue
                fields = line.split(",")
                nodes[int(fields[0])] = tuple(map(float, fields[1:4]))
        elif keyword(block) == "*ELEMENT":
            for line in block[1:]:
                if not line.strip():
                    continue
                fields = list(map(int, line.split(",")))
                elements[fields[0]] = tuple(fields[1:])
    if set(elements) != set(range(1, 19)):
        raise ValueError("Generic generator no longer creates the frozen 18 tetrahedra")
    if nodes[9] != (2, 3, 1) or nodes[21] != (-1, -2, -3):
        raise ValueError("Generic generator changed fixed physical identities")
    return nodes, elements


def interface_pairs(nodes, elements, quadratic):
    """Exact controlled cube topology, not an engineering-model node matcher."""
    domains = []
    for start in (1, 7):
        domain = {
            node for element in range(start, start + 6) for node in elements[element]
        }
        face = [node for node in domain if nodes[node][2] == 1]
        expected_count = 9 if quadratic else 4
        if len(face) != expected_count:
            raise ValueError("Controlled Tie face node count changed")
        mapping = {nodes[node]: node for node in face}
        if len(mapping) != len(face):
            raise ValueError("Controlled domain contains duplicate-coordinate nodes")
        domains.append(mapping)
    base, lower = domains
    if set(base) != set(lower):
        raise ValueError("Controlled independent faces no longer coincide exactly")
    pairs = [(lower[point], base[point]) for point in sorted(lower)]
    if any(slave == master for slave, master in pairs):
        raise ValueError("Controlled Tie must retain independent original node IDs")
    return pairs


def equation_lines(terms):
    if len(terms) > 4:
        raise ValueError("Fixture equation exceeded simple native data-line bound")
    data = ",".join(f"{node},{direction},{coefficient:.17g}" for node, direction, coefficient in terms)
    return ["*EQUATION", str(len(terms)), data]


def prepare_case(root, specification, generator):
    directory = root / specification["name"]
    directory.mkdir()
    quadratic = specification.get("quadratic", False)
    generator.write_case(directory, quadratic=quadratic)
    deck = directory / (FIXTURE_NAME + ".inp")
    request = directory / (FIXTURE_NAME + ".accounting")
    deck_blocks = blocks(deck.read_text())
    nodes, elements = parse_native_fixture(deck_blocks)
    pairs = interface_pairs(nodes, elements, quadratic)
    # Remove the OLD lower penalty contact entirely, retaining the two native
    # element surfaces. No fake/dummy Contact or simultaneous lower law remains.
    removed = {"*SURFACE INTERACTION", "*SURFACE BEHAVIOR", "*CONTACT PAIR", "*FRICTION"}
    deck_blocks = [block for block in deck_blocks if keyword(block) not in removed]
    additions, equations, auxiliary = [], [], []
    scale = specification.get("scale", 1.0)
    if not math.isfinite(scale) or scale == 0:
        raise ValueError("Invalid frozen equation scale")
    if specification["mode"] == "tie":
        additions.append(["*TIE,NAME=IndependentRearTie,ADJUST=NO", "UPPER,BOTTOM"])
    else:
        next_node = max(nodes) + 1
        for slave, master in pairs:
            if specification["mode"] == "chain":
                intermediate = next_node
                next_node += 1
                auxiliary.append((intermediate, nodes[slave]))
            else:
                intermediate = master
            for direction in (1, 2, 3):
                equations.append(
                    [(slave, direction, scale), (intermediate, direction, -scale)]
                )
                if specification["mode"] == "chain":
                    equations.append(
                        [(intermediate, direction, 2 * scale), (master, direction, -2 * scale)]
                    )
    if specification.get("reject") == "shared-cut-mpc":
        # Node13=(2,3,2) belongs to BOTH requested sides at the material cut.
        # This equation is homogeneous/solvable but cannot be attributed to one
        # side. The accounting method must reject it instead of inventing a sign.
        equations.append([(13, 1, 1.0), (1, 1, -1.0)])
    if specification.get("reverse_rows"):
        equations.reverse()
    additions.extend(equation_lines(row) for row in equations)
    if auxiliary:
        node_block = next(block for block in deck_blocks if keyword(block) == "*NODE")
        node_block.extend(
            f"{node},{point[0]:.17g},{point[1]:.17g},{point[2]:.17g}"
            for node, point in auxiliary
        )
    if specification.get("reject") == "body-spc":
        # Node17 is an Upper-only top corner, not a Tie-dependent or cut node.
        additions.append(["*BOUNDARY", "17,1,1,0"])
    boundary_index = next(i for i, block in enumerate(deck_blocks) if keyword(block) == "*BOUNDARY")
    deck_blocks[boundary_index:boundary_index] = additions
    if specification.get("point_load"):
        end_step = next(i for i, block in enumerate(deck_blocks) if keyword(block) == "*END STEP")
        deck_blocks.insert(end_step, ["*CLOAD", "9,1,1", "9,2,-2", "9,3,3"])
    deck.write_text("\n".join(line for block in deck_blocks for line in block) + "\n")
    old_request = request.read_text()
    if not old_request.startswith("CCX_FORCE_ACCOUNTING_V1\n"):
        raise ValueError("Generator request protocol unexpectedly changed")
    request.write_text(SCHEMA + old_request[len("CCX_FORCE_ACCOUNTING_V1"):])
    wanted = DEPENDENT_POINT if specification.get("point_load") else BASELINE
    return {
        **specification,
        "directory": str(directory),
        "deck": str(deck),
        "deck_sha256": sha256(deck),
        "request": str(request),
        "request_sha256": sha256(request),
        "expected_wrenches": wanted,
        "independent_interface_pairs": pairs,
        "auxiliary_chain_nodes": [node for node, _point in auxiliary],
        "declared_point_load": {
            "node": 9,
            "original_position": [2, 3, 1],
            "force": [1, -2, 3],
            "original_origin_moment": [11, -5, -7],
        } if specification.get("point_load") else None,
        "not_public_FreeCAD_writer_coverage": True,
    }


def prepare(root):
    if sha256(GENERATOR) != GENERATOR_SHA256:
        raise ValueError("Unchanged public generator custody failed")
    root.mkdir(parents=False, exist_ok=False)
    spec = importlib.util.spec_from_file_location("unchanged_9zt_fixture_generator", GENERATOR)
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    cases = [prepare_case(root, specification, generator) for specification in CASE_SPECS]
    manifest = {
        "schema": "FREECAD_5AR_INDEPENDENT_NATIVE_ANALYTIC_V1",
        "accounting_schema": SCHEMA,
        "script": str(Path(__file__).resolve()),
        "script_sha256": sha256(__file__),
        "generator": str(GENERATOR),
        "generator_sha256": GENERATOR_SHA256,
        "process_control": str(PROCESS_CONTROL),
        "process_control_sha256": sha256(PROCESS_CONTROL),
        "one_percent_force_and_original_origin_moment_limits": LIMIT,
        "norm": "Euclidean, separately for first 3 and last 3; denominator max(norm(reference),1)",
        "cube_weight": 6,
        "top_pressure_force": 4,
        "global_origin": [0, 0, 0],
        "local_support_reference": [-1, -2, -3],
        "baseline_local_support_couple_not_origin_moment": [121, -77, 0],
        "cases": cases,
        "native_invocations": 0,
        "mixed_contact_MPC_same_body_covered": False,
        "legacy_V1_regression_covered": False,
        "engineering_or_BIM_accepted": False,
    }
    write_json(root / "manifest.json", manifest)
    print(json.dumps({"prepared": str(root), "cases": len(cases), "native_invocations": 0}))


def run_child(candidate, directory, timeout):
    from process_control import assert_serial, run_bounded

    assert_serial((candidate.name,))
    environment = dict(os.environ)
    environment.pop("CCX_9ZT_DIAGNOSTIC", None)
    environment.pop("CCX_FORCE_ACCOUNTING_REQUEST", None)
    environment["CCX_FORCE_ACCOUNTING_REQUEST"] = str(directory / (FIXTURE_NAME + ".accounting"))
    environment["OMP_NUM_THREADS"] = "2"
    return run_bounded(
        [str(candidate), "-i", FIXTURE_NAME], cwd=directory,
        environment=environment, log=directory / "solver.log", timeout=timeout,
    )


def parse_output(path):
    lines = Path(path).read_text().splitlines()
    if len(lines) < 3 or lines[0] != SCHEMA or lines[-1] != "END":
        raise ValueError("Missing complete V2 native output envelope")
    state = lines[1].split()
    if len(state) != 4 or state[0] != "STATE" or int(state[1]) != 1:
        raise ValueError("Unexpected native static output state")
    if int(state[2]) < 1 or float(state[3]) != 1.0:
        raise ValueError("Native output did not reach requested final time 1")
    rows = {}
    for line in lines[2:-1]:
        fields = line.split()
        if len(fields) != 8:
            raise ValueError("Unexpected native output row width")
        key = "/".join(fields[:2])
        if key in rows:
            raise ValueError("Duplicate native output identity")
        row = list(map(float, fields[2:]))
        if not all(math.isfinite(value) for value in row):
            raise ValueError("Nonfinite native output wrench")
        rows[key] = row
    return state, rows


def norm(values):
    return math.sqrt(sum(value * value for value in values))


def compare(rows, expected):
    if set(rows) != set(expected):
        raise ValueError("Output identities differ from fixed SUPPORT/CUT/LOAD/CONTACT/MPC set")
    checks = []
    for key in sorted(expected):
        for meaning, start in (("force", 0), ("original_origin_moment", 3)):
            reference = expected[key][start:start + 3]
            actual = rows[key][start:start + 3]
            denominator = max(norm(reference), 1.0)
            error = norm([a - b for a, b in zip(actual, reference)]) / denominator
            checks.append({
                "identity": key, "meaning": meaning, "actual": actual,
                "reference": reference, "relative_error": error,
                "limit": LIMIT, "denominator": denominator, "passed": error <= LIMIT,
            })
    return checks


def run(root, candidate, only_case, timeout):
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest["script_sha256"] != sha256(__file__) or manifest["generator_sha256"] != sha256(GENERATOR):
        raise ValueError("Prepared fixture source custody changed")
    if manifest["process_control_sha256"] != sha256(PROCESS_CONTROL):
        raise ValueError("Prepared process-supervision source custody changed")
    if manifest["accounting_schema"] != SCHEMA or manifest["one_percent_force_and_original_origin_moment_limits"] != LIMIT:
        raise ValueError("Prepared manifest changed the fixed protocol or acceptance limit")
    if [case["name"] for case in manifest["cases"]] != [case["name"] for case in CASE_SPECS]:
        raise ValueError("Prepared manifest changed the predeclared complete case set")
    for case, specification in zip(manifest["cases"], CASE_SPECS):
        if any(case.get(key) != value for key, value in specification.items()):
            raise ValueError("Prepared manifest changed a predeclared fixture operation")
        reference = DEPENDENT_POINT if specification.get("point_load") else BASELINE
        if case["expected_wrenches"] != reference:
            raise ValueError("Prepared manifest changed the independent analytic references")
    candidate = candidate.resolve(strict=True)
    initial_binary_hash = sha256(candidate)
    selections = [case for case in manifest["cases"] if not only_case or case["name"] == only_case]
    if not selections:
        raise ValueError("No predeclared case matches requested selection")
    reports = []
    all_passed = True
    for case in selections:
        directory = Path(case["directory"])
        report_path = directory / "execution.json"
        if report_path.exists() or (directory / "solver.log").exists():
            raise ValueError("Case already executed; preserve it and prepare a fresh exclusive root")
        expected_custody = {
            "candidate": initial_binary_hash,
            "script": manifest["script_sha256"],
            "generator": manifest["generator_sha256"],
            "process_control": manifest["process_control_sha256"],
            "deck": case["deck_sha256"],
            "request": case["request_sha256"],
        }
        custody_paths = {
            "candidate": candidate,
            "script": Path(__file__),
            "generator": GENERATOR,
            "process_control": PROCESS_CONTROL,
            "deck": Path(case["deck"]),
            "request": Path(case["request"]),
        }
        report = {
            "case": case["name"], "candidate": str(candidate),
            "candidate_sha256": initial_binary_hash,
            "custody_before": {name: sha256(path) for name, path in custody_paths.items()},
        }
        try:
            if report["custody_before"] != expected_custody:
                raise ValueError("Prepared native inputs or source custody changed")
            for field in ("deck", "request"):
                if sha256(case[field]) != case[field + "_sha256"]:
                    raise ValueError("Prepared native input custody changed")
            if sha256(candidate) != initial_binary_hash:
                raise ValueError("Candidate binary changed")
            report.update(run_child(candidate, directory, timeout))
            if report["timed_out"] or not report["child_reaped"] or not report["process_group_gone"]:
                raise ValueError("Native invocation timed out or left an owned process")
            output_path = directory / (FIXTURE_NAME + ".accounting.out")
            if case.get("reject"):
                log = (directory / "solver.log").read_text(errors="replace")
                if report["returncode"] == 0:
                    raise ValueError("Unsupported body/constraint unexpectedly accepted")
                if "CCX force accounting" not in log:
                    raise ValueError("Refusal was not the requested accounting-domain rejection")
                if case["reject"] == "shared-cut-mpc":
                    if "MPC" not in log or not any(word in log.lower() for word in ("cut", "shared", "ambiguous")):
                        raise ValueError("Missing explicit ambiguous cut/shared-node MPC refusal")
                elif "cut body contains a prescribed degree of freedom" not in log:
                    raise ValueError("Missing explicit body-SPC refusal")
                if output_path.exists() and "\nEND\n" in output_path.read_text():
                    raise ValueError("Rejected case left a completed accounting envelope")
                report["expected_domain_refusal"] = case["reject"]
                report["passed"] = True
            else:
                if report["returncode"] != 0:
                    raise ValueError("Native solve failed before analytic qualification")
                state, rows = parse_output(output_path)
                checks = compare(rows, case["expected_wrenches"])
                report.update(state=state, observed_wrenches=rows, checks=checks)
                report["passed"] = all(check["passed"] for check in checks)
                if not report["passed"]:
                    raise ValueError("Fixed independent force/moment reference check failed")
            for field in ("deck", "request"):
                if sha256(case[field]) != case[field + "_sha256"]:
                    raise ValueError("Native invocation changed prepared input bytes")
            if sha256(candidate) != initial_binary_hash or sha256(__file__) != manifest["script_sha256"]:
                raise ValueError("Executed binary or harness changed")
        except Exception as error:
            report["passed"] = False
            report["error"] = repr(error)
            all_passed = False
        report["custody_after"] = {name: sha256(path) for name, path in custody_paths.items()}
        report["protected_inputs_unchanged"] = report["custody_after"] == expected_custody
        if not report["protected_inputs_unchanged"]:
            report["passed"] = False
            report["error"] = "Protected binary, harness, generator, deck or request changed"
            all_passed = False
        report["solver_log_sha256"] = sha256(directory / "solver.log") if (directory / "solver.log").exists() else None
        native_output = directory / (FIXTURE_NAME + ".accounting.out")
        report["native_output_sha256"] = sha256(native_output) if native_output.exists() else None
        write_json(report_path, report)
        reports.append(report)
        print(json.dumps({"case": case["name"], "passed": report["passed"], "error": report.get("error")}), flush=True)
        if not report["passed"]:
            break
    summary = {
        "schema": "FREECAD_5AR_INDEPENDENT_NATIVE_ANALYTIC_RESULT_V1",
        "manifest_sha256": sha256(manifest_path), "candidate": str(candidate),
        "candidate_sha256": initial_binary_hash,
        "selected_cases": [case["name"] for case in selections], "reports": reports,
        "all_selected_passed": all_passed and len(reports) == len(selections),
        "mixed_contact_MPC_same_body_covered": False,
        "legacy_V1_regression_covered": False,
        "engineering_or_BIM_accepted": False,
    }
    summary_path = root / ("summary-" + only_case + ".json" if only_case else "summary.json")
    if summary_path.exists():
        raise ValueError("Summary already exists; refusing overwrite")
    write_json(summary_path, summary)
    return 0 if summary["all_selected_passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "run"))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--ccx", type=Path)
    parser.add_argument("--only-case", choices=tuple(case["name"] for case in CASE_SPECS))
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 180:
        parser.error("Native timeout must be between 1 and 180 seconds")
    if args.mode == "prepare":
        if args.ccx or args.only_case:
            parser.error("prepare does not invoke a binary or select a subset")
        prepare(args.root.resolve())
        return 0
    if not args.ccx:
        parser.error("run requires an explicit qualified candidate binary")
    return run(args.root.resolve(), args.ccx, args.only_case, args.timeout)


if __name__ == "__main__":
    sys.exit(main())
