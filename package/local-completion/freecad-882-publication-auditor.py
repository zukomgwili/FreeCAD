"""Independent file-only audit of the already-published FreeCAD-882 packet.

Does not import or execute a producer, QA helper, FreeCAD, solver, test or Git.
Only the new task-private JSON report is written, exclusively.
"""
import ast
from collections import Counter
import gzip
import hashlib
import json
import marshal
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
TASK = Path('/private/tmp/freecad-882-VGfnpo')
PACKET = Path('/Users/zukomgwili/src/FreeCAD/package/local-completion/freecad-882-source-evidence')
SUMMARY = PACKET.parent / 'freecad-882-validation.json'
PLAN = TASK / 'planning/collection/approved-plan-r01.json'
REPORT = TASK / 'planning/publication-audit-r01.json'
CHILD_REVIEW = TASK / 'planning/actual-publication-scope-privacy-review-r01.json'
CHILD_SHA = 'dfa0ebc521ccb0c37a6495b66b907b25d5b2d9a9003d65ba7a362e75c81518f3'
PINS = {
    'index': 'e7f19fd63d4c391714a4e5413bd208026efdc8331bc440f236750a7d644c85b3',
    'summary': '6817ee664620cfb861e116f0de655d6134f17b6475adb49422f06576c7425785',
    'plan': 'fd1cb65cfa1e69193eaf19b750171201762fd2171c521be1ddf972edb1c3d60a',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def need(value, label):
    if not value:
        raise ValueError(label)


def canonical(value):
    return sha(json.dumps(value, sort_keys=True, allow_nan=False, separators=(',', ':')).encode())


def privacy(value):
    if isinstance(value, dict):
        keys = {str(key).lower() for key in value}
        excluded = {'environment', 'environ', 'profiles', 'profile_inventories',
                    'profile_inventory', 'app_inventory', 'application_inventory',
                    'inventory', 'critical_before', 'critical_after', 'password',
                    'api_key', 'apikey', 'secret', 'access_token', 'refresh_token',
                    'authorization', 'cookie'}
        need(not excluded.intersection(keys), 'Private inventory/environment/secret JSON keys')
        need(not {'dev', 'inode', 'mtime_ns', 'ctime_ns'}.issubset(keys), 'Raw stat inventory')
        need(not (isinstance(value.get('.'), dict) and value['.'].get('kind') == 'dir'),
             'Raw tree inventory')
        for child in value.values():
            privacy(child)
    elif isinstance(value, list):
        for child in value:
            privacy(child)


def main():
    need(not REPORT.exists(), 'Audit report must be new')
    pinned_bytes = {'index': (PACKET / 'index.json').read_bytes(),
                    'summary': SUMMARY.read_bytes(), 'plan': PLAN.read_bytes()}
    for name, value in pinned_bytes.items():
        need(sha(value) == PINS[name], 'Announced ' + name + ' hash')
    index, summary, plan = (json.loads(pinned_bytes[name]) for name in ('index', 'summary', 'plan'))
    need(index['schema'] == 'FreeCAD-882-source-evidence-index-v1', 'Index schema')
    need(plan['root_approved'] is True and len(plan['files']) == 94, 'Approved explicit 94-input plan')
    rows = index['files']
    need(len(rows) == index['indexed_files'] == 95, '95 indexed bodies')
    need(len({row['file'] for row in rows}) == 95, 'Unique indexed destinations')
    planned = {row['destination']: row for row in plan['files']}
    need(len(planned) == 94 and len({row['path'] for row in plan['files']}) == 94,
         'Unique plan inputs and destinations')
    actual_paths = list(PACKET.rglob('*'))
    need(not any(path.is_symlink() for path in actual_paths), 'No packet links')
    actual_files = {str(path.relative_to(PACKET)) for path in actual_paths if path.is_file()}
    need(actual_files == {row['file'] for row in rows} | {'index.json'}, 'Exact physical coverage')
    decoded, parsed, origins, stored_hashes, original_hashes, counters = {}, {}, {}, {}, {}, Counter()
    forbidden_parts = {'.git', '.beads', '.pixi', '__pycache__', 'profiles', 'module-cache',
                       'freecad_user_home', 'freecad_user_data', 'freecad_user_temp',
                       'xdg_config_home', 'xdg_data_home', 'xdg_cache_home'}
    forbidden_suffixes = {'.cfg', '.pyc', '.pyo', '.so', '.dylib', '.o', '.a', '.exe', '.frd', '.dat'}
    for row in rows:
        relative = Path(row['file'])
        need(not relative.is_absolute() and '..' not in relative.parts, 'No traversal')
        logical = str(relative)[:-3] if row['encoding'] == 'gzip' else str(relative)
        need(not forbidden_parts.intersection(Path(logical).parts)
             and Path(logical).suffix.lower() not in forbidden_suffixes
             and not Path(logical).name.startswith('private-'), 'No excluded payload path')
        stored = (PACKET / relative).read_bytes()
        need(len(stored) == row['stored_bytes'] and sha(stored) == row['stored_sha256'], 'Stored bytes: ' + logical)
        need(row['encoding'] in {'identity', 'gzip'} and row['decoded_bytes'] <= 32 * 1024 * 1024,
             'Known bounded encoding')
        payload = gzip.decompress(stored) if row['encoding'] == 'gzip' else stored
        need(len(payload) == row['decoded_bytes'] == row['original_bytes']
             and sha(payload) == row['decoded_sha256'] == row['original_sha256'], 'Decoded/original descriptor: ' + logical)
        original = Path(row['original_path'])
        need(original.is_file() and not original.is_symlink(), 'Regular original: ' + logical)
        source = original.read_bytes()
        need(source == payload and len(source) == row['original_bytes'], 'Actual original equality: ' + logical)
        original_hashes[str(original)] = sha(source)
        need(row['transformation'] == 'exact bytes', 'No excerpts or repairs')
        if logical == 'approved-plan.json':
            need(payload == pinned_bytes['plan'] and original == PLAN, 'Exact approved plan body')
        else:
            selected = planned[logical]
            need((row['original_path'], row['original_sha256'], row['original_bytes'], row['kind'], row['classification'])
                 == (selected['path'], selected['sha256'], selected['bytes'], selected['kind'], selected['classification']),
                 'Exact approved membership: ' + logical)
        need(stored == (gzip.compress(payload, compresslevel=9, mtime=0)
                        if row['encoding'] == 'gzip' else payload), 'Deterministic exact encoding')
        need(row['encoding'] == ('gzip' if len(payload) >= 65536 else 'identity'), 'Planned threshold encoding')
        need(payload[:4] not in {b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xce\xfa\xed\xfe',
                                b'\xfe\xed\xfa\xce', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca',
                                b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca', b'\x7fELF'}
             and not payload.startswith(b'MZ'), 'No executable payload')
        if row['kind'] == 'json':
            value = json.loads(payload)
            privacy(value)
            parsed[logical] = value
            counters['JSON_bodies'] += 1
        elif row['kind'] == 'source':
            ast.parse(payload, filename=logical)
            counters['Python_AST_bodies'] += 1
        elif row['kind'] == 'synthetic-fixture':
            need(logical == 'synthetic-fixture/coupled-before-export.FCStd'
                 and sha(payload) == '3128ea4b56421f21d26256088ca9f4ae5f0f985ac19024b7fa8c9dcf8fa23452'
                 and payload.startswith(b'PK\x03\x04'), 'Only exact generic FCStd allowed')
        elif row['kind'] == 'profile-binary':
            need(logical == 'runs/installed-profile-baseline-r02/whole-public-write.prof'
                 and sha(payload) == 'f9891864c1f566d05a626597a414702e692b2072bb899065721a5c0e99d5bdec',
                 'Only exact own-generated profiler blob allowed')
        else:
            need(row['kind'] == 'text', 'Known payload kind')
            text = payload.decode('utf-8')
            need(b'\0' not in payload and not re.search(
                r'(?im)^(OPENAI_API_KEY|GITHUB_TOKEN|GH_TOKEN|AWS_SECRET_ACCESS_KEY|PASSWORD|ACCESS_TOKEN|REFRESH_TOKEN)\s*=\s*\S+',
                text), 'No environment credential dump')
        decoded[logical] = payload
        origins[row['original_path']] = logical
        stored_hashes[str(relative)] = sha(stored)
        counters[row['encoding']] += 1
        counters['stored_bytes'] += len(stored)
        counters['decoded_bytes'] += len(payload)
    need(set(decoded) == set(planned) | {'approved-plan.json'}, 'Complete logical plan coverage')

    def role(ref):
        logical = origins[ref['path']]
        need(sha(decoded[logical]) == ref['sha256'], 'Role pin ' + logical)
        return parsed[logical]

    qualified = role(plan['qualification_receipt'])
    need(summary['schema'] == 'FreeCAD-882-profile-validation-v1' and summary['passed'] is True
         and summary['mode'] == 'profiling_only' and summary['qualification'] == qualified,
         'Exact summary qualification')
    need(summary['evidence'] == {'directory': 'package/local-completion/freecad-882-source-evidence',
         'index_sha256': PINS['index'], 'indexed_files': 95, 'plan_sha256': PINS['plan']}, 'Summary index binding')
    need(index['qualification_receipt'] == plan['qualification_receipt'], 'Index qualification binding')
    roles = {key: role(ref) for key, ref in qualified['roles'].items()}
    final_review = role(qualified['independent_final_review'])
    need(final_review['passed'] is True and final_review['outstanding_findings'] == [], 'Final profile review')
    need(role(final_review['attribution_report']) == roles['attribution_opportunity_report'], 'Final attribution binding')
    for ref in final_review['supporting_reviews']:
        role(ref)
    before = roles['setup_failure_execution']
    need(before['passed'] is False and roles['setup_failure_classification']['actual_observations']['public_write_started'] is False,
         'Historical setup halt not promoted')
    execution, profile = roles['baseline_execution'], roles['baseline_profile']
    need(execution['passed'] is True and profile['passed'] is True and profile['actual_write_inp_file_calls'] == 1,
         'Actual completed single export')
    prefix = 'runs/installed-profile-baseline-r02/'
    identity, manifest = parsed[prefix + 'identity.json'], parsed[prefix + 'manifest.json']
    need(identity['runtime'][-1] == qualified['actual_installed_commit']
         == '7667033a14654a9b229bf59b94cb3012ce989170'
         and identity['runtime'][3] == qualified['actual_installed_revision'] == '49261 +224 (Git)'
         and manifest['source_HEAD'] == qualified['measured_source_HEAD']
         == '6ba8b0000640e40eda16df2af98ad5e6578cdad9'
         and identity['source_or_build_import_override'] is False,
         'Actual runtime distinct from recorded source')
    need(identity['passed'] is True and identity['selected_suite']['name'] == 'B882Profile'
         and identity['selected_suite']['count'] == 1 and identity['expected_total_count'] == 2
         and execution['identity_sha256'] == sha(decoded[prefix + 'identity.json'])
         and execution['manifest_sha256'] == identity['manifest_sha256'] == sha(decoded[prefix + 'manifest.json'])
         and execution['log_sha256'] == sha(decoded[prefix + 'run.log'])
         and execution['inputs_before'] == execution['inputs_after'] == manifest['inputs']['files'],
         'Identity/manifest/input-map/log bindings')
    log = decoded[prefix + 'run.log'].decode('utf-8')
    need(re.findall(r'^Ran (\d+) tests? in ([\d.]+)s$', log, re.M) == [('2', '1191.885')]
         and len(re.findall(r'^OK$', log, re.M)) == 1
         and not re.search(r'^(FAILED|FAIL:|ERROR:|UNEXPECTED SUCCESS)|\.\.\. skipped ', log, re.M),
         'Two actual tests and no skips/failures')
    need(all(execution[key] is True for key in ['source_and_supervisor_unchanged', 'manifest_unchanged',
         'application_and_three_profiles_unchanged', 'sixteen_selected_dependencies_unchanged',
         'post_run_serial_guard_passed', 'produced_diagnostic_files_unchanged_after_parsing',
         'child_reaped', 'process_group_gone']) and execution['returncode'] == 0 and not execution['timed_out'],
         'Actual fences and owned cleanup')
    for name, descriptor in execution['produced_diagnostic_files'].items():
        need(sha(decoded[prefix + name]) == descriptor['sha256'] and len(decoded[prefix + name]) == descriptor['bytes'],
             'All eight baseline outputs bind')
    need(len(execution['produced_diagnostic_files']) == 8 and execution['guard_errors'] == [], 'Eight fenced outputs/no guard errors')
    metadata = parsed[prefix + 'native/Mesh.accounting.json']
    need(metadata['deck_sha256'] == sha(decoded[prefix + 'native/Mesh.inp'])
         and metadata['request_sha256'] == sha(decoded[prefix + 'native/Mesh.accounting'])
         and {k: metadata['capacity'][k] for k in profile['actual_export_capacity']} == profile['actual_export_capacity'],
         'Sidecar links and exact selected capacity projection')
    need(metadata['capacity']['required'] == {'supports': 1, 'bodies': 264, 'ports': 264,
         'angles': 792, 'springs': 792} and metadata['capacity']['total'] == 2113
         and metadata['capacity']['binary_sha256'] == qualified['default_native_sha256']
         == '6c02452a896727af6cb4578fd3fb6bbfbdd48e3fb887c1c04fa2d8b171976c66',
         'Exact graph and default native candidate')
    request_rows = [line.split() for line in decoded[prefix + 'native/Mesh.accounting'].decode().splitlines() if line.strip()]
    declarations = dict(Counter(row[0] for row in request_rows if row[0][0].isalpha()))
    need(declarations == profile['request_declarations'] == {'ANGLE': 792, 'BODY': 264,
         'CCX_FORCE_ACCOUNTING_V3': 1, 'END': 1, 'PORT': 264, 'SPC_SUPPORT': 1, 'SPRING': 792}, 'Complete graph')
    ports = {row[1]: [int(row[2]), int(row[3])] for row in request_rows if row[0] == 'PORT'}
    need(ports == profile['native_PORT_IDs'] and len(ports) == 264, 'Actual native port IDs')
    stats = marshal.loads(decoded[prefix + 'whole-public-write.prof'])
    profile_rows = {(row['filename'], row['line'], row['function']): row for row in profile['profile_operation_rows']}
    need(len(stats) == 661 and set(stats) == set(profile_rows) and all(
        stats[key][:4] == (row['primitive_calls'], row['total_calls'], row['self_seconds'], row['cumulative_seconds'])
        for key, row in profile_rows.items()), 'All raw profiler rows')
    need(qualified['scope']['profiling_only'] is True and all(qualified['scope'][key] is False for key in
         ['implementation_performed', 'candidate_speedup_claimed', 'installation_performed',
          'new_build_or_physical_qualification_claimed', 'engineering_or_BIM_accepted', 'Oomakhi_accessed_or_solved']),
         'Profiling-only scope')
    need(qualified['implementation_follow_up']['id'] == 'FreeCAD-3q7'
         and qualified['implementation_follow_up']['implemented_or_accepted'] is False
         and qualified['implementation_follow_up']['status'] == 'open', 'Open unimplemented follow-up')
    attribution = roles['attribution_opportunity_report']
    need(qualified['scope']['force_original_origin_moment_limit'] == .01
         and qualified['scope']['scalar_response_limit'] == .05
         and attribution['scope_and_holds']['R49_and_R51_remain_failed_against_5percent'] is True,
         'Original engineering limits and holds')
    for binding in attribution['source_bindings']:
        payload = decoded[origins[binding['runtime_path']]]
        current_source = Path(binding['path']).read_bytes()
        need(payload == current_source and sha(payload) == binding['sha256']
             and len(payload) == binding['bytes']
             and manifest['inputs']['files'][binding['path']] == binding['sha256'],
             'Measured source/runtime/manifest source binding')
        original_hashes[binding['path']] = sha(current_source)
    for logical, payload in decoded.items():
        if logical.startswith('qa/profile-v4/'):
            original_path = next(row['original_path'] for row in rows
                                 if row['file'] == logical or row['file'] == logical + '.gz')
            need(manifest['inputs']['files'][original_path] == sha(payload), 'Executed QA manifest binding')
    custody = roles['fixture_retention_custody']
    need(custody['passed'] is True and len(custody['files']) == 12, 'Twelve retained fixture leaves')
    for entry in custody['files']:
        payload = decoded['synthetic-fixture/' + entry['path']]
        source = Path(entry['source']).read_bytes()
        need(payload == source and len(payload) == entry['bytes'] and sha(payload) == entry['sha256'],
             'Retained fixture equals actual original ' + entry['path'])
        original_hashes[entry['source']] = sha(source)
    original = parsed['synthetic-fixture/mesh-membership.json']
    restored = parsed['synthetic-fixture/restored-volume-connectivity.json']
    need(len(original['volume_connectivity']) == len(restored) == 74228
         and Counter(map(tuple, original['volume_connectivity'].values())) == Counter(map(tuple, restored.values()))
         and canonical(restored) == '23491724b34bf065d49900335b11d6381a0955b8890dddd080bf438b9d7532fc',
         'Ordered-cell bijection, no per-cell sorting')
    need(all(sha((PACKET / path).read_bytes()) == value for path, value in stored_hashes.items())
         and all(sha(Path(path).read_bytes()) == value for path, value in original_hashes.items())
         and (PACKET / 'index.json').read_bytes() == pinned_bytes['index']
         and SUMMARY.read_bytes() == pinned_bytes['summary'] and PLAN.read_bytes() == pinned_bytes['plan'],
         'All published/original bytes and root pins unchanged at audit end')
    child_bytes = CHILD_REVIEW.read_bytes()
    child = json.loads(child_bytes)
    need(sha(child_bytes) == CHILD_SHA and child['outstanding_findings'] == []
         and child['bindings']['index_sha256'] == PINS['index']
         and child['bindings']['summary_sha256'] == PINS['summary']
         and child['bindings']['approved_plan_sha256'] == PINS['plan'], 'Independent semantic/privacy axis')
    report = {
        'schema': 'FreeCAD-882-independent-publication-audit-v1', 'passed': True,
        'status': 'Actual published byte/crosslink/privacy audit passed',
        'scope': 'File/JSON/gzip/hash/AST/marshal arithmetic only; no native/app/test/collector/Git execution or mutation.',
        'packet': str(PACKET), 'index_sha256': PINS['index'], 'summary_sha256': PINS['summary'],
        'approved_plan_sha256': PINS['plan'], 'audit_code_sha256': sha(Path(__file__).read_bytes()),
        'coverage': dict(counters, indexed_bodies=95, indexed_plus_index=96, summary_files=1,
                         approved_explicit_inputs=94, originals_byte_verified=95,
                         derived_excerpts=0, retained_fixture_actual_originals_verified=12,
                         raw_profiler_rows_verified=661),
        'checks': ['Exact physical and logical coverage, safe regular paths, all stored/decoded/original hashes and sizes',
                   'Every gzip body reproduces gzip9/mtime0 encoding exactly; no normalized or excerpted bytes',
                   'All required role, final-review, sidecar, defining output, source/helper and profiler links',
                   'Exactly twelve retained generic fixture leaves equal captured historical/current original bytes',
                   'Ordered-cell tuple multiset and canonical restored topology match without node sorting',
                   'No raw user-profile/app/dependency inventory, configuration, environment dump or runtime executable payload',
                   'Summary remains profiling-only with open unimplemented 3q7; no speedup/new physics/install/engineering claim',
                   'Every published stored body, indexed original, retained prior original, index, summary and approved plan unchanged at audit end'],
        'parallel_scope_privacy_review': {'path': str(CHILD_REVIEW), 'sha256': CHILD_SHA,
                                         'read_completely_by_main_reviewer': True,
                                         'outstanding_findings': [],
                                         'scope': 'Independent decoded JSON semantics/privacy and generic FCStd archive metadata; not the publisher.'},
        'limits': {'native_or_product_execution': False, 'new_physics': False, 'speedup': False,
                   'installation': False, 'Oomakhi': False, 'raw_inventories_or_runtime_binary_payloads': False,
                   'profile_binary': 'The exact own-generated cProfile diagnostic is intentionally retained; user configuration profiles are not.',
                   'engineering_holds': 'Unchanged original limits and R49/R51 engineering holds; this is software profiling evidence only.',
                   'historical_absolute_paths': 'Preserved literally, not rebound for portable replay; an explicit matching external runtime/configuration is required.',
                   'authorship': 'Auditor previously authored yzk native C/hooks and reviewed current QA/attribution; auditor did not publish the packet.'},
        'findings': [], 'report_is_outside_immutable_packet': True,
    }
    with REPORT.open('x') as handle:
        json.dump(report, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write('\n')
    print(json.dumps({'passed': True, 'report': str(REPORT), 'report_sha256': sha(REPORT.read_bytes()),
                      'audit_code_sha256': report['audit_code_sha256'], 'coverage': report['coverage']}, sort_keys=True))


if __name__ == '__main__':
    main()
