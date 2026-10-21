"""Observe installed stock Contact authoring and writer, without deck edits."""
import hashlib
import json
import os
from pathlib import Path
import re
import unittest

import FreeCAD as App
import ObjectsFem
from femexamples.constraint_contact_solid_solid import setup
from femtools.ccxtools import FemToolsCcx


class StockContactBaseline(unittest.TestCase):
    def test_installed_stock_contact_output_coverage(self):
        output = Path(os.environ['F9II_BASELINE'])
        doc = setup()
        try:
            analysis = doc.getObject('Analysis')
            solver = doc.getObject('CalculiXCcxTools')
            contact = doc.getObject('Contact')
            self.assertIsNotNone(analysis)
            fea = FemToolsCcx(analysis=analysis, solver=solver, test_mode=True)
            fea.update_objects()
            fea.setup_working_dir(str(output))
            prerequisites = fea.check_prerequisites()
            self.assertFalse(prerequisites, prerequisites)
            error = fea.write_inp_file()
            self.assertFalse(error, error)
            decks = list(output.glob('*.inp'))
            self.assertEqual(len(decks), 1)
            deck = decks[0].read_text()
            requests = re.findall(r'^\*CONTACT (?:PRINT|FILE|OUTPUT)[^\n]*\n[^\n]*', deck, re.M)
            receipt = {
                'schema': 'FreeCAD-9ii-installed-stock-writer-baseline-v1',
                'version': App.Version(), 'module': getattr(App, '__file__', None),
                'objects_fem': ObjectsFem.__file__,
                'contact_type': contact.TypeId,
                'contact_properties': sorted(contact.PropertiesList),
                'solver_properties': sorted(solver.PropertiesList),
                'mesh_nodes': fea.mesh.FemMesh.NodeCount,
                'mesh_volumes': fea.mesh.FemMesh.VolumeCount,
                'native_contact_requests': requests,
                'deck': str(decks[0]),
                'deck_sha256': hashlib.sha256(decks[0].read_bytes()).hexdigest(),
                'local_cdis_cstr_requested': bool(re.search(r'(?m)^\s*(?:CDIS|CSTR)(?:\s*,|\s*$)', deck)),
                'result_factories': sorted(name for name in dir(ObjectsFem) if name.startswith('makeResult')),
                'scope': 'Stock writer only; no solve, import, GUI reproduction or engineering acceptance.',
            }
            (output / 'baseline.json').write_text(json.dumps(receipt, indent=2) + '\n')
            self.assertTrue(requests, 'Expected ordinary contact output request')
        finally:
            App.closeDocument(doc.Name)
