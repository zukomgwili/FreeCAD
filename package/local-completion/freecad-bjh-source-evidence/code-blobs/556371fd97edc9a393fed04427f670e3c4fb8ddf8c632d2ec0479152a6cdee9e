"""Root-only bounded source gates; every gate uses isolated dotted temporary storage."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import signal
import subprocess
import time

ROOT = Path(__file__).resolve().parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
CORE = REPO / 'package/local-completion/freecad-ywu-installation-evidence/private/stage_install.py'
CORE_SHA = 'cca627502a56b6c9b4aefa4a970172c51e42e2dde834000decca65fd44ab46d9'
APP = Path('/Applications/FreeCAD-27.1.0.app')
PROFILES = tuple(Path('/Users/zukomgwili') / name for name in (
    'Library/Application Support/FreeCAD', 'Library/Application Support/FreeCAD Local',
    'Library/Preferences/FreeCAD'))
SOURCE_FILES = ('src/Base/FileInfo.cpp', 'tests/src/Base/FileInfo.cpp',
                'tests/src/App/BackupPolicy.cpp')
PREFIX = ['pixi', 'run', '--frozen']
COMMANDS = {
    'build-tests': PREFIX + ['cmake', '--build', 'build/release', '--target',
                            'Base_tests_run', 'App_tests_run', '--parallel', '8'],
    'base-regressions': PREFIX + ['build/release/tests/Base_tests_run',
                                  '--gtest_filter=FileInfoExtensionTest.*'],
    'backup-regression': PREFIX + ['build/release/tests/App_tests_run',
        '--gtest_filter=BackupPolicyTest.TimestampExtensionlessTargetStaysInDottedDirectory'],
    'base-all': PREFIX + ['build/release/tests/Base_tests_run'],
    'backup-all': PREFIX + ['build/release/tests/App_tests_run', '--gtest_filter=BackupPolicyTest.*'],
    'build': PREFIX + ['cmake', '--build', 'build/release', '--parallel', '8'],
    'ctest': PREFIX + ['ctest', '--test-dir', 'build/release', '--output-on-failure',
                      '--parallel', '1', '--timeout', '60'],
}


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def serial():
    rows = subprocess.check_output(['ps', '-axo', 'pid=,comm='], text=True, timeout=10)
    names = {'FreeCAD', 'FreeCADCmd', 'ctest', 'gmsh', 'ccx', 'ccx-force-accounting',
             'ninja', 'make', 'gmake'}
    for line in rows.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) == 2:
            name = Path(fields[1]).name
            if name in names or name.lower().endswith('_tests_run'):
                raise RuntimeError('Serial native guard: ' + line.strip())


def group_exists(pid):
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('label')
    parser.add_argument('mode', choices=COMMANDS)
    args = parser.parse_args()
    assert __debug__ and args.label and all(c.isalnum() or c == '-' for c in args.label)
    serial()
    assert sha(CORE) == CORE_SHA
    inventory = runpy.run_path(str(CORE))['inventory']
    protected = (APP, *PROFILES)
    def custody():
        return {str(path): hashlib.sha256(json.dumps(inventory(path), sort_keys=True).encode()).hexdigest()
                for path in protected}
    def inputs():
        paths = [Path(__file__), CORE, REPO / 'pixi.toml', REPO / 'pixi.lock']
        paths += [REPO / name for name in SOURCE_FILES]
        return {str(path): sha(path) for path in paths}
    before, source_before = custody(), inputs()
    run = ROOT / args.label
    run.mkdir()
    temp = run / 'dotted.parent'
    temp.mkdir()
    environment = dict(os.environ)
    for key in tuple(environment):
        if key.startswith(('FREECAD_', 'CCX_', 'DYLD_', 'LD_', 'APPQA_', 'RO1_')) or key in (
            'PYTHONPATH', 'PYTHONHOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME',
            'TMPDIR', 'TMP', 'TEMP', 'DESTDIR'):
            environment.pop(key)
    for key in ('FREECAD_USER_HOME', 'FREECAD_USER_DATA', 'XDG_CONFIG_HOME',
                'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
        path = run / key.lower()
        path.mkdir()
        environment[key] = str(path)
    environment.update(FREECAD_USER_TEMP=str(temp), TMPDIR=str(temp) + '/',
                       TMP=str(temp), TEMP=str(temp), PYTHONDONTWRITEBYTECODE='1',
                       PYTHONNOUSERSITE='1', OMP_NUM_THREADS='2')
    command = COMMANDS[args.mode]
    report = {'schema': 'FreeCAD-8rk-isolated-native-gate-v1', 'mode': args.mode,
              'command': command, 'source_inputs_before': source_before,
              'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO,
                                                       text=True, timeout=10).strip(),
              'isolated_temporary_directory': str(temp), 'dot_free_substitution': False,
              'installation_performed': False}
    child, timed_out, started = None, False, time.monotonic()
    try:
        with (run / 'run.log').open('xb') as output:
            child = subprocess.Popen(command, cwd=REPO, env=environment, stdin=subprocess.DEVNULL,
                                     stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                child.wait(timeout=900)
            except subprocess.TimeoutExpired:
                timed_out = True
            finally:
                for number in (signal.SIGTERM, signal.SIGKILL):
                    if child.poll() is None or group_exists(child.pid):
                        try:
                            os.killpg(child.pid, number)
                        except ProcessLookupError:
                            pass
                        try:
                            child.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            pass
        report.update(returncode=child.returncode, timed_out=timed_out,
                      child_reaped=child.poll() is not None,
                      process_group_gone=not group_exists(child.pid))
    finally:
        report['elapsed_seconds'] = time.monotonic() - started
        report['source_inputs_after'] = inputs()
        report['source_and_supervisor_unchanged'] = source_before == report['source_inputs_after']
        report['protected_before'], report['protected_after'] = before, custody()
        report['app_and_three_profiles_unchanged'] = before == report['protected_after']
        report['log_sha256'] = sha(run / 'run.log')
        serial()
        report['passed'] = bool(report.get('returncode') == 0 and not timed_out
            and report.get('child_reaped') and report.get('process_group_gone')
            and report['source_and_supervisor_unchanged'] and report['app_and_three_profiles_unchanged'])
        with (run / 'execution.json').open('x') as stream:
            json.dump(report, stream, indent=2)
            stream.write('\n')
        print(json.dumps({key: value for key, value in report.items()
            if key not in ('source_inputs_before', 'source_inputs_after', 'protected_before', 'protected_after')}, indent=2))
    return 0 if report['passed'] else report.get('returncode') or 1


if __name__ == '__main__':
    raise SystemExit(main())
