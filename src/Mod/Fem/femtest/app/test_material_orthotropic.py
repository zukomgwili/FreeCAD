# SPDX-License-Identifier: LGPL-2.1-or-later

"""Native orthotropic material data, orientations, and CalculiX export."""

import io
import math
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import FreeCAD as App
import ObjectsFem


MODULI = (
    "YoungsModulus1", "YoungsModulus2", "YoungsModulus3",
    "ShearModulus12", "ShearModulus13", "ShearModulus23",
)
RATIOS = ("PoissonRatio12", "PoissonRatio13", "PoissonRatio23")
ORTHOTROPIC_PROPERTIES = (
    "ElasticityModel", *MODULI, *RATIOS,
    "MaterialOrientation", "MaterialOrientationReference",
)


def configure_orthotropic(material):
    # This card deliberately has no isotropic YoungsModulus/PoissonRatio.
    material.Material = {"Name": "Directional elastic material", "Density": "7900 kg/m^3"}
    material.ElasticityModel = "Orthotropic"
    for name, value in zip(MODULI, (11000, 370, 370, 700, 600, 140)):
        setattr(material, name, f"{value} MPa")
    for name, value in zip(RATIOS, (0.02, 0.03, 0.4)):
        setattr(material, name, value)
    return material


class TestMaterialOrthotropic(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("MaterialOrthotropic")
        self.material = ObjectsFem.makeMaterialSolid(self.doc)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def assertVectorAlmostEqual(self, actual, expected):
        for first, second in zip(actual, expected):
            self.assertAlmostEqual(first, second, places=10)

    def assertRotationAlmostEqual(self, actual, expected):
        for vector in (App.Vector(1, 0, 0), App.Vector(0, 1, 0), App.Vector(0, 0, 1)):
            self.assertVectorAlmostEqual(actual.multVec(vector), expected.multVec(vector))

    def roundtrip(self):
        name = self.material.Name
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory, "material.FCStd"))
            self.doc.recompute()
            self.doc.saveAs(path)
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(path)
            self.doc.recompute(None, True)
            self.material = self.doc.getObject(name)

    def test_native_factory_defaults_and_property_units(self):
        material = self.material
        self.assertEqual(material.ElasticityModel, "Isotropic")
        self.assertEqual(material.getEnumerationsOfProperty("ElasticityModel"),
                         ["Isotropic", "Orthotropic"])
        for name in MODULI:
            self.assertEqual(material.getTypeIdOfProperty(name), "App::PropertyPressure")
            self.assertEqual(getattr(material, name).getValueAs("MPa").Value, 0)
        for name in RATIOS:
            self.assertEqual(material.getTypeIdOfProperty(name), "App::PropertyFloat")
            self.assertEqual(getattr(material, name), 0)
        self.assertEqual(material.getTypeIdOfProperty("MaterialOrientation"),
                         "App::PropertyRotation")
        self.assertEqual(material.getTypeIdOfProperty("MaterialOrientationReference"),
                         "App::PropertyLinkGlobal")
        self.assertIsNone(material.MaterialOrientationReference)
        self.assertRotationAlmostEqual(material.MaterialOrientation, App.Rotation())

    def test_engineering_constants_are_ordered_and_converted_to_mpa(self):
        from femtools.material_orthotropic import engineering_constants, validation_errors

        configure_orthotropic(self.material)
        self.material.YoungsModulus1 = "11 GPa"
        self.material.ShearModulus12 = "0.7 GPa"
        self.assertEqual(engineering_constants(self.material),
                         (11000, 370, 370, 0.02, 0.03, 0.4, 700, 600, 140))
        self.assertEqual(validation_errors(self.material), [])

    def test_legacy_document_migrates_without_changing_isotropic_card(self):
        card = {"Name": "Legacy", "YoungsModulus": "210000 MPa", "PoissonRatio": "0.3"}
        self.material.Material = card
        for name in ORTHOTROPIC_PROPERTIES:
            if name in self.material.PropertiesList:
                self.material.setPropertyStatus(name, "-LockDynamic")
                self.material.removeProperty(name)
        self.roundtrip()
        self.assertEqual(self.material.ElasticityModel, "Isotropic")
        self.assertEqual(self.material.Material, card)
        self.assertTrue(set(ORTHOTROPIC_PROPERTIES).issubset(self.material.PropertiesList))
        self.assertRotationAlmostEqual(self.material.MaterialOrientation, App.Rotation())

    def test_native_constants_references_and_effective_rotation_survive_cold_reopen(self):
        from femtools.material_orthotropic import engineering_constants, material_rotation

        configure_orthotropic(self.material)
        parent = self.doc.addObject("App::Part", "ParentFrame")
        parent.Placement = App.Placement(App.Vector(30, 10, -2),
                                         App.Rotation(App.Vector(1, 0, 0), 20))
        reference = self.doc.addObject("PartDesign::Plane", "MaterialFrame")
        parent.addObject(reference)
        reference.Placement = App.Placement(App.Vector(4, 5, 6),
                                            App.Rotation(App.Vector(0, 0, 1), 30))
        region = self.doc.addObject("Part::Feature", "Region")
        self.material.References = [(region, ["Solid1"])]
        self.material.MaterialOrientationReference = reference
        self.material.MaterialOrientation = App.Rotation(App.Vector(0, 1, 0), 10)
        expected = reference.getGlobalPlacement().Rotation * self.material.MaterialOrientation
        self.assertRotationAlmostEqual(material_rotation(self.material), expected)
        self.roundtrip()
        self.assertEqual(engineering_constants(self.material),
                         (11000, 370, 370, 0.02, 0.03, 0.4, 700, 600, 140))
        self.assertEqual(self.material.MaterialOrientationReference.Name, "MaterialFrame")
        self.assertEqual(self.material.References[0][0].Name, "Region")
        self.assertEqual(tuple(self.material.References[0][1]), ("Solid1",))
        self.assertRotationAlmostEqual(material_rotation(self.material), expected)

    def test_placed_link_occurrence_frame_survives_cold_reopen(self):
        from femtools.material_orthotropic import material_rotation

        configure_orthotropic(self.material)
        source = self.doc.addObject("Part::Feature", "SourceGeometry")
        source.Placement = App.Placement(App.Vector(2, 3, 4),
                                         App.Rotation(App.Vector(0, 0, 1), 15))
        parent = self.doc.addObject("App::Part", "OccurrenceParent")
        parent.Placement = App.Placement(App.Vector(10, 20, 30),
                                         App.Rotation(App.Vector(1, 0, 0), 20))
        occurrence = self.doc.addObject("App::Link", "Occurrence")
        occurrence.setLink(source)
        parent.addObject(occurrence)
        occurrence.Placement = App.Placement(App.Vector(7, 8, 9),
                                             App.Rotation(App.Vector(0, 0, 1), 90))
        self.material.MaterialOrientationReference = occurrence
        self.material.MaterialOrientation = App.Rotation(App.Vector(0, 1, 0), 30)
        expected = (parent.Placement.Rotation * occurrence.Placement.Rotation
                    * self.material.MaterialOrientation)
        self.doc.recompute()
        self.assertRotationAlmostEqual(material_rotation(self.material), expected)
        self.roundtrip()
        self.assertEqual(self.material.MaterialOrientationReference.TypeId, "App::Link")
        self.assertEqual(self.material.MaterialOrientationReference.LinkedObject.Name,
                         "SourceGeometry")
        self.assertRotationAlmostEqual(material_rotation(self.material), expected)

    def test_nonpositive_moduli_are_rejected(self):
        from femtools.material_orthotropic import engineering_constants, validation_errors

        for name in MODULI:
            for value in (0, -1):
                with self.subTest(property=name, value=value):
                    configure_orthotropic(self.material)
                    setattr(self.material, name, f"{value} MPa")
                    self.assertTrue(validation_errors(self.material))
                    with self.assertRaises(ValueError):
                        engineering_constants(self.material)

    def test_nonfinite_values_are_rejected(self):
        from femtools.material_orthotropic import engineering_constants, validation_errors

        for name in (*MODULI, *RATIOS):
            for value in (math.nan, math.inf, -math.inf):
                with self.subTest(property=name, value=value):
                    configure_orthotropic(self.material)
                    # A native property may reject the nonfinite assignment itself.
                    try:
                        setattr(self.material, name, value)
                    except (ValueError, OverflowError):
                        continue
                    self.assertTrue(validation_errors(self.material))
                    with self.assertRaises(ValueError):
                        engineering_constants(self.material)

    def test_nonpositive_definite_compliance_is_rejected(self):
        from femtools.material_orthotropic import engineering_constants, validation_errors

        configure_orthotropic(self.material)
        for name in MODULI:
            setattr(self.material, name, "1000 MPa")
        for name in RATIOS:
            setattr(self.material, name, 0.9)
        self.assertTrue(validation_errors(self.material))
        with self.assertRaises(ValueError):
            engineering_constants(self.material)
        # Individually plausible nu12 still becomes unstable through reciprocity
        # when E2/E1 is large. Checking -1 < nu < .5 alone is insufficient.
        configure_orthotropic(self.material)
        self.material.YoungsModulus1 = "1 MPa"
        self.material.YoungsModulus2 = "1000 MPa"
        self.material.PoissonRatio12 = 0.4
        with self.assertRaises(ValueError):
            engineering_constants(self.material)

    def test_stable_orthotropic_poisson_ratio_need_not_obey_isotropic_limit(self):
        from femtools.material_orthotropic import engineering_constants, validation_errors

        configure_orthotropic(self.material)
        self.material.PoissonRatio12 = 0.75
        self.assertEqual(validation_errors(self.material), [])
        self.assertEqual(engineering_constants(self.material)[3], 0.75)

    def test_compliance_that_becomes_singular_at_writer_precision_is_rejected(self):
        from femtools.material_orthotropic import engineering_constants, validation_errors

        configure_orthotropic(self.material)
        for name in MODULI:
            setattr(self.material, name, "1 MPa")
        self.material.PoissonRatio12 = 0.99999999999999
        self.material.PoissonRatio13 = 0
        self.material.PoissonRatio23 = 0
        # Native doubles are still strictly stable, but the writer's 13G
        # serialization would round nu12 to 1 and destroy positive definiteness.
        self.assertLess(self.material.PoissonRatio12, 1)
        self.assertEqual(float(f"{self.material.PoissonRatio12:.13G}"), 1)
        self.assertTrue(validation_errors(self.material))
        with self.assertRaisesRegex(ValueError, "output precision"):
            engineering_constants(self.material)

    def test_long_orientation_names_are_stable_bounded_and_distinct(self):
        from femtools.material_orthotropic import orientation_name

        prefix = "OrthotropicMaterial" + "A" * 90
        first = ObjectsFem.makeMaterialSolid(self.doc, prefix + "First")
        second = ObjectsFem.makeMaterialSolid(self.doc, prefix + "Second")
        self.assertGreater(len("ORIENT_" + first.Name), 80)
        names = [orientation_name(material) for material in (first, second)]
        self.assertNotEqual(names[0], names[1])
        for material, name in zip((first, second), names):
            self.assertLessEqual(len(name), 80)
            self.assertTrue(name.startswith("ORIENT_"))
            self.assertEqual(orientation_name(material), name)
        self.assertNotEqual(names[0][-12:], names[1][-12:])

    def test_nonplaced_orientation_reference_is_rejected(self):
        from femtools.material_orthotropic import material_rotation, validation_errors

        configure_orthotropic(self.material)
        self.material.MaterialOrientationReference = self.doc.addObject(
            "App::FeaturePython", "NotAPlacedFrame")
        self.assertTrue(validation_errors(self.material))
        with self.assertRaisesRegex(ValueError, "placed object"):
            material_rotation(self.material)

    def writer(self, materials=None):
        materials = materials or [self.material]
        return SimpleNamespace(
            analysis_type="static",
            solver_obj=SimpleNamespace(MaterialNonlinearity=False, ModelSpace="3D",
                                       ExcludeBendingStiffness=False),
            member=SimpleNamespace(mats_linear=[{"Object": obj} for obj in materials],
                                   cons_centrif=[], cons_selfweight=[],
                                   geos_beamsection=[], geos_shellthickness=[],
                                   geos_fluidsection=[]),
            mat_geo_sets=[{"ccx_elset": [index], "ccx_elset_name": f"Region{index}",
                           "mat_obj_name": obj.Name}
                          for index, obj in enumerate(materials, 1)],
        )

    def exported(self, writer):
        from femsolver.calculix.write_femelement_material import write_femelement_material
        from femsolver.calculix.write_femelement_geometry import write_femelement_geometry

        stream = io.StringIO()
        write_femelement_material(stream, writer)
        write_femelement_geometry(stream, writer)
        return stream.getvalue()

    def elastic_constants(self, text):
        lines = text.splitlines()
        index = next(i for i, line in enumerate(lines)
                     if line.upper() == "*ELASTIC, TYPE=ENGINEERING CONSTANTS")
        self.assertEqual(len(lines[index + 1].split(",")), 8)
        self.assertEqual(len(lines[index + 2].split(",")), 1)
        return tuple(float(value) for line in lines[index + 1:index + 3]
                     for value in line.split(","))

    def orientation_vectors(self, text, material):
        lines = text.splitlines()
        prefix = f"*ORIENTATION, NAME=ORIENT_{material.Name}".upper()
        index = next(i for i, line in enumerate(lines) if line.upper().startswith(prefix))
        values = tuple(float(value) for value in lines[index + 1].split(","))
        self.assertEqual(len(values), 6)
        return values[:3], values[3:]

    def test_writer_exports_engineering_constant_order_and_native_orientation(self):
        configure_orthotropic(self.material)
        self.material.MaterialOrientation = App.Rotation(App.Vector(0, 0, 1), 90)
        text = self.exported(self.writer())
        self.assertEqual(self.elastic_constants(text),
                         (11000, 370, 370, 0.02, 0.03, 0.4, 700, 600, 140))
        first, second = self.orientation_vectors(text, self.material)
        self.assertVectorAlmostEqual(first, (0, 1, 0))
        self.assertVectorAlmostEqual(second, (-1, 0, 0))
        section = next(line for line in text.splitlines() if line.startswith("*SOLID SECTION"))
        self.assertIn(f"MATERIAL={self.material.Name}", section)
        self.assertIn(f"ORIENTATION=ORIENT_{self.material.Name}", section)

    def test_two_material_regions_share_card_but_not_axes(self):
        configure_orthotropic(self.material)
        other = configure_orthotropic(ObjectsFem.makeMaterialSolid(self.doc, "OtherMaterial"))
        other.Material = self.material.Material
        other.MaterialOrientation = App.Rotation(App.Vector(0, 0, 1), 90)
        region1 = self.doc.addObject("Part::Feature", "FirstRegion")
        region2 = self.doc.addObject("Part::Feature", "SecondRegion")
        self.material.References = [(region1, ["Solid1"])]
        other.References = [(region2, ["Solid1"])]
        text = self.exported(self.writer([self.material, other]))
        for material, region in ((self.material, 1), (other, 2)):
            line = next(line for line in text.splitlines()
                        if line.startswith("*SOLID SECTION") and f"ELSET=Region{region}," in line)
            self.assertIn(f"MATERIAL={material.Name}", line)
            self.assertIn(f"ORIENTATION=ORIENT_{material.Name}", line)
        self.assertVectorAlmostEqual(self.orientation_vectors(text, self.material)[0], (1, 0, 0))
        self.assertVectorAlmostEqual(self.orientation_vectors(text, other)[0], (0, 1, 0))
        self.assertEqual(self.material.Material, other.Material)

    def test_orientation_parameter_change_regenerates_exported_frame(self):
        configure_orthotropic(self.material)
        reference = self.doc.addObject("Part::Feature", "ReferenceFrame")
        self.material.MaterialOrientationReference = reference
        writer = self.writer()
        first = self.exported(writer)
        reference.Placement = App.Placement(App.Vector(), App.Rotation(App.Vector(0, 0, 1), 90))
        self.doc.recompute()
        second = self.exported(writer)
        self.assertNotEqual(first, second)
        self.assertVectorAlmostEqual(self.orientation_vectors(first, self.material)[0], (1, 0, 0))
        self.assertVectorAlmostEqual(self.orientation_vectors(second, self.material)[0], (0, 1, 0))

    def test_shell_section_gets_its_material_orientation(self):
        configure_orthotropic(self.material)
        shell = ObjectsFem.makeElementGeometry2D(self.doc, thickness=2)
        writer = self.writer()
        writer.member.geos_shellthickness = [{"Object": shell}]
        writer.mat_geo_sets[0]["shellthickness_obj"] = shell
        text = self.exported(writer)
        line = next(line for line in text.splitlines() if line.startswith("*SHELL SECTION"))
        self.assertIn(f"ORIENTATION=ORIENT_{self.material.Name}", line)

    def test_writer_rejects_orthotropic_fluid_category(self):
        configure_orthotropic(self.material)
        self.material.Category = "Fluid"
        with self.assertRaisesRegex(ValueError, "solid-category"):
            self.exported(self.writer())

    def test_writer_rejects_unsupported_section_contexts(self):
        configure_orthotropic(self.material)
        for model_space, geometry_key, exclude_bending in (
            ("2D", None, False),
            ("3D", "beamsection_obj", False),
            ("3D", "beamsection_obj", True),
            ("3D", "fluidsection_obj", False),
        ):
            with self.subTest(space=model_space, geometry=geometry_key,
                              truss=exclude_bending):
                writer = self.writer()
                writer.solver_obj.ModelSpace = model_space
                writer.solver_obj.ExcludeBendingStiffness = exclude_bending
                if geometry_key:
                    writer.mat_geo_sets[0][geometry_key] = object()
                with self.assertRaisesRegex(ValueError, "3D solid/shell"):
                    self.exported(writer)

    def test_writer_rejects_active_isotropic_plasticity_on_orthotropic_material(self):
        configure_orthotropic(self.material)
        nonlinear = ObjectsFem.makeMaterialMechanicalNonlinear(self.doc, self.material)
        nonlinear.YieldPoints = ["235, 0", "400, 0.1"]
        writer = self.writer()
        writer.solver_obj.MaterialNonlinearity = True
        with self.assertRaisesRegex(ValueError, "isotropic plasticity"):
            self.exported(writer)
        nonlinear.Suppressed = True
        self.assertIn("TYPE=ENGINEERING CONSTANTS", self.exported(writer))

    def test_writer_rejects_orthotropic_membrane_section(self):
        configure_orthotropic(self.material)
        shell = ObjectsFem.makeElementGeometry2D(self.doc, thickness=2)
        writer = self.writer()
        writer.solver_obj.ExcludeBendingStiffness = True
        writer.member.geos_shellthickness = [{"Object": shell}]
        writer.mat_geo_sets[0]["shellthickness_obj"] = shell
        with self.assertRaisesRegex(ValueError, "3D solid/shell"):
            self.exported(writer)

    def test_z88_and_mystran_reject_native_orthotropy_before_output_side_effects(self):
        from femsolver.mystran import writer as mystran
        from femsolver.z88 import writer as z88

        configure_orthotropic(self.material)
        writer = SimpleNamespace(member=SimpleNamespace(mats_linear=[{"Object": self.material}]))
        with patch("builtins.open", side_effect=AssertionError("Must reject before opening files")):
            with self.assertRaisesRegex(ValueError, "Z88 exporter"):
                z88.FemInputWriterZ88.write_solver_input(writer)
            with patch.object(mystran, "BDF", create=True,
                              side_effect=AssertionError("Must reject before constructing BDF")):
                with self.assertRaisesRegex(ValueError, "Mystran exporter"):
                    mystran.FemInputWriterMystran.write_solver_input(writer)

    def test_elmer_mechanical_entrypoints_reject_native_orthotropy(self):
        from femsolver.elmer.equations.deformation_writer import DeformationWriter
        from femsolver.elmer.equations.elasticity_writer import ElasticityWriter

        configure_orthotropic(self.material)
        writer = SimpleNamespace(getMember=lambda name: [self.material],
                                 getSingleMember=lambda name: None,
                                 getEquations=lambda: [])
        solver = SimpleNamespace(Group=[])
        for exporter, method, message in (
            (ElasticityWriter, "handleElasticityMaterial", "Elmer elasticity exporter"),
            (DeformationWriter, "handleDeformationMaterial", "Elmer deformation exporter"),
        ):
            with self.subTest(exporter=exporter.__name__):
                with self.assertRaisesRegex(ValueError, message):
                    getattr(exporter(writer, solver), method)(["Solid1"])

    def test_isotropic_material_and_plasticity_export_are_unchanged(self):
        self.material.Material = {"Name": "Steel", "YoungsModulus": "210000 MPa",
                                  "PoissonRatio": "0.3"}
        nonlinear = ObjectsFem.makeMaterialMechanicalNonlinear(self.doc, self.material)
        nonlinear.MaterialModelNonlinearity = "kinematic hardening"
        nonlinear.YieldPoints = ["235, 0", "400, 0.1"]
        writer = self.writer()
        writer.solver_obj.MaterialNonlinearity = True
        text = self.exported(writer)
        self.assertIn("*ELASTIC\n210000,0.3\n", text)
        self.assertIn("*PLASTIC, HARDENING=KINEMATIC\n235, 0\n400, 0.1\n", text)
        self.assertNotIn("ENGINEERING CONSTANTS", text)
        self.assertNotIn("*ORIENTATION", text)
        self.assertNotIn("ORIENTATION=", text)


@unittest.skipUnless(shutil.which("ccx"), "Requires a real CalculiX executable on PATH")
class TestMaterialOrthotropicCalculiX(unittest.TestCase):
    def make_model(self, doc, blocks=1):
        import Fem
        import Part

        analysis = ObjectsFem.makeAnalysis(doc, "Analysis")
        solver = ObjectsFem.makeSolverCalculiXCcxTools(doc)
        analysis.addObject(solver)
        geometry = doc.addObject("Part::Feature", "Blocks")
        solids = [Part.makeBox(1, 1, 1, App.Vector(index, 0, 0))
                  for index in range(blocks)]
        geometry.Shape = solids[0] if blocks == 1 else Part.makeCompound(solids)
        material = configure_orthotropic(ObjectsFem.makeMaterialSolid(doc))
        for name, value in zip(MODULI, (1000, 2000, 3000, 400, 500, 600)):
            setattr(material, name, f"{value} MPa")
        for name, value in zip(RATIOS, (0.1, 0.05, 0.1)):
            setattr(material, name, value)
        analysis.addObject(material)
        mesh = Fem.FemMesh()
        nodes = {(x, y, z): mesh.addNode(x, y, z)
                 for x in range(blocks + 1) for y in range(2) for z in range(2)}
        for x in range(blocks):
            mesh.addVolume([nodes[point] for point in (
                (x, 0, 1), (x + 1, 0, 1), (x + 1, 1, 1), (x, 1, 1),
                (x, 0, 0), (x + 1, 0, 0), (x + 1, 1, 0), (x, 1, 0))])
        mesh_obj = ObjectsFem.makeMeshGmsh(doc, "Mesh")
        mesh_obj.Shape = geometry
        mesh_obj.FemMesh = mesh
        analysis.addObject(mesh_obj)
        return analysis, solver, geometry, material, mesh_obj

    def face(self, geometry, axis, coordinate, normal):
        return next(f"Face{i}" for i, face in enumerate(geometry.Shape.Faces, 1)
                    if abs(face.CenterOfMass[axis] - coordinate) < 1e-8
                    and abs(face.normalAt(0, 0)[axis] - normal) < 1e-8)

    def solve(self, doc, analysis, solver):
        from femtools.ccxtools import FemToolsCcx

        doc.recompute()
        with tempfile.TemporaryDirectory() as directory:
            solver.WorkingDir = directory
            prefs = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/General")
            overwrite = prefs.GetBool("OverwriteSolverWorkingDirectory", True)
            try:
                prefs.SetBool("OverwriteSolverWorkingDirectory", False)
                fea = FemToolsCcx(analysis=analysis, solver=solver)
                fea.purge_results()
                self.assertTrue(fea.run())
            finally:
                prefs.SetBool("OverwriteSolverWorkingDirectory", overwrite)
            self.assertTrue(fea.results_present)
            result = next(obj for obj in doc.Objects
                          if "DisplacementVectors" in obj.PropertiesList)
            return (dict(zip(result.NodeNumbers, result.DisplacementVectors)),
                    Path(directory, "Mesh.inp").read_text(),
                    Path(directory, "Mesh.dat").read_text())

    def test_nonzero_poisson_ratios_and_reciprocity_under_three_axial_loads(self):
        # The symmetry constraints remove rigid motion without inhibiting the
        # homogeneous transverse strains. This checks compliance, not just E_i.
        compliance = ((1 / 1000, -0.1 / 1000, -0.05 / 1000),
                      (-0.1 / 1000, 1 / 2000, -0.1 / 2000),
                      (-0.05 / 1000, -0.1 / 2000, 1 / 3000))
        for loaded_axis in range(3):
            with self.subTest(loaded_axis=loaded_axis):
                doc = App.newDocument("OrthotropicPoisson")
                try:
                    analysis, solver, geometry, material, mesh = self.make_model(doc)
                    for axis, letter in enumerate("xyz"):
                        displacement = ObjectsFem.makeConstraintDisplacement(
                            doc, f"Symmetry{letter}")
                        displacement.References = [(geometry, self.face(geometry, axis, 0, -1))]
                        for free in "xyz":
                            setattr(displacement, free + "Free", free != letter)
                        analysis.addObject(displacement)
                    pressure = ObjectsFem.makeConstraintPressure(doc)
                    pressure.References = [(geometry, self.face(geometry, loaded_axis, 1, 1))]
                    pressure.Pressure = "1 MPa"
                    analysis.addObject(pressure)
                    displacements, _, _ = self.solve(doc, analysis, solver)
                    self.assertEqual(len(displacements), 8)
                    for node, displacement in displacements.items():
                        point = mesh.FemMesh.getNodeById(node)
                        for axis in range(3):
                            expected = -compliance[axis][loaded_axis] * point[axis]
                            self.assertAlmostEqual(displacement[axis], expected, delta=1e-8)
                finally:
                    App.closeDocument(doc.Name)

    def test_affine_shear_uses_g13_g23_and_swaps_them_with_material_rotation(self):
        gamma = 0.001
        for angle in (0, 90):
            for shear_axis in (0, 1):
                with self.subTest(angle=angle, shear_axis=shear_axis):
                    doc = App.newDocument("OrthotropicShear")
                    try:
                        analysis, solver, geometry, material, _ = self.make_model(doc)
                        material.MaterialOrientation = App.Rotation(App.Vector(0, 0, 1), angle)
                        fixed = ObjectsFem.makeConstraintFixed(doc)
                        fixed.References = [(geometry, self.face(geometry, 2, 0, -1))]
                        analysis.addObject(fixed)
                        top = ObjectsFem.makeConstraintDisplacement(doc, "Top")
                        top.References = [(geometry, self.face(geometry, 2, 1, 1))]
                        for axis, letter in enumerate("xyz"):
                            setattr(top, letter + "Free", False)
                            setattr(top, letter + "Displacement",
                                    gamma if axis == shear_axis else 0)
                        analysis.addObject(top)
                        _, _, data = self.solve(doc, analysis, solver)
                        modulus = (500, 600)[shear_axis if angle == 0 else 1 - shear_axis]
                        for name, sign in ((top.Name, 1), (fixed.Name, -1)):
                            match = re.search(
                                rf"total force[^\n]*for set {name.upper()}[^\n]*\n\s*\n([^\n]+)",
                                data)
                            self.assertIsNotNone(match)
                            reaction = tuple(float(value) for value in match.group(1).split())
                            for axis in range(3):
                                expected = sign * modulus * gamma if axis == shear_axis else 0
                                self.assertAlmostEqual(reaction[axis], expected, delta=1e-6)
                    finally:
                        App.closeDocument(doc.Name)

    def test_two_native_regions_assign_conforming_cells_and_independent_axes(self):
        doc = App.newDocument("OrthotropicRegions")
        try:
            analysis, solver, geometry, first, mesh = self.make_model(doc, blocks=2)
            second = configure_orthotropic(ObjectsFem.makeMaterialSolid(doc, "OtherMaterial"))
            second.Material = first.Material
            for name in MODULI:
                setattr(second, name, getattr(first, name))
            for material in (first, second):
                for name in RATIOS:
                    setattr(material, name, 0)
            first.References = [(geometry, ["Solid1"])]
            second.References = [(geometry, ["Solid2"])]
            second.MaterialOrientation = App.Rotation(App.Vector(0, 0, 1), 90)
            analysis.addObject(second)
            fixed = ObjectsFem.makeConstraintFixed(doc)
            fixed.References = [(geometry, self.face(geometry, 0, 0, -1))]
            analysis.addObject(fixed)
            pressure = ObjectsFem.makeConstraintPressure(doc)
            pressure.References = [(geometry, self.face(geometry, 0, 2, 1))]
            pressure.Pressure = "1 MPa"
            analysis.addObject(pressure)
            for swapped in (False, True):
                with self.subTest(swapped=swapped):
                    if swapped:
                        first.References = [(geometry, ["Solid2"])]
                        second.References = [(geometry, ["Solid1"])]
                    displacements, deck, _ = self.solve(doc, analysis, solver)
                    sections = [line for line in deck.splitlines()
                                if line.startswith("*SOLID SECTION")]
                    self.assertEqual(len(sections), 2)
                    ordered = (second, first) if swapped else (first, second)
                    for material, volume in zip(ordered, mesh.FemMesh.Volumes):
                        section = next(line for line in sections
                                       if f"MATERIAL={material.Name}," in line)
                        self.assertIn(f"ORIENTATION=ORIENT_{material.Name}", section)
                        elset = re.search(r"ELSET=([^,\s]+)", section).group(1)
                        match = re.search(rf"\*ELSET,ELSET={re.escape(elset)}\n([^*]+)", deck)
                        self.assertIsNotNone(match)
                        assigned = [int(value) for value
                                    in match.group(1).replace("\n", ",").split(",")
                                    if value.strip()]
                        self.assertEqual(assigned, [volume])
                    left, right = (2000, 1000) if swapped else (1000, 2000)
                    for node, displacement in displacements.items():
                        x = mesh.FemMesh.getNodeById(node).x
                        expected = -min(x, 1) / left - max(x - 1, 0) / right
                        self.assertAlmostEqual(displacement.x, expected, delta=1e-8)
                        self.assertAlmostEqual(displacement.y, 0, delta=1e-9)
                        self.assertAlmostEqual(displacement.z, 0, delta=1e-9)
        finally:
            App.closeDocument(doc.Name)

    def test_quad8_shell_affine_membrane_patch_respects_material_orientation(self):
        import Fem
        import Part

        for angle, modulus in ((0, 12000), (90, 3000)):
            with self.subTest(angle=angle):
                doc = App.newDocument("OrthotropicShell")
                try:
                    analysis = ObjectsFem.makeAnalysis(doc, "Analysis")
                    solver = ObjectsFem.makeSolverCalculiXCcxTools(doc)
                    analysis.addObject(solver)
                    geometry = doc.addObject("Part::Feature", "Plate")
                    geometry.Shape = Part.makePlane(1, 1)
                    material = configure_orthotropic(ObjectsFem.makeMaterialSolid(doc))
                    for name, value in zip(MODULI, (12000, 3000, 1500, 700, 600, 500)):
                        setattr(material, name, f"{value} MPa")
                    for name in RATIOS:
                        setattr(material, name, 0)
                    material.MaterialOrientation = App.Rotation(App.Vector(0, 0, 1), angle)
                    analysis.addObject(material)
                    thickness = ObjectsFem.makeElementGeometry2D(doc, thickness=1)
                    analysis.addObject(thickness)
                    mesh = Fem.FemMesh()
                    points = ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
                              (0.5, 0, 0), (1, 0.5, 0), (0.5, 1, 0), (0, 0.5, 0))
                    references = {}
                    for node, point in enumerate(points, 1):
                        mesh.addNode(*point, node)
                        vertex = doc.addObject("Part::Feature", f"Node{node}")
                        vertex.Shape = Part.Vertex(App.Vector(*point))
                        references[node] = (vertex, ["Vertex1"])
                    mesh.addFace(list(range(1, 9)))
                    mesh_obj = ObjectsFem.makeMeshGmsh(doc, "Mesh")
                    mesh_obj.Shape = geometry
                    mesh_obj.FemMesh = mesh
                    analysis.addObject(mesh_obj)
                    for name, x, nodes in (("Left", 0, (1, 4, 8)),
                                           ("Middle", 0.5, (5, 7)),
                                           ("Right", 1, (2, 3, 6))):
                        displacement = ObjectsFem.makeConstraintDisplacement(doc, name)
                        displacement.References = [references[node] for node in nodes]
                        for axis in "xyz":
                            setattr(displacement, axis + "Free", False)
                            setattr(displacement, axis + "Displacement",
                                    0.001 * x if axis == "x" else 0)
                        for axis in "xyz":
                            setattr(displacement, "rot" + axis + "Free", False)
                            setattr(displacement, axis + "Rotation", 0)
                        analysis.addObject(displacement)
                    _, deck, data = self.solve(doc, analysis, solver)
                    self.assertIn("TYPE=S8R", deck)
                    section = next(line for line in deck.splitlines()
                                   if line.startswith("*SHELL SECTION"))
                    self.assertIn(f"ORIENTATION=ORIENT_{material.Name}", section)
                    for name, sign in (("Right", 1), ("Left", -1)):
                        match = re.search(
                            rf"total force[^\n]*for set {name.upper()}[^\n]*\n\s*\n([^\n]+)",
                            data)
                        self.assertIsNotNone(match)
                        reaction = tuple(float(value) for value in match.group(1).split())
                        self.assertAlmostEqual(reaction[0], sign * modulus * 0.001, delta=1e-5)
                        self.assertAlmostEqual(reaction[1], 0, delta=1e-6)
                        self.assertAlmostEqual(reaction[2], 0, delta=1e-6)
                finally:
                    App.closeDocument(doc.Name)

    def test_rotating_native_material_swaps_analytic_axial_modulus(self):
        """A single constant-strain Hex8, nu=0: ux=-p*L/E along global X."""
        measured = []
        for angle, modulus in ((0, 1000), (90, 2000)):
            with self.subTest(angle=angle):
                doc = App.newDocument("OrthotropicAxial")
                try:
                    analysis, solver, geometry, material, mesh = self.make_model(doc)
                    for name in RATIOS:
                        setattr(material, name, 0)
                    material.MaterialOrientation = App.Rotation(App.Vector(0, 0, 1), angle)
                    fixed = ObjectsFem.makeConstraintFixed(doc)
                    fixed.References = [(geometry, self.face(geometry, 0, 0, -1))]
                    analysis.addObject(fixed)
                    pressure = ObjectsFem.makeConstraintPressure(doc)
                    pressure.References = [(geometry, self.face(geometry, 0, 1, 1))]
                    pressure.Pressure = "1 MPa"
                    analysis.addObject(pressure)
                    displacements, _, _ = self.solve(doc, analysis, solver)
                    self.assertEqual(len(displacements), 8)
                    loaded = []
                    for node, displacement in displacements.items():
                        point = mesh.FemMesh.getNodeById(node)
                        self.assertAlmostEqual(displacement.y, 0, delta=1e-9)
                        self.assertAlmostEqual(displacement.z, 0, delta=1e-9)
                        self.assertAlmostEqual(displacement.x, -point.x / modulus, delta=1e-8)
                        if point.x > 0.5:
                            loaded.append(displacement.x)
                    self.assertEqual(len(loaded), 4)
                    measured.append(sum(loaded) / len(loaded))
                finally:
                    App.closeDocument(doc.Name)
        self.assertEqual(len(measured), 2)
        self.assertAlmostEqual(measured[0] / measured[1], 2, places=6)
