# SPDX-License-Identifier: LGPL-2.1-or-later

"""Validate and resolve one explicit, concentrated translational connector."""

import hashlib
import math

import FreeCAD

from femmesh import meshtools


def identifier(prefix, obj):
    name = prefix + obj.Name
    if len(name) > 80:
        name = name[:67] + "_" + hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]
    return name


def connector_rotation(obj):
    rotation = obj.Orientation
    reference = obj.OrientationReference
    if reference:
        if reference == obj or "Placement" not in reference.PropertiesList:
            raise ValueError("Connector orientation reference must be a placed object.")
        placement = reference.Placement
        parent = reference.getParentGeoFeatureGroup()
        while parent:
            placement = parent.Placement * placement
            parent = parent.getParentGeoFeatureGroup()
        rotation = placement.Rotation * rotation
    for vector in (FreeCAD.Vector(1, 0, 0), FreeCAD.Vector(0, 1, 0)):
        if not all(math.isfinite(value) for value in rotation.multVec(vector)):
            raise ValueError("Connector orientation must be finite.")
    return rotation


def endpoint_node(reference, mesh):
    if not reference or not reference[0] or len(reference[1]) != 1:
        raise ValueError("Each connector endpoint requires one linked CAD vertex.")
    shape = meshtools.sub_shape_at_global_placement(reference[0], reference[1][0])
    if shape.ShapeType != "Vertex":
        raise ValueError("Connector endpoints must be vertices, not distributed regions.")
    nodes = mesh.FemMesh.getNodesByVertex(shape)
    if len(nodes) != 1:
        raise ValueError("Connector vertex must resolve to exactly one mesh node.")
    return nodes[0]


def resolve_connector(obj, mesh):
    stiffness = obj.Stiffness.getValueAs("N/mm").Value
    if not math.isfinite(stiffness) or stiffness <= 0:
        raise ValueError("Connector stiffness must be explicitly supplied, finite and positive.")
    nodes = [endpoint_node(obj.End1, mesh)]
    if obj.Mode == "Two points":
        nodes.append(endpoint_node(obj.End2, mesh))
        if nodes[0] == nodes[1]:
            raise ValueError("A two-point connector requires two distinct mesh nodes.")
    elif obj.End2 and obj.End2[0]:
        raise ValueError("Ground mode requires an empty End2; do not ignore a linked endpoint.")
    return {"nodes": nodes, "stiffness": stiffness, "rotation": connector_rotation(obj),
            "dof": ("X", "Y", "Z").index(obj.Axis) + 1}


def connectors(analysis):
    from .membertools import get_member
    return get_member(analysis, "Fem::ConstraintElasticConnector")


def reject_unsupported(analysis, solver_name):
    if analysis is not None and connectors(analysis):
        raise ValueError(f"Native elastic connectors are not supported by {solver_name} export.")


def validation_errors(analysis, solver, mesh):
    from .membertools import get_member
    errors = []
    if get_member(analysis, "Fem::ConstraintSpring"):
        errors.append("The existing Spring is an Elmer foundation; use an Elastic Connector "
                      "for a concentrated CalculiX spring.")
    objects = connectors(analysis)
    if objects and (solver.AnalysisType != "static" or solver.ModelSpace != "3D"
                    or solver.GeometricalNonlinearity):
        errors.append("Elastic connectors require a linear, small-displacement 3D static analysis.")
    for obj in objects:
        reserved = {identifier(f"EC_END{end}_", obj).upper() for end in (1, 2)}
        if any(other != obj and other.Name.upper() in reserved for other in analysis.Group):
            errors.append(f"{obj.Label}: connector node-set name collides with an analysis object.")
        if mesh:
            try:
                resolve_connector(obj, mesh)
            except (ValueError, TypeError, AttributeError, RuntimeError) as error:
                errors.append(f"{obj.Label}: {error}")
    return errors
