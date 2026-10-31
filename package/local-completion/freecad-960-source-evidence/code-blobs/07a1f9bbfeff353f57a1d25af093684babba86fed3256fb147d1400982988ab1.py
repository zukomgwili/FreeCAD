"""Root-only source qualification with exact native build/source bindings."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
ORIGINAL = REPO / 'package/local-completion/freecad-8rk-installation-evidence/run_gate.py'
def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
assert __debug__ and sha(ORIGINAL) == '556371fd97edc9a393fed04427f670e3c4fb8ddf8c632d2ec0479152a6cdee9e'
spec = importlib.util.spec_from_file_location('_beam960_qualified_guard', ORIGINAL)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
core.ROOT = ROOT
label, mode = sys.argv[1:3]
run = ROOT / label
config = json.loads((ROOT / 'native-candidate.json').read_text())
native = json.loads(Path(config['receipt']).read_text())
assert native['binary_sha256'] == config['sha256'] == sha(config['path'])
assert native['dependency_functional_tests_passed'] is True
for key, name in (('beam_source_sha256','beamsection.c'),('beam_patch_sha256','beamsection.patch'),
                  ('extra_source_sha256','forceaccounting.c'),('contact_source_sha256','contactstate.c'),
                  ('probe_patch_sha256','hooks.patch')):
    assert native[key] == sha(REPO / 'package/calculix/force-accounting' / name)
files = [Path(__file__).resolve(), ROOT / 'Beam960Qualified.py', ROOT / 'native-candidate.json',
         Path(config['receipt']), Path(config['path'])]
files += [REPO / 'src/Mod/Fem' / name for name in (
    'CMakeLists.txt', 'TestFemApp.py', 'femtest/app/test_beam_section_forces.py',
    'femobjects/solver_ccxtools.py', 'femtools/beam_section_forces.py', 'femtools/ccxtools.py',
    'femtools/force_accounting.py', 'feminout/importCcxFrdResults.py',
    'femsolver/calculix/write_step_output.py', 'femsolver/calculix/writer.py')]
files += [REPO / 'package/calculix/force-accounting' / name for name in (
    'beamsection.c','beamsection.patch','forceaccounting.c','contactstate.c','hooks.patch')]
core.SOURCE_FILES = tuple(map(str, files))
os.environ.update(B960_RUN_DIR=str(run), B960_TEST_SOLVER=config['path'], B960_CASE=mode,
                  B960_WITNESS_ROOT=str(run))
prefix = ['/opt/homebrew/bin/pixi','run','--frozen']
command = prefix + [str(REPO/'build/release/bin/FreeCADCmd'),'-u',str(run/'user.cfg'),
                    '-s',str(run/'system.cfg'),'-P',str(ROOT),'-t','Beam960Qualified']
core.COMMANDS = {'build':prefix+['cmake','--build','build/release','--parallel','8'],
                 'request':command,'axial':command}
if __name__ == '__main__':
    raise SystemExit(core.main())
