"""FreeCAD-3sc serial application gates with bounded isolated child supervisors.

Adapted from the verified 4jb installer; runtime pins come only from the shared
private harness_config, never from a historical installation receipt.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from harness_config import COMMIT, REVISION

ROOT = Path(__file__).resolve().parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
assert len(sys.argv) == 3
app = Path(sys.argv[1]).resolve(strict=True)
label = sys.argv[2]
assert label in ('stage', 'installed')
result_path = ROOT / f'{label}-sequence-result.json'
assert not result_path.exists()
modes = ('create', 'reopen', 'cli', 'features', 'gui', 'equilibrium',
         'mixed-create', 'mixed-reopen', 'area-create', 'area-reopen')
runner = ROOT / 'validate_install.py'
identity = ROOT / 'InstalledIdentity.py'
status_runner = ROOT / 'verify_exit_status.py'
protected = [ROOT / name for name in (
    'run_gate_sequence.py', 'validate_install.py', 'InstalledIdentity.py',
    'verify_exit_status.py', 'InstalledExitWitness.py',
    'validate_native_accounting.py', 'validate_4jb.py', 'harness_config.py')]
original = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in protected}
environment = os.environ.copy()
environment.update(EXPECTED_COMMIT=COMMIT,
                   EXPECTED_REVISION=REVISION, PYTHONDONTWRITEBYTECODE='1')
result = {'label': label, 'application': str(app), 'passed': False, 'gates': [],
          'runner_sha256_before': original}
started = time.monotonic()
try:
    for mode in modes:
        print(f'GATE START {label} {mode}', flush=True)
        subprocess.run([sys.executable, str(runner), str(app), label, mode],
                       cwd=REPO, env=environment, check=True)
        report = ROOT / f'{label}-{mode}/summary.json'
        summary = json.loads(report.read_text())
        assert summary['passed'], report
        result['gates'].append({'mode': mode, 'report': str(report),
                                'unittest': summary['unittest']})
        print(f'GATE PASS {label} {mode}', flush=True)
    print(f'GATE START {label} real-process exit status', flush=True)
    subprocess.run([sys.executable, str(status_runner), str(app), label],
                   cwd=REPO, env=environment, check=True)
    status_report = ROOT / f'{label}-exit-status/summary.json'
    assert json.loads(status_report.read_text())['passed']
    result['exit_status_report'] = str(status_report)
    print(f'GATE PASS {label} real-process exit status', flush=True)
    result['runner_sha256_after'] = {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in protected}
    assert result['runner_sha256_after'] == original
    result['passed'] = True
except BaseException as error:
    result['error'] = repr(error)
    raise
finally:
    result['elapsed_seconds'] = round(time.monotonic() - started, 3)
    with result_path.open('x') as handle:
        handle.write(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2), flush=True)
