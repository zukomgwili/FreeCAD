# SPDX-License-Identifier: LGPL-2.1-or-later
"""A native beam/spring/rigid-face/solid path against separate exact controls."""

import hashlib
import json
import os
import shutil
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import FreeCAD as App

from femtest.app.beam_coupling_fixtures import make_hybrid_series
from femtest.app.beam_coupling_fixtures import make_prescribed_beam_control
from femtools.beam_section_forces import require_capability
from femtools.ccxtools import FemToolsCcx
from femtools.force_accounting import solver_binary


class TestBeamSolidCouplingNative(unittest.TestCase):
    def setUp(self):
        previous = App.activeDocument()
        self.previous_document = previous.Name if previous is not None else None
        self.previous_analysis = None
        if App.GuiUp:
            import FemGui

            self.previous_analysis = FemGui.getActiveAnalysis()
        self.documents = []
        self.temporary = None
        self.addCleanup(self._restore_session)
        explicit = os.environ.get("SV7_TEST_SOLVER")
        self.binary = explicit or solver_binary(SimpleNamespace(NativeAccountingSolver=""))
        try:
            require_capability(self.binary, schema="CCX_BEAM_SECTION_V3")
        except (OSError, ValueError) as error:
            if explicit:
                raise
            self.skipTest("Qualified native mixed beam/solid observer required: " + str(error))
        retained = os.environ.get("SV7_WITNESS_ROOT")
        if retained:
            self.directory = Path(retained) / self._testMethodName
            self.directory.mkdir(parents=True)
        else:
            self.temporary = tempfile.TemporaryDirectory(prefix="freecad-beam-solid-")
            self.directory = Path(self.temporary.name)

    def _restore_session(self):
        try:
            if App.GuiUp:
                import FemGui

                FemGui.setActiveAnalysis()
            for doc in reversed(self.documents):
                if doc.Name in App.listDocuments():
                    App.closeDocument(doc.Name)
        finally:
            if self.previous_document in App.listDocuments():
                App.setActiveDocument(self.previous_document)
            if App.GuiUp and self.previous_analysis is not None:
                if self.previous_analysis.Document.Name in App.listDocuments():
                    FemGui.setActiveAnalysis(self.previous_analysis)
            if self.temporary is not None:
                self.temporary.cleanup()

    def vector(self, actual, expected, limit):
        self.assertLessEqual((App.Vector(*actual) - App.Vector(*expected)).Length, limit)

    def _solve(self, model, name, schema):
        directory = self.directory / name
        directory.mkdir()
        model.solver.NativeAccountingSolver = self.binary
        fea = FemToolsCcx(analysis=model.analysis, solver=model.solver)
        fea.update_objects()
        fea.setup_working_dir(str(directory))
        self.assertFalse(fea.check_prerequisites())
        self.assertFalse(fea.write_inp_file())
        deck = Path(fea.inp_file_name).read_bytes()
        (directory / "stock-input.inp").write_bytes(deck)
        self.assertEqual(fea.ccx_run(), 0, fea.ccx_stdout + fea.ccx_stderr)
        self.assertEqual(Path(fea.inp_file_name).read_bytes(), deck)
        fea.load_results()
        results = [
            obj
            for obj in model.analysis.Group
            if getattr(getattr(obj, "Proxy", None), "Type", "") == "Fem::BeamSectionForceResult"
        ]
        self.assertEqual(len(results), 1)
        result = results[0]
        data = result.Proxy.getSectionForces(result)
        self.assertEqual(data["schema"], schema)
        self.assertEqual(data["units"], {"length": "mm", "force": "N", "moment": "N*mm"})
        self.assertEqual(len(data["frames"]), 1)
        self.assertEqual(data["frames"][0]["step"], 1)
        self.assertEqual(data["frames"][0]["time"], 1)
        self.assertTrue(result.Status.startswith("Current"), result.Status)
        self.assertEqual(Path(fea.inp_file_name).read_bytes(), deck)
        (directory / "observed.json").write_text(json.dumps(data, indent=2))
        return result, data, deck

    def test_hybrid_actions_solid_patch_and_native_beam_component_control(self):
        mixed_doc = App.newDocument("NativeBeamSolidSeries")
        self.documents.append(mixed_doc)
        model = make_hybrid_series(mixed_doc)
        self.assertTrue(model.solid.Shape.isValid())
        self.assertAlmostEqual(model.solid.Shape.Volume, 1500, delta=1e-9)
        self.assertTrue(set(model.beam_nodes).isdisjoint(model.solid_nodes))
        result, data, deck = self._solve(model, "mixed", "CCX_BEAM_SECTION_V3")
        for kind in (b"B32R", b"C3D4", b"SPRING2"):
            self.assertIn(b"TYPE=" + kind, deck.upper())
        self.assertEqual(data["position_frame"], "NATIVE_MAP_EXPANDED_SECTION")
        self.assertEqual(data["basis_frame"], "NATIVE_MAP_FACE_BASIS")
        self.assertEqual(data["geometry_source"], "CO_PLUS_NATIVE_MAP_VOLD_ARGUMENT")
        frame = data["frames"][0]
        actions = frame["native_actions"]
        self.assertEqual(actions["position_frame"], "ORIGINAL_GLOBAL")
        self.assertEqual(actions["moment_reference"], "GLOBAL_ORIGIN")
        self.assertEqual(actions["force_action"], "ON_STRUCTURAL_MODEL")
        for name, owner, force, moment in (
            ("source", model.force.Name, (100, 0, 0), (0, -2300, -1700)),
            ("support", model.stabilizer.Name, (0, 0, 0), (0, 0, 0)),
            ("solid_support", model.fixed.Name, (-100, 0, 0), (0, 2300, 1700)),
        ):
            self.assertEqual(actions[name]["owner"], owner)
            self.vector(actions[name]["force_global"], force, 0.01)
            self.vector(actions[name]["moment_origin"], moment, 1)
        spring = actions["spring"]
        self.assertEqual(spring["owner"], model.connector.Name)
        self.assertEqual(len(spring["ends"]), 2)
        first, second = spring["ends"]
        self.assertEqual((first["end"], first["node"], first["role"]), (1, 1, "BEAM_VERTEX"))
        self.assertEqual((second["end"], second["role"]), (2, "RBE_REFERENCE"))
        for end, force, moment in (
            (first, (-100, 0, 0), (0, 2300, 1700)),
            (second, (100, 0, 0), (0, -2300, -1700)),
        ):
            self.vector(end["force_global"], force, 0.01)
            self.vector(end["moment_origin"], moment, 1)
            self.vector(end["native_resisting_force"], tuple(-value for value in force), 0.01)
        relative = first["displacement"][0] - second["displacement"][0]
        self.assertAlmostEqual(relative, 0.01, delta=0.000001)
        self.assertAlmostEqual(10000 * relative, 100, delta=0.01)
        self.vector(second["displacement"], (0.0001333333333333333, 0, 0), 0.0000001)
        self.vector(first["displacement"], (0.010133333333333333, 0, 0), 0.000001)
        port = actions["port"]
        self.assertEqual(port["owner"], model.rbe.Name)
        self.assertEqual(port["reference_node"], second["node"])
        self.assertEqual(set(port["receiving_nodes"]), set(model.near_nodes))
        self.vector(port["receiving_action"]["force_global"], (100, 0, 0), 0.01)
        self.vector(port["receiving_action"]["moment_origin"], (0, -2300, -1700), 1)
        self.vector(port["reference_action"]["force_global"], (-100, 0, 0), 0.01)
        self.vector(port["reference_action"]["moment_origin"], (0, 2300, 1700), 1)
        self.vector(port["reference_action"]["couple_global"], (0, 0, 0), 1)
        self.assertEqual(len(port["algebraic_spcs"]), 9)
        self.assertEqual({row["role"] for row in port["algebraic_spcs"]}, {"ALGEBRAIC"})
        self.assertEqual(
            {(row["receiving_node"], row["direction"]) for row in port["algebraic_spcs"]},
            {(node, direction) for node in model.near_nodes for direction in (1, 2, 3)},
        )
        guide = actions["support"]["spcs"]
        self.assertEqual(len(guide), 8)
        self.assertEqual([row["role"] for row in guide].count("ANGLE"), 3)
        self.assertEqual([row["role"] for row in guide].count("ALGEBRAIC"), 3)
        fixed = actions["solid_support"]["spcs"]
        self.assertEqual(len(fixed), 9)
        self.assertEqual({row["role"] for row in fixed}, {"TRANSLATION"})
        self.assertEqual(
            {(row["node"], row["direction"]) for row in fixed},
            {(node, direction) for node in model.far_nodes for direction in (1, 2, 3)},
        )
        # Each owner closes separately; internal transfers are absent from the
        # whole-model external support sum and algebraic terms are excluded.
        for rows in (
            (actions["source"], first, actions["support"]),
            (second, port["reference_action"]),
            (port["receiving_action"], actions["solid_support"]),
            (actions["source"], actions["support"], actions["solid_support"]),
        ):
            for field, limit in (("force_global", 0.01), ("moment_origin", 1)):
                self.vector(
                    [sum(row[field][index] for row in rows) for index in range(3)],
                    (0, 0, 0),
                    limit,
                )
        self.assertEqual(
            {(row["element"], row["node"], row["end"]) for row in frame["samples"]},
            {(1, 1, 1), (1, 3, 3), (2, 3, 1), (2, 5, 3)},
        )
        for row in frame["samples"]:
            self.vector(row["force_global"], (-100 if row["end"] == 1 else 100, 0, 0), 0.1)
            self.vector(row["moment_global"], (0, 0, 0), 0.4)
            self.assertAlmostEqual(row["native_channels"]["axial"], 100, delta=0.1)
            for channel, limit in (
                ("shear1", 0.1),
                ("shear2", 0.1),
                ("torque", 0.4),
                ("bend1", 0.4),
                ("bend2", 0.4),
            ):
                self.assertAlmostEqual(row["native_channels"][channel], 0, delta=limit)

        mechanical = [
            obj for obj in model.analysis.Group if obj.isDerivedFrom("Fem::FemResultObject")
        ]
        self.assertEqual(len(mechanical), 2)
        solid = next(obj for obj in mechanical if hasattr(obj, "NativeSolidOwner"))
        mixed = next(obj for obj in mechanical if not hasattr(obj, "NativeSolidOwner"))
        self.assertEqual(set(solid.NativeSourceNodeNumbers), set(model.solid_nodes))
        self.assertEqual(
            set(mixed.NativeSourceNodeNumbers), set(model.beam_nodes + model.solid_nodes)
        )
        self.assertEqual((solid.Mesh.FemMesh.NodeCount, solid.Mesh.FemMesh.EdgeCount), (6, 0))
        self.assertEqual((solid.Mesh.FemMesh.VolumeCount, solid.Mesh.FemMesh.FaceCount), (3, 0))
        self.assertEqual((mixed.Mesh.FemMesh.NodeCount, mixed.Mesh.FemMesh.EdgeCount), (11, 2))
        self.assertEqual(mixed.Mesh.FemMesh.VolumeCount, 3)
        self.assertEqual(set(solid.NativeSourceElementNumbers), set(model.solid_elements))
        for res in mechanical:
            self.assertEqual(res.NativeBeamSource, result)
            self.assertEqual(res.NativeSourceFileHash, data["provenance"]["frd"]["sha256"])
            self.assertEqual(json.loads(res.NativeSourceFrame)["case"], data["provenance"]["case"])
            self.assertEqual(len(res.NativeSourceNodeNumbers), len(res.NodeNumbers))
        self.assertEqual(solid.NativeSolidOwner, model.solid)
        self.assertEqual(len(solid.NodeStressXX), 6)
        for value in solid.NodeStressXX:
            self.assertAlmostEqual(value, 4 / 3, delta=0.0001)
        for name in (
            "NodeStressYY",
            "NodeStressZZ",
            "NodeStressXY",
            "NodeStressXZ",
            "NodeStressYZ",
        ):
            self.assertEqual(len(getattr(solid, name)), 6)
            for value in getattr(solid, name):
                self.assertAlmostEqual(value, 0, delta=0.0001)
        for name in (
            "NodeStressXX",
            "NodeStressYY",
            "NodeStressZZ",
            "NodeStressXY",
            "NodeStressXZ",
            "NodeStressYZ",
        ):
            self.assertFalse(getattr(mixed, name))
        displacement = dict(zip(mixed.NativeSourceNodeNumbers, mixed.DisplacementVectors))
        solid_displacement = dict(zip(solid.NativeSourceNodeNumbers, solid.DisplacementVectors))
        for node in model.far_nodes:
            self.vector(displacement[node], (0, 0, 0), 0.0000001)
        for node in model.near_nodes:
            self.vector(displacement[node], (0.0001333333333333333, 0, 0), 0.0000001)
        for node in model.solid_nodes:
            self.vector(solid_displacement[node], displacement[node], 1e-12)

        # Same native beam load discretization, with an independently known
        # root motion, is the displacement control; PL/EA is not fitted.
        pure_doc = App.newDocument("NativePrescribedBeamControl")
        self.documents.append(pure_doc)
        control = make_prescribed_beam_control(pure_doc)
        self.assertAlmostEqual(
            control.stabilizer.xDisplacement.Value, 0.010133333333333333, delta=1e-15
        )
        pure_result, pure_data, pure_deck = self._solve(control, "pure", "CCX_BEAM_SECTION_V1")
        self.assertNotIn(b"TYPE=SPRING", pure_deck.upper())
        self.assertNotIn(b"TYPE=C3D4", pure_deck.upper())
        self.assertNotIn(b"*RIGID BODY", pure_deck.upper())
        self.assertEqual(
            data["provenance"]["binary_sha256"], pure_data["provenance"]["binary_sha256"]
        )
        controls = [
            obj for obj in control.analysis.Group if obj.isDerivedFrom("Fem::FemResultObject")
        ]
        self.assertEqual(len(controls), 1)
        pure_mechanical = controls[0]
        self.assertEqual(list(pure_mechanical.NodeNumbers), list(model.beam_nodes))
        actual_control = dict(zip(pure_mechanical.NodeNumbers, pure_mechanical.DisplacementVectors))
        differences = {}
        for node in model.beam_nodes:
            self.vector(displacement[node], actual_control[node], 0.0000002)
            differences[node] = (displacement[node] - actual_control[node]).Length
        comparison = {
            "method": "Separate public native V1 beam with independently prescribed root motion",
            "root_reference_mm": 0.010133333333333333,
            "equivalence_limit_mm": 0.0000002,
            "mixed_beam_displacements_mm": {
                node: list(displacement[node]) for node in model.beam_nodes
            },
            "pure_beam_displacements_mm": {
                node: list(actual_control[node]) for node in model.beam_nodes
            },
            "differences_mm": differences,
            "mixed_frd_sha256": data["provenance"]["frd"]["sha256"],
            "pure_frd_sha256": pure_data["provenance"]["frd"]["sha256"],
            "elementary_rod_tip_diagnostic": {
                "reference_mm": 0.011383333333333333,
                "original_limit_mm": 0.000001,
                "qualified": False,
                "reason": "Native corner-mean point load is not uniform end traction",
                "observed_mixed_tip_mm": displacement[5].x,
                "difference_mm": displacement[5].x - 0.011383333333333333,
            },
        }
        (self.directory / "comparison.json").write_text(json.dumps(comparison, indent=2))
        (self.directory / "observed.json").write_text(json.dumps(data, indent=2))
        App.setActiveDocument(mixed_doc.Name)
        mixed_doc.saveAs(str(self.directory / "hybrid.FCStd"))
        self.assertEqual(result.Proxy.getSectionForces(result), data)
        self.assertEqual(pure_result.Proxy.getSectionForces(pure_result), pure_data)

    def test_zero_period_is_refused_before_native_export(self):
        doc = App.newDocument("NativeBeamSolidPeriodRefusal")
        self.documents.append(doc)
        model = make_hybrid_series(doc)
        model.solver.NativeAccountingSolver = self.binary
        model.solver.TimePeriod = "0 s"
        fea = FemToolsCcx(analysis=model.analysis, solver=model.solver)
        fea.update_objects()
        fea.setup_working_dir(str(self.directory))
        with self.assertRaisesRegex(ValueError, "positive step period"):
            fea.write_inp_file()
        self.assertFalse(list(self.directory.glob("*.beam-section")))

    def test_saved_rigid_algebraic_terms_cannot_alias_beam_rotation_helpers(self):
        doc = App.newDocument("NativeBeamSolidAliasRefusal")
        self.documents.append(doc)
        model = make_hybrid_series(doc)
        result, data, deck = self._solve(model, "mixed", "CCX_BEAM_SECTION_V3")
        damaged = json.loads(result.SectionData)
        actions = damaged["frames"][0]["native_actions"]
        beam_auxiliary = next(
            row["node"] for row in actions["support"]["spcs"] if row["role"] == "ANGLE"
        )
        receiver = actions["port"]["receiving_nodes"][0]
        for row in actions["port"]["algebraic_spcs"]:
            if row["receiving_node"] == receiver:
                row["node"] = beam_auxiliary
        literal = json.dumps(damaged, sort_keys=True, allow_nan=False)
        result.SectionData = literal
        result.SectionHash = hashlib.sha256(literal.encode()).hexdigest()
        with self.assertRaisesRegex(ValueError, "algebraic identity"):
            result.Proxy.getSectionForces(result, historical=True)

    def test_contact_and_contact_output_requests_are_refused_before_export(self):
        import ObjectsFem

        for selected in (False, True):
            with self.subTest(native_contact_output=selected):
                doc = App.newDocument("NativeBeamSolidContactRefusal")
                self.documents.append(doc)
                model = make_hybrid_series(doc)
                contact = ObjectsFem.makeConstraintContact(doc, "UnqualifiedContact")
                contact.SurfaceBehavior = "Linear"
                contact.Slope = "100000 MPa/mm"
                contact.Adjust = "0 mm"
                contact.References = list(model.rbe.References) + list(model.fixed.References)
                model.analysis.addObject(contact)
                model.solver.NativeContactOutputs = [contact] if selected else []
                model.solver.NativeAccountingSolver = self.binary
                doc.recompute()
                directory = self.directory / ("selected" if selected else "active")
                directory.mkdir()
                fea = FemToolsCcx(analysis=model.analysis, solver=model.solver)
                fea.update_objects()
                fea.setup_working_dir(str(directory))
                message = (
                    "separate from solid accounting/contact diagnostics"
                    if selected
                    else "other constraints, cuts or contact"
                )
                with self.assertRaisesRegex(ValueError, message):
                    fea.write_inp_file()
                self.assertFalse(list(directory.glob("*.beam-section")))
                self.assertFalse(
                    any(
                        getattr(getattr(obj, "Proxy", None), "Type", "")
                        == "Fem::BeamSectionForceResult"
                        for obj in model.analysis.Group
                    )
                )
                self.assertEqual(model.mesh.FemMesh.NodeCount, 11)
                self.assertEqual(model.mesh.FemMesh.VolumeCount, 3)

    def test_moving_port_and_physical_support_ownership_are_not_interchangeable(self):
        for name in ("support_on_moving_face", "beam_in_receiving_region"):
            with self.subTest(ownership=name):
                doc = App.newDocument("NativeBeamSolidOwnerRefusal")
                self.documents.append(doc)
                model = make_hybrid_series(doc)
                if name == "support_on_moving_face":
                    model.fixed.References = list(model.rbe.References)
                    message = "physical solid support must be separate"
                else:
                    # The three noncollinear solid-face nodes remain present;
                    # adding the beam vertex must fail solid ownership, not
                    # simply the minimum receiving-region rank requirement.
                    model.rbe.References = list(model.rbe.References) + [
                        (model.geometry, ["Vertex1"])
                    ]
                    message = "Every rigid port node must belong to the solid mesh"
                model.solver.NativeAccountingSolver = self.binary
                doc.recompute()
                directory = self.directory / name
                directory.mkdir()
                fea = FemToolsCcx(analysis=model.analysis, solver=model.solver)
                fea.update_objects()
                fea.setup_working_dir(str(directory))
                with self.assertRaisesRegex(ValueError, message):
                    fea.write_inp_file()
                self.assertFalse(list(directory.glob("*.beam-section")))
                self.assertFalse(
                    any(
                        getattr(getattr(obj, "Proxy", None), "Type", "")
                        == "Fem::BeamSectionForceResult"
                        for obj in model.analysis.Group
                    )
                )
                self.assertEqual(model.mesh.FemMesh.NodeCount, 11)
                self.assertEqual(model.mesh.FemMesh.VolumeCount, 3)

    def test_mixed_frd_needs_its_owned_v3_source_and_matching_analysis(self):
        import ObjectsFem
        from feminout import importCcxFrdResults

        doc = App.newDocument("NativeBeamSolidImportRefusal")
        self.documents.append(doc)
        model = make_hybrid_series(doc)
        result, data, deck = self._solve(model, "mixed", "CCX_BEAM_SECTION_V3")
        source = Path(data["provenance"]["frd"]["path"])
        directory = self.directory / "unbound"
        directory.mkdir()
        bare = directory / "copied.frd"
        shutil.copyfile(source, bare)
        self.assertEqual(list(directory.iterdir()), [bare])
        before = {obj.Name for obj in doc.Objects}
        with self.assertRaisesRegex(ValueError, "Bare original-beam FRD"):
            importCcxFrdResults.importFrd(str(bare), model.analysis)
        with self.assertRaisesRegex(ValueError, "requires an owned native V3 beam result"):
            importCcxFrdResults.importFrd(str(bare), model.analysis, beam_section_forces=True)
        self.assertEqual({obj.Name for obj in doc.Objects}, before)
        other_doc = App.newDocument("NativeBeamSolidWrongAnalysis")
        self.documents.append(other_doc)
        other_analysis = ObjectsFem.makeAnalysis(other_doc, "UnrelatedAnalysis")
        other_before = {obj.Name for obj in other_doc.Objects}
        with self.assertRaisesRegex(ValueError, "actual native beam result in this analysis"):
            importCcxFrdResults.importFrd(
                str(source), other_analysis, beam_section_forces=True, beam_result=result
            )
        self.assertEqual({obj.Name for obj in other_doc.Objects}, other_before)
        self.assertEqual({obj.Name for obj in doc.Objects}, before)
        self.assertEqual(result.Proxy.getSectionForces(result), data)
        self.assertTrue(result.Status.startswith("Current"), result.Status)
        self.assertEqual(Path(data["provenance"]["deck"]).read_bytes(), deck)

    def test_changed_frd_custody_withdraws_current_before_result_partition(self):
        from feminout import importCcxFrdResults

        doc = App.newDocument("NativeBeamSolidCustodyRefusal")
        self.documents.append(doc)
        model = make_hybrid_series(doc)
        result, data, deck = self._solve(model, "mixed", "CCX_BEAM_SECTION_V3")
        source = Path(data["provenance"]["frd"]["path"])
        original = source.read_bytes()
        (self.directory / "frd-before-tamper.frd").write_bytes(original)
        lines = original.decode("utf-8").splitlines(keepends=True)
        header = start = end = None
        for index, line in enumerate(lines):
            if line[4:10] == "1PSTEP":
                header = index
            elif line[5:11] == "STRESS":
                start = header
            elif start is not None and line[1:3] == "-3":
                end = index + 1
                break
        self.assertIsNotNone(start)
        self.assertIsNotNone(end)
        terminator = next(index for index, line in enumerate(lines) if line[1:5] == "9999")
        changed = "".join(lines[:terminator] + lines[start:end] + lines[terminator:]).encode(
            "utf-8"
        )
        source.write_bytes(changed)
        self.assertNotEqual(
            hashlib.sha256(changed).hexdigest(), data["provenance"]["frd"]["sha256"]
        )
        before = {obj.Name for obj in doc.Objects}
        saved_literal, saved_hash = result.SectionData, result.SectionHash
        # This public negative reaches the custody hash check first. It does
        # not claim coverage of the later raw duplicate-dataset audit.
        with self.assertRaisesRegex(
            ValueError, "Beam request, physical model, mesh or solver changed"
        ) as raised:
            importCcxFrdResults.importFrd(
                str(source), model.analysis, beam_section_forces=True, beam_result=result
            )
        self.assertEqual({obj.Name for obj in doc.Objects}, before)
        self.assertTrue(result.Status.startswith("Stale"), result.Status)
        self.assertEqual((result.SectionData, result.SectionHash), (saved_literal, saved_hash))
        self.assertEqual(result.Proxy.getSectionForces(result, historical=True), data)
        self.assertEqual(Path(data["provenance"]["deck"]).read_bytes(), deck)
        (self.directory / "custody-refusal.json").write_text(
            json.dumps(
                {
                    "control": "Duplicate STRESS dataset in the owned test FRD",
                    "boundary": "Public source custody; raw field auditor not reached",
                    "original_frd_sha256": data["provenance"]["frd"]["sha256"],
                    "changed_frd_sha256": hashlib.sha256(changed).hexdigest(),
                    "refusal": str(raised.exception),
                },
                indent=2,
            )
        )
