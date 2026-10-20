"""Explicit NONPHYSICAL parser-only capacity probe; not a positive graph test.

Root reviews/prepares, freezes the manifest SHA, then runs separately. The
original published stock deck/request are never altered. Three real PORT rows
plus62 unique placeholder rows test cardinality65; placeholders are NOT native
RBE receiving regions. A capacity refusal says nothing about physical validity.
"""
import sys
sys.dont_write_bytecode = True
import argparse
import hashlib
import json
import os
from pathlib import Path
import re

import run_repro as helpers
from process_control import assert_serial, run_bounded

ROOT = Path(__file__).resolve().parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
APP = Path('/Applications/FreeCAD-27.1.0.app')
BINARY = APP / 'Contents/Resources/data/NativeSolvers/ccx-force-accounting'
NATIVE_SHA = '2d59adb06736801f730de077a5f3dbfcfba8c0a430636e5814e5582606b5c89b'
PUBLISHED = REPO / 'package/local-completion/freecad-ywu-installation-evidence/private'
SOURCE = PUBLISHED / 'installed-endload/witness/native'
DECK_SHA = 'b538e11e55f35b5f4638f6d58468d069edb7d44ca570d16276dbee5ef55465f2'
REQUEST_SHA = 'b435fca83da49a27796867b51562cdcff38accf84b0840d8d0cb7fa66dbb751c'
sha, write, inventory = helpers.sha, helpers.write, helpers.inventory


def current_inputs():
    result = helpers.inputs()
    for path in (Path(__file__), SOURCE / 'Mesh.inp', SOURCE / 'Mesh.accounting',
                 PUBLISHED / 'final-audit.json', BINARY):
        result[str(path)] = sha(path)
    assert result[str(SOURCE / 'Mesh.inp')] == DECK_SHA
    assert result[str(SOURCE / 'Mesh.accounting')] == REQUEST_SHA
    assert result[str(BINARY)] == NATIVE_SHA
    return result


def protected():
    paths = [APP, Path('/Users/zukomgwili/Library/Application Support/FreeCAD'),
             Path('/Users/zukomgwili/Library/Application Support/FreeCAD Local'),
             Path('/Users/zukomgwili/Library/Preferences/FreeCAD')]
    return {str(path): inventory(path) for path in paths if path.is_dir()}


def prepare(directory):
    assert not directory.exists()
    pins = current_inputs()
    state = protected()
    old = json.loads((PUBLISHED / 'final-audit.json').read_text())
    canonical = hashlib.sha256(json.dumps(state[str(APP)], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert old['passed'] and old['source_commit'] == '6cdc1affda07ac4e3b45a98097b7ae11039c80c6'
    assert old['compiled_revision'] == '49261 +221 (Git)' and old['native_V3_sha256'] == NATIVE_SHA
    assert canonical == old['application_inventory_sha256']
    deck = (SOURCE / 'Mesh.inp').read_bytes()
    assert not re.search(rb'^\*INCLUDE\b', deck, re.M | re.I)
    original = (SOURCE / 'Mesh.accounting').read_bytes()
    lines = original.decode().splitlines()
    assert lines[0] == 'CCX_FORCE_ACCOUNTING_V3' and lines[-1] == 'END'
    real_ports = [line for line in lines if line.startswith('PORT ')]
    assert len(real_ports) == 3
    placeholders = [f'PORT ParserOnly{index + 1:03d} {2 * index + 1} {2 * index + 2}' for index in range(62)]
    request = ('\n'.join([lines[0], *real_ports, *placeholders,
                          *(line for line in lines[1:] if not line.startswith('PORT '))]) + '\n').encode()
    directory.mkdir()
    for name, data in (('Mesh.inp', deck), ('Mesh.accounting', request),
                       ('original-stock-request.accounting', original)):
        with (directory / name).open('xb') as stream:
            stream.write(data)
    write(directory / 'private-custody-before.json', state)
    manifest = {'schema': 'FreeCAD-yzk-NONPHYSICAL-parser-capacity-only-v1',
                'physical_graph_qualified': False, 'fresh_stock_export_performed': False,
                'request_modified_for_parser_probe_only': True, 'original_request_unchanged': True,
                'real_original_PORT_rows': 3, 'placeholder_PORT_rows': 62, 'total_PORT_rows': 65,
                'placeholder_warning': 'Original mesh IDs1..124 are used only as unique parser integers, NOT qualified RBE reference/rotation IDs.',
                'native_binary': str(BINARY), 'native_binary_sha256': NATIVE_SHA,
                'source_commit': old['source_commit'], 'compiled_revision': old['compiled_revision'],
                'source_deck_sha256': DECK_SHA, 'source_request_sha256': REQUEST_SHA,
                'copied_deck_sha256': sha(directory / 'Mesh.inp'),
                'parser_request_sha256': sha(directory / 'Mesh.accounting'),
                'inputs': pins, 'private_custody_sha256': sha(directory / 'private-custody-before.json'),
                'Oomakhi_opened_or_solved': False}
    write(directory / 'manifest.json', manifest)
    print(json.dumps({'prepared_parser_only': True, 'directory': str(directory),
                      'manifest_sha256': sha(directory / 'manifest.json')}, indent=2))


def run(directory, manifest_sha):
    assert manifest_sha and sha(directory / 'manifest.json') == manifest_sha
    manifest = json.loads((directory / 'manifest.json').read_text())
    assert current_inputs() == manifest['inputs']
    assert sha(directory / 'Mesh.inp') == manifest['copied_deck_sha256'] == DECK_SHA
    assert sha(directory / 'Mesh.accounting') == manifest['parser_request_sha256']
    assert sha(directory / 'original-stock-request.accounting') == REQUEST_SHA
    assert sha(directory / 'private-custody-before.json') == manifest['private_custody_sha256']
    before = json.loads((directory / 'private-custody-before.json').read_text())
    assert protected() == before
    environment = dict(os.environ)
    for key in list(environment):
        if key.startswith(('FREECAD_', 'CCX_', 'APPQA_', 'YWU_', 'YZK_', 'FIVEAR_')) or key in (
                'PYTHONHOME', 'PYTHONPATH', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
            environment.pop(key)
    for key in ('FREECAD_USER_HOME', 'FREECAD_USER_DATA', 'FREECAD_USER_TEMP',
                'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
        path = directory / key.lower()
        path.mkdir()
        environment[key] = str(path)
    environment.update(CCX_FORCE_ACCOUNTING_REQUEST=str(directory / 'Mesh.accounting'), OMP_NUM_THREADS='2',
                       PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', TMPDIR=environment['FREECAD_USER_TEMP'])
    receipt = {'schema': manifest['schema'], 'physical_graph_qualified': False,
               'parser_probe_only': True, 'passed': False, 'manifest_sha256': manifest_sha,
               'native_binary': str(BINARY), 'native_binary_sha256': NATIVE_SHA}
    try:
        receipt.update(run_bounded([str(BINARY), '-i', 'Mesh'], cwd=directory,
                                  log=directory / 'solver.log', timeout=60, environment=environment))
    finally:
        receipt['exact_native_diagnostic'] = (directory / 'solver.log').read_text(errors='replace')
        receipt['inputs_unchanged'] = current_inputs() == manifest['inputs']
        receipt['copied_deck_unchanged'] = sha(directory / 'Mesh.inp') == DECK_SHA
        receipt['parser_request_unchanged'] = sha(directory / 'Mesh.accounting') == manifest['parser_request_sha256']
        after = protected()
        write(directory / 'private-custody-after.json', after)
        receipt['app_and_profiles_unchanged'] = before == after
        receipt['capacity_refusal_observed'] = bool(receipt.get('returncode') == 201 and re.search(
            r'too many[^\n]*port', receipt['exact_native_diagnostic'], re.I))
        receipt['native_acceptance_success'] = receipt.get('returncode') == 0
        receipt['passed'] = bool(receipt['native_acceptance_success'] and receipt['inputs_unchanged'] and
                                receipt['app_and_profiles_unchanged'] and receipt.get('child_reaped') and
                                receipt.get('process_group_gone') and not receipt.get('timed_out'))
        write(directory / 'execution.json', receipt)
        print(json.dumps(receipt, indent=2), flush=True)
    return 0 if receipt['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'run'))
    parser.add_argument('label')
    parser.add_argument('--manifest-sha')
    args = parser.parse_args()
    assert re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', args.label)
    assert_serial(('gmsh', 'ninja', 'make', 'gmake'))
    directory = ROOT / args.label
    if args.action == 'prepare':
        prepare(directory)
        return 0
    return run(directory, args.manifest_sha)


if __name__ == '__main__':
    raise SystemExit(main())
