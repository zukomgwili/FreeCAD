"""Bounded e4k literal-bundle gates; import is side-effect free.

Only the root runs main(). Admission reads the exact completed gate and current
custody; it never launches FreeCAD or edits profiles, payloads or receipts.
"""

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
MODULES = {'cmd':'AppStagedE4k','gui':'GuiStagedE4k','cold':'ColdStagedE4k'}
HELPERS = ('AppStagedE4k.py','GuiStagedE4k.py','ColdStagedE4k.py','run_e4k_application.py')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def context():
    # Lazy imports avoid a stage_install -> admission -> stage_install cycle.
    install = importlib.import_module('stage_install')
    critical = importlib.import_module('critical_pins')
    guard = importlib.import_module('run_gate')
    return install,critical,guard


def locate(install, application):
    application = Path(application)
    if application == install.STAGE:
        return 'stage',application
    assert application == install.APP, application
    return 'installed',application


def expected_command(application, mode, run):
    executable = 'FreeCAD' if mode == 'gui' else 'FreeCADCmd'
    return [str(application/'Contents/MacOS'/executable),'-u',str(run/'user.cfg'),'-s',str(run/'system.cfg'),'-P',str(ROOT),'-t',MODULES[mode]]


def profile_state(install, critical):
    critical.verify()
    return {str(p):install.canonical_sha(install.inventory(p)) for p in install.PROFILES}


def check_regression(reg, install, application, mode, plan):
    count = plan['counts'][mode]
    assert reg['schema'] == 'FreeCAD-e4k-installation-regression-v1'
    assert reg['passed'] is True and reg['mode'] == mode
    assert reg['application'] == str(application)
    assert reg['commit'] == install.COMMIT and reg['revision'] == install.REVISION
    assert reg['native_sha256'] == install.NATIVE_SHA
    assert reg['identity_sha256'] == sha(ROOT/'identity.json')
    assert reg['test_plan_sha256'] == sha(ROOT/'e4k-test-plan.json')
    assert reg['expected_tests'] == reg['executed_tests'] == count
    ids = reg['selected_test_ids']
    assert len(ids) == len(set(ids)) == count
    assert sorted(ids) == plan['expected_ids'][mode]
    assert reg['skipped'] == reg['failures'] == reg['errors'] == []
    assert reg['gui'] is (mode == 'gui')
    for flag in ('source_or_build_import_override','native_solver_override','original_project_opened_changed_or_solved'):
        assert reg[flag] is False, flag
    identity = reg['identity']
    assert identity['application'] == str(application)
    assert identity['runtime'][3] == install.REVISION and identity['runtime'][-1] == install.COMMIT
    assert identity['candidate']['sha256'] == install.NATIVE_SHA
    assert identity['candidate']['override'] is False
    assert Path(identity['candidate']['path']) == application/'Contents/Resources/data/NativeSolvers/ccx-force-accounting'
    assert identity['source_or_build_import_override'] is False
    for row in reg['final_module_origins'].values():
        actual = Path(row['path'])
        assert actual.is_relative_to(application/'Contents/Resources/Mod/Fem')
        assert sha(actual) == row['sha256']
    if mode == 'cmd':
        case = reg['saved_case']
        for name in ('document','literal'):
            p = Path(case[name])
            assert p.is_file() and not p.is_symlink()
            assert p.is_relative_to(ROOT/(f'e4k-{locate(install,application)[0]}-cmd'))
            assert sha(p) == case[name+'_sha256']
        assert case['source_application'] == str(application)
        assert case['source_commit'] == install.COMMIT and case['native_sha256'] == install.NATIVE_SHA


def admit_application_gate(application, mode):
    """Read-only admission used by the root staging/swap and final audits."""
    assert mode in MODULES
    install,critical,_guard = context()
    location,application = locate(install,application)
    run = ROOT/f'e4k-{location}-{mode}'
    proof = read(run/'execution.json')
    reg = read(run/'regression.json')
    plan = read(ROOT/'e4k-test-plan.json')
    assert proof['schema'] == 'FreeCAD-e4k-literal-application-gate-v1'
    assert proof['passed'] is True and proof['returncode'] == 0
    assert proof['application'] == str(application) and proof['location'] == location and proof['mode'] == mode
    assert proof['source_commit'] == install.COMMIT and proof['revision'] == install.REVISION
    assert proof['native_sha256'] == install.NATIVE_SHA
    assert proof['command'] == expected_command(application,mode,run)
    assert proof['expected_tests'] == proof['executed_tests'] == plan['counts'][mode]
    assert proof['timed_out'] is False and proof['skipped_lines'] == []
    for key in ('child_reaped','process_group_gone','inputs_unchanged','application_unchanged','profiles_and_dependencies_unchanged','original_app_unchanged','strict_signature_verified','semantic_tests_passed'):
        assert proof[key] is True,(mode,key)
    assert proof['source_or_build_import_override'] is False and proof['native_solver_override'] is False
    assert proof['inputs_before'] == proof['inputs_after']
    for path,wanted in proof['inputs_after'].items():
        assert sha(path) == wanted, path
    assert sha(run/'run.log') == proof['log_sha256']
    assert sha(run/'regression.json') == proof['regression_sha256']
    text = (run/'run.log').read_text(errors='replace')
    assert re.findall(r'^Ran (\d+) tests? in [0-9.]+s$',text,re.M) == [str(plan['counts'][mode])]
    assert len(re.findall(r'^OK$',text,re.M)) == 1
    assert not re.search(r'^(?:FAILED|FAIL:|ERROR:|UNEXPECTED SUCCESS)|\.\.\. skipped',text,re.M)
    check_regression(reg,install,application,mode,plan)
    sealed = read(ROOT/'stage-inventory.json')
    assert install.inventory(application) == sealed
    assert install.canonical_sha(sealed) == proof['application_inventory_sha256']
    assert sha(application/'Contents/Resources/data/NativeSolvers/ccx-force-accounting') == install.NATIVE_SHA
    install.verify(application)
    install.compiled_identity()
    critical.verify()
    assert profile_state(install,critical) == proof['protected_profiles_after']
    return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('location',choices=('stage','installed'))
    parser.add_argument('mode',choices=tuple(MODULES))
    args = parser.parse_args()
    install,critical,guard = context()
    guard.serial()
    install.compiled_identity()
    application = install.STAGE if args.location == 'stage' else install.APP
    assert application.resolve(strict=True) == application and not application.is_symlink()
    sealed_path = ROOT/'stage-inventory.json'
    sealed = read(sealed_path)
    assert install.inventory(application) == sealed
    install.verify(application)
    original = install.canonical_sha(install.inventory(install.APP))
    before_profiles = profile_state(install,critical)
    plan = read(ROOT/'e4k-test-plan.json')
    assert plan['counts'] == {'cmd':22,'gui':1,'cold':1}
    assert sha(ROOT/'oracles.json') == plan['frozen_oracles_sha256']
    run = ROOT/f'e4k-{args.location}-{args.mode}'
    run.mkdir()
    temporary = run/'dotted.parent'
    temporary.mkdir()
    environment = {
        k:v for k,v in os.environ.items()
        if not k.startswith(('FREECAD_','CCX_','DYLD_','LD_','APPQA_','IBJH_','IE4K_','E4K_','ISV7_','I960_','B960_','BJH_','SV7_','R9_'))
        and k not in ('PYTHONPATH','PYTHONHOME','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_CACHE_HOME','TMPDIR','TMP','TEMP','DESTDIR')
    }
    for key in ('FREECAD_USER_HOME','FREECAD_USER_DATA','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_CACHE_HOME'):
        path = run/key.lower()
        path.mkdir()
        environment[key] = str(path)
    environment.update(TMPDIR=str(temporary)+'/',TMP=str(temporary),TEMP=str(temporary),FREECAD_USER_TEMP=str(temporary),PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',OMP_NUM_THREADS='2',IE4K_APP=str(application),IE4K_MODE=args.mode,IE4K_IDENTITY=str(ROOT/'identity.json'),IE4K_TEST_PLAN=str(ROOT/'e4k-test-plan.json'),IE4K_ORACLES=str(ROOT/'oracles.json'),E4K_RUN=str(run))
    extra = [sealed_path,ROOT/'identity.json',ROOT/'e4k-test-plan.json',ROOT/'oracles.json',ROOT/'critical-before-DESTDIR.json']
    extra += [ROOT/name for name in HELPERS]
    extra += [ROOT/name for name in ('stage_install.py','run_gate.py','critical_pins.py')]
    if args.mode == 'cold':
        admit_application_gate(application,'cmd')
        prior = ROOT/f'e4k-{args.location}-cmd'
        case = read(prior/'regression.json')['saved_case']
        environment['IE4K_COLD_CASE'] = json.dumps(case,sort_keys=True)
        extra += [prior/'execution.json',prior/'regression.json',Path(case['document']),Path(case['literal'])]
    resources = application/'Contents/Resources'
    extra += [install.REPO/name for name in install.SOURCES]
    extra += [resources/name for name in install.SOURCES.values()]
    extra += [resources/name for name in ('bin/FreeCAD','bin/FreeCADCmd','data/NativeSolvers/ccx-force-accounting')]
    def inputs():
        return {str(p):sha(p) for p in sorted(set(extra))}
    before = inputs()
    command = expected_command(application,args.mode,run)
    report = {'schema':'FreeCAD-e4k-literal-application-gate-v1','passed':False,'application':str(application),'location':args.location,'mode':args.mode,'source_commit':install.COMMIT,'revision':install.REVISION,'native_sha256':install.NATIVE_SHA,'expected_tests':plan['counts'][args.mode],'command':command,'inputs_before':before,'source_or_build_import_override':False,'native_solver_override':False,'protected_profiles_before':before_profiles}
    started = time.monotonic()
    timed_out = False
    child = None
    try:
        with (run/'run.log').open('xb') as output:
            child = subprocess.Popen(command,cwd=run,env=environment,stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
            try:
                child.wait(timeout=900)
            except subprocess.TimeoutExpired:
                timed_out = True
            finally:
                for number in (signal.SIGTERM,signal.SIGKILL):
                    if child.poll() is None or guard.group_exists(child.pid):
                        try:
                            os.killpg(child.pid,number)
                        except ProcessLookupError:
                            pass
                        try:
                            child.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            pass
        text = (run/'run.log').read_text(errors='replace')
        counts = re.findall(r'^Ran (\d+) tests? in [0-9.]+s$',text,re.M)
        skips = re.findall(r'^.*\.\.\. skipped.*$',text,re.M)
        reg_path = run/'regression.json'
        reg = read(reg_path) if reg_path.exists() else {}
        valid = counts == [str(plan['counts'][args.mode])] and len(re.findall(r'^OK$',text,re.M)) == 1 and not skips and not re.search(r'^(?:FAILED|FAIL:|ERROR:|UNEXPECTED SUCCESS)',text,re.M)
        try:
            check_regression(reg,install,application,args.mode,plan)
        except (AssertionError,KeyError,TypeError,ValueError) as error:
            valid = False
            report['regression_admission_error'] = repr(error)
        after = inputs()
        current = install.inventory(application)
        install.verify(application)
        install.compiled_identity()
        guard.serial()
        after_profiles = profile_state(install,critical)
        report.update(returncode=child.returncode,timed_out=timed_out,child_reaped=child.poll() is not None,process_group_gone=not guard.group_exists(child.pid),executed_tests=int(counts[0]) if len(counts)==1 else 0,skipped_lines=skips,inputs_after=after,inputs_unchanged=before==after,application_unchanged=current==sealed,application_inventory_sha256=install.canonical_sha(current),profiles_and_dependencies_unchanged=before_profiles==after_profiles,protected_profiles_after=after_profiles,original_app_unchanged=original==install.canonical_sha(install.inventory(install.APP)),strict_signature_verified=True,log_sha256=sha(run/'run.log'),regression_sha256=sha(reg_path) if reg_path.exists() else None,semantic_tests_passed=bool(valid))
        report['passed'] = bool(child.returncode==0 and not timed_out and valid and all(report[k] for k in ('child_reaped','process_group_gone','inputs_unchanged','application_unchanged','profiles_and_dependencies_unchanged','original_app_unchanged','strict_signature_verified')))
    except BaseException as error:
        report['supervisor_error'] = repr(error)
        raise
    finally:
        report['elapsed_seconds'] = time.monotonic()-started
        install.write_json(run/'execution.json',report)
        print(json.dumps({k:v for k,v in report.items() if k not in ('inputs_before','inputs_after','protected_profiles_before','protected_profiles_after')},indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
