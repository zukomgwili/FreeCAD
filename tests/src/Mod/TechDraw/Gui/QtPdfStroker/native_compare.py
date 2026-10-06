# SPDX-License-Identifier: LGPL-2.1-or-later
"""Launch and compare isolated stock FreeCAD exports with mitigation bypassed.

Pre-generated --baseline-dir/--patched-dir can be compared without app launches.
For generation, provide --freecad, --python-runtime, --bypass-module, both Qt
library directories and a new --output directory. The launcher overrides
library/platform paths only for its child processes and uses fresh user/system
configurations. Installed Qt and the user's configurations are never written.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import subprocess
import sys


def compare(*args, **kwargs):
    from compare import compare as compare_pdfs

    return compare_pdfs(*args, **kwargs)


def rasterize(*args, **kwargs):
    from compare import rasterize as rasterize_pdf

    return rasterize_pdf(*args, **kwargs)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_report_destination(destination, directories):
    """Refuse report writes to input evidence, loaded runtimes or protected files."""
    destination = destination.resolve()
    for directory in directories:
        directory = directory.resolve()
        if destination.is_relative_to(directory):
            raise ValueError("Report must stay outside both input evidence directories")
        provenance = json.loads((directory / "native-provenance.json").read_text())
        launch_record = json.loads((directory / "launch.json").read_text())
        prefixes = [
            Path(provenance[key]).resolve()
            for key in ("expected_qt_prefix", "expected_qt_lib", "expected_plugin_dir")
        ]
        prefixes.append(Path(launch_record["environment_overrides"]["PYTHONHOME"]).resolve())
        prefixes.append(Path(provenance["module"]).resolve().parent)
        if any(destination.is_relative_to(prefix) for prefix in prefixes):
            raise ValueError(
                "Report must stay outside selected runtimes and scratch module evidence"
            )
        protected = provenance["bypass_provenance"]["protected_original_sha256"]
        if destination in {Path(path).resolve() for path in protected}:
            raise ValueError("Report must not overwrite a protected source/build file")


def launch(args, side):
    directory = args.output.resolve() / side
    directory.mkdir(parents=True, exist_ok=False)
    qt_lib = getattr(args, side + "_qt_lib").resolve()
    python_runtime = (getattr(args, side + "_python_runtime") or args.python_runtime).resolve()
    plugin_directory = getattr(args, side + "_plugin_dir")
    if plugin_directory:
        plugin_directory = plugin_directory.resolve()
    else:
        candidates = [
            qt_lib.parent / "plugins",
            qt_lib / "qt6/plugins",
            qt_lib.parent / "lib/qt6/plugins",
        ]
        plugin_directory = next(
            (path for path in candidates if (path / "platforms").is_dir()), None
        )
    if plugin_directory is None:
        raise ValueError(f"{side}: specify the selected runtime's --{side}-plugin-dir")
    environment = os.environ.copy()
    macro = Path(__file__).with_name("native-freecad.FCMacro").resolve()
    environment.update(
        {
            "QT_QPA_PLATFORM_PLUGIN_PATH": str(plugin_directory / "platforms"),
            "QT_PLUGIN_PATH": str(plugin_directory),
            "PYTHONHOME": str(python_runtime),
            "TD_NATIVE_DISPOSABLE": "1",
            "TD_NATIVE_EXPECTED_QT_VERSION": getattr(args, "expected_qt_version", "6.11.2"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "TD_NATIVE_OUTPUT": str(directory),
            "TD_NATIVE_BYPASS_MODULE": str(args.bypass_module.resolve()),
            "TD_NATIVE_MACRO_PATH": str(macro),
            "TD_NATIVE_MACRO_SHA256": digest(macro),
            "TD_NATIVE_QT_LIB": str(qt_lib),
            "TD_NATIVE_QT_PREFIX": str(
                (getattr(args, side + "_qt_prefix") or qt_lib.parent).resolve()
            ),
            "TD_NATIVE_PLUGIN_ROOT": str(plugin_directory),
        }
    )
    if sys.platform == "darwin":
        environment.update(
            {
                "DYLD_LIBRARY_PATH": str(qt_lib),
                "DYLD_PRINT_LIBRARIES": "1",
                "QT_QPA_PLATFORM": "cocoa",
            }
        )
    elif sys.platform.startswith("linux"):
        environment["LD_LIBRARY_PATH"] = os.pathsep.join(
            filter(
                None,
                (
                    str(qt_lib),
                    str(python_runtime / "lib"),
                    environment.get("LD_LIBRARY_PATH", ""),
                ),
            )
        )
        environment["QT_QPA_PLATFORM"] = "xcb"
    elif sys.platform == "win32":
        extra = getattr(args, side + "_runtime_dll_dirs", ())
        environment["PATH"] = os.pathsep.join(
            (str(qt_lib), *(str(path.resolve()) for path in extra), environment.get("PATH", ""))
        )
        environment["QT_QPA_PLATFORM"] = "windows"
        # Embedded Python ignores inherited Python paths. FreeCAD's Windows
        # startup registers this selected directory for extension dependencies.
        environment["FREECAD_LIBPACK_BIN"] = str(qt_lib)
    else:
        raise ValueError("The native launcher supports macOS, Linux and Windows")
    command = [
        str(args.freecad.resolve()),
        "--hidden",
        "--user-cfg",
        str(directory / "user.cfg"),
        "--system-cfg",
        str(directory / "system.cfg"),
        str(macro),
    ]
    if sys.platform == "win32":
        site_packages = python_runtime / "Lib/site-packages"
        if not site_packages.is_dir():
            raise ValueError(f"{side}: selected runtime has no Python site-packages")
        command[-1:-1] = ["--python-path", str(site_packages)]
    (directory / "launch.json").write_text(
        json.dumps(
            {
                "command": command,
                "environment_overrides": {
                    key: environment[key]
                    for key in environment
                    if key.startswith(("TD_NATIVE_", "DYLD_", "QT_"))
                    or key
                    in (
                        "PYTHONHOME",
                        "PYTHONDONTWRITEBYTECODE",
                        "PYTHONNOUSERSITE",
                        "LD_LIBRARY_PATH",
                        "PATH",
                        "DISPLAY",
                        "FREECAD_LIBPACK_BIN",
                    )
                },
            },
            indent=2,
        )
        + "\n"
    )
    with (directory / "runtime.log").open("w") as log:
        subprocess.run(
            command,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
            timeout=180,
        )
    if not all(
        (directory / name).is_file() for name in ("manifest.json", "native-provenance.json")
    ):
        raise ValueError(f"{side}: FreeCAD did not complete the macro; inspect runtime.log")
    return directory


def check_pre_export_evidence(record, case, macro_source):
    """Predict null-frame warnings from prospective scene inputs, never PDF results."""
    evidence = record["pre_export_evidence"]
    if (
        evidence["phase"] != "before-stock-command"
        or evidence["macro_source"] != macro_source
        or evidence["device"] != case["device"]
        or evidence["scenario"] != case["scenario"]
        or type(evidence["pdf_version"]) is not int
        or type(case["pdf_version"]) is not int
        or evidence["pdf_version"] != case["pdf_version"]
    ):
        raise ValueError("Prospective native inputs do not match the exported case/source")
    palette = evidence["text_palette"]
    if set(palette) != {
        "application_rgba",
        "widget_text_control_rgba",
        "new_graphics_text_rgba",
    } or any(
        len(rgba) != 4 or any(type(value) is not int or not 0 <= value <= 255 for value in rgba)
        for rgba in palette.values()
    ):
        raise ValueError("Invalid prospective text palette")
    if palette["new_graphics_text_rgba"] != palette["widget_text_control_rgba"]:
        raise ValueError("Default text pen differs from its source palette")
    readiness = evidence["face_readiness"]
    if readiness != {
        "policy": "global-thread-pool-idle/painted-box-face-v1",
        "active_threads": 0,
        "face_count": 1,
        "stable_samples": 2,
        "poll_ms": 50,
        "timeout_ms": 20000,
    } or any(type(value) is not int for key, value in readiness.items() if key != "policy"):
        raise ValueError("Missing completed native face readiness")
    faces = evidence["scene"]["faces"]
    if len(faces) != 1 or faces != record["faces"]:
        raise ValueError("Projected face changed before/after export")
    face = faces[0]
    elements = face["elements"]
    if (
        type(face["type"]) is not int
        or face["type"] != 65556
        or face["visible"] is not True
        or face["empty"] is not False
        or face["bounds"] != [-50.0, -50.0, 100.0, 100.0]
        or not 5 <= len(elements) <= 12
        or elements[0][:2] != elements[-1][:2]
        or any(
            len(element) != 3
            or type(element[2]) is not int
            or element[2] not in (0, 1)
            or any(
                type(value) not in (int, float)
                or not math.isfinite(value)
                or value not in (-50.0, 50.0)
                for value in element[:2]
            )
            for element in elements
        )
        or type(face["length_scene"]) not in (int, float)
        or not math.isclose(face["length_scene"], 400.0, abs_tol=1e-6)
        or any(
            len(face[key]) != 4
            or any(type(value) is not int or not 0 <= value <= 255 for value in face[key])
            for key in ("brush_rgba", "pen_rgba")
        )
        or type(face["qt_pen_is_cosmetic"]) is not bool
        or any(
            type(face[key]) is not int
            for key in ("fill_rule", "brush_style", "pen_style", "cap", "join")
        )
        or any(
            type(face[key]) not in (int, float) or not math.isfinite(face[key])
            for key in ("width_scene", "dash_offset", "effective_opacity")
        )
        or not 0 < face["effective_opacity"] <= 1
        or len(face["scene_transform"]) != 9
        or any(
            type(value) not in (int, float) or not math.isfinite(value)
            for value in face["scene_transform"] + face["dash_pattern"]
        )
    ):
        raise ValueError("Incomplete or invalid projected box face inputs")
    required = {
        "distance": 1,
        "theoretical-exact": 1,
        "area-and-theoretical-exact": 2,
        "area-relocated-and-theoretical-exact": 2,
    }.get(case["scenario"], 0)

    def origin_frames(scene):
        if any(
            type(frame["visible"]) is not bool or type(frame["null"]) is not bool
            for frame in scene["rectangles"]
        ):
            raise ValueError("Frame visibility/null state must be Boolean")
        return sorted(
            (frame for frame in scene["rectangles"] if frame["visible"] and frame["null"]),
            key=lambda frame: json.dumps(frame, sort_keys=True),
        )

    frames = origin_frames(evidence["scene"])
    if len(frames) != required or frames != origin_frames(record):
        raise ValueError("Required null origin frames changed before/after export")
    for frame in frames:
        transform = frame["scene_transform"]
        if (
            type(frame["type"]) is not int
            or frame["type"] != 65540
            or len(frame["rect"]) != 4
            or any(
                type(value) not in (int, float) or not math.isfinite(value)
                for value in frame["rect"]
            )
            or frame["rect"] != [0.0, 0.0, 0.0, 0.0]
            or any(type(value) is not int for value in frame["rgba"])
            or frame["rgba"] != palette["new_graphics_text_rgba"]
            or type(frame["alpha"]) is not int
            or frame["alpha"] != frame["rgba"][3]
            or not 0 < frame["alpha"] <= 255
            or type(frame["width_scene"]) not in (int, float)
            or frame["width_scene"] != 5.0
            or frame["qt_pen_is_cosmetic"] is not False
            or type(frame["pen_style"]) is not int
            or frame["pen_style"] != 1  # Qt::SolidLine
            or type(frame["pen_brush_style"]) is not int
            or frame["pen_brush_style"] != 1  # Qt::SolidPattern
            or type(frame["brush_style"]) is not int
            or frame["brush_style"] != 0  # Qt::NoBrush
            or type(frame["effective_opacity"]) not in (int, float)
            or frame["effective_opacity"] != 1.0
            or len(transform) != 9
            or any(
                type(value) not in (int, float) or not math.isfinite(value) for value in transform
            )
            or [transform[2], transform[5], transform[8]] != [0.0, 0.0, 1.0]
        ):
            raise ValueError("Null origin frame left the independently verified PDF branch")
    translucent = sum(0 < frame["alpha"] < 255 for frame in frames)
    expectation = {
        "required_count": required,
        "actual_count": len(frames),
        "translucent_count": translucent,
        "baseline_invalid_closes": translucent,
        "frames": frames,
    }
    expected = int(case["scenario"] == "short-gap") + translucent
    if (
        any(
            type(evidence["null_origin_frame_expectation"][key]) is not int
            for key in (
                "required_count",
                "actual_count",
                "translucent_count",
                "baseline_invalid_closes",
            )
        )
        or type(evidence["baseline_invalid_closes"]) is not int
        or type(case["baseline_invalid_closes"]) is not int
        or evidence["null_origin_frame_expectation"] != expectation
        or evidence["baseline_invalid_closes"] != expected
        or case["baseline_invalid_closes"] != expected
        or (required and case["pdf_version"] != 0)
    ):
        raise ValueError("Baseline expectation was not derived from prospective pen inputs")
    return {
        "text_palette": palette,
        "null_origin_frame_expectation": expectation,
        "faces": faces,
        "face_readiness": readiness,
    }


def check_stock_records(
    provenance,
    manifest,
    directory,
    expected_qt_version="6.11.2",
    path_type=Path,
    side="native",
    require_prospective=False,
):
    """Validate the same stock model/dialog controls on native or transported paths."""
    if expected_qt_version not in ("6.11.1", "6.11.2"):
        raise ValueError("Unsupported expected native Qt version")
    if path_type not in (Path, PureWindowsPath):
        raise ValueError("Unsupported recorded path protocol")

    def recorded_path(value):
        path = path_type(value)
        return path.resolve() if path_type is Path else path

    suite = [record for record in provenance["records"] if "gui_tests" in record]
    if suite != [{"gui_tests": 11, "failures": 0, "errors": 0}]:
        raise ValueError(f"{side}: full native GUI test suite was not successful")
    area = [
        record["area_value_mm2"] for record in provenance["records"] if "area_value_mm2" in record
    ]
    if len(area) != 1 or abs(area[0] - 100) >= 1e-9:
        raise ValueError(f"{side}: measured Area control changed")
    exports = [record for record in provenance["records"] if "name" in record]
    if (
        provenance["qt_version"] != manifest["qt_version"]
        or provenance["qt_version"] != expected_qt_version
        or provenance.get("expected_qt_version", "6.11.2") != expected_qt_version
    ):
        raise ValueError(f"{side}: native qualification requires verified Qt {expected_qt_version}")
    scenarios = {
        "box-only",
        "short-gap",
        "short-gap-opaque",
        "short-solid",
        "long-dashed",
        "zero-width-translucent",
        "zero-width-opaque",
        "zero-width-archival",
        "distance",
        "theoretical-exact",
        "area-and-theoretical-exact",
        "area-relocated-and-theoretical-exact",
    }
    required = {
        (device, scenario) for device in ("qpdfwriter", "qprinter") for scenario in scenarios
    }
    actual = [(case["device"], case["scenario"]) for case in manifest["cases"]]
    if len(actual) != len(required) or set(actual) != required:
        raise ValueError(f"{side}: all twelve scenarios are required for both stock devices")
    if len(exports) != len(manifest["cases"]):
        raise ValueError(f"{side}: export records do not match the manifest")
    prospective = "macro_source" in provenance
    if require_prospective and not prospective:
        raise ValueError(f"{side}: current launch requires prospective source/input evidence")
    if prospective != any("pre_export_evidence" in record for record in exports):
        raise ValueError(f"{side}: prospective source and input evidence must occur together")
    expectations = []
    for record, case in zip(exports, manifest["cases"]):
        if Path(case["pdf"]).name != case["pdf"] or "\\" in case["pdf"]:
            raise ValueError(f"{side}: expected a PDF filename")
        if record["device"] != case["device"] or record["name"] != case["scenario"]:
            raise ValueError(f"{side}: device/scenario provenance does not match")
        if prospective:
            expectations.append(check_pre_export_evidence(record, case, provenance["macro_source"]))
            if path_type is Path:
                snapshot = Path(directory) / f"pre-export-{case['device']}-{case['scenario']}.json"
                if json.loads(snapshot.read_text()) != record["pre_export_evidence"]:
                    raise ValueError(f"{side}: persisted prospective snapshot changed")
        elif "pre_export_evidence" in record:
            raise ValueError(f"{side}: partial prospective evidence")
        elif type(case["baseline_invalid_closes"]) is not int or case[
            "baseline_invalid_closes"
        ] != {
            "short-gap": 1,
            "distance": 1,
            "theoretical-exact": 1,
            "area-and-theoretical-exact": 2,
            "area-relocated-and-theoretical-exact": 2,
        }.get(
            case["scenario"], 0
        ):
            raise ValueError(
                f"{side}: legacy capture must retain its original baseline expectations"
            )
        if record["device"] == "qpdfwriter":
            valid = record["stock_dialog"] == ["Gui::FileDialog"] and record[
                "screen_mode_before_after"
            ] == [True, True]
        else:
            settings = record["printer_settings"]
            valid = record["stock_dialog"] == ["QPrintDialog"] and record[
                "screen_mode_before_during_after"
            ] == [True, False, True]
            valid = (
                valid
                and bool(settings)
                and all(
                    item["format"] == 1
                    and item["resolution"] == 1200
                    and item["full_page"]
                    and item["pdf_version"] == case["pdf_version"]
                    and recorded_path(item["file"])
                    == recorded_path(path_type(directory) / case["pdf"])
                    for item in settings
                )
            )
            if provenance["qpa_platform"] == "windows":
                native_ui = record.get("native_ui_settings", [])
                valid = valid and len(settings) == 1 and len(native_ui) == 1
                valid = valid and native_ui[0].get("format") == 0
                valid = valid and native_ui[0].get("dialog_class") == "#32770"
                valid = valid and native_ui[0].get("button_id") == 1
                valid = valid and native_ui[0].get("title") == "Print"
                valid = valid and all(
                    native_ui[0].get(key) is True
                    for key in ("visible", "button_visible", "button_enabled")
                )
                valid = valid and native_ui[0].get("button_class") == "Button"
                valid = (
                    valid
                    and native_ui[0].get("button_label", "").replace("&", "").casefold() == "print"
                )
                valid = valid and all(
                    type(native_ui[0].get(key)) is int and native_ui[0][key] > 0
                    for key in ("dialog_handle", "button_handle", "process_id", "thread_id")
                )
                valid = valid and native_ui[0].get("button_process_id") == native_ui[0].get(
                    "process_id"
                )
                valid = valid and native_ui[0].get("button_thread_id") == native_ui[0].get(
                    "thread_id"
                )
            else:
                valid = valid and len(settings) >= 2
        if not valid:
            raise ValueError(
                f"{side}/{case['name']}: stock dialog/physical mode verification failed"
            )
    return expectations


def check_provenance(baseline_dir, patched_dir, allow_external=(), expected_qt_version="6.11.2"):
    sides = {}
    if set(allow_external) - {"Svg", "SvgWidgets", "UiTools"}:
        raise ValueError("External Qt allowance is limited to Svg, SvgWidgets and UiTools")
    for side, directory in (("baseline", baseline_dir), ("patched", patched_dir)):
        provenance = json.loads((directory / "native-provenance.json").read_text())
        module = Path(provenance["module"])
        if digest(module) != provenance["module_sha256"]:
            raise ValueError(f"{side}: scratch module changed after generation")
        bypass = provenance["bypass_provenance"]
        if bypass["module_sha256"] != provenance["module_sha256"]:
            raise ValueError(f"{side}: incorrect bypassed module provenance")
        for original, expected in bypass["protected_original_sha256"].items():
            if digest(Path(original)) != expected:
                raise ValueError(f"{side}: original source/build file changed: {original}")
        qt_lib = Path(provenance["expected_qt_lib"])
        prefix = Path(provenance["expected_qt_prefix"])
        external = {}
        observed = set()
        for entry in provenance["qt_libraries"]:
            path = Path(entry["real_path"])
            match = re.match(r"(?:lib)?Qt6([^.]+)\.", path.name)
            if not match:
                raise ValueError(f"{side}: unrecognized loaded Qt library: {path}")
            family = match[1]
            observed.add(family)
            if digest(path) != entry["sha256"]:
                raise ValueError(f"{side}: loaded Qt library changed: {path}")
            if not path.is_relative_to(prefix):
                if family not in allow_external:
                    raise ValueError(f"{side}: unexpected external Qt library: {path}")
                external[family] = entry
        if not {"Core", "Gui", "Widgets", "PrintSupport"}.issubset(observed):
            raise ValueError(f"{side}: required native Qt modules were not captured")
        active_plugins = []
        qpa = {"cocoa": "qcocoa", "xcb": "qxcb", "windows": "qwindows"}[provenance["qpa_platform"]]
        for entry in provenance["qt_plugins"]:
            path = Path(entry["real_path"])
            if digest(path) != entry["sha256"]:
                raise ValueError(f"{side}: loaded Qt plugin changed: {path}")
            if qpa in path.name and "platforms" in path.parts:
                active_plugins.append(entry)
                if not path.is_relative_to(Path(provenance["expected_plugin_dir"])):
                    raise ValueError(f"{side}: QPA plugin came from another runtime")
            if not path.is_relative_to(prefix):
                if "svg" not in path.name.lower() or "Svg" not in allow_external:
                    raise ValueError(f"{side}: unexpected external Qt plugin: {path}")
                external["plugin:" + path.name] = entry
        if len(active_plugins) != 1:
            raise ValueError(f"{side}: expected exactly one loaded active QPA plugin")
        gui = [
            entry
            for entry in provenance["qt_libraries"]
            if Path(entry["real_path"]).name.lower().startswith(("libqt6gui.", "qt6gui."))
        ]
        if len(gui) != 1 or not Path(gui[0]["real_path"]).is_relative_to(qt_lib):
            raise ValueError(f"{side}: loaded QtGui did not come from the selected runtime")
        if digest(Path(gui[0]["real_path"])) != gui[0]["sha256"]:
            raise ValueError(f"{side}: loaded QtGui changed after generation")
        manifest = json.loads((directory / "manifest.json").read_text())
        launch_record = json.loads((directory / "launch.json").read_text())
        require_prospective = any(
            key in launch_record["environment_overrides"]
            for key in ("TD_NATIVE_MACRO_PATH", "TD_NATIVE_MACRO_SHA256")
        )
        expectations = check_stock_records(
            provenance,
            manifest,
            directory,
            expected_qt_version,
            side=side,
            require_prospective=require_prospective,
        )
        if expectations:
            macro_source = provenance["macro_source"]
            macro = Path(__file__).with_name("native-freecad.FCMacro").resolve()
            if (
                Path(macro_source["path"]).resolve() != macro
                or digest(macro) != macro_source["sha256"]
                or launch_record["command"][-1] != str(macro)
                or launch_record["environment_overrides"]["TD_NATIVE_MACRO_SHA256"]
                != macro_source["sha256"]
                or launch_record["environment_overrides"]["TD_NATIVE_MACRO_PATH"] != str(macro)
            ):
                raise ValueError(f"{side}: prospective source differs from the executed macro")
        sides[side] = {
            "module_sha256": provenance["module_sha256"],
            "qt_gui": gui[0],
            "external_qt_modules": external,
            "active_qpa_plugin": active_plugins[0],
            "pre_export_expectations": expectations,
        }
    if sides["baseline"]["module_sha256"] != sides["patched"]["module_sha256"]:
        raise ValueError("Different FreeCAD module binaries were used on the two sides")
    if sides["baseline"]["qt_gui"]["sha256"] == sides["patched"]["qt_gui"]["sha256"]:
        raise ValueError("QtGui did not change between baseline and patched processes")
    if sides["baseline"]["external_qt_modules"] != sides["patched"]["external_qt_modules"]:
        raise ValueError("External same-version Qt modules/plugins changed between phases")
    if sides["baseline"]["pre_export_expectations"] != sides["patched"]["pre_export_expectations"]:
        raise ValueError("Prospective palette/null-frame inputs changed between Qt runtimes")
    return sides


def check_visible_controls(directory, dpi, pdftoppm, device="qpdfwriter"):
    pixels = {}
    for name in (
        "box-only",
        "short-gap",
        "short-gap-opaque",
        "short-solid",
        "long-dashed",
        "distance",
        "theoretical-exact",
        "zero-width-translucent",
        "zero-width-opaque",
        "zero-width-archival",
    ):
        filename = ("qprinter-" if device == "qprinter" else "") + name + ".pdf"
        _, pixels[name] = rasterize(directory / filename, dpi, pdftoppm)
    if pixels["short-gap"] != pixels["box-only"]:
        raise ValueError(f"{directory}: short gap unexpectedly contributed visible ink")
    if pixels["short-gap-opaque"] != pixels["box-only"]:
        raise ValueError(f"{directory}: opaque short gap unexpectedly contributed visible ink")
    for name in (
        "short-solid",
        "long-dashed",
        "distance",
        "zero-width-translucent",
        "zero-width-opaque",
        "zero-width-archival",
    ):
        if pixels[name] == pixels["box-only"]:
            raise ValueError(f"{directory}: {name} control lost visible ink")
    if pixels["theoretical-exact"] == pixels["distance"]:
        raise ValueError(f"{directory}: theoretical-exact frame lost visible ink")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-dir", type=Path)
    parser.add_argument("--patched-dir", type=Path)
    parser.add_argument("--freecad", type=Path)
    parser.add_argument("--python-runtime", type=Path)
    parser.add_argument("--baseline-python-runtime", type=Path)
    parser.add_argument("--patched-python-runtime", type=Path)
    parser.add_argument("--bypass-module", type=Path)
    parser.add_argument("--baseline-qt-lib", type=Path)
    parser.add_argument("--patched-qt-lib", type=Path)
    parser.add_argument("--baseline-plugin-dir", type=Path)
    parser.add_argument("--patched-plugin-dir", type=Path)
    parser.add_argument("--baseline-qt-prefix", type=Path)
    parser.add_argument("--patched-qt-prefix", type=Path)
    parser.add_argument("--allow-external-qt-module", action="append", default=[])
    parser.add_argument("--expected-qt-version", choices=("6.11.1", "6.11.2"), default="6.11.2")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--pdftoppm", default=shutil.which("pdftoppm"))
    args = parser.parse_args()
    if not args.pdftoppm:
        parser.error("pdftoppm is required")
    generated = not (args.baseline_dir and args.patched_dir)
    if bool(args.baseline_dir) != bool(args.patched_dir):
        parser.error("Provide both --baseline-dir and --patched-dir")
    if generated:
        if not (sys.platform in ("darwin", "win32") or sys.platform.startswith("linux")):
            parser.error("The native generation launcher supports macOS, Linux and Windows")
        for key in (
            "freecad",
            "bypass_module",
            "baseline_qt_lib",
            "patched_qt_lib",
            "output",
        ):
            if getattr(args, key) is None:
                parser.error("Native generation requires --" + key.replace("_", "-"))
        for side in ("baseline", "patched"):
            if getattr(args, side + "_python_runtime") is None and args.python_runtime is None:
                parser.error(
                    "Native generation requires --" + side + "-python-runtime or --python-runtime"
                )
        if args.output.exists() or args.output.is_symlink():
            parser.error("--output must be a new directory to preserve prior evidence")
        if args.report is not None and any(
            args.report.resolve().is_relative_to(args.output.resolve() / side)
            for side in ("baseline", "patched")
        ):
            parser.error("Report must stay outside both generated input evidence directories")
        prefixes = [args.freecad.resolve().parent, args.bypass_module.resolve().parent]
        for side in ("baseline", "patched"):
            qt_lib = getattr(args, side + "_qt_lib").resolve()
            prefixes.extend(
                (
                    (getattr(args, side + "_qt_prefix") or qt_lib.parent).resolve(),
                    (getattr(args, side + "_python_runtime") or args.python_runtime).resolve(),
                )
            )
            plugins = getattr(args, side + "_plugin_dir")
            if plugins is not None:
                prefixes.append(plugins.resolve())
        for destination in (args.output, args.report):
            if destination is not None and any(
                destination.resolve().is_relative_to(prefix) for prefix in prefixes
            ):
                parser.error(
                    "Output and report must be outside the executable and selected runtime prefixes"
                )
        if args.report is not None:
            try:
                bypass = json.loads(
                    (args.bypass_module.resolve().parent / "bypass-provenance.json").read_text()
                )
                protected = {Path(path).resolve() for path in bypass["protected_original_sha256"]}
                if args.report.resolve() in protected:
                    parser.error("Report must not overwrite a protected source/build file")
            except (OSError, ValueError, KeyError) as error:
                parser.error(str(error))
    try:
        baseline_dir = launch(args, "baseline") if generated else args.baseline_dir
        patched_dir = launch(args, "patched") if generated else args.patched_dir
        if args.report is not None:
            try:
                check_report_destination(args.report, (baseline_dir, patched_dir))
            except (OSError, ValueError, KeyError) as error:
                # An unsafe report path must not be used for an error report either.
                parser.error(str(error))
        provenance = check_provenance(
            baseline_dir, patched_dir, args.allow_external_qt_module, args.expected_qt_version
        )
        report = compare(
            baseline_dir, patched_dir, args.pdftoppm, require_device_pixel_parity=False
        )
        report["stock_device_rounding"] = (
            "PagePrinter QPdfWriter computes its target from exact template millimetres; "
            "QPrinter uses QPageLayout.fullRectPixels from rounded page points. "
            "Cross-device pixels can differ; each device must retain exact operators and RGBA."
        )
        report["native_runtime_provenance"] = provenance
        for directory in (baseline_dir, patched_dir):
            for device in ("qpdfwriter", "qprinter"):
                check_visible_controls(directory, report["raster_dpi"], args.pdftoppm, device)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        subprocess.SubprocessError,
    ) as error:
        report = {"passed": False, "failures": [str(error)]}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    for failure in report["failures"]:
        print(failure, file=sys.stderr)
    if report["passed"]:
        print(
            f"PASS: {len(report['cases'])} stock exports, guards bypassed, "
            "loaded QtGui hashes proven, operators and pixels preserved"
        )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
