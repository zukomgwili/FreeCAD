# SPDX-License-Identifier: LGPL-2.1-or-later

"""Native FEM legend export regression; run through FreeCAD -t ColorbarExports.

The command-line wrapper creates private profiles and retains images/logs. This
uses the shipped box FRD and native post view, not a replacement legend renderer.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class TestColorbarExports(unittest.TestCase):
    def test_native_labels_have_contrast_and_fit_after_viewport_changes(self):
        import FreeCAD as App
        import FreeCADGui as Gui
        import Fem

        __import__("FemGui")
        import ObjectsFem
        from PySide.QtGui import QImage
        from vtkmodules import vtkCommonCore, vtkCommonDataModel
        from feminout import importCcxFrdResults

        self.assertTrue(Fem.isVtkCompatible(vtkCommonCore.vtkBitArray()))
        self.assertTrue(Fem.isVtkCompatible(vtkCommonDataModel.vtkUnstructuredGrid()))
        self.assertEqual(Fem.getVtkVersion(), vtkCommonCore.vtkVersion.GetVTKVersion())
        output = Path(os.environ["FREECAD_COLORBAR_OUTPUT"])
        fixture = (
            Path(__file__).resolve().parents[3] / "src/Mod/Fem/femtest/data/calculix/box_static.frd"
        )
        prefs = App.ParamGet("User parameter:BaseApp/Preferences/View")
        cube = prefs.GetBool("ShowNaviCube", True)
        prefs.SetBool("ShowNaviCube", False)
        doc = App.newDocument("ColorbarExports")
        try:
            analysis = ObjectsFem.makeAnalysis(doc)
            importCcxFrdResults.importFrd(str(fixture), analysis)
            pipeline = next(obj for obj in doc.Objects if obj.TypeId == "Fem::FemPostPipeline")
            for obj in doc.Objects:
                obj.ViewObject.Visibility = obj == pipeline
            field = "Displacement Magnitude"
            pipeline.ViewObject.Field = field
            pipeline.ViewObject.Component = "Not a vector"
            pipeline.ViewObject.DisplayMode = "Surface with Edges"
            doc.recompute()
            view = Gui.activeDocument().activeView()
            view.setAnimationEnabled(False)
            view.viewAxonometric()
            view.fitAll()
            Gui.updateGui()
            view.redraw()
            data = pipeline.getDataSet()
            self.assertIsNotNone(data)
            arrays = data.GetPointData()
            report = {
                "version": list(App.Version()),
                "field": field,
                "unit": "mm",
                "fixture_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
                "captures": [],
            }
            report["native_array_ranges"] = {
                arrays.GetArray(index).GetName(): list(arrays.GetArray(index).GetRange())
                for index in range(arrays.GetNumberOfArrays())
            }
            sizes = ((1280, 900), (320, 240), (640, 480), (480, 640), (1280, 900))
            for index, (width, height) in enumerate(sizes):
                for background in ("White", "Black", "Current"):
                    with self.subTest(size=(width, height), background=background, index=index):
                        path = output / f"{index}-{width}x{height}-{background}.png"
                        view.saveImage(str(path), width, height, background)
                        image = QImage(str(path))
                        self.assertEqual((image.width(), image.height()), (width, height))
                        y = height // 2
                        green = [
                            x
                            for x in range(width // 2, width)
                            if image.pixelColor(x, y).green() > 180
                            and image.pixelColor(x, y).red() < 180
                            and image.pixelColor(x, y).blue() < 80
                        ]
                        self.assertTrue(green, "Native green color-scale interval missing")
                        right = max(green)
                        self.assertLess(right, width - 10)
                        ink = 0
                        for y in range(height // 5, int(height * 0.87)):
                            for x in range(right + 2, width):
                                color = image.pixelColor(x, y)
                                rgb = color.red(), color.green(), color.blue()
                                if max(rgb) - min(rgb) < 8 and (
                                    (background == "White" and min(rgb) < 120)
                                    or (background == "Black" and max(rgb) > 150)
                                    or (
                                        background == "Current"
                                        and (min(rgb) < 50 or max(rgb) > 210)
                                    )
                                ):
                                    ink += 1
                            # The final two columns must remain background: a
                            # cropped final digit or halo reaches this boundary.
                            left = image.pixelColor(0, y)
                            for x in (width - 2, width - 1):
                                edge = image.pixelColor(x, y)
                                self.assertLessEqual(
                                    max(
                                        abs(a - b)
                                        for a, b in zip(
                                            (edge.red(), edge.green(), edge.blue()),
                                            (left.red(), left.green(), left.blue()),
                                        )
                                    ),
                                    8,
                                )
                        self.assertGreater(ink, 25, "Numeric legend has no contrasting text")
                        report["captures"].append(
                            {"image": str(path), "text_pixels": ink, "bar_right": right}
                        )
            (output / "verified.json").write_text(json.dumps(report, indent=2))
        finally:
            App.closeDocument(doc.Name)
            prefs.SetBool("ShowNaviCube", cube)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    root = Path(args.output_root)
    root.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="native-colorbar-", dir=root))
    env = os.environ.copy()
    env.update(
        FREECAD_USER_HOME=str(output / "data"),
        FREECAD_USER_DATA=str(output / "data"),
        FREECAD_USER_TEMP=str(output / "temp"),
        FREECAD_COLORBAR_OUTPUT=str(output),
        PYTHONDONTWRITEBYTECODE="1",
    )
    command = [
        args.executable,
        "-u",
        str(output / "user.cfg"),
        "-s",
        str(output / "system.cfg"),
        "-P",
        str(Path(__file__).resolve().parent),
        "-t",
        "ColorbarExports",
    ]
    result = subprocess.run(
        command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120
    )
    (output / "run.log").write_bytes(result.stdout)
    print(result.stdout.decode("utf-8", "replace"))
    print(f"Native colorbar evidence: {output}")
    return result.returncode or (0 if (output / "verified.json").is_file() else 1)


if __name__ == "__main__":
    raise SystemExit(main())
