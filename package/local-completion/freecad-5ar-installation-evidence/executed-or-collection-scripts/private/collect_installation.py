"""Collect already-executed FreeCAD-5ar installation evidence; never run QA.

Root must read this file before executing it. Only the two new repository
destinations below are written. Original receipts remain private and unchanged.
Inventory-bearing receipts are explicitly labelled excerpts, not exact copies.
Large exact-copy text is deterministically gzipped without changing its bytes.
No app, profile, solver, engineering model or saved observation is modified.
"""
import datetime
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
DEST = REPO / 'package/local-completion/freecad-5ar-installation-evidence'
FINAL = REPO / 'package/local-completion/freecad-5ar-installation.json'
APP = Path('/Applications/FreeCAD-27.1.0.app')
STAGE = ROOT / APP.name  # Historical location, intentionally not rebound.
BACKUP = Path('/Users/zukomgwili/Applications/FreeCAD Backups/FreeCAD-27.1.0-before-5ar-f0c43f0a93.app')
COMMIT = 'b6b9e216c4ee2ca1bbc73db70076a6c99b2b1ab5'
REVISION = '49261 +218 (Git)'
NATIVE_SHA = '31fc5615d1753ccbb7b53d5a47175ac1122f18d5cb13060cec272462bb0bd03d'
NATIVE_REL = 'Contents/Resources/data/NativeSolvers/ccx-force-accounting'
GZIP_THRESHOLD = 64 * 1024
V2_CASES = (
    'tie-tet4', 'tie-tet10', 'equation-unit-tet4',
    'equation-negative-scale-reverse-tet4', 'equation-quarter-scale-tet10',
    'equation-chain-reverse-tet4', 'tie-dependent-point-tet4',
    'equation-chain-dependent-point-tet10',
    'reject-shared-cut-mpc-tet4', 'reject-body-spc-tet4',
)
V1_REJECTIONS = (
    'nlgeom', 'missing-cut-node', 'duplicate-support',
    'oversized-integer', 'cut-point-load', 'cut-mpc',
)
PRIVATE_SCRIPTS = (
    'AppNativeIdentity.py', 'NativeAppColdReopen.py', 'SourceNativeIdentity.py',
    'audit_payload_stage.py', 'critical_pins.py', 'harness_config.py',
    'process_control.py', 'run_app_cold.py', 'run_app_tests.py',
    'run_build_gate.py', 'run_source_tests.py', 'run_step.py',
    'run_step.before-swap-hardening.py', 'stage_install.py', 'final_audit.py',
    'collect_installation.py',
)
SOURCE_PINS = (
    'package/calculix/force-accounting/forceaccounting.c',
    'package/calculix/force-accounting/hooks.patch',
    'package/calculix/force-accounting/contract.json',
    'package/calculix/force-accounting/COPYING',
    'src/Mod/Fem/femtools/force_accounting.py',
    'src/Mod/Fem/femresult/contact_observation.py',
    'src/Mod/Fem/femobjects/result_contact_observation.py',
    'src/Mod/Fem/femcommands/commands.py',
    'src/Mod/Fem/femtest/app/test_tie_accounting_native.py',
    'src/Mod/Fem/femtest/gui/test_contact_observation.py',
    'src/Mod/Fem/TestFemApp.py', 'src/Mod/Fem/TestFemGui.py',
    'pixi.toml', 'pixi.lock',
)
# These keys contain whole file inventories, not needed in the committed copy.
INVENTORY_FIELDS = {
    'app_before', 'app_after', 'critical_before', 'critical_after',
    'app_inventory', 'application_inventory', 'profile_inventory',
    'profile_inventories', 'profiles', 'inventory',
    'prior_ctest_logs', 'ctest_logs_after', 'native',
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def read_bytes(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), f'Not a regular file: {path}')
    return path.read_bytes()


def descriptor(path):
    data = read_bytes(path)
    return {'path': str(path), 'sha256': sha_bytes(data), 'bytes': len(data)}


def load(path):
    return json.loads(read_bytes(path))


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()


def source_record(path, expected=None):
    row = descriptor(path)
    if expected is not None:
        require(row['sha256'] == expected, f'Changed recorded input: {path}')
    return row


def passed_receipt(relative):
    path = ROOT / relative
    obj = load(path)
    require(obj.get('passed') is True, f'Receipt did not pass: {path}')
    if 'timed_out' in obj:
        require(obj['timed_out'] is False, f'Timed-out receipt: {path}')
    if 'exit_code' in obj:
        require(obj['exit_code'] == 0, f'Nonzero receipt: {path}')
    for field in ('owned_group_gone', 'process_reaped'):
        if field in obj:
            require(obj[field] is True, f'Incomplete child cleanup: {path}: {field}')
    return obj


def bind_recorded_file(receipt, field, path):
    require(receipt[field] == descriptor(path)['sha256'], f'Changed receipt-bound {path}')


def unit_count(receipt, wanted, name):
    result = receipt['unittest']
    require(result['count'] == wanted and result['skipped_lines'] == [],
            f'Wrong executed or skipped unittest count: {name}')
    if 'outcome' in result:
        require(result['outcome'] == 'OK', f'Unittest did not pass: {name}')


def validate_app_run(location, application, mode, count):
    directory = ROOT / f'{location}-{mode}'
    receipt = passed_receipt(f'{location}-{mode}/execution.json')
    identity = load(directory / 'identity.json')
    require(receipt['application'] == str(application), 'Run rebound to another app')
    require(receipt['runtime'][3] == REVISION and receipt['runtime'][7] == COMMIT,
            'Executed app identity differs from compiled installation')
    require(receipt['application_unchanged'] and receipt['source_and_harness_unchanged'],
            f'Run custody changed: {directory}')
    require(receipt['rebound_or_reused_stage_outputs'] is False, 'Reused/rebound stage result')
    unit_count(receipt, count + 1, str(directory))
    bind_recorded_file(receipt, 'log_sha256', directory / 'run.log')
    bind_recorded_file(receipt, 'identity_sha256', directory / 'identity.json')
    require(identity['passed'] and identity['runtime'] == receipt['runtime'], 'Identity receipt mismatch')
    require(identity['application'] == str(application), 'Identity app path mismatch')
    require(identity['source_or_build_import_override'] is False, 'Source/build fallback present')
    require(identity['bundled_solver']['sha256'] == NATIVE_SHA and
            identity['bundled_solver']['capability'] == 'CCX_FORCE_ACCOUNTING_V2' and
            identity['bundled_solver']['preference_or_candidate_override'] is False,
            'Incorrect bundled native solver capability/custody')
    require(identity['bundled_solver']['path'] == str(application / NATIVE_REL),
            'Bundled native solver is not app-local')
    source_record(identity['version_header']['path'], identity['version_header']['sha256'])
    if mode == 'fem':
        require(identity['TestFemApp_count'] == count, 'Wrong public FEM catalogue')
        ids = identity['registered_native_tie_ids']
        require(len(ids) == 4 and len(set(ids)) == 4, 'Four native Tie tests are not registered')
        log = read_bytes(directory / 'run.log').decode()
        for test_id in ids:
            require(log.count('(' + test_id + ')') == 1,
                    f'Native Tie test did not execute exactly once: {test_id}')
        require(len(receipt['tie_cold_cases']) == 1, 'Missing fresh native cold case')
    else:
        require(identity['TestFemGui_count'] == count, 'Wrong public GUI catalogue')
    return receipt


def validate_cold(location, application, fem):
    directory = ROOT / f'{location}-cold'
    receipt = passed_receipt(f'{location}-cold/execution.json')
    unit_count(receipt, 2, str(directory))
    require(receipt['application'] == str(application), 'Cold process used another app')
    require(receipt['runtime'][3] == REVISION and receipt['runtime'][7] == COMMIT,
            'Cold process has incorrect compiled identity')
    require(receipt['all_protected_inputs_unchanged'] and
            receipt['writer_solve_save_or_rebinding_performed'] is False, 'Cold probe wrote or rebound inputs')
    for field, filename in (('log_sha256', 'run.log'), ('identity_sha256', 'identity.json'),
                            ('probe_sha256', 'probe.json')):
        bind_recorded_file(receipt, field, directory / filename)
    case = fem['tie_cold_cases'][0]
    require(receipt['manifest'] == case['path'] and receipt['manifest_sha256'] == case['sha256'],
            'Cold witness is not bound to this location fresh FEM case')
    source_record(case['path'], case['sha256'])
    source_record(case['document'], case['document_sha256'])
    source_record(case['frd'], case['frd_sha256'])
    require(case['binary_sha256'] == NATIVE_SHA and case['binary'] == str(application / NATIVE_REL),
            'Cold manifest binary custody differs from original app location')
    probe = load(directory / 'probe.json')
    require(probe == receipt['probe'] and probe['passed'] and probe['protected_inputs_unchanged'],
            'Cold probe receipt mismatch')
    require(probe['historical_until_explicit_refresh'] and probe['accounting_not_promoted_to_Current'],
            'Cold witness did not retain historical/stale custody')
    for field in ('Oomakhi_opened_or_solved', 'writer_run', 'solver_solve_run',
                  'saved_document_written', 'status_hash_or_fingerprint_repaired'):
        require(probe[field] is False, f'Cold witness violated scope: {field}')
    return receipt, case


def validate_v2(location, application):
    directory = ROOT / f'{location}-v2'
    summary = load(directory / 'summary.json')
    require(summary['all_selected_passed'] and tuple(summary['selected_cases']) == V2_CASES,
            'Incomplete V2 analytic/rejection corpus')
    require(summary['candidate'] == str(application / NATIVE_REL) and
            summary['candidate_sha256'] == NATIVE_SHA, 'V2 native location/custody mismatch')
    bind_recorded_file(summary, 'manifest_sha256', directory / 'manifest.json')
    reports = summary['reports']
    require([report['case'] for report in reports] == list(V2_CASES), 'V2 report order/coverage differs')
    checks = 0
    for report in reports:
        case = directory / report['case']
        require(load(case / 'execution.json') == report, 'V2 summary differs from original case receipt')
        require(report['passed'] and report['protected_inputs_unchanged'] and
                report['child_reaped'] and report['process_group_gone'] and not report['timed_out'],
                f'V2 case did not complete safely: {case}')
        require(report['candidate_sha256'] == NATIVE_SHA and
                report['candidate'] == str(application / NATIVE_REL), 'V2 per-case candidate mismatch')
        bind_recorded_file(report, 'solver_log_sha256', case / 'solver.log')
        if report['case'].startswith('reject-'):
            require(report['returncode'] == 201 and report.get('expected_domain_refusal'),
                    'Expected V2 domain rejection was not observed')
        else:
            require(report['returncode'] == 0 and len(report['checks']) == 18, 'Incomplete V2 positive checks')
            for check in report['checks']:
                require(check['passed'] and check['limit'] == 0.01 and
                        math.isfinite(check['relative_error']) and check['relative_error'] <= 0.01,
                        'V2 fixed analytic tolerance failed')
            checks += len(report['checks'])
    require(checks == 144 and summary['engineering_or_BIM_accepted'] is False,
            'Incorrect analytic scope/check count')
    return summary


def validate_v1(location, application):
    path = ROOT / f'{location}-v1/qualification.json'
    summary = load(path)
    require(summary['passed'] and summary['schema'] == 'CCX_FORCE_ACCOUNTING_V1', 'Legacy V1 failed')
    require(summary['binary'] == str(application / NATIVE_REL) and summary['binary_sha256'] == NATIVE_SHA,
            'V1 native location/custody mismatch')
    cases = summary['analytic_cases']
    require(len(cases) == 48 and len({case['case'] for case in cases}) == 48, 'Incomplete V1 cases')
    for case in cases:
        require(re.fullmatch(r't[124]-q[01]-r[01]-s[01]/(slave|master)-upper', case['case']),
                'Unexpected synthetic V1 case path')
        require(set(case['relative_force_moment_errors']) == {'SUPPORT/Support', 'CUT/Lower', 'CUT/Upper'},
                'Legacy V1 result coverage changed')
        for pair in case['relative_force_moment_errors'].values():
            require(len(pair) == 2 and all(math.isfinite(value) and 0 <= value <= 0.01 for value in pair),
                    'Legacy fixed one-percent force/moment tolerance failed')
    require(tuple(case['case'] for case in summary['rejections']) == V1_REJECTIONS and
            all(case['exit_code'] == 201 and case['diagnostic'].startswith('*ERROR CCX force accounting V1:')
                for case in summary['rejections']), 'Legacy refusal corpus failed')
    require(summary['original_project_replayed'] is False and summary['design_accepted'] is False,
            'Legacy receipt overclaims engineering scope')
    return summary


def validate_coordinate(location, application):
    directory = ROOT / f'{location}-coordinate'
    receipt = load(directory / 'execution.json')
    require(receipt['candidate'] == str(application / NATIVE_REL) and receipt['candidate_sha256'] == NATIVE_SHA,
            'Coordinate native location/custody mismatch')
    require(receipt['strict_coordinate_contract_passed'] and receipt['protected_inputs_unchanged'] and
            receipt['child_reaped'] and receipt['process_group_gone'] and not receipt['timed_out'] and
            receipt['returncode'] == 201 and receipt['native_invocations'] == 1 and
            receipt['engineering_or_BIM_accepted'] is False,
            'Native coordinate-change refusal was not safely observed')
    bind_recorded_file(receipt, 'manifest_sha256', directory / 'manifest.json')
    bind_recorded_file(receipt, 'solver.log_sha256', directory / 'solver.log')
    return receipt


def main():
    require(ROOT == Path('/private/tmp/freecad-5ar-install-qjCS3M'), 'Wrong private installation root')
    require(not DEST.exists() and not DEST.is_symlink() and not FINAL.exists() and not FINAL.is_symlink(),
            'Refusing to overwrite installation evidence or summary')
    require(DEST.parent.is_dir() and not DEST.parent.is_symlink(), 'Invalid repository evidence parent')
    # A passed root final audit is a prerequisite, never generated here.
    audit = passed_receipt('final-audit.json')
    for aliases, expected in (
        (('compiled_commit', 'source_commit'), COMMIT),
        (('compiled_revision',), REVISION),
        (('installed_application', 'application'), str(APP)),
        (('rollback_backup', 'backup'), str(BACKUP)),
        (('signed_bundled_solver_unchanged_sha256', 'native_V2_sha256'), NATIVE_SHA),
    ):
        values = [audit[key] for key in aliases if key in audit]
        require(values and all(value == expected for value in values), f'Final audit identity mismatch: {aliases}')
    require(APP.is_dir() and not APP.is_symlink() and BACKUP.is_dir() and not BACKUP.is_symlink(),
            'Installed application or rollback backup absent')
    source_record(APP / NATIVE_REL, NATIVE_SHA)
    version = read_bytes(REPO / 'build/release/src/Build/Version.h').decode()
    values = dict(re.findall(r'^#define\s+(\w+)\s+"([^"]*)"', version, re.M))
    require(values.get('FCRepositoryHash') == COMMIT and values.get('FCRevision') == REVISION,
            'Current build header differs')
    build = passed_receipt('build-latest/execution.json')
    ctest = passed_receipt('ctest-latest/execution.json')
    require(build['source_and_supervisor_unchanged'] and ctest['source_and_supervisor_unchanged'],
            'Build/CTest source custody changed')
    for key, value in {'catalogue': 2274, 'enabled': 2266, 'executed_passing': 2264,
                       'skipped': 2, 'disabled': 8, 'failed': 0, 'complete_catalogue_verified': True}.items():
        require(ctest['ctest'][key] == value, f'Unexpected CTest count: {key}')
    for directory, receipt in (('build-latest', build), ('ctest-latest', ctest)):
        bind_recorded_file(receipt, 'log_sha256', ROOT / directory / 'run.log')
    for filename in ('independent-payload-audit.json', 'independent-stage-audit.json',
                     'independent-stage-custody.json', 'independent-installed-audit.json'):
        passed_receipt(filename)
    independent = load(ROOT / 'independent-installed-audit.json')
    require(independent['findings'] == [] and independent['compiled_commit'] == COMMIT and
            independent['compiled_revision'] == REVISION and
            independent['application'] == str(APP) and independent['rollback_backup'] == str(BACKUP) and
            independent['native_binary_sha256'] == NATIVE_SHA, 'Independent installed audit identity/findings differ')
    for step in ('payload', 'stage', 'audit-payload', 'audit-stage', 'audit-custody', 'swap'):
        passed_receipt(f'step-{step}.json')
    swap = load(ROOT / 'step-swap.json')
    require(swap['compiled_commit'] == COMMIT and swap['compiled_revision'] == REVISION and
            swap['critical_pins_unchanged'] and swap['owned_processes_remaining'] == {},
            'Application swap identity/custody incomplete')
    local = read_bytes(ROOT / 'LOCAL-INSTALL.txt')
    require(local == read_bytes(APP / 'Contents/Resources/LOCAL-INSTALL.txt'), 'Installed LOCAL note differs')

    locations = {}
    cold_cases = {}
    for location, application in (('stage', STAGE), ('installed', APP)):
        fem = validate_app_run(location, application, 'fem', 390)
        gui = validate_app_run(location, application, 'gui', 8)
        cold, case = validate_cold(location, application, fem)
        validate_v2(location, application)
        validate_v1(location, application)
        coordinate = validate_coordinate(location, application)
        cold_cases[location] = case
        locations[location] = {
            'application_at_execution': str(application),
            'fresh_outputs_generated_in_this_location': True,
            'public_FEM_tests': 390, 'FEM_identity_tests': 1,
            'public_GUI_tests': 8, 'GUI_identity_tests': 1,
            'separate_process_cold_tests_including_identity': 2,
            'skipped_tests': 0, 'native_Tie_tests_registered_and_executed': 4,
            'V2_positive_cases': 8, 'V2_analytic_force_moment_checks': 144,
            'V2_explicit_domain_rejections': 2,
            'legacy_V1_analytic_cases': 48, 'legacy_V1_explicit_domain_rejections': 6,
            'force_moment_relative_limit': 0.01,
            'native_reference_coordinate_change_explicitly_refused': coordinate['strict_coordinate_contract_passed'],
            'cold_manifest': case,
            'receipt_sha256': {name: descriptor(ROOT / f'{location}-{name}/execution.json')['sha256']
                              for name in ('fem', 'gui', 'cold', 'coordinate')},
        }

    # Build an in-memory publication plan only after all required gates passed.
    # Every copied byte stream has both original and stored SHA/size recorded.
    planned = {}
    index = []
    private_only = []

    def add(path, relative, excerpt=False):
        path = Path(path)
        original = read_bytes(path)
        raw = original
        transformation = 'exact bytes'
        omitted = []
        if excerpt:
            obj = json.loads(original)
            omitted = sorted(INVENTORY_FIELDS.intersection(obj))
            retained = {key: value for key, value in obj.items() if key not in INVENTORY_FIELDS}
            raw = json_bytes({
                'schema': 'FreeCAD-5ar-curated-receipt-excerpt-v1',
                'original_private_receipt': {'path': str(path), 'sha256': sha_bytes(original), 'bytes': len(original)},
                'transformation': 'Inventory bodies omitted; retained facts are copied, not a new independent audit.',
                'omitted_top_level_fields': omitted, 'facts': retained,
            })
            transformation = 'DERIVED curated JSON excerpt; not byte-identical to original receipt'
        relative = Path(relative)
        require(not relative.is_absolute() and '..' not in relative.parts, 'Unsafe output relative path')
        uncompressed = raw
        compressed = len(raw) >= GZIP_THRESHOLD
        if compressed:
            raw = gzip.compress(raw, compresslevel=9, mtime=0)
            relative = Path(str(relative) + '.gz')
            require(gzip.decompress(raw) == uncompressed, 'Gzip byte round-trip failed')
        key = str(relative)
        require(key not in planned, f'Duplicate publication path: {key}')
        planned[key] = raw
        index.append({
            'file': key, 'stored_sha256': sha_bytes(raw), 'stored_bytes': len(raw),
            'encoding': 'gzip' if compressed else 'identity',
            'uncompressed_sha256': sha_bytes(uncompressed), 'uncompressed_bytes': len(uncompressed),
            'original_private_or_repository_path': str(path),
            'original_sha256': sha_bytes(original), 'original_bytes': len(original),
            'transformation': transformation, 'omitted_top_level_fields': omitted,
        })

    def private_reference(path, reason, expected=None):
        row = source_record(path, expected)
        row['not_published_reason'] = reason
        private_only.append(row)
        return row

    for name in PRIVATE_SCRIPTS:
        add(ROOT / name, Path('executed-or-collection-scripts/private') / name)
    for name in ('FreeCADPreviewExtension.appex.plist', 'FreeCADThumbnailExtension.appex.plist', 'LOCAL-INSTALL.txt'):
        add(ROOT / name, Path('installation') / name)
    for name in ('baseline-inventory.json', 'stage-inventory.json', 'profile-inventories.json',
                 'critical-before-DESTDIR.json'):
        private_reference(ROOT / name, 'Full application/profile/dependency inventory intentionally remains private.')
    for directory in ('build-latest', 'ctest-latest'):
        add(ROOT / directory / 'execution.json', Path('receipts') / directory / 'execution.json', excerpt=True)
        add(ROOT / directory / 'run.log', Path('logs') / directory / 'run.log')
    for name in ('LastTest.log', 'LastTestsDisabled.log'):
        add(ROOT / 'ctest-latest' / name, Path('logs/ctest-latest') / name)
    for name in ('independent-payload-audit.json', 'independent-stage-audit.json',
                 'independent-stage-custody.json'):
        add(ROOT / name, Path('receipts') / name, excerpt=True)
    # These two final reports have only counts/hashes and findings, not inventory
    # bodies. Preserve their exact original bytes, with a fail-closed key check.
    for name in ('final-audit.json', 'independent-installed-audit.json'):
        require(not INVENTORY_FIELDS.intersection(load(ROOT / name)),
                f'Unexpected inventory body in final audit: {name}')
        add(ROOT / name, Path('receipts') / name)
    for step in ('payload', 'stage', 'audit-payload', 'audit-stage', 'audit-custody', 'swap'):
        add(ROOT / f'step-{step}.json', Path('receipts/steps') / f'{step}.json')
        add(ROOT / f'step-{step}.log', Path('logs/steps') / f'{step}.log')

    executed_repository_scripts = {}
    for location in ('stage', 'installed'):
        for mode in ('fem', 'gui', 'cold'):
            directory = ROOT / f'{location}-{mode}'
            add(directory / 'execution.json', Path('receipts') / directory.name / 'execution.json', excerpt=True)
            add(directory / 'identity.json', Path('receipts') / directory.name / 'identity.json')
            add(directory / 'run.log', Path('logs') / directory.name / 'run.log')
        add(ROOT / f'{location}-cold/probe.json', Path('receipts') / f'{location}-cold/probe.json')
        case = cold_cases[location]
        add(case['path'], Path('cold-cases') / location / 'tie-cold-case.json')
        for path_key, hash_key in (('document', 'document_sha256'), ('frd', 'frd_sha256')):
            private_reference(case[path_key], 'Small synthetic native fixture retained privately; exact original manifest is published unchanged.',
                              case[hash_key])

        v2 = ROOT / f'{location}-v2'
        for name in ('manifest.json', 'summary.json'):
            add(v2 / name, Path('receipts') / v2.name / name)
        for case_name in V2_CASES:
            for name in ('execution.json', 'solver.log'):
                add(v2 / case_name / name, Path('native') / v2.name / case_name / name)
        v1 = ROOT / f'{location}-v1'
        legacy = load(v1 / 'qualification.json')
        add(v1 / 'qualification.json', Path('receipts') / v1.name / 'qualification.json')
        logs = sorted(path for path in v1.glob('*.log')
                      if re.fullmatch(r't[124]-q[01]-r[01]-s[01]\.log', path.name))
        require(len(logs) == 24, 'Legacy top-level execution logs incomplete')
        for path in logs:
            add(path, Path('native') / v1.name / path.name)
        for row in legacy['analytic_cases']:
            for name in ('qualification.json', 'solver.log'):
                add(v1 / row['case'] / name, Path('native') / v1.name / row['case'] / name)
        for rejection in V1_REJECTIONS:
            add(v1 / rejection / 'solver.log', Path('native') / v1.name / rejection / 'solver.log')

        coordinate = ROOT / f'{location}-coordinate'
        for name in ('manifest.json', 'execution.json', 'original-deck-coordinates.json', 'solver.log'):
            add(coordinate / name, Path('native') / coordinate.name / name)
        for manifest_path in (v2 / 'manifest.json', coordinate / 'manifest.json'):
            manifest = load(manifest_path)
            for key in ('script', 'generator', 'process_control', 'supervisor'):
                if key in manifest:
                    record = source_record(manifest[key], manifest[key + '_sha256'])
                    previous = executed_repository_scripts.setdefault(record['path'], record)
                    require(previous == record, 'Executed repository script changed between manifests')
    legacy_script = REPO / 'package/local-completion/Qualify9ztNative.py'
    executed_repository_scripts[str(legacy_script)] = descriptor(legacy_script)
    for path in sorted(executed_repository_scripts):
        relative = Path(path).relative_to(REPO)
        add(path, Path('executed-or-collection-scripts/repository') / relative)

    pins = {path: descriptor(REPO / path) for path in SOURCE_PINS}
    header = descriptor(REPO / 'build/release/src/Build/Version.h')
    # Source pins are observations of real current files, not a compiler receipt.
    # App/native/source parity itself is established by the passed audit and QA.
    note_sha = descriptor(ROOT / 'LOCAL-INSTALL.txt')['sha256']
    stat = APP.stat()
    finder = {
        'scope': 'application bundle directory modification time shown by Finder; not a substitute for compiled identity',
        'mtime_ns': stat.st_mtime_ns,
        'modified_UTC': datetime.datetime.fromtimestamp(stat.st_mtime, datetime.timezone.utc).isoformat(),
        'modified_Europe_London': datetime.datetime.fromtimestamp(stat.st_mtime, ZoneInfo('Europe/London')).isoformat(),
    }
    index_doc = {
        'schema': 'FreeCAD-5ar-installation-evidence-index-v1',
        'source_private_root': str(ROOT),
        'policy': 'Exact bytes or explicitly labelled receipt excerpts only; deterministic gzip is lossless. No app/profile inventory bodies or binaries published.',
        'files': sorted(index, key=lambda row: row['file']),
        'private_only_files': private_only,
        'index_and_summary_self_hash_policy': 'This index lists every evidence file except itself. The separate installation summary binds this index SHA; neither file claims a self hash.',
    }
    index_data = json_bytes(index_doc)
    final_doc = {
        'schema': 'FreeCAD-5ar-host-local-installation-v1', 'passed': True,
        'installation_bead': 'FreeCAD-5yj', 'source_bead': 'FreeCAD-5ar',
        'collected_UTC': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'application': str(APP), 'rollback_backup': str(BACKUP),
        'compiled_commit': COMMIT, 'compiled_revision': REVISION,
        'application_version': '27.1.0dev49261+218 (Git)',
        'compiled_version_header': header,
        'signed_bundled_V2_solver': source_record(APP / NATIVE_REL, NATIVE_SHA),
        'source_pins': pins, 'Finder_bundle_modification_time': finder,
        'required_Pixi_environment': str(REPO / '.pixi/envs/default'),
        'distribution_limits': [
            'Host-local installation; requires the existing Pixi dependency environment, launchers, patched Qt Cocoa plugin and dependency links.',
            'Not a self-contained or notarized distribution. No user-profile or material-library migration performed.',
            'Existing RF/SOF/SOM/CF and default solver preferences are unchanged. MPC is aggregate physical body action, not per-Tie CF.',
        ],
        'rollback': 'Quit FreeCAD, move the current application aside, and restore the exact rollback backup path above; do not overwrite an active session.',
        'LOCAL_INSTALL_note_sha256': note_sha,
        'CTest': ctest['ctest'],
        'CTest_workaround': {
            'dot_free_private_temporary_root_used': ctest['private_dot_free_temporary_root'],
            'dotted_temporary_directory_product_bug_fixed': ctest['dotted_temporary_directory_product_bug_fixed'],
            'separate_followup': 'FreeCAD-8rk',
        },
        'locations': locations,
        'root_final_audit': descriptor(ROOT / 'final-audit.json'),
        'independent_installed_audit': descriptor(ROOT / 'independent-installed-audit.json'),
        'evidence': {
            'directory': str(DEST.relative_to(REPO)),
            'index': str((DEST / 'index.json').relative_to(REPO)),
            'index_sha256': sha_bytes(index_data), 'index_bytes': len(index_data),
            'indexed_file_count': len(index),
            'omission_policy': 'Inventory-bearing originals remain private and SHA-bound; published excerpts are not represented as byte-identical or as new independent audits.',
        },
        'engineering_holds': {
            'Oomakhi_opened_altered_or_solved_for_this_installation': False,
            'engineering_or_BIM_design_accepted': False,
            'original_R49_comparison_percent': 11.123267892,
            'unchanged_acceptance_limit_percent': 5.0,
            'original_fixture_equilibrium_pass_claimed': False,
            'duties_unchanged': 'Original geometry and loads; 97 pairs/194 vectors; paired cuts; contact-state, slip/overclosure and independent engineering review.',
            'saved_metadata_repaired_or_rebound': False,
            'cold_custody': 'Historical observation and Stale accounting retained; explicit observation refresh is reported as actually observed and never promotes accounting to Current.',
        },
    }
    final_data = json_bytes(final_doc)
    # Fail before publication if any planned input changed while collecting.
    for row in index:
        require(descriptor(row['original_private_or_repository_path'])['sha256'] == row['original_sha256'],
                f'Input changed during collection: {row["original_private_or_repository_path"]}')
    for row in private_only:
        source_record(row['path'], row['sha256'])
    require(APP.stat().st_mtime_ns == finder['mtime_ns'], 'Application bundle mtime changed during collection')
    require(not DEST.exists() and not FINAL.exists(), 'Evidence appeared during validation')
    DEST.mkdir()  # No exist_ok: concurrent collectors cannot replace evidence.
    for name, data in sorted(planned.items()):
        path = DEST / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(data)
    with (DEST / 'index.json').open('xb') as stream:
        stream.write(index_data)
    with FINAL.open('xb') as stream:
        stream.write(final_data)
    # Verify only the new publication, without mutating any original input.
    for row in index:
        require(descriptor(DEST / row['file'])['sha256'] == row['stored_sha256'], 'Published byte mismatch')
    require(descriptor(DEST / 'index.json')['sha256'] == sha_bytes(index_data), 'Published index mismatch')
    require(descriptor(FINAL)['sha256'] == sha_bytes(final_data), 'Published summary mismatch')
    print(json.dumps({'passed': True, 'summary': str(FINAL), 'summary_sha256': sha_bytes(final_data),
                      'evidence_index': str(DEST / 'index.json'), 'index_sha256': sha_bytes(index_data),
                      'indexed_file_count': len(index)}, indent=2))


if __name__ == '__main__':
    main()
