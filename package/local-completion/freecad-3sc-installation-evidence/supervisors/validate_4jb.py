"""FreeCAD-3sc: bounded supervisor for the preserved 4jb native regression.

Requires FREECAD_4JB_WITNESS_PATH and FREECAD_4JB_WITNESS_TEST_COUNT. The
witness must contain the actual retained/minimal reproduction, genuine change
negatives, and exact save/reopen/rerun lifecycle assertions; this supervisor
does not pretend those details are implemented before diagnosis.
The historical private FREECAD_4JB environment/output protocol is retained.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

from harness_config import COMMIT, REVISION, OLD_NATIVE_SHA256

ROOT = Path(__file__).resolve().parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
assert len(sys.argv) == 4
app, label, mode = Path(sys.argv[1]).resolve(strict=True), sys.argv[2], sys.argv[3]
assert label in ('stage', 'installed') and mode in ('cmd', 'gui')
observer = Path(os.environ['FREECAD_4JB_WITNESS_PATH']).resolve(strict=True)
assert observer.suffix == '.py' and not observer.is_symlink()
module = observer.stem
assert re.fullmatch(r'[A-Za-z_]\w*', module)
tests = int(os.environ['FREECAD_4JB_WITNESS_TEST_COUNT'])
assert tests > 0
timeout = int(os.environ.get('FREECAD_4JB_WITNESS_TIMEOUT', '1800'))
assert 1 <= timeout <= 3600
evidence = ROOT / f'{label}-4jb-{mode}'
evidence.mkdir(exist_ok=False)
environment = dict(os.environ)
for key in ('PYTHONPATH', 'PYTHONHOME', 'FREECAD_9ZT_CCX',
            'FREECAD_9ZT_PRODUCTION_CCX', 'CCX_FORCE_ACCOUNTING_REQUEST',
            'CCX_9ZT_DIAGNOSTIC'):
    environment.pop(key, None)
for variable, subdir in (('FREECAD_USER_HOME', 'user'), ('FREECAD_USER_DATA', 'data'),
                        ('FREECAD_USER_TEMP', 'temp'), ('XDG_CONFIG_HOME', 'xdg-config'),
                        ('XDG_CACHE_HOME', 'xdg-cache'), ('XDG_DATA_HOME', 'xdg-data')):
    target = evidence / subdir
    target.mkdir()
    environment[variable] = str(target)
environment.update(EXPECTED_COMMIT=COMMIT, EXPECTED_REVISION=REVISION,
                   EXPECTED_RESOURCES=str(app / 'Contents/Resources'),
                   IDENTITY_REPORT=str(evidence / 'identity.json'),
                   CONFIGURED_TEST_SUITES=json.dumps(['InstalledIdentity', module]),
                   SCRATCH_TEST_SUITES=json.dumps([module]),
                   FREECAD_4JB_OUTPUT=str(evidence), PYTHONDONTWRITEBYTECODE='1',
                   PYTHONNOUSERSITE='1', OMP_NUM_THREADS='2',
                   TMPDIR=str(evidence / 'temp'))
before = hashlib.sha256(observer.read_bytes()).hexdigest()
exe = app / 'Contents/MacOS' / ('FreeCAD' if mode == 'gui' else 'FreeCADCmd')
command = ['pixi', 'run', '--frozen', str(exe), '-u', str(evidence / 'user.cfg'),
           '-s', str(evidence / 'system.cfg'), '-P', str(ROOT),
           '-P', str(observer.parent), '-t', 'InstalledIdentity', '-t', module]
report = {'passed': False, 'application': str(app), 'expected_commit': COMMIT,
          'expected_revision': REVISION, 'command': command,
          'observer': str(observer), 'observer_sha256': before,
          'timeout_seconds': timeout, 'engineering_design_accepted': False,
          'timed_out': False, 'process_reaped': False}
started = time.monotonic()
try:
    with (evidence / 'run.log').open('xb') as log:
        process = subprocess.Popen(command, cwd=REPO, env=environment, stdout=log,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        report['pid'] = process.pid
        try:
            report['exit_code'] = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            report['timed_out'] = True
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            raise
        finally:
            report['process_reaped'] = process.poll() is not None
    text = (evidence / 'run.log').read_text(errors='replace')
    assert report['exit_code'] == 0 and not re.search(r'^(FAILED|FAIL:|ERROR:)', text, re.M), text[-5000:]
    assert re.findall(r'^Ran (\d+) tests? in ', text, re.M) == [str(tests + 1)]
    assert len(re.findall(r'^OK\s*$', text, re.M)) == 1
    identity = json.loads((evidence / 'identity.json').read_text())
    assert identity['passed'] and identity['runtime'][-1] == COMMIT
    assert identity['runtime'][3] == REVISION
    assert identity['root'] == str(app / 'Contents/Resources')
    assert bool(identity['gui_up']) == (mode == 'gui')
    assert identity['configured_test_count'] == tests + 1
    native = app / 'Contents/Resources/data/NativeSolvers/ccx-force-accounting'
    assert hashlib.sha256(native.read_bytes()).hexdigest() == OLD_NATIVE_SHA256
    assert hashlib.sha256(observer.read_bytes()).hexdigest() == before
    report.update(passed=True, native_binary_sha256=OLD_NATIVE_SHA256,
                  witness_tests=tests, unittest_tests=tests + 1)
finally:
    report['elapsed_seconds'] = time.monotonic() - started
    with (evidence / 'summary.json').open('x') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
print(json.dumps(report, indent=2), flush=True)
