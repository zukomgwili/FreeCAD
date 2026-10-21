"""Explicit 3q7 configuration of reviewed ywu payload/signing/rollback machinery.

The immutable original installer is hash-bound. Only configuration and the
pre-swap gate catalogue are replaced. Original full-tree staging, signatures,
exact sealed-image swap and exception rollback are unchanged. No product APIs
or test physics are patched. App/profile inventories remain private.
"""
import sys
sys.dont_write_bytecode = True
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import signal

from harness_config import COMMIT, REVISION, NATIVE_SHA, NATIVE_TIE_IDS, NATIVE_MOVING_IDS
import preservation
import critical_pins

TASK = Path(__file__).resolve().parent
ORIGINAL = preservation.ORIGINAL_HELPER
preservation.require(preservation.sha(ORIGINAL) == preservation.HELPER_SHA, 'Installer changed')
spec = importlib.util.spec_from_file_location('_reviewed_ywu_install_core', ORIGINAL)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
core.ROOT = TASK
core.STAGE = TASK / core.APP.name
core.BACKUP = Path('/Users/zukomgwili/Applications/FreeCAD Backups/FreeCAD-27.1.0-before-3q7-7667033a14.app')
core.COMMIT, core.REVISION, core.NATIVE_SHA = COMMIT, REVISION, NATIVE_SHA
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

def accepted(application, label, module, total):
    directory = TASK / label
    report = json.loads((directory / 'execution.json').read_text())
    identity = json.loads((directory / 'identity.json').read_text())
    log = (directory / 'run.log').read_text()
    need = preservation.require
    need(report['passed'] is True and report['application'] == str(application)
         and report['module'] == module and report['returncode'] == 0
         and report['timed_out'] is False and report['child_reaped'] is True
         and report['process_group_gone'] is True and report['application_unchanged'] is True
         and report['app_and_profiles_unchanged'] is True
         and report['critical_dependency_pins_unchanged'] is True
         and report['source_build_harness_unchanged'] is True,
         'Application gate failed: ' + label)
    need(report['inputs_before'] == report['inputs_after']
         and all(preservation.sha(path) == wanted for path, wanted in report['inputs_after'].items()),
         'Gate inputs changed: ' + label)
    need(identity['passed'] is True and identity['runtime'][3] == REVISION
         and identity['runtime'][-1] == COMMIT
         and identity['application'] == str(application)
         and identity['source_or_build_import_override'] is False
         and identity['candidate'] == {
             'path': str(application / 'Contents/Resources/data/NativeSolvers/ccx-force-accounting'),
             'sha256': NATIVE_SHA, 'capability': 'CCX_FORCE_ACCOUNTING_V3', 'override': False},
         'Actual application identity differs: ' + label)
    need(identity['TestFemApp_count'] == 418
         and len(identity['registered_native_ids']) == 12
         and set(identity['registered_native_ids']) == set(NATIVE_TIE_IDS + NATIVE_MOVING_IDS),
         'Actual registered native catalogue differs: ' + label)
    suite = identity['selected_suite']
    need(suite['name'] == module and suite['count'] == total - 1
         and len(suite['ids']) == len(set(suite['ids'])) == total - 1
         and report['skipped_lines'] == [] and len(report['unittest_counts']) == 1
         and int(report['unittest_counts'][0][0]) == total
         and len(re.findall(r'^Ran ' + str(total) + r' tests? in [0-9.]+s$', log, re.M)) == 1
         and len(re.findall(r'^OK$', log, re.M)) == 1
         and not re.search(r'^(?:FAILED|FAIL:|ERROR:|UNEXPECTED SUCCESS)', log, re.M),
         'Actual executed tests differ: ' + label)
    need(preservation.sha(directory / 'identity.json') == report['identity_sha256']
         and preservation.sha(directory / 'run.log') == report['log_sha256'], 'Gate bytes changed')
    need(report['critical_before_DESTDIR_sha256'] == preservation.sha(TASK / 'critical-before-DESTDIR.json'),
         'Gate critical baseline is not the current captured baseline')
    need(report['manifest_unchanged'] is True
         and report['manifest_sha256'] == identity['manifest_sha256']
         == preservation.sha(directory / 'manifest.json'), 'Gate manifest is not bound to identity')
    sealed = json.loads((TASK / 'stage-inventory.json').read_text())
    custody_rows = []
    for when in ('before', 'after'):
        application_receipt = directory / ('private-application-' + when + '.json')
        custody_receipt = directory / ('private-custody-' + when + '.json')
        need(preservation.sha(application_receipt) == report['application_inventory_' + when + '_sha256']
             and json.loads(application_receipt.read_text()) == sealed,
             'Actual gate application is not the sealed stage image')
        need(preservation.sha(custody_receipt) == report['custody_' + when + '_sha256'],
             'Private custody receipt changed')
        custody_rows.append(json.loads(custody_receipt.read_text()))
    need(custody_rows[0] == custody_rows[1], 'App/profile custody changed during gate')
    return report

def check_stage_receipts(sealed):
    need = preservation.require
    core.compiled_identity()
    preservation.verify()
    critical_pins.verify()
    need(core.inventory(core.STAGE) == sealed, 'Stage changed')
    for name in ('independent-payload-audit.json', 'independent-stage-audit.json',
                 'independent-stage-custody.json'):
        need(json.loads((TASK / name).read_text())['passed'] is True, 'Missing audit: ' + name)
    audit = json.loads((TASK / 'independent-stage-audit.json').read_text())
    payload = json.loads((TASK / 'independent-payload-audit.json').read_text())
    custody = json.loads((TASK / 'independent-stage-custody.json').read_text())
    native_set = {row['relative'] for row in payload['native']}
    need(audit['source_commit'] == COMMIT
         and audit['sealed_stage_inventory_sha256'] == core.canonical_sha(sealed)
         and audit['payload_audit_sha256'] == preservation.sha(TASK / 'independent-payload-audit.json'),
         'Stage audit is not bound to this exact image')
    need(payload['commit'] == custody['compiled_commit'] == COMMIT
         and custody['compiled_revision'] == REVISION
         and len(native_set) == payload['payload_native_count'] == audit['native_payload_parity_count']
         == custody['native_payload_count']
         and native_set == {row['relative'] for row in audit['native']}
         and core.canonical_sha(sorted(native_set)) == payload['native_complete_relative_set_sha256']
         == audit['native_complete_relative_set_sha256'] == custody['native_complete_relative_set_sha256']
         and custody['stage_audit_sha256'] == preservation.sha(TASK / 'independent-stage-audit.json')
         and custody['critical_receipt_sha256'] == preservation.sha(TASK / 'critical-before-DESTDIR.json')
         and custody['profiles_exact_unchanged_count'] == len(core.PROFILES)
         and custody['namespace_unchanged_count'] == len(core.NAMESPACE_FILES)
         and custody['baseline_and_stage_exact'] is True
         and custody['strict_signatures_quicklook_readonly_cachefree'] is True,
         'Payload, stage and custody audits are not for the same complete image')
    for suffix, module, total in (
        ('fem', 'TestFemApp', 419), ('gui', 'TestFemGui', 9),
        ('native', 'femtest.app.test_moving_port_accounting_native', 9),
    ):
        accepted(core.STAGE, 'stage-' + suffix, module, total)

core.check_stage_receipts = check_stage_receipts
def reject_historical_validator(*_args, **_kwargs):
    raise RuntimeError('Historical ywu gate catalogue is not valid for 3q7; use accepted() and final installed audit')
core.check_app_receipts = reject_historical_validator
# Export the explicitly configured old module interfaces for the independent
# payload auditor and app supervisor. Preserve this adapter's __name__/__file__.
globals().update({key: value for key, value in vars(core).items() if not key.startswith('__')})

if __name__ == '__main__':
    preservation.require(not sys.flags.optimize and sys.argv[1:] in (['stage'], ['swap']),
                         'Explicit unoptimized action required')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, core.interrupted)
    {'stage': core.stage, 'swap': core.swap}[sys.argv[1]]()
