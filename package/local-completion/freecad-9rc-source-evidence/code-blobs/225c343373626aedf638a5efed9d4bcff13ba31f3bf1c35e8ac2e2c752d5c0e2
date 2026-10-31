"""Root-only serial native gates with app/profile custody and exact source pins."""
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parent
REPO=Path('/Users/zukomgwili/src/FreeCAD')
GUARD=REPO/'package/local-completion/freecad-8rk-installation-evidence/run_gate.py'
assert hashlib.sha256(GUARD.read_bytes()).hexdigest()=='556371fd97edc9a393fed04427f670e3c4fb8ddf8c632d2ec0479152a6cdee9e'
spec=importlib.util.spec_from_file_location('_9rc_gate_core',GUARD)
core=importlib.util.module_from_spec(spec);spec.loader.exec_module(core)
core.ROOT=ROOT
core.SOURCE_FILES=tuple(str(p) for p in sorted(ROOT.glob('*.py')))+(str(REPO/'src/Mod/Fem/femtest/app/beam_coupling_fixtures.py'),)
changes=set(subprocess.check_output(['git','diff','--name-only','HEAD'],cwd=REPO,text=True).splitlines())
changes.update(subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=REPO,text=True).splitlines())
core.SOURCE_FILES += tuple(str(REPO/name) for name in sorted(changes) if name.startswith(('src/Mod/Fem/','package/calculix/force-accounting/')) or name in ('package/local-completion/freecad-9rc-oracles.md','package/local-completion/freecad-9rc-research.md','package/local-completion/freecad-9rc-usage.md','package/local-completion/freecad-sv7-usage.md'))
if os.environ.get('R9_TEST_SOLVER'):
 core.SOURCE_FILES += (os.environ['R9_TEST_SOLVER'],)
 os.environ['B960_TEST_SOLVER']=os.environ['R9_TEST_SOLVER']
 os.environ['SV7_TEST_SOLVER']=os.environ['R9_TEST_SOLVER']
 os.environ['FREECAD_CONTACT_STATE_SOLVER']=os.environ['R9_TEST_SOLVER']
if os.environ.get('R9_BASELINE_SOLVER'):
 core.SOURCE_FILES += (os.environ['R9_BASELINE_SOLVER'],)
if os.environ.get('R9_COLD_SOURCE_ROOT'):
 cold=Path(os.environ['R9_COLD_SOURCE_ROOT'])
 core.SOURCE_FILES += tuple(str(p) for pattern in ('*/coupled-contact.FCStd','*/section-data.json','*/contact-data.json') for p in sorted(cold.glob(pattern)))
run=ROOT/sys.argv[1]
os.environ['R9_CASE_ROOT']=str(run/'cases')
os.environ['R9_WITNESS_ROOT']=str(run/'cases')
os.environ['B960_WITNESS_ROOT']=str(run/'legacy')
os.environ['SV7_WITNESS_ROOT']=str(run/'legacy-coupled')
app=Path('/Applications/FreeCAD-27.1.0.app')
core.COMMANDS={'baseline':[str(app/'Contents/MacOS/FreeCAD'),'-u',str(run/'user.cfg'),'-s',str(run/'system.cfg'),'-P',str(ROOT),'-t','Rc9Baseline'], 'tracer':['/opt/homebrew/bin/pixi','run','--frozen',str(REPO/'build/release/bin/FreeCADCmd'),'-u',str(run/'user.cfg'),'-s',str(run/'system.cfg'),'-P',str(ROOT),'-t','Rc9Tracer']}
prefix=['/opt/homebrew/bin/pixi','run','--frozen']
core.COMMANDS.update({'scripts':prefix+['cmake','--build','build/release','--target','FemScriptsTarget','FemGuiScriptsTarget','--parallel','8'], 'formal':prefix+[str(REPO/'build/release/bin/FreeCADCmd'),'-u',str(run/'user.cfg'),'-s',str(run/'system.cfg'),'-t','femtest.app.test_beam_contact_native']})
cmdapp=prefix+[str(REPO/'build/release/bin/FreeCADCmd'),'-u',str(run/'user.cfg'),'-s',str(run/'system.cfg')]
core.COMMANDS.update({
 'compression':cmdapp+['-P',str(ROOT),'-t','Rc9Compression'],
 'lifecycle':cmdapp+['-t','femtest.app.test_beam_contact_lifecycle'],
 'rejections':cmdapp+['-t','femtest.app.test_beam_contact_rejections'],
 'cold':cmdapp+['-P',str(ROOT),'-t','Rc9Cold'],
 'regressions':cmdapp+['-P',str(ROOT),'-t','Rc9Regressions'],
 'all':cmdapp+['-t','TestFemApp'],
 'gui':prefix+[str(REPO/'build/release/bin/FreeCAD'),'-u',str(run/'user.cfg'),'-s',str(run/'system.cfg'),'-t','femtest.gui.test_beam_contact_coupling'],
 'build':prefix+['cmake','--build','build/release','--parallel','8'],
 'ctest':prefix+['ctest','--test-dir','build/release','--output-on-failure','--parallel','1'],
})
if os.environ.get('R9_PRODUCTION_SOLVER'):
 core.SOURCE_FILES += (os.environ['R9_PRODUCTION_SOLVER'],)
 core.COMMANDS['configure']=prefix+['cmake','-S','.', '-B','build/release','-DFREECAD_NATIVE_CCX_ACCOUNTING='+os.environ['R9_PRODUCTION_SOLVER']]
blobs=ROOT/'code-blobs';blobs.mkdir(exist_ok=True)
for path in map(Path,core.SOURCE_FILES):
 dest=blobs/hashlib.sha256(path.read_bytes()).hexdigest()
 if not dest.exists():shutil.copyfile(path,dest)
if __name__=='__main__':raise SystemExit(core.main())
