"""Prepare/run unchanged generic V1/V2 native corpora; root alone executes.

Only explicitly requested CLI actions write fresh private evidence. Preparation
does not invoke CalculiX. Run requires the independently supplied outer manifest
hash and uses the already-built 6c candidate, never FreeCAD, a mesher, a build,
installation, or an engineering model. Profile inventories stay private.
"""

import sys
sys.dont_write_bytecode = True

import argparse
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import signal
import time
from types import SimpleNamespace


BASE = Path(__file__).resolve().parent
TASK = BASE.parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
BUILD = REPO / 'build/release'
CANDIDATE = TASK / 'native-capacity-r01/native/CalculiX/ccx_2.23/src/ccx_2.23_conda'
CANDIDATE_SHA = '6c02452a896727af6cb4578fd3fb6bbfbdd48e3fb887c1c04fa2d8b171976c66'
NATIVE_RECEIPT = TASK / 'native-capacity-r01/native/build-receipt.json'
V1 = BASE / 'run_legacy_v1.py'
V2 = REPO / 'package/local-completion/freecad-5ar-qa/qualify_native_v2_analytic.py'
CONTROL = BASE / 'process_control.py'
SUPPORT = TASK / 'qa-v3/YzkBuildSupport.py'
GENERATOR = REPO / 'package/local-completion/FreeCAD9ztContactWitness.py'
PINS = {
    V1: 'c623c6d9d8e73227e01257f58b2f3333d51775b2b15c3238988aef0216ac35c2',
    V2: '50a7fef8edf68a31b1ffc451b089b73008e391a6429d3737e6f0c8b483c3be90',
    CONTROL: '5199c733fdc18a2c6f78d03ea2a3281e236419365219d7b9f33b5ecca0aa733d',
    TASK / 'process_control.py': '5199c733fdc18a2c6f78d03ea2a3281e236419365219d7b9f33b5ecca0aa733d',
    V2.with_name('process_control.py'): '5199c733fdc18a2c6f78d03ea2a3281e236419365219d7b9f33b5ecca0aa733d',
    SUPPORT: '7295417ac65b60a10834b1c21d45cec2e14237822d03b9e09405496434d74828',
    GENERATOR: '2f82057efb43764c20bee8ba2b3b364c7c81cd90a192dd76b14f037bde63ba62',
    CANDIDATE: CANDIDATE_SHA,
    REPO / 'package/calculix/force-accounting/forceaccounting.c': '8c51e06abecf4c2b1537b1e6f4ef4606ea8481a4a180d465cbff00d63329f2a4',
    REPO / 'package/calculix/force-accounting/hooks.patch': 'e500c46cc9cd26fc4e63508a51375bd09ebdc0973638375df14cffd036c9bfa7',
}
V2_CASES = (
    'tie-tet4', 'tie-tet10', 'equation-unit-tet4',
    'equation-negative-scale-reverse-tet4', 'equation-quarter-scale-tet10',
    'equation-chain-reverse-tet4', 'tie-dependent-point-tet4',
    'equation-chain-dependent-point-tet10',
    'reject-shared-cut-mpc-tet4', 'reject-body-spc-tet4',
)
RUNTIME_LIBRARIES = (
    'libarpack.2.dylib', 'libblas.3.dylib', 'liblapack.3.dylib',
    'libopenblas.0.dylib', 'libgfortran.5.dylib', 'libomp.dylib',
    'libquadmath.0.dylib', 'libgcc_s.1.1.dylib',
)


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


def load_reviewed_helpers():
    for path, expected in PINS.items():
        require(sha(path) == expected, f'Reviewed input changed: {path}')
    # V2 imports this name lazily; its actual supervisor must be the pinned
    # repository module, not merely another equal-content import-path alias.
    sys.path.insert(0, str(V2.parent))
    import process_control
    require(Path(process_control.__file__).resolve() == V2.with_name('process_control.py'),
            'Unexpected process helper')
    spec = importlib.util.spec_from_file_location('yzk_legacy_build_support', SUPPORT)
    support = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(support)
    return process_control, support


def file_stamp(path):
    path = Path(path)
    resolved = path.resolve(strict=True)
    return {'path': str(path), 'resolved': str(resolved), 'sha256': sha(resolved),
            'symlink': os.readlink(path) if path.is_symlink() else None}


def snapshots(support):
    paths = [Path(__file__).resolve(), NATIVE_RECEIPT, *PINS]
    paths += sorted(TASK.glob('Yzk*.py')) + sorted((TASK / 'oracle').glob('*.json'))
    source = support.source_snapshot(paths)
    built = support.build_snapshot()
    require(built['fem_python_copy_parity']['passed'], 'Source/build Python parity failed')
    require(built['fem_capacity_json_copy_parity']['passed'], 'Source/build capacity JSON parity failed')
    require(sha(BUILD / 'data/NativeSolvers/ccx-force-accounting') == CANDIDATE_SHA,
            'Current source-build bundled candidate differs')
    return {'source': source, 'build': built,
            'candidate_runtime_libraries': [file_stamp(REPO / '.pixi/envs/default/lib' / name)
                                             for name in RUNTIME_LIBRARIES],
            'python': file_stamp(Path(sys.executable).resolve(strict=True))}


def native_attestation(expected_receipt_sha):
    require(sha(NATIVE_RECEIPT) == expected_receipt_sha, 'Native receipt hash not bound')
    receipt = json.loads(NATIVE_RECEIPT.read_text())
    require(receipt['binary'] == str(CANDIDATE) and receipt['binary_sha256'] == CANDIDATE_SHA
            and receipt['extra_source_sha256'] == PINS[REPO / 'package/calculix/force-accounting/forceaccounting.c']
            and receipt['probe_patch_sha256'] == PINS[REPO / 'package/calculix/force-accounting/hooks.patch']
            and receipt['channel'] == 'CCX_FORCE_ACCOUNTING_V3'
            and receipt['dependency_functional_tests_passed'] is True
            and receipt['physical_duty_qualified'] is False and receipt['installed'] is False,
            'Native build receipt does not attest this candidate and compiled C/hooks')
    lock = REPO / 'package/local-completion/calculix-9zt-probe/pixi.lock'
    require(receipt['toolchain_lock_sha256'] == sha(lock), 'Native toolchain lock differs')
    return {'path': str(NATIVE_RECEIPT), 'sha256': expected_receipt_sha,
            'candidate': str(CANDIDATE), 'candidate_sha256': CANDIDATE_SHA,
            'compiled_C_sha256': receipt['extra_source_sha256'],
            'compiled_hooks_sha256': receipt['probe_patch_sha256'],
            'contract_compilation_claimed': False}


def environment(directory):
    result = dict(os.environ)
    for key in tuple(result):
        if key.startswith(('CCX_', 'FREECAD_', 'YWU_', 'YZK_', 'APPQA_', 'FIVEAR_', 'DYLD_', 'LD_')) or key in (
                'PYTHONPATH', 'PYTHONHOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
            result.pop(key)
    result.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', OMP_NUM_THREADS='2',
                  TMPDIR=str(directory), LC_ALL='C', LANG='C')
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


@contextmanager
def clean_environment(directory):
    original = dict(os.environ)
    cleaned = environment(directory)
    try:
        os.environ.clear()
        os.environ.update(cleaned)
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


@contextmanager
def batch_deadline(seconds, state):
    # Never raise from inside the native helper's bounded cleanup, including
    # when the first deadline happens to coincide with its own timeout cleanup.
    # Exact frozen helper paths prevent confusing an unrelated same-name frame.
    require(signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0), 'Existing real-time alarm')
    previous = signal.getsignal(signal.SIGALRM)
    cleanup_sources = {str(CONTROL), str(V2.with_name('process_control.py'))}

    def expired(_signum, frame):
        state['fired'] = True
        while frame is not None:
            if (frame.f_code.co_name == '_reap_owned_group'
                    and frame.f_code.co_filename in cleanup_sources):
                state['owned_cleanup_deferrals'] = state.get('owned_cleanup_deferrals', 0) + 1
                # This is deferred delivery, not another exception in cleanup.
                # Once cleanup leaves the stack, delivery can fail the batch.
                signal.setitimer(signal.ITIMER_REAL, 0.1)
                return
            frame = frame.f_back
        raise TimeoutError('Complete legacy corpus exceeded its batch deadline')

    signal.signal(signal.SIGALRM, expired)
    try:
        signal.setitimer(signal.ITIMER_REAL, seconds)
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def corpus_inputs(version, corpus):
    path = corpus / 'manifest.json'
    manifest = json.loads(path.read_text())
    result, cases = {str(path): sha(path)}, []
    if version == 'V1':
        require(manifest['schema'] == 'FreeCAD-ywu.LEGACY_V1_PREDECLARED.1'
                and manifest['directory'] == str(corpus) and manifest['binary'] == str(CANDIDATE),
                'Unexpected V1 corpus manifest')
        require(len(manifest['cases']) == 54 and sum(row['positive'] for row in manifest['cases']) == 48,
                'V1 corpus is not the complete 48-positive/6-refusal set')
        for row in manifest['cases']:
            relative = Path(row['case'])
            require(not relative.is_absolute() and '..' not in relative.parts, 'Unsafe V1 case')
            directory = corpus / relative
            require(set(row['inputs']) == {'contact.inp', 'contact.accounting', 'oracle.json'},
                    'Unexpected V1 input membership')
            files = {str(directory / name): value for name, value in row['inputs'].items()}
            cases.append({'name': row['case'], 'directory': str(directory),
                          'positive': row['positive'], 'input_files': files})
            result.update(files)
    else:
        require(manifest['accounting_schema'] == 'CCX_FORCE_ACCOUNTING_V2'
                and manifest['one_percent_force_and_original_origin_moment_limits'] == 0.01
                and tuple(row['name'] for row in manifest['cases']) == V2_CASES,
                'Unexpected V2 corpus or changed fixed limits')
        require(manifest['script_sha256'] == PINS[V2]
                and manifest['generator_sha256'] == PINS[GENERATOR]
                and manifest['process_control_sha256'] == PINS[V2.with_name('process_control.py')],
                'Unexpected V2 helper bindings')
        for row in manifest['cases']:
            directory = corpus / row['name']
            require(row['directory'] == str(directory), 'V2 directory escaped corpus')
            files = {}
            for kind in ('deck', 'request'):
                target = directory / ('contact.inp' if kind == 'deck' else 'contact.accounting')
                require(row[kind] == str(target), 'V2 input path differs')
                files[str(target)] = row[kind + '_sha256']
            cases.append({'name': row['name'], 'directory': str(directory),
                          'positive': not bool(row.get('reject')), 'input_files': files})
            result.update(files)
    require(len({case['name'] for case in cases}) == len(cases), 'Duplicate declared case')
    for path, expected in result.items():
        require(sha(path) == expected, f'Corpus input changed: {path}')
    return result, cases


def require_pristine(cases):
    for case in cases:
        directory = Path(case['directory'])
        require(directory.is_dir() and not directory.is_symlink(), 'Invalid case directory')
        require({str(path) for path in directory.iterdir()} == set(case['input_files']),
                f'Case is not fresh; preserve it and choose a new label: {directory}')


def command(version, mode, corpus, manifest_sha=None):
    values = [str(Path(sys.executable).resolve()), '-B', str(V1 if version == 'V1' else V2),
              mode, '--root', str(corpus)]
    if version == 'V1':
        values += ['--ccx', str(CANDIDATE), '--binary-sha256', CANDIDATE_SHA]
        if mode == 'run':
            values += ['--manifest-sha256', manifest_sha]
    elif mode == 'run':
        values += ['--ccx', str(CANDIDATE), '--timeout', '60']
    return values


def protect(support, directory, suffix):
    state, dependencies = support.custody(), support.critical()
    require(len(state) == 4 and len(dependencies) == 15,
            'Expected application/3 profile roots and selected 15 dependencies')
    write(directory / f'private-custody-{suffix}.json', state)
    write(directory / f'private-critical-{suffix}.json', dependencies)
    return state, dependencies


def prepare(args, directory, control, support):
    require(not directory.exists(), 'Fresh exclusive label required')
    corpus = BASE / (args.label + '-corpus')
    require(not corpus.exists(), 'Fresh exclusive corpus required')
    attestation = native_attestation(args.native_receipt_sha256)
    control.assert_serial(('gmsh', 'ninja', 'make', 'gmake', CANDIDATE.name))
    before = snapshots(support)
    directory.mkdir()
    protected, dependencies = protect(support, directory, 'before')
    report = {'schema': 'FreeCAD-yzk-legacy-preparation-v1', 'passed': False,
              'version': args.version, 'native_invocations': 0,
              'installation_performed': False, 'engineering_or_BIM_accepted': False}
    try:
        with null_stdin():
            report.update(control.run_bounded(command(args.version, 'prepare', corpus), cwd=REPO,
                log=directory / 'prepare.log', timeout=120, environment=environment(directory)))
        require(report['returncode'] == 0 and report['child_reaped'] and report['process_group_gone']
                and not report['timed_out'], 'Generic corpus preparation failed')
        inputs, cases = corpus_inputs(args.version, corpus)
        require_pristine(cases)
        manifest = {'schema': 'FreeCAD-yzk-legacy-corpus-control-v1', 'version': args.version,
                    'directory': str(directory), 'corpus': str(corpus), 'native_build': attestation,
                    'protected_inputs': before, 'corpus_inputs': inputs, 'cases': cases,
                    'corpus_manifest_sha256': inputs[str(corpus / 'manifest.json')],
                    'timeout_seconds': args.timeout, 'native_invocations_at_preparation': 0,
                    'one_percent_force_and_original_origin_moment_limits_unchanged': True,
                    'public_FreeCAD_writer_or_capacity_graph_coverage': False,
                    'Oomakhi_accessed_or_solved': False, 'engineering_or_BIM_accepted': False}
        for kind in ('custody', 'critical'):
            manifest[f'private_{kind}_before_sha256'] = sha(directory / f'private-{kind}-before.json')
        require(snapshots(support) == before and support.custody() == protected
                and support.critical() == dependencies, 'Preparation changed a protected input')
        write(directory / 'manifest.json', manifest)
        report['manifest_sha256'] = sha(directory / 'manifest.json')
        report['passed'] = True
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        report['protected_inputs_unchanged'] = snapshots(support) == before
        report['app_and_profiles_unchanged'] = support.custody() == protected
        report['selected_critical_dependencies_unchanged'] = support.critical() == dependencies
        report['passed'] &= all(report[key] for key in ('protected_inputs_unchanged',
            'app_and_profiles_unchanged', 'selected_critical_dependencies_unchanged'))
        write(directory / 'preparation.json', report)
        print(json.dumps(report, indent=2, sort_keys=True), flush=True)
    return 0 if report['passed'] else 1


def audit_outputs(version, corpus, cases):
    summary_path = corpus / ('qualification.json' if version == 'V1' else 'summary.json')
    summary = json.loads(summary_path.read_text())
    require(summary['binary_sha256' if version == 'V1' else 'candidate_sha256'] == CANDIDATE_SHA,
            'Qualified native candidate differs')
    rows = summary['analytic_cases'] + summary['rejections'] if version == 'V1' else summary['reports']
    require(len(rows) == len(cases) and len({row['case'] for row in rows}) == len(cases),
            'Incomplete or duplicated execution set')
    by_name = {row['case']: row for row in rows}
    receipts, positives, refusals, checks, executions = {}, 0, 0, 0, []
    require(summary['passed' if version == 'V1' else 'all_selected_passed'] is True,
            'Inner native qualification did not pass')
    for case in cases:
        directory = Path(case['directory'])
        path = directory / 'execution.json'
        row = json.loads(path.read_text())
        executions.append(row)
        require(row == by_name[case['name']] and row['passed'] is True
                and row['process_group_gone'] is True and not row['timed_out']
                and row['child_reaped' if version == 'V2' else 'reaped'] is True,
                f'Incomplete owned execution: {case["name"]}')
        for input_path, expected in case['input_files'].items():
            require(sha(input_path) == expected, 'Prepared native input changed')
        log = directory / 'solver.log'
        output = directory / 'contact.accounting.out'
        require(sha(log) == row['solver_log_sha256' if version == 'V2' else 'log_sha256'],
                'Native solver log hash differs')
        if version == 'V2':
            require(row['custody_before'] == row['custody_after']
                    and row['protected_inputs_unchanged'] is True, 'V2 custody changed')
            require(row['native_output_sha256'] == (sha(output) if output.exists() else None),
                    'V2 native output hash differs')
        else:
            require(row['inputs_before'] == row['inputs_after'] and row['inputs_unchanged']
                    and row['protected_before'] == row['protected_after']
                    and row['protected_unchanged'] and row['manifest_unchanged'], 'V1 custody changed')
            require(all(sha(directory / name) == expected for name, expected in row['outputs'].items()),
                    'V1 recorded output changed')
        if case['positive']:
            require(row['returncode'] == 0, 'Positive native case did not exit zero')
            values = ([value for pair in row['relative_force_moment_errors'].values() for value in pair]
                      if version == 'V1' else [check['relative_error'] for check in row['checks']])
            require(len(values) == (6 if version == 'V1' else 18)
                    and all(math.isfinite(value) and 0 <= value <= 0.01 for value in values),
                    'Incomplete or out-of-limit independent wrench checks')
            if version == 'V2':
                require(all(check['passed'] is True and check['limit'] == 0.01 for check in row['checks']),
                        'V2 fixed check status or limit differs')
            positives += 1
            checks += len(values)
        else:
            require(row['returncode'] == 201, 'Expected accounting refusal must be exact exit201')
            require(not output.exists() or 'END' not in output.read_text().splitlines(),
                    'Refused native case left a completed accounting envelope')
            refusals += 1
        receipts[str(path)] = sha(path)
        receipts[str(log)] = sha(log)
        if output.exists():
            receipts[str(output)] = sha(output)
    require((positives, refusals, checks) == ((48, 6, 288) if version == 'V1' else (8, 2, 144)),
            'Whole declared legacy corpus was not qualified')
    return {'summary': str(summary_path), 'summary_sha256': sha(summary_path),
            'positive_cases': positives, 'expected_refusals': refusals,
            'physical_norm_checks': checks,
            'all_native_children_reaped': all(row['child_reaped' if version == 'V2' else 'reaped']
                                              for row in executions),
            'all_native_process_groups_gone': all(row['process_group_gone'] for row in executions),
            'receipts_and_raw_native_log_output_sha256': receipts}


def run(args, directory, control, support):
    manifest_path = directory / 'manifest.json'
    require(args.manifest_sha256 and sha(manifest_path) == args.manifest_sha256,
            'Independently supplied outer manifest hash required')
    manifest = json.loads(manifest_path.read_text())
    require(manifest['schema'] == 'FreeCAD-yzk-legacy-corpus-control-v1'
            and manifest['directory'] == str(directory), 'Wrong control manifest')
    require(not (directory / 'execution.json').exists() and not (directory / 'run.log').exists(),
            'Run already attempted; preserve it and use a fresh label')
    corpus = BASE / (args.label + '-corpus')
    require(manifest['corpus'] == str(corpus), 'Corpus escaped task-private namespace')
    version = manifest['version']
    require(version in ('V1', 'V2'), 'Unexpected declared protocol')
    native_attestation(manifest['native_build']['sha256'])
    inputs, cases = corpus_inputs(version, corpus)
    require(inputs == manifest['corpus_inputs'] and cases == manifest['cases'], 'Corpus manifest changed')
    require_pristine(cases)
    require(snapshots(support) == manifest['protected_inputs'], 'Protected sources/build changed')
    private = {}
    for kind in ('custody', 'critical'):
        path = directory / f'private-{kind}-before.json'
        require(sha(path) == manifest[f'private_{kind}_before_sha256'], 'Private custody receipt changed')
        private[kind] = json.loads(path.read_text())
    require(support.custody() == private['custody'] and support.critical() == private['critical'],
            'Application, profiles or selected dependencies changed since preparation')
    control.assert_serial(('gmsh', 'ninja', 'make', 'gmake', CANDIDATE.name))
    report = {'schema': 'FreeCAD-yzk-legacy-corpus-result-v1', 'passed': False,
              'version': version, 'manifest_sha256': args.manifest_sha256,
              'candidate': str(CANDIDATE), 'candidate_sha256': CANDIDATE_SHA,
              'native_build': manifest['native_build'], 'installation_performed': False,
              'unchanged_corpus_driver_executed_in_supervisor_process': True,
              'outer_driver_process_group_created': False,
              'native_children_supervised_by_unchanged_inner_helper_only': True,
              'public_FreeCAD_writer_or_capacity_graph_coverage': False,
              'Oomakhi_accessed_or_solved': False, 'engineering_or_BIM_accepted': False}
    started, deadline = time.monotonic(), {'fired': False}
    try:
        # Import the unchanged reviewed helper, but do not launch a second
        # supervising Python process whose PG cannot own the nested native PG.
        driver_path = V1 if version == 'V1' else V2
        spec = importlib.util.spec_from_file_location('yzk_unchanged_legacy_driver', driver_path)
        driver = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(driver)
        with (directory / 'run.log').open('x') as log, null_stdin(), clean_environment(directory), \
                redirect_stdout(log), redirect_stderr(log), batch_deadline(manifest['timeout_seconds'], deadline):
            if version == 'V1':
                declared = SimpleNamespace(manifest_sha256=manifest['corpus_manifest_sha256'],
                                           binary_sha256=CANDIDATE_SHA)
                driver.run(declared, CANDIDATE, corpus)
                report['returncode'] = 0
            else:
                require(Path(sys.modules['process_control'].__file__).resolve()
                        == V2.with_name('process_control.py'), 'Unexpected actual V2 supervisor')
                report['returncode'] = driver.run(corpus, CANDIDATE, None, 60)
        require(report['returncode'] == 0 and not deadline['fired'],
                'Legacy native corpus did not complete normally')
        report['qualification'] = audit_outputs(version, corpus, cases)
        report['passed'] = True
    except BaseException as error:
        report['error'] = repr(error)
    finally:
        report['elapsed_seconds'] = time.monotonic() - started
        report['timed_out'] = deadline['fired']
        report['batch_deadline_owned_cleanup_deferrals'] = deadline.get('owned_cleanup_deferrals', 0)
        report['log_sha256'] = sha(directory / 'run.log') if (directory / 'run.log').is_file() else None
        try:
            control.assert_serial(('gmsh', 'ninja', 'make', 'gmake', CANDIDATE.name))
            report['post_run_serial_guard_passed'] = True
        except BaseException as error:
            report['post_run_serial_guard_passed'] = False
            report['post_run_serial_guard_error'] = repr(error)
        qualification = report.get('qualification', {})
        report['child_reaped'] = qualification.get('all_native_children_reaped', False)
        report['process_group_gone'] = qualification.get('all_native_process_groups_gone', False)
        report['protected_inputs_unchanged'] = snapshots(support) == manifest['protected_inputs']
        report['corpus_inputs_unchanged'] = all(sha(path) == expected for path, expected in inputs.items())
        report['manifest_unchanged'] = sha(manifest_path) == args.manifest_sha256
        state, dependencies = protect(support, directory, 'after')
        report['app_and_profiles_unchanged'] = state == private['custody']
        report['selected_critical_dependencies_unchanged'] = dependencies == private['critical']
        for kind in ('custody', 'critical'):
            for when in ('before', 'after'):
                report[f'private_{kind}_{when}_sha256'] = sha(directory / f'private-{kind}-{when}.json')
        report['passed'] &= all(report[key] for key in ('protected_inputs_unchanged',
            'corpus_inputs_unchanged', 'manifest_unchanged', 'app_and_profiles_unchanged',
            'selected_critical_dependencies_unchanged', 'post_run_serial_guard_passed',
            'child_reaped', 'process_group_gone')) and not report['timed_out']
        write(directory / 'execution.json', report)
        print(json.dumps(report, indent=2, sort_keys=True), flush=True)
    return 0 if report['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'run'))
    parser.add_argument('label')
    parser.add_argument('--version', choices=('V1', 'V2'))
    parser.add_argument('--native-receipt-sha256')
    parser.add_argument('--manifest-sha256')
    parser.add_argument('--timeout', type=int, default=1200)
    args = parser.parse_args()
    require(not sys.flags.optimize and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', args.label),
            'Use an unoptimized interpreter and a safe fresh label')
    require(1 <= args.timeout <= 3600, 'Outer timeout must be in 1..3600 seconds')
    if args.mode == 'prepare':
        require(args.version and args.native_receipt_sha256
                and re.fullmatch('[0-9a-f]{64}', args.native_receipt_sha256),
                'prepare requires version and independently bound native receipt hash')
    else:
        require(args.manifest_sha256 and re.fullmatch('[0-9a-f]{64}', args.manifest_sha256)
                and not args.version and not args.native_receipt_sha256,
                'run requires only the independently supplied control manifest hash')
    control, support = load_reviewed_helpers()
    return (prepare if args.mode == 'prepare' else run)(args, BASE / args.label, control, support)


if __name__ == '__main__':
    raise SystemExit(main())
