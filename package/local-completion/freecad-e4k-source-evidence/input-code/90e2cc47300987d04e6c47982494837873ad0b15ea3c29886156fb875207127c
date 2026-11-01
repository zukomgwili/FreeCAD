import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import re
import runpy

ROOT = Path(__file__).resolve().parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('label')
    parser.add_argument('module')
    parser.add_argument('--source', action='store_true')
    parser.add_argument('--gui', action='store_true')
    parser.add_argument('--expected', type=int)
    args = parser.parse_args()
    native = {'FreeCAD', 'FreeCADCmd', 'ccx', 'ccx-force-accounting', 'gmsh', 'ctest', 'ninja', 'make', 'gmake'}
    for line in subprocess.check_output(['ps','-axo','pid=,comm='], text=True).splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) == 2 and Path(fields[1]).name in native:
            raise RuntimeError('Native process active: '+line)
    run = ROOT / args.label
    run.mkdir()
    temp = run / 'dotted.parent'
    temp.mkdir()
    env = {k:v for k,v in os.environ.items() if not k.startswith(('FREECAD_', 'CCX_', 'DYLD_', 'LD_', 'E4K_', 'B960_', 'BJH_', 'SV7_', 'R9_')) and k not in ('PYTHONPATH','PYTHONHOME','TMPDIR','TMP','TEMP','DESTDIR') and not k.startswith('XDG_')}
    for key in ('FREECAD_USER_HOME','FREECAD_USER_DATA','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_CACHE_HOME'):
        path = run / key.lower()
        path.mkdir()
        env[key] = str(path)
    env.update(E4K_RUN=str(run), PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', OMP_NUM_THREADS='2', TMPDIR=str(temp)+'/', TMP=str(temp), TEMP=str(temp), FREECAD_USER_TEMP=str(temp))
    executable = 'FreeCAD' if args.gui else 'FreeCADCmd'
    command = [str(Path('/Applications/FreeCAD-27.1.0.app/Contents/MacOS')/executable), '-u',str(run/'user.cfg'),'-s',str(run/'system.cfg'),'-P',str(ROOT),'-t',args.module]
    if args.source:
        command = ['pixi','run','--frozen', str(REPO/'build/release/bin'/executable), '-u',str(run/'user.cfg'),'-s',str(run/'system.cfg'),'-P',str(ROOT),'-t',args.module]
    paths = list(ROOT.glob('*.py'))
    paths += list((REPO/'src/Mod/Fem/femsolver/calculix').glob('*.py'))
    paths += list((REPO/'src/Mod/Fem/femobjects').glob('solver_calculix.py'))
    paths += list((REPO/'src/Mod/Fem/femtest/app').glob('test_*amplitude*.py'))
    paths += list((REPO/'src/Mod/Fem/femtest/app').glob('test_staged_selfweight_native.py'))
    paths += [REPO/'src/Mod/Fem/femtools'/name for name in ('contact_state.py','force_accounting.py')]
    paths += list((REPO/'src/Mod/Fem/femtest/app').glob('test_contact_state_catalogue.py'))
    paths += [REPO/'build/release/data/NativeSolvers/ccx-force-accounting']
    paths += list(ROOT.glob('*.json'))
    paths += list((REPO/'package/calculix/force-accounting').glob('*'))
    pins = {str(p):sha(p) for p in paths if p.is_file()}
    core = REPO/'package/local-completion/freecad-ywu-installation-evidence/private/stage_install.py'
    assert sha(core) == 'cca627502a56b6c9b4aefa4a970172c51e42e2dde834000decca65fd44ab46d9'
    inventory = runpy.run_path(str(core))['inventory']
    protected = [Path('/Applications/FreeCAD-27.1.0.app')]
    protected += [Path('/Users/zukomgwili') / name for name in ('Library/Application Support/FreeCAD','Library/Application Support/FreeCAD Local','Library/Preferences/FreeCAD')]
    def custody():
        return {str(p):hashlib.sha256(json.dumps(inventory(p),sort_keys=True).encode()).hexdigest() for p in protected}
    before_custody = custody()
    started = time.monotonic()
    timeout = False
    with (run/'run.log').open('xb') as log:
        child = subprocess.Popen(command, cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
        try:
            child.wait(timeout=900)
        except subprocess.TimeoutExpired:
            timeout=True
        finally:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(child.pid, sig)
                except ProcessLookupError:
                    pass
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
    log_text=(run/'run.log').read_text()
    counts=re.findall(r'^Ran (\d+) tests? in [^\n]+$', log_text, re.M)
    semantics= len(counts)==1 and int(counts[0])>0 and re.search(r'^OK$', log_text,re.M) is not None and not re.search(r'^(FAILED|FAIL:|ERROR:)|\.\.\. skipped',log_text,re.M)
    if args.expected is not None:
        semantics = semantics and counts == [str(args.expected)]
    record = {'command':command,'source_mode':args.source,'elapsed_seconds':time.monotonic()-started,'returncode':child.returncode,'timed_out':timeout,'child_reaped':child.poll() is not None,'helper_inputs_before':pins,'helper_inputs_unchanged':all(sha(p)==value for p,value in pins.items()),'log_sha256':sha(run/'run.log'),'test_counts':counts,'semantic_passed':bool(semantics),'protected_before':before_custody,'protected_after':custody()}
    record['installed_app_and_three_profiles_unchanged']=record['protected_before']==record['protected_after']
    record['passed']=bool(child.returncode==0 and not timeout and semantics and record['helper_inputs_unchanged'] and record['installed_app_and_three_profiles_unchanged'])
    (run/'execution.json').write_text(json.dumps(record, indent=2)+'\n')
    print(json.dumps({k:v for k,v in record.items() if k not in ('helper_inputs_before','protected_before','protected_after')}, indent=2))
    print((run/'run.log').read_text()[-10000:])
    return 0 if record['passed'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
