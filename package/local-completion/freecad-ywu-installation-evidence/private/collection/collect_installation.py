"""Publish only root-approved YWU installation evidence after every final gate.

No product, solver, build, signing or installer process is ever launched. Every
publication input is explicitly enumerated and SHA-bound by the supplied plan.
Private inventories are read for custody comparisons only and never copied.
Stage results remain literal historical pre-swap evidence, not a fresh rerun
against an absent stage image. Current APP and rollback BACKUP are checked
separately against the stage seal and old-app baseline.
"""
import sys
sys.dont_write_bytecode = True

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat

from evidence_packet import (PRIVATE, REPOSITORY, Packet, descriptor, digest,
    json_bytes, load, read_regular, relative_path, require, source_path,
    privacy_check)


APP = Path('/Applications/FreeCAD-27.1.0.app')
STAGE = PRIVATE / APP.name
BACKUP = Path('/Users/zukomgwili/Applications/FreeCAD Backups/FreeCAD-27.1.0-before-ywu-b6b9e216c4.app')
PREFIX = REPOSITORY / '.pixi/envs/default'
BUILD = REPOSITORY / 'build/release'
COMMIT = '6cdc1affda07ac4e3b45a98097b7ae11039c80c6'
REVISION = '49261 +221 (Git)'
NATIVE_SHA = '2d59adb06736801f730de077a5f3dbfcfba8c0a430636e5814e5582606b5c89b'
NATIVE_SOURCE = {
    'forceaccounting.c': 'fb35ca4fe0ccd6f1ed1e88439c20926092a06ca32f5c21eb6c9739e52fd0dc5a',
    'hooks.patch': '28bcdb6d042b45db26c817dbb39bc04bb298c0f9a0d717fc9c1a639d0bba15ea',
    'contract.json': '4418a41794adfc386143bd94b709794eea0d9991e774ab559e714e2782730ad3',
}
SOURCE_QUALIFICATION = REPOSITORY / 'package/local-completion/freecad-ywu-validation.json'
SOURCE_QUALIFICATION_SHA = '42c6afb492ebafaeaf06ad93eeffc5d6f6dde685675a3490c84d2f18967ea5b0'
SOURCE_IMPLEMENTATION = 'fc7a359d8d56405b269c956b5709b70a5f9a8fba'
SOURCE_INDEX_SHA = 'eb8a78b36d8fbfdf5ecf66974d9d73535912f3b35415c1e20d697e47adf5ba5e'
DESTINATION = REPOSITORY / 'package/local-completion/freecad-ywu-installation-evidence'
SUMMARY_PATH = REPOSITORY / 'package/local-completion/freecad-ywu-installation.json'
ORACLES = {
    'endload': ('YwuEndLoadGreen', 24, ['ExternalSupport'],
        'd1e436011bbd452ec39453a1c61b7466b6ec7a1bef657d7c8bc1da819114660b'),
    'ordinary': ('YwuOrdinaryGreen', 26, ['FixedPatch', 'PartialAxialPatch'],
        'c8fa248d41273d3d829222c9f57cdcbc6cdf384f7077b34010eab94fd48a77c7'),
}
TIE_IDS = {'femtest.app.test_tie_accounting_native.TestTieAccountingNative.' + name for name in (
    'test_mixed_native_interfaces_keep_independent_nonzero_original_displacements',
    'test_mixed_tie_contact_bodies_preserve_paired_physical_cut_equilibrium',
    'test_nonconformal_tie_uses_native_master_surface_without_an_original_query_node',
    'test_tie_edits_fail_closed_and_saved_native_observation_remains_historical',
)}
MOVING_IDS = {'femtest.app.test_moving_port_accounting_native.TestMovingPortAccountingNative.' + name for name in (
    'test_moving_finite_rbe_ports_keep_elastic_transfer_separate_from_physical_support',
    'test_ordinary_fixed_and_partial_supports_preserve_aggregate_physical_equilibrium',
    'test_invalid_physical_support_selections_fail_at_stock_export_without_solving',
    'test_longitudinal_side_load_on_shared_cut_is_refused_without_current_accounting',
    'test_unselected_ordinary_boundary_cannot_overlap_a_selected_fixed_rbe',
)}
HELPERS = (
    'run_build_gate.py', 'process_control.py', 'harness_config.py', 'run_app.py',
    'AppYwuIdentity.py', 'stage_install.py', 'audit_payload_stage.py',
    'critical_pins.py', 'run_step.py', 'final_audit.py', 'run_legacy_v1.py',
    'YwuMovingPortWitness.py', 'YwuOrdinarySupports.py', 'YwuEndLoadGreen.py',
    'YwuOrdinaryGreen.py', 'YwuColdRestore.py', 'LOCAL-INSTALL.txt',
    'collection/collect_installation.py', 'collection/evidence_packet.py',
    'collection/verify_publication.py',
    'collection/independent_installed_audit.py',
)


def canonical_sha(value):
    return digest(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


def inventory(root):
    """Read-only capture matching the installer; never emitted in this packet."""
    require(root.is_dir() and not root.is_symlink(), f'Unsafe custody root: {root}')
    result = {'.': {'kind': 'dir', 'mode': stat.S_IMODE(root.lstat().st_mode)}}
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in sorted(dirs + files):
            path = Path(directory) / name
            mode = path.lstat().st_mode
            row = {'mode': stat.S_IMODE(mode)}
            if stat.S_ISLNK(mode):
                row.update(kind='link', target=os.readlink(path))
            elif stat.S_ISDIR(mode):
                row.update(kind='dir')
            else:
                require(stat.S_ISREG(mode), f'Nonregular custody leaf: {path}')
                row.update(kind='file', sha256=descriptor(path)['sha256'])
            result[str(path.relative_to(root))] = row
    return result


def private_path(relative):
    path = Path(relative)
    require(path.parts and not path.is_absolute() and '..' not in path.parts,
            'Unsafe private audit reference')
    output = PRIVATE / path
    require(output.resolve().is_relative_to(PRIVATE), 'Private audit reference escapes root')
    cursor = output
    while cursor != PRIVATE:
        require(not cursor.is_symlink(), 'Private audit reference traverses a symlink')
        cursor = cursor.parent
    return output


class Audit:
    def __init__(self):
        self.fences = {}
        self.required_files = set()
        self.receipts = {}
        self.sealed = None
        self.baseline = None

    def bytes(self, path, publish=False):
        path = Path(path)
        data = read_regular(path)
        key = str(path)
        require(self.fences.setdefault(key, digest(data)) == digest(data), 'Audit input changed while reading')
        if publish:
            self.required_files.add(key)
        return data

    def json(self, relative, publish=True):
        path = private_path(relative)
        data = self.bytes(path, publish)
        obj = json.loads(data)
        if publish:
            self.receipts[str(relative)] = digest(data)
        return obj

    def file_sha(self, path, publish=False):
        return digest(self.bytes(path, publish))

    def metadata_sha(self, path):
        """Resolve a historical stage image against its seal, not its old path."""
        path = Path(path)
        for root, saved in ((STAGE, self.sealed), (APP, self.sealed), (BACKUP, self.baseline)):
            if path.is_relative_to(root):
                relative = str(path.relative_to(root))
                proof = saved[relative]
                require(proof['kind'] == 'file', f'Historical image is not sealed regular file: {path}')
                return proof['sha256']
        require(path.is_relative_to(PRIVATE) or path.is_relative_to(REPOSITORY),
                f'Unapproved metadata input root: {path}')
        return self.file_sha(path)

    def check_pins(self, pins):
        require(isinstance(pins, dict) and pins, 'Empty input hash fence')
        for path, expected in pins.items():
            require(self.metadata_sha(path) == expected, f'Input SHA differs: {path}')

    def unchanged(self):
        for path, expected in self.fences.items():
            require(descriptor(path)['sha256'] == expected, f'Audited input changed: {path}')


def validate_build(audit):
    summaries = {}
    for mode in ('build', 'ctest'):
        label = mode + '-latest'
        row = audit.json(label + '/execution.json')
        require(row['passed'] and row['mode'] == mode and row['exit_code'] == 0
                and not row['timed_out'] and row['process_reaped'] and row['owned_group_gone'],
                f'Final {mode} process/custody gate failed')
        require(row['source_and_supervisor_unchanged'] and row['source_before'] == row['source_after'],
                f'Final {mode} source fence differs')
        require(row['source_after']['git_head'] == COMMIT and row['installation_performed'] is False,
                f'Final {mode} source/scope differs')
        header = row['build_after']['version_header']
        require(header['FCRepositoryHash'] == COMMIT and header['FCRevision'] == REVISION,
                'Final compiled identity differs')
        require(row['log_sha256'] == audit.file_sha(PRIVATE / label / 'run.log', True),
                f'{mode} log SHA differs')
        audit.check_pins(row['source_after']['files'])
        audit.check_pins(row['build_after']['files'])
        if mode == 'ctest':
            ct = row['ctest']
            require(ct['complete_catalogue_verified'] and
                tuple(ct[k] for k in ('catalogue', 'executed_passing', 'skipped', 'disabled', 'failed'))
                == (2274, 2264, 2, 8, 0), 'CTest catalogue/results differ')
            require(len(ct['skipped_rows']) == 2 and len(ct['disabled_rows']) == 8,
                    'CTest exclusion rows differ')
            require(row['build_before'] == row['build_after'], 'CTest changed compiled outputs')
        summaries[mode] = {'receipt_sha256': audit.receipts[label + '/execution.json'],
            'log_sha256': row['log_sha256'], 'elapsed_seconds': row['elapsed_seconds']}
    summaries['ctest']['counts'] = audit.json('ctest-latest/execution.json')['ctest']
    return summaries


def validate_transition(audit):
    audit.sealed = audit.json('stage-inventory.json', False)
    audit.baseline = audit.json('baseline-inventory.json', False)
    require(not STAGE.exists() and not STAGE.is_symlink(), 'Stage image survived final transition')
    require(inventory(APP) == audit.sealed and inventory(BACKUP) == audit.baseline,
            'APP/seal or BACKUP/baseline differs')
    profiles = audit.json('profile-inventories.json', False)
    for path, expected in profiles.items():
        require(inventory(Path(path)) == expected, 'Protected user FreeCAD profile changed')
    critical = audit.json('critical-before-DESTDIR.json', False)
    require(critical['passed'] and len(critical['files']) == 16, 'Critical dependency pin count differs')
    for name, expected in critical['files'].items():
        path = Path(name)
        info = path.lstat()
        actual = {'dev': info.st_dev, 'inode': info.st_ino, 'mode': info.st_mode,
            'size': info.st_size, 'mtime_ns': info.st_mtime_ns, 'ctime_ns': info.st_ctime_ns}
        if stat.S_ISLNK(info.st_mode):
            actual.update(kind='link', target=os.readlink(path), resolved=str(path.resolve(strict=True)),
                          resolved_sha256=descriptor(path.resolve(strict=True))['sha256'])
        else:
            require(stat.S_ISREG(info.st_mode), 'Critical nonregular input')
            actual.update(kind='file', sha256=descriptor(path)['sha256'])
        require(actual == expected, 'Selected critical dependency changed')
    namespace = audit.json('namespace-plan.json')
    require(len(namespace) == 11, 'Canonical namespace count differs')
    for relative, row in namespace.items():
        require(not Path(relative).is_absolute() and '..' not in Path(relative).parts,
                'Unsafe namespace reference')
        path = PREFIX / relative
        require(not path.is_symlink() and row['before'] == row['after'] == descriptor(path)['sha256']
                and row['mode'] == stat.S_IMODE(path.stat().st_mode), 'Namespace input changed')
    payload = audit.json('independent-payload-audit.json')
    stage = audit.json('independent-stage-audit.json')
    custody = audit.json('independent-stage-custody.json')
    require(payload['passed'] and stage['passed'] and custody['passed'], 'Historical stage audits failed')
    native_set = {row['relative'] for row in payload['native']}
    require(native_set and len(payload['native']) == len(native_set) == payload['payload_native_count'],
            'Payload native complete-set count differs')
    set_sha = canonical_sha(sorted(native_set))
    require(payload['commit'] == stage['source_commit'] == custody['compiled_commit'] == COMMIT
            and custody['compiled_revision'] == REVISION, 'Stage audit source identity differs')
    require(stage['payload_audit_sha256'] == audit.file_sha(PRIVATE / 'independent-payload-audit.json')
            and custody['stage_audit_sha256'] == audit.file_sha(PRIVATE / 'independent-stage-audit.json'),
            'Stage audit crosslink differs')
    require(all(row['native_complete_relative_set_sha256'] == set_sha for row in (payload, stage, custody)),
            'Native complete-set hash differs')
    require(stage['native_payload_parity_count'] == custody['native_payload_count'] == len(native_set)
            == len(stage['native'])
            and {row['relative'] for row in stage['native']} == native_set,
            'Native parity set differs')
    require(stage['sealed_stage_inventory_sha256'] == canonical_sha(audit.sealed)
            and stage['baseline_inventory_sha256'] == payload['baseline_inventory_sha256'] == canonical_sha(audit.baseline),
            'Historical stage seal/baseline hash differs')
    for row in stage['native']:
        require(audit.sealed['Contents/Resources/' + row['relative']]['sha256'] == row['stage_sha256'],
                'Native stage audit differs from sealed bytes')
    require(custody['baseline_and_stage_exact'] and custody['strict_signatures_quicklook_readonly_cachefree']
            and custody['profiles_exact_unchanged_count'] == len(profiles)
            and custody['namespace_unchanged_count'] == len(namespace)
            and custody['selected_critical_files_unchanged_count'] == 16
            and custody['critical_receipt_sha256'] == audit.file_sha(PRIVATE / 'critical-before-DESTDIR.json'),
            'Historical stage custody fields differ')
    require(audit.sealed['Contents/Resources/data/NativeSolvers/ccx-force-accounting']['sha256'] == NATIVE_SHA,
            'Sealed V3 native leaf differs')
    for name, sha in NATIVE_SOURCE.items():
        require(audit.file_sha(REPOSITORY / 'package/calculix/force-accounting' / name, True) == sha
                and audit.sealed['Contents/Resources/data/NativeSolvers/source/' + name]['sha256'] == sha,
                'Installed native source/contract differs')
    license_sha = audit.file_sha(REPOSITORY / 'package/calculix/force-accounting/COPYING', True)
    require(audit.sealed['Contents/Resources/data/NativeSolvers/source/COPYING']['sha256'] == license_sha,
            'Deployed native source license differs')
    audit.bytes(BUILD / 'src/Build/Version.h', True)
    require(audit.file_sha(APP / 'Contents/Resources/LOCAL-INSTALL.txt') ==
            audit.file_sha(PRIVATE / 'LOCAL-INSTALL.txt', True), 'Installed local note differs')
    return {'sealed_stage_inventory_sha256': canonical_sha(audit.sealed),
        'old_app_baseline_inventory_sha256': canonical_sha(audit.baseline),
        'native_payload_parity_count': len(native_set), 'native_relative_set_sha256': set_sha,
        'protected_user_FreeCAD_profiles_unchanged_count': len(profiles),
        'selected_critical_dependency_files_unchanged': 16, 'namespace_files_unchanged': 11,
        'stage_to_APP_exact': True, 'old_APP_to_BACKUP_exact': True,
        'private_inventory_bodies_published': False}


def validate_steps(audit):
    result = {}
    for step in ('payload', 'audit-payload', 'stage', 'audit-stage', 'audit-custody', 'swap', 'audit-installed'):
        name = 'step-' + step
        row = audit.json(name + '.json')
        require(row['passed'] and row['step'] == step and row['exit_code'] == 0 and not row['timed_out']
                and row['process_reaped'] and row['owned_processes_remaining'] == {}
                and row['critical_pins_unchanged'], f'Installation step failed: {step}')
        require(row['compiled_commit'] == COMMIT and row['compiled_revision'] == REVISION,
                'Installer compiled identity differs')
        require(row['supervisor_sha256'] == audit.file_sha(PRIVATE / 'run_step.py')
                and row['helper_inputs_before'] == row['helper_inputs_after'], 'Installer helper custody differs')
        audit.check_pins(row['helper_inputs_after'])
        require(row['critical_before_DESTDIR_sha256'] == audit.file_sha(PRIVATE / 'critical-before-DESTDIR.json'),
                'Installer critical pin receipt differs')
        log_sha = audit.file_sha(PRIVATE / (name + '.log'), True)
        result[step] = {'receipt_sha256': audit.receipts[name + '.json'],
            'log_sha256_at_collection': log_sha, 'elapsed_seconds': row['elapsed_seconds']}
    return result


def validate_app_gate(audit, location, suffix, module, count):
    application = STAGE if location == 'stage' else APP
    candidate = application / 'Contents/Resources/data/NativeSolvers/ccx-force-accounting'
    label = location + '-' + suffix
    row = audit.json(label + '/execution.json')
    identity = audit.json(label + '/identity.json')
    require(row['passed'] and row['application'] == str(application) and row['module'] == module
            and row['returncode'] == 0 and not row['timed_out']
            and row['child_reaped'] and row['process_group_gone'], f'{label} process gate failed')
    require(row['source_build_harness_unchanged'] and row['application_unchanged']
            and row['app_and_profiles_unchanged'] and row['critical_dependency_pins_unchanged']
            and row['rebound_or_reused_stage_outputs'] is False, f'{label} custody differs')
    require(row['inputs_before'] == row['inputs_after'], f'{label} input SHA fence differs')
    audit.check_pins(row['inputs_after'])
    require(row['critical_before_DESTDIR_sha256'] == audit.file_sha(PRIVATE / 'critical-before-DESTDIR.json'),
            f'{label} critical custody differs')
    require(row['identity_sha256'] == audit.file_sha(PRIVATE / label / 'identity.json')
            and row['log_sha256'] == audit.file_sha(PRIVATE / label / 'run.log', True),
            f'{label} identity/log SHA differs')
    require(identity['passed'] and identity['application'] == str(application)
            and identity['resources'] == str(application / 'Contents/Resources')
            and identity['runtime'][:3] == ['27', '1', '0']
            and identity['runtime'][3] == REVISION and identity['runtime'][-1] == COMMIT
            and identity['source_or_build_import_override'] is False, f'{label} runtime identity differs')
    require(identity['candidate'] == {'path': str(candidate), 'sha256': NATIVE_SHA,
            'capability': 'CCX_FORCE_ACCOUNTING_V3', 'override': False}, f'{label} V3 candidate differs')
    require(identity['bundled_solver'] == {'path': str(candidate), 'sha256': NATIVE_SHA,
            'capability': 'CCX_FORCE_ACCOUNTING_V3', 'preference_or_candidate_override': False},
            f'{label} default solver route differs')
    require(identity['TestFemApp_count'] == 395 and identity['gui_up'] == (suffix == 'gui'),
            f'{label} suite discovery differs')
    if suffix == 'gui':
        require(identity['TestFemGui_count'] == 8, 'GUI discovery count differs')
    require(set(identity['registered_native_tie_ids']) == TIE_IDS
            and len(identity['registered_native_ids']) == 9
            and set(identity['registered_native_ids']) == TIE_IDS | MOVING_IDS, 'Native registration differs')
    suite = identity['selected_suite']
    require(suite['name'] == module and suite['count'] == count
            and len(suite['ids']) == len(set(suite['ids'])) == count
            and identity['expected_total_count'] == count + 1, 'Selected suite differs')
    require(identity['configured_suites'] == {module: {k: v for k, v in suite.items() if k != 'name'}},
            'Configured suite differs from selected suite')
    for name in ('copied_modules', 'loaded_fem_python'):
        for proof in identity[name].values():
            require(Path(proof['origin']).is_relative_to(application / 'Contents/Resources/Mod/Fem')
                    and Path(proof['source']).is_relative_to(REPOSITORY / 'src/Mod/Fem')
                    and audit.metadata_sha(proof['origin']) == proof['sha256']
                    == audit.file_sha(proof['source']), 'Copied/loaded FEM source mismatch')
    for proof in suite['origins'].values():
        require(Path(proof['origin']).is_relative_to(application / 'Contents/Resources')
                or Path(proof['origin']).parent == PRIVATE, 'Suite origin outside qualified locations')
        require(audit.metadata_sha(proof['origin']) == proof['sha256'], 'Suite origin SHA differs')
    for proof in [identity['process_executable'], identity['app_library'], *identity['native_modules'].values()]:
        require(Path(proof['path']).is_relative_to(application / 'Contents/Resources')
                and audit.metadata_sha(proof['path']) == proof['sha256'], 'Loaded native image SHA differs')
    require(audit.file_sha(identity['version_header']['path']) == identity['version_header']['sha256'],
            'Runtime build header SHA differs')
    for when in ('before', 'after'):
        app_file = label + '/private-application-' + when + '.json'
        custody_file = label + '/private-custody-' + when + '.json'
        require(row['application_inventory_' + when + '_sha256'] == audit.file_sha(private_path(app_file))
                and audit.json(app_file, False) == audit.sealed, 'Recorded app differs from stage seal')
        require(row['custody_' + when + '_sha256'] == audit.file_sha(private_path(custody_file)),
                'Private custody capture SHA differs')
    before = audit.json(label + '/private-custody-before.json', False)
    require(before == audit.json(label + '/private-custody-after.json', False), 'Protected custody changed during gate')
    require(before[str(APP)] == (audit.baseline if location == 'stage' else audit.sealed),
            'Historical protected APP transition differs')
    profiles = audit.json('profile-inventories.json', False)
    require({k: v for k, v in before.items() if k != str(APP)} == profiles, 'Protected profile set differs')
    text = audit.bytes(PRIVATE / label / 'run.log').decode()
    counts = re.findall(r'^Ran (\d+) tests? in ([\d.]+)s\s*$', text, re.M)
    require(row['unittest_counts'] == [list(value) for value in counts]
            and len(counts) == 1 and int(counts[0][0]) == count + 1
            and row['skipped_lines'] == [] and not re.search(r'\.\.\. skipped ', text)
            and len(re.findall(r'^OK\s*$', text, re.M)) == 1
            and not re.search(r'^(FAILED\b|FAIL:|ERROR:|UNEXPECTED SUCCESS:)', text, re.M),
            'Verbose unittest result/count differs')
    expected_ids = TIE_IDS | MOVING_IDS if suffix == 'fem' else (MOVING_IDS if suffix == 'native' else set())
    require(expected_ids.issubset(suite['ids']), 'Native methods absent from selected suite')
    if suffix == 'native':
        require(set(suite['ids']) == MOVING_IDS, 'Native-only selection differs')
    for test_id in expected_ids:
        pattern = '^' + re.escape(test_id.rsplit('.', 1)[-1]) + r' \(' + re.escape(test_id) + r'\)([^\n]*)$'
        hits = re.findall(pattern, text, re.M)
        require(len(hits) == 1 and 'skipped' not in hits[0], 'Native method missing/skipped/duplicated')
    return {'receipt_sha256': audit.receipts[label + '/execution.json'],
        'identity_sha256': row['identity_sha256'], 'log_sha256': row['log_sha256'],
        'product_test_count': count, 'identity_test_count': 1, 'total_tests': count + 1,
        'executed_registered_native_ids': sorted(expected_ids), 'elapsed_seconds': row['elapsed_seconds']}


def norm_checks(checks, expected_count):
    require(len(checks) == expected_count and len({row['name'] for row in checks}) == expected_count,
            'Comparison count/unique names differ')
    for row in checks:
        actual, reference = row['actual'], row['reference']
        require(len(actual) == len(reference) == 3 and
                all(math.isfinite(v) for v in actual + reference), 'Nonfinite/non-vector comparison')
        error, norm = math.dist(actual, reference), math.hypot(*reference)
        require(math.isfinite(row['scale']) and row['scale'] > 0 and row['limit'] == 0.01,
                'Fixed normalization/acceptance differs')
        if norm:
            require(math.isclose(row['scale'], norm, rel_tol=1e-12, abs_tol=1e-14), 'Nonzero reference scale differs')
        for value, wanted in ((row['error_norm'], error), (row['reference_norm'], norm),
                              (row['relative_error'], error / row['scale'])):
            require(math.isfinite(value) and math.isclose(value, wanted, rel_tol=1e-12, abs_tol=1e-14),
                    'Recorded norm calculation differs')
        require(row['passed'] and 0 <= row['relative_error'] <= 0.01, 'Physical comparison failed')
    return max(row['relative_error'] for row in checks)


def validate_witness(audit, location, kind):
    module, checks, supports, oracle_sha = ORACLES[kind]
    gate = validate_app_gate(audit, location, kind, module, 1)
    label = location + '-' + kind
    witness_dir = PRIVATE / label / 'witness'
    witness = audit.json(label + '/witness/witness-receipt.json')
    candidate = (STAGE if location == 'stage' else APP) / 'Contents/Resources/data/NativeSolvers/ccx-force-accounting'
    require(witness['passed'] and witness['actual_binary'] == str(candidate)
            and witness['actual_binary_sha256'] == NATIVE_SHA and witness['solver_returncode'] == 0
            and witness['only_public_native_interfaces'] and witness['no_deck_patches_or_mocks']
            and witness['Oomakhi_opened_or_solved'] is False, 'Fresh public native witness failed')
    gate['physical_comparisons'] = len(witness['checks'])
    gate['maximum_relative_error'] = norm_checks(witness['checks'], checks)
    require(witness['frozen_independent_oracle'] == str(PRIVATE / (kind + '-oracle.json'))
            and witness.get('frozen_independent_oracle_sha256', witness.get('oracle_sha256')) == oracle_sha
            == audit.file_sha(PRIVATE / (kind + '-oracle.json'), True), 'Frozen independent oracle differs')
    current = witness['current_native_report']
    require(current['status'].startswith('Current') and current['schema'] == 'CCX_FORCE_ACCOUNTING_V3'
            and current['movement_status'] == 'BOUND', 'Positive witness native state differs')
    for relative, proof in witness['retained_files'].items():
        path = witness_dir / relative_path(relative)
        require(path.is_relative_to(witness_dir) and audit.file_sha(path) == proof['sha256']
                and path.stat().st_size == proof['bytes'], 'Retained witness file differs')
    manifest_path = witness_dir / 'cold-case.json'
    require(witness['cold_manifest'] == str(manifest_path)
            and witness['cold_manifest_sha256'] == audit.file_sha(manifest_path), 'Cold manifest crosslink differs')
    manifest = audit.json(str(manifest_path.relative_to(PRIVATE)))
    require(manifest['schema'] == 'FreeCAD-ywu-native-cold-case-v1'
            and manifest['binary'] == str(candidate) and manifest['binary_sha256'] == NATIVE_SHA
            and manifest['explicit_supports'] == supports and manifest['no_cold_restore_performed_yet']
            and manifest['no_history_or_provenance_repair'] and manifest['saved_status_literal'].startswith('Current'),
            'Literal saved native history differs')
    data = json.loads(manifest['accounting_data_literal'])
    require(data['schema'] == 'CCX_FORCE_ACCOUNTING_V3' and data['binary'] == str(candidate)
            and data['movement_source'] == manifest['movement_source_literal']
            and data['movement_source']['status'] == 'BOUND', 'Saved literal native payload differs')
    document = Path(manifest['document'])
    require(document.parent == witness_dir and document.suffix == '.FCStd'
            and manifest['document_sha256'] == audit.file_sha(document, True), 'Saved generic document differs')
    require(set(manifest['source_files']) == {'deck', 'request', 'native_output', 'frd', 'dat'},
            'Required five generic cold source files differ')
    for proof in manifest['source_files'].values():
        path = Path(proof['path'])
        require(path.is_relative_to(witness_dir) and audit.file_sha(path, True) == proof['sha256'],
                'Cold source file input differs')
    cold = validate_app_gate(audit, location, kind + '-cold', 'YwuColdRestore', 1)
    restore = audit.json(label + '-cold/cold-receipt.json')
    require(restore['passed'] and restore['manifest'] == str(manifest_path)
            and restore['manifest_sha256'] == audit.file_sha(manifest_path)
            and restore['no_native_solve'] and restore['no_history_or_provenance_repair']
            and restore['status'].startswith('Stale after restore') and restore['supports'] == supports
            and restore['accounting_data_sha256'] == digest(manifest['accounting_data_literal'].encode()),
            'Cold result was promoted, rebound, solved or repaired')
    gate.update(witness_receipt_sha256=audit.receipts[label + '/witness/witness-receipt.json'],
                cold_manifest={'path': str(manifest_path), 'sha256': audit.file_sha(manifest_path)})
    cold.update(cold_receipt_sha256=audit.receipts[label + '-cold/cold-receipt.json'],
                saved_history_remains_Stale=True, no_native_solve_or_provenance_repair=True)
    return gate, cold


def validate_legacy_v2(audit, location):
    root = PRIVATE / (location + '-v2')
    summary = audit.json(location + '-v2/summary.json')
    manifest = audit.json(location + '-v2/manifest.json')
    candidate = (STAGE if location == 'stage' else APP) / 'Contents/Resources/data/NativeSolvers/ccx-force-accounting'
    require(summary['all_selected_passed'] and summary['candidate'] == str(candidate)
            and summary['candidate_sha256'] == NATIVE_SHA
            and summary['manifest_sha256'] == audit.file_sha(root / 'manifest.json'), 'V2 manifest/candidate differs')
    reports = summary['reports']
    require(len(summary['selected_cases']) == len(set(summary['selected_cases'])) == len(reports) == 10
            and set(summary['selected_cases']) == {row['case'] for row in reports}, 'V2 case selection differs')
    refusal_count, positive_count, check_count = 0, 0, 0
    for row in reports:
        case_dir = root / relative_path(row['case'])
        require(row['passed'] and row['candidate'] == str(candidate) and row['candidate_sha256'] == NATIVE_SHA
                and row['protected_inputs_unchanged'] and row['child_reaped'] and row['process_group_gone']
                and not row['timed_out'] and row['custody_before'] == row['custody_after'], 'V2 process/custody failed')
        require(audit.json(str((case_dir / 'execution.json').relative_to(PRIVATE))) == row
                and row['solver_log_sha256'] == audit.file_sha(case_dir / 'solver.log', True), 'V2 receipt/log differs')
        declared = [case for case in manifest['cases'] if case['name'] == row['case']]
        require(len(declared) == 1 and declared[0]['directory'] == str(case_dir), 'V2 case declaration differs')
        paths = {'candidate': candidate, 'script': Path(manifest['script']), 'generator': Path(manifest['generator']),
                 'process_control': Path(manifest['process_control']), 'deck': case_dir / 'contact.inp',
                 'request': case_dir / 'contact.accounting'}
        require(row['custody_after'] == {k: audit.metadata_sha(v) for k, v in paths.items()}, 'V2 exact input pins differ')
        for name in ('deck', 'request'):
            require(declared[0][name] == str(paths[name])
                    and declared[0][name + '_sha256'] == row['custody_after'][name], 'V2 deck/request hash differs')
        if row.get('expected_domain_refusal'):
            refusal_count += 1
            require(row['returncode'] == 201 and row['native_output_sha256'] is None, 'V2 refusal differs')
        else:
            positive_count += 1
            require(row['returncode'] == 0, 'V2 positive process failed')
            output = case_dir / 'contact.accounting.out'
            require(audit.file_sha(output) == row['native_output_sha256'], 'V2 native output hash differs')
            lines = audit.bytes(output).decode().splitlines()
            require(lines[0] == 'CCX_FORCE_ACCOUNTING_V2' and lines[-1] == 'END', 'V2 literal envelope differs')
            require(len(row['checks']) == 18 and len({(item['identity'], item['meaning'])
                    for item in row['checks']}) == 18, 'V2 comparison count differs')
            for item in row['checks']:
                actual, reference = item['actual'], item['reference']
                require(len(actual) == len(reference) == 3 and
                        all(math.isfinite(v) for v in actual + reference), 'Nonfinite V2 comparison')
                denominator = max(1.0, math.hypot(*reference))
                error = math.dist(actual, reference) / denominator
                require(math.isclose(item['denominator'], denominator, rel_tol=1e-12, abs_tol=1e-14)
                        and item['limit'] == 0.01 and item['passed']
                        and math.isfinite(item['relative_error']) and 0 <= item['relative_error'] <= 0.01
                        and math.isclose(item['relative_error'], error, rel_tol=1e-12, abs_tol=1e-14),
                        'V2 fixed physical norm comparison differs')
            check_count += len(row['checks'])
    require((positive_count, refusal_count, check_count) == (8, 2, 144), 'Legacy V2 corpus/count differs')
    return {'summary_sha256': audit.receipts[location + '-v2/summary.json'],
        'manifest_sha256': summary['manifest_sha256'], 'positive_cases': positive_count,
        'expected_refusals': refusal_count, 'physical_norm_checks': check_count,
        'request_output_schema': 'CCX_FORCE_ACCOUNTING_V2', 'executable_capability': 'CCX_FORCE_ACCOUNTING_V3'}


def validate_legacy_v1(audit, location):
    root = PRIVATE / (location + '-v1')
    top = audit.json(location + '-v1/qualification.json')
    manifest = audit.json(location + '-v1/manifest.json')
    candidate = (STAGE if location == 'stage' else APP) / 'Contents/Resources/data/NativeSolvers/ccx-force-accounting'
    require(top['passed'] and top['schema'] == 'CCX_FORCE_ACCOUNTING_V1'
            and top['binary'] == manifest['binary'] == str(candidate) and top['binary_sha256'] == NATIVE_SHA
            and top['manifest_sha256'] == audit.file_sha(root / 'manifest.json')
            and top['all_children_reaped'] and top['all_inputs_unchanged'], 'Legacy V1 top qualification differs')
    require(top['protected'] == manifest['protected'], 'Legacy V1 declaration custody differs')
    audit.check_pins(top['protected'])
    positives, negatives = top['analytic_cases'], top['rejections']
    require(len(positives) == top['positive_cases'] == 48 and len(negatives) == top['expected_refusals'] == 6
            and top['physical_norm_checks'] == 288, 'V1 corpus counts differ')
    require(len({row['case'] for row in positives + negatives}) == 54
            and {row['case'] for row in positives + negatives} == {row['case'] for row in manifest['cases']},
            'V1 case selection differs')
    for row in positives + negatives:
        directory = root / relative_path(row['case'])
        require(row['passed'] and row['inputs_unchanged'] and row['protected_unchanged'] and row['manifest_unchanged']
                and row['child_reaped'] and row['process_group_gone'] and not row['timed_out']
                and row['protected_before'] == row['protected_after'] == top['protected'], 'V1 process/custody failed')
        require(audit.json(str((directory / 'execution.json').relative_to(PRIVATE))) == row
                and audit.file_sha(directory / 'solver.log', True) == row['log_sha256'], 'V1 receipt/log differs')
        declared = [case for case in manifest['cases'] if case['case'] == row['case']]
        require(len(declared) == 1 and declared[0]['inputs'] == row['inputs_before'] == row['inputs_after']
                and set(row['inputs_after']) == {'contact.inp', 'contact.accounting', 'oracle.json'}, 'V1 input declaration differs')
        for name, sha in row['inputs_after'].items():
            require(audit.file_sha(directory / name) == sha, 'V1 input SHA differs')
        for name, sha in row['outputs'].items():
            require(Path(name).name == name and audit.file_sha(directory / name) == sha, 'V1 output SHA differs')
        if row['positive']:
            require(row['returncode'] == 0 and row['physical_norm_checks'] == 6, 'V1 positive failed')
            errors = row['relative_force_moment_errors']
            require(len(errors) == 3 and all(len(pair) == 2 and all(math.isfinite(e) and 0 <= e <= 0.01
                    for e in pair) for pair in errors.values()), 'V1 physical norm comparison failed')
            lines = audit.bytes(directory / 'contact.accounting.out').decode().splitlines()
            require(lines[0] == 'CCX_FORCE_ACCOUNTING_V1' and lines[-1] == 'END', 'V1 literal output envelope differs')
        else:
            oracle = json.loads(audit.bytes(directory / 'oracle.json'))
            require(row['returncode'] == 201 and row['complete_accounting_envelope'] is False
                    and row['diagnostic'] == oracle['diagnostic']
                    and row['diagnostic'] in audit.bytes(directory / 'solver.log').decode(), 'V1 refusal differs')
    return {'qualification_sha256': audit.receipts[location + '-v1/qualification.json'],
        'manifest_sha256': top['manifest_sha256'], 'positive_cases': len(positives),
        'expected_refusals': len(negatives), 'physical_norm_checks': top['physical_norm_checks'],
        'request_output_schema': 'CCX_FORCE_ACCOUNTING_V1', 'executable_capability': 'CCX_FORCE_ACCOUNTING_V3'}


def validate_final_audit(audit, locations, transition, build):
    final = audit.json('final-audit.json')
    require(final['schema'] == 'FreeCAD-ywu-installed-audit-v1' and final['passed']
            and final['source_commit'] == COMMIT and final['compiled_revision'] == REVISION
            and final['application'] == str(APP) and final['backup'] == str(BACKUP), 'Final installation audit identity differs')
    require(final['application_inventory_sha256'] == transition['sealed_stage_inventory_sha256']
            and final['backup_inventory_sha256'] == transition['old_app_baseline_inventory_sha256']
            and final['native_payload_parity'] == transition['native_payload_parity_count']
            and final['native_V3_sha256'] == NATIVE_SHA, 'Final audit payload binding differs')
    require(final['strict_signatures_valid'] and final['quicklook_entitlements_preserved']
            and final['readonly_cachefree_resources'] and final['critical_dependency_records_unchanged'] == 16
            and final['profiles_unchanged'] == transition['protected_user_FreeCAD_profiles_unchanged_count']
            and final['namespace_files_unchanged'] == 11, 'Final audit custody/deployment fields differ')
    require(final['Oomakhi_opened_modified_or_solved'] is False and final['engineering_or_BIM_accepted'] is False
            and final['production_geometry_loads_sampling_and_other_acceptance_limits_changed'] is False
            and final['force_origin_moment_acceptance_limit_unchanged'] == 0.01
            and final['displacement_acceptance_limit_percent_unchanged'] == 5, 'Engineering holds changed')
    require(final['ctest'] == build['ctest']['counts'] and final['Pixi_environment_still_required'] == str(PREFIX),
            'Final audit CTest/dependency scope differs')
    for location in ('stage', 'installed'):
        original = final['locations'][location]
        require(original['application_at_execution'] == locations[location]['application_at_execution'],
                'Final audit historical location differs')
        for suffix, gate in locations[location]['gates'].items():
            for key in ('receipt_sha256', 'identity_sha256', 'log_sha256', 'total_tests'):
                require(original['gates'][suffix][key] == gate[key], 'Final audit gate crosslink differs')
        require(original['legacy_v1_qualification_sha256'] == locations[location]['legacy_v1']['qualification_sha256']
                and original['legacy_v2_summary_sha256'] == locations[location]['legacy_v2']['summary_sha256'],
                'Final audit legacy crosslink differs')
    return final


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    require(not sys.flags.optimize, 'Do not optimize away audit assertions')
    plan_path = args.plan.resolve(strict=True)
    require(plan_path.parent == PRIVATE / 'collection' and not args.plan.is_symlink(), 'Plan must be a private collection file')
    plan_bytes = read_regular(plan_path)
    require(digest(plan_bytes) == args.plan_sha256, 'Root-approved plan SHA differs')
    plan = json.loads(plan_bytes)
    require(set(plan).issubset({'schema', 'source_commit', 'compiled_revision', 'independent_audit', 'files', 'notes'})
            and plan['schema'] == 'FreeCAD-ywu-installation-publication-plan-v1'
            and plan['source_commit'] == COMMIT and plan['compiled_revision'] == REVISION,
            'Unexpected root publication plan')
    privacy_check(plan, 'explicit publication plan')
    require(isinstance(plan['files'], list) and plan['files'], 'Explicit root file allowlist is required')
    audit = Audit()
    transition = validate_transition(audit)
    build = validate_build(audit)
    steps = validate_steps(audit)
    locations = {}
    for location, application in (('stage', STAGE), ('installed', APP)):
        gates = {}
        for suffix, module, count in (('fem', 'TestFemApp', 395), ('gui', 'TestFemGui', 8),
                ('native', 'femtest.app.test_moving_port_accounting_native', 5)):
            gates[suffix] = validate_app_gate(audit, location, suffix, module, count)
        for kind in ORACLES:
            gates[kind], gates[kind + '-cold'] = validate_witness(audit, location, kind)
        locations[location] = {'application_at_execution': str(application), 'gates': gates,
            'legacy_v1': validate_legacy_v1(audit, location), 'legacy_v2': validate_legacy_v2(audit, location)}
    final = validate_final_audit(audit, locations, transition, build)
    independent_ref = plan['independent_audit']
    require(set(independent_ref) == {'path', 'sha256'}, 'Unexpected independent audit reference')
    independent = audit.json(independent_ref['path'])
    require(audit.file_sha(private_path(independent_ref['path'])) == independent_ref['sha256'],
            'Independent installed audit SHA differs')
    require(independent['schema'] == 'FreeCAD-ywu-independent-installed-audit-v1' and independent['passed']
            and independent['source_commit'] == COMMIT and independent['revision'] == REVISION
            and independent['application'] == str(APP) and independent['backup'] == str(BACKUP)
            and independent['final_audit_sha256'] == audit.file_sha(PRIVATE / 'final-audit.json'),
            'Independent installed audit identity differs')
    require(all(independent[name] is True for name in ('installed_app_equals_sealed_stage', 'backup_equals_baseline',
            'protected_profiles_unchanged', 'selected_critical_files_unchanged')), 'Independent custody audit failed')
    independent_required = {path for path in audit.receipts
        if path.startswith(('stage-', 'installed-')) or path in
        ('final-audit.json', 'ctest-latest/execution.json', 'step-swap.json')}
    # Namespace plan and raw inventory captures are not independent execution
    # receipts; their bodies stay private, and their seal is checked separately.
    independent_required -= {'stage-inventory.json'}
    require(independent_required <= set(independent['reports']),
            'Independent installed audit does not cover all workflow receipts')
    for path, sha in independent['reports'].items():
        require(audit.file_sha(private_path(path)) == sha, 'Independent audit report crosslink differs')
    require(audit.file_sha(SOURCE_QUALIFICATION, True) == SOURCE_QUALIFICATION_SHA,
            'Existing source qualification changed')
    source_summary = json.loads(audit.bytes(SOURCE_QUALIFICATION))
    # Retain the original +220 source qualification, not relabel it as +221 app QA.
    require(source_summary['passed'] and source_summary['compiled_commit'] == SOURCE_IMPLEMENTATION
            and source_summary['compiled_revision'] == '49261 +220 (Git)'
            and source_summary['evidence']['index_sha256'] == SOURCE_INDEX_SHA,
            'Source qualification implementation/index binding differs')
    for helper in HELPERS:
        audit.bytes(private_path(helper), True)
    packet = Packet()
    approved_paths = set()
    for entry in plan['files']:
        path = source_path(entry['scope'], entry['path'])
        require(str(path) not in approved_paths, 'Duplicate source in explicit file allowlist')
        approved_paths.add(str(path))
        packet.add(entry)
    require(audit.required_files <= approved_paths, 'Required workflow files missing from explicit allowlist: ' +
            ', '.join(sorted(audit.required_files - approved_paths)))
    packet.add({'scope': 'private', 'path': str(plan_path.relative_to(PRIVATE)),
        'destination': 'collection/root-approved-install-plan.json', 'sha256': args.plan_sha256,
        'kind': 'receipt', 'classification': 'Explicit root-approved publication allowlist; not a product QA execution'})
    audit.unchanged()
    packet.unchanged()
    index = {'schema': 'FreeCAD-ywu-installation-evidence-index-v1',
        'source_bead': 'FreeCAD-ywu', 'installation_bead': 'FreeCAD-3je',
        'source_commit': COMMIT, 'compiled_revision': REVISION,
        'scope': 'Host-local software installation evidence; not engineering acceptance',
        'root_approved_plan': {'path': str(plan_path), 'sha256': args.plan_sha256},
        'files': sorted(packet.records, key=lambda row: row['file'])}
    summary = {'schema': 'FreeCAD-ywu-host-local-installation-v1', 'passed': True,
        'installation_bead': 'FreeCAD-3je', 'source_bead': 'FreeCAD-ywu',
        'source_commit': COMMIT, 'compiled_revision': REVISION,
        'application': str(APP), 'rollback_backup': str(BACKUP),
        'previous_source_qualification': {'path': str(SOURCE_QUALIFICATION), 'sha256': SOURCE_QUALIFICATION_SHA,
            'implementation_commit': SOURCE_IMPLEMENTATION, 'compiled_revision': '49261 +220 (Git)',
            'index_sha256': SOURCE_INDEX_SHA, 'not_relabelled_as_installed_qualification': True},
        'native': {'capability': 'CCX_FORCE_ACCOUNTING_V3', 'sha256': NATIVE_SHA,
            'source_and_contract_sha256': NATIVE_SOURCE, 'preference_or_candidate_override': False},
        'build_and_ctest': build, 'installation_steps': steps, 'custody_transition': transition,
        'qualification_locations': locations,
        'historical_stage_semantics': 'Pre-swap executions were validated before rename by the SHA-bound installer checker and retained receipts/seal. The old stage image is now APP; these are not newly executed or rebound stage tests.',
        'installed_semantics': 'All installed gates used literal APP and fresh per-location native outputs, manifests and saved documents. Cold results remain literal historical Stale records, not promoted to Current.',
        'final_audit': {'path': str(PRIVATE / 'final-audit.json'), 'sha256': audit.file_sha(PRIVATE / 'final-audit.json')},
        'independent_installed_audit': independent_ref,
        'deployment_limits': {'Pixi_environment_still_required': str(PREFIX), 'self_contained': False,
            'notarized': False, 'host_local_ad_hoc_signature': True,
            'strict_signatures_verified_by_final_audit': final['strict_signatures_valid'],
            'quicklook_entitlements_preserved': final['quicklook_entitlements_preserved'],
            'readonly_cachefree_resources': final['readonly_cachefree_resources'],
            'dependency_inventory_scope': '16 selected critical files only, not the whole Pixi environment',
            'user_preferences_or_material_libraries_migrated': False},
        'engineering_holds': {'engineering_or_BIM_design_accepted': False,
            'Oomakhi_opened_altered_or_solved_for_this_installation': False,
            'original_side_loaded_fixture_inputs_rewritten': False,
            'separate_predeclared_end_loading_and_support_cases': True,
            'force_and_original_origin_moment_relative_limit_unchanged': 0.01,
            'displacement_limit_percent_unchanged': 5,
            'R49_existing_failed_percent': final['R49_existing_failed_percent'],
            'R51_existing_failed_percent': final['R51_existing_failed_percent'],
            'existing_engineering_failures_not_relabelled_as_passed': True},
        'evidence': {'index_path': str(DESTINATION / 'index.json'), 'index_sha256': digest(json_bytes(index)),
            'indexed_file_count': len(packet.records), 'root_approved_plan_sha256': args.plan_sha256,
            'exact_byte_files': sum(row['transformation'] == 'exact bytes' for row in packet.records),
            'explicit_curated_excerpts': sum(row['transformation'] != 'exact bytes' for row in packet.records),
            'deterministic_gzip_files': sum(row['encoding'] == 'gzip' for row in packet.records),
            'no_raw_private_profiles_inventories_runtime_binaries_or_vendor_tree': True}}
    privacy_check(index, 'publication index')
    privacy_check(summary, 'publication summary')
    require(not DESTINATION.exists() and not SUMMARY_PATH.exists(), 'New-only publication targets already exist')
    audit.unchanged()
    if not args.check_only:
        packet.publish_new(DESTINATION, SUMMARY_PATH, index, summary)
    print(json.dumps({'passed': True, 'check_only': args.check_only,
        'writes': 0 if args.check_only else len(packet.records) + 2,
        'indexed_files': len(packet.records), 'index_sha256': digest(json_bytes(index)),
        'summary_sha256': digest(json_bytes(summary)), 'compiled_revision': REVISION,
        'source_commit': COMMIT, 'no_native_or_product_process_launched': True}, indent=2))


if __name__ == '__main__':
    main()
