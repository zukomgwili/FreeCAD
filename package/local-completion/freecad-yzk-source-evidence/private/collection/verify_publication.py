"""Read-only exact-byte, decoded-byte, privacy and crosslink packet audit.

No collector, application, solver, tests, build or installation is invoked.
Private originals must still exist for this immediate publication audit; the
published packet remains self-describing through its original-byte hashes.
"""
import sys
sys.dont_write_bytecode = True

import argparse
import ast
import gzip
import json
from pathlib import Path

from evidence_packet import (
    PRIVATE, REPOSITORY, check_payload, descriptor, digest, json_bytes,
    load, privacy_check, read_regular, relative_path, require,
)


DESTINATION = REPOSITORY / 'package/local-completion/freecad-yzk-source-evidence'
SUMMARY = REPOSITORY / 'package/local-completion/freecad-yzk-validation.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index-sha256', required=True)
    parser.add_argument('--summary-sha256', required=True)
    args = parser.parse_args()
    require(not sys.flags.optimize, 'Use an unoptimized interpreter')
    require(descriptor(DESTINATION / 'index.json')['sha256'] == args.index_sha256
            and descriptor(SUMMARY)['sha256'] == args.summary_sha256, 'Publication SHA fence differs')
    index, summary = load(DESTINATION / 'index.json'), load(SUMMARY)
    require(index['schema'] == 'FreeCAD-yzk-source-evidence-index-v1'
            and summary['schema'] == 'FreeCAD-yzk-source-validation-v1'
            and summary['passed'] is True and index['source_only'] is True
            and summary['evidence']['index_sha256'] == args.index_sha256,
            'Index/summary schema or crosslink differs')
    privacy_check(index, 'index')
    privacy_check(summary, 'summary')
    rows = index['files']
    names = [row['file'] for row in rows]
    require(len(names) == len(set(names)) == index['indexed_file_count']
            == summary['evidence']['indexed_files'], 'Indexed total/uniqueness differs')
    actual = {str(path.relative_to(DESTINATION)) for path in DESTINATION.rglob('*') if path.is_file()}
    require(actual == set(names) | {'index.json'}, 'Exact publication file coverage differs')
    decoded, originals = {}, {}
    gzip_count = python_count = json_count = excerpt_count = 0
    for row in rows:
        target = DESTINATION / relative_path(row['file'])
        cursor = target
        while cursor != DESTINATION:
            require(not cursor.is_symlink(), 'Published symlink is forbidden')
            cursor = cursor.parent
        stored = read_regular(target)
        require(len(stored) == row['stored_bytes'] and digest(stored) == row['stored_sha256'],
                'Stored-byte hash/size mismatch: ' + row['file'])
        if row['encoding'] == 'gzip':
            data = gzip.decompress(stored)
            require(gzip.compress(data, compresslevel=9, mtime=0) == stored,
                    'Gzip is not deterministic exact-byte encoding')
            gzip_count += 1
        else:
            require(row['encoding'] == 'identity', 'Unexpected encoding')
            data = stored
        require(len(data) == row['uncompressed_bytes'] and digest(data) == row['uncompressed_sha256'],
                'Decoded-byte hash/size mismatch: ' + row['file'])
        original = Path(row['original_private_or_repository_path'])
        require(original.is_relative_to(PRIVATE) or original.is_relative_to(REPOSITORY),
                'Original escaped approved source roots')
        root = PRIVATE if original.is_relative_to(PRIVATE) else REPOSITORY
        relative_path(str(original.relative_to(root)))
        raw = read_regular(original)
        require(digest(raw) == row['original_sha256'] and len(raw) == row['original_bytes'],
                'Original-byte hash/size mismatch: ' + str(original))
        if row['omitted_top_level_fields']:
            omitted = row['omitted_top_level_fields']
            obj = json.loads(raw)
            require(set(omitted).issubset(obj), 'Excerpt omission absent from original')
            expected = {
                'schema': 'FreeCAD-yzk-source-curated-receipt-v1',
                'original_private_receipt': {'path': str(original), 'sha256': digest(raw), 'bytes': len(raw)},
                'omitted_top_level_fields': sorted(omitted),
                'facts': {key: value for key, value in obj.items() if key not in omitted},
                'transformation': 'Explicit inventory/large metadata omissions; retained facts are copied, not a new independent audit.',
            }
            require(data == json_bytes(expected)
                    and row['transformation'].startswith('DERIVED curated JSON excerpt'),
                    'Curated excerpt differs from its explicit original')
            excerpt_count += 1
        else:
            require(data == raw and row['transformation'] == 'exact bytes', 'Exact copy is not exact')
        check_payload(data, str(original), row['kind'])
        if original.suffix == '.py':
            ast.parse(data, filename=str(original))
            python_count += 1
        if original.suffix == '.json':
            json.loads(data)
            json_count += 1
        require(str(original) not in originals, 'Duplicate original source entry')
        originals[str(original)] = row
        decoded[str(original)] = data

    plan_stamp = index['explicit_plan']
    require(plan_stamp['path'] in originals
            and originals[plan_stamp['path']]['original_sha256'] == plan_stamp['sha256']
            == summary['evidence']['approved_plan_sha256'], 'Approved plan crosslink differs')
    plan = json.loads(decoded[plan_stamp['path']])
    require(len(plan['files']) == index['input_count']
            and len(rows) == len(plan['files']) + 1, 'Plan/index exact membership count differs')
    planned = set()
    for entry in plan['files']:
        root = PRIVATE if entry['scope'] == 'private' else REPOSITORY
        path = str(root / entry['path'])
        planned.add(path)
        require(path in originals and originals[path]['original_sha256'] == entry['sha256']
                and originals[path]['classification'] == entry['classification']
                and originals[path]['kind'] == entry['kind'], 'Approved entry/index mapping differs')
    require(set(originals) == planned | {plan_stamp['path']}, 'Unapproved published source entry')
    require(summary['implementation_commit'] == plan['config']['source_commit']
            and summary['revision'] == plan['config']['revision'], 'Final implementation identity differs')
    for role, result in summary['qualification']['applications'].items():
        spec = plan['config']['applications'][role]
        require(result['registered_tests'] + result['identity_tests'] == spec['expected_count']
                and result['skipped'] == 0 and result['module'] == spec['module'], 'App gate summary differs')
    for role in ('primary_132', 'portable_132'):
        require(summary['qualification'][role]['physical_checks'] == 3566
                and summary['qualification'][role]['budget'] == 2113, 'Physical proof summary differs')
    for role in ('primary_cold', 'portable_cold'):
        require(summary['qualification'][role]['no_solve_save_or_repair'] is True
                and summary['qualification'][role]['status'].startswith('Stale'), 'Cold scope summary differs')
    scope = summary['scope']
    require(scope['source_only'] is True and scope['installation_performed'] is False
            and scope['engineering_or_BIM_accepted'] is False and scope['Oomakhi_accessed_or_solved'] is False
            and scope['entire_dependency_environment_filesystem_unchanged_claimed'] is False
            and scope['force_original_origin_moment_limit'] == .01 and scope['scalar_response_limit'] == .05
            and scope['R49_11_123267892_percent_remains_FAIL_against_5_percent'] is True
            and scope['R51_5_240441298_percent_remains_FAIL_against_5_percent'] is True,
            'Source-only/unchanged acceptance/engineering holds differ')
    print(json_bytes({'passed': True, 'read_only': True, 'writes': 0,
        'indexed_exact_files': len(rows), 'deterministic_gzip_files': gzip_count,
        'explicit_derived_excerpts': excerpt_count, 'python_AST_parsed': python_count,
        'JSON_parsed': json_count, 'index_sha256': args.index_sha256,
        'summary_sha256': args.summary_sha256}).decode(), end='')


if __name__ == '__main__':
    main()
