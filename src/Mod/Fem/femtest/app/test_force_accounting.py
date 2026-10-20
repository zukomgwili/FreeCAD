# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native accounting interface tests, independent of a particular solver binary."""

import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import FreeCAD
import Fem
import ObjectsFem
import Part


class TestForceAccounting(unittest.TestCase):
    def setUp(self):
        self.doc = FreeCAD.newDocument("NativeAccountingTest")

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def make_native_model(self):
        geometry = self.doc.addObject("Part::Feature", "Geometry")
        geometry.Shape = Part.makeBox(1, 1, 1)
        analysis = ObjectsFem.makeAnalysis(self.doc)
        material = ObjectsFem.makeMaterialSolid(self.doc)
        material.References = [(geometry, ["Solid1"])]
        analysis.addObject(material)
        mesh = ObjectsFem.makeMeshGmsh(self.doc)
        mesh.Shape = geometry
        tetra = Fem.FemMesh()
        for point in ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)):
            tetra.addNode(*point)
        tetra.addVolume([1, 2, 3, 4])
        mesh.FemMesh = tetra
        analysis.addObject(mesh)
        self.doc.recompute()
        return SimpleNamespace(analysis=analysis, mesh=mesh, geometry=geometry, material=material)

    def test_reading_native_material_does_not_change_input_identity(self):
        from femmesh import quality
        from femtools import force_accounting

        model = self.make_native_model()
        digest = force_accounting._model_digest(model.analysis, model.mesh)
        fingerprint = quality.input_fingerprint(model.mesh)
        # A property read copies the native Material into a Python wrapper.
        # Keeping that copy alive must not change the physical input identity.
        retained = [model.geometry.ShapeMaterial]
        self.assertEqual(force_accounting._model_digest(model.analysis, model.mesh), digest)
        self.assertEqual(quality.input_fingerprint(model.mesh), fingerprint)
        retained.extend(model.geometry.ShapeMaterial for _ in range(32))
        self.assertEqual(force_accounting._model_digest(model.analysis, model.mesh), digest)
        self.assertEqual(quality.input_fingerprint(model.mesh), fingerprint)

    def make_import_context(self, model, directory):
        from femtools import force_accounting

        root = Path(directory)
        deck = root / "model.inp"
        request = root / "model.accounting"
        binary = root / "solver"
        output = root / "model.accounting.out"
        deck.write_text("*HEADING\nNative provenance boundary fixture\n")
        request.write_text("CCX_FORCE_ACCOUNTING_V1\nSUPPORT R 1 2\nEND\n")
        binary.write_bytes(b"Synthetic solver identity; never executed\n")
        output.write_text("CCX_FORCE_ACCOUNTING_V1\nSTATE 1 1 1\nSUPPORT R 0 0 2 4 -6 0\nEND\n")

        def digest(path):
            return hashlib.sha256(path.read_bytes()).hexdigest()

        metadata = {
            "model_digest": force_accounting._model_digest(model.analysis, model.mesh),
            "deck_sha256": digest(deck),
            "request_sha256": digest(request),
            "binary": str(binary),
            "binary_sha256": digest(binary),
            "expected": [["SUPPORT", "R"]],
            "end_time": 1.0,
        }
        fea = SimpleNamespace(analysis=model.analysis, mesh=model.mesh, inp_file_name=str(deck))
        return fea, ({}, metadata, output)

    def test_retained_native_material_import_and_historical_restore(self):
        from femtools import force_accounting

        model = self.make_native_model()
        with tempfile.TemporaryDirectory() as directory:
            fea, context = self.make_import_context(model, directory)
            retained = [model.geometry.ShapeMaterial for _ in range(32)]
            result = force_accounting.import_result(fea, context)
            self.assertEqual(result.Status, "Current native accounting; not design acceptance")
            data, resultants = result.AccountingData, list(result.Resultants)
            self.assertEqual(json.loads(data)["wrenches"]["SUPPORT"]["R"], [0, 0, 2, 4, -6, 0])
            path = str(Path(directory) / "accounting.FCStd")
            name = result.Name
            self.doc.saveAs(path)
            FreeCAD.closeDocument(self.doc.Name)
            self.doc = FreeCAD.openDocument(path)
            restored = self.doc.getObject(name)
            self.assertTrue(restored.Status.startswith("Stale after restore"))
            self.assertEqual(restored.AccountingData, data)
            self.assertEqual(list(restored.Resultants), resultants)
            self.assertEqual(len(retained), 32)

    def add_input_controls(self, model):
        gravity = ObjectsFem.makeConstraintSelfWeight(self.doc)
        contact = ObjectsFem.makeConstraintContact(self.doc)
        contact.References = [(model.geometry, ["Face1"]), (model.geometry, ["Face2"])]
        support = ObjectsFem.makeConstraintRigidBody(self.doc)
        support.References = [(model.geometry, ["Solid1"])]
        section = ObjectsFem.makeConstraintSectionPrint(self.doc)
        section.References = [(model.geometry, ["Face1"])]
        section.NativeEquilibriumCut = True
        section.AccountingBody = [(model.geometry, ["Solid1"])]
        solver = ObjectsFem.makeSolverCalculiXCcxTools(self.doc)
        solver.NativeForceAccounting = True
        for obj in (gravity, contact, support, section, solver):
            model.analysis.addObject(obj)
        model.gravity, model.contact = gravity, contact
        model.support, model.section, model.solver = support, section, solver

    def test_real_model_edits_during_solve_cannot_import_current(self):
        from femtools import force_accounting

        def replace_mesh(model, *, coordinates=False):
            mesh = Fem.FemMesh()
            points = ((0, 0, 0), (2 if coordinates else 1, 0, 0), (0, 1, 0), (0, 0, 1))
            for point in points:
                mesh.addNode(*point)
            mesh.addVolume([1, 2, 3, 4] if coordinates else [1, 3, 2, 4])
            model.mesh.FemMesh = mesh

        changes = {
            "material": lambda m: setattr(m.material, "Material", {"Density": "7901 kg/m^3"}),
            "geometry": lambda m: setattr(m.geometry, "Shape", Part.makeBox(2, 1, 1)),
            "mesh coordinates": lambda m: replace_mesh(m, coordinates=True),
            "mesh connectivity": lambda m: replace_mesh(m),
            "mesh ownership": lambda m: setattr(
                m.mesh, "ElementGroupReferences", [(m.geometry, ["Face1"])]
            ),
            "gravity": lambda m: setattr(m.gravity, "GravityAcceleration", "9.9 m/s^2"),
            "contact stiffness": lambda m: setattr(m.contact, "Slope", "100 MPa/mm"),
            "contact references": lambda m: setattr(
                m.contact,
                "References",
                [(m.geometry, ["Face3"]), (m.geometry, ["Face4"])],
            ),
            "support reference": lambda m: setattr(
                m.support, "ReferenceNode", FreeCAD.Vector(2, 3, 4)
            ),
            "support prescribed mode": lambda m: setattr(
                m.support, "TranslationalModeX", "Constraint"
            ),
            "section references": lambda m: setattr(
                m.section, "References", [(m.geometry, ["Face2"])]
            ),
            "section body": lambda m: setattr(m.section, "AccountingBody", []),
            "solver nonlinearity": lambda m: setattr(m.solver, "GeometricalNonlinearity", True),
        }
        for name, change in changes.items():
            with self.subTest(change=name), tempfile.TemporaryDirectory() as directory:
                model = self.make_native_model()
                self.add_input_controls(model)
                fea, context = self.make_import_context(model, directory)
                # A control import first proves this context is accepted before
                # the same owning thread applies one real input change.
                control = force_accounting.import_result(fea, context)
                self.assertTrue(control.Status.startswith("Current"))
                change(model)
                context[2].unlink()
                with self.assertRaisesRegex(ValueError, r"changed while solving \(model_digest\)"):
                    force_accounting.import_result(fea, context)
                self.assertTrue(control.Status.startswith("Stale"))

    def test_changed_solver_files_during_solve_cannot_import_current(self):
        from femtools import force_accounting

        for identity in ("deck_sha256", "request_sha256", "binary_sha256"):
            with self.subTest(identity=identity), tempfile.TemporaryDirectory() as directory:
                model = self.make_native_model()
                fea, context = self.make_import_context(model, directory)
                control = force_accounting.import_result(fea, context)
                self.assertTrue(control.Status.startswith("Current"))
                paths = {
                    "deck_sha256": Path(fea.inp_file_name),
                    "request_sha256": Path(fea.inp_file_name).with_suffix(".accounting"),
                    "binary_sha256": Path(context[1]["binary"]),
                }
                path = paths[identity]
                path.write_bytes(path.read_bytes() + b"changed after launch\n")
                context[2].unlink()
                with self.assertRaisesRegex(
                    ValueError, "changed while solving \\(" + identity + "\\)"
                ):
                    force_accounting.import_result(fea, context)

    def test_native_material_typed_values_preserve_content_without_addresses(self):
        import Materials
        from femmesh import quality
        from femtools import force_accounting
        from femtools.native_properties import property_value

        def change_array(material, *, depth=False, three_dimensions=False):
            name = "TestArray3D" if three_dimensions or depth else "TestArray2D"
            array = material.getPhysicalValue(name)
            if depth:
                before = array.Array
                array.setDepthValue(1, "20.123456789 C")
                self.assertEqual(array.Array, before)
            elif three_dimensions:
                array.setValue(2, 2, 1, "31.123456789 Pa")
            else:
                array.setValue(0, 1, "10.123456789 kg/m^3")
            material.setValue(name, array)

        changes = {
            "quantity precision": lambda m: m.setPhysicalValue("TestQuantity", "19.7612342 kg/m^3"),
            "float precision": lambda m: m.setPhysicalValue("TestFloat", "32.170008"),
            "list": lambda m: m.setValue("TestList", ["first", "different"]),
            "array2d": lambda m: change_array(m),
            "array3d cell": lambda m: change_array(m, three_dimensions=True),
            "array3d depth": lambda m: change_array(m, depth=True),
            "appearance": lambda m: m.setAppearanceValue("DiffuseColor", "(0.125, 0.25, 0.5)"),
            "identity metadata": lambda m: setattr(m, "Description", "Changed description"),
            "model membership": lambda m: m.addPhysicalModel(Materials.UUIDs().Density),
        }
        for name, change in changes.items():
            with self.subTest(change=name):
                model = self.make_native_model()
                material = Materials.MaterialManager().getMaterial(
                    "c6c64159-19c1-40b5-859c-10561f20f979"
                )
                material.setPhysicalValue("TestQuantity", "19.7612341 kg/m^3")
                material.setPhysicalValue("TestFloat", "32.170001")
                material.setValue("TestList", ["first", "second"])
                model.geometry.ShapeMaterial = material
                baseline = property_value(model.geometry.ShapeMaterial)
                digest = force_accounting._model_digest(model.analysis, model.mesh)
                fingerprint = quality.input_fingerprint(model.mesh)
                wrappers = [model.geometry.ShapeMaterial for _ in range(8)]
                self.assertTrue(all(property_value(wrapper) == baseline for wrapper in wrappers))
                changed = model.geometry.ShapeMaterial
                change(changed)
                self.assertEqual(changed.UUID, material.UUID)
                self.assertNotEqual(property_value(changed), baseline)
                model.geometry.ShapeMaterial = changed
                self.assertNotEqual(property_value(model.geometry.ShapeMaterial), baseline)
                self.assertNotEqual(
                    force_accounting._model_digest(model.analysis, model.mesh), digest
                )
                self.assertNotEqual(quality.input_fingerprint(model.mesh), fingerprint)

        # A declared but unset quantity is not a nonfinite authored value, nor
        # equivalent to a valid zero. Both states must survive fresh wrappers.
        material = Materials.Material()
        material.addPhysicalModel(Materials.UUIDs().Density)
        self.assertTrue(material.PropertyObjects["Density"].Empty)
        model.geometry.ShapeMaterial = material
        unset = property_value(model.geometry.ShapeMaterial)
        self.assertEqual(property_value(model.geometry.ShapeMaterial), unset)
        material.setPhysicalValue("Density", "0 kg/m^3")
        self.assertFalse(material.PropertyObjects["Density"].Empty)
        model.geometry.ShapeMaterial = material
        zero = property_value(model.geometry.ShapeMaterial)
        self.assertNotEqual(zero, unset)
        self.assertEqual(property_value(model.geometry.ShapeMaterial), zero)
        self.assertEqual(zero["physical"]["Density"]["unit"], [-3, 1, 0, 0, 0, 0, 0, 0])
        self.assertEqual(float.fromhex(zero["physical"]["Density"]["quantity"]["float"]), 0.0)

    def test_empty_native_material_arrays_preserve_dimensions(self):
        import Materials
        from femmesh import quality
        from femtools import force_accounting
        from femtools.native_properties import property_value

        for name in ("TestArray2D", "TestArray3D"):
            with self.subTest(array=name):
                model = self.make_native_model()
                material = Materials.Material()
                material.addPhysicalModel(Materials.UUIDs().TestModel)
                array = material.getPhysicalValue(name)
                self.assertEqual(array.Array, [])
                self.assertTrue(material.PropertyObjects[name].Empty)
                model.geometry.ShapeMaterial = material
                baseline = property_value(model.geometry.ShapeMaterial)
                digest = force_accounting._model_digest(model.analysis, model.mesh)
                fingerprint = quality.input_fingerprint(model.mesh)
                array.Columns += 1
                material.setValue(name, array)
                self.assertEqual(array.Array, [])
                self.assertTrue(material.PropertyObjects[name].Empty)
                model.geometry.ShapeMaterial = material
                self.assertEqual(model.geometry.ShapeMaterial.UUID, material.UUID)
                self.assertNotEqual(property_value(model.geometry.ShapeMaterial), baseline)
                self.assertNotEqual(
                    force_accounting._model_digest(model.analysis, model.mesh), digest
                )
                self.assertNotEqual(quality.input_fingerprint(model.mesh), fingerprint)

    def test_native_array_null_and_authored_zero_fingerprints_are_distinct(self):
        import Materials
        from femmesh import quality
        from femtools import force_accounting
        from femtools.native_properties import property_value

        model = self.make_native_model()
        material = Materials.Material()
        material.addPhysicalModel(Materials.UUIDs().TestModel)
        array = material.getPhysicalValue("TestArray2D")
        array.Rows = 1
        material.setValue("TestArray2D", array)
        self.assertEqual(array.TypedArray, [[None, None]])
        model.geometry.ShapeMaterial = material
        baseline = property_value(model.geometry.ShapeMaterial)
        digest = force_accounting._model_digest(model.analysis, model.mesh)
        fingerprint = quality.input_fingerprint(model.mesh)
        self.assertEqual(baseline["physical"]["TestArray2D"]["array2d"], [[None, None]])
        legacy = array.Array
        array.setValue(0, 0, "0")
        self.assertEqual(array.Array, legacy)  # Legacy coercion remains compatible.
        self.assertIsInstance(array.TypedArray[0][0], FreeCAD.Units.Quantity)
        material.setValue("TestArray2D", array)
        model.geometry.ShapeMaterial = material
        zero = property_value(model.geometry.ShapeMaterial)
        self.assertNotEqual(zero, baseline)
        self.assertNotEqual(force_accounting._model_digest(model.analysis, model.mesh), digest)
        self.assertNotEqual(quality.input_fingerprint(model.mesh), fingerprint)
        retained = [model.geometry.ShapeMaterial for _ in range(32)]
        self.assertEqual(property_value(model.geometry.ShapeMaterial), zero)
        self.assertEqual(len(retained), 32)

    def test_native_array_nonquantity_columns_preserve_input_sensitivity(self):
        import Materials
        from femmesh import quality
        from femtools import force_accounting
        from femtools.native_properties import property_value

        model = self.make_native_model()
        material = Materials.Material()
        material.addPhysicalModel(Materials.UUIDs().OgdenN1)
        array = material.getPhysicalValue("OgdenN1")
        array.Rows = 1
        for column, value in enumerate(("20 C", "1000 Pa", "2", "0.001 1/Pa")):
            array.setValue(0, column, value)
        material.setValue("OgdenN1", array)
        self.assertIn(
            "Float",
            [column.Type for column in material.PropertyObjects["OgdenN1"].Columns],
        )
        model.geometry.ShapeMaterial = material
        baseline = property_value(model.geometry.ShapeMaterial)
        digest = force_accounting._model_digest(model.analysis, model.mesh)
        fingerprint = quality.input_fingerprint(model.mesh)
        self.assertEqual(property_value(model.geometry.ShapeMaterial), baseline)
        array.setValue(0, 2, "2.0000000000000004")
        material.setValue("OgdenN1", array)
        model.geometry.ShapeMaterial = material
        self.assertEqual(model.geometry.ShapeMaterial.UUID, material.UUID)
        self.assertNotEqual(property_value(model.geometry.ShapeMaterial), baseline)
        self.assertNotEqual(force_accounting._model_digest(model.analysis, model.mesh), digest)
        self.assertNotEqual(quality.input_fingerprint(model.mesh), fingerprint)

    def test_ambiguous_native_material_properties_are_rejected(self):
        import Materials
        from femmesh import quality
        from femtools import force_accounting
        from femtools.native_properties import property_value

        overlap = Materials.Material()
        overlap.addPhysicalModel(Materials.UUIDs().Density)
        overlap.setPhysicalValue("Density", "7900 kg/m^3")
        overlap.addAppearanceModel(Materials.UUIDs().Density)
        self.assertTrue(overlap.hasPhysicalProperty("Density"))
        self.assertTrue(overlap.hasAppearanceProperty("Density"))

        for material, message in ((overlap, "Ambiguous native material physical/appearance"),):
            with self.subTest(message=message):
                model = self.make_native_model()
                model.geometry.ShapeMaterial = material
                with self.assertRaisesRegex(ValueError, message):
                    property_value(model.geometry.ShapeMaterial)
                with self.assertRaisesRegex(ValueError, message):
                    quality.input_fingerprint(model.mesh)
                with self.assertRaisesRegex(ValueError, message):
                    force_accounting._model_digest(model.analysis, model.mesh)

    def test_properties_are_opt_in_and_restore(self):
        solver = ObjectsFem.makeSolverCalculiXCcxTools(self.doc)
        section = ObjectsFem.makeConstraintSectionPrint(self.doc)
        self.assertFalse(solver.NativeForceAccounting)
        self.assertFalse(section.NativeEquilibriumCut)
        self.assertEqual(section.AccountingBody, [])
        solver.Proxy.onDocumentRestored(solver)
        section.Proxy.onDocumentRestored(section)
        self.assertFalse(solver.NativeForceAccounting)

    def test_output_parser_is_strict(self):
        from femtools import force_accounting

        valid = "CCX_FORCE_ACCOUNTING_V1\nSTATE 1 1 1\nSUPPORT R 0 0 2 4 -6 0\nEND\n"
        result = force_accounting.parse_output(valid, {("SUPPORT", "R")}, 1)
        self.assertEqual(result["SUPPORT"]["R"], [0, 0, 2, 4, -6, 0])
        self.assertNotIn("MPC", result)  # V1 does not claim to provide this term.
        for text in (
            valid.replace(" 2 ", " NaN "),
            valid.replace("END", ""),
            valid.replace("STATE 1 1 1", "STATE 1 1 .5"),
            valid.replace("SUPPORT R", "SUPPORT Wrong"),
            valid.replace("END", "SUPPORT R 0 0 2 4 -6 0\nEND"),
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                force_accounting.parse_output(text, {("SUPPORT", "R")}, 1)

    def test_v2_keeps_mpc_transfer_separate_from_load_and_contact(self):
        from femtools import force_accounting

        # Public wire-contract fixture, not a simulated solver result. Native
        # analytical qualification separately establishes these physical terms.
        text = (
            "CCX_FORCE_ACCOUNTING_V2\nSTATE 1 1 1\n"
            "CUT Rear 0 0 -100 -500 500 0\n"
            "LOAD Rear 0 0 -1 -5 5 0\n"
            "CONTACT Rear 0 0 -2 -10 10 0\n"
            "MPC Rear 0 0 103 515 -515 0\nEND\n"
        )
        values = force_accounting.parse_output(text, {("CUT", "Rear")}, 1)
        self.assertEqual(values["MPC"]["Rear"], [0, 0, 103, 515, -515, 0])
        self.assertEqual(values["LOAD"]["Rear"], [0, 0, -1, -5, 5, 0])
        self.assertEqual(values["CONTACT"]["Rear"], [0, 0, -2, -10, 10, 0])
        for invalid in (
            text.replace("MPC Rear 0 0 103 515 -515 0\n", ""),
            text.replace("MPC Rear", "MPC Wrong"),
            text.replace("103 515 -515", "102 515 -515"),
            text.replace("103 515 -515", "103 514 -515"),
            text.replace("103 515 -515", "NaN 515 -515"),
            text.replace("V2", "V1"),
        ):
            with self.subTest(text=invalid), self.assertRaises(ValueError):
                force_accounting.parse_output(invalid, {("CUT", "Rear")}, 1)

    def test_v2_request_cannot_import_a_downgraded_v1_output(self):
        from femtools import force_accounting

        model = self.make_native_model()
        with tempfile.TemporaryDirectory() as directory:
            fea, context = self.make_import_context(model, directory)
            context[1]["schema"] = force_accounting.SCHEMA
            with self.assertRaisesRegex(ValueError, "unsupported native accounting output"):
                force_accounting.import_result(fea, context)
            self.assertFalse(
                any(
                    isinstance(getattr(obj, "Proxy", None), force_accounting.AccountingResult)
                    for obj in model.analysis.Group
                )
            )

    def test_legacy_context_cannot_import_an_unrequested_v2_output(self):
        from femtools import force_accounting

        model = self.make_native_model()
        with tempfile.TemporaryDirectory() as directory:
            fea, context = self.make_import_context(model, directory)
            self.assertNotIn("schema", context[1])
            context[2].write_text(context[2].read_text().replace("_V1", "_V2"))
            with self.assertRaisesRegex(ValueError, "unsupported native accounting output"):
                force_accounting.import_result(fea, context)

    def test_legacy_import_does_not_claim_mpc_capability(self):
        from femtools import force_accounting

        model = self.make_native_model()
        with tempfile.TemporaryDirectory() as directory:
            fea, context = self.make_import_context(model, directory)
            data = json.loads(force_accounting.import_result(fea, context).AccountingData)
            self.assertEqual(data.get("schema"), force_accounting.LEGACY_SCHEMA)
            self.assertNotIn("MPC", data["method"])
            self.assertNotIn("acyclic", data["limitations"])
            self.assertIn("no MPC cut bodies", data["limitations"])

    def test_result_restore_and_model_changes_invalidate(self):
        from femtools import force_accounting

        analysis = ObjectsFem.makeAnalysis(self.doc)
        box = self.doc.addObject("Part::Box", "Box")
        result = force_accounting.make_result(analysis)
        result.Status = "Current native accounting; not design acceptance"
        box.Length = 20
        self.assertTrue(result.Status.startswith("Stale"))
        result.Status = "Current native accounting; not design acceptance"
        result.Proxy.onDocumentRestored(result)
        self.assertTrue(result.Status.startswith("Stale"))

    def test_unknown_solver_capability_is_rejected(self):
        from femtools import force_accounting

        with self.assertRaises(ValueError):
            force_accounting.require_capability("/usr/bin/false")

    def test_capability_probe_is_private_even_when_the_solver_is_unsupported(self):
        """Replace only the child boundary; never create probe jobs in the project."""
        from subprocess import CompletedProcess
        from subprocess import DEVNULL

        from femtools import force_accounting

        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "probe-only-solver"
            binary.write_text("Adapter identity; never a physical solver\n")
            binary.chmod(0o700)
            for code, stdout in ((0, force_accounting.SCHEMA), (201, "Unsupported option")):
                with self.subTest(returncode=code):
                    observed = []

                    def query(command, **kwargs):
                        probe = Path(kwargs["cwd"])
                        self.assertTrue(probe.is_dir())
                        self.assertNotEqual(probe.resolve(), Path.cwd())
                        self.assertEqual(kwargs["stdin"], DEVNULL)
                        self.assertEqual(command[0], str(binary.resolve()))
                        marker = probe / "--freecad-force-accounting-version.dat"
                        marker.write_text("Simulated unsupported executable job artifact\n")
                        observed.append(marker)
                        return CompletedProcess(command, code, stdout=stdout, stderr="")

                    with patch("subprocess.run", side_effect=query):
                        if code:
                            with self.assertRaisesRegex(ValueError, "does not implement"):
                                force_accounting.require_capability(binary)
                        else:
                            force_accounting.require_capability(binary)
                    self.assertEqual(len(observed), 1)
                    self.assertFalse(observed[0].parent.exists())
            relative = os.path.relpath(binary, Path.cwd())
            for reference, environment in (
                (relative, None),
                (binary.name, {"PATH": str(Path(relative).parent)}),
            ):
                with self.subTest(reference=reference):

                    def query_relative(command, **kwargs):
                        self.assertEqual(command[0], str(binary.resolve()))
                        self.assertNotEqual(Path(kwargs["cwd"]).resolve(), Path.cwd())
                        return CompletedProcess(
                            command, 0, stdout=force_accounting.SCHEMA, stderr=""
                        )

                    with patch("subprocess.run", side_effect=query_relative):
                        force_accounting.require_capability(reference, environment=environment)

    def test_stock_export_refuses_complete_port_count_before_mesh_work(self):
        """Capacity is checked even before an unfinished model has a mesh.

        Only the external executable's query is replaced here. Native physical
        qualification separately exercises real finite faces and the solver.
        """
        from subprocess import CompletedProcess

        from femtools.ccxtools import FemToolsCcx

        analysis = ObjectsFem.makeAnalysis(self.doc)
        solver = ObjectsFem.makeSolverCalculiXCcxTools(self.doc)
        solver.NativeForceAccounting = True
        analysis.addObject(solver)
        support = ObjectsFem.makeConstraintFixed(self.doc)
        analysis.addObject(support)
        solver.NativeAccountingSupports = [support]
        for index in range(4):
            port = ObjectsFem.makeConstraintRigidBody(self.doc, f"MovingPort{index}")
            analysis.addObject(port)
        capacity = {
            "schema": "CCX_FORCE_ACCOUNTING_CAPACITY_V1",
            "request_schema": "CCX_FORCE_ACCOUNTING_V3",
            "allocation": "dynamic",
            "counting_policy": "top-level-declarations-v1",
            "total_records": 3,
            "limits": dict.fromkeys(("supports", "bodies", "ports", "angles", "springs"), 3),
        }

        def query(command, **kwargs):
            option = command[-1]
            self.assertIn(
                option,
                ("--freecad-force-accounting-version", "--freecad-force-accounting-capacity"),
            )
            text = (
                "CCX_FORCE_ACCOUNTING_V3\n" if option.endswith("-version") else json.dumps(capacity)
            )
            return CompletedProcess(command, 0, stdout=text, stderr="")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "query-only-solver"
            binary.write_bytes(b"External capacity-query adapter; never a physical solver\n")
            solver.NativeAccountingSolver = str(binary)
            output = root / "export"
            output.mkdir()
            fea = FemToolsCcx(analysis=analysis, solver=solver)
            fea.update_objects()
            fea.setup_working_dir(str(output))
            with patch("subprocess.run", side_effect=query):
                with self.assertRaisesRegex(ValueError, "ports required 4; supported 3"):
                    fea.write_inp_file()
            self.assertEqual(list(output.iterdir()), [])

    def test_cut_request_cannot_silently_fall_back_to_stress_output(self):
        from femtools import force_accounting

        solver = ObjectsFem.makeSolverCalculiXCcxTools(self.doc)
        section = ObjectsFem.makeConstraintSectionPrint(self.doc)
        section.NativeEquilibriumCut = True
        writer = SimpleNamespace(
            solver_obj=solver,
            mesh_object=None,
            analysis=None,
            member=SimpleNamespace(cons_sectionprint=[{"Object": section}]),
        )
        with self.assertRaisesRegex(ValueError, "Enable NativeForceAccounting"):
            force_accounting.prepare_request(writer)

    def test_stock_export_records_complete_effective_capacity(self):
        """A normal export binds its full graph to the external resource policy."""
        from subprocess import CompletedProcess
        from femtools.ccxtools import FemToolsCcx

        model = self.make_native_model()
        model.material.Material = {
            "Name": "Export boundary material",
            "YoungsModulus": "20000 MPa",
            "PoissonRatio": "0.3",
            "Density": "1 kg/m^3",
        }
        solver = ObjectsFem.makeSolverCalculiXCcxTools(self.doc)
        solver.NativeForceAccounting = True
        solver.SplitInputWriter = False
        body = ObjectsFem.makeConstraintRigidBody(self.doc, "R")
        body.References = [(model.geometry, ["Solid1"])]
        for kind in ("Translational", "Rotational"):
            for axis in "XYZ":
                setattr(body, kind + "Mode" + axis, "Constraint")
        for obj in (solver, body):
            model.analysis.addObject(obj)
        self.doc.recompute()

        def query(command, **kwargs):
            capacity = {
                "schema": "CCX_FORCE_ACCOUNTING_CAPACITY_V1",
                "request_schema": "CCX_FORCE_ACCOUNTING_V3",
                "allocation": "dynamic",
                "counting_policy": "top-level-declarations-v1",
                "total_records": 2,
                "limits": dict.fromkeys(("supports", "bodies", "ports", "angles", "springs"), 2),
            }
            text = (
                "CCX_FORCE_ACCOUNTING_V3\n"
                if command[-1].endswith("-version")
                else json.dumps(capacity)
            )
            return CompletedProcess(command, 0, stdout=text, stderr="")

        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "query-only-solver"
            binary.write_bytes(b"External capacity adapter, not a physics solver\n")
            solver.NativeAccountingSolver = str(binary)
            fea = FemToolsCcx(analysis=model.analysis, solver=solver)
            fea.update_objects()
            fea.setup_working_dir(directory)
            with patch("subprocess.run", side_effect=query):
                fea.write_inp_file()
            request = Path(fea.inp_file_name).with_suffix(".accounting")
            metadata = json.loads(Path(str(request) + ".json").read_text())
            self.assertEqual(
                metadata["capacity"]["required"],
                {
                    "supports": 1,
                    "bodies": 0,
                    "ports": 1,
                    "angles": 0,
                    "springs": 0,
                },
            )
            self.assertEqual(metadata["capacity"]["objects"]["ports"], [body.Name])
            self.assertEqual(metadata["capacity"]["total"], 2)
            self.assertEqual(metadata["capacity"]["supported"]["total_records"], 2)
            self.assertEqual(
                metadata["capacity"]["binary_sha256"],
                hashlib.sha256(binary.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                metadata["request_sha256"], hashlib.sha256(request.read_bytes()).hexdigest()
            )
            self.assertFalse(any(hasattr(obj, "AccountingData") for obj in model.analysis.Group))

    def test_capacity_query_rejects_malformed_mappings_with_actionable_error(self):
        from subprocess import CompletedProcess
        from femtools import force_accounting

        analysis = ObjectsFem.makeAnalysis(self.doc)
        solver = ObjectsFem.makeSolverCalculiXCcxTools(self.doc)
        solver.NativeForceAccounting = True
        analysis.addObject(solver)
        names = ("supports", "bodies", "ports", "angles", "springs")
        malformed = {
            "schema": "CCX_FORCE_ACCOUNTING_CAPACITY_V1",
            "request_schema": "CCX_FORCE_ACCOUNTING_V3",
            "allocation": "dynamic",
            "counting_policy": "top-level-declarations-v1",
            "total_records": 2,
            "limits": list(names),
        }
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "query-only-solver"
            binary.write_bytes(b"External protocol adapter, not a physics solver\n")
            solver.NativeAccountingSolver = str(binary)
            for payload in (list(names), malformed):
                with self.subTest(payload=payload):

                    def query(command, **kwargs):
                        text = (
                            "CCX_FORCE_ACCOUNTING_V3\n"
                            if command[-1].endswith("-version")
                            else json.dumps(payload)
                        )
                        return CompletedProcess(command, 0, stdout=text, stderr="")

                    with patch("subprocess.run", side_effect=query):
                        with self.assertRaisesRegex(ValueError, "capacity.*invalid"):
                            force_accounting.capacity_preflight(analysis, solver)
