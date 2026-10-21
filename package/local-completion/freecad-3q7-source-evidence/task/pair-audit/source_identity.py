"""Read-only git-blob/AST proof binding approved12 files and one diagnostic delta."""

import ast
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path("/Users/zukomgwili/src/FreeCAD")
TASK = Path("/private/tmp/freecad-3q7-Pq3Byy")
APPROVED = TASK / "proposals/private-candidate-files-r02.json"
MEASURED = "9c3e7ec2637d6d3149dc55d0906576225a4d8bf7"
FINAL = "6605b582911c320418951abaa415fa947237c4c8"


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def prove():
    approved_bytes = APPROVED.read_bytes()
    approved = json.loads(approved_bytes)
    files = []
    for row in approved["files"]:
        path = "src/Mod/Fem/" + row["relative"]
        private = Path(row["private_path"]).read_bytes()
        measured, final = git("show", MEASURED + ":" + path), git("show", FINAL + ":" + path)
        assert sha(private) == row["sha256"] and len(private) == row["bytes"]
        assert private == measured
        files.append({"path": path, "approved_and_measured_sha256": sha(measured),
                      "final_sha256": sha(final), "final_bytes": len(final),
                      "byte_identical_to_approved_measured": measured == final})
    changed = git("diff", "--name-only", MEASURED, FINAL).decode().splitlines()
    assert changed == ["src/Mod/Fem/femmesh/ownership_context.py"]
    path = changed[0]
    old = ast.parse(git("show", MEASURED + ":" + path))
    new = ast.parse(git("show", FINAL + ":" + path))
    changes = [(one, two) for one, two in zip(ast.walk(old), ast.walk(new))
               if isinstance(one, ast.Constant) and isinstance(two, ast.Constant)
               and one.value != two.value]
    assert len(changes) == 1
    one, two = changes[0]
    before, after = one.value, two.value
    assert before == "Changed mesh geometry; regenerate the mesh."
    assert after == "References select changed mesh geometry; regenerate the mesh."
    raises = [node for node in ast.walk(new) if isinstance(node, ast.Raise)
              and isinstance(node.exc, ast.Call) and isinstance(node.exc.func, ast.Name)
              and node.exc.func.id == "ValueError" and node.exc.args == [two]]
    assert len(raises) == 1
    two.value = before
    assert ast.dump(old) == ast.dump(new)
    assert APPROVED.read_bytes() == approved_bytes
    assert git("diff", "--name-only", approved["source_base_HEAD"], FINAL).decode().splitlines() == sorted(row["path"] for row in files)
    return {"schema": "FreeCAD-3q7-final-source-approved-bytes-diagnostic-delta-proof-v1", "passed": True,
            "approved_manifest": {"path": str(APPROVED), "sha256": sha(approved_bytes)},
            "measured_product_commit": MEASURED, "final_product_commit": FINAL,
            "files": files, "all12_measured_files_byte_equal_the_reviewed_private_manifest": True,
            "final_diagnostic_delta": {"file": path, "old": before, "new": after,
                                       "only_one_ValueError_Raise_Constant_changed": True,
                                       "all_other_AST_identical": True},
            "timing_attribution": "Accepted pair ran common compiled +226/5b with measured9c3 Python bytes. The later6605 exception literal is not reprofiled. Its Raise branch did not execute in either successful whole-call candidate run; construction and export returned normally. No changed successful-path statement, validation, allocation or guard.",
            "native_or_product_execution": False, "current_build_or_core_read": False,
            "authorship": "Author reviewed product and authored some independent mutation tests; no authorship of the product implementation or diagnostic fix."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = prove()
    payload = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.report is not None:
        assert args.report.is_absolute() and args.report.parent.resolve().is_relative_to(TASK)
        with args.report.open("x") as handle:
            handle.write(payload)
        print(json.dumps({"passed": True, "report": str(args.report), "sha256": sha(payload.encode())}))
    else:
        print(payload, end="")
