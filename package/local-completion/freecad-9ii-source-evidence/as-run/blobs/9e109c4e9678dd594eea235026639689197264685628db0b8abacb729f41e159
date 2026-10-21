"""Separate-process raw-label persistence witness; never solve or repair history."""
import hashlib
import json
from pathlib import Path
import unittest
from xml.etree import ElementTree
import zipfile

import FreeCAD as App

SOURCE = Path('/private/tmp/freecad-9ii-T61k55sb/safety-green-r01/tmp/freecad-contact-state-native-lr4amy1_/native-contact-state.FCStd')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class ColdContactWitness(unittest.TestCase):
    def test_historical_raw_labels_never_promote_onto_restored_mesh(self):
        with zipfile.ZipFile(SOURCE) as archive:
            tree = ElementTree.fromstring(archive.read('Document.xml'))
        saved = tree.find('./ObjectData/Object[@name="NativeContactOutput"]')
        literal = saved.find('./Properties/Property[@name="ContactData"]/String').get('value')
        expected = saved.find('./Properties/Property[@name="ContactHash"]/String').get('value')
        self.assertEqual(hashlib.sha256(literal.encode()).hexdigest(), expected)
        data = json.loads(literal)
        source = data['provenance']
        files = [SOURCE, *[Path(source[name]) for name in ('deck', 'request_path', 'binary', 'output')],
                 Path(source['run']['path'])]
        before = {str(path): sha(path) for path in files}
        self.assertEqual(before[source['output']], source['output_sha256'])
        doc = App.openDocument(str(SOURCE))
        try:
            result = doc.getObject('NativeContactOutput')
            self.assertEqual(result.ContactData, literal)
            self.assertEqual(result.ContactHash, expected)
            self.assertTrue(result.Status.startswith('Historical'), result.Status)
            initial = result.Status
            with self.assertRaises(ValueError):
                result.Proxy.getContactStates(result)
            result.Proxy.refresh(result)
            with self.assertRaises(ValueError):
                result.Proxy.getContactStates(result)
            self.assertTrue(result.Status.startswith('Unavailable'), result.Status)
            self.assertEqual(result.ContactData, literal)
            self.assertEqual(result.ContactHash, expected)
            report = {'meaning': 'Cold historical raw IDs, not new native solve or design acceptance',
                      'source': str(SOURCE), 'source_sha256': before[str(SOURCE)],
                      'saved_data_sha256': expected, 'initial_status': initial,
                      'explicit_refresh_status': result.Status, 'frames': len(data['frames']),
                      'samples': len(data['frames'][-1]['samples']), 'files_before': before}
        finally:
            App.closeDocument(doc.Name)
        after = {str(path): sha(path) for path in files}
        self.assertEqual(before, after)
        report['files_after'] = after
        Path(__file__).with_suffix('.witness.json').write_text(json.dumps(report, indent=2) + '\n')
        print('[9ii-COLD-WITNESS]', json.dumps(report, sort_keys=True))
