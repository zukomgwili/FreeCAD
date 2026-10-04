# SPDX-License-Identifier: LGPL-2.1-or-later
"""Qualify an actual Qt PDF stroker patch against its unmodified baseline.

Requires pypdf, Pillow and Poppler's pdftoppm. Generate PDFs separately using
qt_pdf_stroker_fixture --output DIR, then pass --baseline-dir and --patched-dir.
Alternatively pass --baseline-executable, --patched-executable and --output DIR.
Library/plugin environment variables are inherited when generating each side;
use pre-generated directories when the same executable loads different libraries.

A successful comparison requires a reproduced baseline defect, no malformed
patched path operators or Poppler diagnostics, identical coordinate operators
and all other page operators, and byte-identical RGBA pixels. Only the baseline's
invalid, coordinate-free h/f pairs are removed for the operator comparison.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from PIL import Image
from pypdf import PdfReader
from pypdf.generic import ContentStream, IndirectObject

COORDINATE_OPERATORS = {b"m", b"l", b"c", b"v", b"y", b"re"}
END_PATH_OPERATORS = {b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*", b"n"}
WARNING = "No current point in closepath"


def stable_operand(value):
    """Compare parsed PDF operands without reader identity or binary dumps."""
    if isinstance(value, IndirectObject):
        return ("reference", value.idnum, value.generation)
    if isinstance(value, dict):
        return tuple(sorted((str(key), stable_operand(item)) for key, item in value.items()))
    if isinstance(value, (tuple, list)):
        return tuple(stable_operand(item) for item in value)
    if isinstance(value, bytes):
        return ("bytes", hashlib.sha256(value).hexdigest())
    return str(value)


def inspect_operators(pdf):
    reader = PdfReader(pdf, strict=True)
    if len(reader.pages) != 1:
        raise ValueError(f"{pdf}: expected one PDF page")
    contents = ContentStream(reader.pages[0].get_contents(), reader)
    operations = contents.operations
    current_point = False
    invalid_closes = []
    errors = []
    omit = set()
    for index, (operands, operator) in enumerate(operations):
        if operator in {b"m", b"re"}:
            current_point = True
        elif operator in {b"l", b"c", b"v", b"y"}:
            if not current_point:
                errors.append(f"operator {index}: {operator.decode()} has no current point")
        elif operator == b"h" and not current_point:
            invalid_closes.append(index)
            # The proposed correction removes precisely this terminal pair.
            if not operands and index + 1 < len(operations) and operations[index + 1] == ([], b"f"):
                omit.update((index, index + 1))
            else:
                errors.append(f"operator {index}: invalid close is not a bare h/f pair")
        elif operator in END_PATH_OPERATORS:
            current_point = False
        # q/Q save graphics state, not the current path. W/W* consume it only
        # when followed by an end-path operator such as n.
    normalized = [
        (operator.decode("latin1"), stable_operand(operands))
        for index, (operands, operator) in enumerate(operations)
        if index not in omit
    ]
    coordinates = [
        (operator.decode("ascii"), stable_operand(operands))
        for operands, operator in operations
        if operator in COORDINATE_OPERATORS
    ]
    return (
        {
            "invalid_close_count": len(invalid_closes),
            "invalid_close_indices": invalid_closes,
            "path_errors": errors,
            "operation_count": len(operations),
            "coordinate_count": len(coordinates),
        },
        normalized,
        coordinates,
    )


def rasterize(pdf, dpi, pdftoppm):
    prefix = pdf.with_suffix("")
    render = subprocess.run(
        [pdftoppm, "-r", str(dpi), "-singlefile", "-png", str(pdf), str(prefix)],
        capture_output=True,
        text=True,
        check=False,
    )
    png = prefix.with_suffix(".png")
    if render.returncode or not png.is_file():
        raise ValueError(f"{pdf}: Poppler failed ({render.returncode}): {render.stderr}")
    with Image.open(png) as image:
        rgba = image.convert("RGBA")
        pixels = rgba.tobytes()
        ink = red = blue = 0
        for r, g, b in zip(pixels[0::4], pixels[1::4], pixels[2::4]):
            ink += (r, g, b) != (255, 255, 255)
            red += r > g and r > b
            blue += b > r and b > g
        result = {
            "size": list(rgba.size),
            "rgba_sha256": hashlib.sha256(pixels).hexdigest(),
            "ink_pixels": ink,
            "red_pixels": red,
            "blue_pixels": blue,
            "poppler_status": render.returncode,
            "poppler_stderr": render.stderr,
            "closepath_warnings": render.stderr.count(WARNING),
        }
    return result, pixels


def load_manifest(directory):
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest.get("schema_version") != 1:
        raise ValueError(f"{directory}: unsupported manifest schema")
    cases = manifest["cases"]
    if not cases or len({case["name"] for case in cases}) != len(cases):
        raise ValueError(f"{directory}: missing or duplicated cases")
    for case in cases:
        if Path(case["pdf"]).name != case["pdf"]:
            raise ValueError(f"{directory}: expected a PDF filename, got {case['pdf']}")
    return manifest


def generate(executable, directory):
    subprocess.run([str(executable.resolve()), "--output", str(directory.resolve())], check=True)
    return directory


def compare(baseline_dir, patched_dir, pdftoppm):
    baseline = load_manifest(baseline_dir)
    patched = load_manifest(patched_dir)
    if baseline != patched:
        raise ValueError(
            "Baseline and patched manifests differ; compare the same Qt version and cases"
        )
    report = {
        "qt_version": baseline["qt_version"],
        "raster_dpi": baseline["raster_dpi"],
        "baseline_dir": str(baseline_dir.resolve()),
        "patched_dir": str(patched_dir.resolve()),
        "cases": [],
        "failures": [],
    }
    reproduced = 0
    for case in baseline["cases"]:
        name = case["name"]
        failures = []
        sides = {}
        normalized = {}
        coordinates = {}
        pixels = {}
        for side, directory in (("baseline", baseline_dir), ("patched", patched_dir)):
            pdf = directory / case["pdf"]
            operator_info, normalized[side], coordinates[side] = inspect_operators(pdf)
            raster_info, pixels[side] = rasterize(pdf, baseline["raster_dpi"], pdftoppm)
            sides[side] = {**operator_info, **raster_info}
            if operator_info["path_errors"]:
                failures.append(f"{side}: {operator_info['path_errors']}")
            expected_closes = case["baseline_invalid_closes"] if side == "baseline" else 0
            if operator_info["invalid_close_count"] != expected_closes:
                failures.append(
                    f"{side}: expected {expected_closes} invalid closes, "
                    f"got {operator_info['invalid_close_count']}"
                )
            if raster_info["closepath_warnings"] != expected_closes:
                failures.append(
                    f"{side}: expected {expected_closes} Poppler closepath warnings, "
                    f"got {raster_info['closepath_warnings']}"
                )
            other_diagnostics = [
                line for line in raster_info["poppler_stderr"].splitlines() if WARNING not in line
            ]
            if other_diagnostics:
                failures.append(f"{side}: unexpected Poppler diagnostics: {other_diagnostics}")
            if bool(raster_info["ink_pixels"]) != case["expect_ink"]:
                failures.append(
                    f"{side}: expected ink={case['expect_ink']}, "
                    f"got {raster_info['ink_pixels']} ink pixels"
                )
            color = case["expected_color"]
            if color and not raster_info[f"{color}_pixels"]:
                failures.append(f"{side}: expected visible {color} ink")
        if sides["baseline"]["invalid_close_count"] and sides["baseline"]["closepath_warnings"]:
            reproduced += 1
        same_coordinates = coordinates["baseline"] == coordinates["patched"]
        same_operations = normalized["baseline"] == normalized["patched"]
        same_pixels = (
            sides["baseline"]["size"] == sides["patched"]["size"]
            and pixels["baseline"] == pixels["patched"]
        )
        if not same_coordinates:
            failures.append("coordinate-bearing PDF operators changed")
        if not same_operations:
            failures.append("PDF operators changed beyond invalid h/f removal")
        if not same_pixels:
            failures.append("rendered RGBA pixels changed")
        report["cases"].append(
            {
                "name": name,
                **sides,
                "same_coordinates": same_coordinates,
                "same_normalized_operations": same_operations,
                "same_pixels": same_pixels,
                "failures": failures,
            }
        )
        report["failures"].extend(f"{name}: {failure}" for failure in failures)
    if not reproduced:
        report["failures"].append(
            "No baseline case reproduced both invalid close and Poppler warning"
        )
    report["baseline_reproduced_cases"] = reproduced
    report["passed"] = not report["failures"]
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for side in ("baseline", "patched"):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(f"--{side}-dir", type=Path)
        group.add_argument(f"--{side}-executable", type=Path)
    parser.add_argument("--output", type=Path, help="Generated PDF parent directory")
    parser.add_argument("--report", type=Path, help="Write the detailed JSON report")
    parser.add_argument("--pdftoppm", default=shutil.which("pdftoppm"))
    args = parser.parse_args()
    if not args.pdftoppm:
        parser.error("pdftoppm is required")
    directories = {}
    for side in ("baseline", "patched"):
        executable = getattr(args, f"{side}_executable")
        directory = getattr(args, f"{side}_dir")
        if executable:
            if not args.output:
                parser.error("--output is required when generating PDFs")
            directory = generate(executable, args.output / side)
        directories[side] = directory
    try:
        report = compare(directories["baseline"], directories["patched"], args.pdftoppm)
    except (OSError, ValueError, KeyError) as error:
        report = {"passed": False, "failures": [str(error)]}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    for failure in report["failures"]:
        print(failure, file=sys.stderr)
    if report["passed"]:
        print(
            f"PASS: {len(report['cases'])} cases; "
            f"{report['baseline_reproduced_cases']} baseline defects; "
            "all patched paths valid, Poppler clean, operators and RGBA pixels preserved"
        )
    else:
        print(f"FAIL: {len(report['failures'])} qualification failure(s)", file=sys.stderr)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
