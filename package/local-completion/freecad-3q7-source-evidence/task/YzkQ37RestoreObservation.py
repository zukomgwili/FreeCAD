"""Read-only cold native snapshot observation; no export or model repair."""
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest

import FreeCAD as App

QA = Path('/private/tmp/freecad-3q7-Pq3Byy/large-qa')
sys.path.insert(0, str(QA))
from Q37LargeProfile import canonical, mesh_snapshot, pins
from large_config import WITNESS


class RestoreObservation(unittest.TestCase):
    def test_literal_mesh_snapshot_components(self):
        run = Path(os.environ['YZK_OUTPUT'])
        saved = Path(WITNESS) / 'coupled-before-export.FCStd'
        before = pins()
        document = None
        report = {'passed': False, 'no_export_save_recompute_mesher_or_solver': True,
                  'inputs_before': before}
        try:
            document = App.openDocument(str(saved))
            mesh, analysis = document.getObject('Mesh'), document.getObject('Analysis')
            first = mesh_snapshot(mesh, analysis)
            second = mesh_snapshot(mesh, analysis)
            self.assertTrue(first == second, 'Immediate unchanged snapshots differ')
            output = run / 'literal-mesh-snapshot.json'
            with output.open('x') as handle:
                json.dump(first, handle, sort_keys=True, allow_nan=False, separators=(',', ':'))
                handle.write('\n')
            report.update(passed=True, document_name=document.Name,
                canonical_snapshot_sha256=canonical(first),
                component_sha256={name: canonical(value) for name, value in first.items()},
                output={'path': str(output), 'bytes': output.stat().st_size,
                        'sha256': hashlib.sha256(output.read_bytes()).hexdigest()},
                counts={'nodes': len(first['nodes']),
                        'all_elements': len(first['ordered_all_element_ids']),
                        'volume_elements': len(first['volume_connectivity']),
                        'groups': len(first['groups'])})
        finally:
            if document is not None and document.Name in App.listDocuments():
                App.closeDocument(document.Name)
            report['inputs_after'] = pins()
            report['inputs_unchanged'] = before == report['inputs_after']
            report['passed'] &= report['inputs_unchanged']
            with (run / 'restore-observation.json').open('x') as handle:
                json.dump(report, handle, indent=2)
                handle.write('\n')
        self.assertTrue(report['passed'])
