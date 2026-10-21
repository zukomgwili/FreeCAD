"""Root-only exact explicit-plan collector. No native/app/Git/test execution.

Requires a separately root-approved final plan and a captured final semantic
qualification receipt. Pending roles cannot qualify. Historical RED/rejected
receipts remain failed. New-only publication follows all semantic, privacy,
byte-cap and original/capsule fences; check-only writes zero files. A separate
independent publication audit is REQUIRED after publication, not performed or
claimed here. Original runtime/profile inventories and binaries stay private.

Final receipt interface: schema FreeCAD-3q7-source-qualification-v1, passed true,
pending_roles [], source_identity, scope, roles {name:{path,sha256,bytes}},
role_expectations {name:actual passed boolean}, role_checks
{name:[{pointer:'/literal/JSON/pointer',equals:literal}]}. The root supplies
actual completed roles/paths/counts, never placeholders or prospective PASS.
"""
import sys
sys.dont_write_bytecode = True
import argparse
import ast
import gzip
import hashlib
import json
import math
from pathlib import Path
import re

TASK = Path('/private/tmp/freecad-3q7-Pq3Byy')
REPO = Path('/Users/zukomgwili/src/FreeCAD')
APP = Path('/Applications/FreeCAD-27.1.0.app')
BUILD = REPO / 'build/release'
OUT = REPO / 'package/local-completion/freecad-3q7-source-evidence'
SUMMARY = REPO / 'package/local-completion/freecad-3q7-validation.json'
PER_FILE = 128 * 1024 * 1024
PACKET = 256 * 1024 * 1024
NATIVE = '6c02452a896727af6cb4578fd3fb6bbfbdd48e3fb887c1c04fa2d8b171976c66'
FROZEN = {
    'coupled_port_capacity_fixture.json': '9142f5aa4d149aa1f0d518a592a78638f9489fb3e245af67ea4fd463e5b8ae22',
    'coupled_port_capacity_oracle.json': '42fa6289fd9e1f80efa56db27c02c06a5454ed9880f7ca61bfd80992dfb251b8'}
REQUIRED = {'tiny_red_first': False, 'tiny_red_second': False, 'rejected_large_pair': False,
    'restore_first': True, 'restore_second': True, 'group_handle_amendment': True,
    'paired_baseline': True, 'paired_candidate': True, 'full_graph_execution': True,
    'full_graph_witness': True, 'cold_execution': True, 'cold_receipt': True,
    'fem': True, 'gui': True, 'guards': True, 'ctest': True, 'source_build': True,
    'final_review': True}
DENIED_PARTS = {'.git', '.beads', '.pixi', '__pycache__', 'CMakeFiles', 'CalculiX',
    'profiles', 'module-cache', 'freecad_user_home', 'freecad_user_data', 'freecad_user_temp',
    'xdg_config_home', 'xdg_data_home', 'xdg_cache_home'}
DENIED_SUFFIXES = {'.cfg', '.pyc', '.pyo', '.so', '.dylib', '.o', '.a', '.exe'}
KINDS = {'json', 'source', 'text', 'native-input', 'native-output', 'mesh-snapshot',
         'profile-data', 'synthetic-fixture'}
RAW_KEYS = {'environment', 'environ', 'profiles', 'profile_inventories', 'profile_inventory',
    'app_inventory', 'application_inventory', 'inventory', 'critical_before', 'critical_after'}
SECRET_KEYS = {'password', 'api_key', 'apikey', 'secret', 'access_token', 'refresh_token',
               'authorization', 'cookie'}
MAGIC = {b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xce',
         b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca', b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca', b'\x7fELF'}
CASE_NAMES = {'coupled-before-export.FCStd', 'coupled-native-current.FCStd',
    'witness-receipt.json', 'independent-export-audit.json', 'physical-face-motion-proof.json',
    'motion-from-original-dat.json', 'cold-case.json', 'geometry-contract.json',
    'export-properties.json', 'native-properties.json', 'native-accounting-data.json',
    'mesh-membership.json', 'native.stdout', 'native.stderr', 'native/Mesh.inp',
    'native/Mesh.accounting', 'native/Mesh.accounting.json', 'native/Mesh.accounting.out',
    'native/Mesh.dat', 'native/Mesh.frd'}
CASE_REQUIRED = {'coupled-before-export.FCStd', 'coupled-native-current.FCStd',
    'witness-receipt.json', 'cold-case.json', 'native-accounting-data.json',
    'native/Mesh.inp', 'native/Mesh.accounting', 'native/Mesh.accounting.out',
    'native/Mesh.dat', 'native/Mesh.frd'}


def need(value, message):
    if not value:
        raise RuntimeError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()


def file_hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def descriptor(data, path):
    return {'path': str(path), 'sha256': digest(data), 'bytes': len(data)}


def regular(path, copied):
    path = Path(path)
    need(path.is_absolute() and '..' not in path.parts, 'Absolute exact original path required')
    roots = [root for root in (TASK, REPO, APP) if path.is_relative_to(root)]
    need(len(roots) == 1, 'Input outside explicit task/repository/application roots')
    root = roots[0]
    cursor = path
    while cursor != root:
        need(not cursor.is_symlink(), 'Input links are excluded: ' + str(cursor))
        cursor = cursor.parent
    need(path.is_file(), 'Missing regular input: ' + str(path))
    if copied:
        need(root != APP and not DENIED_PARTS.intersection(path.relative_to(root).parts),
             'Runtime/profile/vendor namespace is not a copy source: ' + str(path))
        need(not path.name.startswith('private-') and path.name not in {'.env', 'user.cfg', 'system.cfg'}
             and path.suffix.lower() not in DENIED_SUFFIXES, 'Excluded private/config/runtime payload')
        need(path.stat().st_size <= PER_FILE, 'Per-file cap exceeded: ' + str(path))
    return path


def privacy(value):
    if isinstance(value, dict):
        need(not (isinstance(value.get('.'), dict) and value['.'].get('kind') == 'dir'), 'Raw application/profile inventory')
        keys = {str(key).lower() for key in value}
        need(not RAW_KEYS.intersection(keys) and not SECRET_KEYS.intersection(keys), 'Raw inventory/environment/secret dictionary')
        need(not {'dev', 'inode', 'mtime_ns', 'ctime_ns'}.issubset(keys), 'Raw dependency stat inventory')
        need(not {'sha256', 'mode', 'size', 'mtime_ns', 'target'}.issubset(keys), 'Raw selected-dependency inventory row')
        for item in value.values():
            privacy(item)
    elif isinstance(value, list):
        for item in value:
            privacy(item)


def validate_descriptor(ref):
    need(set(ref) == {'path', 'sha256', 'bytes'} and type(ref['bytes']) is int
         and ref['bytes'] >= 0 and re.fullmatch('[0-9a-f]{64}', ref['sha256']), 'Malformed exact descriptor')


def reference(raw, ref):
    validate_descriptor(ref)
    need(ref['path'] in raw and descriptor(raw[ref['path']], ref['path']) == ref,
         'Role/reference must be exact indexed bytes: ' + ref['path'])
    return json.loads(raw[ref['path']])


def bound_bytes(raw, ref):
    validate_descriptor(ref)
    need(ref['path'] in raw and descriptor(raw[ref['path']], ref['path']) == ref,
         'Defining output must be exact indexed bytes: ' + ref['path'])
    return raw[ref['path']]


def named_snapshot(value):
    keys = [(row['name'], row['element_type']) for row in value['groups']]
    need(len(keys) == len(set(keys)), 'Duplicate group name/type cannot be normalized')
    other = {name: item for name, item in value.items() if name != 'groups'}
    other['ordered_native_group_handles'] = [row['id'] for row in value['groups']]
    other['groups'] = [{name: row[name] for name in ('name', 'element_type', 'elements')}
        for row in sorted(value['groups'], key=lambda row: (row['name'], row['element_type']))]
    return other


def validate_pair(values, qualified, raw):
    profiles, outputs, snapshots = {}, {}, {}
    names = {'identity.json', 'export-profile.json', 'run.log', 'whole-public-write.prof',
        'profile-cumulative.txt', 'native/Mesh.inp', 'native/Mesh.accounting',
        'native/Mesh.accounting.json', 'mesh-before.json', 'mesh-after.json'}
    flags = ('source_and_supervisor_unchanged', 'compiled_native_runtime_unchanged',
        'python_copy_parity_unchanged', 'manifest_unchanged', 'application_and_three_profiles_unchanged',
        'sixteen_selected_dependencies_unchanged', 'serial_post_guard_passed', 'produced_outputs_unchanged_after_capture')
    for name in ('paired_baseline', 'paired_candidate'):
        run = values[name]
        need(run['schema'] == 'FreeCAD-3q7-large-common-runtime-execution-v2'
             and run['role'] == ('baseline' if name.endswith('baseline') else 'candidate')
             and run['returncode'] == 0 and run['child_reaped'] is True and run['process_group_gone'] is True
             and run['timed_out'] is False and all(run[flag] is True for flag in flags), 'Actual accepted guarded v2 pair required')
        need(set(run['produced_outputs']) == names, 'All ten defining accepted-pair outputs are mandatory')
        outputs[name] = {leaf: bound_bytes(raw, ref) for leaf, ref in run['produced_outputs'].items()}
        profiles[name] = json.loads(outputs[name]['export-profile.json'])
        profile = profiles[name]
        need(profile['passed'] is True and profile['schema'] == 'FreeCAD-3q7-common-runtime-whole-export-profile-v2'
             and profile['actual_write_inp_file_calls'] == 1 and profile['role'] == run['role'], 'One accepted whole public export required')
        before, after = (json.loads(outputs[name][leaf]) for leaf in ('mesh-before.json', 'mesh-after.json'))
        need(before == after, 'Within-leg raw native IDs/order/provenance/membership changed')
        snapshots[name] = named_snapshot(before)
    baseline, candidate = values['paired_baseline'], values['paired_candidate']
    need(baseline['compiled_native_pins'] == candidate['compiled_native_pins'], 'Accepted pair compiled runtime differs')
    need(candidate['baseline_reference']['execution'] == qualified['roles']['paired_baseline'], 'Candidate refers to another baseline')
    need(profiles['paired_candidate']['strict_matched_baseline_outputs_and_named_mesh_snapshots_equal'] is True,
         'Candidate lacks strict matched-baseline proof')
    need(snapshots['paired_baseline'] == snapshots['paired_candidate'], 'Reviewed named-group/all-other-raw snapshot comparison differs')
    need(outputs['paired_baseline']['native/Mesh.accounting'] == outputs['paired_candidate']['native/Mesh.accounting'],
         'Native request/PORT/ownership IDs changed across accepted pair')
    decks = [outputs[name]['native/Mesh.inp'] for name in ('paired_baseline', 'paired_candidate')]
    timestamp = re.compile(rb'^\*\*   written on    --> [^\r\n]+$', re.M)
    need(all(len(timestamp.findall(deck)) == 1 for deck in decks)
         and timestamp.sub(b'**   written on    --> <timestamp>', decks[0])
         == timestamp.sub(b'**   written on    --> <timestamp>', decks[1]), 'Deck differs beyond its one exact timestamp comment')


def validate_red(name, value, ref, raw):
    need(value['schema'] == 'FreeCAD-3q7-whole-export-work-regression-v1'
         and value['passed'] is False and value['actual_public_writes'] == 1, 'Actual whole-write bound RED required: ' + name)
    maxima = {'Part.Shape.isValid': 36, 'Fem.FemMesh.getElementNodes': 24 * value['element_count'],
              'Fem.FemMesh.getGroupElements': 20 * value['group_count'] + 64}
    need(len(value['checks']) == 3 and {row['native_operation'] for row in value['checks']} == set(maxima), 'All three predeclared work bounds required')
    for row in value['checks']:
        need(row['maximum_calls'] == maxima[row['native_operation']] and row['passed'] is False
             and row['actual_calls'] > row['maximum_calls'], 'Expected actual native-work failure differs')
    parent = Path(ref['path']).parent
    run_path, observation_path = str(parent / 'execution.json'), str(parent / 'observation.json')
    need(run_path in raw and observation_path in raw and digest(raw[run_path]) == value['execution_sha256']
         and digest(raw[observation_path]) == value['observation_sha256'], 'RED must bind successful observer execution and output')
    run, observation = json.loads(raw[run_path]), json.loads(raw[observation_path])
    need(run['passed'] is True and run['returncode'] == 0 and run['child_reaped'] is True
         and run['process_group_gone'] is True and run['timed_out'] is False
         and observation['passed'] is True and observation['actual_write_inp_file_calls'] == 1,
         'Work RED is not a successful real public export observation')
    for output in run['produced_outputs'].values():
        bound_bytes(raw, output)
    need(observation['profile_blob']['sha256'] == value['profiler_sha256'], 'RED profiler binding differs')


def pointer(value, path):
    need(path.startswith('/') and path != '/', 'Nonempty explicit JSON pointer required')
    for term in path[1:].split('/'):
        term = term.replace('~1', '/').replace('~0', '~')
        if isinstance(value, list):
            need(re.fullmatch('0|[1-9][0-9]*', term), 'Invalid list pointer')
            value = value[int(term)]
        else:
            need(isinstance(value, dict) and term in value, 'Missing JSON pointer component: ' + path)
            value = value[term]
    return value


def qualification(plan, raw):
    qualified = reference(raw, plan['qualification_receipt'])
    need(qualified['schema'] == 'FreeCAD-3q7-source-qualification-v1'
         and qualified['passed'] is True and qualified['pending_roles'] == [], 'Actual completed semantic qualification required')
    scope = qualified['scope']
    for name, expected in {'source_only': True, 'installation_performed': False,
            'Oomakhi_accessed_or_solved': False, 'engineering_or_BIM_accepted': False,
            'R49_R51_acceptance_claimed': False, 'no_timing_SLA_or_universal_scaling_claim': True,
            'historical_failed_pair_remains_failed': True,
            'force_original_origin_moment_limit': .01, 'scalar_response_limit': .05}.items():
        need(scope[name] == expected and type(scope[name]) is type(expected), 'Scope/hold differs: ' + name)
    identity = qualified['source_identity']
    need(re.fullmatch('[0-9a-f]{40}', identity['implementation_commit'])
         and isinstance(identity['compiled_revision'], str) and identity['compiled_revision']
         and identity['default_native_sha256'] == NATIVE, 'Final source identity is incomplete/different')
    roles, expected, checks = qualified['roles'], qualified['role_expectations'], qualified['role_checks']
    need(REQUIRED.keys() <= roles.keys() and roles.keys() == expected.keys() == checks.keys(), 'Missing or inconsistent actual role set')
    need(all(expected[name] is state for name, state in REQUIRED.items()), 'Historical/final role outcome was changed')
    values = {}
    for name, ref in roles.items():
        need(type(expected[name]) is bool, 'Each role needs an actual boolean outcome')
        row = reference(raw, ref)
        need(row.get('passed') is expected[name], 'Captured role outcome differs: ' + name)
        need(checks[name] and isinstance(checks[name], list), 'Explicit semantic checks required for role: ' + name)
        for check in checks[name]:
            need(set(check) == {'pointer', 'equals'}, 'Unexpected semantic assertion fields')
            actual = pointer(row, check['pointer'])
            need(type(actual) is type(check['equals']) and actual == check['equals'], 'Semantic assertion differs: ' + name + check['pointer'])
        values[name] = row
    for name in ('tiny_red_first', 'tiny_red_second'):
        validate_red(name, values[name], roles[name], raw)
    validate_pair(values, qualified, raw)
    witness = values['full_graph_witness']
    need(witness['schema'] == 'FreeCAD-native-coupled-port-coupled-native-witness-v1'
         and witness['case'] == 'capacity' and witness['rows_y'] == 11 and witness['columns_z'] == 12
         and witness['only_public_native_interfaces'] is True and witness['no_deck_patches_or_mocks'] is True
         and witness['engineering_project_accessed_or_solved'] is False and witness['engineering_or_BIM_accepted'] is False
         and witness['frozen_oracle_sha256'] == FROZEN and witness['physical_check_count'] == 3566
         and len(witness['checks']) == 3566 and witness['solver_returncode'] == 0
         and witness['actual_binary_sha256'] == NATIVE and witness['protected_inputs_unchanged'] is True
         and witness['force_and_original_origin_moment_limit'] == .01
         and witness['local_generalized_force_and_couple_limit'] == .01 and witness['scalar_response_limit'] == .05,
         'Actual unchanged complete generic132-bay physical qualification required')
    need(len({row['name'] for row in witness['checks']}) == 3566, 'Repeated/missing physical check names')
    for row in witness['checks']:
        actual, target = row['actual'], row['reference']
        need(len(actual) == len(target) == 3 and all(math.isfinite(v) for v in actual + target), 'Nonfinite physical vector')
        limit = .05 if row['name'].endswith(('/differential-translation', '/differential-rotation')) else .01
        scale, error = row['scale'], math.dist(actual, target)
        need(math.isfinite(scale) and scale > 0 and row['limit'] == limit and row['passed'] is True
             and error <= limit * scale and math.isclose(error, row['error_norm'], rel_tol=1e-12, abs_tol=1e-12)
             and math.isclose(error / scale, row['relative_error'], rel_tol=1e-12, abs_tol=1e-12),
             'Physical check arithmetic/unchanged ceiling differs: ' + row['name'])
    cold = values['cold_receipt']
    need(cold['schema'] == 'FreeCAD-yzk-portable-cold-receipt-v1' and cold['status'].startswith('Stale')
         and all(cold[name] is True for name in ('no_native_solve', 'no_save', 'no_history_or_provenance_repair')),
         'Separate-process literal historical cold scope differs')
    return qualified, values


def capsule(plan, raw, qualified, values):
    custody = reference(raw, plan['synthetic_capsule'])
    need(custody['schema'] == 'FreeCAD-3q7-exact-generic-case-capsule-v1'
         and custody['passed'] is True and custody['copies_exact'] is True and custody['originals_unchanged'] is True
         and custody['engineering_project_accessed_or_solved'] is False,
         'Exact approved public synthetic capsule custody required')
    need(custody['source_run_execution'] == qualified['roles']['full_graph_execution'], 'Capsule belongs to another physical execution')
    source_root = Path(custody['source_witness_directory'])
    copy_root = Path(custody['copy_directory'])
    need(source_root.is_absolute() and source_root.is_relative_to(TASK)
         and copy_root.is_absolute() and copy_root.is_relative_to(TASK)
         and source_root != copy_root
         and not DENIED_PARTS.intersection(copy_root.relative_to(TASK).parts), 'Capsule/source namespace differs')
    rows = custody['files']
    names = {row['path'] for row in rows}
    need(len(names) == len(rows) and CASE_REQUIRED <= names <= CASE_NAMES, 'Unknown/duplicate/missing exact generic case leaf')
    approved = plan['synthetic_file_approvals']
    need(len(approved) == len(rows) and {row['path'] for row in approved} == names, 'Explicit root approval of every synthetic leaf required')
    approvals = {row['path']: row for row in approved}
    witness = values['full_graph_witness']
    originals, allowed = {}, {}
    for row in rows:
        need(set(row) == {'source', 'path', 'sha256', 'bytes'}, 'Unexpected custody leaf fields')
        need(row == approvals[row['path']], 'Exact synthetic path/SHA/size approval differs')
        source, copy = source_root / row['path'], copy_root / row['path']
        need(row['source'] == str(source) and str(copy) in raw
             and descriptor(raw[str(copy)], str(source)) == {'path': str(source), 'sha256': row['sha256'], 'bytes': row['bytes']},
             'Capsule bytes differ from approved original')
        source = regular(source, copied=False)
        need(file_hash(source) == row['sha256'] and source.stat().st_size == row['bytes'], 'Original synthetic leaf changed')
        if row['path'] != 'witness-receipt.json':
            need(witness['retained_files'][row['path']] == {'sha256': row['sha256'], 'bytes': row['bytes']},
                 'Synthetic leaf is not the exact witness-bound output')
        else:
            need(qualified['roles']['full_graph_witness'] == descriptor(raw[str(copy)], str(copy)), 'Capsule witness is not the qualified witness')
        originals[str(source)] = {'sha256': row['sha256'], 'bytes': row['bytes']}
        allowed[str(copy)] = row['path']
    cold = json.loads(raw[str(copy_root / 'cold-case.json')])
    need(cold['schema'] == 'FreeCAD-native-coupled-port-coupled-cold-case-v1' and cold['frozen_oracle_sha256'] == FROZEN
         and cold['document'] == str(source_root / 'coupled-native-current.FCStd')
         and cold['document_sha256'] == originals[cold['document']]['sha256']
         and values['cold_receipt']['manifest'] == str(source_root / 'cold-case.json')
         and values['cold_receipt']['manifest_sha256'] == originals[str(source_root / 'cold-case.json')]['sha256'],
         'Literal cold manifest/saved history was rebound or changed')
    need(set(cold['source_files']) == {'dat', 'deck', 'frd', 'native_output', 'request'}, 'Exactly five literal native source files required')
    for name, leaf in {'dat': 'Mesh.dat', 'deck': 'Mesh.inp', 'frd': 'Mesh.frd',
                       'native_output': 'Mesh.accounting.out', 'request': 'Mesh.accounting'}.items():
        ref = cold['source_files'][name]
        need(ref['path'] == str(source_root / 'native' / leaf)
             and ref['sha256'] == originals[ref['path']]['sha256'], 'Literal native cold file binding differs')
    need(witness['before_export_document_sha256'] == originals[str(source_root / 'coupled-before-export.FCStd')]['sha256'],
         'Before-export saved public fixture differs')
    data = json.loads(raw[str(copy_root / 'native-accounting-data.json')])
    counts = {'supports': 1, 'bodies': 264, 'ports': 264, 'angles': 792, 'springs': 792}
    need(data['schema'] == 'CCX_FORCE_ACCOUNTING_V3' and data['binary_sha256'] == NATIVE
         and data['capacity']['required'] == counts and data['capacity']['total'] == 2113
         and data['capacity']['supported']['total_records'] == 2113
         and data['capacity_applied'] == {'budget': 2113, 'counts': counts, 'total': 2113},
         'Actual native2113 applied budget echo differs')
    return allowed, originals


def payload(path, data, kind, allowed, profile_bindings):
    need(kind in KINDS and data[:4] not in MAGIC and not data.startswith(b'MZ'), 'Forbidden runtime/unknown payload')
    if path.suffix.lower() in {'.fcstd', '.frd'}:
        need(str(path) in allowed, 'Only exact individually approved public capsule FCStd/FRD may be copied')
        if path.suffix.lower() == '.fcstd':
            need(kind == 'synthetic-fixture' and data.startswith(b'PK\x03\x04'), 'Approved FCStd must be an exact archive')
            return
    if kind == 'profile-data':
        need(path.name in {'whole-public-write.prof', 'whole-write.prof'}
             and (str(path), digest(data), len(data)) in profile_bindings,
             'Opaque profile must be a captured receipt-bound own output')
        return  # Never unmarshal/execute profiler data.
    text = data.decode('utf-8')
    need(b'\x00' not in data and not re.search(r'(?im)^(?:OPENAI_API_KEY|GITHUB_TOKEN|GH_TOKEN|'
        r'AWS_SECRET_ACCESS_KEY|PASSWORD|ACCESS_TOKEN|REFRESH_TOKEN)\s*=\s*\S+', text), 'Environment/credential dump')
    if path.suffix == '.py':
        ast.parse(data, filename=str(path))
    if path.suffix == '.json':
        privacy(json.loads(data))


def endfence(raw, refs, plan_path, plan_bytes):
    for path, data in raw.items():
        need(regular(path, copied=True).read_bytes() == data, 'Captured original changed: ' + path)
    for path, ref in refs.items():
        need(file_hash(regular(path, copied=False)) == ref['sha256'] and Path(path).stat().st_size == ref['bytes'],
             'Hash-only/original-case reference changed: ' + path)
    need(plan_path.read_bytes() == plan_bytes, 'Approved plan changed')


def profile_references(raw):
    result = set()
    def visit(value):
        if isinstance(value, dict):
            if set(value) == {'path', 'sha256', 'bytes'} and isinstance(value['path'], str):
                if Path(value['path']).name in {'whole-public-write.prof', 'whole-write.prof'}:
                    validate_descriptor(value)
                    result.add((value['path'], value['sha256'], value['bytes']))
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    for path, data in raw.items():
        if Path(path).name in {'execution.json', 'observation.json', 'export-profile.json'}:
            visit(json.loads(data))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    need(not sys.flags.optimize and re.fullmatch('[0-9a-f]{64}', args.plan_sha256), 'Exact SHA/unoptimized interpreter required')
    plan_path = regular(args.plan, copied=True)
    need(plan_path.parent == TASK / 'collection', 'Explicit private root-approved plan only')
    plan_bytes = plan_path.read_bytes()
    need(digest(plan_bytes) == args.plan_sha256, 'Approved plan SHA differs')
    plan = json.loads(plan_bytes)
    need(plan['schema'] == 'FreeCAD-3q7-approved-source-evidence-plan-v1' and plan['root_approved'] is True,
         'Pending/proposal plan is not publishable')
    need(plan['approved_limits'] == {'per_file_bytes': PER_FILE, 'packet_uncompressed_bytes': PACKET}, 'Byte-cap change requires a separately reviewed collector revision')
    privacy(plan)
    rows = plan['files']
    need(rows and len(rows) == len({row['path'] for row in rows}) == len({row['destination'] for row in rows}), 'Duplicate explicit originals/destinations')
    requested = sum(row['bytes'] for row in rows) + len(plan_bytes)
    need(requested <= PACKET, f'Zero-write packet-cap refusal: requested_uncompressed_bytes={requested}, cap={PACKET}, files={len(rows)}')
    raw, entries = {}, {}
    for row in rows:
        need(set(row) == {'path', 'destination', 'sha256', 'bytes', 'kind', 'classification'}, 'Unexpected explicit file fields')
        path = regular(row['path'], copied=True)
        data = path.read_bytes()
        need(descriptor(data, path) == {name: row[name] for name in ('path', 'sha256', 'bytes')}
             and row['classification'] and row['kind'] in KINDS, 'Explicit original differs or is unclassified')
        target = Path(row['destination'])
        need(target.parts and not target.is_absolute() and '..' not in target.parts and '\\' not in row['destination']
             and target.as_posix() == row['destination'] and not DENIED_PARTS.intersection(target.parts)
             and target.name != 'index.json', 'Unsafe/noncanonical destination')
        raw[str(path)], entries[str(path)] = data, row
    qualified, values = qualification(plan, raw)
    allowed, refs = capsule(plan, raw, qualified, values)
    profile_bindings = profile_references(raw)
    for ref in plan['hash_only_references']:
        need(set(ref) == {'path', 'sha256', 'bytes', 'scope'} and ref['scope'], 'Explicit hash-only scope required')
        path = regular(ref['path'], copied=False)
        need(str(path) not in refs and file_hash(path) == ref['sha256'] and path.stat().st_size == ref['bytes'], 'Hash-only reference differs/duplicates')
        refs[str(path)] = ref
    pending, indexed = {}, []
    for path, data in raw.items():
        row = entries[path]
        payload(Path(path), data, row['kind'], allowed, profile_bindings)
        encoding = 'gzip' if len(data) >= 65536 else 'identity'
        stored = gzip.compress(data, compresslevel=9, mtime=0) if encoding == 'gzip' else data
        target = row['destination'] + ('.gz' if encoding == 'gzip' else '')
        need(target not in pending and target != 'approved-plan.json', 'Transformed destination collision')
        pending[target] = stored
        indexed.append({'file': target, 'kind': row['kind'], 'classification': row['classification'],
            'original_path': path, 'original_sha256': digest(data), 'original_bytes': len(data),
            'stored_sha256': digest(stored), 'stored_bytes': len(stored), 'encoding': encoding,
            'decoded_sha256': digest(data), 'decoded_bytes': len(data), 'transformation': 'exact bytes'})
    pending['approved-plan.json'] = plan_bytes
    indexed.append({'file': 'approved-plan.json', 'kind': 'json', 'classification': 'Exact separately root-approved final file plan',
        'original_path': str(plan_path), 'original_sha256': digest(plan_bytes), 'original_bytes': len(plan_bytes),
        'stored_sha256': digest(plan_bytes), 'stored_bytes': len(plan_bytes), 'encoding': 'identity',
        'decoded_sha256': digest(plan_bytes), 'decoded_bytes': len(plan_bytes), 'transformation': 'exact bytes'})
    index = {'schema': 'FreeCAD-3q7-source-evidence-index-v1', 'files': sorted(indexed, key=lambda row: row['file']),
        'indexed_files': len(indexed), 'uncompressed_payload_bytes': requested,
        'qualification_receipt': plan['qualification_receipt'], 'hash_only_references': plan['hash_only_references'],
        'scope': 'Curated exact software QA/source/synthetic-case bytes; no private inventories/environment/runtime binaries'}
    summary = {'schema': 'FreeCAD-3q7-source-validation-v1', 'passed': True,
        'meaning': 'Completed source qualification and exact-byte publication; a separate independent publication audit remains required',
        'qualification': qualified, 'evidence': {'directory': str(OUT.relative_to(REPO)),
            'index_sha256': digest(encode(index)), 'indexed_files': len(indexed), 'plan_sha256': digest(plan_bytes),
            'uncompressed_payload_bytes': requested},
        'publication': {'independent_audit_required': True, 'independent_audit_completed_by_collector': False},
        'replay_limits': 'Executed paths/history remain literal. Matching external FreeCAD/Pixi/native dependencies are required; runtime binaries are not bundled. Generic software-QA results do not accept Oomakhi/R49/R51 or building design. No installation is performed.'}
    privacy(index)
    privacy(summary)
    packet_bytes = requested + len(encode(index)) + len(encode(summary))
    need(packet_bytes <= PACKET,
         f'Zero-write packet-cap refusal including index/summary: uncompressed_bytes={packet_bytes}, cap={PACKET}, payload_bytes={requested}')
    for name in pending:
        need(all(parent.as_posix() not in set(pending) | {'index.json'}
                 for parent in Path(name).parents if parent.parts), 'File/directory destination-prefix collision')
    endfence(raw, refs, plan_path, plan_bytes)
    need(OUT.parent.is_dir() and not OUT.parent.is_symlink() and not OUT.exists() and not OUT.is_symlink()
         and not SUMMARY.exists() and not SUMMARY.is_symlink(), 'Both publication destinations must be new')
    if not args.check_only:
        OUT.mkdir()
        for name, data in sorted(pending.items()):
            target = OUT / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(data)
        with (OUT / 'index.json').open('xb') as stream:
            stream.write(encode(index))
        with SUMMARY.open('xb') as stream:
            stream.write(encode(summary))
        need({str(path.relative_to(OUT)) for path in OUT.rglob('*') if path.is_file()} == set(pending) | {'index.json'}, 'Published coverage differs')
        for name, data in pending.items():
            need((OUT / name).read_bytes() == data, 'Published stored bytes differ: ' + name)
            row = next(row for row in indexed if row['file'] == name)
            decoded = gzip.decompress(data) if row['encoding'] == 'gzip' else data
            need(digest(decoded) == row['decoded_sha256'] and len(decoded) == row['decoded_bytes'], 'Published decoded bytes differ')
        need((OUT / 'index.json').read_bytes() == encode(index) and SUMMARY.read_bytes() == encode(summary), 'Index/summary bytes differ')
        endfence(raw, refs, plan_path, plan_bytes)
    print(json.dumps({'passed': True, 'check_only': args.check_only, 'writes': 0 if args.check_only else len(indexed) + 2,
        'indexed_files': len(indexed), 'uncompressed_payload_bytes': requested,
        'uncompressed_packet_bytes': packet_bytes,
        'index_sha256': digest(encode(index)), 'summary_sha256': digest(encode(summary)),
        'independent_publication_audit_required': True}, sort_keys=True))


if __name__ == '__main__':
    main()
