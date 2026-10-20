"""Bounded serial app-location tests; never install or use live profiles."""
import argparse
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


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    with path.open('x') as stream:
        stream.write(json.dumps(value, indent=2) + '\n')


def snapshot():
    files = sorted((REPO / 'src/Mod/Fem').rglob('*.py')) + sorted(ROOT.glob('*.py'))
    files += [ROOT / 'oracle.json', ROOT / 'endload-oracle.json',
              ROOT / 'ordinary-oracle.json', ROOT / 'oracle-spec-proposal.json',
              BUILD / 'src/Build/Version.h', BUILD / 'bin/FreeCADCmd', BUILD / 'bin/FreeCAD',
              BUILD / 'Mod/Fem/Fem.so', BUILD / 'Mod/Fem/FemGui.so',
              BUILD / 'lib/libFreeCADApp.dylib', BUILD / 'data/NativeSolvers/ccx-force-accounting',
              REPO / 'package/calculix/force-accounting/forceaccounting.c',
              REPO / 'package/calculix/force-accounting/hooks.patch',
              REPO / 'package/calculix/force-accounting/contract.json']
    return {str(path): sha(path) for path in files if path.is_file()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('application', type=Path)
    parser.add_argument('label')
    parser.add_argument('--module', default='TestFemApp')
    parser.add_argument('--count', type=int, default=396)
    parser.add_argument('--timeout', type=int, default=240)
    parser.add_argument('--cold-case', type=Path)
    parser.add_argument('--gui', action='store_true')
    args = parser.parse_args()
    assert re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', args.label)
    assert re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*', args.module)
    assert 1 <= args.timeout <= 600
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
    assert sha(resources / 'data/NativeSolvers/ccx-force-accounting') == '2d59adb06736801f730de077a5f3dbfcfba8c0a430636e5814e5582606b5c89b'
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip() == '6cdc1affda07ac4e3b45a98097b7ae11039c80c6'
    app = Path('/Applications/FreeCAD-27.1.0.app')
    protected = [app, Path('/Users/zukomgwili/Library/Application Support/FreeCAD'),
                 Path('/Users/zukomgwili/Library/Application Support/FreeCAD Local'),
                 Path('/Users/zukomgwili/Library/Preferences/FreeCAD')]
    custody = {str(path): inventory(path) for path in protected if path.is_dir()}
    app_before = inventory(application)
    before = snapshot()
    run = ROOT / args.label
    run.mkdir()
    write(run / 'private-custody-before.json', custody)
    write(run / 'private-application-before.json', app_before)
    environment = dict(os.environ)
    for key in list(environment):
        if key.startswith(('FREECAD_', 'CCX_', 'APPQA_', 'YWU_', 'FIVEAR_')) or key in (
            'PYTHONHOME', 'PYTHONPATH', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
            environment.pop(key)
    for key in ('FREECAD_USER_HOME', 'FREECAD_USER_DATA', 'FREECAD_USER_TEMP',
                'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
        path = run / key.lower()
        path.mkdir()
        environment[key] = str(path)
    environment.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', OMP_NUM_THREADS='2',
                       TMPDIR=environment['FREECAD_USER_TEMP'], YWU_OUTPUT=str(run),
                       YWU_IDENTITY=str(run / 'identity.json'))
    if args.cold_case:
        assert args.cold_case.resolve().is_relative_to(ROOT)
        environment['YWU_COLD_MANIFEST'] = str(args.cold_case.resolve(strict=True))
    environment['YWU_EXPECT_GUI'] = str(int(args.gui))
    environment.update(APPQA_APPLICATION=str(application), APPQA_MODE='gui' if args.gui else 'cmd',
                       APPQA_REPORT=str(run / 'identity.json'), APPQA_SUITES=json.dumps([args.module]))
    command = [str(wrapper),
               '-u', str(run / 'user.cfg'), '-s', str(run / 'system.cfg'),
               '-P', str(ROOT), '-t', 'AppYwuIdentity', '-t', args.module]
    report = {'passed': False, 'application': str(application), 'source_build': str(BUILD),
              'module': args.module, 'inputs_before': before,
              'rebound_or_reused_stage_outputs': False}
    try:
        report.update(run_bounded(command, cwd=REPO, log=run / 'run.log', timeout=args.timeout,
                                  environment=environment))
    except BaseException as error:
        report['error'] = repr(error)
    finally:
        report['inputs_after'] = snapshot()
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
                                and report['source_build_harness_unchanged']
                                and report['app_and_profiles_unchanged'] and report['application_unchanged'])
        selected = set(identity.get('selected_suite', {}).get('ids', []))
        for test_id in set(identity.get('registered_native_ids', [])) & selected:
            pattern = '^' + re.escape(test_id.rsplit('.', 1)[-1]) + r' \(' + re.escape(test_id) + r'\)([^\n]*)$'
            hits = re.findall(pattern, text, re.M)
            if len(hits) != 1 or 'skipped' in hits[0]:
                report.update(passed=False, missing_or_skipped_native_method=test_id)
        write(run / 'execution.json', report)
        print(json.dumps({key: value for key, value in report.items()
                          if key not in ('inputs_before', 'inputs_after')}, indent=2))
    assert_serial(('gmsh',))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
