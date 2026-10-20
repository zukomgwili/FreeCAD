"""Root-only explicit evidence archiver; no native, Git or qualification run.

Root supplies a separately reviewed completed profiling receipt and exact file
plan. This module verifies custody, privacy and byte copies; it does not run
or claim optimization, builds, candidate speedup, physics or installation.
Check-only writes zero files. Every destination must be new.
"""
import argparse
import ast
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
TASK = Path('/private/tmp/freecad-882-VGfnpo')
REPO = Path('/Users/zukomgwili/src/FreeCAD')
APP_SOURCE = Path('/Applications/FreeCAD-27.1.0.app/Contents/Resources/Mod/Fem')
OUT = REPO / 'package/local-completion/freecad-882-source-evidence'
SUMMARY = REPO / 'package/local-completion/freecad-882-validation.json'
MAX = 32 * 1024 * 1024
DENIED_PARTS = {'.git', '.beads', '.pixi', '__pycache__', 'CMakeFiles', 'CalculiX',
    'profiles', 'module-cache', 'freecad_user_home', 'freecad_user_data', 'freecad_user_temp',
    'xdg_config_home', 'xdg_data_home', 'xdg_cache_home'}
DENIED_SUFFIXES = {'.cfg', '.pyc', '.pyo', '.so', '.dylib', '.o', '.a', '.exe', '.frd', '.dat'}
RAW_KEYS = {'environment', 'environ', 'profiles', 'profile_inventories', 'profile_inventory',
    'app_inventory', 'application_inventory', 'inventory', 'critical_before', 'critical_after'}
SECRET_KEYS = {'password', 'api_key', 'apikey', 'secret', 'access_token', 'refresh_token',
               'authorization', 'cookie'}
REQUIRED_ROLES = {'setup_failure_execution', 'setup_failure_classification', 'restore_execution', 'restore_probe',
    'restore_bijection_amendment', 'fixture_retention_custody',
    'baseline_execution', 'baseline_profile', 'attribution_opportunity_report', 'scope_clarification'}


def need(value, message):
    if not value:
        raise RuntimeError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()


def regular(path):
    path = Path(path)
    need(path.is_absolute() and '..' not in path.parts, 'Absolute non-traversing input required')
    roots = [root for root in (TASK, REPO, APP_SOURCE) if path.is_relative_to(root)]
    need(len(roots) == 1, 'Input outside explicit known evidence/source roots: ' + str(path))
    root = roots[0]
    relative = path.relative_to(root)
    need(not DENIED_PARTS.intersection(relative.parts)
         and not (path.name.startswith('private-') and path.suffix == '.json')
         and path.name not in {'.env', 'user.cfg', 'system.cfg'}
         and path.suffix.lower() not in DENIED_SUFFIXES, 'Excluded private/runtime input: ' + str(path))
    cursor = path
    while cursor != root:
        need(not cursor.is_symlink(), 'Input links are excluded: ' + str(cursor))
        cursor = cursor.parent
    need(path.is_file() and path.stat().st_size <= MAX, 'Missing/oversized regular file: ' + str(path))
    return path


def privacy(value):
    if isinstance(value, dict):
        need(not (isinstance(value.get('.'), dict) and value['.'].get('kind') == 'dir'), 'Raw app/profile inventory body')
        keys = {str(key).lower() for key in value}
        need(not RAW_KEYS.intersection(keys) and not SECRET_KEYS.intersection(keys), 'Inventory/environment/secret dictionary')
        need(not {'dev', 'inode', 'mtime_ns', 'ctime_ns'}.issubset(keys), 'Raw selected-dependency stat inventory')
        for item in value.values():
            privacy(item)
    elif isinstance(value, list):
        for item in value:
            privacy(item)


def payload_check(path, data, kind, own_profiles):
    need(kind in {'text', 'json', 'source', 'synthetic-fixture', 'profile-binary'}, 'Unknown payload kind')
    need(data[:4] not in {b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xce\xfa\xed\xfe',
         b'\xfe\xed\xfa\xce', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca', b'\xca\xfe\xba\xbf',
         b'\xbf\xba\xfe\xca', b'\x7fELF'}
         and not data.startswith(b'MZ'), 'Runtime executable payload is forbidden')
    if path.suffix.lower() == '.fcstd':
        need(kind == 'synthetic-fixture' and path.name == 'coupled-before-export.FCStd'
             and path.parent == TASK / 'retained-synthetic-fixture-r01'
             and len(data) == 6045688
             and digest(data) == '3128ea4b56421f21d26256088ca9f4ae5f0f985ac19024b7fa8c9dcf8fa23452'
             and data.startswith(b'PK\x03\x04'), 'Only the exact generic saved fixture is approved')
        return
    if kind == 'profile-binary':
        need(path.name == 'whole-public-write.prof' and str(path) in own_profiles
             and digest(data) == own_profiles[str(path)]['sha256'], 'Profiler blob is not a bound own-generated output')
        return  # Preserve exact diagnostic bytes; never unmarshal/execute them.
    text = data.decode('utf-8')
    need(b'\x00' not in data and not re.search(r'(?im)^(?:OPENAI_API_KEY|GITHUB_TOKEN|GH_TOKEN|'
        r'AWS_SECRET_ACCESS_KEY|PASSWORD|ACCESS_TOKEN|REFRESH_TOKEN)\s*=\s*\S+', text), 'Environment/credential dump')
    if path.suffix == '.py':
        ast.parse(data, filename=str(path))
    if path.suffix == '.json':
        privacy(json.loads(data))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    need(not sys.flags.optimize, 'Unoptimized interpreter required')
    plan_path = regular(args.plan.absolute())
    need(plan_path.parent == TASK / 'planning/collection', 'Explicit private root-reviewed plan only')
    plan_bytes = plan_path.read_bytes()
    need(digest(plan_bytes) == args.plan_sha256, 'Root-approved plan SHA differs')
    plan = json.loads(plan_bytes)
    need(plan['schema'] == 'FreeCAD-882-approved-evidence-plan-v1' and plan['root_approved'] is True,
         'A completed approved plan is required, not the proposal')
    files = plan['files']
    need(len(files) == len({row['path'] for row in files}) == len({row['destination'] for row in files}), 'Duplicate input or destination')
    raw, entries = {}, {}
    for row in files:
        need(set(row) == {'path', 'destination', 'sha256', 'bytes', 'kind', 'classification'}, 'Unexpected explicit-file fields')
        path = regular(Path(row['path']))
        data = path.read_bytes()
        need(digest(data) == row['sha256'] and len(data) == row['bytes'], 'Explicit original changed: ' + str(path))
        target = Path(row['destination'])
        need(target.parts and not target.is_absolute() and '..' not in target.parts
             and not DENIED_PARTS.intersection(target.parts)
             and target.name != 'index.json' and row['classification'], 'Unsafe/unclassified destination')
        raw[str(path)], entries[str(path)] = data, row
    qualified_ref = plan['qualification_receipt']
    need(qualified_ref['path'] in raw and digest(raw[qualified_ref['path']]) == qualified_ref['sha256'], 'Final qualification is not exactly indexed')
    qualified = json.loads(raw[qualified_ref['path']])
    need(qualified['schema'] == 'FreeCAD-882-completed-profile-review-v1' and qualified['passed'] is True,
         'Actual completed profiling review required; no future PASS inference')
    scope = qualified['scope']
    need(scope['profiling_only'] is True and scope['installation_performed'] is False
         and scope['Oomakhi_accessed_or_solved'] is False and scope['engineering_or_BIM_accepted'] is False
         and scope['implementation_performed'] is False and scope['candidate_speedup_claimed'] is False
         and scope['new_build_or_physical_qualification_claimed'] is False
         and scope['force_original_origin_moment_limit'] == .01 and scope['scalar_response_limit'] == .05,
         'Qualification scope/unchanged limits differ')
    roles = qualified['roles']
    need(set(roles) == REQUIRED_ROLES, 'Actual required role receipts missing or unexpectedly expanded')
    role_data = {}
    for role, ref in roles.items():
        need(ref['path'] in raw and digest(raw[ref['path']]) == ref['sha256'], 'Role receipt is not an exact indexed input: ' + role)
        role_data[role] = json.loads(raw[ref['path']])
    need(role_data['setup_failure_execution']['passed'] is False,
         'Preserve the failed setup receipt without promoting it to PASS')
    halted = role_data['setup_failure_classification']
    need(halted['schema'] == 'FreeCAD-882-baseline-setup-halt-review-v1'
         and halted['actual_observations']['public_write_started'] is False
         and halted['actual_observations']['profiler_output_produced'] is False
         and halted['receipt_interpretation']['no_historical_receipt_or_executed_QA_bytes_should_be_repaired'] is True,
         'Failed comparison setup is not a product reproduction or export measurement')
    probe = role_data['restore_probe']
    need(probe['schema'] == 'FreeCAD-882-restore-representation-probe-v1'
         and probe['passed'] is True and probe['actual_write_inp_file_calls'] == 0
         and probe['geometry_or_orientation_equivalence_qualification_claimed'] is False,
         'Read-only restore observation scope differs')
    amendment = role_data['restore_bijection_amendment']
    arithmetic = amendment['independent_arithmetic']
    need(amendment['schema'] == 'FreeCAD-882-independent-restore-bijection-and-benchmark-amendment-v1'
         and arithmetic['original_cells'] == arithmetic['restored_cells'] == 74228
         and arithmetic['missing_ordered_tuples'] == arithmetic['extra_ordered_tuples'] == 0
         and amendment['benchmark_scope_amendment']['historical_physical_qualification_transfer'] is False
         and amendment['outstanding_audit_findings'] == [], 'Restored-ID amendment differs')
    clarification = role_data['scope_clarification']
    need(clarification['schema'] == 'FreeCAD-882-profiling-vs-implementation-scope-clarification-v1'
         and clarification['limits']['permission_expansion'] is False
         and clarification['existing_plan_clarification']['frozen_existing_plan_or_receipts_changed'] is False,
         'Profiling-only scope clarification differs')
    for role in ('restore_execution', 'fixture_retention_custody', 'baseline_execution', 'baseline_profile', 'attribution_opportunity_report'):
        need(role_data[role]['passed'] is True, 'Completed profiling role not passed: ' + role)
    profile = role_data['baseline_profile']
    need(profile['schema'] == 'FreeCAD-882-whole-public-export-profile-v3'
         and profile['actual_write_inp_file_calls'] == 1
         and profile['historical_deck_request_PORT_comparisons_are_diagnostic_only'] is True
         and profile['old_physical_qualification_inherited_by_this_export'] is False,
         'Completed single whole-call measurement scope differs')
    own_profiles = {}
    qa_directories = {'setup_failure_execution': TASK / 'proposals',
        'restore_execution': TASK / 'restore-probe-r01', 'baseline_execution': TASK / 'profile-v4'}
    for role, qa in qa_directories.items():
        run = role_data[role]
        need(run['child_reaped'] is True and run['process_group_gone'] is True and run['timed_out'] is False
             and all(run[key] is True for key in ('source_and_supervisor_unchanged', 'manifest_unchanged',
                 'application_and_three_profiles_unchanged', 'sixteen_selected_dependencies_unchanged',
                 'post_run_serial_guard_passed')), 'Historical/run custody or cleanup incomplete: ' + role)
        manifest = str(Path(roles[role]['path']).parent / 'manifest.json')
        need(manifest in raw and digest(raw[manifest]) == run['manifest_sha256'], 'Exact executed manifest missing: ' + role)
        for path, wanted in run['inputs_before'].items():
            if Path(path).parent == qa and Path(path).suffix == '.py':
                need(path in raw and digest(raw[path]) == wanted, 'Frozen run QA source missing: ' + path)
        for ref in run['produced_diagnostic_files'].values():
            need(ref['path'] in raw and digest(raw[ref['path']]) == ref['sha256']
                 and len(raw[ref['path']]) == ref['bytes'], 'Exact historical/run output missing: ' + role)
    for role in ('baseline_execution',):
        run = role_data[role]
        need(run['returncode'] == 0 and run['child_reaped'] is True and run['process_group_gone'] is True
             and run['timed_out'] is False and run['produced_diagnostic_files_unchanged_after_parsing'] is True,
             'Profile child/custody gate incomplete')
        need(all(run[key] is True for key in ('source_and_supervisor_unchanged', 'manifest_unchanged',
             'application_and_three_profiles_unchanged', 'sixteen_selected_dependencies_unchanged',
             'post_run_serial_guard_passed')), 'Profile source/protected-input custody incomplete')
        outputs = run['produced_diagnostic_files']
        need(set(outputs) == {'identity.json', 'export-profile.json', 'run.log', 'whole-public-write.prof',
            'profile-cumulative.txt', 'native/Mesh.inp', 'native/Mesh.accounting', 'native/Mesh.accounting.json'},
            'All eight defining profile outputs must be retained')
        for ref in outputs.values():
            need(ref['path'] in raw and digest(raw[ref['path']]) == ref['sha256']
                 and len(raw[ref['path']]) == ref['bytes'], 'Bound profile output missing/changed')
        need(outputs['export-profile.json']['path'] == roles['baseline_profile']['path']
             and outputs['export-profile.json']['sha256'] == roles['baseline_profile']['sha256'],
             'Profile role must be the exact output bound by its execution')
        own_profiles[outputs['whole-public-write.prof']['path']] = outputs['whole-public-write.prof']
    custody = role_data['fixture_retention_custody']
    need(custody['schema'] == 'FreeCAD-882-exact-synthetic-retention-v1'
         and custody['originals_unchanged'] is True and custody['copies_exact'] is True, 'Exact generic retention required')
    for ref in custody['files']:
        name = str(TASK / 'retained-synthetic-fixture-r01' / ref['path'])
        need(name in raw and digest(raw[name]) == ref['sha256'] and len(raw[name]) == ref['bytes'], 'Retained replay input missing/changed')
    records, pending = [], {}
    for path, data in raw.items():
        row = entries[path]
        payload_check(Path(path), data, row['kind'], own_profiles)
        stored = gzip.compress(data, compresslevel=9, mtime=0) if len(data) >= 65536 else data
        encoding = 'gzip' if len(data) >= 65536 else 'identity'
        destination = row['destination'] + ('.gz' if encoding == 'gzip' else '')
        need(destination not in pending and destination != 'approved-plan.json', 'Transformed destination collision')
        pending[destination] = stored
        records.append({'file': destination, 'kind': row['kind'], 'classification': row['classification'],
            'original_path': path, 'original_sha256': digest(data), 'original_bytes': len(data),
            'stored_sha256': digest(stored), 'stored_bytes': len(stored), 'encoding': encoding,
            'decoded_sha256': digest(data), 'decoded_bytes': len(data), 'transformation': 'exact bytes'})
    pending['approved-plan.json'] = plan_bytes
    records.append({'file': 'approved-plan.json', 'kind': 'json', 'classification': 'Exact separately root-reviewed file plan',
        'original_path': str(plan_path), 'original_sha256': digest(plan_bytes), 'original_bytes': len(plan_bytes),
        'stored_sha256': digest(plan_bytes), 'stored_bytes': len(plan_bytes), 'encoding': 'identity',
        'decoded_sha256': digest(plan_bytes), 'decoded_bytes': len(plan_bytes), 'transformation': 'exact bytes'})
    index = {'schema': 'FreeCAD-882-source-evidence-index-v1', 'files': sorted(records, key=lambda row: row['file']),
        'indexed_files': len(records), 'qualification_receipt': qualified_ref,
        'scope': 'Exact curated software-QA inputs/outputs; no raw profiles/environment/dependency inventory or runtime binaries'}
    summary = {'schema': 'FreeCAD-882-profile-validation-v1', 'passed': True, 'mode': 'profiling_only',
        'qualification': qualified, 'evidence': {'directory': str(OUT.relative_to(REPO)),
        'index_sha256': digest(encode(index)), 'indexed_files': len(records), 'plan_sha256': digest(plan_bytes)},
        'replay_limits': 'Actual synthetic saved fixture/mesh and defining inputs are retained. Executed historical paths remain literal. Replay needs an explicit new configuration and matching FreeCAD/Pixi/native runtime; none are bundled. Profile CPU/cumulative limits and old engineering holds remain unchanged. No candidate, speedup, implementation, fresh build, physics or installation is claimed.'}
    privacy(plan)
    privacy(index)
    privacy(summary)
    for path, data in raw.items():
        need(digest(regular(Path(path)).read_bytes()) == digest(data), 'Original changed during collection')
    need(digest(regular(plan_path).read_bytes()) == args.plan_sha256, 'Approved plan changed during collection')
    need(OUT.parent.is_dir() and not OUT.parent.is_symlink()
         and not OUT.exists() and not OUT.is_symlink() and not SUMMARY.exists() and not SUMMARY.is_symlink(), 'New publication only')
    if not args.check_only:
        OUT.mkdir()
        for name, data in sorted(pending.items()):
            target = OUT / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(data)
        with (OUT / 'index.json').open('xb') as stream:
            stream.write(encode(index))
        with SUMMARY.open('xb') as stream:
            stream.write(encode(summary))
        need({str(path.relative_to(OUT)) for path in OUT.rglob('*') if path.is_file()} == set(pending) | {'index.json'}, 'Published coverage differs')
        for name, data in pending.items():
            need((OUT / name).read_bytes() == data, 'Published bytes differ: ' + name)
        need((OUT / 'index.json').read_bytes() == encode(index) and SUMMARY.read_bytes() == encode(summary),
             'Published index or summary bytes differ')
        for path, data in raw.items():
            need(digest(regular(Path(path)).read_bytes()) == digest(data), 'Original changed during publication')
        need(digest(regular(plan_path).read_bytes()) == args.plan_sha256, 'Approved plan changed during publication')
    print(json.dumps({'passed': True, 'check_only': args.check_only, 'indexed_files': len(records),
        'writes': 0 if args.check_only else len(records) + 2,
        'index_sha256': digest(encode(index)), 'summary_sha256': digest(encode(summary))}))


if __name__ == '__main__':
    main()
