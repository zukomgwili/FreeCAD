"""Root-only source build; no installation or dependency mutation."""
import sys
sys.dont_write_bytecode = True

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re

TASK = Path(__file__).resolve().parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
BUILD = REPO / 'build/release'
PRIOR = Path('/private/tmp/freecad-yzk-Sd0mDG/qa-v3/YzkBuildSupport.py')
CONTROL = PRIOR.parent.parent / 'process_control.py'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('label')
    parser.add_argument('--support-sha256', required=True)
    args = parser.parse_args()
    if sys.flags.optimize or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]*', args.label):
        raise RuntimeError('Unoptimized interpreter and fresh safe label required')
    import hashlib
    digest = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if digest(PRIOR) != args.support_sha256 or digest(CONTROL) != '5199c733fdc18a2c6f78d03ea2a3281e236419365219d7b9f33b5ecca0aa733d':
        raise RuntimeError('Reviewed read-only helper changed')
    spec = importlib.util.spec_from_file_location('B3q7ReadOnlyBuildSupport', PRIOR)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    helper.assert_serial(('gmsh', 'ninja', 'make', 'gmake'))
    before = helper.source_snapshot([Path(__file__), PRIOR, CONTROL])
    built_before, protected, dependencies = helper.build_snapshot(), helper.custody(), helper.critical()
    if len(protected) != 4 or len(dependencies) != 15:
        raise RuntimeError('Protected custody scope changed')
    run = TASK / args.label
    run.mkdir()
    helper.write(run / 'private-custody-before.json', protected)
    helper.write(run / 'private-critical-before.json', dependencies)
    env = dict(os.environ)
    for key in tuple(env):
        if key.startswith(('FREECAD_', 'CCX_', 'APPQA_', 'YWU_', 'YZK_', 'B882_', 'B3Q7_', 'FIVEAR_', 'DYLD_', 'LD_')) or key in ('PYTHONPATH', 'PYTHONHOME', 'DESTDIR', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_DATA_HOME'):
            env.pop(key)
    for key in ('FREECAD_USER_HOME', 'FREECAD_USER_DATA', 'FREECAD_USER_TEMP', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_DATA_HOME'):
        directory = run / key.lower()
        directory.mkdir()
        env[key] = str(directory)
    env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', OMP_NUM_THREADS='2', TMPDIR=env['FREECAD_USER_TEMP'])
    command = ['pixi', 'run', '--frozen', 'cmake', '--build', str(BUILD), '--parallel', '8']
    report = {'schema': 'FreeCAD-3q7-source-build-v1', 'passed': False, 'source_before': before,
              'build_before': built_before, 'installation_performed': False}
    saved_stdin = os.dup(0)
    try:
        with open(os.devnull, 'rb') as empty:
            os.dup2(empty.fileno(), 0)
            report.update(helper.run_bounded(command, cwd=REPO, log=run / 'run.log', timeout=900, environment=env))
    except BaseException as error:
        report['error'] = repr(error)
    finally:
        os.dup2(saved_stdin, 0)
        os.close(saved_stdin)
        report['source_after'], report['build_after'] = helper.source_snapshot([Path(__file__), PRIOR, CONTROL]), helper.build_snapshot()
        after, critical_after = helper.custody(), helper.critical()
        helper.write(run / 'private-custody-after.json', after)
        helper.write(run / 'private-critical-after.json', critical_after)
        report['source_unchanged'] = before == report['source_after']
        report['application_and_three_profiles_unchanged'] = protected == after
        report['selected_dependencies_unchanged'] = dependencies == critical_after
        for kind in ('custody', 'critical'):
            for when in ('before', 'after'):
                report[f'private_{kind}_{when}_sha256'] = digest(run / f'private-{kind}-{when}.json')
        try:
            helper.assert_serial(('gmsh', 'ninja', 'make', 'gmake'))
            report['post_run_serial_guard_passed'] = True
        except BaseException as error:
            report['post_run_serial_guard_passed'] = False
            report['post_run_serial_guard_error'] = repr(error)
        report['passed'] = bool(report.get('returncode') == 0 and report.get('child_reaped') and report.get('process_group_gone') and not report.get('timed_out') and report['source_unchanged'] and report['application_and_three_profiles_unchanged'] and report['selected_dependencies_unchanged'] and report['build_after']['fem_python_copy_parity']['passed'] and report['build_after']['fem_capacity_json_copy_parity']['passed'] and report['post_run_serial_guard_passed'])
        helper.write(run / 'execution.json', report)
        print(json.dumps({key: value for key, value in report.items() if key not in ('source_before', 'source_after', 'build_before', 'build_after')}, indent=2), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
