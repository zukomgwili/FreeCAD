"""Retain an explicit exact-byte selection only after the owned portable run passes.

No native/app/build execution, original edits, profile copying or output repair.
Root must bind the actual completed outer execution hash at invocation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
TASK = Path(__file__).resolve().parents[1]
RUN = TASK / 'qa-v3/portable-capacity-final-r01'
WITNESS = RUN / 'freecad_user_temp/freecad-moving-port-capacity-native-xqtprwkw/witness'
NAMES = (
    'witness-receipt.json', 'independent-export-audit.json',
    'physical-face-motion-proof.json', 'motion-from-original-dat.json',
    'cold-case.json', 'geometry-contract.json', 'export-properties.json',
    'native-properties.json', 'native-accounting-data.json', 'native.stdout', 'native.stderr',
)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def regular(path):
    assert path.is_file() and not path.is_symlink(), path
    cursor = path.parent
    while cursor != TASK:
        assert cursor.is_relative_to(TASK) and not cursor.is_symlink(), cursor
        cursor = cursor.parent
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execution-sha', required=True)
    args = parser.parse_args()
    destination = TASK / 'portable-retained-r01'
    assert not destination.exists() and not destination.is_symlink()
    execution_path, manifest_path = RUN / 'execution.json', RUN / 'manifest.json'
    assert sha(regular(execution_path)) == args.execution_sha
    execution = json.loads(execution_path.read_text())
    manifest = json.loads(regular(manifest_path).read_text())
    assert sha(manifest_path) == execution['manifest_sha256']
    assert execution['passed'] and not execution['timed_out']
    assert execution['returncode'] == 0 and execution['process_group_gone']
    assert execution['child_reaped'] and execution['inputs_unchanged']
    assert execution['app_and_profiles_unchanged']
    assert execution['selected_critical_dependencies_unchanged']
    assert execution['runtime'][3] == '49261 +223 (Git)'
    assert execution['runtime'][-1] == 'cf23c61504c9a25699899a87b68571b86de37438'
    assert manifest['module'] == 'femtest.app.test_moving_port_capacity_native'
    assert manifest['expected_count'] == 2 and not manifest['unit_only']
    witness = json.loads(regular(WITNESS / 'witness-receipt.json').read_text())
    assert witness['passed'] and witness['protected_inputs_unchanged']
    assert witness['physical_check_count'] == 3566
    assert len(witness['checks']) == 3566 and all(row['passed'] for row in witness['checks'])
    assert witness['in_process_historical_reopen']['passed']
    assert not witness['in_process_historical_reopen']['separate_process_cold_claimed']
    payloads = {name: regular(WITNESS / name).read_bytes() for name in NAMES}
    before = {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()}
    for name in NAMES:
        assert sha(WITNESS / name) == before[name]
    destination.mkdir()
    rows = []
    for name, data in payloads.items():
        target = destination / name
        with target.open('xb') as stream:
            stream.write(data)
        assert sha(target) == before[name] and sha(WITNESS / name) == before[name]
        rows.append({'source': str(WITNESS / name), 'path': name,
                     'sha256': before[name], 'bytes': len(data)})
    assert sha(execution_path) == args.execution_sha
    assert sha(manifest_path) == execution['manifest_sha256']
    receipt = {
        'schema': 'FreeCAD-yzk-exact-portable-selection-v1', 'passed': True,
        'source_run_manifest': {'path': str(manifest_path), 'sha256': sha(manifest_path)},
        'source_run_execution': {'path': str(execution_path), 'sha256': args.execution_sha},
        'source_witness_directory': str(WITNESS), 'files': rows,
        'scope': 'Exact selected generic software QA proof copies, not an engineering model.',
        'all_originals_unchanged': True, 'all_copies_exact': True,
        'large_FCStd_FRD_payloads_copied': False,
        'profile_cache_or_environment_payloads_copied': False,
        'new_native_application_or_build_execution': False,
        'separate_process_cold_or_engineering_acceptance_claimed': False,
        'copy_helper': {'path': str(Path(__file__)), 'sha256': sha(__file__)},
    }
    with (destination / 'copy-custody.json').open('x') as stream:
        json.dump(receipt, stream, indent=2)
        stream.write('\n')
    print(json.dumps({'passed': True, 'files': len(rows), 'destination': str(destination),
                     'custody_sha256': sha(destination / 'copy-custody.json')}))


if __name__ == '__main__':
    main()
