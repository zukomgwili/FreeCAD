# SPDX-License-Identifier: LGPL-2.1-or-later

import os
import tempfile
import unittest

import Arch
import FreeCAD
import Part


class TestArchSite(unittest.TestCase):
    def setUp(self):
        self.document = FreeCAD.newDocument("SiteSurfaceTest")
        self.terrain = self.document.addObject("Part::Feature", "Terrain")
        self.terrain.Shape = Part.makePlane(1000, 1000)
        self.site = Arch.makeSite()
        self.site.Terrain = self.terrain
        self.site.ExtrusionVector = FreeCAD.Vector(0, 0, -1000)

    def tearDown(self):
        FreeCAD.closeDocument(self.document.Name)

    def box(self, name, x, depth):
        box = self.document.addObject("Part::Box", name)
        box.Length, box.Width, box.Height = 300, 200, depth + 200
        box.Placement.Base = FreeCAD.Vector(x, 200, -depth)
        return box

    def area_at(self, shape, axis, coordinate):
        return sum(
            face.Area for face in shape.Faces
            if abs(getattr(face.BoundBox, axis + "Min") - coordinate) < 1e-6
            and abs(getattr(face.BoundBox, axis + "Max") - coordinate) < 1e-6
        )

    def assert_union_surface(self, x, depth):
        a, b = self.box("CutA", 200, 100), self.box("CutB", x, depth)
        self.site.Subtractions = [a, b]
        self.document.recompute()
        separate = self.site.Shape.copy()
        union = self.document.addObject("Part::MultiFuse", "CutUnion")
        union.Shapes, union.Refine = [a, b], True
        self.site.Subtractions = [union]
        self.document.recompute()
        expected = self.site.Shape.copy()
        self.assertTrue(separate.isValid())
        self.assertAlmostEqual(separate.Area, expected.Area, places=5)
        self.assertAlmostEqual(separate.cut(expected).Area, 0, places=5)
        self.assertAlmostEqual(expected.cut(separate).Area, 0, places=5)
        self.site.Subtractions = [b, a]
        self.document.recompute()
        self.assertAlmostEqual(self.site.Shape.cut(expected).Area, 0, places=5)
        self.assertAlmostEqual(expected.cut(self.site.Shape).Area, 0, places=5)
        return a, b, expected

    def test_overlapping_cuts(self):
        self.assert_union_surface(450, 200)
        self.assertAlmostEqual(self.area_at(self.site.Shape, "Z", -200), 60000)
        self.assertAlmostEqual(self.area_at(self.site.Shape, "Z", -100), 50000)
        self.assertAlmostEqual(self.area_at(self.site.Shape, "X", 500), 0)
        self.assertAlmostEqual(self.area_at(self.site.Shape, "X", 450), 20000)
        self.assertAlmostEqual(self.area_at(self.site.Shape, "X", 200), 20000)
        self.assertAlmostEqual(self.area_at(self.site.Shape, "X", 750), 40000)

    def test_adjoining_cuts(self):
        self.assert_union_surface(500, 100)
        self.assertAlmostEqual(self.area_at(self.site.Shape, "X", 500), 0)
        self.assertAlmostEqual(self.area_at(self.site.Shape, "Z", -100), 120000)

    def test_disjoint_cuts(self):
        self.assert_union_surface(600, 200)
        self.assertAlmostEqual(self.area_at(self.site.Shape, "X", 500), 20000)
        self.assertAlmostEqual(self.area_at(self.site.Shape, "X", 600), 40000)

    def test_single_cut_and_empty_subtractions(self):
        self.document.recompute()
        self.assertAlmostEqual(self.site.Shape.Area, 1000000, places=3)
        a = self.box("CutA", 200, 100)
        self.site.Subtractions = [a]
        self.document.recompute()
        self.assertAlmostEqual(self.area_at(self.site.Shape, "Z", -100), 60000)
        self.assertAlmostEqual(self.area_at(self.site.Shape, "Z", 0), 940000, places=3)

    def test_solid_terrain(self):
        self.terrain.Shape = Part.makeBox(1000, 1000, 1000, FreeCAD.Vector(0, 0, -1000))
        a, b = self.box("CutA", 200, 100), self.box("CutB", 450, 200)
        self.site.Subtractions = [a, b]
        self.document.recompute()
        self.assertTrue(self.site.Shape.isValid())
        self.assertAlmostEqual(self.site.Shape.Volume, 1000000000 - 17000000, delta=1)

    def test_edit_and_reopen(self):
        a, b, _ = self.assert_union_surface(450, 200)
        b.Height = 500
        b.Placement.Base.z = -300
        self.document.recompute()
        self.assertAlmostEqual(self.area_at(self.site.Shape, "Z", -300), 60000)
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "site.FCStd")
            self.document.saveAs(path)
            name = self.document.Name
            FreeCAD.closeDocument(name)
            self.document = FreeCAD.openDocument(path)
            self.document.getObject("Site").touch()
            self.document.recompute()
            site = self.document.getObject("Site")
            self.assertAlmostEqual(self.area_at(site.Shape, "Z", -300), 60000)
