# SPDX-License-Identifier: LGPL-2.1-or-later

# -*- coding: utf8 -*-
# ***************************************************************************
# *   Copyright (c) 2009 Yorik van Havre <yorik@uncreated.net>              *
# *   Copyright (c) 2018 George Shuklin (amarao)                            *
# *   Copyright (c) 2020 Eliud Cabrera Castillo <e.cabrera-castillo@tum.de> *
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
"""Provides functions to return the SVG representation of some shapes."""

## @package svgshapes
# \ingroup draftfunctions
# \brief Provides functions to return the SVG representation of some shapes.

import math
import lazy_loader.lazy_loader as lz

import FreeCAD as App
import DraftVecUtils
import WorkingPlane
from draftgeoutils import edges as geo_edges
from draftgeoutils import general as geo_general
from draftutils import params
from draftutils import utils
from draftutils.messages import _msg, _wrn

# Delay import of module until first use because it is heavy
Part = lz.LazyLoader("Part", globals(), "Part")
TechDraw = lz.LazyLoader("TechDraw", globals(), "TechDraw")

## \addtogroup draftfunctions
# @{


def get_proj(vec, plane=None):
    """Get a projection of the vector in the plane's u and v directions.

    TODO: check if the same function for SVG and DXF projection can be used
    so that this function is not just duplicated code.
    This function may also be present elsewhere, like `WorkingPlane`
    or `DraftGeomUtils`, so we should avoid code duplication.

    Parameters
    ----------
    vec: Base::Vector3
        An arbitrary vector that will be projected on the U and V directions.

    plane: WorkingPlane.PlaneBase
        Working plane.
    """
    if not plane:
        return vec

    nx = DraftVecUtils.project(vec, plane.u)
    lx = nx.Length

    if abs(nx.getAngle(plane.u)) > 0.1:
        lx = -lx

    ny = DraftVecUtils.project(vec, plane.v)
    ly = ny.Length

    if abs(ny.getAngle(plane.v)) > 0.1:
        ly = -ly

    # if techdraw: buggy - we now simply do it at the end
    #    ly = -ly
    return App.Vector(lx, ly, 0)


def getProj(vec, plane=None):
    """Get a projection of a vector. DEPRECATED."""
    utils.use_instead("get_proj")
    return get_proj(vec, plane)


def get_discretized(edge, plane):
    """Get a discretized edge on a plane."""
    pieces = params.get_param("svgDiscretization")

    if pieces == 0:
        pieces = 10

    d = int(edge.Length / pieces)
    if d == 0:
        d = 1

    edata = ""
    for i in range(d + 1):
        _length = edge.LastParameter - edge.FirstParameter
        _point = edge.FirstParameter + float(i) / d * _length
        _vec = edge.valueAt(_point)
        v = get_proj(_vec, plane)

        if not edata:
            edata += "M " + str(v.x) + " " + str(v.y) + " "
        else:
            edata += "L " + str(v.x) + " " + str(v.y) + " "

    return edata


def getDiscretized(edge, plane):
    """Get a discretized edge on a plane. DEPRECATED."""
    utils.use_instead("get_discretized")
    return get_discretized(edge, plane)


def _get_path_circ_ellipse(
    plane, edge, verts, edata, iscircle, isellipse, fill, stroke, linewidth, lstyle, allow_final_svg
):
    """Get the edge data from a path that is a circle or ellipse."""
    if plane:
        drawing_plane_normal = plane.axis
    else:
        drawing_plane_normal = WorkingPlane.get_working_plane(update=False).axis

    center = edge.Curve
    ax = center.Axis

    # The angle between the curve axis and the plane is not 0 nor 180 degrees
    _angle = math.degrees(ax.getAngle(drawing_plane_normal))
    if round(_angle, 2) not in (0, 180):
        edata += get_discretized(edge, plane)
        return "edata", edata

    # The angle is 0 or 180, coplanar
    occversion = Part.OCC_VERSION.split(".")
    done = False
    if tuple(map(int, occversion[:2])) >= (7, 1):
        # if using occ >= 7.1, use HLR algorithm
        # HLR chooses its own axes from the projection normal. Express the
        # edge in the same u/v coordinates as the path's existing start point
        # before projecting along Z. get_proj intentionally ignores the
        # working plane origin, so use only its rotation here.
        projected_edge = edge.copy()
        if plane:
            rotation = App.Rotation(plane.u, plane.v, plane.axis, "ZXY")
            placement = App.Placement(App.Vector(), rotation.inverted())
            projected_edge.Placement = placement * projected_edge.Placement
        # Center the native input so SVG's limited numeric precision does not
        # depend on the object's distance from the model origin.
        projected_edge.translate(-projected_edge.Curve.Center)
        snip = TechDraw.projectToSVG(projected_edge, App.Vector(0, 0, 1))

        if snip:
            try:
                _a = snip.split('path d="')[1]
                _a = _a.split('"')[0]
                _start, _arc = _a.split("A")
                native_start = App.Vector(*map(float, _start.strip()[1:].split()), 0)
                rx, ry, rot, large, sweep, x, y = map(float, _arc.split())
                # Native SVG rounds coordinates/radii to six significant
                # digits. Keep the source geometry's precision, especially
                # at semicircles where endpoint rounding moves the centre.
                if iscircle:
                    rx = ry = center.Radius
                    rot = 0
                else:
                    rx, ry = center.MajorRadius, center.MinorRadius
                    major_axis = get_proj(center.XAxis, plane)
                    rot = math.degrees(math.atan2(major_axis.y, major_axis.x))
                start = get_proj(verts[0].Point, plane)
                end = get_proj(verts[-1].Point, plane)
                projected_center = get_proj(center.Center, plane)
                relative_start = start - projected_center
                relative_end = end - projected_center
                native_end = App.Vector(x, y, 0)
                tolerance = max(rx, ry) * 1e-5
                forward = (native_start - relative_start).Length <= tolerance and (
                    native_end - relative_end
                ).Length <= tolerance
                backward = (native_start - relative_end).Length <= tolerance and (
                    native_end - relative_start
                ).Length <= tolerance
                if forward == backward:
                    raise ValueError("Native SVG arc traversal is ambiguous")
                if backward:
                    sweep = 1 - sweep
                A = "A {} {} {} {} {} {} {} ".format(
                    rx, ry, rot, int(large), int(sweep), end.x, end.y
                )
            except (IndexError, ValueError):
                # Full circles/ellipses and unsupported snippets use the
                # analytic path below instead of a single native arc.
                pass
            else:
                edata += A
                done = True

    if not done:
        if len(edge.Vertexes) == 1 and iscircle:
            # Complete circle not only arc
            if allow_final_svg:
                svg = get_circle(plane, fill, stroke, linewidth, lstyle, edge)
                # If it's the whole exported shape we can return a compact SVG
                # circle, otherwise we must keep a single path so islands work.
                return "svg", svg

            _diff = (center.LastParameter - center.FirstParameter) / 2.0
            endpoints = [get_proj(center.value(_diff), plane), get_proj(verts[-1].Point, plane)]
        elif len(edge.Vertexes) == 1 and isellipse:
            # Complete ellipse not only arc
            # svg = get_ellipse(plane,
            #                   fill, stroke, linewidth,
            #                   lstyle, edge)
            # return svg

            # Difference in angles
            _diff = (center.LastParameter - center.FirstParameter) / 2.0
            endpoints = [get_proj(center.value(_diff), plane), get_proj(verts[-1].Point, plane)]
        else:
            endpoints = [get_proj(verts[-1].Point, plane)]

        # Arc with more than one vertex
        if iscircle:
            rx = ry = center.Radius
            rot = 0
        else:  # ellipse
            rx = center.MajorRadius
            ry = center.MinorRadius
            major_axis = get_proj(center.XAxis, plane)
            rot = math.degrees(math.atan2(major_axis.y, major_axis.x))

        # Be careful with the sweep flag
        _diff = edge.ParameterRange[1] - edge.ParameterRange[0]
        _diff = _diff / math.pi
        flag_large_arc = (_diff % 2) > 1

        # SVG selects one of two possible circle/ellipse centres from the
        # endpoints, radii and flags. Determine the sweep in the emitted 2D
        # coordinate system. A 3D tangent angle has the opposite sign for the
        # SVG sweep convention and also misses traversal reversals introduced
        # while joining edges into a path.
        first_point = edge.valueAt(edge.FirstParameter)
        last_point = edge.valueAt(edge.LastParameter)
        emitted_start = verts[0].Point
        first_distance = (emitted_start - first_point).Length
        last_distance = (emitted_start - last_point).Length
        if first_distance <= last_distance:
            tangent = edge.tangentAt(edge.FirstParameter)
        else:
            tangent = -edge.tangentAt(edge.LastParameter)
        projected_start = get_proj(emitted_start, plane)
        projected_center = get_proj(center.Center, plane)
        projected_tangent = get_proj(tangent, plane)
        radial = projected_start - projected_center
        sweep_cross_product = radial.x * projected_tangent.y
        sweep_cross_product -= radial.y * projected_tangent.x
        flag_sweep = sweep_cross_product > 0

        for v in endpoints:
            edata += (
                "A {} {} {} "
                "{} {} "
                "{} {} ".format(rx, ry, rot, int(flag_large_arc), int(flag_sweep), v.x, v.y)
            )

    return "edata", edata


def _get_path_bspline(plane, edge, edata):
    """Convert the edge to a BSpline and discretize it."""
    bspline = edge.Curve.toBSpline(edge.FirstParameter, edge.LastParameter)
    if bspline.Degree > 3 or bspline.isRational():
        try:
            bspline = bspline.approximateBSpline(0.05, 50, 3, "C0")
        except RuntimeError:
            _wrn("Debug: unable to approximate bspline from edge")

    if bspline.Degree <= 3 and not bspline.isRational():
        for bezierseg in bspline.toBezier():
            if bezierseg.Degree > 3:  # should not happen
                _wrn("Bezier segment of degree > 3")
                raise AssertionError
            elif bezierseg.Degree == 1:
                edata += "L "
            elif bezierseg.Degree == 2:
                edata += "Q "
            elif bezierseg.Degree == 3:
                edata += "C "

            for pole in bezierseg.getPoles()[1:]:
                v = get_proj(pole, plane)
                edata += "{} {} ".format(v.x, v.y)
    else:
        _msg(
            "Debug: one edge (hash {}) "
            "has been discretized "
            "with parameter 0.1".format(edge.hashCode())
        )

        for linepoint in bspline.discretize(0.1)[1:]:
            v = get_proj(linepoint, plane)
            edata += "L {} {} ".format(v.x, v.y)

    return edata


def get_circle(plane, fill, stroke, linewidth, lstyle, edge):
    """Get the SVG representation from a circular edge."""
    cen = get_proj(edge.Curve.Center, plane)
    rad = edge.Curve.Radius

    if plane:
        drawing_plane_normal = plane.axis
    else:
        drawing_plane_normal = WorkingPlane.get_working_plane(update=False).axis

    if round(edge.Curve.Axis.getAngle(drawing_plane_normal), 2) in [0, 3.14]:
        # Perpendicular projection: circle
        svg = "<circle "
        svg += 'cx="{}" cy="{}" r="{}" '.format(cen.x, cen.y, rad)
    else:
        # Any other projection: ellipse
        svg = '<path d="{}" '.format(get_discretized(edge, plane))

    svg += 'stroke="{}" '.format(stroke)
    # Editor: why is stroke-width repeated? Is this really necessary
    # for the generated SVG?
    svg += 'stroke-width="{}px" '.format(linewidth)
    svg += 'style="'
    svg += "stroke-width:{};".format(linewidth)
    svg += "stroke-miterlimit:4;"
    svg += "stroke-dasharray:{};".format(lstyle)
    svg += "stroke-linecap:square;"
    svg += "fill:{}".format(fill) + '"'
    svg += "/>\n"
    return svg


def getCircle(plane, fill, stroke, linewidth, lstyle, edge):
    """Get the SVG representation from a circular edge."""
    utils.use_instead("get_circle")
    return get_circle(plane, fill, stroke, linewidth, lstyle, edge)


def get_ellipse(plane, fill, stroke, linewidth, lstyle, edge):
    """Get the SVG representation from an elliptical edge."""
    cen = get_proj(edge.Curve.Center, plane)
    mir = edge.Curve.MinorRadius
    mar = edge.Curve.MajorRadius
    svg = "<ellipse "
    svg += 'cx="{}" cy="{}" '.format(cen.x, cen.y)
    svg += 'rx="{}" ry="{}" '.format(mar, mir)
    svg += 'stroke="{}" '.format(stroke)
    svg += 'stroke-width="{}px" '.format(linewidth)
    svg += 'style="'
    svg += "stroke-width:{};".format(linewidth)
    svg += "stroke-miterlimit:4;"
    svg += "stroke-dasharray:{};".format(lstyle)
    svg += "stroke-linecap:square;"
    svg += "fill:{}".format(fill) + '"'
    svg += "/>\n"
    return svg


def getEllipse(plane, fill, stroke, linewidth, lstyle, edge):
    """Get the SVG representation from an elliptical edge. DEPRECATED."""
    utils.use_instead("get_ellipse")
    return get_ellipse(plane, fill, stroke, linewidth, lstyle, edge)


def get_path(
    obj,
    plane,
    fill,
    pathdata,
    stroke,
    linewidth,
    lstyle,
    fill_opacity=None,
    edges=[],
    wires=[],
    pathname=None,
):
    """Get the SVG representation from an object's edges or wires.

    TODO: the `edges` and `wires` must not default to empty list `[]`
    but to `None`. Verify that the code doesn't break with this change.

    `edges` and `wires` are mutually exclusive. If no `wires` are provided,
    sort the `edges`, and use them. If `wires` are provided, sort the edges
    in these `wires`, and use them.
    """
    svg = "<path "

    if pathname is None:
        svg += 'id="{}" '.format(obj.Name)
    elif pathname != "":
        svg += 'id="{}" '.format(pathname)

    svg += ' d="'

    if not wires:
        egroups = Part.sortEdges(edges)
    else:
        egroups = []
        first = True
        for w in wires:
            wire = w.copy()
            if first:
                first = False
            else:
                # invert further wires to create holes
                wire = geo_edges.invert(wire)

            wire.fixWire()
            egroups.append(Part.__sortEdges__(wire.Edges))

    for _edges in egroups:
        edata = ""

        for edgeindex, edge in enumerate(_edges):
            if edgeindex == 0:
                verts = edge.Vertexes
                if len(_edges) > 1:
                    last_pt = verts[-1].Point
                    nextverts = _edges[1].Vertexes
                    if (last_pt - nextverts[0].Point).Length > 1e-6 and (
                        last_pt - nextverts[-1].Point
                    ).Length > 1e-6:
                        verts.reverse()
                v = get_proj(verts[0].Point, plane)
                edata += "M {} {} ".format(v.x, v.y)
            else:
                previousverts = verts
                verts = edge.Vertexes
                if (verts[0].Point - previousverts[-1].Point).Length > 1e-6:
                    verts.reverse()
                    if (verts[0].Point - previousverts[-1].Point).Length > 1e-6:
                        raise ValueError("edges not ordered")

            iscircle = geo_general.geomType(edge) == "Circle"
            isellipse = geo_general.geomType(edge) == "Ellipse"

            if iscircle or isellipse:
                _type, data = _get_path_circ_ellipse(
                    plane,
                    edge,
                    verts,
                    edata,
                    iscircle,
                    isellipse,
                    fill,
                    stroke,
                    linewidth,
                    lstyle,
                    allow_final_svg=len(egroups) == 1 and len(_edges) == 1,
                )
                if _type == "svg":
                    # final svg string already calculated, so just return it
                    return data

                # else the `edata` was properly augmented, so re-assing it
                edata = data
            elif geo_general.geomType(edge) == "Line":
                v = get_proj(verts[-1].Point, plane)
                edata += "L {} {} ".format(v.x, v.y)
            else:
                # If it's not a circle nor ellipse nor straight line
                # convert the curve to BSpline
                edata = _get_path_bspline(plane, edge, edata)

        if fill != "none":
            edata += "Z "

        if edata in pathdata:
            # do not draw a path on another identical path
            return ""
        else:
            svg += edata
            pathdata.append(edata)

    svg += '" '
    svg += 'stroke="{}" '.format(stroke)
    svg += 'stroke-width="{}px" '.format(linewidth)
    svg += 'style="'
    svg += "stroke-width:{};".format(linewidth)
    svg += "stroke-miterlimit:4;"
    svg += "stroke-dasharray:{};".format(lstyle)
    svg += "stroke-linecap:square;"
    svg += "fill:{};".format(fill)
    # fill_opacity must be a number, but if it's `None` it is omitted
    if fill_opacity is not None:
        svg += "fill-opacity:{};".format(fill_opacity)

    svg += 'fill-rule: evenodd"'
    svg += "/>\n"
    return svg


def getPath(
    obj,
    plane,
    fill,
    pathdata,
    stroke,
    linewidth,
    lstyle,
    fill_opacity,
    edges=[],
    wires=[],
    pathname=None,
):
    """Get the SVG representation from a path. DEPRECATED."""
    utils.use_instead("get_path")
    return get_path(
        obj,
        plane,
        fill,
        pathdata,
        stroke,
        linewidth,
        lstyle,
        fill_opacity,
        edges=edges,
        wires=wires,
        pathname=pathname,
    )


## @}
