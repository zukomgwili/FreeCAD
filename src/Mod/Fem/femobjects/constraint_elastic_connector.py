# SPDX-License-Identifier: LGPL-2.1-or-later

"""Concentrated translational spring, distinct from an Elmer foundation."""

from FreeCAD import Base

from .base_fempythonobject import BaseFemPythonObject
from .base_fempythonobject import _PropHelper


class ConstraintElasticConnector(BaseFemPythonObject):
    Type = "Fem::ConstraintElasticConnector"

    def __init__(self, obj):
        super().__init__(obj)
        for prop in self._properties():
            prop.add_to_object(obj)
        obj.addExtension("App::SuppressibleExtensionPython")

    def _properties(self):
        return [
            _PropHelper(type="App::PropertyEnumeration", name="Mode", group="Connector",
                        doc="One mesh node to ground, or two mesh nodes",
                        value=["Ground", "Two points"]),
            _PropHelper(type="App::PropertyStiffness", name="Stiffness", group="Connector",
                        doc="Total stiffness of this one connector; no distribution or division",
                        value="0 N/mm"),
            *[_PropHelper(type="App::PropertyLinkSubGlobal", name=name, group="Connector",
                          doc="One CAD vertex resolving to exactly one mesh node", value=None)
              for name in ("End1", "End2")],
            _PropHelper(type="App::PropertyEnumeration", name="Axis", group="Direction",
                        doc="Translational direction in the saved local frame",
                        value=["X", "Y", "Z"]),
            _PropHelper(type="App::PropertyRotation", name="Orientation", group="Direction",
                        doc="Local frame rotation relative to the reference, or global mesh axes",
                        value=Base.Rotation()),
            _PropHelper(type="App::PropertyLinkGlobal", name="OrientationReference",
                        group="Direction", doc="Optional placed object or occurrence frame",
                        value=None),
        ]

    def onDocumentRestored(self, obj):
        for prop in self._properties():
            if prop.name not in obj.PropertiesList:
                prop.add_to_object(obj)
        if not obj.hasExtension("App::SuppressibleExtensionPython"):
            obj.addExtension("App::SuppressibleExtensionPython")
