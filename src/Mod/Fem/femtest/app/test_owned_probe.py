# SPDX-License-Identifier: LGPL-2.1-or-later

"""Native VTK owner-restricted sampling, with independently known fields."""

import math
import unittest

try:
    from vtkmodules.vtkCommonCore import reference, vtkDoubleArray, vtkIdTypeArray, vtkPoints
    from vtkmodules.vtkCommonDataModel import (
        vtkPolyData,
        vtkQuad,
        vtkQuadraticQuad,
        vtkQuadraticTriangle,
        vtkTriangle,
        vtkUnstructuredGrid,
    )
    from vtkmodules.vtkFiltersCore import vtkProbeFilter
except ImportError:
    HAS_VTK = False
else:
    HAS_VTK = True


def surface(points, cells, values, point_ids=None, element_ids=None):
    grid = vtkUnstructuredGrid()
    coordinates = vtkPoints()
    coordinates.SetDataTypeToDouble()
    for point in points:
        coordinates.InsertNextPoint(point)
    grid.SetPoints(coordinates)
    for kind, indices in cells:
        cell = kind()
        for index, point_index in enumerate(indices):
            cell.GetPointIds().SetId(index, point_index)
        grid.InsertNextCell(cell.GetCellType(), cell.GetPointIds())
    for name, data, field in (
        ("FreeCADNodeId", point_ids or range(101, 101 + len(points)), grid.GetPointData()),
        ("FreeCADElementId", element_ids or range(7001, 7001 + len(cells)), grid.GetCellData()),
    ):
        array = vtkIdTypeArray()
        array.SetName(name)
        for value in data:
            array.InsertNextValue(value)
        field.AddArray(array)
    if values is not None:
        displacement = vtkDoubleArray()
        displacement.SetName("Displacement")
        displacement.SetNumberOfComponents(3)
        for value in values:
            displacement.InsertNextTuple(value)
        grid.GetPointData().AddArray(displacement)
    return grid


@unittest.skipUnless(HAS_VTK, "VTK Python support is not available in this build")
class TestOwnedProbe(unittest.TestCase):
    def test_triangle_interior_retains_vector_components_and_original_ids(self):
        from femresult.owned_probe import sample_surface

        grid = surface(
            [(0, 0, 0), (2, 0, 0), (0, 2, 0)],
            [(vtkTriangle, [0, 1, 2])],
            [(0, 0, 2), (2, 6, 2), (4, -2, 2)],
            point_ids=[11, 31, 97],
            element_ids=[100003],
        )
        result = sample_surface(grid, (0.5, 0.5, 0))
        self.assertEqual(result["status"], "AVAILABLE", result)
        self.assertEqual(result["value_mm"], (1.5, 1.0, 2.0))
        self.assertEqual(result["source_element_ids"], (100003,))
        self.assertEqual(result["source_node_ids"], (11, 31, 97))

    def test_malformed_source_never_becomes_available_or_zero(self):
        from femresult.owned_probe import sample_surface

        def triangle():
            return surface(
                [(0, 0, 0), (2, 0, 0), (0, 2, 0)], [(vtkTriangle, [0, 1, 2])], [(0, 0, 0)] * 3
            )

        cases = []
        grid = triangle()
        grid.GetPointData().RemoveArray("Displacement")
        cases.append(grid)
        grid = triangle()
        grid.GetPointData().GetArray("Displacement").SetNumberOfTuples(2)
        cases.append(grid)
        grid = triangle()
        grid.GetPointData().GetArray("Displacement").SetTuple3(1, math.nan, 0, 0)
        cases.append(grid)
        grid = triangle()
        grid.GetPointData().GetArray("FreeCADNodeId").SetValue(1, 101)
        cases.append(grid)
        grid = triangle()
        grid.GetCellData().GetArray("FreeCADElementId").SetNumberOfTuples(0)
        cases.append(grid)
        for index, grid in enumerate(cases):
            with self.subTest(index=index):
                result = sample_surface(grid, (0.5, 0.5, 0))
                self.assertEqual(result["status"], "UNAVAILABLE", result)
                self.assertNotIn("value_mm", result)

    def test_connected_edge_and_vertex_are_single_consistent_traces(self):
        from femresult.owned_probe import sample_surface

        grid = surface(
            [(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)],
            [(vtkTriangle, [0, 1, 2]), (vtkTriangle, [0, 2, 3])],
            [(0, 0, 2), (2, 6, 2), (6, 4, 2), (4, -2, 2)],
        )
        for point, expected in [((1, 1, 0), (3, 2, 2)), ((0, 0, 0), (0, 0, 2))]:
            with self.subTest(point=point):
                result = sample_surface(grid, point)
                self.assertEqual(result["status"], "AVAILABLE", result)
                self.assertEqual(result["value_mm"], expected)
                self.assertEqual(result["source_element_ids"], (7001, 7002))

    def test_affine_native_surface_types_include_negative_quadratic_weights(self):
        from femresult.owned_probe import sample_surface

        cases = [
            (
                vtkQuad,
                [(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)],
                [(0, 0, 2), (2, 6, 2), (6, 4, 2), (4, -2, 2)],
            ),
            (
                vtkQuadraticTriangle,
                [(0, 0, 0), (2, 0, 0), (0, 2, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
                [(0, 0, 2), (2, 6, 2), (4, -2, 2), (1, 3, 2), (3, 2, 2), (2, -1, 2)],
            ),
            (
                vtkQuadraticQuad,
                [
                    (0, 0, 0),
                    (2, 0, 0),
                    (2, 2, 0),
                    (0, 2, 0),
                    (1, 0, 0),
                    (2, 1, 0),
                    (1, 2, 0),
                    (0, 1, 0),
                ],
                [
                    (0, 0, 2),
                    (2, 6, 2),
                    (6, 4, 2),
                    (4, -2, 2),
                    (1, 3, 2),
                    (4, 5, 2),
                    (5, 1, 2),
                    (2, -1, 2),
                ],
            ),
        ]
        for kind, points, values in cases:
            grid = surface(points, [(kind, list(range(len(points))))], values)
            for point, expected in [
                ((0.5, 0.5, 0), (1.5, 1, 2)),
                ((0.5, 0, 0), (0.5, 1.5, 2)),
                ((0, 0, 0), (0, 0, 2)),
            ]:
                with self.subTest(kind=kind.__name__, point=point):
                    result = sample_surface(grid, point)
                    self.assertEqual(result["status"], "AVAILABLE", result)
                    for actual, wanted in zip(result["value_mm"], expected):
                        self.assertAlmostEqual(actual, wanted, places=12)
            if kind != vtkQuad:
                weights = [0.0] * len(points)
                grid.GetCell(0).EvaluatePosition(
                    (0.5, 0.5, 0), [0.0] * 3, reference(0), [0.0] * 3, reference(0.0), weights
                )
                self.assertLess(min(weights), 0, "Exercise legitimate quadratic weights")

    def test_outside_point_rejected_even_when_permissive_native_probe_is_valid(self):
        from femresult.owned_probe import sample_surface

        grid = surface(
            [(0, 0, 0), (2, 0, 0), (0, 2, 0)], [(vtkTriangle, [0, 1, 2])], [(0, 0, 0)] * 3
        )
        point = (1, 1.00001, 0)  # Inside bounds, outside the triangular parametric domain.
        coordinates = vtkPoints()
        coordinates.SetDataTypeToDouble()
        coordinates.InsertNextPoint(point)
        probe_points = vtkPolyData()
        probe_points.SetPoints(coordinates)
        probe = vtkProbeFilter()
        probe.SetInputData(probe_points)
        probe.SetSourceData(grid)
        probe.ComputeToleranceOff()
        probe.SetTolerance(0.01)  # Existing DataAtPoint's permissive setting.
        probe.SnapToCellWithClosestPointOff()
        probe.Update()
        self.assertEqual(
            probe.GetOutput().GetPointData().GetArray("vtkValidPointMask").GetTuple1(0), 1
        )
        for outside in (point, (0.5, 0.5, 0.00001), (5, 5, 0)):
            with self.subTest(point=outside):
                result = sample_surface(grid, outside)
                self.assertEqual(result["status"], "UNAVAILABLE", result)
                self.assertNotIn("value_mm", result)

    def test_independent_coincident_owners_stay_distinct_and_combination_is_ambiguous(self):
        from femresult.owned_probe import sample_surface

        points = [(0, 0, 0), (2, 0, 0), (0, 2, 0)]
        for offset in (0, 100):
            grid = surface(points, [(vtkTriangle, [0, 1, 2])], [(offset, offset, offset)] * 3)
            result = sample_surface(grid, (0.5, 0.5, 0))
            self.assertEqual(result["status"], "AVAILABLE", result)
            self.assertEqual(result["value_mm"], (offset, offset, offset))
        for other in (0, 100):
            combined = surface(
                points + points,
                [(vtkTriangle, [0, 1, 2]), (vtkTriangle, [3, 4, 5])],
                [(0, 0, 0)] * 3 + [(other, other, other)] * 3,
            )
            result = sample_surface(combined, (0.5, 0.5, 0))
            self.assertEqual(result["status"], "AMBIGUOUS", result)
            self.assertNotIn("value_mm", result)
            self.assertTrue(all("value_mm" not in row for row in result["native_locations"]))

    def test_duplicate_topology_and_original_ids_are_rejected(self):
        from femresult.owned_probe import sample_surface

        points = [(0, 0, 0), (2, 0, 0), (0, 2, 0), (2, 2, 0)]
        for cells, element_ids in [
            ([(vtkTriangle, [0, 1, 2]), (vtkTriangle, [2, 1, 0])], [7, 9]),
            ([(vtkTriangle, [0, 1, 2]), (vtkTriangle, [1, 3, 2])], [7, 7]),
        ]:
            grid = surface(points, cells, [(0, 0, 0)] * 4, element_ids=element_ids)
            result = sample_surface(grid, (0.5, 0.5, 0))
            self.assertEqual(result["status"], "UNAVAILABLE", result)
            self.assertNotIn("value_mm", result)

    def test_sparse_int64_ids_are_not_rounded_through_double(self):
        from femresult.owned_probe import sample_surface

        ids = [2**53 + 1, 2**53 + 3, 2**53 + 7]
        grid = surface(
            [(0, 0, 0), (2, 0, 0), (0, 2, 0)],
            [(vtkTriangle, [0, 1, 2])],
            [(0, 0, 0)] * 3,
            point_ids=ids,
            element_ids=[2**53 + 101],
        )
        result = sample_surface(grid, (0.5, 0.5, 0))
        self.assertEqual(result["status"], "AVAILABLE", result)
        self.assertEqual(result["source_node_ids"], tuple(ids))
        self.assertEqual(result["source_element_ids"], (2**53 + 101,))

    def test_curved_geometry_cannot_be_replaced_by_planar_projection(self):
        from femresult.owned_probe import sample_surface

        grid = surface(
            [(0, 0, 0), (2, 0, 0), (0, 2, 0), (1, 0, 0.2), (1, 1, 0), (0, 1, 0)],
            [(vtkQuadraticTriangle, [0, 1, 2, 3, 4, 5])],
            [(0, 0, 0)] * 6,
        )
        result = sample_surface(grid, (0.5, 0.5, 0))
        self.assertEqual(result["status"], "UNAVAILABLE", result)
        self.assertNotIn("value_mm", result)

    def test_noninvertible_cell_cannot_be_hidden_behind_another_valid_candidate(self):
        from femresult.owned_probe import sample_surface

        grid = surface(
            [(0, 0, 0), (2, 0, 0), (0, 2, 0), (1, 0, 0)],
            [(vtkTriangle, [0, 1, 2]), (vtkTriangle, [0, 1, 3])],
            [(0, 0, 0)] * 4,
        )
        result = sample_surface(grid, (0.5, 0.5, 0))
        self.assertEqual(result["status"], "UNAVAILABLE", result)
        self.assertNotIn("value_mm", result)

    def test_sparse_unused_native_point_slots_are_not_mesh_nodes(self):
        from femresult.owned_probe import sample_surface

        points = [(0, 0, 0), (0, 0, 0), (2, 0, 0), (0, 0, 0), (0, 2, 0)]
        grid = surface(
            points, [(vtkTriangle, [0, 2, 4])], [(0, 0, 0)] * 5, point_ids=[11, -1, 31, -1, 97]
        )
        result = sample_surface(grid, (0.5, 0.5, 0))
        self.assertEqual(result["status"], "AVAILABLE", result)
        self.assertEqual(result["source_node_ids"], (11, 31, 97))
        self.assertEqual(result["value_mm"], (0, 0, 0))
        grid = surface(
            points, [(vtkTriangle, [1, 2, 4])], [(0, 0, 0)] * 5, point_ids=[11, -1, 31, -1, 97]
        )
        result = sample_surface(grid, (0.5, 0.5, 0))
        self.assertEqual(result["status"], "UNAVAILABLE", result)
        self.assertNotIn("value_mm", result)

    def test_shared_quadratic_edge_requires_all_original_trace_ids(self):
        from femresult.owned_probe import sample_surface

        points = [
            (0, 0, 0),
            (2, 0, 0),
            (2, 2, 0),
            (1, 0, 0),
            (2, 1, 0),
            (1, 1, 0),
            (0, 2, 0),
            (1, 2, 0),
            (0, 1, 0),
        ]
        cells = [
            (vtkQuadraticTriangle, [0, 1, 2, 3, 4, 5]),
            (vtkQuadraticTriangle, [0, 2, 6, 5, 7, 8]),
        ]
        result = sample_surface(surface(points, cells, [(0, 0, 0)] * 9), (1, 1, 0))
        self.assertEqual(result["status"], "AVAILABLE", result)
        self.assertEqual(result["value_mm"], (0, 0, 0))
        # Same geometric edge and corners, but an independent midside degree of
        # freedom: not a conforming shared native trace, even with zero fields.
        cells[1] = (vtkQuadraticTriangle, [0, 2, 6, 9, 7, 8])
        for value in ((0, 0, 0), (1, 2, 3)):
            grid = surface(points + [(1, 1, 0)], cells, [(0, 0, 0)] * 9 + [value])
            result = sample_surface(grid, (1, 1, 0))
            self.assertEqual(result["status"], "AMBIGUOUS", result)
            self.assertNotIn("value_mm", result)

    def test_rotated_translated_affine_surface_and_spatial_outside_guard(self):
        from femresult.owned_probe import sample_surface

        def placed(x, y, offset=0):
            # Orthogonal unit directions (1,2,2)/3 and (2,1,-2)/3.
            return (
                1000 + x / 3 + 2 * y / 3 - 2 * offset / 3,
                -2000 + 2 * x / 3 + y / 3 + 2 * offset / 3,
                77 + 2 * x / 3 - 2 * y / 3 - offset / 3,
            )

        grid = surface(
            [placed(0, 0), placed(2, 0), placed(0, 2)],
            [(vtkTriangle, [0, 1, 2])],
            [(0, 0, 2), (2, 6, 2), (4, -2, 2)],
        )
        result = sample_surface(grid, placed(0.5, 0.5))
        self.assertEqual(result["status"], "AVAILABLE", result)
        for actual, expected in zip(result["value_mm"], (1.5, 1, 2)):
            self.assertAlmostEqual(actual, expected, places=10)
        self.assertLess(result["native_locations"][0]["roundoff_bound_mm"], 1e-9)
        result = sample_surface(grid, placed(0.5, 0.5, 0.00001))
        self.assertEqual(result["status"], "UNAVAILABLE", result)
        self.assertNotIn("value_mm", result)

    def test_invalid_queries_and_source_layouts_are_explicitly_unavailable(self):
        from femresult.owned_probe import sample_surface

        def triangle():
            return surface(
                [(0, 0, 0), (2, 0, 0), (0, 2, 0)], [(vtkTriangle, [0, 1, 2])], [(0, 0, 0)] * 3
            )

        for point in (None, (1, 2), (1, 2, 3, 4), (math.inf, 0, 0), (math.nan, 0, 0)):
            result = sample_surface(triangle(), point)
            self.assertEqual(result["status"], "UNAVAILABLE", result)
            self.assertNotIn("value_mm", result)
        cases = [None, object(), vtkUnstructuredGrid()]
        grid = triangle()
        grid.GetPoints().SetDataTypeToFloat()
        cases.append(grid)
        grid = triangle()
        grid.GetPoints().SetPoint(0, math.inf, 0, 0)
        cases.append(grid)
        grid = triangle()
        ids = vtkDoubleArray()
        ids.SetName("FreeCADNodeId")
        for value in (11.0, 31.0, 97.0):
            ids.InsertNextValue(value)
        grid.GetPointData().AddArray(ids)
        cases.append(grid)
        grid = triangle()
        grid.GetPointData().GetArray("Displacement").SetNumberOfComponents(1)
        cases.append(grid)
        grid = surface(
            [(0, 0, 0), (2, 0, 0), (0, 2, 0)], [(vtkTriangle, [0, 1, 999])], [(0, 0, 0)] * 3
        )
        cases.append(grid)
        for index, grid in enumerate(cases):
            with self.subTest(index=index):
                result = sample_surface(grid, (0.5, 0.5, 0))
                self.assertEqual(result["status"], "UNAVAILABLE", result)
                self.assertNotIn("value_mm", result)
