"""Fresh tracer gates; original installed-baseline helper remains frozen."""
import hashlib
import importlib.util
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
ORIGINAL = REPO / 'package/local-completion/freecad-8rk-installation-evidence/run_gate.py'
assert __debug__ and hashlib.sha256(ORIGINAL.read_bytes()).hexdigest() == '556371fd97edc9a393fed04427f670e3c4fb8ddf8c632d2ec0479152a6cdee9e'
spec = importlib.util.spec_from_file_location('_beam960_tracer_guard', ORIGINAL)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
core.ROOT = ROOT
label, mode = sys.argv[1:3]
run = ROOT / label
os.environ['B960_RUN_DIR'] = str(run)
files = [Path(__file__).resolve(), ROOT / 'Beam960Tracer.py']
files += [REPO / 'src/Mod/Fem' / name for name in (
    'femtest/app/test_beam_section_forces.py', 'femobjects/solver_ccxtools.py',
    'femsolver/calculix/write_step_output.py', 'femtools/ccxtools.py')]
core.SOURCE_FILES = tuple(map(str, files))
prefix = ['/opt/homebrew/bin/pixi', 'run', '--frozen']
def command(executable):
    return prefix + [str(executable), '-u', str(run / 'user.cfg'), '-s', str(run / 'system.cfg'),
                     '-P', str(ROOT), '-t', 'Beam960Tracer']
core.COMMANDS = {
    'installed-tracer': command(Path('/Applications/FreeCAD-27.1.0.app/Contents/MacOS/FreeCADCmd')),
    'source-tracer': command(REPO / 'build/release/bin/FreeCADCmd'),
    'build': prefix + ['cmake', '--build', 'build/release', '--parallel', '8'],
}
if __name__ == '__main__':
    raise SystemExit(core.main())
