# SPDX-License-Identifier: LGPL-2.1-or-later
"""Signed beam resultants through native authoring, export and result interfaces."""

import tempfile
import unittest
from pathlib import Path

import FreeCAD as App
from femexamples.ccx_cantilever_base_edge import setup_cantilever_base_edge
from femtools.ccxtools import FemToolsCcx


class TestBeamSectionForces(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="freecad-beam-resultants-")
        self.doc = App.newDocument("BeamSectionForces")
        setup_cantilever_base_edge(self.doc)
        self.analysis = self.doc.Analysis
        self.solver = self.doc.CalculiXCcxTools

    def tearDown(self):
        App.closeDocument(self.doc.Name)
        self.directory.cleanup()

    def test_native_request_exports_section_forces_in_original_beam_nodes(self):
        self.assertIn("BeamSectionForces", self.solver.PropertiesList)
        self.solver.BeamSectionForces = True
        self.solver.Output3d = False
        fea = FemToolsCcx(analysis=self.analysis, solver=self.solver)
        fea.update_objects()
        fea.setup_working_dir(self.directory.name)
        self.assertFalse(fea.check_prerequisites())
        self.assertFalse(fea.write_inp_file())
        text = Path(fea.inp_file_name).read_text().upper()
        self.assertIn("*ELEMENT, TYPE=B32R", text)
        self.assertIn("*NODE FILE, OUTPUT=2D", text)
        self.assertIn("*EL FILE, OUTPUT=2D, SECTION FORCES\nS, NOE", text)
