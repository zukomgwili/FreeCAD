"""Stage the qualified native binary only inside the ignored local build tree."""
import json
from pathlib import Path
import shutil
from run_gate import protected, serial, sha

serial()
source = Path('/private/tmp/freecad-9ii-T61k55sb/native-build-r03/native/CalculiX/ccx_2.23/src/ccx_2.23_conda')
expected = '0c2a86318df9c7cc9d921e5068ae52f1d53e27b7b16747e00a74ccc8fe37c6cc'
target = Path('/Users/zukomgwili/src/FreeCAD/build/native-solvers/contact-state-0c2a86318df9/ccx-force-accounting')
before = protected()
assert sha(source) == expected
assert not target.exists() and not target.is_symlink()
target.parent.mkdir(parents=True, exist_ok=False)
shutil.copy2(source, target)
assert sha(target) == expected
after = protected()
assert before == after
serial()
report = {'source': str(source), 'target': str(target), 'sha256': expected,
          'protected_before': before, 'protected_after': after, 'installed': False}
Path(__file__).with_suffix('.receipt.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
