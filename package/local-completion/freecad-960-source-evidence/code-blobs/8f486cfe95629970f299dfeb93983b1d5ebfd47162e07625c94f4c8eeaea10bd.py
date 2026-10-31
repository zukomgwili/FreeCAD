"""Run selected shipped tests with exact built module-origin qualification."""
import sys
sys.dont_write_bytecode = True
import hashlib
import importlib
import json
import os
from pathlib import Path
import FreeCAD as App

REPO = Path('/Users/zukomgwili/src/FreeCAD')


def load_tests(loader, _tests, _pattern):
    records = {}
    for name, relative in (
        ('femtools.beam_section_forces', 'femtools/beam_section_forces.py'),
        ('femtools.ccxtools', 'femtools/ccxtools.py'),
        ('femobjects.solver_ccxtools', 'femobjects/solver_ccxtools.py'),
        ('femtest.app.test_beam_section_forces', 'femtest/app/test_beam_section_forces.py'),
    ):
        module = importlib.import_module(name)
        path = Path(module.__file__).resolve()
        assert path == (REPO / 'build/release/Mod/Fem' / relative).resolve(), path
        wanted = (REPO / 'src/Mod/Fem' / relative).read_bytes()
        assert path.read_bytes() == wanted
        records[name] = {'path': str(path), 'sha256': hashlib.sha256(wanted).hexdigest()}
    print('[BEAM960-QUALIFIED-ORIGINS]', json.dumps({'runtime': App.Version(), 'modules': records}), flush=True)
    if os.environ['B960_CASE'] in ('gui','gui-invalid'):
        module = importlib.import_module('femtest.gui.test_beam_section_forces')
        path = Path(module.__file__).resolve()
        assert path == (REPO/'build/release/Mod/Fem/femtest/gui/test_beam_section_forces.py').resolve()
        assert path.read_bytes() == (REPO/'src/Mod/Fem/femtest/gui/test_beam_section_forces.py').read_bytes()
        if os.environ['B960_CASE']=='gui-invalid':
            return loader.loadTestsFromName('TestBeamSectionForcesGui.test_invalid_output_request_reports_error_and_clears_busy_cursor',module)
        return loader.loadTestsFromTestCase(module.TestBeamSectionForcesGui)
    if os.environ['B960_CASE'] == 'transverse':
        module = importlib.import_module('femtest.app.test_beam_section_forces_native')
        path = Path(module.__file__).resolve()
        assert path == (REPO/'build/release/Mod/Fem/femtest/app/test_beam_section_forces_native.py').resolve()
        assert path.read_bytes() == (REPO/'src/Mod/Fem/femtest/app/test_beam_section_forces_native.py').read_bytes()
        return loader.loadTestsFromTestCase(module.TestBeamSectionForcesNative)
    if os.environ['B960_CASE'] in ('lifecycle','metadata'):
        module = importlib.import_module('femtest.app.test_beam_section_forces_lifecycle')
        path = Path(module.__file__).resolve()
        assert path == (REPO/'build/release/Mod/Fem/femtest/app/test_beam_section_forces_lifecycle.py').resolve()
        assert path.read_bytes() == (REPO/'src/Mod/Fem/femtest/app/test_beam_section_forces_lifecycle.py').read_bytes()
        if os.environ['B960_CASE']=='metadata':
            return loader.loadTestsFromName('TestBeamSectionForcesLifecycle.test_altered_export_metadata_is_refused_before_native_solve',module)
        return loader.loadTestsFromTestCase(module.TestBeamSectionForcesLifecycle)
    if os.environ['B960_CASE'] in ('safety','off','relative','projection','frame','comment'):
        module = importlib.import_module('femtest.app.test_beam_section_forces_safety')
        path = Path(module.__file__).resolve()
        assert path == (REPO/'build/release/Mod/Fem/femtest/app/test_beam_section_forces_safety.py').resolve()
        assert path.read_bytes() == (REPO/'src/Mod/Fem/femtest/app/test_beam_section_forces_safety.py').read_bytes()
        methods = {'off':'test_disabling_and_rewriting_does_not_relabel_old_beam_frd_as_stress',
                   'relative':'test_relative_solver_selection_is_not_accepted_for_native_beam_output',
                   'projection':'test_saved_local_channel_must_match_its_retained_native_wrench_projection',
                   'frame':'test_saved_earlier_frame_cannot_follow_the_requested_final_time',
                   'comment':'test_comment_about_section_forces_is_not_a_resultant_output_request'}
        if os.environ['B960_CASE'] in methods:
            return loader.loadTestsFromName('TestBeamSectionForcesSafety.'+methods[os.environ['B960_CASE']],module)
        return loader.loadTestsFromTestCase(module.TestBeamSectionForcesSafety)
    module = importlib.import_module('femtest.app.test_beam_section_forces')
    names = {
        'request': 'TestBeamSectionForces',
        'axial': 'TestBeamSectionForcesNative.test_axial_member_ends_have_native_identity_units_and_signed_actions',
    }
    return loader.loadTestsFromName(names[os.environ['B960_CASE']], module)
