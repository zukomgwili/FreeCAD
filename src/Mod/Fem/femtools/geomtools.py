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

__title__ = "FEM geometry tools"
__author__ = "Bernd Hahnebach"
__url__ = "https://www.freecad.org"

import FreeCAD


# ************************************************************************************************
def find_element_in_shape(aShape, anElement):
    """Find a subelement, preserving topology before using geometric fallback.

    OCCT locations can have different representations of the same placement,
    so isSame alone is insufficient for subshapes retrieved through a compound.
    Partner identity must also have the same placement: isPartner alone would
    confuse different occurrences of one shape. External geometry is supported
    only when it identifies one element unambiguously.
    """
    ele_st = anElement.ShapeType
    attributes = {"Solid": "Solids", "CompSolid": "Solids", "Face": "Faces",
                  "Shell": "Faces", "Edge": "Edges", "Wire": "Edges", "Vertex": "Vertexes"}
    if ele_st not in attributes:
        if ele_st == "Compound":
            FreeCAD.Console.PrintError("Compound is not supported.\n")
        return None

    elements = getattr(aShape, attributes[ele_st])
    predicates = (
        lambda candidate: candidate.isSame(anElement),
        lambda candidate: candidate.isPartner(anElement)
        and candidate.Placement.isSame(anElement.Placement),
        lambda candidate: is_same_geometry(candidate, anElement),
    )
    for matches_element in predicates:
        matches = [f"{ele_st}{index}" for index, candidate in enumerate(elements, 1)
                   if matches_element(candidate)]
        if len(matches) == 1:
            return matches[0]
        if matches:
            raise ValueError(
                f"Ambiguous {ele_st} reference: matches {', '.join(matches)}. "
                "Select an explicit subelement of the part to mesh."
            )
    return None


# ************************************************************************************************
def get_vertexes_by_element(aShape, anElement):
    # we're going to extend the method find_element_in_shape and return the vertexes
    # import Part
    ele_vertexes = []
    ele_st = anElement.ShapeType
    if ele_st == "Solid" or ele_st == "CompSolid":
        for index, solid in enumerate(aShape.Solids):
            if is_same_geometry(solid, anElement):
                for vele in aShape.Solids[index].Vertexes:
                    for i, v in enumerate(aShape.Vertexes):
                        if vele.isSame(v):  # use isSame, because orientation could be different
                            ele_vertexes.append(i)
                # FreeCAD.Console.PrintMessage("  " + str(sorted(ele_vertexes)), "\n")
                return ele_vertexes
        FreeCAD.Console.PrintError(
            "Error, Solid " + str(anElement) + " not found in: " + str(aShape) + "\n"
        )
    elif ele_st == "Face" or ele_st == "Shell":
        for index, face in enumerate(aShape.Faces):
            if is_same_geometry(face, anElement):
                for vele in aShape.Faces[index].Vertexes:
                    for i, v in enumerate(aShape.Vertexes):
                        if vele.isSame(v):  # use isSame, because orientation could be different
                            ele_vertexes.append(i)
                # FreeCAD.Console.PrintMessage("  " + str(sorted(ele_vertexes)) + "\n")
                return ele_vertexes
    elif ele_st == "Edge" or ele_st == "Wire":
        for index, edge in enumerate(aShape.Edges):
            if is_same_geometry(edge, anElement):
                for vele in aShape.Edges[index].Vertexes:
                    for i, v in enumerate(aShape.Vertexes):
                        if vele.isSame(v):  # use isSame, because orientation could be different
                            ele_vertexes.append(i)
                # FreeCAD.Console.PrintMessage("  " + str(sorted(ele_vertexes)) + "\n")
                return ele_vertexes
    elif ele_st == "Vertex":
        for index, vertex in enumerate(aShape.Vertexes):
            if is_same_geometry(vertex, anElement):
                ele_vertexes.append(index)
                # FreeCAD.Console.PrintMessage("  " + str(sorted(ele_vertexes)) + "\n")
                return ele_vertexes
    elif ele_st == "Compound":
        FreeCAD.Console.PrintError("Compound is not supported.\n")


# ************************************************************************************************
def is_same_geometry(shape1, shape2):
    # the vertexes and the CenterOfMass are compared
    # it is a hack, but I do not know any better !
    # check of Volume and Area before starting with the vertices could be added
    # BoundBox is possible too, but is BB calculations robust?!
    # FreeCAD.Console.PrintMessage("{}\n".format(shape1))
    # FreeCAD.Console.PrintMessage("{}\n".format(shape2))
    same_Vertexes = 0
    if len(shape1.Vertexes) == len(shape2.Vertexes) and len(shape1.Vertexes) > 1:
        # compare CenterOfMass
        if shape1.CenterOfMass != shape2.CenterOfMass:
            return False
        else:
            # compare the Vertexes
            for vs1 in shape1.Vertexes:
                for vs2 in shape2.Vertexes:
                    if vs1.X == vs2.X and vs1.Y == vs2.Y and vs1.Z == vs2.Z:
                        same_Vertexes += 1
                        continue
            # FreeCAD.Console.PrintMessage("{}\n".(same_Vertexes))
            if same_Vertexes == len(shape1.Vertexes):
                return True
            else:
                return False
    if len(shape1.Vertexes) == len(shape2.Vertexes) and len(shape1.Vertexes) == 1:
        vs1 = shape1.Vertexes[0]
        vs2 = shape2.Vertexes[0]
        if vs1.X == vs2.X and vs1.Y == vs2.Y and vs1.Z == vs2.Z:
            return True
        else:
            return False
    else:
        return False


# ************************************************************************************************
def get_element(part, element):
    if element.startswith("Solid"):
        index = int(element.lstrip("Solid")) - 1
        if index >= len(part.Shape.Solids):
            FreeCAD.Console.PrintError(
                "Index out of range. This Solid does not exist in the Shape!\n"
            )
            return None
        else:
            return part.Shape.Solids[index]  # Solid
    else:
        return part.Shape.getElement(element)  # Face, Edge, Vertex
