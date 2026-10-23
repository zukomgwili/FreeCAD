"""Run source BIM tests with explicit module-origin qualification."""
import sys

sys.dont_write_bytecode = True

import importlib
import json
import os
from pathlib import Path

from H88OriginalCheckpoint import module_origins, sha


def load_tests(loader, _tests, _pattern):
    origins = module_origins()
    name = ("TestArch" if os.environ["H88_SUITE"] == "all"
            else "bimtests.TestArchShapeCleanup")
    module = importlib.import_module(name)
    relative = "TestArch.py" if name == "TestArch" else "bimtests/TestArchShapeCleanup.py"
    path = Path(module.__file__).resolve()
    assert path == (Path(os.environ["H88_MODULE_ROOT"]) / relative).resolve()
    assert sha(path) == sha(Path(os.environ["H88_CODE_ROOT"]) / relative)
    print("[H88-SUITE-ORIGINS]", json.dumps(origins, sort_keys=True), flush=True)
    return loader.loadTestsFromModule(module)
