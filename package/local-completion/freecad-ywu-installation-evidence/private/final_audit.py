"""Final host-local installation audit; no engineering document or profile writes."""
import hashlib
import json
import plistlib
from pathlib import Path
import sys
from datetime import datetime, timezone

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import critical_pins
import stage_install as s


def read(relative):
    return json.loads((ROOT / relative).read_text())


def main():
    s.no_live_app()
    version = s.compiled_identity()
    critical = critical_pins.verify()
    sealed, baseline = read('stage-inventory.json'), read('baseline-inventory.json')
    assert s.inventory(s.APP) == sealed and s.inventory(s.BACKUP) == baseline
    assert not s.STAGE.exists() and not s.STAGE.is_symlink()
    for app in (s.APP, s.BACKUP):
        s.verify(app)
    profiles = read('profile-inventories.json')
    for path, wanted in profiles.items():
        assert s.inventory(Path(path)) == wanted, path
    s.check_namespace(read('namespace-plan.json'))
    resources = s.APP / 'Contents/Resources'
    s.source_equal(resources)
    for name in s.EXTENSIONS:
        expected = plistlib.loads((ROOT / (name + '.plist')).read_bytes())
        assert s.entitlements(resources / 'PlugIns' / name) == expected
        assert s.entitlements(s.BACKUP / 'Contents/Resources/PlugIns' / name) == expected
    assert not list(resources.rglob('*.pyc')) and not list(resources.rglob('__pycache__'))
    assert all(row['kind'] == 'link' or not row['mode'] & 0o222
               for row in s.inventory(resources).values())
    assert s.digest(resources / 'LOCAL-INSTALL.txt') == s.digest(ROOT / 'LOCAL-INSTALL.txt')
    for step in ('payload', 'audit-payload', 'stage', 'audit-stage', 'audit-custody', 'swap'):
        report = read('step-' + step + '.json')
        assert report['passed'] and report['exit_code'] == 0 and not report['timed_out']
        assert report['process_reaped'] and not report['owned_processes_remaining']
        assert report['critical_pins_unchanged']
        assert report['helper_inputs_before'] == report['helper_inputs_after']
        for path, wanted in report['helper_inputs_after'].items():
            assert s.digest(Path(path)) == wanted, path
    payload = read('independent-payload-audit.json')
    audit = read('independent-stage-audit.json')
    custody = read('independent-stage-custody.json')
    assert payload['passed'] and audit['passed'] and custody['passed']
    assert audit['payload_audit_sha256'] == s.digest(ROOT / 'independent-payload-audit.json')
    assert custody['stage_audit_sha256'] == s.digest(ROOT / 'independent-stage-audit.json')
    assert audit['sealed_stage_inventory_sha256'] == s.canonical_sha(sealed)
    assert audit['baseline_inventory_sha256'] == s.canonical_sha(baseline)
    assert custody['baseline_and_stage_exact']
    assert payload['payload_native_count'] == audit['native_payload_parity_count'] == custody['native_payload_count']
    assert audit['native_payload_parity_count'] > 0
    for label in ('build', 'ctest'):
        report = read(label + '-latest/execution.json')
        assert report['passed'] and report['exit_code'] == 0 and not report['timed_out']
        assert report['process_reaped'] and report['owned_group_gone']
        assert report['source_and_supervisor_unchanged']
        assert report['log_sha256'] == s.digest(ROOT / (label + '-latest/run.log'))
        assert report['source_after']['git_head'] == s.COMMIT
        assert report['build_after']['version_header'] == version
    ct = read('ctest-latest/execution.json')['ctest']
    assert ct['complete_catalogue_verified']
    assert (ct['catalogue'], ct['executed_passing'], ct['skipped'], ct['disabled'], ct['failed']) == (2274, 2264, 2, 8, 0)
    # Current installed receipts must bind the actual installed path. The same
    # helper validated staged receipts before the successful SHA-bound swap.
    s.check_app_receipts('installed', sealed)
    locations = {}
    for location, application in (('stage', s.STAGE), ('installed', s.APP)):
        gates = {}
        for suffix, total in (('fem', 396), ('gui', 9), ('native', 6),
                              ('endload', 2), ('ordinary', 2),
                              ('endload-cold', 2), ('ordinary-cold', 2)):
            label = location + '-' + suffix
            directory = ROOT / label
            report, identity = read(label + '/execution.json'), read(label + '/identity.json')
            assert report['passed'] and report['application'] == str(application)
            assert report['returncode'] == 0 and not report['timed_out']
            assert report['child_reaped'] and report['process_group_gone']
            assert report['source_build_harness_unchanged'] and report['application_unchanged']
            assert report['app_and_profiles_unchanged'] and report['critical_dependency_pins_unchanged']
            assert report['identity_sha256'] == s.digest(directory / 'identity.json')
            assert report['log_sha256'] == s.digest(directory / 'run.log')
            assert len(report['unittest_counts']) == 1 and int(report['unittest_counts'][0][0]) == total
            assert not report['skipped_lines']
            assert identity['passed'] and identity['runtime'][-1] == s.COMMIT
            assert identity['runtime'][3] == s.REVISION and identity['application'] == str(application)
            assert identity['candidate']['path'] == str(application / 'Contents/Resources/data/NativeSolvers/ccx-force-accounting')
            assert identity['candidate']['sha256'] == s.NATIVE_SHA
            for when in ('before', 'after'):
                filename = directory / ('private-application-' + when + '.json')
                assert report['application_inventory_' + when + '_sha256'] == s.digest(filename)
                assert json.loads(filename.read_text()) == sealed
            assert report['inputs_before'] == report['inputs_after']
            for path, wanted in report['inputs_after'].items():
                assert s.digest(Path(path)) == wanted, path
            gates[suffix] = {'receipt_sha256': s.digest(directory / 'execution.json'),
                             'identity_sha256': report['identity_sha256'],
                             'log_sha256': report['log_sha256'], 'total_tests': total}
        for kind in ('endload', 'ordinary'):
            witness = read(location + '-' + kind + '/witness/witness-receipt.json')
            cold = read(location + '-' + kind + '-cold/cold-receipt.json')
            manifest = Path(witness['cold_manifest'])
            assert s.digest(manifest) == witness['cold_manifest_sha256'] == cold['manifest_sha256']
            assert cold['manifest'] == str(manifest) and cold['no_native_solve']
            assert cold['no_history_or_provenance_repair'] and cold['status'].startswith('Stale')
            literal = json.loads(manifest.read_text())['accounting_data_literal']
            assert hashlib.sha256(literal.encode()).hexdigest() == cold['accounting_data_sha256']
            gates[kind]['cold_manifest'] = {'path': str(manifest), 'sha256': s.digest(manifest)}
        locations[location] = {'application_at_execution': str(application), 'gates': gates,
                               'legacy_v1_qualification_sha256': s.digest(ROOT / (location + '-v1/qualification.json')),
                               'legacy_v2_summary_sha256': s.digest(ROOT / (location + '-v2/summary.json'))}
    for kind in ('endload', 'ordinary'):
        assert locations['stage']['gates'][kind]['cold_manifest']['path'] != locations['installed']['gates'][kind]['cold_manifest']['path']
    s.no_live_app()
    critical_pins.verify()
    assert s.inventory(s.APP) == sealed and s.inventory(s.BACKUP) == baseline
    proof = {'schema': 'FreeCAD-ywu-installed-audit-v1', 'passed': True,
             'audit_completed_utc': datetime.now(timezone.utc).isoformat(),
             'source_commit': s.COMMIT, 'compiled_revision': s.REVISION,
             'application': str(s.APP), 'backup': str(s.BACKUP),
             'application_inventory_sha256': s.canonical_sha(sealed),
             'backup_inventory_sha256': s.canonical_sha(baseline),
             'application_inventory_entries': len(sealed), 'backup_inventory_entries': len(baseline),
             'critical_dependency_records_unchanged': len(critical['files']),
             'critical_dependency_scope': critical['scope'], 'profiles_unchanged': len(profiles),
             'namespace_files_unchanged': len(s.NAMESPACE_FILES), 'source_files_match': len(s.SOURCES),
             'native_payload_parity': audit['native_payload_parity_count'], 'native_V3_sha256': s.NATIVE_SHA,
             'strict_signatures_valid': True, 'quicklook_entitlements_preserved': True,
             'readonly_cachefree_resources': True, 'locations': locations, 'ctest': ct,
             'bundle_mtime_ns': s.APP.stat().st_mtime_ns,
             'Pixi_environment_still_required': str(s.PREFIX),
             'Oomakhi_opened_modified_or_solved': False, 'engineering_or_BIM_accepted': False,
             'R49_existing_failed_percent': 11.123267892, 'R51_existing_failed_percent': 5.240441298,
             'displacement_acceptance_limit_percent_unchanged': 5,
             'force_origin_moment_acceptance_limit_unchanged': 0.01,
             'production_geometry_loads_sampling_and_other_acceptance_limits_changed': False,
             'audit_script_sha256': s.digest(Path(__file__))}
    s.write_json(ROOT / 'final-audit.json', proof)
    print(json.dumps({key: value for key, value in proof.items() if key not in ('locations', 'ctest')}))


if __name__ == '__main__':
    main()
