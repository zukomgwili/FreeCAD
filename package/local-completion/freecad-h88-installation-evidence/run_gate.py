"""Fresh h88 deployment build gates using the immutable bounded supervisor."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
ORIGINAL = REPO / 'package/local-completion/freecad-8rk-installation-evidence/run_gate.py'
assert __debug__ and hashlib.sha256(ORIGINAL.read_bytes()).hexdigest() == '556371fd97edc9a393fed04427f670e3c4fb8ddf8c632d2ec0479152a6cdee9e'
spec = importlib.util.spec_from_file_location('_h88_build_supervisor', ORIGINAL)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
core.ROOT = ROOT
prior = json.loads((REPO / 'package/local-completion/freecad-9ii-validation.json').read_text())
core.SOURCE_FILES = tuple(prior['source_files_sha256']) + (
    str(Path(__file__).resolve()),
    'src/Base/FileInfo.cpp', 'tests/src/Base/FileInfo.cpp', 'tests/src/App/BackupPolicy.cpp',
    'build/native-solvers/contact-state-0c2a86318df9/ccx-force-accounting',
    'src/Mod/BIM/ArchComponent.py', 'src/Mod/BIM/ArchStructure.py',
    'src/Mod/BIM/TestArch.py', 'src/Mod/BIM/bimtests/TestArchShapeCleanup.py',
    'src/Mod/BIM/CMakeLists.txt',
)
core.PREFIX = ['/opt/homebrew/bin/pixi', 'run', '--frozen']
core.COMMANDS = {name: core.PREFIX + command[3:] for name, command in core.COMMANDS.items()}
serial, group_exists = core.serial, core.group_exists

if __name__ == '__main__':
    raise SystemExit(core.main())
