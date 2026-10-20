"""Root-only exact generic proof selection after the installed132 gate passes.

No app, solver, build, tests, signing or installation is invoked. Sixteen
known files are copied unchanged; large models/results and all other retained
inputs remain explicitly hash-only originals. No profile tree is copied.
"""
import sys
sys.dont_write_bytecode = True

import argparse
import hashlib
import json
import math
from pathlib import Path
import re


TASK = Path(__file__).resolve().parent.parent
APP = Path('/Applications/FreeCAD-27.1.0.app')
RUN = TASK / 'installed-capacity'
DESTINATION = TASK / 'installed-retained-r01'
COMMIT = '7667033a14654a9b229bf59b94cb3012ce989170'
REVISION = '49261 +224 (Git)'
CANDIDATE = '6c02452a896727af6cb4578fd3fb6bbfbdd48e3fb887c1c04fa2d8b171976c66'
NAMES = (
    'witness-receipt.json', 'independent-export-audit.json',
    'physical-face-motion-proof.json', 'motion-from-original-dat.json',
    'cold-case.json', 'geometry-contract.json', 'export-properties.json',
    'native-properties.json', 'native-accounting-data.json', 'native.stdout', 'native.stderr',
    'native/Mesh.inp', 'native/Mesh.accounting', 'native/Mesh.accounting.json',
    'native/Mesh.accounting.out', 'native/Mesh.dat',
)


def need(value, message):
    if not value:
        raise RuntimeError(message)


def regular(path):
    path = Path(path)
    need(path.is_file() and not path.is_symlink() and path.is_relative_to(TASK), str(path))
    cursor = path.parent
    while cursor != TASK:
        need(not cursor.is_symlink(), 'Ancestor link: ' + str(cursor))
        cursor = cursor.parent
    return path


def sha(path):
    with regular(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def stamp(path):
    path = regular(path)
    return {'path': str(path), 'sha256': sha(path), 'bytes': path.stat().st_size}


def read(path):
    return json.loads(regular(path).read_bytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execution-sha256', required=True)
    args = parser.parse_args()
    need(not sys.flags.optimize, 'Unoptimized interpreter required')
    need(not DESTINATION.exists() and not DESTINATION.is_symlink(), 'New selection only')
    execution_path = RUN / 'execution.json'
    execution_bytes = regular(execution_path).read_bytes()
    execution_hash = hashlib.sha256(execution_bytes).hexdigest()
    need(execution_hash == args.execution_sha256, 'Independent execution SHA differs')
    execution = json.loads(execution_bytes)
    manifest_path, identity_path = RUN / 'manifest.json', RUN / 'identity.json'
    manifest_bytes, identity_bytes = regular(manifest_path).read_bytes(), regular(identity_path).read_bytes()
    manifest_hash, identity_hash = hashlib.sha256(manifest_bytes).hexdigest(), hashlib.sha256(identity_bytes).hexdigest()
    need(manifest_hash == execution['manifest_sha256']
         and identity_hash == execution['identity_sha256'], 'Gate crosslinks differ')
    manifest, identity = json.loads(manifest_bytes), json.loads(identity_bytes)
    helper_before = stamp(Path(__file__))
    need(execution['passed'] is True and execution['application'] == str(APP)
         and execution['returncode'] == 0 and execution['timed_out'] is False
         and execution['child_reaped'] is True and execution['process_group_gone'] is True
         and execution['post_run_serial_guard_passed'] is True
         and execution['source_build_harness_unchanged'] is True
         and execution['application_unchanged'] is True and execution['app_and_profiles_unchanged'] is True
         and execution['critical_dependency_pins_unchanged'] is True
         and execution['inputs_before'] == execution['inputs_after'], 'Installed gate not qualified')
    need(identity['passed'] is True and identity['application'] == str(APP)
         and identity['runtime'][3] == REVISION and identity['runtime'][-1] == COMMIT
         and identity['candidate'] == {
             'path': str(APP / 'Contents/Resources/data/NativeSolvers/ccx-force-accounting'),
             'sha256': CANDIDATE, 'capability': 'CCX_FORCE_ACCOUNTING_V3', 'override': False}
         and manifest['application'] == str(APP) and manifest['commit'] == COMMIT
         and manifest['revision'] == REVISION and manifest['expected_count'] == 2
         and manifest['module'] == 'femtest.app.test_moving_port_capacity_native',
         'Not literal current installed132 identity')
    for path, wanted in execution['inputs_after'].items():
        # Source/build references are metadata only, never copied by this script.
        with Path(path).open('rb') as stream:
            need(hashlib.file_digest(stream, 'sha256').hexdigest() == wanted, 'Gate input changed: ' + path)
    proof = execution['capacity_witness']
    witness = Path(proof['directory'])
    need(witness.is_relative_to(RUN / 'freecad_user_temp') and witness.name == 'witness',
         'Unexpected generic witness namespace')
    receipt_path = witness / 'witness-receipt.json'
    receipt_bytes = regular(receipt_path).read_bytes()
    receipt_hash = hashlib.sha256(receipt_bytes).hexdigest()
    need(receipt_hash == proof['witness_receipt_sha256'], 'Witness receipt not bound to execution')
    receipt = json.loads(receipt_bytes)
    need('witness-receipt.json' not in receipt['retained_files'], 'Receipt cannot override its captured hash')
    need(receipt['schema'] == 'FreeCAD-native-coupled-port-coupled-native-witness-v1'
         and receipt['passed'] is True and receipt['protected_inputs_unchanged'] is True
         and receipt['physical_check_count'] == len(receipt['checks']) == 3566
         and len({row['name'] for row in receipt['checks']}) == 3566
         and all(row['passed'] is True and row['limit'] in (.01, .05)
                 and math.isfinite(row['relative_error']) and 0 <= row['relative_error'] <= row['limit']
                 for row in receipt['checks'])
         and receipt['actual_binary'] == identity['candidate']['path']
         and receipt['actual_binary_sha256'] == CANDIDATE
         and receipt['only_public_native_interfaces'] is True
         and receipt['no_deck_patches_or_mocks'] is True
         and receipt['engineering_project_accessed_or_solved'] is False
         and receipt['engineering_or_BIM_accepted'] is False
         and receipt['force_and_original_origin_moment_limit'] == .01
         and receipt['local_generalized_force_and_couple_limit'] == .01
         and receipt['scalar_response_limit'] == .05,
         'Actual installed physical proof differs')
    all_originals = {str(execution_path): execution_hash, str(manifest_path): manifest_hash,
                     str(identity_path): identity_hash, str(receipt_path): receipt_hash,
                     helper_before['path']: helper_before['sha256']}
    selected, omitted = {}, []
    for relative, expected in receipt['retained_files'].items():
        need(not Path(relative).is_absolute() and '..' not in Path(relative).parts, 'Unsafe retained path')
        path = witness / relative
        observed = stamp(path)
        need(observed['sha256'] == expected['sha256'] and observed['bytes'] == expected['bytes'],
             'Retained original changed: ' + relative)
        all_originals[str(path)] = observed['sha256']
        if relative not in NAMES:
            omitted.append(observed)
    for relative in NAMES:
        path = witness / relative
        need(path.stat().st_size <= 32 * 1024 * 1024, 'Selected generic artifact exceeds32MiB')
        selected[relative] = receipt_bytes if relative == 'witness-receipt.json' else regular(path).read_bytes()
        if relative != 'witness-receipt.json':
            expected = receipt['retained_files'][relative]
            need(len(selected[relative]) == expected['bytes']
                 and hashlib.sha256(selected[relative]).hexdigest() == expected['sha256'], 'Selection receipt binding differs')
    need(hashlib.sha256(selected['witness-receipt.json']).hexdigest() == proof['witness_receipt_sha256'],
         'Selected receipt bytes differ from parsed qualified receipt')
    accounting = json.loads(selected['native-accounting-data.json'])
    expected_capacity = {'budget': 2113, 'counts': {
        'supports': 1, 'bodies': 264, 'ports': 264, 'angles': 792, 'springs': 792}, 'total': 2113}
    need(accounting['capacity_applied'] == expected_capacity
         and accounting['capacity']['required'] == expected_capacity['counts']
         and accounting['capacity']['total'] == 2113
         and accounting['capacity']['supported']['total_records'] == 2113
         and accounting['binary'] == identity['candidate']['path']
         and accounting['binary_sha256'] == CANDIDATE, 'Actual imported2113 provenance differs')
    echoes = re.findall(r'^CCX_FORCE_ACCOUNTING_CAPACITY_APPLIED_V1 (.+)$',
                        selected['native.stdout'].decode(), re.M)
    need(len(echoes) == 1 and json.loads(echoes[0]) == expected_capacity,
         'Owned child applied-capacity echo differs')
    for path, wanted in all_originals.items():
        need(sha(path) == wanted, 'Original changed before copy: ' + path)
    DESTINATION.mkdir()
    rows = []
    for relative, payload in selected.items():
        target = DESTINATION / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(payload)
        need(sha(target) == hashlib.sha256(payload).hexdigest(), 'Selected copy differs')
        rows.append({'source': str(witness / relative), 'path': relative,
                     'sha256': sha(target), 'bytes': len(payload)})
    for path, wanted in all_originals.items():
        need(sha(path) == wanted, 'Original changed after copy: ' + path)
    need(sha(execution_path) == args.execution_sha256, 'Caller execution SHA changed after copy')
    custody = {'schema': 'FreeCAD-yzk-exact-installed-selection-v1', 'passed': True,
        'source_run_execution': {'path': str(execution_path), 'sha256': execution_hash, 'bytes': len(execution_bytes)},
        'source_run_manifest': {'path': str(manifest_path), 'sha256': manifest_hash, 'bytes': len(manifest_bytes)},
        'source_run_identity': {'path': str(identity_path), 'sha256': identity_hash, 'bytes': len(identity_bytes)},
        'source_witness_directory': str(witness),
        'files': rows, 'hash_only_originals_not_copied': omitted,
        'all_originals_unchanged': True, 'all_copies_exact': True,
        'FCStd_FRD_or_other_geometry_payloads_copied': False,
        'raw_profile_cache_or_environment_payloads_copied': False,
        'original_paths_statuses_fingerprints_rebound_or_repaired': False,
        'new_native_application_build_or_test_execution': False,
        'copy_helper': helper_before}
    with (DESTINATION / 'copy-custody.json').open('x') as stream:
        json.dump(custody, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'passed': True, 'selected_files': len(rows),
                      'hash_only_originals': len(omitted), 'custody': stamp(DESTINATION / 'copy-custody.json')}))


if __name__ == '__main__':
    main()
