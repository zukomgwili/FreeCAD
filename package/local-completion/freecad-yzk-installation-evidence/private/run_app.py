"""PROPOSAL: bounded literal-app yzk QA; no installation or live profile use.

Root must read/adopt into the task root with frozen config and existing serial
process_control/critical_pins/stage_install helpers before any execution.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
BUILD = REPO / 'build/release'
sys.path.insert(0, str(ROOT))
from process_control import assert_serial, run_bounded
from harness_config import COMMIT, REVISION, NATIVE_SHA

CAPACITY_MODULE = "femtest.app.test_moving_port_capacity_native"
CAPACITY_COUNTS = {"supports": 1, "bodies": 264, "ports": 264, "angles": 792, "springs": 792}


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    with path.open('x') as stream:
        stream.write(json.dumps(value, indent=2) + '\n')


def snapshot(extra=()):
    files = sorted((REPO / 'src/Mod/Fem').rglob('*.py')) + sorted(ROOT.glob('*.py'))
    files += [ROOT / 'oracle.json', ROOT / 'endload-oracle.json',
              ROOT / 'ordinary-oracle.json', ROOT / 'oracle-spec-proposal.json',
              BUILD / 'src/Build/Version.h', BUILD / 'bin/FreeCADCmd', BUILD / 'bin/FreeCAD',
              BUILD / 'Mod/Fem/Fem.so', BUILD / 'Mod/Fem/FemGui.so',
              BUILD / 'lib/libFreeCADApp.dylib', BUILD / 'data/NativeSolvers/ccx-force-accounting',
              REPO / 'package/calculix/force-accounting/forceaccounting.c',
              REPO / 'package/calculix/force-accounting/hooks.patch',
              REPO / 'package/calculix/force-accounting/contract.json']
    files += [REPO / 'src/Mod/Fem/femtest/data/calculix' / name for name in
              ('coupled_port_capacity_fixture.json', 'coupled_port_capacity_oracle.json')]
    files += list(extra)
    return {str(path): sha(path) for path in files if path.is_file()}


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


def cold_inputs(path, expected_sha):
    assert path.is_relative_to(ROOT) and not path.is_symlink() and sha(path) == expected_sha
    value = json.loads(path.read_text())
    assert set(value['source_files']) == {'deck', 'request', 'native_output', 'dat', 'frd'}
    files = [path, Path(value['document'])]
    assert sha(files[-1]) == value['document_sha256']
    for proof in value['source_files'].values():
        target = Path(proof['path'])
        assert sha(target) == proof['sha256']
        files.append(target)
    for target in files:
        assert target.is_file() and target.is_relative_to(ROOT) and not target.is_symlink()
        parent = target.parent
        while parent != ROOT:
            assert not parent.is_symlink()
            parent = parent.parent
    return files


def capacity_witness(run, text, candidate):
    # This is custody of the public test's proof, not a replacement physical
    # oracle. The test itself performs every frozen3566 acceptance comparison.
    matches = re.findall(r'^Native capacity evidence: (.+)$', text, re.M)
    assert len(matches) == 1, matches
    directory = Path(matches[0]) / 'witness'
    assert directory.is_relative_to(run / 'freecad_user_temp') and not directory.is_symlink()
    receipt_path = directory / 'witness-receipt.json'
    receipt = json.loads(receipt_path.read_text())
    assert receipt['schema'] == 'FreeCAD-native-coupled-port-coupled-native-witness-v1'
    assert receipt['passed'] and receipt['protected_inputs_unchanged']
    assert receipt['actual_binary'] == str(candidate) and receipt['actual_binary_sha256'] == NATIVE_SHA
    assert receipt['engineering_project_accessed_or_solved'] is False
    assert receipt['engineering_or_BIM_accepted'] is False
    assert receipt['physical_check_count'] == len(receipt['checks']) == 3566
    assert len({row['name'] for row in receipt['checks']}) == 3566
    assert all(row['passed'] and row['limit'] in (.01, .05) for row in receipt['checks'])
    for relative, stamp in receipt['retained_files'].items():
        assert not Path(relative).is_absolute() and '..' not in Path(relative).parts
        path = directory / relative
        assert path.is_file() and not path.is_symlink()
        assert sha(path) == stamp['sha256'] and path.stat().st_size == stamp['bytes']
    data = json.loads((directory / 'native-accounting-data.json').read_text())
    expected = {'budget': 2113, 'counts': CAPACITY_COUNTS, 'total': 2113}
    assert data['capacity_applied'] == expected
    assert data['capacity']['required'] == CAPACITY_COUNTS and data['capacity']['total'] == 2113
    assert data['capacity']['supported']['total_records'] == 2113
    assert data['binary'] == str(candidate) and data['binary_sha256'] == NATIVE_SHA
    stdout = (directory / 'native.stdout').read_text()
    echoes = re.findall(r'^CCX_FORCE_ACCOUNTING_CAPACITY_APPLIED_V1 (.+)$', stdout, re.M)
    assert len(echoes) == 1 and json.loads(echoes[0]) == expected
    cold = Path(receipt['cold_manifest'])
    assert cold == directory / 'cold-case.json' and sha(cold) == receipt['cold_manifest_sha256']
    return {'directory': str(directory), 'witness_receipt_sha256': sha(receipt_path),
            'cold_manifest': {'path': str(cold), 'sha256': sha(cold)},
            'owned_child_applied_capacity': expected, 'physical_checks': 3566,
            'public_test_not_replaced_by_supervisor_arithmetic': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('application', type=Path)
    parser.add_argument('label')
    parser.add_argument('--module', default='TestFemApp')
    parser.add_argument('--count', type=int, default=406)
    parser.add_argument('--timeout', type=int, default=240)
    parser.add_argument('--cold-case', type=Path)
    parser.add_argument('--cold-case-sha256')
    parser.add_argument('--gui', action='store_true')
    args = parser.parse_args()
    if sys.flags.optimize:
        raise RuntimeError('Optimized Python disables custody assertions')
    assert re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', args.label)
    assert re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*', args.module)
    assert 1 <= args.timeout <= 1800
    assert args.count >= 2
    if args.module == CAPACITY_MODULE:
        assert args.count == 2 and args.timeout == 1800 and not args.gui
    assert bool(args.cold_case) == bool(args.cold_case_sha256)
    assert_serial(('gmsh', 'ninja', 'make', 'gmake'))
    import critical_pins
    critical_pins.verify()
    helper = runpy.run_path(str(ROOT / 'stage_install.py'))
    inventory = helper['inventory']
    application = args.application.resolve(strict=True)
    assert application in (ROOT / 'FreeCAD-27.1.0.app', Path('/Applications/FreeCAD-27.1.0.app'))
    resources = application / 'Contents/Resources'
    wrapper = application / 'Contents/MacOS' / ('FreeCAD' if args.gui else 'FreeCADCmd')
    assert wrapper.is_file() and os.access(wrapper, os.X_OK)
    candidate = resources / 'data/NativeSolvers/ccx-force-accounting'
    assert sha(candidate) == NATIVE_SHA
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO,
                                   text=True, timeout=10).strip() == COMMIT
    app = Path('/Applications/FreeCAD-27.1.0.app')
    protected = [app, Path('/Users/zukomgwili/Library/Application Support/FreeCAD'),
                 Path('/Users/zukomgwili/Library/Application Support/FreeCAD Local'),
                 Path('/Users/zukomgwili/Library/Preferences/FreeCAD')]
    custody = {str(path): inventory(path) for path in protected if path.is_dir()}
    app_before = inventory(application)
    extra = cold_inputs(args.cold_case.resolve(strict=True), args.cold_case_sha256) if args.cold_case else []
    before = snapshot(extra)
    run = ROOT / args.label
    run.mkdir()
    write(run / 'private-custody-before.json', custody)
    write(run / 'private-application-before.json', app_before)
    environment = dict(os.environ)
    for key in list(environment):
        if key.startswith(('FREECAD_', 'CCX_', 'APPQA_', 'YWU_', 'YZK_', 'FIVEAR_', 'DYLD_', 'LD_')) or key in (
            'PYTHONHOME', 'PYTHONPATH', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
            environment.pop(key)
    for key in ('FREECAD_USER_HOME', 'FREECAD_USER_DATA', 'FREECAD_USER_TEMP',
                'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
        path = run / key.lower()
        path.mkdir()
        environment[key] = str(path)
    environment.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', OMP_NUM_THREADS='2',
                       TMPDIR=environment['FREECAD_USER_TEMP'], YWU_OUTPUT=str(run),
                       YWU_IDENTITY=str(run / 'identity.json'), YZK_OUTPUT=str(run))
    if args.cold_case:
        assert args.cold_case.resolve().is_relative_to(ROOT)
        environment['YWU_COLD_MANIFEST'] = str(args.cold_case.resolve(strict=True))
        environment['APPQA_COLD_MANIFEST'] = environment['YWU_COLD_MANIFEST']
        environment['APPQA_COLD_MANIFEST_SHA'] = args.cold_case_sha256
    environment['YWU_EXPECT_GUI'] = str(int(args.gui))
    environment.update(APPQA_APPLICATION=str(application), APPQA_MODE='gui' if args.gui else 'cmd',
                       APPQA_REPORT=str(run / 'identity.json'), APPQA_SUITES=json.dumps([args.module]))
    manifest = {'schema': 'FreeCAD-yzk-application-run-manifest-v1',
                'application': str(application), 'module': args.module, 'expected_count': args.count,
                'commit': COMMIT, 'revision': REVISION, 'candidate_sha256': NATIVE_SHA,
                'inputs': {'files': before}, 'cold_manifest': str(args.cold_case.resolve()) if args.cold_case else None,
                'cold_manifest_sha256': args.cold_case_sha256, 'installation_performed': False}
    write(run / 'manifest.json', manifest)
    environment.update(APPQA_MANIFEST=str(run / 'manifest.json'), APPQA_MANIFEST_SHA=sha(run / 'manifest.json'),
                       YZK_QA_MANIFEST=str(run / 'manifest.json'))
    command = [str(wrapper),
               '-u', str(run / 'user.cfg'), '-s', str(run / 'system.cfg'),
               '-P', str(ROOT), '-t', 'AppYzkIdentity', '-t', args.module]
    report = {'passed': False, 'application': str(application), 'source_build': str(BUILD),
              'module': args.module, 'inputs_before': before,
              'rebound_or_reused_stage_outputs': False, 'manifest_sha256': sha(run / 'manifest.json'),
              'installation_performed': False, 'stdin_is_DEVNULL': True}
    try:
        with null_stdin():
            report.update(run_bounded(command, cwd=REPO, log=run / 'run.log', timeout=args.timeout,
                                      environment=environment))
    except BaseException as error:
        report['error'] = repr(error)
    finally:
        report['inputs_after'] = snapshot(extra)
        report['manifest_unchanged'] = sha(run / 'manifest.json') == report['manifest_sha256']
        report['source_build_harness_unchanged'] = before == report['inputs_after']
        report['app_and_profiles_unchanged'] = all(inventory(Path(path)) == wanted
                                                  for path, wanted in custody.items())
        app_after = inventory(application)
        custody_after = {path: inventory(Path(path)) for path in custody}
        write(run / 'private-application-after.json', app_after)
        write(run / 'private-custody-after.json', custody_after)
        report['application_unchanged'] = app_after == app_before
        critical_pins.verify()
        report['critical_dependency_pins_unchanged'] = True
        report['critical_before_DESTDIR_sha256'] = sha(critical_pins.RECEIPT)
        report['application_inventory_before_sha256'] = sha(run / 'private-application-before.json')
        report['application_inventory_after_sha256'] = sha(run / 'private-application-after.json')
        report['custody_before_sha256'] = sha(run / 'private-custody-before.json')
        report['custody_after_sha256'] = sha(run / 'private-custody-after.json')
        identity = json.loads((run / 'identity.json').read_text()) if (run / 'identity.json').exists() else {}
        text = (run / 'run.log').read_text(errors='replace')
        counts = re.findall(r'^Ran (\d+) tests? in ([\d.]+)s\s*$', text, re.M)
        skipped = re.findall(r'^.*\.\.\. skipped .*$', text, re.M)
        report['identity_sha256'] = sha(run / 'identity.json') if identity else None
        report['unittest_counts'] = counts
        report['skipped_lines'] = skipped
        report['passed'] = bool(report.get('returncode') == 0 and identity.get('passed')
                                and len(counts) == 1 and int(counts[0][0]) == args.count
                                and args.count == identity.get('selected_suite', {}).get('count', -2) + 1
                                and not skipped and re.search(r'^OK\s*$', text, re.M)
                                and not re.search(r'^(FAILED\b|FAIL:|ERROR:|UNEXPECTED SUCCESS:)', text, re.M)
                                and report.get('child_reaped') and report.get('process_group_gone')
                                and not report.get('timed_out')
                                and report['source_build_harness_unchanged'] and report['manifest_unchanged']
                                and report['app_and_profiles_unchanged'] and report['application_unchanged'])
        selected = list(identity.get('selected_suite', {}).get('ids', []))
        if len(selected) != len(set(selected)):
            report.update(passed=False, repeated_selected_methods=True)
        for test_id in selected:
            pattern = '^' + re.escape(test_id.rsplit('.', 1)[-1]) + r' \(' + re.escape(test_id) + r'\)([^\n]*)$'
            hits = re.findall(pattern, text, re.M)
            if len(hits) != 1 or 'skipped' in hits[0]:
                report.update(passed=False, missing_or_skipped_native_method=test_id)
        try:
            assert_serial(('gmsh', 'ninja', 'make', 'gmake'))
            report['post_run_serial_guard_passed'] = True
        except BaseException as error:
            report.update(passed=False, post_run_serial_guard_passed=False,
                          post_run_serial_guard_error=repr(error))
        report['passed'] &= report['post_run_serial_guard_passed']
        if report['passed'] and args.module == CAPACITY_MODULE:
            try:
                report['capacity_witness'] = capacity_witness(run, text, candidate)
            except BaseException as error:
                report.update(passed=False, capacity_witness_error=repr(error))
        write(run / 'execution.json', report)
        print(json.dumps({key: value for key, value in report.items()
                          if key not in ('inputs_before', 'inputs_after')}, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
