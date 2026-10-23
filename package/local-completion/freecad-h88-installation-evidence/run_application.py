"""Bounded root-only literal-bundle h88 gates with isolated profiles."""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

sys.dont_write_bytecode = True

import critical_pins
import run_gate
import stage_install as install

ROOT = Path(__file__).resolve().parent
COUNTS = {'cmd': 8, 'gui': 8, 'save': 3, 'cold': 2}
SOURCE = ROOT / 'input/EN2-failed-recovery-r02.FCStd'
ORIGINAL_SOURCE = Path('/Users/zukomgwili/src/oomakhi/artifacts/Fire-Access-Integration/r01/review/en2-complete-r01/complete-native-p01-p02-r67/native/recovery-r02/EN2-failed-recovery-r02.FCStd')
ORIGINAL_SHA = '570e7ffd62c4dfb95c7b0bcbb1eafab69f11c5d54152bf9fd840ad0464402a33'


def sha(path):
    return install.digest(Path(path))


def inputs(extra):
    paths = {*ROOT.glob('*.py'), ROOT / 'identity.json', *extra}
    return {str(path): sha(path) for path in sorted(paths)}


def profiles():
    critical_pins.verify()
    assert len(install.PROFILES) == 3
    return {str(path): install.canonical_sha(install.inventory(path)) for path in install.PROFILES}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('location', choices=('stage', 'installed'))
    parser.add_argument('mode', choices=tuple(COUNTS))
    parser.add_argument('label')
    parser.add_argument('--save-directory', type=Path)
    args = parser.parse_args()
    assert __debug__ and re.fullmatch(r'[a-z0-9-]+', args.label)
    assert (args.mode == 'cold') == (args.save_directory is not None)
    assert sha(SOURCE) == ORIGINAL_SHA and sha(ORIGINAL_SOURCE) == ORIGINAL_SHA
    run_gate.serial()
    install.compiled_identity()
    application = install.STAGE if args.location == 'stage' else install.APP
    assert application.resolve(strict=True) == application and not application.is_symlink()
    sealed_path = ROOT / 'stage-inventory.json'
    sealed = json.loads(sealed_path.read_text())
    assert install.inventory(application) == sealed
    install.verify(application)
    original_app = install.canonical_sha(install.inventory(install.APP))
    before_profiles = profiles()
    run = ROOT / args.label
    run.mkdir()
    temporary = run / 'dotted.parent'
    temporary.mkdir()
    savedir = run if args.mode == 'save' else args.save_directory
    extra = [sealed_path, SOURCE, ORIGINAL_SOURCE]
    if args.mode == 'cold':
        savedir = savedir.resolve(strict=True)
        assert savedir.is_relative_to(ROOT) and not savedir.is_symlink()
        prior = savedir / 'execution.json'
        prior_proof = json.loads(prior.read_text())
        assert prior_proof['passed'] is True and prior_proof['mode'] == 'save'
        assert prior_proof['location'] == args.location and prior_proof['application'] == str(application)
        assert prior_proof['source_commit'] == install.COMMIT
        saved = savedir / 'private-checkpoint.FCStd'
        semantic = json.loads((savedir / 'regression.json').read_text())
        assert semantic['private_checkpoint'] == {'path': str(saved), 'sha256': sha(saved)}
        extra += [saved, prior, savedir / 'cold-observation.json', savedir / 'regression.json',
                  savedir / 'manifest.json', savedir / 'run.log']
    resources = application / 'Contents/Resources'
    native_names = ['bin/FreeCADCmd', 'bin/FreeCAD', 'lib/FreeCAD.so', 'lib/FreeCADGui.so',
                    'lib/libFreeCADBase.dylib', 'lib/libFreeCADApp.dylib',
                    'lib/libFreeCADGui.dylib', 'lib/Fem.so', 'lib/FemGui.so', 'lib/Part.so',
                    'lib/Materials.so', 'data/NativeSolvers/ccx-force-accounting']
    native = {str(resources / name): sha(resources / name) for name in native_names}
    source = {target: sha(install.REPO / name) for name, target in install.SOURCES.items()}
    manifest = {
        'schema': 'FreeCAD-h88-literal-application-manifest-v1',
        'application': str(application), 'location': args.location, 'mode': args.mode,
        'commit': install.COMMIT, 'revision': install.REVISION, 'native_sha256': install.NATIVE_SHA,
        'gui': args.mode == 'gui', 'expected_tests': COUNTS[args.mode],
        'expected_native_files': native, 'expected_source_files': source,
        'report_path': str(run / 'regression.json'), 'working_directory': str(run),
        'save_directory': str(savedir) if savedir else None,
        'original_source': str(ORIGINAL_SOURCE), 'original_sha256': ORIGINAL_SHA,
        'private_input': str(SOURCE),
    }
    manifest_path = run / 'manifest.json'
    install.write_json(manifest_path, manifest)
    environment = dict(os.environ)
    for key in tuple(environment):
        if key.startswith(('FREECAD_', 'CCX_', 'DYLD_', 'LD_', 'APPQA_', 'F8_', 'F9II_', 'H88_')) or key in (
            'PYTHONPATH', 'PYTHONHOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME',
            'TMPDIR', 'TMP', 'TEMP', 'DESTDIR'):
            environment.pop(key)
    for key in ('FREECAD_USER_HOME', 'FREECAD_USER_DATA', 'FREECAD_USER_TEMP',
                'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
        path = run / key.lower()
        path.mkdir()
        environment[key] = str(path)
    environment.update(TMPDIR=str(temporary) + '/', TMP=str(temporary), TEMP=str(temporary),
                       FREECAD_USER_TEMP=str(temporary), PYTHONDONTWRITEBYTECODE='1',
                       PYTHONNOUSERSITE='1', OMP_NUM_THREADS='2',
                       H88_INSTALL_MANIFEST=str(manifest_path), H88_RUN_DIR=str(run),
                       H88_SOURCE=str(SOURCE), H88_MODULE_ROOT=str(resources / 'Mod/BIM'),
                       H88_CODE_ROOT=str(install.REPO / 'src/Mod/BIM'),
                       H88_EXPECT_COMMIT=install.COMMIT, H88_SUITE='controls',
                       H88_COLD_PHASE='save' if args.mode == 'save' else 'cold-reopen',
                       H88_SAVE_DIR=str(savedir) if savedir else str(run))
    executable = 'FreeCAD' if args.mode == 'gui' else 'FreeCADCmd'
    command = [str(application / 'Contents/MacOS' / executable), '-u', str(run / 'user.cfg'),
               '-s', str(run / 'system.cfg'), '-P', str(ROOT), '-t', 'AppH88Identity']
    extra += [manifest_path, *map(Path, native), *[install.REPO / name for name in install.SOURCES]]
    before = inputs(extra)
    started, timed_out = time.monotonic(), False
    child = None
    report = {'schema': 'FreeCAD-h88-literal-application-gate-v1', 'passed': False,
              'application': str(application), 'location': args.location, 'mode': args.mode,
              'source_commit': install.COMMIT, 'revision': install.REVISION,
              'native_sha256': install.NATIVE_SHA, 'expected_tests': COUNTS[args.mode],
              'command': command, 'working_directory': str(run), 'inputs_before': before,
              'source_or_build_import_override': False, 'native_solver_override': False}
    try:
        with (run / 'run.log').open('xb') as output:
            child = subprocess.Popen(command, cwd=run, env=environment, stdin=subprocess.DEVNULL,
                                     stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                child.wait(timeout=900)
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
        text = (run / 'run.log').read_text(errors='replace')
        counts = re.findall(r'^Ran (\d+) tests? in [0-9.]+s$', text, re.M)
        valid = (counts == [str(COUNTS[args.mode])]
                 and len(re.findall(r'^OK$', text, re.M)) == 1
                 and not re.search(r'^(?:FAILED|FAIL:|ERROR:|UNEXPECTED SUCCESS)|\.\.\. skipped', text, re.M))
        receipt_path = run / 'regression.json'
        regression = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
        valid = bool(valid and regression.get('passed') is True
                     and regression.get('commit') == install.COMMIT
                     and regression.get('application') == str(application)
                     and regression.get('mode') == args.mode
                     and regression.get('test_count') == COUNTS[args.mode]
                     and regression.get('native_sha256') == install.NATIVE_SHA)
        after = inputs(extra)
        current = install.inventory(application)
        install.verify(application)
        install.compiled_identity()
        run_gate.serial()
        report.update(
            returncode=child.returncode, timed_out=timed_out,
            child_reaped=child.poll() is not None, process_group_gone=not run_gate.group_exists(child.pid),
            executed_tests=int(counts[0]) if len(counts) == 1 else 0,
            inputs_after=after, inputs_unchanged=before == after,
            application_unchanged=current == sealed,
            application_inventory_sha256=install.canonical_sha(current),
            profiles_and_dependencies_unchanged=before_profiles == profiles(),
            original_app_unchanged=original_app == install.canonical_sha(install.inventory(install.APP)),
            strict_signature_verified=True, log_sha256=sha(run / 'run.log'),
            regression_sha256=sha(receipt_path) if receipt_path.exists() else None,
            semantic_tests_passed=valid)
        report['passed'] = bool(child.returncode == 0 and not timed_out and valid
            and report['child_reaped'] and report['process_group_gone'] and report['inputs_unchanged']
            and report['application_unchanged'] and report['profiles_and_dependencies_unchanged']
            and report['original_app_unchanged'] and report['strict_signature_verified'])
    except BaseException as error:
        report['supervisor_error'] = repr(error)
        raise
    finally:
        report['elapsed_seconds'] = time.monotonic() - started
        install.write_json(run / 'execution.json', report)
        print(json.dumps({key: value for key, value in report.items()
                          if key not in ('inputs_before', 'inputs_after')}, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
