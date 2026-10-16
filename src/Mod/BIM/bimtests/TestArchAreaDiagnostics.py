# SPDX-License-Identifier: LGPL-2.1-or-later

"""Optional area failure must not invalidate valid BIM material geometry.

The 3.4 KB native face fixture is minimized from FreeCAD-0o1. Its shared
vertices have legitimate kernel tolerances, but TechDraw projection separates
one edge from the inner loop. Planar face projection must retain the original
topology; failure injection still qualifies safe optional-error handling.
"""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import Arch
import ArchComponent
import FreeCAD as App
import Part
from bimtests.TestArchBase import TestArchBase


class TestArchAreaDiagnostics(TestArchBase):
    def setUp(self):
        super().setUp()
        self.arch_params = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Arch")
        self.old_max = (self.arch_params.GetInt("MaxComputeAreas")
                        if "MaxComputeAreas" in self.arch_params.GetInts() else None)
        self.arch_params.SetInt("MaxComputeAreas", 20)
        self.debug_params = App.ParamGet("User parameter:BaseApp/Preferences/Mod/TechDraw/debug")
        self.old_crazy = (self.debug_params.GetBool("allowCrazyEdge")
                          if "allowCrazyEdge" in self.debug_params.GetBools() else None)

    def tearDown(self):
        self.restore_preference()
        if self.old_max is None:
            self.arch_params.RemInt("MaxComputeAreas")
        else:
            self.arch_params.SetInt("MaxComputeAreas", self.old_max)
        super().tearDown()

    def restore_preference(self):
        if self.old_crazy is None:
            self.debug_params.RemBool("allowCrazyEdge")
        else:
            self.debug_params.SetBool("allowCrazyEdge", self.old_crazy)

    def set_preference(self, value):
        if value is None:
            self.debug_params.RemBool("allowCrazyEdge")
        else:
            self.debug_params.SetBool("allowCrazyEdge", value)

    def assert_preference(self, value):
        self.assertEqual("allowCrazyEdge" in self.debug_params.GetBools(), value is not None)
        if value is not None:
            self.assertEqual(self.debug_params.GetBool("allowCrazyEdge"), value)

    @staticmethod
    def projection_face():
        shape = Part.Shape()
        shape.read(str(Path(__file__).parent / "fixtures" / "area_projection_open_loop.brep"))
        return shape.Faces[0]

    def make_model(self):
        profile = self.document.addObject("Part::Feature", "Profile")
        profile.Shape = self.projection_face()
        extrusion = self.document.addObject("Part::Extrusion", "Extrusion")
        extrusion.Base = profile
        extrusion.Dir = App.Vector(0, 0, 100)
        extrusion.Solid = True
        covering = Arch.makeStructure(extrusion, name="Covering")
        other = self.document.addObject("Part::Box", "Other")
        other.Placement.Base = App.Vector(750, -142.5, 90)
        union = self.document.addObject("Part::MultiFuse", "Downstream")
        union.Shapes = [covering, other]
        return covering, union

    def assert_model(self, covering, union):
        self.assertNotIn("Invalid", covering.State)
        self.assertNotIn("Touched", covering.State)
        self.assertTrue(covering.Shape.isValid())
        self.assertGreater(covering.Shape.Volume, 0)
        self.assertFalse(union.Shape.isNull())
        self.assertTrue(union.Shape.isValid())
        self.assertNotIn("Touched", union.State)
        self.assertNotIn("Invalid", union.State)

    def assert_zero_areas(self, obj):
        for prop in ("VerticalArea", "HorizontalArea", "PerimeterLength"):
            self.assertEqual(getattr(obj, prop).Value, 0, prop)

    def assert_fixture_quantities(self, obj):
        # A fixture-specific numerical budget, never passed to a geometry API.
        # Native extrusion integration differs from the original20,000mm2
        # profile by9.94e-5mm2 because its inherited vertices are toleranced.
        self.assertAlmostEqual(obj.HorizontalArea.Value, 20000, delta=1e-3)
        self.assertAlmostEqual(obj.PerimeterLength.Value, 900, delta=1e-6)
        self.assertAlmostEqual(obj.VerticalArea.Value, 160000, delta=1e-3)

    def test_native_recompute_save_reopen(self):
        covering, union = self.make_model()
        with patch.object(App.Console, "PrintWarning") as warning:
            self.document.recompute()
        self.assert_model(covering, union)
        self.assert_fixture_quantities(covering)
        self.assertFalse(warning.called)
        before = (covering.Shape.Volume, union.Shape.Volume)
        covering_name, union_name = covering.Name, union.Name
        with TemporaryDirectory() as directory:
            filename = str(Path(directory) / "optional-area.FCStd")
            self.document.saveAs(filename)
            App.closeDocument(self.document.Name)
            self.document = App.openDocument(filename)
            covering = self.document.getObject(covering_name)
            union = self.document.getObject(union_name)
            # Check saved status/shape before explicitly touching or recomputing.
            self.assert_model(covering, union)
            self.assert_fixture_quantities(covering)
            self.assertEqual(before, (covering.Shape.Volume, union.Shape.Volume))
            covering.touch()
            self.document.recompute()
            self.assert_model(covering, union)
            self.assert_fixture_quantities(covering)
            self.assertEqual(before, (covering.Shape.Volume, union.Shape.Volume))

    def test_original_preference_and_disabled_control(self):
        covering, union = self.make_model()
        self.arch_params.SetInt("MaxComputeAreas", 0)
        self.document.recompute()
        self.assert_model(covering, union)
        before = covering.Shape.copy()
        volume = union.Shape.Volume
        self.arch_params.SetInt("MaxComputeAreas", 20)
        covering.touch()
        self.document.recompute()
        self.assert_model(covering, union)
        self.assertAlmostEqual(covering.Shape.Volume, before.Volume, places=7)
        self.assertLess(covering.Shape.cut(before).Volume, 1e-7)
        self.assertLess(before.cut(covering.Shape).Volume, 1e-7)
        self.assertAlmostEqual(union.Shape.Volume, volume, places=7)
        self.assert_fixture_quantities(covering)

    def test_native_optional_failure_and_recovery(self):
        covering, union = self.make_model()
        with patch.object(ArchComponent, "_project_planar_face_to_xy",
                          side_effect=ValueError("native FaceMaker failure probe")):
            with patch.object(App.Console, "PrintWarning") as warning:
                self.document.recompute()
        self.assert_model(covering, union)
        self.assert_zero_areas(covering)
        messages = " ".join(str(call.args) for call in warning.call_args_list)
        self.assertIn(covering.Label, messages)
        self.assertIn("FaceMaker", messages)
        before = (covering.Shape.Volume, union.Shape.Volume)
        name = covering.Name
        with TemporaryDirectory() as directory:
            filename = str(Path(directory) / "failed-quantities-valid-material.FCStd")
            self.document.saveAs(filename)
            App.closeDocument(self.document.Name)
            self.document = App.openDocument(filename)
            covering = self.document.getObject(name)
            union = self.document.getObject("Downstream")
            self.assert_model(covering, union)
            self.assert_zero_areas(covering)
            covering.touch()
            self.document.recompute()
            self.assert_model(covering, union)
            self.assert_fixture_quantities(covering)
            self.assertEqual(before, (covering.Shape.Volume, union.Shape.Volume))

    def test_preference_restoration_on_projection_failure(self):
        obj = SimpleNamespace(Label="Projection fixture", VerticalArea=10,
                              HorizontalArea=20, PerimeterLength=30)
        for value in (None, False, True):
            with self.subTest(preference=value):
                self.set_preference(value)
                with patch.object(ArchComponent, "_project_planar_face_to_xy",
                                  side_effect=ValueError("FaceMaker projection probe")):
                    ArchComponent.AreaCalculator(obj)._computeHorizontalAreaAndPerimeter(
                        [self.projection_face()])
                self.assert_preference(value)
                self.assertEqual((obj.VerticalArea, obj.HorizontalArea, obj.PerimeterLength),
                                 (0, 0, 0))

    def test_preference_restoration_on_early_return(self):
        obj = SimpleNamespace(Label="Nonplanar holes", VerticalArea=10,
                              HorizontalArea=20, PerimeterLength=30)
        face = SimpleNamespace(findPlane=lambda: None, Wires=[None, None])
        for value in (None, False, True):
            with self.subTest(preference=value):
                self.set_preference(value)
                ArchComponent.AreaCalculator(obj)._computeHorizontalAreaAndPerimeter([face])
                self.assert_preference(value)
                self.assertEqual(obj.HorizontalArea, 0)

    def test_known_errors_reset_but_unexpected_errors_propagate(self):
        obj = SimpleNamespace(Label="Projection errors", VerticalArea=10,
                              HorizontalArea=20, PerimeterLength=30)
        for error in (Part.OCCError, ValueError, TypeError):
            for value in (None, False, True):
                with self.subTest(error=error, preference=value):
                    self.set_preference(value)
                    calculator = ArchComponent.AreaCalculator(obj)
                    with patch.object(ArchComponent, "_project_planar_face_to_xy",
                                      side_effect=error("probe")):
                        if error is TypeError:
                            with self.assertRaises(TypeError):
                                calculator._computeHorizontalAreaAndPerimeter(
                                    [self.projection_face()])
                        else:
                            calculator._computeHorizontalAreaAndPerimeter([self.projection_face()])
                            self.assertEqual(obj.HorizontalArea, 0)
                    self.assert_preference(value)

    def test_valid_quantities_and_preference_restoration(self):
        box = self.document.addObject("Part::Box", "Box")
        box.Length, box.Width, box.Height = 10, 20, 30
        obj = Arch.makeStructure(box)
        for value in (None, False, True):
            with self.subTest(preference=value):
                self.set_preference(value)
                obj.touch()
                self.document.recompute()
                self.assertAlmostEqual(obj.VerticalArea.Value, 1800)
                self.assertAlmostEqual(obj.HorizontalArea.Value, 200)
                self.assertAlmostEqual(obj.PerimeterLength.Value, 60)
                self.assert_preference(value)

    def test_combine_failure_resets_quantities(self):
        obj = SimpleNamespace(Label="Combine errors", VerticalArea=10,
                              HorizontalArea=20, PerimeterLength=30)
        face = Part.makePlane(10, 20)
        for error in (Part.OCCError, ValueError):
            with self.subTest(error=error):
                with patch.object(ArchComponent, "_make_projected_horizontal_area_face",
                                  side_effect=error("combine probe")):
                    ArchComponent.AreaCalculator(obj)._computeHorizontalAreaAndPerimeter([face])
                self.assertEqual((obj.VerticalArea, obj.HorizontalArea, obj.PerimeterLength),
                                 (0, 0, 0))

    def test_invalid_material_shape_is_not_accepted(self):
        box = self.document.addObject("Part::Box", "ValidBox")
        component = Arch.makeComponent(box)
        self.document.recompute()
        original = component.Shape.copy()
        invalid = Part.makeSolid(Part.makeShell([Part.makePlane(10, 10)]))
        self.assertFalse(invalid.isValid())
        with patch.object(App.Console, "PrintWarning") as warning:
            component.Proxy.applyShape(component, invalid, App.Placement())
        self.assertTrue(warning.called)
        self.assertTrue(component.Shape.isValid())
        self.assertAlmostEqual(component.Shape.Volume, original.Volume)
