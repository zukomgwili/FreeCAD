# SPDX-License-Identifier: LGPL-2.1-or-later

"""Draft view rendering and document ownership regressions."""

import os
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import FreeCAD as App

try:
    import Draft
except ImportError:
    Draft = None

from .TechDrawTestUtilities import createPageWithSVGTemplate


@unittest.skipIf(Draft is None, "Draft workbench is not installed")
class DrawViewDraftTest(unittest.TestCase):
    def setUp(self):
        self.documents = []
        self.document = self._newDocument(self._testMethodName)

    def tearDown(self):
        for name in reversed(self.documents):
            if name in App.listDocuments():
                App.closeDocument(name)

    def _newDocument(self, suffix):
        document = App.newDocument("DrawViewDraft_" + suffix)
        self.documents.append(document.Name)
        return document

    def _makeView(self, document, length=100):
        App.setActiveDocument(document.Name)
        source = Draft.make_wire([App.Vector(), App.Vector(length, 0, 0)])
        page = createPageWithSVGTemplate(document)
        view = document.addObject("TechDraw::DrawViewDraft", "DraftView")
        view.Source = source
        page.addView(view)
        document.recompute()
        self._assertValid(view)
        return source, view

    def _assertValid(self, view):
        self.assertNotIn("Invalid", view.State)
        self.assertNotIn("Touched", view.State)
        self.assertTrue(view.Symbol)
        root = ET.fromstring(view.Symbol)
        self.assertEqual(root.tag, "{http://www.w3.org/2000/svg}svg")

    def _assertMatchesSource(self, view):
        # Match Base::Color::asHexString(), including rounding and uppercase.
        color = "#" + "".join(f"{int(channel * 255 + 0.5):02X}" for channel in view.Color[:3])
        expected = Draft.get_svg(
            view.Source,
            scale=view.Scale,
            linewidth=view.LineWidth,
            fontsize=view.FontSize,
            direction=view.Direction,
            linestyle=view.LineStyle,
            color=color,
            linespacing=view.LineSpacing,
            techdraw=True,
            override=view.OverrideStyle,
        )
        self.assertTrue(expected)
        self.assertIn(expected, view.Symbol)
        self._assertValid(view)

    def testInactiveOwner(self):
        source, view = self._makeView(self.document)
        previous = view.Symbol
        foreign = self._newDocument("Unrelated")
        source.Points = [App.Vector(), App.Vector(140, 0, 0)]
        view.LineWidth = 0.75
        view.OverrideStyle = True
        self.document.recompute()
        self.assertEqual(App.ActiveDocument.Name, foreign.Name)
        self.assertEqual(foreign.Objects, [])
        self._assertValid(view)
        self.assertNotEqual(view.Symbol, previous)
        self._assertMatchesSource(view)

    def testDuplicateNamesInActiveDocument(self):
        source, view = self._makeView(self.document)
        foreign = self._newDocument("DuplicateNames")
        foreign_source, foreign_view = self._makeView(foreign, length=300)
        self.assertEqual(source.Name, foreign_source.Name)
        self.assertEqual(view.Name, foreign_view.Name)
        previous = foreign_view.Symbol
        states = [(obj.Name, list(obj.State)) for obj in foreign.Objects]
        source.Points = [App.Vector(), App.Vector(140, 0, 0)]
        view.LineWidth = 0.75
        view.OverrideStyle = True
        self.document.recompute()
        self.assertEqual(App.ActiveDocument.Name, foreign.Name)
        self.assertEqual(foreign_view.Symbol, previous)
        self.assertEqual([(obj.Name, list(obj.State)) for obj in foreign.Objects], states)
        self._assertMatchesSource(view)

    def testInactiveOwnerAfterReopen(self):
        source, view = self._makeView(self.document)
        source_name, view_name = source.Name, view.Name
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "DraftViewOwner.FCStd")
            self.document.saveAs(path)
            App.closeDocument(self.document.Name)
            self.document = App.openDocument(path)
            self.documents.append(self.document.Name)
            source = self.document.getObject(source_name)
            view = self.document.getObject(view_name)
            foreign = self._newDocument("RestoredDuplicateNames")
            foreign_source, foreign_view = self._makeView(foreign, length=300)
            previous = foreign_view.Symbol
            source.Points = [App.Vector(), App.Vector(140, 0, 0)]
            view.LineWidth = 0.75
            view.OverrideStyle = True
            self.document.recompute()
            self.assertEqual(App.ActiveDocument.Name, foreign.Name)
            self.assertEqual(foreign_view.Symbol, previous)
            self._assertMatchesSource(view)

    def testSingleDocumentRenderingOptions(self):
        source, view = self._makeView(self.document)
        source.Points = [App.Vector(11, 23, 7), App.Vector(61, 73, 37)]
        view.Scale = 0.5
        view.LineWidth = 0.75
        view.FontSize = 15
        view.LineSpacing = 2
        view.Direction = App.Vector(1, 2, 3)
        view.Color = (0.25, 0.5, 0.75)
        view.LineStyle = "0.20, 0.40"
        if App.GuiUp:
            source.ViewObject.LineWidth = 2
            source.ViewObject.LineColor = (0.75, 0.25, 0.5)
            source.ViewObject.DrawStyle = "Dashed"
        for override in (False, True):
            with self.subTest(override=override):
                view.OverrideStyle = override
                with patch("Draft.get_svg", wraps=Draft.get_svg) as renderer:
                    view.touch()
                    self.document.recompute()
                renderer.assert_called_once()
                args, options = renderer.call_args
                self.assertEqual(args, (source,))
                self.assertEqual(
                    options,
                    {
                        "scale": 0.5,
                        "linewidth": 0.75,
                        "fontsize": 15,
                        "direction": App.Vector(1, 2, 3),
                        "linestyle": "0.20, 0.40",
                        "color": "#4080BF",
                        "linespacing": 2,
                        "techdraw": True,
                        "override": override,
                    },
                )
                self._assertMatchesSource(view)

    def testRendererErrorPreservesSymbol(self):
        source, view = self._makeView(self.document)
        previous = view.Symbol
        with patch("Draft.get_svg", side_effect=RuntimeError("Draft renderer failure")):
            view.touch()
            self.document.recompute()
        self.assertIn("Invalid", view.State)
        self.assertIn("Draft renderer failure", view.getStatusString())
        self.assertEqual(view.Symbol, previous)
