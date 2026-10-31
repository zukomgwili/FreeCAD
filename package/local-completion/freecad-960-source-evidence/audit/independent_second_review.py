"""Offline, independent free-body arithmetic from actual stock-written decks.

No FreeCAD, solver, fixture/test oracle, stress field or force-recovery import.
The reference is the negative sum of literal deck CLOAD forces and their
original-position moments about the actually fixed original node.
"""

from collections import Counter
from decimal import Decimal, localcontext
import hashlib
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "rotated-matrix-r01"
ZERO = Decimal(0)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dec(value):
    return Decimal(value.replace("D", "E").replace("d", "e"))


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0]]


def norm(a):
    return math.sqrt(math.fsum(float(value) ** 2 for value in a))


def difference(a, b):
    return [float(x) - float(y) for x, y in zip(a, b)]


def parse_deck(path):
    nodes, elements, nsets, elsets, materials, sections = {}, {}, {}, {}, {}, []
    boundary, loads, keywords = [], [], []
    mode, options, material, section, step_count, static_times = "", {}, None, None, 0, None
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("**"):
            continue
        if line.startswith("*"):
            fields = [item.strip().upper() for item in line.split(",")]
            mode, options = fields[0], {}
            for field in fields[1:]:
                key, equal, value = field.partition("=")
                options[key] = value if equal else True
            keywords.append(mode)
            if mode == "*MATERIAL":
                material = options["NAME"]
                materials[material] = {}
            if mode == "*BEAM SECTION":
                section = {"options": dict(options), "rows": []}
                sections.append(section)
            if mode == "*ELEMENT":
                assert options["TYPE"] == "B32R"
            if mode == "*STEP":
                step_count += 1
                assert "NLGEOM" not in options
            continue
        fields = [item.strip() for item in line.split(",") if item.strip()]
        if mode == "*NODE":
            label = int(fields[0])
            assert label not in nodes and len(fields) == 4
            nodes[label] = [dec(item) for item in fields[1:]]
            if "NSET" in options:
                nsets.setdefault(options["NSET"], []).append(label)
        elif mode == "*ELEMENT":
            label = int(fields[0])
            assert label not in elements and len(fields) == 4
            elements[label] = [int(item) for item in fields[1:]]
            if "ELSET" in options:
                elsets.setdefault(options["ELSET"], []).append(label)
        elif mode in ("*NSET", "*ELSET"):
            sets = nsets if mode == "*NSET" else elsets
            key = "NSET" if mode == "*NSET" else "ELSET"
            assert "GENERATE" not in options
            sets.setdefault(options[key], []).extend(
                int(item) if item.isdecimal() else item.upper() for item in fields
            )
        elif mode == "*ELASTIC":
            assert material is not None and len(fields) == 2
            materials[material]["elastic"] = [dec(item) for item in fields]
        elif mode == "*BEAM SECTION":
            section["rows"].append([dec(item) for item in fields])
        elif mode == "*BOUNDARY":
            boundary.append(fields)
        elif mode == "*CLOAD":
            assert len(fields) == 3
            loads.append((int(fields[0]), int(fields[1]), dec(fields[2])))
        elif mode == "*STATIC":
            static_times = [dec(item) for item in fields]

    assert step_count == 1 and static_times is not None and static_times[1] == 1
    assert not set(keywords).intersection({"*DLOAD", "*DSLOAD", "*DYNAMIC", "*AMPLITUDE", "*INCLUDE"})

    def expand(sets, value, visited=()):
        if isinstance(value, int):
            return [value]
        assert value not in visited
        return [item for entry in sets[value] for item in expand(sets, entry, (*visited, value))]

    prescribed = {}
    for row in boundary:
        assert 2 <= len(row) <= 4
        first = int(row[1])
        last = int(row[2]) if len(row) >= 3 else first
        value = dec(row[3]) if len(row) >= 4 else ZERO
        assert value == 0
        selector = int(row[0]) if row[0].isdecimal() else row[0].upper()
        for node in expand(nsets, selector):
            for direction in range(first, last + 1):
                prescribed.setdefault(node, set()).add(direction)
    assert len(prescribed) == 1
    root = next(iter(prescribed))
    assert prescribed[root] == set(range(1, 7))
    owners = {}
    for section in sections:
        assert section["options"]["SECTION"] == "RECT" and len(section["rows"]) == 2
        assert section["rows"][0] == [Decimal(2), Decimal(4)]
        assert materials[section["options"]["MATERIAL"]]["elastic"] == [Decimal(100000), Decimal("0.3")]
        for element in expand(elsets, section["options"]["ELSET"]):
            assert element not in owners
            owners[element] = section
    assert set(owners) == set(elements)
    adjacency = {}
    for element, (first, middle, last) in elements.items():
        assert norm([nodes[middle][i] - (nodes[first][i] + nodes[last][i]) / 2 for i in range(3)]) <= 1e-8
        adjacency.setdefault(first, []).append(last)
        adjacency.setdefault(last, []).append(first)
        tangent = difference(nodes[last], nodes[first])
        axis = owners[element]["rows"][1]
        assert abs(norm(axis) - 1) < 1e-10
        assert abs(math.fsum(float(a) * t for a, t in zip(axis, tangent))) / norm(tangent) < 1e-10
    previous, current, length, stem = None, root, 0.0, [root]
    while current == root or len(adjacency[current]) == 2:
        targets = [node for node in adjacency[current] if node != previous]
        assert len(targets) == 1
        following = targets[0]
        length += norm(difference(nodes[following], nodes[current]))
        previous, current = current, following
        stem.append(current)
    assert abs(length - 100) <= 1e-8
    assert all(node in nodes and 1 <= direction <= 3 for node, direction, _ in loads)
    return nodes, elements, materials, sections, loads, root, stem, length


def inspect(path):
    nodes, elements, materials, sections, loads, root, stem, length = parse_deck(path)
    with localcontext() as context:
        context.prec = 60
        applied_force, applied_moment, terms = [ZERO] * 3, [ZERO] * 3, []
        for node, direction, magnitude in loads:
            force = [ZERO] * 3
            force[direction - 1] = magnitude
            lever = [nodes[node][i] - nodes[root][i] for i in range(3)]
            moment = cross(lever, force)
            applied_force = [a + b for a, b in zip(applied_force, force)]
            applied_moment = [a + b for a, b in zip(applied_moment, moment)]
            terms.append({"node": node, "dof": direction, "force_N": list(map(str, force)),
                          "position_mm": list(map(str, nodes[node])),
                          "lever_mm": list(map(str, lever)), "moment_Nmm": list(map(str, moment))})
        reference_force = [-value for value in applied_force]
        reference_moment = [-value for value in applied_moment]
    outputs = sorted(path.parent.glob("Mesh.beam-section.run-*.out"))
    assert len(outputs) == 1
    output = outputs[0]
    data = json.loads(output.read_text())
    assert data["schema"] == "CCX_BEAM_SECTION_V1" and data["complete"] is True
    assert data["units"] == {"length": "mm", "force": "N", "moment": "N*mm"}
    assert data["sample_identity_scope"] == "ELEMENT_END_BEFORE_NODE_AVERAGING"
    expected_labels = {(element, nodes_[end - 1], end) for element, nodes_ in elements.items() for end in (1, 3)}
    frame = data["frames"][-1]
    assert frame["step"] == 1 and frame["time"] == 1 and frame["complete"] is True
    labels = [(row["element"], row["node"], row["end"]) for row in frame["samples"]]
    assert len(labels) == len(set(labels)) and set(labels) == expected_labels
    roots = [row for row in frame["samples"] if (row["element"], row["node"], row["end"]) == (1, root, 1)]
    assert root == 1 and len(roots) == 1
    observed = roots[0]
    delta = difference(observed["position"], nodes[root])
    assert norm(delta) <= 1e-8
    translated = cross(delta, observed["force_global"])
    observed_root_moment = [a + b for a, b in zip(observed["moment_global"], translated)]
    force_scale, moment_scale = norm(reference_force), norm(reference_moment)
    if force_scale == 0:
        force_scale = 0.02
        nodal_forces = {}
        for node, direction, magnitude in loads:
            nodal_forces.setdefault(node, [ZERO] * 3)[direction - 1] += magnitude
        assert len(nodal_forces) == 2
        assert math.isclose(sum(norm(force) for force in nodal_forces.values()),
                            0.02, rel_tol=1e-12, abs_tol=0.0)
    if moment_scale == 0:
        assert math.isclose(norm(reference_force), 100.0) and math.isclose(length, 100.0)
        moment_scale = 10000.0
    force_error = norm(difference(observed["force_global"], reference_force)) / force_scale
    moment_error = norm(difference(observed_root_moment, reference_moment)) / moment_scale
    handedness, axis_error, projection_error = Counter(), 0.0, 0.0
    for row in frame["samples"]:
        basis = row["basis"]
        axes = [basis[name] for name in ("e1", "e2", "normal")]
        assert all(math.isfinite(value) for axis in axes for value in axis)
        axis_error = max(axis_error, *(abs(norm(axis) - 1) for axis in axes),
                         *(abs(math.fsum(a * b for a, b in zip(axes[i], axes[j])))
                           for i, j in ((0, 1), (0, 2), (1, 2))))
        determinant = math.fsum(a * b for a, b in zip(axes[0], cross(axes[1], axes[2])))
        assert abs(abs(determinant) - 1) <= 1e-8
        handedness["positive" if determinant > 0 else "negative"] += 1
        for name, vector, axis in (("shear1", "force_global", "e1"),
                                   ("shear2", "force_global", "e2"),
                                   ("axial", "force_global", "normal"),
                                   ("torque", "moment_global", "normal"),
                                   ("bend2", "moment_global", "e2"),
                                   ("bend1", "moment_global", "e1")):
            projected = math.fsum(a * b for a, b in zip(row[vector], basis[axis]))
            wire_error = abs(projected - row["native_channels"][name]) / max(1.0, abs(projected), abs(row["native_channels"][name]))
            projection_error = max(projection_error, wire_error)
    assert axis_error <= 1e-8 and projection_error <= 1e-12
    paths = [path, output, Path(str(output)[:-4]), path.with_suffix(".beam-section"),
             Path(str(path.with_suffix(".beam-section")) + ".json")]
    return {"case": path.parent.name, "inputs_sha256": {str(p): sha(p) for p in paths},
            "declared_units": "Stock writer footer: mm, N, MPa=N/mm^2; raw diagnostic mm/N/N*mm agrees",
            "root_node": root, "root_position_mm": list(map(str, nodes[root])),
            "fixed_dofs": [1, 2, 3, 4, 5, 6], "stem_endpoint_path": stem,
            "stem_length_mm": length, "rectangular_dimensions_mm": [2, 4],
            "young_modulus_MPa": 100000, "poisson_ratio": 0.3,
            "cload_terms": terms, "reference_force_N_decimal": list(map(str, reference_force)),
            "reference_moment_about_root_Nmm_decimal": list(map(str, reference_moment)),
            "native_force_N": observed["force_global"],
            "native_moment_about_section_centroid_Nmm": observed["moment_global"],
            "native_moment_about_fixed_root_Nmm": observed_root_moment,
            "root_centroid_offset_mm": delta, "root_centroid_offset_norm_mm": norm(delta),
            "force_denominator_N": force_scale, "moment_denominator_Nmm": moment_scale,
            "force_error_fraction": force_error, "moment_error_fraction": moment_error,
            "physical_tolerance_fraction": 0.01,
            "frame": {key: frame[key] for key in ("step", "increment", "frame", "time")},
            "end_sample_count": len(labels), "maximum_end_incidence_at_one_original_node": max(Counter(node for _, node, _ in labels).values()),
            "basis_handedness_counts": dict(handedness), "maximum_axis_consistency_error": axis_error,
            "maximum_local_projection_wire_error": projection_error,
            "passed": force_error <= 0.01 and moment_error <= 0.01}


decks = sorted(SOURCE.glob("*/Mesh.inp"))
assert len(decks) == 6
rows = [inspect(path) for path in decks]
report = {"schema": "FreeCAD-960-independent-second-static-equilibrium-review-v1",
          "reviewer": "/root/beam960_lifecycle",
          "authorship_disclosure": "Reviewer authored safety/lifecycle tests only, not the analytical physics fixtures, production implementation, native observer, or first arithmetic audit.",
          "method": "Independent 60-digit Decimal summation from literal stock NODE/CLOAD and BOUNDARY/NSET records. Root force=-sum(CLOAD); root moment=-sum((original loaded-node position-original fixed-root position) cross CLOAD). Compare to literal native final element1/node1/end1 wrench; shift its current-centroid moment to the fixed-root point using its observed force and centroid offset. No test-oracle constants or recovered stresses supply references.",
          "frozen_zero_scales": {"pure_couple_force_N": 0.02, "axial_moment_Nmm": 10000.0},
          "script_sha256": sha(__file__), "source_gate_receipt_sha256": sha(SOURCE / "execution.json"),
          "native_execution_performed": False, "FreeCAD_import_performed": False,
          "engineering_limit_changed": False, "cases": rows,
          "findings": [], "passed": all(row["passed"] for row in rows),
          "limitations": "This independently checks six software-fixture free bodies and literal labels/bases. It does not independently re-solve mechanics, repair native expanded-node stress averaging, qualify general meshes/constitutive accuracy, or grant Oomakhi/building acceptance."}
if not report["passed"]:
    report["findings"].append("At least one final native root wrench exceeds the unchanged 1% reference-scaled limit")
destination = ROOT / "independent-second-review.json"
with destination.open("x") as stream:
    json.dump(report, stream, indent=2, allow_nan=False)
    stream.write("\n")
print(json.dumps({"path": str(destination), "sha256": sha(destination), "passed": report["passed"],
                  "cases": [{"case": row["case"], "force_error_fraction": row["force_error_fraction"],
                             "moment_error_fraction": row["moment_error_fraction"]} for row in rows]}, indent=2))
