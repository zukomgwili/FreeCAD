"""Select exactly the eleven permanent 3q7 native guard regressions."""
import unittest

SELECTORS = [
    "femtest.app.test_rigid_region_ownership.TestRigidRegionOwnership.test_rbe_batch_reference_mutation_preserves_previous_rows",
    "femtest.app.test_rigid_region_ownership.TestRigidRegionOwnership.test_rbe_batch_provenance_mutation_preserves_previous_rows",
    "femtest.app.test_rigid_region_ownership.TestRigidRegionOwnership.test_rbe_batch_same_id_node_motion_preserves_previous_rows",
    "femtest.app.test_rigid_region_ownership.TestRigidRegionOwnership.test_rbe_batch_same_id_group_rename_preserves_previous_rows",
    "femtest.app.test_rigid_region_ownership.TestRigidRegionOwnership.test_rbe_batch_same_id_connectivity_change_preserves_previous_rows",
    "femtest.app.test_rigid_region_ownership.TestRigidRegionOwnership.test_owned_port_resolution_preserves_independent_mutable_regions",
    "femtest.app.test_rigid_region_ownership.TestRigidRegionOwnership.test_owned_pure_beam_keeps_generic_rbe_getter_and_preflight",
    "femtest.app.test_rigid_region_ownership.TestRigidRegionOwnership.test_owned_pure_shell_keeps_generic_rbe_getter_and_preflight",
    "femtest.app.test_moving_port_accounting_native.TestMovingPortAccountingNative.test_body_reference_changed_during_request_is_not_published",
    "femtest.app.test_moving_port_accounting_native.TestMovingPortAccountingNative.test_provenance_changed_during_request_is_not_published",
    "femtest.app.test_elastic_connector.TestRigidPortConnector.test_legacy_classifier_fences_same_id_native_coordinate_mutation"
]


def load_tests(loader, _standard_tests, _pattern):
    return unittest.TestSuite(loader.loadTestsFromName(name) for name in SELECTORS)

