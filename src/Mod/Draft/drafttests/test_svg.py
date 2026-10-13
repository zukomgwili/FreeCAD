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
import xml.etree.ElementTree as ET

import FreeCAD as App
import Draft
import Part
import TechDraw
import WorkingPlane
import draftfunctions.svg as svgfunctions
import draftfunctions.svgshapes as svgshapes
import draftfunctions.svgtext as svgtext
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


class DraftSVGTextExportRegression(test_base.DraftTestCaseDoc):
    """Regression tests for text orientation in SVG exports."""

    @staticmethod
    def _text_plane_rotations():
        return (
            App.Rotation(),
            App.Rotation(App.Vector(0, 0, 1), 37),
            App.Rotation(App.Vector(1, 0, 0), 90),
            App.Rotation(App.Vector(0, 1, 0), 90),
            App.Rotation(App.Vector(1, 2, 3), 63),
        )

    @staticmethod
    def _text_plane(rotation, opposite=False):
        u = rotation.multVec(App.Vector(1, 0, 0))
        v = rotation.multVec(App.Vector(0, 1, 0))
        normal = rotation.multVec(App.Vector(0, 0, 1))
        return WorkingPlane.PlaneBase(u, -v if opposite else v, -normal if opposite else normal)

    @staticmethod
    def _text_svg(rotation, plane, techdraw):
        return svgtext.get_text(
            plane,
            techdraw,
            "#123456",
            5,
            "DejaVu Sans",
            rotation,
            App.Vector(17, -23, 0),
            ["Parallel <note> & detail", "Second line"],
            linespacing=7,
            align="left",
        )

    @staticmethod
    def _svg_root(svg):
        return ET.fromstring(
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'xmlns:freecad="https://www.freecad.org/wiki/index.php?title=Svg_Namespace">'
            + svg
            + "</svg>"
        )

    def _assert_text_content(self, svg, techdraw):
        nodes = self._svg_root(svg).findall(".//{http://www.w3.org/2000/svg}text")
        self.assertEqual(len(nodes), 2 if techdraw else 1)
        text = "".join("".join(node.itertext()) for node in nodes)
        self.assertIn("Parallel <note> & detail", text)
        self.assertIn("Second line", text)
        return nodes

    def test_text_parallel_to_rotated_plane(self):
        """Text uses its actual normal and baseline in either SVG output mode."""
        cases = itertools.product(
            self._text_plane_rotations(), (False, True), (-37, -2, 0, 2, 37, 143), (False, True)
        )
        for frame, opposite, roll, techdraw in cases:
            plane = self._text_plane(frame, opposite)
            rotation = frame * App.Rotation(App.Vector(0, 0, 1), roll)
            with self.subTest(frame=frame.Q, opposite=opposite, roll=roll, techdraw=techdraw):
                svg = self._text_svg(rotation, plane, techdraw)
                nodes = self._assert_text_content(svg, techdraw)
                angle = math.radians(
                    float(re.search(r"rotate\(([^,]+),", nodes[0].get("transform"))[1])
                )
                expected = math.radians(-roll if opposite else roll)
                self.assertAlmostEqual(math.cos(angle), math.cos(expected), places=7)
                self.assertAlmostEqual(math.sin(angle), math.sin(expected), places=7)

    def test_text_perpendicular_to_rotated_plane_is_hidden(self):
        """Actually edge-on text remains suppressed, independent of rotation axis."""
        cases = itertools.product(
            self._text_plane_rotations(), (False, True), (90, -90), (False, True)
        )
        for frame, opposite, tilt, techdraw in cases:
            plane = self._text_plane(frame, opposite)
            rotation = frame * App.Rotation(App.Vector(1, 0, 0), tilt)
            with self.subTest(frame=frame.Q, opposite=opposite, tilt=tilt, techdraw=techdraw):
                self.assertEqual(self._text_svg(rotation, plane, techdraw), "")

    def test_text_oblique_to_rotated_plane(self):
        """A non-edge-on baseline is projected into the view's u/v axes."""
        cases = itertools.product(self._text_plane_rotations(), (False, True), (False, True))
        for frame, opposite, techdraw in cases:
            plane = self._text_plane(frame, opposite)
            rotation = (
                frame
                * App.Rotation(App.Vector(1, 0, 0), 45)
                * App.Rotation(App.Vector(0, 0, 1), 37)
            )
            with self.subTest(frame=frame.Q, opposite=opposite, techdraw=techdraw):
                svg = self._text_svg(rotation, plane, techdraw)
                nodes = self._assert_text_content(svg, techdraw)
                angle = math.radians(
                    float(re.search(r"rotate\(([^,]+),", nodes[0].get("transform"))[1])
                )
                x = math.cos(math.radians(37))
                y = math.sin(math.radians(37)) * math.cos(math.radians(45))
                length = math.hypot(x, y)
                self.assertAlmostEqual(math.cos(angle), x / length, places=7)
                self.assertAlmostEqual(math.sin(angle), (-y if opposite else y) / length, places=7)

    def test_text_existing_numeric_and_unprojected_angles(self):
        """Dimension angles and unprojected rotations keep their existing contract."""
        cases = itertools.product((-0.37, 0, 0.37), (False, True))
        for angle, techdraw in cases:
            plane = self._text_plane(App.Rotation(App.Vector(1, 0, 0), 90))
            svg = self._text_svg(angle, plane, techdraw)
            nodes = self._assert_text_content(svg, techdraw)
            actual = math.radians(
                float(re.search(r"rotate\(([^,]+),", nodes[0].get("transform"))[1])
            )
            self.assertAlmostEqual(actual, angle)
            rotation = App.Rotation(App.Vector(0, 0, 1), math.degrees(angle))
            nodes = self._assert_text_content(self._text_svg(rotation, None, techdraw), techdraw)
            actual = math.radians(
                float(re.search(r"rotate\(([^,]+),", nodes[0].get("transform"))[1])
            )
            self.assertAlmostEqual(actual, rotation.Angle)

    @unittest.skipUnless(App.GuiUp, "Draft label rendering requires its native view provider")
    def test_label_and_text_svg_in_rotated_planes(self):
        """Stock annotations retain parallel text, and label leaders stay intact."""
        label = Draft.make_label(
            custom_text=["Parallel <note> & detail", "Second line"], distance=-10
        )
        label.ViewObject.Justification = "Left"
        text = Draft.make_text(["Parallel <note> & detail", "Second line"])
        cases = itertools.product(
            self._text_plane_rotations(), (False, True), (False, True), (0, 90)
        )
        for frame, opposite, techdraw, tilt in cases:
            plane = self._text_plane(frame, opposite)
            rotation = frame * App.Rotation(App.Vector(1, 0, 0), tilt)
            placement = App.Placement(App.Vector(23, 31, 17), rotation)
            label.Placement = placement
            text.Placement = placement
            label.TargetPoint = placement.multVec(App.Vector(-35, -20, 0))
            self.doc.recompute()
            for obj in (label, text):
                with self.subTest(
                    frame=frame.Q, opposite=opposite, tilt=tilt, techdraw=techdraw, obj=obj.Name
                ):
                    svg = Draft.get_svg(obj, direction=plane, techdraw=techdraw)
                    root = self._svg_root(svg)
                    if obj is label:
                        self.assertTrue(root.findall(".//{http://www.w3.org/2000/svg}path"))
                    if tilt == 0:
                        self._assert_text_content(svg, techdraw)
                    else:
                        self.assertFalse(root.findall(".//{http://www.w3.org/2000/svg}text"))

    @unittest.skipUnless(App.GuiUp and have_arch, "Arch label views require BIM and the GUI")
    def test_arch_view_label_text_in_rotated_sections(self):
        """Ordinary TechDraw Arch views retain label text and their stock leaders."""
        label = Draft.make_label(custom_text="Section label", distance=-10)
        label.ViewObject.Justification = "Left"
        section = Arch.makeSectionPlane([label])
        page = self.doc.addObject("TechDraw::DrawPage", "Page")
        template = self.doc.addObject("TechDraw::DrawSVGTemplate", "Template")
        template.Template = os.path.join(
            App.getResourceDir(), "Mod", "TechDraw", "Templates", "ISO", "A3_Landscape_blank.svg"
        )
        page.Template = template
        view = self.doc.addObject("TechDraw::DrawViewArch", "ArchView")
        view.Source = section
        view.AllOn = True
        page.addView(view)
        cases = itertools.product(self._text_plane_rotations(), (0, 90, 180), (0, -90))
        for frame, flip, view_angle in cases:
            section.Placement = App.Placement(App.Vector(), frame)
            rotation = frame * App.Rotation(App.Vector(1, 0, 0), flip)
            label.Placement = App.Placement(App.Vector(), rotation)
            label.TargetPoint = label.Placement.multVec(App.Vector(-35, -20, 0))
            view.Rotation = view_angle
            view.touch()
            self.doc.recompute()
            with self.subTest(frame=frame.Q, flip=flip, view_angle=view_angle):
                self.assertNotIn("Invalid", view.State)
                self.assertNotIn("Touched", view.State)
                root = ET.fromstring(view.Symbol)
                nodes = root.findall(".//{http://www.w3.org/2000/svg}text")
                paths = root.findall(".//{http://www.w3.org/2000/svg}path")
                if flip == 90:
                    self.assertFalse(nodes)
                    self.assertFalse(paths)
                else:
                    self.assertEqual(len(nodes), 1)
                    self.assertIn("Section label", "".join(nodes[0].itertext()))
                    self.assertTrue(paths)

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "SectionLabel.FCStd")
            view_name = view.Name
            self.doc.saveAs(path)
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(path)
            view = self.doc.getObject(view_name)
            view.touch()
            self.doc.recompute()
            self.assertNotIn("Invalid", view.State)
            self.assertNotIn("Touched", view.State)
            root = ET.fromstring(view.Symbol)
            nodes = root.findall(".//{http://www.w3.org/2000/svg}text")
            self.assertEqual(len(nodes), 1)
            self.assertIn("Section label", "".join(nodes[0].itertext()))


class DraftSVGExportRegression(test_base.DraftTestCaseDoc):
    """Regression tests for SVG export edge cases."""

    @staticmethod
    def _linear_svg_segments(paths):
        segments = set()
        number = r"[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?"
        for path in paths:
            previous = None
            for command, x, y in re.findall(
                r"([ML])\s+(" + number + r")\s+(" + number + r")", path.get("d")
            ):
                point = (round(float(x), 7), round(float(y), 7))
                if command == "L":
                    segments.add(tuple(sorted((previous, point))))
                previous = point
        return segments

    @staticmethod
    def _path_for_ordered_groups(groups, pathdata):
        edges = [edge for group in groups for edge in group]
        shape = Part.makeCompound(edges)
        with mock.patch.object(svgshapes.Part, "sortEdges", return_value=groups):
            return svgshapes.get_path(
                shape,
                None,
                "none",
                pathdata,
                "#123456",
                0.75,
                "0.4,0.8",
                fill_opacity=0.4,
                edges=edges,
                pathname="",
            )

    def test_duplicate_subpaths_preserve_other_groups(self):
        """Exact duplicate-first/middle/last groups cannot discard unique geometry."""
        a = Part.makeLine(App.Vector(), App.Vector(10, 0, 0))
        duplicate = Part.makeLine(App.Vector(0, 0, 3), App.Vector(10, 0, 3))
        b = Part.makeLine(App.Vector(20, 4, 0), App.Vector(30, 4, 0))
        expected = {((0.0, 0.0), (10.0, 0.0)), ((20.0, 4.0), (30.0, 4.0))}
        for order, preseed in itertools.product(
            itertools.permutations((a, duplicate, b)), (False, True)
        ):
            pathdata = []
            if preseed:
                self._path_for_ordered_groups([[a]], pathdata)
            with self.subTest(order=[edge.Vertexes[0].Point for edge in order], preseed=preseed):
                svg = self._path_for_ordered_groups([[edge] for edge in order], pathdata)
                paths = self._raw_svg_paths(svg)
                self.assertEqual(len(paths), 1)
                self.assertEqual(len(pathdata), 2)
                self.assertEqual(len(set(pathdata)), 2)
                self.assertEqual(paths[0].get("d").count("M"), 1 if preseed else 2)
                wanted = {((20.0, 4.0), (30.0, 4.0))} if preseed else expected
                self.assertEqual(self._linear_svg_segments(paths), wanted)
                self.assertEqual(paths[0].get("stroke"), "#123456")
                self.assertEqual(paths[0].get("stroke-width"), "0.75px")
                self.assertIn("stroke-dasharray:0.4,0.8", paths[0].get("style"))
                self.assertIn("fill-opacity:0.4", paths[0].get("style"))

    def test_all_cached_subpaths_produce_no_empty_path(self):
        """A fully deduped call stays empty and does not mutate the shared cache."""
        a = Part.makeLine(App.Vector(), App.Vector(10, 0, 0))
        b = Part.makeLine(App.Vector(20, 4, 0), App.Vector(30, 4, 0))
        pathdata = []
        self.assertTrue(self._path_for_ordered_groups([[a], [b]], pathdata))
        previous = list(pathdata)
        self.assertEqual(self._path_for_ordered_groups([[b], [a]], pathdata), "")
        self.assertEqual(pathdata, previous)
        self.assertEqual(self._path_for_ordered_groups([], pathdata), "")
        self.assertEqual(pathdata, previous)

    def test_coincident_raw_compound_keeps_visible_geometry(self):
        """The public exporter keeps a single instance of coincident projected edges."""
        shape = Part.makeCompound(
            [
                Part.makeLine(App.Vector(), App.Vector(10, 0, 0)),
                Part.makeLine(App.Vector(0, 0, 3), App.Vector(10, 0, 3)),
            ]
        )
        original = shape.exportBrepToString()
        for techdraw in (False, True):
            paths = self._raw_svg_paths(Draft.get_svg(shape, fillstyle="none", techdraw=techdraw))
            self.assertEqual(len(paths), 1)
            self.assertEqual(paths[0].get("d").count("M"), 1)
            self.assertEqual(self._linear_svg_segments(paths), {((0.0, 0.0), (10.0, 0.0))})
            self.assertEqual(shape.exportBrepToString(), original)

    def test_raw_box_axial_and_default_projection_geometry(self):
        """Default/axial box projections retain every unique edge and their styles."""
        shape = Part.makeBox(10, 7, 3)
        original = shape.exportBrepToString()
        directions = (
            None,
            App.Vector(0, 0, 1),
            App.Vector(0, 0, -1),
            App.Vector(1, 0, 0),
            App.Vector(-1, 0, 0),
            App.Vector(0, 1, 0),
            App.Vector(0, -1, 0),
            App.Vector(1, 2, 3),
        )
        for direction, fill, techdraw in itertools.product(
            directions, ("none", "#ABCDEF"), (False, True)
        ):
            if direction is None:
                u, v = App.Vector(1, 0, 0), App.Vector(0, 1, 0)
            else:
                plane = WorkingPlane.PlaneBase()
                plane.align_to_point_and_axis_svg(App.Vector(), direction)
                u, v = plane.u, plane.v
            expected = set()
            for edge in shape.Edges:
                points = [
                    (round(vertex.Point.dot(u), 7), round(vertex.Point.dot(v), 7))
                    for vertex in edge.Vertexes
                ]
                expected.add(tuple(sorted(points)))
            with self.subTest(direction=direction, fill=fill, techdraw=techdraw):
                paths = self._raw_svg_paths(
                    Draft.get_svg(
                        shape,
                        direction=direction,
                        fillstyle=fill,
                        techdraw=techdraw,
                        scale=0.5,
                        linewidth=0.75,
                        color="#123456",
                        linestyle="0.20, 0.40",
                    )
                )
                self.assertTrue(paths)
                self.assertEqual(self._linear_svg_segments(paths), expected)
                for path in paths:
                    self.assertTrue(path.get("d").strip())
                    subpaths = [data.strip() for data in re.findall(r"M[^M]*", path.get("d"))]
                    self.assertEqual(len(subpaths), len(set(subpaths)))
                    self.assertEqual(path.get("stroke"), "#123456")
                    self.assertEqual(path.get("stroke-width"), "1.5px")
                    self.assertIn("fill:" + fill, path.get("style"))
                    self.assertIn("stroke-dasharray:0.4,0.8", path.get("style"))
                self.assertEqual(shape.exportBrepToString(), original)

    @staticmethod
    def _raw_shapes():
        edge = Part.makeLine(App.Vector(), App.Vector(10, 0, 0))
        wire = Part.makePolygon(
            [
                App.Vector(),
                App.Vector(10, 0, 0),
                App.Vector(10, 7, 0),
                App.Vector(0, 7, 0),
                App.Vector(),
            ]
        )
        return edge, wire, Part.Face(wire), Part.makeBox(10, 7, 3)

    @staticmethod
    def _raw_svg_paths(svg):
        root = ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg">' + svg + "</svg>")
        return root.findall(".//{http://www.w3.org/2000/svg}path")

    def test_raw_shapes_have_no_layer_print_color(self):
        """Detached shapes cannot acquire style metadata from an active document."""
        with mock.patch.object(svgfunctions.layer, "get_layer", return_value=None) as get_layer:
            for shape in self._raw_shapes():
                with self.subTest(shape=shape.ShapeType):
                    self.assertFalse(hasattr(shape, "Document"))
                    self.assertIsNone(svgfunctions.get_print_color(shape))
            self.assertIsNone(svgfunctions.get_print_color(mock.Mock(Document=None)))
            get_layer.assert_not_called()

    def test_raw_shape_svg_default_styles(self):
        """Raw edges, wires, faces and solids export in GUI and command mode."""
        for shape, override, techdraw in itertools.product(
            self._raw_shapes(), (False, True), (False, True)
        ):
            original = shape.exportBrepToString()
            with self.subTest(shape=shape.ShapeType, override=override, techdraw=techdraw):
                svg = Draft.get_svg(
                    shape, direction=App.Vector(1, 2, 3), override=override, techdraw=techdraw
                )
                paths = self._raw_svg_paths(svg)
                self.assertTrue(paths)
                for path in paths:
                    self.assertEqual(path.get("stroke"), "#000000")
                    self.assertEqual(path.get("stroke-width"), "0.35px")
                    self.assertIn("stroke-dasharray:none", path.get("style"))
                self.assertEqual(shape.exportBrepToString(), original)

    def test_raw_shape_svg_override_styles(self):
        """Explicit raw-shape colors, fills and scaled line styles stay intact."""
        for shape, override, techdraw in itertools.product(
            self._raw_shapes(), (False, True), (False, True)
        ):
            original = shape.exportBrepToString()
            with self.subTest(shape=shape.ShapeType, override=override, techdraw=techdraw):
                svg = Draft.get_svg(
                    shape,
                    scale=0.5,
                    linewidth=0.75,
                    direction=App.Vector(1, 2, 3),
                    color="#123456",
                    fillstyle="#ABCDEF",
                    linestyle="0.20, 0.40",
                    override=override,
                    techdraw=techdraw,
                )
                paths = self._raw_svg_paths(svg)
                self.assertTrue(paths)
                for path in paths:
                    self.assertEqual(path.get("stroke"), "#123456" if override else "#000000")
                    self.assertEqual(path.get("stroke-width"), "1.5px")
                    self.assertIn("fill:#ABCDEF", path.get("style"))
                    self.assertIn(
                        "stroke-dasharray:" + ("0.4,0.8" if override else "none"), path.get("style")
                    )
                self.assertEqual(shape.exportBrepToString(), original)

    @unittest.skipUnless(App.GuiUp, "Layer print colors require native view providers")
    def test_document_layer_print_color_and_raw_shape_fallback(self):
        """Document-owned print colors still work, but bare shapes cannot inherit them."""
        obj = self._add_shape("LayeredEdge", self._raw_shapes()[0])
        layer = Draft.make_layer(line_color=(0.0, 1.0, 0.0), line_width=2)
        layer.Group = [obj]
        layer.ViewObject.LinePrintColor = (1.0, 0.0, 0.0)
        layer.ViewObject.UsePrintColor = True
        self.doc.recompute()
        self.assertEqual(svgfunctions.get_print_color(obj), layer.ViewObject.LinePrintColor)
        paths = self._raw_svg_paths(Draft.get_svg(obj, override=False))
        self.assertTrue(paths)
        self.assertEqual([path.get("stroke") for path in paths], ["#ff0000"] * len(paths))

        raw = obj.Shape
        self.assertIsNone(svgfunctions.get_print_color(raw))
        paths = self._raw_svg_paths(Draft.get_svg(raw, override=False))
        self.assertTrue(paths)
        self.assertTrue(all(path.get("stroke") == "#000000" for path in paths))

        layer.ViewObject.UsePrintColor = False
        self.assertIsNone(svgfunctions.get_print_color(obj))
        paths = self._raw_svg_paths(Draft.get_svg(obj, override=False))
        self.assertTrue(paths)
        self.assertTrue(all(path.get("stroke") == "#00ff00" for path in paths))
        self.assertTrue(all(path.get("stroke-width") == "0.7px" for path in paths))

        layer.ViewObject.UsePrintColor = True
        paths = self._raw_svg_paths(Draft.get_svg(obj, color="#123456", override=True))
        self.assertTrue(paths)
        self.assertTrue(all(path.get("stroke") == "#123456" for path in paths))
        unlayered = self._add_shape("UnlayeredEdge", raw)
        unlayered.ViewObject.LineColor = (0.0, 0.0, 1.0)
        self.assertIsNone(svgfunctions.get_print_color(unlayered))
        paths = self._raw_svg_paths(Draft.get_svg(unlayered, override=False))
        self.assertTrue(paths)
        self.assertTrue(all(path.get("stroke") == "#0000ff" for path in paths))

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
        return mock.patch.object(TechDraw, "projectToSVG", return_value="")

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

    def test_native_arc_projection_occ_versions(self):
        """OCC 7.1 and later major releases use native arc projection."""
        edge = Part.Arc(
            App.Vector(11, 23, 0),
            App.Vector(31, 43, 0),
            App.Vector(51, 23, 0),
        ).toShape()
        for version, supported in (
            ("6.9.0", False),
            ("7.0.0", False),
            ("7.1.0", True),
            ("7.9.3", True),
            ("8.0.0", True),
            ("8.0.1", True),
        ):
            with self.subTest(version=version):
                with mock.patch.object(Part, "OCC_VERSION", version):
                    with mock.patch.object(
                        TechDraw,
                        "projectToSVG",
                        wraps=TechDraw.projectToSVG,
                    ) as project:
                        svg = Draft.get_svg(edge, direction=App.Vector(0, 0, 1))
                self.assertEqual(project.call_count, int(supported))
                centre, radii, midpoint = self._elliptical_arc_geometry(svg)
                self.assertLess((centre - App.Vector(31, 23, 0)).Length, 1e-4)
                self.assertAlmostEqual(radii[0], 20, places=6)
                self.assertAlmostEqual(radii[1], 20, places=6)
                self.assertLess((midpoint - App.Vector(31, 43, 0)).Length, 1e-4)

    def test_native_arc_projection_working_plane_coordinates(self):
        """HLR arcs share the path's projected centre, endpoints and swept side."""
        rotations = (
            App.Rotation(),
            App.Rotation(App.Vector(1, 0, 0), 90),
            App.Rotation(App.Vector(0, 1, 0), 90),
            App.Rotation(App.Vector(1, 2, 3), 63),
        )
        cases = itertools.product(rotations, (0, 37), (False, True), (False, True))
        for rotation, roll, opposite_normal, ellipse in cases:
            u = rotation.multVec(App.Vector(1, 0, 0))
            v = rotation.multVec(App.Vector(0, 1, 0))
            plane_rotation = App.Rotation(u.cross(v), roll)
            u = plane_rotation.multVec(u)
            v = plane_rotation.multVec(v)
            plane = WorkingPlane.PlaneBase(
                u,
                -v if opposite_normal else v,
                -u.cross(v) if opposite_normal else u.cross(v),
                App.Vector(101, -53, 29),
            )
            centre = App.Vector(17, -23, 11)
            if ellipse:
                major, minor = 60, 25
                edge = Part.Edge(Part.Ellipse(App.Vector(), major, minor), 0, math.pi / 2)
                edge.Placement = App.Placement(centre, rotation)
                midpoint = centre + rotation.multVec(
                    App.Vector(major / math.sqrt(2), minor / math.sqrt(2), 0)
                )
            else:
                major = minor = 60
                edge = Part.Arc(
                    centre + rotation.multVec(App.Vector(60, 0, 0)),
                    centre + rotation.multVec(App.Vector(60 / math.sqrt(2), 60 / math.sqrt(2), 0)),
                    centre + rotation.multVec(App.Vector(0, 60, 0)),
                ).toShape()
                midpoint = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2)

            def project(point):
                return App.Vector(point.dot(plane.u), point.dot(plane.v), 0)

            with self.subTest(
                rotation=rotation.Q, roll=roll, opposite_normal=opposite_normal, ellipse=ellipse
            ):
                with mock.patch.object(
                    TechDraw, "projectToSVG", wraps=TechDraw.projectToSVG
                ) as native:
                    svg = Draft.get_svg(edge, direction=plane)
                self.assertEqual(native.call_count, 1)
                actual, radii, actual_midpoint = self._elliptical_arc_geometry(svg)
                self.assertLess((actual - project(centre)).Length, 1e-4)
                self.assertAlmostEqual(radii[0], major, places=4)
                self.assertAlmostEqual(radii[1], minor, places=4)
                self.assertLess((actual_midpoint - project(midpoint)).Length, 1e-4)

    def test_native_arc_projection_reversed_emission(self):
        """Joined paths keep their arc endpoint and side with native projection."""
        # The native input must retain traversal even far from the origin,
        # where six-digit serialization of global endpoints would merge them.
        for centre in (App.Vector(17, -23, 0), App.Vector(1e8, 1e8, 0)):
            with self.subTest(centre=centre):
                start = centre + App.Vector(60, 0, 0)
                midpoint = centre + App.Vector(60 / math.sqrt(2), 60 / math.sqrt(2), 0)
                end = centre + App.Vector(0, 60, 0)
                arc = Part.Arc(start, midpoint, end).toShape()
                leaf = Part.makeLine(centre, end)
                with mock.patch.object(svgshapes.Part, "sortEdges", return_value=[[leaf, arc]]):
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
                actual, radii, actual_midpoint = self._elliptical_arc_geometry(svg)
                self.assertLess((actual - centre).Length, 1e-4)
                self.assertLess((actual_midpoint - midpoint).Length, 1e-4)
                emitted_end = App.Vector(*self._svg_arc_data(svg)[-2:], 0)
                self.assertLess((emitted_end - start).Length, 1e-4)

    def test_native_projection_preserves_circular_islands(self):
        """Closed native circle snippets retain the compound path and its holes."""
        for name, shape_factory in self._iter_island_cases():
            with self.subTest(case=name):
                obj = self._add_shape(f"NativeIslandFace_{name}", shape_factory())
                svg = Draft.get_svg(obj, direction=App.Vector(0, 0, 1))
                self._assert_island_svg(svg)

    def test_native_projection_preserves_closed_ellipse(self):
        """Full native ellipse snippets use two arcs in the working plane."""
        centre = App.Vector(17, -23, 11)
        rotation = App.Rotation(App.Vector(1, 2, 3), 63)
        u = rotation.multVec(App.Vector(1, 0, 0))
        v = rotation.multVec(App.Vector(0, 1, 0))
        roll = App.Rotation(u.cross(v), 37)
        for opposite in (False, True):
            plane_v = roll.multVec(v)
            plane = WorkingPlane.PlaneBase(
                roll.multVec(u),
                -plane_v if opposite else plane_v,
                -u.cross(v) if opposite else u.cross(v),
            )
            edge = Part.Ellipse(App.Vector(), 60, 25).toShape()
            edge.Placement = App.Placement(centre, rotation)
            with self.subTest(opposite=opposite):
                svg = Draft.get_svg(edge, direction=plane)
                self.assertEqual(svg.count("A "), 2)
                actual, radii, midpoint = self._elliptical_arc_geometry(svg)
                expected = App.Vector(centre.dot(plane.u), centre.dot(plane.v), 0)
                self.assertLess((actual - expected).Length, 1e-4)
                self.assertAlmostEqual(radii[0], 60, places=6)
                self.assertAlmostEqual(radii[1], 25, places=6)
                expected_mid = edge.valueAt(math.pi / 2)
                expected_mid = App.Vector(expected_mid.dot(plane.u), expected_mid.dot(plane.v), 0)
                self.assertLess((midpoint - expected_mid).Length, 1e-4)

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
        self._check_circle_arc_centres_and_sweeps(native=False)

    def test_native_circle_arc_centres_and_sweeps(self):
        """HLR preserves clockwise, major and semicircular arc geometry."""
        self._check_circle_arc_centres_and_sweeps(native=True)

    def _check_circle_arc_centres_and_sweeps(self, native):
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
        projection = (
            mock.patch.object(TechDraw, "projectToSVG", wraps=TechDraw.projectToSVG)
            if native
            else self._force_circle_fallback()
        )
        with projection as project_to_svg:
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
                    if native:
                        self.assertEqual(project_to_svg.call_count, 1)
                        project_to_svg.reset_mock()
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
