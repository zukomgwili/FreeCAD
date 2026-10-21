# SPDX-License-Identifier: LGPL-2.1-or-later

"""Resolve scalar point springs or ports of explicit native rigid-body couplings."""

import hashlib
import math
import re

import FreeCAD

from femmesh import meshtools


class PortResolutionContext:
    """Resolve current ports once during one synchronous validation/export.

    Native meshes can change without a document-property revision. This context
    must therefore be local to one operation, never stored on analysis objects or
    reused after an edit. Standalone public calls create their own fresh context.
    Coordinates and solid connectivity are materialized lazily, at most once;
    only fully validated receiving regions and native node IDs are retained.
    """

    def __init__(self, mesh, analysis=None):
        self.mesh = mesh
        self.analysis = analysis
        self.analysis_group = tuple(analysis.Group) if analysis is not None else ()
        self._femmesh = mesh.FemMesh
        self._coordinates = None
        self._max_node_id = None
        self._volumes = None
        self._volume_nodes = None
        self._regions = {}
        self._node_ids = {}
        self._generic_regions = {}
        self._body_states = {}
        self._connector_states = {}
        self._ownership = None
        self._ownership_initialized = False
        self._legacy_mesh = None

    @staticmethod
    def _mesh_state(mesh):
        """Exact mutable native state, without imposing CAD provenance on legacy meshes."""
        elements = tuple(mesh.getIdByElementType("All"))
        return (
            {node: tuple(point) for node, point in mesh.Nodes.items()},
            elements,
            {element: tuple(mesh.getElementNodes(element)) for element in elements},
            tuple(
                (
                    group,
                    mesh.getGroupName(group),
                    mesh.getGroupElementType(group),
                    tuple(mesh.getGroupElements(group)),
                )
                for group in mesh.Groups
            ),
            tuple(mesh.Faces),
            tuple(mesh.Edges),
            tuple(mesh.Volumes),
            tuple(mesh.getIdByElementType("0DElement")),
        )

    def _owned_facts(self):
        if not self._ownership_initialized:
            from femmesh.ownership_context import _for_mesh

            facts = _for_mesh(self._femmesh, self.mesh, kind="Rigid Body ports")
            nodes = facts.nodes if facts is not None else self._femmesh.Nodes
            volumes = facts._volumes if facts is not None else tuple(self._femmesh.Volumes)
            if self._coordinates is not None and not self._same_nodes(self._coordinates, nodes):
                raise ValueError("Mesh nodes changed before rigid port region resolution.")
            if self._volumes is not None and self._volumes != volumes:
                raise ValueError("Mesh volumes changed before rigid port region resolution.")
            if facts is None:
                self._legacy_mesh = self._mesh_state(self._femmesh)
                if self._legacy_mesh != self._mesh_state(self.mesh.FemMesh):
                    raise ValueError("Supplied mesh changed before rigid port resolution.")
            self._ownership = facts
            self._ownership_initialized = True
        return self._ownership

    @staticmethod
    def _same_nodes(first, second):
        return first.keys() == second.keys() and all(
            tuple(point) == tuple(second[node]) for node, point in first.items()
        )

    @staticmethod
    def _body_state(body):
        return (
            tuple((owner, tuple(names)) for owner, names in body.References),
            tuple(body.ReferenceNode),
            tuple(body.Displacement),
            tuple(body.Rotation.Q),
            body.EnableAmplitude,
            tuple(
                getattr(body, kind + "Mode" + axis)
                for kind in ("Translational", "Rotational")
                for axis in "XYZ"
            ),
            tuple(getattr(body, "Force" + axis).getValueAs("N").Value for axis in "XYZ"),
            tuple(getattr(body, "Moment" + axis).getValueAs("N*mm").Value for axis in "XYZ"),
        )

    @staticmethod
    def _connector_state(obj):
        kind = getattr(obj, "Kind", "Translational")
        return (
            getattr(obj, "Attachment", "Vertices"),
            obj.Mode,
            kind,
            obj.Axis,
            (
                obj.RotationalStiffness.getValueAs("N*mm/rad").Value
                if kind == "Rotational"
                else obj.Stiffness.getValueAs("N/mm").Value
            ),
            obj.RigidBody1,
            obj.RigidBody2,
            tuple(
                (reference[0], tuple(reference[1])) if reference else None
                for reference in (obj.End1, obj.End2)
            ),
            obj.OrientationReference,
            tuple(connector_rotation(obj).Q),
        )

    def _region_nodes(self, body):
        """Share owned facts, not the stricter solid/rank rules of a port."""
        if body not in self._body_states:
            self._body_states[body] = self._body_state(body)
        if body not in self._generic_regions:
            facts = self._owned_facts()
            nodes = meshtools._get_mesh_region_by_owned_references(
                self._femmesh, body, self.mesh, facts
            )[0]
            if facts is None:
                # Keep the established geometric classifier for every legacy
                # reference. Only owned, end-fenced entity facts are shared.
                return set(nodes)
            self._generic_regions[body] = frozenset(nodes)
        return set(self._generic_regions[body])

    def validate_unchanged(self):
        """Fence this operation before its results escape to a later call."""
        if self.analysis is not None and tuple(self.analysis.Group) != self.analysis_group:
            raise ValueError(
                "Analysis order changed during rigid port resolution; retry the writer."
            )
        if any(self._body_state(body) != state for body, state in self._body_states.items()):
            raise ValueError("Rigid Body references or properties changed during port resolution.")
        if any(
            self._connector_state(obj) != state for obj, state in self._connector_states.items()
        ):
            raise ValueError(
                "Elastic Connector references or properties changed during resolution."
            )
        if self._ownership is not None:
            self._ownership.validate_unchanged()
        else:
            # Legacy meshes do not acquire an owned-provenance requirement.
            # They still cannot change data already used by this operation.
            current = self.mesh.FemMesh
            if self._legacy_mesh is not None and (
                self._mesh_state(self._femmesh) != self._legacy_mesh
                or self._mesh_state(current) != self._legacy_mesh
            ):
                raise ValueError("Native mesh or groups changed during rigid port resolution.")
            if self._coordinates is not None and not self._same_nodes(
                current.Nodes, self._coordinates
            ):
                raise ValueError("Mesh nodes changed during rigid port resolution.")
            if self._volumes is not None and tuple(current.Volumes) != self._volumes:
                raise ValueError("Mesh volumes changed during rigid port resolution.")

    @property
    def max_node_id(self):
        self._nodes()
        return self._max_node_id

    def _nodes(self):
        if self._coordinates is None:
            # Allocation-only public calls do not add a CAD ownership
            # prerequisite. Region callers initialize/fence owned facts first.
            facts = self._ownership
            self._coordinates = facts.nodes if facts is not None else self._femmesh.Nodes
            self._max_node_id = max(self._coordinates, default=0)
        return self._coordinates

    def _solid_elements(self):
        if self._volumes is None:
            facts = self._owned_facts()
            self._volumes = facts._volumes if facts is not None else tuple(self._femmesh.Volumes)
        return self._volumes

    def _solid_nodes(self):
        if self._volume_nodes is None:
            self._volume_nodes = set()
            facts = self._owned_facts()
            for element in self._solid_elements():
                nodes = (
                    facts.elements[element]
                    if facts is not None
                    else tuple(self._femmesh.getElementNodes(element))
                )
                self._volume_nodes.update(nodes)
        return self._volume_nodes


def _resolution_context(mesh, analysis=None, context=None):
    if context is None:
        return PortResolutionContext(mesh, analysis)
    if context.mesh != mesh or (analysis is not None and context.analysis != analysis):
        raise ValueError("Port resolution context belongs to a different mesh or analysis.")
    return context


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


def rigid_body_node_ids(analysis, mesh, body, context=None):
    """Match native rigid-body allocation, including meshes with sparse node IDs."""
    local = context is None
    context = _resolution_context(mesh, analysis, context)
    if body not in context._node_ids:
        base = context.max_node_id + 2 * context.analysis_group.index(body)
        context._node_ids[body] = base + 1, base + 2
    result = context._node_ids[body]
    if local:
        context.validate_unchanged()
    return result


def rigid_body_nodes(body, mesh, context=None):
    """Validate user-selected solid-mesh regions; never infer a coupling region."""
    local = context is None
    context = _resolution_context(mesh, context=context)
    if body not in context._regions:
        context._regions[body] = frozenset(_validated_rigid_body_nodes(body, mesh, context))
    # Public callers historically receive mutable sets. Do not expose the
    # operation's verified cache to mutation through one connector's result.
    if local:
        context.validate_unchanged()
    return set(context._regions[body])


def _validated_rigid_body_nodes(body, mesh, context):
    if body is None or not body.isDerivedFrom("Fem::ConstraintRigidBody"):
        raise ValueError("Each port requires an existing native Rigid Body object.")
    if not body.References:
        raise ValueError("Rigid Body ports require explicit CAD region references.")
    if not context._solid_elements():
        raise ValueError("Rigid Body connector ports require a 3D solid mesh, not shells or beams.")
    for owner, names in body.References:
        if owner is None or not names:
            raise ValueError("Rigid Body region references must be explicit and resolvable.")
        for name in names:
            _, mapped, indexed = owner.resolveSubElement(name)
            if not mapped and (
                ";" in name
                or re.fullmatch(r"(?:Vertex|Edge|Face|Solid)[1-9][0-9]*", indexed) is None
            ):
                raise ValueError(f"Unresolved Rigid Body region {owner.Name}.{name}.")
    nodes = context._region_nodes(body)
    if not nodes:
        raise ValueError("Rigid Body region has no mesh nodes.")
    coordinates = context._nodes()
    points = [coordinates[node] for node in sorted(nodes)]
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
    if not nodes.issubset(context._solid_nodes()):
        raise ValueError("Every rigid port node must belong to the solid mesh.")
    if not all(math.isfinite(value) for point in points for value in point):
        raise ValueError("Rigid port node coordinates must be finite.")
    if not all(math.isfinite(value) for value in body.ReferenceNode):
        raise ValueError("Rigid Body reference position must be finite.")
    return nodes


def resolve_connector(obj, mesh, analysis=None, context=None):
    local = context is None
    rotational = getattr(obj, "Kind", "Translational") == "Rotational"
    ports = getattr(obj, "Attachment", "Vertices") == "Rigid body ports"
    if rotational and not ports:
        raise ValueError("Rotational connectors require explicit Rigid Body ports.")
    stiffness = (
        obj.RotationalStiffness.getValueAs("N*mm/rad").Value
        if rotational
        else obj.Stiffness.getValueAs("N/mm").Value
    )
    if not math.isfinite(stiffness) or stiffness <= 0:
        raise ValueError("Connector stiffness must be explicitly supplied, finite and positive.")
    result = {
        "stiffness": stiffness,
        "rotation": connector_rotation(obj),
        "dof": ("X", "Y", "Z").index(obj.Axis) + 1,
        "rotational": rotational,
    }
    if ports:
        context = _resolution_context(mesh, analysis, context)
        if obj not in context._connector_states:
            context._connector_states[obj] = context._connector_state(obj)
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
            regions.append(rigid_body_nodes(body, mesh, context))
            if analysis is not None and body not in analysis.Group:
                raise ValueError("Rigid Body ports must belong to the same analysis.")
        if len(regions) == 2 and regions[0].intersection(regions[1]):
            raise ValueError("Rigid Body connector regions must not overlap.")
        result.update(bodies=bodies, regions=regions, nodes=[])
        if local:
            context.validate_unchanged()
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


def validation_errors(analysis, solver, mesh, context=None):
    from .membertools import get_member
    from .rigid_body import validation_diagnostics

    errors = []
    if mesh:
        context = _resolution_context(mesh, analysis, context)

    def complete():
        if context is not None:
            try:
                context.validate_unchanged()
            except (ValueError, TypeError, AttributeError, RuntimeError) as error:
                errors.append(str(error))
        return errors

    for diagnostic in validation_diagnostics(analysis, solver, mesh, context=context):
        if diagnostic["severity"] == "error":
            errors.append(diagnostic["message"])
        elif diagnostic["severity"] == "warning":
            FreeCAD.Console.PrintWarning(diagnostic["message"] + "\n")
    if get_member(analysis, "Fem::ConstraintSpring"):
        errors.append(
            "The existing Spring is an Elmer foundation; use an Elastic Connector "
            "for a concentrated CalculiX spring."
        )
    objects = connectors(analysis)
    if not objects:
        return complete()
    materials = get_member(analysis, "Fem::MaterialCommon")
    materials += get_member(analysis, "Fem::MaterialReinforced")
    active_nonlinearity = solver.MaterialNonlinearity and any(
        material.Nonlinear and not material.Nonlinear.Suppressed for material in materials
    )
    if objects and (
        solver.AnalysisType != "static"
        or solver.ModelSpace != "3D"
        or solver.GeometricalNonlinearity
        or active_nonlinearity
    ):
        errors.append("Elastic connectors require a linear, small-displacement 3D static analysis.")
    for obj in objects:
        reserved = {identifier(f"EC_END{end}_", obj).upper() for end in (1, 2)}
        if any(other != obj and other.Name.upper() in reserved for other in analysis.Group):
            errors.append(f"{obj.Label}: connector node-set name collides with an analysis object.")
        if mesh:
            try:
                resolve_connector(obj, mesh, analysis, context)
            except (ValueError, TypeError, AttributeError, RuntimeError) as error:
                errors.append(f"{obj.Label}: {error}")
    port_objects = [
        obj for obj in objects if getattr(obj, "Attachment", "Vertices") == "Rigid body ports"
    ]
    if port_objects and mesh:
        if get_member(analysis, "Fem::ElementGeometry1D") or get_member(
            analysis, "Fem::ElementGeometry2D"
        ):
            errors.append("Rigid Body connector ports are qualified for solid-only analyses.")
        occupied = {}
        for body in get_member(analysis, "Fem::ConstraintRigidBody"):
            try:
                nodes = rigid_body_nodes(body, mesh, context)
            except (ValueError, TypeError, AttributeError, RuntimeError) as error:
                errors.append(f"{body.Label}: {error}")
                continue
            for node in nodes:
                if node in occupied:
                    errors.append(f"Rigid Body regions overlap at mesh node {node}.")
                    break
                occupied[node] = body
    return complete()
