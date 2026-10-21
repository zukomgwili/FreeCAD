"""Root-only, new-only retention of individually approved fresh synthetic files."""
import argparse
import hashlib
import json
import re
from pathlib import Path

TASK = Path('/private/tmp/freecad-3q7-Pq3Byy')
RUN = TASK / 'source-qa/capacity-native-r01'
OUT = TASK / 'generic-case-capsule-r01'
RECEIPT = TASK / 'collection/generic-case-custody-r01.json'
ALLOWED = {'coupled-before-export.FCStd', 'coupled-native-current.FCStd',
    'witness-receipt.json', 'independent-export-audit.json', 'physical-face-motion-proof.json',
    'motion-from-original-dat.json', 'cold-case.json', 'geometry-contract.json',
    'export-properties.json', 'native-properties.json', 'native-accounting-data.json',
    'mesh-membership.json', 'native.stdout', 'native.stderr', 'native/Mesh.inp',
    'native/Mesh.accounting', 'native/Mesh.accounting.json', 'native/Mesh.accounting.out',
    'native/Mesh.dat', 'native/Mesh.frd'}

def need(value, message):
    if not value:
        raise RuntimeError(message)

def digest(data):
    return hashlib.sha256(data).hexdigest()

def desc(path, data):
    return {'path': str(path), 'sha256': digest(data), 'bytes': len(data)}

def capture(path):
    need(path.is_absolute() and path.is_relative_to(TASK) and '..' not in path.parts,
         'Exact task-local absolute path required')
    need(path.is_file() and not any(p.is_symlink() for p in (path, *path.parents)),
         'Regular nonlinked source required')
    return path.read_bytes()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approval', required=True, type=Path)
    parser.add_argument('--approval-sha256', required=True)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    approval_bytes = capture(args.approval)
    need(digest(approval_bytes) == args.approval_sha256, 'Approval SHA differs')
    approval = json.loads(approval_bytes)
    need(approval['schema'] == 'FreeCAD-3q7-root-approved-exact-generic-case-v1'
         and approval['root_approved'] is True, 'Explicit root approval required')
    execution_path = RUN / 'execution.json'
    execution_bytes = capture(execution_path)
    need(desc(execution_path, execution_bytes) == approval['source_run_execution'],
         'Actual physical execution differs')
    execution = json.loads(execution_bytes)
    need(execution['passed'] is True and execution['returncode'] == 0
         and execution['reaped'] is True and execution['process_group_gone'] is True
         and execution['unit_only'] is False and execution['discovery_only'] is False
         and not execution['skipped_lines'] and not execution['missing_repeated_or_skipped_ids'],
         'Completed fresh physical gate required')
    log_path = RUN / 'run.log'
    log_bytes = capture(log_path)
    need(digest(log_bytes) == execution['log_sha256'], 'Physical log binding differs')
    prefixes = re.findall(r'^Native capacity evidence: ([^\r\n]+)$',
                          log_bytes.decode('utf-8'), re.M)
    need(len(prefixes) == 1, 'One actual producer-logged native witness required')
    manifest_path = RUN / 'manifest.json'
    manifest_bytes = capture(manifest_path)
    need(digest(manifest_bytes) == execution['manifest_sha256'], 'Physical manifest differs')
    manifest = json.loads(manifest_bytes)
    need(manifest['module'] == 'femtest.app.test_moving_port_capacity_native'
         and manifest['case'] == 'capacity' and manifest['expected_count'] == 2
         and manifest['expected_ids'] == [
             'femtest.app.test_moving_port_capacity_native.TestMovingPortCapacityNative.'
             'test_complete_132_bay_graph_obeys_the_native_declaration_budget']
         and len(execution['unittest_counts']) == 1
         and execution['unittest_counts'][0][0] == '2', 'Exact fresh physical test required')
    source = Path(approval['source_witness_directory'])
    need(source.is_relative_to(RUN / 'freecad_user_temp') and source.name == 'witness',
         'Exact fresh physical source required')
    need(source == Path(prefixes[0].strip()) / 'witness',
         'Source is not the actual producer-logged witness')
    need(approval['copy_directory'] == str(OUT), 'Fixed new private capsule required')
    rows = approval['files']
    names = {row['path'] for row in rows}
    need(len(names) == len(rows) and names <= ALLOWED and
         {'witness-receipt.json', 'cold-case.json', 'native-accounting-data.json',
          'coupled-before-export.FCStd',
          'coupled-native-current.FCStd', 'native/Mesh.inp', 'native/Mesh.accounting',
          'native/Mesh.accounting.json', 'native/Mesh.accounting.out',
          'native/Mesh.dat', 'native/Mesh.frd'} <= names,
         'Unknown, repeated or missing approved synthetic leaves')
    raw = {}
    for row in rows:
        need(set(row) == {'source', 'path', 'sha256', 'bytes'}
             and row['source'] == str(source / row['path']), 'Nonliteral approved source')
        data = capture(Path(row['source']))
        need(desc(Path(row['source']), data) == {'path': row['source'],
             'sha256': row['sha256'], 'bytes': row['bytes']}, 'Approved bytes differ')
        raw[row['path']] = data
    witness = json.loads(raw['witness-receipt.json'])
    need(witness['passed'] is True and witness['physical_check_count'] == 3566
         and witness['engineering_project_accessed_or_solved'] is False,
         'Qualified public synthetic witness required')
    for row in rows:
        if row['path'] != 'witness-receipt.json':
            need(witness['retained_files'][row['path']] ==
                 {'sha256': row['sha256'], 'bytes': row['bytes']}, 'Producer output differs')
    def fence():
        need(capture(args.approval) == approval_bytes
             and capture(execution_path) == execution_bytes
             and capture(log_path) == log_bytes
             and capture(manifest_path) == manifest_bytes, 'Control input changed')
        for name, data in raw.items():
            need(capture(source / name) == data, 'Original synthetic bytes changed')
    fence()
    need(not OUT.exists() and not OUT.is_symlink() and not RECEIPT.exists(), 'New-only outputs required')
    if not args.check_only:
        OUT.mkdir()
        for name, data in raw.items():
            target = OUT / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(data)
            need(target.read_bytes() == data, 'Retained copy differs')
        fence()
        need({str(path.relative_to(OUT)) for path in OUT.rglob('*') if path.is_file()}
             == names and not any(path.is_symlink() for path in OUT.rglob('*')),
             'Retained capsule path set differs')
        for name, data in raw.items():
            need(capture(OUT / name) == data, 'Retained capsule end fence differs')
        receipt = {'schema': 'FreeCAD-3q7-exact-generic-case-capsule-v1', 'passed': True,
            'copies_exact': True, 'originals_unchanged': True,
            'engineering_project_accessed_or_solved': False,
            'source_run_execution': approval['source_run_execution'],
            'source_run_log': desc(log_path, log_bytes),
            'source_run_manifest': desc(manifest_path, manifest_bytes),
            'source_witness_directory': str(source), 'copy_directory': str(OUT), 'files': rows,
            'exact_approval': desc(args.approval, approval_bytes)}
        with RECEIPT.open('x') as stream:
            json.dump(receipt, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write('\n')
    print(json.dumps({'passed': True, 'check_only': args.check_only,
        'copied_files': 0 if args.check_only else len(rows), 'bytes': sum(map(len, raw.values())),
        'receipt': str(RECEIPT)}))

if __name__ == '__main__':
    main()
