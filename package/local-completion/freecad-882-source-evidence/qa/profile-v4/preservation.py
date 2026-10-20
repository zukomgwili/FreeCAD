"""Private, explicit app/profile and selected dependency custody; no native runs."""
import sys
sys.dont_write_bytecode = True
import hashlib
import json
import os
from pathlib import Path
import runpy
import stat

ROOT = Path(__file__).resolve().parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
ORIGINAL_HELPER = REPO / 'package/local-completion/freecad-ywu-installation-evidence/private/stage_install.py'
HELPER_SHA = 'cca627502a56b6c9b4aefa4a970172c51e42e2dde834000decca65fd44ab46d9'
APP = Path('/Applications/FreeCAD-27.1.0.app')
PREFIX = REPO / '.pixi/envs/default'
PROFILES = tuple(Path('/Users/zukomgwili') / name for name in (
    'Library/Application Support/FreeCAD', 'Library/Application Support/FreeCAD Local',
    'Library/Preferences/FreeCAD'))

def require(value, message):
    if not value:
        raise RuntimeError(message)

def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

require(sha(ORIGINAL_HELPER) == HELPER_SHA, 'Reviewed inventory helper changed')
INVENTORY = runpy.run_path(str(ORIGINAL_HELPER))['inventory']

def selected_inputs():
    paths = [REPO / 'pixi.toml', REPO / 'pixi.lock',
             PREFIX / 'lib/qt6/plugins/platforms/libqcocoa.dylib', PREFIX / 'bin/ccx']
    paths += [PREFIX / 'lib/python3.13/site-packages/freecad' / name for name in (
        'UiTools.py', '__init__.py', 'deprecation.py', 'freecad_doc.py', 'module_io.py',
        'part.py', 'partdesign.py', 'project_utility.py', 'sketcher.py', 'utils.py', 'utils_zip.py')]
    result = {}
    for path in paths:
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode), str(path))
        result[str(path)] = {'sha256': sha(path), 'mode': info.st_mode,
            'bytes': info.st_size, 'mtime_ns': info.st_mtime_ns,
            'link': os.readlink(path) if path.is_symlink() else None}
    return result

def write(path, value):
    with Path(path).open('x') as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True) + '\n')

def capture():
    from process_control import assert_serial
    assert_serial(('gmsh', 'ninja', 'make', 'gmake'))
    require(all(path.is_dir() for path in PROFILES), 'Expected protected profile missing')
    write(ROOT / 'private-baseline-app.json', INVENTORY(APP))
    write(ROOT / 'private-baseline-profiles.json', {str(path): INVENTORY(path) for path in PROFILES})
    write(ROOT / 'selected-inputs-before.json', selected_inputs())
    print(json.dumps({'passed': True, 'profiles': len(PROFILES), 'selected_files': 15,
                      'scope': 'selected dependency files only, not entire prefix'}))

def verify(original_app=True):
    if original_app:
        require(INVENTORY(APP) == json.loads((ROOT / 'private-baseline-app.json').read_text()),
                'Original app changed')
    for path, expected in json.loads((ROOT / 'private-baseline-profiles.json').read_text()).items():
        require(INVENTORY(Path(path)) == expected, 'Protected profile changed: ' + path)
    require(selected_inputs() == json.loads((ROOT / 'selected-inputs-before.json').read_text()),
            'Selected dependency inputs changed')
    return True

if __name__ == '__main__':
    require(not sys.flags.optimize and sys.argv[1:] in (['capture'], ['verify']), 'Explicit action required')
    if sys.argv[1] == 'capture':
        capture()
    else:
        verify()
        print(json.dumps({'passed': True, 'app_profiles_and_selected_inputs_unchanged': True}))
