# SPDX-License-Identifier: LGPL-2.1-or-later

import io
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import FreeCAD as App
import Fem
import ObjectsFem
import Part


class TestElasticConnector(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("ElasticConnector")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def connector(self):
        return ObjectsFem.makeConstraintElasticConnector(self.doc)

    def mesh_and_points(self):
        mesh = ObjectsFem.makeMeshGmsh(self.doc)
        data = Fem.FemMesh()
        points = []
        for index, point in enumerate(((0, 0, 0), (1, 0, 0)), 1):
            data.addNode(*point, index)
            obj = self.doc.addObject("Part::Feature", f"Point{index}")
            obj.Shape = Part.Vertex(App.Vector(*point))
            points.append(obj)
        mesh.FemMesh = data
        return mesh, points

    def configured(self):
        mesh, points = self.mesh_and_points()
        obj = self.connector()
        obj.End1 = (points[0], ["Vertex1"])
        obj.Mode = "Two points"
        obj.End2 = (points[1], ["Vertex1"])
        obj.Stiffness = "2 kN/mm"
        return obj, mesh, points

    def test_native_factory_and_zero_default(self):
        obj = self.connector()
        self.assertEqual(obj.getTypeIdOfProperty("Stiffness"), "App::PropertyStiffness")
        self.assertEqual(obj.Stiffness.getValueAs("N/mm").Value, 0)
        self.assertEqual(obj.Mode, "Ground")
        self.assertEqual(obj.Axis, "X")
        self.assertEqual(obj.getTypeIdOfProperty("End1"), "App::PropertyLinkSubGlobal")

    def test_resolves_native_vertices_and_converts_units(self):
        from femtools.elastic_connector import resolve_connector
        obj, mesh, _ = self.configured()
        data = resolve_connector(obj, mesh)
        self.assertEqual(data["nodes"], [1, 2])
        self.assertEqual(data["stiffness"], 2000)
        self.assertEqual(data["dof"], 1)

    def test_invalid_or_ambiguous_inputs_rejected(self):
        from femtools.elastic_connector import resolve_connector
        obj, mesh, points = self.configured()
        for stiffness in ("0 N/mm", "-1 N/mm"):
            obj.Stiffness = stiffness
            with self.assertRaises(ValueError):
                resolve_connector(obj, mesh)
        obj.Stiffness = "1 N/mm"
        obj.End2 = obj.End1
        with self.assertRaises(ValueError):
            resolve_connector(obj, mesh)
        obj.End2 = (points[1], ["Vertex1"])
        duplicate = Fem.FemMesh()
        duplicate.addNode(0, 0, 0, 1)
        duplicate.addNode(1, 0, 0, 2)
        duplicate.addNode(0, 0, 0, 99)
        mesh.FemMesh = duplicate
        with self.assertRaisesRegex(ValueError, "exactly one"):
            resolve_connector(obj, mesh)

    def test_changed_reference_regenerates_nodes(self):
        from femtools.elastic_connector import resolve_connector
        obj, mesh, points = self.configured()
        self.assertEqual(resolve_connector(obj, mesh)["nodes"], [1, 2])
        obj.End1, obj.End2 = obj.End2, obj.End1
        self.assertEqual(resolve_connector(obj, mesh)["nodes"], [2, 1])

    def test_remeshing_re_resolves_geometry_instead_of_retaining_node_ids(self):
        from femtools.elastic_connector import resolve_connector
        obj, mesh, _ = self.configured()
        data = Fem.FemMesh()
        data.addNode(0, 0, 0, 77)
        data.addNode(1, 0, 0, 42)
        mesh.FemMesh = data
        self.assertEqual(resolve_connector(obj, mesh)["nodes"], [77, 42])

    def test_endpoints_in_placed_parent_resolve_in_global_mesh_coordinates(self):
        from femtools.elastic_connector import resolve_connector
        obj, mesh, points = self.configured()
        parent = self.doc.addObject("App::Part", "PlacedAssembly")
        for point in points:
            parent.addObject(point)
        parent.Placement = App.Placement(App.Vector(10, 20, 30),
                                         App.Rotation(App.Vector(0, 0, 1), 90))
        obj.OrientationReference = parent
        data = Fem.FemMesh()
        data.addNode(10, 20, 30, 77)
        data.addNode(10, 21, 30, 42)
        mesh.FemMesh = data
        self.doc.recompute()
        result = resolve_connector(obj, mesh)
        self.assertEqual(result["nodes"], [77, 42])
        self.assertLess((result["rotation"].multVec(App.Vector(1, 0, 0))
                         - App.Vector(0, 1, 0)).Length, 1e-12)

    def test_long_export_names_are_bounded_and_element_ids_do_not_overlap(self):
        from femtools.elastic_connector import identifier
        from femsolver.calculix.write_constraint_elastic_connector import write_connectors
        first = identifier("EC_", SimpleNamespace(Name="A" * 100 + "X"))
        second = identifier("EC_", SimpleNamespace(Name="A" * 100 + "Y"))
        self.assertLessEqual(len(first), 80)
        self.assertNotEqual(first, second)
        obj, mesh, _ = self.configured()
        other = self.connector()
        other.Mode, other.End1, other.End2 = obj.Mode, obj.End1, obj.End2
        other.Stiffness = "300 N/mm"
        writer = SimpleNamespace(mesh_object=mesh, member=SimpleNamespace(
            cons_elasticconnector=[{"Object": obj}, {"Object": other}]))
        stream = io.StringIO()
        write_connectors(stream, writer)
        ids = re.findall(r"TYPE=SPRING2[^\n]*\n(\d+),", stream.getvalue())
        self.assertEqual(len(ids), 2)
        self.assertNotEqual(ids[0], ids[1])

    def test_wrong_region_missing_endpoint_and_ground_extra_endpoint_fail(self):
        from femtools.elastic_connector import resolve_connector
        obj, mesh, points = self.configured()
        obj.Mode = "Ground"
        with self.assertRaisesRegex(ValueError, "empty End2"):
            resolve_connector(obj, mesh)
        obj.End2 = None
        obj.End1 = None
        with self.assertRaises(ValueError):
            resolve_connector(obj, mesh)
        points[0].Shape = Part.makeLine(App.Vector(), App.Vector(1, 0, 0))
        obj.End1 = (points[0], ["Edge1"])
        with self.assertRaisesRegex(ValueError, "vertices"):
            resolve_connector(obj, mesh)

    def test_nonfinite_stiffness_and_nonplaced_orientation_reference_fail(self):
        from femtools.elastic_connector import resolve_connector
        obj, mesh, _ = self.configured()
        obj.OrientationReference = self.doc.addObject("App::FeaturePython", "NotPlaced")
        with self.assertRaisesRegex(ValueError, "placed"):
            resolve_connector(obj, mesh)
        obj.OrientationReference = None
        for value in (float("nan"), float("inf")):
            try:
                obj.Stiffness = value
            except (ValueError, OverflowError):
                continue
            with self.assertRaisesRegex(ValueError, "finite"):
                resolve_connector(obj, mesh)

    def test_suppressed_connector_and_other_exporters_fail_closed(self):
        from femsolver.elmer.writer import Writer as Elmer
        from femsolver.mystran.writer import FemInputWriterMystran as Mystran
        from femsolver.z88.writer import FemInputWriterZ88 as Z88
        from femtools.elastic_connector import connectors
        analysis = ObjectsFem.makeAnalysis(self.doc)
        obj = self.connector()
        analysis.addObject(obj)
        for writer_class in (Elmer, Mystran, Z88):
            with self.assertRaisesRegex(ValueError, "not supported"):
                writer_class.write_solver_input(SimpleNamespace(analysis=analysis))
        self.assertEqual(connectors(analysis), [obj])
        obj.Suppressed = True
        self.assertEqual(connectors(analysis), [])

    def test_unsupported_analysis_and_legacy_foundation_are_rejected(self):
        from femtools.elastic_connector import validation_errors
        obj, mesh, _ = self.configured()
        analysis = ObjectsFem.makeAnalysis(self.doc)
        solver = ObjectsFem.makeSolverCalculiXCcxTools(self.doc)
        analysis.addObject(obj)
        self.assertEqual(validation_errors(analysis, solver, mesh), [])
        for prop, value in (("AnalysisType", "frequency"), ("ModelSpace", "plane stress"),
                            ("GeometricalNonlinearity", True)):
            original = getattr(solver, prop)
            setattr(solver, prop, value)
            self.assertTrue(validation_errors(analysis, solver, mesh))
            setattr(solver, prop, original)
        material = ObjectsFem.makeMaterialSolid(self.doc)
        analysis.addObject(material)
        nonlinear = ObjectsFem.makeMaterialMechanicalNonlinear(self.doc, material)
        solver.MaterialNonlinearity = True
        self.assertTrue(validation_errors(analysis, solver, mesh))
        nonlinear.Suppressed = True
        self.assertEqual(validation_errors(analysis, solver, mesh), [])
        foundation = ObjectsFem.makeConstraintSpring(self.doc)
        analysis.addObject(foundation)
        self.assertTrue(any("Elmer foundation" in error
                            for error in validation_errors(analysis, solver, mesh)))

    def test_generated_node_set_collision_is_rejected(self):
        from femtools.elastic_connector import identifier
        from femtools.elastic_connector import validation_errors
        obj, mesh, _ = self.configured()
        analysis = ObjectsFem.makeAnalysis(self.doc)
        analysis.addObject(obj)
        solver = ObjectsFem.makeSolverCalculiXCcxTools(self.doc)
        conflict = ObjectsFem.makeConstraintFixed(self.doc, identifier("EC_END1_", obj))
        analysis.addObject(conflict)
        self.assertTrue(any("collides" in error
                            for error in validation_errors(analysis, solver, mesh)))

    def test_save_reopen_preserves_endpoints_and_local_frame(self):
        from femtools.elastic_connector import resolve_connector
        obj, mesh, _ = self.configured()
        parent = self.doc.addObject("App::Part", "Parent")
        source = self.doc.addObject("Part::Feature", "SourceFrame")
        frame = self.doc.addObject("App::Link", "Frame")
        frame.setLink(source)
        parent.addObject(frame)
        parent.Placement.Rotation = App.Rotation(App.Vector(0, 0, 1), 30)
        frame.Placement.Rotation = App.Rotation(App.Vector(0, 0, 1), 60)
        obj.OrientationReference = frame
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "connector.FCStd")
            self.doc.saveAs(path)
            obj_name, mesh_name = obj.Name, mesh.Name
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(path)
            obj, mesh = self.doc.getObject(obj_name), self.doc.getObject(mesh_name)
            data = resolve_connector(obj, mesh)
            self.assertEqual(data["nodes"], [1, 2])
            self.assertLess((data["rotation"].multVec(App.Vector(1, 0, 0))
                             - App.Vector(0, 1, 0)).Length, 1e-12)

    def test_stock_export_includes_spring_element_orientation_and_decimal_stiffness(self):
        from femsolver.calculix.write_constraint_elastic_connector import write_connectors
        obj, mesh, _ = self.configured()
        writer = SimpleNamespace(mesh_object=mesh, member=SimpleNamespace(
            cons_elasticconnector=[{"Object": obj}]))
        stream = io.StringIO()
        write_connectors(stream, writer)
        text = stream.getvalue()
        self.assertIn("TYPE=SPRING2", text)
        self.assertIn("*ORIENTATION", text)
        self.assertIn("1,1\n2.000000000000e+03", text)
        obj.Mode, obj.End2 = "Ground", None
        stream = io.StringIO()
        write_connectors(stream, writer)
        self.assertIn("TYPE=SPRING1", stream.getvalue())


@unittest.skipUnless(shutil.which("ccx"), "Requires real CalculiX")
class TestElasticConnectorCalculiX(unittest.TestCase):
    def model(self, ground, angle, prescribed, axis="X", sign=1):
        doc = App.newDocument("SpringExact")
        analysis = ObjectsFem.makeAnalysis(doc)
        solver = ObjectsFem.makeSolverCalculiXCcxTools(doc)
        analysis.addObject(solver)
        block = doc.addObject("Part::Feature", "Block")
        block.Shape = Part.makeBox(1, 1, 1)
        material = ObjectsFem.makeMaterialSolid(doc)
        material.Material = {"Name": "Synthetic patch", "YoungsModulus": "1000 MPa",
                             "PoissonRatio": "0"}
        analysis.addObject(material)
        data = Fem.FemMesh()
        for index, point in enumerate(((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1),
                                       (0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)), 1):
            data.addNode(*point, index)
        data.addVolume(list(range(1, 9)))
        points = []
        for index, x in enumerate((-1, -2), 9):
            data.addNode(x, 0, 0, index)
            point = doc.addObject("Part::Feature", f"Point{index}")
            point.Shape = Part.Vertex(x, 0, 0)
            points.append(point)
        mesh = ObjectsFem.makeMeshGmsh(doc, "Mesh")
        mesh.Shape, mesh.FemMesh = block, data
        analysis.addObject(mesh)
        fixed = ObjectsFem.makeConstraintFixed(doc)
        fixed.References = [(block, ["Solid1"])]
        analysis.addObject(fixed)
        obj = ObjectsFem.makeConstraintElasticConnector(doc)
        obj.Stiffness = "2000 N/mm"
        obj.Axis = axis
        obj.Orientation = App.Rotation(App.Vector(0, 0, 1), angle)
        obj.End1 = (points[0], ["Vertex1"])
        if not ground:
            obj.Mode, obj.End2 = "Two points", (points[1], ["Vertex1"])
        analysis.addObject(obj)
        direction = obj.Orientation.multVec(
            {"X": App.Vector(1, 0, 0), "Y": App.Vector(0, 1, 0), "Z": App.Vector(0, 0, 1)}[axis]
        )
        for index, point in enumerate(points[:1] if ground else points):
            support = ObjectsFem.makeConstraintDisplacement(doc, f"Port{index + 1}")
            support.References = [(point, ["Vertex1"])]
            for axis, letter in enumerate("xyz"):
                free = not prescribed and index == 0 and abs(direction[axis]) > 0.5
                setattr(support, letter + "Free", free)
                delta = (0.1 if index == 0 else -0.05) if prescribed else 0
                setattr(support, letter + "Displacement", sign * delta * direction[axis])
            analysis.addObject(support)
        if not prescribed:
            line = doc.addObject("Part::Feature", "LoadDirection")
            line.Shape = Part.makeLine(App.Vector(), sign * direction)
            load = ObjectsFem.makeConstraintForce(doc)
            load.References = [(points[0], ["Vertex1"])]
            load.Force = "10 N"
            load.Direction = (line, ["Edge1"])
            analysis.addObject(load)
        doc.recompute()
        return doc, analysis, solver, obj, direction

    def solve(self, doc, analysis, solver):
        from femtools.ccxtools import FemToolsCcx
        prefs = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/General")
        overwrite = prefs.GetBool("OverwriteSolverWorkingDirectory", True)
        try:
            prefs.SetBool("OverwriteSolverWorkingDirectory", False)
            with tempfile.TemporaryDirectory() as directory:
                solver.WorkingDir = directory
                doc.recompute()
                fea = FemToolsCcx(analysis=analysis, solver=solver)
                fea.purge_results()
                self.assertTrue(fea.run())
                self.assertTrue(fea.results_present)
                capture = os.environ.get("FREECAD_CTQ_SOLVER_OUTPUT")
                if capture:
                    root = Path(capture)
                    root.mkdir(parents=True, exist_ok=True)
                    target = tempfile.mkdtemp(prefix="spring-", dir=root)
                    shutil.copytree(directory, target, dirs_exist_ok=True)
                return Path(directory, "Mesh.dat").read_text()
        finally:
            prefs.SetBool("OverwriteSolverWorkingDirectory", overwrite)

    def values(self, data, title, name):
        match = re.search(title + rf"[^\n]*for set {name.upper()}[^\n]*\n\s*\n([^\n]+)",
                          data, re.IGNORECASE)
        self.assertIsNotNone(match, data)
        return [float(value) for value in match.group(1).split()[1:]]

    def test_exact_springs_ground_pair_and_rotated_direction(self):
        from femtools.elastic_connector import identifier
        for ground in (True, False):
            for angle in (0, 90):
                for prescribed in (True, False):
                    with self.subTest(ground=ground, angle=angle, prescribed=prescribed):
                        doc, analysis, solver, obj, direction = self.model(
                            ground, angle, prescribed
                        )
                        try:
                            data = self.solve(doc, analysis, solver)
                            name = identifier("EC_END1_", obj)
                            displacement = self.values(data, "displacements", name)
                            expected_delta = 0.1 if prescribed else 10 / 2000
                            for actual, axis in zip(displacement, direction):
                                self.assertAlmostEqual(actual, expected_delta * axis, delta=1e-8)
                            if prescribed:
                                force = 2000 * (0.1 if ground else 0.15)
                                for end, sign in ((1, 1),) if ground else ((1, 1), (2, -1)):
                                    name = identifier(f"EC_END{end}_", obj)
                                    action = self.values(data, "forces", name)
                                    for actual, axis in zip(action, direction):
                                        self.assertAlmostEqual(actual, sign * force * axis,
                                                               delta=1e-6)
                            elif not ground:
                                action = self.values(data, "forces", identifier("EC_END2_", obj))
                                for actual, axis in zip(action, direction):
                                    self.assertAlmostEqual(actual, -10 * axis, delta=1e-6)
                        finally:
                            App.closeDocument(doc.Name)

    def test_changed_native_reference_regenerates_actual_spring_and_actions(self):
        from femtools.elastic_connector import identifier
        doc, analysis, solver, obj, _ = self.model(False, 0, True)
        try:
            before = self.solve(doc, analysis, solver)
            name = identifier("EC_END1_", obj)
            self.assertAlmostEqual(self.values(before, "forces", name)[0], 300, places=6)
            block = doc.getObject("Block")
            vertex = next(f"Vertex{index}" for index, shape in enumerate(block.Shape.Vertexes, 1)
                          if shape.Point.Length < 1e-10)
            obj.End2 = (block, [vertex])
            after = self.solve(doc, analysis, solver)
            self.assertAlmostEqual(self.values(after, "forces", name)[0], 200, places=6)
            self.assertAlmostEqual(self.values(after, "forces", identifier("EC_END2_", obj))[0],
                                   -200, places=6)
        finally:
            App.closeDocument(doc.Name)

    def test_negative_actions_and_other_local_axes(self):
        from femtools.elastic_connector import identifier
        for ground in (True, False):
            for axis in ("Y", "Z"):
                doc, analysis, solver, obj, direction = self.model(ground, 0, True, axis, -1)
                try:
                    data = self.solve(doc, analysis, solver)
                    force = -2000 * (0.1 if ground else 0.15)
                    for end, sign in ((1, 1),) if ground else ((1, 1), (2, -1)):
                        values = self.values(data, "forces", identifier(f"EC_END{end}_", obj))
                        for actual, component in zip(values, direction):
                            self.assertAlmostEqual(actual, sign * force * component, delta=1e-6)
                finally:
                    App.closeDocument(doc.Name)

    def test_split_input_ground_force_case(self):
        from femtools.elastic_connector import identifier
        doc, analysis, solver, obj, direction = self.model(True, 90, False)
        try:
            solver.SplitInputWriter = True
            data = self.solve(doc, analysis, solver)
            values = self.values(data, "displacements", identifier("EC_END1_", obj))
            for actual, component in zip(values, direction):
                self.assertAlmostEqual(actual, 0.005 * component, delta=1e-8)
        finally:
            App.closeDocument(doc.Name)

    def test_explicit_parallel_connectors_add_without_stiffness_division(self):
        from femtools.elastic_connector import identifier
        doc, analysis, solver, obj, _ = self.model(True, 0, False)
        try:
            other = ObjectsFem.makeConstraintElasticConnector(doc)
            other.End1 = obj.End1
            other.Stiffness = "3000 N/mm"
            analysis.addObject(other)
            data = self.solve(doc, analysis, solver)
            values = self.values(data, "displacements", identifier("EC_END1_", obj))
            self.assertAlmostEqual(values[0], 10 / (2000 + 3000), delta=1e-8)
        finally:
            App.closeDocument(doc.Name)
