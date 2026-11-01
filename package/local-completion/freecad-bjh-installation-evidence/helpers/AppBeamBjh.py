"""Literal installed identity and unskipped shipped native V1--V5 beam suites."""

import sys

sys.dont_write_bytecode = True

import ctypes
import hashlib
import importlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import FreeCAD as App

REPO = Path("/Users/zukomgwili/src/FreeCAD")
APP = Path(os.environ["IBJH_APP"])
RESOURCES = APP / "Contents/Resources"
IDENTITY_PATH = Path(os.environ["IBJH_IDENTITY"])
IDENTITY_BYTES = IDENTITY_PATH.read_bytes()
IDENTITY = json.loads(IDENTITY_BYTES)
MODE = os.environ["IBJH_MODE"]
WORK = Path(os.environ["B960_WITNESS_ROOT"])
RESULTS = {}
NATIVE_SHA = "b6a356e8635a35cef2621db7bd80145566dc1f671683edb405ab927cb415b353"
COMMON = {
    "femobjects.solver_ccxtools": "femobjects/solver_ccxtools.py",
    "femtools.beam_network_coupling": "femtools/beam_network_coupling.py",
    "femtools.beam_contact_coupling": "femtools/beam_contact_coupling.py",
    "femtools.beam_contact_results": "femtools/beam_contact_results.py",
    "femtools.contact_state": "femtools/contact_state.py",
    "femtools.beam_coupling": "femtools/beam_coupling.py",
    "femtools.beam_solid_coupling": "femtools/beam_solid_coupling.py",
    "femtools.beam_solid_results": "femtools/beam_solid_results.py",
    "femtools.elastic_connector": "femtools/elastic_connector.py",
    "femobjects.constraint_elastic_connector": "femobjects/constraint_elastic_connector.py",
    "femtools.beam_section_forces": "femtools/beam_section_forces.py",
    "femtools.ccxtools": "femtools/ccxtools.py",
    "femtools.force_accounting": "femtools/force_accounting.py",
    "feminout.importCcxFrdResults": "feminout/importCcxFrdResults.py",
    "femsolver.calculix.write_step_output": "femsolver/calculix/write_step_output.py",
    "femsolver.calculix.write_constraint_elastic_connector": "femsolver/calculix/write_constraint_elastic_connector.py",
    "femsolver.calculix.write_constraint_contact": "femsolver/calculix/write_constraint_contact.py",
    "femsolver.calculix.writer": "femsolver/calculix/writer.py",
}
CMD_MODULES = (
    "femtest.app.test_beam_section_forces",
    "femtest.app.test_beam_section_forces_native",
    "femtest.app.test_beam_section_forces_lifecycle",
    "femtest.app.test_beam_section_forces_safety",
    "femtest.app.test_beam_coupling_native",
    "femtest.app.test_beam_solid_coupling_native",
    "femtest.app.test_beam_contact_native",
    "femtest.app.test_beam_contact_lifecycle",
    "femtest.app.test_beam_contact_rejections",
    "femtest.app.test_beam_network_native",
    "femtest.app.test_beam_network_fork",
    "femtest.app.test_beam_network_integrity",
)
GUI_MODULES = (
    "femtest.gui.test_beam_section_forces",
    "femtest.gui.test_beam_coupling",
    "femtest.gui.test_beam_solid_coupling",
    "femtest.gui.test_beam_contact_coupling",
    "femtest.gui.test_beam_network_coupling",
)
EXPECTED_IDS = {
    "cmd": [
        "AppBeamBjh.AppBeamIdentity.test_exact_application_identity_native_origins_and_default_solver",
        "femtest.app.test_beam_contact_lifecycle.TestBeamContactLifecycle.test_deleting_either_companion_withdraws_the_surviving_literal",
        "femtest.app.test_beam_contact_lifecycle.TestBeamContactLifecycle.test_each_owned_source_withdraws_both_without_rewriting_history",
        "femtest.app.test_beam_contact_lifecycle.TestBeamContactLifecycle.test_getting_withdrawn_data_during_repeat_run_cannot_cancel_new_child",
        "femtest.app.test_beam_contact_lifecycle.TestBeamContactLifecycle.test_invalid_literal_or_hash_withdraws_its_companion",
        "femtest.app.test_beam_contact_lifecycle.TestBeamContactLifecycle.test_late_child_completion_cannot_withdraw_a_newer_owned_pair",
        "femtest.app.test_beam_contact_lifecycle.TestBeamContactLifecycle.test_native_prescriptions_and_child_frame_bindings_cannot_be_relabelled",
        "femtest.app.test_beam_contact_lifecycle.TestBeamContactLifecycle.test_new_export_withdraws_both_before_a_failed_input_capture",
        "femtest.app.test_beam_contact_lifecycle.TestBeamContactLifecycle.test_observers_preserve_the_ordinary_native_fields_on_the_same_stock_deck",
        "femtest.app.test_beam_contact_lifecycle.TestBeamContactLifecycle.test_partial_publication_keeps_no_single_current_observation",
        "femtest.app.test_beam_contact_lifecycle.TestBeamContactLifecycle.test_physical_edits_and_detached_links_withdraw_both",
        "femtest.app.test_beam_contact_lifecycle.TestBeamContactLifecycle.test_save_reopen_preserves_both_literals_as_historical",
        "femtest.app.test_beam_contact_native.TestBeamContactNative.test_beam_edge_cannot_become_a_solid_contact_side",
        "femtest.app.test_beam_contact_native.TestBeamContactNative.test_explicit_contact_face_reversal_is_refused_before_native_run",
        "femtest.app.test_beam_contact_native.TestBeamContactNative.test_force_controlled_opening_is_refused_before_native_run",
        "femtest.app.test_beam_contact_native.TestBeamContactNative.test_frictionless_compression_keeps_beam_contact_and_solid_owners_in_one_case",
        "femtest.app.test_beam_contact_native.TestBeamContactNative.test_malformed_contact_face_count_is_refused_before_native_run",
        "femtest.app.test_beam_contact_native.TestBeamContactNative.test_multiple_active_contacts_are_refused_before_native_run",
        "femtest.app.test_beam_contact_native.TestBeamContactNative.test_selected_contact_must_be_the_active_contact",
        "femtest.app.test_beam_contact_native.TestBeamContactNative.test_zero_tangential_compression_reports_actual_native_stick",
        "femtest.app.test_beam_contact_rejections.TestBeamContactRejections.test_native_request_mismatches_cannot_authorize_beam_contact_composition",
        "femtest.app.test_beam_coupling_native.TestBeamCouplingNative.test_series_beam_ground_spring_and_restraints_share_one_owned_frame",
        "femtest.app.test_beam_coupling_native.TestBeamCouplingNative.test_stiffness_edit_withdraws_current_actions_and_preserves_literal_history",
        "femtest.app.test_beam_coupling_native.TestBeamCouplingNative.test_transverse_components_observe_nonzero_physical_rotation_reactions",
        "femtest.app.test_beam_coupling_native.TestBeamCouplingNative.test_unqualified_couplings_and_restraints_are_refused_before_export",
        "femtest.app.test_beam_network_fork.TestBeamNetworkFork.test_three_branches_keep_both_child_links_and_all_native_owners",
        "femtest.app.test_beam_network_integrity.TestBeamNetworkIntegrity.test_bare_network_frd_cannot_be_imported_as_mechanical_stress",
        "femtest.app.test_beam_network_integrity.TestBeamNetworkIntegrity.test_internal_spring_edit_preserves_literal_history_through_save_and_reopen",
        "femtest.app.test_beam_network_integrity.TestBeamNetworkIntegrity.test_nonlinear_export_retires_completion_and_preserves_chosen_setting_and_history",
        "femtest.app.test_beam_network_integrity.TestBeamNetworkIntegrity.test_owned_file_tampering_is_refused_and_never_resurrects_current_after_restoration",
        "femtest.app.test_beam_network_integrity.TestBeamNetworkIntegrity.test_physical_edits_and_detached_owners_withdraw_current_without_erasing_history",
        "femtest.app.test_beam_network_integrity.TestBeamNetworkIntegrity.test_rehashed_history_rejects_six_source_omissions_port_loss_and_knot_role_aliases",
        "femtest.app.test_beam_network_integrity.TestBeamNetworkIntegrity.test_unsupported_native_network_requests_are_refused_without_export_or_silent_changes",
        "femtest.app.test_beam_network_native.TestBeamNetworkNative.test_connected_branches_keep_two_materials_and_both_active_spring_ports",
        "femtest.app.test_beam_network_native.TestBeamNetworkNative.test_grounded_branch_keeps_sources_member_ends_and_physical_supports_distinct",
        "femtest.app.test_beam_section_forces.TestBeamSectionForces.test_native_request_exports_section_forces_in_original_beam_nodes",
        "femtest.app.test_beam_section_forces.TestBeamSectionForcesNative.test_axial_member_ends_have_native_identity_units_and_signed_actions",
        "femtest.app.test_beam_section_forces_lifecycle.TestBeamSectionForcesLifecycle.test_altered_export_metadata_is_refused_before_native_solve",
        "femtest.app.test_beam_section_forces_lifecycle.TestBeamSectionForcesLifecycle.test_bare_copied_beam_frd_cannot_be_imported_as_stress",
        "femtest.app.test_beam_section_forces_lifecycle.TestBeamSectionForcesLifecycle.test_physical_load_change_withdraws_current_but_preserves_saved_history",
        "femtest.app.test_beam_section_forces_lifecycle.TestBeamSectionForcesLifecycle.test_preexisting_frd_alias_is_refused_without_changing_its_target",
        "femtest.app.test_beam_section_forces_lifecycle.TestBeamSectionForcesLifecycle.test_unsupported_solver_settings_are_refused_without_silent_changes",
        "femtest.app.test_beam_section_forces_lifecycle.TestBeamSectionForcesLifecycle.test_warm_rerun_keeps_export_and_preserves_previous_native_output",
        "femtest.app.test_beam_section_forces_native.TestBeamSectionForcesNative.test_axial_compression_root_reverses_the_global_end_action",
        "femtest.app.test_beam_section_forces_native.TestBeamSectionForcesNative.test_axial_tension_root_has_negative_global_end_action",
        "femtest.app.test_beam_section_forces_native.TestBeamSectionForcesNative.test_rotated_translated_torsion_preserves_global_actions_and_native_end_axes",
        "femtest.app.test_beam_section_forces_native.TestBeamSectionForcesNative.test_torsion_couple_preserves_distinct_native_ends_at_a_shared_joint",
        "femtest.app.test_beam_section_forces_native.TestBeamSectionForcesNative.test_transverse_y_root_has_signed_shear_and_bending_equilibrium",
        "femtest.app.test_beam_section_forces_native.TestBeamSectionForcesNative.test_transverse_z_root_has_signed_shear_and_orthogonal_bending_equilibrium",
        "femtest.app.test_beam_section_forces_safety.TestBeamSectionForcesSafety.test_comment_about_section_forces_is_not_a_resultant_output_request",
        "femtest.app.test_beam_section_forces_safety.TestBeamSectionForcesSafety.test_disabling_and_rewriting_does_not_relabel_old_beam_frd_as_stress",
        "femtest.app.test_beam_section_forces_safety.TestBeamSectionForcesSafety.test_relative_solver_selection_is_not_accepted_for_native_beam_output",
        "femtest.app.test_beam_section_forces_safety.TestBeamSectionForcesSafety.test_saved_earlier_frame_cannot_follow_the_requested_final_time",
        "femtest.app.test_beam_section_forces_safety.TestBeamSectionForcesSafety.test_saved_local_channel_must_match_its_retained_native_wrench_projection",
        "femtest.app.test_beam_solid_coupling_native.TestBeamSolidCouplingNative.test_changed_frd_custody_withdraws_current_before_result_partition",
        "femtest.app.test_beam_solid_coupling_native.TestBeamSolidCouplingNative.test_contact_and_contact_output_requests_are_refused_before_export",
        "femtest.app.test_beam_solid_coupling_native.TestBeamSolidCouplingNative.test_hybrid_actions_solid_patch_and_native_beam_component_control",
        "femtest.app.test_beam_solid_coupling_native.TestBeamSolidCouplingNative.test_mixed_frd_needs_its_owned_v3_source_and_matching_analysis",
        "femtest.app.test_beam_solid_coupling_native.TestBeamSolidCouplingNative.test_moving_port_and_physical_support_ownership_are_not_interchangeable",
        "femtest.app.test_beam_solid_coupling_native.TestBeamSolidCouplingNative.test_saved_rigid_algebraic_terms_cannot_alias_beam_rotation_helpers",
        "femtest.app.test_beam_solid_coupling_native.TestBeamSolidCouplingNative.test_zero_period_is_refused_before_native_export",
    ],
    "gui": [
        "AppBeamBjh.AppBeamIdentity.test_exact_application_identity_native_origins_and_default_solver",
        "femtest.gui.test_beam_contact_coupling.TestBeamContactCouplingGui.test_contact_sides_and_physical_guide_withdraw_with_the_paired_observation",
        "femtest.gui.test_beam_coupling.TestBeamCouplingGui.test_inspector_shows_native_coupled_actions_and_withdraws_after_stiffness_edit",
        "femtest.gui.test_beam_network_coupling.TestBeamNetworkCouplingGui.test_connected_network_inspector_preserves_two_materials_and_both_internal_spring_ends",
        "femtest.gui.test_beam_network_coupling.TestBeamNetworkCouplingGui.test_network_inspector_preserves_owners_and_withdraws_every_typed_table",
        "femtest.gui.test_beam_section_forces.TestBeamSectionForcesGui.test_invalid_output_request_reports_error_and_clears_busy_cursor",
        "femtest.gui.test_beam_section_forces.TestBeamSectionForcesGui.test_stop_button_cancels_only_its_owned_beam_attempt",
        "femtest.gui.test_beam_section_forces.TestBeamSectionForcesGui.test_visible_solver_write_and_run_saves_current_native_beam_end_actions",
        "femtest.gui.test_beam_solid_coupling.TestBeamSolidCouplingGui.test_hybrid_inspector_keeps_internal_actions_and_solid_pipeline_separate",
    ],
}


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_report(name, data):
    with (WORK / name).open("x") as stream:
        json.dump(data, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def source_origins():
    """Reject any source/build overlay, even for transitively loaded modules."""
    forbidden = (REPO / "src", REPO / "build")
    for entry in sys.path:
        actual = Path(entry or os.getcwd()).resolve()
        assert not any(actual.is_relative_to(root) for root in forbidden), actual
    rows = {}
    for name, module in tuple(sys.modules.items()):
        origin = getattr(module, "__file__", None)
        if not origin:
            continue
        actual = Path(origin).resolve()
        assert not any(actual.is_relative_to(root) for root in forbidden), (name, actual)
        if (
            name.startswith(
                (
                    "femtools",
                    "femmesh",
                    "femresult",
                    "femobjects",
                    "feminout",
                    "femsolver",
                    "femtest",
                    "femtaskpanels",
                    "femviewprovider",
                )
            )
            or name == "ObjectsFem"
        ):
            assert actual.is_relative_to(RESOURCES / "Mod/Fem"), (name, actual)
            relative = actual.relative_to(RESOURCES / "Mod/Fem")
            source = REPO / "src/Mod/Fem" / relative
            assert source.is_file() and source.read_bytes() == actual.read_bytes(), name
            rows[name] = {"path": str(actual), "sha256": sha(actual)}
    return rows


def check_identity(test):
    test.assertEqual(IDENTITY["schema"], "FreeCAD-bjh-install-identity-v1")
    test.assertEqual(IDENTITY["commit"], "f87fabb9340177691d4bcea22f6014cab692bde7")
    test.assertEqual(IDENTITY["native_sha256"], NATIVE_SHA)
    test.assertEqual(IDENTITY["revision"], "49261 +245 (Git)")
    test.assertEqual(IDENTITY_PATH.read_bytes(), IDENTITY_BYTES)
    test.assertTrue(APP.is_absolute())
    test.assertEqual(APP.resolve(strict=True), APP)
    test.assertFalse(APP.is_symlink())
    test.assertEqual(Path(App.getHomePath()).resolve(strict=True), RESOURCES)
    test.assertEqual(Path(App.ConfigGet("AppHomePath")).resolve(strict=True), RESOURCES)
    runtime = App.Version()
    test.assertEqual(runtime[:3], ["27", "1", "0"])
    test.assertEqual(runtime[3], IDENTITY["revision"])
    test.assertEqual(runtime[-1], IDENTITY["commit"])
    test.assertEqual(bool(App.GuiUp), MODE == "gui")
    test.assertNotIn("B960_TEST_SOLVER", os.environ)
    test.assertNotIn("SV7_TEST_SOLVER", os.environ)
    test.assertNotIn("FREECAD_CONTACT_STATE_SOLVER", os.environ)
    for key in ("R9_TEST_SOLVER", "R9_BASELINE_SOLVER", "BJH_TEST_SOLVER"):
        test.assertNotIn(key, os.environ)
    test.assertFalse([key for key in os.environ if key.startswith("CCX_")])
    test.assertTrue(sys.dont_write_bytecode)
    for name, relative in COMMON.items():
        module = importlib.import_module(name)
        path = Path(module.__file__).resolve(strict=True)
        test.assertEqual(path, RESOURCES / "Mod/Fem" / relative)
        test.assertEqual(path.read_bytes(), (REPO / "src/Mod/Fem" / relative).read_bytes())
    if App.GuiUp:
        for name, relative in (
            ("femtaskpanels.task_solver_ccxtools", "femtaskpanels/task_solver_ccxtools.py"),
            (
                "femviewprovider.view_beam_section_forces",
                "femviewprovider/view_beam_section_forces.py",
            ),
        ):
            module = importlib.import_module(name)
            path = Path(module.__file__).resolve(strict=True)
            test.assertEqual(path, RESOURCES / "Mod/Fem" / relative)
            test.assertEqual(path.read_bytes(), (REPO / "src/Mod/Fem" / relative).read_bytes())

    modules = {"FreeCAD": App}
    modules.update({name: importlib.import_module(name) for name in ("Part", "Fem")})
    if App.GuiUp:
        modules.update({name: importlib.import_module(name) for name in ("FreeCADGui", "FemGui")})
    dyld = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
    dyld._NSGetExecutablePath.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    dyld._NSGetExecutablePath.restype = ctypes.c_int
    size = ctypes.c_uint32(4096)
    buffer = ctypes.create_string_buffer(size.value)
    test.assertEqual(dyld._NSGetExecutablePath(buffer, ctypes.byref(size)), 0)
    executable = Path(os.fsdecode(buffer.value)).resolve(strict=True)
    test.assertEqual(executable, RESOURCES / "bin" / ("FreeCAD" if App.GuiUp else "FreeCADCmd"))
    dyld._dyld_image_count.restype = ctypes.c_uint32
    dyld._dyld_get_image_name.argtypes = [ctypes.c_uint32]
    dyld._dyld_get_image_name.restype = ctypes.c_char_p
    images = [
        Path(os.fsdecode(dyld._dyld_get_image_name(index))).resolve()
        for index in range(dyld._dyld_image_count())
    ]
    native = {}
    libraries = ["libFreeCADBase.dylib", "libFreeCADApp.dylib"]
    if App.GuiUp:
        libraries.append("libFreeCADGui.dylib")
    for name in libraries:
        wanted = RESOURCES / "lib" / name
        test.assertEqual([path for path in images if path.name == name], [wanted])
        native[name] = {"path": str(wanted), "sha256": sha(wanted)}
    for name, module in modules.items():
        wanted = RESOURCES / "lib" / (name + ".so")
        origin = getattr(module, "__file__", None)
        matching = [path for path in images if path.name == wanted.name]
        if origin:
            test.assertEqual(Path(origin).resolve(strict=True), wanted)
            test.assertEqual(matching, [wanted])
            native[name] = {"path": str(wanted), "sha256": sha(wanted)}
        else:
            test.assertIn(name, ("FreeCAD", "FreeCADGui"))
            test.assertTrue(
                inspect.isbuiltin(App.Version if name == "FreeCAD" else module.updateGui)
            )
            test.assertIn(matching, ([], [wanted]))
            native[name] = {"embedded_native_binding": True, "standalone_loaded": bool(matching)}

    import ObjectsFem
    from femtools.force_accounting import solver_binary

    previous = App.activeDocument()
    previous_name = previous.Name if previous else None
    doc = App.newDocument("BeamBjhLiteralBundleIdentity")
    try:
        solver = ObjectsFem.makeSolverCalculiXCcxTools(doc)
        test.assertEqual(solver.NativeAccountingSolver, "")
        test.assertFalse(solver.BeamSectionForces)
        candidate = Path(solver_binary(solver))
        test.assertEqual(candidate, RESOURCES / "data/NativeSolvers/ccx-force-accounting")
        test.assertFalse(candidate.is_symlink())
        test.assertEqual(sha(candidate), NATIVE_SHA)
        capabilities = {}
        environment = {
            key: value for key, value in os.environ.items() if not key.startswith("CCX_")
        }
        with tempfile.TemporaryDirectory(
            prefix="beam-bjh-installed-capability-", dir=WORK
        ) as directory:
            for option, expected in (
                ("--freecad-force-accounting-version", "CCX_FORCE_ACCOUNTING_V3"),
                ("--freecad-contact-state-version", "CCX_CONTACT_STATE_V1"),
                ("--freecad-beam-section-version", "CCX_BEAM_SECTION_V1"),
                ("--freecad-beam-coupling-version", "CCX_BEAM_SECTION_V2"),
                ("--freecad-beam-solid-version", "CCX_BEAM_SECTION_V3"),
                ("--freecad-beam-contact-version", "CCX_BEAM_SECTION_V4"),
                ("--freecad-beam-network-version", "CCX_BEAM_SECTION_V5"),
            ):
                child = subprocess.run(
                    [str(candidate), option],
                    cwd=directory,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    timeout=10,
                    text=True,
                    check=False,
                )
                test.assertEqual(child.returncode, 0, child.stderr)
                test.assertEqual(child.stdout.strip(), expected)
                capabilities[option] = child.stdout.strip()
        test.assertEqual(sha(candidate), NATIVE_SHA)
    finally:
        App.closeDocument(doc.Name)
        if previous_name in App.listDocuments():
            App.setActiveDocument(previous_name)
    observation = {
        "schema": "FreeCAD-bjh-literal-application-identity-v1",
        "application": str(APP),
        "runtime": runtime,
        "GuiUp": bool(App.GuiUp),
        "home_path": App.getHomePath(),
        "process_executable": {"path": str(executable), "sha256": sha(executable)},
        "native_origins": native,
        "python_origins": source_origins(),
        "candidate": {
            "path": str(candidate),
            "sha256": sha(candidate),
            "override": False,
            "capabilities": capabilities,
        },
        "source_or_build_import_override": False,
    }
    RESULTS["identity"] = observation
    write_report("identity-observation.json", observation)
    return observation


class AppBeamIdentity(unittest.TestCase):
    def test_exact_application_identity_native_origins_and_default_solver(self):
        check_identity(self)


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


class VerifiedSuite(unittest.TestSuite):
    def run(self, result, debug=False):
        ids = [test.id() for test in flatten(self)]
        expected = {"cmd": 61, "gui": 9}[MODE]
        assert len(ids) == len(set(ids)) == expected, ids
        assert sorted(ids) == EXPECTED_IDS[MODE], ids
        super().run(result, debug=debug)
        origins = source_origins()
        passed = bool(
            result.wasSuccessful()
            and not result.skipped
            and result.testsRun == expected
            and "identity" in RESULTS
        )
        write_report(
            "regression.json",
            {
                "schema": "FreeCAD-bjh-installation-regression-v1",
                "passed": passed,
                "mode": MODE,
                "application": str(APP),
                "gui": bool(App.GuiUp),
                "commit": IDENTITY["commit"],
                "revision": IDENTITY["revision"],
                "native_sha256": NATIVE_SHA,
                "identity_sha256": sha(IDENTITY_PATH),
                "expected_tests": expected,
                "executed_tests": result.testsRun,
                "selected_test_ids": ids,
                "skipped": [test.id() for test, _reason in result.skipped],
                "failures": [test.id() for test, _traceback in result.failures],
                "errors": [test.id() for test, _traceback in result.errors],
                "source_or_build_import_override": False,
                "native_solver_override": False,
                "only_public_native_interfaces": True,
                "original_project_opened_changed_or_solved": False,
                "module_sha256": sha(__file__),
                "final_module_origins": origins,
                "identity": RESULTS.get("identity"),
            },
        )
        return result


def load_tests(loader, _tests, _pattern):
    assert MODE in ("cmd", "gui"), MODE
    suite = VerifiedSuite(
        [AppBeamIdentity("test_exact_application_identity_native_origins_and_default_solver")]
    )
    names = CMD_MODULES if MODE == "cmd" else GUI_MODULES
    for name in names:
        module = importlib.import_module(name)
        actual = Path(module.__file__).resolve(strict=True)
        relative = name.replace(".", "/") + ".py"
        assert actual == RESOURCES / "Mod/Fem" / relative, actual
        assert actual.read_bytes() == (REPO / "src/Mod/Fem" / relative).read_bytes()
        suite.addTests(loader.loadTestsFromModule(module))
    return suite
