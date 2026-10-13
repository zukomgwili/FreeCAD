# SPDX-License-Identifier: LGPL-2.1-or-later

"""Regression tests for the native TechDraw PDF export API."""

import os
from pathlib import Path
import tempfile
import unittest

import FreeCAD as App

if App.GuiUp:
    import FreeCADGui as Gui
    import TechDrawGui
    from PySide import QtCore


@unittest.skipUnless(App.GuiUp, "PDF export requires the native GUI")
class DrawPageExportTest(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("TDPdfExport")
        self.directory = tempfile.TemporaryDirectory()

    @staticmethod
    def _process_events():
        Gui.updateGui()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        Gui.updateGui()

    def tearDown(self):
        App.closeDocument(self.doc.Name)
        self._process_events()
        self.directory.cleanup()

    def _page(self, name, text=None):
        page = self.doc.addObject("TechDraw::DrawPage", name)
        template = self.doc.addObject("TechDraw::DrawSVGTemplate", "Template")
        template.Template = os.path.join(
            App.getResourceDir(), "Mod", "TechDraw", "Templates", "ISO", "A3_Landscape_blank.svg"
        )
        page.Template = template
        if text:
            annotation = self.doc.addObject("TechDraw::DrawViewAnnotation", "Annotation")
            annotation.Text = [text]
            page.addView(annotation)
            annotation.X = 150
            annotation.Y = 150
        self.doc.recompute()
        return page

    def _assert_rejected_without_state_change(self, page, output):
        gui_doc = Gui.getDocument(self.doc.Name)
        modified = gui_doc.Modified
        visibility = page.ViewObject.Visibility
        preferences = App.ParamGet("User parameter:BaseApp/Preferences/Mod/TechDraw/View")
        screen_mode = preferences.GetBool("ScreenMode", True)
        self.assertEqual(gui_doc.mdiViewsOfType("TechDrawGui::MDIViewPage"), [])
        with self.assertRaisesRegex(RuntimeError, "Page graphics are not initialized"):
            TechDrawGui.exportPageAsPdf(page, str(output))
        self.assertEqual(gui_doc.Modified, modified)
        self.assertEqual(page.ViewObject.Visibility, visibility)
        self.assertEqual(preferences.GetBool("ScreenMode", True), screen_mode)
        self.assertEqual(gui_doc.mdiViewsOfType("TechDrawGui::MDIViewPage"), [])

    def _assert_pdf(self, page, output):
        TechDrawGui.exportPageAsPdf(page, str(output))
        data = output.read_bytes()
        self.assertTrue(data.startswith(b"%PDF-"))
        self.assertTrue(data.rstrip().endswith(b"%%EOF"))
        # QPdfWriter uses the requested page name as its UTF-16 PDF title.
        # This catches an accidental export of the foreground page instead.
        self.assertIn(b"/Title (\xfe\xff" + page.Name.encode("utf-16-be") + b")", data)
        self._process_events()

    def test_uninitialized_pdf_does_not_create_output(self):
        """Reject missing page graphics before opening the PDF destination."""
        page = self._page("Unshown")
        output = Path(self.directory.name) / "unshown.pdf"
        self._assert_rejected_without_state_change(page, output)
        self.assertFalse(output.exists())

    def test_uninitialized_pdf_preserves_existing_output(self):
        """An invalid export must not truncate an existing destination."""
        page = self._page("Unshown")
        output = Path(self.directory.name) / "existing.pdf"
        sentinel = b"Preserve this existing destination.\n"
        output.write_bytes(sentinel)
        self._assert_rejected_without_state_change(page, output)
        self.assertEqual(output.read_bytes(), sentinel)

    def test_initialized_pdf_from_inactive_page(self):
        """Export the requested page while another page is foreground."""
        target = self._page("ExportTarget", "Intended PDF page")
        target.ViewObject.show()
        self._process_events()
        other = self._page("OtherPage", "Other foreground page")
        other.ViewObject.show()
        self._process_events()
        self.assertEqual(
            len(Gui.getDocument(self.doc.Name).mdiViewsOfType("TechDrawGui::MDIViewPage")), 2
        )
        self._assert_pdf(target, Path(self.directory.name) / "inactive.pdf")

    def test_initialized_pdf_without_tab(self):
        """An initialized scene remains exportable after its page tab closes."""
        page = self._page("Initialized", "Initialized PDF page")
        page.ViewObject.show()
        self._process_events()
        page.ViewObject.hide()
        self._process_events()
        self.assertEqual(
            Gui.getDocument(self.doc.Name).mdiViewsOfType("TechDrawGui::MDIViewPage"), []
        )
        self._assert_pdf(page, Path(self.directory.name) / "closed-tab.pdf")
