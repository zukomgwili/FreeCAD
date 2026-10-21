"""Bounded isolated installed-app observer. Never writes installed files."""
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import signal
import subprocess
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
APP = Path('/Applications/FreeCAD-27.1.0.app')
helper = runpy.run_path(str(REPO / 'package/local-completion/freecad-ywu-installation-evidence/private/stage_install.py'))
inventory = helper['inventory']


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def serial():
    output = subprocess.check_output(['ps', '-axo', 'pid=,comm='], text=True, timeout=10)
    active = [line for line in output.splitlines() if re.search(
        r'(?:^|/)(?:FreeCAD|FreeCADCmd|tests_run|gmsh|ccx(?:-force-accounting)?|ctest|ninja|gmake|make)\s*$', line)]
    assert not active, active


def fingerprint():
    roots = [APP, *helper['PROFILE_CANDIDATES']]
    return {str(path): hashlib.sha256(json.dumps(inventory(path), sort_keys=True,
        separators=(',', ':')).encode()).hexdigest() if path.exists() else None for path in roots}


def group_exists(pid):
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False


def main():
    serial()
    run = ROOT / 'native-state-red'
    run.mkdir()
    before = fingerprint()
    inputs = {str(path): digest(path) for path in ROOT.glob('*.py')}
    env = dict(os.environ)
    for key in tuple(env):
        if key.startswith(('FREECAD_', 'CCX_', 'DYLD_', 'LD_', 'APPQA_', 'F8_', 'F9II_')) or key in (
            'PYTHONPATH', 'PYTHONHOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME',
            'TMPDIR', 'TMP', 'TEMP', 'DESTDIR'):
            env.pop(key)
    for key in ('FREECAD_USER_HOME', 'FREECAD_USER_DATA', 'FREECAD_USER_TEMP',
                'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
        path = run / key.lower()
        path.mkdir()
        env[key] = str(path)
    temporary = run / 'tmp'
    temporary.mkdir()
    env.update(TMPDIR=str(temporary) + '/', TMP=str(temporary), TEMP=str(temporary),
               PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', OMP_NUM_THREADS='2',
               F9II_BASELINE=str(run))
    command = [str(APP / 'Contents/MacOS/FreeCADCmd'), '-u', str(run / 'user.cfg'),
               '-s', str(run / 'system.cfg'), '-P', str(ROOT), '-t', 'ContactStateRed']
    started = time.monotonic()
    timed_out = False
    with (run / 'run.log').open('xb') as output:
        child = subprocess.Popen(command, cwd=REPO, env=env, stdin=subprocess.DEVNULL,
                                 stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            child.wait(timeout=180)
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
    text = (run / 'run.log').read_text()
    counts = re.findall(r'^Ran (\d+) tests? in [0-9.]+s$', text, re.M)
    after = fingerprint()
    result = {'command': command, 'returncode': child.returncode, 'timed_out': timed_out,
              'child_reaped': child.poll() is not None, 'group_gone': not group_exists(child.pid),
              'elapsed_seconds': time.monotonic() - started,
              'protected_before': before, 'protected_after': after,
              'inputs_unchanged': inputs == {path: digest(Path(path)) for path in inputs},
              'log_sha256': digest(run / 'run.log'), 'test_counts': counts}
    result['passed'] = bool(child.returncode == 0 and not timed_out and counts == ['1']
        and len(re.findall(r'^OK$', text, re.M)) == 1 and not re.search(
            r'^(?:FAILED|FAIL:|ERROR:|UNEXPECTED SUCCESS)', text, re.M)
        and before == after and result['inputs_unchanged'] and result['child_reaped']
        and result['group_gone'] and (run / 'baseline.json').is_file())
    (run / 'execution.json').write_text(json.dumps(result, indent=2) + '\n')
    serial()
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
