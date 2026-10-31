"""Stock native beam workflow tracer, before affected implementation inspection."""
import sys
sys.dont_write_bytecode = True
import hashlib
import json
import os
from pathlib import Path
import unittest

import FreeCAD as App
from femexamples.ccx_cantilever_base_edge import setup_cantilever_base_edge
from femtools.ccxtools import FemToolsCcx


class Beam960Baseline(unittest.TestCase):
    def test_native_solver_can_request_beam_section_forces(self):
        root = Path(os.environ['B960_RUN_DIR'])
        doc = App.newDocument('Beam960StockBaseline')
        try:
            setup_cantilever_base_edge(doc)
            solver = doc.CalculiXCcxTools
            fea = FemToolsCcx(analysis=doc.Analysis, solver=solver)
            fea.update_objects()
            default = root / 'stock-default'
            default.mkdir()
            fea.setup_working_dir(str(default))
            self.assertFalse(fea.check_prerequisites())
            self.assertFalse(fea.write_inp_file())
            deck = Path(fea.inp_file_name)
            text = deck.read_text()
            report = {
                'schema': 'FreeCAD-960-stock-baseline-v1', 'runtime': App.Version(),
                'GuiUp': bool(App.GuiUp), 'home_path': App.getHomePath(),
                'solver_properties': list(solver.PropertiesList),
                'deck': str(deck), 'deck_sha256': hashlib.sha256(deck.read_bytes()).hexdigest(),
                'native_element_cards': [line for line in text.splitlines()
                                         if line.upper().startswith('*ELEMENT')],
                'native_output_cards': [line for line in text.splitlines()
                                        if line.upper().startswith(('*EL FILE', '*NODE FILE'))],
                'section_forces_written': 'SECTION FORCES' in text.upper(),
                'no_deck_edits': True, 'no_mesh_or_solve': True,
                'Oomakhi_opened_or_mutated': False,
            }
            (root / 'baseline.json').write_text(json.dumps(report, indent=2) + '\n')
            print('[BEAM960-STOCK-BASELINE]', json.dumps(report, sort_keys=True), flush=True)
            self.assertIn('BeamSectionForces', solver.PropertiesList,
                          'Stock solver offers no native beam-section output request')
        finally:
            App.closeDocument(doc.Name)


def load_tests(loader, _tests, _pattern):
    return loader.loadTestsFromTestCase(Beam960Baseline)
