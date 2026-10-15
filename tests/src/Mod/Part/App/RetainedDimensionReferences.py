# SPDX-License-Identifier: LGPL-2.1-or-later

"""Opt-in FreeCAD-6g7 integration probe; never modifies the retained input.

Run with FreeCADCmd -P tests/src/Mod/Part/App -t RetainedDimensionReferences.
Set FREECAD_6G7_INPUT to the retained EN2 file (or a previous probe's output),
and FREECAD_6G7_OUTPUT to a distinct disposable successor path. Run again in a
fresh process with that successor as input to verify cold restoration.
"""

import hashlib
import os
from pathlib import Path
import unittest

import FreeCAD as App


@unittest.skipUnless(os.environ.get("FREECAD_6G7_INPUT"), "Requires retained EN2 fixture")
class RetainedDimensionReferences(unittest.TestCase):
    def test_physical_points_survive_recompute_and_save(self):
        source = Path(os.environ["FREECAD_6G7_INPUT"]).resolve()
        output = Path(os.environ["FREECAD_6G7_OUTPUT"]).resolve()
        self.assertNotEqual(source, output, "Never overwrite the retained input")
        original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        controls = (
            ("Dimension135", "Window016", (2082, -152.5, 3944), (2860, -112.5, 3940)),
            ("Dimension139", "Window017", (6082, 7352.5, 3944), (6860, 7392.5, 3940)),
        )
        doc = App.openDocument(str(source))
        try:
            for cycle in range(3):
                if cycle:
                    doc.recompute(None, True)
                for name, window_name, start, end in controls:
                    with self.subTest(cycle=cycle, dimension=name):
                        dimension = doc.getObject(name)
                        window = doc.getObject(window_name)
                        self.assertAlmostEqual(abs(dimension.End.x - dimension.Start.x), 778)
                        self.assertLess((dimension.Start - App.Vector(*start)).Length, 1e-7)
                        self.assertLess((dimension.End - App.Vector(*end)).Length, 1e-7)
                        self.assertEqual(len(dimension.LinkedGeometry), 1)
                        owner, subs = dimension.LinkedGeometry[0]
                        self.assertEqual(owner, window)
                        self.assertEqual(len(subs), 2)
                        for sub, point in zip(subs, (start, end)):
                            self.assertLess(
                                (window.Shape.getElement(sub).Point - App.Vector(*point)).Length,
                                1e-7,
                            )
                        print(f"FreeCAD-6g7 cycle={cycle} {name}: 778 mm; points preserved",
                              flush=True)
            doc.saveAs(str(output))
        finally:
            App.closeDocument(doc.Name)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original_hash)
