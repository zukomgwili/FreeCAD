# SPDX-License-Identifier: LGPL-2.1-or-later

"""Export scalar point/explicit rigid-body port springs without mutating the mesh."""

import FreeCAD

from femtools import elastic_connector


def write_connectors(f, writer):
    mesh = writer.mesh_object
    # The full writer owns one fresh context for this export. Direct callers
    # receive a local context on every call, even when reusing a writer object.
    context = getattr(writer, "port_resolution_context", None)
    if context is None:
        context = elastic_connector.PortResolutionContext(mesh, getattr(writer, "analysis", None))
    # Private export metadata binds accounting to the exact native element and
    # angular auxiliary identities written below. It never changes the mesh,
    # model constraints, ordinary deck or ordinary result channels.
    writer.native_accounting_springs = []
    ids = list(mesh.FemMesh.Edges) + list(mesh.FemMesh.Faces) + list(mesh.FemMesh.Volumes)
    next_id = max(ids, default=0) + 1
    next_node = None
    for item in writer.member.cons_elasticconnector:
        obj = item["Object"]
        data = elastic_connector.resolve_connector(
            obj, mesh, getattr(writer, "analysis", None), context
        )
        elset = elastic_connector.identifier("EC_", obj)
        orientation = elastic_connector.identifier("EC_ORIENT_", obj)
        nodes = data["nodes"]
        if "bodies" in data:
            ports = [
                elastic_connector.rigid_body_node_ids(writer.analysis, mesh, body, context)
                for body in data["bodies"]
            ]
            nodes = [port[1 if data["rotational"] else 0] for port in ports]
        output_nodes = nodes
        angular_bindings = []
        if data["rotational"]:
            # A CalculiX rotational node must not belong to an element. Couple
            # a scalar auxiliary DOF to its selected global rotation projection.
            # This is an algebraic port, not a translational spring/lever model.
            if next_node is None:
                next_node = context.max_node_id + 2 * len(context.analysis_group) + 1
            axis = data["rotation"].multVec(
                (FreeCAD.Vector(1, 0, 0), FreeCAD.Vector(0, 1, 0), FreeCAD.Vector(0, 0, 1))[
                    data["dof"] - 1
                ]
            )
            auxiliary = []
            for node in nodes:
                auxiliary.append(next_node)
                angular_bindings.append((next_node, node, tuple(axis)))
                f.write(f"\n*NODE\n{next_node},0.,0.,0.\n")
                terms = [f"{next_node},1,1."]
                terms += [
                    f"{node},{index + 1},{-value:.12e}"
                    for index, value in enumerate(axis)
                    if abs(value) > 1e-14
                ]
                f.write(f"*EQUATION\n{len(terms)}\n" + ",".join(terms) + "\n")
                # SPRING1/2 activate three DOFs on an auxiliary node. Only its
                # scalar DOF1 has meaning; these are not physical body restraints.
                f.write(f"*BOUNDARY\n{next_node},2,3,0.\n")
                next_node += 1
            nodes = auxiliary
        kind = "SPRING1" if len(nodes) == 1 else "SPRING2"
        writer.native_accounting_springs.append(
            {
                "name": obj.Name,
                "element": next_id,
                "nodes": tuple(nodes),
                "kind": kind,
                "bodies": tuple(body.Name for body in data.get("bodies", ())),
                "angles": tuple(angular_bindings),
            }
        )
        f.write(f"\n*ELEMENT, TYPE={kind}, ELSET={elset}\n")
        f.write(",".join(str(value) for value in [next_id] + nodes) + "\n")
        next_id += 1
        if data["rotational"]:
            f.write("** Scalar rotational stiffness in N*mm/rad; auxiliary U is an angle\n")
            f.write(f"*SPRING, ELSET={elset}\n")
        else:
            rotation = data["rotation"]
            axes = list(rotation.multVec(FreeCAD.Vector(1, 0, 0)))
            axes += list(rotation.multVec(FreeCAD.Vector(0, 1, 0)))
            f.write(f"*ORIENTATION, NAME={orientation}\n")
            f.write(",".join(f"{value:.13G}" for value in axes) + "\n")
            f.write(f"*SPRING, ELSET={elset}, ORIENTATION={orientation}\n")
        dof = 1 if data["rotational"] else data["dof"]
        f.write(",".join([str(dof)] * len(nodes)) + "\n")
        # CalculiX identifies real spring data by a decimal point.
        f.write(f"{data['stiffness']:.12e}\n")
        for end, node in enumerate(output_nodes, 1):
            nset = elastic_connector.identifier(f"EC_END{end}_", obj)
            f.write(f"*NSET, NSET={nset}\n{node}\n")


def write_output(f, writer):
    """Request raw node values, not separated forces for a connected assembly."""
    for item in writer.member.cons_elasticconnector:
        obj = item["Object"]
        count = 1 if obj.Mode == "Ground" else 2
        for end in range(1, count + 1):
            nset = elastic_connector.identifier(f"EC_END{end}_", obj)
            if getattr(obj, "Kind", "Translational") == "Rotational":
                f.write("\n** Rotational port: U is radians, RF is N*mm (global components)\n")
            else:
                f.write("\n** Translational port: U is mm, RF is N (global components)\n")
            f.write("** RF is not generally an isolated connector-action result\n")
            f.write(f"\n*NODE PRINT, NSET={nset}, GLOBAL=YES\nU,RF\n")
