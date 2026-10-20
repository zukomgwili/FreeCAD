"""Root-only exact synthetic fixture retention; no FreeCAD/native execution.

There is no recursive source traversal or general profile-tree exception.
Only these twelve known software-QA inputs may be copied. Original paths in
their bytes remain literal; retention is not a new solve or repaired model.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
TASK = Path('/private/tmp/freecad-882-VGfnpo')
REPO = Path('/Users/zukomgwili/src/FreeCAD')
CASE = Path('/private/tmp/freecad-yzk-install-gTbYLA/installed-capacity/freecad_user_temp/freecad-moving-port-capacity-native-zoc2wkam/witness')
DEST = TASK / 'retained-synthetic-fixture-r01'
KNOWN = {
    'coupled-before-export.FCStd': (CASE / 'coupled-before-export.FCStd', '3128ea4b56421f21d26256088ca9f4ae5f0f985ac19024b7fa8c9dcf8fa23452'),
    'mesh-membership.json': (CASE / 'mesh-membership.json', '8f4f4d2bb4e88a225acbab5b04bda802127cc2bd42af9aad9efcb14e8da2ea44'),
    'geometry-contract.json': (CASE / 'geometry-contract.json', 'd0285f0c99c239f792f6eca63be1eb34b813ab1d08839a19fb0301aef8091911'),
    'export-properties.json': (CASE / 'export-properties.json', '19c7f44abc3de40655830db8da189c4798644d59ad16a318547471161fbdbfac'),
    'historical-witness-receipt.json': (CASE / 'witness-receipt.json', '8bf09e2a1a6d95df0020a5bdc6657c0b77ebe7a9be7c6e7f2fab2b06f90d2b69'),
    'historical-native/Mesh.inp': (CASE / 'native/Mesh.inp', '1e21fe31ee296e10a6d6c7870c0ea4d270aa6b6da5d6185083c8509e75be70d5'),
    'historical-native/Mesh.accounting': (CASE / 'native/Mesh.accounting', '59ff7b58b047b94b308e5bf5f1209dc329c6e2535b1369a8286685a151b1cdee'),
    'historical-native/Mesh.accounting.json': (CASE / 'native/Mesh.accounting.json', '1c8184bfd75aa57b1184b0fb0453a7ad2a5ed5991ac55a87ba504cd106667305'),
    'restored-volume-connectivity.json': (TASK / 'restore-observation-r01/restored-volume-connectivity.json', 'a10760248706e1f9aee3cfd6661f95700092d1b6a8fc05e4796624d801633132'),
    'restore-probe.json': (TASK / 'restore-observation-r01/restore-probe.json', '110f6da352734cd288ab8b75d1c80133b4a6de86686d4b6cd8390ab60393ae6a'),
    'coupled_port_capacity_fixture.json': (REPO / 'src/Mod/Fem/femtest/data/calculix/coupled_port_capacity_fixture.json', '9142f5aa4d149aa1f0d518a592a78638f9489fb3e245af67ea4fd463e5b8ae22'),
    'coupled_port_capacity_oracle.json': (REPO / 'src/Mod/Fem/femtest/data/calculix/coupled_port_capacity_oracle.json', '42fa6289fd9e1f80efa56db27c02c06a5454ed9880f7ca61bfd80992dfb251b8'),
}


def need(value, message):
    if not value:
        raise RuntimeError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    need(path.is_file() and not path.is_symlink(), 'Not a regular known source: ' + str(path))
    return path.read_bytes()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check-only', action='store_true')
    mode.add_argument('--retain', action='store_true')
    args = parser.parse_args()
    need(not sys.flags.optimize, 'Unoptimized interpreter required')
    need(not DEST.exists() and not DEST.is_symlink(), 'New retention directory only')
    payloads, rows = {}, []
    for name, (source, wanted) in KNOWN.items():
        data = read(source)
        need(digest(data) == wanted and len(data) <= 32 * 1024 * 1024, 'Known synthetic input changed: ' + name)
        payloads[name] = data
        rows.append({'source': str(source), 'path': name, 'sha256': wanted, 'bytes': len(data)})
    receipt = {'schema': 'FreeCAD-882-exact-synthetic-retention-v1', 'passed': True,
        'fixture_scope': 'Generic software QA only; not an engineering model or acceptance',
        'files': rows, 'source_payloads_captured_once_before_write': True,
        'originals_unchanged': True, 'copies_exact': True,
        'historical_deck_request_and_witness_are_not_a_new_physical_qualification': True,
        'no_recursive_copy_profile_environment_runtime_or_raw_solver_result_files': True,
        'no_paths_properties_statuses_or_fingerprints_rebound_or_repaired': True,
        'saved_fixture_and_mesh_retained_as_actual_bytes_not_hash_only': True,
        'replay_requires_explicit_new_configuration_not_execution_of_historical_absolute_paths': True,
        'FreeCAD_native_build_or_collector_execution': False, 'Oomakhi_accessed_or_solved': False}
    for name, (source, wanted) in KNOWN.items():
        need(digest(read(source)) == wanted, 'Known source changed before retention: ' + name)
    if args.retain:
        DEST.mkdir()
        for name, data in payloads.items():
            target = DEST / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(data)
            need(read(target) == data, 'Retained bytes differ: ' + name)
        for name, (source, wanted) in KNOWN.items():
            need(digest(read(source)) == wanted, 'Known source changed after retention: ' + name)
        with (DEST / 'retention-custody.json').open('x') as stream:
            json.dump(receipt, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write('\n')
    print(json.dumps({'passed': True, 'check_only': args.check_only, 'input_files': len(rows),
                      'writes': 0 if args.check_only else len(rows) + 1}))


if __name__ == '__main__':
    main()
