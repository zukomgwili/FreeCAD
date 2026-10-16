# SPDX-License-Identifier: LGPL-2.1-or-later

"""Native fresh-process persistence probe, without any building document.

Set FREECAD_N1H_OUTPUT to a new output directory. Set FREECAD_N1H_REOPEN to
the preceding native-material.FCStd for a second independent process.
"""

import json
import os
from pathlib import Path
import unittest

import FreeCAD as App
import ObjectsFem

from femtools.material_orthotropic import engineering_constants
from femtools.material_orthotropic import material_rotation


@unittest.skipUnless(App.GuiUp, "Requires native GUI to preserve view providers")
class OrthotropicRoundtrip(unittest.TestCase):
    def test_fresh_process_material_axes(self):
        root = Path(os.environ["FREECAD_N1H_OUTPUT"])
        root.mkdir(parents=True, exist_ok=False)
        reopen = os.environ.get("FREECAD_N1H_REOPEN")
        doc = App.openDocument(reopen) if reopen else App.newDocument("OrthotropicNative")
        try:
            if not reopen:
                material = ObjectsFem.makeMaterialSolid(doc, "Material")
                material.Material = {"Name": "Synthetic software test, not timber design data"}
                material.ElasticityModel = "Orthotropic"
                for name, value in zip(
                    ("YoungsModulus1", "YoungsModulus2", "YoungsModulus3",
                     "ShearModulus12", "ShearModulus13", "ShearModulus23"),
                    (12000, 3000, 1500, 700, 500, 300),
                ):
                    setattr(material, name, f"{value} MPa")
                parent = doc.addObject("App::Part", "Parent")
                parent.Placement.Rotation = App.Rotation(App.Vector(0, 0, 1), 30)
                source = doc.addObject("Part::Feature", "Source")
                occurrence = doc.addObject("App::Link", "Occurrence")
                occurrence.setLink(source)
                parent.addObject(occurrence)
                occurrence.Placement.Rotation = App.Rotation(App.Vector(0, 0, 1), 60)
                material.MaterialOrientationReference = occurrence
            material = doc.Material
            self.assertEqual(material.ElasticityModel, "Orthotropic")
            self.assertEqual(engineering_constants(material),
                             (12000, 3000, 1500, 0, 0, 0, 700, 500, 300))
            self.assertEqual(material.MaterialOrientationReference.Name, "Occurrence")
            self.assertLess((material_rotation(material).multVec(App.Vector(1, 0, 0))
                             - App.Vector(0, 1, 0)).Length, 1e-12)
            if reopen:
                doc.Parent.Placement.Rotation = App.Rotation(App.Vector(0, 0, 1), 60)
                doc.recompute()
                expected = App.Rotation(App.Vector(0, 0, 1), 120).multVec(App.Vector(1, 0, 0))
                self.assertLess((material_rotation(material).multVec(App.Vector(1, 0, 0))
                                 - expected).Length, 1e-12)
            doc.recompute()
            doc.saveAs(str(root / "native-material.FCStd"))
            (root / "report.json").write_text(json.dumps({
                "runtime": App.Version(), "gui_up": App.GuiUp,
                "fresh_process_reopen": bool(reopen),
                "engineering_constants_MPa": engineering_constants(material),
                "global_material_axis_1": list(
                    material_rotation(material).multVec(App.Vector(1, 0, 0))),
                "building_design_accepted": False,
            }, indent=2))
        finally:
            App.closeDocument(doc.Name)
