"""Serial bounded V1 qualification using the untouched generic 9zt generator.

Prepare all declarations before any native process. Run requires the resulting
manifest hash and the independently supplied candidate hash. No FreeCAD or
engineering document is imported, opened, edited or solved.
"""

import argparse
import hashlib
import importlib.util
import itertools
import json
import math
import os
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
PRIVATE = Path(__file__).resolve().parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
GENERATOR = REPO / 'package/local-completion/FreeCAD9ztContactWitness.py'
HELPER = PRIVATE / 'process_control.py'
GENERATOR_SHA = '2f82057efb43764c20bee8ba2b3b364c7c81cd90a192dd76b14f037bde63ba62'
HELPER_SHA = '5199c733fdc18a2c6f78d03ea2a3281e236419365219d7b9f33b5ecca0aa733d'
SCHEMA = 'CCX_FORCE_ACCOUNTING_V1'
LIMIT = 0.01


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def source_pins(binary):
    assert sha(GENERATOR) == GENERATOR_SHA, 'Untouched generic generator differs'
    assert sha(HELPER) == HELPER_SHA, 'Bounded process helper differs'
    paths = [Path(__file__).resolve(), GENERATOR, HELPER, binary]
    paths += [REPO / 'package/calculix/force-accounting' / name
              for name in ('forceaccounting.c', 'hooks.patch', 'contract.json')]
    return {str(path): sha(path) for path in paths}


def cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def rotation(vector):
    """Independent matrix for +35deg about Y, followed by +20deg about Z."""
    cy, sy = math.cos(math.radians(35)), math.sin(math.radians(35))
    cz, sz = math.cos(math.radians(20)), math.sin(math.radians(20))
    matrix = ((cz*cy, -sz, cz*sy), (sz*cy, cz, sz*sy), (-sy, 0., cy))
    return [sum(a*b for a, b in zip(row, vector)) for row in matrix]


def oracle(transformed, shear):
    """Declared load statics, never a calculation from solver result rows."""
    weight = 2.0 * 3.0 * 1.0
    pressure = 4.0 * 1.0
    shear_force = 4.0 * 0.25 if shear else 0.0
    total_force = [shear_force, 0.0, -3.0*weight-pressure]
    total_moment = cross([2.5, 3.5, 1.5], [0.0, 0.0, -3.0*weight])
    top_pressure_moment = cross([2.5, 3.5, 3.0], [0.0, 0.0, -pressure])
    top_shear_moment = cross([2.5, 3.5, 3.0], [shear_force, 0.0, 0.0])
    total_moment = [a+b+c for a, b, c in zip(total_moment, top_pressure_moment, top_shear_moment)]
    upper_force = [shear_force, 0.0, -weight-pressure]
    upper_moment = cross([2.5, 3.5, 2.5], [0.0, 0.0, -weight])
    upper_moment = [a+b+c for a, b, c in zip(upper_moment, top_pressure_moment, top_shear_moment)]
    expected = {
        'SUPPORT/Support': [-value for value in total_force+total_moment],
        'CUT/Lower': upper_force+upper_moment,
        'CUT/Upper': [-value for value in upper_force+upper_moment],
    }
    if transformed:
        for identity, wrench in list(expected.items()):
            force = rotation(wrench[:3])
            moment = [a+b for a, b in zip(rotation(wrench[3:]), cross([11., -4., 7.], force))]
            expected[identity] = force+moment
    return {
        'schema': SCHEMA, 'expected': expected, 'limit': LIMIT,
        'normalization': 'Euclidean force/moment error divided by its finite positive reference norm; no result-derived target and no added floor',
        'basis': 'Three unit cubes, density2, gravity3, pressure4 on unit top area; optional four known0.25 point shear loads. Upper-body cut follows top-cube free-body statics; opposite shared cut is equal/opposite. Transformation uses independently authored rotation matrix plus translation cross force.',
    }


def replace_once(path, before, after):
    text = path.read_text()
    assert text.count(before) == 1, (path, before)
    path.write_text(text.replace(before, after, 1))


NEGATIVES = (
    ('nlgeom', ' requires one small-displacement'),
    ('missing-cut-node', ' body has an undeclared'),
    ('duplicate-support', ' support identities or ports overlap'),
    ('oversized-integer', ' invalid integer field'),
    ('cut-point-load', ' point load on cut has ambiguous body ownership'),
    ('cut-mpc', ' cut body intersects an MPC'),
)


def prepare(args, binary, destination):
    before = source_pins(binary)
    assert before[str(binary)] == args.binary_sha256, 'Candidate differs from declared hash'
    destination.mkdir(exist_ok=False)
    spec = importlib.util.spec_from_file_location('legacy_generic_generator', GENERATOR)
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    cases = []
    for threads, quadratic, transformed, shear, reverse in itertools.product(
        (1, 2, 4), (False, True), (False, True), (False, True), (False, True)
    ):
        name = f't{threads}-q{int(quadratic)}-r{int(transformed)}-s{int(shear)}/' + ('master-upper' if reverse else 'slave-upper')
        directory = destination / name
        directory.mkdir(parents=True, exist_ok=False)
        declaration = oracle(transformed, shear)
        write(directory / 'oracle.json', declaration)
        generator.write_case(directory, reverse, quadratic, transformed, shear)
        cases.append({'case': name, 'positive': True, 'threads': threads,
                      'quadratic': quadratic, 'transformed': transformed,
                      'shear': shear, 'reverse': reverse})
    for name, suffix in NEGATIVES:
        directory = destination / name
        directory.mkdir()
        generator.write_case(directory)
        deck, request = directory / 'contact.inp', directory / 'contact.accounting'
        if name == 'nlgeom':
            replace_once(deck, '*STEP\n', '*STEP,NLGEOM\n')
        elif name == 'missing-cut-node':
            replace_once(request, 'BODY Lower 6 4', 'BODY Lower 6 3')
            replace_once(request, '13 14 15 16\nBODY Upper', '13 14 15\nBODY Upper')
        elif name == 'duplicate-support':
            replace_once(request, 'END\n', 'SUPPORT Duplicate 21 22\nEND\n')
        elif name == 'oversized-integer':
            replace_once(request, 'Support 21 22', 'Support 9223372036854775808 22')
        elif name == 'cut-point-load':
            replace_once(deck, '*NODE PRINT,NSET=REF', '*CLOAD\n13,1,1\n*NODE PRINT,NSET=REF')
        elif name == 'cut-mpc':
            replace_once(deck, '*BOUNDARY', '*EQUATION\n2\n13,1,1,17,1,-1\n*BOUNDARY')
        declaration = {'schema': SCHEMA, 'expected_exit_code': 201,
                       'diagnostic': '*ERROR CCX force accounting V1:'+suffix,
                       'completed_accounting_envelope_forbidden': True}
        write(directory / 'oracle.json', declaration)
        cases.append({'case': name, 'positive': False, 'threads': 2})
    assert len(cases) == 54 and sum(item['positive'] for item in cases) == 48
    for case in cases:
        directory = destination / case['case']
        assert (directory / 'contact.accounting').read_text().splitlines()[0] == SCHEMA
        case['inputs'] = {name: sha(directory / name)
                          for name in ('contact.inp', 'contact.accounting', 'oracle.json')}
    assert source_pins(binary) == before, 'Preparation changed protected sources'
    manifest = {'schema': 'FreeCAD-ywu.LEGACY_V1_PREDECLARED.1', 'directory': str(destination),
                'binary': str(binary), 'protected': before, 'cases': cases,
                'original_project_replayed': False, 'design_accepted': False}
    write(destination / 'manifest.json', manifest)
    print(json.dumps({'prepared': True, 'cases': 54, 'positive': 48, 'negative': 6,
                      'manifest_sha256': sha(destination / 'manifest.json')}, sort_keys=True))


def parse_output(path):
    lines = path.read_text().splitlines()
    assert len(lines) >= 3 and lines[0] == SCHEMA and lines[-1] == 'END', 'Incomplete/wrong schema envelope'
    state = lines[1].split()
    assert len(state) == 4 and state[0] == 'STATE'
    assert int(state[1]) == 1 and int(state[2]) >= 1 and float(state[3]) == 1.0, 'Wrong final state'
    rows = {}
    for line in lines[2:-1]:
        fields = line.split()
        assert len(fields) == 8 and fields[0] in ('SUPPORT', 'CUT', 'LOAD', 'CONTACT'), 'Unexpected V1 row'
        key = '/'.join(fields[:2])
        assert key not in rows, 'Duplicate V1 row'
        values = [float(value) for value in fields[2:]]
        assert all(math.isfinite(value) for value in values), 'Nonfinite V1 wrench'
        rows[key] = values
    assert set(rows) == {'SUPPORT/Support', 'CUT/Lower', 'CUT/Upper',
                         'LOAD/Lower', 'LOAD/Upper', 'CONTACT/Lower', 'CONTACT/Upper'}
    return state, rows


def qualify_positive(directory):
    state, rows = parse_output(directory / 'contact.accounting.out')
    declared = json.loads((directory / 'oracle.json').read_text())
    errors = {}
    for identity, wanted in declared['expected'].items():
        got = rows[identity]
        errors[identity] = []
        for offset in (0, 3):
            norm = math.hypot(*wanted[offset:offset+3])
            assert math.isfinite(norm) and norm > 0
            error = math.dist(got[offset:offset+3], wanted[offset:offset+3]) / norm
            assert math.isfinite(error) and error <= declared['limit'], (identity, error, got, wanted)
            errors[identity].append(error)
    balances = {}
    for body in ('Lower', 'Upper'):
        vectors = [rows[kind+'/'+body] for kind in ('CUT', 'LOAD', 'CONTACT')]
        residual = max(abs(sum(vector[index] for vector in vectors)) for index in range(6))
        scale = max(1., *(abs(value) for vector in vectors for value in vector))
        balances[body] = residual / scale
        assert balances[body] <= 1e-12, 'V1 wire balance differs'
    return {'state': state, 'relative_force_moment_errors': errors,
            'wire_balance_relative_residuals': balances, 'physical_norm_checks': 6}


def run(args, binary, destination):
    manifest_path = destination / 'manifest.json'
    assert args.manifest_sha256 and sha(manifest_path) == args.manifest_sha256, 'Manifest hash not independently bound'
    manifest = json.loads(manifest_path.read_text())
    assert manifest['directory'] == str(destination) and manifest['binary'] == str(binary)
    protected = manifest['protected']
    assert source_pins(binary) == protected and sha(binary) == args.binary_sha256
    assert len(manifest['cases']) == 54 and sum(case['positive'] for case in manifest['cases']) == 48
    assert len({case['case'] for case in manifest['cases']}) == 54
    spec = importlib.util.spec_from_file_location('legacy_process_control', HELPER)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    receipts = []
    for case in manifest['cases']:
        relative = Path(case['case'])
        assert not relative.is_absolute() and '..' not in relative.parts
        directory = destination / relative
        assert {path.name for path in directory.iterdir()} == set(case['inputs']), 'Case is not pristine'
        before = {name: sha(directory / name) for name in case['inputs']}
        assert before == case['inputs'] and source_pins(binary) == protected
        assert sha(manifest_path) == args.manifest_sha256
        helper.assert_serial(('gmsh', 'ninja', 'make', 'gmake', binary.name))
        environment = dict(os.environ)
        for key in list(environment):
            if key.startswith(('CCX_', 'FREECAD_', 'YWU_', 'FIVEAR_')):
                environment.pop(key)
        environment.update(CCX_FORCE_ACCOUNTING_REQUEST=str(directory / 'contact.accounting'),
                           OMP_NUM_THREADS=str(case['threads']), PYTHONDONTWRITEBYTECODE='1')
        result = {'case': case['case'], 'positive': case['positive'], 'passed': False,
                  'inputs_before': before, 'protected_before': protected}
        error = None
        try:
            result.update(helper.run_bounded([str(binary), '-i', 'contact'], cwd=directory,
                                            log=directory / 'solver.log', timeout=60,
                                            environment=environment))
            assert not result['timed_out'] and result['reaped'] and result['process_group_gone']
            if case['positive']:
                assert result['returncode'] == 0, 'Positive native process did not exit zero'
                result.update(qualify_positive(directory))
            else:
                declaration = json.loads((directory / 'oracle.json').read_text())
                assert result['returncode'] == 201, 'Negative native process did not refuse201'
                assert declaration['diagnostic'] in (directory / 'solver.log').read_text(errors='replace')
                output = directory / 'contact.accounting.out'
                assert not output.exists() or 'END' not in output.read_text().splitlines(), 'Refusal has completed envelope'
                result['diagnostic'] = declaration['diagnostic']
                result['complete_accounting_envelope'] = False
            result['passed'] = True
        except BaseException as caught:
            error = caught
            result['error'] = repr(caught)
        finally:
            result['inputs_after'] = {name: sha(directory / name) for name in case['inputs']}
            result['protected_after'] = source_pins(binary)
            result['inputs_unchanged'] = result['inputs_after'] == before
            result['protected_unchanged'] = result['protected_after'] == protected
            result['manifest_unchanged'] = sha(manifest_path) == args.manifest_sha256
            result['passed'] &= result['inputs_unchanged'] and result['protected_unchanged'] and result['manifest_unchanged']
            result['outputs'] = {path.name: sha(path) for path in directory.iterdir()
                                 if path.is_file() and path.name not in case['inputs']}
            write(directory / 'execution.json', result)
        receipts.append(result)
        if error is not None or not result['passed']:
            write(destination / 'failure.json', {'passed': False, 'case': case['case'],
                                                'execution': result, 'error': repr(error)})
            if error is not None:
                raise error
            raise AssertionError('Protected input mutation')
    assert len(receipts) == 54 and all(item['passed'] for item in receipts)
    assert source_pins(binary) == protected and sha(manifest_path) == args.manifest_sha256
    receipt = {'schema': SCHEMA, 'binary': str(binary), 'binary_sha256': sha(binary),
               'manifest_sha256': args.manifest_sha256, 'protected': protected,
               'analytic_cases': [item for item in receipts if item['positive']],
               'rejections': [item for item in receipts if not item['positive']],
               'positive_cases': 48, 'expected_refusals': 6, 'physical_norm_checks': 288,
               'all_children_reaped': all(item['reaped'] and item['process_group_gone'] for item in receipts),
               'all_inputs_unchanged': all(item['inputs_unchanged'] and item['protected_unchanged'] for item in receipts),
               'passed': True, 'original_project_replayed': False, 'design_accepted': False}
    write(destination / 'qualification.json', receipt)
    print('PASS 48 fresh V1 analytic native cases, 6 expected refusals, 288 physical norm checks')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'run'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--ccx', type=Path, required=True)
    parser.add_argument('--binary-sha256', required=True)
    parser.add_argument('--manifest-sha256')
    args = parser.parse_args()
    assert re.fullmatch('[0-9a-f]{64}', args.binary_sha256)
    if args.manifest_sha256:
        assert re.fullmatch('[0-9a-f]{64}', args.manifest_sha256)
    binary = args.ccx.resolve(strict=True)
    destination = args.root.resolve()
    assert destination.parent == PRIVATE, 'Evidence must be a fresh direct child of the private task root'
    assert not sys.flags.optimize, 'Assertions must not be optimized away'
    (prepare if args.action == 'prepare' else run)(args, binary, destination)


if __name__ == '__main__':
    main()
