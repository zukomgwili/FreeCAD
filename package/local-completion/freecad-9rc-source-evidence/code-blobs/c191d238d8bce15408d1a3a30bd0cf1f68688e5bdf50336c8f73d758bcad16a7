"""Run only the first analytical compression slice."""
from femtest.app import test_beam_contact_native

def load_tests(loader, tests, pattern):
    return loader.loadTestsFromName(
        'TestBeamContactNative.test_frictionless_compression_keeps_beam_contact_and_solid_owners_in_one_case',
        test_beam_contact_native)
