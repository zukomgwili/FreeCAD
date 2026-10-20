# SPDX-License-Identifier: LGPL-2.1-or-later
"""Independent, read-only parsing of the frozen coupled-port stock interfaces.

No FreeCAD, writer, native-extension or solver module is imported. Importing
defines functions only. These functions never write files or launch processes.
The accepted deck language is deliberately the small stock-fixture language;
an unsupported card is a setup/audit failure, never a truncated qualification.
"""

import hashlib
import math
import re
from pathlib import Path

NUMBER = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?")
INTEGER = re.compile(r"[+]?[0-9]+\Z")
GEOMETRY_TOLERANCE_MM = 1e-8
ALLOWED_CARDS = {
    "NODE",
    "ELEMENT",
    "NSET",
    "ELSET",
    "SURFACE",
    "PHYSICAL CONSTANTS",
    "MATERIAL",
    "ELASTIC",
    "EXPANSION",
    "DENSITY",
    "SOLID SECTION",
    "RIGID BODY",
    "ORIENTATION",
    "SPRING",
    "EQUATION",
    "BOUNDARY",
    "STEP",
    "STATIC",
    "SECTION PRINT",
    "CLOAD",
    "NODE FILE",
    "EL FILE",
    "NODE PRINT",
    "OUTPUT",
    "END STEP",
}


def need(condition, message):
    if not condition:
        raise AssertionError(message)


def read_bytes(path):
    path = Path(path)
    need(path.is_file() and not path.is_symlink(), f"Not a regular input: {path}")
    return path.read_bytes()


def descriptor(path, data=None):
    data = read_bytes(path) if data is None else data
    return {"path": str(Path(path)), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def real(token):
    value = float(token.replace("D", "E").replace("d", "e"))
    need(math.isfinite(value), f"Nonfinite native number: {token}")
    return value


def integer(token):
    need(INTEGER.fullmatch(str(token)) is not None, f"Not a positive native integer: {token}")
    value = int(token)
    need(value > 0, f"Nonpositive native identity/count: {token}")
    return value


def fields(line):
    return [item.strip() for item in line.split(",") if item.strip()]


def cards(text):
    result, active = [], None
    for line_number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("**"):
            continue
        if line.startswith("*"):
            parts = [part.strip() for part in line[1:].split(",")]
            kind, attributes, flags = parts[0].upper(), {}, set()
            need(kind in ALLOWED_CARDS, f"Unsupported fixture card {kind} at line {line_number}")
            for part in parts[1:]:
                if not part:
                    continue
                if "=" in part:
                    key, value = (item.strip().upper() for item in part.split("=", 1))
                    need(key not in attributes, f"Duplicate card attribute: {line}")
                    attributes[key] = value
                else:
                    flag = part.upper()
                    need(flag not in flags, f"Duplicate card flag: {line}")
                    flags.add(flag)
            active = {
                "kind": kind,
                "attributes": attributes,
                "flags": flags,
                "rows": [],
                "line": line_number,
            }
            result.append(active)
        else:
            need(active is not None, f"Data before first native card at line {line_number}")
            active["rows"].append(fields(line))
    return result


def unique(mapping, key, value, description):
    need(key not in mapping, f"Duplicate {description}: {key}")
    mapping[key] = value


def append_set(mapping, name, tokens):
    mapping.setdefault(name.upper(), []).extend(tokens)


def resolve_set(mapping, name, stack=()):
    name = name.upper()
    need(name in mapping and name not in stack, f"Missing/cyclic native set: {name}")
    result = []
    for token in mapping[name]:
        result.extend(
            [integer(token)]
            if INTEGER.fullmatch(token)
            else resolve_set(mapping, token, (*stack, name))
        )
    need(len(result) == len(set(result)), f"Duplicate native set members: {name}")
    return set(result)


def parse_deck(text):
    """Parse original cards, before any native MPC cascade or generated nodes."""
    source = cards(text)
    nodes, elements, nsets, elsets, orientations = {}, {}, {}, {}, {}
    rigid, springs, equations, boundaries, cloads, node_prints = [], [], [], [], [], set()
    materials, sections, current_material = {}, [], None
    for card in source:
        kind, attrs, flags, rows = (card[key] for key in ("kind", "attributes", "flags", "rows"))
        if kind == "NODE":
            need(not flags and set(attrs) <= {"NSET"}, "Unsupported NODE options")
            for row in rows:
                need(len(row) == 4, "NODE must contain original ID and three coordinates")
                node = integer(row[0])
                unique(nodes, node, [real(item) for item in row[1:]], "original node")
                if "NSET" in attrs:
                    append_set(nsets, attrs["NSET"], [row[0]])
        elif kind == "ELEMENT":
            need(
                not flags and set(attrs) <= {"TYPE", "ELSET"} and "TYPE" in attrs,
                "Unsupported ELEMENT options",
            )
            element_type = attrs["TYPE"]
            need(
                element_type in ("C3D4", "C3D10", "SPRING2"),
                f"Unexpected element type: {element_type}",
            )
            width = {"C3D4": 4, "C3D10": 10, "SPRING2": 2}[element_type]
            for row in rows:
                need(len(row) == width + 1, "Unexpected native connectivity/continuation layout")
                element, connectivity = integer(row[0]), tuple(integer(item) for item in row[1:])
                need(
                    len(connectivity) == len(set(connectivity)),
                    "Repeated node within native element",
                )
                unique(elements, element, {"type": element_type, "nodes": connectivity}, "element")
                if "ELSET" in attrs:
                    append_set(elsets, attrs["ELSET"], [row[0]])
        elif kind in ("NSET", "ELSET"):
            need(set(attrs) == {kind} and flags <= {"GENERATE"}, f"Unsupported {kind} options")
            tokens = []
            for row in rows:
                if "GENERATE" in flags:
                    need(len(row) in (2, 3), "Malformed generated set")
                    start, end = integer(row[0]), integer(row[1])
                    increment = integer(row[2]) if len(row) == 3 else 1
                    need(end >= start, "Descending generated set")
                    tokens.extend(str(value) for value in range(start, end + 1, increment))
                else:
                    tokens.extend(row)
            append_set(nsets if kind == "NSET" else elsets, attrs[kind], tokens)
        elif kind == "RIGID BODY":
            need(
                not flags and set(attrs) == {"NSET", "REF NODE", "ROT NODE"} and not rows,
                "Unexpected original RIGID BODY construction",
            )
            rigid.append(
                {
                    "set": attrs["NSET"],
                    "reference_node": integer(attrs["REF NODE"]),
                    "rotation_node": integer(attrs["ROT NODE"]),
                }
            )
        elif kind == "ORIENTATION":
            need(
                not flags and set(attrs) == {"NAME"} and len(rows) == 1 and len(rows[0]) == 6,
                "Unsupported orientation construction",
            )
            unique(orientations, attrs["NAME"], [real(item) for item in rows[0]], "orientation")
        elif kind == "SPRING":
            need(
                not flags and set(attrs) <= {"ELSET", "ORIENTATION"} and "ELSET" in attrs,
                "Nonlinear, transformed or otherwise unsupported scalar spring law",
            )
            need(
                len(rows) == 2 and len(rows[0]) == 2 and len(rows[1]) == 1,
                "Spring law is not a positive single-table linear scalar law",
            )
            directions = tuple(integer(item) for item in rows[0])
            stiffness = real(rows[1][0])
            need(
                directions[0] == directions[1] and directions[0] in (1, 2, 3) and stiffness > 0,
                "Nonmatching direction or nonpositive scalar spring stiffness",
            )
            springs.append(
                {
                    "set": attrs["ELSET"],
                    "orientation": attrs.get("ORIENTATION"),
                    "directions": directions,
                    "stiffness": stiffness,
                }
            )
        elif kind == "EQUATION":
            need(not attrs and not flags, "Unsupported EQUATION options")
            cursor = 0
            while cursor < len(rows):
                need(len(rows[cursor]) == 1, "Missing original equation term count")
                count, flat = integer(rows[cursor][0]), []
                cursor += 1
                while len(flat) < 3 * count:
                    need(cursor < len(rows), "Truncated original equation")
                    flat.extend(rows[cursor])
                    cursor += 1
                need(len(flat) == 3 * count, "Extra original equation terms")
                terms = [
                    (integer(flat[i]), integer(flat[i + 1]), real(flat[i + 2]))
                    for i in range(0, len(flat), 3)
                ]
                need(
                    all(direction in (1, 2, 3) for _, direction, _ in terms),
                    "Nontranslational equation DOF",
                )
                equations.append(terms)
        elif kind == "BOUNDARY":
            need(
                not attrs and not flags,
                "Amplitude/type/operation boundary is outside the frozen fixture",
            )
            for row in rows:
                need(2 <= len(row) <= 4, "Malformed native boundary")
                first = integer(row[1])
                last = integer(row[2]) if len(row) >= 3 else first
                value = real(row[3]) if len(row) == 4 else 0.0
                need(
                    1 <= first <= last <= 3 and value == 0.0,
                    "Nonzero or unsupported prescribed mode",
                )
                boundaries.append((row[0], first, last))
        elif kind == "CLOAD":
            need(not attrs and not flags, "Amplitude/operation concentrated load is not frozen")
            for row in rows:
                need(len(row) == 3, "Malformed concentrated load")
                node, direction, value = integer(row[0]), integer(row[1]), real(row[2])
                need(direction in (1, 2, 3), "Nontranslational physical concentrated load")
                cloads.append((node, direction, value))
        elif kind == "NODE PRINT":
            if any("U" in row for row in rows) and "NSET" in attrs:
                node_prints.add(attrs["NSET"])
        elif kind == "MATERIAL":
            need(
                not flags and set(attrs) == {"NAME"} and not rows,
                "Unexpected native material definition",
            )
            current_material = attrs["NAME"]
            unique(materials, current_material, {}, "native material")
        elif kind == "ELASTIC":
            need(
                current_material is not None
                and not attrs
                and not flags
                and len(rows) == 1
                and len(rows[0]) == 2,
                "Non-frozen native elastic law",
            )
            unique(
                materials[current_material],
                "elastic",
                [real(item) for item in rows[0]],
                "material elastic law",
            )
        elif kind == "SOLID SECTION":
            need(
                not flags and set(attrs) == {"ELSET", "MATERIAL"} and not rows,
                "Unexpected native solid section",
            )
            sections.append({"set": attrs["ELSET"], "material": attrs["MATERIAL"]})
    need(
        len([card for card in source if card["kind"] == "STEP"]) == 1
        and len([card for card in source if card["kind"] == "END STEP"]) == 1,
        "Expected exactly one native step",
    )
    step = next(card for card in source if card["kind"] == "STEP")
    need(
        not step["flags"] and set(step["attributes"]) <= {"INC"},
        "Nonlinear/perturbation step is not frozen",
    )
    static = [card for card in source if card["kind"] == "STATIC"]
    need(
        len(static) == 1
        and not static[0]["attributes"]
        and not static[0]["flags"]
        and len(static[0]["rows"]) == 1
        and len(static[0]["rows"][0]) >= 2
        and real(static[0]["rows"][0][1]) == 1.0,
        "Expected a static final time of exactly one",
    )
    start = source.index(step)
    end = next(index for index, card in enumerate(source) if card["kind"] == "END STEP")
    need(
        start < source.index(static[0]) < end == len(source) - 1,
        "Native step layout is not the frozen single static step",
    )
    need(
        all(
            (start < index < end) if card["kind"] == "CLOAD" else True
            for index, card in enumerate(source)
        ),
        "A physical load is outside the actual static step",
    )
    need(
        all(
            index < start
            for index, card in enumerate(source)
            if card["kind"] in {"NODE", "ELEMENT", "RIGID BODY", "SPRING", "EQUATION"}
        ),
        "Native physical/helper graph is not an original pre-step construction",
    )
    need(
        all(node in nodes for element in elements.values() for node in element["nodes"]),
        "Element references a missing original node",
    )
    return {
        "nodes": nodes,
        "elements": elements,
        "nsets": nsets,
        "elsets": elsets,
        "rigid": rigid,
        "springs": springs,
        "orientations": orientations,
        "equations": equations,
        "boundaries": boundaries,
        "cloads": cloads,
        "node_prints": node_prints,
        "materials": materials,
        "sections": sections,
    }


def parse_request(text):
    tokens, index = text.split(), 0

    def take():
        nonlocal index
        need(index < len(tokens), "Truncated accounting request")
        value = tokens[index]
        index += 1
        return value

    def identity_list(count):
        values = [integer(take()) for _ in range(count)]
        need(len(values) == len(set(values)), "Repeated identity in native request list")
        return set(values)

    need(take() == "CCX_FORCE_ACCOUNTING_V3", "Not a literal V3 accounting request")
    ports, angles, springs, bodies, supports = {}, {}, {}, {}, {}
    while True:
        kind = take()
        if kind == "END":
            need(index == len(tokens), "Trailing request tokens after END")
            break
        if kind == "PORT":
            name, reference, rotation = take(), integer(take()), integer(take())
            unique(ports, name, (reference, rotation), "requested PORT")
        elif kind == "ANGLE":
            auxiliary, rotation = integer(take()), integer(take())
            axis = tuple(real(take()) for _ in range(3))
            unique(angles, auxiliary, {"rotation_node": rotation, "axis": axis}, "requested ANGLE")
        elif kind == "SPRING":
            element, one, two = integer(take()), integer(take()), integer(take())
            unique(springs, element, (one, two), "requested SPRING")
        elif kind == "BODY":
            name, volumes, cuts = take(), integer(take()), integer(take())
            unique(
                bodies,
                name,
                {"elements": identity_list(volumes), "cut_nodes": identity_list(cuts)},
                "requested BODY",
            )
        elif kind == "SPC_SUPPORT":
            name, count = take(), integer(take())
            pairs = [(integer(take()), integer(take())) for _ in range(count)]
            need(
                len(pairs) == len(set(pairs))
                and all(direction in (1, 2, 3) for _, direction in pairs),
                "Repeated or invalid selected support node/DOF",
            )
            unique(supports, name, set(pairs), "requested SPC_SUPPORT")
        else:
            raise AssertionError(f"Unfrozen accounting declaration: {kind}")
    return {
        "ports": ports,
        "angles": angles,
        "springs": springs,
        "bodies": bodies,
        "supports": supports,
    }


def close_vector(actual, expected, tolerance, description):
    need(
        len(actual) == len(expected) and all(math.isfinite(value) for value in actual + expected),
        f"Nonfinite/invalid vector: {description}",
    )
    need(math.dist(actual, expected) <= tolerance, f"{description}: {actual} != {expected}")


def norm_check(actual, expected, description):
    scale = math.hypot(*expected)
    need(scale > 0, "The declared nonzero load reference vanished")
    error = math.dist(actual, expected) / scale
    need(
        math.isfinite(error) and error <= 0.01,
        f"Frozen 1% physical load check failed: {description}",
    )
    return {
        "name": description,
        "actual": actual,
        "reference": expected,
        "relative_error": error,
        "limit": 0.01,
        "passed": True,
    }


def audit_export(fixture, deck, request, output):
    """Return export proof; output is a literal future native-output descriptor.

    No files are written, no output is read, and no preflight/solver is invoked.
    Exact identities/incidence are separate from fixed physical 1% load checks.
    """
    deck, request, output = Path(deck), Path(request), Path(output)
    need(
        output == deck.with_suffix(".accounting.out"),
        "Native output literal does not match the stock deck basename",
    )
    deck_bytes, request_bytes = read_bytes(deck), read_bytes(request)
    native, asked = parse_deck(deck_bytes.decode()), parse_request(request_bytes.decode())
    membership = fixture.membership
    need(isinstance(membership, dict), "Independent physical mesh membership is required")
    coordinates = {int(node): list(point) for node, point in membership["nodes"].items()}
    connectivity = {
        int(element): tuple(nodes) for element, nodes in membership["volume_connectivity"].items()
    }
    physical_nodes, physical_elements = set(coordinates), set(connectivity)
    actual_volumes = {
        element: value
        for element, value in native["elements"].items()
        if value["type"] != "SPRING2"
    }
    need(
        set(actual_volumes) == physical_elements,
        "Original deck volume element identities differ from physical mesh",
    )
    material_name = fixture.material.Name.upper()
    need(
        native["materials"] == {material_name: {"elastic": [20000.0, 0.3]}},
        "Frozen positive finite elastic backbone/branch material differs",
    )
    assigned = set()
    for section in native["sections"]:
        need(section["material"] == material_name, "Physical solid uses an undeclared material")
        members = resolve_set(native["elsets"], section["set"])
        need(
            members <= physical_elements and not members.intersection(assigned),
            "Physical solid section assignment overlaps or includes helper elements",
        )
        assigned.update(members)
    need(
        assigned == physical_elements,
        "A physical volume lacks exactly one finite material assignment",
    )
    for element, expected in connectivity.items():
        # The public mesh exporter may reorder tetra corner/midside positions.
        actual = actual_volumes[element]["nodes"]
        need(
            len(actual) == len(expected) and set(actual) == set(expected),
            "Original volume-node incidence changed",
        )
    for node, point in coordinates.items():
        need(node in native["nodes"], "Original physical mesh node is missing")
        close_vector(
            native["nodes"][node],
            point,
            GEOMETRY_TOLERANCE_MM,
            "Original physical node coordinates",
        )
    branches = fixture.branches
    count = len(branches)
    need(count in (1, 132), "Only the frozen tracer/capacity graph is admitted")
    expected_ports = {branch["ports"][side].Name for branch in branches for side in ("A", "B")}
    expected_bodies = {
        branch["cuts"][side].Name for branch in branches for side in ("Left", "Right")
    }
    need(
        len(expected_ports) == 2 * count and set(asked["ports"]) == expected_ports,
        "PORT declarations differ",
    )
    need(
        len(expected_bodies) == 2 * count and set(asked["bodies"]) == expected_bodies,
        "BODY declarations differ",
    )
    rigid = {}
    for item in native["rigid"]:
        unique(rigid, item["set"], item, "actual original RIGID BODY receiving set")
    need(set(rigid) == {name.upper() for name in expected_ports}, "Actual RIGID BODY graph differs")
    rbe_ids, detached, reference_pairs, rotation_pairs = {}, set(), {}, {}
    body_proof = []
    for branch in branches:
        bay = branch["name"]
        for side, x in (("A", 10), ("B", 20)):
            name = branch["ports"][side].Name
            reference, rotation = asked["ports"][name]
            need(
                reference != rotation
                and not {reference, rotation}.intersection(physical_nodes | detached),
                "RBE reference/rotation identities overlap physical or another detached port",
            )
            detached.update((reference, rotation))
            actual = rigid[name.upper()]
            need(
                (actual["reference_node"], actual["rotation_node"]) == (reference, rotation),
                "PORT does not bind original native RIGID identities",
            )
            face_nodes = set(membership["moving_face_nodes"][name])
            need(
                resolve_set(native["nsets"], actual["set"]) == face_nodes,
                "Original finite RBE receiving nodes differ",
            )
            position = [x, branch["y"], branch["z"]]
            for node in (reference, rotation):
                need(node in native["nodes"], "Declared RBE node is absent from original deck")
                close_vector(
                    native["nodes"][node], position, GEOMETRY_TOLERANCE_MM, "Original RBE centroid"
                )
            reference_set, rotation_set = name + "_RefNode", name + "_RotNode"
            for set_name, node in ((reference_set, reference), (rotation_set, rotation)):
                need(
                    resolve_set(native["nsets"], set_name) == {node}
                    and set_name.upper() in native["node_prints"],
                    "Original RBE identity/motion-print set is missing or rebound",
                )
            rbe_ids[name] = {
                "reference_node": reference,
                "rotation_node": rotation,
                "reference_set": reference_set,
                "rotation_set": rotation_set,
                "branch": bay,
                "side": side,
                "position_mm": position,
            }
        a, b = (rbe_ids[branch["ports"][side].Name] for side in ("A", "B"))
        unique(reference_pairs, (a["reference_node"], b["reference_node"]), bay, "reference pair")
        unique(rotation_pairs, (a["rotation_node"], b["rotation_node"]), bay, "rotation pair")
        for side, role in (("Left", "B_left"), ("Right", "B_right")):
            name = branch["cuts"][side].Name
            volumes = set(membership["cell_volume_elements"][branch["solids"][role]])
            cut_nodes = set(membership["paired_cut_nodes"][bay])
            need(
                asked["bodies"][name] == {"elements": volumes, "cut_nodes": cut_nodes},
                f"{bay}/{side}: native BODY ownership/cut-node identities differ",
            )
            body_proof.append(
                {
                    "name": name,
                    "branch": bay,
                    "side": side,
                    "volume_elements": sorted(volumes),
                    "cut_nodes": sorted(cut_nodes),
                }
            )
    need(
        len(asked["angles"]) == 6 * count
        and not set(asked["angles"]).intersection(physical_nodes | detached),
        "ANGLE count or detached auxiliary identities differ",
    )
    need(
        set(native["nodes"]) == physical_nodes | detached | set(asked["angles"]),
        "Unaccounted original native node/helper",
    )
    equations = {}
    for terms in native["equations"]:
        need(
            len(terms) == 2 and terms[0][1] == 1 and terms[0][2] != 0,
            "Original angular equation is not a two-term auxiliary dependent equation",
        )
        unique(equations, terms[0][0], terms, "original angular dependent node")
    need(
        set(equations) == set(asked["angles"]),
        "Actual original equations and ANGLE declarations differ",
    )
    angle_proof = {}
    rotation_nodes = {value["rotation_node"] for value in rbe_ids.values()}
    axes = {(1.0, 0.0, 0.0): 1, (0.0, 1.0, 0.0): 2, (0.0, 0.0, 1.0): 3}
    for auxiliary, declaration in asked["angles"].items():
        need(
            auxiliary in native["nodes"]
            and declaration["axis"] in axes
            and declaration["rotation_node"] in rotation_nodes,
            "Unexpected ANGLE identity/global axis",
        )
        axis = axes[declaration["axis"]]
        terms = equations[auxiliary]
        need(
            terms[1][:2] == (declaration["rotation_node"], axis)
            and math.isclose(terms[1][2] / terms[0][2], -1.0, rel_tol=0, abs_tol=1e-12),
            "ANGLE does not equal the declared original native rotation-axis equation",
        )
        angle_proof[auxiliary] = {
            "rotation_node": declaration["rotation_node"],
            "axis": axis,
            "original_equation": [list(term) for term in terms],
        }
    actual_springs = {
        element: item for element, item in native["elements"].items() if item["type"] == "SPRING2"
    }
    need(
        len(actual_springs) == 6 * count and set(actual_springs) == set(asked["springs"]),
        "Actual native SPRING2 and request element IDs/counts differ",
    )
    laws = {}
    for law in native["springs"]:
        for element in resolve_set(native["elsets"], law["set"]):
            need(element in actual_springs, "Scalar spring law includes an unapproved element")
            unique(laws, element, law, "native scalar spring law assignment")
    need(set(laws) == set(actual_springs), "An actual scalar spring has no single native law")
    used_angles, incidence, seen_modes = set(), [], set()
    for element in sorted(actual_springs):
        endpoints = actual_springs[element]["nodes"]
        need(
            asked["springs"][element] == endpoints,
            "Requested SPRING connectivity differs from original native element",
        )
        law = laws[element]
        if endpoints in reference_pairs:
            bay, kind, axis = reference_pairs[endpoints], "Translational", law["directions"][0]
            need(
                law["stiffness"] == 1200.0 and law["orientation"] in native["orientations"],
                "Wrong positive translational law/orientation",
            )
            close_vector(
                native["orientations"][law["orientation"]],
                [1, 0, 0, 0, 1, 0],
                1e-12,
                "Global spring orientation",
            )
        else:
            need(
                all(node in angle_proof for node in endpoints),
                "Cross-bay, reversed or mixed scalar endpoints",
            )
            one, two = (angle_proof[node] for node in endpoints)
            pair = (one["rotation_node"], two["rotation_node"])
            need(
                pair in rotation_pairs and one["axis"] == two["axis"],
                "Cross-bay or mismatched-axis angular scalar endpoints",
            )
            bay, kind, axis = rotation_pairs[pair], "Rotational", one["axis"]
            need(
                law["stiffness"] == 6000.0
                and law["orientation"] is None
                and law["directions"] == (1, 1),
                "Wrong positive untransformed angular spring law",
            )
            need(
                not used_angles.intersection(endpoints),
                "Angular endpoint is reused by multiple springs",
            )
            used_angles.update(endpoints)
        mode = (bay, kind, axis)
        need(mode not in seen_modes, "Duplicate scalar branch/mode incidence")
        seen_modes.add(mode)
        incidence.append(
            {
                "element": element,
                "branch": bay,
                "kind": kind,
                "axis": axis,
                "endpoints": list(endpoints),
                "stiffness": law["stiffness"],
                "law_elset": law["set"],
            }
        )
    need(
        used_angles == set(asked["angles"])
        and seen_modes
        == {
            (branch["name"], kind, axis)
            for branch in branches
            for kind in ("Translational", "Rotational")
            for axis in (1, 2, 3)
        },
        "Missing/orphaned declared branch/axis/angle",
    )
    actual_boundaries = set()
    for token, first, last in native["boundaries"]:
        nodes = (
            {integer(token)} if INTEGER.fullmatch(token) else resolve_set(native["nsets"], token)
        )
        for node in nodes:
            need(node in native["nodes"], "Boundary references a missing original node")
            for direction in range(first, last + 1):
                need(
                    (node, direction) not in actual_boundaries,
                    "Duplicate original prescribed node/DOF",
                )
                actual_boundaries.add((node, direction))
    physical_support = {tuple(pair) for pair in membership["physical_fixed_node_DOF_pairs"]}
    need(
        set(asked["supports"]) == {fixture.fixed.Name}
        and asked["supports"][fixture.fixed.Name] == physical_support,
        "Selected physical SPC_SUPPORT is not the exact once-only ordinary Fixed face",
    )
    angular_restraints = {(node, direction) for node in asked["angles"] for direction in (2, 3)}
    need(
        actual_boundaries == physical_support | angular_restraints
        and not any(node in detached for node, _ in actual_boundaries),
        "Actual physical boundaries differ or moving RBE references are prescribed",
    )
    end_nodes, node_bay = {}, {}
    for branch in branches:
        bay = branch["name"]
        end_nodes[bay] = set(membership["end_loaded_nodes"][bay])
        for node in end_nodes[bay]:
            unique(node_bay, node, bay, "physical loaded-end ownership")
    contributions = {branch["name"]: [] for branch in branches}
    for node, direction, value in native["cloads"]:
        need(node in native["nodes"], "Physical CLOAD references an absent original node")
        if value:
            need(
                node in node_bay and node in physical_nodes,
                "Nonzero load is not on a B-right external end",
            )
            contributions[node_bay[node]].append((node, direction, value))
    checks, branch_loads, total = [], {}, [0.0] * 6
    by_name = {branch["name"]: branch for branch in branches}
    for bay, entries in contributions.items():
        branch, wrench, plus, minus = by_name[bay], [0.0] * 6, 0.0, 0.0
        need(entries, f"Branch end load is missing: {bay}")
        for node, direction, value in entries:
            x, y, z = native["nodes"][node]
            need(
                abs(x - 30) <= GEOMETRY_TOLERANCE_MM, "Load is not on the frozen external end plane"
            )
            force = [0.0, 0.0, 0.0]
            force[direction - 1] = value
            need(direction in (1, 3), "Unfrozen transverse physical end load")
            if direction == 3:
                if abs(y - (branch["y"] + 1)) <= GEOMETRY_TOLERANCE_MM:
                    plus += value
                else:
                    need(
                        abs(y - (branch["y"] - 1)) <= GEOMETRY_TOLERANCE_MM,
                        "Torque load is not on either declared end edge",
                    )
                    minus += value
            moment = [
                y * force[2] - z * force[1],
                z * force[0] - x * force[2],
                x * force[1] - y * force[0],
            ]
            for index, value_i in enumerate(force + moment):
                wrench[index] += value_i
        expected = [12, 0, 0, 6, 12 * branch["z"], -12 * branch["y"]]
        checks.append(norm_check(wrench[:3], expected[:3], bay + "/applied force"))
        checks.append(norm_check(wrench[3:], expected[3:], bay + "/applied original-origin moment"))
        need(
            abs(plus - 3) / 3 <= 0.01 and abs(minus + 3) / 3 <= 0.01,
            "Physical end edge loads are not the frozen +/-3N pair",
        )
        branch_loads[bay] = {
            "actual": wrench,
            "reference": expected,
            "positive_edge_Z_N": plus,
            "negative_edge_Z_N": minus,
            "nonzero_CLOAD_entries": len(entries),
        }
        total = [one + two for one, two in zip(total, wrench)]
    expected_total = [
        12 * count,
        0,
        0,
        6 * count,
        sum(12 * branch["z"] for branch in branches),
        -sum(12 * branch["y"] for branch in branches),
    ]
    checks.append(norm_check(total[:3], expected_total[:3], "whole applied force"))
    checks.append(norm_check(total[3:], expected_total[3:], "whole applied original-origin moment"))
    need(
        read_bytes(deck) == deck_bytes and read_bytes(request) == request_bytes,
        "Native original inputs changed during independent export audit",
    )
    return {
        "schema": "FreeCAD-native-coupled-port-independent-stock-export-audit-v1",
        "passed": True,
        "deck": descriptor(deck, deck_bytes),
        "request": descriptor(request, request_bytes),
        "native_output_literal": str(output),
        "native_output_read_or_solver_run": False,
        "counts": {
            "PORT": len(rbe_ids),
            "BODY": len(body_proof),
            "SPRING": len(incidence),
            "ANGLE": len(angle_proof),
            "SPC_SUPPORT": len(asked["supports"]),
        },
        "physical_volume_elements": len(physical_elements),
        "physical_nodes": len(physical_nodes),
        "volume_node_incidence_exact_native_tetra_ordering_not_assumed": True,
        "original_physical_coordinate_tolerance_mm": GEOMETRY_TOLERANCE_MM,
        "rbe_ids": rbe_ids,
        "body_ownership": body_proof,
        "scalar_incidence": incidence,
        "original_angular_equations": {str(node): value for node, value in angle_proof.items()},
        "physical_support_node_DOF_pairs": [list(pair) for pair in sorted(physical_support)],
        "angular_unused_DOF_restraints_excluded_from_physical_support": len(angular_restraints),
        "all_reference_modes_unprescribed": True,
        "all_declarations_and_actual_elements_once_only": True,
        "branch_applied_load_ledger": branch_loads,
        "whole_applied_wrench": total,
        "whole_applied_reference": expected_total,
        "physical_load_checks": checks,
        "no_SPRING_extra_channel_is_computed_by_this_input_audit": True,
        "only_original_public_stock_inputs_parsed": True,
        "engineering_project_accessed_or_solved": False,
        "engineering_or_BIM_accepted": False,
    }


def parse_port_motion(dat, rbe_ids):
    """Read final-time original RefNode/RotNode U from stock public DAT sets.

    Connector RF rows are deliberately ignored: they are not isolated spring
    forces, and angular dummy coordinates never locate a force/couple. The
    caller evaluates the frozen positive scalar laws from these original U's.
    """
    raw = read_bytes(dat)
    lines = raw.decode().splitlines()
    header = re.compile(
        r"^\s*displacements\s+\(vx,vy,vz\)\s+for set\s+(\S+)\s+and time\s+(\S+)\s*$", re.I
    )
    expected, records = {}, {}
    for name, identity in rbe_ids.items():
        for role, key in (("translation_mm", "reference"), ("rotation_rad", "rotation")):
            set_name = identity[key + "_set"].upper()
            unique(
                expected,
                set_name,
                (name, role, identity[key + "_node"]),
                "expected original DAT set",
            )
    for index, line in enumerate(lines):
        match = header.match(line)
        if not match or match[1].upper() not in expected:
            continue
        set_name, time = match[1].upper(), real(match[2])
        need(0 <= time <= 1.0 + 1e-12, "Unexpected port-motion output time")
        if not math.isclose(time, 1.0, rel_tol=0, abs_tol=1e-12):
            continue
        cursor = index + 1
        while cursor < len(lines) and not lines[cursor].strip():
            cursor += 1
        rows = []
        while cursor < len(lines) and lines[cursor].strip():
            row = lines[cursor]
            tokens = NUMBER.findall(row)
            need(
                not NUMBER.sub("", row).strip() and len(tokens) == 4,
                "Malformed original port DAT displacement row",
            )
            rows.append((integer(tokens[0]), [real(token) for token in tokens[1:]]))
            cursor += 1
        need(
            len(rows) == 1 and rows[0][0] == expected[set_name][2],
            "DAT set does not contain its exact original native port ID",
        )
        unique(records, set_name, rows[0][1], "final-time original DAT displacement set")
    need(
        set(records) == set(expected),
        "Missing final-time original RefNode/RotNode displacement set",
    )
    ports = {}
    for name, identity in rbe_ids.items():
        ports[name] = {
            "reference_node": identity["reference_node"],
            "rotation_node": identity["rotation_node"],
            "translation_mm": records[identity["reference_set"].upper()],
            "rotation_rad": records[identity["rotation_set"].upper()],
            "source_sets": [identity["reference_set"], identity["rotation_set"]],
        }
    need(read_bytes(dat) == raw, "Original DAT changed during independent motion parsing")
    return {
        "schema": "FreeCAD-native-coupled-port-independent-original-port-motion-v1",
        "passed": True,
        "source": descriptor(dat, raw),
        "time": 1.0,
        "ports": ports,
        "original_node_IDs_checked": True,
        "no_RF_SOF_CF_or_fitted_motion": True,
    }
