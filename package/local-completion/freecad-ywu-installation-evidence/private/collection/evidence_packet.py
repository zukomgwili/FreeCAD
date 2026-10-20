"""Explicit-file evidence encoding only; no application/gate execution.

This module defines helpers and an in-memory publication plan. Importing it
does not read product state, write files, launch subprocesses or import FreeCAD.
Root must review every producer before invoking it. Inventory-bearing original
receipts remain private; any excerpt identifies its original bytes and omitted
top-level fields. This is not a new independent native or engineering audit.
"""
import sys
sys.dont_write_bytecode = True

import ast
import gzip
import hashlib
import json
from pathlib import Path
import re


PRIVATE = Path(__file__).resolve().parent.parent
REPOSITORY = Path('/Users/zukomgwili/src/FreeCAD')
SOURCES = {'private': PRIVATE, 'repository': REPOSITORY}
GZIP_THRESHOLD = 64 * 1024
EXCLUDED_NAMES = {
    'private-custody-before.json', 'private-custody-after.json',
    'private-application-before.json', 'private-application-after.json',
    'private-baseline.json',
    'baseline-inventory.json', 'stage-inventory.json',
    'profile-inventories.json', 'critical-before-DESTDIR.json',
    'environment.log', '.env', 'user.cfg', 'system.cfg',
}
EXCLUDED_PARTS = {
    '__pycache__', 'CalculiX', '.pixi', '.git', 'profiles',
    'freecad_user_home', 'freecad_user_data', 'freecad_user_temp',
    'xdg_config_home', 'xdg_data_home', 'xdg_cache_home',
}
EXCLUDED_SUFFIXES = {'.cfg', '.pyc', '.pyo', '.so', '.dylib', '.exe', '.o', '.a'}
INVENTORY_KEYS = {
    'app_before', 'app_after', 'critical_before', 'critical_after',
    'private_custody_before', 'private_baseline', 'inventory',
    'app_inventory', 'application_inventory', 'profile_inventory',
    'profile_inventories', 'profiles',
}
SECRET_KEYS = {
    'password', 'api_key', 'apikey', 'secret', 'authorization', 'cookie',
    'access_token', 'refresh_token', 'environment', 'environ',
}
BINARY_MAGICS = {
    b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xce\xfa\xed\xfe',
    b'\xfe\xed\xfa\xce', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca',
    b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca', b'\x7fELF',
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_regular(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), f'Not a regular file: {path}')
    return path.read_bytes()


def descriptor(path):
    """Hash/path/size only; runtime binaries may be referenced, never copied."""
    path = Path(path)
    data = read_regular(path)
    return {'path': str(path), 'sha256': digest(data), 'bytes': len(data)}


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()


def load(path):
    return json.loads(read_regular(path))


def relative_path(value):
    path = Path(value)
    require(path.parts and not path.is_absolute() and '..' not in path.parts,
            f'Unsafe relative path: {value}')
    require(not EXCLUDED_PARTS.intersection(path.parts) and path.name not in EXCLUDED_NAMES
            and not (path.name.startswith('private-') and path.suffix == '.json')
            and path.suffix.lower() not in EXCLUDED_SUFFIXES, f'Excluded evidence path: {value}')
    return path


def source_path(scope, relative):
    require(scope in SOURCES, f'Unknown evidence source scope: {scope}')
    parent = SOURCES[scope]
    path = parent / relative_path(relative)
    require(path.resolve().is_relative_to(parent.resolve()), f'Escaped source root: {path}')
    cursor = path
    while cursor != parent:
        require(not cursor.is_symlink(), f'Input link is not permitted: {cursor}')
        cursor = cursor.parent
    return path


def privacy_check(value, location):
    if isinstance(value, dict):
        # Inventory capture names are excluded too, but a renamed explicit
        # input must not bypass the raw app/profile inventory prohibition.
        require(not (isinstance(value.get('.'), dict) and
                     value['.'].get('kind') == 'dir' and 'mode' in value['.']),
                f'Raw filesystem inventory body: {location}')
        require(not INVENTORY_KEYS.intersection(value), f'Raw inventory body: {location}')
        require(not SECRET_KEYS.intersection(str(k).lower() for k in value),
                f'Environment/secret dictionary: {location}')
        for item in value.values():
            privacy_check(item, location)
    elif isinstance(value, list):
        for item in value:
            privacy_check(item, location)


def check_payload(data, name, kind):
    path = Path(name)
    require(data[:4] not in BINARY_MAGICS and not data.startswith(b'MZ'),
            f'Runtime binary cannot be published: {name}')
    require(len(data) <= 32 * 1024 * 1024, f'Oversized evidence file: {name}')
    if path.suffix == '.FCStd':
        require(kind == 'generic-fixture' and data.startswith(b'PK\x03\x04'),
                f'Only explicitly approved generic FCStd fixtures are allowed: {name}')
    else:
        text = data.decode('utf-8')
        require(b'\x00' not in data, f'Non-text runtime payload: {name}')
        require(not re.search(r'(?im)^(?:OPENAI_API_KEY|AWS_SECRET_ACCESS_KEY|'
            r'GITHUB_TOKEN|GH_TOKEN|ACCESS_TOKEN|REFRESH_TOKEN|PASSWORD)\s*=\s*\S+', text),
            f'Secret-bearing environment dump: {name}')
    if path.suffix in {'.FCStd', '.frd', '.dat', '.inp', '.accounting'} or name.endswith('.accounting.out'):
        require(kind == 'generic-fixture', f'Native model/result needs explicit generic-fixture approval: {name}')
    if path.suffix == '.py':
        ast.parse(data, filename=name)
    if path.suffix == '.json':
        privacy_check(json.loads(data), name)


class Packet:
    """Prepare exact copied streams from a complete, explicit root file list."""

    def __init__(self):
        self.pending = {}
        self.records = []
        self.originals = {}

    def add(self, entry):
        require(set(entry).issubset({'scope', 'path', 'destination', 'sha256',
                    'kind', 'classification', 'omit_top_level_fields', 'fixture_scope'}),
                'Unknown explicit file-manifest field')
        require(all(key in entry for key in ('scope', 'path', 'destination',
                    'sha256', 'kind', 'classification')), 'Incomplete explicit evidence entry')
        require(entry['kind'] in {'text', 'receipt', 'source', 'generic-fixture'}, 'Unknown evidence kind')
        require(isinstance(entry['classification'], str) and entry['classification'],
                'Evidence requires a nonempty classification')
        require(re.fullmatch(r'[0-9a-f]{64}', entry['sha256']), 'Explicit SHA256 is required')
        path = source_path(entry['scope'], entry['path'])
        original = read_regular(path)
        require(digest(original) == entry['sha256'], f'Approved file changed: {path}')
        omitted = entry.get('omit_top_level_fields', [])
        require(isinstance(omitted, list) and len(omitted) == len(set(omitted))
                and all(isinstance(k, str) for k in omitted), 'Invalid excerpt omission declaration')
        data = original
        transformation = 'exact bytes'
        if omitted:
            require(path.suffix == '.json' and entry['kind'] == 'receipt', 'Only JSON receipts may be excerpted')
            obj = json.loads(original)
            require(isinstance(obj, dict) and set(omitted).issubset(obj), 'Omission field absent from original receipt')
            facts = {key: value for key, value in obj.items() if key not in omitted}
            privacy_check(facts, str(path))
            data = json_bytes({
                'schema': 'FreeCAD-ywu-installation-curated-receipt-v1',
                'original_private_receipt': {'path': str(path), 'sha256': digest(original), 'bytes': len(original)},
                'omitted_top_level_fields': sorted(omitted), 'facts': facts,
                'transformation': 'Explicit inventory/large metadata omissions; retained facts are copied, not a new independent audit.',
            })
            transformation = 'DERIVED curated JSON excerpt; not byte-identical to original receipt'
        if entry['kind'] == 'generic-fixture':
            require(entry.get('fixture_scope') == 'generic software QA; not a retained engineering model',
                    'Generic fixture scope must be explicitly approved')
        check_payload(data, str(path), entry['kind'])
        destination = relative_path(entry['destination'])
        stored = data
        encoding = 'identity'
        if len(data) >= GZIP_THRESHOLD and path.suffix != '.FCStd':
            stored = gzip.compress(data, compresslevel=9, mtime=0)
            destination = Path(str(destination) + '.gz')
            encoding = 'gzip'
            require(gzip.decompress(stored) == data, 'Gzip did not preserve exact bytes')
        key = str(destination)
        require(key not in self.pending and key != 'index.json', f'Duplicate/reserved output: {key}')
        self.pending[key] = stored
        self.originals[str(path)] = digest(original)
        self.records.append({
            'file': key, 'kind': entry['kind'], 'classification': entry['classification'],
            'stored_sha256': digest(stored), 'stored_bytes': len(stored), 'encoding': encoding,
            'uncompressed_sha256': digest(data), 'uncompressed_bytes': len(data),
            'original_private_or_repository_path': str(path),
            'original_sha256': digest(original), 'original_bytes': len(original),
            'transformation': transformation, 'omitted_top_level_fields': sorted(omitted),
        })

    def unchanged(self):
        for path, wanted in self.originals.items():
            require(descriptor(path)['sha256'] == wanted, f'Original changed during collection: {path}')

    def publish_new(self, destination, summary_path, index, summary):
        """Call only after workflow validation; never replace existing evidence."""
        destination, summary_path = Path(destination), Path(summary_path)
        require(destination.parent == summary_path.parent and destination.parent.is_dir()
                and not destination.parent.is_symlink(), 'Unsafe publication parent')
        require(not destination.exists() and not destination.is_symlink() and
                not summary_path.exists() and not summary_path.is_symlink(), 'Publication already exists')
        privacy_check(index, 'publication index')
        privacy_check(summary, 'publication summary')
        index_data, summary_data = json_bytes(index), json_bytes(summary)
        require(index['files'] == sorted(self.records, key=lambda row: row['file']), 'Index differs from explicit byte plan')
        require(summary['evidence']['index_sha256'] == digest(index_data), 'Summary/index hash fence differs')
        self.unchanged()
        destination.mkdir()
        for relative, data in sorted(self.pending.items()):
            path = destination / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(data)
        with (destination / 'index.json').open('xb') as stream:
            stream.write(index_data)
        with summary_path.open('xb') as stream:
            stream.write(summary_data)
        actual = {str(p.relative_to(destination)) for p in destination.rglob('*')
                  if p.is_file() and p != destination / 'index.json'}
        require(actual == set(self.pending), 'Exact publication coverage differs from plan')
        for relative, data in self.pending.items():
            require(read_regular(destination / relative) == data, f'Published byte mismatch: {relative}')
        require(read_regular(destination / 'index.json') == index_data and
                read_regular(summary_path) == summary_data, 'Published index/summary differs')
        self.unchanged()
