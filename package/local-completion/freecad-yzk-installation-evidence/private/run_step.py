"""Root-only bounded explicit deployment steps; retain new-only logs/receipts."""
import sys
sys.dont_write_bytecode = True
import json
import os
from pathlib import Path
import runpy

from process_control_devnull import assert_serial, run_bounded
import critical_pins
import preservation

ROOT = Path(__file__).resolve().parent
REPO = preservation.REPO
ACTIONS = {
    'payload': ['pixi', 'run', '--frozen', 'cmake', '--install', 'build/release'],
    'audit-payload': [sys.executable, '-B', str(ROOT / 'audit_payload_stage.py'), 'payload'],
    'stage': [sys.executable, '-B', str(ROOT / 'stage_install.py'), 'stage'],
    'audit-stage': [sys.executable, '-B', str(ROOT / 'audit_payload_stage.py'), 'stage'],
    'audit-custody': [sys.executable, '-B', str(ROOT / 'audit_payload_stage.py'), 'custody'],
    'swap': [sys.executable, '-B', str(ROOT / 'stage_install.py'), 'swap'],
}

def main():
    preservation.require(not sys.flags.optimize and len(sys.argv) == 2 and sys.argv[1] in ACTIONS,
                         'Explicit unoptimized action required')
    action = sys.argv[1]
    assert_serial(('gmsh', 'ninja', 'make', 'gmake'))
    preservation.verify()
    critical_pins.verify()
    state = runpy.run_path(str(ROOT / 'stage_install.py'))
    state['compiled_identity']()
    run = ROOT / ('step-' + action)
    run.mkdir()
    environment = dict(os.environ)
    for key in list(environment):
        if key.startswith(('FREECAD_', 'CCX_', 'APPQA_', 'YWU_', 'YZK_')) or key in (
            'PYTHONHOME', 'PYTHONPATH', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME', 'DESTDIR'):
            environment.pop(key)
    for key in ('FREECAD_USER_HOME', 'FREECAD_USER_DATA', 'FREECAD_USER_TEMP',
                'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
        directory = run / key.lower()
        directory.mkdir()
        environment[key] = str(directory)
    environment.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1',
                       TMPDIR=environment['FREECAD_USER_TEMP'], OMP_NUM_THREADS='2')
    if action == 'payload':
        payload = ROOT / 'payload'
        preservation.require(not payload.exists() and not payload.is_symlink(), 'Existing DESTDIR')
        environment['DESTDIR'] = str(payload)
    report = {'passed': False, 'action': action, 'source_commit': state['COMMIT'],
              'compiled_revision': state['REVISION'], 'installation_replacement': action == 'swap'}
    try:
        report.update(run_bounded(ACTIONS[action], cwd=REPO, log=run / 'run.log',
                                  timeout=600, environment=environment))
        preservation.verify(original_app=action != 'swap')
        critical_pins.verify()
        state['compiled_identity']()
        report['passed'] = bool(report['returncode'] == 0 and report['child_reaped']
                               and report['process_group_gone'] and not report['timed_out'])
        report['protected_profiles_and_selected_inputs_unchanged'] = True
    except BaseException as error:
        report['error'] = repr(error)
    finally:
        preservation.write(run / 'execution.json', report)
        print(json.dumps(report, indent=2), flush=True)
    return 0 if report['passed'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
