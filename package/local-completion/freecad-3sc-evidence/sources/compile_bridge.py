import json
from pathlib import Path
import shlex
import subprocess

root = Path(__file__).resolve().parent
repo = Path('/Users/zukomgwili/src/FreeCAD')
database = json.loads((repo / 'build/release/compile_commands.json').read_text())
entry = next(e for e in database if e['file'].endswith('/MaterialPyImp.cpp'))
command = shlex.split(entry['command'])
filtered = []
skip = False
for part in command:
    if skip:
        skip = False
        continue
    if part in ('-o', '-MF', '-MT', '-MQ'):
        skip = True
    elif part in ('-c', '-MD', '-MMD', '-MP') or part == entry['file']:
        continue
    else:
        filtered.append(part)
prefix = repo / '.pixi/envs/default'
app_lib = Path('/Applications/FreeCAD-27.1.0.app/Contents/Resources/lib')
filtered += [f'-I{prefix}/include/qt6/QtGui', '-bundle', '-undefined', 'dynamic_lookup',
             str(root / 'GuiMaterialReadBridge.cpp'), str(app_lib / 'Materials.so'),
             f'-L{prefix}/lib', '-lQt6Gui', '-lQt6Core',
             f'-Wl,-rpath,{app_lib}', f'-Wl,-rpath,{prefix}/lib',
             '-o', str(root / 'GuiMaterialReadBridge.so')]
print(shlex.join(filtered))
subprocess.run(filtered, check=True, cwd=entry['directory'])
