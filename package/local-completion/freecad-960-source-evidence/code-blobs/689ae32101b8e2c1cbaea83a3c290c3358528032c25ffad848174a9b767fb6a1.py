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
    'femtest/app/test_beam_section_forces_native.py',
    'femtest/app/test_beam_section_forces_safety.py',
    'femtest/app/test_beam_section_forces_lifecycle.py',
    'femtest/gui/test_beam_section_forces.py', 'femtaskpanels/task_solver_ccxtools.py',
    'femviewprovider/view_beam_section_forces.py',
    'femobjects/solver_ccxtools.py', 'femtools/beam_section_forces.py', 'femtools/ccxtools.py',
    'femtools/force_accounting.py', 'feminout/importCcxFrdResults.py',
    'femsolver/calculix/write_step_output.py', 'femsolver/calculix/writer.py')]
files += [REPO / 'package/calculix/force-accounting' / name for name in (
    'beamsection.c','beamsection.patch','forceaccounting.c','contactstate.c','hooks.patch')]
if mode in ('cold','cold-gui'):
    cold = json.loads((ROOT/'cold-source.json').read_text())
    files += [ROOT/'Beam960Cold.py',ROOT/'cold-source.json',Path(cold['document']),Path(cold['literal'])]
if mode == 'legacy':
    files = [Path(__file__).resolve(), ROOT/'native-candidate.json',
             Path(config['receipt']),Path(config['path'])]
    files += [REPO/'package/calculix/force-accounting'/name for name in
              ('beamsection.c','beamsection.patch','forceaccounting.c','contactstate.c','hooks.patch')]
    files += [ROOT/'LegacyBeam.py',Path('/Applications/FreeCAD-27.1.0.app/Contents/Resources/data/NativeSolvers/ccx-force-accounting')]
    for method in ('test_axial_tension_root_has_negative_global_end_action',
                   'test_transverse_y_root_has_signed_shear_and_bending_equilibrium',
                   'test_torsion_couple_preserves_distinct_native_ends_at_a_shared_joint'):
        files.append(ROOT/'torsion-matrix-r01'/method/'Mesh.inp')
        files.append(ROOT/'torsion-matrix-r01'/method/'Mesh.beam-section')
stable_solver = REPO/'build/native-solvers'/('beam-section-'+config['sha256'][:12])/'ccx-force-accounting'
if mode == 'stage-solver':
    files = [Path(__file__).resolve(),ROOT/'StageBeamSolver.py',ROOT/'native-candidate.json',
             Path(config['path']),Path(config['receipt'])]
if mode == 'configure':
    files.append(stable_solver)
core.SOURCE_FILES = tuple(map(str, files))
os.environ.update(B960_RUN_DIR=str(run), B960_TEST_SOLVER=config['path'], B960_CASE=mode,
                  B960_WITNESS_ROOT=str(run))
prefix = ['/opt/homebrew/bin/pixi','run','--frozen']
command = prefix + [str(REPO/'build/release/bin/FreeCADCmd'),'-u',str(run/'user.cfg'),
                    '-s',str(run/'system.cfg'),'-P',str(ROOT),'-t','Beam960Qualified']
core.COMMANDS = {'build':prefix+['cmake','--build','build/release','--parallel','8'],
                 'stage-solver':prefix+['python','-B',str(ROOT/'StageBeamSolver.py')],
                 'configure':prefix+['cmake','-S','.', '-B','build/release',
                     '-DFREECAD_NATIVE_CCX_ACCOUNTING='+str(stable_solver)],
                 'cold-gui':prefix+[str(REPO/'build/release/bin/FreeCAD'),'-u',str(run/'user.cfg'),
                     '-s',str(run/'system.cfg'),'-P',str(ROOT),'-t','Beam960Cold'],
                 'legacy':prefix+[str(REPO/'build/release/bin/FreeCADCmd'),'-u',str(run/'user.cfg'),
                     '-s',str(run/'system.cfg'),'-P',str(ROOT),'-t','LegacyBeam'],
                 'cold':prefix+[str(REPO/'build/release/bin/FreeCADCmd'),'-u',str(run/'user.cfg'),
                     '-s',str(run/'system.cfg'),'-P',str(ROOT),'-t','Beam960Cold'],
                 'scripts':prefix+['cmake','--build','build/release','--target',
                                   'FemScriptsTarget','FemGuiScriptsTarget','--parallel','8'],
                 'request':command,'axial':command,'transverse':command,'safety':command,
                 'off':command,'relative':command,'projection':command,'lifecycle':command,'frame':command,
                 'comment':command,
                 'gui':prefix+[str(REPO/'build/release/bin/FreeCAD'),'-u',str(run/'user.cfg'),
                               '-s',str(run/'system.cfg'),'-P',str(ROOT),'-t','Beam960Qualified']}
if __name__ == '__main__':
    raise SystemExit(core.main())
