# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native beam-to-solid scalar coupling admission and owned wire validation.

The rigid body receives only genuine tetrahedral nodes. Its detached reference
receives one translational scalar spring; no beam node becomes an RBE member.
This domain does not establish a six-component beam/solid joint law.
"""

import math

import FreeCAD as App

from femmesh import meshtools
from femtools import beam_coupling
from femtools.elastic_connector import PortResolutionContext
from femtools.elastic_connector import resolve_connector
from femtools.membertools import AnalysisMember
from femtools.membertools import get_member

SCHEMA = "CCX_BEAM_SECTION_V3"
ATTACHMENT = "Vertex to rigid body port"


def requested(analysis):
    return any(
        obj.Attachment == ATTACHMENT
        for obj in get_member(analysis, "Fem::ConstraintElasticConnector")
    )


def admitted(analysis, solver, mesh):
    """A narrow opt-in, never a general mixed-mesh preflight waiver."""
    if not requested(analysis):
        return False
    if not solver.BeamSectionForces:
        raise ValueError(
            "Beam-to-solid scalar coupling requires qualified BeamSectionForces output"
        )
    from femtools.beam_section_forces import preflight

    preflight(analysis, solver, mesh)
    return True


def plan(analysis, solver, mesh):
    members = AnalysisMember(analysis)
    allowed = {
        "cons_force",
        "cons_displacement",
        "cons_fixed",
        "cons_rigidbody",
        "cons_rigidbody_step",
        "cons_elasticconnector",
    }
    if any(
        value
        for key, value in vars(members).items()
        if key.startswith("cons_") and key not in allowed
    ):
        raise ValueError("Beam-to-solid output does not support other constraints, cuts or contact")
    if (
        len(members.cons_force) != 1
        or len(members.cons_displacement) != 1
        or len(members.cons_fixed) != 1
        or len(members.cons_rigidbody) != 1
        or len(members.cons_elasticconnector) != 1
        or len(members.geos_beamsection) != 1
        or members.geos_beamrotation
        or members.geos_shellthickness
        or len(members.mats_linear) != 1
        or members.mats_nonlinear
    ):
        raise ValueError(
            "Beam-to-solid output requires one beam chain, material, scalar connector, RBE, guide, solid support and source"
        )
    force = members.cons_force[0]["Object"]
    guide = members.cons_displacement[0]["Object"]
    fixed = members.cons_fixed[0]["Object"]
    rbe = members.cons_rigidbody[0]["Object"]
    connector = members.cons_elasticconnector[0]["Object"]
    if any(
        obj not in (force, guide, fixed, rbe) for obj in get_member(analysis, "Fem::Constraint")
    ):
        raise ValueError("Unexpected native constraint in beam-to-solid output")
    if (
        connector.Attachment != ATTACHMENT
        or connector.Mode != "Two points"
        or connector.Kind != "Translational"
        or connector.RigidBody2 != rbe
    ):
        raise ValueError("Select the explicit beam vertex to rigid-body reference scalar connector")
    if list(solver.NativeAccountingSupports):
        raise ValueError(
            "Beam-to-solid output owns a complete support catalogue; clear NativeAccountingSupports"
        )
    if any(getattr(obj, "EnableAmplitude", False) for obj in (force, guide, rbe)):
        raise ValueError("Beam-to-solid output does not support amplitudes")
    if any(
        getattr(rbe, kind + "Mode" + axis) != "Free"
        for kind in ("Translational", "Rotational")
        for axis in "XYZ"
    ):
        raise ValueError("The solid RBE must be a moving internal port with all six modes free")
    native = mesh.FemMesh
    if not native.Volumes or not native.EdgesOnly or native.FacesOnly:
        raise ValueError(
            "Beam-to-solid output requires standalone B32R edges and Tet4 volumes, without shells"
        )
    volumes, solid_nodes = [], set()
    for element in native.Volumes:
        nodes = list(native.getElementNodes(element))
        if len(nodes) != 4 or len(set(nodes)) != 4:
            raise ValueError("Beam-to-solid output currently qualifies C3D4 tetrahedra only")
        # FemMesh's Tet4 ordering differs from its native ABAQUS writer.
        # Bind the emitted CalculiX order, not the SMESH storage order.
        volumes.append({"element": element, "nodes": [nodes[1], nodes[0], nodes[2], nodes[3]]})
        solid_nodes.update(nodes)
    coordinates = native.Nodes
    if not all(math.isfinite(value) for point in coordinates.values() for value in point):
        raise ValueError("Beam-to-solid mesh coordinates must be finite")
    graph, midsides, beam_nodes = {}, set(), set()
    for element in native.EdgesOnly:
        nodes = list(native.getElementNodes(element))
        if len(nodes) != 3 or len(set(nodes)) != 3:
            raise ValueError("Beam-to-solid output requires three distinct B32R nodes")
        first, last, middle = nodes
        if middle in midsides:
            raise ValueError("A beam midside node cannot belong to multiple elements")
        midsides.add(middle)
        graph.setdefault(first, []).append(last)
        graph.setdefault(last, []).append(first)
        beam_nodes.update(nodes)
        length = (coordinates[last] - coordinates[first]).Length
        if (
            length <= 0
            or (coordinates[middle] - (coordinates[first] + coordinates[last]) * 0.5).Length
            > 1e-10 * length
        ):
            raise ValueError("Beam-to-solid output requires straight quadratic beam segments")
    if (
        beam_nodes & solid_nodes
        or set(coordinates) != beam_nodes | solid_nodes
        or midsides & set(graph)
    ):
        raise ValueError("Beam and solid native node ownership must be complete and disjoint")
    context = PortResolutionContext(mesh, analysis)
    resolved = resolve_connector(connector, mesh, analysis, context)
    context.validate_unchanged()
    if (
        not resolved.get("hybrid")
        or resolved["rotation"].Angle > 1e-12
        or connector.OrientationReference
    ):
        raise ValueError(
            "Beam-to-solid output requires a translational connector in a global frame"
        )
    port = resolved["port"]
    root, tip = resolved["nodes"][0], beam_coupling._vertex(force, mesh)
    direction = resolved["dof"]
    if beam_coupling._vertex(guide, mesh) != root:
        raise ValueError("The beam guide must act at its spring endpoint")
    endpoints = {node for node, neighbours in graph.items() if len(neighbours) == 1}
    if endpoints != {root, tip} or any(len(neighbours) > 2 for neighbours in graph.values()):
        raise ValueError("Beam-to-solid output requires one unbranched beam chain")
    span = coordinates[tip] - coordinates[root]
    components = [0.0, 0.0, 0.0]
    components[direction - 1] = 1.0
    axis = App.Vector(*components)
    if span.Length <= 0 or span.cross(axis).Length > 1e-10 * span.Length:
        raise ValueError("The beam and scalar connector must share one global axis")
    previous, current, visited = None, root, {root}
    while current != tip:
        following = next(node for node in graph[current] if node != previous)
        if following in visited or (coordinates[following] - coordinates[current]).dot(span) <= 0:
            raise ValueError("Overlapping, reversed or disconnected beam paths are unsupported")
        visited.add(following)
        previous, current = current, following
    if visited != set(graph) or any(
        (coordinates[node] - coordinates[root]).cross(axis).Length > 1e-10 * span.Length
        for node in beam_nodes
    ):
        raise ValueError("The beam catalogue is not one connected straight chain")
    if (rbe.ReferenceNode - coordinates[root]).cross(axis).Length > 1e-10 * max(1.0, span.Length):
        raise ValueError("A scalar connector cannot supply an unmodelled transverse offset moment")
    directions = []
    for index, letter in enumerate("xyz", 1):
        if (
            getattr(guide, letter + "Free") != (index == direction)
            or getattr(guide, letter + "Displacement").Value != 0
        ):
            raise ValueError("The beam guide must leave only the scalar spring direction free")
        if index != direction:
            directions.append(index)
        if (
            getattr(guide, "rot" + letter + "Free")
            or getattr(guide, letter + "Rotation").Value != 0
        ):
            raise ValueError("The beam guide must prescribe three zero rotations")
    directions.extend((4, 5, 6))
    support_nodes = sorted(meshtools._get_mesh_region_by_owned_references(native, fixed, mesh)[0])
    if (
        not support_nodes
        or not set(support_nodes).issubset(solid_nodes)
        or set(support_nodes) & set(port["nodes"])
    ):
        raise ValueError(
            "The physical solid support must be separate from the moving RBE receiving region"
        )
    owners = {owner for owner, names in rbe.References}
    if len(owners) != 1:
        raise ValueError("One explicit solid owner is required for the RBE receiving region")
    owner = next(iter(owners))
    if (
        owner.Document != analysis.Document
        or len(owner.Shape.Solids) != 1
        or not owner.Shape.isValid()
        or len(mesh.Shape.Shape.Solids) != 1
        or any(not owner.Shape.isInside(coordinates[node], 1e-7, True) for node in solid_nodes)
    ):
        raise ValueError("All tetrahedral nodes must belong to the one genuine solid specimen")
    return {
        "schema": SCHEMA,
        "source": {"owner": force.Name, "node": tip, "position": list(coordinates[tip])},
        "support": {
            "owner": guide.Name,
            "node": root,
            "directions": directions,
            "position": list(coordinates[root]),
        },
        "solid_support": {"owner": fixed.Name, "nodes": support_nodes},
        "spring": {
            "owner": connector.Name,
            "nodes": list(resolved["nodes"]),
            "direction": direction,
            "stiffness_N_per_mm": resolved["stiffness"],
        },
        "port": {**port, "position": list(rbe.ReferenceNode)},
        "solid_owner": owner.Name,
        "solid_elements": sorted(volumes, key=lambda row: row["element"]),
        "solid_nodes": sorted(solid_nodes),
        "beam_nodes": sorted(beam_nodes),
        "nodes": [
            {"node": node, "position": list(coordinates[node])} for node in sorted(coordinates)
        ],
    }


def _blocks(literal):
    blocks, mode, options, rows = [], "", {}, []
    for raw in literal.splitlines():
        line = raw.strip()
        if not line or line.startswith("**"):
            continue
        if line.startswith("*"):
            if mode:
                blocks.append((mode, options, rows))
            tokens = [value.strip().upper() for value in line.split(",")]
            mode, options, rows = tokens[0], {}, []
            for token in tokens[1:]:
                key, sep, value = token.partition("=")
                options[key.strip()] = value.strip() if sep else True
        else:
            rows.append([value.strip() for value in line.split(",") if value.strip()])
    if mode:
        blocks.append((mode, options, rows))
    return blocks


def catalogue(writer, literal, expected):
    """Bind every source, restraint, connector and true-solid element to stock input."""
    springs = list(getattr(writer, "native_accounting_springs", ()))
    if len(springs) != 1:
        raise ValueError("Native hybrid connector catalogue is incomplete")
    row = springs[0]
    if (
        not row.get("hybrid")
        or row["name"] != expected["spring"]["owner"]
        or row["kind"] != "SPRING2"
        or list(row["nodes"]) != expected["spring"]["nodes"]
        or row["angles"]
        or row.get("port")
        != {key: expected["port"][key] for key in ("name", "reference", "rotation", "nodes")}
    ):
        raise ValueError("The stock hybrid connector differs from its resolved endpoint catalogue")
    result = {**expected, "spring": {**expected["spring"], "element": row["element"]}}
    blocks = _blocks(literal)
    nodes, sets, actual_solids, boundaries, loads = {}, {}, {}, {}, [0.0, 0.0, 0.0]
    forbidden = {
        "*DLOAD",
        "*DSLOAD",
        "*TEMPERATURE",
        "*INITIAL CONDITIONS",
        "*AMPLITUDE",
        "*TRANSFORM",
        "*EQUATION",
        "*TIE",
        "*CONTACT PAIR",
    }
    for mode, options, rows in blocks:
        if mode in forbidden:
            raise ValueError("Unsupported load/equation/contact in the hybrid beam input")
        if mode == "*NODE":
            for values in rows:
                node = int(values[0])
                if node in nodes or len(values) != 4:
                    raise ValueError("Repeated or malformed native hybrid node")
                nodes[node] = list(map(float, values[1:]))
        elif mode == "*NSET":
            target = sets.setdefault(options["NSET"], [])
            for values in rows:
                if options.get("GENERATE"):
                    start, stop, stride = map(int, values)
                    if (
                        stride <= 0
                        or stop < start
                        or len(range(start, stop + 1, stride)) > len(nodes)
                    ):
                        raise ValueError("Invalid generated hybrid node set")
                    target.extend(range(start, stop + 1, stride))
                else:
                    target.extend(
                        int(value) if value.isdecimal() else value.upper() for value in values
                    )
        elif mode == "*ELEMENT" and options.get("TYPE") == "C3D4":
            for values in rows:
                element = int(values[0])
                if len(values) != 5 or element in actual_solids:
                    raise ValueError("Malformed or repeated native tetrahedron")
                actual_solids[element] = list(map(int, values[1:]))
        elif mode == "*CLOAD":
            if options:
                raise ValueError("Hybrid source does not support load options or amplitudes")
            for values in rows:
                node, direction, value = int(values[0]), int(values[1]), float(values[2])
                if (
                    node != result["source"]["node"]
                    or direction not in (1, 2, 3)
                    or not math.isfinite(value)
                ):
                    raise ValueError("Unexpected actual point source in the hybrid input")
                loads[direction - 1] += value

    def expand(name, visiting=()):
        if isinstance(name, int):
            return [name]
        if name not in sets or name in visiting:
            raise ValueError("Unknown or recursive native hybrid node set")
        return [node for value in sets[name] for node in expand(value, (*visiting, name))]

    for mode, options, rows in blocks:
        if mode != "*BOUNDARY":
            continue
        if options:
            raise ValueError("Hybrid restraints require plain zero native boundaries")
        for values in rows:
            if not 2 <= len(values) <= 4:
                raise ValueError("Malformed native hybrid boundary")
            target = int(values[0]) if values[0].isdecimal() else values[0].upper()
            first = int(values[1])
            last = int(values[2]) if len(values) > 2 else first
            value = float(values[3]) if len(values) > 3 else 0.0
            if value != 0.0 or first < 1 or last > 6 or first > last:
                raise ValueError(
                    "Hybrid boundary must prescribe a supported zero degree of freedom"
                )
            for node in expand(target):
                for direction in range(first, last + 1):
                    if (node, direction) in boundaries:
                        raise ValueError("Repeated native hybrid physical boundary")
                    boundaries[node, direction] = 0.0
    expected_boundaries = {
        (result["support"]["node"], direction) for direction in result["support"]["directions"]
    }
    expected_boundaries.update(
        (node, direction) for node in result["solid_support"]["nodes"] for direction in (1, 2, 3)
    )
    if (
        set(boundaries) != expected_boundaries
        or not any(loads)
        or actual_solids != {row["element"]: row["nodes"] for row in result["solid_elements"]}
    ):
        raise ValueError("Native hybrid support/source/solid catalogue is incomplete")
    laws = [(options, rows) for mode, options, rows in blocks if mode == "*SPRING"]
    frames = [(options, rows) for mode, options, rows in blocks if mode == "*ORIENTATION"]
    if len(laws) != 1 or len(frames) != 1:
        raise ValueError("One native hybrid scalar spring law/frame is required")
    options, rows = laws[0]
    frame, axes = frames[0]
    spring = result["spring"]
    if (
        len(rows) != 2
        or rows[0] != [str(spring["direction"])] * 2
        or len(rows[1]) != 1
        or not math.isclose(
            float(rows[1][0]), spring["stiffness_N_per_mm"], rel_tol=5e-13, abs_tol=0
        )
        or options.get("ORIENTATION") != frame.get("NAME")
        or len(axes) != 1
        or list(map(float, axes[0])) != [1, 0, 0, 0, 1, 0]
    ):
        raise ValueError("The actual hybrid scalar law/directions/frame differ from the model")
    for row in result["nodes"]:
        point = nodes.get(row["node"])
        if point is None or (
            App.Vector(*point) - App.Vector(*row["position"])
        ).Length > 1e-10 * max(1, App.Vector(*point).Length):
            raise ValueError("The native hybrid physical node coordinates changed")
        row["position"] = point
    result["source"] = {
        **result["source"],
        "force_global": loads,
        "position": nodes[result["source"]["node"]],
    }
    result["support"] = {**result["support"], "position": nodes[result["support"]["node"]]}
    for kind in ("reference", "rotation"):
        point = nodes.get(result["port"][kind])
        if (
            point is None
            or len(point) != 3
            or not all(map(math.isfinite, point))
            or (App.Vector(*point) - App.Vector(*expected["port"]["position"])).Length
            > 1e-10 * max(1.0, App.Vector(*point).Length)
        ):
            raise ValueError(
                "Written rigid-body reference/rotation coordinates differ from the model"
            )
    result["port"] = {**result["port"], "position": nodes[result["port"]["reference"]]}
    return result


def request_lines(coupling):
    spring, source, support, fixed, port = (
        coupling[name] for name in ("spring", "source", "support", "solid_support", "port")
    )
    lines = [
        "SOLID {} {} {}".format(
            coupling["solid_owner"], row["element"], " ".join(map(str, row["nodes"]))
        )
        for row in coupling["solid_elements"]
    ]
    lines.extend(
        [
            "SPRING2 {} {} {} {} {}".format(
                spring["owner"], spring["element"], *spring["nodes"], spring["direction"]
            ),
            f"SOURCE {source['owner']} {source['node']}",
            "SUPPORT {} {} {} {}".format(
                support["owner"],
                support["node"],
                len(support["directions"]),
                " ".join(map(str, support["directions"])),
            ),
            "SPC_SUPPORT {} {} {}".format(
                fixed["owner"], len(fixed["nodes"]), " ".join(map(str, fixed["nodes"]))
            ),
            "PORT {} {} {} {} {}".format(
                port["name"],
                port["reference"],
                port["rotation"],
                len(port["nodes"]),
                " ".join(map(str, port["nodes"])),
            ),
        ]
    )
    return lines


def validate(actions, coupling):
    """Validate native identities/conventions, without recovering reactions."""

    def vector(value):
        return (
            isinstance(value, list)
            and len(value) == 3
            and all(type(item) in (int, float) and math.isfinite(item) for item in value)
        )

    def close(actual, expected):
        return all(abs(a - b) <= 1e-12 * max(1.0, abs(a), abs(b)) for a, b in zip(actual, expected))

    def cross(point, force):
        return list(App.Vector(*point).cross(App.Vector(*force)))

    def paired(first, second, names):
        for name in names:
            if any(
                abs(a + b) > 1e-10 * max(1.0, abs(a), abs(b))
                for a, b in zip(first[name], second[name])
            ):
                raise ValueError(
                    "Native internal action pair has inconsistent signs or origin transport"
                )

    if not isinstance(actions, dict):
        raise ValueError("Native mixed beam actions must be a record")
    spring = actions.get("spring")
    if (
        not isinstance(spring, dict)
        or spring.get("owner") != coupling["spring"]["owner"]
        or type(spring.get("element")) is not int
        or spring["element"] != coupling["spring"]["element"]
        or not isinstance(spring.get("ends"), list)
        or len(spring["ends"]) != 2
    ):
        raise ValueError("Native mixed scalar spring identity is unavailable")
    coordinates = {row["node"]: row["position"] for row in coupling["nodes"]}
    first, second = spring["ends"]
    for index, row in enumerate((first, second)):
        expected_position = (
            coordinates[coupling["spring"]["nodes"][0]]
            if index == 0
            else coupling["port"]["position"]
        )
        if (
            not isinstance(row, dict)
            or type(row.get("end")) is not int
            or row["end"] != index + 1
            or type(row.get("node")) is not int
            or row["node"] != coupling["spring"]["nodes"][index]
            or row.get("role") != ("BEAM_VERTEX" if index == 0 else "RBE_REFERENCE")
            or not all(
                vector(row.get(name))
                for name in (
                    "position",
                    "native_resisting_force",
                    "force_global",
                    "moment_origin",
                    "displacement",
                )
            )
            or not close(row["position"], expected_position)
            or any(a != -b for a, b in zip(row["force_global"], row["native_resisting_force"]))
            or not close(row["moment_origin"], cross(row["position"], row["force_global"]))
        ):
            raise ValueError("Native hybrid spring endpoint identity/frame/action is invalid")
    paired(first, second, ("force_global", "moment_origin"))
    # Reuse the already qualified wire validation for the beam-side source,
    # guide and actual spring endpoint; this adapts copied native fields only.
    beam_coupling.validate(
        {**actions, "spring": {**first, "owner": spring["owner"], "element": spring["element"]}},
        {
            **coupling,
            "spring": {
                **coupling["spring"],
                "node": first["node"],
                "position": coordinates[first["node"]],
            },
        },
    )
    fixed = actions.get("solid_support")
    expected_fixed = coupling["solid_support"]
    if (
        not isinstance(fixed, dict)
        or fixed.get("owner") != expected_fixed["owner"]
        or fixed.get("nodes") != expected_fixed["nodes"]
        or not all(vector(fixed.get(name)) for name in ("force_global", "moment_origin"))
        or not isinstance(fixed.get("spcs"), list)
    ):
        raise ValueError("Native physical solid support identity/wrench is unavailable")
    expected_spcs = {
        (node, direction) for node in expected_fixed["nodes"] for direction in (1, 2, 3)
    }
    seen, force, moment = set(), [0.0] * 3, [0.0] * 3
    for row in fixed["spcs"]:
        if not isinstance(row, dict):
            raise ValueError("Native solid support term must be a record")
        node, direction, value = (row.get(name) for name in ("node", "direction", "value"))
        if (
            type(node) is not int
            or type(direction) is not int
            or (node, direction) not in expected_spcs
            or (node, direction) in seen
            or row.get("role") != "TRANSLATION"
            or type(value) not in (int, float)
            or not math.isfinite(value)
            or not vector(row.get("position"))
            or not close(row["position"], coordinates[node])
        ):
            raise ValueError("Native physical solid support term is invalid or repeated")
        seen.add((node, direction))
        component = [0.0, 0.0, 0.0]
        component[direction - 1] = value
        force = [a + b for a, b in zip(force, component)]
        moment = [a + b for a, b in zip(moment, cross(row["position"], component))]
    if (
        seen != expected_spcs
        or not close(force, fixed["force_global"])
        or not close(moment, fixed["moment_origin"])
    ):
        raise ValueError("Native solid support aggregate differs from its complete physical terms")
    port = actions.get("port")
    expected_port = coupling["port"]
    if (
        not isinstance(port, dict)
        or port.get("owner") != expected_port["name"]
        or type(port.get("reference_node")) is not int
        or port["reference_node"] != expected_port["reference"]
        or type(port.get("rotation_node")) is not int
        or port["rotation_node"] != expected_port["rotation"]
        or port.get("receiving_nodes") != expected_port["nodes"]
    ):
        raise ValueError("Native moving rigid-body port identity is unavailable")
    for name in ("receiving_action", "reference_action"):
        if not isinstance(port.get(name), dict) or not all(
            vector(port[name].get(field)) for field in ("force_global", "moment_origin")
        ):
            raise ValueError("Native rigid-body port action is unavailable")
    reference = port["reference_action"]
    if not vector(reference.get("couple_global")):
        raise ValueError("Native rigid-body rotation-node couple is unavailable")
    origin = [
        a + b
        for a, b in zip(
            cross(expected_port["position"], reference["force_global"]), reference["couple_global"]
        )
    ]
    if not close(reference["moment_origin"], origin):
        raise ValueError("Native rigid-body reference moment has invalid force/couple transport")
    paired(port["receiving_action"], reference, ("force_global", "moment_origin"))
    # These are finite native equation values, explicitly excluded from the
    # physical support and port wrenches, even when they are nonzero.
    spcs = port.get("algebraic_spcs")
    if not isinstance(spcs, list):
        raise ValueError("Native rigid-body algebraic catalogue is unavailable")
    expected_algebraic = {
        (node, direction) for node in expected_port["nodes"] for direction in (1, 2, 3)
    }
    seen, auxiliary = set(), {}
    physical = set(coordinates) | {expected_port["reference"], expected_port["rotation"]}
    physical.update(
        row["node"] for row in actions["support"]["spcs"] if row["role"] != "TRANSLATION"
    )
    for row in spcs:
        if not isinstance(row, dict):
            raise ValueError("Native rigid-body algebraic term must be a record")
        node, receiver, direction, value = (
            row.get(name) for name in ("node", "receiving_node", "direction", "value")
        )
        if (
            type(node) is not int
            or node < 1
            or node in physical
            or type(receiver) is not int
            or type(direction) is not int
            or (receiver, direction) not in expected_algebraic
            or (receiver, direction) in seen
            or row.get("role") != "ALGEBRAIC"
            or type(value) not in (int, float)
            or not math.isfinite(value)
        ):
            raise ValueError("Native rigid-body algebraic identity/value is invalid")
        seen.add((receiver, direction))
        if receiver in auxiliary and auxiliary[receiver] != node:
            raise ValueError("Native rigid-body algebraic node identity changed")
        auxiliary[receiver] = node
    if seen != expected_algebraic or len(set(auxiliary.values())) != len(expected_port["nodes"]):
        raise ValueError("Native rigid-body algebraic catalogue is incomplete or aliased")
