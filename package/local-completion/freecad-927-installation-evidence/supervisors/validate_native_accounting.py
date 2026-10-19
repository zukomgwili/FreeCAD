"""FreeCAD-3sc staged/installed native accounting checks with isolated identity."""
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
evidence = ROOT / f'{label}-native-{mode}'
evidence.mkdir(exist_ok=False)
environment = dict(os.environ)
for key in ('PYTHONPATH', 'PYTHONHOME', 'FREECAD_9ZT_CCX', 'FREECAD_9ZT_PRODUCTION_CCX',
            'CCX_FORCE_ACCOUNTING_REQUEST', 'CCX_9ZT_DIAGNOSTIC'):
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
                   CONFIGURED_TEST_SUITES=json.dumps(['InstalledIdentity', 'FreeCAD9ztProductionWitness']),
                   SCRATCH_TEST_SUITES=json.dumps(['FreeCAD9ztProductionWitness']),
                   FREECAD_9ZT_OUTPUT=str(evidence), PYTHONDONTWRITEBYTECODE='1',
                   PYTHONNOUSERSITE='1', OMP_NUM_THREADS='2', TMPDIR=str(evidence / 'temp'))
observer = REPO / 'package/local-completion/FreeCAD9ztProductionWitness.py'
before = hashlib.sha256(observer.read_bytes()).hexdigest()
exe = app / 'Contents/MacOS' / ('FreeCAD' if mode == 'gui' else 'FreeCADCmd')
command = ['pixi', 'run', '--frozen', str(exe), '-u', str(evidence / 'user.cfg'),
           '-s', str(evidence / 'system.cfg'), '-P', str(ROOT),
           '-P', str(observer.parent), '-t', 'InstalledIdentity', '-t', 'FreeCAD9ztProductionWitness']
report = {'passed': False, 'application': str(app), 'expected_commit': COMMIT,
          'expected_revision': REVISION, 'command': command, 'observer_sha256': before,
          'timed_out': False, 'process_reaped': False, 'timeout_seconds': 180}
started = time.monotonic()
try:
    with (evidence / 'run.log').open('xb') as log:
        process = subprocess.Popen(command, cwd=REPO, env=environment, stdout=log,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        report['pid'] = process.pid
        try:
            status = process.wait(timeout=180)
        except subprocess.TimeoutExpired:
            report['timed_out'] = True
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
            raise
        finally:
            report['process_reaped'] = process.poll() is not None
    report['exit_code'] = status
    text = (evidence / 'run.log').read_text()
    assert status == 0 and not re.search(r'^(FAILED|FAIL:|ERROR:)', text, re.M), text[-5000:]
    assert re.findall(r'^Ran (\d+) tests? in ', text, re.M) == ['2']
    assert len(re.findall(r'^OK\s*$', text, re.M)) == 1
    identity = json.loads((evidence / 'identity.json').read_text())
    assert identity['passed'] and identity['runtime'][-1] == COMMIT
    assert identity['runtime'][3] == REVISION
    assert identity['root'] == str(app / 'Contents/Resources')
    assert bool(identity['gui_up']) == (mode == 'gui')
    assert identity['configured_test_count'] == 2
    receipts = list(evidence.glob('native-accounting-*/pipeline-receipt.json'))
    assert len(receipts) == 1
    data = json.loads(receipts[0].read_text())
    native = app / 'Contents/Resources/data/NativeSolvers/ccx-force-accounting'
    assert data['binary'] == str(native)
    assert data['binary_sha256'] == hashlib.sha256(native.read_bytes()).hexdigest()
    assert data['binary_sha256'] == OLD_NATIVE_SHA256
    if mode == 'gui':
        image = receipts[0].parent / 'native-accounting-ui.png'
        assert image.is_file() and image.stat().st_size > 10000
        report['screenshot'] = str(image)
    assert hashlib.sha256(observer.read_bytes()).hexdigest() == before
    report.update(passed=True, pipeline_receipt=str(receipts[0]), native_binary_sha256=data['binary_sha256'])
finally:
    report['elapsed_seconds'] = time.monotonic() - started
    with (evidence / 'summary.json').open('x') as stream:
        stream.write(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2), flush=True)
