import sys
sys.dont_write_bytecode = True
import json
import os
from pathlib import Path
import unittest
import FreeCAD as App
from femexamples.constraint_selfweight_cantilever import setup
from femtools.ccxtools import FemToolsCcx

class Probe(unittest.TestCase):
    def test_stock_route_exposes_independent_gravity_history(self):
        doc = App.newDocument('E4kReproducer')
        try:
            setup(doc=doc, test_mode=True)
            solver, weight = doc.CalculiXCcxTools, doc.Gravity
            out = Path(os.environ['E4K_RUN'])
            fea = FemToolsCcx(doc.Analysis, solver, test_mode=True)
            fea.update_objects()
            fea.setup_working_dir(str(out))
            self.assertFalse(fea.write_inp_file())
            deck = Path(fea.inp_file_name).read_text()
            controls = {obj.Name: list(obj.PropertiesList) for obj in (solver, weight)}
            keywords = [line for line in deck.splitlines() if line.upper().startswith(('*STEP', '*DLOAD', '*AMPLITUDE')) or ',GRAV,' in line.replace(' ', '').upper()]
            result = {'version': App.Version(), 'controls': controls, 'stock_keywords': keywords, 'input_file': fea.inp_file_name, 'module_origin': __import__('femtools.ccxtools', fromlist=['x']).__file__}
            (out / 'baseline.json').write_text(json.dumps(result, indent=2))
            print('E4K_BASELINE', json.dumps(result))
            route = any('amplitude' in prop.lower() for obj in (solver, weight) for prop in obj.PropertiesList)
            self.assertTrue(route, 'Neither native self-weight amplitude nor native static-step amplitude control is exposed')
        finally:
            App.closeDocument(doc.Name)

def suite():
    return unittest.defaultTestLoader.loadTestsFromTestCase(Probe)
