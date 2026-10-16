# SPDX-License-Identifier: LGPL-2.1-or-later

"""Native thermal field regression: FreeCAD -P tests/src/Mod/Fem -t MaterialThermalGui."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import FreeCAD as App
import FreeCADGui as Gui
import ObjectsFem
from femtaskpanels.task_material_common import _TaskPanel


@unittest.skipUnless(App.GuiUp, "Requires native GUI")
class MaterialThermalGui(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("ThermalMaterialGui")
        self.material = ObjectsFem.makeMaterialSolid(self.doc)
        self.material.Material = {
            "Name": "Thermal test", "YoungsModulus": "210000 MPa", "PoissonRatio": "0.3",
            "Density": "7800 kg/m^3", "ThermalExpansionCoefficient": "12 um/m/K",
            "ThermalExpansionReferenceTemperature": "293.15 K",
        }
        self.doc.openTransaction("Edit thermal material")
        self.panel = _TaskPanel(self.material)
        self.panel.parameterWidget.chbu_allow_edit.setChecked(True)
        self.panel.toggleInputFieldsReadOnly()

    def tearDown(self):
        self.panel.selectionWidget.finish_selection()
        Gui.Control.closeDialog()
        App.closeDocument(self.doc.Name)

    def edit(self, name, value):
        control = getattr(self.panel.parameterWidget, name)
        control.setProperty("value", App.Units.Quantity(value))
        control.editingFinished.emit()

    def assert_value(self, values, key, expected):
        self.assertAlmostEqual(App.Units.Quantity(values[key]).Value, expected, places=12)

    def test_coefficient_signal_accept_and_saved_material(self):
        self.edit("qsb_expansion_coefficient", "25 um/m/K")
        self.assert_value(self.panel.material, "ThermalExpansionCoefficient", 25e-6)
        self.assert_value(self.panel.material, "ThermalExpansionReferenceTemperature", 293.15)
        self.assertTrue(self.panel.accept())
        with TemporaryDirectory() as directory:
            path = str(Path(directory) / "thermal.FCStd")
            name = self.material.Name
            self.doc.saveAs(path)
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(path)
            self.material = self.doc.getObject(name)
            self.assert_value(self.material.Material, "ThermalExpansionCoefficient", 25e-6)
            self.assert_value(
                self.material.Material, "ThermalExpansionReferenceTemperature", 293.15
            )

    def test_reference_signal_does_not_update_coefficient(self):
        self.edit("qsb_expansion_reference_temperature", "310 K")
        self.assert_value(self.panel.material, "ThermalExpansionCoefficient", 12e-6)
        self.assert_value(self.panel.material, "ThermalExpansionReferenceTemperature", 310)
        self.assertTrue(self.panel.accept())
        self.assert_value(self.material.Material, "ThermalExpansionReferenceTemperature", 310)

    def test_reject_discards_both_fields(self):
        self.edit("qsb_expansion_coefficient", "25 um/m/K")
        self.edit("qsb_expansion_reference_temperature", "310 K")
        self.assertTrue(self.panel.reject())
        self.assert_value(self.material.Material, "ThermalExpansionCoefficient", 12e-6)
        self.assert_value(self.material.Material, "ThermalExpansionReferenceTemperature", 293.15)
