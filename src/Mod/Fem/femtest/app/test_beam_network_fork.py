# SPDX-License-Identifier: LGPL-2.1-or-later
"""A three-component scalar fork against independently frozen free bodies."""

import FreeCAD as App

from femtest.app.beam_network_fixtures import make_forked_trees
from femtest.app.test_beam_network_native import BeamNetworkNativeCase


class TestBeamNetworkFork(BeamNetworkNativeCase):
    def test_three_branches_keep_both_child_links_and_all_native_owners(self):
        doc = App.newDocument("NativeForkedBranches")
        self.document_names.append(doc.Name)
        model = make_forked_trees(doc)
        self.assertEqual((model.mesh.FemMesh.NodeCount, model.mesh.FemMesh.EdgeCount), (57, 27))
        self.assertEqual((model.mesh.FemMesh.VolumeCount, model.mesh.FemMesh.FaceCount), (0, 0))
        self.assertEqual(len(model.geometry.Shape.Edges), 9)
        self.assertEqual(len(model.materials), 2)
        self.assertEqual(len(model.sections), 2)
        self.assertEqual(
            [spring.Stiffness.getValueAs("N/mm").Value for spring in model.springs],
            [10000, 2500, 5000],
        )
        result, data, deck = self.solve(model)
        self.assertIn(b"TYPE=B32R", deck.upper())
        self.assertEqual(deck.upper().count(b"TYPE=SPRING1"), 1)
        self.assertEqual(deck.upper().count(b"TYPE=SPRING2"), 2)
        self.assertEqual(data["position_frame"], "NATIVE_MAP_EXPANDED_SECTION")
        self.assertEqual(data["basis_frame"], "NATIVE_MAP_FACE_BASIS")
        self.assertEqual(data["geometry_source"], "CO_PLUS_NATIVE_MAP_VOLD_ARGUMENT")
        self.assertEqual(data["moment_reference"], "NATIVE_SECTION_CENTROID")
        catalogue = {row["element"]: row for row in data["provenance"]["elements"]}
        self.assertEqual(set(catalogue), set(range(1, 28)))
        for element, row in catalogue.items():
            component = (element - 1) // 9
            local = (element - 1) % 9 + 1
            member = 1 if local <= 5 else 2 if local <= 7 else 3
            self.assertEqual(row["component"], component + 1)
            self.assertEqual(row["member"], f"{model.geometry.Name}.Edge{3 * component + member}")
            self.assertEqual(row["section"], model.component_sections[component].Name)
            self.assertEqual(row["material"], model.component_materials[component].Name.upper())
            self.assertEqual(row["material_owner"], model.component_materials[component].Name)
            self.assertEqual(row["dimensions_mm"], [4.0, 8.0] if component == 0 else [6.0, 6.0])
            self.assertEqual(
                row["reference_n1"],
                (
                    [0.0, 1.0, 0.0]
                    if member == 1
                    else [-1.0, 0.0, 0.0] if member == 2 else [1.0, 0.0, 0.0]
                ),
            )
        frame = data["frames"][0]
        actions = frame["native_actions"]
        self.assertEqual(actions["position_frame"], "ORIGINAL_GLOBAL")
        self.assertEqual(actions["moment_reference"], "GLOBAL_ORIGIN")
        self.assertEqual(actions["force_action"], "ON_STRUCTURAL_MODEL")
        sources = {row["owner"]: row for row in actions["sources"]}
        self.assertEqual(set(sources), {force.Name for force in model.forces})
        source_controls = (
            (15, (1, 0, 0.01), (0.57, -24, -57)),
            (19, (4, 0, -0.02), (0.46, -90, 92)),
            (34, (1, 0, 0.03), (2.91, -29.3, -97)),
            (38, (2, 0, -0.01), (-0.17, -43.9, -34)),
            (53, (2, 0, 0.02), (0.34, -52.4, -34)),
            (57, (3, 0, -0.01), (0.63, -65.8, 189)),
        )
        for owner, (node, force, moment) in zip(model.forces, source_controls):
            row = sources[owner.Name]
            self.assertEqual(row["node"], node)
            self.components(row["position"], model.nodes[node], (1e-8,) * 3)
            self.wrench(row, force, moment)
        self.components(
            [sum(row["force_global"][i] for row in sources.values()) for i in range(3)],
            (13, 0, 0.02),
            (1e-5,) * 3,
        )
        self.components(
            [sum(row["moment_origin"][i] for row in sources.values()) for i in range(3)],
            (4.74, -305.4, 59),
            (1e-3,) * 3,
        )
        supports = {row["owner"]: row for row in actions["supports"]}
        self.assertEqual(set(supports), {guide.Name for guide in model.guides})
        guides = [supports[guide.Name] for guide in model.guides]
        guide_controls = (
            (1, (0, 0, 0.01), (-1.03, -1, -200), (-1.2, -1, -200)),
            (20, (0, 0, -0.02), (-2.74, 4.2, -40), (-1.6, 2, -40)),
            (39, (0, 0, -0.01), (-0.97, 3.2, -40), (-1.2, 1, -40)),
        )
        for guide, (node, force, moment, couple) in zip(guides, guide_controls):
            self.assertEqual(guide["node"], node)
            self.components(guide["position"], model.nodes[node], (1e-8,) * 3)
            self.wrench(guide, force, moment)
            self.assertEqual(
                sorted(row["role"] for row in guide["spcs"]),
                ["ALGEBRAIC"] * 3 + ["ANGLE"] * 3 + ["TRANSLATION"] * 2,
            )
            angles = {
                row["original_direction"]: row["value"]
                for row in guide["spcs"]
                if row["role"] == "ANGLE"
            }
            self.assertEqual(set(angles), {4, 5, 6})
            self.components([angles[d] for d in (4, 5, 6)], couple, (1e-3,) * 3)
        springs = {row["owner"]: row for row in actions["springs"]}
        self.assertEqual(set(springs), {spring.Name for spring in model.springs})
        observed_springs = [springs[spring.Name] for spring in model.springs]
        self.assertEqual(
            [row["mode"] for row in observed_springs], ["GROUND", "TWO_POINTS", "TWO_POINTS"]
        )
        self.assertEqual([row["direction"] for row in observed_springs], [1, 1, 1])
        self.assertEqual(
            [row["stiffness_N_per_mm"] for row in observed_springs], [10000, 2500, 5000]
        )
        self.assertEqual([len(row["ends"]) for row in observed_springs], [1, 2, 2])
        end_controls = (
            ((1, (-13, 0, 0), (0, 299, 221)),),
            ((15, (3, 0, 0), (0, -69, -171)), (20, (-3, 0, 0), (0, 69, 171))),
            ((19, (5, 0, 0), (0, -115, 115)), (39, (-5, 0, 0), (0, 115, -115))),
        )
        ends = []
        for spring, controls in zip(observed_springs, end_controls):
            indexed = {row["end"]: row for row in spring["ends"]}
            self.assertEqual(set(indexed), set(range(1, len(controls) + 1)))
            actual_ends = [indexed[i + 1] for i in range(len(controls))]
            ends.append(actual_ends)
            for end, (node, force, moment) in zip(actual_ends, controls):
                self.assertEqual((end["node"], end["role"]), (node, "BEAM_VERTEX"))
                self.components(end["position"], model.nodes[node], (1e-8,) * 3)
                self.wrench(end, force, moment)
                self.components(end["native_resisting_force"], [-v for v in force], (1e-5,) * 3)
        ground, child_one, child_two = ends[0][0], ends[1], ends[2]
        self.assertAlmostEqual(ground["displacement"][0], 0.0013, delta=1e-8)
        for pair, relative in ((child_one, 0.0012), (child_two, 0.001)):
            self.assertAlmostEqual(
                pair[1]["displacement"][0] - pair[0]["displacement"][0], relative, delta=1e-8
            )
            self._balance(pair)
        ordered_sources = [sources[force.Name] for force in model.forces]
        for rows in (
            (*ordered_sources[:2], child_one[0], child_two[0], guides[0], ground),
            (*ordered_sources[2:4], child_one[1], guides[1]),
            (*ordered_sources[4:], child_two[1], guides[2]),
            (*ordered_sources, *guides, ground),
        ):
            self._balance(rows)
        expected = self._fork_ends()
        actual = {(row["element"], row["node"], row["end"]): row for row in frame["samples"]}
        self.assertEqual(set(actual), set(expected))
        self.assertEqual(len(frame["samples"]), 54)
        for key, (force, moment, moment_budget) in expected.items():
            row = actual[key]
            point = model.nodes[key[1]]
            self.components(row["position"], point, (1e-8,) * 3)
            force_budget = (0.005, 1e-5, 1e-4)
            self.components(row["force_global"], force, force_budget)
            self.components(row["moment_global"], moment, moment_budget)
            expected_origin = App.Vector(*point).cross(App.Vector(*force)) + App.Vector(*moment)
            observed_origin = App.Vector(*row["position"]).cross(
                App.Vector(*row["force_global"])
            ) + App.Vector(*row["moment_global"])
            transport_budget = [
                moment_budget[i]
                + abs(point[(i + 1) % 3]) * force_budget[(i + 2) % 3]
                + abs(point[(i + 2) % 3]) * force_budget[(i + 1) % 3]
                for i in range(3)
            ]
            self.components(observed_origin, expected_origin, transport_budget)
            axes = {name: App.Vector(*vector) for name, vector in row["basis"].items()}
            for axis in axes.values():
                self.assertAlmostEqual(axis.Length, 1, delta=1e-8)
            for first, last in (("e1", "e2"), ("e1", "normal"), ("e2", "normal")):
                self.assertAlmostEqual(axes[first].dot(axes[last]), 0, delta=1e-8)
            determinant = axes["e1"].cross(axes["e2"]).dot(axes["normal"])
            self.assertAlmostEqual(determinant, -1 if key[2] == 1 else 1, delta=1e-8)
        for element_offset, node_offset in ((0, 0), (9, 19), (18, 38)):
            joint = 11 + node_offset
            self.assertEqual(
                {key for key in actual if key[1] == joint},
                {
                    (5 + element_offset, joint, 3),
                    (6 + element_offset, joint, 1),
                    (8 + element_offset, joint, 1),
                },
            )
        knot_rows = actions["knot_algebraic_spcs"]
        self.assertTrue(knot_rows)
        self.assertEqual({row["original_node"] for row in knot_rows}, {11, 30, 49})
        self.assertTrue(all(row["role"] == "ALGEBRAIC" for row in knot_rows))
        self.assertEqual(len({row["mpc_row"] for row in knot_rows}), len(knot_rows))
        mechanical = [o for o in model.analysis.Group if o.isDerivedFrom("Fem::FemResultObject")]
        self.assertEqual(len(mechanical), 1)
        for field in (
            "NodeStressXX",
            "NodeStressYY",
            "NodeStressZZ",
            "NodeStressXY",
            "NodeStressXZ",
            "NodeStressYZ",
        ):
            self.assertFalse(getattr(mechanical[0], field))
        doc.recompute()
        doc.saveAs(str(self.directory / "forked-branches.FCStd"))
        self.assertEqual(result.Proxy.getSectionForces(result), data)

    def _balance(self, rows):
        for field, budget in (("force_global", 1e-5), ("moment_origin", 1e-3)):
            self.components(
                [sum(row[field][i] for row in rows) for i in range(3)], (0, 0, 0), (budget,) * 3
            )

    @staticmethod
    def _fork_ends():
        """Cuts use prescribed loads and independently determined scalar port actions."""
        expected = {}
        components = (
            (
                0,
                0,
                0,
                (4, 0.01),
                (9, -0.02),
                (0.012, 0.01, 2.0),
                (0.004, 0.001, 1.6),
                (0.008, 0.001, 3.6),
            ),
            (
                9,
                19,
                110,
                (1, 0.03),
                (2, -0.01),
                (0.016, 0.02, 0.4),
                (0.012, 0.001, 0.4),
                (0.004, 0.001, 0.8),
            ),
            (
                18,
                38,
                220,
                (2, 0.02),
                (3, -0.01),
                (0.012, 0.01, 0.4),
                (0.008, 0.001, 0.8),
                (0.004, 0.001, 1.2),
            ),
        )
        for eoff, noff, root_x, upper, lower, stem_budget, upper_budget, lower_budget in components:
            fx, fz = upper[0] + lower[0], upper[1] + lower[1]
            joint_mx, joint_mz = 40 * (upper[1] - lower[1]), 40 * (lower[0] - upper[0])
            for local in range(1, 6):
                for end, node, x, sign in (
                    (1, 2 * local - 1 + noff, root_x + 20 * (local - 1), -1),
                    (3, 2 * local + 1 + noff, root_x + 20 * local, 1),
                ):
                    expected[local + eoff, node, end] = (
                        (sign * fx, 0, sign * fz),
                        (sign * joint_mx, -sign * fz * (root_x + 100 - x), sign * joint_mz),
                        stem_budget,
                    )
            for local, first, last, d0, d1, load, orientation, budget in (
                (6, 11, 13, 40, 20, upper, 1, upper_budget),
                (7, 13, 15, 20, 0, upper, 1, upper_budget),
                (8, 11, 17, 40, 20, lower, -1, lower_budget),
                (9, 17, 19, 20, 0, lower, -1, lower_budget),
            ):
                for end, node, distance, sign in ((1, first, d0, -1), (3, last, d1, 1)):
                    expected[local + eoff, node + noff, end] = (
                        (sign * load[0], 0, sign * load[1]),
                        (
                            sign * orientation * distance * load[1],
                            0,
                            -sign * orientation * distance * load[0],
                        ),
                        budget,
                    )
        return expected
