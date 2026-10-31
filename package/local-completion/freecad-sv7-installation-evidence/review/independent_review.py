"""Root-invoked standard-library-only independent deployment review."""

import hashlib
from pathlib import Path
import re
import runpy
import sys

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "review"
assert sys.argv[1:2] in (["stage"], ["final"])
name = "independent_" + ("stage" if sys.argv[1] == "stage" else "final") + "_review.py"
expected = {
    "stage": "9ad628f2a1c10091ba949ba5530a2907f9057da259bcb9ff146163de33101f59",
    "final": "9b95cbb55003505075532bc158ed0ac122575b49c086f163c3a15941a01d69f9",
}
assert hashlib.sha256((HELPERS / name).read_bytes()).hexdigest() == expected[sys.argv[1]]
if sys.argv[1] == "stage":
    assert len(sys.argv) == 2
    sys.argv = [str(HELPERS / name)]
else:
    assert len(sys.argv) == 3 and re.fullmatch(r"[0-9a-f]{64}", sys.argv[2])
    sys.argv = [str(HELPERS / name), sys.argv[2]]
runpy.run_path(str(HELPERS / name), run_name="__main__")
