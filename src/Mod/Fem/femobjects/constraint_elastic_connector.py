# SPDX-License-Identifier: LGPL-2.1-or-later

"""Scalar point/explicit-rigid-port springs, distinct from an Elmer foundation."""

from FreeCAD import Base, Units

from .base_fempythonobject import BaseFemPythonObject
from .base_fempythonobject import _PropHelper


class ConstraintElasticConnector(BaseFemPythonObject):
    Type = "Fem::ConstraintElasticConnector"
    _attachments = ["Vertices", "Rigid body ports", "Vertex to rigid body port"]

    def __init__(self, obj):
        super().__init__(obj)
        for prop in self._properties():
            prop.add_to_object(obj)
        obj.addExtension("App::SuppressibleExtensionPython")
        self._update_editor_modes(obj)

    def _properties(self):
        return [
            _PropHelper(
                type="App::PropertyEnumeration",
                name="Attachment",
                group="Connector",
                doc="Vertices, explicit Rigid Body ports, or one beam vertex to a solid port",
                value=list(self._attachments),
            ),
            _PropHelper(
                type="App::PropertyEnumeration",
                name="Kind",
                group="Connector",
                doc="Scalar translational or rotational response, never a coupled 6x6 law",
                value=["Translational", "Rotational"],
            ),
            _PropHelper(
                type="App::PropertyEnumeration",
                name="Mode",
                group="Connector",
                doc="One mesh node to ground, or two mesh nodes",
                value=["Ground", "Two points"],
            ),
            _PropHelper(
                type="App::PropertyStiffness",
                name="Stiffness",
                group="Connector",
                doc="Total stiffness of this one connector; no distribution or division",
                value="0 N/mm",
            ),
            _PropHelper(
                type="App::PropertyQuantity",
                name="RotationalStiffness",
                group="Connector",
                doc="Total rotational stiffness in N*mm/rad; explicitly supplied",
                value=Units.Unit("N*mm/rad"),
            ),
            *[
                _PropHelper(
                    type="App::PropertyLinkGlobal",
                    name=name,
                    group="Connector",
                    doc="Existing Rigid Body in this analysis; no automatic region coupling",
                    value=None,
                )
                for name in ("RigidBody1", "RigidBody2")
            ],
            *[
                _PropHelper(
                    type="App::PropertyLinkSubGlobal",
                    name=name,
                    group="Connector",
                    doc="One CAD vertex resolving to exactly one mesh node",
                    value=None,
                )
                for name in ("End1", "End2")
            ],
            _PropHelper(
                type="App::PropertyEnumeration",
                name="Axis",
                group="Direction",
                doc="Translational direction in the saved local frame",
                value=["X", "Y", "Z"],
            ),
            _PropHelper(
                type="App::PropertyRotation",
                name="Orientation",
                group="Direction",
                doc="Local frame rotation relative to the reference, or global mesh axes",
                value=Base.Rotation(),
            ),
            _PropHelper(
                type="App::PropertyLinkGlobal",
                name="OrientationReference",
                group="Direction",
                doc="Optional placed object or occurrence frame",
                value=None,
            ),
        ]

    def onDocumentRestored(self, obj):
        for prop in self._properties():
            if prop.name not in obj.PropertiesList:
                prop.add_to_object(obj)
        # Enumeration choices are persisted with the property. Add the new
        # choice to older files without resetting their selection or links.
        selected = obj.Attachment
        choices = list(obj.getEnumerationsOfProperty("Attachment"))
        updated = choices + [value for value in self._attachments if value not in choices]
        if updated != choices:
            obj.Attachment = updated
            obj.Attachment = selected
        # Dynamic PropertyQuantity stores the base-unit numeric value, not its
        # custom unit signature. Reapply that signature without changing value.
        obj.RotationalStiffness = Units.Unit("N*mm/rad")
        if not obj.hasExtension("App::SuppressibleExtensionPython"):
            obj.addExtension("App::SuppressibleExtensionPython")
        self._update_editor_modes(obj)

    def onChanged(self, obj, prop):
        if prop == "Attachment":
            self._update_editor_modes(obj)

    @staticmethod
    def _update_editor_modes(obj):
        hybrid = getattr(obj, "Attachment", "Vertices") == "Vertex to rigid body port"
        # Inactive links remain literal saved data. Conflicts are rejected by
        # the resolver rather than silently discarded by an editor callback.
        for name in ("End1", "End2", "RigidBody1", "RigidBody2"):
            if name in obj.PropertiesList:
                obj.setEditorMode(name, 1 if hybrid and name in ("End2", "RigidBody1") else 0)
