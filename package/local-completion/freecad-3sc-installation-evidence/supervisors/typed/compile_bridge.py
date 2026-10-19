"""Fresh read-only bridge, explicitly linked and pinned to one signed app phase."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import time

from RuntimeIdentity import COMMIT, REVISION, sha

ROOT = Path(__file__).resolve().parent
REPO = Path("/Users/zukomgwili/src/FreeCAD")
parser = argparse.ArgumentParser()
parser.add_argument("phase", choices=("stage", "installed"))
parser.add_argument("application", type=Path)
args = parser.parse_args()
app = args.application.resolve(strict=True)
expected = ROOT.parent / "FreeCAD-27.1.0.app" if args.phase == "stage" else Path("/Applications/FreeCAD-27.1.0.app")
assert app == expected.resolve(strict=True), app
resources = app / "Contents/Resources"
subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
local_install = (resources / "LOCAL-INSTALL.txt").read_text()
assert COMMIT in local_install and "+205" in local_install
subprocess.run(["git", "diff", "--quiet", COMMIT, "--", "src"], cwd=REPO, check=True)
header = (REPO / "build/release/src/Build/Version.h").read_text()
values = dict(re.findall(r'^#define\s+(\w+)\s+"([^"]*)"', header, re.MULTILINE))
assert values["FCRepositoryHash"] == COMMIT and values["FCRevision"] == REVISION
work = ROOT / args.phase
work.mkdir()
source_names = ("RuntimeIdentity.py", "NativeMixedGuiWitness.py", "NativeMixedGuiGreenWitness.py",
                "NativeMixedGuiPersistenceWitness.py", "NativeMixedGuiColdRestore.py",
                "TypedMaterialReadBridge.cpp", "compile_bridge.py", "run_typed.py")
for name in source_names:
    shutil.copy2(ROOT / name, work / name)
database_path = REPO / "build/release/compile_commands.json"
database = json.loads(database_path.read_text())
entry = next(item for item in database if item["file"].endswith("/Mod/Material/App/MaterialPyImp.cpp"))
command = shlex.split(entry["command"])
filtered = []
skip = False
for part in command:
    if skip:
        skip = False
        continue
    if part in ("-o", "-MF", "-MT", "-MQ"):
        skip = True
    elif part in ("-c", "-MD", "-MMD", "-MP") or part == entry["file"]:
        continue
    else:
        filtered.append(part)
prefix = REPO / ".pixi/envs/default"
native_lib = resources / "lib"
bridge = work / "TypedMaterialReadBridge.so"
assert not bridge.exists()
filtered += [f"-I{prefix}/include/qt6/QtGui", "-bundle", "-undefined", "dynamic_lookup",
             str(work / "TypedMaterialReadBridge.cpp"), str(native_lib / "Materials.so"),
             f"-L{prefix}/lib", "-lQt6Gui", "-lQt6Core", f"-Wl,-rpath,{native_lib}",
             f"-Wl,-rpath,{prefix}/lib", "-o", str(bridge)]
start = time.monotonic()
compile_result = subprocess.run(filtered, cwd=entry["directory"], text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90)
(work / "bridge-compile.log").write_text(shlex.join(filtered) + "\n" + compile_result.stdout)
compile_result.check_returncode()
subprocess.run(["codesign", "--force", "--sign", "-", "--identifier",
                f"org.freecad.private.3sc-{args.phase}", str(bridge)], check=True)
links = subprocess.check_output(["otool", "-L", str(bridge)], text=True)
load_commands = subprocess.check_output(["otool", "-l", str(bridge)], text=True)
(work / "bridge-links.txt").write_text(links + "\n" + load_commands)
assert str(native_lib) in load_commands and "build/release/Mod/Material" not in load_commands
module_paths = {name: str((native_lib / f"{name}.so").resolve(strict=True))
                for name in ("Materials", "MatGui", "Part", "Fem")}
for name, relative in {"femtools.native_properties": "femtools/native_properties.py",
                       "femtools.force_accounting": "femtools/force_accounting.py",
                       "femmesh.quality": "femmesh/quality.py"}.items():
    path = resources / "Mod/Fem" / relative
    assert path.read_bytes() == (REPO / "src/Mod/Fem" / relative).read_bytes()
    module_paths[name] = str(path.resolve(strict=True))
protected = [ROOT / name for name in source_names] + [work / name for name in source_names]
protected += [bridge, work / "bridge-compile.log", work / "bridge-links.txt",
              resources / "LOCAL-INSTALL.txt", app / "Contents/Info.plist",
              app / "Contents/_CodeSignature/CodeResources"]
protected += [app / "Contents/MacOS" / name for name in ("FreeCAD", "FreeCADCmd")]
protected += [resources / "bin" / name for name in ("FreeCAD", "FreeCADCmd")]
protected += [Path(path) for path in module_paths.values()]
receipt = {"phase": args.phase, "application": str(app), "commit": COMMIT, "revision": REVISION,
           "bridge": str(bridge), "module_paths": module_paths,
           "protected_sha256": {str(path.resolve(strict=True)): sha(path) for path in protected},
           "compile_command": filtered, "compile_database_sha256": sha(database_path),
           "elapsed_compile_seconds": time.monotonic() - start,
           "bridge_source_sha256": sha(work / "TypedMaterialReadBridge.cpp"),
           "bridge_sha256": sha(bridge)}
(work / "runtime.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps(receipt, indent=2))
