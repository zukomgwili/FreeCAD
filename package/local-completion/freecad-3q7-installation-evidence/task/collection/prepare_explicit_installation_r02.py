"""Root-only private exact capsule / unapproved plan drafting, never publish.

No product helpers are imported and no native/app/build/test/Git process runs.
Both actions need an exact SHA-bound explicit selection. Capsule copying also
requires root_approved true and actual completed installed-capacity evidence.
Plan drafting requires an actual completed semantic review, writes only new
private files and always leaves root_approved false. No discovery by glob/tree.
"""
import sys
sys.dont_write_bytecode = True
import argparse
import hashlib
import json
from pathlib import Path
import re

TASK = Path('/private/tmp/freecad-3q7-install-W35DLJ')
REPO = Path('/Users/zukomgwili/src/FreeCAD')
COLLECTION = TASK / 'collection'
NATIVE = '6c02452a896727af6cb4578fd3fb6bbfbdd48e3fb887c1c04fa2d8b171976c66'
PER_FILE, PACKET = 128 * 1024 * 1024, 512 * 1024 * 1024
CASE_NAMES = {'coupled-before-export.FCStd', 'coupled-native-current.FCStd', 'witness-receipt.json',
    'independent-export-audit.json', 'physical-face-motion-proof.json', 'motion-from-original-dat.json',
    'cold-case.json', 'geometry-contract.json', 'export-properties.json', 'native-properties.json',
    'native-accounting-data.json', 'mesh-membership.json', 'native.stdout', 'native.stderr',
    'native/Mesh.inp', 'native/Mesh.accounting', 'native/Mesh.accounting.json',
    'native/Mesh.accounting.out', 'native/Mesh.dat', 'native/Mesh.frd'}
CASE_REQUIRED = {'coupled-before-export.FCStd', 'coupled-native-current.FCStd', 'witness-receipt.json',
    'cold-case.json', 'native-accounting-data.json', 'native/Mesh.inp', 'native/Mesh.accounting',
    'native/Mesh.accounting.out', 'native/Mesh.dat', 'native/Mesh.frd'}
DENIED = {'.git', '.beads', '.pixi', '__pycache__', 'CMakeFiles', 'CalculiX', 'profiles',
    'module-cache', 'freecad_user_home', 'freecad_user_data', 'freecad_user_temp',
    'xdg_config_home', 'xdg_data_home', 'xdg_cache_home'}


def need(value, message):
    if not value:
        raise RuntimeError(message)


def encode(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()


def desc(path, data):
    return {'path': str(path), 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


def regular(value):
    path = Path(value)
    need(path.is_absolute() and '..' not in path.parts and str(path) == str(value), 'Exact canonical absolute path required')
    roots = [root for root in (TASK, REPO) if path.is_relative_to(root)]
    need(len(roots) == 1, 'Input outside task/repository roots')
    cursor = path
    while cursor != roots[0]:
        need(not cursor.is_symlink(), 'Input link excluded')
        cursor = cursor.parent
    need(path.is_file(), 'Actual existing file required: ' + str(path))
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('capsule', 'plan-draft'))
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--selection-sha256', required=True)
    parser.add_argument('--label', required=True)
    args = parser.parse_args()
    need(not sys.flags.optimize and re.fullmatch('[0-9a-f]{64}', args.selection_sha256), 'Unoptimized exact-SHA invocation required')
    need(re.fullmatch('[a-z0-9][a-z0-9-]{0,63}', args.label), 'Private new output label invalid')
    source = regular(args.selection)
    need(source.parent == COLLECTION, 'Explicit private collection selection required')
    captured = {}

    def capture(value):
        path = regular(value)
        data = path.read_bytes()
        need(len(data) <= PER_FILE, 'Per-file cap exceeded')
        if str(path) in captured:
            need(captured[str(path)] == data, 'Input changed while capturing')
        else:
            captured[str(path)] = data
        return path, data

    def exact(ref):
        need(set(ref) == {'path', 'sha256', 'bytes'} and type(ref['bytes']) is int
             and ref['bytes'] >= 0 and re.fullmatch('[0-9a-f]{64}', ref['sha256']), 'Exact actual descriptor required')
        path, body = capture(ref['path'])
        need(desc(path, body) == ref, 'Actual descriptor differs')
        return json.loads(body)

    _, selection_bytes = capture(source)
    need(hashlib.sha256(selection_bytes).hexdigest() == args.selection_sha256, 'Selection SHA differs')
    selected = json.loads(selection_bytes)
    outputs = {}
    if args.action == 'capsule':
        need(selected['schema'] == 'FreeCAD-3q7-installation-case-retention-plan-v1'
             and selected['root_approved'] is True, 'Exact root-approved capsule selection required')
        execution = exact(selected['source_run_execution'])
        need(execution['passed'] is True and execution['returncode'] == 0 and execution['timed_out'] is False
             and execution['child_reaped'] is True and execution['process_group_gone'] is True
             and execution['module'] == 'femtest.app.test_moving_port_capacity_native', 'Completed real installed capacity execution required')
        original = Path(selected['source_witness_directory'])
        target = Path(selected['copy_directory'])
        need(original == Path(execution['capacity_witness']['directory'])
             and original.is_relative_to(TASK / 'installed-capacity/freecad_user_temp')
             and original.name == 'witness' and target.is_absolute() and target.parent == TASK
             and target.name == args.label and not target.exists() and not target.is_symlink(), 'Exact fresh witness/new private capsule paths differ')
        rows = selected['files']
        names = {row['path'] for row in rows}
        need(len(rows) == len(names) and CASE_REQUIRED <= names <= CASE_NAMES, 'Unknown/duplicate/missing exact generic leaf')
        need(sum(row['bytes'] for row in rows) <= PACKET, 'Capsule cap exceeded')
        for row in rows:
            need(set(row) == {'source', 'path', 'sha256', 'bytes'}
                 and row['source'] == str(original / row['path']), 'Unexpected exact capsule row')
            path, body = capture(row['source'])
            need(desc(path, body) == {'path': row['source'], 'sha256': row['sha256'], 'bytes': row['bytes']}, 'Approved original capsule bytes differ')
            outputs[target / row['path']] = body
        witness_body = captured[str(original / 'witness-receipt.json')]
        witness = json.loads(witness_body)
        need(hashlib.sha256(witness_body).hexdigest() == execution['capacity_witness']['witness_receipt_sha256']
             and witness['passed'] is True and witness['actual_binary_sha256'] == NATIVE
             and witness['engineering_project_accessed_or_solved'] is False
             and witness['engineering_or_BIM_accepted'] is False, 'Not actual public generic witness')
        for row in rows:
            if row['path'] != 'witness-receipt.json':
                need(witness['retained_files'][row['path']] == {'sha256': row['sha256'], 'bytes': row['bytes']}, 'Not exact witness-bound generic output')
        omitted = selected['omitted_witness_files']
        omitted_names = {row['path'] for row in omitted}
        expected_omissions = {'mesh/CoupledCells_Geometry.brep', 'mesh/CoupledCells_Mesh.vtk',
            'mesh/shape2mesh.geo', 'native/Mesh.12d', 'native/Mesh.cvg', 'native/Mesh.sta', 'native/spooles.out'}
        need(len(omitted) == len(omitted_names) == 7 and omitted_names == expected_omissions
             and omitted_names.isdisjoint(names)
             and set(witness['retained_files']) == (names - {'witness-receipt.json'}) | omitted_names,
             'Exact selected/omitted witness coverage required; no whole-witness retention claim')
        for row in omitted:
            need(set(row) == {'path', 'sha256', 'bytes', 'scope'} and row['scope']
                 and witness['retained_files'][row['path']] == {'sha256': row['sha256'], 'bytes': row['bytes']},
                 'Accurate exact omission descriptor/scope required')
            path, body = capture(original / row['path'])
            need(desc(path, body) == {'path': str(path), 'sha256': row['sha256'], 'bytes': row['bytes']},
                 'Omitted original hash/size differs')
        custody_path = COLLECTION / (args.label + '-custody.json')
        need(not custody_path.exists() and not custody_path.is_symlink(), 'New capsule custody output required')
        custody = {'schema': 'FreeCAD-3q7-installation-exact-generic-case-capsule-v1',
            'passed': True, 'copies_exact': True, 'originals_unchanged': True,
            'engineering_project_accessed_or_solved': False,
            'source_run_execution': selected['source_run_execution'],
            'source_witness_directory': str(original), 'copy_directory': str(target), 'files': rows,
            'omitted_witness_files': omitted, 'whole_witness_retention_claimed': False,
            'approved_selection': desc(source, selection_bytes),
            'scope': 'Exact individually approved synthetic software-fixture proof bytes only; original receipt/native/saved paths remain literal. No qualification or installation is performed by this copy helper.'}
        outputs[custody_path] = encode(custody)
    else:
        need(selected['schema'] == 'FreeCAD-3q7-installation-explicit-selection-v1'
             and selected['pending_roles'] == [], 'Only completed explicit selection can be drafted')
        review = exact(selected['semantic_review'])
        need(review['schema'] == 'FreeCAD-3q7-installation-final-gates-independent-review-v1'
             and review['passed'] is True and review['pending_roles'] == [], 'Actual completed semantic review required; no prospective PASS')
        custody = exact(selected['capsule_custody'])
        need(custody['schema'] == 'FreeCAD-3q7-installation-exact-generic-case-capsule-v1'
             and custody['passed'] is True and custody['copies_exact'] is True
             and custody['originals_unchanged'] is True, 'Actual completed capsule custody required')
        rows, names, originals, captures = [], set(), set(), set()
        for row in selected['file_selections']:
            need(set(row) == {'original_path', 'capture_path', 'destination', 'kind', 'classification'}, 'Explicit file selection fields required')
            origin, original_body = capture(row['original_path'])
            capture_path, body = capture(row['capture_path'])
            need(body == original_body, 'Original/capture bytes differ; no provenance rebinding')
            target = Path(row['destination'])
            need(target.parts and not target.is_absolute() and '..' not in target.parts
                 and '\\' not in row['destination'] and target.as_posix() == row['destination']
                 and not DENIED.intersection(target.parts)
                 and target.name not in {'index.json', 'approved-plan.json'}, 'Unsafe explicit destination')
            need(str(origin) not in originals and str(capture_path) not in captures and row['destination'] not in names, 'Duplicate explicit selection')
            rows.append({**row, 'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body)})
            names.add(row['destination'])
            originals.add(str(origin))
            captures.add(str(capture_path))
        need(selected['semantic_review']['path'] in originals and selected['capsule_custody']['path'] in originals
             and all(ref['path'] in originals for ref in review['roles'].values()), 'Every actual role/review/capsule must be retained')
        for ref in review['roles'].values():
            exact(ref)
        plan = {'schema': 'FreeCAD-3q7-installation-approved-plan-v1', 'root_approved': False,
            'pending_roles': [], 'draft_status': 'Actual existing bytes only; root approval and collector check-only remain required',
            'approved_limits': {'per_file_bytes': PER_FILE, 'packet_uncompressed_bytes': PACKET},
            'semantic_review': selected['semantic_review'], 'capsule_custody': selected['capsule_custody'],
            'synthetic_file_approvals': custody['files'], 'files': rows}
        body = encode(plan)
        total = sum(row['bytes'] for row in rows) + len(body)
        report = {'schema': 'FreeCAD-3q7-installation-private-plan-draft-report-v1',
            'status': 'UNAPPROVED PRIVATE DRAFT; not a collector preflight or publication PASS',
            'files': len(rows), 'payload_and_draft_plan_bytes': total, 'packet_cap_bytes': PACKET,
            'over_cap_before_index_summary': total > PACKET, 'additional_index_summary_bytes_not_included': True,
            'root_approval_pending': True, 'publication_performed': False,
            'selection': desc(source, selection_bytes)}
        outputs[COLLECTION / (args.label + '-plan-draft.json')] = body
        outputs[COLLECTION / (args.label + '-plan-draft-report.json')] = encode(report)
        need(all(not path.exists() and not path.is_symlink() for path in outputs), 'Private draft outputs must be new')
    for path, body in captured.items():
        need(regular(path).read_bytes() == body, 'Original changed before private writes')
    if args.action == 'capsule':
        target.mkdir()
    for path, body in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(body)
    for path, body in outputs.items():
        need(path.read_bytes() == body, 'New private copy differs')
    for path, body in captured.items():
        need(regular(path).read_bytes() == body, 'Original changed after private writes')
    print(json.dumps({'private_action': args.action, 'publication_performed': False,
        'actual_qualification_performed_by_this_helper': False,
        'outputs': [desc(path, body) for path, body in outputs.items()]}, sort_keys=True))


if __name__ == '__main__':
    main()
