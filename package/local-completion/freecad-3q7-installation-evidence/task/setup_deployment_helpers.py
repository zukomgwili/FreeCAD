"""Root-only new-file 3q7 adaptation of exact retained deployment helpers.

This setup reads Python/JSON/source text only. It does not import deployment or
product helpers or execute a process, build, native test, probe or installation.
The immutable installer core, full-tree staging/signing/rollback machinery and
independent payload auditor remain unchanged. Every destination must be new.
"""

import ast
import hashlib
import json
from pathlib import Path

ROOT = Path("/private/tmp/freecad-3q7-install-W35DLJ")
REPO = Path("/Users/zukomgwili/src/FreeCAD")
OLD = REPO / "package/local-completion/freecad-yzk-installation-evidence/private"
COMMIT = "6a0ed157b1063fa21407dc8f3cdfa3aef9484d8d"
REVISION = "49261 +229 (Git)"
NATIVE = "6c02452a896727af6cb4578fd3fb6bbfbdd48e3fb887c1c04fa2d8b171976c66"
BACKUP = "/Users/zukomgwili/Applications/FreeCAD Backups/FreeCAD-27.1.0-before-3q7-7667033a14.app"
PINS = {
    "stage_install.py": "e3722c04a0231a1be99532dbb89cd937c628564879c2190440d3c5c384ab2f8c",
    "AppYzkIdentity.py": "e4a6b5f645b570b6afde88c09ec5fc63e2362e1ea3556fcc2e1d0fc652b78c1a",
    "critical_pins.py": "15b675d33addb03f4f3a54a9e44f78fe63f7ff21065185cf957fa682ef82f0e9",
    "run_app.py": "d7bb1dc4004bc472961e3fcfefcbbb6b9c14e738382d8f3d2b19b274d50a3b36",
    "run_step.py": "96c2f4806cab1d1930280a34001fcafbaca9546eeb8f1a9fff23540116250f6c",
    "audit_payload_stage.py": "d2dd63a5dd9d9868816777e3af75fa06798f93910c56cf25b7a2ad51117ddaf3",
    "YzkPortableColdRestore.py": "164691a5afeedbee55f47841ed9a064c9addbb37e89d143f36de4d5d927b4c51",
}


def change(body, before, after):
    assert body.count(before) == 1, before
    return body.replace(before, after)


def native_ids(relative, class_name, expected_count):
    path = REPO / "src/Mod/Fem" / relative
    tree = ast.parse(path.read_bytes(), filename=str(path))
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name]
    assert len(classes) == 1
    methods = sorted(node.name for node in classes[0].body
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"))
    assert len(methods) == len(set(methods)) == expected_count
    module = relative.removesuffix(".py").replace("/", ".")
    return [module + "." + class_name + "." + method for method in methods]


def main():
    assert ROOT.is_dir() and not ROOT.is_symlink()
    old = {}
    for name, wanted in PINS.items():
        path = OLD / name
        assert path.is_file() and not path.is_symlink()
        old[name] = path.read_bytes()
        assert hashlib.sha256(old[name]).hexdigest() == wanted
    bodies = {name: data.decode() for name, data in old.items()}
    tie_ids = native_ids("femtest/app/test_tie_accounting_native.py", "TestTieAccountingNative", 4)
    moving_ids = native_ids("femtest/app/test_moving_port_accounting_native.py", "TestMovingPortAccountingNative", 8)
    assert len(set(tie_ids + moving_ids)) == 12
    config = (f"COMMIT = {COMMIT!r}\nREVISION = {REVISION!r}\nNATIVE_SHA = {NATIVE!r}\n"
              "NATIVE_SCHEMA = 'CCX_FORCE_ACCOUNTING_V3'\n"
              f"NATIVE_TIE_IDS = {tuple(tie_ids)!r}\nNATIVE_MOVING_IDS = {tuple(moving_ids)!r}\n")
    bodies["harness_config.py"] = config

    body = bodies["stage_install.py"]
    body = change(body, "Explicit yzk configuration", "Explicit 3q7 configuration")
    body = change(body, "from harness_config import COMMIT, REVISION, NATIVE_SHA",
                  "from harness_config import COMMIT, REVISION, NATIVE_SHA, NATIVE_TIE_IDS, NATIVE_MOVING_IDS")
    body = change(body, "core.BACKUP = Path('/Users/zukomgwili/Applications/FreeCAD Backups/FreeCAD-27.1.0-before-yzk-6cdc1affda.app')",
                  f"core.BACKUP = Path({BACKUP!r})")
    body = change(body, "    'femtools/elastic_connector.py', 'femsolver/calculix/writer.py',",
                  "    'femtools/elastic_connector.py', 'femsolver/calculix/writer.py',\n"
                  "    'femtools/rigid_body.py', 'femtest/app/support_utils.py',\n"
                  "    'femtest/app/test_rigid_region_ownership.py',")
    body = change(body, "    suite = identity['selected_suite']",
                  "    need(identity['TestFemApp_count'] == 418\n"
                  "         and len(identity['registered_native_ids']) == 12\n"
                  "         and set(identity['registered_native_ids']) == set(NATIVE_TIE_IDS + NATIVE_MOVING_IDS),\n"
                  "         'Actual registered native catalogue differs: ' + label)\n"
                  "    suite = identity['selected_suite']")
    body = change(body, "('fem', 'TestFemApp', 406)", "('fem', 'TestFemApp', 419)")
    body = change(body, "('native', 'femtest.app.test_moving_port_accounting_native', 6)",
                  "('native', 'femtest.app.test_moving_port_accounting_native', 9)")
    body = change(body, "Historical ywu gate catalogue is not valid for yzk", "Historical ywu gate catalogue is not valid for 3q7")
    bodies["stage_install.py"] = body

    body = bodies["AppYzkIdentity.py"]
    body = change(body, "literal-app yzk identity", "literal-app 3q7 identity")
    body = change(body, "from harness_config import NATIVE_SHA as PINNED_SOLVER",
                  "from harness_config import NATIVE_SHA as PINNED_SOLVER\n"
                  "from harness_config import NATIVE_TIE_IDS, NATIVE_MOVING_IDS")
    body = change(body, '    "femtools.elastic_connector": "femtools/elastic_connector.py",',
                  '    "femtools.elastic_connector": "femtools/elastic_connector.py",\n'
                  '    "femtools.rigid_body": "femtools/rigid_body.py",\n'
                  '    "femtest.app.support_utils": "femtest/app/support_utils.py",\n'
                  '    "femtest.app.test_rigid_region_ownership": "femtest/app/test_rigid_region_ownership.py",')
    body = change(body, "self.assertEqual(app_suite.countTestCases(), 405)", "self.assertEqual(app_suite.countTestCases(), 418)")
    body = change(body, "            self.assertEqual(len(expected), 4)",
                  "            self.assertEqual(len(expected), 4)\n            self.assertCountEqual(expected, NATIVE_TIE_IDS)")
    body = change(body, "            self.assertEqual(len(moving_expected), 5)",
                  "            self.assertEqual(len(moving_expected), 8)\n            self.assertCountEqual(moving_expected, NATIVE_MOVING_IDS)")
    bodies["AppYzkIdentity.py"] = body

    body = bodies["critical_pins.py"]
    body = change(body, "'6cdc1affda07ac4e3b45a98097b7ae11039c80c6' in note",
                  "'7667033a14654a9b229bf59b94cb3012ce989170' in note")
    body = change(body, "'49261+221' in note", "'49261+224' in note")
    bodies["critical_pins.py"] = body
    bodies["run_app.py"] = change(bodies["run_app.py"], "default=406", "default=419")

    note = (f"FreeCAD Local Release built from {COMMIT}.\n"
            "21 October 2026, version 27.1.0dev49261+229 (Git).\n\n"
            "Includes FreeCAD-3q7: operation-local exact ownership reuse across stock\n"
            "CalculiX export, retaining native edit/remesh/reference guards and no\n"
            "cross-operation cache. Earlier native V3 accounting and fixes are retained.\n"
            "The accepted matched profiling pair is separate historical source evidence;\n"
            "no universal pipeline timing, memory or engineering guarantee is made.\n\n"
            "The bundled native solver/source/contract/license are in data/NativeSolvers.\n"
            "This host-local app requires the existing repository dependency environment:\n"
            "/Users/zukomgwili/src/FreeCAD/.pixi/envs/default\n"
            "It is not self-contained or notarized. Existing launchers, patched Qt,\n"
            "dependency links and canonical Ext/freecad namespace are retained.\n"
            "Preferences and material libraries are not migrated.\n\n"
            "Rollback: quit FreeCAD, move this app aside and restore the exact prior app:\n"
            f"{BACKUP}\nOlder rollback backups are not replaced or modified.\n\n"
            "Software qualification is not engineering, Oomakhi, R49/R51, building or BIM\n"
            "acceptance. Engineering projects are not opened, altered, remeshed or solved.\n"
            "Original physical geometry, loads, equilibrium and acceptance limits remain.\n"
            "Saved cold accounting remains historical/Stale until fresh normal execution;\n"
            "saved paths, statuses, hashes and provenance are never repaired.\n")
    bodies["LOCAL-INSTALL.txt"] = note
    for name, body in bodies.items():
        path = ROOT / name
        assert not path.exists() and not path.is_symlink(), path
        if name.endswith(".py"):
            ast.parse(body, filename=str(path))
    for name, body in bodies.items():
        with (ROOT / name).open("x") as stream:
            stream.write(body)
    for name, body in bodies.items():
        assert (ROOT / name).read_text() == body
    for name, original in old.items():
        assert (OLD / name).read_bytes() == original
    print(json.dumps({"passed": True, "files": {name: hashlib.sha256(body.encode()).hexdigest()
          for name, body in bodies.items()}, "native_execution_performed": False,
          "expected_COMMIT": COMMIT, "expected_REVISION": REVISION,
          "tie_ids": tie_ids, "moving_ids": moving_ids}, indent=2))


if __name__ == "__main__":
    main()
