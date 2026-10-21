"""Explicit 8rk deployment adapter for unchanged reviewed staging/rollback core."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import signal
import subprocess
import sys

sys.dont_write_bytecode = True
TASK = Path(__file__).resolve().parent
sys.path.insert(0, str(TASK))
import run_gate

ORIGINAL = Path('/Users/zukomgwili/src/FreeCAD/package/local-completion/freecad-ywu-installation-evidence/private/stage_install.py')
CORE_SHA = 'cca627502a56b6c9b4aefa4a970172c51e42e2dde834000decca65fd44ab46d9'
AUDITOR_SHA = 'd2dd63a5dd9d9868816777e3af75fa06798f93910c56cf25b7a2ad51117ddaf3'
assert __debug__ and hashlib.sha256(ORIGINAL.read_bytes()).hexdigest() == CORE_SHA
spec = importlib.util.spec_from_file_location('_unchanged_8rk_install_core', ORIGINAL)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
core.ROOT = TASK
core.STAGE = TASK / core.APP.name
core.BACKUP = Path('/Users/zukomgwili/Applications/FreeCAD Backups/FreeCAD-27.1.0-before-8rk-6a0ed157b1.app')
core.COMMIT = '4eb8f43362c0cbc5a0dab4869ad77be6f27ad679'
core.REVISION = '49261 +233 (Git)'
core.NATIVE_SHA = '6c02452a896727af6cb4578fd3fb6bbfbdd48e3fb887c1c04fa2d8b171976c66'
for relative in (
    'femtools/elastic_connector.py', 'femsolver/calculix/writer.py',
    'femtools/rigid_body.py', 'femtest/app/support_utils.py',
    'femtest/app/test_rigid_region_ownership.py',
    'femsolver/calculix/write_constraint_rigidbody.py',
    'femsolver/calculix/write_constraint_rigidbody_step.py',
    'femtest/app/test_elastic_connector.py',
    'femtest/app/coupled_port_fixture.py', 'femtest/app/coupled_port_audit.py',
    'femtest/app/test_moving_port_capacity_native.py',
    'femtest/data/calculix/coupled_port_capacity_fixture.json',
    'femtest/data/calculix/coupled_port_capacity_oracle.json',
):
    core.SOURCES['src/Mod/Fem/' + relative] = 'Mod/Fem/' + relative


def compiled_identity():
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=core.REPO,
                                   text=True, timeout=10).strip() == core.COMMIT
    subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--', 'src', 'tests/src',
                    'package/calculix'], cwd=core.REPO, check=True, timeout=10)
    values = dict(re.findall(r'^#define\s+(\w+)\s+"([^"]*)"',
                            (core.BUILD / 'src/Build/Version.h').read_text(), re.M))
    assert values['FCRepositoryHash'] == core.COMMIT
    assert values['FCRevision'] == core.REVISION
    build = json.loads((TASK / 'build-latest/execution.json').read_text())
    assert build['passed'] and build['source_commit'] == core.COMMIT and build['mode'] == 'build'
    assert build['returncode'] == 0 and not build['timed_out']
    for name, wanted in build['source_inputs_after'].items():
        assert core.digest(name) == wanted, name
    assert core.digest(core.BUILD / 'data/NativeSolvers/ccx-force-accounting') == core.NATIVE_SHA
    if (TASK / 'build-identity.json').exists():
        for name, wanted in json.loads((TASK / 'build-identity.json').read_text()).items():
            assert core.digest(name) == wanted, name
    return values


def application_gate(application, label, count):
    report = json.loads((TASK / label / 'execution.json').read_text())
    mode = label.rsplit('-', 1)[-1]
    assert report['schema'] == 'FreeCAD-8rk-literal-application-gate-v1'
    assert report['mode'] == mode and mode in ('cmd', 'gui')
    assert report['passed'] and report['application'] == str(application)
    assert report['expected_tests'] == count and report['executed_tests'] == count
    assert report['returncode'] == 0 and not report['timed_out']
    assert report['child_reaped'] and report['process_group_gone']
    assert report['application_unchanged'] and report['profiles_and_dependencies_unchanged']
    assert report['inputs_unchanged'] and report['source_commit'] == core.COMMIT
    assert report['inputs_before'] == report['inputs_after']
    for name, wanted in report['inputs_after'].items():
        assert core.digest(name) == wanted, name
    assert core.digest(TASK / label / 'run.log') == report['log_sha256']
    assert core.digest(TASK / label / 'regression.json') == report['regression_sha256']
    proof = json.loads((TASK / label / 'regression.json').read_text())
    assert proof['schema'] == 'FreeCAD-8rk-installation-regression-v1'
    assert proof['passed'] and proof['application'] == str(application)
    assert proof['commit'] == core.COMMIT and proof['revision'] == core.REVISION
    assert proof['gui'] is (mode == 'gui') and proof['test_count'] == 2
    backup = proof['backup_regression']
    assert backup['backups_contain_exact_previous_target_bytes']
    assert backup['no_escape_or_temporary_leftovers']
    assert [row['marker'] for row in backup['same_process_native_reopen']] == ['third', 'first', 'second']
    assert report['application_inventory_sha256'] == core.canonical_sha(
        json.loads((TASK / 'stage-inventory.json').read_text()))
    return report


def check_stage_receipts(sealed):
    import critical_pins
    compiled_identity()
    critical_pins.verify()
    assert core.inventory(core.STAGE) == sealed
    rows = {}
    for mode in ('payload', 'stage', 'custody'):
        path = TASK / ('independent-' + ('payload-audit' if mode == 'payload' else
                                        'stage-audit' if mode == 'stage' else 'stage-custody') + '.json')
        row = json.loads(path.read_text())
        assert row['passed'] and row['schema'] == 'FreeCAD.LOCAL_INSTALL_INDEPENDENT_AUDIT_V1'
        assert row['mode'] == mode and row['helper_sha256'] == AUDITOR_SHA
        rows[mode] = row
    payload, stage, custody = (rows[mode] for mode in ('payload', 'stage', 'custody'))
    assert payload['commit'] == stage['source_commit'] == custody['compiled_commit'] == core.COMMIT
    assert custody['compiled_revision'] == core.REVISION
    assert stage['stage_signature_verified'] is True
    assert custody['strict_signatures_quicklook_readonly_cachefree'] is True
    assert stage['sealed_stage_inventory_sha256'] == core.canonical_sha(sealed)
    assert stage['payload_audit_sha256'] == core.digest(TASK / 'independent-payload-audit.json')
    assert custody['stage_audit_sha256'] == core.digest(TASK / 'independent-stage-audit.json')
    assert custody['critical_receipt_sha256'] == core.digest(TASK / 'critical-before-DESTDIR.json')
    assert payload['payload_native_count'] == stage['native_payload_parity_count'] == custody['native_payload_count']
    assert payload['native_complete_relative_set_sha256'] == stage['native_complete_relative_set_sha256'] == custody['native_complete_relative_set_sha256']
    assert custody['baseline_and_stage_exact'] is True
    assert custody['profiles_exact_unchanged_count'] == len(core.PROFILES)
    assert custody['namespace_unchanged_count'] == len(core.NAMESPACE_FILES)
    application_gate(core.STAGE, 'stage-cmd', 2)
    application_gate(core.STAGE, 'stage-gui', 10)


core.compiled_identity = compiled_identity
core.no_live_app = run_gate.serial
core.HELPER = {'no_live_app': lambda *_: run_gate.serial()}
core.check_stage_receipts = check_stage_receipts
globals().update({key: value for key, value in vars(core).items() if not key.startswith('__')})

if __name__ == '__main__':
    assert __debug__ and sys.argv[1:] in (['stage'], ['swap'])
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, core.interrupted)
    {'stage': core.stage, 'swap': core.swap}[sys.argv[1]]()
