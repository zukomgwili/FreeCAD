"""Generic portable-cold adapter of the unchanged source runner; root alone executes.

Uses the exact85-line APPQA_COLD_MANIFEST cold helper at its natural TASK
module origin and the unchanged source-qa identity/support at their real paths.
No source/build/installed app modification, solve, save or provenance repair.

Frozen source-build QA; root alone prepares/runs/discovers. NEVER install.

Narrow unit example:
 prepare LABEL --module femtest.app.test_force_accounting.TestForceAccounting.METHOD
   --expected-count 2 --expected-id FULL_ID --unit-only
 run LABEL --manifest-sha SHA
For full suites: discover LABEL --module TestFemApp --unit-only, review identity
IDs/counts, then prepare another LABEL --discovery IDENTITY --discovery-sha SHA
--expected-count TOTAL. Discovery executes identity only, not feature tests.
Physical witness preparation requires --native-receipt PATH --native-receipt-sha
and binds its C/hooks/contract/binary to the current default bundled candidate.
"""
import sys
sys.dont_write_bytecode = True
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re

ADAPTER = Path(__file__).resolve().parent
TASK = ADAPTER.parent
QA = TASK / 'source-qa'
COLD_HELPER = TASK / 'YzkPortableColdRestore.py'
COLD_HELPER_SHA = '164691a5afeedbee55f47841ed9a064c9addbb37e89d143f36de4d5d927b4c51'
REPO = Path('/Users/zukomgwili/src/FreeCAD')
BUILD = REPO / 'build/release'
sys.path.insert(0, str(TASK))
from process_control import assert_serial, run_bounded
sys.path.insert(0, str(QA))
from YzkBuildSupport import sha, write, custody, critical, source_snapshot, build_snapshot


def snapshots(extra=()):
    paths = [Path(__file__), QA / 'SourceBuildIdentity.py']
    paths += sorted(TASK.glob('Yzk*.py')) + sorted((TASK / 'oracle').glob('*.json'))
    paths += [Path(path) for path in build_snapshot()['files']]
    # Every copied FEM Python module and both approved capacity JSON assets are pinned.
    paths += [path for path in (BUILD / 'Mod/Fem').rglob('*.py') if path.is_file()]
    paths += list(extra)
    return source_snapshot(paths)


def prepare(args, directory, discovery_only=False):
    assert sha(COLD_HELPER) == COLD_HELPER_SHA, 'Exact reviewed cold helper changed'
    assert not discovery_only and not args.unit_only and not args.gui
    assert args.module == 'YzkPortableColdRestore'
    assert args.expected_count == 2
    assert args.expected_id == ['YzkPortableColdRestore.PortableColdRestore.test_saved_full_graph_remains_literal_historical_data']
    assert args.cold_manifest and args.cold_manifest_sha
    assert not directory.exists()
    assert re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*', args.module)
    assert 1 <= args.timeout <= 3600
    extra, ids = list(args.input_file or []), args.expected_id or []
    physical_modules = ('YzkCoupledWitness', 'YzkCapacityAtLimit', 'YzkCapacityRefusal',
                        'YzkColdRestore', 'YzkPortableColdRestore', 'femtest.app.test_moving_port_capacity_native')
    if not discovery_only and any(args.module == name or args.module.startswith(name + '.')
                                  for name in physical_modules):
        assert not args.unit_only, 'Physical/cold witnesses require the actual compiled native attestation'
    if args.discovery:
        assert args.discovery_sha and sha(args.discovery) == args.discovery_sha
        previous = json.loads(args.discovery.read_text())
        assert previous['passed'] and previous['discovery_only']
        assert previous['selected_suite']['name'] == args.module
        ids = previous['selected_suite']['ids']
        extra.append(args.discovery)
    if not discovery_only:
        assert ids and len(ids) == len(set(ids)) and args.expected_count == len(ids) + 1
    native_receipt = None
    candidate = BUILD / 'data/NativeSolvers/ccx-force-accounting'
    native_source = {name: sha(REPO / 'package/calculix/force-accounting' / name)
                     for name in ('forceaccounting.c', 'hooks.patch', 'contract.json')}
    if not args.unit_only:
        assert args.native_receipt and args.native_receipt_sha
    if args.native_receipt:
        assert sha(args.native_receipt) == args.native_receipt_sha
        receipt = json.loads(args.native_receipt.read_text())
        assert receipt['passed'] and receipt['mode'] == 'native'
        assert receipt['candidate']['sha256'] == sha(candidate)
        assert sha(receipt['candidate']['path']) == sha(candidate)
        assert receipt['native_source_sha256'] == native_source
        if receipt.get('schema') == 'FreeCAD-yzk-existing-native-build-attestation-v1':
            assert receipt['derived_receipt'] is True
            assert receipt['new_execution_performed'] is False
            assert receipt['physical_duty_qualified'] is False
            assert receipt['native_capacity_qualified'] is False
            assert receipt['contract_compilation_claimed'] is False
            for proof in receipt['original_evidence'].values():
                assert sha(proof['path']) == proof['sha256'], proof['path']
                extra.append(Path(proof['path']))
            for path, expected in receipt['validated_original_inputs'].items():
                assert sha(path) == expected, path
                extra.append(Path(path))
            for path, expected in receipt['validated_current_files'].items():
                assert sha(path) == expected, path
                extra.append(Path(path))
            assert receipt['compiled_sources_sha256'] == {
                name: native_source[name] for name in ('forceaccounting.c', 'hooks.patch')}
        native_receipt = {'path': str(args.native_receipt), 'sha256': args.native_receipt_sha,
                          'native_source_sha256': native_source, 'candidate': receipt['candidate'],
                          'schema': receipt.get('schema'),
                          'contract_compilation_claimed': False}
        extra += [args.native_receipt, Path(receipt['candidate']['path'])]
    cold = None
    if args.cold_manifest:
        cold_bytes = args.cold_manifest.read_bytes()
        assert args.cold_manifest_sha and hashlib.sha256(cold_bytes).hexdigest() == args.cold_manifest_sha
        saved = json.loads(cold_bytes)
        assert args.cold_manifest.resolve().is_relative_to(TASK)
        assert saved['schema'] == 'FreeCAD-native-coupled-port-coupled-cold-case-v1'
        assert set(saved['source_files']) == {'dat', 'deck', 'frd', 'native_output', 'request'}
        expected_names = {'dat': 'Mesh.dat', 'deck': 'Mesh.inp', 'frd': 'Mesh.frd',
                          'native_output': 'Mesh.accounting.out', 'request': 'Mesh.accounting'}
        assert all(Path(row['path']).name == expected_names[name]
                   for name, row in saved['source_files'].items())
        assert Path(saved['document']).resolve().is_relative_to(TASK)
        assert sha(saved['document']) == saved['document_sha256']
        for row in saved['source_files'].values():
            assert Path(row['path']).resolve().is_relative_to(TASK)
            assert sha(row['path']) == row['sha256'], row['path']
        extra += [args.cold_manifest, Path(saved['document'])]
        extra += [Path(row['path']) for row in saved['source_files'].values()]
        cold = {'path': str(args.cold_manifest), 'sha256': args.cold_manifest_sha}
    before = snapshots(extra)
    state, dependencies, built = custody(), critical(), build_snapshot()
    assert len(state) == 4 and len(dependencies) == 15
    assert built['version_header'] and candidate.is_file()
    assert built['fem_python_copy_parity']['passed'], built['fem_python_copy_parity']
    assert built['fem_capacity_json_copy_parity']['passed'], built['fem_capacity_json_copy_parity']
    contract = json.loads((REPO / 'package/calculix/force-accounting/contract.json').read_text())
    manifest = {'schema': 'FreeCAD-yzk-source-run-manifest-v3', 'module': args.module,
                'expected_count': 1 if discovery_only else args.expected_count,
                'expected_ids': ids, 'discovery_only': discovery_only, 'unit_only': args.unit_only,
                'gui': args.gui, 'case': args.case, 'timeout_seconds': args.timeout,
                'inputs': before, 'version_header': built['version_header'],
                'fem_python_copy_plan': built['fem_python_copy_plan'],
                'fem_python_copy_parity': built['fem_python_copy_parity'],
                'fem_capacity_json_copy_plan': built['fem_capacity_json_copy_plan'],
                'fem_capacity_json_copy_parity': built['fem_capacity_json_copy_parity'],
                'candidate': {'path': str(candidate), 'sha256': sha(candidate), 'schema': contract['schema'], 'override': False},
                'native_source_observed_sha256': native_source, 'native_build_receipt': native_receipt,
                'cold_manifest': cold,
                'qualification_limits': 'Unit-only can use an older compiled candidate; it does NOT attest the observed C/hooks were compiled. Discovery is not feature execution.'}
    directory.mkdir()
    write(directory / 'private-custody-before.json', state)
    write(directory / 'private-critical-before.json', dependencies)
    manifest['private_custody_before_sha256'] = sha(directory / 'private-custody-before.json')
    manifest['private_critical_before_sha256'] = sha(directory / 'private-critical-before.json')
    write(directory / 'manifest.json', manifest)
    print(json.dumps({'prepared': True, 'discovery_only': discovery_only, 'manifest': str(directory / 'manifest.json'),
                      'manifest_sha256': sha(directory / 'manifest.json'), 'expected_count': manifest['expected_count']}, indent=2))


def run(directory, manifest_sha):
    manifest_path = directory / 'manifest.json'
    manifest_bytes = manifest_path.read_bytes()
    assert manifest_sha and hashlib.sha256(manifest_bytes).hexdigest() == manifest_sha
    manifest = json.loads(manifest_bytes)
    assert manifest['module'] == 'YzkPortableColdRestore' and not manifest['unit_only']
    assert manifest['cold_manifest'] and manifest['expected_count'] == 2
    assert sha(COLD_HELPER) == COLD_HELPER_SHA
    assert sha(manifest['cold_manifest']['path']) == manifest['cold_manifest']['sha256']
    for path, expected in manifest['inputs']['files'].items():
        assert sha(path) == expected, path
    before = json.loads((directory / 'private-custody-before.json').read_text())
    dependencies = json.loads((directory / 'private-critical-before.json').read_text())
    assert sha(directory / 'private-custody-before.json') == manifest['private_custody_before_sha256']
    assert sha(directory / 'private-critical-before.json') == manifest['private_critical_before_sha256']
    assert len(before) == 4 and len(dependencies) == 15
    assert custody() == before and critical() == dependencies
    environment = dict(os.environ)
    for key in list(environment):
        if key.startswith(('FREECAD_', 'CCX_', 'APPQA_', 'YWU_', 'YZK_', 'FIVEAR_')) or key in (
                'PYTHONHOME', 'PYTHONPATH', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
            environment.pop(key)
    for key in ('FREECAD_USER_HOME', 'FREECAD_USER_DATA', 'FREECAD_USER_TEMP',
                'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
        path = directory / key.lower()
        path.mkdir()
        environment[key] = str(path)
    environment.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', OMP_NUM_THREADS='2',
        TMPDIR=environment['FREECAD_USER_TEMP'], YZK_OUTPUT=str(directory),
        YZK_QA_MANIFEST=str(manifest_path), YZK_QA_MANIFEST_SHA=manifest_sha, YZK_CASE=manifest['case'])
    if manifest['cold_manifest']:
        environment['APPQA_COLD_MANIFEST'] = manifest['cold_manifest']['path']
    command = ['pixi', 'run', '--frozen', str(BUILD / 'bin' / ('FreeCAD' if manifest['gui'] else 'FreeCADCmd')),
               '-u', str(directory / 'user.cfg'), '-s', str(directory / 'system.cfg'), '-P', str(QA),
               '-t', 'SourceBuildIdentity']
    if not manifest['discovery_only']:
        command += ['-t', manifest['module']]
    report = {'passed': False, 'manifest_sha256': manifest_sha, 'discovery_only': manifest['discovery_only'],
              'unit_only': manifest['unit_only'], 'native_capacity_qualification_claimed': False,
              'inputs_before': manifest['inputs'], 'installation_performed': False}
    try:
        with null_stdin():
            report.update(run_bounded(command, cwd=REPO, log=directory / 'run.log',
                                      timeout=manifest['timeout_seconds'], environment=environment))
    except BaseException as error:
        report['error'] = repr(error)
    finally:
        try:
            report['inputs_after'] = {path: sha(path) for path in manifest['inputs']['files']}
            report['inputs_unchanged'] = report['inputs_after'] == manifest['inputs']['files']
            after, critical_after = custody(), critical()
            write(directory / 'private-custody-after.json', after)
            write(directory / 'private-critical-after.json', critical_after)
            for kind in ('custody', 'critical'):
                for when in ('before', 'after'):
                    report[f'private_{kind}_{when}_sha256'] = sha(
                        directory / f'private-{kind}-{when}.json')
            assert report['private_custody_before_sha256'] == manifest['private_custody_before_sha256']
            assert report['private_critical_before_sha256'] == manifest['private_critical_before_sha256']
            report['app_and_profiles_unchanged'] = before == after
            report['selected_critical_dependencies_unchanged'] = dependencies == critical_after
            identity_path = directory / 'identity.json'
            cold_path = directory / 'cold-receipt.json'
            captured = {path: path.read_bytes() for path in (
                identity_path, cold_path, directory / 'run.log') if path.is_file()}
            identity = json.loads(captured[identity_path]) if identity_path in captured else {}
            cold = json.loads(captured[cold_path]) if cold_path in captured else {}
            log_bytes = captured.get(directory / 'run.log', b'')
            text = log_bytes.decode(errors='replace')
            report['captured_outputs'] = {str(path): {'sha256': hashlib.sha256(raw).hexdigest(),
                                                   'bytes': len(raw)} for path, raw in captured.items()}
            report['captured_log_matches_process_receipt'] = (
                hashlib.sha256(log_bytes).hexdigest() == report.get('log_sha256'))
            report['literal_cold_receipt_passed'] = bool(
                cold.get('schema') == 'FreeCAD-yzk-portable-cold-receipt-v1' and cold.get('passed') is True
                and cold.get('manifest') == manifest['cold_manifest']['path']
                and cold.get('manifest_sha256') == manifest['cold_manifest']['sha256']
                and cold.get('no_native_solve') is True and cold.get('no_save') is True
                and cold.get('no_history_or_provenance_repair') is True
                and cold.get('status', '').startswith('Stale'))
            counts = re.findall(r'^Ran (\d+) tests? in ([\d.]+)s\s*$', text, re.M)
            report['unittest_counts'] = counts
            report['identity_sha256'] = hashlib.sha256(captured[identity_path]).hexdigest() if identity else None
            report['skipped_lines'] = re.findall(r'^.*\.\.\. skipped .*$', text, re.M)
            missing = []
            for test_id in ([] if manifest['discovery_only'] else manifest['expected_ids']):
                pattern = '^' + re.escape(test_id.rsplit('.', 1)[-1]) + r' \(' + re.escape(test_id) + r'\)([^\n]*)$'
                hits = re.findall(pattern, text, re.M)
                if len(hits) != 1 or 'skipped' in hits[0]:
                    missing.append(test_id)
            report['missing_repeated_or_skipped_ids'] = missing
            report['passed'] = bool(report.get('returncode') == 0 and report.get('child_reaped') and
                report.get('process_group_gone') and not report.get('timed_out') and identity.get('passed') and
                report['inputs_unchanged'] and report['app_and_profiles_unchanged'] and
                report['selected_critical_dependencies_unchanged'] and len(counts) == 1 and
                int(counts[0][0]) == manifest['expected_count'] and not missing and not report['skipped_lines'] and
                re.search(r'^OK\s*$', text, re.M) and not re.search(r'^(FAILED\b|FAIL:|ERROR:|UNEXPECTED SUCCESS:)', text, re.M))
            report['runtime'] = identity.get('runtime')
            report['output_bytes_endfenced'] = all(
                path.read_bytes() == raw for path, raw in captured.items())
            report['manifest_endfenced'] = manifest_path.read_bytes() == manifest_bytes
            report['final_inputs_endfenced'] = all(
                sha(path) == wanted for path, wanted in manifest['inputs']['files'].items())
            report['private_receipt_bytes_endfenced'] = all(
                sha(directory / f'private-{kind}-{when}.json') == report[f'private_{kind}_{when}_sha256']
                for kind in ('custody', 'critical') for when in ('before', 'after'))
            report['passed'] = bool(report['passed'] and report['literal_cold_receipt_passed']
                and report['captured_log_matches_process_receipt'] and report['output_bytes_endfenced']
                and report['manifest_endfenced'] and report['final_inputs_endfenced']
                and report['private_receipt_bytes_endfenced'])
            report['scope'] = 'Separate-process literal cold restore only; no new solve/save/repair or engineering acceptance'
            assert_serial(('gmsh', 'ninja', 'make', 'gmake'))
            report['post_run_serial_guard_passed'] = True
        except BaseException as error:
            report['passed'] = False
            report['finalization_error'] = repr(error)
        write(directory / 'execution.json', report)
        print(json.dumps({key: value for key, value in report.items() if key not in ('inputs_before', 'inputs_after')}, indent=2), flush=True)
    return 0 if report['passed'] else 1


@contextmanager
def null_stdin():
    original = os.dup(0)
    try:
        with open(os.devnull, 'rb') as empty:
            os.dup2(empty.fileno(), 0)
            yield
    finally:
        os.dup2(original, 0)
        os.close(original)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'run', 'discover'))
    parser.add_argument('label')
    parser.add_argument('--module', default='TestFemApp')
    parser.add_argument('--expected-count', type=int)
    parser.add_argument('--expected-id', action='append')
    parser.add_argument('--discovery', type=Path)
    parser.add_argument('--discovery-sha')
    parser.add_argument('--manifest-sha')
    parser.add_argument('--native-receipt', type=Path)
    parser.add_argument('--native-receipt-sha')
    parser.add_argument('--unit-only', action='store_true')
    parser.add_argument('--gui', action='store_true')
    parser.add_argument('--case', choices=('tracer', 'capacity'), default='tracer')
    parser.add_argument('--cold-manifest', type=Path)
    parser.add_argument('--cold-manifest-sha')
    parser.add_argument('--input-file', action='append', type=Path,
                        help='Additional immutable benchmark/fixture input pinned before and after')
    parser.add_argument('--timeout', type=int, default=900)
    args = parser.parse_args()
    assert re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', args.label)
    assert not sys.flags.optimize
    assert_serial(('gmsh', 'ninja', 'make', 'gmake'))
    directory = ADAPTER / args.label
    if args.action == 'prepare':
        prepare(args, directory)
        return 0
    if args.action == 'discover':
        prepare(args, directory, discovery_only=True)
        return run(directory, sha(directory / 'manifest.json'))
    return run(directory, args.manifest_sha)


if __name__ == '__main__':
    raise SystemExit(main())
