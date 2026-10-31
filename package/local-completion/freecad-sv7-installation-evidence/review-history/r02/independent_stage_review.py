"""Independent offline stage audit. Reads bytes; never imports or runs FreeCAD."""

import ast
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import stat
import struct
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
REPO = Path("/Users/zukomgwili/src/FreeCAD")
APP = Path("/Applications/FreeCAD-27.1.0.app")
STAGE = ROOT / APP.name
RES = Path("Contents/Resources")
PREFIX = REPO / ".pixi/envs/default"
PAYROOT = ROOT / "payload"
PAY = PAYROOT / APP.relative_to("/") / RES
COMMIT = "2f6ed5df7bd9786449230ad01366a7d8e10ae0e2"
NATIVE = "1f6281e8d779deeeb0f6a587d2cdcb5a7fc935e95f90b394cb28e761b22a603e"
AUDITOR = "82f9e5ba571599b06a6df87811bb9384a28f3661c9e563820e93e11988ccf3e3"
inputs = {}


def sha(path):
    path = Path(path)
    value = hashlib.sha256(path.read_bytes()).hexdigest()
    if str(path) in inputs:
        assert inputs[str(path)] == value, path
    inputs[str(path)] = value
    return value


def unique(pairs):
    result = {}
    for key, value in pairs:
        assert key not in result, key
        result[key] = value
    return result


def reject(value):
    raise ValueError(value)


def read(path):
    path = Path(path)
    sha(path)
    return json.loads(path.read_text(), object_pairs_hook=unique, parse_constant=reject)


def canonical(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def inventory(root):
    assert root.is_dir() and not root.is_symlink(), root
    result = {".": {"kind": "dir", "mode": stat.S_IMODE(root.lstat().st_mode)}}
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = Path(directory) / name
            kind = path.lstat().st_mode
            row = {"mode": stat.S_IMODE(kind)}
            if stat.S_ISLNK(kind):
                row.update(kind="link", target=os.readlink(path))
            elif stat.S_ISDIR(kind):
                row.update(kind="dir")
            else:
                assert stat.S_ISREG(kind), path
                row.update(kind="file", sha256=sha(path))
            result[str(path.relative_to(root))] = row
    return result


def native_set(root):
    result = set()
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [name for name in dirs if not (Path(directory) / name).is_symlink()]
        for name in files:
            path = Path(directory) / name
            if path.is_symlink():
                continue
            magic = path.read_bytes()[:4]
            if magic == b"\xcf\xfa\xed\xfe":
                result.add(str(path.relative_to(root)))
    return result


def macho(path):
    """Independently parse thin Mach-O; omit only relocation/signature bookkeeping."""
    sha(path)
    data = path.read_bytes()
    header = struct.unpack_from("<IiiIIIII", data)
    assert header[0] == 0xFEEDFACF, path
    offset = 32
    retained, rpaths, sections = [], [], {}
    signature = None
    for _ in range(header[4]):
        tag, size = struct.unpack_from("<II", data, offset)
        assert size >= 8 and offset + size <= len(data)
        blob = bytearray(data[offset : offset + size])
        if tag == 0x8000001C:
            (start,) = struct.unpack_from("<I", blob, 8)
            rpaths.append(bytes(blob[start:]).split(b"\0", 1)[0].decode())
        elif tag == 0x1D:
            signature, length = struct.unpack_from("<II", blob, 8)
            assert signature + length == len(data)
        else:
            if tag == 0x19:
                segment = bytes(blob[8:24]).split(b"\0", 1)[0]
                if segment == b"__LINKEDIT":
                    blob[32:40] = b"\0" * 8
                    blob[48:56] = b"\0" * 8
                (nsects,) = struct.unpack_from("<I", blob, 64)
                for index in range(nsects):
                    entry = blob[72 + 80 * index : 152 + 80 * index]
                    section = bytes(entry[:16]).split(b"\0", 1)[0].decode()
                    segment_name = bytes(entry[16:32]).split(b"\0", 1)[0].decode()
                    (length,) = struct.unpack_from("<Q", entry, 40)
                    start, _alignment, _reloc, _count, flags = struct.unpack_from(
                        "<IIIII", entry, 48
                    )
                    if start and flags & 0xFF not in (1, 0xC, 0x12):
                        sections[segment_name + "," + section] = {
                            "offset": start,
                            "size": length,
                            "sha256": hashlib.sha256(data[start : start + length]).hexdigest(),
                        }
            retained.append(bytes(blob))
        offset += size
    assert offset == 32 + header[5] and sections
    first = min(row["offset"] for row in sections.values())
    normalized = {
        "header_without_command_counts": [header[index] for index in (0, 1, 2, 3, 6, 7)],
        "non_rpath_signature_commands_sha256": hashlib.sha256(b"".join(retained)).hexdigest(),
        "sections": sections,
        "post_load_command_body_sha256": hashlib.sha256(data[first:signature]).hexdigest(),
    }
    return {
        "sha256": sha(path),
        "rpaths": rpaths,
        "normalized": normalized,
        "normalized_sha256": hashlib.sha256(
            json.dumps(normalized, sort_keys=True).encode()
        ).hexdigest(),
        "signature_offset": signature,
    }


def embedded_entitlements(bundle):
    info = plistlib.loads((bundle / "Contents/Info.plist").read_bytes())
    executable = bundle / "Contents/MacOS" / info["CFBundleExecutable"]
    record = macho(executable)
    data = executable.read_bytes()
    offset = record["signature_offset"]
    magic, length, count = struct.unpack_from(">III", data, offset)
    assert magic == 0xFADE0CC0 and offset + length <= len(data)
    for index in range(count):
        slot, relative = struct.unpack_from(">II", data, offset + 12 + 8 * index)
        if slot == 5:
            tag, length = struct.unpack_from(">II", data, offset + relative)
            assert tag == 0xFADE7171
            return plistlib.loads(data[offset + relative + 8 : offset + relative + length])
    raise AssertionError("Missing embedded XML entitlements: " + str(bundle))


def source_map():
    core = (
        REPO / "package/local-completion/freecad-ywu-installation-evidence/private/stage_install.py"
    )
    assert sha(core) == "cca627502a56b6c9b4aefa4a970172c51e42e2dde834000decca65fd44ab46d9"
    result = {}
    tree = ast.parse(core.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.DictComp):
            if any(isinstance(t, ast.Name) and t.id == "SOURCES" for t in node.targets):
                for name in ast.literal_eval(node.value.generators[0].iter):
                    result["src/Mod/Fem/" + name] = "Mod/Fem/" + name
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            func = node.value.func
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "SOURCES"
            ):
                value = node.value.args[0]
                for name in ast.literal_eval(value.generators[0].iter):
                    result["package/calculix/force-accounting/" + name] = (
                        "data/NativeSolvers/source/" + name
                    )
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "SOURCES"
                ):
                    result[ast.literal_eval(target.slice)] = ast.literal_eval(node.value)
    adapter = ROOT / "stage_install.py"
    sha(adapter)
    text = adapter.read_text()
    for node in ast.parse(text).body:
        if isinstance(node, ast.For) and isinstance(node.target, ast.Name):
            if node.target.id == "relative":
                names = ast.literal_eval(node.iter)
                source = ast.get_source_segment(text, node)
                prefix = "Mod/BIM/" if "src/Mod/BIM/" in source else "Mod/Fem/"
                for name in names:
                    result["src/" + prefix + name] = prefix + name
            elif node.target.id == "name" and isinstance(node.iter, ast.Tuple):
                for name in ast.literal_eval(node.iter):
                    result["package/calculix/force-accounting/" + name] = (
                        "data/NativeSolvers/source/" + name
                    )
    for bead in ("960", "sv7"):
        validation = read(REPO / ("package/local-completion/freecad-" + bead + "-validation.json"))
        for name in validation["source_inputs"]:
            if name.startswith("src/Mod/Fem/") and name.endswith(".py"):
                result[name] = name.removeprefix("src/")
    return result


def dependency_record(path):
    info = path.lstat()
    value = {
        key: getattr(info, "st_" + name)
        for key, name in (
            ("dev", "dev"),
            ("inode", "ino"),
            ("mode", "mode"),
            ("size", "size"),
            ("mtime_ns", "mtime_ns"),
            ("ctime_ns", "ctime_ns"),
        )
    }
    if stat.S_ISLNK(info.st_mode):
        value.update(
            kind="link",
            target=os.readlink(path),
            resolved=str(path.resolve(strict=True)),
            resolved_sha256=sha(path),
        )
    else:
        assert stat.S_ISREG(info.st_mode)
        value.update(kind="file", sha256=sha(path))
    return value


def expected_ids(mode):
    if mode == "cold":
        return {
            "ColdBeamSv7.ColdBeamSv7.test_saved_literal_axes_case_and_output_request_survive_cold_restore"
        }
    result = {
        "AppBeamSv7.AppBeamIdentity.test_exact_application_identity_native_origins_and_default_solver"
    }
    modules = (
        [
            ("gui", name)
            for name in (
                "test_beam_section_forces",
                "test_beam_coupling",
                "test_beam_solid_coupling",
            )
        ]
        if mode == "gui"
        else [
            ("app", "test_beam_section_forces"),
            ("app", "test_beam_section_forces_native"),
            ("app", "test_beam_section_forces_lifecycle"),
            ("app", "test_beam_section_forces_safety"),
            ("app", "test_beam_coupling_native"),
            ("app", "test_beam_solid_coupling_native"),
        ]
    )
    for directory, name in modules:
        path = REPO / "src/Mod/Fem/femtest" / directory / (name + ".py")
        sha(path)
        for cls in ast.parse(path.read_text()).body:
            if isinstance(cls, ast.ClassDef):
                result.update(
                    "femtest." + directory + "." + name + "." + cls.name + "." + method.name
                    for method in cls.body
                    if isinstance(method, ast.FunctionDef) and method.name.startswith("test_")
                )
    return result


def cold_audit(location, application):
    cold = read(ROOT / (location + "-cold/cold-observation.json"))
    assert cold["schema"] == "FreeCAD-sv7-cold-beam-history-v1"
    assert cold["passed"] is True and cold["application"] == str(application)
    assert cold["commit"] == COMMIT and cold["native_sha256"] == NATIVE
    assert cold["revision"] == read(ROOT / "identity.json")["revision"]
    for name in (
        "source_inputs_rebound_or_history_promoted_current",
        "analysis_solver_rerun",
        "source_or_build_import_override",
    ):
        assert cold[name] is False, name
    assert cold["input_unchanged"] is True
    assert [row["schema"] for row in cold["cases"]] == [
        "CCX_BEAM_SECTION_V1",
        "CCX_BEAM_SECTION_V2",
        "CCX_BEAM_SECTION_V3",
    ]
    legacy = ROOT / (
        location + "-gui/test_visible_solver_write_and_run_saves_current_native_beam_end_actions"
    )
    v2 = ROOT / (
        location
        + "-cmd/coupled/test_series_beam_ground_spring_and_restraints_share_one_owned_frame"
    )
    v3 = ROOT / (
        location + "-cmd/coupled/test_hybrid_actions_solid_patch_and_native_beam_component_control"
    )
    summary = []
    for index, (folder, docname, refname, samples) in enumerate(
        (
            (legacy, "native-beam-gui.FCStd", "saved-output.json", 10),
            (v2, "series.FCStd", "observed.json", 10),
            (v3, "hybrid.FCStd", "observed.json", 4),
        ),
        1,
    ):
        row = cold["cases"][index - 1]
        document, reference = folder / docname, folder / refname
        assert row["document"] == {"path": str(document), "sha256": sha(document)}
        assert row["reference"] == {"path": str(reference), "sha256": sha(reference)}
        literal = read(reference)
        assert literal["schema"] == row["schema"] == "CCX_BEAM_SECTION_V" + str(index)
        assert literal["provenance"]["binary"] == str(
            application / RES / "data/NativeSolvers/ccx-force-accounting"
        )
        assert literal["provenance"]["binary_sha256"] == NATIVE
        assert literal["provenance"]["case"] == row["case"]
        assert literal["units"] == {"length": "mm", "force": "N", "moment": "N*mm"}
        assert len(literal["frames"]) == row["frames"] == 1
        assert len(literal["frames"][0]["samples"]) == row["samples"] == samples
        assert row["completed_run"] is False and row["status"].startswith("Historical")
        assert row["reference_is_exact_stored_text"] is (index == 1)
        with zipfile.ZipFile(document) as archive:
            tree = ET.fromstring(archive.read("Document.xml"))
        result_properties = []
        for obj in tree.findall(".//ObjectData/Object"):
            props = {p.attrib["name"]: p for p in obj.findall("./Properties/Property")}
            if "SectionData" in props:
                assert "SectionHash" in props and "CompletedRun" in props
                result_properties.append(props)
        assert len(result_properties) == 1
        props = result_properties[0]
        saved = props["SectionData"].find("String").attrib["value"]
        saved_hash = props["SectionHash"].find("String").attrib["value"]
        assert (
            hashlib.sha256(saved.encode()).hexdigest()
            == saved_hash
            == row["stored_section_data_sha256"]
        )
        assert json.loads(saved, object_pairs_hook=unique, parse_constant=reject) == literal
        assert props["CompletedRun"].find("Bool").attrib["value"] == "true"
        if index == 1:
            assert reference.read_text() == saved
            assert row["mechanical_results"] is None
        elif index == 2:
            assert row["mechanical_results"] is None
            assert literal["position_frame"] == "NATIVE_MAP_EXPANDED_SECTION"
            assert literal["geometry_source"] == "CO_PLUS_NATIVE_MAP_VOLD_ARGUMENT"
            assert len(literal["frames"][0]["native_actions"]["support"]["spcs"]) == 8
        else:
            mechanical = row["mechanical_results"]
            assert set(mechanical["solid_original_nodes"]) == set(range(101, 107))
            assert len(mechanical["solid_original_nodes"]) == 6
            assert set(mechanical["mixed_original_nodes"]) == set(range(1, 6)) | set(
                range(101, 107)
            )
            assert len(mechanical["mixed_original_nodes"]) == 11
            assert mechanical["solid_owner"] == "HybridPrism"
            assert mechanical["mixed_stress_xx_empty"] is True
            assert mechanical["source_file_sha256"] == literal["provenance"]["frd"]["sha256"]
            assert len(mechanical["solid_stress_xx_MPa"]) == 6
            assert all(abs(v - 4 / 3) <= 0.0001 for v in mechanical["solid_stress_xx_MPa"])
            assert literal["position_frame"] == "NATIVE_MAP_EXPANDED_SECTION"
            assert literal["geometry_source"] == "CO_PLUS_NATIVE_MAP_VOLD_ARGUMENT"
        summary.append(
            {
                "schema": row["schema"],
                "document": row["document"],
                "reference": row["reference"],
                "stored_section_data_sha256": saved_hash,
                "saved_completed_run": True,
                "restored_completed_run": False,
                "historical_status": row["status"],
                "case": row["case"],
                "samples": samples,
            }
        )
    return summary


def validate_identity(identity):
    assert identity == {
        "schema": "FreeCAD-sv7-install-identity-v1",
        "commit": COMMIT,
        "revision": "49261 +242 (Git)",
        "native_sha256": NATIVE,
        "fix_bead": "FreeCAD-sv7",
        "deployment_bead": "FreeCAD-nta",
        "application": str(APP),
        "rollback_backup": "/Users/zukomgwili/Applications/FreeCAD Backups/FreeCAD-27.1.0-before-sv7-o698f09g.app",
    }


def main():
    identity = read(ROOT / "identity.json")
    validate_identity(identity)
    baseline, sealed = read(ROOT / "baseline-inventory.json"), read(ROOT / "stage-inventory.json")
    assert canonical(baseline) == "35421d224265349faebeb8ab974ec69e77452e0c44cb7b758709985292d86081"
    assert inventory(APP) == baseline and inventory(STAGE) == sealed
    payload = inventory(PAYROOT)
    audits = {
        mode: read(ROOT / name)
        for mode, name in (
            ("payload", "independent-payload-audit.json"),
            ("stage", "independent-stage-audit.json"),
            ("custody", "independent-stage-custody.json"),
        )
    }
    assert sha(ROOT / "audit_payload_stage.py") == AUDITOR
    for mode, proof in audits.items():
        assert proof["schema"] == "FreeCAD.LOCAL_INSTALL_INDEPENDENT_AUDIT_V2"
        assert (
            proof["mode"] == mode and proof["passed"] is True and proof["helper_sha256"] == AUDITOR
        )
    p, s, c = (audits[mode] for mode in ("payload", "stage", "custody"))
    assert p["commit"] == s["source_commit"] == c["compiled_commit"] == COMMIT
    assert c["compiled_revision"] == identity["revision"]
    assert canonical(payload) == p["payload_inventory_sha256"]
    assert len(payload) == p["payload_inventory_entries"]
    assert canonical(baseline) == p["baseline_inventory_sha256"] == s["baseline_inventory_sha256"]
    assert canonical(sealed) == s["sealed_stage_inventory_sha256"]
    assert (
        s["payload_audit_sha256"]
        == c["payload_audit_sha256"]
        == sha(ROOT / "independent-payload-audit.json")
    )
    assert c["stage_audit_sha256"] == sha(ROOT / "independent-stage-audit.json")
    manifest = REPO / "build/release/install_manifest.txt"
    assert sha(manifest) == p["install_manifest"]["sha256"]
    expected = {str(Path(line).relative_to("/")) for line in manifest.read_text().splitlines()}
    assert expected == {name for name, row in payload.items() if row["kind"] != "dir"}
    assert len(expected) == p["install_manifest"]["unique_leaf_count"]
    native = native_set(PAY)
    assert (
        native
        == {row["relative"] for row in p["native"]}
        == {row["relative"] for row in s["native"]}
    )
    assert (
        len(native)
        == len(p["native"])
        == len(s["native"])
        == p["payload_native_count"]
        == s["native_payload_parity_count"]
        == c["native_payload_count"]
    )
    assert (
        canonical(sorted(native))
        == p["native_complete_relative_set_sha256"]
        == s["native_complete_relative_set_sha256"]
        == c["native_complete_relative_set_sha256"]
    )
    prows, srows = ({row["relative"]: row for row in proof["native"]} for proof in (p, s))
    for relative in sorted(native):
        pp, sp = macho(PAY / relative), macho(STAGE / RES / relative)
        pr, sr = prows[relative], srows[relative]
        assert pp["sha256"] == pr["payload_sha256"] == sr["payload_sha256"]
        assert sp["sha256"] == sr["stage_sha256"]
        assert pp["normalized"] == sp["normalized"]
        assert (
            pp["normalized_sha256"]
            == pr["normalized_sha256"]
            == sp["normalized_sha256"]
            == sr["normalized_sha256"]
        )
        assert pp["rpaths"] == pr["payload_rpaths"] == sp["rpaths"] == sr["rpaths"]
        assert pr["build_matches"]
        for match in pr["build_matches"]:
            actual = macho(REPO / "build/release" / match["path"])
            assert actual["sha256"] == match["sha256"] and actual["rpaths"] == match["rpaths"]
            assert actual["normalized"] == pp["normalized"]
    assert native_set(STAGE) == {str(RES / name) for name in native} | (
        native_set(APP) - {str(RES / name) for name in native}
    )
    for row in s["additional_inherited_native"]:
        old, new = macho(APP / row["relative"]), macho(STAGE / row["relative"])
        assert old["sha256"] == row["old_sha256"] and new["sha256"] == row["stage_sha256"]
        assert old["normalized"] == new["normalized"] and old["rpaths"] == new["rpaths"]
        assert new["normalized_sha256"] == row["normalized_sha256"]
    non_native = 0
    for relative, row in inventory(PAY).items():
        parts = Path(relative).parts
        if (
            row["kind"] == "dir"
            or relative in native
            or "__pycache__" in parts
            or "_CodeSignature" in parts
            or relative.endswith(".pyc")
        ):
            continue
        actual = sealed[str(RES / relative)]
        assert actual["kind"] == row["kind"]
        assert actual["mode"] == (row["mode"] if row["kind"] == "link" else row["mode"] & ~0o222)
        key = "target" if row["kind"] == "link" else "sha256"
        assert actual[key] == row[key]
        non_native += 1
    assert non_native == s["non_native_payload_matches"]
    sources = source_map()
    for source, target in sources.items():
        assert sha(REPO / source) == sha(STAGE / RES / target), source
    assert len(sources) == s["selected_source_matches"]
    for base in (STAGE / RES, PAY):
        assert sha(base / "data/NativeSolvers/ccx-force-accounting") == NATIVE
    resource_inventory = inventory(STAGE / RES)
    assert not any(
        "__pycache__" in Path(name).parts or name.endswith(".pyc") for name in resource_inventory
    )
    assert all(
        row["kind"] == "link" or not row["mode"] & 0o222 for row in resource_inventory.values()
    )
    profiles = read(ROOT / "profile-inventories.json")
    assert len(profiles) == c["profiles_exact_unchanged_count"] == 3
    for path, expected_inventory in profiles.items():
        assert inventory(Path(path)) == expected_inventory
    assert c["profiles_inventory_receipt_sha256"] == sha(ROOT / "profile-inventories.json")
    critical = read(ROOT / "critical-before-DESTDIR.json")
    assert (
        critical["passed"] is True
        and len(critical["files"]) == c["selected_critical_files_unchanged_count"] == 17
    )
    for path, expected_record in critical["files"].items():
        assert dependency_record(Path(path)) == expected_record, path
    assert c["critical_receipt_sha256"] == sha(ROOT / "critical-before-DESTDIR.json")
    namespace = read(ROOT / "namespace-plan.json")
    assert (
        len(namespace)
        == len(p["external_namespace_sha256"])
        == c["namespace_unchanged_count"]
        == 11
    )
    for relative, row in namespace.items():
        live, incoming, canonical_path = (
            PREFIX / relative,
            PAYROOT / PREFIX.relative_to("/") / relative,
            STAGE / RES / "Ext/freecad" / Path(relative).name,
        )
        assert (
            sha(live)
            == sha(incoming)
            == sha(canonical_path)
            == row["before"]
            == row["after"]
            == p["external_namespace_sha256"][relative]
        )
        assert stat.S_IMODE(live.stat().st_mode) == row["mode"]
    entitlements = {}
    for name in ("FreeCADPreviewExtension.appex", "FreeCADThumbnailExtension.appex"):
        recorded = plistlib.loads((ROOT / (name + ".plist")).read_bytes())
        sha(ROOT / (name + ".plist"))
        assert embedded_entitlements(APP / RES / "PlugIns" / name) == recorded
        assert embedded_entitlements(STAGE / RES / "PlugIns" / name) == recorded
        entitlements[name] = recorded
    applications = {}
    for mode, count in (("cmd", 31), ("gui", 6), ("cold", 1)):
        directory = ROOT / ("stage-" + mode)
        execution, regression = read(directory / "execution.json"), read(
            directory / "regression.json"
        )
        assert execution["schema"] == "FreeCAD-sv7-literal-application-gate-v1"
        assert execution["passed"] is True and execution["application"] == str(STAGE)
        assert execution["mode"] == mode and execution["location"] == "stage"
        assert (
            execution["source_commit"] == COMMIT
            and execution["revision"] == identity["revision"]
            and execution["native_sha256"] == NATIVE
        )
        assert (
            type(execution["returncode"]) is int
            and execution["returncode"] == 0
            and execution["timed_out"] is False
        )
        for key in (
            "child_reaped",
            "process_group_gone",
            "application_unchanged",
            "profiles_and_dependencies_unchanged",
            "inputs_unchanged",
            "strict_signature_verified",
            "semantic_tests_passed",
            "original_app_unchanged",
        ):
            assert execution[key] is True, (mode, key)
        assert execution["inputs_before"] == execution["inputs_after"]
        for path, expected_sha in execution["inputs_after"].items():
            assert sha(path) == expected_sha, path
        assert sha(directory / "run.log") == execution["log_sha256"]
        assert sha(directory / "regression.json") == execution["regression_sha256"]
        text = (directory / "run.log").read_text()
        assert re.findall(r"^Ran (\d+) tests? in [0-9.]+s$", text, re.M) == [str(count)]
        assert len(re.findall(r"^OK$", text, re.M)) == 1
        assert (
            regression["schema"] == "FreeCAD-sv7-installation-regression-v1"
            and regression["passed"] is True
        )
        assert (
            regression["application"] == str(STAGE)
            and regression["commit"] == COMMIT
            and regression["revision"] == identity["revision"]
            and regression["native_sha256"] == NATIVE
        )
        assert (
            regression["expected_tests"]
            == regression["executed_tests"]
            == execution["executed_tests"]
            == count
        )
        assert (
            set(regression["selected_test_ids"]) == expected_ids(mode)
            and len(regression["selected_test_ids"]) == count
        )
        assert regression["skipped"] == regression["failures"] == regression["errors"] == []
        assert regression["gui"] is (mode == "gui")
        for key in (
            "source_or_build_import_override",
            "native_solver_override",
            "original_project_opened_changed_or_solved",
        ):
            assert regression[key] is False
        assert regression["identity_sha256"] == sha(ROOT / "identity.json")
        for record in regression["final_module_origins"].values():
            path = Path(record["path"])
            assert path.is_relative_to(STAGE / RES / "Mod/Fem") and sha(path) == record["sha256"]
            assert (
                sha(REPO / "src/Mod/Fem" / path.relative_to(STAGE / RES / "Mod/Fem"))
                == record["sha256"]
            )
        observed = read(directory / "identity-observation.json")
        assert (
            observed["application"] == str(STAGE)
            and observed["runtime"][-1] == COMMIT
            and observed["runtime"][3] == identity["revision"]
        )
        assert (
            observed["GuiUp"] is (mode == "gui")
            and Path(observed["home_path"]).resolve() == STAGE / RES
        )
        assert observed["candidate"] == {
            "path": str(STAGE / RES / "data/NativeSolvers/ccx-force-accounting"),
            "sha256": NATIVE,
            "override": False,
            "capabilities": {
                "--freecad-force-accounting-version": "CCX_FORCE_ACCOUNTING_V3",
                "--freecad-contact-state-version": "CCX_CONTACT_STATE_V1",
                "--freecad-beam-section-version": "CCX_BEAM_SECTION_V1",
                "--freecad-beam-coupling-version": "CCX_BEAM_SECTION_V2",
                "--freecad-beam-solid-version": "CCX_BEAM_SECTION_V3",
            },
        }
        for group in ("native_origins", "python_origins"):
            for record in observed[group].values():
                if "path" in record:
                    path = Path(record["path"])
                    assert path.is_relative_to(STAGE / RES) and sha(path) == record["sha256"]
        executable = Path(observed["process_executable"]["path"])
        assert executable == STAGE / RES / "bin" / ("FreeCAD" if mode == "gui" else "FreeCADCmd")
        assert sha(executable) == observed["process_executable"]["sha256"]
        applications[mode] = {
            "tests": count,
            "receipt_sha256": sha(directory / "execution.json"),
            "regression_sha256": sha(directory / "regression.json"),
            "identity_sha256": sha(directory / "identity-observation.json"),
        }
    cold_domains = cold_audit("stage", STAGE)
    assert inventory(APP) == baseline and inventory(STAGE) == sealed
    for path, expected_inventory in profiles.items():
        assert inventory(Path(path)) == expected_inventory
    for path, expected_sha in tuple(inputs.items()):
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected_sha, path
    report = {
        "schema": "FreeCAD-sv7-independent-stage-review-v1",
        "passed": True,
        "reviewer": "/root/sv7_install_audit",
        "compiled_commit": COMMIT,
        "revision": identity["revision"],
        "native_sha256": NATIVE,
        "payload_native_images": len(native),
        "inherited_native_images": len(s["additional_inherited_native"]),
        "non_native_payload_matches": non_native,
        "selected_source_matches": len(sources),
        "manifest_leaf_set_count": len(expected),
        "profiles_unchanged": 3,
        "namespace_files_unchanged": 11,
        "selected_critical_files_unchanged": 17,
        "stage_inventory_sha256": canonical(sealed),
        "baseline_inventory_sha256": canonical(baseline),
        "quicklook_embedded_entitlements": entitlements,
        "application_gates": applications,
        "cold_domains": cold_domains,
        "findings": [],
        "scope": "Independent read/hash/parse only. No dynamic deployment helper, FreeCAD, solver or native signature command executed. Actual Mach-O bytes/body/RPATH/embedded-entitlement/source/inventory checks performed; cryptographic strict-signature success is bound to root-produced frozen-supervisor reports, not independently rerun here. No engineering acceptance.",
        "inputs": inputs,
        "helper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    with (ROOT / "stage-independent-review.json").open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(
        json.dumps(
            {
                key: value
                for key, value in report.items()
                if key not in ("inputs", "quicklook_embedded_entitlements")
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
