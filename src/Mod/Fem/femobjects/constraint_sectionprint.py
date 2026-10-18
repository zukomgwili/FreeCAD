# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *   Copyright (c) 2020 Bernd Hahnebach <bernd@bimstatik.org>              *
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

__title__ = "FreeCAD FEM constraint section print document object"
__author__ = "Bernd Hahnebach"
__url__ = "https://www.freecad.org"

## @package constraint_sectionprint
#  \ingroup FEM
#  \brief constraint section print object

from FreeCAD import Base
from . import base_fempythonobject

_PropHelper = base_fempythonobject._PropHelper


class ConstraintSectionPrint(base_fempythonobject.BaseFemPythonObject):
    """
    The FemConstraintSectionPrint object
    """

    Type = "Fem::ConstraintSectionPrint"

    def __init__(self, obj):
        super().__init__(obj)

        for prop in self._get_properties():
            prop.add_to_object(obj)

    def _get_properties(self):
        prop = []
        prop.extend(
            [
                _PropHelper(
                    type="App::PropertyBool",
                    name="NativeEquilibriumCut",
                    group="Native Force Accounting",
                    value=False,
                    doc="Request a native equilibrium-derived cut wrench on AccountingBody. "
                    "Separate from the approximate recovered-stress SOF/SOM output.",
                ),
                _PropHelper(
                    type="App::PropertyLinkSubList",
                    name="AccountingBody",
                    group="Native Force Accounting",
                    value=[],
                    doc="Explicit solid(s) on the selected facet-owner side of the cut. "
                    "The cut must be their only shared-node interface; prescribed DOFs/MPCs "
                    "inside this free body are not supported.",
                ),
            ]
        )

        prop.append(
            _PropHelper(
                type="App::PropertyEnumeration",
                name="Variable",
                group="Constraint Section Print",
                doc="Set facial variable",
                value=["Section Force", "Heat Flux", "Drag Stress", "Electric Flux"],
            )
        )

        return prop

    def onDocumentRestored(self, obj):
        # update old project with new properties
        for prop in self._get_properties():
            try:
                obj.getPropertyByName(prop.name)
            except Base.PropertyError:
                prop.add_to_object(obj)
