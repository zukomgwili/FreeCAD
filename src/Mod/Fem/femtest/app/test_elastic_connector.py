# SPDX-License-Identifier: LGPL-2.1-or-later

import io
import math
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
from femtest.app.support_utils import (
    assign_exact_native_mesh,
    checked_native_mesh_copy,
    during_native_return,
)


class TestRigidPortConnector(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("RigidPortConnector")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def model(self, ground=False, angle=0, prescribed=True, sign=1, rotational=True, axis="X"):
        if self.doc.Objects:
            App.closeDocument(self.doc.Name)
            self.doc = App.newDocument("RigidPortConnector")
        analysis = ObjectsFem.makeAnalysis(self.doc)
        solver = ObjectsFem.makeSolverCalculiXCcxTools(self.doc)
        analysis.addObject(solver)
        data = Fem.FemMesh()
        boxes = []
        for offset, start in ((0, 1), (4, 21)):
            box = self.doc.addObject("Part::Feature", "Region")
            box.Shape = Part.makeBox(1, 1, 1, App.Vector(offset, 0, 0))
            boxes.append(box)
            coords = (
                (0, 0, 1),
                (1, 0, 1),
                (1, 1, 1),
                (0, 1, 1),
                (0, 0, 0),
                (1, 0, 0),
                (1, 1, 0),
                (0, 1, 0),
            )
            for node, (x, y, z) in enumerate(coords, start):
                data.addNode(x + offset, y, z, node)
            data.addVolume(list(range(start, start + 8)))
        geometry = self.doc.addObject("Part::Feature", "Geometry")
        geometry.Shape = Part.makeCompound([box.Shape for box in boxes])
        mesh = ObjectsFem.makeMeshGmsh(self.doc, "Mesh")
        mesh.Shape, mesh.FemMesh = geometry, data
        analysis.addObject(mesh)
        material = ObjectsFem.makeMaterialSolid(self.doc)
        material.Material = {
            "Name": "Rigid-region test",
            "YoungsModulus": "1000 MPa",
            "PoissonRatio": "0",
        }
        analysis.addObject(material)
        bodies = []
        direction = App.Rotation(App.Vector(0, 0, 1), angle).multVec(
            {"X": App.Vector(1, 0, 0), "Y": App.Vector(0, 1, 0), "Z": App.Vector(0, 0, 1)}[axis]
        )
        for index, box in enumerate(boxes):
            body = ObjectsFem.makeConstraintRigidBody(self.doc)
            body.References = [(box, ["Solid1"])]
            body.ReferenceNode = App.Vector(0.5 + 4 * index, 0.5, 0.5)
            for component_axis in "XYZ":
                setattr(body, "TranslationalMode" + component_axis, "Constraint")
                setattr(body, "RotationalMode" + component_axis, "Constraint")
            delta = (0.001 if index == 0 else (-0.0005 if not ground else 0)) * sign
            if rotational:
                body.Rotation = App.Rotation(direction, math.degrees(delta))
            else:
                body.Displacement = delta * direction
            if not prescribed:
                if rotational:
                    body.Rotation = App.Rotation()
                else:
                    body.Displacement = App.Vector()
                if index == 0:
                    component = max(range(3), key=lambda i: abs(direction[i]))
                    global_axis = "XYZ"[component]
                    setattr(
                        body,
                        ("RotationalMode" if rotational else "TranslationalMode") + global_axis,
                        "Load",
                    )
                    setattr(
                        body,
                        ("Moment" if rotational else "Force") + global_axis,
                        f"{10 * sign * direction[component]:g} " + ("N*mm" if rotational else "N"),
                    )
            analysis.addObject(body)
            bodies.append(body)
        obj = ObjectsFem.makeConstraintElasticConnector(self.doc)
        obj.Attachment = "Rigid body ports"
        obj.Kind = "Rotational" if rotational else "Translational"
        obj.Axis = axis
        obj.RotationalStiffness = App.Units.Quantity("2000 N*mm/rad")
        obj.Stiffness = "2000 N/mm"
        obj.Orientation = App.Rotation(App.Vector(0, 0, 1), angle)
        obj.RigidBody1 = bodies[0]
        if not ground:
            obj.Mode = "Two points"
            obj.RigidBody2 = bodies[1]
        analysis.addObject(obj)
        self.doc.recompute()
        return analysis, solver, obj, mesh, bodies, direction

    def test_explicit_ports_native_units_and_sparse_node_allocation(self):
        from femtools.elastic_connector import resolve_connector, rigid_body_node_ids

        analysis, _, obj, mesh, bodies, _ = self.model()
        result = resolve_connector(obj, mesh, analysis)
        self.assertTrue(result["rotational"])
        self.assertEqual(result["stiffness"], 2000)
        self.assertEqual(result["bodies"], bodies)
        self.assertEqual([len(nodes) for nodes in result["regions"]], [8, 8])
        for body in bodies:
            self.assertGreater(
                min(rigid_body_node_ids(analysis, mesh, body)), max(mesh.FemMesh.Nodes)
            )

    def test_shared_port_resolution_preserves_independent_mutable_regions(self):
        from femtools.elastic_connector import PortResolutionContext
        from femtools.elastic_connector import resolve_connector

        analysis, _, obj, mesh, bodies, _ = self.model()
        context = PortResolutionContext(mesh, analysis)
        first = resolve_connector(obj, mesh, analysis, context=context)
        self.assertEqual(first["bodies"], bodies)
        self.assertEqual(first["regions"], [set(range(1, 9)), set(range(21, 29))])
        for region in first["regions"]:
            self.assertIsInstance(region, set)
        first["regions"][0].clear()
        second = resolve_connector(obj, mesh, analysis, context=context)
        self.assertEqual(second["regions"], [set(range(1, 9)), set(range(21, 29))])
        self.assertEqual(second["nodes"], [])

    def test_stock_reexports_resolve_changed_regions_mesh_and_native_ids(self):
        from femtools.ccxtools import FemToolsCcx
        from femtools.elastic_connector import identifier

        analysis, solver, obj, mesh, bodies, _ = self.model()
        solver.SplitInputWriter = False

        def nodes(text, name):
            match = re.search(
                r"\*NSET,\s*NSET=" + re.escape(name) + r"\s*\n([^*]+)", text, re.IGNORECASE
            )
            self.assertIsNotNone(match, name)
            return {int(value) for value in re.split(r"[,\s]+", match[1]) if value}

        with tempfile.TemporaryDirectory() as directory:
            fea = FemToolsCcx(analysis=analysis, solver=solver)
            fea.setup_working_dir(directory)

            def export():
                fea.update_objects()
                fea.write_inp_file()
                return Path(fea.inp_file_name).read_text()

            before = export()
            self.assertEqual(nodes(before, bodies[0].Name), set(range(1, 9)))
            self.assertEqual(nodes(before, bodies[1].Name), set(range(21, 29)))
            self.assertEqual(nodes(before, bodies[0].Name + "_RefNode"), {35})
            self.assertEqual(nodes(before, bodies[1].Name + "_RotNode"), {38})

            original = bodies[1].References
            bodies[1].References = bodies[0].References
            self.doc.recompute()
            with self.assertRaisesRegex(ValueError, "overlap"):
                export()
            bodies[1].References = original

            # A new physical mesh and changed analysis order must allocate from
            # the new sparse IDs, not from an earlier export's port resolution.
            data = Fem.FemMesh()
            for node, point in mesh.FemMesh.Nodes.items():
                data.addNode(point.x, point.y, point.z, node + 100)
            data.addVolume(list(range(101, 109)))
            data.addVolume(list(range(121, 129)))
            mesh.FemMesh = data
            region = bodies[0].References[0][0]
            face = next(
                index
                for index, shape in enumerate(region.Shape.Faces, 1)
                if abs(shape.CenterOfMass.x) < 1e-12
            )
            bodies[0].References = [(region, [f"Face{face}"])]
            group = list(analysis.Group)
            first, second = group.index(bodies[0]), group.index(bodies[1])
            group[first], group[second] = group[second], group[first]
            analysis.Group = group
            self.doc.recompute()
            after = export()
            self.assertEqual(nodes(after, bodies[0].Name), {101, 104, 105, 108})
            self.assertEqual(nodes(after, bodies[1].Name), set(range(121, 129)))
            self.assertEqual(nodes(after, bodies[0].Name + "_RefNode"), {137})
            self.assertEqual(nodes(after, bodies[1].Name + "_RotNode"), {136})
            self.assertEqual(nodes(after, identifier("EC_END1_", obj)), {138})
            self.assertEqual(nodes(after, identifier("EC_END2_", obj)), {136})

    def test_direct_writes_after_completed_and_failed_full_exports_are_fresh(self):
        from femmesh.meshsetsgetter import MeshSetsGetter
        from femsolver.calculix.calculixutils import define_masks
        from femsolver.calculix.write_constraint_elastic_connector import write_connectors
        from femsolver.calculix.write_constraint_rigidbody import write_constraint
        from femsolver.calculix.writer import FemInputWriterCcx
        from femtools.membertools import AnalysisMember

        def node_set(text, name):
            match = re.search(
                r"\*NSET,\s*NSET=" + re.escape(name) + r"\s*\n([^*]+)", text, re.IGNORECASE
            )
            self.assertIsNotNone(match, name)
            return {int(value) for value in re.split(r"[,\s]+", match[1]) if value}

        for failed_export in (False, True):
            with self.subTest(failed_export=failed_export):
                analysis, solver, connector, mesh, bodies, _ = self.model()
                solver.SplitInputWriter = False
                solver.NativeForceAccounting = False
                getter = MeshSetsGetter(analysis, solver, mesh, AnalysisMember(analysis))
                for name, mask in define_masks(solver).items():
                    setattr(getter, "mask_" + name, mask)
                getter.get_mesh_sets()
                original = bodies[1].References
                with tempfile.TemporaryDirectory() as directory:
                    writer = FemInputWriterCcx(
                        analysis, solver, mesh, getter.member, directory, getter.mat_geo_sets
                    )
                    if failed_export:
                        bodies[1].References = bodies[0].References
                        self.doc.recompute()
                        with self.assertRaisesRegex(ValueError, "overlap"):
                            writer.write_solver_input()
                    else:
                        filename = writer.write_solver_input()
                        self.assertEqual(
                            node_set(Path(filename).read_text(), bodies[0].Name + "_RefNode"), {35}
                        )
                        bodies[1].References = bodies[0].References
                        self.doc.recompute()
                        with self.assertRaisesRegex(ValueError, "overlap"):
                            write_connectors(io.StringIO(), writer)

                    # Reuse the exact concrete writer after its success/error,
                    # but with a new mesh and a different native allocation.
                    bodies[1].References = original
                    shifted = Fem.FemMesh()
                    for node, point in mesh.FemMesh.Nodes.items():
                        shifted.addNode(point.x, point.y, point.z, node + 100)
                    shifted.addVolume(list(range(101, 109)))
                    shifted.addVolume(list(range(121, 129)))
                    mesh.FemMesh = shifted
                    group = list(analysis.Group)
                    first, second = group.index(bodies[0]), group.index(bodies[1])
                    group[first], group[second] = group[second], group[first]
                    analysis.Group = group
                    self.doc.recompute()
                    stream = io.StringIO()
                    write_connectors(stream, writer)
                    self.assertEqual(
                        node_set(stream.getvalue(), "EC_END1_" + connector.Name), {138}
                    )
                    self.assertEqual(
                        node_set(stream.getvalue(), "EC_END2_" + connector.Name), {136}
                    )
                    for body in bodies:
                        row = next(
                            item for item in getter.member.cons_rigidbody if item["Object"] == body
                        )
                        stream = io.StringIO()
                        write_constraint(stream, row, body, writer)
                        ref, rot = (137, 138) if body == bodies[0] else (135, 136)
                        self.assertEqual(node_set(stream.getvalue(), body.Name + "_RefNode"), {ref})
                        self.assertEqual(node_set(stream.getvalue(), body.Name + "_RotNode"), {rot})

    def test_ports_fail_closed_for_implicit_or_invalid_coupling(self):
        from femtools.elastic_connector import resolve_connector, validation_errors

        analysis, solver, obj, mesh, bodies, _ = self.model()
        obj.Attachment = "Vertices"
        with self.assertRaisesRegex(ValueError, "explicit Rigid Body"):
            resolve_connector(obj, mesh, analysis)
        obj.Attachment = "Rigid body ports"
        obj.RigidBody2 = obj.RigidBody1
        with self.assertRaisesRegex(ValueError, "distinct"):
            resolve_connector(obj, mesh, analysis)
        obj.RigidBody2 = bodies[1]
        old = bodies[1].References
        bodies[1].References = bodies[0].References
        self.assertTrue(
            any("overlap" in error for error in validation_errors(analysis, solver, mesh))
        )
        bodies[1].References = old
        obj.RotationalStiffness = App.Units.Quantity("0 N*mm/rad")
        with self.assertRaisesRegex(ValueError, "positive"):
            resolve_connector(obj, mesh, analysis)

    def test_native_body_links_and_axes_survive_save_and_regenerated_export(self):
        from femtools.elastic_connector import resolve_connector
        from femsolver.calculix.write_constraint_elastic_connector import write_connectors

        analysis, _, obj, mesh, bodies, _ = self.model(angle=45)
        frame = self.doc.addObject("App::Part", "Frame")
        frame.Placement.Rotation = App.Rotation(App.Vector(0, 0, 1), 30)
        obj.OrientationReference = frame
        names = [item.Name for item in (analysis, obj, mesh, frame)]
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "ports.FCStd")
            self.doc.saveAs(path)
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(path)
            analysis, obj, mesh, frame = [self.doc.getObject(name) for name in names]
            data = resolve_connector(obj, mesh, analysis)
            self.assertEqual([len(nodes) for nodes in data["regions"]], [8, 8])
            expected = App.Rotation(App.Vector(0, 0, 1), 75).multVec(App.Vector(1, 0, 0))
            self.assertLess(
                (data["rotation"].multVec(App.Vector(1, 0, 0)) - expected).Length, 1e-12
            )
            stream = io.StringIO()
            writer = SimpleNamespace(
                analysis=analysis,
                mesh_object=mesh,
                member=SimpleNamespace(cons_elasticconnector=[{"Object": obj}]),
            )
            write_connectors(stream, writer)
            before = stream.getvalue()
            frame.Placement.Rotation = App.Rotation(App.Vector(0, 0, 1), 60)
            stream = io.StringIO()
            write_connectors(stream, writer)
            self.assertNotEqual(stream.getvalue(), before)
            self.assertIn("*EQUATION", stream.getvalue())
            self.assertIn("N*mm/rad", stream.getvalue())
            self.assertEqual(mesh.FemMesh.NodeCount, 16)

    def test_native_rotational_unit_conversion_and_undo_redo(self):
        _, _, obj, _, _, _ = self.model()
        self.doc.UndoMode = 1
        self.doc.openTransaction("Change rotational stiffness")
        obj.RotationalStiffness = App.Units.Quantity("4 N*m/rad")
        self.doc.commitTransaction()
        self.assertAlmostEqual(obj.RotationalStiffness.getValueAs("N*mm/rad").Value, 4000)
        self.doc.undo()
        self.assertAlmostEqual(obj.RotationalStiffness.getValueAs("N*mm/rad").Value, 2000)
        self.doc.redo()
        self.assertAlmostEqual(obj.RotationalStiffness.getValueAs("N*mm/rad").Value, 4000)

    def test_explicit_occurrence_region_and_regenerated_mesh(self):
        from femtools.elastic_connector import resolve_connector

        analysis, _, obj, mesh, bodies, _ = self.model()
        region = bodies[1].References[0][0]
        link = self.doc.addObject("App::Link", "RegionOccurrence")
        link.LinkedObject = region
        bodies[1].References = [(link, ["Solid1"])]
        self.doc.recompute()
        self.assertEqual(resolve_connector(obj, mesh, analysis)["regions"][1], set(range(21, 29)))
        # A changed occurrence must not silently continue using old mesh nodes.
        link.Placement.Base = App.Vector(20, 0, 0)
        self.doc.recompute()
        with self.assertRaisesRegex(ValueError, "no mesh nodes"):
            resolve_connector(obj, mesh, analysis)
        data = Fem.FemMesh()
        for node, point in mesh.FemMesh.Nodes.items():
            point = point + App.Vector(20, 0, 0) if node >= 21 else point
            data.addNode(point.x, point.y, point.z, node)
        data.addVolume(list(range(1, 9)))
        data.addVolume(list(range(21, 29)))
        mesh.FemMesh = data
        self.assertEqual(resolve_connector(obj, mesh, analysis)["regions"][1], set(range(21, 29)))
        frame = self.doc.addObject("App::Part", "OccurrenceFrame")
        frame.addObject(link)
        frame.Placement.Base = App.Vector(10, 0, 0)
        link.Placement.Base = App.Vector(10, 0, 0)
        self.doc.recompute()
        self.assertEqual(resolve_connector(obj, mesh, analysis)["regions"][1], set(range(21, 29)))
        names = [item.Name for item in (obj, mesh, analysis)]
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "occurrence.FCStd")
            self.doc.saveAs(path)
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(path)
            obj, mesh, analysis = [self.doc.getObject(name) for name in names]
            # Native mesh persistence may compact sparse IDs. Preserve the
            # selected physical occurrence, not an obsolete numeric node list.
            selected = resolve_connector(obj, mesh, analysis)["regions"][1]
            self.assertEqual(len(selected), 8)
            self.assertEqual({round(mesh.FemMesh.Nodes[node].x, 9) for node in selected}, {24, 25})

    @unittest.skipUnless(shutil.which("ccx"), "Requires real CalculiX")
    def test_other_local_rotational_axes(self):
        from femtools.elastic_connector import identifier

        helper = TestElasticConnectorCalculiX()
        for axis in ("Y", "Z"):
            for ground in (True, False):
                with self.subTest(axis=axis, ground=ground):
                    analysis, solver, obj, _, _, direction = self.model(
                        ground=ground, angle=90, prescribed=False, sign=-1, axis=axis
                    )
                    obj.RotationalStiffness = App.Units.Quantity("2 N*m/rad")
                    data = helper.solve(self.doc, analysis, solver)
                    values = helper.values(data, "displacements", identifier("EC_END1_", obj))
                    for actual, component in zip(values, direction):
                        self.assertAlmostEqual(actual, -10 / 2000 * component, delta=1e-8)

    @unittest.skipUnless(shutil.which("ccx"), "Requires real CalculiX")
    def test_exact_rigid_ports_signed_ground_pair_and_rotated_axes(self):
        from femtools.elastic_connector import identifier

        helper = TestElasticConnectorCalculiX()
        for ground in (True, False):
            for angle in (0, 90, 45):
                for sign in (-1, 1):
                    with self.subTest(ground=ground, angle=angle, sign=sign):
                        analysis, solver, obj, mesh, _, direction = self.model(
                            ground, angle, True, sign
                        )
                        original_nodes = dict(mesh.FemMesh.Nodes)
                        data = helper.solve(self.doc, analysis, solver)
                        self.assertEqual(mesh.FemMesh.Nodes, original_nodes)
                        delta = (0.001 if ground else 0.0015) * sign
                        for end, factor in ((1, 1),) if ground else ((1, 1), (2, -1)):
                            name = identifier(f"EC_END{end}_", obj)
                            action = helper.values(data, "forces", name)
                            for actual, axis in zip(action, direction):
                                self.assertAlmostEqual(
                                    actual, factor * 2000 * delta * axis, delta=1e-6
                                )

    @unittest.skipUnless(shutil.which("ccx"), "Requires real CalculiX")
    def test_exact_rigid_port_force_and_moment_response(self):
        from femtools.elastic_connector import identifier

        helper = TestElasticConnectorCalculiX()
        for rotational in (False, True):
            for ground in (False, True):
                for angle in (0, 90):
                    with self.subTest(rotational=rotational, ground=ground, angle=angle):
                        analysis, solver, obj, _, _, direction = self.model(
                            ground, angle, False, -1, rotational
                        )
                        data = helper.solve(self.doc, analysis, solver)
                        values = helper.values(data, "displacements", identifier("EC_END1_", obj))
                        for actual, axis in zip(values, direction):
                            self.assertAlmostEqual(actual, -10 / 2000 * axis, delta=1e-8)
                        if not ground:
                            values = helper.values(data, "forces", identifier("EC_END2_", obj))
                            for actual, axis in zip(values, direction):
                                self.assertAlmostEqual(actual, 10 * axis, delta=1e-6)

    def test_legacy_classifier_fences_same_id_native_coordinate_mutation(self):
        from femtools.elastic_connector import validation_errors

        analysis, solver, _connector, mesh, _bodies, _direction = self.model()
        self.assertFalse(mesh.ElementGroupGeometry)
        native = mesh.FemMesh
        backup = checked_native_mesh_copy(native)
        before_ids = tuple(native.Nodes)
        errors = []

        def change_coordinates():
            shifted = checked_native_mesh_copy(backup)
            shifted.setTransform(App.Placement(App.Vector(0, 0, 0.25), App.Rotation()))
            assign_exact_native_mesh(mesh, shifted)
            self.assertEqual(tuple(mesh.FemMesh.Nodes), before_ids)
            self.assertEqual(mesh.FemMesh.NodeCount, backup.NodeCount)
            self.assertNotEqual(mesh.FemMesh.Nodes, backup.Nodes)

        def classify():
            errors.extend(validation_errors(analysis, solver, mesh))

        observed = during_native_return(
            "getNodesBySolid",
            change_coordinates,
            classify,
            python_caller="get_femnodes_by_refshape",
        )
        self.assertEqual(len(observed), 1, "Must mutate after actual legacy native classification")
        self.assertTrue(errors, "A single operation must not adopt a post-classifier snapshot")
        self.assertTrue(any("changed" in error.lower() for error in errors), errors)
        assign_exact_native_mesh(mesh, backup)
        self.assertEqual(validation_errors(analysis, solver, mesh), [])


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
        parent.Placement = App.Placement(
            App.Vector(10, 20, 30), App.Rotation(App.Vector(0, 0, 1), 90)
        )
        obj.OrientationReference = parent
        data = Fem.FemMesh()
        data.addNode(10, 20, 30, 77)
        data.addNode(10, 21, 30, 42)
        mesh.FemMesh = data
        self.doc.recompute()
        result = resolve_connector(obj, mesh)
        self.assertEqual(result["nodes"], [77, 42])
        self.assertLess(
            (result["rotation"].multVec(App.Vector(1, 0, 0)) - App.Vector(0, 1, 0)).Length, 1e-12
        )

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
        writer = SimpleNamespace(
            mesh_object=mesh,
            member=SimpleNamespace(cons_elasticconnector=[{"Object": obj}, {"Object": other}]),
        )
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
        for prop, value in (
            ("AnalysisType", "frequency"),
            ("ModelSpace", "plane stress"),
            ("GeometricalNonlinearity", True),
        ):
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
        self.assertTrue(
            any("Elmer foundation" in error for error in validation_errors(analysis, solver, mesh))
        )

    def test_generated_node_set_collision_is_rejected(self):
        from femtools.elastic_connector import identifier
        from femtools.elastic_connector import validation_errors

        obj, mesh, _ = self.configured()
        analysis = ObjectsFem.makeAnalysis(self.doc)
        analysis.addObject(obj)
        solver = ObjectsFem.makeSolverCalculiXCcxTools(self.doc)
        conflict = ObjectsFem.makeConstraintFixed(self.doc, identifier("EC_END1_", obj))
        analysis.addObject(conflict)
        self.assertTrue(
            any("collides" in error for error in validation_errors(analysis, solver, mesh))
        )

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
            self.assertLess(
                (data["rotation"].multVec(App.Vector(1, 0, 0)) - App.Vector(0, 1, 0)).Length, 1e-12
            )

    def test_stock_export_includes_spring_element_orientation_and_decimal_stiffness(self):
        from femsolver.calculix.write_constraint_elastic_connector import write_connectors

        obj, mesh, _ = self.configured()
        writer = SimpleNamespace(
            mesh_object=mesh, member=SimpleNamespace(cons_elasticconnector=[{"Object": obj}])
        )
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
        material.Material = {
            "Name": "Synthetic patch",
            "YoungsModulus": "1000 MPa",
            "PoissonRatio": "0",
        }
        analysis.addObject(material)
        data = Fem.FemMesh()
        for index, point in enumerate(
            (
                (0, 0, 1),
                (1, 0, 1),
                (1, 1, 1),
                (0, 1, 1),
                (0, 0, 0),
                (1, 0, 0),
                (1, 1, 0),
                (0, 1, 0),
            ),
            1,
        ):
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
                success = fea.run()
                capture = os.environ.get("FREECAD_CTQ_SOLVER_OUTPUT")
                if capture:
                    root = Path(capture)
                    root.mkdir(parents=True, exist_ok=True)
                    target = tempfile.mkdtemp(prefix="spring-", dir=root)
                    shutil.copytree(directory, target, dirs_exist_ok=True)
                self.assertTrue(success)
                self.assertTrue(fea.results_present)
                return Path(directory, "Mesh.dat").read_text()
        finally:
            prefs.SetBool("OverwriteSolverWorkingDirectory", overwrite)

    def values(self, data, title, name):
        match = re.search(
            title + rf"[^\n]*for set {name.upper()}[^\n]*\n\s*\n([^\n]+)", data, re.IGNORECASE
        )
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
                                        self.assertAlmostEqual(
                                            actual, sign * force * axis, delta=1e-6
                                        )
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
            vertex = next(
                f"Vertex{index}"
                for index, shape in enumerate(block.Shape.Vertexes, 1)
                if shape.Point.Length < 1e-10
            )
            obj.End2 = (block, [vertex])
            after = self.solve(doc, analysis, solver)
            self.assertAlmostEqual(self.values(after, "forces", name)[0], 200, places=6)
            self.assertAlmostEqual(
                self.values(after, "forces", identifier("EC_END2_", obj))[0], -200, places=6
            )
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
