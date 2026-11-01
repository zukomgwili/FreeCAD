"""Root-only serial native gates with immutable app/profile custody."""
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
spec=importlib.util.spec_from_file_location('_bjh_gate_core',GUARD)
core=importlib.util.module_from_spec(spec);spec.loader.exec_module(core)
core.ROOT=ROOT
core.SOURCE_FILES=tuple(str(ROOT/name) for name in ('run_gate.py','run_native_build.py','BjhBaseline.py','BjhComponent.py','BjhMechanics.py','BjhMechanicsBounded.py','BjhCold.py','BjhRegressions.py') if (ROOT/name).exists())
core.SOURCE_FILES+=tuple(str(p) for p in sorted(ROOT.glob('*.md')))
if sys.argv[2] not in ('mechanics','bounded-mechanics'):
 core.SOURCE_FILES+=(str(REPO/'src/Mod/Fem/femtest/app/test_beam_section_forces_native.py'),)
changes=set(subprocess.check_output(['git','diff','--name-only','HEAD'],cwd=REPO,text=True).splitlines())
changes.update(subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=REPO,text=True).splitlines())
core.SOURCE_FILES+=tuple(str(REPO/n) for n in sorted(changes) if n.startswith('package/calculix/force-accounting/') or sys.argv[2] not in ('mechanics','bounded-mechanics') and (n.startswith('src/Mod/Fem/') or n in ('package/local-completion/freecad-bjh-research.md','package/local-completion/freecad-bjh-oracles.md','package/local-completion/freecad-bjh-connected-oracles.md','package/local-completion/freecad-bjh-fork-oracles.md','package/local-completion/freecad-bjh-usage.md')))
if os.environ.get('BJH_TEST_SOLVER'):
 for key in ('B960_TEST_SOLVER','SV7_TEST_SOLVER','FREECAD_CONTACT_STATE_SOLVER','R9_TEST_SOLVER'):
  os.environ[key]=os.environ['BJH_TEST_SOLVER']
run=ROOT/sys.argv[1]
os.environ['BJH_CASE_ROOT']=str(run/'cases')
os.environ['BJH_WITNESS_ROOT']=str(run/'cases')
if os.environ.get('BJH_TEST_SOLVER'):
 core.SOURCE_FILES+=(os.environ['BJH_TEST_SOLVER'],)
if os.environ.get('BJH_COMPONENT_SOURCE'):
 source=Path(os.environ['BJH_COMPONENT_SOURCE'])
 core.SOURCE_FILES+=(str(source/'section-data.json'),)
 core.SOURCE_FILES+=tuple(str(p) for p in sorted(source.glob('*.frd')))
 core.SOURCE_FILES+=tuple(str(p) for p in sorted(source.glob('NetworkMesh.inp')))
if os.environ.get('BJH_BASELINE_SOLVER'):
 core.SOURCE_FILES+=(os.environ['BJH_BASELINE_SOLVER'],)
if os.environ.get('BJH_COLD_SOURCE'):
 source=Path(os.environ['BJH_COLD_SOURCE'])
 core.SOURCE_FILES+=tuple(str(p) for pattern in ('*/*.FCStd','*/section-data.json') for p in sorted(source.glob(pattern)))
prefix=['/opt/homebrew/bin/pixi','run','--frozen']
def application(path,module):
 return [str(path),'-u',str(run/'user.cfg'),'-s',str(run/'system.cfg'),'-P',str(ROOT),'-t',module]
core.COMMANDS={
 'baseline':prefix+application(REPO/'build/release/bin/FreeCAD','BjhBaseline'),
 'installed-baseline':application(Path('/Applications/FreeCAD-27.1.0.app/Contents/MacOS/FreeCAD'),'BjhBaseline'),
 'scripts':prefix+['cmake','--build','build/release','--target','FemScriptsTarget','FemGuiScriptsTarget','--parallel','8'],
 'formal':prefix+application(REPO/'build/release/bin/FreeCADCmd','femtest.app.test_beam_network_native'),
 'component':prefix+application(REPO/'build/release/bin/FreeCADCmd','BjhComponent'),
 'bounded-mechanics':prefix+['python','-B',str(ROOT/'BjhMechanicsBounded.py')],
 'mechanics':prefix+['python','-B',str(ROOT/'BjhMechanics.py')],
 'gui':prefix+application(REPO/'build/release/bin/FreeCAD','femtest.gui.test_beam_network_coupling'),
 'all':prefix+application(REPO/'build/release/bin/FreeCADCmd','TestFemApp'),
 'build':prefix+['cmake','--build','build/release','--parallel','8'],
 'ctest':prefix+['ctest','--test-dir','build/release','--output-on-failure','--parallel','1'],
 'regressions':prefix+application(REPO/'build/release/bin/FreeCADCmd','BjhRegressions'),
 'fork':prefix+application(REPO/'build/release/bin/FreeCADCmd','femtest.app.test_beam_network_fork'),
 'cold':prefix+application(REPO/'build/release/bin/FreeCADCmd','BjhCold'),
 'integrity':prefix+application(REPO/'build/release/bin/FreeCADCmd','femtest.app.test_beam_network_integrity'),
}
if os.environ.get('BJH_PRODUCTION_SOLVER'):
 core.SOURCE_FILES+=(os.environ['BJH_PRODUCTION_SOLVER'],)
 core.COMMANDS['configure']=prefix+['cmake','-S','.', '-B','build/release','-DFREECAD_NATIVE_CCX_ACCOUNTING='+os.environ['BJH_PRODUCTION_SOLVER']]
if sys.argv[2] not in ('build','configure','scripts','mechanics','bounded-mechanics'):
 actual=[]
 for path in tuple(core.SOURCE_FILES):
  source=Path(path)
  if source.is_relative_to(REPO/'src/Mod/Fem') and source.suffix=='.py':
   target=REPO/'build/release/Mod/Fem'/source.relative_to(REPO/'src/Mod/Fem')
   assert target.read_bytes()==source.read_bytes(), 'Uncopied Python source: '+str(source)
   actual.append(str(target))
 actual.extend(str(REPO/'build/release'/name) for name in ('bin/FreeCAD','bin/FreeCADCmd','data/NativeSolvers/ccx-force-accounting'))
 core.SOURCE_FILES+=tuple(actual)
blobs=ROOT/'code-blobs';blobs.mkdir(exist_ok=True)
for path in map(Path,core.SOURCE_FILES):
 target=blobs/hashlib.sha256(path.read_bytes()).hexdigest()
 if not target.exists():shutil.copyfile(path,target)
if __name__=='__main__':raise SystemExit(core.main())
