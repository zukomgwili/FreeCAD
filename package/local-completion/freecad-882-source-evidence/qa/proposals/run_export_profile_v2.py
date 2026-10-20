"""Root-only bounded installed export-profile driver, never build/install/solve.

All outputs are new task-private files. Raw app/profile/critical inventories
stay private. Source HEAD and the unchanged installed runtime are separate.
The copied process and custody helpers retain their original exact bytes.
"""
import sys
sys.dont_write_bytecode = True

import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess

from harness_config import COMMIT, REVISION, NATIVE_SHA, SOURCE_HEAD, WITNESS, FIXTURE_PINS

QA = Path(__file__).resolve().parent
TASK = Path('/private/tmp/freecad-882-VGfnpo')
REPO = Path('/Users/zukomgwili/src/FreeCAD')
APP = Path('/Applications/FreeCAD-27.1.0.app')
OLD = Path('/private/tmp/freecad-yzk-install-gTbYLA')
HELPERS = {
    'AppYzkIdentity.py': 'e4a6b5f645b570b6afde88c09ec5fc63e2362e1ea3556fcc2e1d0fc652b78c1a',
    'process_control.py': '5199c733fdc18a2c6f78d03ea2a3281e236419365219d7b9f33b5ecca0aa733d',
    'critical_pins.py': '15b675d33addb03f4f3a54a9e44f78fe63f7ff21065185cf957fa682ef82f0e9',
    'preservation.py': '30fb49829d4f017ca99d82f7d2e169ec244d691150cb0f5c5f1ea00b73ff3989',
}
PROFILES = [Path('/Users/zukomgwili') / name for name in (
    'Library/Application Support/FreeCAD', 'Library/Application Support/FreeCAD Local',
    'Library/Preferences/FreeCAD')]


def require(value, message):
    if not value:
        raise RuntimeError(message)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')


def head():
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO,
                                   text=True, timeout=10).strip()


def source_inputs():
    files = list((REPO / 'src/Mod/Fem').rglob('*.py')) + list(QA.glob('*.py'))
    files += [OLD / name for name in HELPERS]
    files += [REPO / 'package/local-completion/freecad-ywu-installation-evidence/private/stage_install.py',
              REPO / 'build/release/src/Build/Version.h', REPO / 'build/release/CMakeCache.txt',
              APP / 'Contents/Resources/data/NativeSolvers/ccx-force-accounting']
    files += [REPO / 'package/calculix/force-accounting' / name
              for name in ('forceaccounting.c', 'hooks.patch', 'contract.json')]
    files += [REPO / 'src/Mod/Fem/femtest/data/calculix' / name for name in
              ('coupled_port_capacity_fixture.json', 'coupled_port_capacity_oracle.json')]
    files += [Path(WITNESS) / name for name in FIXTURE_PINS]
    return {str(path): sha(path) for path in sorted(set(files))}


@contextmanager
def null_stdin():
    saved = os.dup(0)
    try:
        with open(os.devnull, 'rb') as empty:
            os.dup2(empty.fileno(), 0)
            yield
    finally:
        os.dup2(saved, 0)
        os.close(saved)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', required=True)
    parser.add_argument('--timeout', type=int, default=2400)
    args = parser.parse_args()
    require(not sys.flags.optimize, 'Use an unoptimized interpreter')
    require(QA.is_relative_to(TASK) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', args.label), 'Private new label required')
    require(args.timeout == 2400, 'Initial whole-profile diagnostic bound is2400s, not an SLA')
    for name, wanted in HELPERS.items():
        require(sha(QA / name) == sha(OLD / name) == wanted, 'Exact copied helper changed: ' + name)
    from process_control import assert_serial, run_bounded
    import critical_pins
    from preservation import INVENTORY
    assert_serial(('gmsh', 'ninja', 'make', 'gmake'))
    require(head() == SOURCE_HEAD, 'Source HEAD changed; installed runtime is deliberately pinned separately')
    require(all(path.is_dir() for path in PROFILES), 'Protected profile scope changed')
    for name, wanted in FIXTURE_PINS.items():
        require(sha(Path(WITNESS) / name) == wanted, 'Immutable original fixture changed: ' + name)
    wrapper = APP / 'Contents/MacOS/FreeCADCmd'
    require(wrapper.is_file() and os.access(wrapper, os.X_OK), 'Missing literal installed wrapper')
    require(sha(APP / 'Contents/Resources/data/NativeSolvers/ccx-force-accounting') == NATIVE_SHA, 'Installed native candidate differs')
    custody = {str(path): INVENTORY(path) for path in [APP, *PROFILES]}
    critical = critical_pins.snapshot()
    require(len(critical) == 16, 'Expected16 selected dependencies, not the whole prefix')
    before = source_inputs()
    run = TASK / args.label
    run.mkdir()
    write(run / 'private-custody-before.json', custody)
    write(run / 'private-critical-before.json', critical)
    manifest = {'schema': 'FreeCAD-yzk-application-run-manifest-v1', 'task': 'FreeCAD-882',
        'application': str(APP), 'module': 'B882Profile', 'expected_count': 2,
        'commit': COMMIT, 'revision': REVISION, 'candidate_sha256': NATIVE_SHA,
        'source_HEAD': SOURCE_HEAD, 'inputs': {'files': before},
        'export_only': True, 'installation_performed': False, 'physics_SLA_asserted': False}
    write(run / 'manifest.json', manifest)
    manifest_sha = sha(run / 'manifest.json')
    environment = dict(os.environ)
    for key in list(environment):
        if key.startswith(('FREECAD_', 'CCX_', 'APPQA_', 'YWU_', 'YZK_', 'B882_', 'FIVEAR_', 'DYLD_', 'LD_')) or key in (
                'PYTHONHOME', 'PYTHONPATH', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
            environment.pop(key)
    for key in ('FREECAD_USER_HOME', 'FREECAD_USER_DATA', 'FREECAD_USER_TEMP',
                'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
        path = run / key.lower()
        path.mkdir()
        environment[key] = str(path)
    environment.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', OMP_NUM_THREADS='2',
        TMPDIR=environment['FREECAD_USER_TEMP'], B882_OUTPUT=str(run),
        CCX_FORCE_ACCOUNTING_MAX_DECLARATIONS='2113', APPQA_APPLICATION=str(APP), APPQA_MODE='cmd',
        APPQA_REPORT=str(run / 'identity.json'), APPQA_SUITES='["B882Profile"]',
        APPQA_MANIFEST=str(run / 'manifest.json'), APPQA_MANIFEST_SHA=manifest_sha)
    command = [str(wrapper), '-u', str(run / 'user.cfg'), '-s', str(run / 'system.cfg'),
               '-P', str(QA), '-t', 'B882Identity', '-t', 'B882Profile']
    report = {'passed': False, 'task': 'FreeCAD-882', 'application': str(APP),
        'source_HEAD': SOURCE_HEAD, 'installed_commit': COMMIT, 'installed_revision': REVISION,
        'candidate_sha256': NATIVE_SHA, 'inputs_before': before, 'manifest_sha256': manifest_sha,
        'stdin_is_DEVNULL': True, 'installation_performed': False, 'solver_or_mesher_invoked_by_harness': False,
        'incidental_public_writer_or_identity_native_policy_query_allowed': True,
        'raw_app_profile_and_dependency_inventories_remain_private': True,
        'timing_is_profiled_diagnostic_not_a_runtime_SLA_or_physics_acceptance': True}
    try:
        with null_stdin():
            report.update(run_bounded(command, cwd=REPO, log=run / 'run.log',
                                      timeout=args.timeout, environment=environment))
    except BaseException as error:
        report['error'] = repr(error)
    finally:
        failures = []
        captured_outputs = {}
        try:
            report['inputs_after'] = source_inputs()
            report['source_and_supervisor_unchanged'] = before == report['inputs_after'] and head() == SOURCE_HEAD
            report['manifest_unchanged'] = sha(run / 'manifest.json') == manifest_sha
            after = {str(path): INVENTORY(path) for path in [APP, *PROFILES]}
            critical_after = critical_pins.snapshot()
            write(run / 'private-custody-after.json', after)
            write(run / 'private-critical-after.json', critical_after)
            report['application_and_three_profiles_unchanged'] = after == custody
            report['sixteen_selected_dependencies_unchanged'] = critical_after == critical
            for name in ('private-custody-before.json', 'private-custody-after.json',
                         'private-critical-before.json', 'private-critical-after.json'):
                report[name.replace('.json', '_sha256')] = sha(run / name)
        except BaseException as error:
            failures.append(repr(error))
        try:
            assert_serial(('gmsh', 'ninja', 'make', 'gmake'))
            report['post_run_serial_guard_passed'] = True
        except BaseException as error:
            failures.append(repr(error))
        try:
            def capture(name):
                path = run / name
                require(path.is_file() and not path.is_symlink(), 'Produced output is not a regular file: ' + name)
                payload = path.read_bytes()
                captured_outputs[name] = {'path': str(path),
                    'sha256': hashlib.sha256(payload).hexdigest(), 'bytes': len(payload)}
                return payload

            identity_bytes = capture('identity.json')
            profile_bytes = capture('export-profile.json')
            log_bytes = capture('run.log')
            require(captured_outputs['run.log']['sha256'] == report['log_sha256'],
                    'Captured parsed log differs from the bounded-process receipt')
            capture('whole-public-write.prof')
            capture('profile-cumulative.txt')
            identity, profile = json.loads(identity_bytes), json.loads(profile_bytes)
            text = log_bytes.decode('utf-8')
            counts = re.findall(r'^Ran (\d+) tests? in ([\d.]+)s$', text, re.M)
            report['unittest_counts'] = counts
            report['identity_sha256'] = captured_outputs['identity.json']['sha256']
            report['export_profile_sha256'] = captured_outputs['export-profile.json']['sha256']
            report['profiled_stock_write_wall_seconds'] = profile['profiled_stock_write_wall_seconds']
            report['profiled_stock_write_FreeCAD_process_CPU_seconds'] = profile['profiled_stock_write_FreeCAD_process_CPU_seconds']
            require(identity['passed'] and profile['passed'] and len(counts) == 1 and counts[0][0] == '2', 'Both actual profile and identity tests must pass')
            require(identity['runtime'][3] == REVISION and identity['runtime'][-1] == COMMIT
                    and identity['application'] == str(APP) and identity['selected_suite']['name'] == 'B882Profile'
                    and identity['selected_suite']['count'] == 1, 'Actual literal installed identity differs')
            require(math.isfinite(profile['profiled_stock_write_wall_seconds'])
                    and profile['profiled_stock_write_wall_seconds'] >= 0
                    and math.isfinite(profile['profiled_stock_write_FreeCAD_process_CPU_seconds'])
                    and profile['profiled_stock_write_FreeCAD_process_CPU_seconds'] >= 0,
                    'Nonfinite diagnostic measurement')
            require(len(re.findall(r'^OK$', text, re.M)) == 1
                    and not re.search(r'^(FAILED|FAIL:|ERROR:|UNEXPECTED SUCCESS)|\.\.\. skipped ', text, re.M), 'Failed/skipped actual test')
        except BaseException as error:
            failures.append(repr(error))
        try:
            require(set(captured_outputs) == {'identity.json', 'export-profile.json', 'run.log',
                    'whole-public-write.prof', 'profile-cumulative.txt'}, 'Missing produced diagnostic files')
            for name, expected in captured_outputs.items():
                path = run / name
                require(sha(path) == expected['sha256'] and path.stat().st_size == expected['bytes'],
                        'Produced evidence changed after parsing/capture: ' + name)
            report['produced_diagnostic_files_unchanged_after_parsing'] = True
        except BaseException as error:
            failures.append(repr(error))
        report['produced_diagnostic_files'] = captured_outputs
        report['guard_errors'] = failures
        report['passed'] = (not failures and report.get('returncode') == 0 and report.get('child_reaped')
            and report.get('process_group_gone') and not report.get('timed_out')
            and all(report.get(key) is True for key in ('source_and_supervisor_unchanged', 'manifest_unchanged',
                'application_and_three_profiles_unchanged', 'sixteen_selected_dependencies_unchanged',
                'post_run_serial_guard_passed', 'produced_diagnostic_files_unchanged_after_parsing')))
        write(run / 'execution.json', report)
        print(json.dumps({key: value for key, value in report.items() if key not in ('inputs_before', 'inputs_after')}, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
