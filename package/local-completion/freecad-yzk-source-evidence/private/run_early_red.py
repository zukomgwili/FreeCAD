"""Serial isolated one-test preflight RED; installed product imports unchanged."""
import sys
sys.dont_write_bytecode = True
import argparse
import hashlib
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
REPRO = ROOT / 'repro'
sys.path.insert(0, str(ROOT))
from process_control import assert_serial, run_bounded
sys.path.insert(0, str(REPRO))
import run_repro as helpers


def write(path, value):
    with path.open('x') as stream:
        stream.write(json.dumps(value, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('label')
    args = parser.parse_args()
    assert re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', args.label)
    assert_serial(('gmsh', 'ninja', 'make', 'gmake'))
    app = Path('/Applications/FreeCAD-27.1.0.app')
    watched = [app, Path('/Users/zukomgwili/Library/Application Support/FreeCAD'),
               Path('/Users/zukomgwili/Library/Application Support/FreeCAD Local'),
               Path('/Users/zukomgwili/Library/Preferences/FreeCAD')]
    before = {str(path): helpers.inventory(path) for path in watched if path.is_dir()}
    pins = helpers.inputs()
    for path in [Path(__file__), ROOT / 'YzkPreflightRed.py',
                 Path('/Users/zukomgwili/src/FreeCAD/src/Mod/Fem/femtest/app/test_force_accounting.py')]:
        pins[str(path)] = helpers.sha(path)
    run = ROOT / args.label
    run.mkdir()
    write(run / 'private-custody-before.json', before)
    env = dict(os.environ)
    for key in list(env):
        if key.startswith(('FREECAD_', 'CCX_', 'APPQA_', 'YWU_', 'YZK_', 'FIVEAR_')) or key in (
            'PYTHONHOME', 'PYTHONPATH', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'
        ):
            env.pop(key)
    for key in ('FREECAD_USER_HOME', 'FREECAD_USER_DATA', 'FREECAD_USER_TEMP',
                'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
        directory = run / key.lower()
        directory.mkdir()
        env[key] = str(directory)
    env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', OMP_NUM_THREADS='2',
               TMPDIR=env['FREECAD_USER_TEMP'], YZK_OUTPUT=str(run))
    command = [str(app / 'Contents/MacOS/FreeCADCmd'), '-u', str(run / 'user.cfg'),
               '-s', str(run / 'system.cfg'), '-P', str(REPRO), '-P', str(ROOT),
               '-t', 'InstalledIdentity', '-t', 'YzkPreflightRed']
    report = {'passed': False, 'scope': 'New public one-test regression against installed old product',
              'not_source_build_or_physical_solver_qualification': True, 'inputs_before': pins}
    try:
        report.update(run_bounded(command, cwd=ROOT, log=run / 'run.log', timeout=120, environment=env))
    finally:
        after = {path: helpers.inventory(Path(path)) for path in before}
        write(run / 'private-custody-after.json', after)
        report['app_and_profiles_unchanged'] = before == after
        report['inputs_unchanged'] = all(helpers.sha(path) == wanted for path, wanted in pins.items())
        identity = json.loads((run / 'identity.json').read_text()) if (run / 'identity.json').is_file() else {}
        text = (run / 'run.log').read_text(errors='replace')
        report['identity_passed'] = identity.get('passed') is True
        report['unittest_counts'] = re.findall(r'^Ran (\d+) tests? in ([\d.]+)s\s*$', text, re.M)
        report['log_sha256'] = helpers.sha(run / 'run.log')
        report['passed'] = bool(report.get('returncode') == 0 and report['identity_passed']
                                and report['unittest_counts'] and report['unittest_counts'][0][0] == '2'
                                and re.search(r'^OK\s*$', text, re.M)
                                and not re.search(r'^(FAILED\b|FAIL:|ERROR:|UNEXPECTED SUCCESS:)', text, re.M)
                                and report['app_and_profiles_unchanged'] and report['inputs_unchanged']
                                and report.get('child_reaped') and report.get('process_group_gone')
                                and not report.get('timed_out'))
        write(run / 'execution.json', report)
        print(json.dumps({key: value for key, value in report.items() if key != 'inputs_before'}, indent=2))
    assert_serial(('gmsh',))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
