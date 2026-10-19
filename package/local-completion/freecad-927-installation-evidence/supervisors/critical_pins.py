"""Read-only critical prefix custody, captured before the first DESTDIR action.

Only private receipts are written. No app, dependency, namespace or profile is
modified. lstat identities omit atime because hashing may update access time.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

ROOT = Path(__file__).resolve().parent
REPO = Path("/Users/zukomgwili/src/FreeCAD")
PREFIX = REPO / ".pixi/envs/default"
RECEIPT = ROOT / "critical-before-DESTDIR.json"
FIXED = {
    "pixi.toml": "119ea10b858e6926f16a014b3245b3f301a3624500bf6b5b8c6c98010c55352b",
    "pixi.lock": "730693309df0ef3afd2c35ea7becf1dc4cd097bfd4b287a459449ca1a1b81ad7",
    "build/release/CMakeCache.txt": "dfd57e93eaf716b81fb45af9cb8a953bc6a3e37b8ce88d63023a75620bba370d",
    ".pixi/envs/default/lib/qt6/plugins/platforms/libqcocoa.dylib":
        "b5929d48bec6a97ce61f6792a866daf5c3ea6badb9d58d98bc0eeaf75ed3e704",
    ".pixi/envs/default/bin/ccx":
        "b94868f6dd50533d7a8f11d271864a04bbf01f4117046d0c5b35e3cad470aac6",
}
NAMESPACE = tuple("lib/python3.13/site-packages/freecad/" + name for name in (
    "UiTools.py", "__init__.py", "deprecation.py", "freecad_doc.py", "module_io.py",
    "part.py", "partdesign.py", "project_utility.py", "sketcher.py", "utils.py",
    "utils_zip.py"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path):
    info = path.lstat()
    result = {"dev": info.st_dev, "inode": info.st_ino, "mode": info.st_mode,
              "uid": info.st_uid, "gid": info.st_gid, "size": info.st_size,
              "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns}
    if stat.S_ISLNK(info.st_mode):
        result.update(kind="link", target=os.readlink(path), resolved=str(path.resolve(strict=True)),
                      resolved_sha256=sha(path))
    else:
        assert stat.S_ISREG(info.st_mode), path
        result.update(kind="file", sha256=sha(path))
    return result


def snapshot():
    cache = (REPO / "build/release/CMakeCache.txt").read_text()
    assert "\nCMAKE_INSTALL_PREFIX:PATH=/Applications/FreeCAD-27.1.0.app/Contents/Resources\n" in cache
    paths = [REPO / relative for relative in FIXED]
    namespace = [PREFIX / relative for relative in NAMESPACE]
    for path in namespace:
        assert path.is_file() and not path.is_symlink(), path
        parent = path.parent
        while parent != PREFIX:
            assert parent.is_dir() and not parent.is_symlink(), parent
            parent = parent.parent
    assert len(namespace) == 11
    result = {str(path): record(path) for path in paths + namespace}
    for relative, required in FIXED.items():
        assert sha(REPO / relative) == required, relative
    return result


def capture():
    assert not RECEIPT.exists()
    proof = {"passed": True, "scope": "16 selected critical files before first DESTDIR; not a whole-prefix inventory", "files": snapshot()}
    with RECEIPT.open("x") as stream:
        stream.write(json.dumps(proof, indent=2) + "\n")
    return proof


def verify():
    proof = json.loads(RECEIPT.read_text())
    assert proof["passed"] and snapshot() == proof["files"], "Critical prefix/input identity changed"
    return proof


if __name__ == "__main__":
    assert len(sys.argv) == 2 and sys.argv[1] in ("capture", "verify")
    proof = capture() if sys.argv[1] == "capture" else verify()
    print(json.dumps({"passed": True, "action": sys.argv[1], "files": len(proof["files"]),
                      "receipt": str(RECEIPT), "sha256": sha(RECEIPT)}, indent=2))
