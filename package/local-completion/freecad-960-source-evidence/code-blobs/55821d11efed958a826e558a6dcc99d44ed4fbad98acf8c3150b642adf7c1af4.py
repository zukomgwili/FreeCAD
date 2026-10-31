"""Retain the exact qualified signed solver at a stable build-cache path."""
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
config = json.loads((ROOT/'native-candidate.json').read_text())
source = Path(config['path'])
assert hashlib.sha256(source.read_bytes()).hexdigest() == config['sha256']
target = REPO/'build/native-solvers'/('beam-section-'+config['sha256'][:12])/'ccx-force-accounting'
target.parent.mkdir(parents=True,exist_ok=True)
if target.exists():
    assert hashlib.sha256(target.read_bytes()).hexdigest() == config['sha256']
else:
    shutil.copy2(source,target)
assert target.is_file() and not target.is_symlink()
assert hashlib.sha256(target.read_bytes()).hexdigest() == config['sha256']
receipt = {'schema':'FreeCAD-960-stable-build-solver-v1','source':str(source),
           'target':str(target),'sha256':config['sha256'],'application_installation':False}
(Path(__import__('os').environ['B960_WITNESS_ROOT'])/'stable-solver.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt),flush=True)
