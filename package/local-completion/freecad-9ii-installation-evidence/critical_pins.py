"""9ii deployment custody; selected dependency pins are never a whole-prefix claim."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
ORIGINAL = REPO / 'package/local-completion/freecad-8rk-installation-evidence/critical_pins.py'
assert __debug__ and hashlib.sha256(ORIGINAL.read_bytes()).hexdigest() == 'a2e81c1d1adb5c8e18093b42e0b15b3bc2c194cfb352f3c76925b9120943cfdc'
spec = importlib.util.spec_from_file_location('_9ii_critical_core', ORIGINAL)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
core.ROOT = ROOT
core.RECEIPT = ROOT / 'critical-before-DESTDIR.json'
RECEIPT = core.RECEIPT
PREFIX, NAMESPACE = core.PREFIX, core.NAMESPACE
sha, record = core.sha, core.record


def snapshot():
    state = core.snapshot()
    candidate = REPO / 'build/native-solvers/contact-state-0c2a86318df9/ccx-force-accounting'
    assert sha(candidate) == '0c2a86318df9c7cc9d921e5068ae52f1d53e27b7b16747e00a74ccc8fe37c6cc'
    state[str(candidate)] = record(candidate)
    return state


def capture():
    import stage_install as install
    assert not RECEIPT.exists()
    install.compiled_identity()
    install.no_live_app()
    assert not install.BACKUP.exists() and not install.BACKUP.is_symlink()
    assert install.BACKUP.parent.is_dir() and not install.BACKUP.parent.is_symlink()
    install.verify(install.APP)
    note = (install.APP / 'Contents/Resources/LOCAL-INSTALL.txt').read_text()
    assert '4eb8f43362c0cbc5a0dab4869ad77be6f27ad679' in note and '49261+233' in note
    baseline = install.inventory(install.APP)
    assert install.canonical_sha(baseline) == 'ad3e2241c9688ea15738d70ad8bd8ad6bd1bf2469c3161825b7b1da158a93438'
    install.write_json(ROOT / 'baseline-inventory.json', baseline)
    install.write_json(ROOT / 'profile-inventories.json', {
        str(path): install.inventory(path) for path in install.PROFILES})
    proof = {'passed': True, 'scope': '17 selected critical files, not a whole-prefix inventory',
             'files': snapshot()}
    install.write_json(RECEIPT, proof)
    return proof


def verify():
    proof = json.loads(RECEIPT.read_text())
    assert proof['passed'] is True and snapshot() == proof['files'], 'Critical input/prefix changed'
    return proof
