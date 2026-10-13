# SPDX-License-Identifier: LGPL-2.1-or-later

"""Native integration tests, using a non-installed bridge to production PagePrinter."""

import os
from pathlib import Path
import re
import tempfile
import unittest

import FreeCAD as App
import FreeCADGui as Gui
import TechDrawGui
from PySide import QtCore
import _PagePrinterTestSupport as Native


class PagePrinterTest(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("TDNativePrint")
        self.directory = tempfile.TemporaryDirectory()
        self.view_preferences = App.ParamGet("User parameter:BaseApp/Preferences/Mod/TechDraw/View")
        self.color_preferences = App.ParamGet(
            "User parameter:BaseApp/Preferences/Mod/TechDraw/Colors"
        )
        self.screen_mode = self.view_preferences.GetBool("ScreenMode", True)
        self.light_on_dark = self.color_preferences.GetBool("LightOnDark", False)

    @staticmethod
    def _events():
        Gui.updateGui()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        Gui.updateGui()

    def tearDown(self):
        App.closeDocument(self.doc.Name)
        self._events()
        self.view_preferences.SetBool("ScreenMode", self.screen_mode)
        self.color_preferences.SetBool("LightOnDark", self.light_on_dark)
        self._events()
        self.directory.cleanup()

    def _page(self, name, initialized=False):
        page = self.doc.addObject("TechDraw::DrawPage", name)
        template = self.doc.addObject("TechDraw::DrawSVGTemplate", "Template")
        template.Template = os.path.join(
            App.getResourceDir(), "Mod", "TechDraw", "Templates", "ISO", "A3_Landscape_blank.svg"
        )
        page.Template = template
        annotation = self.doc.addObject("TechDraw::DrawViewAnnotation", "Annotation")
        annotation.Text = [name + " native print"]
        page.addView(annotation)
        annotation.X = 150
        annotation.Y = 150
        self.doc.recompute()
        if initialized:
            page.ViewObject.show()
            self._events()
        return page

    def _state(self, page):
        gui_doc = Gui.getDocument(self.doc.Name)
        preferences = App.ParamGet("User parameter:BaseApp/Preferences/Mod/TechDraw/View")
        return (
            gui_doc.Modified,
            page.ViewObject.Visibility,
            preferences.GetBool("ScreenMode", True),
            self.color_preferences.GetBool("LightOnDark", False),
            tuple(gui_doc.mdiViewsOfType("TechDrawGui::MDIViewPage")),
            Native.state(self.doc, page.Name),
        )

    def _assert_pdf(self, path, pages):
        data = path.read_bytes()
        self.assertTrue(data.startswith(b"%PDF-"))
        self.assertTrue(data.rstrip().endswith(b"%%EOF"))
        self.assertEqual(len(re.findall(rb"/Type\s*/Page\b", data)), pages)

    def test_batch_rejects_uninitialized_before_output(self):
        """Both batch devices preflight every page before starting output."""
        shown = self._page("Shown", initialized=True)
        fresh = self._page("Fresh")
        for mode in (0, 1):
            for existing in (False, True):
                with self.subTest(mode=mode, existing=existing):
                    output = Path(self.directory.name) / f"batch-{mode}-{existing}.pdf"
                    sentinel = b"Existing destination must survive.\n"
                    if existing:
                        output.write_bytes(sentinel)
                    state = [self._state(p) for p in (shown, fresh)]
                    with self.assertRaisesRegex(RuntimeError, "Page graphics are not initialized"):
                        Native.print_pages(self.doc, str(output), mode)
                    self.assertEqual([self._state(p) for p in (shown, fresh)], state)
                    if existing:
                        self.assertEqual(output.read_bytes(), sentinel)
                    else:
                        self.assertFalse(output.exists())

    def test_single_printer_rejects_uninitialized_before_output(self):
        page = self._page("Fresh")
        output = Path(self.directory.name) / "single.pdf"
        sentinel = b"Existing destination must survive.\n"
        output.write_bytes(sentinel)
        state = self._state(page)
        with self.assertRaisesRegex(RuntimeError, "Page graphics are not initialized"):
            Native.print_pages(self.doc, str(output), 2, page.Name)
        self.assertEqual(self._state(page), state)
        self.assertEqual(output.read_bytes(), sentinel)

    def test_empty_batch_does_not_open_output(self):
        for mode in (0, 1):
            with self.subTest(mode=mode):
                output = Path(self.directory.name) / f"empty-{mode}.pdf"
                with self.assertRaisesRegex(RuntimeError, "No drawing pages"):
                    Native.print_pages(self.doc, str(output), mode)
                self.assertFalse(output.exists())

    def test_initialized_inactive_and_tabless_batch(self):
        pages = [self._page("First", initialized=True), self._page("Second", initialized=True)]
        pages[0].ViewObject.hide()
        self._events()
        state = [self._state(p) for p in pages]
        for mode in (0, 1):
            with self.subTest(mode=mode):
                output = Path(self.directory.name) / f"valid-{mode}.pdf"
                Native.print_pages(self.doc, str(output), mode)
                self._assert_pdf(output, 2)
                self.assertEqual([self._state(p) for p in pages], state)

    def test_non_svg_graphics_template_common_interface(self):
        """Qualify the graphics interface, not unfinished parametric-page sizing."""
        page = self._page("GraphicsInterface", initialized=True)
        template = self.doc.addObject("TechDraw::DrawParametricTemplate", "ParametricGraphics")
        # Parametric DrawTemplate.getWidth/getHeight are currently unimplemented.
        # Keep a valid SVG-backed page and substitute only its real scene item to
        # exercise the printing helper's common QGITemplate virtual interface.
        Native.set_graphics_template(self.doc, page.Name, template.Name)
        self.assertIn("QGIDrawingTemplate", Native.state(self.doc, page.Name)[1])
        state = self._state(page)
        for mode in (0, 1, 2):
            with self.subTest(mode=mode):
                output = Path(self.directory.name) / f"non-svg-{mode}.pdf"
                Native.print_pages(self.doc, str(output), mode, page.Name)
                self._assert_pdf(output, 1)
                self.assertEqual(self._state(page), state)
        output = Path(self.directory.name) / "non-svg-api.pdf"
        TechDrawGui.exportPageAsPdf(page, str(output))
        self._assert_pdf(output, 1)

    def test_render_failure_restores_export_and_document_state(self):
        page = self._page("Fault", initialized=True)
        for exporting in (False, True):
            for modified in (False, True):
                with self.subTest(exporting=exporting, modified=modified):
                    Native.set_exporting(self.doc, page.Name, exporting)
                    Gui.getDocument(self.doc.Name).Modified = modified
                    state = self._state(page)
                    with self.assertRaisesRegex(RuntimeError, "Injected render failure"):
                        Native.print_pages(self.doc, "", 3, page.Name)
                    self.assertEqual(self._state(page), state)
        Native.set_exporting(self.doc, page.Name, False)

    def test_template_update_failure_restores_full_print_state(self):
        """An actual graphics-template update error unwinds the complete PDF path."""
        page = self._page("TemplateFault", initialized=True)
        self.doc.addObject("TechDraw::DrawParametricTemplate", "WrongGraphicsModel")
        for screen_mode in (False, True):
            for light_on_dark in (False, True):
                with self.subTest(screen_mode=screen_mode, light_on_dark=light_on_dark):
                    self.view_preferences.SetBool("ScreenMode", screen_mode)
                    self.color_preferences.SetBool("LightOnDark", light_on_dark)
                    Gui.getDocument(self.doc.Name).Modified = False
                    state = self._state(page)
                    output = Path(self.directory.name) / "template-update-fault.pdf"
                    with self.assertRaisesRegex(RuntimeError, "Template Feature not set"):
                        Native.print_pages(self.doc, str(output), 4, page.Name)
                    self.assertEqual(self._state(page), state)
                    recovered = Path(self.directory.name) / "after-template-update-fault.pdf"
                    TechDrawGui.exportPageAsPdf(page, str(recovered))
                    self._assert_pdf(recovered, 1)
                    self.assertEqual(self._state(page), state)

    def test_pdf_export_list_preflight_preserves_destination(self):
        pages = [self._page("Shown", initialized=True), self._page("Fresh")]
        output = Path(self.directory.name) / "list.pdf"
        sentinel = b"Existing destination must survive.\n"
        output.write_bytes(sentinel)
        state = [self._state(p) for p in pages]
        with self.assertRaisesRegex(RuntimeError, "Page graphics are not initialized"):
            TechDrawGui.export(pages, str(output))
        self.assertEqual(output.read_bytes(), sentinel)
        self.assertEqual([self._state(p) for p in pages], state)

    def test_valid_pdf_export_list_keeps_last_page_semantics(self):
        pages = [self._page("First", initialized=True), self._page("Last", initialized=True)]
        pages[1].Template.Template = os.path.join(
            App.getResourceDir(), "Mod", "TechDraw", "Templates", "ISO", "A4_Portrait_blank.svg"
        )
        self.doc.recompute()
        self._events()
        state = [self._state(p) for p in pages]
        output = Path(self.directory.name) / "valid-list.pdf"
        TechDrawGui.export(pages, str(output))
        self._assert_pdf(output, 1)
        # The existing API writes selected pages sequentially to the same path,
        # leaving only the final page. Preflight must not turn it into a batch.
        media_box = re.search(rb"/MediaBox\s*\[([^]]+)\]", output.read_bytes())
        self.assertIsNotNone(media_box)
        dimensions = [float(value) for value in media_box.group(1).split()]
        self.assertAlmostEqual(dimensions[2], 210 * 72 / 25.4, delta=1)
        self.assertAlmostEqual(dimensions[3], 297 * 72 / 25.4, delta=1)
        self.assertEqual([self._state(p) for p in pages], state)
