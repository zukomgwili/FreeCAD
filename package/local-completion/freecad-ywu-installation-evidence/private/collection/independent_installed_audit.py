"""Independent read-only installed audit; explicit main writes one new receipt.

No FreeCAD, solver, mesher, build, signing mutation, stage or engineering model
is launched. codesign verification/entitlement reads, git and ps are bounded.
Historical stage paths are checked as literal evidence, never dereferenced or
rewritten after the rename. Full app/profile inventory bodies remain private.
"""
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import plistlib
import re
import runpy
import stat
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
BUILD = REPO / 'build/release'
APP = Path('/Applications/FreeCAD-27.1.0.app')
HISTORICAL_STAGE = ROOT / APP.name
BACKUP = Path('/Users/zukomgwili/Applications/FreeCAD Backups/FreeCAD-27.1.0-before-ywu-b6b9e216c4.app')
PREFIX = REPO / '.pixi/envs/default'
COMMIT = '6cdc1affda07ac4e3b45a98097b7ae11039c80c6'
REVISION = '49261 +221 (Git)'
NATIVE_SHA = '2d59adb06736801f730de077a5f3dbfcfba8c0a430636e5814e5582606b5c89b'
NATIVE_RELATIVE = Path('Contents/Resources/data/NativeSolvers/ccx-force-accounting')
OUTPUT = ROOT / 'independent-installed-audit.json'
PROFILES = (
    Path('/Users/zukomgwili/Library/Application Support/FreeCAD'),
    Path('/Users/zukomgwili/Library/Application Support/FreeCAD Local'),
    Path('/Users/zukomgwili/Library/Preferences/FreeCAD'),
)
SOURCE_NATIVE_SHA = {
    'forceaccounting.c': 'fb35ca4fe0ccd6f1ed1e88439c20926092a06ca32f5c21eb6c9739e52fd0dc5a',
    'hooks.patch': '28bcdb6d042b45db26c817dbb39bc04bb298c0f9a0d717fc9c1a639d0bba15ea',
    'contract.json': '4418a41794adfc386143bd94b709794eea0d9991e774ab559e714e2782730ad3',
}
FROZEN_ORACLES = {
    'endload': 'd1e436011bbd452ec39453a1c61b7466b6ec7a1bef657d7c8bc1da819114660b',
    'ordinary': 'c8fa248d41273d3d829222c9f57cdcbc6cdf384f7077b34010eab94fd48a77c7',
}
REPORTS = {}
READ_HASHES = {}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def bind(path, expected=None, report=False):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), f'Not a regular input: {path}')
    digest = sha(path)
    if expected is not None:
        require(digest == expected, f'Changed recorded bytes: {path}')
    previous = READ_HASHES.setdefault(str(path), digest)
    require(previous == digest, f'Input changed during audit: {path}')
    if report:
        REPORTS[str(path.relative_to(ROOT))] = digest
    return digest


def read(path, report=False):
    bind(path, report=report)
    return json.loads(Path(path).read_text())


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def inventory(root):
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), f'Invalid inventory root: {root}')
    result = {'.': {'kind': 'dir', 'mode': stat.S_IMODE(root.lstat().st_mode)}}
    for directory, directories, files in os.walk(root, followlinks=False):
        for name in sorted(directories + files):
            path = Path(directory) / name
            mode = path.lstat().st_mode
            row = {'mode': stat.S_IMODE(mode)}
            if stat.S_ISLNK(mode):
                row.update(kind='link', target=os.readlink(path))
            elif stat.S_ISDIR(mode):
                row.update(kind='dir')
            else:
                require(stat.S_ISREG(mode), f'Unexpected filesystem object: {path}')
                row.update(kind='file', sha256=sha(path))
            result[str(path.relative_to(root))] = row
    return result


def native_set(root):
    result = set()
    for directory, directories, files in os.walk(root, followlinks=False):
        directories[:] = [name for name in directories if not (Path(directory) / name).is_symlink()]
        for name in files:
            path = Path(directory) / name
            if path.is_symlink():
                continue
            with path.open('rb') as stream:
                magic = stream.read(4)
            if magic == b'\xcf\xfa\xed\xfe':
                result.add(str(path.relative_to(root)))
            else:
                require(magic not in (b'\xfe\xed\xfa\xce', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xcf',
                                      b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca',
                                      b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca'),
                        f'Unexpected native architecture: {path}')
    return result


def command(args, timeout):
    return subprocess.run(args, check=True, capture_output=True, timeout=timeout)


def no_product_process():
    output = command(['/bin/ps', '-axo', 'pid=,comm='], 10).stdout.decode()
    conflicts = []
    for line in output.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) == 2:
            name = Path(fields[1]).name
            if name in ('FreeCAD', 'FreeCADCmd', 'ctest', 'gmsh', 'ninja', 'make', 'gmake',
                        'ccx', 'ccx-force-accounting') or name.startswith('ccx_'):
                conflicts.append(line)
    require(not conflicts, f'Concurrent product/build/solver process: {conflicts}')


def dependency_record(path):
    info = path.lstat()
    result = {'dev': info.st_dev, 'inode': info.st_ino, 'mode': info.st_mode,
              'size': info.st_size, 'mtime_ns': info.st_mtime_ns, 'ctime_ns': info.st_ctime_ns}
    if stat.S_ISLNK(info.st_mode):
        result.update(kind='link', target=os.readlink(path), resolved=str(path.resolve(strict=True)),
                      resolved_sha256=sha(path))
    else:
        require(stat.S_ISREG(info.st_mode), f'Unexpected dependency type: {path}')
        result.update(kind='file', sha256=sha(path))
    return result


def successful_app_gate(location, suffix, total, sealed):
    directory = ROOT / (location + '-' + suffix)
    execution = read(directory / 'execution.json', report=True)
    identity = read(directory / 'identity.json', report=True)
    application = HISTORICAL_STAGE if location == 'stage' else APP
    require(execution['passed'] and execution['returncode'] == 0 and not execution['timed_out'] and
            execution['child_reaped'] and execution['process_group_gone'], f'App execution failed: {directory}')
    for field in ('source_build_harness_unchanged', 'app_and_profiles_unchanged',
                  'application_unchanged', 'critical_dependency_pins_unchanged'):
        require(execution[field] is True, f'App gate custody failed: {field}')
    require(execution['rebound_or_reused_stage_outputs'] is False, 'Reused stage outputs')
    require(execution['application'] == str(application), 'App gate location changed')
    require(execution['inputs_before'] == execution['inputs_after'], 'App gate inputs changed')
    for path, expected in execution['inputs_after'].items():
        bind(path, expected)
    require(len(execution['unittest_counts']) == 1 and int(execution['unittest_counts'][0][0]) == total and
            execution['skipped_lines'] == [], 'Wrong actual unittest count or skips')
    bind(directory / 'identity.json', execution['identity_sha256'])
    bind(directory / 'run.log', execution['log_sha256'], report=True)
    text = (directory / 'run.log').read_text()
    require(re.search(r'^OK\s*$', text, re.M) and
            not re.search(r'^(FAILED\b|FAIL:|ERROR:|UNEXPECTED SUCCESS:)', text, re.M), 'Normal unittest failure')
    require(identity['passed'] and identity['runtime'][-1] == COMMIT and identity['runtime'][3] == REVISION,
            'Wrong executed version')
    require(identity['application'] == str(application) and not identity['source_or_build_import_override'],
            'Application-only identity failed')
    require(identity['candidate'] == {'path': str(application / NATIVE_RELATIVE), 'sha256': NATIVE_SHA,
                                     'capability': 'CCX_FORCE_ACCOUNTING_V3', 'override': False},
            'Candidate identity or default selection changed')
    require(identity['TestFemApp_count'] == 395 and len(identity['registered_native_ids']) == 9 and
            len(set(identity['registered_native_ids'])) == 9, 'Native catalogue registration differs')
    suite = identity['selected_suite']
    require(suite['count'] + 1 == total and len(suite['ids']) == len(set(suite['ids'])) == total - 1,
            'Configured suite count differs')
    required = set(identity['registered_native_ids']).intersection(suite['ids'])
    if suffix == 'fem':
        require(len(required) == 9 and suite['name'] == 'TestFemApp', 'Full FEM did not include all native methods')
    elif suffix == 'native':
        require(len(required) == 5 and all('TestMovingPortAccountingNative.' in item for item in required),
                'Missing new native methods')
    elif suffix == 'gui':
        require(identity['TestFemGui_count'] == 8 and suite['name'] == 'TestFemGui', 'Wrong GUI catalogue')
    for test_id in required:
        expression = '^' + re.escape(test_id.rsplit('.', 1)[-1]) + r' \(' + re.escape(test_id) + r'\)([^\n]*)$'
        hits = re.findall(expression, text, re.M)
        require(len(hits) == 1 and 'skipped' not in hits[0], f'Missing/repeated/skipped native method: {test_id}')
    custody = []
    for when in ('before', 'after'):
        path = directory / ('private-application-' + when + '.json')
        bind(path, execution['application_inventory_' + when + '_sha256'])
        require(read(path) == sealed, 'Actual app gate inventory differs from seal')
        path = directory / ('private-custody-' + when + '.json')
        bind(path, execution['custody_' + when + '_sha256'])
        custody.append(read(path))
    require(custody[0] == custody[1], 'Private custody body changed during app gate')


def witness_and_cold(location, kind):
    directory = ROOT / (location + '-' + kind) / 'witness'
    witness = read(directory / 'witness-receipt.json', report=True)
    application = HISTORICAL_STAGE if location == 'stage' else APP
    require(witness['passed'] and witness['solver_returncode'] == 0 and
            witness['actual_binary'] == str(application / NATIVE_RELATIVE) and
            witness['actual_binary_sha256'] == NATIVE_SHA, 'Physical witness binary/custody mismatch')
    require(len(witness['checks']) == (24 if kind == 'endload' else 26), 'Physical witness checks missing')
    require(all(row['passed'] and row['limit'] == 0.01 and math.isfinite(row['relative_error']) and
                0 <= row['relative_error'] <= 0.01 for row in witness['checks']), 'Physical fixed tolerance failed')
    require(witness['current_native_report']['status'].startswith('Current') and
            witness['current_native_report']['movement_status'] == 'BOUND' and
            witness['current_native_report']['schema'] == 'CCX_FORCE_ACCOUNTING_V3', 'Witness was not current')
    require(witness['only_public_native_interfaces'] and witness['no_deck_patches_or_mocks'] and
            witness['Oomakhi_opened_or_solved'] is False, 'Witness scope changed')
    bind(ROOT / (kind + '-oracle.json'), FROZEN_ORACLES[kind])
    require(witness['frozen_independent_oracle'] == str(ROOT / (kind + '-oracle.json')) and
            witness.get('frozen_independent_oracle_sha256', witness.get('oracle_sha256')) == FROZEN_ORACLES[kind],
            'Frozen oracle was replaced')
    for name, expected in witness['retained_files'].items():
        require(not Path(name).is_absolute() and '..' not in Path(name).parts, 'Unsafe fixture reference')
        bind(directory / name, expected['sha256'])
        require((directory / name).stat().st_size == expected['bytes'], 'Fixture byte size changed')
    manifest_path = Path(witness['cold_manifest'])
    require(manifest_path == directory / 'cold-case.json', 'Not a fresh location-bound cold fixture')
    bind(manifest_path, witness['cold_manifest_sha256'], report=True)
    manifest = read(manifest_path)
    require(manifest['binary'] == str(application / NATIVE_RELATIVE) and manifest['binary_sha256'] == NATIVE_SHA,
            'Cold manifest binary was rebound')
    bind(manifest['document'], manifest['document_sha256'])
    require(Path(manifest['document']).parent == directory, 'Cold fixture document is not fresh')
    for row in manifest['source_files'].values():
        require(Path(row['path']).is_relative_to(directory), 'Cold fixture source escaped its run')
        bind(row['path'], row['sha256'])
    cold = read(ROOT / (location + '-' + kind + '-cold/cold-receipt.json'), report=True)
    require(cold['passed'] and cold['manifest'] == str(manifest_path) and
            cold['manifest_sha256'] == witness['cold_manifest_sha256'] and
            cold['status'].startswith('Stale after restore') and cold['no_native_solve'] and
            cold['no_history_or_provenance_repair'], 'Cold history check failed or rebound')
    expected_supports = ['ExternalSupport'] if kind == 'endload' else ['FixedPatch', 'PartialAxialPatch']
    require(cold['supports'] == manifest['explicit_supports'] == expected_supports, 'Saved support role links changed')
    require(cold['accounting_data_sha256'] == hashlib.sha256(manifest['accounting_data_literal'].encode()).hexdigest(),
            'Saved accounting literal changed')


def legacy(location):
    application = HISTORICAL_STAGE if location == 'stage' else APP
    binary = str(application / NATIVE_RELATIVE)
    v1root = ROOT / (location + '-v1')
    v1 = read(v1root / 'qualification.json', report=True)
    require(v1['passed'] and v1['binary'] == binary and v1['binary_sha256'] == NATIVE_SHA,
            'V1 location/candidate differs')
    require(v1['positive_cases'] == 48 and v1['expected_refusals'] == 6 and v1['physical_norm_checks'] == 288,
            'V1 corpus incomplete')
    bind(v1root / 'manifest.json', v1['manifest_sha256'], report=True)
    for path, expected in v1['protected'].items():
        if path == str(HISTORICAL_STAGE / NATIVE_RELATIVE):
            require(location == 'stage' and expected == NATIVE_SHA, 'Unexpected historical candidate hash')
        else:
            bind(path, expected)
    for row in v1['analytic_cases'] + v1['rejections']:
        directory = v1root / row['case']
        require(read(directory / 'execution.json', report=True) == row, 'V1 aggregate differs from case receipt')
        require(row['passed'] and row['child_reaped'] and row['process_group_gone'] and not row['timed_out'] and
                row['inputs_unchanged'] and row['protected_unchanged'] and row['manifest_unchanged'], 'V1 case failed custody')
        require(row['inputs_before'] == row['inputs_after'] and
                row['protected_before'] == row['protected_after'] == v1['protected'], 'V1 custody maps differ')
        for name, expected in row['inputs_after'].items():
            bind(directory / name, expected)
        for name, expected in row['outputs'].items():
            require(Path(name).name == name, 'Unsafe V1 output name')
            bind(directory / name, expected)
        bind(directory / 'solver.log', row['log_sha256'], report=True)
        if row['positive']:
            require(row['returncode'] == 0 and row['physical_norm_checks'] == 6 and
                    all(len(pair) == 2 and all(math.isfinite(value) and 0 <= value <= 0.01 for value in pair)
                        for pair in row['relative_force_moment_errors'].values()), 'V1 physical norm failure')
        else:
            require(row['returncode'] == 201 and row['complete_accounting_envelope'] is False, 'V1 refusal incomplete')
    v2root = ROOT / (location + '-v2')
    v2 = read(v2root / 'summary.json', report=True)
    manifest = read(v2root / 'manifest.json', report=True)
    bind(v2root / 'manifest.json', v2['manifest_sha256'])
    require(v2['all_selected_passed'] and v2['candidate'] == binary and v2['candidate_sha256'] == NATIVE_SHA,
            'V2 location/candidate differs')
    require(len(v2['reports']) == 10 and sum(bool(row.get('expected_domain_refusal')) for row in v2['reports']) == 2,
            'V2 corpus incomplete')
    checks = [check for row in v2['reports'] for check in row.get('checks', [])]
    require(len(checks) == 144 and all(row['passed'] and row['limit'] == 0.01 and
            math.isfinite(row['relative_error']) and 0 <= row['relative_error'] <= 0.01 for row in checks),
            'V2 fixed analytic checks failed')
    for row in v2['reports']:
        directory = v2root / row['case']
        require(read(directory / 'execution.json', report=True) == row, 'V2 aggregate differs from case receipt')
        require(row['passed'] and row['protected_inputs_unchanged'] and row['child_reaped'] and
                row['process_group_gone'] and not row['timed_out'] and
                row['custody_before'] == row['custody_after'], 'V2 custody failed')
        bind(directory / 'solver.log', row['solver_log_sha256'], report=True)
        paths = {'script': Path(manifest['script']), 'generator': Path(manifest['generator']),
                 'process_control': Path(manifest['process_control']),
                 'deck': directory / 'contact.inp', 'request': directory / 'contact.accounting'}
        require(row['candidate'] == binary and row['candidate_sha256'] == row['custody_after']['candidate'] == NATIVE_SHA,
                'V2 candidate custody changed')
        for name, path in paths.items():
            bind(path, row['custody_after'][name])
        cases = [case for case in manifest['cases'] if case['name'] == row['case']]
        require(len(cases) == 1 and cases[0]['directory'] == str(directory), 'V2 case declaration changed')
        for name in ('deck', 'request'):
            require(cases[0][name] == str(paths[name]) and cases[0][name + '_sha256'] == row['custody_after'][name],
                    'V2 prepared input declaration changed')
        if row.get('expected_domain_refusal'):
            require(row['returncode'] == 201, 'V2 refusal did not occur')
        else:
            require(row['returncode'] == 0, 'V2 positive did not complete')
            output = directory / 'contact.accounting.out'
            bind(output, row['native_output_sha256'])
            lines = output.read_text().splitlines()
            require(lines[0] == 'CCX_FORCE_ACCOUNTING_V2' and lines[-1] == 'END', 'V2 literal envelope changed')


def audit():
    no_product_process()
    require(ROOT == Path('/private/tmp/freecad-ywu-install-QnEflFoR'), 'Wrong private root')
    require(not OUTPUT.exists() and not OUTPUT.is_symlink(), 'Refusing to replace independent audit')
    final = read(ROOT / 'final-audit.json', report=True)
    require(final['passed'] and final['source_commit'] == COMMIT and final['compiled_revision'] == REVISION and
            final['application'] == str(APP) and final['backup'] == str(BACKUP) and final['native_V3_sha256'] == NATIVE_SHA,
            'Root final audit is missing, failed or differently bound')
    require(not HISTORICAL_STAGE.exists() and not HISTORICAL_STAGE.is_symlink(), 'Stage was not renamed away')
    sealed = read(ROOT / 'stage-inventory.json')
    baseline = read(ROOT / 'baseline-inventory.json')
    require(inventory(APP) == sealed and inventory(BACKUP) == baseline, 'Actual installed/backup inventory differs')
    profiles = read(ROOT / 'profile-inventories.json')
    require(set(profiles) == {str(path) for path in PROFILES if path.is_dir()}, 'Protected profile membership changed')
    for path, expected in profiles.items():
        require(inventory(Path(path)) == expected, 'Protected user profile changed')
    critical = read(ROOT / 'critical-before-DESTDIR.json')
    require(critical['passed'] and len(critical['files']) == 16, 'Wrong selected dependency custody scope')
    for path, expected in critical['files'].items():
        require(dependency_record(Path(path)) == expected, f'Selected dependency changed: {path}')
    require(command(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], 10).stdout.decode().strip() == COMMIT,
            'Current source HEAD differs')
    command(['git', '-C', str(REPO), 'diff', '--quiet', 'HEAD', '--', 'src', 'package/calculix'], 10)
    version = BUILD / 'src/Build/Version.h'
    bind(version)
    macros = dict(re.findall(r'^#define\s+(\w+)\s+"([^"]*)"', version.read_text(), re.M))
    require(macros['FCRepositoryHash'] == COMMIT and macros['FCRevision'] == REVISION, 'Compiled header differs')
    resources = APP / 'Contents/Resources'
    bind(APP / NATIVE_RELATIVE, NATIVE_SHA)
    bind(BUILD / 'data/NativeSolvers/ccx-force-accounting', NATIVE_SHA)
    for name, expected in SOURCE_NATIVE_SHA.items():
        bind(REPO / 'package/calculix/force-accounting' / name, expected)
        bind(resources / 'data/NativeSolvers/source' / name, expected)
    # Only these reviewed pure helpers are reused; no root audit/checker or
    # product-entry function is called. Comparison decisions below are separate.
    bind(ROOT / 'stage_install.py', 'cca627502a56b6c9b4aefa4a970172c51e42e2dde834000decca65fd44ab46d9')
    helper = runpy.run_path(str(ROOT / 'stage_install.py'))
    macho = helper['macho_identity']
    for source, target in helper['SOURCES'].items():
        require(bind(REPO / source) == bind(resources / target), f'Installed source parity failed: {target}')
    bind(resources / 'LOCAL-INSTALL.txt', bind(ROOT / 'LOCAL-INSTALL.txt'))
    resource_inventory = inventory(resources)
    require(all(row['kind'] == 'link' or not row['mode'] & 0o222 for row in resource_inventory.values()),
            'Resources are writable')
    require(not any('__pycache__' in Path(name).parts or Path(name).suffix in ('.pyc', '.pyo')
                    for name in resource_inventory), 'Resource bytecode/cache exists')
    for application in (APP, BACKUP):
        command(['codesign', '--verify', '--deep', '--strict', str(application)], 60)
        for name in ('FreeCADPreviewExtension.appex', 'FreeCADThumbnailExtension.appex'):
            path = application / 'Contents/Resources/PlugIns' / name
            actual = command(['codesign', '-d', '--entitlements', ':-', str(path)], 20).stdout
            expected = ROOT / (name + '.plist')
            bind(expected)
            require(plistlib.loads(actual) == plistlib.loads(expected.read_bytes()), 'QuickLook entitlements changed')
    payload = ROOT / 'payload/Applications/FreeCAD-27.1.0.app/Contents/Resources'
    payload_audit = read(ROOT / 'independent-payload-audit.json', report=True)
    stage_audit = read(ROOT / 'independent-stage-audit.json', report=True)
    stage_custody = read(ROOT / 'independent-stage-custody.json', report=True)
    payload_native = native_set(payload)
    require(len(payload_native) == 61 and payload_native == {row['relative'] for row in payload_audit['native']} ==
            {row['relative'] for row in stage_audit['native']}, 'Complete native payload set differs')
    require(canonical(sorted(payload_native)) == payload_audit['native_complete_relative_set_sha256'] ==
            stage_audit['native_complete_relative_set_sha256'] == stage_custody['native_complete_relative_set_sha256'],
            'Native relative-set hashes differ')
    native_rows = {row['relative']: row for row in payload_audit['native']}
    for relative in sorted(payload_native):
        installed, emitted = macho(resources / relative), macho(payload / relative)
        require(installed['normalized'] == emitted['normalized'] and installed['rpaths'] == emitted['rpaths'],
                f'Installed native differs from emitted payload: {relative}')
        row = native_rows[relative]
        require(emitted['sha256'] == row['payload_sha256'] and emitted['normalized_sha256'] == row['normalized_sha256'],
                'Payload native receipt differs')
        matches = []
        for match in row['build_matches']:
            path = BUILD / match['path']
            source = macho(path)
            if source['normalized'] == installed['normalized'] and source['sha256'] == match['sha256']:
                matches.append(path)
        require(matches, f'No actual build-native code match: {relative}')
    all_installed, all_backup = native_set(APP), native_set(BACKUP)
    in_app = {str(Path('Contents/Resources') / relative) for relative in payload_native}
    require(all_installed == in_app | (all_backup - in_app), 'New/unaccounted inherited native image')
    for relative in all_installed - in_app:
        installed, old = macho(APP / relative), macho(BACKUP / relative)
        require(installed['normalized'] == old['normalized'] and installed['rpaths'] == old['rpaths'],
                'Inherited native code or RPATH changed')
    namespace = read(ROOT / 'namespace-plan.json')
    require(len(namespace) == 11, 'Wrong selected namespace scope')
    for relative, row in namespace.items():
        require(row['before'] == row['after'], 'Namespace declaration changed')
        bind(PREFIX / relative, row['before'])
        bind(resources / 'Ext/freecad' / Path(relative).name, row['before'])
        require(stat.S_IMODE((PREFIX / relative).stat().st_mode) == row['mode'], 'Namespace mode changed')

    for location in ('stage', 'installed'):
        for suffix, total in (('fem', 396), ('gui', 9), ('native', 6), ('endload', 2), ('ordinary', 2),
                              ('endload-cold', 2), ('ordinary-cold', 2)):
            successful_app_gate(location, suffix, total, sealed)
        for kind in ('endload', 'ordinary'):
            witness_and_cold(location, kind)
        legacy(location)
    ctest = read(ROOT / 'ctest-latest/execution.json', report=True)
    ct = ctest['ctest']
    require(ctest['passed'] and ctest['exit_code'] == 0 and ctest['source_and_supervisor_unchanged'] and
            ct['complete_catalogue_verified'] and
            (ct['catalogue'], ct['executed_passing'], ct['skipped'], ct['disabled'], ct['failed']) == (2274, 2264, 2, 8, 0),
            'CTest regression gate differs')
    bind(ROOT / 'ctest-latest/run.log', ctest['log_sha256'], report=True)
    swap = read(ROOT / 'step-swap.json', report=True)
    require(swap['passed'] and swap['exit_code'] == 0 and not swap['timed_out'] and swap['process_reaped'] and
            swap['owned_processes_remaining'] == {} and swap['critical_pins_unchanged'], 'Swap did not complete safely')
    for path, expected in swap['helper_inputs_after'].items():
        bind(path, expected)
    require(swap['helper_inputs_before'] == swap['helper_inputs_after'], 'Swap helper changed')
    # Recheck real protected state and every byte input after read-only commands.
    no_product_process()
    require(inventory(APP) == sealed and inventory(BACKUP) == baseline, 'App/backup changed during independent audit')
    for path, expected in profiles.items():
        require(inventory(Path(path)) == expected, 'Profile changed during independent audit')
    for path, expected in critical['files'].items():
        require(dependency_record(Path(path)) == expected, 'Selected dependency changed during independent audit')
    for path, expected in READ_HASHES.items():
        require(sha(path) == expected, f'Input changed during independent audit: {path}')
    return {
        'schema': 'FreeCAD-ywu-independent-installed-audit-v1', 'passed': True,
        'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'source_commit': COMMIT, 'revision': REVISION, 'application': str(APP), 'backup': str(BACKUP),
        'final_audit_sha256': REPORTS['final-audit.json'], 'reports': REPORTS,
        'installed_app_equals_sealed_stage': True, 'backup_equals_baseline': True,
        'protected_profiles_unchanged': True, 'selected_critical_files_unchanged': True,
        'private_inventory_receipt_sha256': {name: READ_HASHES[str(ROOT / name)] for name in
            ('stage-inventory.json', 'baseline-inventory.json', 'profile-inventories.json', 'critical-before-DESTDIR.json')},
        'native_V3_sha256': NATIVE_SHA, 'normalized_complete_native_payload_count': len(payload_native),
        'signatures_quicklook_readonly_cachefree_and_source_native_parity_passed': True,
        'findings': [], 'no_product_or_solver_launch': True,
        'historical_stage_paths_preserved_not_dereferenced_or_rebound': True,
        'historical_stage_scope': 'Retained literal receipts and their present byte custody, plus unchanged seal; not a new post-swap stage execution or product-path verification.',
        'scope': 'Host-local software installation and saved generic analytical QA only; not a whole-prefix inventory.',
        'engineering_or_BIM_accepted': False, 'Oomakhi_opened_altered_or_solved': False,
        'R49_failed_percent': 11.123267892, 'R51_failed_percent': 5.240441298,
        'unchanged_displacement_limit_percent': 5, 'unchanged_force_origin_moment_limit': 0.01,
        'audit_script_sha256': sha(Path(__file__)),
    }


def main():
    require(not OUTPUT.exists() and not OUTPUT.is_symlink(), 'Refusing to replace independent audit')
    proof = {'schema': 'FreeCAD-ywu-independent-installed-audit-v1', 'passed': False,
             'source_commit': COMMIT, 'revision': REVISION, 'application': str(APP), 'backup': str(BACKUP),
             'reports': REPORTS}
    try:
        proof = audit()
    except BaseException as error:
        proof.update(findings=[repr(error)])
        raise
    finally:
        with OUTPUT.open('x') as stream:
            stream.write(json.dumps(proof, indent=2) + '\n')
        print(json.dumps({'passed': proof['passed'], 'receipt': str(OUTPUT),
                          'sha256': sha(OUTPUT), 'reports': len(REPORTS)}, indent=2))


if __name__ == '__main__':
    main()
