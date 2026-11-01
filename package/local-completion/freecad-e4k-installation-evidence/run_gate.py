"""Fresh e4k deployment build gates over the immutable serial supervisor."""

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
REPO = Path("/Users/zukomgwili/src/FreeCAD")
ORIGINAL = REPO / "package/local-completion/freecad-8rk-installation-evidence/run_gate.py"
assert hashlib.sha256(ORIGINAL.read_bytes()).hexdigest() == (
    "556371fd97edc9a393fed04427f670e3c4fb8ddf8c632d2ec0479152a6cdee9e"
)
spec = importlib.util.spec_from_file_location("_e4k_install_guard", ORIGINAL)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
core.ROOT = ROOT
sources = set(
    json.loads((REPO / "package/local-completion/freecad-sv7-validation.json").read_text())[
        "source_inputs"
    ]
)
for name, key in (
    ("freecad-9rc-validation.json", "final_source_sha256"),
    ("freecad-bjh-validation.json", "final_source_sha256"),
    ("freecad-e4k-validation.json", "source_files_sha256"),
):
    sources.update(json.loads((REPO / "package/local-completion" / name).read_text())[key])
core.SOURCE_FILES = tuple(sorted(sources)) + (
    str(Path(__file__).resolve()),
    str(ROOT / "request.json"),
    "package/local-completion/freecad-e4k-validation.json",
    "build/native-solvers/staged-selfweight-d4970161eb4e/ccx-force-accounting",
)
prefix = ["/opt/homebrew/bin/pixi", "run", "--frozen"]
core.COMMANDS = {
    "build": prefix + ["cmake", "--build", "build/release", "--parallel", "8"],
    "ctest": prefix
    + [
        "ctest", "--test-dir", "build/release", "--output-on-failure",
        "--parallel", "1", "--timeout", "60",
    ],
}
serial, group_exists = core.serial, core.group_exists
if __name__ == "__main__":
    raise SystemExit(core.main())
