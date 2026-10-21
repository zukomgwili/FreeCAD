"""Bounded serial deployment steps; no live-profile use or unqualified direct install."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time

import run_gate
import stage_install as install

ROOT = Path(__file__).resolve().parent
PREFIX = ['pixi', 'run', '--frozen']
COMMANDS = {
    'capture': PREFIX + ['python', '-B', '-c',
        'import critical_pins; critical_pins.capture()'],
    'payload': PREFIX + ['cmake', '--install', 'build/release'],
    'audit-payload': PREFIX + ['python', '-B', str(ROOT / 'audit_payload_stage.py'), 'payload'],
    'stage': PREFIX + ['python', '-B', str(ROOT / 'stage_install.py'), 'stage'],
    'audit-stage': PREFIX + ['python', '-B', str(ROOT / 'audit_payload_stage.py'), 'stage'],
    'audit-custody': PREFIX + ['python', '-B', str(ROOT / 'audit_payload_stage.py'), 'custody'],
    'swap': PREFIX + ['python', '-B', str(ROOT / 'stage_install.py'), 'swap'],
}


def sha(path):
    return install.digest(path)


def build_identity():
    files = [install.BUILD / 'src/Build/Version.h', install.BUILD / 'CMakeCache.txt']
    files += [install.REPO / name for name in ('pixi.toml', 'pixi.lock',
        'src/Base/FileInfo.cpp', 'tests/src/Base/FileInfo.cpp', 'tests/src/App/BackupPolicy.cpp')]
    for directory, dirs, names in os.walk(install.BUILD, followlinks=False):
        dirs[:] = [name for name in dirs if name != 'CMakeFiles'
                   and not (Path(directory) / name).is_symlink()]
        for name in names:
            path = Path(directory) / name
            if not path.is_symlink() and path.is_file():
                with path.open('rb') as stream:
                    if stream.read(4) == b'\xcf\xfa\xed\xfe':
                        files.append(path)
    return {str(path): sha(path) for path in files}


def protected():
    return {str(path): install.canonical_sha(install.inventory(path))
            for path in (install.APP, *install.PROFILES)}


def inputs():
    return {str(path): sha(path) for path in sorted(ROOT.glob('*.py'))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=COMMANDS)
    args = parser.parse_args()
    assert __debug__
    run_gate.serial()
    install.compiled_identity()
    path = ROOT / ('step-' + args.mode)
    path.mkdir()
    before, scripts = protected(), inputs()
    if args.mode == 'capture':
        install.write_json(ROOT / 'build-identity.json', build_identity())
    env = dict(os.environ)
    for key in tuple(env):
        if key.startswith(('FREECAD_', 'CCX_', 'DYLD_', 'LD_', 'APPQA_', 'F8_')) or key in (
            'PYTHONPATH', 'PYTHONHOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME',
            'TMPDIR', 'TMP', 'TEMP', 'DESTDIR'):
            env.pop(key)
    for key in ('FREECAD_USER_HOME', 'FREECAD_USER_DATA', 'XDG_CONFIG_HOME',
                'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
        place = path / key.lower()
        place.mkdir()
        env[key] = str(place)
    temporary = path / 'dotted.parent'
    temporary.mkdir()
    env.update(TMPDIR=str(temporary) + '/', TMP=str(temporary), TEMP=str(temporary),
               FREECAD_USER_TEMP=str(temporary), PYTHONDONTWRITEBYTECODE='1',
               PYTHONNOUSERSITE='1', OMP_NUM_THREADS='2')
    if args.mode == 'payload':
        assert not (ROOT / 'payload').exists()
        env['DESTDIR'] = str(ROOT / 'payload')
    command = COMMANDS[args.mode]
    timed_out, started = False, time.monotonic()
    with (path / 'run.log').open('xb') as output:
        child = subprocess.Popen(command, cwd=install.REPO, env=env, stdin=subprocess.DEVNULL,
                                 stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            child.wait(timeout=600)
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
    report = {'schema': 'FreeCAD-8rk-install-step-v1', 'mode': args.mode, 'command': command,
              'source_commit': install.COMMIT, 'returncode': child.returncode,
              'timed_out': timed_out, 'child_reaped': child.poll() is not None,
              'process_group_gone': not run_gate.group_exists(child.pid),
              'elapsed_seconds': time.monotonic() - started,
              'inputs_before': scripts, 'inputs_after': inputs(),
              'protected_before': before, 'protected_after': protected(),
              'log_sha256': sha(path / 'run.log')}
    report['inputs_unchanged'] = report['inputs_before'] == report['inputs_after']
    if args.mode == 'swap':
        report['expected_sealed_install_and_exact_backup'] = (
            install.inventory(install.APP) == json.loads((ROOT / 'stage-inventory.json').read_text())
            and install.inventory(install.BACKUP) == json.loads((ROOT / 'baseline-inventory.json').read_text()))
        report['protected_unchanged'] = all(report['protected_before'][str(p)] ==
            report['protected_after'][str(p)] for p in install.PROFILES)
    else:
        report['protected_unchanged'] = before == report['protected_after']
    if (ROOT / 'critical-before-DESTDIR.json').exists():
        import critical_pins
        critical_pins.verify()
    install.compiled_identity()
    run_gate.serial()
    report['passed'] = bool(child.returncode == 0 and not timed_out
        and report['child_reaped'] and report['process_group_gone']
        and report['inputs_unchanged'] and report['protected_unchanged']
        and report.get('expected_sealed_install_and_exact_backup', True))
    install.write_json(path / 'execution.json', report)
    print(json.dumps({k: v for k, v in report.items() if k not in (
        'inputs_before', 'inputs_after', 'protected_before', 'protected_after')}, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
