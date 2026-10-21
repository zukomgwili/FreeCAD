"""Root-only exact explicit-plan installation evidence collector; no app launches.

This is an unexecuted proposal. Root must read/approve its exact bytes, the
completed semantic review and every actual selection before any invocation.
Check-only writes nothing. Publication is new-only and needs a separate audit.
"""
import sys
sys.dont_write_bytecode = True
import argparse
import ast
import gzip
import hashlib
import json
import math
from pathlib import Path
import re

TASK = Path('/private/tmp/freecad-3q7-install-W35DLJ')
REPO = Path('/Users/zukomgwili/src/FreeCAD')
APP = Path('/Applications/FreeCAD-27.1.0.app')
BACKUP = Path('/Users/zukomgwili/Applications/FreeCAD Backups/FreeCAD-27.1.0-before-3q7-7667033a14.app')
OUT = REPO / 'package/local-completion/freecad-3q7-installation-evidence'
SUMMARY = REPO / 'package/local-completion/freecad-3q7-installation.json'
COMMIT = '6a0ed157b1063fa21407dc8f3cdfa3aef9484d8d'
REVISION = '49261 +229 (Git)'
NATIVE = '6c02452a896727af6cb4578fd3fb6bbfbdd48e3fb887c1c04fa2d8b171976c66'
PER_FILE, PACKET = 128 * 1024 * 1024, 512 * 1024 * 1024
REQUIRED = {'source_build', 'ctest', 'payload_audit', 'stage_audit', 'custody_audit',
    'swap', 'stage_fem', 'stage_gui', 'stage_native', 'installed_fem', 'installed_gui',
    'installed_native', 'installed_capacity', 'installed_witness', 'installed_cold',
    'installed_cold_receipt', 'installed_physical_audit'}
DENIED = {'.git', '.beads', '.pixi', '__pycache__', 'CMakeFiles', 'CalculiX', 'profiles',
    'module-cache', 'freecad_user_home', 'freecad_user_data', 'freecad_user_temp',
    'xdg_config_home', 'xdg_data_home', 'xdg_cache_home'}
SUFFIXES = {'.cfg', '.pyc', '.pyo', '.so', '.dylib', '.o', '.a', '.exe'}
KINDS = {'json', 'source', 'text', 'native-input', 'native-output', 'synthetic-fixture'}
RAW_KEYS = {'environment', 'environ', 'profiles', 'inventory', 'profile_inventory',
    'profile_inventories', 'app_inventory', 'application_inventory', 'critical_before', 'critical_after',
    'password', 'api_key', 'apikey', 'secret', 'access_token', 'refresh_token', 'authorization', 'cookie'}
MAGIC = {b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xce',
    b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca', b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca', b'\x7fELF'}
CASE_NAMES = {'coupled-before-export.FCStd', 'coupled-native-current.FCStd', 'witness-receipt.json',
    'independent-export-audit.json', 'physical-face-motion-proof.json', 'motion-from-original-dat.json',
    'cold-case.json', 'geometry-contract.json', 'export-properties.json', 'native-properties.json',
    'native-accounting-data.json', 'mesh-membership.json', 'native.stdout', 'native.stderr',
    'native/Mesh.inp', 'native/Mesh.accounting', 'native/Mesh.accounting.json',
    'native/Mesh.accounting.out', 'native/Mesh.dat', 'native/Mesh.frd'}
CASE_REQUIRED = {'coupled-before-export.FCStd', 'coupled-native-current.FCStd', 'witness-receipt.json',
    'cold-case.json', 'native-accounting-data.json', 'native/Mesh.inp', 'native/Mesh.accounting',
    'native/Mesh.accounting.out', 'native/Mesh.dat', 'native/Mesh.frd'}
FROZEN = {'coupled_port_capacity_fixture.json': '9142f5aa4d149aa1f0d518a592a78638f9489fb3e245af67ea4fd463e5b8ae22',
    'coupled_port_capacity_oracle.json': '42fa6289fd9e1f80efa56db27c02c06a5454ed9880f7ca61bfd80992dfb251b8'}


def need(value, message):
    if not value:
        raise RuntimeError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()


def desc(path, data):
    return {'path': str(path), 'sha256': sha(data), 'bytes': len(data)}


def regular(value, copying):
    path = Path(value)
    need(path.is_absolute() and '..' not in path.parts and str(path) == str(value), 'Exact absolute path required')
    roots = [root for root in (TASK, REPO, APP, BACKUP) if path.is_relative_to(root)]
    need(len(roots) == 1, 'Input outside explicit roots')
    root = roots[0]
    cursor = path
    while cursor != root:
        need(not cursor.is_symlink(), 'Input link excluded: ' + str(cursor))
        cursor = cursor.parent
    need(path.is_file(), 'Missing regular input: ' + str(path))
    if copying:
        need(root in (TASK, REPO) and not DENIED.intersection(path.relative_to(root).parts), 'Excluded copy namespace')
        need(not path.name.startswith('private-') and path.name != '.env'
             and path.suffix.lower() not in SUFFIXES and path.stat().st_size <= PER_FILE, 'Excluded private/config/binary/oversized leaf')
    return path


def privacy(value):
    if isinstance(value, dict):
        keys = {str(key).lower() for key in value}
        need(not RAW_KEYS.intersection(keys), 'Raw inventory/environment/credential dictionary')
        need(not (isinstance(value.get('.'), dict) and value['.'].get('kind') == 'dir'), 'Raw app/profile inventory')
        need(not {'dev', 'inode', 'mtime_ns', 'ctime_ns'}.issubset(keys), 'Raw dependency inventory')
        for item in value.values():
            privacy(item)
    elif isinstance(value, list):
        for item in value:
            privacy(item)
    elif isinstance(value, float):
        need(math.isfinite(value), 'Nonfinite JSON value')


def exact_ref(raw, ref, parse=True):
    need(set(ref) == {'path', 'sha256', 'bytes'} and type(ref['bytes']) is int and ref['bytes'] >= 0
         and re.fullmatch('[0-9a-f]{64}', ref['sha256']), 'Malformed exact descriptor')
    need(ref['path'] in raw and desc(ref['path'], raw[ref['path']]) == ref, 'Missing/different defining bytes: ' + ref['path'])
    return json.loads(raw[ref['path']]) if parse else raw[ref['path']]


def app_gate(name, run, raw, count, module, application):
    flags = ('child_reaped', 'process_group_gone', 'manifest_unchanged', 'source_build_harness_unchanged',
        'app_and_profiles_unchanged', 'application_unchanged', 'critical_dependency_pins_unchanged', 'post_run_serial_guard_passed')
    need(run['passed'] is True and run['returncode'] == 0 and run['timed_out'] is False
         and all(run[key] is True for key in flags) and run['application'] == str(application)
         and run['module'] == module and run['skipped_lines'] == []
         and run['rebound_or_reused_stage_outputs'] is False and run['inputs_before'] == run['inputs_after'], 'Actual guarded literal-app gate differs: ' + name)
    parent = Path(run['_selected_role_path']).parent
    identity_path, manifest_path, log_path = (str(parent / leaf) for leaf in ('identity.json', 'manifest.json', 'run.log'))
    need(all(path in raw for path in (identity_path, manifest_path, log_path)), 'Defining identity/manifest/log not retained')
    need(sha(raw[identity_path]) == run['identity_sha256'] and sha(raw[manifest_path]) == run['manifest_sha256'], 'Identity/manifest binding differs')
    need(sha(raw[log_path]) == run['log_sha256'], 'Producer log binding differs')
    identity, manifest = json.loads(raw[identity_path]), json.loads(raw[manifest_path])
    need(identity['passed'] is True and identity['runtime'][3] == REVISION and identity['runtime'][-1] == COMMIT
         and identity['application'] == str(application) and identity['source_or_build_import_override'] is False
         and identity['manifest_sha256'] == sha(raw[manifest_path])
         and manifest['application'] == str(application) and manifest['commit'] == COMMIT
         and manifest['revision'] == REVISION and manifest['expected_count'] == count
         and manifest['module'] == module, 'Actual identity/source manifest differs')
    need(identity['candidate'] == {'path': str(application / 'Contents/Resources/data/NativeSolvers/ccx-force-accounting'),
         'sha256': NATIVE, 'capability': 'CCX_FORCE_ACCOUNTING_V3', 'override': False}, 'Bundled solver identity differs')
    suite = identity['selected_suite']
    need(identity['TestFemApp_count'] == 418 and len(identity['registered_native_ids'])
         == len(set(identity['registered_native_ids'])) == 12 and suite['name'] == module
         and suite['count'] == len(suite['ids']) == len(set(suite['ids'])) == count - 1
         and len(run['unittest_counts']) == 1 and run['unittest_counts'][0][0] == str(count), 'Actual suite IDs/count differ')
    text = raw[log_path].decode()
    need(len(re.findall(r'^Ran ' + str(count) + r' tests? in [0-9.]+s$', text, re.M)) == 1
         and len(re.findall(r'^OK$', text, re.M)) == 1
         and not re.search(r'^(?:FAILED|FAIL:|ERROR:|UNEXPECTED SUCCESS)', text, re.M), 'Raw unittest result differs')
    for test_id in suite['ids']:
        hits = re.findall('^' + re.escape(test_id.rsplit('.', 1)[-1]) + r' \(' + re.escape(test_id) + r'\)([^\n]*)$', text, re.M)
        need(len(hits) == 1 and 'skipped' not in hits[0], 'Missing/repeated/skipped actual selected ID')
    return identity


def qualify(plan, raw):
    review = exact_ref(raw, plan['semantic_review'])
    need(review['schema'] == 'FreeCAD-3q7-installation-final-gates-independent-review-v1'
         and review['passed'] is True and review['pending_roles'] == []
         and review['source_identity'] == {'commit': COMMIT, 'revision': REVISION, 'native_sha256': NATIVE}, 'Completed current semantic review required')
    need(REQUIRED <= review['roles'].keys(), 'Missing actual installation roles')
    values = {name: exact_ref(raw, ref) for name, ref in review['roles'].items()}
    need(all(value.get('passed') is True for value in values.values()), 'Actual required role did not pass')
    for name, value in values.items():
        value['_selected_role_path'] = review['roles'][name]['path']
    build, ctest = values['source_build'], values['ctest']
    for run in (build, ctest):
        need(run['exit_code'] == 0 and run['timed_out'] is False and run['process_reaped'] is True
             and run['owned_group_gone'] is True and run['source_and_supervisor_unchanged'] is True
             and run['app_profiles_selected_dependencies_unchanged'] is True
             and run['source_after']['git_head'] == COMMIT
             and run['build_after']['version_header']['FCRepositoryHash'] == COMMIT
             and run['build_after']['version_header']['FCRevision'] == REVISION, 'Fresh build/CTest identity differs')
    catalog = ctest['ctest']
    need(catalog['complete_catalogue_verified'] is True and catalog['failed'] == 0
         and catalog['executed_passing'] + catalog['skipped'] + catalog['disabled'] == catalog['catalogue'], 'Actual complete CTest catalogue differs')
    payload, stage, custody = (values[name] for name in ('payload_audit', 'stage_audit', 'custody_audit'))
    native_set = {row['relative'] for row in payload['native']}
    need(len(native_set) == len(payload['native']) == payload['payload_native_count'] == 61
         and payload['commit'] == stage['source_commit'] == custody['compiled_commit'] == COMMIT
         and custody['compiled_revision'] == REVISION and stage['native_payload_parity_count'] == custody['native_payload_count'] == 61
         and native_set == {row['relative'] for row in stage['native']}
         and len(stage['native']) == 61 and payload['native_complete_relative_set_sha256']
         == stage['native_complete_relative_set_sha256'] == custody['native_complete_relative_set_sha256']
         and stage['payload_audit_sha256'] == review['roles']['payload_audit']['sha256']
         and custody['stage_audit_sha256'] == review['roles']['stage_audit']['sha256']
         and custody['profiles_exact_unchanged_count'] == 3 and custody['namespace_unchanged_count'] == 11
         and custody['selected_critical_files_unchanged_count'] == 16
         and custody['baseline_and_stage_exact'] is True and custody['strict_signatures_quicklook_readonly_cachefree'] is True,
         'Complete current61-image stage/custody chain differs')
    need(values['swap']['installation_replacement'] is True and values['swap']['source_commit'] == COMMIT
         and values['swap']['compiled_revision'] == REVISION, 'Actual swap identity differs')
    for location, application in (('stage', TASK / APP.name), ('installed', APP)):
        for suffix, module, count in (('fem', 'TestFemApp', 419), ('gui', 'TestFemGui', 9),
                ('native', 'femtest.app.test_moving_port_accounting_native', 9)):
            app_gate(location + '_' + suffix, values[location + '_' + suffix], raw, count, module, application)
    app_gate('installed_capacity', values['installed_capacity'], raw, 2,
        'femtest.app.test_moving_port_capacity_native', APP)
    app_gate('installed_cold', values['installed_cold'], raw, 2, 'YzkPortableColdRestore', APP)
    physical = values['installed_physical_audit']
    need(physical['schema'] == 'FreeCAD-3q7-fresh-installed-capacity-independent-file-audit-v1'
         and physical['fresh_run'] == str(TASK / 'installed-capacity')
         and physical['application'] == str(APP)
         and physical['witness'] == str(Path(review['roles']['installed_witness']['path']).parent)
         and physical['native_binary_sha256'] == NATIVE
         and physical['supervisor']['runtime'][3] == REVISION and physical['supervisor']['runtime'][-1] == COMMIT
         and physical['acceptance']['unique_recomputed_checks'] == 3566
         and physical['acceptance']['limits_unchanged'] is True
         and physical['acceptance']['force_and_original_origin_moment'] == .01
         and physical['acceptance']['differential_response'] == .05
         and physical['acceptance']['local_generalized_force_and_couple'] == .01
         and physical['stage_132_run_claimed'] is False and physical['new_performance_measurement_claimed'] is False,
         'Actual independently recomputed installed physical audit differs')
    exact_ref(raw, physical['application_manifest'])
    witness = values['installed_witness']
    need(witness['schema'] == 'FreeCAD-native-coupled-port-coupled-native-witness-v1'
         and witness['case'] == 'capacity' and witness['rows_y'] == 11 and witness['columns_z'] == 12
         and witness['actual_binary'] == str(APP / 'Contents/Resources/data/NativeSolvers/ccx-force-accounting')
         and witness['actual_binary_sha256'] == NATIVE and witness['solver_returncode'] == 0
         and witness['only_public_native_interfaces'] is True and witness['no_deck_patches_or_mocks'] is True
         and witness['engineering_project_accessed_or_solved'] is False and witness['engineering_or_BIM_accepted'] is False
         and witness['frozen_oracle_sha256'] == FROZEN and witness['physical_check_count'] == len(witness['checks']) == 3566
         and len({row['name'] for row in witness['checks']}) == 3566 and witness['protected_inputs_unchanged'] is True,
         'Fresh complete installed132-bay witness differs')
    for row in witness['checks']:
        actual, target, scale = row['actual'], row['reference'], row['scale']
        need(len(actual) == len(target) == 3 and all(math.isfinite(v) for v in actual + target), 'Nonfinite physical vector')
        limit = .05 if row['name'].endswith(('/differential-translation', '/differential-rotation')) else .01
        error = math.dist(actual, target)
        need(row['passed'] is True and row['limit'] == limit and math.isfinite(scale) and scale > 0
             and error <= limit * scale and math.isclose(error, row['error_norm'], rel_tol=1e-12, abs_tol=1e-12)
             and math.isclose(error / scale, row['relative_error'], rel_tol=1e-12, abs_tol=1e-12), 'Installed physical arithmetic/ceiling differs')
    cold = values['installed_cold_receipt']
    need(cold['schema'] == 'FreeCAD-yzk-portable-cold-receipt-v1' and cold['status'].startswith('Stale')
         and all(cold[name] is True for name in ('no_native_solve', 'no_save', 'no_history_or_provenance_repair')), 'Literal separate cold scope differs')
    return review, values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    need(not sys.flags.optimize, 'Unoptimized interpreter required')
    plan_path = regular(args.plan, True)
    need(plan_path.parent == TASK / 'collection', 'Exact private collection plan required')
    plan_bytes = plan_path.read_bytes()
    need(sha(plan_bytes) == args.plan_sha256, 'Approved plan SHA differs')
    plan = json.loads(plan_bytes)
    need(plan['schema'] == 'FreeCAD-3q7-installation-approved-plan-v1' and plan['root_approved'] is True
         and plan['pending_roles'] == [] and plan['approved_limits']
         == {'per_file_bytes': PER_FILE, 'packet_uncompressed_bytes': PACKET}, 'Completed separately approved exact plan required')
    privacy(plan)
    capsule_ref = plan['capsule_custody']
    capsule_path = regular(capsule_ref['path'], True)
    capsule_bytes = capsule_path.read_bytes()
    need(desc(capsule_path, capsule_bytes) == capsule_ref, 'Exact capsule custody differs')
    capsule = json.loads(capsule_bytes)
    need(capsule['schema'] == 'FreeCAD-3q7-installation-exact-generic-case-capsule-v1'
         and capsule['passed'] is True and capsule['copies_exact'] is True and capsule['originals_unchanged'] is True
         and capsule['engineering_project_accessed_or_solved'] is False, 'Exact public synthetic capsule required')
    source_root, copy_root = Path(capsule['source_witness_directory']), Path(capsule['copy_directory'])
    need(source_root.is_relative_to(TASK) and copy_root.is_relative_to(TASK) and source_root != copy_root
         and not DENIED.intersection(copy_root.relative_to(TASK).parts), 'Capsule namespaces differ')
    approval = plan['synthetic_file_approvals']
    need(approval == capsule['files'] and len(approval) == len({row['path'] for row in approval})
         and CASE_REQUIRED <= {row['path'] for row in approval} <= CASE_NAMES, 'Individual exact synthetic leaf approvals differ')
    allowed = {}
    for row in approval:
        need(set(row) == {'source', 'path', 'sha256', 'bytes'} and row['source'] == str(source_root / row['path']), 'Malformed capsule leaf')
        allowed[row['source']] = {'capture': str(copy_root / row['path']), 'sha256': row['sha256'], 'bytes': row['bytes'], 'leaf': row['path']}
    rows = plan['files']
    need(rows and len(rows) == len({row['original_path'] for row in rows})
         == len({row['capture_path'] for row in rows}) == len({row['destination'] for row in rows}), 'Duplicate explicit original/capture/destination')
    need(sum(row['bytes'] for row in rows) + len(plan_bytes) <= PACKET, 'Zero-write uncompressed packet-cap refusal')
    raw, captures, originals, pending, indexed = {}, {}, {}, {}, []
    for row in rows:
        need(set(row) == {'original_path', 'capture_path', 'destination', 'sha256', 'bytes', 'kind', 'classification'}, 'Unexpected selection fields')
        original, capture = regular(row['original_path'], False), regular(row['capture_path'], True)
        if original != capture:
            need(str(original) in allowed and allowed[str(original)]['capture'] == str(capture)
                 and allowed[str(original)]['sha256'] == row['sha256'] and allowed[str(original)]['bytes'] == row['bytes'], 'Only individually approved exact generic capsule dual-path capture is allowed')
        else:
            regular(original, True)
        data = capsule_bytes if capture == capsule_path else capture.read_bytes()
        need(desc(original, data) == {'path': str(original), 'sha256': row['sha256'], 'bytes': row['bytes']}
             and original.read_bytes() == data and row['kind'] in KINDS and row['classification'], 'Actual original/copy bytes differ')
        need(data[:4] not in MAGIC and not data.startswith(b'MZ'), 'Runtime binary excluded')
        if original.suffix.lower() == '.fcstd':
            need(str(original) in allowed and row['kind'] == 'synthetic-fixture' and data.startswith(b'PK\x03\x04'), 'Only exact approved synthetic FCStd allowed')
        else:
            text = data.decode('utf-8')
            need(b'\x00' not in data and not re.search(r'(?im)^(?:OPENAI_API_KEY|GITHUB_TOKEN|GH_TOKEN|AWS_SECRET_ACCESS_KEY|PASSWORD|ACCESS_TOKEN|REFRESH_TOKEN)\s*=\s*\S+', text), 'Environment/credential dump excluded')
            if original.suffix.lower() == '.frd':
                need(str(original) in allowed, 'Only exact approved synthetic FRD allowed')
            if original.suffix == '.json':
                privacy(json.loads(data))
            if original.suffix == '.py':
                ast.parse(data, filename=str(original))
        target = Path(row['destination'])
        need(target.parts and not target.is_absolute() and '..' not in target.parts and '\\' not in row['destination']
             and target.as_posix() == row['destination'] and not DENIED.intersection(target.parts)
             and target.name not in {'index.json', 'approved-plan.json'}, 'Unsafe destination')
        encoding = 'gzip' if len(data) >= 65536 else 'identity'
        stored = gzip.compress(data, compresslevel=9, mtime=0) if encoding == 'gzip' else data
        name = row['destination'] + ('.gz' if encoding == 'gzip' else '')
        need(name not in pending, 'Transformed destination collision')
        pending[name], raw[str(original)], captures[str(capture)] = stored, data, data
        originals[str(original)] = data
        indexed.append({'file': name, 'kind': row['kind'], 'classification': row['classification'],
            'original_path': str(original), 'capture_path': str(capture), 'original_sha256': sha(data), 'original_bytes': len(data),
            'stored_sha256': sha(stored), 'stored_bytes': len(stored), 'encoding': encoding,
            'decoded_sha256': sha(data), 'decoded_bytes': len(data), 'transformation': 'exact bytes; literal provenance unchanged'})
    need(set(allowed) <= raw.keys(), 'Every individually approved capsule leaf must be retained')
    need(capsule_ref['path'] in raw and raw[capsule_ref['path']] == capsule_bytes, 'Exact capsule custody must be retained')
    review, values = qualify(plan, raw)
    witness = values['installed_witness']
    capacity = values['installed_capacity']
    capacity_log = raw[str(Path(capacity['_selected_role_path']).parent / 'run.log')].decode()
    prefixes = re.findall(r'^Native capacity evidence: ([^\r\n]+)$', capacity_log, re.M)
    need(len(prefixes) == 1, 'One actual fresh installed witness prefix required')
    prefix = Path(prefixes[0])
    need(prefix.is_absolute() and prefix.is_relative_to(TASK / 'installed-capacity/freecad_user_temp')
         and prefix.name.startswith('freecad-moving-port-capacity-native-')
         and source_root == prefix / 'witness'
         and capacity['capacity_witness']['directory'] == str(source_root)
         and capacity['capacity_witness']['witness_receipt_sha256']
         == review['roles']['installed_witness']['sha256'], 'Capsule is not this actual installed execution witness')
    witness_path = str(source_root / 'witness-receipt.json')
    need(review['roles']['installed_witness'] == desc(witness_path, raw[witness_path])
         and capsule['source_run_execution'] == review['roles']['installed_capacity'], 'Witness/capsule belong to another actual installed execution')
    for source, proof in allowed.items():
        if proof['leaf'] != 'witness-receipt.json':
            need(witness['retained_files'][proof['leaf']] == {'sha256': proof['sha256'], 'bytes': proof['bytes']}, 'Capsule leaf is not actual witness-bound output')
    omitted = capsule['omitted_witness_files']
    omitted_names = {row['path'] for row in omitted}
    omitted_expected = {'mesh/CoupledCells_Geometry.brep', 'mesh/CoupledCells_Mesh.vtk',
        'mesh/shape2mesh.geo', 'native/Mesh.12d', 'native/Mesh.cvg', 'native/Mesh.sta', 'native/spooles.out'}
    need(len(omitted) == len(omitted_names) == 7 and omitted_names == omitted_expected
         and omitted_names.isdisjoint({row['path'] for row in approval})
         and set(witness['retained_files']) == ({row['path'] for row in approval} - {'witness-receipt.json'}) | omitted_names,
         'Selected/omitted witness coverage differs; whole-witness retention is not claimed')
    omitted_refs = {}
    for row in omitted:
        need(set(row) == {'path', 'sha256', 'bytes', 'scope'} and row['scope'], 'Explicit accurate omission scope required')
        need(witness['retained_files'][row['path']] == {'sha256': row['sha256'], 'bytes': row['bytes']}, 'Omitted witness descriptor differs')
        path = regular(source_root / row['path'], False)
        with path.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        need(actual == row['sha256'] and path.stat().st_size == row['bytes'], 'Omitted original changed')
        omitted_refs[str(path)] = row
    cold_path = str(source_root / 'cold-case.json')
    cold = json.loads(raw[cold_path])
    cold_run_manifest = json.loads(raw[str(Path(values['installed_cold']['_selected_role_path']).parent / 'manifest.json')])
    need(cold_run_manifest['cold_manifest'] == cold_path
         and cold_run_manifest['cold_manifest_sha256'] == sha(raw[cold_path]), 'Installed cold execution uses another manifest')
    need(cold['schema'] == 'FreeCAD-native-coupled-port-coupled-cold-case-v1' and cold['frozen_oracle_sha256'] == FROZEN
         and cold['document'] == str(source_root / 'coupled-native-current.FCStd')
         and cold['document_sha256'] == sha(raw[cold['document']])
         and values['installed_cold_receipt']['manifest'] == cold_path
         and values['installed_cold_receipt']['manifest_sha256'] == sha(raw[cold_path])
         and witness['before_export_document_sha256'] == sha(raw[str(source_root / 'coupled-before-export.FCStd')]), 'Literal cold saved-file bindings differ')
    leaves = {'deck': 'Mesh.inp', 'request': 'Mesh.accounting', 'native_output': 'Mesh.accounting.out', 'dat': 'Mesh.dat', 'frd': 'Mesh.frd'}
    need(set(cold['source_files']) == leaves.keys(), 'Exactly five literal native source files required')
    for name, leaf in leaves.items():
        path = str(source_root / 'native' / leaf)
        need(cold['source_files'][name]['path'] == path and cold['source_files'][name]['sha256'] == sha(raw[path]), 'Literal native source path/SHA changed')
    counts = {'supports': 1, 'bodies': 264, 'ports': 264, 'angles': 792, 'springs': 792}
    data = json.loads(raw[str(source_root / 'native-accounting-data.json')])
    need(data['schema'] == 'CCX_FORCE_ACCOUNTING_V3' and data['binary_sha256'] == NATIVE
         and data['capacity_applied'] == {'budget': 2113, 'counts': counts, 'total': 2113}
         and data['capacity']['required'] == counts and data['capacity']['total'] == 2113
         and data['capacity']['supported']['total_records'] == 2113, 'Actual installed2113 capacity echo differs')
    pending['approved-plan.json'] = plan_bytes
    indexed.append({'file': 'approved-plan.json', 'kind': 'json', 'classification': 'Exact root-approved final explicit file plan',
        'original_path': str(plan_path), 'capture_path': str(plan_path), 'original_sha256': sha(plan_bytes), 'original_bytes': len(plan_bytes),
        'stored_sha256': sha(plan_bytes), 'stored_bytes': len(plan_bytes), 'encoding': 'identity', 'decoded_sha256': sha(plan_bytes), 'decoded_bytes': len(plan_bytes), 'transformation': 'exact bytes'})
    index = {'schema': 'FreeCAD-3q7-installation-evidence-index-v1', 'files': sorted(indexed, key=lambda row: row['file']),
        'indexed_files': len(indexed), 'semantic_review': plan['semantic_review'], 'capsule_custody': capsule_ref,
        'omitted_witness_files': [{'original_path': path, **row} for path, row in sorted(omitted_refs.items())],
        'whole_witness_retention_claimed': False}
    summary = {'schema': 'FreeCAD-3q7-installation-validation-v1', 'passed': True,
        'source_identity': review['source_identity'], 'application': str(APP), 'rollback_backup': str(BACKUP),
        'actual_gates': {'complete_payload_native_images': 61, 'stage_fem_gui_moving_totals': [419, 9, 9],
            'installed_fem_gui_moving_totals': [419, 9, 9], 'installed_physical_checks': 3566,
            'installed_capacity_test_total': 2, 'separate_installed_cold_test_total': 2, 'ctest': values['ctest']['ctest']},
        'synthetic_case_retention': {'selected_files': len(allowed), 'hash_only_omitted_files': len(omitted_refs),
            'whole_witness_retention_claimed': False},
        'evidence': {'directory': str(OUT.relative_to(REPO)), 'index_sha256': sha(encode(index)),
            'indexed_files': len(indexed), 'plan_sha256': sha(plan_bytes), 'semantic_review': plan['semantic_review']},
        'independent_publication_audit_required': True, 'independent_publication_audit_completed_by_collector': False,
        'scope': 'Host-local source/build/install software qualification only. Matching repository Pixi dependencies remain required; not self-contained or notarized. No new timing measurement, engineering/BIM/Oomakhi/R49/R51 acceptance, saved provenance repair, or stage132-bay physical run is claimed.'}
    privacy(index)
    privacy(summary)
    packet_bytes = sum(row['original_bytes'] for row in indexed) + len(encode(index)) + len(encode(summary))
    need(packet_bytes <= PACKET, 'Zero-write index/summary-inclusive packet cap refusal')
    for name in pending:
        need(all(parent.as_posix() not in set(pending) | {'index.json'} for parent in Path(name).parents if parent.parts), 'File/directory prefix collision')

    def fence():
        need(plan_path.read_bytes() == plan_bytes, 'Approved plan changed')
        for path, wanted in originals.items():
            need(regular(path, False).read_bytes() == wanted, 'Literal original changed')
        for path, wanted in captures.items():
            need(regular(path, True).read_bytes() == wanted, 'Captured copy changed')
        for path, wanted in omitted_refs.items():
            item = regular(path, False)
            with item.open('rb') as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            need(actual == wanted['sha256'] and item.stat().st_size == wanted['bytes'], 'Omitted hash-only original changed')

    fence()
    need(OUT.parent.is_dir() and not OUT.parent.is_symlink() and not OUT.exists() and not OUT.is_symlink()
         and not SUMMARY.exists() and not SUMMARY.is_symlink(), 'Publication destinations must both be new')
    if not args.check_only:
        OUT.mkdir()
        for name, value in sorted(pending.items()):
            target = OUT / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(value)
        with (OUT / 'index.json').open('xb') as stream:
            stream.write(encode(index))
        with SUMMARY.open('xb') as stream:
            stream.write(encode(summary))
        need({str(path.relative_to(OUT)) for path in OUT.rglob('*') if path.is_file()} == set(pending) | {'index.json'}, 'Published coverage differs')
        for row in indexed:
            stored = (OUT / row['file']).read_bytes()
            need(sha(stored) == row['stored_sha256'] and len(stored) == row['stored_bytes'], 'Published stored bytes differ')
            decoded = gzip.decompress(stored) if row['encoding'] == 'gzip' else stored
            need(sha(decoded) == row['decoded_sha256'] and len(decoded) == row['decoded_bytes'], 'Published decoded bytes differ')
        need((OUT / 'index.json').read_bytes() == encode(index) and SUMMARY.read_bytes() == encode(summary), 'Index/summary differ')
        fence()
    print(json.dumps({'passed': True, 'check_only': args.check_only, 'writes': 0 if args.check_only else len(indexed) + 2,
        'indexed_files': len(indexed), 'uncompressed_packet_bytes': packet_bytes, 'index_sha256': sha(encode(index)),
        'summary_sha256': sha(encode(summary)), 'independent_publication_audit_required': True}, sort_keys=True))


if __name__ == '__main__':
    main()
