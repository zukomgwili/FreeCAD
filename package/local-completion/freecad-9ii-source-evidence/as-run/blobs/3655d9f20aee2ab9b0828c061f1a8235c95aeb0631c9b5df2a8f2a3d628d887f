"""DEBUG-9ii-link-fingerprint: diagnose a harness expectation, not a feature pass."""
import json
from pathlib import Path
import sys
import unittest
from femtest.app import test_input_fingerprint
from femtools import force_accounting


class LinkFingerprintProbe(unittest.TestCase):
    def test_capture_native_retarget_state(self):
        snapshots = []
        def profile(frame, event, value):
            if event == 'return' and frame.f_code is force_accounting._model_digest.__code__:
                snapshots.append({'digest': value, 'state': frame.f_locals['state']})
        case = test_input_fingerprint.TestInputFingerprint('test_contact_model_admits_local_nested_link_but_refuses_external_target')
        case.setUp()
        prior = sys.getprofile()
        sys.setprofile(profile)
        try:
            with self.assertRaises(AssertionError):
                case.test_contact_model_admits_local_nested_link_but_refuses_external_target()
        finally:
            sys.setprofile(prior)
            case.tearDown()
            case.doCleanups()
        self.assertGreaterEqual(len(snapshots), 2)
        Path(__file__).with_suffix('.states.json').write_text(json.dumps(snapshots, indent=2) + '\n')
        print('[DEBUG-9ii-LINK]', [row['digest'] for row in snapshots])
