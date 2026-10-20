"""Frozen source-build QA; root alone prepares/runs/discovers. NEVER install.

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
import hashlib
import json
import os
from pathlib import Path
import re

QA = Path(__file__).resolve().parent
TASK = QA.parent
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
    # Every copied FEM Python module is pinned, including all loaded test files.
    paths += [path for path in (BUILD / 'Mod/Fem').rglob('*.py') if path.is_file()]
    paths += list(extra)
    return source_snapshot(paths)


def prepare(args, directory, discovery_only=False):
    assert not directory.exists()
    assert re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*', args.module)
    assert 1 <= args.timeout <= 3600
    extra, ids = list(args.input_file or []), args.expected_id or []
    if not discovery_only and args.module.split('.')[0] in ('YzkCoupledWitness', 'YzkColdRestore'):
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
        assert args.cold_manifest_sha and sha(args.cold_manifest) == args.cold_manifest_sha
        saved = json.loads(args.cold_manifest.read_text())
        assert args.cold_manifest.resolve().is_relative_to(TASK)
        assert saved['schema'] == 'FreeCAD-yzk-coupled-cold-case-v1'
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
    assert built['version_header'] and candidate.is_file()
    contract = json.loads((REPO / 'package/calculix/force-accounting/contract.json').read_text())
    manifest = {'schema': 'FreeCAD-yzk-source-run-manifest-v1', 'module': args.module,
                'expected_count': 1 if discovery_only else args.expected_count,
                'expected_ids': ids, 'discovery_only': discovery_only, 'unit_only': args.unit_only,
                'gui': args.gui, 'case': args.case, 'timeout_seconds': args.timeout,
                'inputs': before, 'version_header': built['version_header'],
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
    assert manifest_sha and sha(manifest_path) == manifest_sha
    manifest = json.loads(manifest_path.read_text())
    for path, expected in manifest['inputs']['files'].items():
        assert sha(path) == expected, path
    before = json.loads((directory / 'private-custody-before.json').read_text())
    dependencies = json.loads((directory / 'private-critical-before.json').read_text())
    assert sha(directory / 'private-custody-before.json') == manifest['private_custody_before_sha256']
    assert sha(directory / 'private-critical-before.json') == manifest['private_critical_before_sha256']
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
        environment['YZK_COLD_MANIFEST'] = manifest['cold_manifest']['path']
    command = ['pixi', 'run', '--frozen', str(BUILD / 'bin' / ('FreeCAD' if manifest['gui'] else 'FreeCADCmd')),
               '-u', str(directory / 'user.cfg'), '-s', str(directory / 'system.cfg'), '-P', str(QA),
               '-t', 'SourceBuildIdentity']
    if not manifest['discovery_only']:
        command += ['-t', manifest['module']]
    report = {'passed': False, 'manifest_sha256': manifest_sha, 'discovery_only': manifest['discovery_only'],
              'unit_only': manifest['unit_only'], 'native_capacity_qualification_claimed': False,
              'inputs_before': manifest['inputs'], 'installation_performed': False}
    try:
        report.update(run_bounded(command, cwd=REPO, log=directory / 'run.log',
                                  timeout=manifest['timeout_seconds'], environment=environment))
    except BaseException as error:
        report['error'] = repr(error)
    finally:
        report['inputs_after'] = {path: sha(path) for path in manifest['inputs']['files']}
        report['inputs_unchanged'] = report['inputs_after'] == manifest['inputs']['files']
        after, critical_after = custody(), critical()
        write(directory / 'private-custody-after.json', after)
        write(directory / 'private-critical-after.json', critical_after)
        report['app_and_profiles_unchanged'] = before == after
        report['selected_critical_dependencies_unchanged'] = dependencies == critical_after
        identity_path = directory / 'identity.json'
        identity = json.loads(identity_path.read_text()) if identity_path.exists() else {}
        text = (directory / 'run.log').read_text(errors='replace')
        counts = re.findall(r'^Ran (\d+) tests? in ([\d.]+)s\s*$', text, re.M)
        report['unittest_counts'], report['identity_sha256'] = counts, sha(identity_path) if identity else None
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
        write(directory / 'execution.json', report)
        print(json.dumps({key: value for key, value in report.items() if key not in ('inputs_before', 'inputs_after')}, indent=2), flush=True)
    return 0 if report['passed'] else 1


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
    directory = QA / args.label
    if args.action == 'prepare':
        prepare(args, directory)
        return 0
    if args.action == 'discover':
        prepare(args, directory, discovery_only=True)
        return run(directory, sha(directory / 'manifest.json'))
    return run(directory, args.manifest_sha)


if __name__ == '__main__':
    raise SystemExit(main())
