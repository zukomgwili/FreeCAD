# SPDX-License-Identifier: LGPL-2.1-or-later
"""Model-grounded native contact-side displacement observations.

No contact-law recovery, geometric matching or interpolation formula lives
here. Original solver IDs bind the field. Native CAD ownership binds each
surface, and VTK supplies the guarded surface interpolation when a coincident
original node is absent. Values are reference-state global XYZ in millimetres.
"""

import hashlib
import json
import math
import sys
from types import SimpleNamespace

import Fem

from femmesh import meshtools
from femmesh.ownership_context import _OwnershipContext


SCHEMA = "FreeCAD.CONTACT_SIDE_OBSERVATION_V1"


def definition(obj):
    """Identity of the editable selection, independently of cached output."""
    doc = obj.Document
    analysis, mesh, accounting = obj.Analysis, obj.Mesh, obj.AccountingResult
    if not (analysis and mesh and accounting and obj.Contacts):
        raise ValueError("Select analysis, mesh, native source and contacts")
    if any(item.Document != doc for item in (analysis, mesh, accounting, *obj.Contacts)):
        raise ValueError("Observation inputs must belong to the same document")
    if not analysis.isDerivedFrom("Fem::FemAnalysis"):
        raise ValueError("Select a native FEM analysis")
    if not mesh.isDerivedFrom("Fem::FemMeshObject") or mesh not in analysis.Group:
        raise ValueError("Select the original mesh in this analysis")
    contacts = list(obj.Contacts)
    if len(set(contacts)) != len(contacts):
        raise ValueError("Duplicate contact selection")
    rows = []
    for contact in contacts:
        if not contact.isDerivedFrom("Fem::ConstraintContact") or contact not in analysis.Group:
            raise ValueError("Select native contacts in this analysis")
        refs = list(contact.References)
        if len(refs) != 2 or any(
            owner is None or owner.Document != doc or len(names) != 1 or not names[0]
            for owner, names in refs
        ):
            raise ValueError(f"{contact.Name}: select one independent face per side")
        rows.append(
            {
                "contact": contact.Name,
                "references_slave_then_master": [
                    [owner.Name, list(names)] for owner, names in refs
                ],
            }
        )
    return {
        "analysis": analysis.Name,
        "mesh": mesh.Name,
        "accounting_result": accounting.Name,
        "slave_vertex": obj.SlaveVertex,
        "contacts": rows,
    }


def _surface_grid(context, nodes, members, field):
    """Adapt exact owned native faces; never rebuild a face from coordinates."""
    from vtkmodules.vtkCommonCore import vtkDoubleArray

    elements = sorted({element for values in members.values() for element in values})
    if not elements or not set(elements).issubset(context.faces):
        raise ValueError("Owned original surface elements are unavailable")
    used = {node for element in elements for node in context.elements[element]}
    if used != set(nodes) or any(node not in field for node in used):
        raise ValueError("Original displacement field is incomplete for the owned surface")
    surface = Fem.FemMesh()
    for node in sorted(used):
        point = context.nodes[node]
        surface.addNode(point.x, point.y, point.z, node)
    for element in elements:
        connectivity = list(context.elements[element])
        if len(connectivity) not in (3, 4, 6, 8):
            raise ValueError("Unsupported native surface element")
        surface.addFace(connectivity, element)
        if tuple(surface.getElementNodes(element)) != tuple(connectivity):
            raise ValueError("Native surface copy changed original connectivity")
    grid = surface.toVTK()
    source_nodes = grid.GetPointData().GetArray("FreeCADNodeId")
    source_elements = grid.GetCellData().GetArray("FreeCADElementId")
    if source_nodes is None or source_elements is None:
        raise ValueError("Native mesh export did not preserve original identities")
    if {source_elements.GetValue(i) for i in range(grid.GetNumberOfCells())} != set(elements):
        raise ValueError("Native surface export changed original element identities")
    if {
        source_nodes.GetValue(i)
        for i in range(grid.GetNumberOfPoints())
        if source_nodes.GetValue(i) > 0
    } != used:
        raise ValueError("Native surface export changed original node identities")
    displacement = vtkDoubleArray()
    displacement.SetName("Displacement")
    displacement.SetNumberOfComponents(3)
    displacement.SetNumberOfTuples(grid.GetNumberOfPoints())
    # Only explicit UNUSED sparse index gaps receive zeros; every used node
    # below must have actual original-ID U, including genuine measured zeros.
    for component in range(3):
        displacement.FillComponent(component, 0)
    for index in range(grid.GetNumberOfPoints()):
        node = source_nodes.GetValue(index)
        if node == -1:
            continue
        if node not in used or node not in field:
            raise ValueError("Unbound original node in native surface export")
        if tuple(grid.GetPoint(index)) != tuple(context.nodes[node]):
            raise ValueError("Native surface export changed original coordinates")
        values = tuple(field[node])
        if len(values) != 3 or not all(math.isfinite(value) for value in values):
            raise ValueError("Missing or nonfinite original nodal displacement")
        displacement.SetTuple(index, values)
    grid.GetPointData().AddArray(displacement)
    return grid


def _side(context, mesh, reference, vertex, field):
    from femresult.owned_probe import sample_surface

    selector = SimpleNamespace(Name="ContactObservation", References=[reference])
    nodes, members = meshtools._get_mesh_region_by_owned_references(
        context.femmesh, selector, mesh, context
    )
    if not members or not nodes:
        raise ValueError("Independently owned native face groups are required")
    point = tuple(vertex.Point)
    # This is an original native Vertex query plus a numerical equality check,
    # not a nearest-node search or a CAD vertex-tolerance acceptance rule.
    candidates = sorted(set(context.femmesh.getNodesByVertex(vertex)).intersection(nodes))
    scale = max(1.0, *(abs(value) for value in point))
    bound = 128 * sys.float_info.epsilon * scale
    coincident = [
        node for node in candidates if math.dist(point, tuple(context.nodes[node])) <= bound
    ]
    if len(coincident) > 1:
        result = {"status": "AMBIGUOUS", "reason": "Multiple original nodes on one owned side"}
    elif len(coincident) == 1:
        node = coincident[0]
        if node not in field or not all(math.isfinite(value) for value in field[node]):
            result = {"status": "UNAVAILABLE", "reason": "Original nodal displacement is missing"}
        else:
            contributing = sorted(
                element
                for values in members.values()
                for element in values
                if node in context.elements[element]
            )
            result = {
                "status": "AVAILABLE",
                "method": "ORIGINAL_NODE",
                "value_mm": tuple(field[node]),
                "original_node_id": node,
                "source_element_ids": contributing,
                "source_node_ids": [node],
                "point_residual_mm": math.dist(point, tuple(context.nodes[node])),
                "roundoff_bound_mm": bound,
            }
    else:
        result = sample_surface(_surface_grid(context, nodes, members, field), point)
        result["method"] = "NATIVE_VTK_SURFACE"
    result["owned_face_entities"] = sorted(members)
    return result, set(nodes)


def _frame(face, point):
    uv = face.Surface.parameter(point)
    normal, tangents = face.normalAt(*uv), face.tangentAt(*uv)
    values = (*uv, *normal, *(value for tangent in tangents for value in tangent))
    if not all(math.isfinite(value) for value in values) or normal.Length == 0:
        raise ValueError("Native reference frame is unavailable at the declared point")
    return {
        "side": "slave",
        "native_uv": list(uv),
        "normal": list(normal),
        "tangents": [list(tangent) for tangent in tangents],
    }


def observe(obj):
    """Qualify all selected native contacts without changing physical inputs."""
    from femresult.contact_observation_source import load_source, validate_source

    selected = definition(obj)
    field, source = load_source(obj.Analysis, obj.Mesh, obj.AccountingResult)
    native_mesh = obj.Mesh.FemMesh
    tables = SimpleNamespace(
        femnodes_mesh=native_mesh.Nodes,
        femelement_table={
            element: tuple(native_mesh.getElementNodes(element)) for element in native_mesh.Volumes
        },
    )
    context = _OwnershipContext(native_mesh, obj.Mesh, tables)
    report = {
        "schema": SCHEMA,
        "units": "mm",
        "frame": "Global Cartesian; original reference geometry (not CDIS)",
        "definition": selected,
        "source": source,
        "contacts": [],
        "engineering_acceptance": False,
    }
    for contact in obj.Contacts:
        refs = list(contact.References)
        faces = [meshtools.sub_shape_at_global_placement(owner, names[0]) for owner, names in refs]
        if any(face.ShapeType != "Face" for face in faces):
            raise ValueError(f"{contact.Name}: contact references must resolve to native faces")
        ordinal = obj.SlaveVertex
        if ordinal < 1 or ordinal > len(faces[0].Vertexes):
            raise ValueError(f"{contact.Name}: selected existing slave vertex is unavailable")
        vertex = faces[0].Vertexes[ordinal - 1]
        row = {
            "contact": contact.Name,
            "point_mm": list(vertex.Point),
            "references_slave_then_master": [[owner.Name, list(names)] for owner, names in refs],
            "reference_frame": _frame(faces[0], vertex.Point),
        }
        slave, slave_nodes = _side(context, obj.Mesh, refs[0], vertex, field)
        master, master_nodes = _side(context, obj.Mesh, refs[1], vertex, field)
        if slave_nodes.intersection(master_nodes):
            raise ValueError(
                f"{contact.Name}: shared original nodes do not identify independent sides"
            )
        row.update(
            slave=slave,
            master=master,
            status=(
                "AVAILABLE" if slave["status"] == master["status"] == "AVAILABLE" else "UNAVAILABLE"
            ),
        )
        report["contacts"].append(row)
    context.validate_unchanged()
    if definition(obj) != selected:
        raise ValueError("Contact selection changed during observation")
    current = validate_source(obj.Analysis, obj.Mesh, obj.AccountingResult)
    if any(source.get(key) != value for key, value in current.items()):
        raise ValueError("Native source changed during observation")
    report["status"] = (
        "AVAILABLE"
        if all(row["status"] == "AVAILABLE" for row in report["contacts"])
        else "UNAVAILABLE"
    )
    return report


def validate_observation(obj, report):
    """Revalidate external bytes and physical inputs on every qualified read."""
    from femresult.contact_observation_source import validate_source

    if report.get("schema") != SCHEMA or report.get("status") != "AVAILABLE":
        raise ValueError("Observation does not contain all requested available samples")
    if report.get("definition") != definition(obj):
        raise ValueError("Observation selection changed; refresh required")
    current = validate_source(obj.Analysis, obj.Mesh, obj.AccountingResult)
    if any(report.get("source", {}).get(key) != value for key, value in current.items()):
        raise ValueError("Observation source changed; refresh required")


def data_digest(data):
    return hashlib.sha256(data.encode("utf-8")).hexdigest()
