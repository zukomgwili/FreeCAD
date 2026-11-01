"""Collect e4k source evidence without changing historical execution receipts.

Root executes this only after its serial native gates finish. No native command
or product code is executed here. Existing targets are always refused.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
REPO = Path("/Users/zukomgwili/src/FreeCAD")
DEFAULT_TARGET = REPO / "package/local-completion/freecad-e4k-source-evidence"
MAX_POSITIVE_CONTACT_BYTES = 256 * 1024 * 1024
SOURCE_NAMES = (
    "src/Mod/Fem/femobjects/solver_calculix.py",
    "src/Mod/Fem/femsolver/calculix/write_step_equation.py",
    "src/Mod/Fem/femsolver/calculix/write_amplitude.py",
    "src/Mod/Fem/femsolver/calculix/write_constraint_selfweight.py",
    "src/Mod/Fem/femtools/contact_state.py",
    "src/Mod/Fem/femtools/force_accounting.py",
    "src/Mod/Fem/femtest/app/test_static_step_amplitude.py",
    "src/Mod/Fem/femtest/app/test_staged_selfweight_native.py",
    "src/Mod/Fem/femtest/app/test_contact_state_catalogue.py",
    "src/Mod/Fem/TestFemApp.py",
    "src/Mod/Fem/CMakeLists.txt",
    "package/calculix/force-accounting/forceaccounting.c",
    "package/calculix/force-accounting/contactstate.c",
    "package/calculix/force-accounting/hooks.patch",
    "package/calculix/force-accounting/contract.json",
    "package/calculix/force-accounting/beamsection.c",
    "package/calculix/force-accounting/beamsection.patch",
    "package/local-completion/freecad-e4k-oracles.md",
    "package/local-completion/freecad-e4k-usage.md",
)
CONTEXT_NAMES = {
    "amplitudes.f",
    "boundarys.f",
    "calinput.f",
    "steps.f",
    "tempload.f",
    "ccx_2.23.c",
    "ccx_2.23step.c",
    "spc_guard_test.c",
}
SKIP_DIRS = {
    ".pixi",
    "__pycache__",
    ".cache",
    "ccache",
    "freecad_user_home",
    "freecad_user_data",
    "xdg_config_home",
    "xdg_data_home",
    "xdg_cache_home",
}
BINARY_NAMES = {"spc_guard_test", "ccx-force-accounting", "FreeCAD", "FreeCADCmd"}
BINARY_SUFFIXES = {".pyc", ".o", ".a", ".so", ".dylib", ".dll", ".exe"}
KNOWN_CLASSIFICATIONS = {
    "baseline": "INSTALLED_FEATURE_ABSENCE_REPRODUCER_EXPECTED_RED",
    "controls-red": "NONQUALIFYING_WRAPPER_ERROR_NO_TESTS_RAN",
    "controls-red-r02": "ACTUAL_RED_MISSING_CONTROL_AND_INVALID_AMPLITUDE_ADMISSION",
    "native-r01": "FAILED_NATIVE_GENERATED_STEP_ZERO_SPC_ADMISSION",
    "native-r02": "FAILED_NATIVE_SHARED_CONTACT_CATALOGUE_AND_SUPERSEDED_CHECKS",
    "native-r03": "FAILED_NATIVE_ENDPOINT_COMPLETION_REPRESENTATION",
    "build-r03": "NONQUALIFYING_SOURCE_GATE_INPUT_CHANGED",
}


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def json_read(path):
    return json.loads(Path(path).read_text())


def profile_map_name(path):
    name = path.name.lower()
    return "profil" in name and any(word in name for word in ("inventor", "input-map", "input_map"))


def private_files():
    """Prune environments/profiles/build trees before looking at file bodies."""
    files, excluded_directories = [], []
    for folder, directories, names in os.walk(ROOT, followlinks=False):
        base = Path(folder)
        relative = base.relative_to(ROOT)
        retained = []
        for name in sorted(directories):
            path = base / name
            reason = None
            if path.is_symlink():
                reason = "Symlink directory; never followed"
            elif name in SKIP_DIRS:
                reason = "Environment, cache or private profile directory; no body or input map collected"
            elif path == ROOT / "code-blobs":
                reason = (
                    "Opaque archives are resolved only by explicitly named source/helper input pins"
                )
            elif (
                len(relative.parts) == 2
                and relative.parts[0].startswith("native-build-")
                and relative.parts[1] == "build"
                and name != "functional-tests"
            ):
                reason = "Native build/environment/binary/source tree; receipts and logs collected separately"
            if reason:
                excluded_directories.append({"path": str(path), "reason": reason})
            else:
                retained.append(name)
        directories[:] = retained
        for name in sorted(names):
            path = base / name
            if path.is_symlink():
                excluded_directories.append(
                    {"path": str(path), "reason": "Symlink file; never dereferenced or copied"}
                )
                continue
            if path.is_file():
                # Do not scan opaque code blobs or build toolchain bodies.
                if relative.parts and relative.parts[0] == "code-blobs":
                    continue
                files.append(path)
    return files, excluded_directories


def gates(files):
    records = {}
    for path in files:
        relative = path.relative_to(ROOT)
        if path.name != "execution.json" or len(relative.parts) != 2:
            continue
        label = relative.parts[0]
        data = json_read(path)
        log = path.parent / "run.log"
        text = log.read_text(errors="replace") if log.is_file() else ""
        counts = re.findall(r"^Ran (\d+) tests? in [^\n]+$", text, re.M)
        if data.get("log_sha256") and log.is_file():
            if data["log_sha256"] != sha(log):
                raise ValueError("Historical gate log no longer matches its receipt: " + label)
        if "passed" in data:
            positive = data["passed"] is True
        else:
            # Early immutable receipts predate the semantic_passed field.
            # This selection rule never rewrites or promotes those receipts.
            positive = (
                data.get("returncode") == 0
                and data.get("timed_out") is False
                and data.get("child_reaped") is True
                and data.get("helper_inputs_unchanged") is True
                and len(counts) == 1
                and int(counts[0]) > 0
                and re.search(r"^OK$", text, re.M) is not None
                and not re.search(r"^(FAILED|FAIL:|ERROR:)|\.\.\. skipped", text, re.M)
            )
        if label in KNOWN_CLASSIFICATIONS:
            positive = False
        if data.get("passed") is True and data.get("returncode") != 0:
            raise ValueError("Inconsistent recorded gate verdict: " + label)
        records[label] = {
            "receipt": str(path),
            "receipt_sha256": sha(path),
            "receipt_mtime_ns": path.stat().st_mtime_ns,
            "command_module": (
                data["command"][data["command"].index("-t") + 1]
                if "-t" in data.get("command", [])
                else None
            ),
            "recorded_returncode": data.get("returncode"),
            "recorded_passed": data.get("passed"),
            "recorded_semantic_passed": data.get("semantic_passed"),
            "recorded_source_inputs_unchanged": data.get("source_and_supervisor_unchanged"),
            "recorded_helper_inputs_unchanged": data.get("helper_inputs_unchanged"),
            "observed_unittest_summary_counts": counts,
            "collection_positive_gate_selection": positive,
            "classification": KNOWN_CLASSIFICATIONS.get(label, "ORIGINAL_RECEIPT_RETAINED"),
        }
    return records


def gate_label(path):
    relative = path.relative_to(ROOT)
    return relative.parts[0] if len(relative.parts) > 1 else None


def named_input(path):
    """Bodies may come from named source/helpers, never arbitrary receipt paths."""
    try:
        relative = path.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in relative.parts) or profile_map_name(path):
            return False
        return path.suffix in {".py", ".c", ".f", ".json", ".md"} and (
            len(relative.parts) == 1
            or relative.parts[0] in {"review-history", "oracle-history", "gui-helper-history"}
        )
    except ValueError:
        pass
    try:
        relative = path.relative_to(REPO).as_posix()
    except ValueError:
        return False
    if relative in SOURCE_NAMES:
        return True
    if relative.startswith("src/Mod/Fem/"):
        return path.suffix in {".py", ".c", ".h", ".cpp", ".ui"}
    return relative in {
        "package/local-completion/calculix-9zt-probe/build_probe.py",
        "package/local-completion/freecad-8rk-installation-evidence/run_gate.py",
        "package/local-completion/freecad-ywu-installation-evidence/private/stage_install.py",
    }


def saved_summary(path):
    raw = path.read_bytes()
    data = json.loads(raw)
    summary = {
        "schema": "FreeCAD-e4k-saved-literal-summary-v1",
        "source": str(path),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "source_bytes": len(raw),
        "derived_summary_not_original_receipt": True,
        "no_CAD_body": True,
        "items": {},
    }
    for key, value in data.items():
        if not isinstance(value, str) or not value.lstrip().startswith(("{", "[")):
            summary["items"][key] = value
            continue
        item = {
            "literal_bytes": len(value.encode()),
            "literal_sha256": hashlib.sha256(value.encode()).hexdigest(),
        }
        try:
            literal = json.loads(value)
        except ValueError as error:
            item["parse_error"] = str(error)
            summary["items"][key] = item
            continue
        if isinstance(literal, dict):
            for name in (
                "schema",
                "units",
                "inventory_scope",
                "sample_identity_scope",
                "complete",
                "provenance",
                "end_time",
                "wrenches",
            ):
                if name in literal:
                    item[name] = literal[name]
            item["frames"] = [
                {
                    **{
                        name: frame.get(name)
                        for name in ("step", "increment", "time", "complete", "success")
                    },
                    "samples": len(frame.get("samples", [])),
                    "faces": len(frame.get("face_inventory", [])),
                    "catalogue_samples": len(frame.get("sample_inventory", [])),
                }
                for frame in literal.get("frames", [])
            ]
        summary["items"][key] = item
    return encoded(summary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--validation", type=Path)
    args = parser.parse_args()
    if args.target.exists() or args.target.is_symlink():
        raise FileExistsError("Refusing existing evidence target: " + str(args.target))
    target = args.target.resolve(strict=False)
    if not target.is_relative_to(REPO / "package/local-completion"):
        raise ValueError("Evidence target must be beneath repository package/local-completion")
    files, excluded_directories = private_files()
    gate_records = gates(files)
    positive = {
        label for label, row in gate_records.items() if row["collection_positive_gate_selection"]
    }
    plans, omitted, index = {}, [], []

    def add(source, destination, *, kind="exact-copy", body=None):
        relative = Path(destination)
        if relative.is_absolute() or ".." in relative.parts or relative in plans:
            raise ValueError("Unsafe or duplicate public destination: " + str(destination))
        data = source.read_bytes() if body is None else body
        plans[relative] = {
            "source": source,
            "body": data,
            "kind": kind,
            "source_sha256": sha(source),
            "source_bytes": source.stat().st_size,
        }

    def omit(path, reason):
        omitted.append(
            {
                "source": str(path),
                "bytes": path.stat().st_size,
                "sha256": sha(path),
                "reason": reason,
            }
        )

    # Resolve the one qualifying full-pressure case before selecting bulk.
    current_native_sha = json_read(ROOT / "candidate-binary.json")["sha256"]
    dedicated_native = []
    for label in positive:
        origins = ROOT / label / "origins.json"
        if (
            gate_records[label]["command_module"] == "NativeE4k"
            and origins.is_file()
            and json_read(origins).get("native_sha256") == current_native_sha
        ):
            dedicated_native.append(label)
    if not dedicated_native:
        raise ValueError("No successful dedicated NativeE4k gate for the current candidate exists")
    native_gate = max(
        dedicated_native, key=lambda label: (gate_records[label]["receipt_mtime_ns"], label)
    )
    dedicated_gui = set()
    for path in files:
        label = gate_label(path)
        if (
            path.name == "gui-receipt.json"
            and label in positive
            and gate_records[label]["command_module"] == "GuiE4k"
        ):
            receipt = json_read(path)
            if receipt.get("passed") is True and receipt.get("binary_sha256") == current_native_sha:
                dedicated_gui.add(label)
    if not dedicated_gui:
        raise ValueError("No successful dedicated GuiE4k gate for the current candidate exists")
    contact_body_gates = {native_gate, *dedicated_gui}
    pressure = []
    for path in files:
        if path.suffix != ".inp" or gate_label(path) != native_gate:
            continue
        reference = path.parent / "equilibrium.json"
        if not reference.is_file():
            continue
        reference_data = json_read(reference)
        if (
            reference_data.get("time") != 1.0
            or reference_data.get("binary_sha256") != current_native_sha
        ):
            continue
        deck = path.read_bytes().upper()
        steps = [
            line.replace(b" ", b"")
            for line in deck.splitlines()
            if line.split(b",", 1)[0].strip() == b"*STEP"
        ]
        if (
            len(steps) == 1
            and b"AMPLITUDE=STEP" in steps[0].split(b",")
            and b"AMPLITUDE=VARIABLEQPRESSURE" in deck
        ):
            pressure.append(path.parent)
    if len(pressure) != 1:
        raise ValueError(
            "Expected exactly one current dedicated native STEP full-pressure one-second case"
        )
    pressure_directory = pressure[0]
    mechanical_gates = []
    for label in positive:
        if gate_records[label]["command_module"] != "MechanicalE4k":
            continue
        report_path = ROOT / label / "mechanical-preservation.json"
        if not report_path.is_file():
            continue
        report = json_read(report_path)
        if (
            report.get("passed") is True
            and report.get("runs", {}).get("candidate-default", {}).get("binary_sha256")
            == current_native_sha
        ):
            mechanical_gates.append(label)
    if not mechanical_gates:
        raise ValueError("No qualifying mechanical comparison for the current native binary exists")
    mechanical_gate = max(
        mechanical_gates, key=lambda label: (gate_records[label]["receipt_mtime_ns"], label)
    )
    mechanical_directories = {
        path.parent
        for path in files
        if path.suffix == ".frd"
        and gate_label(path) == mechanical_gate
        and path.parent.name in {"previous-b6", "candidate-default"}
    }
    if len(mechanical_directories) != 2:
        raise ValueError("Expected exactly the two qualifying mechanical preservation runs")
    contacts = [
        path
        for path in files
        if ".contact-state" in path.name
        and path.name.endswith(".out")
        and gate_label(path) in contact_body_gates
    ]
    contact_bytes = sum(path.stat().st_size for path in contacts)
    if contact_bytes > MAX_POSITIVE_CONTACT_BYTES:
        raise ValueError(
            f"Positive raw contact outputs total {contact_bytes} bytes; explicit review "
            f"needed before exceeding frozen {MAX_POSITIVE_CONTACT_BYTES}-byte budget"
        )

    for name in SOURCE_NAMES:
        source = REPO / name
        if not source.is_file() or source.is_symlink():
            raise FileNotFoundError("Required named source missing: " + str(source))
        add(source, Path("final-source") / name)
    for path in files:
        relative = path.relative_to(ROOT)
        label = gate_label(path)
        if profile_map_name(path):
            continue
        if path.name in BINARY_NAMES or path.suffix.lower() in BINARY_SUFFIXES:
            continue
        if path.name in {"ccx_2.23.pdf", "ccx_2.23.txt"}:
            omit(path, "Official manual or extracted manual text; copyright body not published")
            continue
        if len(relative.parts) == 1:
            if path.suffix == ".py" or path.name in CONTEXT_NAMES:
                add(path, Path("helpers") / relative)
            elif path.suffix in {".json", ".md"}:
                add(path, Path("review-and-oracles") / relative)
            continue
        if relative.parts[0] in {
            "review-history",
            "oracle-history",
            "gui-helper-history",
            "hooks-dry-run",
        }:
            if path.suffix in {".json", ".md", ".py", ".c", ".f", ".inc", ".h"}:
                add(path, Path("history") / relative)
            else:
                omit(path, "Unselected historical non-source bulk")
            continue
        if path.name == "saved-literals.json":
            add(
                path,
                Path("summaries") / relative,
                kind="derived-saved-literal-summary",
                body=saved_summary(path),
            )
            omit(
                path,
                "Full duplicate saved literal bodies replaced by explicit derived summary; native raw outputs retained separately",
            )
        elif path.suffix.lower().startswith(".fcstd") or path.suffix.lower() in {
            ".cfg",
            ".brep",
            ".vtk",
            ".vtu",
            ".msh",
            ".geo",
            ".step",
            ".stp",
        }:
            if path.suffix.lower() != ".cfg":
                omit(path, "Private generated CAD/geometry/mesh bulk; no body published")
        elif path.suffix in {".frd", ".dat"}:
            if path.parent in mechanical_directories or path.parent == pressure_directory:
                add(path, Path("runs") / relative)
            else:
                omit(
                    path,
                    "Other private native FRD/DAT bulk; selected full pressure and two mechanical pairs retained",
                )
        elif ".contact-state" in path.name and path.name.endswith(".out.tmp"):
            omit(
                path,
                "Unpublished or partial native contact temporary output; body is not qualification",
            )
        elif ".contact-state" in path.name and path.name.endswith(".out"):
            if label in contact_body_gates:
                add(path, Path("runs") / relative)
            elif label in positive:
                omit(
                    path,
                    "Repeated broad-regression or earlier dedicated bulk; latest dedicated native/GUI current-candidate bodies retained",
                )
            else:
                omit(
                    path,
                    "Failed or superseded native contact bulk; original failure log/receipt retained without promotion",
                )
        elif path.name.endswith(".accounting.out") or path.suffix in {
            ".accounting",
            ".contact-state",
            ".inp",
            ".stdout",
            ".stderr",
            ".png",
        }:
            add(path, Path("runs") / relative)
        elif path.suffix in {".json", ".log"}:
            add(path, Path("runs") / relative)
        elif re.fullmatch(r".+\.(?:accounting|contact-state)\.run-[0-9a-f]{32}", path.name):
            add(path, Path("runs") / relative)
        else:
            omit(path, "Other private native auxiliary bulk; body not selected")

    # Immutable historical input maps stay verbatim in original receipts. A
    # separate resolution table says honestly which exact named source bodies
    # remain available; a newer current file is never repinned to an old run.
    resolutions, unresolved = [], []
    input_pins = {}
    for path in files:
        if path.name != "execution.json":
            continue
        data = json_read(path)
        for field in ("source_inputs_before", "source_inputs_after", "helper_inputs_before"):
            for source, digest in data.get(field, {}).items():
                if isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest):
                    input_pins.setdefault((source, digest), set()).add(str(path))
    historical = [path for path in files if named_input(path)]
    by_hash = {}
    for path in historical:
        by_hash.setdefault(sha(path), path)
    for (name, digest), receipts in sorted(input_pins.items()):
        source = Path(name)
        row = {"original_source": name, "expected_sha256": digest, "receipts": sorted(receipts)}
        if not named_input(source):
            row["disposition"] = (
                "External, binary, archive or excluded non-source input; original pin retained only"
            )
        else:
            blob = ROOT / "code-blobs" / digest
            candidate = None
            if blob.is_file() and not blob.is_symlink() and sha(blob) == digest:
                candidate = blob
            elif source.is_file() and not source.is_symlink() and sha(source) == digest:
                candidate = source
            elif digest in by_hash:
                candidate = by_hash[digest]
            if candidate is None:
                row["disposition"] = (
                    "Exact historical named source body unavailable; original receipt hash preserved, never repinned"
                )
                unresolved.append(row)
            else:
                candidate.read_bytes().decode("utf-8")
                destination = Path("input-code") / digest
                if destination not in plans:
                    add(candidate, destination, kind="exact-historical-input-code")
                row.update(
                    disposition="Exact named source/helper body retained",
                    snapshot=destination.as_posix(),
                    available_source=str(candidate),
                )
        resolutions.append(row)
    if args.validation:
        if not args.validation.is_file() or args.validation.is_symlink():
            raise FileNotFoundError("Validation input missing: " + str(args.validation))
        json_read(args.validation)
        add(args.validation, "validation-input.json", kind="exact-root-validation-input")

    manifest = {
        "schema": "FreeCAD-e4k-source-evidence-collection-v1",
        "source_root": str(ROOT),
        "target": str(target),
        "collector": str(Path(__file__).resolve()),
        "collector_sha256": sha(__file__),
        "native_execution_by_collector": False,
        "installation_performed": False,
        "historical_receipts_rewritten": False,
        "execution_provenance_rebased": False,
        "root_validation_supplied": str(args.validation) if args.validation else None,
        "product_pass_verdict": "Not generated by collector; root owns the final validation report",
        "gate_records": gate_records,
        "selected_full_pressure_native_directory": str(pressure_directory),
        "current_native_sha256": current_native_sha,
        "selected_dedicated_native_gate": native_gate,
        "selected_dedicated_gui_gates": sorted(dedicated_gui),
        "raw_contact_body_selection": "Latest successful dedicated NativeE4k gate by original "
        "receipt mtime, with origins bound to current candidate; successful GuiE4k receipts "
        "bound to the same candidate. Repeated broad-regression contact bulk is hash-only.",
        "selected_mechanical_gate": mechanical_gate,
        "selected_mechanical_native_directories": sorted(map(str, mechanical_directories)),
        "positive_raw_contact_files": len(contacts),
        "positive_raw_contact_bytes": contact_bytes,
        "positive_raw_contact_byte_budget": MAX_POSITIVE_CONTACT_BYTES,
        "exact_historical_named_inputs_unavailable": len(unresolved),
        "exclusions": "No CAD, native executable, object, environment, profile/config/cache body or full manual body. Excluded profile/environment/build directories are not traversed. Protected-directory digests and original command/source pins already present in receipts stay unchanged.",
    }
    generated = {
        Path("collection.json"): encoded(manifest),
        Path("hash-only-private-native-bulk.json"): encoded(
            {"schema": "FreeCAD-e4k-hash-only-private-bulk-v1", "files": omitted}
        ),
        Path("excluded-directories.json"): encoded(
            {
                "schema": "FreeCAD-e4k-excluded-directory-policy-v1",
                "directories": excluded_directories,
            }
        ),
        Path("historical-input-resolution.json"): encoded(
            {"schema": "FreeCAD-e4k-historical-input-resolution-v1", "inputs": resolutions}
        ),
    }
    # All planning, availability/capacity checks and reads precede creation.
    target.mkdir()
    for relative, plan in sorted(plans.items()):
        source = plan["source"]
        if sha(source) != plan["source_sha256"]:
            raise ValueError("Collection source changed after planning: " + str(source))
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as stream:
            stream.write(plan["body"])
        item = {
            "path": relative.as_posix(),
            "bytes": len(plan["body"]),
            "sha256": sha(destination),
            "source": str(source),
            "source_sha256": plan["source_sha256"],
            "source_bytes": plan["source_bytes"],
            "kind": plan["kind"],
        }
        if plan["kind"].startswith("exact") and item["sha256"] != item["source_sha256"]:
            raise ValueError("Exact snapshot hash mismatch: " + str(source))
        index.append(item)
    for relative, body in sorted(generated.items()):
        destination = target / relative
        with destination.open("xb") as stream:
            stream.write(body)
        index.append(
            {
                "path": relative.as_posix(),
                "bytes": len(body),
                "sha256": sha(destination),
                "source": str(Path(__file__).resolve()),
                "kind": "collector-derived-manifest",
            }
        )
    artifact_index = {
        "schema": "FreeCAD-e4k-source-artifact-index-v1",
        "artifacts": index,
        "artifact_count_excluding_this_index": len(index),
        "bytes_excluding_this_index": sum(row["bytes"] for row in index),
        "self_index_policy": "This index does not recursively include its own bytes/hash; root final report or review records its external hash.",
    }
    index_path = target / "artifact-index.json"
    with index_path.open("xb") as stream:
        stream.write(encoded(artifact_index))
    for relative, plan in plans.items():
        if sha(plan["source"]) != plan["source_sha256"]:
            raise ValueError("Collection source changed while copying: " + str(plan["source"]))
        if sha(target / relative) != hashlib.sha256(plan["body"]).hexdigest():
            raise ValueError("Collected body changed: " + str(relative))
    print(
        json.dumps(
            {
                "target": str(target),
                "artifact_count": len(index) + 1,
                "artifact_index_sha256": sha(index_path),
                "bytes_excluding_index": artifact_index["bytes_excluding_this_index"],
                "historical_named_source_bodies_unavailable": len(unresolved),
                "product_pass_verdict_generated": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
