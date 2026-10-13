# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *   Copyright (c) 2013 Yorik van Havre <yorik@uncreated.net>              *
# *   Copyright (c) 2019 Eliud Cabrera Castillo <e.cabrera-castillo@tum.de> *
# *   Copyright (c) 2025 FreeCAD Project Association                        *
# *                                                                         *
# *   This file is part of the FreeCAD CAx development system.              *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful,            *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
# *   GNU Library General Public License for more details.                  *
# *                                                                         *
# *   You should have received a copy of the GNU Library General Public     *
# *   License along with FreeCAD; if not, write to the Free Software        *
# *   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
# *   USA                                                                   *
# *                                                                         *
# ***************************************************************************
"""Unit tests for the Draft Workbench, SVG import and export tests."""

## @package test_svg
# \ingroup drafttests
# \brief Unit tests for the Draft Workbench, SVG import and export tests.

## \addtogroup drafttests
# @{

import itertools
import math
import os
import re
import tempfile
import unittest
from unittest import mock

import FreeCAD as App
import Draft
import Part
import WorkingPlane
import draftfunctions.svgshapes as svgshapes
import importSVG
from drafttests import auxiliary as aux
from drafttests import test_base
from draftutils.messages import _msg

try:
    import Arch
except ModuleNotFoundError:
    have_arch = False
else:
    have_arch = True


class DraftSVG(test_base.DraftTestCaseDoc):
    """Test reading and writing of SVGs with Draft."""

    def test_read_svg(self):
        """Read an SVG file and import its elements as Draft objects."""
        operation = "importSVG.import"
        _msg("  Test '{}'".format(operation))
        _msg("  This test requires an SVG file to read.")

        file = "Mod/Draft/drafttest/test.svg"
        in_file = os.path.join(App.getResourceDir(), file)
        _msg("  file={}".format(in_file))
        _msg("  exists={}".format(os.path.exists(in_file)))

        obj = aux.fake_function(in_file)
        self.assertTrue(obj, "'{}' failed".format(operation))

    def test_export_svg(self):
        """Create some figures and export them to an SVG file."""
        operation = "importSVG.export"
        _msg("  Test '{}'".format(operation))

        file = "Mod/Draft/drafttest/out_test.svg"
        out_file = os.path.join(App.getResourceDir(), file)
        _msg("  file={}".format(out_file))
        _msg("  exists={}".format(os.path.exists(out_file)))

        obj = aux.fake_function(out_file)
        self.assertTrue(obj, "'{}' failed".format(operation))

    @unittest.skipIf(not have_arch, "BIM module is not installed")
    def test_get_svg_from_arch_space_with_zero_vector(self):
        """Try to get a svg string from an Arch Space with a zero-vector as direction."""
        import Part
        import Draft

        sb = Part.makeBox(1, 1, 1)
        b = self.doc.addObject("Part::Feature", "Box")
        b.Shape = sb

        s = Arch.makeSpace(b)
        self.doc.recompute()

        try:
            Draft.get_svg(s, direction=App.Vector(0, 0, 0))
        except AttributeError as err:
            self.fail("Cryptic exception thrown: {}".format(err))
        except ValueError as err:
            App.Console.PrintLog("Exception thrown, OK: {}".format(err))
        else:
            self.fail("no exception thrown")


class DraftSVGExportRegression(test_base.DraftTestCaseDoc):
    """Regression tests for SVG export edge cases."""

    @staticmethod
    def _make_face_with_circular_island():
        outer = Part.makePolygon(
            [
                App.Vector(0, 0, 0),
                App.Vector(20, 0, 0),
                App.Vector(20, 20, 0),
                App.Vector(0, 20, 0),
                App.Vector(0, 0, 0),
            ]
        )
        inner = Part.Wire([Part.makeCircle(5, App.Vector(10, 10, 0), App.Vector(0, 0, 1))])
        return Part.Face([outer, inner])

    @staticmethod
    def _make_circular_face():
        wire = Part.Wire([Part.makeCircle(5, App.Vector(0, 0, 0), App.Vector(0, 0, 1))])
        return Part.Face([wire])

    @staticmethod
    def _make_face_with_rectangular_island_in_circle():
        outer = Part.Wire([Part.makeCircle(10, App.Vector(10, 10, 0), App.Vector(0, 0, 1))])
        inner = Part.makePolygon(
            [
                App.Vector(7, 8, 0),
                App.Vector(13, 8, 0),
                App.Vector(13, 12, 0),
                App.Vector(7, 12, 0),
                App.Vector(7, 8, 0),
            ]
        )
        return Part.Face([outer, inner])

    def _add_shape(self, name, shape):
        obj = self.doc.addObject("Part::Feature", name)
        obj.Shape = shape
        self.doc.recompute()
        return obj

    def _assert_island_svg(self, svg):
        self.assertIn("<path ", svg)
        self.assertIn("fill-rule: evenodd", svg)
        self.assertNotIn("<circle ", svg)
        self.assertEqual(svg.count("M "), 2)
        self.assertEqual(svg.count("Z "), 2)
        self.assertEqual(svg.count("A "), 2)
        self.assertEqual(svg.count("L "), 4)

    @staticmethod
    def _iter_island_cases():
        return (
            ("rect_outer_circle_hole", DraftSVGExportRegression._make_face_with_circular_island),
            (
                "circle_outer_rect_hole",
                DraftSVGExportRegression._make_face_with_rectangular_island_in_circle,
            ),
        )

    @staticmethod
    def _force_circle_fallback():
        return mock.patch.object(svgshapes.TechDraw, "projectToSVG", return_value="")

    def test_get_svg_from_face_with_circular_island(self):
        with self._force_circle_fallback():
            for name, shape_factory in self._iter_island_cases():
                with self.subTest(case=name):
                    obj = self._add_shape(f"IslandFace_{name}", shape_factory())
                    svg = Draft.get_svg(obj, direction=App.Vector(0, 0, 1))
                    self._assert_island_svg(svg)

    def test_get_svg_from_face_with_circular_island_for_techdraw(self):
        with self._force_circle_fallback():
            for name, shape_factory in self._iter_island_cases():
                with self.subTest(case=name):
                    obj = self._add_shape(f"TechDrawIslandFace_{name}", shape_factory())
                    svg = Draft.get_svg(obj, direction=App.Vector(0, 0, 1), techdraw=True)
                    self._assert_island_svg(svg)

    def test_export_svg_from_face_with_circular_island(self):
        with self._force_circle_fallback():
            for name, shape_factory in self._iter_island_cases():
                with self.subTest(case=name):
                    obj = self._add_shape(f"ExportIslandFace_{name}", shape_factory())
                    with tempfile.TemporaryDirectory() as temp_dir:
                        out_file = os.path.join(temp_dir, "island_face.svg")
                        importSVG.export([obj], out_file)
                        with open(out_file, "r", encoding="utf-8") as svg_file:
                            svg = svg_file.read()
                    self._assert_island_svg(svg)

    def test_get_svg_from_circular_face_stays_compact(self):
        obj = self._add_shape("DiskFace", self._make_circular_face())

        svg = Draft.get_svg(obj, direction=App.Vector(0, 0, 1))

        self.assertIn("<circle ", svg)
        self.assertNotIn("fill-rule: evenodd", svg)

    @staticmethod
    def _svg_arc_data(svg):
        """Return the start point and first elliptical-arc command."""
        number = r"([-+\d.eE]+)"
        arc = re.search(
            r"A\s*" + r"[ ,]+".join([number] * 7),
            svg,
        )
        points = re.findall(
            r"(?:M|L)\s*" + number + r"[ ,]+" + number,
            svg[: arc.start()] if arc else "",
        )
        if not arc or not points:
            raise AssertionError("Expected an SVG elliptical arc: " + svg)
        return (*map(float, points[-1]), *map(float, arc.groups()))

    @classmethod
    def _elliptical_arc_geometry(cls, svg):
        """Reconstruct an ellipse from SVG endpoints and flags.

        This is SVG's endpoint-to-centre conversion. Correct endpoints and
        radii alone do not select the right centre or swept side.
        """
        arc_data = cls._svg_arc_data(svg)
        x1, y1, rx, ry, rotation, large, sweep, x2, y2 = arc_data
        rx, ry = abs(rx), abs(ry)
        angle = math.radians(rotation % 360)
        cosine, sine = math.cos(angle), math.sin(angle)
        dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
        prime_x = cosine * dx + sine * dy
        prime_y = -sine * dx + cosine * dy
        radii_scale = prime_x * prime_x / (rx * rx)
        radii_scale += prime_y * prime_y / (ry * ry)
        if radii_scale > 1:
            radii_scale = math.sqrt(radii_scale)
            rx *= radii_scale
            ry *= radii_scale
        numerator = rx * rx * ry * ry
        numerator -= rx * rx * prime_y * prime_y
        numerator -= ry * ry * prime_x * prime_x
        denominator = rx * rx * prime_y * prime_y
        denominator += ry * ry * prime_x * prime_x
        factor = math.sqrt(max(0, numerator / denominator))
        if large == sweep:
            factor = -factor
        centre_prime_x = factor * rx * prime_y / ry
        centre_prime_y = -factor * ry * prime_x / rx
        centre_x = cosine * centre_prime_x - sine * centre_prime_y
        centre_x += (x1 + x2) / 2
        centre_y = sine * centre_prime_x + cosine * centre_prime_y
        centre_y += (y1 + y2) / 2
        start = math.atan2(
            (prime_y - centre_prime_y) / ry,
            (prime_x - centre_prime_x) / rx,
        )
        end = math.atan2(
            (-prime_y - centre_prime_y) / ry,
            (-prime_x - centre_prime_x) / rx,
        )
        delta = (end - start) % (2 * math.pi)
        if not sweep:
            delta -= 2 * math.pi
        midpoint_angle = start + delta / 2
        midpoint_prime_x = rx * math.cos(midpoint_angle)
        midpoint_prime_y = ry * math.sin(midpoint_angle)
        midpoint = App.Vector(
            centre_x + cosine * midpoint_prime_x - sine * midpoint_prime_y,
            centre_y + sine * midpoint_prime_x + cosine * midpoint_prime_y,
            0,
        )
        centre = App.Vector(centre_x, centre_y, 0)
        return centre, (rx, ry), midpoint

    def test_circle_arc_centres_and_sweeps(self):
        """Native exported arcs retain their projected centre and swept side."""
        # Serialized SVG endpoints lose some precision at 180 degrees.
        tolerance = 1e-4
        rotations = (
            App.Rotation(),
            App.Rotation(App.Vector(0, 0, 1), 37),
            App.Rotation(App.Vector(1, 0, 0), 90),
            App.Rotation(App.Vector(0, 1, 0), 90),
            App.Rotation(App.Vector(1, 2, 3), 63),
        )
        spans = (45, -45, 90, -90, 180, -180, 270, -270)
        cases = itertools.product(
            rotations,
            (False, True),
            spans,
            (False, True),
        )
        with self._force_circle_fallback():
            for rotation, opposite_normal, span, techdraw in cases:
                u = rotation.multVec(App.Vector(1, 0, 0))
                v = rotation.multVec(App.Vector(0, 1, 0))
                normal = u.cross(v)
                centre = App.Vector(17, -23, 11)
                plane = WorkingPlane.PlaneBase(
                    u,
                    -v if opposite_normal else v,
                    -normal if opposite_normal else normal,
                )

                def project(point):
                    return App.Vector(
                        point.dot(plane.u),
                        point.dot(plane.v),
                        0,
                    )

                def point(angle):
                    radians = math.radians(angle)
                    radial = u * math.cos(radians)
                    radial += v * math.sin(radians)
                    return centre + 847 * radial

                edge = Part.Arc(
                    point(0),
                    point(span / 2),
                    point(span),
                ).toShape()
                with self.subTest(
                    rotation=rotation.Q,
                    opposite_normal=opposite_normal,
                    span=span,
                    techdraw=techdraw,
                ):
                    svg = Draft.get_svg(
                        edge,
                        direction=plane,
                        techdraw=techdraw,
                    )
                    actual, radii, midpoint = self._elliptical_arc_geometry(svg)
                    self.assertLess(
                        (actual - project(centre)).Length,
                        tolerance,
                    )
                    self.assertAlmostEqual(radii[0], 847, places=6)
                    self.assertAlmostEqual(radii[1], 847, places=6)
                    expected_mid = project(point(span / 2))
                    self.assertLess(
                        (midpoint - expected_mid).Length,
                        tolerance,
                    )

    def test_rotated_ellipse_arc_sweep_and_reversed_emission(self):
        """Rotated ellipses retain their centre and side in both traversals."""
        centre = App.Vector(31, -19, 0)
        major, minor = 60, 25
        rotation = App.Rotation(App.Vector(0, 0, 1), 37)
        ellipse = Part.Ellipse(centre, major, minor)
        edge = Part.Edge(ellipse, 0, math.pi / 2)
        edge.rotate(centre, App.Vector(0, 0, 1), 37)
        expected_mid = centre + rotation.multVec(
            App.Vector(
                major / math.sqrt(2),
                minor / math.sqrt(2),
                0,
            )
        )

        with self._force_circle_fallback():
            forward_svg = Draft.get_svg(
                edge,
                direction=App.Vector(0, 0, 1),
            )
            leaf = Part.makeLine(
                centre,
                edge.valueAt(edge.LastParameter),
            )
            sorted_edges = [[leaf, edge]]
            with mock.patch.object(
                svgshapes.Part,
                "sortEdges",
                return_value=sorted_edges,
            ):
                reversed_svg = svgshapes.get_path(
                    None,
                    None,
                    "none",
                    [],
                    "#000000",
                    1,
                    "none",
                    edges=[leaf, edge],
                    pathname="",
                )

        reversed_start = App.Vector(
            *self._svg_arc_data(reversed_svg)[:2],
            0,
        )
        self.assertLess(
            (reversed_start - edge.valueAt(edge.LastParameter)).Length,
            1e-7,
        )
        for svg in (forward_svg, reversed_svg):
            actual, radii, midpoint = self._elliptical_arc_geometry(svg)
            self.assertLess((actual - centre).Length, 1e-6)
            self.assertAlmostEqual(radii[0], major, places=6)
            self.assertAlmostEqual(radii[1], minor, places=6)
            self.assertLess((midpoint - expected_mid).Length, 1e-6)

    def test_circle_arc_reversed_emission(self):
        """A joined path can emit an arc from its final parameter backwards."""
        centre = App.Vector(0, 0, 0)
        start = App.Vector(0, 847, 0)
        mid = App.Vector(-847 / math.sqrt(2), 847 / math.sqrt(2), 0)
        end = App.Vector(-847, 0, 0)
        arc = Part.Arc(start, mid, end).toShape()
        leaf = Part.makeLine(centre, end)
        with self._force_circle_fallback():
            # Preserve this joined order so get_path must reverse the arc's
            # emitted vertices to continue from the leaf endpoint.
            sorted_edges = [[leaf, arc]]
            with mock.patch.object(
                svgshapes.Part,
                "sortEdges",
                return_value=sorted_edges,
            ):
                svg = svgshapes.get_path(
                    None,
                    None,
                    "none",
                    [],
                    "#000000",
                    1,
                    "none",
                    edges=[leaf, arc],
                    pathname="",
                )

        emitted_start = App.Vector(*self._svg_arc_data(svg)[:2], 0)
        self.assertLess(
            (emitted_start - arc.valueAt(arc.LastParameter)).Length,
            1e-7,
        )

        actual, radii, midpoint = self._elliptical_arc_geometry(svg)
        self.assertLess(actual.Length, 1e-5)
        self.assertAlmostEqual(radii[0], 847, places=6)
        self.assertAlmostEqual(radii[1], 847, places=6)
        self.assertLess((midpoint - mid).Length, 1e-5)


## @}
