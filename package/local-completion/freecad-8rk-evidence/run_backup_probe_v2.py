"""Bounded native backup regression in a new isolated dotted temporary path."""
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
TARGET = 'BackupPolicyTest.TimestampTargetHasNoExtension'
APP = Path('/Applications/FreeCAD-27.1.0.app')
PROFILES = tuple(Path('/Users/zukomgwili') / name for name in (
    'Library/Application Support/FreeCAD', 'Library/Application Support/FreeCAD Local',
    'Library/Preferences/FreeCAD'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def serial():
    names = {'FreeCAD', 'FreeCADCmd', 'ccx', 'ccx-force-accounting', 'ctest',
             'gmsh', 'ninja', 'make', 'gmake', 'App_tests_run', 'Base_tests_run'}
    rows = subprocess.check_output(['ps', '-axo', 'pid=,comm='], text=True, timeout=10)
    for line in rows.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) == 2 and Path(fields[1]).name in names:
            raise RuntimeError('Serial native guard: ' + line.strip())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('label')
    parser.add_argument('--dot-free', action='store_true')
    args = parser.parse_args()
    assert not __debug__ is False
    assert args.label and all(char.isalnum() or char == '-' for char in args.label)
    serial()
    assert sha(CORE) == CORE_SHA
    inventory = runpy.run_path(str(CORE))['inventory']
    protected = (APP, *PROFILES)
    before = {str(path): canonical(inventory(path)) for path in protected}
    inputs = {str(path): sha(path) for path in (
        Path(__file__), CORE, REPO / 'build/release/tests/App_tests_run',
        REPO / 'build/release/src/Build/Version.h')}
    run = ROOT / args.label
    run.mkdir()
    dotted = run / ('plainparent' if args.dot_free else 'dotted.parent')
    dotted.mkdir()
    environment = dict(os.environ)
    for key in tuple(environment):
        if key.startswith(('FREECAD_', 'CCX_', 'DYLD_', 'LD_', 'APPQA_')) or key in (
                'PYTHONPATH', 'PYTHONHOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME',
                'TMPDIR', 'TMP', 'TEMP', 'DESTDIR'):
            environment.pop(key)
    for key in ('FREECAD_USER_HOME', 'FREECAD_USER_DATA', 'FREECAD_USER_TEMP',
                'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
        path = run / key.lower()
        path.mkdir()
        environment[key] = str(path)
    environment.update(TMPDIR=str(dotted) + '/', TMP=str(dotted), TEMP=str(dotted),
                       PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', OMP_NUM_THREADS='2')
    command = ['pixi', 'run', '--frozen', 'build/release/tests/App_tests_run',
               '--gtest_filter=' + TARGET]
    log = run / 'run.log'
    started, child, timed_out = time.monotonic(), None, False
    try:
        with log.open('xb') as stream:
            child = subprocess.Popen(command, cwd=REPO, env=environment,
                                     stdin=subprocess.DEVNULL, stdout=stream,
                                     stderr=subprocess.STDOUT, start_new_session=True)
            try:
                child.wait(timeout=60)
            except subprocess.TimeoutExpired:
                timed_out = True
            finally:
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGTERM)
                    try:
                        child.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL)
                        child.wait(timeout=3)
    finally:
        after = {str(path): canonical(inventory(path)) for path in protected}
        backup_paths = sorted(path for path in run.rglob('*') if path.is_file() and path.suffix == '.FCBak')
        report = {
            'schema': 'FreeCAD-8rk-native-backup-probe-v1',
            'command': command, 'test': TARGET, 'temporary_directory': str(dotted),
            'returncode': child.returncode if child else None, 'timed_out': timed_out,
            'child_reaped': child is not None and child.poll() is not None,
            'elapsed_seconds': time.monotonic() - started,
            'native_test_passed': child is not None and child.returncode == 0 and not timed_out,
            'app_and_three_profiles_unchanged': before == after,
            'protected_sha256_before': before, 'protected_sha256_after': after,
            'inputs_unchanged': all(sha(path) == wanted for path, wanted in inputs.items()),
            'inputs': inputs, 'log_sha256': sha(log),
            'remaining_backup_files': [
                {'path': str(path), 'bytes': path.stat().st_size, 'sha256': sha(path),
                 'outside_requested_temporary_directory': not path.is_relative_to(dotted)}
                for path in backup_paths],
            'installation_performed': False,
        }
        serial()
        assert before == after and report['inputs_unchanged']
        with (run / 'execution.json').open('x') as stream:
            json.dump(report, stream, indent=2)
            stream.write('\n')
        print(json.dumps(report, indent=2))
    return child.returncode if child and not timed_out else 124


if __name__ == '__main__':
    raise SystemExit(main())
