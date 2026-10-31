"""Root-only native gates under the immutable isolated bounded supervisor."""
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
spec = importlib.util.spec_from_file_location('_beam960_bounded_native', ORIGINAL)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
core.ROOT = ROOT
label, mode = sys.argv[1:3]
run = ROOT / label
os.environ['B960_RUN_DIR'] = str(run)
installed = Path('/Applications/FreeCAD-27.1.0.app/Contents/Resources')
paths = [*ROOT.glob('*.py'), REPO / 'src/Mod/Fem/femexamples/ccx_cantilever_base_edge.py']
paths += [installed / name for name in (
    'Mod/Fem/femsolver/calculix/write_step_output.py',
    'Mod/Fem/femtools/ccxtools.py', 'Mod/Fem/femobjects/solver_ccxtools.py',
    'Mod/Fem/feminout/importCcxFrdResults.py', 'bin/FreeCADCmd',
    'data/NativeSolvers/ccx-force-accounting')]
core.SOURCE_FILES = tuple(map(str, paths))
prefix = ['/opt/homebrew/bin/pixi', 'run', '--frozen']
core.COMMANDS = {
    'installed-baseline': prefix + [str(installed.parent / 'MacOS/FreeCADCmd'),
        '-u', str(run / 'user.cfg'), '-s', str(run / 'system.cfg'),
        '-P', str(ROOT), '-t', 'Beam960Baseline'],
}
if __name__ == '__main__':
    raise SystemExit(core.main())
