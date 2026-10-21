#!/usr/bin/env python3
"""Read-only, stdlib-only independent audit of the fresh FreeCAD-3q7 capacity run.

No FreeCAD/FEM/product imports, subprocesses, solves, geometry changes, fitted
acceptance, or use of a historical physical receipt as fresh qualification.
The only write is an explicitly named, new-only report outside the witness.
"""

import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
import re
import sys


TASK = Path("/private/tmp/freecad-3q7-Pq3Byy")
REPO = Path("/Users/zukomgwili/src/FreeCAD")
RUN = TASK / "source-qa/capacity-native-r01"
TEST = ("femtest.app.test_moving_port_capacity_native.TestMovingPortCapacityNative."
        "test_complete_132_bay_graph_obeys_the_native_declaration_budget")
BINARY = "6c02452a896727af6cb4578fd3fb6bbfbdd48e3fb887c1c04fa2d8b171976c66"
FROZEN = {
    "coupled_port_capacity_fixture.json":
        "9142f5aa4d149aa1f0d518a592a78638f9489fb3e245af67ea4fd463e5b8ae22",
    "coupled_port_capacity_oracle.json":
        "42fa6289fd9e1f80efa56db27c02c06a5454ed9880f7ca61bfd80992dfb251b8",
}
COUNTS = {"supports": 1, "bodies": 264, "ports": 264, "angles": 792, "springs": 792}
NUMBER = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?")
READS = {}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def descriptor(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), f"Missing or symlink file: {path}")
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(block)
            digest.update(block)
    return {"sha256": digest.hexdigest(), "bytes": size}


def pin(path):
    path = Path(path)
    value = descriptor(path)
    previous = READS.setdefault(str(path), value)
    require(previous == value, f"File changed during audit: {path}")
    return value


def text(path):
    path = Path(path)
    before = pin(path)
    value = path.read_text(encoding="utf-8")
    require(hashlib.sha256(value.encode()).hexdigest() == before["sha256"],
            f"Read bytes differ from pinned bytes: {path}")
    return value


def unique_pairs(pairs):
    value = {}
    for name, item in pairs:
        require(name not in value, f"Duplicate JSON key: {name}")
        value[name] = item
    return value


def load(path):
    return json.loads(text(path), object_pairs_hook=unique_pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(
                          AssertionError(f"Nonfinite JSON constant: {value}")))


def integer(value):
    require(re.fullmatch(r"[1-9]\d*", str(value)) is not None, f"Invalid positive ID: {value}")
    return int(value)


def real(value):
    result = float(str(value).replace("D", "E").replace("d", "e"))
    require(math.isfinite(result), f"Nonfinite value: {value}")
    return result


def put(mapping, key, value):
    require(key not in mapping, f"Duplicate identity: {key}")
    mapping[key] = value


def exact_set(values, label):
    result = set(values)
    require(len(result) == len(values), f"Duplicate {label}")
    return result


def close(actual, expected, tolerance=1e-12, label="vector"):
    require(len(actual) == len(expected), f"Wrong width: {label}")
    require(all(math.isfinite(value) for value in (*actual, *expected)), f"Nonfinite {label}")
    require(math.dist(actual, expected) <= tolerance, f"Mismatch: {label}")


def cross(one, two):
    return [one[1] * two[2] - one[2] * two[1],
            one[2] * two[0] - one[0] * two[2],
            one[0] * two[1] - one[1] * two[0]]


def supervisor():
    execution, manifest, identity = (load(RUN / (name + ".json"))
                                     for name in ("execution", "manifest", "identity"))
    log = text(RUN / "run.log")
    require(execution["manifest_sha256"] == pin(RUN / "manifest.json")["sha256"],
            "Supervisor manifest binding differs")
    require(execution["identity_sha256"] == pin(RUN / "identity.json")["sha256"],
            "Supervisor identity binding differs")
    require(execution["log_sha256"] == pin(RUN / "run.log")["sha256"], "Run log binding differs")
    for name in ("passed", "reaped", "child_reaped", "process_group_gone", "inputs_unchanged",
                 "app_and_profiles_unchanged", "selected_critical_dependencies_unchanged"):
        require(execution[name] is True, f"Supervisor did not establish {name}")
    require(execution["returncode"] == 0 and execution["timed_out"] is False,
            "Native run failed or timed out")
    require(not execution["missing_repeated_or_skipped_ids"] and not execution["skipped_lines"],
            "Missing, repeated or skipped test")
    require(execution["unittest_counts"][0][0] == "2"
            and len(execution["unittest_counts"]) == 1, "Not exactly two executed tests")
    require(manifest["expected_ids"] == [TEST] and manifest["expected_count"] == 2,
            "Wrong selected physical test")
    require(manifest["case"] == "capacity" and manifest["module"] == "femtest.app.test_moving_port_capacity_native",
            "Wrong physical case/module")
    for item in (execution, manifest, identity):
        require(item["unit_only"] is False and item["discovery_only"] is False,
                "Unit-only/discovery is not physical qualification")
    require(identity["passed"] is True and identity["selected_suite"]["ids"] == [TEST]
            and identity["selected_suite"]["count"] == 1, "Identity did not execute the capacity test")
    pattern = "^" + re.escape(TEST.rsplit(".", 1)[-1]) + r" \(" + re.escape(TEST) + r"\)([^\n]*)$"
    hits = re.findall(pattern, log, re.M)
    require(len(hits) == 1 and "skipped" not in hits[0], "Physical test log identity differs")
    require(re.search(r"^OK\s*$", log, re.M) and not re.search(r"^(FAILED\b|FAIL:|ERROR:|UNEXPECTED SUCCESS:)", log, re.M),
            "Unittest log is not clean")
    require(manifest["inputs"] == execution["inputs_before"], "Supervisor input manifest differs")
    require(execution["inputs_after"] == manifest["inputs"]["files"], "Input end fence differs")
    for path, expected in manifest["inputs"]["files"].items():
        require(pin(path)["sha256"] == expected, f"Current run input changed: {path}")
    for name in ("fem_python_copy_parity", "fem_capacity_json_copy_parity"):
        require(manifest[name] == {"passed": True, "missing": [], "mismatched": []},
                f"Source/build copy parity failure: {name}")
    for stem, key in (("private-custody", "private_custody_before_sha256"),
                      ("private-critical", "private_critical_before_sha256")):
        before = RUN / (stem + "-before.json")
        require(pin(before)["sha256"] == manifest[key], "Private before-custody binding differs")
        require(load(before) == load(RUN / (stem + "-after.json")), "Private custody changed")
    require(manifest["candidate"] == identity["candidate"], "Runtime candidate identity differs")
    require(manifest["candidate"]["sha256"] == BINARY
            and manifest["candidate"]["override"] is False, "Not the qualified default native binary")
    require(pin(manifest["candidate"]["path"])["sha256"] == BINARY, "Current native binary differs")
    native = manifest["native_build_receipt"]
    require(native is not None and native == identity["native_build_receipt"],
            "No native-build receipt binding")
    require(pin(native["path"])["sha256"] == native["sha256"], "Native receipt hash differs")
    attestation = load(native["path"])
    require(attestation["passed"] is True and attestation["candidate"]["sha256"] == BINARY,
            "Inherited native attestation does not bind this binary")
    # The inherited compilation provenance is explicit; no claim of a new compile.
    require(attestation["derived_receipt"] is True and attestation["new_execution_performed"] is False
            and attestation["contract_compilation_claimed"] is False,
            "Unexpected native compilation claim")
    require(attestation["compiled_sources_sha256"] == {
                name: manifest["native_source_observed_sha256"][name]
                for name in ("forceaccounting.c", "hooks.patch")}
            and native["native_source_sha256"] == manifest["native_source_observed_sha256"],
            "Compiled C/hooks and observed current native sources differ")
    for key in ("validated_original_inputs", "validated_current_files"):
        for path, expected in attestation[key].items():
            require(pin(path)["sha256"] == expected, f"Native attestation input differs: {path}")
    for item in attestation["original_evidence"].values():
        require(pin(item["path"])["sha256"] == item["sha256"], "Inherited native evidence differs")
    prefixes = re.findall(r"Native capacity evidence: ([^\r\n]+)", log)
    require(len(prefixes) == 1, "Need one concrete fresh logged native witness prefix")
    prefix = Path(prefixes[0].strip())
    require(prefix.is_absolute() and prefix.resolve().is_relative_to((RUN / "freecad_user_temp").resolve())
            and prefix.name.startswith("freecad-moving-port-capacity-native-"),
            "Logged witness is not this session's fresh capacity output")
    return prefix / "witness", manifest, execution, identity


def request_file(path):
    tokens = iter(text(path).split())

    def take():
        try:
            return next(tokens)
        except StopIteration as error:
            raise AssertionError("Truncated request") from error

    require(take() == "CCX_FORCE_ACCOUNTING_V3", "Wrong request schema")
    result = {key: {} for key in COUNTS}
    while True:
        kind = take()
        if kind == "END":
            require(next(tokens, None) is None, "Trailing request tokens")
            return result
        if kind == "PORT":
            put(result["ports"], take(), (integer(take()), integer(take())))
        elif kind == "ANGLE":
            put(result["angles"], integer(take()), (integer(take()), tuple(real(take()) for _ in range(3))))
        elif kind == "SPRING":
            put(result["springs"], integer(take()), (integer(take()), integer(take())))
        elif kind == "BODY":
            name, cells, nodes = take(), integer(take()), integer(take())
            put(result["bodies"], name, (exact_set([integer(take()) for _ in range(cells)], "BODY cells"),
                                         exact_set([integer(take()) for _ in range(nodes)], "BODY cut nodes")))
        elif kind == "SPC_SUPPORT":
            name, count = take(), integer(take())
            pairs = [(integer(take()), integer(take())) for _ in range(count)]
            require(all(dof in (1, 2, 3) for _, dof in pairs), "Unsupported support DOF")
            put(result["supports"], name, exact_set(pairs, "support node/DOF pairs"))
        else:
            raise AssertionError(f"Unfrozen request record: {kind}")


def deck_file(path):
    cards, current = [], None
    allowed = {"NODE", "ELEMENT", "NSET", "ELSET", "SURFACE", "PHYSICAL CONSTANTS", "MATERIAL",
               "ELASTIC", "EXPANSION", "DENSITY", "SOLID SECTION", "RIGID BODY", "ORIENTATION",
               "SPRING", "EQUATION", "BOUNDARY", "STEP", "STATIC", "SECTION PRINT", "CLOAD",
               "NODE FILE", "EL FILE", "NODE PRINT", "OUTPUT", "END STEP"}
    for line in text(path).splitlines():
        line = line.strip()
        if not line or line.startswith("**"):
            continue
        fields = [item.strip().upper() for item in line.split(",") if item.strip()]
        if line.startswith("*"):
            name, options, flags = fields[0][1:], {}, set()
            require(name in allowed, f"Unfrozen deck card: {name}")
            for field in fields[1:]:
                if "=" in field:
                    key, value = field.split("=", 1)
                    put(options, key.strip(), value.strip())
                else:
                    require(field not in flags, "Repeated card flag")
                    flags.add(field)
            current = [name, options, flags, []]
            cards.append(current)
        else:
            require(current is not None, "Orphan deck data")
            current[3].append(fields)
    out = {name: {} for name in ("nodes", "elements", "nsets", "elsets", "rigid", "orientations", "materials")}
    out.update({name: [] for name in ("springs", "equations", "boundaries", "loads", "sections")})
    out["motion_sets"] = set()
    material = None
    for kind, attrs, flags, rows in cards:
        if kind == "NODE":
            require(not flags and set(attrs) <= {"NSET"}, "Unexpected NODE options")
            for row in rows:
                require(len(row) == 4, "NODE width")
                node = integer(row[0])
                put(out["nodes"], node, [real(value) for value in row[1:]])
                if "NSET" in attrs:
                    out["nsets"].setdefault(attrs["NSET"], []).append(str(node))
        elif kind == "ELEMENT":
            require(not flags and "TYPE" in attrs and set(attrs) <= {"TYPE", "ELSET"}, "ELEMENT options")
            width = {"C3D4": 4, "C3D10": 10, "SPRING2": 2}.get(attrs["TYPE"])
            require(width is not None, "Unfrozen element type")
            for row in rows:
                require(len(row) == width + 1, "Element width/continuation")
                number, nodes = integer(row[0]), tuple(integer(value) for value in row[1:])
                require(len(set(nodes)) == width, "Repeated element node")
                put(out["elements"], number, (attrs["TYPE"], nodes))
                if "ELSET" in attrs:
                    out["elsets"].setdefault(attrs["ELSET"], []).append(str(number))
        elif kind in ("NSET", "ELSET"):
            require(set(attrs) == {kind} and flags <= {"GENERATE"}, "Unexpected set options")
            values = out["nsets" if kind == "NSET" else "elsets"].setdefault(attrs[kind], [])
            for row in rows:
                if "GENERATE" in flags:
                    require(len(row) in (2, 3), "GENERATE width")
                    start, end = integer(row[0]), integer(row[1])
                    require(end >= start, "Descending generated set")
                    values.extend(str(value) for value in range(start, end + 1, integer(row[2]) if len(row) == 3 else 1))
                else:
                    values.extend(row)
        elif kind == "RIGID BODY":
            require(not flags and set(attrs) == {"NSET", "REF NODE", "ROT NODE"} and not rows, "RBE construction")
            put(out["rigid"], attrs["NSET"], (integer(attrs["REF NODE"]), integer(attrs["ROT NODE"])))
        elif kind == "ORIENTATION":
            require(not flags and set(attrs) == {"NAME"} and len(rows) == 1 and len(rows[0]) == 6, "Orientation construction")
            put(out["orientations"], attrs["NAME"], [real(value) for value in rows[0]])
        elif kind == "SPRING":
            require(not flags and set(attrs) <= {"ELSET", "ORIENTATION"} and "ELSET" in attrs
                    and len(rows) == 2 and len(rows[0]) == 2 and len(rows[1]) == 1, "Spring law construction")
            dofs, stiffness = tuple(integer(value) for value in rows[0]), real(rows[1][0])
            require(dofs[0] == dofs[1] and dofs[0] in (1, 2, 3) and stiffness > 0, "Spring direction/stiffness")
            out["springs"].append((attrs["ELSET"], attrs.get("ORIENTATION"), dofs, stiffness))
        elif kind == "EQUATION":
            require(not attrs and not flags, "EQUATION options")
            index = 0
            while index < len(rows):
                require(len(rows[index]) == 1, "Equation term count")
                count, flat = integer(rows[index][0]), []
                index += 1
                while len(flat) < count * 3:
                    require(index < len(rows), "Truncated equation")
                    flat.extend(rows[index])
                    index += 1
                require(len(flat) == count * 3, "Excess equation terms")
                out["equations"].append([(integer(flat[n]), integer(flat[n + 1]), real(flat[n + 2]))
                                         for n in range(0, len(flat), 3)])
        elif kind == "BOUNDARY":
            require(not attrs and not flags, "BOUNDARY options")
            for row in rows:
                require(2 <= len(row) <= 4, "Boundary width")
                first, last = integer(row[1]), integer(row[2]) if len(row) >= 3 else integer(row[1])
                require(1 <= first <= last <= 3 and (real(row[3]) if len(row) == 4 else 0) == 0, "Nonzero/unsupported boundary")
                out["boundaries"].append((row[0], first, last))
        elif kind == "CLOAD":
            require(not attrs and not flags, "CLOAD options")
            for row in rows:
                require(len(row) == 3 and integer(row[1]) in (1, 2, 3), "CLOAD width/DOF")
                out["loads"].append((integer(row[0]), integer(row[1]), real(row[2])))
        elif kind == "NODE PRINT" and "NSET" in attrs and any("U" in row for row in rows):
            out["motion_sets"].add(attrs["NSET"])
        elif kind == "MATERIAL":
            require(not flags and set(attrs) == {"NAME"} and not rows, "Material construction")
            material = attrs["NAME"]
            put(out["materials"], material, {})
        elif kind == "ELASTIC":
            require(material is not None and not attrs and not flags and len(rows) == 1 and len(rows[0]) == 2, "Elastic law")
            put(out["materials"][material], "elastic", [real(value) for value in rows[0]])
        elif kind == "SOLID SECTION":
            require(not flags and set(attrs) == {"ELSET", "MATERIAL"} and not rows, "Solid section")
            out["sections"].append((attrs["ELSET"], attrs["MATERIAL"]))
    starts = [index for index, row in enumerate(cards) if row[0] == "STEP"]
    statics = [index for index, row in enumerate(cards) if row[0] == "STATIC"]
    ends = [index for index, row in enumerate(cards) if row[0] == "END STEP"]
    require(len(starts) == len(statics) == len(ends) == 1 and starts[0] < statics[0] < ends[0] == len(cards) - 1, "Single linear static step layout")
    step, static = cards[starts[0]], cards[statics[0]]
    require(not step[2] and set(step[1]) <= {"INC"} and not static[1] and not static[2]
            and len(static[3]) == 1 and len(static[3][0]) >= 2 and real(static[3][0][1]) == 1, "Static final time/options")
    require(all(starts[0] < index < ends[0] for index, row in enumerate(cards) if row[0] == "CLOAD"), "Load outside step")
    require(all(index < starts[0] for index, row in enumerate(cards)
                if row[0] in {"NODE", "ELEMENT", "RIGID BODY", "SPRING", "EQUATION"}), "Graph constructed inside step")
    require(all(node in out["nodes"] for _, nodes in out["elements"].values() for node in nodes), "Missing element node")
    return out


def members(sets, name, visiting=()):
    name = name.upper()
    require(name not in visiting and name in sets, f"Missing/cyclic set: {name}")
    result = set()
    for token in sets[name]:
        values = {integer(token)} if token.isdecimal() else members(sets, token, (*visiting, name))
        require(not result.intersection(values), f"Repeated member in {name}")
        result.update(values)
    return result


def mesh_and_graph(geometry, membership, asked, deck):
    branches = geometry["branches_and_references"]
    require(geometry["rows_y"] == 11 and geometry["columns_z"] == 12
            and geometry["branches"] == len(branches) == 132 and geometry["physical_solids"] == 397,
            "Not the complete physical capacity fixture")
    require(geometry["frozen_oracle_sha256"] == FROZEN, "Geometry frozen inputs differ")
    require({key: len(value) for key, value in asked.items()} == COUNTS, "Declaration counts differ")
    require(sum(COUNTS.values()) == 2113, "Wrong exact total")
    coordinates = {integer(node): [real(value) for value in point] for node, point in membership["nodes"].items()}
    cells = {integer(cell): tuple(integer(node) for node in nodes)
             for cell, nodes in membership["volume_connectivity"].items()}
    volumes = {cell: value for cell, value in deck["elements"].items() if value[0] != "SPRING2"}
    require(set(cells) == set(volumes), "Physical element IDs differ")
    for cell, nodes in cells.items():
        require(len(nodes) in (4, 10) and len(set(nodes)) == len(nodes), "Invalid native tetra connectivity")
        # Fixed public FreeCAD -> CalculiX tetra order, independently checked in
        # FemMesh.cpp and the inverse FRD reader. Never accept an arbitrary
        # corner/midside permutation merely because its full node set matches.
        order = (1, 0, 2, 3) if len(nodes) == 4 else (1, 0, 2, 3, 4, 6, 5, 8, 7, 9)
        require(volumes[cell] == ("C3D4" if len(nodes) == 4 else "C3D10", tuple(nodes[index] for index in order)),
                "Exact native/deck tetra corner-and-midside node order differs")
    require(set(coordinates) == {node for nodes in cells.values() for node in nodes}, "Native physical node union differs")
    for node, point in coordinates.items():
        close(deck["nodes"][node], point, 1e-8, "physical coordinate")
    solid_cells, solid_nodes, assigned = {}, {}, set()
    for name, values in membership["cell_volume_elements"].items():
        selected = exact_set(values, "native solid elements")
        require(selected and selected <= set(cells) and not assigned.intersection(selected), "Overlapping native solid cells")
        assigned.update(selected)
        solid_cells[name] = selected
        solid_nodes[name] = {node for cell in selected for node in cells[cell]}
        facets = {}
        for cell in selected:
            for facet in itertools.combinations(cells[cell][:4], 3):
                facets.setdefault(tuple(sorted(facet)), []).append(cell)
        require(all(len(owners) <= 2 for owners in facets.values()), "Nonmanifold native solid tetra facet")
        neighbours = {cell: set() for cell in selected}
        for owners in facets.values():
            if len(owners) == 2:
                neighbours[owners[0]].add(owners[1])
                neighbours[owners[1]].add(owners[0])
        visited, pending = set(), [next(iter(selected))]
        while pending:
            cell = pending.pop()
            if cell not in visited:
                visited.add(cell)
                pending.extend(neighbours[cell] - visited)
        proof = membership["cell_tetra_facet_connectivity_proof"][name]
        require(visited == selected and proof["connected_tetra_facet_components"] == 1
                and proof["volume_elements"] == len(selected)
                and proof["interior_shared_tetra_facets"] == sum(len(owners) == 2 for owners in facets.values()),
                "Native finite-solid facet connectivity proof differs")
    require(len(solid_cells) == 397 and assigned == set(cells), "Solid ownership is not an exact 397-cell partition")
    # Prove actual cross-solid tetra-facet joins, not merely shared single nodes.
    owner_of = {cell: owner for owner, selected in solid_cells.items() for cell in selected}
    global_facets = {}
    for cell, nodes in cells.items():
        for facet in itertools.combinations(nodes[:4], 3):
            global_facets.setdefault(tuple(sorted(facet)), []).append(cell)
    require(all(len(owners) <= 2 for owners in global_facets.values()), "Nonmanifold global native tetra facet")
    shared_nodes, shared_area = {}, {}
    exterior = {}
    for facet, owners in global_facets.items():
        points = [coordinates[node] for node in facet]
        one, two = ([points[index][k] - points[0][k] for k in range(3)] for index in (1, 2))
        area = .5 * math.hypot(*cross(one, two))
        require(area > 0, "Degenerate native tetra facet")
        if len(owners) == 2 and owner_of[owners[0]] != owner_of[owners[1]]:
            pair = frozenset(owner_of[cell] for cell in owners)
            shared_nodes.setdefault(pair, set()).update(set(cells[owners[0]]).intersection(cells[owners[1]]))
            shared_area[pair] = shared_area.get(pair, 0.0) + area
        elif len(owners) == 1:
            cell = owners[0]
            ccx_nodes = volumes[cell][1]
            faces = ((0, 1, 2), (0, 3, 1), (1, 3, 2), (2, 3, 0)) if len(ccx_nodes) == 4 else (
                (0, 1, 2, 4, 5, 6), (0, 3, 1, 7, 8, 4),
                (1, 3, 2, 8, 9, 5), (2, 3, 0, 9, 7, 6))
            face = next((face for face in faces if {ccx_nodes[index] for index in face[:3]} == set(facet)), None)
            require(face is not None, "Native/CalculiX exterior facet corner identity differs")
            exterior.setdefault(owner_of[cell], []).append((facet, {ccx_nodes[index] for index in face}, area))
    declared_shared = {}
    for item in membership["conforming_shared_CAD_and_mesh_face_proof"]:
        owners = frozenset(item["owners"])
        require(len(owners) == 2, "Repeated shared face owner")
        put(declared_shared, owners, exact_set(item["face_nodes"], "shared face nodes"))
        require(item["area_mm2"] == 4 and abs(shared_area.get(owners, 0) - 4) <= 1e-8,
                "Native shared tetra-facet area differs from the declared finite 4mm2 face")
    require(declared_shared == shared_nodes and len(shared_nodes) == 264, "Actual native cross-solid facet joins differ")
    del global_facets

    def exterior_square(solid, x, y0, y1, z0, z1, expected_area):
        selected, area = set(), 0.0
        for corners, face_nodes, facet_area in exterior.get(solid, []):
            if all(abs(coordinates[node][0] - x) <= 1e-8
                   and y0 - 1e-8 <= coordinates[node][1] <= y1 + 1e-8
                   and z0 - 1e-8 <= coordinates[node][2] <= z1 + 1e-8 for node in corners):
                require(all(abs(coordinates[node][0] - x) <= 1e-8
                            and y0 - 1e-8 <= coordinates[node][1] <= y1 + 1e-8
                            and z0 - 1e-8 <= coordinates[node][2] <= z1 + 1e-8 for node in face_nodes),
                        "Native quadratic face midside lies off the frozen exterior square")
                selected.update(face_nodes)
                area += facet_area
        require(selected and abs(area - expected_area) <= 1e-8, "Frozen finite exterior patch area differs")
        return selected
    require(len(deck["materials"]) == 1 and next(iter(deck["materials"].values())) == {"elastic": [20000.0, 0.3]}, "Frozen elastic material differs")
    assigned = set()
    for name, material in deck["sections"]:
        values = members(deck["elsets"], name)
        require(material in deck["materials"] and values <= set(cells) and not assigned.intersection(values), "Material assignment overlaps/helpers")
        assigned.update(values)
    require(assigned == set(cells), "Missing physical material assignment")
    pairs = exact_set([tuple(pair) for pair in membership["physical_fixed_node_DOF_pairs"]], "physical support DOFs")
    fixed = exact_set(membership["fixed_face_nodes"], "fixed face nodes")
    require(pairs == {(node, dof) for node in fixed for dof in (1, 2, 3)} and fixed <= solid_nodes[geometry["backbone_solid"]], "Physical fixed face differs")
    require(fixed == exterior_square(geometry["backbone_solid"], 0, 0, 44, 1, 49, 2112),
            "Selected physical support is not the complete finite original x0 backbone face")
    require(len(asked["supports"]) == 1 and next(iter(asked["supports"].values())) == pairs, "Selected support differs")
    allports, allcuts, detached, refpairs, rotpairs = set(), set(), set(), {}, {}
    ports, indices, all_B, all_receiving, all_end = {}, set(), set(), set(), set()
    host = solid_nodes[geometry["backbone_solid"]].copy()
    for branch in branches:
        i, j, bay = branch["i"], branch["j"], branch["name"]
        require(type(i) is int and type(j) is int and 0 <= i < 11 and 0 <= j < 12
                and (i, j) not in indices and bay == f"Bay_{i:02d}_{j:02d}"
                and branch["y"] == 2 + 4 * i and branch["z"] == 3 + 4 * j, "Frozen branch identity/position differs")
        indices.add((i, j))
        left, right, stub = (branch["solids"][role] for role in ("B_left", "B_right", "A"))
        host_pair = frozenset((geometry["backbone_solid"], stub))
        body_pair = frozenset((left, right))
        require(host_pair in shared_nodes and body_pair in shared_nodes
                and solid_nodes[stub].intersection(solid_nodes[geometry["backbone_solid"]]) == shared_nodes[host_pair],
                "Host tongue lacks an exact finite shared native face")
        cut = exact_set(membership["paired_cut_nodes"][bay], "paired cut nodes")
        end = exact_set(membership["end_loaded_nodes"][bay], "end load nodes")
        require(end == exterior_square(right, 30, branch["y"] - 1, branch["y"] + 1,
                                       branch["z"] - 1, branch["z"] + 1, 4),
                "Loaded physical face is not the complete frozen native end square")
        require(cut and cut == solid_nodes[left].intersection(solid_nodes[right]) and end and end <= solid_nodes[right]
                and not end.intersection(cut | fixed | all_end), "Native body/cut/end ownership differs")
        require(cut == shared_nodes[body_pair], "Paired cut is not the actual native shared tetra face")
        all_end.update(end)
        body = solid_nodes[left] | solid_nodes[right]
        require(not all_B.intersection(body) and not host.intersection(body), "Disconnected B body was welded/reused")
        all_B.update(body)
        host.update(solid_nodes[stub])
        for side, role in (("Left", left), ("Right", right)):
            name = branch["cuts"][side]["object"]
            require(name not in allcuts and asked["bodies"].get(name) == (solid_cells[role], cut), "BODY owner/incidence differs")
            allcuts.add(name)
        for side, x, solid in (("A", 10, stub), ("B", 20, left)):
            name = branch["ports"][side]["object"]
            require(name not in allports and name in asked["ports"], "Duplicate/missing PORT")
            allports.add(name)
            reference, rotation = asked["ports"][name]
            require(reference != rotation and not {reference, rotation}.intersection(set(coordinates) | detached), "Reference/rotation IDs overlap")
            detached.update((reference, rotation))
            face = exact_set(membership["moving_face_nodes"][name], "port face nodes")
            require(face == exterior_square(solid, x, branch["y"] - 1, branch["y"] + 1,
                                             branch["z"] - 1, branch["z"] + 1, 4),
                    "Receiving face is not the complete frozen finite native exterior square")
            require(len(face) >= 3 and face <= solid_nodes[solid]
                    and not face.intersection(cut | end | fixed | all_receiving), "Receiving face is missing/shared/loaded/prescribed")
            origin = coordinates[next(iter(face))]
            vectors = [[coordinates[node][k] - origin[k] for k in range(3)] for node in face]
            require(any(math.hypot(*cross(one, two)) > 1e-12 for one, two in itertools.combinations(vectors, 2)), "Collinear receiving face")
            all_receiving.update(face)
            require(deck["rigid"].get(name.upper()) == (reference, rotation)
                    and members(deck["nsets"], name) == face, "Original RBE differs from declared finite face")
            position = [x, branch["y"], branch["z"]]
            for node in (reference, rotation):
                close(deck["nodes"][node], position, 1e-8, "RBE position")
            for suffix, node in (("_RefNode", reference), ("_RotNode", rotation)):
                require(members(deck["nsets"], name + suffix) == {node}
                        and (name + suffix).upper() in deck["motion_sets"], "RBE motion-print ID differs")
            ports[name] = {"reference_node": reference, "rotation_node": rotation, "position": position, "side": side, "branch": bay}
        a, b = (ports[branch["ports"][side]["object"]] for side in ("A", "B"))
        put(refpairs, (a["reference_node"], b["reference_node"]), bay)
        put(rotpairs, (a["rotation_node"], b["rotation_node"]), bay)
    require(indices == set(itertools.product(range(11), range(12))) and allports == set(asked["ports"])
            and allcuts == set(asked["bodies"]) and set(deck["rigid"]) == {name.upper() for name in allports}, "Incomplete branch graph")
    require(not host.intersection(all_B) and host | all_B == set(coordinates), "Host/B continuum partition differs")
    require(not all_end.intersection(all_receiving | fixed | set().union(*(
                set(values) for values in membership["paired_cut_nodes"].values())))
            and not all_receiving.intersection(set().union(*(
                set(values) for values in membership["paired_cut_nodes"].values()))),
            "Cross-branch physical load/port/cut overlap")
    require(membership["physical_continuum_components_before_scalar_links"] == 133
            and membership["coupled_graph_components_after_scalar_links"] == 1,
            "Declared continuum/linked component counts differ")
    angles = asked["angles"]
    require(not set(angles).intersection(set(coordinates) | detached)
            and set(deck["nodes"]) == set(coordinates) | detached | set(angles), "Extra/detached node graph differs")
    equations = {}
    for terms in deck["equations"]:
        require(len(terms) == 2 and terms[0][1] == 1 and terms[0][2] != 0, "Angular equation topology")
        put(equations, terms[0][0], terms)
    require(set(equations) == set(angles), "Equation/ANGLE identities differ")
    axis_of = {(1.0, 0.0, 0.0): 1, (0.0, 1.0, 0.0): 2, (0.0, 0.0, 1.0): 3}
    rotation_nodes = {port["rotation_node"] for port in ports.values()}
    for auxiliary, (rotation, axis) in angles.items():
        require(axis in axis_of and rotation in rotation_nodes, "ANGLE axis/rotation differs")
        terms = equations[auxiliary]
        require(terms[1][:2] == (rotation, axis_of[axis])
                and abs(terms[1][2] / terms[0][2] + 1) <= 1e-12, "Angular scalar equation differs")
    springs = {cell: nodes for cell, (kind, nodes) in deck["elements"].items() if kind == "SPRING2"}
    require(springs == asked["springs"], "Scalar native/request element incidence differs")
    laws = {}
    for name, orientation, directions, stiffness in deck["springs"]:
        for cell in members(deck["elsets"], name):
            put(laws, cell, (orientation, directions, stiffness))
    require(set(laws) == set(springs), "Missing/extra scalar law")
    modes, used_angles = set(), set()
    for cell, endpoints in springs.items():
        orientation, directions, stiffness = laws[cell]
        if endpoints in refpairs:
            bay, mode, axis = refpairs[endpoints], "T", directions[0]
            require(stiffness == 1200 and orientation in deck["orientations"], "Translational scalar stiffness/orientation")
            close(deck["orientations"][orientation], [1, 0, 0, 0, 1, 0], 1e-12, "global scalar orientation")
        else:
            require(all(node in angles for node in endpoints) and not used_angles.intersection(endpoints), "Scalar endpoint reuse/cross-domain")
            one, two = (angles[node] for node in endpoints)
            require((one[0], two[0]) in rotpairs and one[1] == two[1]
                    and stiffness == 6000 and orientation is None and directions == (1, 1), "Rotational scalar incidence/law")
            bay, mode, axis = rotpairs[(one[0], two[0])], "R", axis_of[one[1]]
            used_angles.update(endpoints)
        require((bay, mode, axis) not in modes, "Duplicate bay/mode/axis")
        modes.add((bay, mode, axis))
    require(used_angles == set(angles) and modes == {(branch["name"], mode, axis) for branch in branches
                                                   for mode in ("T", "R") for axis in (1, 2, 3)}, "Missing/orphan scalar mode")
    boundaries = set()
    for token, first, last in deck["boundaries"]:
        selected = {integer(token)} if token.isdecimal() else members(deck["nsets"], token)
        for pair in itertools.product(selected, range(first, last + 1)):
            require(pair not in boundaries, "Repeated prescribed node/DOF")
            boundaries.add(pair)
    require(boundaries == pairs | {(node, dof) for node in angles for dof in (2, 3)}, "Moving port is prescribed/physical support differs")
    loads = {branch["name"]: [0.0] * 6 for branch in branches}
    torque_edges = {branch["name"]: [0.0, 0.0] for branch in branches}
    branch_map = {branch["name"]: branch for branch in branches}
    end_owner = {node: branch["name"] for branch in branches for node in membership["end_loaded_nodes"][branch["name"]]}
    for node, dof, value in deck["loads"]:
        if value:
            require(node in end_owner and node in coordinates and dof in (1, 3), "Nonzero load outside physical end")
            require(abs(deck["nodes"][node][0] - 30) <= 1e-8, "Nonzero load off end plane")
            force = [0.0] * 3
            force[dof - 1] = value
            if dof == 3:
                centre = branch_map[end_owner[node]]["y"]
                y = deck["nodes"][node][1]
                require(abs(y - (centre + 1)) <= 1e-8 or abs(y - (centre - 1)) <= 1e-8,
                        "Torque is not applied on a frozen original end edge")
                torque_edges[end_owner[node]][0 if abs(y - (centre + 1)) <= 1e-8 else 1] += value
            contribution = force + cross(deck["nodes"][node], force)
            loads[end_owner[node]] = [one + two for one, two in zip(loads[end_owner[node]], contribution)]
    for branch in branches:
        target = [12, 0, 0, 6, 12 * branch["z"], -12 * branch["y"]]
        require(abs(torque_edges[branch["name"]][0] - 3) <= .03
                and abs(torque_edges[branch["name"]][1] + 3) <= .03, "Frozen +/-3N physical edge pair differs")
        for offset in (0, 3):
            require(math.dist(loads[branch["name"]][offset:offset + 3], target[offset:offset + 3])
                    <= .01 * math.hypot(*target[offset:offset + 3]), "Frozen applied load/moment differs")
    return branches, coordinates, ports, loads


def raw_channels(path, support, bodies):
    rows = [line.split() for line in text(path).splitlines() if line.strip()]
    require(rows[0] == ["CCX_FORCE_ACCOUNTING_V3"] and rows[-1] == ["END"], "Incomplete native V3 output")
    require(len(rows[1]) == 4 and rows[1][0] == "STATE" and integer(rows[1][1]) == 1
            and integer(rows[1][2]) >= 1 and abs(real(rows[1][3]) - 1) <= 1e-12, "Wrong actual native state")
    channels = {key: {} for key in ("SUPPORT", "CUT", "LOAD", "CONTACT", "MPC")}
    for row in rows[2:-1]:
        require(len(row) == 8 and row[0] in channels, "Invalid native accounting row")
        put(channels[row[0]], row[1], [real(value) for value in row[2:]])
    require(set(channels["SUPPORT"]) == {support}, "Support accounting identity differs")
    require(all(set(channels[kind]) == bodies for kind in ("CUT", "LOAD", "CONTACT", "MPC")), "Missing native body/channel")
    return channels


def original_dat(path, ports):
    expected, found = {}, {}
    for name, port in ports.items():
        for suffix, key, node in (("_REFNODE", "translation_mm", port["reference_node"]),
                                  ("_ROTNODE", "rotation_rad", port["rotation_node"])):
            put(expected, (name + suffix).upper(), (name, key, node))
    header = re.compile(r"^\s*displacements\s+\(vx,vy,vz\)\s+for set\s+(\S+)\s+and time\s+(\S+)\s*$", re.I)
    lines = text(path).splitlines()
    index = 0
    while index < len(lines):
        match = header.match(lines[index])
        index += 1
        if not match or match[1].upper() not in expected:
            continue
        time = real(match[2])
        require(0 <= time <= 1 + 1e-12, "Unexpected original port-motion DAT time")
        if abs(time - 1) > 1e-12:
            continue
        set_name = match[1].upper()
        require(set_name not in found, "Duplicate final-time DAT motion set")
        while index < len(lines) and not lines[index].strip():
            index += 1
        values = []
        while index < len(lines) and lines[index].strip():
            line = lines[index]
            parts = NUMBER.findall(line)
            require(not NUMBER.sub("", line).strip() and len(parts) == 4, "Invalid DAT displacement row")
            values.append((integer(parts[0]), [real(item) for item in parts[1:]]))
            index += 1
        require(len(values) == 1 and values[0][0] == expected[set_name][2], "Original DAT RefNode/RotNode identity differs")
        found[set_name] = values[0][1]
    require(set(found) == set(expected), "Missing final-time native DAT motion")
    result = {name: {} for name in ports}
    for set_name, (name, key, _) in expected.items():
        result[name][key] = found[set_name]
    return result


def original_frd(path):
    pin(path)
    current_time, active, current, blocks = None, False, {}, []
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            if re.match(r"^\s*100CL\s", line):
                require(not active, "FRD field missing terminator")
                current_time = real(line.split()[2])
            elif re.match(r"^\s*-4\s+DISP\b", line):
                require(not active and current_time is not None, "Unbound/nested FRD DISP")
                active, current = True, {}
            elif active and line.startswith(" -1"):
                require(len(line.rstrip("\r\n")) >= 49, "Truncated fixed-width FRD DISP")
                put(current, integer(line[4:13].strip()), [real(line[start:start + 12]) for start in (13, 25, 37)])
            elif active and line.startswith(" -3"):
                require(current, "Empty FRD displacement state")
                blocks.append((current_time, current))
                active = False
            elif active:
                require(line.startswith(" -5"), "Unexpected FRD DISP record/continuation")
    require(not active and blocks and all(0 <= time <= 1 for time, _ in blocks)
            and blocks[-1][0] == 1 and sum(time == 1 for time, _ in blocks) == 1, "FRD final actual displacement time differs")
    pin(path)
    return [time for time, _ in blocks], blocks[-1][1]


def vector_check(result, name, actual, reference, zero_scale, limit):
    close(actual, actual, label=name)
    require(len(actual) == len(reference) == 3, "Not a three-vector")
    norm, error = math.hypot(*reference), math.dist(actual, reference)
    scale = norm or zero_scale
    require(math.isfinite(scale) and scale > 0 and error <= limit * scale, f"Physical acceptance failed: {name}")
    put(result, name, {"name": name, "actual": actual, "reference": reference, "reference_norm": norm,
                       "error_norm": error, "scale": scale, "relative_error": error / scale,
                       "limit": limit, "passed": True})


def wrench_check(result, name, actual, reference, force_scale, moment_scale):
    require(len(actual) == len(reference) == 6, "Not a six-wrench")
    for offset, suffix, zero in ((0, "/force", force_scale), (3, "/original-origin-moment", moment_scale)):
        vector_check(result, name + suffix, actual[offset:offset + 3], reference[offset:offset + 3], zero, .01)


def mathematics(branches, channels, motion, support, oracle):
    result = {}
    total = oracle["capacity_11_by_12"]["whole_applied_wrench"]
    wrench_check(result, "SUPPORT/" + support, channels["SUPPORT"][support], [-value for value in total],
                 math.hypot(*total[:3]), math.hypot(*total[3:]))
    work, energy = 0.0, 0.0
    for branch in branches:
        bay = branch["name"]
        w = [12, 0, 0, 6, 12 * branch["z"], -12 * branch["y"]]
        moment_scale = math.hypot(*w[3:])
        for side in ("Left", "Right"):
            name = branch["cuts"][side]["object"]
            targets = {"CUT": w if side == "Left" else [-value for value in w],
                       "LOAD": [0] * 6 if side == "Left" else w,
                       "CONTACT": [0] * 6, "MPC": [-value for value in w] if side == "Left" else [0] * 6}
            for kind, target in targets.items():
                wrench_check(result, kind + "/" + name, channels[kind][name], target, 12, moment_scale)
            balance = [sum(channels[kind][name][axis] for kind in targets) for axis in range(6)]
            wrench_check(result, name + "/body-equilibrium", balance, [0] * 6, 12, moment_scale)
        paired = [sum(channels["CUT"][branch["cuts"][side]["object"]][axis] for side in ("Left", "Right")) for axis in range(6)]
        wrench_check(result, bay + "/paired-cut-sum", paired, [0] * 6, 12, moment_scale)
        a, b = (motion[branch["ports"][side]["object"]] for side in ("A", "B"))
        du = [two - one for one, two in zip(a["translation_mm"], b["translation_mm"])]
        dr = [two - one for one, two in zip(a["rotation_rad"], b["rotation_rad"])]
        vector_check(result, bay + "/differential-translation", du, [.01, 0, 0], .01, .05)
        vector_check(result, bay + "/differential-rotation", dr, [.001, 0, 0], .001, .05)
        vector_check(result, bay + "/local-generalized-force", [1200 * value for value in du], [12, 0, 0], 12, .01)
        vector_check(result, bay + "/local-generalized-couple", [6000 * value for value in dr], [6, 0, 0], 6, .01)
        vector_check(result, bay + "/explicit-local-X-torque", [6000 * dr[0], 0, 0], [6, 0, 0], 6, .01)
        work += 12 * a["translation_mm"][0] + 6 * a["rotation_rad"][0]
        energy += .5 * (1200 * sum(value * value for value in du) + 6000 * sum(value * value for value in dr))
    require(len(result) == 3566 and math.isfinite(work) and work > 0, "Wrong check cardinality/zero host work")
    return result, work, energy


def audit():
    pin(Path(__file__))
    witness, manifest, execution, identity = supervisor()
    require(witness.is_dir() and not witness.is_symlink(), "No fresh witness directory")
    receipt = load(witness / "witness-receipt.json")
    for key in ("passed", "only_public_native_interfaces", "no_deck_patches_or_mocks", "protected_inputs_unchanged"):
        require(receipt[key] is True, f"Witness did not establish {key}")
    require(receipt["engineering_project_accessed_or_solved"] is False
            and receipt["engineering_or_BIM_accepted"] is False, "Unexpected engineering acceptance claim")
    require(receipt["case"] == "capacity" and receipt["rows_y"] == 11 and receipt["columns_z"] == 12
            and receipt["phase"] == "normal-import-save-inprocess-reopen-complete", "Incomplete capacity witness")
    require(receipt["frozen_oracle_sha256"] == FROZEN and receipt["inputs_before"] == receipt["inputs_after"], "Witness input fence differs")
    for path, expected in receipt["inputs_before"].items():
        require(pin(path)["sha256"] == expected, f"Witness protected input differs: {path}")
    files = {str(path.relative_to(witness)): path for path in witness.rglob("*") if path.is_file()}
    require(not any(path.is_symlink() for path in witness.rglob("*")), "Symlink in fresh witness tree")
    require(set(files) - {"witness-receipt.json"} == set(receipt["retained_files"]), "Missing/extra retained native evidence")
    for relative, expected in receipt["retained_files"].items():
        require(pin(files[relative]) == expected, f"Retained evidence differs: {relative}")
    oracle_path = REPO / "src/Mod/Fem/femtest/data/calculix/coupled_port_capacity_oracle.json"
    oracle = load(oracle_path)
    for name, expected in FROZEN.items():
        require(pin(oracle_path.parent / name)["sha256"] == expected, "Frozen oracle/fixture digest differs")
    require(oracle["capacity_11_by_12"]["counts"] == {"PORT": 264, "SPC_SUPPORT": 1, "BODY": 264, "SPRING": 792, "ANGLE": 792}, "Frozen count contract differs")
    geometry, membership = load(witness / "geometry-contract.json"), load(witness / "mesh-membership.json")
    deck, request = Path(receipt["deck"]), Path(receipt["request"])
    require(deck == witness / "native/Mesh.inp" and request == deck.with_suffix(".accounting"), "Nonliteral native input path")
    require(receipt["original_native_input_sha256"] == {"deck": pin(deck)["sha256"], "request": pin(request)["sha256"]}, "Original input hash differs")
    asked, native = request_file(request), deck_file(deck)
    branches, coordinates, ports, applied = mesh_and_graph(geometry, membership, asked, native)
    export = load(witness / "independent-export-audit.json")
    require(export["passed"] is True and receipt["export_audit_sha256"] == pin(witness / "independent-export-audit.json")["sha256"],
            "Producer export audit hash differs")
    require(export["deck"] == {"path": str(deck), **pin(deck)}
            and export["request"] == {"path": str(request), **pin(request)}, "Producer export original input descriptors differ")
    support = next(iter(asked["supports"]))
    wire, dat, frd = (deck.with_suffix(suffix) for suffix in (".accounting.out", ".dat", ".frd"))
    channels = raw_channels(wire, support, set(asked["bodies"]))
    data = load(witness / "native-accounting-data.json")
    require(data["schema"] == "CCX_FORCE_ACCOUNTING_V3" and data["wrenches"] == channels, "Imported report does not equal original native channels")
    require(data["capacity"]["required"] == COUNTS and data["capacity"]["total"] == 2113
            and data["capacity"]["supported"]["total_records"] == 2113
            and data["capacity_applied"] == {"budget": 2113, "counts": COUNTS, "total": 2113}, "Accepted native capacity contract differs")
    echoes = re.findall(r"^CCX_FORCE_ACCOUNTING_CAPACITY_APPLIED_V1 (.+)$", text(witness / "native.stdout"), re.M)
    require(len(echoes) == 1, "Missing/repeated actual native applied-capacity echo")
    echo = json.loads(echoes[0], object_pairs_hook=unique_pairs)
    require(type(echo) is dict and set(echo) == {"budget", "counts", "total"}
            and type(echo["counts"]) is dict and set(echo["counts"]) == set(COUNTS)
            and all(type(value) is int for value in (echo["budget"], echo["total"], *echo["counts"].values()))
            and echo == data["capacity_applied"],
            "Actual native stdout applied-capacity echo differs")
    require(data["binary_sha256"] == receipt["actual_binary_sha256"] == BINARY
            and data["binary"] == receipt["actual_binary"] == manifest["candidate"]["path"]
            and receipt["solver_returncode"] == 0, "Actual native binary/process differs")
    require(data["deck_sha256"] == pin(deck)["sha256"] and data["request_sha256"] == pin(request)["sha256"]
            and data["output_sha256"] == pin(wire)["sha256"] and data["end_time"] == 1
            and re.fullmatch(r"[0-9a-f]{64}", data["model_digest"]), "Imported data provenance differs")
    require(exact_set([tuple(item) for item in data["expected"]], "expected accounting IDs")
            == {("SUPPORT", support)} | {("CUT", name) for name in asked["bodies"]}, "Imported expected IDs differ")
    source = data["movement_source"]
    require(source["schema"] == "FREECAD_MOVEMENT_SOURCE_V1" and source["status"] == "BOUND"
            and source["path"] == str(frd) and source["sha256"] == pin(frd)["sha256"]
            and source["deck"] == str(deck) and source["request"] == str(request)
            and source["deck_sha256"] == pin(deck)["sha256"] and source["request_sha256"] == pin(request)["sha256"]
            and source["binary"] == data["binary"] and source["binary_sha256"] == BINARY
            and source["model_digest"] == data["model_digest"] and source["requested_end_time"] == 1,
            "Original FRD movement custody differs")
    motion = original_dat(dat, ports)
    producer_motion = load(witness / "motion-from-original-dat.json")
    require(producer_motion["passed"] is True and set(producer_motion["ports"]) == set(motion), "Producer motion ID set differs")
    for name in motion:
        for key in ("translation_mm", "rotation_rad"):
            require(producer_motion["ports"][name][key] == motion[name][key], "Producer motion differs from original DAT")
    checks, work, energy = mathematics(branches, channels, motion, support, oracle)
    recorded = {}
    for row in receipt["checks"]:
        put(recorded, row["name"], row)
    require(set(recorded) == set(checks) and receipt["physical_check_count"] == 3566, "Missing/duplicate physical check IDs")
    for name, recomputed in checks.items():
        row = recorded[name]
        require(set(row) == set(recomputed), f"Check field set differs: {name}")
        for key in recomputed:
            if isinstance(recomputed[key], float):
                require(math.isclose(row[key], recomputed[key], rel_tol=2e-12, abs_tol=1e-15), f"Recorded check metric differs: {name}/{key}")
            else:
                require(row[key] == recomputed[key], f"Recorded check value differs: {name}/{key}")
    times, displacement = original_frd(frd)
    require(times == receipt["observed_FRD_displacement_times"], "Producer FRD actual times differ")
    proof, max_error = {}, 0.0
    for name, port in ports.items():
        translation, rotation = motion[name]["translation_mm"], motion[name]["rotation_rad"]
        errors, moving = [], False
        for node in membership["moving_face_nodes"][name]:
            require(node in displacement, "Original FRD misses finite receiving-face node")
            lever = [value - origin for value, origin in zip(coordinates[node], port["position"])]
            predicted = [value + turn for value, turn in zip(translation, cross(rotation, lever))]
            error = math.dist(displacement[node], predicted) / (math.hypot(*predicted) or .01)
            require(math.isfinite(error) and error <= .05, f"Physical FRD face kinematics failed: {name}/{node}")
            errors.append(error)
            moving |= math.hypot(*displacement[node]) > 0
        proof[name] = {"nodes": len(errors), "maximum_relative_kinematic_error": max(errors),
                       "finite_physical_face_has_nonzero_motion": moving}
        max_error = max(max_error, max(errors))
    producer_proof = load(witness / "physical-face-motion-proof.json")
    require(set(producer_proof) == set(proof), "Producer physical proof IDs differ")
    for name, values in proof.items():
        require(producer_proof[name]["nodes"] == values["nodes"]
                and producer_proof[name]["finite_physical_face_has_nonzero_motion"] == values["finite_physical_face_has_nonzero_motion"]
                and math.isclose(producer_proof[name]["maximum_relative_kinematic_error"], values["maximum_relative_kinematic_error"], rel_tol=1e-9, abs_tol=1e-13), "Producer FRD proof differs")
    require(any(proof[name]["finite_physical_face_has_nonzero_motion"] for name, port in ports.items() if port["side"] == "A")
            and all(proof[name]["finite_physical_face_has_nonzero_motion"] for name, port in ports.items() if port["side"] == "B"), "Finite moving host/branch proof failed")
    require(math.isclose(work, receipt["host_positive_generalized_load_work_N_mm"], rel_tol=2e-12, abs_tol=1e-15), "Recorded host work differs")
    refusal = receipt["one_below_capacity_refusal"]
    require(refusal["budget"] == 2112 and refusal["required"] == COUNTS and refusal["total"] == 2113
            and refusal["export_directory_untouched"] is True
            and refusal["selected_properties_and_public_mesh_membership_unchanged"] is True
            and refusal["no_FE_solve"] is True, "Early2112 refusal receipt incomplete")
    for kind, count in COUNTS.items():
        require(f"{kind} required {count}; supported 2112" in refusal["diagnostic"], "Early refusal diagnostic incomplete")
    require("total required 2113; supported 2112" in refusal["diagnostic"], "Total refusal diagnostic missing")
    require(receipt["cold_manifest"] == str(witness / "cold-case.json"), "Cold manifest is not the literal fresh witness path")
    cold = load(receipt["cold_manifest"])
    require(pin(receipt["cold_manifest"])["sha256"] == receipt["cold_manifest_sha256"], "Cold manifest binding differs")
    require(cold["document"] == str(witness / "coupled-native-current.FCStd"), "Saved document is not the literal fresh witness path")
    require(pin(cold["document"])["sha256"] == cold["document_sha256"], "Saved native document differs")
    require(cold["accounting_data_literal"] == text(witness / "native-accounting-data.json")
            and cold["movement_source_literal"] == source and cold["frozen_oracle_sha256"] == FROZEN
            and cold["explicit_supports"] == [support] and cold["saved_status_literal"].startswith("Current")
            and cold["no_history_or_provenance_repair"] is True, "Saved literal report/custody differs")
    for key, path in (("deck", deck), ("request", request), ("native_output", wire), ("dat", dat), ("frd", frd)):
        require(cold["source_files"][key] == {"path": str(path), "sha256": pin(path)["sha256"]}, "Saved literal source custody differs")
    reopen = receipt["in_process_historical_reopen"]
    require(reopen["passed"] is True and reopen["literal_accounting_unchanged"] is True
            and reopen["source_document_bytes_unchanged"] is True and reopen["separate_process_cold_claimed"] is False,
            "In-process reopen evidence differs")
    require(reopen["status"].startswith("Stale"), "Historical in-process reopen is not stale")
    require(receipt["current_native_report"]["schema"] == "CCX_FORCE_ACCOUNTING_V3"
            and receipt["current_native_report"]["status"].startswith("Current")
            and receipt["current_native_report"]["movement_status"] == "BOUND", "Current imported report status differs")
    for path, before in READS.copy().items():
        require(descriptor(path) == before, f"Final file fence changed: {path}")
    require({str(path.relative_to(witness)) for path in witness.rglob("*") if path.is_file()} == set(files)
            and not any(path.is_symlink() for path in witness.rglob("*")),
            "Fresh native evidence inventory changed during audit")
    return {
        "schema": "FreeCAD-3q7-fresh-capacity-independent-file-audit-v1", "passed": True,
        "fresh_run": str(RUN), "witness": str(witness), "source_test_id": TEST,
        "independence": {"method": "New stdlib-only file parsers and arithmetic; no product imports or native execution",
                         "author_of_product_fix": False, "author_of_frozen_oracle": False,
                         "author_of_physical_producer": False, "author_of_some_mutation_guards": True},
        "supervisor": {"two_tests_no_skips": True, "reaped_and_process_group_gone": True,
                       "unit_only": False, "runtime": identity["runtime"],
                       "app_profiles_and_critical_dependencies_unchanged": True,
                       "source_build_copy_parity": True, "all_input_and_evidence_end_fences": True},
        "native_binary_sha256": BINARY,
        "compilation_provenance": {"inherited_receipt": manifest["native_build_receipt"], "fresh_compilation_claimed": False},
        "physical_graph": {"branches": 132, "declarations": COUNTS, "total": 2113,
                           "physical_nodes": len(coordinates), "native_volume_elements": len(membership["volume_connectivity"]),
                           "solid_partitions": 397, "finite_solid_tetra_facet_connectivity_recomputed": True,
                           "cross_solid_shared_tetra_facet_joins_recomputed": 264,
                           "native_to_CalculiX_tetra_order_exact_including_all_midsides": True,
                           "complete_finite_exterior_support_receiving_and_loaded_face_sets_recomputed": True,
                           "native_element_node_port_angle_spring_body_support_identity_and_incidence_recomputed": True,
                           "branch_applied_original_origin_wrenches": applied},
        "acceptance": {"unique_recomputed_checks": len(checks), "limits_unchanged": True,
                       "force_and_original_origin_moment": .01, "differential_response": .05,
                       "local_generalized_force_and_couple": .01,
                       "all_recorded_actual_reference_norm_error_scale_limit_and_pass_fields_crosschecked": True,
                       "checks": list(checks.values())},
        "physical_motion": {"original_DAT_and_FRD_independently_parsed": True, "FRD_times": times,
                            "maximum_relative_finite_face_kinematic_error": max_error, "limit": .05,
                            "positive_host_work_N_mm": work, "observed_scalar_spring_energy_N_mm": energy,
                            "energy_is_diagnostic_not_new_acceptance": True, "ports": proof},
        "early_2112_refusal": {"same_run_producer_receipt_crosschecked": True,
                               "independent_no_solve_observation_claimed": False,
                               "diagnostic": refusal["diagnostic"]},
        "save_reopen": {"saved_file_and_literal_native_source_hashes_crosschecked": True,
                        "in_process_stale_receipt_crosschecked": True, "separate_process_cold_audited": False},
        "installation_performed": False, "engineering_project_accessed_or_solved": False,
        "engineering_or_BIM_accepted": False, "evidence_sha256_and_bytes": READS,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    require(not sys.flags.optimize, "Audit requires assertions enabled")
    require(args.report.is_absolute() and args.report.parent.resolve().is_relative_to(TASK.resolve()), "Report must be a private absolute path")
    require(not args.report.exists() and not args.report.resolve().is_relative_to(RUN.resolve()), "Report must be new and outside native evidence")
    report = audit()
    with args.report.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"passed": True, "report": str(args.report), "sha256": descriptor(args.report)["sha256"],
                      "recomputed_checks": report["acceptance"]["unique_recomputed_checks"]}, sort_keys=True))


if __name__ == "__main__":
    main()
