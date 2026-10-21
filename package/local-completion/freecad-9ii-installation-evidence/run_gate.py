"""9ii deployment source gates through the unchanged bounded 8rk supervisor."""
import hashlib
import importlib.util
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
ORIGINAL = REPO / 'package/local-completion/freecad-8rk-installation-evidence/run_gate.py'
EXPECTED = '556371fd97edc9a393fed04427f670e3c4fb8ddf8c632d2ec0479152a6cdee9e'
assert __debug__
assert hashlib.sha256(ORIGINAL.read_bytes()).hexdigest() == EXPECTED
spec = importlib.util.spec_from_file_location('_9ii_build_supervisor', ORIGINAL)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
core.ROOT = ROOT
source = __import__('json').loads((REPO / 'package/local-completion/freecad-9ii-validation.json').read_text())
core.SOURCE_FILES = tuple(source['source_files_sha256']) + (
    str(Path(__file__).resolve()),
    'src/Base/FileInfo.cpp', 'tests/src/Base/FileInfo.cpp', 'tests/src/App/BackupPolicy.cpp',
    'build/native-solvers/contact-state-0c2a86318df9/ccx-force-accounting',
)
core.PREFIX = ['/opt/homebrew/bin/pixi', 'run', '--frozen']
core.COMMANDS = {name: core.PREFIX + command[3:] for name, command in core.COMMANDS.items()}
serial, group_exists = core.serial, core.group_exists

if __name__ == '__main__':
    raise SystemExit(core.main())
