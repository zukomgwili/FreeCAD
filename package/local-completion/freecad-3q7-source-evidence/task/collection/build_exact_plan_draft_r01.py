"""PRIVATE plan drafting only; never qualifies roles, approves or publishes.

Consumes one SHA-bound explicit selection. Every role, custody record and file
must already exist. The generated plan has root_approved false and cannot pass
the collector. No recursive input discovery, native/app/Git/test execution,
source editing or publication is performed. Root must inspect exact semantics,
privacy, packet size and all final input descriptors before approval.
"""
import sys
sys.dont_write_bytecode = True
import argparse
import hashlib
import json
from pathlib import Path
import re

TASK = Path('/private/tmp/freecad-3q7-Pq3Byy')
REPO = Path('/Users/zukomgwili/src/FreeCAD')
COLLECTION = TASK / 'collection'
PER_FILE = 128 * 1024 * 1024
PACKET = 256 * 1024 * 1024
REQUIRED = {'tiny_red_first': False, 'tiny_red_second': False,
    'rejected_large_pair': False, 'restore_first': True, 'restore_second': True,
    'group_handle_amendment': True, 'paired_baseline': True, 'paired_candidate': True,
    'full_graph_execution': True, 'full_graph_witness': True, 'cold_execution': True,
    'cold_receipt': True, 'fem': True, 'gui': True, 'guards': True, 'ctest': True,
    'source_build': True, 'final_review': True}
DENIED = {'.git', '.beads', '.pixi', '__pycache__', 'CMakeFiles', 'CalculiX',
    'profiles', 'module-cache', 'freecad_user_home', 'freecad_user_data',
    'freecad_user_temp', 'xdg_config_home', 'xdg_data_home', 'xdg_cache_home'}
KINDS = {'json', 'source', 'text', 'native-input', 'native-output',
    'mesh-snapshot', 'profile-data', 'synthetic-fixture'}


def need(value, message):
    if not value:
        raise RuntimeError(message)


def encode(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()


def descriptor(path, data):
    return {'path': str(path), 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


def regular(value, copying):
    path = Path(value)
    need(path.is_absolute() and '..' not in path.parts and str(path) == str(value),
         'Exact canonical absolute input path required')
    roots = [root for root in (TASK, REPO) if path.is_relative_to(root)]
    need(len(roots) == 1, 'Input outside the exact task/repository roots')
    root = roots[0]
    cursor = path
    while cursor != root:
        need(not cursor.is_symlink(), 'Input link is forbidden: ' + str(cursor))
        cursor = cursor.parent
    need(path.is_file(), 'Actual existing file required: ' + str(path))
    if copying:
        need(not DENIED.intersection(path.relative_to(root).parts)
             and not path.name.startswith('private-'), 'Private namespace cannot be copied')
        need(path.stat().st_size <= PER_FILE, 'Per-file cap exceeded')
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--selection-sha256', required=True)
    parser.add_argument('--label', required=True)
    args = parser.parse_args()
    need(not sys.flags.optimize and re.fullmatch('[0-9a-f]{64}', args.selection_sha256),
         'Unoptimized interpreter and exact selection SHA required')
    need(re.fullmatch('[a-z0-9][a-z0-9-]{0,63}', args.label), 'Private draft label invalid')
    selection_path = regular(args.selection, True)
    need(selection_path.parent == COLLECTION, 'Selection must be directly under private collection/')
    captured = {}

    def capture(path, copying=True):
        path = regular(path, copying)
        data = path.read_bytes()
        if str(path) in captured:
            need(captured[str(path)] == data, 'Input changed while drafting')
        else:
            captured[str(path)] = data
        return path, data

    def exact(ref):
        need(set(ref) == {'path', 'sha256', 'bytes'} and type(ref['bytes']) is int
             and ref['bytes'] >= 0 and re.fullmatch('[0-9a-f]{64}', ref['sha256']),
             'Actual exact descriptor required; no pending/prospective role')
        path, data = capture(ref['path'])
        need(descriptor(path, data) == ref, 'Actual descriptor differs: ' + str(path))
        return json.loads(data)

    _, selection_bytes = capture(selection_path)
    need(hashlib.sha256(selection_bytes).hexdigest() == args.selection_sha256,
         'Explicit selection SHA differs')
    selection = json.loads(selection_bytes)
    need(selection['schema'] == 'FreeCAD-3q7-private-plan-selection-v1'
         and selection['pending_roles'] == [], 'Only completed explicit selection may be drafted')
    qualification = exact(selection['qualification_receipt'])
    need(qualification['schema'] == 'FreeCAD-3q7-source-qualification-v1'
         and qualification['passed'] is True and qualification['pending_roles'] == [],
         'A real completed root qualification receipt is required; builder does not create one')
    roles = qualification['roles']
    need(REQUIRED.keys() <= roles.keys()
         and roles.keys() == qualification['role_expectations'].keys()
         == qualification['role_checks'].keys(), 'Missing/inconsistent actual roles')
    for name, ref in roles.items():
        role = exact(ref)
        state = qualification['role_expectations'][name]
        need(type(state) is bool and role.get('passed') is state,
             'Actual role state differs: ' + name)
        if name in REQUIRED:
            need(state is REQUIRED[name], 'Historical/final outcome changed: ' + name)
        need(qualification['role_checks'][name], 'Missing explicit semantic assertions: ' + name)
    custody = exact(selection['synthetic_capsule'])
    need(custody['schema'] == 'FreeCAD-3q7-exact-generic-case-capsule-v1'
         and custody['passed'] is True and custody['copies_exact'] is True
         and custody['originals_unchanged'] is True,
         'Actual exact synthetic capsule custody required')
    rows, indexed = [], set()
    destinations = set()
    for item in selection['files']:
        need(set(item) == {'path', 'destination', 'kind', 'classification'},
             'Only explicit actual file selections allowed')
        path, data = capture(item['path'])
        target = Path(item['destination'])
        need(target.parts and not target.is_absolute() and '..' not in target.parts
             and '\\' not in item['destination'] and target.as_posix() == item['destination']
             and not DENIED.intersection(target.parts)
             and target.name not in {'index.json', 'approved-plan.json'}, 'Unsafe exact destination')
        need(str(path) not in indexed and item['destination'] not in destinations,
             'Duplicate original/destination')
        need(item['kind'] in KINDS and type(item['classification']) is str
             and item['classification'].strip(), 'Explicit kind and honest classification required')
        rows.append({**descriptor(path, data), **{key: item[key]
            for key in ('destination', 'kind', 'classification')}})
        indexed.add(str(path))
        destinations.add(item['destination'])
    mandatory = [selection['qualification_receipt'], selection['synthetic_capsule'], *roles.values()]
    need(all(ref['path'] in indexed for ref in mandatory), 'Qualification/capsule/every role must be selected')
    for name in ('paired_baseline', 'paired_candidate'):
        execution = exact(roles[name])
        for ref in execution['produced_outputs'].values():
            path, data = capture(ref['path'])
            need(descriptor(path, data) == ref and str(path) in indexed,
                 'Every accepted-pair defining output must be explicitly selected')
    for ref in selection['hash_only_references']:
        need(set(ref) == {'path', 'sha256', 'bytes', 'scope'} and ref['scope'],
             'Explicit hash-only scope required')
        path, data = capture(ref['path'], False)
        need(descriptor(path, data) == {key: ref[key] for key in ('path', 'sha256', 'bytes')},
             'Hash-only original differs')
    plan = {'schema': 'FreeCAD-3q7-approved-source-evidence-plan-v1',
        'root_approved': False,
        'draft_status': 'Exact actual inputs only; root semantic/privacy/cap review and approval pending',
        'approved_limits': {'per_file_bytes': PER_FILE, 'packet_uncompressed_bytes': PACKET},
        'qualification_receipt': selection['qualification_receipt'],
        'synthetic_capsule': selection['synthetic_capsule'],
        'synthetic_file_approvals': custody['files'],
        'hash_only_references': selection['hash_only_references'], 'files': rows}
    plan_bytes = encode(plan)
    total = sum(row['bytes'] for row in rows) + len(plan_bytes)
    report = {'schema': 'FreeCAD-3q7-private-plan-draft-report-v1',
        'status': 'UNAPPROVED PRIVATE DRAFT; no qualification/publication check performed',
        'files': len(rows), 'payload_and_draft_plan_uncompressed_bytes': total,
        'collector_packet_cap_bytes': PACKET,
        'over_cap_before_index_and_summary': total > PACKET,
        'index_and_summary_additional_bytes_not_yet_included': True,
        'root_approval_pending': True, 'publication_performed': False,
        'actual_selection': descriptor(selection_path, selection_bytes),
        'note': 'Do not omit evidence or increase limits automatically. Collector check-only must independently validate the final root-approved exact plan and complete index/summary-inclusive cap.'}
    outputs = {COLLECTION / (args.label + '-plan-draft.json'): plan_bytes,
        COLLECTION / (args.label + '-plan-draft-report.json'): encode(report)}
    need(all(not path.exists() and not path.is_symlink() for path in outputs),
         'Draft outputs must be new private files')
    for path, data in captured.items():
        need(regular(path, False).read_bytes() == data, 'Captured input changed before private draft')
    for path, data in outputs.items():
        with path.open('xb') as stream:
            stream.write(data)
    print(json.dumps({'private_draft_only': True, 'root_approved': False,
        'publication_performed': False, 'outputs': [descriptor(path, data)
            for path, data in outputs.items()], 'payload_and_draft_plan_bytes': total}, sort_keys=True))


if __name__ == '__main__':
    main()
