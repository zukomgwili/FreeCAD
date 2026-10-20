"""Independent, file-only audit of an already published yzk source packet.

No publisher/verifier imports, subprocesses, app/native/test/build operations,
source changes, or publication writes. The only write is a new private receipt.
"""

import argparse
import ast
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import sys


TASK = Path('/private/tmp/freecad-yzk-Sd0mDG')
REPO = Path('/Users/zukomgwili/src/FreeCAD')
HERE = TASK / 'publication-independent-r01'
PLAN = TASK / 'collection/approved-file-plan-r01.json'
PLAN_SHA = 'd18b130f205c3ff38b45289db653b92424fbc9e2cff9b70719e5543cfe96c132'
DEST = REPO / 'package/local-completion/freecad-yzk-source-evidence'
SUMMARY = REPO / 'package/local-completion/freecad-yzk-validation.json'
COMMIT = 'cf23c61504c9a25699899a87b68571b86de37438'
REVISION = '49261 +223 (Git)'
CANDIDATE = '6c02452a896727af6cb4578fd3fb6bbfbdd48e3fb887c1c04fa2d8b171976c66'
COUNTS = {'supports': 1, 'bodies': 264, 'ports': 264, 'angles': 792, 'springs': 792}
BAD_PARTS = {
    '.git', '.pixi', 'CalculiX', 'profiles', '__pycache__', 'CMakeFiles',
    'module-cache', 'freecad_user_home', 'freecad_user_data', 'freecad_user_temp',
    'xdg_config_home', 'xdg_data_home', 'xdg_cache_home',
}
BAD_NAMES = {
    'user.cfg', 'system.cfg', '.env', 'environment.log', 'baseline-inventory.json',
    'stage-inventory.json', 'profile-inventories.json',
}
BAD_SUFFIXES = {'.cfg', '.pyc', '.pyo', '.so', '.dylib', '.exe', '.o', '.a'}
BAD_JSON_KEYS = {
    'app_before', 'app_after', 'critical_before', 'critical_after',
    'private_custody_before', 'private_baseline', 'inventory', 'app_inventory',
    'application_inventory', 'profile_inventory', 'profile_inventories', 'profiles',
    'password', 'api_key', 'apikey', 'secret', 'authorization', 'cookie',
    'access_token', 'refresh_token', 'environment', 'environ',
}
MAGICS = {
    b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xce\xfa\xed\xfe',
    b'\xfe\xed\xfa\xce', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca',
    b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca', b'\x7fELF',
}
CODE_PINS = {
    'collect_source.py': '51b7069c96821e06ac6bd1b50330bfde32e905abeb7ac1ce6e4de8c61005ffd4',
    'evidence_packet.py': '7042cf407fe4f707af8f1f992f49643afa35b2610183a239f9916859c8eebd58',
    'prepare_plan.py': 'd72b1ea0aa015778d461f567ee523542bb072e4ebebcc89e7af7143e19104129',
    'verify_publication.py': '67012a7b367755e3de0331be7d1471a3aeef13e53474a3ba6924f6e851071794',
}


def need(value, message):
    if not value:
        raise RuntimeError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()


def regular(path):
    path = Path(path)
    need(path.is_file() and not path.is_symlink(), 'Not a regular nonlink: ' + str(path))
    return path.read_bytes()


def safe_relative(name):
    path = Path(name)
    need(path.parts and not path.is_absolute() and '..' not in path.parts, 'Unsafe path ' + name)
    need(not BAD_PARTS.intersection(path.parts) and path.name not in BAD_NAMES,
         'Private/runtime namespace: ' + name)
    need(not (path.name.startswith('private-') and path.suffix == '.json')
         and path.suffix.lower() not in BAD_SUFFIXES, 'Private/runtime filename: ' + name)
    return path


def no_links(path, base):
    need(path.is_relative_to(base), 'Root escape: ' + str(path))
    for item in [path, *path.parents]:
        need(not item.is_symlink(), 'Symlink path component: ' + str(item))
        if item == base:
            return
    raise RuntimeError('Root not reached')


def privacy(value, location):
    if isinstance(value, dict):
        need(not BAD_JSON_KEYS.intersection(str(key).lower() for key in value),
             'Secret/raw inventory key: ' + location)
        need(not (isinstance(value.get('.'), dict) and value['.'].get('kind') == 'dir'
                  and 'mode' in value['.']), 'Raw filesystem inventory: ' + location)
        for item in value.values():
            privacy(item, location)
    elif isinstance(value, list):
        for item in value:
            privacy(item, location)


def process(row):
    need(row['passed'] is True and row['returncode'] == 0 and row['timed_out'] is False
         and row['child_reaped'] is True and row['process_group_gone'] is True,
         'Failed/unreaped process receipt')


def audit(index_sha, summary_sha):
    need(not sys.flags.optimize, 'Unoptimized interpreter required')
    plan_raw = regular(PLAN)
    index_raw = regular(DEST / 'index.json')
    summary_raw = regular(SUMMARY)
    need(sha(plan_raw) == PLAN_SHA and sha(index_raw) == index_sha
         and sha(summary_raw) == summary_sha, 'Top-level expected hash mismatch')
    plan, index, summary = map(json.loads, (plan_raw, index_raw, summary_raw))
    need(plan['schema'] == 'FreeCAD-yzk-source-approved-file-plan-v1'
         and plan['planned_input_count'] == len(plan['files']) == 907,
         'Approved plan schema/count differs')
    need(index['schema'] == 'FreeCAD-yzk-source-evidence-index-v1'
         and summary['schema'] == 'FreeCAD-yzk-source-validation-v1'
         and summary['passed'] is True, 'Publication schema/status differs')
    need(plan['repository'] == str(REPO) and plan['task_root'] == str(TASK), 'Plan roots differ')
    need(summary['implementation_commit'] == plan['config']['source_commit'] == COMMIT
         and summary['revision'] == plan['config']['revision'] == REVISION, 'Source identity differs')
    need(index['source_only'] is True and index['input_count'] == 907
         and index['indexed_file_count'] == summary['evidence']['indexed_files'] == 908
         and summary['evidence']['index_sha256'] == index_sha
         and summary['evidence']['approved_plan_sha256'] == PLAN_SHA
         and summary['evidence']['directory'] == str(DEST.relative_to(REPO)), 'Index crosslink differs')
    privacy(index, 'index')
    privacy(summary, 'summary')
    expected = {}
    destinations = set()
    for entry in plan['files']:
        need(entry['scope'] in ('private', 'repository'), 'Unknown plan scope')
        base = TASK if entry['scope'] == 'private' else REPO
        original = base / safe_relative(entry['path'])
        no_links(original, base)
        need(str(original) not in expected, 'Duplicate approved input')
        need(entry['destination'] not in destinations, 'Duplicate approved destination')
        safe_relative(entry['destination'])
        expected[str(original)] = entry
        destinations.add(entry['destination'])
    expected[str(PLAN)] = {
        'scope': 'private', 'path': str(PLAN.relative_to(TASK)),
        'destination': 'approved-plan.json', 'sha256': PLAN_SHA, 'kind': 'receipt',
        'classification': 'Exact root-reviewed explicit publication plan; producer did not execute product gates',
    }
    rows = index['files']
    names = [row['file'] for row in rows]
    need(len(names) == len(set(names)) == 908, 'Index duplicates/count differs')
    need(rows == sorted(rows, key=lambda row: row['file']), 'Index order differs')
    actual = set()
    for path in DEST.rglob('*'):
        need(not path.is_symlink(), 'Published tree symlink')
        if path.is_file():
            actual.add(str(path.relative_to(DEST)))
        else:
            need(path.is_dir(), 'Special filesystem entry')
    need(actual == set(names) | {'index.json'}, 'Extra/missing publication files')
    objects, records, texts = {}, {}, {}
    totals = Counter()
    coverage = []
    for row in rows:
        name = row['file']
        target = DEST / safe_relative(name)
        no_links(target, DEST)
        stored = regular(target)
        need(sha(stored) == row['stored_sha256'] and len(stored) == row['stored_bytes'],
             'Stored-byte mismatch: ' + name)
        if row['encoding'] == 'gzip':
            data = gzip.decompress(stored)
            need(stored == gzip.compress(data, compresslevel=9, mtime=0), 'Noncanonical gzip: ' + name)
            totals['gzip_files'] += 1
        else:
            need(row['encoding'] == 'identity', 'Unknown encoding')
            data = stored
        need(sha(data) == row['uncompressed_sha256'] and len(data) == row['uncompressed_bytes'],
             'Decoded-byte mismatch: ' + name)
        original = row['original_private_or_repository_path']
        need(original in expected and original not in records, 'Unapproved/duplicate original')
        entry = expected[original]
        raw = regular(original)
        need(sha(raw) == row['original_sha256'] == entry['sha256']
             and len(raw) == row['original_bytes'], 'Original-byte mismatch: ' + original)
        omissions = entry.get('omit_top_level_fields', [])
        need(row['omitted_top_level_fields'] == sorted(omissions), 'Omission policy changed')
        # The frozen907-file actual plan uses no excerpts. Enforce exactness.
        need(not omissions and row['transformation'] == 'exact bytes' and data == raw,
             'Actual publication must contain complete original bytes: ' + name)
        need(row['kind'] == entry['kind'] and row['classification'] == entry['classification'],
             'Approved classification/kind changed')
        expected_name = entry['destination'] + ('.gz' if len(data) >= 65536 else '')
        need(name == expected_name and (row['encoding'] == 'gzip') == (len(data) >= 65536),
             'Approved destination/encoding policy changed')
        need(data[:4] not in MAGICS and not data.startswith(b'MZ'), 'Runtime executable bytes')
        original_path = Path(original)
        if original_path.suffix == '.FCStd':
            need(entry['kind'] == 'generic-fixture' and data.startswith(b'PK\x03\x04'),
                 'Non-generic FCStd payload')
            totals['generic_FCStd_files'] += 1
        else:
            text = data.decode('utf-8')
            need('\0' not in text, 'Unexpected binary non-FCStd file')
            need(not re.search(r'(?im)^(?:OPENAI_API_KEY|AWS_SECRET_ACCESS_KEY|GITHUB_TOKEN|GH_TOKEN|'
                               r'ACCESS_TOKEN|REFRESH_TOKEN|PASSWORD)\s*=\s*\S+', text),
                 'Environment secret assignment')
            if original_path.name == 'run.log':
                texts[original] = text
            if original_path.suffix == '.py':
                ast.parse(text, filename=original)
                totals['python_AST_parsed'] += 1
            if original_path.suffix == '.json':
                objects[original] = json.loads(text)
                privacy(objects[original], original)
                totals['JSON_parsed'] += 1
        if entry['kind'] == 'generic-fixture':
            need(entry.get('fixture_scope') == 'generic software QA; not a retained engineering model',
                 'Missing explicit software fixture scope')
        records[original] = row
        totals['stored_bytes'] += len(stored)
        totals['decoded_bytes'] += len(data)
        totals['original_bytes'] += len(raw)
        totals['files'] += 1
        coverage.append([name, sha(stored), sha(data), sha(raw), len(stored), len(data), len(raw)])
    need(set(records) == set(expected), 'Incomplete full-original coverage')
    need(index['explicit_plan'] == {'path': str(PLAN), 'sha256': PLAN_SHA, 'bytes': len(plan_raw)},
         'Exact plan descriptor differs')
    config = plan['config']
    config_stamp = plan['config_descriptor']
    need(records[config_stamp['path']]['original_sha256'] == config_stamp['sha256']
         and records[config_stamp['path']]['original_bytes'] == config_stamp['bytes']
         and objects[config_stamp['path']] == config, 'Embedded approved config differs')
    for name, wanted in CODE_PINS.items():
        need(records[str(TASK / 'collection' / name)]['original_sha256'] == wanted,
             'Reviewed publication helper changed')

    def obj(path):
        return objects[str(path)]

    # Every summary descriptor must resolve to the actual archived original.
    descriptor_count = 0

    def crosslinks(value):
        nonlocal descriptor_count
        if isinstance(value, dict):
            if {'path', 'sha256', 'bytes'}.issubset(value):
                need(value['path'] in records, 'Summary receipt is not archived')
                record = records[value['path']]
                need(value['sha256'] == record['original_sha256']
                     and value['bytes'] == record['original_bytes'], 'Summary descriptor hash/size differs')
                descriptor_count += 1
            for item in value.values():
                crosslinks(item)
        elif isinstance(value, list):
            for item in value:
                crosslinks(item)

    crosslinks(summary)
    expected_app_counts = {'fem': 406, 'gui': 9, 'native_moving': 6, 'portable': 2,
                           'portable_cold': 2, 'tracer_cold': 2, 'benchmark': 2}
    need(set(config['applications']) == set(expected_app_counts)
         == set(summary['qualification']['applications']), 'Final app role membership changed')
    app_counts = {}
    for role, count in expected_app_counts.items():
        spec = config['applications'][role]
        directory = TASK / spec['directory']
        run, manifest, identity = [obj(directory / filename)
                                   for filename in ('execution.json', 'manifest.json', 'identity.json')]
        log = texts[str(directory / 'run.log')]
        process(run)
        need(spec['expected_count'] == count and manifest['expected_count'] == count
             and manifest['discovery_only'] is False and manifest['unit_only'] is False,
             'Final run count/discovery/native-attestation differs')
        need(run['manifest_sha256'] == records[str(directory / 'manifest.json')]['original_sha256']
             and run['identity_sha256'] == records[str(directory / 'identity.json')]['original_sha256']
             and run['log_sha256'] == records[str(directory / 'run.log')]['original_sha256'],
             'App receipt/manifest/identity/log crosslink differs')
        need(identity['passed'] is True and identity['runtime'][3] == REVISION
             and identity['runtime'][7] == COMMIT and run['runtime'] == identity['runtime'],
             'Final runtime rebound or mismatched')
        ids = identity['selected_suite']['ids']
        need(len(ids) == len(set(ids)) == count - 1 and set(ids) == set(manifest['expected_ids'])
             and set(spec['critical_ids']).issubset(ids), 'Selected actual methods differ')
        need(identity['candidate'] == manifest['candidate']
             and identity['candidate']['sha256'] == CANDIDATE
             and identity['candidate']['override'] is False
             and bool(identity['native_build_receipt']), 'Final candidate/attestation differs')
        need(run['unittest_counts'] == re.findall(r'^Ran (\d+) tests? in ([0-9.]+)s$', log, re.M)
             or run['unittest_counts'] == [list(row) for row in re.findall(
                 r'^Ran (\d+) tests? in ([0-9.]+)s$', log, re.M)], 'Unittest parsed counts differ')
        need(len(re.findall(r'^Ran ' + str(count) + r' tests? in [0-9.]+s$', log, re.M)) == 1
             and len(re.findall(r'^OK$', log, re.M)) == 1
             and not re.search(r'^(?:FAILED|FAIL:|ERROR:|UNEXPECTED SUCCESS)', log, re.M)
             and run['skipped_lines'] == [] and run['missing_repeated_or_skipped_ids'] == [],
             'Actual app log failed/skipped/repeated')
        for test_id in ids:
            pattern = '^' + re.escape(test_id.rsplit('.', 1)[-1]) + r' \(' + re.escape(test_id) + r'\)([^\n]*)$'
            matches = re.findall(pattern, log, re.M)
            need(len(matches) == 1 and 'skipped' not in matches[0], 'Missing/repeated/skipped method')
        need(run['inputs_unchanged'] is True and run['app_and_profiles_unchanged'] is True
             and run['selected_critical_dependencies_unchanged'] is True
             and run['installation_performed'] is False, 'Final app custody failed')
        result = summary['qualification']['applications'][role]
        need(result['registered_tests'] == count - 1 and result['identity_tests'] == 1
             and result['skipped'] == 0 and result['runtime'] == identity['runtime'], 'Summary app count differs')
        app_counts[role] = {'registered': count - 1, 'identity': 1, 'skipped': 0}

    physical_counts = {}
    for role in ('primary_132', 'portable_132'):
        result = summary['qualification'][role]
        witness = obj(result['receipt']['path'])
        checks = witness['checks']
        need(witness['passed'] is True and len(checks) == len({c['name'] for c in checks}) == 3566,
             'Physical named check coverage differs')
        need(Counter(c['limit'] for c in checks) == Counter({.01: 3302, .05: 264}),
             'Original acceptance limits changed')
        need(all(c['passed'] is True and math.isfinite(c['relative_error'])
                 and 0 <= c['relative_error'] <= c['limit'] for c in checks), 'Physical acceptance failed')
        need(result['budget'] == 2113 and result['counts'] == COUNTS
             and result['max_relative_error'] == max(c['relative_error'] for c in checks)
             and result['separate_process_cold_claimed_by_this_physical_receipt'] is False,
             'Physical summary or cold claim differs')
        physical_counts[role] = len(checks)
    primary = summary['qualification']['primary_132']
    need(primary['generation']['runtime'][3] == '49261 +222 (Git)'
         and primary['generation']['runtime'][7] == 'a878b8ae8e0536a70b016b80b4b92ff7c8f75dff'
         and primary['generation']['rebound_to_final_committed_source'] is False,
         'Historical primary runtime falsely rebound')
    for role in ('primary_cold', 'portable_cold'):
        result = summary['qualification'][role]
        cold = obj(result['receipt']['path'])
        need(cold['passed'] is True and cold['status'].startswith('Stale')
             and cold['no_native_solve'] is True and cold['no_save'] is True
             and cold['no_history_or_provenance_repair'] is True
             and result['manifest_sha256'] == cold['manifest_sha256']
             == summary['qualification'][role.replace('_cold', '_132')]['cold_manifest_sha256'],
             'Separate cold literal scope/crosslink differs')
    ctest_dir = TASK / config['ctest_directory']
    ctest = obj(ctest_dir / 'execution.json')
    process(ctest)
    lines = re.findall(r'^\s*(\d+)/(\d+)\s+Test\s+#(\d+):([^\r\n]*)$',
                       texts[str(ctest_dir / 'run.log')], re.M)
    need(len(lines) == 2274 and {int(r[0]) for r in lines} == set(range(1, 2275))
         and {int(r[2]) for r in lines} == set(range(1, 2275))
         and {int(r[1]) for r in lines} == {2274}, 'CTest incomplete catalogue')
    ctest_counts = Counter('disabled' if '***Not Run (Disabled)' in r[3] else
                           'skipped' if '***Skipped' in r[3] else
                           'passed' if re.search(r'\bPassed\s+[\d.]+\s+sec\s*$', r[3]) else
                           'failed' for r in lines)
    need(ctest_counts == Counter({'passed': 2264, 'skipped': 2, 'disabled': 8}), 'CTest actual counts differ')
    for key, actual_key in [('executed_passing', 'passed'), ('skipped', 'skipped'), ('disabled', 'disabled')]:
        need(summary['qualification']['ctest']['actual_complete_catalogue'][key] == ctest_counts[actual_key],
             'CTest summary masks actual status')
    need(summary['qualification']['ctest']['actual_complete_catalogue']['failed'] == 0,
         'CTest summary failure count')
    for version, expected_counts in [('V1', (48, 6, 288)), ('V2', (8, 2, 144))]:
        result = summary['qualification']['legacy'][version]
        need(tuple(result[k] for k in ('positive_cases', 'expected_refusals', 'physical_norm_checks'))
             == expected_counts and result['FreeCAD_writer_or_capacity_graph_coverage'] is False,
             'Legacy qualification overclaimed')
        process(obj(result['receipt']['path']))
    scope = summary['scope']
    for key, expected_value in {
        'source_only': True, 'installation_performed': False,
        'engineering_or_BIM_accepted': False, 'Oomakhi_accessed_or_solved': False,
        'entire_dependency_environment_filesystem_unchanged_claimed': False,
        'original_side_loaded_fixture_inputs_rewritten': False,
        'R49_11_123267892_percent_remains_FAIL_against_5_percent': True,
        'R51_5_240441298_percent_remains_FAIL_against_5_percent': True,
        'force_original_origin_moment_limit': .01, 'scalar_response_limit': .05,
    }.items():
        need(scope[key] == expected_value, 'Scope/engineering hold changed: ' + key)
    need(summary['native']['candidate_sha256'] == CANDIDATE
         and summary['native']['contract_observed_not_compiled'] is True,
         'Native source/contract qualification overclaimed')
    # End fences cover all908 originals and all908 stored files, not a sample.
    for original, row in records.items():
        need(sha(regular(original)) == row['original_sha256']
             and sha(regular(DEST / row['file'])) == row['stored_sha256'], 'End custody changed')
    need(regular(PLAN) == plan_raw and regular(DEST / 'index.json') == index_raw
         and regular(SUMMARY) == summary_raw, 'Top-level end custody changed')
    return {
        'passed': True, 'read_only_publication_audit': True,
        'native_app_solver_mesher_build_test_install_collector_or_verifier_executed': False,
        'publication_modified': False, 'findings': [],
        'approved_plan_sha256': PLAN_SHA, 'index_sha256': index_sha, 'summary_sha256': summary_sha,
        'implementation_commit': COMMIT, 'revision': REVISION, 'totals': dict(totals),
        'full_file_coverage_digest': sha(encoded(coverage)),
        'coverage_digest_columns': ['file', 'stored_sha256', 'decoded_sha256', 'original_sha256',
                                    'stored_bytes', 'decoded_bytes', 'original_bytes'],
        'summary_archived_receipt_crosslinks': descriptor_count,
        'final_app_counts': app_counts, 'physical_check_counts': physical_counts,
        'actual_ctest_status_counts': dict(ctest_counts),
        'privacy': {'full_json_recursive_key_scan': True, 'full_text_secret_assignment_scan': True,
                    'raw_app_profile_inventories_excluded': True, 'runtime_vendor_payloads_excluded': True,
                    'generic_FCStd_allowed_only_by_explicit_pinned_plan': True,
                    'absolute_paths_and_hash_only_reference_metadata_retained': True},
        'history_and_engineering_holds': 'Primary+222/a878 is explicitly historical; final app gates are+223/cf23. Software/source-only; no installation, Oomakhi, BIM or engineering acceptance; R49/R51 remain failing.',
        'independence_disclosure': {
            'this_auditor_authored_publisher_or_verifier': False,
            'prior_native_C_hooks_and_cache_lifetime_test_authorship': True,
            'prior_QA_helper_and_product_review': True,
            'claim': 'Fresh full file/hash/JSON/gzip arithmetic audit of actual publication, not independent physics implementation authorship or organizational independence.',
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index-sha256', required=True)
    parser.add_argument('--summary-sha256', required=True)
    args = parser.parse_args()
    result = audit(args.index_sha256, args.summary_sha256)
    result['auditor_code_sha256'] = sha(regular(__file__))
    target = HERE / 'audit-receipt.json'
    with target.open('xb') as stream:
        stream.write(encoded(result))
    print(json.dumps({'passed': True, 'receipt': str(target), 'sha256': sha(regular(target)),
                      'code_sha256': result['auditor_code_sha256'], 'files': result['totals']['files']}))


if __name__ == '__main__':
    main()
