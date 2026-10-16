# SPDX-License-Identifier: LGPL-2.1-or-later

"""Opt-in native GUI regression: FreeCAD -P tests/src/Mod/Fem -t OrthotropicMaterialGui."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide import QtGui

import FreeCAD as App
import FreeCADGui as Gui
import ObjectsFem

from femtaskpanels.task_material_common import _TaskPanel
from femtools.material_orthotropic import engineering_constants
from femtools.material_orthotropic import material_rotation


@unittest.skipUnless(App.GuiUp, "Requires native FreeCAD GUI")
class OrthotropicMaterialGui(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("OrthotropicGuiQA")
        self.material = ObjectsFem.makeMaterialSolid(self.doc)
        self.material.Material = {"Name": "GUI QA", "YoungsModulus": "210000 MPa",
                                  "PoissonRatio": "0.3"}
        self.doc.openTransaction("Edit material")
        self.panel = _TaskPanel(self.material)

    def tearDown(self):
        Gui.Control.closeDialog()
        App.closeDocument(self.doc.Name)

    def configure(self):
        self.panel.elasticityModel.setCurrentIndex(1)
        for name, value in (
            ("YoungsModulus1", 12000), ("YoungsModulus2", 3000), ("YoungsModulus3", 1500),
            ("ShearModulus12", 700), ("ShearModulus13", 500), ("ShearModulus23", 300),
        ):
            self.panel.orthotropicFields[name].setValue(value)
        self.panel.orientationAxis[0].setValue(0)
        self.panel.orientationAxis[1].setValue(0)
        self.panel.orientationAxis[2].setValue(1)
        self.panel.orientationAngle.setValue(90)

    def reopen_panel(self):
        self.panel.selectionWidget.finish_selection()
        self.panel = _TaskPanel(self.material)

    def set_native_constants(self):
        for name, value in (
            ("YoungsModulus1", 12000.123456789012),
            ("YoungsModulus2", 3000.987654321012),
            ("YoungsModulus3", 1500.135791357913),
            ("ShearModulus12", 700.246802468024),
            ("ShearModulus13", 500.369123691236),
            ("ShearModulus23", 300.579135791357),
        ):
            setattr(self.material, name, App.Units.Quantity(f"{value:.17g} MPa"))
        for name, value in (
            ("PoissonRatio12", 0.123456789012345),
            ("PoissonRatio13", 0.234567890123456),
            ("PoissonRatio23", 0.078901234567890),
        ):
            setattr(self.material, name, value)
        self.material.ElasticityModel = "Orthotropic"

    def test_accept_save_cold_reopen_and_native_widget(self):
        self.configure()
        self.assertEqual(self.material.ElasticityModel, "Isotropic")
        self.assertFalse(self.panel.parameterWidget.qsb_young_modulus.isEnabled())
        Gui.Control.showDialog(self.panel)
        Gui.updateGui()
        output = os.environ.get("FREECAD_N1H_OUTPUT")
        if output:
            Path(output).mkdir(parents=True, exist_ok=True)
            form = self.panel.form[1]
            self.assertTrue(form.grab().save(str(Path(output) / "orthotropic-form.png")))
        self.assertTrue(self.panel.accept())
        self.assertEqual(engineering_constants(self.material),
                         (12000, 3000, 1500, 0, 0, 0, 700, 500, 300))
        self.assertLess((material_rotation(self.material).multVec(App.Vector(1, 0, 0))
                         - App.Vector(0, 1, 0)).Length, 1e-12)
        with tempfile.TemporaryDirectory() as directory:
            name = self.material.Name
            path = str(Path(directory) / "native.FCStd")
            self.doc.saveAs(path)
            Gui.Control.closeDialog()
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(path)
            self.material = self.doc.getObject(name)
            self.assertEqual(self.material.ElasticityModel, "Orthotropic")
            self.assertEqual(engineering_constants(self.material),
                             (12000, 3000, 1500, 0, 0, 0, 700, 500, 300))

    def test_reject_preserves_native_material(self):
        self.configure()
        self.assertTrue(self.panel.reject())
        self.assertEqual(self.material.ElasticityModel, "Isotropic")
        self.assertEqual(self.material.YoungsModulus1.getValueAs("MPa").Value, 0)

    def test_invalid_data_keeps_edit_open_and_preserves_material(self):
        self.panel.elasticityModel.setCurrentIndex(1)
        with patch.object(QtGui.QMessageBox, "warning") as warning:
            self.assertFalse(self.panel.accept())
            warning.assert_called_once()
        self.assertEqual(self.material.ElasticityModel, "Isotropic")

    def test_fluid_has_no_elasticity_page(self):
        self.material = ObjectsFem.makeMaterialFluid(self.doc)
        self.material.Material = {
            "Name": "GUI fluid QA",
            "Density": "1000 kg/m^3",
            "KinematicViscosity": "1e-6 m^2/s",
        }
        self.reopen_panel()
        self.assertEqual(self.material.Category, "Fluid")
        self.assertEqual(len(self.panel.form), 2)
        self.assertFalse(hasattr(self.panel, "elasticityModel"))
        self.assertFalse(hasattr(self.panel, "orthotropicFields"))
        self.assertTrue(self.panel.parameterWidget.groupBox_mechanical.isHidden())
        self.assertTrue(self.panel.accept())
        self.assertEqual(self.material.Category, "Fluid")

    def test_unchanged_accept_preserves_full_native_precision(self):
        self.set_native_constants()
        self.material.MaterialOrientation = App.Rotation(
            App.Vector(0.123456789012345, 0.345678901234567, 0.567890123456789),
            12.123456789012345,
        )
        expected_constants = engineering_constants(self.material)
        expected_rotation = self.material.MaterialOrientation.Q
        self.reopen_panel()
        # The controls intentionally show fewer decimals than native properties store.
        self.assertNotEqual(
            self.panel.orthotropicFields["PoissonRatio12"].value(),
            self.material.PoissonRatio12,
        )
        self.assertTrue(self.panel.accept())
        self.assertEqual(engineering_constants(self.material), expected_constants)
        self.assertEqual(self.material.MaterialOrientation.Q, expected_rotation)

    def test_card_and_edit_toggle_preserve_directional_properties_and_controls(self):
        self.set_native_constants()
        expected_constants = engineering_constants(self.material)
        self.reopen_panel()
        self.panel.orthotropicFields["YoungsModulus1"].setValue(12555)
        expected_controls = {
            name: field.value() for name, field in self.panel.orthotropicFields.items()
        }
        # This is the shipped standard steel card also used by Material's own tests.
        steel_uuid = "92589471-a6cb-4bbc-b748-d425a17dea7d"
        self.panel.material_tree.UUID = steel_uuid
        self.panel.set_from_editor(steel_uuid)
        self.assertEqual(self.panel.uuid, steel_uuid)
        for editable in (True, False):
            self.panel.parameterWidget.chbu_allow_edit.setChecked(editable)
            self.panel.toggleInputFieldsReadOnly()
            self.assertEqual(engineering_constants(self.material), expected_constants)
            self.assertEqual(
                {name: field.value() for name, field in self.panel.orthotropicFields.items()},
                expected_controls,
            )
            self.assertFalse(self.panel.parameterWidget.qsb_young_modulus.isEnabled())
            self.assertFalse(self.panel.parameterWidget.qsb_poisson_ratio.isEnabled())
        self.assertTrue(self.panel.accept())
        self.assertEqual(self.material.YoungsModulus1.getValueAs("MPa").Value, 12555)
        self.assertEqual(engineering_constants(self.material)[1:], expected_constants[1:])

    def test_zero_axis_nonzero_angle_keeps_edit_open(self):
        self.configure()
        for field in self.panel.orientationAxis:
            field.setValue(0)
        with patch.object(QtGui.QMessageBox, "warning") as warning:
            self.assertFalse(self.panel.accept())
            warning.assert_called_once()
        self.assertEqual(self.material.ElasticityModel, "Isotropic")
        self.assertEqual(self.material.YoungsModulus1.getValueAs("MPa").Value, 0)
        self.panel.orientationAxis[2].setValue(1)
        self.assertTrue(self.panel.accept())
        self.assertEqual(self.material.ElasticityModel, "Orthotropic")

    def test_selected_placed_reference_persists_and_follows_parent_rotation(self):
        parent = self.doc.addObject("App::Part", "ReferenceParent")
        parent.Placement = App.Placement(
            App.Vector(10, 20, 30), App.Rotation(App.Vector(0, 0, 1), 30)
        )
        reference = self.doc.addObject("App::Part", "MaterialAxesReference")
        parent.addObject(reference)
        reference.Placement = App.Placement(
            App.Vector(2, 4, 6), App.Rotation(App.Vector(1, 0, 0), 45)
        )
        self.doc.recompute()
        self.reopen_panel()
        self.configure()
        self.panel.orientationAxis[1].setValue(1)
        self.panel.orientationAxis[2].setValue(0)
        self.panel.orientationAngle.setValue(20)
        self.panel.orientationReference.setCurrentIndex(
            self.panel._orientation_references.index(reference)
        )
        self.assertIsNone(self.material.MaterialOrientationReference)
        self.assertTrue(self.panel.accept())
        self.assertEqual(self.material.MaterialOrientationReference, reference)
        local_rotation = App.Rotation(App.Vector(0, 1, 0), 20)
        expected = reference.getGlobalPlacement().Rotation * local_rotation
        for axis in (App.Vector(1, 0, 0), App.Vector(0, 1, 0), App.Vector(0, 0, 1)):
            self.assertLess(
                (material_rotation(self.material).multVec(axis) - expected.multVec(axis)).Length,
                1e-12,
            )
        with tempfile.TemporaryDirectory() as directory:
            material_name = self.material.Name
            reference_name = reference.Name
            parent_name = parent.Name
            path = str(Path(directory) / "reference.FCStd")
            self.doc.saveAs(path)
            Gui.Control.closeDialog()
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(path)
            self.material = self.doc.getObject(material_name)
            reference = self.doc.getObject(reference_name)
            self.assertEqual(self.material.MaterialOrientationReference, reference)
            self.assertLess(
                (material_rotation(self.material).multVec(App.Vector(1, 0, 0))
                 - expected.multVec(App.Vector(1, 0, 0))).Length,
                1e-12,
            )
            parent = self.doc.getObject(parent_name)
            parent.Placement = App.Placement(
                App.Vector(100, 200, 300), App.Rotation(App.Vector(0, 0, 1), 60)
            )
            self.doc.recompute()
            updated_expected = reference.getGlobalPlacement().Rotation * local_rotation
            actual = material_rotation(self.material).multVec(App.Vector(1, 0, 0))
            self.assertLess(
                (actual - updated_expected.multVec(App.Vector(1, 0, 0))).Length, 1e-12
            )
            self.assertGreater((actual - expected.multVec(App.Vector(1, 0, 0))).Length, 0.1)
