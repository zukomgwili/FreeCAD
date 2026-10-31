"""Bounded literal bundle tests with private profiles and exact custody."""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
sys.dont_write_bytecode=True
import critical_pins
import run_gate
import stage_install as install
ROOT=Path(__file__).resolve().parent
COUNTS={'cmd':20,'gui':4,'cold':1}
def sha(path):return install.digest(Path(path))
def profiles():
 critical_pins.verify()
 return {str(p):install.canonical_sha(install.inventory(p)) for p in install.PROFILES}
def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('location',choices=('stage','installed'))
 parser.add_argument('mode',choices=tuple(COUNTS))
 args=parser.parse_args()
 run_gate.serial();install.compiled_identity()
 application=install.STAGE if args.location=='stage' else install.APP
 assert application.resolve(strict=True)==application and not application.is_symlink()
 sealed_path=ROOT/'stage-inventory.json'; sealed=json.loads(sealed_path.read_text())
 assert install.inventory(application)==sealed
 install.verify(application)
 original=install.canonical_sha(install.inventory(install.APP));before_profiles=profiles()
 run=ROOT/(args.location+'-'+args.mode);run.mkdir()
 temporary=run/'dotted.parent';temporary.mkdir()
 environment={k:v for k,v in os.environ.items() if not k.startswith(('FREECAD_','CCX_','DYLD_','LD_','APPQA_','I960_','B960_')) and k not in ('PYTHONPATH','PYTHONHOME','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_CACHE_HOME','TMPDIR','TMP','TEMP','DESTDIR')}
 for key in ('FREECAD_USER_HOME','FREECAD_USER_DATA','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_CACHE_HOME'):
  path=run/key.lower();path.mkdir();environment[key]=str(path)
 environment.update(TMPDIR=str(temporary)+'/',TMP=str(temporary),TEMP=str(temporary),
  FREECAD_USER_TEMP=str(temporary),PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',OMP_NUM_THREADS='2',
  I960_APP=str(application),I960_MODE=args.mode,I960_IDENTITY=str(ROOT/'identity.json'),B960_WITNESS_ROOT=str(run))
 extra=[sealed_path,ROOT/'identity.json']
 if args.mode=='cold':
  prior=ROOT/(args.location+'-gui');proof=json.loads((prior/'execution.json').read_text())
  assert proof['passed'] is True and proof['application']==str(application)
  saved=prior/'test_visible_solver_write_and_run_saves_current_native_beam_end_actions'
  document=saved/'native-beam-gui.FCStd';literal=saved/'saved-output.json'
  extra += [document,literal,prior/'execution.json',prior/'regression.json']
  environment.update(I960_COLD_DOCUMENT=str(document),I960_COLD_LITERAL=str(literal),
   I960_COLD_DOCUMENT_SHA256=sha(document),I960_COLD_LITERAL_SHA256=sha(literal))
 resources=application/'Contents/Resources'
 extra += [install.REPO/name for name in install.SOURCES]
 extra += [resources/name for name in install.SOURCES.values()]
 extra += [resources/name for name in ('bin/FreeCAD','bin/FreeCADCmd','data/NativeSolvers/ccx-force-accounting')]
 def inputs():
  return {str(p):sha(p) for p in sorted(set(extra)|set(ROOT.glob('*.py')))}
 before=inputs()
 executable='FreeCAD' if args.mode=='gui' else 'FreeCADCmd'
 module='ColdBeam960' if args.mode=='cold' else 'AppBeam960'
 command=[str(application/'Contents/MacOS'/executable),'-u',str(run/'user.cfg'),'-s',str(run/'system.cfg'),'-P',str(ROOT),'-t',module]
 report={'schema':'FreeCAD-960-literal-application-gate-v1','passed':False,'application':str(application),
  'location':args.location,'mode':args.mode,'source_commit':install.COMMIT,'revision':install.REVISION,
  'native_sha256':install.NATIVE_SHA,'expected_tests':COUNTS[args.mode],'command':command,
  'inputs_before':before,'source_or_build_import_override':False,'native_solver_override':False}
 started=time.monotonic();timed_out=False;child=None
 try:
  with (run/'run.log').open('xb') as output:
   child=subprocess.Popen(command,cwd=run,env=environment,stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
   try:child.wait(timeout=900)
   except subprocess.TimeoutExpired:timed_out=True
   finally:
    for number in (signal.SIGTERM,signal.SIGKILL):
     if child.poll() is None or run_gate.group_exists(child.pid):
      try:os.killpg(child.pid,number)
      except ProcessLookupError:pass
      try:child.wait(timeout=3)
      except subprocess.TimeoutExpired:pass
  text=(run/'run.log').read_text(errors='replace')
  counts=re.findall(r'^Ran (\d+) tests? in [0-9.]+s$',text,re.M)
  skipped=re.findall(r'^.*\.\.\. skipped.*$',text,re.M)
  reg_path=run/'regression.json';reg=json.loads(reg_path.read_text()) if reg_path.exists() else {}
  valid=(counts==[str(COUNTS[args.mode])] and len(re.findall(r'^OK$',text,re.M))==1 and not skipped
   and not re.search(r'^(?:FAILED|FAIL:|ERROR:|UNEXPECTED SUCCESS)',text,re.M)
   and reg.get('passed') is True and reg.get('application')==str(application)
   and reg.get('commit')==install.COMMIT and reg.get('mode')==args.mode
   and reg.get('expected_tests')==reg.get('executed_tests')==COUNTS[args.mode]
   and reg.get('native_sha256')==install.NATIVE_SHA)
  after=inputs();current=install.inventory(application)
  install.verify(application);install.compiled_identity();run_gate.serial()
  report.update(returncode=child.returncode,timed_out=timed_out,child_reaped=child.poll() is not None,
   process_group_gone=not run_gate.group_exists(child.pid),executed_tests=int(counts[0]) if len(counts)==1 else 0,
   skipped_lines=skipped,inputs_after=after,inputs_unchanged=before==after,
   application_unchanged=current==sealed,application_inventory_sha256=install.canonical_sha(current),
   profiles_and_dependencies_unchanged=before_profiles==profiles(),
   original_app_unchanged=original==install.canonical_sha(install.inventory(install.APP)),
   strict_signature_verified=True,log_sha256=sha(run/'run.log'),
   regression_sha256=sha(reg_path) if reg_path.exists() else None,semantic_tests_passed=valid)
  report['passed']=bool(child.returncode==0 and not timed_out and valid and all(report[key] for key in
   ('child_reaped','process_group_gone','inputs_unchanged','application_unchanged','profiles_and_dependencies_unchanged','original_app_unchanged','strict_signature_verified')))
 except BaseException as error:
  report['supervisor_error']=repr(error);raise
 finally:
  report['elapsed_seconds']=time.monotonic()-started
  install.write_json(run/'execution.json',report)
  print(json.dumps({k:v for k,v in report.items() if k not in ('inputs_before','inputs_after')},indent=2))
 return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
