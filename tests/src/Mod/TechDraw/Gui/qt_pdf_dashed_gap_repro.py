# SPDX-License-Identifier: LGPL-2.1-or-later
"""Standalone Qt PDF diagnostic; exits 1 if Poppler finds an invalid closepath.

Requires PySide6 and pdftoppm. The default nonempty line lies entirely inside a
dash gap. Example: python qt_pdf_dashed_gap_repro.py --case gap
Controls: --case visible-dash, solid, offset-zero, round-cap, or square-cap.
Native-route controls: opaque-native-clamp and archival-native-clamp.
Output files are retained in a temporary directory, or at --output PATH.
This script neither imports FreeCAD nor modifies the generated PDF.

A FreeCAD no-ink preflight must exclude opaque pens and PDF/A-1b: their native
PDF route clamps zero-length dashes into visible strokes. Cosmetic pens use
transformed coordinates; zero/tiny widths receive PDF-specific substitutions.
Opaque backgrounds can carry visible ink, and projective transforms use emulation.
"""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zlib

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt, qVersion
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QImage,
    QPagedPaintDevice,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPdfWriter,
    QPen,
)

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--case",
    choices=[
        "gap",
        "visible-dash",
        "solid",
        "offset-zero",
        "round-cap",
        "square-cap",
        "opaque-native-clamp",
        "archival-native-clamp",
    ],
    default="gap",
)
parser.add_argument("--output", type=Path)
args = parser.parse_args()
pdftoppm = shutil.which("pdftoppm")
if not pdftoppm:
    parser.error("pdftoppm is required to check the PDF syntax warning")
pdf = args.output or Path(tempfile.mkdtemp(prefix="qt-pdf-dash-gap-")) / "output.pdf"
app = QGuiApplication([])

native_clamp = args.case in ["opaque-native-clamp", "archival-native-clamp"]
start = 0 if native_clamp else 100
path = QPainterPath()
path.moveTo(start, start)
path.lineTo(start + (10 if args.case == "visible-dash" else 0.01), start)
assert not path.isEmpty()
pen = QPen(QColor(0, 0, 0, 255 if args.case == "opaque-native-clamp" else 128))
pen.setWidthF(2)
pen.setCosmetic(False)
pen.setCapStyle({"round-cap": Qt.RoundCap, "square-cap": Qt.SquareCap}.get(args.case, Qt.FlatCap))
if args.case != "solid":
    pen.setDashPattern([0, 5] if native_clamp else [1, 5])
    pen.setDashOffset(0 if native_clamp or args.case == "offset-zero" else 2)
stroke = QPainterPathStroker(pen).createStroke(path)

writer = QPdfWriter(str(pdf))
if args.case == "archival-native-clamp":
    writer.setPdfVersion(QPagedPaintDevice.PdfVersion_A1b)
painter = QPainter(writer)
if native_clamp:
    painter.scale(100000, 100000)
painter.setPen(pen)
painter.setBrush(Qt.NoBrush)
painter.drawPath(path)
assert painter.end()

contents = []
for match in re.finditer(rb"<<(.*?)>>\s*stream\r?\n(.*?)\r?\nendstream", pdf.read_bytes(), re.S):
    if b"/Subtype /XML" in match.group(1):
        continue
    data = match.group(2)
    data = zlib.decompress(data) if b"FlateDecode" in match.group(1) else data
    # This Qt-only fixture has one page; PDF/A also embeds a binary ICC profile.
    if b"/GSa gs" in data:
        contents.append(data)
assert len(contents) == 1, "Expected one Qt PDF page content stream"
contents = b"\n".join(contents)
pdf.with_suffix(".contents.txt").write_bytes(contents)
current_point = False
empty_closes = 0
for token in contents.split():
    if token in [b"m", b"l", b"c", b"v", b"y", b"re"]:
        current_point = True
    elif token == b"h" and not current_point:
        empty_closes += 1
    elif token in [b"n", b"f", b"f*", b"S", b"s", b"B", b"B*", b"b", b"b*"]:
        current_point = False
render = subprocess.run(
    [
        pdftoppm,
        "-r",
        "100" if native_clamp else "12",
        "-singlefile",
        "-png",
        str(pdf),
        str(pdf.with_suffix("")),
    ],
    capture_output=True,
    text=True,
)
report = {
    "qt": qVersion(),
    "case": args.case,
    "path_empty": path.isEmpty(),
    "stroke_empty": stroke.isEmpty(),
    "empty_closepaths": empty_closes,
    "poppler_status": render.returncode,
    "poppler_stderr": render.stderr,
    "pdf": str(pdf),
}
if native_clamp:
    image = QImage(str(pdf.with_suffix(".png"))).convertToFormat(QImage.Format_RGBA8888)
    assert not image.isNull()
    report["ink_pixels"] = sum(red < 250 for red in bytes(image.constBits())[::4])
print(json.dumps(report, indent=2))
assert render.returncode == 0, render.stderr
assert empty_closes == 0, "PDF closes a path without a current point"
assert "No current point in closepath" not in render.stderr, render.stderr
if native_clamp:
    assert stroke.isEmpty() and report["ink_pixels"] > 0, report
