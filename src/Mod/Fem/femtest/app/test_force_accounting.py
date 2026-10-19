# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native accounting interface tests, independent of a particular solver binary."""

import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

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
        return SimpleNamespace(
            analysis=analysis, mesh=mesh, geometry=geometry, material=material
        )

    def test_reading_native_material_does_not_change_input_identity(self):
        from femmesh import quality
        from femtools import force_accounting

        model = self.make_native_model()
        digest = force_accounting._model_digest(model.analysis, model.mesh)
        fingerprint = quality.input_fingerprint(model.mesh)
        # A property read copies the native Material into a Python wrapper.
        # Keeping that copy alive must not change the physical input identity.
        retained = [model.geometry.ShapeMaterial]
        self.assertEqual(
            force_accounting._model_digest(model.analysis, model.mesh), digest
        )
        self.assertEqual(quality.input_fingerprint(model.mesh), fingerprint)
        retained.extend(model.geometry.ShapeMaterial for _ in range(32))
        self.assertEqual(
            force_accounting._model_digest(model.analysis, model.mesh), digest
        )
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
        output.write_text(
            "CCX_FORCE_ACCOUNTING_V1\nSTATE 1 1 1\nSUPPORT R 0 0 2 4 -6 0\nEND\n"
        )

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
        fea = SimpleNamespace(
            analysis=model.analysis, mesh=model.mesh, inp_file_name=str(deck)
        )
        return fea, ({}, metadata, output)

    def test_retained_native_material_import_and_historical_restore(self):
        from femtools import force_accounting

        model = self.make_native_model()
        with tempfile.TemporaryDirectory() as directory:
            fea, context = self.make_import_context(model, directory)
            retained = [model.geometry.ShapeMaterial for _ in range(32)]
            result = force_accounting.import_result(fea, context)
            self.assertEqual(
                result.Status, "Current native accounting; not design acceptance"
            )
            data, resultants = result.AccountingData, list(result.Resultants)
            self.assertEqual(
                json.loads(data)["wrenches"]["SUPPORT"]["R"], [0, 0, 2, 4, -6, 0]
            )
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
            "material": lambda m: setattr(
                m.material, "Material", {"Density": "7901 kg/m^3"}
            ),
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
            "solver nonlinearity": lambda m: setattr(
                m.solver, "GeometricalNonlinearity", True
            ),
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
                with self.assertRaisesRegex(
                    ValueError, r"changed while solving \(model_digest\)"
                ):
                    force_accounting.import_result(fea, context)
                self.assertTrue(control.Status.startswith("Stale"))

    def test_changed_solver_files_during_solve_cannot_import_current(self):
        from femtools import force_accounting

        for identity in ("deck_sha256", "request_sha256", "binary_sha256"):
            with self.subTest(
                identity=identity
            ), tempfile.TemporaryDirectory() as directory:
                model = self.make_native_model()
                fea, context = self.make_import_context(model, directory)
                control = force_accounting.import_result(fea, context)
                self.assertTrue(control.Status.startswith("Current"))
                paths = {
                    "deck_sha256": Path(fea.inp_file_name),
                    "request_sha256": Path(fea.inp_file_name).with_suffix(
                        ".accounting"
                    ),
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
            "quantity precision": lambda m: m.setPhysicalValue(
                "TestQuantity", "19.7612342 kg/m^3"
            ),
            "float precision": lambda m: m.setPhysicalValue("TestFloat", "32.170008"),
            "list": lambda m: m.setValue("TestList", ["first", "different"]),
            "array2d": lambda m: change_array(m),
            "array3d cell": lambda m: change_array(m, three_dimensions=True),
            "array3d depth": lambda m: change_array(m, depth=True),
            "appearance": lambda m: m.setAppearanceValue(
                "DiffuseColor", "(0.125, 0.25, 0.5)"
            ),
            "identity metadata": lambda m: setattr(
                m, "Description", "Changed description"
            ),
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
                self.assertTrue(
                    all(property_value(wrapper) == baseline for wrapper in wrappers)
                )
                changed = model.geometry.ShapeMaterial
                change(changed)
                self.assertEqual(changed.UUID, material.UUID)
                self.assertNotEqual(property_value(changed), baseline)
                model.geometry.ShapeMaterial = changed
                self.assertNotEqual(
                    property_value(model.geometry.ShapeMaterial), baseline
                )
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
        self.assertEqual(
            float.fromhex(zero["physical"]["Density"]["quantity"]["float"]), 0.0
        )

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
                self.assertNotEqual(
                    property_value(model.geometry.ShapeMaterial), baseline
                )
                self.assertNotEqual(
                    force_accounting._model_digest(model.analysis, model.mesh), digest
                )
                self.assertNotEqual(quality.input_fingerprint(model.mesh), fingerprint)

    def test_ambiguous_or_lossy_native_material_properties_are_rejected(self):
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

        mixed_array = Materials.Material()
        mixed_array.addPhysicalModel(Materials.UUIDs().OgdenN1)
        array = mixed_array.getPhysicalValue("OgdenN1")
        self.assertTrue(mixed_array.PropertyObjects["OgdenN1"].Empty)
        # A genuinely empty declared array can be represented by dimensions.
        property_value(mixed_array)
        array.Rows = 1
        for column, value in enumerate(("20 C", "1000 Pa", "2", "0.001 1/Pa")):
            array.setValue(0, column, value)
        mixed_array.setValue("OgdenN1", array)
        self.assertFalse(mixed_array.PropertyObjects["OgdenN1"].Empty)
        self.assertIn(
            "Float",
            [column.Type for column in mixed_array.PropertyObjects["OgdenN1"].Columns],
        )

        null_array = Materials.Material()
        null_array.addPhysicalModel(Materials.UUIDs().TestModel)
        array = null_array.getPhysicalValue("TestArray2D")
        array.Rows = 1  # Native resize creates null QVariant cells.
        null_array.setValue("TestArray2D", array)
        empty_cells = array.Array
        array.setValue(0, 0, "0")
        # The Python getter loses that change.
        self.assertEqual(array.Array, empty_cells)
        null_array.setValue("TestArray2D", array)

        for material, message in (
            (overlap, "Ambiguous native material physical/appearance"),
            (mixed_array, "non-Quantity columns"),
            (null_array, "ambiguous null/zero cells"),
        ):
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
        for text in (
            valid.replace(" 2 ", " NaN "),
            valid.replace("END", ""),
            valid.replace("STATE 1 1 1", "STATE 1 1 .5"),
            valid.replace("SUPPORT R", "SUPPORT Wrong"),
            valid.replace("END", "SUPPORT R 0 0 2 4 -6 0\nEND"),
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                force_accounting.parse_output(text, {("SUPPORT", "R")}, 1)

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
