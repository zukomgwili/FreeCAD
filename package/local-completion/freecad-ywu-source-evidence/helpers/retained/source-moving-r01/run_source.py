"""Bounded serial native source-build tests; never install or use live profiles."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
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
    files += [ROOT / 'oracle.json', BUILD / 'src/Build/Version.h', BUILD / 'bin/FreeCADCmd',
              BUILD / 'lib/libFreeCADApp.dylib', BUILD / 'data/NativeSolvers/ccx-force-accounting',
              REPO / 'package/calculix/force-accounting/forceaccounting.c',
              REPO / 'package/calculix/force-accounting/hooks.patch',
              REPO / 'package/calculix/force-accounting/contract.json']
    return {str(path): sha(path) for path in files if path.is_file()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('label')
    parser.add_argument('--module', default='YwuMovingPortGreen')
    parser.add_argument('--count', type=int, default=2)
    parser.add_argument('--timeout', type=int, default=240)
    args = parser.parse_args()
    assert re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', args.label)
    assert re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*', args.module)
    assert 1 <= args.timeout <= 600
    assert_serial(('gmsh', 'ninja', 'make', 'gmake'))
    helper = runpy.run_path('/private/tmp/freecad-5ar-install-qjCS3M/stage_install.py')
    inventory = helper['inventory']
    app = Path('/Applications/FreeCAD-27.1.0.app')
    protected = [app, Path('/Users/zukomgwili/Library/Application Support/FreeCAD'),
                 Path('/Users/zukomgwili/Library/Application Support/FreeCAD Local'),
                 Path('/Users/zukomgwili/Library/Preferences/FreeCAD')]
    custody = {str(path): inventory(path) for path in protected if path.is_dir()}
    before = snapshot()
    run = ROOT / args.label
    run.mkdir()
    write(run / 'private-custody-before.json', custody)
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
    command = ['pixi', 'run', '--frozen', str(BUILD / 'bin/FreeCADCmd'),
               '-u', str(run / 'user.cfg'), '-s', str(run / 'system.cfg'),
               '-P', str(ROOT), '-t', 'SourceYwuIdentity', '-t', args.module]
    report = {'passed': False, 'source_build': str(BUILD), 'inputs_before': before}
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
        identity = json.loads((run / 'identity.json').read_text()) if (run / 'identity.json').exists() else {}
        text = (run / 'run.log').read_text(errors='replace')
        counts = re.findall(r'^Ran (\d+) tests? in ([\d.]+)s\s*$', text, re.M)
        skipped = re.findall(r'^.*\.\.\. skipped .*$', text, re.M)
        report['identity_sha256'] = sha(run / 'identity.json') if identity else None
        report['unittest_counts'] = counts
        report['skipped_lines'] = skipped
        report['passed'] = bool(report.get('returncode') == 0 and identity.get('passed')
                                and len(counts) == 1 and int(counts[0][0]) == args.count
                                and not skipped and re.search(r'^OK\s*$', text, re.M)
                                and report.get('child_reaped') and report.get('process_group_gone')
                                and not report.get('timed_out')
                                and report['source_build_harness_unchanged']
                                and report['app_and_profiles_unchanged'])
        write(run / 'execution.json', report)
        print(json.dumps({key: value for key, value in report.items()
                          if key not in ('inputs_before', 'inputs_after')}, indent=2))
    assert_serial(('gmsh',))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
