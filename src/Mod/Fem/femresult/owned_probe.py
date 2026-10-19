# SPDX-License-Identifier: LGPL-2.1-or-later

"""Sample a caller-validated, owner-restricted native surface dataset.

Ownership, source-result provenance, units (mm), and the declared physical
point belong to the caller. This adapter uses native VTK cell location/interpolation;
it does not construct shape functions, move a point, or recover missing U.
"""

import math
import sys
from itertools import combinations

from vtkmodules.vtkCommonCore import VTK_DOUBLE, reference, vtkIdList
from vtkmodules.vtkCommonDataModel import vtkPointData
from vtkmodules.vtkFiltersCore import vtkExtractCells


def _unavailable(reason):
    return {
        "status": "UNAVAILABLE",
        "reason": reason,
        "source_element_ids": (),
        "source_node_ids": (),
        "native_locations": [],
    }


def _original_ids(array, count, allow_gaps=False):
    if (
        array is None
        or array.GetNumberOfComponents() != 1
        or array.GetNumberOfTuples() != count
        or not hasattr(array, "GetValue")
    ):
        return None
    values = tuple(array.GetValue(index) for index in range(count))
    if any(
        not isinstance(value, int) or (value <= 0 and not (allow_gaps and value == -1))
        for value in values
    ):
        return None
    positive = [value for value in values if value > 0]
    if len(set(positive)) != len(positive):
        return None
    return values


def _copy_cell(dataset, index):
    # GetCell may return storage reused by later native filter iteration.
    cell = dataset.GetCell(index).NewInstance()
    cell.DeepCopy(dataset.GetCell(index))
    return cell


def _shared_trace(dataset, first, second, point, nodes):
    cells = [_copy_cell(dataset, row["_cell_index"]) for row in (first, second)]
    corners = [
        set(nodes[cell.GetPointId(i)] for i in range(cell.GetNumberOfEdges())) for cell in cells
    ]
    bound = max(first["roundoff_bound_mm"], second["roundoff_bound_mm"])
    for node in corners[0] & corners[1]:
        if math.dist(point, dataset.GetPoint(nodes.index(node))) <= bound:
            return True
    edges = []
    for cell in cells:
        mapping = {}
        for index in range(cell.GetNumberOfEdges()):
            edge = cell.GetEdge(index)
            key = frozenset(nodes[edge.GetPointId(i)] for i in range(edge.GetNumberOfPoints()))
            copied = edge.NewInstance()
            copied.DeepCopy(edge)
            mapping[key] = copied
        edges.append(mapping)
    for key in edges[0].keys() & edges[1].keys():
        for mapping in edges:
            edge = mapping[key]
            closest, pcoords, world = [0.0] * 3, [0.0] * 3, [0.0] * 3
            sub_id, distance = reference(0), reference(0.0)
            weights = [0.0] * edge.GetNumberOfPoints()
            inside = edge.EvaluatePosition(point, closest, sub_id, pcoords, distance, weights)
            edge.EvaluateLocation(sub_id, pcoords, world, weights)
            parametric = edge.GetParametricDistance(pcoords)
            if (
                inside != 1
                or not all(
                    math.isfinite(value)
                    for value in (*pcoords, *world, parametric, float(distance))
                )
                or parametric > 128 * sys.float_info.epsilon
                or math.dist(point, world) > bound
            ):
                break
        else:
            return True
    return False


def sample_surface(dataset, point):
    """Return native XYZ, or explicit unavailability/ambiguity, without snapping.

    Required arrays are FreeCADNodeId, FreeCADElementId, and three-component
    Displacement. Original IDs must refer to the exact source mesh, not VTK
    indices. Sparse native point slots may carry -1 only when unused by every
    cell; they are never sampled or returned as nodes. Numerical guards use
    128 double epsilons times max(1 mm, absolute query/cell coordinates), and
    128 epsilons in native parametric coordinates. Multiple trace vectors must
    agree within 128 epsilons times their contributing nodal field scale, with
    no displacement floor. These conservative arithmetic guards are not CAD
    tolerances, movement criteria, or a guarantee of arbitrary cell accuracy.
    Affine planar Tri3/Quad4/Tri6/Quad8 are qualified; native inverse/reconstruction
    failure for other geometry remains unavailable, never a nearest projection.
    """
    if dataset is None or not hasattr(dataset, "IsA") or not dataset.IsA("vtkUnstructuredGrid"):
        return _unavailable("A native unstructured surface dataset is required")
    try:
        point = tuple(float(value) for value in point)
    except (TypeError, ValueError, OverflowError):
        return _unavailable("The declared point is invalid")
    if len(point) != 3 or not all(math.isfinite(value) for value in point):
        return _unavailable("The declared point must have three finite coordinates")
    point_count, cell_count = dataset.GetNumberOfPoints(), dataset.GetNumberOfCells()
    if not point_count or not cell_count:
        return _unavailable("The owned surface dataset is empty")
    nodes = _original_ids(
        dataset.GetPointData().GetArray("FreeCADNodeId"), point_count, allow_gaps=True
    )
    elements = _original_ids(dataset.GetCellData().GetArray("FreeCADElementId"), cell_count)
    values = dataset.GetPointData().GetArray("Displacement")
    if nodes is None or elements is None or values is None:
        return _unavailable("Required original IDs or displacement field are missing")
    if (
        values.GetNumberOfComponents() != 3
        or values.GetNumberOfTuples() != point_count
        or values.GetDataType() != VTK_DOUBLE
        or dataset.GetPoints().GetDataType() != VTK_DOUBLE
    ):
        return _unavailable("Complete double-precision coordinates and XYZ values are required")
    if not all(
        math.isfinite(value)
        for index in range(point_count)
        for value in (*dataset.GetPoint(index), *values.GetTuple(index))
    ):
        return _unavailable("A source coordinate or displacement is nonfinite")
    topologies = set()
    for index in range(cell_count):
        indices = vtkIdList()
        dataset.GetCellPoints(index, indices)
        connectivity = tuple(indices.GetId(i) for i in range(indices.GetNumberOfIds()))
        expected = {5: 3, 9: 4, 22: 6, 23: 8}.get(dataset.GetCellType(index))
        if (
            expected is None
            or len(connectivity) != expected
            or len(set(connectivity)) != expected
            or any(value < 0 or value >= point_count for value in connectivity)
        ):
            return _unavailable("Unsupported or invalid native surface-cell connectivity")
        if any(nodes[value] <= 0 for value in connectivity):
            return _unavailable("A native surface cell references an unused sparse point slot")
        topology = frozenset(connectivity)
        if topology in topologies:
            return _unavailable("Duplicate native surface-cell topology")
        topologies.add(topology)
    matches = []
    for index in range(cell_count):
        cell = _copy_cell(dataset, index)
        scale = max(
            1.0,
            *(abs(value) for value in point),
            *(
                abs(value)
                for i in range(cell.GetNumberOfPoints())
                for value in cell.GetPoints().GetPoint(i)
            )
        )
        bound = 128 * sys.float_info.epsilon * scale
        closest, pcoords = [0.0] * 3, [0.0] * 3
        sub_id, distance = reference(0), reference(0.0)
        weights = [0.0] * cell.GetNumberOfPoints()
        inside = cell.EvaluatePosition(point, closest, sub_id, pcoords, distance, weights)
        if inside < 0:
            return _unavailable("Native cell inversion failed; no alternate trace may conceal it")
        parametric = cell.GetParametricDistance(pcoords)
        world = [0.0] * 3
        cell.EvaluateLocation(sub_id, pcoords, world, weights)
        residual = math.dist(point, world)
        if (
            inside != 1
            or not all(
                math.isfinite(value)
                for value in (*pcoords, *world, *weights, parametric, residual, float(distance))
            )
            or parametric > 128 * sys.float_info.epsilon
            or residual > bound
        ):
            continue
        selected = vtkIdList()
        selected.InsertNextId(index)
        extract = vtkExtractCells()
        extract.SetInputData(dataset)
        extract.SetCellList(selected)
        extract.Update()
        source = extract.GetOutput()
        expected_nodes = tuple(nodes[cell.GetPointId(i)] for i in range(cell.GetNumberOfPoints()))
        extracted_nodes = _original_ids(
            source.GetPointData().GetArray("FreeCADNodeId"),
            source.GetNumberOfPoints(),
            allow_gaps=True,
        )
        extracted_elements = _original_ids(
            source.GetCellData().GetArray("FreeCADElementId"), source.GetNumberOfCells()
        )
        extracted_indices = vtkIdList()
        if source.GetNumberOfCells() == 1:
            source.GetCellPoints(0, extracted_indices)
        # VTK's all-cells fast path may retain unused native point slots. Only
        # cell connectivity establishes the extracted original-node set.
        extracted_connectivity = tuple(
            extracted_indices.GetId(i) for i in range(extracted_indices.GetNumberOfIds())
        )
        if (
            extracted_elements != (elements[index],)
            or extracted_nodes is None
            or any(value < 0 or value >= len(extracted_nodes) for value in extracted_connectivity)
            or tuple(extracted_nodes[value] for value in extracted_connectivity) != expected_nodes
        ):
            return _unavailable(
                "Native extraction did not preserve the exact requested original IDs"
            )
        # The native inverse/reconstruction guards above establish membership.
        # vtkProbeFilter adds an exact dataset-bounds intersection that can
        # reject a native forward-evaluated planar point by one double ULP.
        # Use its native field-interpolation operation directly, with the
        # exact native weights and verified extracted connectivity order.
        # Only the vector field is allocated: original integer IDs must never
        # be interpolated through a floating-point array.
        field_data = vtkPointData()
        field_data.AddArray(source.GetPointData().GetArray("Displacement"))
        output = vtkPointData()
        output.InterpolateAllocate(field_data, 1)
        output.InterpolatePoint(field_data, 0, extracted_indices, weights)
        field = output.GetArray("Displacement")
        if (
            field is None
            or field.GetNumberOfTuples() != 1
            or field.GetNumberOfComponents() != 3
            or field.GetDataType() != VTK_DOUBLE
            or not all(math.isfinite(value) for value in field.GetTuple(0))
        ):
            return _unavailable("A containing native cell has no valid finite native interpolation")
        matches.append(
            {
                "element_id": elements[index],
                "node_ids": expected_nodes,
                "_cell_index": index,
                "pcoords": tuple(pcoords),
                "parametric_distance": parametric,
                "spatial_residual_mm": residual,
                "roundoff_bound_mm": bound,
                "native_squared_distance_mm2": float(distance),
                "native_interpolation_method": "vtkDataSetAttributes.InterpolatePoint",
                "native_interpolation_valid": True,
                "value_mm": tuple(field.GetTuple(0)),
            }
        )
    if not matches:
        return _unavailable("No native surface cell contains the declared point")
    matches.sort(key=lambda row: row["element_id"])
    result = {
        "status": "AVAILABLE",
        "reason": "Native owner-restricted surface observation",
        "source_element_ids": tuple(row["element_id"] for row in matches),
        "source_node_ids": tuple(sorted({node for row in matches for node in row["node_ids"]})),
        "native_locations": [
            {key: value for key, value in row.items() if key not in ("_cell_index", "value_mm")}
            for row in matches
        ],
    }
    used_indices = {nodes.index(node) for row in matches for node in row["node_ids"]}
    vector_bound = (
        128
        * sys.float_info.epsilon
        * max(abs(value) for index in used_indices for value in values.GetTuple(index))
    )
    for first, second in combinations(matches, 2):
        if (
            not _shared_trace(dataset, first, second, point, nodes)
            or math.dist(first["value_mm"], second["value_mm"]) > vector_bound
        ):
            result.update(
                status="AMBIGUOUS", reason="Disconnected, overlapping or inconsistent native traces"
            )
            return result
    result["value_mm"] = matches[0]["value_mm"]
    return result
