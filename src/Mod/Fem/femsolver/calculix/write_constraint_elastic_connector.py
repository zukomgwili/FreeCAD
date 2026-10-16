# SPDX-License-Identifier: LGPL-2.1-or-later

"""Export native concentrated springs, without changing the source mesh."""

import FreeCAD

from femtools import elastic_connector


def write_connectors(f, writer):
    mesh = writer.mesh_object
    ids = list(mesh.FemMesh.Edges) + list(mesh.FemMesh.Faces) + list(mesh.FemMesh.Volumes)
    next_id = max(ids, default=0) + 1
    for item in writer.member.cons_elasticconnector:
        obj = item["Object"]
        data = elastic_connector.resolve_connector(obj, mesh)
        elset = elastic_connector.identifier("EC_", obj)
        orientation = elastic_connector.identifier("EC_ORIENT_", obj)
        kind = "SPRING1" if len(data["nodes"]) == 1 else "SPRING2"
        f.write(f"\n*ELEMENT, TYPE={kind}, ELSET={elset}\n")
        f.write(",".join(str(value) for value in [next_id] + data["nodes"]) + "\n")
        next_id += 1
        rotation = data["rotation"]
        axes = list(rotation.multVec(FreeCAD.Vector(1, 0, 0)))
        axes += list(rotation.multVec(FreeCAD.Vector(0, 1, 0)))
        f.write(f"*ORIENTATION, NAME={orientation}\n")
        f.write(",".join(f"{value:.13G}" for value in axes) + "\n")
        f.write(f"*SPRING, ELSET={elset}, ORIENTATION={orientation}\n")
        f.write(",".join([str(data["dof"])] * len(data["nodes"])) + "\n")
        # CalculiX identifies real spring data by a decimal point.
        f.write(f"{data['stiffness']:.12e}\n")
        for end, node in enumerate(data["nodes"], 1):
            nset = elastic_connector.identifier(f"EC_END{end}_", obj)
            f.write(f"*NSET, NSET={nset}\n{node}\n")


def write_output(f, writer):
    """Request raw node values, not separated forces for a connected assembly."""
    for item in writer.member.cons_elasticconnector:
        obj = item["Object"]
        count = 1 if obj.Mode == "Ground" else 2
        for end in range(1, count + 1):
            nset = elastic_connector.identifier(f"EC_END{end}_", obj)
            f.write("\n** Connector node U/RF; RF is not an isolated connector-force result\n")
            f.write(f"\n*NODE PRINT, NSET={nset}, GLOBAL=YES\nU,RF\n")
