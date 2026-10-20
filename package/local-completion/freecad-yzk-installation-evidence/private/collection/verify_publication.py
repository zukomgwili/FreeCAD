"""Read-only immediate installed-packet verification; no collector/native calls."""
import sys
sys.dont_write_bytecode = True

import argparse
import gzip
import json
from pathlib import Path

from evidence_packet import (PRIVATE, REPOSITORY, check_payload, descriptor, digest,
                             load, privacy_check, read_regular, relative_path, require)


ROOT = REPOSITORY / 'package/local-completion/freecad-yzk-installation-evidence'
SUMMARY = REPOSITORY / 'package/local-completion/freecad-yzk-installation.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index-sha256', required=True)
    parser.add_argument('--summary-sha256', required=True)
    args = parser.parse_args()
    require(not sys.flags.optimize, 'Use an unoptimized interpreter')
    require(ROOT.is_dir() and not ROOT.is_symlink(), 'Publication root must be a real directory')
    index_bytes, summary_bytes = read_regular(ROOT / 'index.json'), read_regular(SUMMARY)
    require(digest(index_bytes) == args.index_sha256
            and digest(summary_bytes) == args.summary_sha256, 'Publication SHA fence differs')
    index, summary = json.loads(index_bytes), json.loads(summary_bytes)
    require(index['schema'] == 'FreeCAD-yzk-installation-evidence-index-v1'
            and summary['schema'] == 'FreeCAD-yzk-installation-v1', 'Unexpected publication schema')
    privacy_check(index, 'published index')
    privacy_check(summary, 'published summary')
    rows = index['files']
    require(len(rows) == len({row['file'] for row in rows}) == index['indexed_file_count']
            == summary['evidence']['indexed_files'], 'Index cardinality differs')
    paths = list(ROOT.rglob('*'))
    require(not any(path.is_symlink() for path in paths), 'Publication links are not allowed')
    actual = {str(path.relative_to(ROOT)) for path in paths if path.is_file()}
    require(actual == {row['file'] for row in rows} | {'index.json'}, 'Exact file coverage differs')
    decoded, compressed, python, parsed = {}, 0, 0, 0
    for row in rows:
        path = ROOT / relative_path(row['file'])
        stored = read_regular(path)
        require(digest(stored) == row['stored_sha256'] and len(stored) == row['stored_bytes'], 'Stored bytes differ')
        data = gzip.decompress(stored) if row['encoding'] == 'gzip' else stored
        require(row['encoding'] in ('gzip', 'identity'), 'Unexpected encoding')
        if row['encoding'] == 'gzip':
            require(gzip.compress(data, compresslevel=9, mtime=0) == stored, 'Nondeterministic gzip')
            compressed += 1
        require(digest(data) == row['uncompressed_sha256'] and len(data) == row['uncompressed_bytes'], 'Decoded bytes differ')
        original = Path(row['original_private_or_repository_path'])
        root = PRIVATE if original.is_relative_to(PRIVATE) else REPOSITORY
        require(original.is_relative_to(root), 'Original escaped approved roots')
        relative_path(str(original.relative_to(root)))
        raw = read_regular(original)
        require(data == raw and digest(raw) == row['original_sha256'] and len(raw) == row['original_bytes']
                and row['transformation'] == 'exact bytes' and not row['omitted_top_level_fields'],
                'Payload is not an exact approved copy')
        check_payload(data, str(original), row['kind'])
        python += original.suffix == '.py'
        parsed += original.suffix == '.json'
        require(str(original) not in decoded, 'Repeated original input')
        decoded[str(original)] = data
    stamp = index['approved_plan']
    require(digest(decoded[stamp['path']]) == stamp['sha256'] == summary['evidence']['approved_plan_sha256'],
            'Plan crosslink differs')
    plan = json.loads(decoded[stamp['path']])
    require(len(rows) == plan['explicit_inputs'] + 1 == len(plan['files']) + 1,
            'Explicit plan/index count differs')
    expected = {str((PRIVATE if row['scope'] == 'private' else REPOSITORY) / row['path']): row['sha256']
                for row in plan['files']}
    expected[stamp['path']] = stamp['sha256']
    require(set(expected) == set(decoded) and all(digest(decoded[path]) == wanted for path, wanted in expected.items()),
            'Plan exact input coverage/hash differs')
    require(summary['passed'] is True and summary['evidence']['index_sha256'] == args.index_sha256
            and summary['deployment_limits_and_engineering_holds']['FreeCAD_882_remains_open'] is True
            and summary['deployment_limits_and_engineering_holds']['engineering_or_BIM_accepted'] is False,
            'Summary/index/scope differs')
    print(json.dumps({'passed': True, 'writes': 0, 'exact_files': len(rows),
        'deterministic_gzip_files': compressed, 'Python_AST_checked': python, 'JSON_checked': parsed}))


if __name__ == '__main__':
    main()
