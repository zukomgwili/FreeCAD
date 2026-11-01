"""Fresh e4k selected dependency/profile custody; no live-prefix writes."""

import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = Path("/Users/zukomgwili/src/FreeCAD")
original = REPO / "package/local-completion/freecad-8rk-installation-evidence/critical_pins.py"
assert (
    hashlib.sha256(original.read_bytes()).hexdigest()
    == "a2e81c1d1adb5c8e18093b42e0b15b3bc2c194cfb352f3c76925b9120943cfdc"
)
spec = importlib.util.spec_from_file_location("_e4k_critical_core", original)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
core.ROOT = ROOT
core.RECEIPT = ROOT / "critical-before-DESTDIR.json"
RECEIPT = core.RECEIPT


def snapshot():
    result = core.snapshot()
    path = REPO / "build/native-solvers/staged-selfweight-d4970161eb4e/ccx-force-accounting"
    assert core.sha(path) == "d4970161eb4ec8ea4af7e222d2a1c6dc54f960df33f0f0b0aff00195f1b37959"
    result[str(path)] = core.record(path)
    return result


def capture():
    import stage_install as install

    install.compiled_identity()
    install.no_live_app()
    install.verify(install.APP)
    assert not install.BACKUP.exists() and not install.BACKUP.is_symlink()
    assert install.BACKUP.parent.is_dir() and not install.BACKUP.parent.is_symlink()
    baseline = install.inventory(install.APP)
    assert (
        install.canonical_sha(baseline)
        == "06d689ed5ff8c8f19533cb548d1111f9399790239713d6a1d74ee9ee073a125f"
    )
    install.write_json(ROOT / "baseline-inventory.json", baseline)
    install.write_json(
        ROOT / "profile-inventories.json", {str(p): install.inventory(p) for p in install.PROFILES}
    )
    proof = {
        "passed": True,
        "scope": "17 selected critical files, not a whole-prefix inventory",
        "files": snapshot(),
    }
    install.write_json(RECEIPT, proof)
    return proof


def verify():
    proof = json.loads(RECEIPT.read_text())
    assert (
        proof["passed"] is True and proof["files"] == snapshot()
    ), "Critical dependency inputs changed"
    return proof
