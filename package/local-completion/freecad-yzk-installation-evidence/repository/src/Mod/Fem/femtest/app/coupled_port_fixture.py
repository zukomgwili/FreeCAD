# SPDX-License-Identifier: LGPL-2.1-or-later
"""Frozen coupled finite-face fixture through existing public native objects.

Importing defines helpers; it does not create a document or launch a process.
A dedicated native capacity test calls make_fixture with its own fresh output directory.
No writer/accounting implementation helper, deck patch or solver call is used.
The one-bay tracer and132-bay graph use the same parametric construction.
"""

import hashlib
import json
from itertools import combinations
from pathlib import Path
from types import SimpleNamespace

import FreeCAD as App

import ObjectsFem
import Part
from BOPTools.SplitAPI import booleanFragments

from femmesh import gmshtools

DATA = Path(__file__).resolve().parents[1] / "data" / "calculix"
FROZEN = {
    "coupled_port_capacity_fixture.json": (
        "9142f5aa4d149aa1f0d518a592a78638f9489fb3e245af67ea4fd463e5b8ae22"
    ),
    "coupled_port_capacity_oracle.json": (
        "42fa6289fd9e1f80efa56db27c02c06a5454ed9880f7ca61bfd80992dfb251b8"
    ),
}
TOL = 1e-8


def need(condition, message):
    if not condition:
        raise AssertionError(message)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def plain(value):
    if isinstance(value, (str, bool, int, float)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if isinstance(value, App.Vector):
        return [value.x, value.y, value.z]
    if isinstance(value, App.Rotation):
        return list(value.Q)
    if hasattr(value, "Name") and hasattr(value, "Document"):
        return {"object": value.Name, "document": value.Document.Name}
    return str(value)


def key(point):
    return tuple(round(getattr(point, axis), 9) for axis in "xyz")


def face_index(owner):
    result = {}
    for index, face in enumerate(owner.Shape.Faces, 1):
        result.setdefault(key(face.CenterOfMass), []).append((f"Face{index}", face))
    return result


def exact_face(index, centre, normal=None, area=4.0):
    matches = []
    for name, face in index.get(tuple(float(value) for value in centre), []):
        direction_ok = normal is None or face.normalAt(0, 0).dot(App.Vector(*normal)) > 0.99
        if direction_ok and abs(face.Area - area) < TOL:
            matches.append((name, face))
    need(
        len(matches) == 1,
        f"Expected one finite face at {centre}, normal={normal}; "
        f"got {[item[0] for item in matches]}",
    )
    return matches[0]


def exact_solid(index, centre):
    matches = index.get(tuple(float(value) for value in centre), [])
    need(len(matches) == 1, f"Expected one material cell at {centre}: {matches}")
    return matches[0]


def noncollinear(nodes, coordinates):
    need(len(nodes) >= 3, "Finite receiving/cut region has fewer than three nodes")
    points = [coordinates[node] for node in sorted(nodes)]
    anchor = points[0]
    vectors = [point - anchor for point in points[1:]]
    first = next((vector for vector in vectors if vector.Length > TOL), None)
    need(
        first is not None and any(first.cross(vector).Length > TOL for vector in vectors),
        "Finite receiving/cut face nodes are collinear",
    )


def model_properties(analysis, mesh):
    names = (
        "References",
        "ReferenceNode",
        "Displacement",
        "Rotation",
        *("TranslationalMode" + axis for axis in "XYZ"),
        *("RotationalMode" + axis for axis in "XYZ"),
        *("Force" + axis for axis in "XYZ"),
        *("Moment" + axis for axis in "XYZ"),
        "Attachment",
        "Mode",
        "Kind",
        "Axis",
        "Orientation",
        "RigidBody1",
        "RigidBody2",
        "Stiffness",
        "RotationalStiffness",
        "Force",
        "Direction",
        "Reversed",
        "NativeEquilibriumCut",
        "AccountingBody",
        "NativeForceAccounting",
        "NativeAccountingSolver",
        "NativeAccountingSupports",
        "Material",
    )
    return {
        item.Name: {
            "type": item.TypeId,
            "properties": {
                name: {"type": item.getTypeIdOfProperty(name), "value": plain(getattr(item, name))}
                for name in names
                if name in item.PropertiesList
            },
        }
        for item in analysis.Group
        if item != mesh
    }


def mesh_membership(fixture):
    """Public mesh groups/coordinates prove exact physical ownership/continuity."""
    geometry, data = fixture.geometry, fixture.mesh.FemMesh
    coordinates = data.Nodes
    connectivity = {element: tuple(data.getElementNodes(element)) for element in data.Volumes}
    groups = {data.getGroupName(group): set(data.getGroupElements(group)) for group in data.Groups}
    cells, cell_nodes, seen_elements, cell_connectivity_proof = {}, {}, set(), {}
    volume_ids = set(connectivity)
    for index in range(1, len(geometry.Shape.Solids) + 1):
        name = f"Solid{index}"
        elements = groups[name]
        need(
            bool(elements) and elements <= volume_ids,
            f"Empty or non-volume native cell group: {name}",
        )
        need(
            not seen_elements.intersection(elements),
            f"Duplicate physical volume element ownership: {name}",
        )
        seen_elements.update(elements)
        cells[name] = elements
        cell_nodes[name] = {node for element in elements for node in connectivity[element]}
        # Public tetra connectivity lists the four vertices before midsides.
        # Connected-through-a-node is insufficient: prove a whole tetra facet
        # adjacency path through every physical element of each requested cell.
        face_owners, adjacent = {}, {element: set() for element in elements}
        for element in elements:
            nodes = connectivity[element]
            need(len(nodes) in (4, 10), f"Unsupported non-tetra volume element in {name}")
            for face in combinations(nodes[:4], 3):
                owners = face_owners.setdefault(tuple(sorted(face)), [])
                owners.append(element)
                need(len(owners) <= 2, f"Nonmanifold tetra facet inside {name}")
                if len(owners) == 2:
                    adjacent[owners[0]].add(owners[1])
                    adjacent[owners[1]].add(owners[0])
        pending, reached = [next(iter(elements))], set()
        while pending:
            element = pending.pop()
            if element not in reached:
                reached.add(element)
                pending.extend(adjacent[element] - reached)
        need(reached == elements, f"Physical cell has disconnected tetra facet components: {name}")
        cell_connectivity_proof[name] = {
            "volume_elements": len(elements),
            "connected_tetra_facet_components": 1,
            "interior_shared_tetra_facets": sum(
                len(owners) == 2 for owners in face_owners.values()
            ),
        }
    need(seen_elements == volume_ids, "Physical volume elements are omitted from cell ownership")

    def nodes_on(face):
        nodes = set(data.getNodesByFace(face))
        noncollinear(nodes, coordinates)
        return nodes

    fixed_nodes = nodes_on(geometry.getSubObject(fixture.fixed_face))
    backbone_nodes = cell_nodes[fixture.backbone_solid]
    host_nodes = set(backbone_nodes)
    port_nodes, branch_nodes, cut_nodes, load_nodes = {}, {}, {}, {}
    shared_proof, used_port_nodes, used_B_nodes = [], set(), set()
    for branch in fixture.branches:
        bay = branch["name"]
        stub, left, right = (branch["solids"][role] for role in ("A", "B_left", "B_right"))
        host_nodes.update(cell_nodes[stub])
        base_face = exact_face(fixture.faces_index, (5, branch["y"], branch["z"]))[1]
        base_nodes = nodes_on(base_face)
        need(
            cell_nodes[stub] & backbone_nodes == base_nodes,
            f"{bay}: host/tongue is not exactly conforming",
        )
        need(
            any(base_face.isSame(face) for face in geometry.getSubObject(stub).Faces)
            and any(
                base_face.isSame(face)
                for face in geometry.getSubObject(fixture.backbone_solid).Faces
            ),
            f"{bay}: tongue/backbone do not share the same CAD face",
        )
        shared_proof.append(
            {
                "owners": [fixture.backbone_solid, stub],
                "face_nodes": sorted(base_nodes),
                "area_mm2": 4,
            }
        )
        cut_face = exact_face(fixture.faces_index, (25, branch["y"], branch["z"]))[1]
        shared = nodes_on(cut_face)
        need(
            cell_nodes[left] & cell_nodes[right] == shared,
            f"{bay}: B pair is not exactly conforming",
        )
        need(
            any(cut_face.isSame(face) for face in geometry.getSubObject(left).Faces)
            and any(cut_face.isSame(face) for face in geometry.getSubObject(right).Faces),
            f"{bay}: B cells do not share the same CAD cut face",
        )
        pair_nodes = cell_nodes[left] | cell_nodes[right]
        need(not used_B_nodes.intersection(pair_nodes), f"{bay}: distinct B continua share nodes")
        used_B_nodes.update(pair_nodes)
        branch_nodes[bay] = pair_nodes
        cut_nodes[bay] = shared
        shared_proof.append({"owners": [left, right], "face_nodes": sorted(shared), "area_mm2": 4})
        for side in ("A", "B"):
            face_nodes = nodes_on(geometry.getSubObject(branch["faces"][side]))
            need(
                not used_port_nodes.intersection(face_nodes),
                f"{bay}/{side}: moving receiving faces overlap",
            )
            need(
                not face_nodes.intersection(fixed_nodes | shared),
                f"{bay}/{side}: port overlaps support or cut",
            )
            need(
                face_nodes <= (cell_nodes[stub] if side == "A" else cell_nodes[left]),
                f"{bay}/{side}: wrong receiving owner",
            )
            used_port_nodes.update(face_nodes)
            port_nodes[branch["ports"][side].Name] = face_nodes
        loaded = nodes_on(geometry.getSubObject(branch["faces"]["load"]))
        need(
            loaded <= cell_nodes[right] and not loaded.intersection(shared),
            f"{bay}: end load touches cut or wrong owner",
        )
        need(
            not loaded.intersection(used_port_nodes | fixed_nodes),
            f"{bay}: loaded face overlaps port/support",
        )
        load_nodes[bay] = loaded
    need(
        fixed_nodes <= backbone_nodes and not host_nodes.intersection(used_B_nodes),
        "Physical backbone/support and B continua are not disjoint",
    )
    need(
        host_nodes | used_B_nodes == set(coordinates),
        "Physical mesh nodes are omitted from continuum membership",
    )
    for nodes in port_nodes.values():
        need(
            not nodes.intersection(set().union(*cut_nodes.values())),
            "A moving port overlaps another branch cut",
        )
    for nodes in load_nodes.values():
        need(
            not nodes.intersection(
                used_port_nodes | fixed_nodes | set().union(*cut_nodes.values())
            ),
            "A physical end load overlaps another port, support or cut",
        )
    return {
        "schema": "FreeCAD-native-coupled-port-native-physical-membership-v1",
        "nodes": {str(node): plain(point) for node, point in coordinates.items()},
        "volume_connectivity": {
            str(element): list(nodes) for element, nodes in connectivity.items()
        },
        "cell_volume_elements": {name: sorted(elements) for name, elements in cells.items()},
        "cell_tetra_facet_connectivity_proof": cell_connectivity_proof,
        "fixed_face_nodes": sorted(fixed_nodes),
        "physical_fixed_node_DOF_pairs": [
            [node, direction] for node in sorted(fixed_nodes) for direction in (1, 2, 3)
        ],
        "moving_face_nodes": {name: sorted(nodes) for name, nodes in port_nodes.items()},
        "paired_cut_nodes": {name: sorted(nodes) for name, nodes in cut_nodes.items()},
        "end_loaded_nodes": {name: sorted(nodes) for name, nodes in load_nodes.items()},
        "host_volume_cells": [fixture.backbone_solid]
        + [branch["solids"]["A"] for branch in fixture.branches],
        "B_volume_cells": {
            branch["name"]: [branch["solids"]["B_left"], branch["solids"]["B_right"]]
            for branch in fixture.branches
        },
        "physical_continuum_components_before_scalar_links": 1 + len(fixture.branches),
        "coupled_graph_components_after_scalar_links": 1,
        "conforming_shared_CAD_and_mesh_face_proof": shared_proof,
        "all_volume_elements_owned_exactly_once": True,
        "all_physical_nodes_covered": True,
        "no_disjoint_continua_merged_or_port_support_cut_overlap": True,
    }


def make_fixture(doc, output, *, rows_y=1, columns_z=1, create_mesh=True):
    """Construct only; the dedicated test uses normal writer/solver/import/save separately."""
    need(
        (rows_y, columns_z) in ((1, 1), (11, 12)),
        "Only the frozen tracer or132-bay case is approved",
    )
    for name, expected in FROZEN.items():
        need(sha(DATA / name) == expected, f"Frozen independent input changed: {name}")
    output = Path(output).resolve()
    need(
        output.parent.is_dir() and not output.exists(),
        "Fixture output must be a new caller-owned subdirectory",
    )
    output.mkdir()
    for name in ("mesh", "native"):
        (output / name).mkdir()
    count = rows_y * columns_z
    analysis = ObjectsFem.makeAnalysis(doc, "Analysis")
    solver = ObjectsFem.makeSolverCalculiXCcxTools(doc, "SolverCcxTools")
    solver.NativeForceAccounting = True
    solver.SplitInputWriter = False
    solver.AnalysisType = "static"
    solver.WorkingDir = str(output / "native")
    analysis.addObject(solver)
    centres = [(i, j, 2 + 4 * i, 3 + 4 * j) for i in range(rows_y) for j in range(columns_z)]
    plate = Part.makeBox(5, 4 * rows_y, 4 * columns_z, App.Vector(0, 0, 1))
    tongues = [Part.makeBox(5, 2, 2, App.Vector(5, y - 1, z - 1)) for _, _, y, z in centres]
    host = booleanFragments([plate, *tongues], "CompSolid")
    beams = [
        booleanFragments(
            [Part.makeBox(5, 2, 2, App.Vector(x, y - 1, z - 1)) for x in (20, 25)], "CompSolid"
        )
        for _, _, y, z in centres
    ]
    geometry = doc.addObject("Part::Feature", "CoupledCells")
    geometry.Shape = Part.makeCompound([host, *beams])
    doc.recompute()
    need(geometry.Shape.isValid(), "Coupled finite geometry is not valid")
    need(
        len(geometry.Shape.Solids) == 1 + 3 * count,
        "Conforming physical cell count differs from frozen geometry",
    )
    need(abs(geometry.Shape.Volume - 140 * count) < TOL, "Frozen physical material volume differs")
    faces = face_index(geometry)
    solids = {}
    for index, solid in enumerate(geometry.Shape.Solids, 1):
        solids.setdefault(key(solid.CenterOfMass), []).append(f"Solid{index}")
    backbone = exact_solid(solids, (2.5, 2 * rows_y, 1 + 2 * columns_z))
    fixed_face = exact_face(faces, (0, 2 * rows_y, 1 + 2 * columns_z), (-1, 0, 0), 16 * count)[0]
    material = ObjectsFem.makeMaterialSolid(doc, "WitnessMaterial")
    material.Material = {
        "Name": "Synthetic native-capacity linear finite-backbone material",
        "YoungsModulus": "20000 MPa",
        "PoissonRatio": "0.3",
        "Density": "1 kg/m^3",
    }
    analysis.addObject(material)
    fixed = ObjectsFem.makeConstraintFixed(doc, "BackboneFixed")
    fixed.References = [(geometry, [fixed_face])]
    analysis.addObject(fixed)
    solver.NativeAccountingSupports = [fixed]
    directions = {}
    for name, vector in (("Axial", (1, 0, 0)), ("PositiveZ", (0, 0, 1)), ("NegativeZ", (0, 0, -1))):
        direction = doc.addObject("Part::Feature", name + "Direction")
        direction.Shape = Part.makeLine(App.Vector(), App.Vector(*vector))
        directions[name] = direction
    edges = {}
    for index, edge in enumerate(geometry.Shape.Edges, 1):
        if len(edge.Vertexes) == 2 and abs(edge.Length - 2) < TOL:
            endpoints = [vertex.Point for vertex in edge.Vertexes]
            if (
                all(abs(point.x - 30) < TOL for point in endpoints)
                and abs(endpoints[0].y - endpoints[1].y) < TOL
            ):
                edges.setdefault(key(edge.CenterOfMass), []).append(f"Edge{index}")
    reverse, reverse_faces, branches, all_ports, connectors, cuts, loads = (
        None,
        None,
        [],
        [],
        [],
        [],
        [],
    )
    for i, j, y, z in centres:
        bay = f"Bay_{i:02d}_{j:02d}"
        branch = {
            "name": bay,
            "i": i,
            "j": j,
            "y": y,
            "z": z,
            "faces": {},
            "ports": {},
            "solids": {
                "A": exact_solid(solids, (7.5, y, z)),
                "B_left": exact_solid(solids, (22.5, y, z)),
                "B_right": exact_solid(solids, (27.5, y, z)),
            },
            "connectors": [],
            "cuts": {},
            "loads": [],
        }
        for side, x, normal in (("A", 10, (1, 0, 0)), ("B", 20, (-1, 0, 0))):
            name, face = exact_face(faces, (x, y, z), normal)
            port = ObjectsFem.makeConstraintRigidBody(doc, f"Port{side}_{i:02d}_{j:02d}")
            port.References = [(geometry, [name])]
            port.ReferenceNode = App.Vector(x, y, z)
            port.Displacement, port.Rotation = App.Vector(), App.Rotation()
            for axis in "XYZ":
                setattr(port, "TranslationalMode" + axis, "Free")
                setattr(port, "RotationalMode" + axis, "Free")
            analysis.addObject(port)
            branch["faces"][side], branch["ports"][side] = name, port
            all_ports.append(port)
        for kind, prefix in (("Translational", "T"), ("Rotational", "R")):
            for axis in "XYZ":
                connector = ObjectsFem.makeConstraintElasticConnector(
                    doc, f"Connector{prefix}{axis}_{i:02d}_{j:02d}"
                )
                connector.Attachment, connector.Mode = "Rigid body ports", "Two points"
                connector.Kind, connector.Axis, connector.Orientation = kind, axis, App.Rotation()
                connector.RigidBody1, connector.RigidBody2 = (
                    branch["ports"]["A"],
                    branch["ports"]["B"],
                )
                if kind == "Translational":
                    connector.Stiffness = "1200 N/mm"
                else:
                    connector.RotationalStiffness = App.Units.Quantity("6000 N*mm/rad")
                analysis.addObject(connector)
                branch["connectors"].append(connector)
                connectors.append(connector)
        branch["faces"]["load"] = exact_face(faces, (30, y, z), (1, 0, 0))[0]
        for label, selection, amount, direction in (
            ("Axial", branch["faces"]["load"], 12, directions["Axial"]),
            ("TorquePositive", None, 3, directions["PositiveZ"]),
            ("TorqueNegative", None, 3, directions["NegativeZ"]),
        ):
            if selection is None:
                matches = edges.get(
                    (30.0, float(y + (1 if label == "TorquePositive" else -1)), float(z)), []
                )
                need(len(matches) == 1, f"{bay}: ambiguous physical end edge {label}")
                selection = matches[0]
            load = ObjectsFem.makeConstraintForce(doc, label + f"_{i:02d}_{j:02d}")
            load.References, load.Force = [(geometry, [selection])], f"{amount} N"
            load.Direction, load.Reversed = (direction, ["Edge1"]), False
            analysis.addObject(load)
            branch["loads"].append(load)
            loads.append(load)
        for side, normal, solid in (
            ("Left", (1, 0, 0), branch["solids"]["B_left"]),
            ("Right", (-1, 0, 0), branch["solids"]["B_right"]),
        ):
            owner, index = geometry, faces
            candidates = [
                (name, face)
                for name, face in index.get((25.0, float(y), float(z)), [])
                if face.normalAt(0, 0).dot(App.Vector(*normal)) > 0.99
            ]
            if not candidates:
                if reverse is None:
                    reverse = doc.addObject("Part::Reverse", "OppositeCutOrientation")
                    reverse.Source = geometry
                    doc.recompute()
                    reverse_faces = face_index(reverse)
                owner, index = reverse, reverse_faces
            name, _ = exact_face(index, (25, y, z), normal)
            cut = ObjectsFem.makeConstraintSectionPrint(doc, f"Cut{side}_{i:02d}_{j:02d}")
            cut.References, cut.AccountingBody = [(owner, [name])], [(geometry, [solid])]
            cut.NativeEquilibriumCut = True
            analysis.addObject(cut)
            branch["cuts"][side] = cut
            cuts.append(cut)
        branches.append(branch)
    mesh = ObjectsFem.makeMeshGmsh(doc, "Mesh")
    mesh.Shape, mesh.ElementOrder = geometry, "2nd"
    mesh.SecondOrderLinear, mesh.CoherenceMesh = False, False
    mesh.CharacteristicLengthMax, mesh.CharacteristicLengthMin = 1.5, 0.75
    mesh.WorkingDirectory = str(output / "mesh")
    analysis.addObject(mesh)
    doc.recompute()
    need(
        len(all_ports) == 2 * count and len(connectors) == 6 * count and len(cuts) == 2 * count,
        "Frozen public object cardinality differs",
    )
    need(
        list(solver.NativeAccountingSupports) == [fixed],
        "Ordinary external support selection changed",
    )
    fixture = SimpleNamespace(
        doc=doc,
        output=output,
        analysis=analysis,
        solver=solver,
        geometry=geometry,
        material=material,
        fixed=fixed,
        fixed_face=fixed_face,
        backbone_solid=backbone,
        faces_index=faces,
        ports=all_ports,
        connectors=connectors,
        cuts=cuts,
        loads=loads,
        branches=branches,
        mesh=mesh,
        membership=None,
    )
    write_json(
        output / "geometry-contract.json",
        {
            "schema": "FreeCAD-native-coupled-port-frozen-public-fixture-v1",
            "rows_y": rows_y,
            "columns_z": columns_z,
            "branches": count,
            "physical_solids": len(geometry.Shape.Solids),
            "physical_volume_mm3": geometry.Shape.Volume,
            "frozen_oracle_sha256": FROZEN,
            "public_object_counts": {
                "PORT": len(all_ports),
                "BODY": len(cuts),
                "SPRING": len(connectors),
                "ANGLE": 6 * count,
                "SPC_SUPPORT": 1,
            },
            "branches_and_references": plain(branches),
            "backbone_solid": backbone,
            "fixed_face": fixed_face,
            "only_public_native_interfaces": True,
            "no_deck_patches_or_mocks": True,
            "engineering_project_accessed_or_solved": False,
        },
    )
    write_json(output / "native-properties.json", model_properties(analysis, mesh))
    if create_mesh:
        mesher = gmshtools.GmshTools(mesh)
        mesher.create_mesh()
        need(mesher.process.exitCode() == 0, "Native Gmsh process did not exit zero")
        need(
            mesher.process.exitStatus() == mesher.process.ExitStatus.NormalExit,
            "Native Gmsh process did not exit normally",
        )
        need(mesh.FemMesh.VolumeCount > 0, "Native mesh has no volume elements")
        fixture.membership = mesh_membership(fixture)
        write_json(output / "mesh-membership.json", fixture.membership)
    return fixture
