# SPDX-License-Identifier: LGPL-2.1-or-later

"""Root-selected export-only cache-lifetime regression; no solver invocation.

Select the single method below explicitly: the inherited fixture methods remain
the existing public native-object model, not mocks or new physical acceptance.
This private proposal does not alter the product or public test registration.
"""

import io
import re
import tempfile
from pathlib import Path

import Fem

from femmesh.meshsetsgetter import MeshSetsGetter
from femsolver.calculix.calculixutils import define_masks
from femsolver.calculix.write_constraint_elastic_connector import write_connectors
from femsolver.calculix.write_constraint_rigidbody import write_constraint
from femsolver.calculix.writer import FemInputWriterCcx
from femtest.app.test_elastic_connector import TestRigidPortConnector
from femtools.force_accounting import capacity_preflight
from femtools.membertools import AnalysisMember


class TestPortCacheLifetime(TestRigidPortConnector):
    def test_direct_writes_after_completed_and_failed_full_exports_are_fresh(self):
        def node_set(text, name):
            match = re.search(
                r"\*NSET,\s*NSET=" + re.escape(name) + r"\s*\n([^*]+)",
                text,
                re.IGNORECASE,
            )
            self.assertIsNotNone(match, name)
            return {int(value) for value in re.split(r"[,\s]+", match[1]) if value}

        for failed_export in (False, True):
            with self.subTest(failed_export=failed_export):
                analysis, solver, connector, mesh, bodies, _ = self.model()
                solver.SplitInputWriter = False
                # Port resolution itself is independent of opt-in accounting.
                # Keep this focused gate export-only and free of native queries.
                solver.NativeForceAccounting = False
                getter = MeshSetsGetter(analysis, solver, mesh, AnalysisMember(analysis))
                for name, mask in define_masks(solver).items():
                    setattr(getter, "mask_" + name, mask)
                getter.get_mesh_sets()
                original = bodies[1].References

                with tempfile.TemporaryDirectory() as directory:
                    writer = FemInputWriterCcx(
                        analysis, solver, mesh, getter.member, directory, getter.mat_geo_sets
                    )
                    # This is the same stock metadata binding as FemToolsCcx,
                    # obtained from the real disabled-accounting preflight.
                    writer.native_accounting_capacity = capacity_preflight(analysis, solver)
                    if failed_export:
                        bodies[1].References = bodies[0].References
                        self.doc.recompute()
                        with self.assertRaisesRegex(ValueError, "overlap"):
                            writer.write_solver_input()
                    else:
                        filename = writer.write_solver_input()
                        self.assertTrue(Path(filename).is_file())
                        original_deck = Path(filename).read_text()
                        self.assertEqual(
                            node_set(original_deck, bodies[0].Name + "_RefNode"), {35}
                        )
                        # A completed writer must not retain an old verified
                        # region that could hide a newly overlapping endpoint.
                        bodies[1].References = bodies[0].References
                        self.doc.recompute()
                        with self.assertRaisesRegex(ValueError, "overlap"):
                            write_connectors(io.StringIO(), writer)

                    # Reuse that exact concrete writer outside its completed or
                    # rejected full export. New mesh IDs and analysis order must
                    # be resolved by both existing direct writing interfaces.
                    bodies[1].References = original
                    shifted = Fem.FemMesh()
                    for node, point in mesh.FemMesh.Nodes.items():
                        shifted.addNode(point.x, point.y, point.z, node + 100)
                    shifted.addVolume(list(range(101, 109)))
                    shifted.addVolume(list(range(121, 129)))
                    mesh.FemMesh = shifted
                    group = list(analysis.Group)
                    first, second = group.index(bodies[0]), group.index(bodies[1])
                    group[first], group[second] = group[second], group[first]
                    analysis.Group = group
                    self.doc.recompute()

                    connector_stream = io.StringIO()
                    write_connectors(connector_stream, writer)
                    self.assertEqual(
                        node_set(connector_stream.getvalue(), "EC_END1_" + connector.Name), {138}
                    )
                    self.assertEqual(
                        node_set(connector_stream.getvalue(), "EC_END2_" + connector.Name), {136}
                    )
                    for body in bodies:
                        row = next(
                            item for item in getter.member.cons_rigidbody if item["Object"] == body
                        )
                        rigid_stream = io.StringIO()
                        write_constraint(rigid_stream, row, body, writer)
                        expected_ref, expected_rot = (
                            (137, 138) if body == bodies[0] else (135, 136)
                        )
                        self.assertEqual(
                            node_set(rigid_stream.getvalue(), body.Name + "_RefNode"), {expected_ref}
                        )
                        self.assertEqual(
                            node_set(rigid_stream.getvalue(), body.Name + "_RotNode"), {expected_rot}
                        )
