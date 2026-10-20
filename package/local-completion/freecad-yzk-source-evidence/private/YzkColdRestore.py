# SPDX-License-Identifier: LGPL-2.1-or-later
"""Separate-process literal cold restore; no solve, save or provenance repair."""
import hashlib
import json
import os
from pathlib import Path
import unittest

import FreeCAD as App
from YzkCoupledFixture import FROZEN, ROOT, plain, sha, write_json


class CoupledColdRestore(unittest.TestCase):
    def test_saved_full_graph_remains_literal_historical_data(self):
        source = Path(os.environ['YZK_COLD_MANIFEST'])
        output = Path(os.environ['YZK_OUTPUT']) / 'cold-receipt.json'
        expected = json.loads(source.read_text())
        receipt = {'schema': 'FreeCAD-yzk-coupled-cold-receipt-v1', 'passed': False,
            'manifest': str(source), 'manifest_sha256': sha(source),
            'no_native_solve': True, 'no_save': True, 'no_history_or_provenance_repair': True}
        doc = None
        try:
            self.assertEqual(expected['schema'], 'FreeCAD-yzk-coupled-cold-case-v1')
            self.assertEqual(expected['frozen_oracle_sha256'], FROZEN)
            for name, wanted in FROZEN.items():
                self.assertEqual(sha(ROOT / 'oracle' / name), wanted)
            saved = Path(expected['document'])
            self.assertEqual(sha(saved), expected['document_sha256'])
            for proof in expected['source_files'].values():
                self.assertEqual(sha(proof['path']), proof['sha256'])
            doc = App.openDocument(str(saved))
            report = doc.getObject(expected['report_name'])
            self.assertTrue(report.Status.startswith('Stale after restore'), report.Status)
            self.assertEqual(report.AccountingData, expected['accounting_data_literal'])
            self.assertEqual(plain(list(report.Resultants)), expected['resultants_literal'])
            self.assertEqual(json.loads(report.AccountingData)['movement_source'], expected['movement_source_literal'])
            solver = doc.getObject(expected['solver_name'])
            self.assertEqual([obj.Name for obj in solver.NativeAccountingSupports], expected['explicit_supports'])
            previous_names = set()

            def local(value, restored):
                if isinstance(value, dict):
                    if set(value) == {'object', 'document'}:
                        if restored:
                            self.assertEqual(value['document'], doc.Name)
                            self.assertIsNotNone(doc.getObject(value['object']))
                        else:
                            previous_names.add(value['document'])
                        return {'object': value['object'], 'document': '<owning document>'}
                    return {key: local(item, restored) for key, item in value.items()}
                if isinstance(value, list):
                    return [local(item, restored) for item in value]
                return value

            for name, references in expected['saved_references'].items():
                self.assertEqual(local(plain(doc.getObject(name).References), True), local(references, False))
            for name, item in expected['saved_native_properties'].items():
                obj = doc.getObject(name)
                self.assertEqual(obj.TypeId, item['type'])
                for prop, row in item['properties'].items():
                    self.assertEqual(obj.getTypeIdOfProperty(prop), row['type'])
                    self.assertEqual(local(plain(getattr(obj, prop)), True), local(row['value'], False), (name, prop))
            self.assertEqual(len(previous_names), 1)
            doc.recompute()
            self.assertTrue(report.Status.startswith('Stale'), report.Status)
            self.assertEqual(report.AccountingData, expected['accounting_data_literal'])
            self.assertEqual(plain(list(report.Resultants)), expected['resultants_literal'])
            self.assertEqual(json.loads(report.AccountingData)['movement_source'], expected['movement_source_literal'])
            self.assertEqual(sha(saved), expected['document_sha256'])
            for proof in expected['source_files'].values():
                self.assertEqual(sha(proof['path']), proof['sha256'])
            receipt.update(passed=True, status=report.Status,
                supports=[obj.Name for obj in solver.NativeAccountingSupports],
                accounting_data_sha256=hashlib.sha256(report.AccountingData.encode()).hexdigest(),
                session_document_name_mapping={'saved_session': next(iter(previous_names)), 'cold_session': doc.Name})
        finally:
            if doc is not None and doc.Name in App.listDocuments():
                App.closeDocument(doc.Name)
            write_json(output, receipt)
