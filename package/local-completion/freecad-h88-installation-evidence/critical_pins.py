"""Fresh h88 custody; selected critical files are not a whole-prefix inventory."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
REPO = Path("/Users/zukomgwili/src/FreeCAD")
ORIGINAL = REPO / "package/local-completion/freecad-8rk-installation-evidence/critical_pins.py"
assert __debug__ and not sys.flags.optimize
assert hashlib.sha256(ORIGINAL.read_bytes()).hexdigest() == "a2e81c1d1adb5c8e18093b42e0b15b3bc2c194cfb352f3c76925b9120943cfdc"
spec = importlib.util.spec_from_file_location("_h88_critical_core", ORIGINAL)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
core.ROOT = ROOT
core.RECEIPT = ROOT / "critical-before-DESTDIR.json"
RECEIPT = core.RECEIPT
PREFIX, NAMESPACE = core.PREFIX, core.NAMESPACE
sha, record = core.sha, core.record
BASELINE_COMMIT = "d15a59e8ff39d610337b02ca290fe477d24d065c"
BASELINE_INVENTORY_SHA = "0de4c139e9d2d90bfcfc12ce4fa9d0237687bdfa62aa5c82f667f1f43274903e"


def snapshot():
    state = core.snapshot()
    candidate = REPO / "build/native-solvers/contact-state-0c2a86318df9/ccx-force-accounting"
    assert sha(candidate) == "0c2a86318df9c7cc9d921e5068ae52f1d53e27b7b16747e00a74ccc8fe37c6cc"
    state[str(candidate)] = record(candidate)
    return state


def capture():
    import stage_install as install
    assert not RECEIPT.exists() and not RECEIPT.is_symlink()
    install.compiled_identity()
    install.no_live_app()
    assert set(install.PROFILES) == set(install.PROFILE_CANDIDATES) and len(install.PROFILES) == 3
    assert not install.BACKUP.exists() and not install.BACKUP.is_symlink()
    assert install.BACKUP.parent.is_dir() and not install.BACKUP.parent.is_symlink()
    install.verify(install.APP)
    note = (install.APP / "Contents/Resources/LOCAL-INSTALL.txt").read_text()
    assert BASELINE_COMMIT in note and "49261+235" in note
    baseline = install.inventory(install.APP)
    assert install.canonical_sha(baseline) == BASELINE_INVENTORY_SHA
    install.write_json(ROOT / "baseline-inventory.json", baseline)
    install.write_json(ROOT / "profile-inventories.json", {
        str(path): install.inventory(path) for path in install.PROFILES})
    proof = {"passed": True, "scope": "17 selected critical files, not a whole-prefix inventory",
             "identity_sha256": sha(ROOT / "identity.json"), "files": snapshot()}
    install.write_json(RECEIPT, proof)
    return proof


def verify():
    proof = json.loads(RECEIPT.read_text())
    assert proof["passed"] is True
    assert sha(ROOT / "identity.json") == proof["identity_sha256"], "Identity metadata changed"
    assert snapshot() == proof["files"], "Critical input/prefix changed"
    return proof
