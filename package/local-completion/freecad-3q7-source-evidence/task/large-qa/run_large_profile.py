"""Root-only same-core source-runtime baseline/candidate export profiling.

No build/copy target, solver, mesher, save, recompute or install is invoked.
Root updates candidate Python through its separately reviewed CMake copy target
only after baseline completion. All watched sources stay fixed during a run.
"""
import sys
sys.dont_write_bytecode = True

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from large_config import BUILD, COMMIT, REVISION, NATIVE_SHA, SOURCE_HEAD
from large_config import WITNESS, FIXTURE_PINS, RESTORED_CONNECTIVITY, RESTORED_CONNECTIVITY_SHA

TASK = Path('/private/tmp/freecad-3q7-Pq3Byy')
QA = Path(__file__).resolve().parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
APP = Path('/Applications/FreeCAD-27.1.0.app')
OLD = Path('/private/tmp/freecad-882-VGfnpo/profile-v4')
INVENTORY_SOURCE = REPO / 'package/local-completion/freecad-ywu-installation-evidence/private/stage_install.py'
HELPERS = {'process_control.py': '5199c733fdc18a2c6f78d03ea2a3281e236419365219d7b9f33b5ecca0aa733d',
    'preservation.py': '30fb49829d4f017ca99d82f7d2e169ec244d691150cb0f5c5f1ea00b73ff3989',
    'critical_pins.py': '15b675d33addb03f4f3a54a9e44f78fe63f7ff21065185cf957fa682ef82f0e9'}
PROTECTED = [APP, *(Path('/Users/zukomgwili') / name for name in (
    'Library/Application Support/FreeCAD', 'Library/Application Support/FreeCAD Local',
    'Library/Preferences/FreeCAD'))]
PYTHON_PARITY = ('femmesh/meshtools.py', 'femmesh/ownership_context.py',
    'femmesh/meshsetsgetter.py', 'femtools/rigid_body.py', 'femtools/elastic_connector.py',
    'femtools/ccxtools.py', 'femtools/force_accounting.py', 'femtest/app/coupled_port_fixture.py',
    'femsolver/calculix/writer.py', 'femsolver/calculix/write_constraint_rigidbody.py',
    'femsolver/calculix/write_constraint_rigidbody_step.py',
    'femsolver/calculix/write_constraint_elastic_connector.py')


def need(value, message):
    if not value:
        raise RuntimeError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')


def head():
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO,
                                   timeout=10, text=True).strip()


def compiled_native_inputs():
    # Runtime output folders only, never a vendor/build-object tree or binaries
    # copied into evidence. Pin all existing native module/library leaf bodies.
    files = [BUILD / 'bin/FreeCADCmd', BUILD / 'bin/FreeCAD',
             BUILD / 'data/NativeSolvers/ccx-force-accounting']
    for folder in (BUILD / 'lib', BUILD / 'Mod'):
        files.extend(path for path in folder.rglob('*')
                     if path.is_file() and path.suffix in ('.so', '.dylib'))
    return {str(path): sha(path) for path in sorted(set(files))}


def inputs(native, reference):
    files = list((REPO / 'src/Mod/Fem').rglob('*.py'))
    files += list((BUILD / 'Mod/Fem').rglob('*.py')) + list(QA.glob('*.py'))
    files += [INVENTORY_SOURCE, BUILD / 'src/Build/Version.h', BUILD / 'CMakeCache.txt']
    files += [REPO / 'package/calculix/force-accounting' / name
              for name in ('forceaccounting.c', 'hooks.patch', 'contract.json')]
    files += [Path(WITNESS) / name for name in FIXTURE_PINS] + [Path(RESTORED_CONNECTIVITY)]
    files += [Path(path) for path in native]
    if reference:
        files += [Path(ref['path']) for ref in reference.values()]
    return {str(path): sha(path) for path in sorted(set(files))}


def python_parity():
    result = {}
    for relative in PYTHON_PARITY:
        source, runtime = REPO / 'src/Mod/Fem' / relative, BUILD / 'Mod/Fem' / relative
        need(source.is_file() and runtime.is_file() and source.read_bytes() == runtime.read_bytes(),
             'Source/runtime Python copy mismatch: ' + relative)
        result[relative] = sha(source)
    return result


def baseline_reference(path, wanted, native):
    need(path.is_absolute() and path.is_relative_to(TASK) and path.name == 'execution.json', 'Task baseline execution required')
    payload = path.read_bytes()
    need(hashlib.sha256(payload).hexdigest() == wanted, 'Explicit baseline execution SHA differs')
    previous = json.loads(payload)
    need(previous['passed'] is True and previous['role'] == 'baseline'
         and previous['compiled_native_pins'] == native, 'Completed same-core baseline required')
    outputs = previous['produced_outputs']
    profile_ref = outputs['export-profile.json']
    profile_bytes = Path(profile_ref['path']).read_bytes()
    need(hashlib.sha256(profile_bytes).hexdigest() == profile_ref['sha256']
         and len(profile_bytes) == profile_ref['bytes'], 'Captured baseline profile changed')
    profile = json.loads(profile_bytes)
    need(profile['passed'] is True and profile['role'] == 'baseline'
         and profile['schema'] == 'FreeCAD-3q7-common-runtime-whole-export-profile-v1', 'Actual baseline producer differs')
    refs = {'execution': {'path': str(path), 'sha256': wanted, 'bytes': len(payload)},
            'profile': profile_ref, 'deck': outputs['native/Mesh.inp'],
            'request': outputs['native/Mesh.accounting']}
    for ref in refs.values():
        actual = Path(ref['path']).read_bytes()
        need(hashlib.sha256(actual).hexdigest() == ref['sha256'] and len(actual) == ref['bytes'],
             'Matched reference changed: ' + ref['path'])
    need(path.read_bytes() == payload, 'Baseline execution changed during capture')
    return refs


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
    parser.add_argument('--role', choices=('baseline', 'candidate'), required=True)
    parser.add_argument('--baseline-execution', type=Path)
    parser.add_argument('--baseline-execution-sha256')
    args = parser.parse_args()
    need(not sys.flags.optimize, 'Unoptimized Python required')
    need(QA == TASK / 'large-qa' and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', args.label), 'Private label only')
    need(bool(args.baseline_execution) == bool(args.baseline_execution_sha256)
         == (args.role == 'candidate'), 'Only candidate requires an explicit baseline execution/SHA')
    for name, wanted in HELPERS.items():
        need(sha(QA / name) == sha(OLD / name) == wanted, 'Reviewed exact helper differs')
    from process_control import assert_serial, run_bounded
    from preservation import INVENTORY
    import critical_pins
    assert_serial(('gmsh', 'ninja', 'make', 'gmake'))
    need(head() == SOURCE_HEAD, 'Current Python source HEAD differs from the agreed common-core experiment')
    native = compiled_native_inputs()
    need(native[str(BUILD / 'data/NativeSolvers/ccx-force-accounting')] == NATIVE_SHA, 'Source native candidate differs')
    parity = python_parity()
    reference = baseline_reference(args.baseline_execution, args.baseline_execution_sha256, native) if args.role == 'candidate' else None
    for name, wanted in FIXTURE_PINS.items():
        need(sha(Path(WITNESS) / name) == wanted, 'Original generic fixture changed: ' + name)
    need(sha(RESTORED_CONNECTIVITY) == RESTORED_CONNECTIVITY_SHA, 'Pinned restored mesh changed')
    need(all(path.is_dir() for path in PROTECTED), 'Protected application/user scope missing')
    protected = {str(path): INVENTORY(path) for path in PROTECTED}
    dependencies = critical_pins.snapshot()
    need(len(dependencies) == 16, 'Exactly16 selected critical inputs required')
    before = inputs(native, reference)
    run = TASK / args.label
    run.mkdir()
    write(run / 'private-custody-before.json', protected)
    write(run / 'private-critical-before.json', dependencies)
    manifest = {'schema': 'FreeCAD-3q7-large-common-runtime-manifest-v1', 'role': args.role,
        'source_HEAD': SOURCE_HEAD, 'compiled_commit': COMMIT, 'revision': REVISION,
        'compiled_native_pins': native, 'inputs': before, 'python_source_runtime_parity': parity,
        'reference': reference, 'selected_tests_including_identity': 2, 'timeout_seconds': 2400,
        'whole_public_write_only_no_solver_or_installation': True}
    write(run / 'manifest.json', manifest)
    manifest_sha = sha(run / 'manifest.json')
    environment = dict(os.environ)
    for key in list(environment):
        if key.startswith(('FREECAD_', 'CCX_', 'APPQA_', 'YWU_', 'YZK_', 'B882_', 'Q37',
                           'FIVEAR_', 'DYLD_', 'LD_')) or key in ('PYTHONHOME', 'PYTHONPATH',
                           'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
            environment.pop(key)
    for key in ('FREECAD_USER_HOME', 'FREECAD_USER_DATA', 'FREECAD_USER_TEMP',
                'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
        folder = run / key.lower()
        folder.mkdir()
        environment[key] = str(folder)
    environment.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', OMP_NUM_THREADS='2',
        TMPDIR=environment['FREECAD_USER_TEMP'], Q37L_OUTPUT=str(run),
        Q37L_MANIFEST=str(run / 'manifest.json'), Q37L_MANIFEST_SHA=manifest_sha,
        CCX_FORCE_ACCOUNTING_MAX_DECLARATIONS='2113')
    command = ['pixi', 'run', '--frozen', str(BUILD / 'bin/FreeCADCmd'),
        '-u', str(run / 'user.cfg'), '-s', str(run / 'system.cfg'),
        '-P', str(QA), '-t', 'Q37LargeIdentity', '-t', 'Q37LargeProfile']
    report = {'schema': 'FreeCAD-3q7-large-common-runtime-execution-v1', 'passed': False,
        'role': args.role, 'source_HEAD': SOURCE_HEAD, 'compiled_commit': COMMIT, 'revision': REVISION,
        'compiled_native_pins': native, 'python_source_runtime_parity': parity,
        'inputs_before': before, 'manifest_sha256': manifest_sha, 'baseline_reference': reference,
        'stdin_is_DEVNULL': True, 'no_solver_mesher_save_recompute_build_copy_or_install': True,
        'raw_user_app_dependency_inventories_private': True}
    try:
        with null_stdin():
            report.update(run_bounded(command, cwd=REPO, log=run / 'run.log', timeout=2400,
                                      environment=environment))
    except BaseException as error:
        report['error'] = repr(error)
    finally:
        failures, produced = [], {}
        try:
            report['inputs_after'] = inputs(compiled_native_inputs(), reference)
            report['source_and_supervisor_unchanged'] = before == report['inputs_after'] and head() == SOURCE_HEAD
            report['compiled_native_runtime_unchanged'] = compiled_native_inputs() == native
            report['python_copy_parity_unchanged'] = python_parity() == parity
            report['manifest_unchanged'] = sha(run / 'manifest.json') == manifest_sha
            after = {str(path): INVENTORY(path) for path in PROTECTED}
            dependency_after = critical_pins.snapshot()
            write(run / 'private-custody-after.json', after)
            write(run / 'private-critical-after.json', dependency_after)
            report['application_and_three_profiles_unchanged'] = after == protected
            report['sixteen_selected_dependencies_unchanged'] = dependency_after == dependencies
            for name in ('private-custody-before.json', 'private-custody-after.json',
                         'private-critical-before.json', 'private-critical-after.json'):
                report[name + '_sha256'] = sha(run / name)
            assert_serial(('gmsh', 'ninja', 'make', 'gmake'))
            report['serial_post_guard_passed'] = True
        except BaseException as error:
            failures.append(repr(error))
        try:
            def capture(name):
                path = run / name
                need(path.is_file() and not path.is_symlink(), 'Missing regular output: ' + name)
                data = path.read_bytes()
                produced[name] = {'path': str(path), 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
                return data

            identity = json.loads(capture('identity.json'))
            profile = json.loads(capture('export-profile.json'))
            text = capture('run.log').decode('utf-8')
            need(produced['run.log']['sha256'] == report['log_sha256'], 'Captured log differs from process receipt')
            bindings = {'whole-public-write.prof': 'output_profile_blob',
                'profile-cumulative.txt': 'output_cumulative_text', 'native/Mesh.inp': 'output_deck',
                'native/Mesh.accounting': 'output_request', 'native/Mesh.accounting.json': 'output_request_metadata'}
            for name, field in bindings.items():
                capture(name)
                need(produced[name] == profile[field], 'Producer output binding differs: ' + name)
            counts = re.findall(r'^Ran (\d+) tests? in ([\d.]+)s$', text, re.M)
            report['unittest_counts'] = counts
            need(identity['passed'] is True and profile['passed'] is True and len(counts) == 1
                 and counts[0][0] == '2', 'Exactly2 non-skipped actual tests must pass')
            need(len(re.findall(r'^OK$', text, re.M)) == 1
                 and not re.search(r'^(FAILED|FAIL:|ERROR:|UNEXPECTED SUCCESS)|\.\.\. skipped ', text, re.M),
                 'Actual failure/error/skip')
            need(profile['actual_write_inp_file_calls'] == 1 and profile['role'] == args.role
                 and profile['manifest']['sha256'] == manifest_sha
                 and profile['same_compiled_runtime_pins'] == native, 'Whole-call manifest/core binding differs')
            if args.role == 'candidate':
                need(profile['strict_matched_baseline_outputs_and_raw_snapshots_equal'] is True,
                     'Candidate lacks strict matched baseline equality')
            for name, ref in produced.items():
                need(sha(run / name) == ref['sha256'] and (run / name).stat().st_size == ref['bytes'],
                     'Produced output changed after capture: ' + name)
            report['produced_outputs_unchanged_after_capture'] = True
        except BaseException as error:
            failures.append(repr(error))
        report.update(guard_errors=failures, produced_outputs=produced)
        flags = ('source_and_supervisor_unchanged', 'compiled_native_runtime_unchanged',
            'python_copy_parity_unchanged', 'manifest_unchanged', 'application_and_three_profiles_unchanged',
            'sixteen_selected_dependencies_unchanged', 'serial_post_guard_passed', 'produced_outputs_unchanged_after_capture')
        report['passed'] = bool(not failures and report.get('returncode') == 0
            and report.get('child_reaped') and report.get('process_group_gone') and not report.get('timed_out')
            and all(report.get(key) is True for key in flags))
        write(run / 'execution.json', report)
        print(json.dumps({key: value for key, value in report.items() if key not in ('inputs_before', 'inputs_after')}, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

