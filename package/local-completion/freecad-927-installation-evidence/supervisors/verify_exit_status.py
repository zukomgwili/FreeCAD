"""FreeCAD-3sc: run permanent real-process regressions on one sealed app bundle.

Called only after the existing pinned CLI and native Cocoa identity gates pass.
The permanent driver bounds and reaps each child and creates isolated profiles.
This supervisor preserves exact logs and authenticates app and test-file custody.
"""
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
SCOPE = runpy.run_path(str(ROOT / 'stage_install.py'))
DRIVER, FIXTURE = SCOPE['EXIT_DRIVER'], SCOPE['EXIT_FIXTURE']
digest, inventory = SCOPE['digest'], SCOPE['inventory']
assert len(sys.argv) == 3
app = Path(sys.argv[1]).resolve(strict=True)
label = sys.argv[2]
assert label in ('stage', 'installed')
assert app == (SCOPE['STAGE'] if label == 'stage' else SCOPE['APP'])
revision, _ = SCOPE['compiled_identity']()
assert revision == SCOPE['REVISION']
for mode in ('cli', 'gui'):
    identity = json.loads((ROOT / f'{label}-{mode}/identity.json').read_text())
    assert identity['passed'] and identity['runtime'][-1] == SCOPE['COMMIT']
    assert identity['runtime'][3] == revision
    assert identity['root'] == str(app / 'Contents/Resources')
    assert bool(identity['gui_up']) == (mode == 'gui')
    if mode == 'gui':
        assert identity['cocoa_plugin'] == str(SCOPE['PREFIX'] /
            'lib/qt6/plugins/platforms/libqcocoa.dylib')
evidence = ROOT / f'{label}-exit-status'
evidence.mkdir(exist_ok=False)
(evidence / 'temp').mkdir()
before = inventory(app)
result = {'application': str(app), 'expected_commit': SCOPE['COMMIT'],
          'expected_revision': revision, 'passed': False, 'gates': [],
          'driver_sha256_before': digest(DRIVER),
          'fixture_sha256_before': digest(FIXTURE)}
started = time.monotonic()
try:
    for mode, name in (('cmd', 'FreeCADCmd'), ('gui', 'FreeCAD')):
        log_path = evidence / f'{mode}.log'
        environment = os.environ.copy()
        for key in ('PYTHONPATH', 'PYTHONHOME', 'FREECAD_USER_HOME', 'FREECAD_USER_DATA',
                    'FREECAD_USER_TEMP', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_DATA_HOME',
                    'FREECAD_9ZT_CCX', 'FREECAD_9ZT_PRODUCTION_CCX',
                    'CCX_FORCE_ACCOUNTING_REQUEST', 'CCX_9ZT_DIAGNOSTIC'):
            environment.pop(key, None)
        environment.update(PYTHONDONTWRITEBYTECODE='1',
                           PYTHONNOUSERSITE='1',
                           TMPDIR=str(evidence / 'temp'), QT_QPA_PLATFORM='cocoa')
        command = [sys.executable, str(DRIVER), '--executable',
                   str(app / 'Contents/MacOS' / name)]
        if mode == 'gui':
            command.append('--gui')
        gate = {'mode': mode, 'command': command, 'log': str(log_path),
                'passed': False, 'timed_out': False, 'process_reaped': False,
                'timeout_seconds': 510}
        result['gates'].append(gate)
        print(f'EXIT STATUS START {label} {mode}', flush=True)
        with log_path.open('xb') as output:
            process = subprocess.Popen(command, cwd=SCOPE['REPO'], env=environment,
                                       stdout=output, stderr=subprocess.STDOUT,
                                       start_new_session=True)
            gate['pid'] = process.pid
            try:
                gate['exit_code'] = process.wait(timeout=510)
            except subprocess.TimeoutExpired:
                gate['timed_out'] = True
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)
                gate['process_reaped'] = True
                raise
            gate['process_reaped'] = True
        assert gate['exit_code'] == 0, log_path
        log = log_path.read_text(errors='replace')
        counts = re.findall(r'^Ran (\d+) tests in [\d.]+s$', log, re.MULTILINE)
        summaries = re.findall(r'^(OK(?: \([^\n]*\))?)$', log, re.MULTILINE)
        expected_summary = 'OK (skipped=4)' if mode == 'cmd' else 'OK'
        assert counts == ['15'] and summaries == [expected_summary], log_path
        assert not re.search(r'^(?:FAILED\b|FAIL:|ERROR:)', log, re.MULTILINE), log_path
        gate.update(tests_run=15, skipped=4 if mode == 'cmd' else 0, passed=True)
        assert inventory(app) == before, 'Application changed during exit-status tests'
        print(f'EXIT STATUS PASS {label} {mode}', flush=True)
    SCOPE['compiled_identity']()
    result['driver_sha256_after'] = digest(DRIVER)
    result['fixture_sha256_after'] = digest(FIXTURE)
    assert result['driver_sha256_after'] == result['driver_sha256_before']
    assert result['fixture_sha256_after'] == result['fixture_sha256_before']
    result['app_inventory_unchanged'] = True
    result['passed'] = True
except BaseException as error:
    result['error'] = repr(error)
    raise
finally:
    result['elapsed_seconds'] = round(time.monotonic() - started, 3)
    with (evidence / 'summary.json').open('x') as output:
        output.write(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2), flush=True)
