"""Existing writer, input-identity and output-custody regressions for 9ii."""
import unittest

MODULES = (
    'femtest.app.test_ccxtools',
    'femtest.app.test_force_accounting',
    'femtest.app.test_mesh_quality',
    'femtest.app.test_contact_observation',
    'femtest.app.test_contact_observation_source',
    'femtest.app.test_movement_provenance',
    'femtest.app.test_geometry_signature',
    'femtest.app.test_reference_groups',
)


def load_tests(loader, tests, pattern):
    return loader.loadTestsFromNames(MODULES)
