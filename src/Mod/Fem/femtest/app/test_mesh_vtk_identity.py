# SPDX-License-Identifier: LGPL-2.1-or-later

"""Native mesh export retains original identity, precision, and connectivity."""

import tempfile
import unittest
from pathlib import Path

try:
    import vtk
except ImportError:
    vtk = None

import Fem


@unittest.skipUnless(vtk is not None, "VTK Python wrappers required")
class TestMeshVTKIdentity(unittest.TestCase):
    def setUp(self):
        try:
            Fem.FemMesh().toVTK()
        except NotImplementedError:
            self.skipTest("Native VTK Python export disabled in this build")

    def test_sparse_coincident_faces_keep_original_ids_and_double_coordinates(self):
        mesh = Fem.FemMesh()
        points = ((0.123456789012345, 0, 0), (1, 0, 0), (0, 1, 0))
        for node_ids in ((1, 4, 9), (11, 14, 19)):
            for node_id, point in zip(node_ids, points):
                mesh.addNode(*point, node_id)
        mesh.addFace([1, 4, 9], 731)
        mesh.addFace([11, 14, 19], 218)

        grid = mesh.toVTK()
        self.assertIsInstance(grid, vtk.vtkUnstructuredGrid)
        self.assertEqual(grid.GetPoints().GetDataType(), vtk.VTK_DOUBLE)
        self.assertEqual(grid.GetNumberOfPoints(), 19)
        self.assertEqual(grid.GetNumberOfCells(), 2)
        node_ids = grid.GetPointData().GetArray("FreeCADNodeId")
        element_ids = grid.GetCellData().GetArray("FreeCADElementId")
        self.assertIsNotNone(node_ids)
        self.assertIsNotNone(element_ids)
        actual_nodes = {1, 4, 9, 11, 14, 19}
        for index in range(19):
            expected_id = index + 1 if index + 1 in actual_nodes else -1
            self.assertEqual(node_ids.GetValue(index), expected_id)
        self.assertEqual(grid.GetPoint(0), points[0])
        self.assertEqual(grid.GetPoint(10), points[0])
        connectivity = {}
        for index in range(2):
            cell = grid.GetCell(index)
            self.assertEqual(cell.GetCellType(), vtk.VTK_TRIANGLE)
            connectivity[element_ids.GetValue(index)] = tuple(
                node_ids.GetValue(cell.GetPointId(local)) for local in range(3)
            )
        self.assertEqual(connectivity, {731: (1, 4, 9), 218: (11, 14, 19)})

        # The exported grid is independently mutable, not a view into FemMesh.
        grid.GetPoints().SetPoint(0, 99, 98, 97)
        self.assertEqual(tuple(mesh.getNodeById(1)), points[0])
        self.assertEqual(mesh.toVTK().GetPoint(0), points[0])

    def test_linear_and_quadratic_cells_retain_native_vtk_order(self):
        # These literal node orders are the native SMESH-to-VTK contract.
        # In particular tetrahedra are not exported in addVolume input order.
        triangle = ((0, 0, 0), (2, 0, 0), (0, 2, 0))
        tri6 = triangle + ((1, 0, 0), (1, 1, 0), (0, 1, 0))
        quad = ((0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0))
        quad8 = quad + ((1, 0, 0), (2, 1, 0), (1, 2, 0), (0, 1, 0))
        tetra = triangle + ((0, 0, 2),)
        tet10 = tetra + ((1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (0, 1, 1))
        native_ids = (11, 17, 29, 31, 37, 41, 43, 47, 53, 59)
        cases = (
            ("tri3", triangle, False, vtk.VTK_TRIANGLE, (11, 17, 29)),
            ("tri6", tri6, False, vtk.VTK_QUADRATIC_TRIANGLE, (11, 17, 29, 31, 37, 41)),
            ("quad4", quad, False, vtk.VTK_QUAD, (11, 17, 29, 31)),
            ("quad8", quad8, False, vtk.VTK_QUADRATIC_QUAD, (11, 17, 29, 31, 37, 41, 43, 47)),
            ("tet4", tetra, True, vtk.VTK_TETRA, (11, 29, 17, 31)),
            (
                "tet10",
                tet10,
                True,
                vtk.VTK_QUADRATIC_TETRA,
                (11, 29, 17, 31, 43, 41, 37, 47, 59, 53),
            ),
        )
        for name, points, volume, kind, expected in cases:
            with self.subTest(cell=name):
                mesh = Fem.FemMesh()
                ids = native_ids[: len(points)]
                for node_id, point in zip(ids, points):
                    mesh.addNode(*point, node_id)
                if volume:
                    mesh.addVolume(list(ids), 853)
                else:
                    mesh.addFace(list(ids), 853)
                grid = mesh.toVTK()
                self.assertEqual(grid.GetNumberOfCells(), 1)
                self.assertEqual(grid.GetCellType(0), kind)
                self.assertEqual(grid.GetCellData().GetArray("FreeCADElementId").GetValue(0), 853)
                cell = grid.GetCell(0)
                node_ids = grid.GetPointData().GetArray("FreeCADNodeId")
                self.assertEqual(
                    tuple(node_ids.GetValue(cell.GetPointId(i)) for i in range(len(points))),
                    expected,
                )
                for node_id, point in zip(ids, points):
                    self.assertEqual(grid.GetPoint(node_id - 1), point)

    def test_highest_dimension_selection_and_all_dimension_ids(self):
        mesh = Fem.FemMesh()
        for node_id, point in enumerate(((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)), 1):
            mesh.addNode(*point, node_id)
        mesh.addEdge([1, 2], 901)
        mesh.addFace([1, 2, 3], 607)
        mesh.addVolume([1, 2, 3, 4], 413)

        highest = mesh.toVTK()
        self.assertEqual(highest.GetNumberOfCells(), 1)
        self.assertEqual(highest.GetCellType(0), vtk.VTK_TETRA)
        self.assertEqual(highest.GetCellData().GetArray("FreeCADElementId").GetValue(0), 413)
        all_cells = mesh.toVTK(highest=False)
        self.assertEqual(all_cells.GetNumberOfCells(), 3)
        ids = all_cells.GetCellData().GetArray("FreeCADElementId")
        self.assertEqual(tuple(ids.GetValue(i) for i in range(3)), (901, 607, 413))
        self.assertEqual(
            tuple(all_cells.GetCellType(i) for i in range(3)),
            (vtk.VTK_LINE, vtk.VTK_TRIANGLE, vtk.VTK_TETRA),
        )

    def test_each_export_is_detached_from_mesh_and_previous_export(self):
        mesh = Fem.FemMesh()
        mesh.addNode(0.123456789012345, 0, 0, 1)
        mesh.addNode(1, 0, 0, 2)
        mesh.addNode(0, 1, 0, 3)
        mesh.addFace([1, 2, 3], 211)
        first = mesh.toVTK()
        second = mesh.toVTK()
        first.GetPoints().SetPoint(0, 9, 8, 7)
        first.GetPointData().GetArray("FreeCADNodeId").SetValue(0, -1)
        first.GetCellData().GetArray("FreeCADElementId").SetValue(0, -1)
        self.assertEqual(second.GetPoint(0), (0.123456789012345, 0, 0))
        self.assertEqual(second.GetPointData().GetArray("FreeCADNodeId").GetValue(0), 1)
        self.assertEqual(second.GetCellData().GetArray("FreeCADElementId").GetValue(0), 211)
        mesh.addNode(0, 0, 1, 4)
        mesh.addVolume([1, 2, 3, 4], 307)
        self.assertEqual(second.GetNumberOfPoints(), 3)
        self.assertEqual(second.GetCellType(0), vtk.VTK_TRIANGLE)
        self.assertEqual(mesh.toVTK().GetCellType(0), vtk.VTK_TETRA)

    def test_empty_mesh_has_explicit_empty_identity_arrays(self):
        grid = Fem.FemMesh().toVTK()
        self.assertEqual(grid.GetNumberOfPoints(), 0)
        self.assertEqual(grid.GetNumberOfCells(), 0)
        self.assertEqual(grid.GetPoints().GetDataType(), vtk.VTK_DOUBLE)
        self.assertEqual(grid.GetPointData().GetArray("FreeCADNodeId").GetNumberOfTuples(), 0)
        self.assertEqual(grid.GetCellData().GetArray("FreeCADElementId").GetNumberOfTuples(), 0)

    def test_legacy_file_export_does_not_gain_identity_or_precision_changes(self):
        mesh = Fem.FemMesh()
        for node_id, point in enumerate(((0, 0, 0), (1, 0, 0), (0, 1, 0)), 1):
            mesh.addNode(*point, node_id)
        mesh.addFace([1, 2, 3], 211)
        exported = mesh.toVTK()
        self.assertEqual(exported.GetPoints().GetDataType(), vtk.VTK_DOUBLE)
        with tempfile.TemporaryDirectory(prefix="freecad-mesh-vtk-identity-") as directory:
            path = Path(directory) / "legacy.vtu"
            mesh.write(str(path))
            reader = vtk.vtkXMLUnstructuredGridReader()
            reader.SetFileName(str(path))
            reader.Update()
            legacy = reader.GetOutput()
            self.assertEqual(legacy.GetPoints().GetDataType(), vtk.VTK_FLOAT)
            self.assertIsNone(legacy.GetPointData().GetArray("FreeCADNodeId"))
            self.assertIsNone(legacy.GetCellData().GetArray("FreeCADElementId"))
