"""Selected external dependency/input custody; never mutate the live prefix."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import stat
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
PREFIX = REPO / '.pixi/envs/default'
RECEIPT = ROOT / 'critical-before-DESTDIR.json'
NAMESPACE = tuple('lib/python3.13/site-packages/freecad/' + name for name in (
    'UiTools.py', '__init__.py', 'deprecation.py', 'freecad_doc.py', 'module_io.py',
    'part.py', 'partdesign.py', 'project_utility.py', 'sketcher.py', 'utils.py', 'utils_zip.py'))


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def record(path):
    info = path.lstat()
    row = {'dev': info.st_dev, 'inode': info.st_ino, 'mode': info.st_mode,
           'size': info.st_size, 'mtime_ns': info.st_mtime_ns, 'ctime_ns': info.st_ctime_ns}
    if stat.S_ISLNK(info.st_mode):
        row.update(kind='link', target=os.readlink(path), resolved=str(path.resolve(strict=True)),
                   resolved_sha256=sha(path))
    else:
        assert stat.S_ISREG(info.st_mode), path
        row.update(kind='file', sha256=sha(path))
    return row


def snapshot():
    cache = REPO / 'build/release/CMakeCache.txt'
    assert '\nCMAKE_INSTALL_PREFIX:PATH=/Applications/FreeCAD-27.1.0.app/Contents/Resources\n' in cache.read_text()
    paths = [REPO / 'pixi.toml', REPO / 'pixi.lock', cache,
             PREFIX / 'lib/qt6/plugins/platforms/libqcocoa.dylib', PREFIX / 'bin/ccx']
    for relative in NAMESPACE:
        path = PREFIX / relative
        assert path.is_file() and not path.is_symlink()
        parent = path.parent
        while parent != PREFIX:
            assert parent.is_dir() and not parent.is_symlink()
            parent = parent.parent
        paths.append(path)
    assert sha(paths[3]) == 'b5929d48bec6a97ce61f6792a866daf5c3ea6badb9d58d98bc0eeaf75ed3e704'
    assert sha(paths[4]) == 'b94868f6dd50533d7a8f11d271864a04bbf01f4117046d0c5b35e3cad470aac6'
    return {str(path): record(path) for path in paths}


def capture():
    assert not RECEIPT.exists()
    state = runpy.run_path(str(ROOT / 'stage_install.py'))
    state['compiled_identity']()
    state['no_live_app']()
    assert not state['BACKUP'].exists() and not state['BACKUP'].is_symlink()
    assert state['BACKUP'].parent.is_dir() and not state['BACKUP'].parent.is_symlink()
    state['verify'](state['APP'])
    note = (state['APP'] / 'Contents/Resources/LOCAL-INSTALL.txt').read_text()
    assert '7667033a14654a9b229bf59b94cb3012ce989170' in note
    assert '49261+224' in note
    state['write_json'](ROOT / 'baseline-inventory.json', state['inventory'](state['APP']))
    state['write_json'](ROOT / 'profile-inventories.json', {
        str(path): state['inventory'](path) for path in state['PROFILES']})
    proof = {'passed': True, 'scope': '16 selected critical files, not a whole-prefix inventory',
             'files': snapshot()}
    state['write_json'](RECEIPT, proof)
    return proof


def verify():
    proof = json.loads(RECEIPT.read_text())
    assert proof['passed'] and snapshot() == proof['files'], 'Critical input/prefix changed'
    return proof
