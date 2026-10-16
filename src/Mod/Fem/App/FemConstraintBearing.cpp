// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2013 Jan Rheinländer                                    *
 *                                   <jrheinlaender@users.sourceforge.net> *
 *                                                                         *
 *   This file is part of the FreeCAD CAx development system.              *
 *                                                                         *
 *   This library is free software; you can redistribute it and/or         *
 *   modify it under the terms of the GNU Library General Public           *
 *   License as published by the Free Software Foundation; either          *
 *   version 2 of the License, or (at your option) any later version.      *
 *                                                                         *
 *   This library  is distributed in the hope that it will be useful,      *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
 *   GNU Library General Public License for more details.                  *
 *                                                                         *
 *   You should have received a copy of the GNU Library General Public     *
 *   License along with this library; see the file COPYING.LIB. If not,    *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,         *
 *   Suite 330, Boston, MA  02111-1307, USA                                *
 *                                                                         *
 ***************************************************************************/


#include <cmath>
#include <Standard_Failure.hxx>
#include <Base/Console.h>


#include <Mod/Part/App/PartFeature.h>

#include "FemConstraintBearing.h"
#include "FemTools.h"

using namespace Fem;

PROPERTY_SOURCE(Fem::ConstraintBearing, Fem::Constraint)

ConstraintBearing::ConstraintBearing()
{
    ADD_PROPERTY_TYPE(
        Location,
        (nullptr),
        "ConstraintBearing",
        (App::PropertyType)(App::Prop_None),
        "Element giving axial location of constraint"
    );
    ADD_PROPERTY(Dist, (0.0));
    ADD_PROPERTY(AxialFree, (0));
    ADD_PROPERTY(Radius, (0.0));
    ADD_PROPERTY(Height, (0.0));
    ADD_PROPERTY_TYPE(
        BasePoint,
        (Base::Vector3d(0, 0, 0)),
        "ConstraintBearing",
        App::PropertyType(App::Prop_ReadOnly | App::Prop_Output),
        "Base point of cylindrical bearing seat"
    );
    ADD_PROPERTY_TYPE(
        Axis,
        (Base::Vector3d(0, 1, 0)),
        "ConstraintBearing",
        App::PropertyType(App::Prop_ReadOnly | App::Prop_Output),
        "Axis of bearing seat"
    );
    Location.setScope(App::LinkScope::Global);
}

App::DocumentObjectExecReturn* ConstraintBearing::execute()
{
    return Constraint::execute();
}

void ConstraintBearing::onChanged(const App::Property* prop)
{
    try {
        // Calculate the normal before updating the bearing symbol.
        Constraint::onChanged(prop);
        if (getDocument() && !isRestoring()
            && (prop == &References || prop == &Location || prop == &Dist)) {
            updateGeometry();
        }
    }
    catch (const Standard_Failure& error) {
        clearGeometry();
        if (isRecomputing()) {
            throw;  // Constraint::execute records the diagnostic as an object error.
        }
        Base::Console().error("{}: {}\n", getNameInDocument(), error.GetMessageString());
    }
}

void ConstraintBearing::clearGeometry()
{
    Radius.setValue(0);
    Height.setValue(0);
    Axis.setValue(Base::Vector3d());
    BasePoint.setValue(Base::Vector3d());
    BasePoint.touch();
}

void ConstraintBearing::updateGeometry()
{
    const auto& refs = References.getValues();
    const auto& names = References.getSubValues();
    if (refs.empty()) {
        clearGeometry();
        return;  // An unfinished constraint has no bearing geometry yet.
    }
    if (refs.size() != 1 || names.size() != 1) {
        throw Standard_Failure("Bearing References must select one cylindrical face or circular edge");
    }
    TopoDS_Shape shape = Tools::getFeatureSubShape(refs.front(), names.front().c_str(), true);
    double radius = 0, height = 0;
    Base::Vector3d base, axis;
    if (shape.IsNull() || !Tools::getCylinderParams(shape, base, axis, height, radius)) {
        throw Standard_Failure("Bearing References must select a cylindrical face or circular edge");
    }
    if (!std::isfinite(Dist.getValue())) {
        throw Standard_Failure("Bearing distance must be finite");
    }
    // Preserve the original References-path seat and signed-offset convention.
    base += axis * height / 2;
    if (Location.getValue()) {
        base = getBasePoint(base, axis, Location, Dist.getValue());
    }
    Radius.setValue(radius);
    Axis.setValue(axis);
    Height.setValue(height);
    BasePoint.setValue(base);
    BasePoint.touch();  // Recreate the symbol after all geometry is valid.
}
