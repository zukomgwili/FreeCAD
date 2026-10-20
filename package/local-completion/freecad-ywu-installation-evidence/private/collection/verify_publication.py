"""Read-only installation packet verification; never rerun product QA.

Root executes this only after publication. It verifies stored/original/decoded
bytes, excerpt honesty, complete coverage and privacy. Native workflow semantic
checks remain the collector/final independent-audit prerequisites; this checker
does not relabel a receipt excerpt as an independent software/engineering test.
"""
import sys
sys.dont_write_bytecode = True

import argparse
import ast
import gzip
import json
from pathlib import Path

from evidence_packet import (digest, load, read_regular, relative_path,
                             require, privacy_check, check_payload)

REPO = Path('/Users/zukomgwili/src/FreeCAD')
ROOT = REPO / 'package/local-completion/freecad-ywu-installation-evidence'
SUMMARY = REPO / 'package/local-completion/freecad-ywu-installation.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-summary-sha256')
    parser.add_argument('--expected-index-sha256')
    args = parser.parse_args()
    summary_data = read_regular(SUMMARY)
    summary = json.loads(summary_data)
    index_data = read_regular(ROOT / 'index.json')
    index = json.loads(index_data)
    require(summary['schema'] == 'FreeCAD-ywu-host-local-installation-v1' and summary['passed'],
            'Not a passed YWU installation packet')
    require(summary['installation_bead'] == 'FreeCAD-3je' and summary['source_bead'] == 'FreeCAD-ywu',
            'Unexpected installation/source bead')
    require(digest(index_data) == summary['evidence']['index_sha256'], 'Summary/index SHA differs')
    if args.expected_summary_sha256:
        require(digest(summary_data) == args.expected_summary_sha256, 'Summary differs from supplied fence')
    if args.expected_index_sha256:
        require(digest(index_data) == args.expected_index_sha256, 'Index differs from supplied fence')
    rows = index['files']
    require(len(rows) == len({row['file'] for row in rows}) == summary['evidence']['indexed_file_count'],
            'Duplicate/incomplete index records')
    actual = {str(p.relative_to(ROOT)) for p in ROOT.rglob('*') if p.is_file()}
    require(actual == {'index.json', *(row['file'] for row in rows)}, 'Exact file coverage differs')
    counts = {'exact': 0, 'excerpts': 0, 'gzip': 0, 'python_AST': 0, 'JSON': 0}
    for row in rows:
        relative = relative_path(row['file'])
        path = ROOT / relative
        require(path.resolve().is_relative_to(ROOT.resolve()), 'Published path escapes packet')
        raw = read_regular(path)
        require(digest(raw) == row['stored_sha256'] and len(raw) == row['stored_bytes'], 'Stored bytes differ')
        require(row['encoding'] in ('identity', 'gzip'), 'Unsupported evidence encoding')
        decoded = gzip.decompress(raw) if row['encoding'] == 'gzip' else raw
        require(digest(decoded) == row['uncompressed_sha256'] and len(decoded) == row['uncompressed_bytes'],
                'Decoded bytes differ')
        original = read_regular(row['original_private_or_repository_path'])
        require(digest(original) == row['original_sha256'] and len(original) == row['original_bytes'],
                'Original byte/hash fence differs')
        if row['transformation'] == 'exact bytes':
            require(decoded == original and not row['omitted_top_level_fields'], 'Exact-copy claim differs')
            counts['exact'] += 1
        else:
            excerpt, source = json.loads(decoded), json.loads(original)
            omitted = row['omitted_top_level_fields']
            require(excerpt['omitted_top_level_fields'] == omitted and
                    excerpt['facts'] == {k: v for k, v in source.items() if k not in omitted},
                    'Derived excerpt changed retained facts')
            require(excerpt['original_private_receipt'] == {
                    'path': row['original_private_or_repository_path'],
                    'sha256': row['original_sha256'], 'bytes': row['original_bytes']}, 'Excerpt original fence differs')
            require('not a new independent audit' in excerpt['transformation'], 'Excerpt scope not explicit')
            counts['excerpts'] += 1
        original_name = row['original_private_or_repository_path']
        check_payload(decoded, original_name, row['kind'])
        if Path(original_name).suffix == '.py':
            ast.parse(decoded)
            counts['python_AST'] += 1
        if Path(original_name).suffix == '.json':
            privacy_check(json.loads(decoded), str(path))
            counts['JSON'] += 1
        counts['gzip'] += row['encoding'] == 'gzip'
    require(summary['engineering_holds']['engineering_or_BIM_design_accepted'] is False and
            summary['engineering_holds']['Oomakhi_opened_altered_or_solved_for_this_installation'] is False,
            'Engineering/Oomakhi scope differs')
    print(json.dumps({'passed': True, 'indexed_files': len(rows), 'counts': counts,
        'summary_sha256': digest(summary_data), 'index_sha256': digest(index_data)}, indent=2))


if __name__ == '__main__':
    main()
