"""Root-only serial literal-application gates, with no product source overlay."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from xml.etree import ElementTree
import zipfile

sys.dont_write_bytecode = True

import critical_pins
import run_gate
import stage_install as install

ROOT = Path(__file__).resolve().parent
COUNTS = {"cmd": 132, "gui": 14, "cold": 2}


def sha(path):
    return install.digest(Path(path))


def inputs(extra):
    paths = {*ROOT.glob("*.py"), *extra}
    return {str(path): sha(path) for path in sorted(paths)}


def profiles():
    critical_pins.verify()
    return {str(path): install.canonical_sha(install.inventory(path)) for path in install.PROFILES}


def cold_case(document, application, location):
    document = document.resolve(strict=True)
    assert document.is_relative_to(ROOT) and document.is_file() and not document.is_symlink()
    origin = ROOT / document.relative_to(ROOT).parts[0]
    execution = origin / "execution.json"
    proof = json.loads(execution.read_text())
    assert proof["passed"] is True and proof["mode"] == "cmd" and proof["location"] == location
    assert proof["schema"] == "FreeCAD-9ii-literal-application-gate-v1"
    assert proof["application"] == str(application) and proof["source_commit"] == install.COMMIT
    assert proof["native_sha256"] == install.NATIVE_SHA
    assert {"path": str(document), "sha256": sha(document)} in proof["cold_witness_documents"]
    with zipfile.ZipFile(document) as archive:
        tree = ElementTree.fromstring(archive.read("Document.xml"))
    saved = tree.find('./ObjectData/Object[@name="NativeContactOutput"]')
    assert saved is not None
    literal = saved.find('./Properties/Property[@name="ContactData"]/String').get("value")
    digest = saved.find('./Properties/Property[@name="ContactHash"]/String').get("value")
    assert hashlib.sha256(literal.encode()).hexdigest() == digest
    data = json.loads(literal)
    source = data["provenance"]
    candidate = application / "Contents/Resources/data/NativeSolvers/ccx-force-accounting"
    assert source["binary"] == str(candidate) and sha(candidate) == install.NATIVE_SHA
    assert source["binary_sha256"] == install.NATIVE_SHA and data["complete"] is True
    files = {document, candidate, execution, origin / "regression.json", origin / "manifest.json",
             Path(source["run"]["path"])}
    files.update(Path(source[key]) for key in ("deck", "request_path", "output"))
    assert sha(source["output"]) == source["output_sha256"]
    assert sha(source["deck"]) == source["deck_sha256"]
    assert sha(source["request_path"]) == source["request_sha256"]
    assert sha(source["run"]["path"]) == source["run"]["sha256"]
    for path in files:
        assert path.resolve(strict=True) == path and path.is_file() and not path.is_symlink()
        assert path == candidate or path.is_relative_to(ROOT), path
    return {"document": str(document), "result_name": "NativeContactOutput",
            "contact_data_literal": literal, "contact_hash_literal": digest,
            "contacts": [item["contact"] for item in source["contacts"]],
            "source_files": [{"path": str(path), "sha256": sha(path)} for path in sorted(files)]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("location", choices=("stage", "installed"))
    parser.add_argument("mode", choices=tuple(COUNTS))
    parser.add_argument("label")
    parser.add_argument("--cold-source", type=Path)
    args = parser.parse_args()
    assert __debug__ and re.fullmatch(r"[a-z0-9-]+", args.label)
    assert (args.mode == "cold") == (args.cold_source is not None)
    run_gate.serial()
    install.compiled_identity()
    application = install.STAGE if args.location == "stage" else install.APP
    assert application.resolve(strict=True) == application and not application.is_symlink()
    sealed_path = ROOT / "stage-inventory.json"
    sealed = json.loads(sealed_path.read_text())
    assert install.inventory(application) == sealed
    install.verify(application)
    original_app = install.canonical_sha(install.inventory(install.APP))
    before_profiles = profiles()
    run = ROOT / args.label
    run.mkdir()
    temporary = run / "dotted.parent"
    temporary.mkdir()
    resources = application / "Contents/Resources"
    native_names = ["bin/FreeCADCmd", "bin/FreeCAD", "lib/FreeCAD.so", "lib/FreeCADGui.so",
                    "lib/libFreeCADBase.dylib", "lib/libFreeCADApp.dylib",
                    "lib/libFreeCADGui.dylib", "lib/Fem.so", "lib/FemGui.so", "lib/Part.so",
                    "lib/Materials.so", "data/NativeSolvers/ccx-force-accounting"]
    native = {str(resources / name): sha(resources / name) for name in native_names}
    source = {target: sha(install.REPO / name) for name, target in install.SOURCES.items()}
    manifest = {
        "schema": "FreeCAD-9ii-literal-application-manifest-v1",
        "application": str(application), "location": args.location, "mode": args.mode,
        "commit": install.COMMIT, "revision": install.REVISION, "native_sha256": install.NATIVE_SHA,
        "gui": args.mode == "gui", "expected_tests": COUNTS[args.mode],
        "expected_native_files": native, "expected_source_files": source,
        "report_path": str(run / "regression.json"), "witness_path": str(run / "witness"),
        "working_directory": str(run), "cold_case": None,
    }
    if args.cold_source is not None:
        manifest["cold_case"] = cold_case(args.cold_source, application, args.location)
    manifest_path = run / "manifest.json"
    install.write_json(manifest_path, manifest)
    environment = dict(os.environ)
    for key in tuple(environment):
        if key.startswith(("FREECAD_", "CCX_", "DYLD_", "LD_", "APPQA_", "F8_", "F9II_")) or key in (
            "PYTHONPATH", "PYTHONHOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
            "TMPDIR", "TMP", "TEMP", "DESTDIR"):
            environment.pop(key)
    for key in ("FREECAD_USER_HOME", "FREECAD_USER_DATA", "FREECAD_USER_TEMP",
                "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        path = run / key.lower()
        path.mkdir()
        environment[key] = str(path)
    environment.update(TMPDIR=str(temporary) + "/", TMP=str(temporary), TEMP=str(temporary),
                       FREECAD_USER_TEMP=str(temporary), PYTHONDONTWRITEBYTECODE="1",
                       PYTHONNOUSERSITE="1", OMP_NUM_THREADS="2",
                       F9II_INSTALL_MANIFEST=str(manifest_path))
    executable = "FreeCAD" if args.mode == "gui" else "FreeCADCmd"
    command = [str(application / "Contents/MacOS" / executable), "-u", str(run / "user.cfg"),
               "-s", str(run / "system.cfg"), "-P", str(ROOT), "-t", "App9iiIdentity"]
    extra = [manifest_path, sealed_path, *map(Path, native)]
    extra += [install.REPO / name for name in install.SOURCES]
    if manifest["cold_case"]:
        extra += [Path(row["path"]) for row in manifest["cold_case"]["source_files"]]
    before = inputs(extra)
    started, timed_out = time.monotonic(), False
    child = None
    report = {"schema": "FreeCAD-9ii-literal-application-gate-v1", "passed": False,
              "application": str(application), "location": args.location, "mode": args.mode,
              "source_commit": install.COMMIT, "revision": install.REVISION,
              "native_sha256": install.NATIVE_SHA, "expected_tests": COUNTS[args.mode],
              "command": command, "working_directory": str(run), "inputs_before": before,
              "source_or_build_import_override": False, "native_solver_override": False}
    try:
        with (run / "run.log").open("xb") as output:
            child = subprocess.Popen(command, cwd=run, env=environment, stdin=subprocess.DEVNULL,
                                     stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                child.wait(timeout=900)
            except subprocess.TimeoutExpired:
                timed_out = True
            finally:
                for number in (signal.SIGTERM, signal.SIGKILL):
                    if child.poll() is None or run_gate.group_exists(child.pid):
                        try:
                            os.killpg(child.pid, number)
                        except ProcessLookupError:
                            pass
                        try:
                            child.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            pass
        text = (run / "run.log").read_text(errors="replace")
        counts = re.findall(r"^Ran (\d+) tests? in [0-9.]+s$", text, re.M)
        valid = (counts == [str(COUNTS[args.mode])]
                 and len(re.findall(r"^OK$", text, re.M)) == 1
                 and not re.search(r"^(?:FAILED|FAIL:|ERROR:|UNEXPECTED SUCCESS)|\.\.\. skipped", text, re.M))
        receipt_path = run / "regression.json"
        regression = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
        valid = bool(valid and regression.get("passed") is True
                     and regression.get("commit") == install.COMMIT
                     and regression.get("application") == str(application)
                     and regression.get("mode") == args.mode
                     and regression.get("test_count") == COUNTS[args.mode]
                     and regression.get("native_sha256") == install.NATIVE_SHA)
        after = inputs(extra)
        current = install.inventory(application)
        install.verify(application)
        install.compiled_identity()
        run_gate.serial()
        report.update(
            returncode=child.returncode, timed_out=timed_out,
            child_reaped=child.poll() is not None, process_group_gone=not run_gate.group_exists(child.pid),
            executed_tests=int(counts[0]) if len(counts) == 1 else 0,
            inputs_after=after, inputs_unchanged=before == after,
            application_unchanged=current == sealed,
            application_inventory_sha256=install.canonical_sha(current),
            profiles_and_dependencies_unchanged=before_profiles == profiles(),
            original_app_unchanged=original_app == install.canonical_sha(install.inventory(install.APP)),
            strict_signature_verified=True, log_sha256=sha(run / "run.log"),
            regression_sha256=sha(receipt_path) if receipt_path.exists() else None,
            semantic_tests_passed=valid,
        )
        if args.mode == "cmd":
            witnesses = sorted(temporary.glob("freecad-contact-state-native-*/native-contact-state.FCStd"))
            report["cold_witness_documents"] = [{"path": str(path), "sha256": sha(path)} for path in witnesses]
            valid = valid and len(witnesses) == 1
        report["passed"] = bool(child.returncode == 0 and not timed_out and valid
            and report["child_reaped"] and report["process_group_gone"] and report["inputs_unchanged"]
            and report["application_unchanged"] and report["profiles_and_dependencies_unchanged"]
            and report["original_app_unchanged"] and report["strict_signature_verified"])
    except BaseException as error:
        report["supervisor_error"] = repr(error)
        raise
    finally:
        report["elapsed_seconds"] = time.monotonic() - started
        install.write_json(run / "execution.json", report)
        print(json.dumps({key: value for key, value in report.items()
                          if key not in ("inputs_before", "inputs_after")}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
