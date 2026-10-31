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
    "stage": "48125c1a1bcf93fb1bd17fff21c39ae2c2657116dd4dc9beb828fbafb2354c73",
    "final": "ca3fc1cebdb24c9f97b995507929e96de0c86549044e3945dcf000dd91ff2450",
}
assert hashlib.sha256((HELPERS / name).read_bytes()).hexdigest() == expected[sys.argv[1]]
if sys.argv[1] == "stage":
    assert len(sys.argv) == 2
    sys.argv = [str(HELPERS / name)]
else:
    assert len(sys.argv) == 3 and re.fullmatch(r"[0-9a-f]{64}", sys.argv[2])
    sys.argv = [str(HELPERS / name), sys.argv[2]]
runpy.run_path(str(HELPERS / name), run_name="__main__")
