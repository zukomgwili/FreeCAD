"""Root-invoked standard-library-only independent deployment review."""

import hashlib
from pathlib import Path
import re
import runpy
import sys

ROOT = Path(__file__).resolve().parent
assert sys.argv[1:2] in (["stage"], ["final"])
name = "independent_" + ("stage" if sys.argv[1] == "stage" else "final") + "_review.py"
expected = {
    "stage": "5e98a43f1bfeb73fa06296e2cd22b12818aaa07db89a91b649465d969f4abc43",
    "final": "7493af890707a4254d7a6b31ffdbfa18102d5fdeb279eb48042768e5f81dbfae",
}
assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected[sys.argv[1]]
if sys.argv[1] == "stage":
    assert len(sys.argv) == 2
    sys.argv = [str(ROOT / name)]
else:
    assert len(sys.argv) == 3 and re.fullmatch(r"[0-9a-f]{64}", sys.argv[2])
    sys.argv = [str(ROOT / name), sys.argv[2]]
runpy.run_path(str(ROOT / name), run_name="__main__")
