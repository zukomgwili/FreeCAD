"""Assemble a private, unapproved selection only from completed actual receipts.

Root must inspect qualification assertions, privacy, actual aggregate and the
separately reviewed collector before approving any publication. Never native.
"""
import argparse
import hashlib
import json
from pathlib import Path

TASK = Path('/private/tmp/freecad-3q7-Pq3Byy')
REPO = Path('/Users/zukomgwili/src/FreeCAD')
FINAL = '6605b582911c320418951abaa415fa947237c4c8'
NATIVE = '6c02452a896727af6cb4578fd3fb6bbfbdd48e3fb887c1c04fa2d8b171976c66'
COLLECTION = TASK / 'collection'

def need(value, message):
    if not value:
        raise RuntimeError(message)

def load(path):
    return json.loads(Path(path).read_bytes())

def descriptor(path):
    path = Path(path)
    need(path.is_file() and not path.is_symlink(), 'Actual regular file required: ' + str(path))
    data = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}

def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--final-review', required=True, type=Path)
    parser.add_argument('--label', required=True)
    parser.add_argument('--extra-file', action='append', type=Path, default=[])
    args = parser.parse_args()
    need(args.label.isascii() and args.label.replace('-', '').isalnum(), 'Safe label required')
    files = {}
    def add(path, kind=None, classification='Exact software QA evidence; historical failures remain literal'):
        path = Path(path)
        need(path.is_file() and path.is_absolute() and not path.is_symlink(), 'Missing exact evidence: ' + str(path))
        if str(path) in files:
            return
        need(not path.name.startswith('private-') and path.suffix not in {'.cfg', '.pyc', '.so', '.dylib'}, 'Private/runtime input excluded')
        root = TASK if path.is_relative_to(TASK) else REPO
        need(path.is_relative_to(root), 'Unexpected source root')
        rel = path.relative_to(root)
        need(not {'freecad_user_temp', 'freecad_user_home', '.pixi', '.git', '.beads'}.intersection(rel.parts), 'Unapproved namespace')
        destination = ('task/' if root == TASK else 'repository/') + rel.as_posix()
        kind = kind or ('json' if path.suffix == '.json' else 'source' if path.suffix == '.py' else
            'profile-data' if path.suffix == '.prof' else 'native-input' if path.suffix in {'.inp', '.accounting'} else
            'synthetic-fixture' if path.suffix.lower() == '.fcstd' else 'native-output' if path.suffix in {'.frd', '.dat', '.out'} else 'text')
        files[str(path)] = {'path': str(path), 'destination': destination, 'kind': kind, 'classification': classification}
    roles, states, checks = {}, {}, {}
    def role(name, path, expected, assertions):
        path = Path(path)
        value = load(path)
        need(value.get('passed') is expected, 'Actual role outcome differs: ' + name)
        for pointer, expected_value in assertions.items():
            actual = value
            for term in pointer[1:].split('/'):
                term = term.replace('~1', '/').replace('~0', '~')
                actual = actual[int(term)] if isinstance(actual, list) else actual[term]
            need(type(actual) is type(expected_value) and actual == expected_value,
                 'Actual semantic assertion differs: ' + name + pointer)
        roles[name], states[name] = descriptor(path), expected
        checks[name] = [{'pointer': key, 'equals': item} for key, item in assertions.items()]
        add(path)
        return value
    def supervised(name, directory, expected=True, count=None, final=False):
        path = directory / 'execution.json'
        value = load(path)
        assertions = {'/returncode': 0 if expected else 1, '/timed_out': False,
            '/child_reaped': True, '/process_group_gone': True,
            '/inputs_unchanged': True, '/app_and_profiles_unchanged': True,
            '/selected_critical_dependencies_unchanged': True, '/skipped_lines': [],
            '/missing_repeated_or_skipped_ids': []}
        if count is not None:
            assertions['/unittest_counts/0/0'] = str(count)
        if final:
            assertions['/runtime/7'] = FINAL
            assertions['/discovery_only'] = False
            assertions['/unit_only'] = False
        role(name, path, expected, assertions)
        for leaf in ('manifest.json', 'identity.json', 'run.log'):
            add(directory / leaf)
    for name, label in (('tiny_red_first', 'tiny-work-red-r01'), ('tiny_red_second', 'tiny-work-red-r02')):
        directory = TASK / label
        role(name, directory / 'work-bound.json', False, {'/actual_public_writes': 1})
        for leaf in ('execution.json', 'manifest.json', 'identity.json', 'observation.json', 'run.log', 'mesh-and-properties-before.json'):
            add(directory / leaf)
        for ref in load(directory / 'execution.json')['produced_outputs'].values():
            add(ref['path'])
    first_observation = TASK / 'tiny-observation-r01'
    for leaf in ('execution.json', 'manifest.json', 'identity.json', 'observation.json', 'run.log', 'mesh-and-properties-before.json'):
        add(first_observation / leaf)
    for ref in load(first_observation / 'execution.json')['produced_outputs'].values():
        add(ref['path'])
    for name, label in (('paired_baseline', 'large-baseline-r02'), ('paired_candidate', 'large-candidate-r02'),
                         ('historical_baseline', 'large-baseline-r01'), ('rejected_large_pair', 'large-candidate-r01')):
        directory = TASK / label
        expected = name != 'rejected_large_pair'
        assertions = {'/role': 'candidate' if 'candidate' in label else 'baseline',
            '/child_reaped': True, '/process_group_gone': True, '/timed_out': False,
            '/source_and_supervisor_unchanged': True, '/compiled_native_runtime_unchanged': True,
            '/unittest_counts/0/0': '2',
            '/application_and_three_profiles_unchanged': True, '/sixteen_selected_dependencies_unchanged': True,
            '/returncode': 0 if expected else 1}
        if expected:
            assertions['/produced_outputs_unchanged_after_capture'] = True
        value = role(name, directory / 'execution.json', expected, assertions)
        add(directory / 'manifest.json')
        for ref in value['produced_outputs'].values():
            add(ref['path'])
    for name, label in (('restore_first', 'restore-components-r01'), ('restore_second', 'restore-components-r02')):
        directory = TASK / 'source-qa' / label
        observation = role(name, directory / 'restore-observation.json', True,
            {'/no_export_save_recompute_mesher_or_solver': True, '/inputs_unchanged': True,
             '/counts/nodes': 144951, '/counts/volume_elements': 74228, '/counts/groups': 9531})
        add(observation['output']['path'], 'mesh-snapshot')
        supervised(name + '_execution', directory, count=2)
    role('group_handle_amendment', TASK / 'proposals/benchmark-native-group-handle-amendment-r01.json', True,
         {'/old_failed_pair_reclassified': False, '/product_guard_or_engineering_limit_changed': False})
    for name, label, count in (('fem', 'fem-full-r02', 419), ('gui', 'gui-full-r01', 9),
                              ('guards', 'native-guards-r03', 13), ('full_graph_execution', 'capacity-native-r01', 2)):
        supervised(name, TASK / 'source-qa' / label, count=count, final=True)
    for name, label in (('historical_fem_failure', 'fem-full-r01'), ('historical_tiny_selection_failure', 'tiny-source-green-r03'),
                        ('historical_none_endpoint_failure', 'tiny-source-green-r01'), ('source_work_red', 'tiny-source-red-r01')):
        supervised(name, TASK / 'source-qa' / label, False,
                   count=9 if name == 'historical_tiny_selection_failure' else
                   419 if name == 'historical_fem_failure' else 2)
    for label in ('tiny-source-green-r02', 'tiny-source-green-r04', 'native-guards-r01', 'native-guards-r02',
                  'fem-discovery-r01', 'fem-discovery-r02', 'gui-discovery-r01'):
        for leaf in ('execution.json', 'manifest.json', 'identity.json', 'run.log'):
            add(TASK / 'source-qa' / label / leaf)
    custody_path = COLLECTION / 'generic-case-custody-r01.json'
    custody = load(custody_path)
    add(custody_path)
    copy_root = Path(custody['copy_directory'])
    for row in custody['files']:
        add(copy_root / row['path'], classification='Individually approved exact public synthetic-case bytes; literal original paths unchanged')
    role('full_graph_witness', copy_root / 'witness-receipt.json', True,
        {'/physical_check_count': 3566, '/solver_returncode': 0,
         '/force_and_original_origin_moment_limit': .01, '/scalar_response_limit': .05,
         '/one_below_capacity_refusal/budget': 2112, '/one_below_capacity_refusal/export_directory_untouched': True})
    role('independent_physical_audit', TASK / 'physical-audit/fresh-audit-r01.json', True,
         {'/acceptance/unique_recomputed_checks': 3566, '/acceptance/limits_unchanged': True,
          '/physical_graph/total': 2113, '/physical_graph/branches': 132})
    cold_directory = TASK / 'cold-qa/cold-native-r01'
    cold_execution = load(cold_directory / 'execution.json')
    role('cold_execution', cold_directory / 'execution.json', True,
        {'/returncode': 0, '/child_reaped': True, '/process_group_gone': True, '/timed_out': False,
         '/unittest_counts/0/0': '2', '/runtime/7': FINAL, '/skipped_lines': [],
         '/inputs_unchanged': True, '/app_and_profiles_unchanged': True,
         '/selected_critical_dependencies_unchanged': True, '/literal_cold_receipt_passed': True,
         '/output_bytes_endfenced': True, '/manifest_endfenced': True,
         '/final_inputs_endfenced': True, '/post_run_serial_guard_passed': True})
    for leaf in ('manifest.json', 'identity.json', 'run.log'):
        add(cold_directory / leaf)
    role('cold_receipt', cold_directory / 'cold-receipt.json', True,
        {'/no_native_solve': True, '/no_save': True, '/no_history_or_provenance_repair': True})
    for label in ('source-baseline-build-r01', 'regression-copy-build-r01', 'implementation-build-r01', 'diagnostic-build-r01'):
        path = TASK / label / 'execution.json'
        role('source_build' if label == 'diagnostic-build-r01' else label.replace('-', '_'), path, True,
            {'/schema': 'FreeCAD-3q7-source-build-v1', '/returncode': 0, '/installation_performed': False,
             '/source_unchanged': True, '/application_and_three_profiles_unchanged': True,
             '/selected_dependencies_unchanged': True, '/post_run_serial_guard_passed': True})
        add(path.parent / 'run.log')
    for label in ('candidate-script-copy-r01', 'candidate-script-copy-r02', 'candidate-guards-copy-r01',
                  'repeated-baseline-script-copy-r01', 'final-candidate-script-copy-r01'):
        add(TASK / label / 'execution.json')
        add(TASK / label / 'run.log')
    ctest = load(TASK / 'ctest-qa/ctest-r01/execution.json')
    role('ctest', TASK / 'ctest-qa/ctest-r01/execution.json', True,
         {'/schema': ctest['schema'], '/returncode': 0, '/timed_out': False,
          '/child_reaped': True, '/process_group_gone': True,
          '/ctest/catalogue': 2274, '/ctest/enabled': 2266, '/ctest/executed_passing': 2264,
          '/ctest/failed': 0, '/ctest/skipped': 2, '/ctest/disabled': 8,
          '/ctest/complete_catalogue_verified': True, '/source_build_supervisor_candidate_unchanged': True,
          '/app_and_profiles_unchanged': True, '/selected_critical_dependencies_unchanged': True,
          '/retained_log_bytes_endfenced': True, '/fresh_ctest_log_bytes_endfenced': True,
          '/post_run_serial_guard_passed': True})
    add(TASK / 'ctest-qa/ctest-r01/run.log')
    for leaf, row in ctest['ctest_logs_after'].items():
        if row['fresh_for_this_run']:
            add(TASK / 'ctest-qa/ctest-r01' / leaf)
    role('final_review', args.final_review, True, {'/pending_roles': []})
    role('source_quality', COLLECTION / 'source-quality-r01.json', True,
         {'/source_commit': FINAL, '/formatting/returncode': 0, '/whitespace/returncode': 0,
          '/rails_checks/applicable': False})
    scope = {'source_only': True, 'installation_performed': False, 'Oomakhi_accessed_or_solved': False,
        'engineering_or_BIM_accepted': False, 'R49_R51_acceptance_claimed': False,
        'no_timing_SLA_or_universal_scaling_claim': True, 'historical_failed_pair_remains_failed': True,
        'force_original_origin_moment_limit': .01, 'scalar_response_limit': .05}
    qualification = {'schema': 'FreeCAD-3q7-source-qualification-v1', 'passed': True, 'pending_roles': [],
        'source_identity': {'implementation_commit': '9c3e7ec2637d6d3149dc55d0906576225a4d8bf7',
            'diagnostic_only_followup_commit': FINAL, 'final_product_commit': FINAL,
            'compiled_revision': '49261 +228 (Git)', 'default_native_sha256': NATIVE,
            'performance_pair_common_compiled_commit': '5b11849843232fdffa4c9c08e2821a6f7c99dee3',
            'performance_pair_is_not_relabelled_as_final_build': True},
        'scope': scope, 'roles': roles, 'role_expectations': states, 'role_checks': checks}
    qualification_path = COLLECTION / (args.label + '-qualification.json')
    write(qualification_path, qualification)
    add(qualification_path)
    # Exact frozen software-QA helpers, never runtime/configuration trees.
    for directory in ('source-qa', 'large-qa', 'large-qa-v2', 'cold-qa', 'ctest-qa', 'physical-audit', 'collection'):
        for path in sorted((TASK / directory).glob('*.py')):
            add(path)
    for path in sorted(TASK.glob('Yzk*.py')):
        add(path)
    for leaf in ('process_control.py', 'run_build_3q7.py', 'run_copy_3q7.py', 'run_count_regression.py'):
        add(TASK / leaf)
    for rel in ('source-change.patch', 'generic-case-approval-r01.json'):
        add(COLLECTION / rel)
    pins = load(TASK / 'proposals/private-candidate-files-r02.json')
    for row in pins['files']:
        add(row['private_path'], classification='Exact reviewed measured-candidate Python source/test bytes before diagnostic-only followup')
        add(REPO / 'src/Mod/Fem' / row['relative'], classification='Exact final committed Python source/test bytes')
    for leaf in ('coupled_port_capacity_fixture.json', 'coupled_port_capacity_oracle.json'):
        add(REPO / 'src/Mod/Fem/femtest/data/calculix' / leaf)
    for rel in ('femtest/app/test_moving_port_capacity_native.py', 'femtest/app/coupled_port_fixture.py',
                'femtest/app/coupled_port_audit.py', 'femtools/ccxtools.py',
                'femsolver/calculix/write_constraint_rigidbody.py', 'TestFemApp.py',
                'TestFemGui.py', 'coding_conventions.md'):
        add(REPO / 'src/Mod/Fem' / rel)
    for leaf in ('forceaccounting.c', 'hooks.patch', 'contract.json'):
        add(REPO / 'package/calculix/force-accounting' / leaf)
    add(REPO / 'package/local-completion/freecad-yzk-source-evidence/private/qa/native-capacity-r01-attestation-v2.json')
    for path in args.extra_file:
        add(path, classification='Explicit root-selected independently reviewed source, QA or evidence-custody artifact')
    selection = {'schema': 'FreeCAD-3q7-private-plan-selection-v1', 'pending_roles': [],
        'qualification_receipt': descriptor(qualification_path), 'synthetic_capsule': descriptor(custody_path),
        'files': list(files.values()), 'hash_only_references': [
            {**descriptor(REPO / 'package/local-completion/freecad-882-source-evidence/index.json'),
             'scope': 'Immutable prior profiling/saved-fixture evidence retained by exact index reference; not fresh physical qualification'}]}
    write(COLLECTION / (args.label + '-selection.json'), selection)
    print(json.dumps({'private_selection_only': True, 'root_approval_pending': True,
        'files': len(files), 'actual_payload_bytes': sum(descriptor(p)['bytes'] for p in files)}))

if __name__ == '__main__':
    main()
