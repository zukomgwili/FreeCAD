# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2025 Furgo
# SPDX-FileNotice: Part of the FreeCAD project.

################################################################################
#                                                                              #
#   FreeCAD is free software: you can redistribute it and/or modify            #
#   it under the terms of the GNU Lesser General Public License as             #
#   published by the Free Software Foundation, either version 2.1              #
#   of the License, or (at your option) any later version.                     #
#                                                                              #
#   FreeCAD is distributed in the hope that it will be useful,                 #
#   but WITHOUT ANY WARRANTY; without even the implied warranty                #
#   of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.                    #
#   See the GNU Lesser General Public License for more details.                #
#                                                                              #
#   You should have received a copy of the GNU Lesser General Public           #
#   License along with FreeCAD. If not, see https://www.gnu.org/licenses       #
#                                                                              #
################################################################################

import itertools
import math
import os
import tempfile
import unittest

import FreeCAD
import Arch
import Draft
import Part
from bimtests import TestArchBase

try:
    import ifcopenshell
    import ifcopenshell.geom
    import ifcopenshell.util.placement
    import ifcopenshell.util.unit
    from importers import exportIFC
except ImportError:
    _HAS_IFCOPENSHELL = False
else:
    _HAS_IFCOPENSHELL = True


class TestArchRebar(TestArchBase.TestArchBase):

    def _create_sketch(self, add_line=True, length=500.0):
        """Helper function to create a basic sketch."""
        sketch = self.document.addObject("Sketcher::SketchObject")
        if add_line:
            sketch.addGeometry(
                Part.LineSegment(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(length, 0, 0)), False
            )
        self.document.recompute()
        return sketch

    def _create_host_structure(self, length=1000.0, width=200.0, height=300.0):
        """Helper function to create a basic host structure."""
        host = Arch.makeStructure(length=length, width=width, height=height)
        self.document.recompute()
        return host

    def _create_placement_rebar(self):
        host = self._create_host_structure(length=200, width=300, height=100)
        base = Draft.make_wire([FreeCAD.Vector(20, 40, 50), FreeCAD.Vector(180, 40, 50)])
        rebar = Arch.makeRebar(baseobj=host, sketch=base, diameter=12, amount=1, offset=0)
        rebar.Direction = FreeCAD.Vector(0, 1, 0)
        self.document.recompute()
        return rebar, host

    def _assert_straight_rebar_data(self, rebar, offsets, axis=FreeCAD.Vector(0, 1, 0)):
        """Compare exported local centrelines with analytic positions and actual solids."""
        original_base = rebar.Base.Shape.exportBrepToString()
        original_solid = rebar.Shape.exportBrepToString()
        original_placements = list(rebar.PlacementList)
        wires, radius = rebar.Proxy.getRebarData(rebar)
        solids = rebar.Shape.Solids
        self.assertEqual(len(wires), len(offsets))
        self.assertEqual(len(solids), len(offsets))
        self.assertAlmostEqual(radius, 6)
        for wire, solid, offset in zip(wires, solids, offsets):
            expected = [
                rebar.Placement.multVec(point + axis * offset)
                for point in (FreeCAD.Vector(20, 40, 50), FreeCAD.Vector(180, 40, 50))
            ]
            world_wire = wire.copy()
            world_wire.Placement = rebar.Placement.multiply(wire.Placement)
            self.assertEqual(len(world_wire.Vertexes), 2)
            for vertex, point in zip(world_wire.Vertexes, expected):
                self.assertLess((vertex.Point - point).Length, 1e-7)
            midpoint = (expected[0] + expected[1]) * 0.5
            self.assertLess((world_wire.CenterOfMass - midpoint).Length, 1e-7)
            self.assertLess((solid.CenterOfMass - midpoint).Length, 1e-7)
            self.assertAlmostEqual(wire.Length, 160)
            self.assertAlmostEqual(solid.Volume, math.pi * radius**2 * 160, delta=1e-6)
        self.assertEqual(rebar.Base.Shape.exportBrepToString(), original_base)
        self.assertEqual(rebar.Shape.exportBrepToString(), original_solid)
        self.assertEqual(rebar.PlacementList, original_placements)
        return wires

    def test_getRebarData_single_bar_placement(self):
        """Single bars use OffsetStart, not half a host or explicit distribution span."""
        rebar, host = self._create_placement_rebar()
        directions = (
            (FreeCAD.Vector(0, 2, 0), FreeCAD.Vector(0, 1, 0)),
            (FreeCAD.Vector(0, -3, 0), FreeCAD.Vector(0, -1, 0)),
            (FreeCAD.Vector(), FreeCAD.Vector(0, 0, -1)),
        )
        for hosted, (direction, axis), (distance, start) in itertools.product(
            (False, True), directions, ((0, 0), (100, 0), (100, 5), (2, 1))
        ):
            with self.subTest(hosted=hosted, direction=direction, distance=distance, start=start):
                rebar.Host = host if hosted else None
                rebar.Direction = direction
                rebar.Distance = distance
                rebar.OffsetStart = start
                rebar.OffsetEnd = 7
                self.document.recompute()
                self._assert_straight_rebar_data(rebar, [start], axis)

    def test_getRebarData_multiple_bar_placement(self):
        """Hosted and standalone distribution agrees with generated solid geometry."""
        rebar, host = self._create_placement_rebar()
        rebar.Amount = 3
        for hosted, distance in itertools.product((False, True), (0, 100)):
            with self.subTest(hosted=hosted, distance=distance):
                rebar.Host = host if hosted else None
                rebar.Distance = distance
                rebar.OffsetStart = 5
                rebar.OffsetEnd = 7
                self.document.recompute()
                size = distance or (300 if hosted else 1)
                self._assert_straight_rebar_data(rebar, [5, (size - 2) / 2, size - 7])

    def test_getRebarData_custom_spacing(self):
        """Nonuniform placement is shared by centrelines and solids."""
        rebar, host = self._create_placement_rebar()
        rebar.OffsetStart = 5
        rebar.OffsetEnd = 7
        rebar.Distance = 72
        rebar.CustomSpacing = "10+30+50"
        self.document.recompute()
        self.assertEqual(rebar.Amount, 3)
        self._assert_straight_rebar_data(rebar, [5, 25, 65])

        # Stored custom placements carry the host rotation as well as the offset.
        host.Placement = FreeCAD.Placement(
            FreeCAD.Vector(10, -20, 30), FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 23)
        )
        rebar.Base.Placement = FreeCAD.Placement(
            FreeCAD.Vector(20, -30, 70), FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 31)
        )
        self.document.recompute()
        original_base = rebar.Base.Shape.exportBrepToString()
        original_solid = rebar.Shape.exportBrepToString()
        wires, radius = rebar.Proxy.getRebarData(rebar)
        self.assertEqual(len(wires), 3)
        self.assertEqual(len(rebar.Proxy.wires), 3)
        self.assertEqual(len(rebar.Shape.Solids), 3)
        self.assertAlmostEqual(radius, 6)
        for wire, cached, solid, offset in zip(
            wires, rebar.Proxy.wires, rebar.Shape.Solids, (5, 25, 65)
        ):
            expected = [
                host.Placement.Rotation.multVec(vertex.Point) + FreeCAD.Vector(0, offset, 0)
                for vertex in rebar.Base.Shape.Vertexes
            ]
            self.assertEqual(len(wire.Vertexes), 2)
            for vertex, point in zip(wire.Vertexes, expected):
                self.assertLess((vertex.Point - point).Length, 1e-7)
            midpoint = (expected[0] + expected[1]) * 0.5
            self.assertLess((solid.CenterOfMass - rebar.Placement.multVec(midpoint)).Length, 1e-7)
            self.assertLess((cached.CenterOfMass - midpoint).Length, 1e-7)
        self.assertEqual(rebar.Base.Shape.exportBrepToString(), original_base)
        self.assertEqual(rebar.Shape.exportBrepToString(), original_solid)

    def test_getRebarData_local_coordinates_and_copies(self):
        """Returned wires stay local and callers may transform them without changing the model."""
        rebar, host = self._create_placement_rebar()
        rebar.OffsetStart = 5
        rebar.Placement = FreeCAD.Placement(
            FreeCAD.Vector(70, -20, 30), FreeCAD.Rotation(FreeCAD.Vector(1, 1, 1), 37)
        )
        self.document.recompute()
        wires = self._assert_straight_rebar_data(rebar, [5])
        wires[0].translate(FreeCAD.Vector(1000, 2000, 3000))
        wires[0].scale(0.001)
        self._assert_straight_rebar_data(rebar, [5])

    def test_getRebarData_single_edge_base(self):
        """The single-edge base supported by solid generation also exports as a wire."""
        base = self.document.addObject("Part::Feature", "EdgeBase")
        base.Shape = Part.makeLine(FreeCAD.Vector(20, 40, 50), FreeCAD.Vector(180, 40, 50))
        base.addProperty("App::PropertyLength", "Length")
        base.Length = 160
        rebar = Arch.makeRebar(sketch=base, diameter=12, amount=1, offset=0)
        rebar.Direction = FreeCAD.Vector(0, 1, 0)
        rebar.OffsetStart = 5
        self.document.recompute()
        self._assert_straight_rebar_data(rebar, [5])

        # Unsupported disconnected edges must not index an absent Wires list.
        base.Shape = Part.makeCompound(
            [
                Part.makeLine(FreeCAD.Vector(), FreeCAD.Vector(10, 0, 0)),
                Part.makeLine(FreeCAD.Vector(0, 5, 0), FreeCAD.Vector(10, 5, 0)),
            ]
        )
        self.assertIsNone(rebar.Proxy.getRebarData(rebar))

    def test_getRebarData_rounded_base(self):
        """Rounded centreline sweeps occupy the same geometry as the generated bars."""
        base = Draft.make_wire(
            [FreeCAD.Vector(20, 40, 50), FreeCAD.Vector(180, 40, 50), FreeCAD.Vector(180, 100, 50)]
        )
        rebar = Arch.makeRebar(sketch=base, diameter=12, amount=2, offset=0)
        rebar.Direction = FreeCAD.Vector(0, 1, 0)
        rebar.Distance = 100
        rebar.OffsetStart = 5
        rebar.OffsetEnd = 7
        rebar.Rounding = 2
        self.document.recompute()
        original_base = base.Shape.exportBrepToString()
        original_solid = rebar.Shape.exportBrepToString()
        wires, radius = rebar.Proxy.getRebarData(rebar)
        self.assertEqual(len(wires), 2)
        for wire, solid, offset in zip(wires, rebar.Shape.Solids, (5, 93)):
            self.assertAlmostEqual(wire.Length, 220 - 48 + math.pi * 24 / 2)
            for point in (
                FreeCAD.Vector(20, 40 + offset, 50),
                FreeCAD.Vector(180, 100 + offset, 50),
            ):
                self.assertLess(wire.distToShape(Part.Vertex(point))[0], 1e-7)
            edge = wire.Edges[0]
            profile = Part.Wire(
                Part.makeCircle(radius, edge.Vertexes[0].Point, edge.tangentAt(edge.FirstParameter))
            )
            swept = wire.makePipeShell([profile], True, False, 2)
            self.assertLess(solid.cut(swept).Volume, 1e-6)
            self.assertLess(swept.cut(solid).Volume, 1e-6)
        self.assertEqual(base.Shape.exportBrepToString(), original_base)
        self.assertEqual(rebar.Shape.exportBrepToString(), original_solid)

    def test_getRebarData_rotated_sketch_base(self):
        """Exported and native display centrelines retain the transformed sketch path."""
        base = self._create_sketch(length=160)
        base.Placement = FreeCAD.Placement(
            FreeCAD.Vector(20, 40, 50), FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 31)
        )
        rebar = Arch.makeRebar(sketch=base, diameter=12, amount=1, offset=5)
        rebar.Direction = FreeCAD.Vector(0, 1, 0)
        self.document.recompute()
        original_base = base.Shape.exportBrepToString()
        original_solid = rebar.Shape.exportBrepToString()
        wires, radius = rebar.Proxy.getRebarData(rebar)
        self.assertEqual(len(wires), 1)
        expected = base.Placement.multVec(FreeCAD.Vector(80, 0, 0)) + FreeCAD.Vector(0, 5, 0)
        self.assertLess((rebar.Shape.Solids[0].CenterOfMass - expected).Length, 1e-7)
        # The native Centerline display mode consumes this cache.
        self.assertLess((rebar.Proxy.wires[0].CenterOfMass - expected).Length, 1e-7)
        self.assertLess((wires[0].CenterOfMass - expected).Length, 1e-7)
        self.assertAlmostEqual(wires[0].Length, 160)
        self.assertAlmostEqual(rebar.Shape.Volume, math.pi * radius**2 * 160, delta=1e-6)
        self.assertEqual(base.Shape.exportBrepToString(), original_base)
        self.assertEqual(rebar.Shape.exportBrepToString(), original_solid)

    def test_getRebarData_after_save_reopen(self):
        """Persisted placements work before and after recompute, without a transient wire cache."""
        rebar, host = self._create_placement_rebar()
        rebar.OffsetStart = 5
        rebar.Distance = 100
        self.document.recompute()
        name = rebar.Name
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "rebar-placement.FCStd")
            self.document.saveAs(path)
            FreeCAD.closeDocument(self.document.Name)
            self.document = FreeCAD.openDocument(path)
            rebar = self.document.getObject(name)
            self._assert_straight_rebar_data(rebar, [5])
            self.document.recompute()
            self._assert_straight_rebar_data(rebar, [5])

    def _assert_written_ifc_rebar(self, rebar, unit="metre"):
        """Reopen an actual IFC and compare its directrices and world mesh to native solids."""
        original_base = rebar.Base.Shape.exportBrepToString()
        original_solid = rebar.Shape.exportBrepToString()
        original_placements = list(rebar.PlacementList)
        original_wires = [wire.exportBrepToString() for wire in rebar.Proxy.wires]
        native = rebar.Shape.copy()
        native.Placement = rebar.getGlobalPlacement()
        preferences = exportIFC.getPreferences()
        preferences.update(
            SCHEMA="IFC4",
            IFC_UNIT=unit,
            SCALE_FACTOR=0.001 if unit == "metre" else 0.00328084,
            FORCE_BREP=False,
            CREATE_CLONES=False,
            FULL_PARAMETRIC=False,
            STORE_UID=False,
            SERIALIZE=False,
            EXPORT_MODEL="arch",
            DEBUG=False,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "rebar.ifc")
            exportIFC.export([rebar], path, preferences=preferences)
            model = ifcopenshell.open(path)

        entities = model.by_type("IfcReinforcingBar")
        self.assertEqual(len(entities), 1)
        entity = entities[0]
        items = [
            item
            for representation in entity.Representation.Representations
            if representation.RepresentationIdentifier == "Body"
            for item in representation.Items
        ]
        self.assertEqual(len(items), len(native.Solids))
        unit_scale = ifcopenshell.util.unit.calculate_unit_scale(model)
        self.assertAlmostEqual(unit_scale, 1 if unit == "metre" else 0.3048)
        placement = ifcopenshell.util.placement.get_local_placement(entity.ObjectPlacement)
        # This exporter branch stores world curves with an identity product placement.
        for i in range(4):
            for j in range(4):
                self.assertAlmostEqual(placement[i][j], 1 if i == j else 0)
        for item, solid in zip(items, native.Solids):
            self.assertTrue(item.is_a("IfcSweptDiskSolid"))
            self.assertAlmostEqual(
                item.Radius * unit_scale * 1000, rebar.Diameter.Value / 2, delta=1e-6
            )
            self.assertAlmostEqual(
                item.Radius,
                rebar.Diameter.Value / 2 * preferences["SCALE_FACTOR"],
                delta=1e-12,
            )
            self.assertTrue(item.Directrix.is_a("IfcIndexedPolyCurve"))
            coordinates = item.Directrix.Points.CoordList
            self.assertEqual(len(coordinates), 2)
            points = [
                FreeCAD.Vector(
                    *[
                        (sum(placement[i][j] * point[j] for j in range(3)) + placement[i][3])
                        / preferences["SCALE_FACTOR"]
                        for i in range(3)
                    ]
                )
                for point in coordinates
            ]
            # Planar end-cap centroids give an independent native centreline oracle.
            expected = [
                face.CenterOfMass for face in solid.Faces if isinstance(face.Surface, Part.Plane)
            ]
            self.assertEqual(len(expected), 2)
            error = min(
                max((a - b).Length for a, b in zip(points, order))
                for order in (expected, list(reversed(expected)))
            )
            self.assertLess(error, 1e-4)
            self.assertAlmostEqual((points[1] - points[0]).Length, 160, delta=1e-4)

        settings = ifcopenshell.geom.settings()
        settings.set("use-world-coords", True)
        shape = ifcopenshell.geom.create_shape(settings, entity)
        vertices = list(shape.geometry.verts)
        axes = [vertices[i::3] for i in range(3)]
        centre = FreeCAD.Vector(*[(min(axis) + max(axis)) * 500 for axis in axes])
        self.assertLess((centre - native.BoundBox.Center).Length, 1e-4)
        self.assertEqual(rebar.Base.Shape.exportBrepToString(), original_base)
        self.assertEqual(rebar.Shape.exportBrepToString(), original_solid)
        self.assertEqual(rebar.PlacementList, original_placements)
        self.assertEqual([wire.exportBrepToString() for wire in rebar.Proxy.wires], original_wires)

    @unittest.skipUnless(_HAS_IFCOPENSHELL, "ifcopenshell not available")
    def test_ifc_export_single_bar_placements(self):
        """Identity, translated and rotated owners preserve physical endpoints and units."""
        rebar, host = self._create_placement_rebar()
        rebar.Distance = 2
        rebar.OffsetStart = 1
        placements = (
            FreeCAD.Placement(),
            FreeCAD.Placement(FreeCAD.Vector(70, -20, 30), FreeCAD.Rotation()),
            FreeCAD.Placement(FreeCAD.Vector(), FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 90)),
            FreeCAD.Placement(
                FreeCAD.Vector(70, -20, 30), FreeCAD.Rotation(FreeCAD.Vector(1, 1, 1), 37)
            ),
        )
        for hosted, placement, unit in itertools.product(
            (False, True), placements, ("metre", "foot")
        ):
            with self.subTest(hosted=hosted, placement=placement, unit=unit):
                rebar.Host = host if hosted else None
                rebar.Placement = placement
                self.document.recompute()
                self._assert_written_ifc_rebar(rebar, unit)

    @unittest.skipUnless(_HAS_IFCOPENSHELL, "ifcopenshell not available")
    def test_ifc_export_multiple_and_custom_spacing(self):
        """Uniform and nonuniform bars retain every placement under noncommuting rotations."""
        rebar, host = self._create_placement_rebar()
        rebar.Amount = 3
        rebar.OffsetStart = 5
        rebar.OffsetEnd = 7
        for custom in (False, True):
            with self.subTest(custom=custom):
                if custom:
                    rebar.Distance = 72
                    rebar.CustomSpacing = "10+30+50"
                    host.Placement.Rotation = FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 23)
                    rebar.Base.Placement = FreeCAD.Placement(
                        FreeCAD.Vector(20, -30, 70), FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 31)
                    )
                else:
                    rebar.Distance = 100
                rebar.Placement = FreeCAD.Placement(
                    FreeCAD.Vector(70, -20, 30), FreeCAD.Rotation(FreeCAD.Vector(1, 1, 1), 37)
                )
                self.document.recompute()
                self._assert_written_ifc_rebar(rebar)

    @unittest.skipUnless(_HAS_IFCOPENSHELL, "ifcopenshell not available")
    def test_ifc_export_nested_parent_global_placement(self):
        """Nested App::Part placements are applied once, in the same order as native geometry."""
        rebar, host = self._create_placement_rebar()
        rebar.Amount = 2
        rebar.Distance = 100
        rebar.OffsetStart = 3
        rebar.OffsetEnd = 4
        parent = self.document.addObject("App::Part", "Parent")
        child = self.document.addObject("App::Part", "Child")
        parent.addObject(child)
        child.addObject(rebar)
        parent.Placement = FreeCAD.Placement(
            FreeCAD.Vector(300, -100, 150), FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 23)
        )
        child.Placement = FreeCAD.Placement(
            FreeCAD.Vector(100, 200, 50), FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), 41)
        )
        rebar.Placement = FreeCAD.Placement(
            FreeCAD.Vector(70, -20, 30), FreeCAD.Rotation(FreeCAD.Vector(1, 1, 1), 37)
        )
        self.document.recompute()
        self._assert_written_ifc_rebar(rebar)

    def test_makeRebar_default_name(self):
        """Test makeRebar creates rebar with default 'Rebar' Label.

        See https://github.com/FreeCAD/FreeCAD/issues/21670
        """
        sketch = self._create_sketch()
        rebar = Arch.makeRebar(sketch=sketch, diameter=6)
        self.document.recompute()

        self.assertIsNotNone(rebar, "makeRebar failed to create a rebar object.")
        self.assertEqual(rebar.Label, "Rebar", "Rebar default label should be 'Rebar'.")
        self.assertTrue(
            rebar.Name.startswith("Rebar"), "Rebar internal name should start with 'Rebar'."
        )

    def test_makeRebar_custom_name(self):
        """Test makeRebar with a custom name sets Label and Mark correctly."""
        sketch = self._create_sketch()
        custom_name = "MyCustomRebar"
        rebar = Arch.makeRebar(sketch=sketch, diameter=16, amount=5, name=custom_name)
        self.document.recompute()

        self.assertIsNotNone(rebar, "makeRebar failed to create a rebar object.")
        self.assertEqual(rebar.Label, custom_name, "Rebar label is incorrect.")
        self.assertEqual(rebar.Mark, custom_name, "Rebar mark should match label by default.")

    def test_makeRebar_with_sketch_and_host(self):
        """Test makeRebar with both sketch and host object links them correctly."""
        sketch_len = 800.0
        host_len = 1000.0
        sketch = self._create_sketch(length=sketch_len)
        host = self._create_host_structure(length=host_len)

        rebar = Arch.makeRebar(baseobj=host, sketch=sketch, diameter=10, amount=3, offset=20)
        self.document.recompute()

        self.assertIsNotNone(rebar, "makeRebar failed.")
        self.assertEqual(rebar.Host, host, "Rebar.Host is not set correctly.")
        self.assertEqual(rebar.Base, sketch, "Rebar.Base (sketch) is not set correctly.")
        self.assertAlmostEqual(rebar.Diameter.Value, 10.0, delta=1e-9)
        self.assertEqual(rebar.Amount, 3)
        self.assertAlmostEqual(rebar.OffsetStart.Value, 20.0, delta=1e-9)

        self.assertTrue(hasattr(rebar, "Shape"), "Rebar should have a Shape attribute.")
        self.assertIsNotNone(rebar.Shape, "Rebar.Shape should not be None after recompute.")
        self.assertTrue(rebar.Shape.isValid(), "Rebar.Shape should be valid.")
        self.assertGreater(rebar.Shape.Length, 0, "Rebar shape seems to have no length.")
        self.assertGreater(
            rebar.TotalLength.Value, 0, "Rebar total length should be greater than 0."
        )

    def test_makeRebar_with_sketch_only(self):
        """Test makeRebar with only sketch results in no host and valid geometry."""
        sketch = self._create_sketch()
        rebar = Arch.makeRebar(sketch=sketch, diameter=8)
        self.document.recompute()

        self.assertIsNotNone(rebar, "makeRebar failed.")
        self.assertIsNone(rebar.Host, "Rebar.Host should be None.")
        self.assertEqual(rebar.Base, sketch, "Rebar.Base (sketch) is not set correctly.")
        self.assertAlmostEqual(rebar.Diameter.Value, 8.0, delta=1e-9)
        self.assertIsNotNone(rebar.Shape)
        self.assertTrue(rebar.Shape.isValid())
        self.assertGreater(rebar.Shape.Length, 0)

    def test_makeRebar_with_baseobj_only_shape_conversion(self):
        """Test makeRebar with baseobj only copies shape."""
        host_shape_provider = self._create_host_structure()
        rebar = Arch.makeRebar(baseobj=host_shape_provider)
        self.document.recompute()

        self.assertIsNotNone(rebar, "makeRebar failed.")
        self.assertIsNone(rebar.Host, "Rebar.Host should be None in this mode.")
        self.assertIsNone(rebar.Base, "Rebar.Base should be None in this mode.")
        self.assertIsNotNone(rebar.Shape, "Rebar.Shape should be set from baseobj.")
        self.assertTrue(rebar.Shape.isValid())
        self.assertGreater(rebar.Shape.Volume, 0, "Converted rebar shape should have volume.")

    def test_makeRebar_properties_set_correctly(self):
        """Test makeRebar sets dimensional and calculated properties correctly."""
        sketch = self._create_sketch(length=900)
        host = self._create_host_structure(length=1200)

        rebar = Arch.makeRebar(baseobj=host, sketch=sketch, diameter=12.5, amount=7, offset=30.0)
        # Default label "Rebar" will be used, and Mark will also be "Rebar"
        self.document.recompute()

        self.assertEqual(rebar.Mark, "Rebar")
        self.assertAlmostEqual(rebar.Diameter.Value, 12.5, delta=1e-9)
        self.assertEqual(rebar.Amount, 7)
        self.assertAlmostEqual(rebar.OffsetStart.Value, 30.0, delta=1e-9)
        self.assertAlmostEqual(rebar.OffsetEnd.Value, 30.0, delta=1e-9)
        self.assertEqual(rebar.Host, host)
        self.assertEqual(rebar.Base, sketch)

        self.assertTrue(hasattr(rebar, "Length"), "Rebar should have Length property.")
        self.assertTrue(hasattr(rebar, "TotalLength"), "Rebar should have TotalLength property.")
        self.assertAlmostEqual(
            rebar.Length.Value,
            sketch.Shape.Length,
            delta=1e-9,
            msg="Single rebar length should match sketch length.",
        )
        expected_total_length = rebar.Length.Value * rebar.Amount
        self.assertAlmostEqual(
            rebar.TotalLength.Value,
            expected_total_length,
            delta=1e-9,
            msg="TotalLength calculation is incorrect.",
        )

    def test_makeRebar_no_sketch_no_baseobj(self):
        """Test makeRebar with no sketch/baseobj creates object with no meaningful shape."""
        rebar = Arch.makeRebar(diameter=10, amount=1)
        self.document.recompute()

        self.assertIsNotNone(rebar, "makeRebar should create an object even with minimal inputs.")
        self.assertIsNone(rebar.Base, "Rebar.Base should be None.")
        self.assertIsNone(rebar.Host, "Rebar.Host should be None.")
        self.assertAlmostEqual(rebar.Diameter.Value, 10.0, delta=1e-9)
        self.assertEqual(rebar.Amount, 1)

        # A Part::FeaturePython object always has a .Shape attribute.
        # For a rebar with no Base, its execute() returns early, so no geometry is made.
        # The Shape should be the default null/empty shape.
        self.assertIsNotNone(rebar.Shape, "Rebar object should always have a Shape attribute.")
        self.assertTrue(
            rebar.Shape.isNull(), "Rebar.Shape should be a null shape if no Base is provided."
        )

    def test_RebarMe(self):
        """
        Tests the creation of an Arch Rebar
        """
        import Sketcher

        self.printTestMessage("Checking Arch Rebar...\n")
        s = Arch.makeStructure(length=2, width=3, height=5)
        sk = self.document.addObject("Sketcher::SketchObject", "Sketch")
        sk.AttachmentSupport = (s, ["Face6"])
        sk.addGeometry(
            Part.LineSegment(FreeCAD.Vector(-0.85, 1.25, 0), FreeCAD.Vector(0.75, 1.25, 0))
        )
        sk.addGeometry(
            Part.LineSegment(FreeCAD.Vector(0.75, 1.25, 0), FreeCAD.Vector(0.75, -1.20, 0))
        )
        sk.addGeometry(
            Part.LineSegment(FreeCAD.Vector(0.75, -1.20, 0), FreeCAD.Vector(-0.85, -1.20, 0))
        )
        sk.addGeometry(
            Part.LineSegment(FreeCAD.Vector(-0.85, -1.20, 0), FreeCAD.Vector(-0.85, 1.25, 0))
        )
        sk.addConstraint(Sketcher.Constraint("Coincident", 0, 2, 1, 1))
        sk.addConstraint(Sketcher.Constraint("Coincident", 1, 2, 2, 1))
        sk.addConstraint(Sketcher.Constraint("Coincident", 2, 2, 3, 1))
        sk.addConstraint(Sketcher.Constraint("Coincident", 3, 2, 0, 1))
        self.document.recompute()
        r = Arch.makeRebar(s, sk, diameter=0.1, amount=2)
        self.document.recompute()
        self.assertTrue(r, "Arch Rebar creation failed")
        self.assertFalse(r.Shape.isNull(), "Rebar shape is null")
