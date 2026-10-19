"""Strict runtime/custody guards for one signed 3sc application, never a fallback."""
import sys
sys.dont_write_bytecode = True

import ctypes
import hashlib
import json
import os
from pathlib import Path

COMMIT = "f0c43f0a9368eaab7d469d825d1a3e75bff90903"
REVISION = "49261 +213 (Git)"
PROFILE_KEYS = ("FREECAD_USER_HOME", "FREECAD_USER_DATA", "FREECAD_USER_TEMP",
                "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def manifest():
    path = Path(os.environ["FREECAD_3SC_RUNTIME_MANIFEST"]).resolve(strict=True)
    result = json.loads(path.read_text())
    assert result["commit"] == COMMIT and result["revision"] == REVISION
    assert path.parent == Path(__file__).resolve().parent
    return result


def native_images():
    process = ctypes.CDLL(None)
    process._dyld_image_count.restype = ctypes.c_uint32
    process._dyld_get_image_name.argtypes = [ctypes.c_uint32]
    process._dyld_get_image_name.restype = ctypes.c_char_p
    names = [process._dyld_get_image_name(i).decode()
             for i in range(process._dyld_image_count())]
    return [{"path": str(Path(name).resolve(strict=True)), "sha256": sha(name)}
            for name in names if Path(name).name in ("Materials.so", "MatGui.so", "Part.so", "Fem.so")]


def verify_runtime(require_gui=False):
    import FreeCAD as App
    import Materials

    identity = manifest()
    version = App.Version()
    assert version[:3] == ["27", "1", "0"], version
    assert version[3] == REVISION and version[-1] == COMMIT, version
    for path, digest in identity["protected_sha256"].items():
        assert sha(path) == digest, f"Runtime/producers changed: {path}"
    expected_modules = identity["module_paths"]
    assert Path(Materials.__file__).resolve(strict=True) == Path(expected_modules["Materials"])
    for name, path in expected_modules.items():
        if name in sys.modules:
            assert Path(sys.modules[name].__file__).resolve(strict=True) == Path(path), (name, path)
    images = native_images()
    for basename, name in (("Materials.so", "Materials"), ("MatGui.so", "MatGui"),
                           ("Part.so", "Part"), ("Fem.so", "Fem")):
        actual = [entry for entry in images if Path(entry["path"]).name == basename]
        if name == "Materials" or (name == "MatGui" and require_gui) or name in sys.modules:
            assert len(actual) == 1 and actual[0]["path"] == expected_modules[name], actual
        elif actual:
            assert len(actual) == 1 and actual[0]["path"] == expected_modules[name], actual
    if require_gui:
        assert App.GuiUp, "Expected actual application GUI"
    return {"version": version, "application": identity["application"],
            "phase": identity["phase"], "module_images": images,
            "manifest_sha256": sha(os.environ["FREECAD_3SC_RUNTIME_MANIFEST"])}
