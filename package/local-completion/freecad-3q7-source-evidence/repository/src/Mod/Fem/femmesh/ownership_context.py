# SPDX-License-Identifier: LGPL-2.1-or-later

"""Short-lived, exact ownership validation for one interface gathering batch.

Native meshes are mutable without a document-property revision.  Keep this
context local to one synchronous batch, and validate again before publishing its
results.  A native mesh copy cannot replace these snapshots: copying can omit
empty groups and unresolvable group members.
"""


class _OwnershipContext:
    def __init__(self, femmesh, mesh_object, getter=None, kind="Contact", *, canonical_only=False):
        self.femmesh = femmesh
        self.mesh_object = mesh_object
        self._kind = kind
        self._canonical_only = canonical_only
        self.part, self._names, self._references, self._signature = self._provenance()
        if not self.part:
            raise ValueError("Missing mesh geometry owner; regenerate the mesh.")
        if (
            not self._names
            or not self._references
            or not self._signature
            or len(self._names) != len(self._references)
            or len(self._names) != len(set(self._names))
        ):
            raise ValueError("Invalid mesh group provenance; regenerate the mesh.")
        if not self._geometry_matches():
            raise ValueError("References select changed mesh geometry; regenerate the mesh.")

        self.current_groups = {}
        for original, (owner, current) in zip(self._names, self._references):
            if owner != self.part:
                raise ValueError("Changed mesh geometry owner; regenerate the mesh.")
            self.current_groups.setdefault(current, []).append(original)

        # Nodes contains detached vectors in world coordinates.  Retain only one
        # complete snapshot; comparisons below release their temporary data.
        self.nodes = femmesh.Nodes
        self._element_ids = tuple(femmesh.getIdByElementType("All"))
        self.elements = {
            element: tuple(femmesh.getElementNodes(element)) for element in self._element_ids
        }
        self._group_ids = tuple(femmesh.Groups)
        self.groups = {group: self._group_data(femmesh, group) for group in self._group_ids}
        self.faces = set(femmesh.Faces)
        self.edges = set(femmesh.Edges)
        self.vertices = set(femmesh.getIdByElementType("0DElement"))
        self._volumes = tuple(femmesh.Volumes)
        # Match the stock getter's highest-dimensional element table. Generic
        # RBEs also support shell/beam meshes, unlike solid connector ports.
        self._table_elements = set(self._volumes or self.faces or self.edges)
        self.group_ids = {}
        for group, (name, _kind, _members) in self.groups.items():
            self.group_ids.setdefault(name, []).append(group)
        self.regions = {}
        self._getter = getter

        own_mesh = mesh_object.FemMesh
        if own_mesh is not femmesh:
            self._validate_mesh(own_mesh)
        self._validate_getter()

    def _provenance(self):
        mesh_object = self.mesh_object
        return (
            getattr(mesh_object, "Shape", None),
            tuple(getattr(mesh_object, "ElementGroupNames", [])),
            tuple(
                (owner, name)
                for owner, names in getattr(mesh_object, "ElementGroupReferences", [])
                for name in names
            ),
            getattr(mesh_object, "ElementGroupGeometry", ""),
        )

    def _geometry_matches(self):
        from femmesh import meshtools

        if self._canonical_only:
            return self._signature == meshtools.get_mesh_geometry_signature(self.part)
        return meshtools.mesh_geometry_matches(self.mesh_object, self.part)

    @staticmethod
    def _group_data(mesh, group):
        return (
            mesh.getGroupName(group),
            mesh.getGroupElementType(group),
            tuple(mesh.getGroupElements(group)),
        )

    def _nodes_match(self, nodes):
        if self.nodes.keys() != nodes.keys():
            return False
        return all(
            (point.x, point.y, point.z) == (nodes[node].x, nodes[node].y, nodes[node].z)
            for node, point in self.nodes.items()
        )

    def _validate_mesh(self, mesh):
        if (
            not self._nodes_match(mesh.Nodes)
            or self._element_ids != tuple(mesh.getIdByElementType("All"))
            or self.faces != set(mesh.Faces)
            or self.edges != set(mesh.Edges)
            or self.vertices != set(mesh.getIdByElementType("0DElement"))
            or self._volumes != tuple(mesh.Volumes)
            or any(
                connectivity != tuple(mesh.getElementNodes(element))
                for element, connectivity in self.elements.items()
            )
        ):
            raise ValueError("Supplied mesh does not match its geometry owner or changed in batch.")
        if self._group_ids != tuple(mesh.Groups) or any(
            data != self._group_data(mesh, group) for group, data in self.groups.items()
        ):
            raise ValueError("Mesh groups do not match their geometry owner or changed in batch.")

    def _validate_getter(self):
        getter = self._getter
        if getter is None:
            return
        if (
            not self._nodes_match(getter.femnodes_mesh)
            or set(getter.femelement_table) != self._table_elements
            or any(
                tuple(getter.femelement_table[element]) != self.elements[element]
                for element in self._table_elements
            )
        ):
            raise ValueError(
                "Cached mesh tables do not match the current mesh; recreate the writer."
            )

    def validate_unchanged(self):
        """Reject changes before any of this batch's interface sets are published."""
        if (
            self.part,
            self._names,
            self._references,
            self._signature,
        ) != self._provenance() or not self._geometry_matches():
            raise ValueError(
                f"Mesh geometry owner or group provenance changed during {self._kind} batch."
            )
        self._validate_mesh(self.femmesh)
        own_mesh = self.mesh_object.FemMesh
        if own_mesh is not self.femmesh:
            self._validate_mesh(own_mesh)
        self._validate_getter()


def _for_mesh(femmesh, mesh_object, getter=None, kind="Rigid Body", *, canonical_only=False):
    """Keep provenance-free legacy resolution outside the owned-mesh domain."""
    if not any(
        getattr(mesh_object, name, None)
        for name in ("ElementGroupNames", "ElementGroupReferences", "ElementGroupGeometry")
    ):
        return None
    return _OwnershipContext(femmesh, mesh_object, getter, kind, canonical_only=canonical_only)
