# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *   Copyright (c) 2013 Juergen Riegel <FreeCAD@juergen-riegel.net>        *
# *   Copyright (c) 2016 Bernd Hahnebach <bernd@bimstatik.org>              *
# *                                                                         *
# *   This file is part of the FreeCAD CAx development system.              *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# *                                                                         *
# *   This program is distributed in the hope that it will be useful,       *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
# *   GNU Library General Public License for more details.                  *
# *                                                                         *
# *   You should have received a copy of the GNU Library General Public     *
# *   License along with this program; if not, write to the Free Software   *
# *   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
# *   USA                                                                   *
# *                                                                         *
# ***************************************************************************

__title__ = "FreeCAD FEM material task panel for the document object"
__author__ = "Juergen Riegel, Bernd Hahnebach, Qingfeng Xia"
__url__ = "https://www.freecad.org"

## @package task_material_common
#  \ingroup FEM
#  \brief FreeCAD FEM _ViewProviderFemMaterial
#  \brief task panel for common material object

import math
from types import SimpleNamespace

from PySide import QtCore
from PySide import QtGui

import FreeCAD
import FreeCADGui
from FreeCAD import Units
import Materials
import MatGui

from femguiutils import selection_widgets
from femtools import material_orthotropic
from . import base_femtaskpanel


class _TaskPanel(base_femtaskpanel._BaseTaskPanel):
    """
    The editmode TaskPanel for FemMaterial objects
    """

    def __init__(self, obj):
        super().__init__(obj)

        # FreeCAD material dictionary of current material
        self.material = self.obj.Material
        self.uuid = self.obj.UUID
        self.material_manager = Materials.MaterialManager()

        # parameter widget
        self.parameterWidget = FreeCADGui.PySideUic.loadUi(
            FreeCAD.getHomePath() + "Mod/Fem/Resources/ui/Material.ui"
        )
        self.material_tree = MatGui.MaterialTreeWidget(self.parameterWidget.wgt_material_tree)
        self.material_tree.expanded = False
        self.material_tree.IncludeEmptyFolders = False
        self.material_tree.IncludeEmptyLibraries = False

        QtCore.QObject.connect(
            self.parameterWidget.chbu_allow_edit,
            QtCore.SIGNAL("clicked()"),
            self.toggleInputFieldsReadOnly,
        )
        # basic properties must be provided
        QtCore.QObject.connect(
            self.parameterWidget.qsb_density,
            QtCore.SIGNAL("editingFinished()"),
            self.density_changed,
        )
        # mechanical properties
        QtCore.QObject.connect(
            self.parameterWidget.qsb_young_modulus,
            QtCore.SIGNAL("editingFinished()"),
            self.ym_changed,
        )
        QtCore.QObject.connect(
            self.parameterWidget.qsb_poisson_ratio,
            QtCore.SIGNAL("editingFinished()"),
            self.pr_changed,
        )
        # thermal properties
        QtCore.QObject.connect(
            self.parameterWidget.qsb_thermal_conductivity,
            QtCore.SIGNAL("editingFinished()"),
            self.tc_changed,
        )
        QtCore.QObject.connect(
            self.parameterWidget.qsb_expansion_coefficient,
            QtCore.SIGNAL("editingFinished()"),
            self.tec_changed,
        )
        QtCore.QObject.connect(
            self.parameterWidget.qsb_expansion_reference_temperature,
            QtCore.SIGNAL("editingFinished()"),
            self.tert_changed,
        )
        QtCore.QObject.connect(
            self.parameterWidget.qsb_specific_heat,
            QtCore.SIGNAL("editingFinished()"),
            self.sh_changed,
        )
        # fluidic properties, only volumetric thermal expansion coeff makes sense
        QtCore.QObject.connect(
            self.parameterWidget.qsb_kinematic_viscosity,
            QtCore.SIGNAL("editingFinished()"),
            self.kinematic_viscosity_changed,
        )
        QtCore.QObject.connect(
            self.parameterWidget.wgt_material_tree,
            QtCore.SIGNAL("onMaterial(QString)"),
            self.set_from_editor,
        )

        # init all parameter input files with read only
        self.parameterWidget.chbu_allow_edit.setCheckState(QtCore.Qt.CheckState.Unchecked)
        self.toggleInputFieldsReadOnly()

        # hide some groupBox according to material category
        if self.obj.Category == "Fluid":
            self.filter_models(self.obj.Category)
            self.parameterWidget.groupBox_mechanical.setVisible(0)
        else:
            self.parameterWidget.groupBox_fluidic.setVisible(0)

        # geometry selection widget
        self.selectionWidget = selection_widgets.GeometryElementsSelection(
            obj.References, ["Solid", "Face", "Edge"], False, True
        )  # start with Solid in list!

        # form made from param and selection widget
        self.form = [self.parameterWidget, self.selectionWidget]
        if self.obj.Category == "Solid":
            self.form.insert(1, self._create_elasticity_widget())

        # check references, has to be after initialisation of selectionWidget
        self.material_tree.UUID = self.uuid
        self.set_mat_params_in_input_fields(self.material)

        self.selectionWidget.has_equal_references_shape_types()

    # leave task panel ***************************************************************************
    def accept(self):
        if self.selectionWidget.has_equal_references_shape_types():
            if self.obj.Category == "Solid":
                try:
                    elasticity = self._staged_elasticity_values()
                    errors = material_orthotropic.validation_errors(
                        SimpleNamespace(
                            PropertiesList=["ElasticityModel"], Category="Solid", **elasticity
                        )
                    )
                except ValueError as error:
                    errors = [str(error)]
                if errors:
                    QtGui.QMessageBox.warning(
                        FreeCADGui.getMainWindow(),
                        FreeCAD.Qt.translate("FEM", "Invalid orthotropic material"),
                        "\n".join(errors),
                    )
                    return False
                for name, value in elasticity.items():
                    if getattr(self.obj, name) != value:
                        setattr(self.obj, name, value)
            self.obj.Material = self.material
            self.obj.UUID = self.uuid
            self.obj.References = self.selectionWidget.references

        self.selectionWidget.finish_selection()
        return super().accept()

    def reject(self):
        self.selectionWidget.finish_selection()
        return super().reject()

    # choose material ****************************************************************************
    def filter_models(self, category):
        material_filter = Materials.MaterialFilter()
        models = set(Materials.ModelManager().Models.keys())
        uuids = Materials.UUIDs()
        if category == "Fluid":
            material_filter.RequiredModels = [uuids.Fluid]
            self.material_tree.setFilter(material_filter)

    def toggleInputFieldsReadOnly(self):
        if self.parameterWidget.chbu_allow_edit.isChecked():
            self.parameterWidget.qsb_density.setDisabled(False)
            self.parameterWidget.qsb_young_modulus.setDisabled(False)
            self.parameterWidget.qsb_poisson_ratio.setDisabled(False)
            self.parameterWidget.qsb_thermal_conductivity.setDisabled(False)
            self.parameterWidget.qsb_expansion_coefficient.setDisabled(False)
            self.parameterWidget.qsb_expansion_reference_temperature.setDisabled(False)
            self.parameterWidget.qsb_specific_heat.setDisabled(False)
            self.parameterWidget.qsb_kinematic_viscosity.setDisabled(False)
            self.parameterWidget.wgt_material_tree.setEnabled(False)
            self.uuid = ""
            self.mat_from_input_fields()
        else:
            self.parameterWidget.qsb_density.setDisabled(True)
            self.parameterWidget.qsb_young_modulus.setDisabled(True)
            self.parameterWidget.qsb_poisson_ratio.setDisabled(True)
            self.parameterWidget.qsb_thermal_conductivity.setDisabled(True)
            self.parameterWidget.qsb_expansion_coefficient.setDisabled(True)
            self.parameterWidget.qsb_expansion_reference_temperature.setDisabled(True)
            self.parameterWidget.qsb_specific_heat.setDisabled(True)
            self.parameterWidget.qsb_kinematic_viscosity.setDisabled(True)
            self.parameterWidget.wgt_material_tree.setEnabled(True)
            self.set_from_editor(self.material_tree.UUID)
        self._elasticity_model_changed()

    # Native directional properties are independent of the selected material card.
    # All controls below are staged: opening/cancelling the panel never changes them.
    def _create_elasticity_widget(self):
        translate = FreeCAD.Qt.translate
        widget = QtGui.QWidget()
        widget.setWindowTitle(translate("FEM", "Elasticity and material axes"))
        layout = QtGui.QVBoxLayout(widget)
        model_layout = QtGui.QFormLayout()
        self.elasticityModel = QtGui.QComboBox()
        self.elasticityModel.setObjectName("elasticityModel")
        self.elasticityModel.setToolTip(translate(
            "FEM", "Orthotropic elasticity is supported by the CalculiX exporter for 3D "
            "solids and shells, not composite layups or isotropic plasticity. A single "
            "material covers the whole mesh. Use separate material objects to assign "
            "different regions or material axes."
        ))
        self.elasticityModel.addItem(translate("FEM", "Isotropic"), "Isotropic")
        self.elasticityModel.addItem(translate("FEM", "Orthotropic"), "Orthotropic")
        self.elasticityModel.setCurrentIndex(1 if self.obj.ElasticityModel == "Orthotropic" else 0)
        model_layout.addRow(translate("FEM", "Elasticity model"), self.elasticityModel)
        layout.addLayout(model_layout)

        self.orthotropicWidget = QtGui.QWidget()
        directional_layout = QtGui.QFormLayout(self.orthotropicWidget)
        self.orthotropicFields = {}
        self._initial_elasticity_values = {}
        self._initial_elasticity_display = {}
        fields = (
            ("YoungsModulus1", translate("FEM", "Young's modulus E1")),
            ("YoungsModulus2", translate("FEM", "Young's modulus E2")),
            ("YoungsModulus3", translate("FEM", "Young's modulus E3")),
            ("ShearModulus12", translate("FEM", "Shear modulus G12")),
            ("ShearModulus13", translate("FEM", "Shear modulus G13")),
            ("ShearModulus23", translate("FEM", "Shear modulus G23")),
            ("PoissonRatio12", translate("FEM", "Poisson ratio nu12")),
            ("PoissonRatio13", translate("FEM", "Poisson ratio nu13")),
            ("PoissonRatio23", translate("FEM", "Poisson ratio nu23")),
        )
        for name, label in fields:
            value = getattr(self.obj, name)
            field = QtGui.QDoubleSpinBox()
            field.setObjectName(name)
            field.setDecimals(10)
            field.setKeyboardTracking(False)
            if name.startswith("Poisson"):
                field.setRange(-1e6, 1e6)
                field.setSingleStep(0.01)
                field.setValue(value)
                field.setToolTip(
                    translate("FEM", "nu_ij = -strain_j / strain_i under uniaxial stress i.")
                )
            else:
                field.setRange(0, 1e15)
                field.setSuffix(" MPa")
                field.setValue(value.getValueAs("MPa").Value)
            self.orthotropicFields[name] = field
            self._initial_elasticity_values[name] = value
            self._initial_elasticity_display[name] = field.value()
            directional_layout.addRow(label, field)

        self.orientationReference = QtGui.QComboBox()
        self.orientationReference.setObjectName("MaterialOrientationReference")
        self.orientationReference.addItem(translate("FEM", "Global axes (no reference)"))
        self._orientation_references = [None]
        reference = self.obj.MaterialOrientationReference
        candidates = [
            candidate
            for candidate in self.obj.Document.Objects
            if candidate != self.obj and "Placement" in candidate.PropertiesList
        ]
        if reference and reference not in candidates:
            candidates.append(reference)
        for candidate in candidates:
            self.orientationReference.addItem(f"{candidate.Label} [{candidate.Name}]")
            self._orientation_references.append(candidate)
            if candidate == reference:
                self.orientationReference.setCurrentIndex(len(self._orientation_references) - 1)
        directional_layout.addRow(
            translate("FEM", "Orientation reference"), self.orientationReference
        )

        self._initial_orientation = self.obj.MaterialOrientation
        axis = self._initial_orientation.Axis
        self.orientationAxis = []
        for label, value in zip(("X", "Y", "Z"), (axis.x, axis.y, axis.z)):
            field = QtGui.QDoubleSpinBox()
            field.setObjectName("MaterialOrientationAxis" + label)
            field.setDecimals(12)
            field.setRange(-1e6, 1e6)
            field.setSingleStep(0.1)
            field.setValue(value)
            directional_layout.addRow(
                translate("FEM", "Local rotation axis") + " " + label, field
            )
            self.orientationAxis.append(field)
        self.orientationAngle = QtGui.QDoubleSpinBox()
        self.orientationAngle.setObjectName("MaterialOrientationAngle")
        self.orientationAngle.setDecimals(10)
        self.orientationAngle.setRange(-360, 360)
        self.orientationAngle.setSuffix(translate("FEM", " degrees"))
        self.orientationAngle.setValue(math.degrees(self._initial_orientation.Angle))
        directional_layout.addRow(
            translate("FEM", "Local rotation angle"), self.orientationAngle
        )
        self._initial_orientation_display = [field.value() for field in self.orientationAxis] + [
            self.orientationAngle.value()
        ]
        guidance = QtGui.QLabel(
            translate(
                "FEM",
                "The local rotation defines material axes 1, 2, 3 relative to the reference's "
                "global placement. With no reference they start at global X, Y, Z. Geometry "
                "references below assign the material region; they do not set its axes. "
                "Shells project these directions into their plane; their normal sets axis 3.",
            )
        )
        guidance.setWordWrap(True)
        directional_layout.addRow(guidance)
        layout.addWidget(self.orthotropicWidget)
        self.elasticityModel.currentIndexChanged.connect(self._elasticity_model_changed)
        self._elasticity_model_changed()
        return widget

    def _elasticity_model_changed(self, *_):
        if not hasattr(self, "elasticityModel"):
            return
        orthotropic = self.elasticityModel.currentData() == "Orthotropic"
        self.orthotropicWidget.setEnabled(orthotropic)
        isotropic_editable = self.parameterWidget.chbu_allow_edit.isChecked() and not orthotropic
        self.parameterWidget.qsb_young_modulus.setEnabled(isotropic_editable)
        self.parameterWidget.qsb_poisson_ratio.setEnabled(isotropic_editable)

    def _staged_elasticity_values(self):
        values = dict(self._initial_elasticity_values)
        values["ElasticityModel"] = self.elasticityModel.currentData()
        for name, field in self.orthotropicFields.items():
            # Preserve full native precision if the user has not changed the display.
            if field.value() != self._initial_elasticity_display[name]:
                value = field.value()
                values[name] = value if name.startswith("Poisson") else Units.Quantity(
                    f"{value:.17g} MPa"
                )
        values["MaterialOrientationReference"] = self._orientation_references[
            self.orientationReference.currentIndex()
        ]
        if (
            values["ElasticityModel"] == "Orthotropic"
            and values["MaterialOrientationReference"] == self.obj
        ):
            raise ValueError(
                FreeCAD.Qt.translate(
                    "FEM", "The material cannot be its own orientation reference."
                )
            )
        displayed = [field.value() for field in self.orientationAxis]
        displayed.append(self.orientationAngle.value())
        rotation = self._initial_orientation
        if displayed != self._initial_orientation_display:
            axis = FreeCAD.Vector(*displayed[:3])
            if axis.Length == 0 and displayed[3] != 0:
                raise ValueError(
                    FreeCAD.Qt.translate(
                        "FEM", "A nonzero material rotation needs a nonzero rotation axis."
                    )
                )
            rotation = FreeCAD.Rotation(axis, displayed[3])
        values["MaterialOrientation"] = rotation
        return values

    # material parameter input fields ************************************************************
    # mechanical input fields
    def ym_changed(self):
        if self.parameterWidget.chbu_allow_edit.isChecked():
            self.material["YoungsModulus"] = self.parameterWidget.qsb_young_modulus.property(
                "value"
            ).UserString

    def density_changed(self):
        if self.parameterWidget.chbu_allow_edit.isChecked():
            self.material["Density"] = self.parameterWidget.qsb_density.property("value").UserString

    def pr_changed(self):
        if self.parameterWidget.chbu_allow_edit.isChecked():
            self.material["PoissonRatio"] = str(
                self.parameterWidget.qsb_poisson_ratio.property("value").Value
            )

    # thermal input fields
    def tc_changed(self):
        if self.parameterWidget.chbu_allow_edit.isChecked():
            self.material["ThermalConductivity"] = (
                self.parameterWidget.qsb_thermal_conductivity.property("value").UserString
            )

    def tec_changed(self):
        if self.parameterWidget.chbu_allow_edit.isChecked():
            self.material["ThermalExpansionCoefficient"] = (
                self.parameterWidget.qsb_expansion_coefficient.property("value").UserString
            )

    def tert_changed(self):
        if self.parameterWidget.chbu_allow_edit.isChecked():
            self.material["ThermalExpansionReferenceTemperature"] = (
                self.parameterWidget.qsb_expansion_reference_temperature.property(
                    "value"
                ).UserString
            )

    def sh_changed(self):
        if self.parameterWidget.chbu_allow_edit.isChecked():
            self.material["SpecificHeat"] = self.parameterWidget.qsb_specific_heat.property(
                "value"
            ).UserString

    # fluidic input fields
    def kinematic_viscosity_changed(self):
        if self.parameterWidget.chbu_allow_edit.isChecked():
            self.material["KinematicViscosity"] = (
                self.parameterWidget.qsb_kinematic_viscosity.property("value").UserString
            )

    def set_mat_params_in_input_fields(self, matmap):
        if "YoungsModulus" in matmap:
            self.parameterWidget.qsb_young_modulus.setProperty(
                "value", Units.Quantity(matmap["YoungsModulus"])
            )
        else:
            self.parameterWidget.qsb_young_modulus.setProperty("rawValue", 0.0)

        if "PoissonRatio" in matmap:
            self.parameterWidget.qsb_poisson_ratio.setProperty(
                "value", Units.Quantity(matmap["PoissonRatio"])
            )
        else:
            self.parameterWidget.qsb_poisson_ratio.setProperty("rawValue", 0.0)
        # Fluidic properties
        if "KinematicViscosity" in matmap:
            self.parameterWidget.qsb_kinematic_viscosity.setProperty(
                "value", Units.Quantity(matmap["KinematicViscosity"])
            )
        else:
            self.parameterWidget.qsb_kinematic_viscosity.setProperty("rawValue", 0.0)

        if "Density" in matmap:
            self.parameterWidget.qsb_density.setProperty("value", Units.Quantity(matmap["Density"]))
        else:
            self.parameterWidget.qsb_density.setProperty("rawValue", 0.0)
        # thermal properties
        if "ThermalConductivity" in matmap:
            self.parameterWidget.qsb_thermal_conductivity.setProperty(
                "value", Units.Quantity(matmap["ThermalConductivity"])
            )
        else:
            self.parameterWidget.qsb_thermal_conductivity.setProperty("rawValue", 0.0)

        if "ThermalExpansionCoefficient" in matmap:
            v = Units.Quantity(matmap["ThermalExpansionCoefficient"])
            v.Format = {"Precision": 3}
            self.parameterWidget.qsb_expansion_coefficient.setProperty("value", v)
        else:
            self.parameterWidget.qsb_expansion_coefficient.setProperty("rawValue", 0.0)
        if "ThermalExpansionReferenceTemperature" in matmap:
            self.parameterWidget.qsb_expansion_reference_temperature.setProperty(
                "value", Units.Quantity(matmap["ThermalExpansionReferenceTemperature"])
            )
        else:
            self.parameterWidget.qsb_expansion_reference_temperature.setProperty("rawValue", 0.0)
        if "SpecificHeat" in matmap:
            self.parameterWidget.qsb_specific_heat.setProperty(
                "value", Units.Quantity(matmap["SpecificHeat"])
            )
        else:
            self.parameterWidget.qsb_specific_heat.setProperty("rawValue", 0.0)

    def set_from_editor(self, value):
        if not value:
            return
        mat = self.material_manager.getMaterial(value)
        self.material = mat.Properties
        self.uuid = mat.UUID
        self.set_mat_params_in_input_fields(self.material)

    def mat_from_input_fields(self):
        d = {}
        d["Name"] = "Custom"
        p = self.parameterWidget
        d["Density"] = p.qsb_density.property("value").UserString
        d["ThermalConductivity"] = p.qsb_thermal_conductivity.property("value").UserString
        d["ThermalExpansionCoefficient"] = p.qsb_expansion_coefficient.property("value").UserString
        d["ThermalExpansionReferenceTemperature"] = p.qsb_expansion_reference_temperature.property(
            "value"
        ).UserString
        d["SpecificHeat"] = p.qsb_specific_heat.property("value").UserString
        if self.obj.Category == "Solid":
            d["YoungsModulus"] = p.qsb_young_modulus.property("value").UserString
            d["PoissonRatio"] = str(p.qsb_poisson_ratio.property("value").Value)
        elif self.obj.Category == "Fluid":
            d["KinematicViscosity"] = p.qsb_kinematic_viscosity.property("value").UserString
        self.material = d
