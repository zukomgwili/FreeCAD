"""Root-executed, serial CTest-only source gate; never build or install.

Fixed command only: frozen Pixi CTest, parallel1, default test timeout60,
outer timeout1800. Existing per-test TIMEOUT properties are not rewritten.
The exact prior catalogue parser checks every outcome, not selected tests.
Private application/profile/critical inventory bodies must never be published.
"""

import sys
sys.dont_write_bytecode = True

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile
import time


BASE = Path(__file__).resolve().parent
TASK = BASE.parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
BUILD = REPO / 'build/release'
PREFIX = REPO / '.pixi/envs/default'
TEMPORARY = BUILD / 'Testing/Temporary'
CONTROL = BASE / 'process_control.py'
SUPPORT = TASK / 'qa-v3/YzkBuildSupport.py'
PRIOR = Path('/private/tmp/freecad-ywu-sG46Lsc8/run_full_build.py')
NATIVE_RECEIPT = TASK / 'native-capacity-r01/native/build-receipt.json'
CANDIDATE = TASK / 'native-capacity-r01/native/CalculiX/ccx_2.23/src/ccx_2.23_conda'
CANDIDATE_SHA = '6c02452a896727af6cb4578fd3fb6bbfbdd48e3fb887c1c04fa2d8b171976c66'
PINS = {
    CONTROL: '5199c733fdc18a2c6f78d03ea2a3281e236419365219d7b9f33b5ecca0aa733d',
    TASK / 'process_control.py': '5199c733fdc18a2c6f78d03ea2a3281e236419365219d7b9f33b5ecca0aa733d',
    SUPPORT: '7295417ac65b60a10834b1c21d45cec2e14237822d03b9e09405496434d74828',
    PRIOR: '3c246d1ae4ab86e2e866dd6c9e5ceb88add87d4eb7af3526c2e94714eba64ab3',
    CANDIDATE: CANDIDATE_SHA,
    PREFIX / 'bin/ctest': '6a11388967f89618542e8005575db5c0b94a50b9d31b2360dce2aa9a490beb76',
    REPO / 'package/calculix/force-accounting/forceaccounting.c': '8c51e06abecf4c2b1537b1e6f4ef4606ea8481a4a180d465cbff00d63329f2a4',
    REPO / 'package/calculix/force-accounting/hooks.patch': 'e500c46cc9cd26fc4e63508a51375bd09ebdc0973638375df14cffd036c9bfa7',
}
LOG_NAMES = ('LastTest.log', 'LastTestsFailed.log', 'LastTestsDisabled.log')
PROFILE_NAMES = ('FREECAD_USER_HOME', 'FREECAD_USER_DATA', 'FREECAD_USER_TEMP',
                 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_DATA_HOME')
COMMAND = ['pixi', 'run', '--frozen', 'ctest', '--test-dir', str(BUILD),
           '--output-on-failure', '--parallel', '1', '--timeout', '60']
TIMEOUT = 1800


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), f'Not a regular input: {path}')
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    with Path(path).open('x') as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    require(Path(loaded.__file__).resolve() == path, 'Unexpected helper import origin')
    return loaded


def helpers():
    for path, expected in PINS.items():
        require(sha(path) == expected, f'Reviewed input changed: {path}')
    sys.path.insert(0, str(BASE))
    import process_control
    require(Path(process_control.__file__).resolve() == CONTROL, 'Unexpected process supervisor')
    return process_control, module(SUPPORT, 'yzk_ctest_build_support'), module(PRIOR, 'yzk_prior_ctest_parser')


def serial_guard(control):
    # Observe the actual unit executable names too: a leftover test child must
    # not coexist with this gate merely because its CTest parent has exited.
    units = tuple(path.name for path in (BUILD / 'tests').glob('*_tests_run'))
    control.assert_serial(('gmsh', 'ninja', 'make', 'gmake', CANDIDATE.name, *units))


def snapshots(support):
    paths = [Path(__file__).resolve(), NATIVE_RECEIPT, *PINS]
    paths += sorted(TASK.glob('Yzk*.py')) + sorted((TASK / 'oracle').glob('*.json'))
    source = support.source_snapshot(paths)
    built = support.build_snapshot()
    require(built['fem_python_copy_parity']['passed'], 'Source/build Python parity failed')
    require(built['fem_capacity_json_copy_parity']['passed'], 'Source/build capacity JSON parity failed')
    for name in ('src/Build/Version.h', 'bin/FreeCADCmd', 'bin/FreeCAD',
                 'lib/libFreeCADApp.dylib', 'Mod/Fem/Fem.so', 'Mod/Fem/FemGui.so',
                 'data/NativeSolvers/ccx-force-accounting', 'CMakeCache.txt'):
        require(str(BUILD / name) in built['files'], 'Required source-build identity missing: ' + name)
    require(sha(BUILD / 'data/NativeSolvers/ccx-force-accounting') == CANDIDATE_SHA,
            'Current source-build bundled native candidate differs')
    # Pin immutable catalogue inputs and actual unit-test executables, never
    # copy their binary payloads. GoogleTest generated discovery files/logs are
    # outputs, deliberately not immutable inputs of this command.
    catalogue = sorted(BUILD.rglob('CTestTestfile.cmake'))
    catalogue += sorted((BUILD / 'tests').glob('*_include.cmake'))
    executables = sorted((BUILD / 'tests').glob('*_tests_run'))
    require(BUILD / 'CTestTestfile.cmake' in catalogue and executables,
            'Complete source-build CTest catalogue/executables missing')
    return {'source': source, 'build': built,
            'ctest_catalogue_inputs_and_test_executables': {str(path): sha(path)
                                                          for path in catalogue + executables}}


def native_attestation(expected):
    require(sha(NATIVE_RECEIPT) == expected, 'Native build receipt is not independently hash-bound')
    row = json.loads(NATIVE_RECEIPT.read_text())
    require(row['binary'] == str(CANDIDATE) and row['binary_sha256'] == CANDIDATE_SHA
            and row['extra_source_sha256'] == PINS[REPO / 'package/calculix/force-accounting/forceaccounting.c']
            and row['probe_patch_sha256'] == PINS[REPO / 'package/calculix/force-accounting/hooks.patch']
            and row['channel'] == 'CCX_FORCE_ACCOUNTING_V3'
            and row['dependency_functional_tests_passed'] is True
            and row['physical_duty_qualified'] is False and row['installed'] is False,
            'Build receipt does not attest this actual candidate/C/hooks')
    return {'path': str(NATIVE_RECEIPT), 'sha256': expected, 'candidate': str(CANDIDATE),
            'candidate_sha256': CANDIDATE_SHA, 'compiled_C_sha256': row['extra_source_sha256'],
            'compiled_hooks_sha256': row['probe_patch_sha256'],
            'contract_compilation_claimed': False}


def observation(path):
    if not path.exists():
        return {'exists': False}
    require(path.is_file() and not path.is_symlink(), 'CTest log is not a regular file')
    info = path.stat()
    return {'exists': True, 'sha256': sha(path), 'bytes': info.st_size,
            'mtime_ns': info.st_mtime_ns, 'inode': info.st_ino}


def environment(directory, temporary):
    result = dict(os.environ)
    for key in tuple(result):
        if key.startswith(('FREECAD_', 'CCX_', 'CTEST_', 'APPQA_', 'YWU_', 'YZK_', 'FIVEAR_', 'RO1_', 'DYLD_', 'LD_')) or key in (
                'PYTHONPATH', 'PYTHONHOME', 'DESTDIR', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_DATA_HOME'):
            result.pop(key)
    for name in PROFILE_NAMES:
        path = temporary if name == 'FREECAD_USER_TEMP' else directory / name.lower()
        if name != 'FREECAD_USER_TEMP':
            path.mkdir()
        result[name] = str(path)
    result.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', OMP_NUM_THREADS='2',
                  TMPDIR=str(temporary), LC_ALL='C', LANG='C')
    return result


@contextmanager
def null_stdin():
    original = os.dup(0)
    try:
        with open(os.devnull, 'rb') as empty:
            os.dup2(empty.fileno(), 0)
            yield
    finally:
        os.dup2(original, 0)
        os.close(original)


def capture_logs(directory, prior, started_ns):
    result = {}
    for name, before in prior.items():
        path = TEMPORARY / name
        after = observation(path)
        fresh = bool(after.get('exists') and after != before and after['mtime_ns'] >= started_ns)
        result[name] = {**after, 'fresh_for_this_run': fresh,
                        'classification': 'fresh' if fresh else 'absent_or_stale_not_current_evidence'}
        if fresh:
            raw = path.read_bytes()
            require(hashlib.sha256(raw).hexdigest() == after['sha256'], 'CTest log changed while reading')
            with (directory / name).open('xb') as output:
                output.write(raw)
            require(sha(directory / name) == after['sha256'], 'Retained CTest log bytes differ')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('label')
    parser.add_argument('--native-receipt-sha256', required=True)
    args = parser.parse_args()
    require(not sys.flags.optimize and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', args.label),
            'Use an unoptimized interpreter and a safe fresh label')
    require(re.fullmatch('[0-9a-f]{64}', args.native_receipt_sha256), 'Native receipt SHA256 required')
    control, support, reader = helpers()
    with (BASE / 'ctest-serial.lock').open('a+') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        serial_guard(control)
        attestation = native_attestation(args.native_receipt_sha256)
        before = snapshots(support)
        protected, dependencies = support.custody(), support.critical()
        require(len(protected) == 4 and len(dependencies) == 15,
                'Expected application/3 profiles and selected 15 critical dependency records')
        prior = {name: observation(TEMPORARY / name) for name in LOG_NAMES}
        directory = BASE / args.label
        directory.mkdir(exist_ok=False)
        write(directory / 'private-custody-before.json', protected)
        write(directory / 'private-critical-before.json', dependencies)
        temporary = Path(tempfile.mkdtemp(prefix='freecad-yzk-ctest-', dir='/private/tmp'))
        require('.' not in str(temporary) and temporary.parent == Path('/private/tmp'),
                'CTest temporary root must be fresh and dot-free')
        env = environment(directory, temporary)
        report = {'schema': 'FreeCAD-yzk-serial-ctest-result-v1', 'passed': False, 'mode': 'ctest',
                  'command': COMMAND, 'cwd': str(REPO), 'timeout_seconds': TIMEOUT,
                  'ctest_parallel': 1, 'ctest_default_test_timeout_seconds': 60,
                  'existing_per_test_TIMEOUT_properties_overridden': False,
                  'protected_inputs_before': before, 'native_build': attestation,
                  'prior_ctest_logs': prior, 'private_dot_free_temporary_root': str(temporary),
                  'isolated_profile_environment_names': list(PROFILE_NAMES),
                  'dotted_temporary_directory_product_bug_fixed': False,
                  'installation_performed': False, 'engineering_or_BIM_accepted': False,
                  'Oomakhi_accessed_or_solved': False}
        started_ns = time.time_ns()
        try:
            serial_guard(control)
            with null_stdin():
                report.update(control.run_bounded(COMMAND, cwd=REPO, log=directory / 'run.log',
                    timeout=TIMEOUT, environment=env))
            require(report['returncode'] == 0 and not report['timed_out']
                    and report['child_reaped'] and report['process_group_gone'],
                    'CTest did not finish normally within its owned process group')
            report['ctest'] = reader.ctest_summary((directory / 'run.log').read_text(errors='replace'))
            report['passed'] = True
        except BaseException as error:
            report['error'] = repr(error)
        finally:
            try:
                report['ctest_logs_after'] = capture_logs(directory, prior, started_ns)
                if report.get('ctest'):
                    require(report['ctest_logs_after']['LastTest.log']['fresh_for_this_run'],
                            'CTest did not write a fresh LastTest.log')
                    if report['ctest']['disabled']:
                        require(report['ctest_logs_after']['LastTestsDisabled.log']['fresh_for_this_run'],
                                'CTest disabled outcomes lack a fresh disabled index')
                    failed = report['ctest_logs_after']['LastTestsFailed.log']
                    require(not failed['fresh_for_this_run'] or not (directory / 'LastTestsFailed.log').read_text().strip(),
                            'Fresh failure index contradicts successful catalogue')
            except BaseException as error:
                report['passed'] = False
                report['ctest_log_custody_error'] = repr(error)
            try:
                report['protected_inputs_after'] = snapshots(support)
                report['source_build_supervisor_candidate_unchanged'] = report['protected_inputs_after'] == before
            except BaseException as error:
                report['source_build_supervisor_candidate_unchanged'] = False
                report['source_fence_error'] = repr(error)
            try:
                after, dependencies_after = support.custody(), support.critical()
                write(directory / 'private-custody-after.json', after)
                write(directory / 'private-critical-after.json', dependencies_after)
                report['app_and_profiles_unchanged'] = after == protected
                report['selected_critical_dependencies_unchanged'] = dependencies_after == dependencies
                for kind in ('custody', 'critical'):
                    for when in ('before', 'after'):
                        report[f'private_{kind}_{when}_sha256'] = sha(directory / f'private-{kind}-{when}.json')
            except BaseException as error:
                report['app_and_profiles_unchanged'] = False
                report['selected_critical_dependencies_unchanged'] = False
                report['private_custody_fence_error'] = repr(error)
            try:
                serial_guard(control)
                report['post_run_serial_guard_passed'] = True
            except BaseException as error:
                report['post_run_serial_guard_passed'] = False
                report['post_run_serial_guard_error'] = repr(error)
            report['passed'] &= all(report.get(key) for key in (
                'source_build_supervisor_candidate_unchanged', 'app_and_profiles_unchanged',
                'selected_critical_dependencies_unchanged', 'post_run_serial_guard_passed',
                'child_reaped', 'process_group_gone')) and not report.get('timed_out', False)
            report['exit_code'] = report.get('returncode')
            report['catalogue_parser'] = {'path': str(PRIOR), 'sha256': PINS[PRIOR], 'function': 'ctest_summary'}
            report['log_sha256'] = sha(directory / 'run.log') if (directory / 'run.log').is_file() else None
            write(directory / 'execution.json', report)
            print(json.dumps(report, indent=2, sort_keys=True), flush=True)
        return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
