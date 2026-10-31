"""Root-only isolated, bounded native-observer build with unchanged app/profile custody."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import runpy
import signal
import subprocess
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
GUARD = REPO / 'package/local-completion/freecad-8rk-installation-evidence/run_gate.py'
CORE = REPO / 'package/local-completion/freecad-ywu-installation-evidence/private/stage_install.py'
def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()
assert __debug__ and sha(GUARD) == '556371fd97edc9a393fed04427f670e3c4fb8ddf8c632d2ec0479152a6cdee9e'
assert sha(CORE) == 'cca627502a56b6c9b4aefa4a970172c51e42e2dde834000decca65fd44ab46d9'
spec = importlib.util.spec_from_file_location('_beam960_native_build_guard', GUARD)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
inventory = runpy.run_path(str(CORE))['inventory']
ARCHIVE = Path('/private/tmp/freecad-960-semantics-gdfoMero/ccx_2.23.src.tar.bz2')
RECIPE = Path('/Users/zukomgwili/Library/Caches/rattler/cache/pkgs/calculix-2.23-pl5321hd17ca8b_8/info/recipe')
DRIVER = REPO / 'package/local-completion/calculix-9zt-probe'
NATIVE = REPO / 'package/calculix/force-accounting'
label = sys.argv[1]
assert len(sys.argv) == 2 and all(c.isalnum() or c == '-' for c in label)
run = ROOT / label
run.mkdir()
paths = [Path(__file__).resolve(), GUARD, CORE, ARCHIVE,
         *[DRIVER / name for name in ('build_probe.py', 'pixi.toml', 'pixi.lock', 'recipe-pins.json')],
         *[NATIVE / name for name in ('hooks.patch', 'forceaccounting.c', 'contactstate.c',
                                      'beamsection.c', 'beamsection.patch')]]
paths += [RECIPE / name for name in json.loads((DRIVER / 'recipe-pins.json').read_text())]
def inputs():
    return {str(path): sha(path) for path in paths}
def custody():
    return {str(path): hashlib.sha256(json.dumps(inventory(path), sort_keys=True).encode()).hexdigest()
            for path in (guard.APP, *guard.PROFILES)}
guard.serial()
before, protected = inputs(), custody()
assert before[str(ARCHIVE)] == '9c88385c10fb04f5dc6c4e98027a51bebdd8aee3920e05190d6c1dd08357d6e7'
temp = run / 'dotted.parent'
temp.mkdir()
env = dict(os.environ)
for key in tuple(env):
    if key.startswith(('FREECAD_', 'CCX_', 'DYLD_', 'LD_', 'APPQA_')) or key in (
        'PYTHONPATH','PYTHONHOME','TMPDIR','TMP','TEMP','DESTDIR',
        'XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_CACHE_HOME'):
        env.pop(key)
for key in ('FREECAD_USER_HOME','FREECAD_USER_DATA','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_CACHE_HOME'):
    place = run / key.lower()
    place.mkdir()
    env[key] = str(place)
env.update(TMPDIR=str(temp)+'/', TMP=str(temp), TEMP=str(temp), FREECAD_USER_TEMP=str(temp),
           PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', OMP_NUM_THREADS='2')
command = ['/opt/homebrew/bin/pixi','run','--frozen','python','-B',str(DRIVER/'build_probe.py'),
           '--source-archive',str(ARCHIVE),'--recipe',str(RECIPE),'--workdir',str(run/'build'),
           '--patch',str(NATIVE/'hooks.patch'),'--extra-source',str(NATIVE/'forceaccounting.c'),
           '--contact-source',str(NATIVE/'contactstate.c'),'--beam-source',str(NATIVE/'beamsection.c'),
           '--beam-patch',str(NATIVE/'beamsection.patch'),
           '--runtime-prefix',str(REPO/'.pixi/envs/default')]
report = {'schema':'FreeCAD-960-isolated-native-build-v1','mode':'native-build','command':command,
          'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
          'source_inputs_before':before,'protected_before':protected,'passed':False,
          'installation_performed':False,'isolated_temporary_directory':str(temp),
          'dot_free_substitution':False}
child = None
timed_out = False
started = time.monotonic()
def interrupted(number, _frame):
    raise RuntimeError('Native build interrupted by signal '+str(number))
for number in (signal.SIGTERM,signal.SIGHUP):
    signal.signal(number, interrupted)
try:
    with (run/'run.log').open('xb') as output:
        child = subprocess.Popen(command,cwd=REPO,env=env,stdin=subprocess.DEVNULL,
                                 stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            child.wait(timeout=2700)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            for number in (signal.SIGTERM,signal.SIGKILL):
                if child.poll() is None or guard.group_exists(child.pid):
                    try: os.killpg(child.pid, number)
                    except ProcessLookupError: pass
                    try: child.wait(timeout=3)
                    except subprocess.TimeoutExpired: pass
    report.update(returncode=child.returncode,timed_out=timed_out,
                  child_reaped=child.poll() is not None,process_group_gone=not guard.group_exists(child.pid))
finally:
    report.update(elapsed_seconds=time.monotonic()-started,source_inputs_after=inputs(),
                  protected_after=custody(),log_sha256=sha(run/'run.log'))
    report['source_and_supervisor_unchanged'] = before == report['source_inputs_after']
    report['app_and_three_profiles_unchanged'] = protected == report['protected_after']
    guard.serial()
    report['passed'] = bool(report.get('returncode') == 0 and not timed_out
        and report.get('child_reaped') and report.get('process_group_gone')
        and report['source_and_supervisor_unchanged'] and report['app_and_three_profiles_unchanged'])
    with (run/'execution.json').open('x') as stream:
        json.dump(report,stream,indent=2); stream.write('\n')
    print(json.dumps({key:value for key,value in report.items()
        if key not in ('source_inputs_before','source_inputs_after','protected_before','protected_after')},indent=2))
raise SystemExit(0 if report['passed'] else 1)
