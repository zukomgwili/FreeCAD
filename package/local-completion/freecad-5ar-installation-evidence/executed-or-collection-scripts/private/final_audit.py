"""Final host-local installation audit; no model, preference or app mutations."""
import json
import plistlib
import re
import runpy
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import critical_pins
import stage_install as s


def read(relative):
    return json.loads((ROOT / relative).read_text())


def success(report, native=False):
    assert report['passed'] and not report['timed_out']
    assert report['child_reaped' if native else 'process_reaped']
    assert report['process_group_gone' if native else 'owned_group_gone']


def audit_location(label, app):
    receipts = {}
    candidate = str(app / 'Contents/Resources/data/NativeSolvers/ccx-force-accounting')
    for mode, suite, count in (('fem', 'TestFemApp', 390), ('gui', 'TestFemGui', 8)):
        directory = ROOT / f'{label}-{mode}'
        report = read(f'{label}-{mode}/execution.json')
        identity = read(f'{label}-{mode}/identity.json')
        success(report)
        assert report['exit_code'] == 0 and report['application'] == str(app)
        assert report['source_and_harness_unchanged'] and report['application_unchanged']
        assert not report['rebound_or_reused_stage_outputs']
        assert report['configured_suite_counts'] == {suite: count}
        assert report['unittest']['count'] == count + 1
        assert report['unittest']['details'] == '' and not report['unittest']['skipped_lines']
        assert report['identity_sha256'] == s.digest(directory / 'identity.json')
        assert report['log_sha256'] == s.digest(directory / 'run.log')
        assert identity['passed'] and identity['application'] == str(app)
        assert identity['runtime'] == report['runtime']
        assert report['runtime'][-1] == s.COMMIT and report['runtime'][3] == s.REVISION
        assert identity['bundled_solver'] == {
            'path': candidate, 'sha256': s.NATIVE_SHA, 'capability': 'CCX_FORCE_ACCOUNTING_V2',
            'preference_or_candidate_override': False}
        ids = identity['registered_native_tie_ids']
        assert len(ids) == len(set(ids)) == 4
        if mode == 'fem':
            assert set(ids).issubset(identity['configured_suites'][suite]['ids'])
            text = (directory / 'run.log').read_text()
            for test_id in ids:
                method = test_id.rsplit('.', 1)[-1]
                pattern = '^' + re.escape(method) + r' \(' + re.escape(test_id) + r'\) \.\.\.(.*)$'
                matches = re.findall(pattern, text, re.M)
                assert len(matches) == 1 and 'skipped' not in matches[0], test_id
        receipts[mode] = {'receipt_sha256': s.digest(directory / 'execution.json'),
                          'suite_tests': count, 'identity_tests': 1,
                          'log_sha256': report['log_sha256']}
    fresh_cases = read(f'{label}-fem/execution.json')['tie_cold_cases']
    assert len(fresh_cases) == 1
    fresh = fresh_cases[0]
    for field in ('path', 'document', 'frd'):
        key = 'sha256' if field == 'path' else field + '_sha256'
        assert s.digest(Path(fresh[field])) == fresh[key]
    assert fresh['binary'] == candidate and fresh['binary_sha256'] == s.NATIVE_SHA
    cold = read(f'{label}-cold/execution.json')
    identity = read(f'{label}-cold/identity.json')
    probe = read(f'{label}-cold/probe.json')
    success(cold)
    assert cold['application'] == str(app) and cold['exit_code'] == 0
    assert cold['all_protected_inputs_unchanged']
    assert cold['manifest'] == fresh['path'] and cold['manifest_sha256'] == fresh['sha256']
    assert cold['unittest']['count'] == 2 and not cold['unittest']['skipped_lines']
    for name in ('identity', 'probe', 'log'):
        path = ROOT / f'{label}-cold' / ('run.log' if name == 'log' else name + '.json')
        assert cold[name + '_sha256'] == s.digest(path)
    assert identity['passed'] and identity['application'] == str(app)
    assert identity['runtime'] == cold['runtime']
    assert cold['runtime'][-1] == s.COMMIT and cold['runtime'][3] == s.REVISION
    assert cold['probe'] == probe and probe['passed'] and probe['application'] == str(app)
    for key in ('historical_until_explicit_refresh', 'accounting_not_promoted_to_Current',
                'opened_copy_unsaved', 'protected_inputs_unchanged'):
        assert probe[key]
    for key in ('writer_run', 'solver_solve_run', 'saved_document_written',
                'status_hash_or_fingerprint_repaired', 'Oomakhi_opened_or_solved'):
        assert not probe[key]
    receipts['cold'] = {'receipt_sha256': s.digest(ROOT / f'{label}-cold/execution.json'),
                        'manifest': fresh, 'tests': 2}
    v2 = read(f'{label}-v2/summary.json')
    assert v2['all_selected_passed'] and not v2['engineering_or_BIM_accepted']
    assert v2['candidate'] == candidate and v2['candidate_sha256'] == s.NATIVE_SHA
    assert v2['manifest_sha256'] == s.digest(ROOT / f'{label}-v2/manifest.json')
    expected = {'tie-tet4', 'tie-tet10', 'equation-unit-tet4',
                'equation-negative-scale-reverse-tet4', 'equation-quarter-scale-tet10',
                'equation-chain-reverse-tet4', 'tie-dependent-point-tet4',
                'equation-chain-dependent-point-tet10', 'reject-shared-cut-mpc-tet4',
                'reject-body-spc-tet4'}
    assert set(v2['selected_cases']) == expected and len(v2['selected_cases']) == 10
    assert {row['case'] for row in v2['reports']} == expected and len(v2['reports']) == 10
    checks = []
    for row in v2['reports']:
        success(row, native=True)
        assert row['candidate'] == candidate and row['candidate_sha256'] == s.NATIVE_SHA
        assert row['protected_inputs_unchanged'] and row['custody_before'] == row['custody_after']
        directory = ROOT / f'{label}-v2' / row['case']
        assert row == json.loads((directory / 'execution.json').read_text())
        assert row['solver_log_sha256'] == s.digest(directory / 'solver.log')
        if row.get('native_output_sha256'):
            assert row['native_output_sha256'] == s.digest(directory / 'contact.accounting.out')
        assert row['returncode'] == (201 if row.get('expected_domain_refusal') else 0)
        checks.extend(row.get('checks', []))
    assert len(checks) == 144 and all(row['passed'] and row['limit'] == 0.01 for row in checks)
    assert sum(bool(row.get('expected_domain_refusal')) for row in v2['reports']) == 2
    v1 = read(f'{label}-v1/qualification.json')
    assert v1['passed'] and v1['binary'] == candidate and v1['binary_sha256'] == s.NATIVE_SHA
    assert not v1['original_project_replayed'] and not v1['design_accepted']
    assert len(v1['analytic_cases']) == 48 and len(v1['rejections']) == 6
    assert len({row['case'] for row in v1['analytic_cases']}) == 48
    assert all(row['exit_code'] == 201 for row in v1['rejections'])
    coordinate = read(f'{label}-coordinate/execution.json')
    assert coordinate['candidate'] == candidate and coordinate['candidate_sha256'] == s.NATIVE_SHA
    assert coordinate['strict_coordinate_contract_passed'] and coordinate['returncode'] == 201
    assert coordinate['child_reaped'] and coordinate['process_group_gone']
    assert coordinate['protected_inputs_unchanged'] and not coordinate['timed_out']
    assert coordinate['custody_before'] == coordinate['custody_after']
    assert not coordinate['engineering_or_BIM_accepted']
    assert coordinate['contact.accounting.out_sha256'] is None
    assert not (ROOT / f'{label}-coordinate/contact.accounting.out').exists()
    assert coordinate['solver.log_sha256'] == s.digest(ROOT / f'{label}-coordinate/solver.log')
    for key, path in (('native_V2', 'v2/summary.json'), ('native_V1', 'v1/qualification.json'),
                      ('coordinate_refusal', 'coordinate/execution.json')):
        receipts[key] = s.digest(ROOT / (label + '-' + path))
    return receipts


def main():
    s.no_live_app()
    version = s.compiled_identity()
    critical = critical_pins.verify()
    sealed, baseline = read('stage-inventory.json'), read('baseline-inventory.json')
    assert s.inventory(s.APP) == sealed and s.inventory(s.BACKUP) == baseline
    assert not s.STAGE.exists() and not s.STAGE.is_symlink()
    for app in (s.APP, s.BACKUP):
        s.verify(app)
    for path, wanted in read('profile-inventories.json').items():
        assert s.inventory(Path(path)) == wanted, path
    s.check_namespace(read('namespace-plan.json'))
    resources = s.APP / 'Contents/Resources'
    s.source_equal(resources)
    for name in s.EXTENSIONS:
        assert s.entitlements(resources / 'PlugIns' / name) == plistlib.loads(
            (ROOT / (name + '.plist')).read_bytes())
    assert not list(resources.rglob('*.pyc')) and not list(resources.rglob('__pycache__'))
    assert all(row['kind'] == 'link' or not row['mode'] & 0o222
               for row in s.inventory(resources).values())
    assert s.digest(resources / 'LOCAL-INSTALL.txt') == s.digest(ROOT / 'LOCAL-INSTALL.txt')
    for name in ('independent-payload-audit.json', 'independent-stage-audit.json',
                 'independent-stage-custody.json'):
        assert read(name)['passed']
    audit = read('independent-stage-audit.json')
    assert audit['sealed_stage_inventory_sha256'] == s.canonical_sha(sealed)
    assert audit['native_payload_parity_count'] == 61
    for step in ('payload', 'audit-payload', 'stage', 'audit-stage', 'audit-custody', 'swap'):
        report = read('step-' + step + '.json')
        assert report['passed'] and report['exit_code'] == 0 and not report['timed_out']
        assert report['process_reaped'] and not report['owned_processes_remaining']
    gate = runpy.run_path(str(ROOT / 'run_build_gate.py'))
    for mode in ('build', 'ctest'):
        report = read(mode + '-latest/execution.json')
        success(report)
        assert report['exit_code'] == 0 and report['source_and_supervisor_unchanged']
        assert report['log_sha256'] == s.digest(ROOT / (mode + '-latest/run.log'))
        assert report['source_after']['git_head'] == s.COMMIT
        assert report['build_after']['version_header'] == version
        if mode == 'ctest':
            summary = gate['ctest_summary']((ROOT / 'ctest-latest/run.log').read_text())
            assert summary == report['ctest']
            assert (summary['catalogue'], summary['executed_passing'], summary['skipped'],
                    summary['disabled'], summary['failed']) == (2274, 2264, 2, 8, 0)
    locations = {label: audit_location(label, app)
                 for label, app in (('stage', s.STAGE), ('installed', s.APP))}
    assert locations['stage']['cold']['manifest']['path'] != locations['installed']['cold']['manifest']['path']
    s.no_live_app()
    critical_pins.verify()
    proof = {'passed': True, 'audit_completed_utc': datetime.now(timezone.utc).isoformat(),
             'source_commit': s.COMMIT, 'compiled_revision': s.REVISION,
             'application': str(s.APP), 'backup': str(s.BACKUP),
             'application_inventory_sha256': s.canonical_sha(sealed),
             'backup_inventory_sha256': s.canonical_sha(baseline),
             'application_inventory_entries': len(sealed), 'backup_inventory_entries': len(baseline),
             'critical_dependency_records_unchanged': len(critical['files']),
             'profiles_unchanged': len(s.PROFILES), 'namespace_files_unchanged': 11,
             'source_files_match': len(s.SOURCES), 'native_payload_parity': 61,
             'native_V2_sha256': s.NATIVE_SHA, 'strict_signatures_valid': True,
             'quicklook_entitlements_preserved': True, 'readonly_cachefree_resources': True,
             'Pixi_environment_still_required': str(s.PREFIX), 'locations': locations,
             'ctest': read('ctest-latest/execution.json')['ctest'],
             'Oomakhi_opened_modified_or_solved': False, 'engineering_or_BIM_accepted': False,
             'R49_existing_failed_percent': 11.123267892, 'R49_acceptance_limit_percent_unchanged': 5,
             'production_geometry_loads_sampling_and_other_acceptance_limits_changed': False,
             'audit_script_sha256': s.digest(Path(__file__))}
    s.write_json(ROOT / 'final-audit.json', proof)
    print(json.dumps({key: value for key, value in proof.items() if key not in ('locations', 'ctest')}))


if __name__ == '__main__':
    main()
