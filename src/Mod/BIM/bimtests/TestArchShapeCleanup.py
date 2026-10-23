# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the FreeCAD project.

"""Native Structure cleanup regressions and compatibility controls."""

import math
import os
import tempfile

import FreeCAD as App
import Arch
import Part
from bimtests import TestArchBase


class TestArchShapeCleanup(TestArchBase.TestArchBase):
    """Check material at the public Part-to-Structure boundary."""

    def _assert_solid_health(self, shape, count=1):
        self.assertFalse(shape.isNull())
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Solids), count)
        for solid in shape.Solids:
            self.assertTrue(solid.isClosed())
            self.assertGreater(solid.Volume, 0)
            self.assertTrue(math.isfinite(solid.Volume))

    def _assert_same_material(self, expected, actual, count=1):
        self._assert_solid_health(expected, count)
        self._assert_solid_health(actual, count)
        for left, right in ((expected, actual), (actual, expected)):
            difference = left.cut(right)
            if not difference.isNull():
                self.assertTrue(
                    difference.isValid(),
                    "An invalid material difference is inconclusive",
                )
            self.assertEqual(len(difference.Vertexes), 0, "Structure changed Base material")

    def _wrap(self, shape, placement=None):
        base = self.document.addObject("Part::Feature", "Base")
        base.Shape = shape
        if placement is not None:
            base.Placement = placement
        self.document.recompute()
        structure = Arch.makeStructure(baseobj=base)
        material = Arch.makeMaterial(name="CleanupControlMaterial")
        structure.Material = material
        structure.touch()
        self.assertTrue(structure.recompute())
        self.assertEqual(structure.Base, base)
        self.assertEqual(list(structure.Additions), [])
        self.assertEqual(list(structure.Subtractions), [])
        self.assertEqual(structure.Material, material)
        return base, structure

    def _bored_box(self):
        box = Part.makeBox(10, 20, 30)
        bore = Part.makeCylinder(2, 30, App.Vector(5, 10, 0))
        return box.cut(bore)

    def _notched_channels(self):
        """Two crossing caps with independently notched downward returns."""
        long_cap = Part.makeBox(20, 720, 2, App.Vector(0, -480, 5))
        cross_cap = Part.makeBox(440, 20, 2, App.Vector(-430, 0, 5))
        long_return = Part.makeBox(2, 720, 5, App.Vector(0, -480, 0))
        cross_return = Part.makeBox(440, 2, 5, App.Vector(-430, 18, 0))
        long_slot = Part.makeBox(22, 20, 7, App.Vector(-1, 0, -2))
        cross_slot = Part.makeBox(11, 22, 7, App.Vector(0, -1, -2))
        return long_cap.multiFuse(
            [cross_cap, long_return.cut(long_slot), cross_return.cut(cross_slot)]
        )

    def test_notched_channels_keep_valid_material(self):
        """An unhealthy automatic cleanup must not replace a valid Base."""
        shape = self._notched_channels()
        self._assert_solid_health(shape)
        # Cap union: 46,000; notched returns: 7,000 + 4,300 mm³.
        self.assertAlmostEqual(shape.Volume, 57300, delta=1e-7)
        base, structure = self._wrap(shape)
        self._assert_same_material(base.Shape, structure.Shape)
        self.assertAlmostEqual(structure.Shape.Volume, 57300, delta=1e-7)

    def test_box_material_is_preserved(self):
        base, structure = self._wrap(Part.makeBox(10, 20, 30))
        self._assert_same_material(base.Shape, structure.Shape)
        self.assertAlmostEqual(structure.Shape.Volume, 6000, delta=1e-7)
        self.assertTrue(structure.Shape.isInside(App.Vector(5, 10, 15), 1e-7, False))
        self.assertFalse(structure.Shape.isInside(App.Vector(-1, 10, 15), 1e-7, False))

    def test_bore_material_and_void_are_preserved(self):
        base, structure = self._wrap(self._bored_box())
        self._assert_same_material(base.Shape, structure.Shape)
        self.assertAlmostEqual(structure.Shape.Volume, 6000 - 120 * math.pi, delta=1e-7)
        self.assertFalse(structure.Shape.isInside(App.Vector(5, 10, 15), 1e-7, False))
        self.assertTrue(structure.Shape.isInside(App.Vector(1, 1, 15), 1e-7, False))

    def test_successful_cleanup_still_removes_splitters(self):
        left = Part.makeBox(10, 20, 30)
        right = Part.makeBox(10, 20, 30, App.Vector(10, 0, 0))
        base, structure = self._wrap(left.fuse(right))
        self.assertGreater(len(base.Shape.Faces), 6)
        self._assert_same_material(base.Shape, structure.Shape)
        self.assertAlmostEqual(structure.Shape.Volume, 12000, delta=1e-7)
        self.assertEqual(len(structure.Shape.Faces), 6)

    def test_compound_preserves_both_disconnected_solids(self):
        first = Part.makeBox(10, 20, 30)
        second = Part.makeBox(5, 5, 5, App.Vector(20, 0, 0))
        base, structure = self._wrap(Part.makeCompound([first, second]))
        self._assert_same_material(base.Shape, structure.Shape, count=2)
        self.assertAlmostEqual(structure.Shape.Volume, 6125, delta=1e-7)
        self.assertTrue(structure.Shape.isInside(App.Vector(22, 2, 2), 1e-7, False))
        self.assertFalse(structure.Shape.isInside(App.Vector(15, 10, 15), 1e-7, False))

    def test_placed_bore_keeps_material_in_the_global_frame(self):
        placement = App.Placement(App.Vector(100, -20, 7), App.Rotation(App.Vector(0, 0, 1), 90))
        base, structure = self._wrap(self._bored_box(), placement)
        self._assert_same_material(base.Shape, structure.Shape)
        self.assertAlmostEqual(structure.Shape.Volume, 6000 - 120 * math.pi, delta=1e-7)
        bounds = structure.Shape.BoundBox
        actual = (
            bounds.XMin,
            bounds.YMin,
            bounds.ZMin,
            bounds.XMax,
            bounds.YMax,
            bounds.ZMax,
        )
        for observed, expected in zip(actual, (80, -20, 7, 100, -10, 37)):
            self.assertAlmostEqual(observed, expected, delta=1e-7)
        self.assertFalse(structure.Shape.isInside(App.Vector(90, -15, 22), 1e-7, False))
        self.assertTrue(structure.Shape.isInside(App.Vector(99, -19, 22), 1e-7, False))

    def test_saved_bases_preserve_base_and_material_links(self):
        for make_shape, volume in (
            (self._bored_box, 6000 - 120 * math.pi),
            (self._notched_channels, 57300),
        ):
            with self.subTest(fixture=make_shape.__name__):
                base, structure = self._wrap(make_shape())
                self._assert_same_material(base.Shape, structure.Shape)
                base_name = base.Name
                structure_name = structure.Name
                material_name = structure.Material.Name
                with tempfile.TemporaryDirectory() as directory:
                    path = os.path.join(directory, "structure_cleanup.FCStd")
                    self.document.saveAs(path)
                    App.closeDocument(self.document.Name)
                    self.document = App.openDocument(path)
                    base = self.document.getObject(base_name)
                    structure = self.document.getObject(structure_name)
                    structure.touch()
                    self.assertTrue(structure.recompute())
                    self.assertEqual(structure.Base, base)
                    self.assertEqual(structure.Material.Name, material_name)
                    self._assert_same_material(base.Shape, structure.Shape)
                    self.assertAlmostEqual(structure.Shape.Volume, volume, delta=1e-7)
