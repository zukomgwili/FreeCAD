# SPDX-License-Identifier: LGPL-2.1-or-later

"""Resolve scalar point springs or ports of explicit native rigid-body couplings."""

import hashlib
import math
import re

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


def rigid_body_node_ids(analysis, mesh, body):
    """Match native rigid-body allocation, including meshes with sparse node IDs."""
    base = max(mesh.FemMesh.Nodes, default=0) + 2 * analysis.Group.index(body)
    return base + 1, base + 2


def rigid_body_nodes(body, mesh):
    """Validate user-selected solid-mesh regions; never infer a coupling region."""
    if body is None or not body.isDerivedFrom("Fem::ConstraintRigidBody"):
        raise ValueError("Each port requires an existing native Rigid Body object.")
    if not body.References:
        raise ValueError("Rigid Body ports require explicit CAD region references.")
    if not mesh.FemMesh.Volumes:
        raise ValueError("Rigid Body connector ports require a 3D solid mesh, not shells or beams.")
    for owner, names in body.References:
        if owner is None or not names:
            raise ValueError("Rigid Body region references must be explicit and resolvable.")
        for name in names:
            _, mapped, indexed = owner.resolveSubElement(name)
            if not mapped and (";" in name or re.fullmatch(
                    r"(?:Vertex|Edge|Face|Solid)[1-9][0-9]*", indexed) is None):
                raise ValueError(f"Unresolved Rigid Body region {owner.Name}.{name}.")
    nodes = set(meshtools.get_femnodes_by_femobj_with_references(
        mesh.FemMesh, {"Object": body}, mesh))
    if not nodes:
        raise ValueError("Rigid Body region has no mesh nodes.")
    points = [mesh.FemMesh.Nodes[node] for node in sorted(nodes)]
    if len(points) < 3:
        raise ValueError("A rigid port requires at least three non-collinear solid-mesh nodes.")
    origin = points[0]
    vectors = [point - origin for point in points[1:]]
    scale = max(vector.Length for vector in vectors)
    if not math.isfinite(scale) or scale == 0:
        raise ValueError("Rigid port node coordinates must be finite and non-collinear.")
    direction = max(vectors, key=lambda vector: vector.Length)
    if not any(direction.cross(vector).Length > 1e-10 * scale * scale for vector in vectors):
        raise ValueError("Collinear rigid ports are unsupported; choose a non-collinear region.")
    volume_nodes = set()
    for element in mesh.FemMesh.Volumes:
        volume_nodes.update(mesh.FemMesh.getElementNodes(element))
    if not nodes.issubset(volume_nodes):
        raise ValueError("Every rigid port node must belong to the solid mesh.")
    if not all(math.isfinite(value) for point in points for value in point):
        raise ValueError("Rigid port node coordinates must be finite.")
    if not all(math.isfinite(value) for value in body.ReferenceNode):
        raise ValueError("Rigid Body reference position must be finite.")
    return nodes


def resolve_connector(obj, mesh, analysis=None):
    rotational = getattr(obj, "Kind", "Translational") == "Rotational"
    ports = getattr(obj, "Attachment", "Vertices") == "Rigid body ports"
    if rotational and not ports:
        raise ValueError("Rotational connectors require explicit Rigid Body ports.")
    stiffness = (obj.RotationalStiffness.getValueAs("N*mm/rad").Value if rotational
                 else obj.Stiffness.getValueAs("N/mm").Value)
    if not math.isfinite(stiffness) or stiffness <= 0:
        raise ValueError("Connector stiffness must be explicitly supplied, finite and positive.")
    result = {"stiffness": stiffness, "rotation": connector_rotation(obj),
              "dof": ("X", "Y", "Z").index(obj.Axis) + 1, "rotational": rotational}
    if ports:
        if (obj.End1 and obj.End1[0]) or (obj.End2 and obj.End2[0]):
            raise ValueError("Rigid Body port attachment requires empty vertex endpoints.")
        bodies = [obj.RigidBody1]
        if obj.Mode == "Two points":
            bodies.append(obj.RigidBody2)
            if bodies[0] == bodies[1]:
                raise ValueError("The connector requires two distinct Rigid Body ports.")
        elif obj.RigidBody2:
            raise ValueError("Ground mode requires an empty RigidBody2.")
        regions = []
        for body in bodies:
            regions.append(rigid_body_nodes(body, mesh))
            if analysis is not None and body not in analysis.Group:
                raise ValueError("Rigid Body ports must belong to the same analysis.")
        if len(regions) == 2 and regions[0].intersection(regions[1]):
            raise ValueError("Rigid Body connector regions must not overlap.")
        result.update(bodies=bodies, regions=regions, nodes=[])
        return result
    if getattr(obj, "RigidBody1", None) or getattr(obj, "RigidBody2", None):
        raise ValueError("Vertex attachment requires empty Rigid Body port links.")
    nodes = [endpoint_node(obj.End1, mesh)]
    if obj.Mode == "Two points":
        nodes.append(endpoint_node(obj.End2, mesh))
        if nodes[0] == nodes[1]:
            raise ValueError("A two-point connector requires two distinct mesh nodes.")
    elif obj.End2 and obj.End2[0]:
        raise ValueError("Ground mode requires an empty End2; do not ignore a linked endpoint.")
    result["nodes"] = nodes
    return result


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
    if not objects:
        return errors
    materials = get_member(analysis, "Fem::MaterialCommon")
    materials += get_member(analysis, "Fem::MaterialReinforced")
    active_nonlinearity = solver.MaterialNonlinearity and any(
        material.Nonlinear and not material.Nonlinear.Suppressed for material in materials
    )
    if objects and (solver.AnalysisType != "static" or solver.ModelSpace != "3D"
                    or solver.GeometricalNonlinearity or active_nonlinearity):
        errors.append("Elastic connectors require a linear, small-displacement 3D static analysis.")
    for obj in objects:
        reserved = {identifier(f"EC_END{end}_", obj).upper() for end in (1, 2)}
        if any(other != obj and other.Name.upper() in reserved for other in analysis.Group):
            errors.append(f"{obj.Label}: connector node-set name collides with an analysis object.")
        if mesh:
            try:
                resolve_connector(obj, mesh, analysis)
            except (ValueError, TypeError, AttributeError, RuntimeError) as error:
                errors.append(f"{obj.Label}: {error}")
    port_objects = [obj for obj in objects
                    if getattr(obj, "Attachment", "Vertices") == "Rigid body ports"]
    if port_objects and mesh:
        if get_member(analysis, "Fem::ElementGeometry1D") or get_member(
                analysis, "Fem::ElementGeometry2D"):
            errors.append("Rigid Body connector ports are qualified for solid-only analyses.")
        occupied = {}
        for body in get_member(analysis, "Fem::ConstraintRigidBody"):
            try:
                nodes = rigid_body_nodes(body, mesh)
            except (ValueError, TypeError, AttributeError, RuntimeError) as error:
                errors.append(f"{body.Label}: {error}")
                continue
            for node in nodes:
                if node in occupied:
                    errors.append(f"Rigid Body regions overlap at mesh node {node}.")
                    break
                occupied[node] = body
    return errors
