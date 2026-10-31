"""Root-only isolated diagnostic capability gate, with exact executable custody."""
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
spec = importlib.util.spec_from_file_location('_beam960_diag_guard', ORIGINAL)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
core.ROOT = ROOT
label, mode = sys.argv[1:3]
binary = (Path(sys.argv.pop()).resolve(strict=True) if len(sys.argv) == 4 else
          Path('/Applications/FreeCAD-27.1.0.app/Contents/Resources/data/NativeSolvers/ccx-force-accounting'))
run = ROOT / label
os.environ['B960_RUN_DIR'] = str(run)
os.environ['B960_BINARY'] = str(binary)
files = [Path(__file__).resolve(), ROOT / 'Beam960Capability.py', binary,
         REPO / 'package/calculix/force-accounting/hooks.patch']
core.SOURCE_FILES = tuple(map(str, files))
prefix = ['/opt/homebrew/bin/pixi', 'run', '--frozen']
core.COMMANDS = {'capability': prefix + [str(REPO / 'build/release/bin/FreeCADCmd'),
    '-u', str(run / 'user.cfg'), '-s', str(run / 'system.cfg'),
    '-P', str(ROOT), '-t', 'Beam960Capability']}
if __name__ == '__main__':
    raise SystemExit(core.main())
