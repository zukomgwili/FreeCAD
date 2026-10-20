"""Serial installed-application reproduction; isolated profiles and input custody."""
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
APP = Path('/Applications/FreeCAD-27.1.0.app')
sys.path.insert(0, str(ROOT))
from process_control import assert_serial, run_bounded


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, obj):
    with path.open('x') as stream:
        stream.write(json.dumps(obj, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('label')
    args = parser.parse_args()
    assert re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', args.label)
    assert_serial(('gmsh', 'ninja', 'make', 'gmake'))
    helper = runpy.run_path('/private/tmp/freecad-5ar-install-qjCS3M/stage_install.py')
    inventory = helper['inventory']
    profiles = tuple(Path('/Users/zukomgwili/Library/Application Support') / name
                     for name in ('FreeCAD', 'FreeCAD Local'))
    profiles += (Path('/Users/zukomgwili/Library/Preferences/FreeCAD'),)
    private_sources = sorted(ROOT.glob('*.py'))
    source_paths = sorted((REPO / 'src/Mod/Fem').rglob('*.py'))
    source_paths += list((REPO / 'package/calculix/force-accounting').glob('*'))
    source_paths += [REPO / 'pixi.toml', REPO / 'pixi.lock', REPO / 'build/release/CMakeCache.txt',
                     REPO / 'build/release/src/Build/Version.h', ROOT / 'oracle.json',
                     Path('/private/tmp/freecad-5ar-install-qjCS3M/stage_install.py'), *private_sources]
    source_paths = [path for path in source_paths if path.is_file()]
    source_before = {str(path): sha(path) for path in source_paths}
    app_before = inventory(APP)
    profiles_before = {str(path): inventory(path) for path in profiles if path.is_dir()}
    run = ROOT / args.label
    run.mkdir()
    write(run / 'private-baseline.json', {'application': app_before, 'profiles': profiles_before})
    environment = dict(os.environ)
    for key in list(environment):
        if key.startswith(('FREECAD_', 'CCX_', 'APPQA_', 'YWU_')) or key in (
            'PYTHONHOME', 'PYTHONPATH', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
            environment.pop(key)
    for key in ('FREECAD_USER_HOME', 'FREECAD_USER_DATA', 'FREECAD_USER_TEMP',
                'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
        path = run / key.lower()
        path.mkdir()
        environment[key] = str(path)
    environment.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', OMP_NUM_THREADS='2',
                       TMPDIR=environment['FREECAD_USER_TEMP'], APPQA_APPLICATION=str(APP),
                       APPQA_MODE='cmd', APPQA_REPORT=str(run / 'identity.json'),
                       APPQA_SUITES='["YwuMovingPortWitness"]', YWU_OUTPUT=str(run))
    command = [str(APP / 'Contents/MacOS/FreeCADCmd'), '-u', str(run / 'user.cfg'),
               '-s', str(run / 'system.cfg'), '-P', str(ROOT), '-t', 'AppNativeIdentity',
               '-t', 'YwuMovingPortWitness']
    report = {'passed': False, 'application': str(APP), 'label': args.label,
              'source_before': source_before, 'no_Oomakhi_model_opened': True}
    try:
        report.update(run_bounded(command, cwd=REPO, log=run / 'run.log', timeout=240,
                                  environment=environment))
    except BaseException as error:
        report['error'] = repr(error)
    finally:
        source_after = {str(path): sha(path) for path in source_paths}
        report['source_and_harness_unchanged'] = source_before == source_after
        report['application_unchanged'] = app_before == inventory(APP)
        report['profiles_unchanged'] = all(inventory(Path(path)) == wanted
                                           for path, wanted in profiles_before.items())
        report['source_after'] = source_after
        if (run / 'identity.json').is_file():
            identity = json.loads((run / 'identity.json').read_text())
            report['identity_passed'] = identity['passed']
            report['identity_sha256'] = sha(run / 'identity.json')
            report['runtime'] = identity['runtime']
        text = (run / 'run.log').read_text(errors='replace')
        report['unittest_counts'] = re.findall(r'^Ran (\d+) tests? in ([\d.]+)s\s*$', text, re.M)
        report['unittest_failed'] = bool(re.search(r'^(FAILED\b|ERROR:|FAIL:)', text, re.M))
        report['passed'] = bool(report.get('returncode') == 0 and report.get('identity_passed')
                                and not report['unittest_failed'] and 'OK\n' in text)
        custody = all(report[key] for key in ('source_and_harness_unchanged',
                                             'application_unchanged', 'profiles_unchanged'))
        report['passed'] = report['passed'] and custody
        write(run / 'execution.json', report)
        print(json.dumps({key: value for key, value in report.items()
                          if key not in ('source_before', 'source_after')}, indent=2))
    assert_serial(('gmsh',))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
