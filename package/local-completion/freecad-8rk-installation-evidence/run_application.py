"""Run two native save/identity checks, plus GUI controls, in one literal app."""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

import critical_pins
import run_gate
import stage_install as install

ROOT = Path(__file__).resolve().parent


def sha(path):
    return install.digest(path)


def inputs(extra=()):
    paths = list(ROOT.glob('*.py')) + list(extra)
    return {str(path): sha(path) for path in paths}


def profiles():
    critical_pins.verify()
    return {str(path): install.canonical_sha(install.inventory(path)) for path in install.PROFILES}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('location', choices=('stage', 'installed'))
    parser.add_argument('mode', choices=('cmd', 'gui'))
    args = parser.parse_args()
    assert __debug__
    run_gate.serial()
    install.compiled_identity()
    application = install.STAGE if args.location == 'stage' else install.APP
    assert application.resolve(strict=True) == application and not application.is_symlink()
    sealed = json.loads((ROOT / 'stage-inventory.json').read_text())
    assert install.inventory(application) == sealed
    install.verify(application)
    original_app = install.canonical_sha(install.inventory(install.APP))
    before_profiles = profiles()
    label = args.location + '-' + args.mode
    run = ROOT / label
    run.mkdir()
    env = dict(os.environ)
    for key in tuple(env):
        if key.startswith(('FREECAD_', 'CCX_', 'DYLD_', 'LD_', 'APPQA_', 'F8_')) or key in (
            'PYTHONPATH', 'PYTHONHOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME',
            'TMPDIR', 'TMP', 'TEMP', 'DESTDIR'):
            env.pop(key)
    for key in ('FREECAD_USER_HOME', 'FREECAD_USER_DATA', 'XDG_CONFIG_HOME',
                'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
        path = run / key.lower()
        path.mkdir()
        env[key] = str(path)
    temporary = run / 'dotted.parent'
    temporary.mkdir()
    gui = args.mode == 'gui'
    resources = application / 'Contents/Resources'
    native_names = ['bin/' + ('FreeCAD' if gui else 'FreeCADCmd'), 'lib/FreeCAD.so',
                    'lib/libFreeCADBase.dylib', 'lib/libFreeCADApp.dylib']
    if gui:
        native_names += ['lib/FreeCADGui.so', 'lib/libFreeCADGui.dylib']
    native = {str(resources / name): sha(resources / name) for name in native_names}
    manifest = {'application': str(application), 'commit': install.COMMIT,
                'revision': install.REVISION, 'gui': gui, 'expected_native_files': native,
                'report_path': str(run / 'regression.json'),
                'witness_path': str(run / 'witness')}
    install.write_json(run / 'manifest.json', manifest)
    env.update(TMPDIR=str(temporary) + '/', TMP=str(temporary), TEMP=str(temporary),
               FREECAD_USER_TEMP=str(temporary), PYTHONDONTWRITEBYTECODE='1',
               PYTHONNOUSERSITE='1', OMP_NUM_THREADS='2',
               F8_INSTALL_MANIFEST=str(run / 'manifest.json'))
    command = [str(application / 'Contents/MacOS' / ('FreeCAD' if gui else 'FreeCADCmd')),
               '-u', str(run / 'user.cfg'), '-s', str(run / 'system.cfg'),
               '-P', str(ROOT), '-t', 'App8rkRegression']
    expected = 10 if gui else 2
    if gui:
        command += ['-t', 'TestFemGui']
    before = inputs([run / 'manifest.json', *map(Path, native)])
    timed_out, started = False, time.monotonic()
    with (run / 'run.log').open('xb') as output:
        child = subprocess.Popen(command, cwd=install.REPO, env=env, stdin=subprocess.DEVNULL,
                                 stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            child.wait(timeout=240)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            for number in (signal.SIGTERM, signal.SIGKILL):
                if child.poll() is None or run_gate.group_exists(child.pid):
                    try:
                        os.killpg(child.pid, number)
                    except ProcessLookupError:
                        pass
                    try:
                        child.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        pass
    text = (run / 'run.log').read_text()
    counts = re.findall(r'^Ran (\d+) tests? in [0-9.]+s$', text, re.M)
    valid = (counts == [str(expected)] and len(re.findall(r'^OK$', text, re.M)) == 1
             and not re.search(r'^(?:FAILED|FAIL:|ERROR:|UNEXPECTED SUCCESS)', text, re.M)
             and not re.search(r'\.\.\. skipped\b', text))
    receipt_path = run / 'regression.json'
    regression = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
    valid = valid and regression.get('passed') is True and regression.get('commit') == install.COMMIT
    after = inputs([run / 'manifest.json', *map(Path, native)])
    current = install.inventory(application)
    report = {'schema': 'FreeCAD-8rk-literal-application-gate-v1', 'application': str(application),
              'mode': args.mode, 'source_commit': install.COMMIT, 'command': command,
              'expected_tests': expected, 'executed_tests': int(counts[0]) if len(counts) == 1 else 0,
              'returncode': child.returncode, 'timed_out': timed_out,
              'child_reaped': child.poll() is not None, 'process_group_gone': not run_gate.group_exists(child.pid),
              'elapsed_seconds': time.monotonic() - started, 'inputs_before': before, 'inputs_after': after,
              'inputs_unchanged': before == after, 'application_unchanged': current == sealed,
              'application_inventory_sha256': install.canonical_sha(current),
              'profiles_and_dependencies_unchanged': before_profiles == profiles(),
              'original_app_unchanged': original_app == install.canonical_sha(install.inventory(install.APP)),
              'log_sha256': sha(run / 'run.log'),
              'regression_sha256': sha(receipt_path) if receipt_path.exists() else None,
              'semantic_tests_passed': bool(valid)}
    run_gate.serial()
    install.compiled_identity()
    install.verify(application)
    report['passed'] = bool(child.returncode == 0 and not timed_out and valid
        and report['child_reaped'] and report['process_group_gone'] and report['inputs_unchanged']
        and report['application_unchanged'] and report['profiles_and_dependencies_unchanged']
        and report['original_app_unchanged'])
    install.write_json(run / 'execution.json', report)
    print(json.dumps({k: v for k, v in report.items() if k not in ('inputs_before', 'inputs_after')}, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
