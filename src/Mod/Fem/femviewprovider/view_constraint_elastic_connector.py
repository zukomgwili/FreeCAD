# SPDX-License-Identifier: LGPL-2.1-or-later

from .view_base_femconstraint import VPBaseFemConstraint


class VPConstraintElasticConnector(VPBaseFemConstraint):
    def getIcon(self):
        return ":/icons/FEM_ConstraintSpring.svg"
