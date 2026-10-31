"""Offline independent arithmetic/byte audit of retained native beam outputs.

This script imports no FreeCAD, product module, solver or executed harness.
It validates observations; it does not recover forces from stress or rerun a
calculation. Only its new JSON report is written, with exclusive creation.
"""

import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat

ROOT = Path(__file__).resolve().parent
REPO = Path("/Users/zukomgwili/src/FreeCAD")
MATRIX = ROOT / "rotated-matrix-r01"
LEGACY = ROOT / "legacy-observer-equivalence-r01"
REPORT = ROOT / "independent-equilibrium-audit.json"
TEST = REPO / "src/Mod/Fem/femtest/app/test_beam_section_forces_native.py"
TEST_SHA = "931dee1f6d4cec8f19c461418464bbce850437a3631ade2e47c043dbc5e1f289"
NATIVE_SHA = "3fdd2b7f7cc3198e7fd1a5dc89a71e0cfacbd1f6ee3e21b106e2171ed6b52d7a"
OLD_SHA = "0c2a86318df9c7cc9d921e5068ae52f1d53e27b7b16747e00a74ccc8fe37c6cc"
TRANSLATION = [37.0, -19.0, 11.0]
FILES = {}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def capture(path):
    path = Path(path)
    before = path.lstat()
    assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1, path
    identity = lambda x: (x.st_dev, x.st_ino, x.st_mode, x.st_nlink,
                          x.st_size, x.st_mtime_ns, x.st_ctime_ns)
    with os.fdopen(os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)), "rb") as stream:
        assert identity(before) == identity(os.fstat(stream.fileno())), path
        data = stream.read()
        assert identity(before) == identity(os.fstat(stream.fileno())), path
    assert identity(before) == identity(path.lstat()), path
    record = {"sha256": sha(data), "bytes": len(data)}
    assert FILES.get(str(path), record) == record, path
    FILES[str(path)] = record
    return data


def pairs(items):
    result = {}
    for key, value in items:
        assert key not in result, key
        result[key] = value
    return result


def parsed(path):
    def invalid(value):
        raise ValueError("Nonfinite JSON: " + value)
    return json.loads(capture(path), object_pairs_hook=pairs, parse_constant=invalid)


def dot(a, b):
    return math.fsum(x * y for x, y in zip(a, b))


def cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def norm(a):
    return math.sqrt(dot(a, a))


def difference(a, b):
    return [x-y for x, y in zip(a, b)]


def finite_vector(value):
    return (isinstance(value, list) and len(value) == 3
            and all(type(x) in (float, int) and math.isfinite(x) for x in value))


def rotate(value):
    # Independent Rodrigues formula, not FreeCAD's Rotation implementation.
    axis = [x / math.sqrt(14.0) for x in (1.0, 2.0, 3.0)]
    angle = math.radians(31.0)
    c, s = math.cos(angle), math.sin(angle)
    k_cross_v, k_dot_v = cross(axis, value), dot(axis, value)
    return [c*v + s*w + (1-c)*k_dot_v*k
            for v, w, k in zip(value, k_cross_v, axis)]


def transformed(value):
    return [x+y for x, y in zip(rotate(value), TRANSLATION)]


def receipt(directory, count):
    proof = parsed(directory / "execution.json")
    assert proof["passed"] is True and proof["returncode"] == 0
    assert proof["timed_out"] is False and proof["installation_performed"] is False
    for key in ("child_reaped", "process_group_gone", "source_and_supervisor_unchanged",
                "app_and_three_profiles_unchanged"):
        assert proof[key] is True, key
    assert proof["source_inputs_before"] == proof["source_inputs_after"]
    assert proof["protected_before"] == proof["protected_after"]
    assert len(proof["protected_before"]) == 4
    raw = capture(directory / "run.log")
    assert sha(raw) == proof["log_sha256"]
    text = raw.decode()
    assert re.findall(r"^Ran (\d+) tests? in [0-9.]+s$", text, re.M) == [str(count)]
    assert len(re.findall(r"^OK$", text, re.M)) == 1
    assert not re.search(r"^(?:FAILED|FAIL:|ERROR:|UNEXPECTED SUCCESS)", text, re.M)
    snapshots = parsed(directory / "input-snapshots-complete.json")
    assert snapshots["execution_sha256"] == FILES[str(directory / "execution.json")]["sha256"]
    assert set(snapshots["inputs"]) == set(proof["source_inputs_before"])
    for name, row in snapshots["inputs"].items():
        assert row["sha256"] == proof["source_inputs_before"][name]
        if "snapshot" in row:
            assert sha(capture(ROOT / row["snapshot"])) == row["sha256"]
        else:
            assert "withheld" in row
    return proof


def deck_records(literal):
    nodes, elements, loads, boundaries, node_sets, element_sets = {}, {}, [], [], {}, {}
    sections, keyword, options, rows = [], "", {}, []
    elastic, steps, outputs = [], 0, []

    def flush():
        if keyword == "*BEAM SECTION":
            assert options["SECTION"] == "RECT" and len(rows) == 2
            sections.append({"elset": options["ELSET"], "material": options["MATERIAL"],
                             "dimensions_mm": list(map(float, rows[0])),
                             "reference_n1": list(map(float, rows[1]))})

    for raw in literal.splitlines():
        line = raw.strip()
        if not line or line.startswith("**"):
            continue
        if line.startswith("*"):
            flush()
            tokens = [x.strip().upper() for x in line.split(",")]
            keyword, options, rows = tokens[0], {}, []
            for item in tokens[1:]:
                key, separator, value = item.partition("=")
                options[key] = value if separator else True
            if keyword == "*STEP":
                steps += 1
            if keyword == "*ELEMENT":
                assert options["TYPE"] == "B32R"
            if keyword in ("*EL FILE", "*NODE FILE"):
                outputs.append((keyword, dict(options)))
            assert keyword != "*INCLUDE"
            continue
        values = [x.strip() for x in line.split(",") if x.strip()]
        if keyword == "*NODE":
            node = int(values[0]); assert node not in nodes and len(values) == 4
            nodes[node] = list(map(float, values[1:]))
            if "NSET" in options:
                node_sets.setdefault(options["NSET"], []).append(node)
        elif keyword == "*ELEMENT":
            element = int(values[0]); assert element not in elements and len(values) == 4
            elements[element] = list(map(int, values[1:]))
            if "ELSET" in options:
                element_sets.setdefault(options["ELSET"], []).append(element)
        elif keyword in ("*ELSET", "*NSET"):
            target = element_sets if keyword == "*ELSET" else node_sets
            name = options["ELSET" if keyword == "*ELSET" else "NSET"]
            if options.get("GENERATE"):
                first, last, stride = map(int, values)
                target.setdefault(name, []).extend(range(first, last+1, stride))
            else:
                target.setdefault(name, []).extend(int(x) if x.isdecimal() else x.upper()
                                                   for x in values)
        elif keyword == "*CLOAD":
            assert len(values) == 3
            loads.append((int(values[0]), int(values[1]), float(values[2])))
        elif keyword == "*BOUNDARY":
            first = int(values[1]); last = int(values[2]) if len(values) > 2 else first
            value = float(values[3]) if len(values) > 3 else 0.0
            boundaries.append((values[0].upper(), first, last, value))
        elif keyword == "*BEAM SECTION":
            rows.append(values)
        elif keyword == "*ELASTIC":
            elastic.append(list(map(float, values)))
    flush()
    assert steps == 1 and elastic == [[100000.0, 0.3]]
    assert ("*EL FILE", {"OUTPUT": "2D", "SECTION FORCES": True}) in outputs
    assert ("*NODE FILE", {"OUTPUT": "2D"}) in outputs

    def expand(name, source, active=()):
        assert name not in active
        if name.isdecimal():
            return {int(name)}
        return set().union(*(set([x]) if isinstance(x, int)
                             else expand(x, source, (*active, name)) for x in source[name]))
    fixed = {(node, direction, value) for name, first, last, value in boundaries
             for node in expand(name, node_sets) for direction in range(first, last+1)}
    assert fixed == {(1, direction, 0.0) for direction in range(1, 7)}
    return nodes, elements, loads, sections, lambda name: expand(name, element_sets)


def expected_mesh(is_t, rotated):
    nodes = {node: [10.0*(node-1), 0.0, 0.0] for node in range(1, 12)}
    elements = {element: [2*element-1, 2*element, 2*element+1] for element in range(1, 6)}
    if is_t:
        nodes.update({12: [100.0, 5.0, 0.0], 13: [100.0, 10.0, 0.0],
                      14: [100.0, -5.0, 0.0], 15: [100.0, -10.0, 0.0]})
        elements.update({6: [11, 12, 13], 7: [11, 14, 15]})
    if rotated:
        nodes = {key: transformed(value) for key, value in nodes.items()}
    return nodes, elements


CASES = {
    "test_axial_compression_root_reverses_the_global_end_action":
        {"force": [100., 0., 0.], "moment": [0., 0., 0.], "scales": [100., 10000.],
         "load": [-100., 0., 0.]},
    "test_axial_tension_root_has_negative_global_end_action":
        {"force": [-100., 0., 0.], "moment": [0., 0., 0.], "scales": [100., 10000.],
         "load": [100., 0., 0.]},
    "test_transverse_y_root_has_signed_shear_and_bending_equilibrium":
        {"force": [0., -.1, 0.], "moment": [0., 0., -10.], "scales": [.1, 10.],
         "load": [0., .1, 0.]},
    "test_transverse_z_root_has_signed_shear_and_orthogonal_bending_equilibrium":
        {"force": [0., 0., -.2], "moment": [0., 20., 0.], "scales": [.2, 20.],
         "load": [0., 0., .2]},
    "test_torsion_couple_preserves_distinct_native_ends_at_a_shared_joint":
        {"force": [0., 0., 0.], "moment": [-.2, 0., 0.], "scales": [.02, .2], "T": True},
    "test_rotated_translated_torsion_preserves_global_actions_and_native_end_axes":
        {"force": [0., 0., 0.], "moment": rotate([-.2, 0., 0.]), "scales": [.02, .2],
         "T": True, "rotated": True},
}


def audit_case(name, oracle):
    folder = MATRIX / name
    metadata_path, deck_path = folder / "Mesh.beam-section.json", folder / "Mesh.inp"
    metadata = parsed(metadata_path)
    deck_bytes = capture(deck_path)
    assert metadata["schema"] == "CCX_BEAM_SECTION_V1"
    assert metadata["deck"] == str(deck_path) and metadata["deck_sha256"] == sha(deck_bytes)
    assert metadata["binary_sha256"] == NATIVE_SHA
    assert sha(capture(metadata["binary"])) == NATIVE_SHA
    assert metadata["end_time"] == 1.0
    assert metadata["case"] == {"analysis": "Analysis", "solver": "Solver", "mesh": "Mesh"}
    master = folder / "Mesh.beam-section"
    master_bytes = capture(master)
    assert metadata["request_path"] == str(master)
    assert metadata["request_sha256"] == sha(master_bytes)
    outputs = list(folder.glob("Mesh.beam-section.run-*.out"))
    assert len(outputs) == 1
    output_path = outputs[0]
    match = re.fullmatch(r"Mesh\.beam-section\.run-([0-9a-f]{32})\.out", output_path.name)
    assert match
    token = match.group(1)
    child_path = Path(str(output_path)[:-4])
    child_bytes = capture(child_path)
    assert master_bytes.count(("REQUEST " + metadata["request"] + "\n").encode()) == 1
    assert child_bytes == master_bytes.replace(("REQUEST " + metadata["request"] + "\n").encode(),
                                               ("REQUEST " + token + "\n").encode())
    data = parsed(output_path)
    assert data["schema"] == "CCX_BEAM_SECTION_V1" and data["request"] == token
    assert data["complete"] is True
    assert data["units"] == {"length": "mm", "force": "N", "moment": "N*mm"}
    assert data["moment_reference"] == "NATIVE_SECTION_CENTROID"
    assert data["force_action"] == "OUTWARD_NATIVE_ELEMENT_END_FACE"
    assert data["sample_identity_scope"] == "ELEMENT_END_BEFORE_NODE_AVERAGING"
    assert data["basis_frame"] == "NATIVE_CURRENT_FACE_BASIS"
    assert data["completion_requires_successful_child"] is True
    nodes, elements, loads, sections, expand = deck_records(deck_bytes.decode())
    expected_nodes, expected_elements = expected_mesh(oracle.get("T"), oracle.get("rotated"))
    assert set(nodes) == set(expected_nodes) and elements == expected_elements
    max_coordinate_error = max(norm(difference(nodes[key], expected_nodes[key])) for key in nodes)
    assert max_coordinate_error < 1.e-8
    if oracle.get("T"):
        direction = rotate([0., 0., 1.]) if oracle.get("rotated") else [0., 0., 1.]
        expected_loads = [(node, axis, sign*.01*x) for node, sign in ((13, 1.), (15, -1.))
                          for axis, x in enumerate(direction, 1) if x]
    else:
        expected_loads = [(11, axis, value) for axis, value in enumerate(oracle["load"], 1)
                          if value]
    assert len(loads) == len(expected_loads)
    for actual, expected in zip(sorted(loads), sorted(expected_loads)):
        assert actual[:2] == expected[:2]
        assert math.isclose(actual[2], expected[2], rel_tol=1.e-12, abs_tol=0.)
    declared = {row["element"]: row for row in metadata["elements"]}
    assert set(declared) == set(elements) and len(declared) == len(metadata["elements"])
    ownership = {}
    for section in sections:
        assert section["dimensions_mm"] == [2., 4.]
        for element in expand(section["elset"]):
            assert element not in ownership
            ownership[element] = section
    assert set(ownership) == set(elements)
    for element, row in declared.items():
        assert row["nodes"] == elements[element] and row["section"] == "BeamCrossSection"
        for key in ("elset", "material", "dimensions_mm", "reference_n1"):
            assert row[key] == ownership[element][key]
        ref = row["reference_n1"]
        tangent = difference(nodes[row["nodes"][2]], nodes[row["nodes"][0]])
        assert finite_vector(ref) and abs(norm(ref)-1.) < 1.e-10
        assert abs(dot(ref, tangent))/norm(tangent) < 1.e-10
    expected_ends = {(element, ids[end-1], end) for element, ids in elements.items() for end in (1, 3)}
    assert len(data["frames"]) == 1
    frame = data["frames"][0]
    assert frame["step"] == frame["increment"] == 1 and frame["time"] == 1.
    assert frame["complete"] is True
    samples = frame["samples"]
    keys = [(row["element"], row["node"], row["end"]) for row in samples]
    assert len(keys) == len(set(keys)) == len(expected_ends) and set(keys) == expected_ends
    max_orthogonality, max_projection, max_determinant, max_normal_angle = 0., 0., 0., 0.
    for row in samples:
        assert all(finite_vector(row[key]) for key in ("position", "force_global", "moment_global"))
        basis = row["basis"]
        assert set(basis) == {"e1", "e2", "normal"} and all(map(finite_vector, basis.values()))
        axes = [basis[key] for key in ("e1", "e2", "normal")]
        orthogonality = max(*(abs(norm(v)-1.) for v in axes),
                            *(abs(dot(axes[i], axes[j])) for i, j in ((0, 1), (0, 2), (1, 2))))
        assert orthogonality < 1.e-8
        max_orthogonality = max(max_orthogonality, orthogonality)
        determinant_error = abs(dot(cross(axes[0], axes[1]), axes[2]) - (-1. if row["end"] == 1 else 1.))
        assert determinant_error < 1.e-8
        max_determinant = max(max_determinant, determinant_error)
        channels = row["native_channels"]
        for name, axis, vector in (("shear1", axes[0], row["force_global"]),
                                   ("shear2", axes[1], row["force_global"]),
                                   ("axial", axes[2], row["force_global"]),
                                   ("torque", axes[2], row["moment_global"]),
                                   ("bend2", axes[1], row["moment_global"]),
                                   ("bend1", axes[0], row["moment_global"])):
            projected = dot(axis, vector)
            residual = abs(channels[name]-projected)/max(1., abs(channels[name]), abs(projected))
            assert residual <= 1.e-12
            max_projection = max(max_projection, residual)
        if oracle.get("rotated") and row["element"] <= 5:
            tangent = rotate([1., 0., 0.])
            normal = [x*(-1. if row["end"] == 1 else 1.) for x in tangent]
            cosine = dot(normal, axes[2])/(norm(normal)*norm(axes[2]))
            angle = math.acos(max(-1., min(1., cosine)))
            assert angle <= .001
            max_normal_angle = max(max_normal_angle, angle)
    root = next(row for row in samples if (row["element"], row["node"], row["end"]) == (1, 1, 1))
    force_error = norm(difference(root["force_global"], oracle["force"])) / oracle["scales"][0]
    moment_error = norm(difference(root["moment_global"], oracle["moment"])) / oracle["scales"][1]
    assert force_error <= .01 and moment_error <= .01
    root_target = TRANSLATION if oracle.get("rotated") else [0., 0., 0.]
    centroid_error = norm(difference(root["position"], root_target))
    assert centroid_error <= 1.e-8
    joint = [(row["element"], row["node"], row["end"]) for row in samples if row["node"] == 11]
    if oracle.get("T"):
        assert len(joint) == 3 and set(joint) == {(5, 11, 3), (6, 11, 1), (7, 11, 1)}
    # Verify the actual FRD STRESS header identity, never consume its averaged
    # stress-labelled values to obtain new member forces or moments.
    stress_headers, header, time = [], None, None
    frd_path = folder / "Mesh.frd"
    for line in capture(frd_path).decode().splitlines():
        if line.startswith("    1PSTEP"):
            _, dataset, increment, step = line.split()
            header = (int(dataset), int(increment), int(step))
        elif line.startswith("  100CL"):
            time = float(line[12:24])
        elif line.startswith(" -4  STRESS"):
            stress_headers.append((*header, time))
    assert stress_headers == [(frame["frame"], frame["increment"], frame["step"], frame["time"])]
    files = {str(path): FILES[str(path)] for path in
             (metadata_path, deck_path, master, child_path, output_path, frd_path)}
    return {"case": name, "passed": True, "files": files,
            "predeclared_root_force_N": oracle["force"],
            "predeclared_root_centroid_moment_Nmm": oracle["moment"],
            "force_normalization_N": oracle["scales"][0],
            "moment_normalization_Nmm": oracle["scales"][1], "equilibrium_limit": .01,
            "observed_root_force_N": root["force_global"],
            "observed_root_centroid_moment_Nmm": root["moment_global"],
            "relative_force_error": force_error, "relative_moment_error": moment_error,
            "force_error_percent": 100*force_error, "moment_error_percent": 100*moment_error,
            "root_centroid_error_mm": centroid_error, "maximum_written_node_error_mm": max_coordinate_error,
            "element_count": len(elements), "distinct_native_end_samples": len(samples),
            "shared_junction_end_ids": joint if oracle.get("T") else [],
            "maximum_basis_orthogonality_error": max_orthogonality,
            "maximum_basis_determinant_error": max_determinant,
            "maximum_local_global_projection_relative_wire_error": max_projection,
            "maximum_rotated_stem_normal_angle_rad": max_normal_angle,
            "actual_FRD_STRESS_header_identity": stress_headers[0],
            "native_frame_id": frame["frame"], "native_increment": frame["increment"],
            "native_step": frame["step"], "native_time": frame["time"],
            "stock_CLOAD_values_verified": loads,
            "stock_reference_sections_verified_without_orientation_substitution": True}


def audit_legacy():
    proof = receipt(LEGACY, 1)
    old_path = "/Applications/FreeCAD-27.1.0.app/Contents/Resources/data/NativeSolvers/ccx-force-accounting"
    assert proof["source_inputs_before"][old_path] == OLD_SHA
    assert sha(capture(old_path)) == OLD_SHA
    claimed = parsed(LEGACY / "legacy-equivalence.json")
    assert len(claimed) == 3 and {row["case"] for row in claimed} == {"axial", "bending", "torsion"}
    prefixes = (b"    1UDATE ", b"    1UTIME ", b"    1UCOMPILETIME ")
    results = []
    for row in claimed:
        retained, dat, decks, details = [], [], [], []
        for label in ("legacy", "candidate", "observed"):
            folder = LEGACY / (row["case"] + "-" + label)
            deck = capture(folder / "Mesh.inp")
            raw_frd = capture(folder / "Mesh.frd")
            raw_dat = capture(folder / "Mesh.dat")
            log = capture(folder / "solver.log")
            assert not re.search(rb"^\s*\*ERROR", log, re.M)
            lines = raw_frd.splitlines(keepends=True)
            excluded = [line for line in lines if line.startswith(prefixes)]
            assert len(excluded) == 3
            assert {next(prefix.decode().strip() for prefix in prefixes if line.startswith(prefix))
                    for line in excluded} == {"1UDATE", "1UTIME", "1UCOMPILETIME"}
            # Keep every remaining byte, including all original line endings.
            normalized = b"".join(line for line in lines if not line.startswith(prefixes))
            legacy_form = b"\n".join(line for line in raw_frd.splitlines() if not line.startswith(prefixes))
            assert sha(deck) == row["deck_sha256"]
            assert sha(raw_dat) == row["dat_sha256"]
            assert sha(legacy_form) == row["frd_without_build_and_creation_metadata_sha256"]
            retained.append(normalized); dat.append(raw_dat); decks.append(deck)
            details.append({"label": label, "frd_sha256": sha(raw_frd),
                            "dat_sha256": sha(raw_dat), "solver_log_sha256": sha(log),
                            "excluded_timestamp_records": [x.decode().rstrip("\r\n") for x in excluded]})
            if label == "observed":
                observation = parsed(folder / "Mesh.beam-section.out")
                assert observation["complete"] is True and observation["frames"]
            else:
                assert not (folder / "Mesh.beam-section.out").exists()
        assert decks[0] == decks[1] == decks[2]
        assert dat[0] == dat[1] == dat[2]
        assert retained[0] == retained[1] == retained[2]
        assert row["legacy_candidate_off_candidate_on_bitwise_equal"] is True
        results.append({"case": row["case"], "passed": True, "jobs": details,
                        "deck_sha256": sha(decks[0]), "dat_full_bytes_sha256": sha(dat[0]),
                        "frd_all_non_timestamp_bytes_sha256": sha(retained[0]),
                        "ordinary_Frd_and_Dat_equal_old_candidate_off_candidate_on": True,
                        "only_excluded_FRD_record_types": [x.decode().strip() for x in prefixes],
                        "all_other_bytes_and_original_line_endings_preserved": True})
    return results


def main():
    assert __debug__ and not REPORT.exists()
    matrix_receipt = receipt(MATRIX, 6)
    assert matrix_receipt["source_inputs_before"][str(TEST)] == TEST_SHA
    assert sha(capture(TEST)) == TEST_SHA
    assert {path.name for path in MATRIX.iterdir() if path.is_dir() and path.name.startswith("test_")} == set(CASES)
    cases = [audit_case(name, oracle) for name, oracle in CASES.items()]
    legacy = audit_legacy()
    report = {
        "schema": "FreeCAD-960-independent-raw-equilibrium-audit-v1", "result": "pass",
        "checked_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "auditor": "/root/beam960_fixture_review", "findings": [],
        "method": {"stdlib_only": True, "FreeCAD_product_harness_or_solver_code_imported": False,
                   "native_or_build_execution": False, "new_force_or_stress_recovery": False,
                   "expected_wrenches_derived_from_output": False,
                   "rotation_method": "Independent Rodrigues formula: normalized (1,2,3), +31 degrees",
                   "authorship_disclosure": "This auditor authored the analytical fixtures/tests and earlier static reviews, but did not execute native runs. This separate audit uses no product/test/harness imports, parses actual retained native files and uses separately written standard-library vector arithmetic with predeclared literal statics references. A fresh nested arithmetic reviewer could not be started because the collaboration tool returned agent thread limit reached.",
                   "only_new_outputs": [str(Path(__file__)), str(REPORT)]},
        "frozen_test_source": {"path": str(TEST), "sha256": TEST_SHA,
                               "matches_executed_receipt_and_archived_snapshot": True},
        "native_binary_sha256": NATIVE_SHA, "legacy_binary_sha256": OLD_SHA,
        "fixture": {"length_mm": 100., "rectangular_section_mm": [2., 4.],
                    "YoungsModulus_MPa": 100000., "PoissonRatio": .3,
                    "stem_Seg3_elements": 5, "stem_original_nodes": 11,
                    "T_arm_lengths_mm": [10., 10.], "T_arm_Seg3_elements": [1, 1],
                    "T_shared_original_node": 11, "T_point_force_magnitudes_N": [.01, .01],
                    "T_resultant_applied_torque_Nmm": [.2, 0., 0.],
                    "rotation_axis": [1., 2., 3.], "rotation_degrees": 31.,
                    "translation_mm": TRANSLATION,
                    "nodes_connectivity_sections_fixed_DOFs_and_CLOADs_independently_verified": True},
        "cases": cases, "legacy_equivalence": legacy,
        "summary": {"cases_passed": len(cases), "equilibrium_limit": .01,
                    "maximum_relative_force_error": max(x["relative_force_error"] for x in cases),
                    "maximum_relative_moment_error": max(x["relative_moment_error"] for x in cases),
                    "maximum_force_error_percent": max(x["force_error_percent"] for x in cases),
                    "maximum_moment_error_percent": max(x["moment_error_percent"] for x in cases),
                    "distinct_native_end_samples_checked": sum(x["distinct_native_end_samples"] for x in cases),
                    "all_six_channels_dot_checked_per_sample": True,
                    "legacy_cases_with_old_off_new_off_new_on_byte_parity": len(legacy)},
        "limits": ["Only the six explicit small linear B32R rectangular fixtures are qualified; no universal mesh/solver accuracy guarantee.",
                   "Distinct original beam-element ends are observed before original-beam-node averaging; earlier native expanded-node stress extrapolation/averaging remains.",
                   "Rotated translation test uses a pure couple. It does not independently qualify nonzero-force moment transport about a translated global origin.",
                   "This arithmetic/file audit is not fresh native execution, GUI acceptance, installation, Oomakhi replay, structural/design approval or multi-step/mixed-dimensional qualification."],
        "input_files": FILES,
    }
    report["audit_helper_sha256"] = sha(capture(Path(__file__)))
    # Every observed file must remain the same fenced bytes through the audit.
    for path, expected in list(FILES.items()):
        assert sha(capture(path)) == expected["sha256"]
    with REPORT.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
