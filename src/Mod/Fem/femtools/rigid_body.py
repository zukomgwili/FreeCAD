# SPDX-License-Identifier: LGPL-2.1-or-later

"""Owner-aware standalone RBE preflight, not an MPC or mechanics solver.

CalculiX may omit repeated dependent-node equations and still return zero.
Disjoint regions are unambiguous. Matching fully prescribed pure translations
have compatible shared-node kinematics; conflicting ones do not. Other overlap
modes are reported as unqualified warnings, not universally rejected. Connector
ports retain their separately qualified, stricter solid/non-collinear domain.
No writer equations, RF semantics or port allocation are changed here.
"""

from itertools import combinations
import math

from .membertools import get_member


def _prescribed_translation(body):
    if body.EnableAmplitude:
        return None
    if not all(
        getattr(body, kind + axis) == "Constraint"
        for kind in ("TranslationalMode", "RotationalMode")
        for axis in "XYZ"
    ):
        return None
    if body.Rotation.Angle != 0:
        return None
    # Match the unchanged stock step writer's exported values, not a new tolerance.
    return tuple(float(f"{value:.13G}") for value in body.Displacement)


def validation_diagnostics(analysis, solver, mesh, context=None):
    """Structured identity/ownership errors and bounded compatibility warnings."""
    if mesh is None:
        return []  # The ordinary analysis prerequisite owns missing-mesh errors.
    result = []
    regions = {}
    allocated = set()
    from .elastic_connector import rigid_body_node_ids, _resolution_context

    local = context is None
    context = _resolution_context(mesh, analysis, context)

    def report(severity, bodies, message, nodes=()):
        result.append(
            {
                "severity": severity,
                "objects": [body.Name for body in bodies],
                "nodes": sorted(nodes),
                "message": message,
            }
        )

    for body in get_member(analysis, "Fem::ConstraintRigidBody"):
        try:
            if not body.References:
                raise ValueError("Rigid Body requires explicit resolvable CAD references.")
            values = (
                *body.ReferenceNode,
                *body.Displacement,
                *body.Rotation.Axis,
                body.Rotation.Angle,
                *(getattr(body, "Force" + axis).getValueAs("N").Value for axis in "XYZ"),
                *(getattr(body, "Moment" + axis).getValueAs("N*mm").Value for axis in "XYZ"),
            )
            if not all(math.isfinite(value) for value in values):
                raise ValueError("Rigid Body position, motion and loads must be finite.")
            nodes = context._region_nodes(body)
            if not nodes:
                raise ValueError("Rigid Body region has no current mesh nodes.")
            ids = rigid_body_node_ids(analysis, mesh, body, context)
            if (
                len(set(ids)) != 2
                or allocated.intersection(ids)
                or set(ids).intersection(context._nodes())
            ):
                raise ValueError("Rigid Body external reference/rotation node identities collide.")
            allocated.update(ids)
            regions[body] = nodes
        except (ValueError, TypeError, AttributeError, RuntimeError) as error:
            report("error", [body], f"{body.Label}: {error}")

    for first, second in combinations(regions, 2):
        shared = regions[first].intersection(regions[second])
        if not shared:
            continue
        left, right = _prescribed_translation(first), _prescribed_translation(second)
        names = f"{first.Label} / {second.Label}"
        if left is not None and right is not None:
            if left != right:
                report(
                    "error",
                    [first, second],
                    f"{names}: incompatible prescribed translations at shared Rigid Body "
                    f"mesh nodes (first {min(shared)}); use compatible regions/motions.",
                    shared,
                )
            else:
                report(
                    "info",
                    [first, second],
                    f"{names}: shared nodes have matching fully prescribed pure translations; "
                    "native duplicate-MPC warnings do not add a new motion constraint.",
                    shared,
                )
        else:
            report(
                "warning",
                [first, second],
                f"{names}: shared Rigid Body slave nodes (first {min(shared)}); compatibility "
                "is unqualified for these modes/amplitudes. CalculiX can omit repeated MPC "
                "equations; inspect native warnings and verify the intended motion.",
                shared,
            )
    if local:
        try:
            context.validate_unchanged()
        except (ValueError, TypeError, AttributeError, RuntimeError) as error:
            report("error", list(regions), str(error))
    return result
