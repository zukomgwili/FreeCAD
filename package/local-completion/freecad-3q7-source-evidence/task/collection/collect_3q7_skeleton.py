"""UNEXECUTED explicit-byte/privacy collector skeleton; NOT publication-ready.

This draft can only check a later root-approved explicit file plan. It cannot
publish, infer a qualification verdict, run Git/native/app/tests, or bless any
pending gate. Final role-specific semantic checks and a separately reviewed
publication entrypoint must be added in a NEW version after actual evidence
exists. No private inventories, environments, binaries or user models belong
in this packet. Historical failed receipts are never repaired.
"""
import sys
sys.dont_write_bytecode = True
import argparse
import ast
import gzip
import hashlib
import json
from pathlib import Path
import re

TASK = Path('/private/tmp/freecad-3q7-Pq3Byy')
REPO = Path('/Users/zukomgwili/src/FreeCAD')
APP = Path('/Applications/FreeCAD-27.1.0.app')
MAX_BYTES = 32 * 1024 * 1024
DENIED_PARTS = {'.git', '.beads', '.pixi', '__pycache__', 'CMakeFiles',
    'CalculiX', 'profiles', 'module-cache', 'freecad_user_home', 'freecad_user_data',
    'freecad_user_temp', 'xdg_config_home', 'xdg_data_home', 'xdg_cache_home'}
DENIED_SUFFIXES = {'.cfg', '.pyc', '.pyo', '.so', '.dylib', '.o', '.a', '.exe',
                   '.fcstd', '.frd'}
KINDS = {'json', 'source', 'text', 'native-input', 'native-output',
         'mesh-snapshot', 'profile-data'}
RAW_KEYS = {'environment', 'environ', 'profiles', 'profile_inventories',
    'profile_inventory', 'app_inventory', 'application_inventory', 'inventory',
    'critical_before', 'critical_after'}
SECRET_KEYS = {'password', 'api_key', 'apikey', 'secret', 'access_token',
               'refresh_token', 'authorization', 'cookie'}
MAGIC = {b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xce\xfa\xed\xfe',
    b'\xfe\xed\xfa\xce', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca',
    b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca', b'\x7fELF'}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def regular(path, copied):
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts, 'Absolute exact path required')
    roots = [root for root in (TASK, REPO, APP) if path.is_relative_to(root)]
    require(len(roots) == 1, 'Input outside known task/repository/application roots')
    root = roots[0]
    cursor = path
    while cursor != root:
        require(not cursor.is_symlink(), 'Input links are excluded: ' + str(cursor))
        cursor = cursor.parent
    require(path.is_file(), 'Missing regular input: ' + str(path))
    if copied:
        require(root != APP and not DENIED_PARTS.intersection(path.relative_to(root).parts),
                'Runtime/profile/vendor-tree payload is excluded')
        require(not path.name.startswith('private-') and path.name not in {'.env', 'user.cfg', 'system.cfg'}
                and path.suffix.lower() not in DENIED_SUFFIXES, 'Private/config/binary/model payload excluded')
        require(path.stat().st_size <= MAX_BYTES, 'No unreviewed size-cap exception')
    return path


def privacy(value):
    if isinstance(value, dict):
        require(not (isinstance(value.get('.'), dict) and value['.'].get('kind') == 'dir'),
                'Raw application/profile inventory body')
        keys = {str(key).lower() for key in value}
        require(not RAW_KEYS.intersection(keys) and not SECRET_KEYS.intersection(keys),
                'Raw inventory/environment/secret dictionary')
        require(not {'dev', 'inode', 'mtime_ns', 'ctime_ns'}.issubset(keys),
                'Raw selected-dependency stat inventory')
        for item in value.values():
            privacy(item)
    elif isinstance(value, list):
        for item in value:
            privacy(item)


def payload(path, data, kind):
    require(kind in KINDS and data[:4] not in MAGIC and not data.startswith(b'MZ'),
            'Unknown kind or forbidden runtime executable payload')
    if kind == 'profile-data':
        require(path.name == 'whole-public-write.prof', 'Only a declared own profiler blob is allowed')
        return  # Never unmarshal/execute diagnostic profiler bytes.
    text = data.decode('utf-8')
    require(b'\x00' not in data and not re.search(r'(?im)^(?:OPENAI_API_KEY|GITHUB_TOKEN|GH_TOKEN|'
        r'AWS_SECRET_ACCESS_KEY|PASSWORD|ACCESS_TOKEN|REFRESH_TOKEN)\s*=\s*\S+', text),
        'Environment or credential dump')
    if path.suffix == '.py':
        ast.parse(data, filename=str(path))
    if path.suffix == '.json':
        privacy(json.loads(data))


def capture(plan_path, wanted):
    raw_plan = regular(plan_path, copied=True).read_bytes()
    require(digest(raw_plan) == wanted, 'Exact approved plan SHA differs')
    plan = json.loads(raw_plan)
    require(plan['schema'] == 'FreeCAD-3q7-approved-source-evidence-plan-v1'
            and plan['root_approved'] is True, 'Proposal or unapproved plan is not collectable')
    require(plan_path.parent == TASK / 'collection', 'Explicit private collection plan required')
    privacy(plan)
    rows = plan['files']
    require(rows and len(rows) == len({row['path'] for row in rows})
            == len({row['destination'] for row in rows}), 'Duplicate/missing explicit file rows')
    captured, pending, entries = {}, {}, []
    for row in rows:
        require(set(row) == {'path', 'destination', 'sha256', 'bytes', 'kind', 'classification'},
                'Unexpected explicit file fields')
        path = regular(row['path'], copied=True)
        data = path.read_bytes()
        require(digest(data) == row['sha256'] and len(data) == row['bytes']
                and bool(row['classification']), 'Changed or unclassified original: ' + str(path))
        destination = Path(row['destination'])
        require(destination.parts and not destination.is_absolute() and '..' not in destination.parts
                and '\\' not in row['destination'] and not DENIED_PARTS.intersection(destination.parts)
                and destination.name != 'index.json', 'Unsafe destination')
        payload(path, data, row['kind'])
        encoding = 'gzip' if len(data) >= 65536 else 'identity'
        stored = gzip.compress(data, compresslevel=9, mtime=0) if encoding == 'gzip' else data
        target = destination.as_posix() + ('.gz' if encoding == 'gzip' else '')
        require(target not in pending, 'Transformed destination collision')
        captured[str(path)] = data
        pending[target] = stored
        entries.append({'file': target, 'kind': row['kind'], 'classification': row['classification'],
            'original_path': str(path), 'original_sha256': digest(data), 'original_bytes': len(data),
            'stored_sha256': digest(stored), 'stored_bytes': len(stored), 'encoding': encoding,
            'decoded_sha256': digest(data), 'decoded_bytes': len(data), 'transformation': 'exact bytes'})
    references = {}
    for row in plan['hash_only_references']:
        require(set(row) == {'path', 'sha256', 'bytes', 'scope'}, 'Unexpected hash-only reference fields')
        path = regular(row['path'], copied=False)
        require(str(path) not in references and row['scope'] and file_hash(path) == row['sha256']
                and path.stat().st_size == row['bytes'], 'Missing/changed/duplicate hash-only reference')
        references[str(path)] = row
    for path, data in captured.items():
        require(regular(path, copied=True).read_bytes() == data, 'Original drifted during draft checks')
    for path, row in references.items():
        require(file_hash(Path(path)) == row['sha256'] and Path(path).stat().st_size == row['bytes'],
                'Hash-only original drifted during draft checks')
    require(plan_path.read_bytes() == raw_plan, 'Approved plan drifted during draft checks')
    return {'schema': 'FreeCAD-3q7-draft-byte-policy-check-v1',
        'byte_policy_check_passed': True, 'publication_ready': False, 'writes': 0,
        'semantic_qualification_checked': False,
        'reason': 'Draft skeleton only; final actual role semantics and publication entrypoint are intentionally absent',
        'plan_sha256': wanted, 'files': entries, 'hash_only_references': list(references.values()),
        'prepared_compressed_payloads': len(pending)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True, type=Path)
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--check-only', required=True, action='store_true')
    args = parser.parse_args()
    require(not sys.flags.optimize and re.fullmatch(r'[0-9a-f]{64}', args.plan_sha256),
            'Unoptimized interpreter and exact plan SHA required')
    print(json.dumps(capture(args.plan, args.plan_sha256), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
