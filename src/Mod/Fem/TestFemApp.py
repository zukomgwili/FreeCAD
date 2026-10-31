# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *   Copyright (c) 2018 Przemo Firszt <przemo@firszt.eu>                   *
# *   Copyright (c) 2018 Bernd Hahnebach <bernd@bimstatik.org>              *
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

# Unit test for the FEM module
# to get the right order import as is used
from femtest.app.test_femimport import TestFemImport as FemTest01
from femtest.app.test_common import TestFemCommon as FemTest02
from femtest.app.test_object import TestObjectCreate as FemTest03
from femtest.app.test_object import TestObjectType as FemTest04
from femtest.app.test_open import TestObjectOpen as FemTest05
from femtest.app.test_material import TestMaterialUnits as FemTest06
from femtest.app.test_mesh import TestMeshCommon as FemTest07
from femtest.app.test_mesh import TestMeshEleTetra10 as FemTest08
from femtest.app.test_mesh import TestMeshGroups as FemTest09
from femtest.app.test_result import TestResult as FemTest10
from femtest.app.test_ccxtools import TestCcxTools as FemTest11
from femtest.app.test_solver_elmer import TestSolverElmer as FemTest13
from femtest.app.test_solver_z88 import TestSolverZ88 as FemTest14
from femtest.app.test_gmsh import TestGMSHTransfinite as FemTest15
from femtest.app.test_gmsh import TestGMSHRefinements as FemTest16
from femtest.app.test_security import TestPostDataObjectSecurity as FemTest17
from femtest.app.test_sectionprint import TestSectionPrint as FemTest18
from femtest.app.test_sectionprint import TestSectionPrintEquilibrium as FemTest19
from femtest.app.test_material_orthotropic import TestMaterialOrthotropic as FemTest20
from femtest.app.test_material_orthotropic import TestMaterialOrthotropicCalculiX as FemTest21
from femtest.app.test_elastic_connector import TestElasticConnector as FemTest22
from femtest.app.test_elastic_connector import TestElasticConnectorCalculiX as FemTest23
from femtest.app.test_elastic_connector import TestRigidPortConnector as FemTest27
from femtest.app.test_rigid_region_ownership import TestRigidRegionOwnership as FemTest28
from femtest.app.test_contact_ownership import TestContactOwnership as FemTest29
from femtest.app.test_material_groups import TestMaterialGroups as FemTest30
from femtest.app.test_rigid_region_ownership import TestSecondOrderLinearOwnership as FemTest31
from femtest.app.test_geometry_signature import TestGeometrySignature as FemTest32
from femtest.app.test_mesh_quality import TestMeshQuality as FemTest33
from femtest.app.test_rigid_body_preflight import TestRigidBodyPreflight as FemTest34
from femtest.app.test_force_accounting import TestForceAccounting as FemTest35
from femtest.app.test_contact_observation import TestContactObservation as FemTest36
from femtest.app.test_contact_observation_source import TestContactObservationSource as FemTest37
from femtest.app.test_contact_observation_native import TestContactObservationNative as FemTest38
from femtest.app.test_movement_provenance import TestMovementProvenance as FemTest39
from femtest.app.test_mesh_vtk_identity import TestMeshVTKIdentity as FemTest40
from femtest.app.test_owned_probe import TestOwnedProbe as FemTest41
from femtest.app.test_tie_ownership import TestTieOwnership as FemTest42
from femtest.app.test_tie_ownership import TestTieShellCompatibility as FemTest43
from femtest.app.test_tie_accounting_native import TestTieAccountingNative as FemTest44
from femtest.app.test_moving_port_accounting_native import (
    TestMovingPortAccountingNative as FemTest45,
)
from femtest.app.test_beam_section_forces import TestBeamSectionForces as FemTest46
from femtest.app.test_reference_groups import TestReferenceGroups as FemTest24
from femtest.app.test_constraint_links import TestConstraintLinks as FemTest25
from femtest.app.test_bearing_location import TestBearingLocation as FemTest26

# dummy usage to get flake8 and lgtm quiet
False if FemTest01.__name__ else True
False if FemTest02.__name__ else True
False if FemTest03.__name__ else True
False if FemTest04.__name__ else True
False if FemTest05.__name__ else True
False if FemTest06.__name__ else True
False if FemTest07.__name__ else True
False if FemTest08.__name__ else True
False if FemTest09.__name__ else True
False if FemTest10.__name__ else True
False if FemTest11.__name__ else True
False if FemTest13.__name__ else True
False if FemTest14.__name__ else True
False if FemTest15.__name__ else True
False if FemTest16.__name__ else True
False if FemTest17.__name__ else True
False if FemTest18.__name__ else True
False if FemTest19.__name__ else True
False if FemTest20.__name__ else True
False if FemTest21.__name__ else True
False if FemTest22.__name__ else True
False if FemTest23.__name__ else True
False if FemTest24.__name__ else True
False if FemTest25.__name__ else True
False if FemTest26.__name__ else True
False if FemTest27.__name__ else True
False if FemTest28.__name__ else True
False if FemTest29.__name__ else True
False if FemTest30.__name__ else True
False if FemTest31.__name__ else True
False if FemTest32.__name__ else True
False if FemTest33.__name__ else True
False if FemTest34.__name__ else True
False if FemTest35.__name__ else True
False if FemTest36.__name__ else True
False if FemTest37.__name__ else True
False if FemTest38.__name__ else True
False if FemTest39.__name__ else True
False if FemTest40.__name__ else True
False if FemTest41.__name__ else True
False if FemTest42.__name__ else True
False if FemTest43.__name__ else True
False if FemTest44.__name__ else True
False if FemTest45.__name__ else True
False if FemTest46.__name__ else True
