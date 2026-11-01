# SPDX-License-Identifier: LGPL-2.1-or-later
"""Public availability and refusal controls for genuine native beam networks."""

from contextlib import contextmanager
import copy
import hashlib
import json
from pathlib import Path

import FreeCAD as App
import ObjectsFem

from femtest.app.beam_network_fixtures import make_connected_trees, make_forked_trees
from femtest.app.test_beam_network_native import BeamNetworkNativeCase
from femtools.ccxtools import FemToolsCcx


class TestBeamNetworkIntegrity(BeamNetworkNativeCase):
    def _completed_network(self, factory=make_connected_trees):
        doc = App.newDocument("NativeNetworkIntegrity")
        self.document_names.append(doc.Name)
        model = factory(doc)
        result, data, deck = self.solve(model)
        self.assertEqual(len(data["frames"][0]["samples"]), 2 * model.mesh.FemMesh.EdgeCount)
        self.assertEqual(len(data["frames"][0]["native_actions"]["springs"]), len(model.springs))
        return model, result, data, deck

    @contextmanager
    def _fresh_completed(self, name, factory=make_connected_trees):
        previous = self.directory
        self.directory = previous / name
        self.directory.mkdir()
        try:
            yield self._completed_network(factory)
        finally:
            self.directory = previous

    @staticmethod
    def _owned_files(data):
        provenance = data["provenance"]
        paths = (
            provenance["deck"],
            provenance["request_path"],
            provenance["request_path"] + ".json",
            provenance["run"]["path"],
            provenance["output"],
            provenance["frd"]["path"],
        )
        return {Path(path): Path(path).read_bytes() for path in paths}

    def _unchanged_history(self, result, data, literal, digest, files):
        self.assertFalse(result.Status.startswith("Current"), result.Status)
        self.assertEqual((result.SectionData, result.SectionHash), (literal, digest))
        self.assertEqual(result.Proxy.getSectionForces(result, historical=True), data)
        self.assertEqual({path: path.read_bytes() for path in files}, files)

    def test_nonlinear_export_retires_completion_and_preserves_chosen_setting_and_history(self):
        model, result, data, deck = self._completed_network()
        literal, digest = result.SectionData, result.SectionHash
        files = self._owned_files(data)
        self.assertEqual(Path(data["provenance"]["deck"]).read_bytes(), deck)
        rejected = self.directory / "rejected-export"
        rejected.mkdir()
        model.solver.GeometricalNonlinearity = True
        model.doc.recompute()
        fea = FemToolsCcx(analysis=model.analysis, solver=model.solver)
        fea.update_objects()
        fea.setup_working_dir(str(rejected))
        with self.assertRaisesRegex(ValueError, "linear small-displacement"):
            fea.write_inp_file()
        self.assertTrue(model.solver.GeometricalNonlinearity)
        self.assertTrue(model.solver.BeamSectionForces)
        self.assertFalse(result.CompletedRun)
        with self.assertRaises(ValueError):
            result.Proxy.getSectionForces(result)
        self._unchanged_history(result, data, literal, digest, files)
        self.assertFalse(list(rejected.glob("*.beam-section*")))
        self.assertFalse(list(rejected.glob("*.dat")))
        self.assertFalse(list(rejected.glob("*.sta")))
        model.solver.GeometricalNonlinearity = False
        model.doc.recompute()
        with self.assertRaises(ValueError):
            result.Proxy.getSectionForces(result)
        self._unchanged_history(result, data, literal, digest, files)

    def test_internal_spring_edit_preserves_literal_history_through_save_and_reopen(self):
        model, result, data, _ = self._completed_network()
        literal, digest = result.SectionData, result.SectionHash
        files = self._owned_files(data)
        model.springs[1].Stiffness = "2600 N/mm"
        model.doc.recompute()
        with self.assertRaises(ValueError):
            result.Proxy.getSectionForces(result)
        self._unchanged_history(result, data, literal, digest, files)
        model.springs[1].Stiffness = "2500 N/mm"
        model.doc.recompute()
        with self.assertRaises(ValueError):
            result.Proxy.getSectionForces(result)
        self._unchanged_history(result, data, literal, digest, files)
        filename = self.directory / "network-history.FCStd"
        result_name = result.Name
        model.doc.saveAs(str(filename))
        App.closeDocument(model.doc.Name)
        reopened = App.openDocument(str(filename))
        self.document_names.append(reopened.Name)
        restored = reopened.getObject(result_name)
        self.assertIsNotNone(restored)
        self.assertTrue(restored.Status.startswith("Historical"), restored.Status)
        self.assertFalse(restored.CompletedRun)
        self.assertEqual(restored.Proxy.getSectionForces(restored, historical=True), data)
        with self.assertRaises(ValueError):
            restored.Proxy.getSectionForces(restored)
        self._unchanged_history(restored, data, literal, digest, files)

    def test_physical_edits_and_detached_owners_withdraw_current_without_erasing_history(self):
        changes = (
            ("source", lambda model, result: setattr(model.forces[2], "Force", "1.1 N")),
            (
                "material",
                lambda model, result: setattr(
                    model.materials[1],
                    "Material",
                    {**model.materials[1].Material, "YoungsModulus": "100001 MPa"},
                ),
            ),
            ("section", lambda model, result: setattr(model.sections[1], "RectHeight", "7 mm")),
            (
                "physical_guide",
                lambda model, result: setattr(model.guides[1], "yDisplacement", "0.001 mm"),
            ),
            ("detached_source", lambda model, result: model.analysis.removeObject(model.forces[2])),
            ("detached_result", lambda model, result: model.analysis.removeObject(result)),
            ("removed_solver", lambda model, result: model.doc.removeObject(model.solver.Name)),
        )
        for name, change in changes:
            with self.subTest(change=name), self._fresh_completed(name) as (model, result, data, _):
                literal, digest = result.SectionData, result.SectionHash
                files = self._owned_files(data)
                change(model, result)
                model.doc.recompute()
                with self.assertRaises(ValueError):
                    result.Proxy.getSectionForces(result)
                self._unchanged_history(result, data, literal, digest, files)

    def test_owned_file_tampering_is_refused_and_never_resurrects_current_after_restoration(self):
        for kind in ("request", "export_metadata", "run_request", "output", "deck", "frd"):
            with self.subTest(file=kind), self._fresh_completed(kind) as (_, result, data, _):
                provenance = data["provenance"]
                paths = {
                    "request": provenance["request_path"],
                    "export_metadata": provenance["request_path"] + ".json",
                    "run_request": provenance["run"]["path"],
                    "output": provenance["output"],
                    "deck": provenance["deck"],
                    "frd": provenance["frd"]["path"],
                }
                target = Path(paths[kind])
                original = target.read_bytes()
                literal, digest = result.SectionData, result.SectionHash
                files = self._owned_files(data)
                try:
                    # This is a completed-run getter control only. In particular,
                    # the altered stock deck is never passed to any solver.
                    target.write_bytes(original + b"\nUNOWNED_DIAGNOSTIC_TAMPER\n")
                    (self.directory / "tampered-file.bin").write_bytes(target.read_bytes())
                    with self.assertRaises(ValueError):
                        result.Proxy.getSectionForces(result)
                    self.assertFalse(result.Status.startswith("Current"), result.Status)
                    self.assertEqual((result.SectionData, result.SectionHash), (literal, digest))
                    self.assertEqual(result.Proxy.getSectionForces(result, historical=True), data)
                finally:
                    target.write_bytes(original)
                self._unchanged_history(result, data, literal, digest, files)
                with self.assertRaises(ValueError):
                    result.Proxy.getSectionForces(result)

    def test_rehashed_history_rejects_six_source_omissions_port_loss_and_knot_role_aliases(self):
        model, result, data, _ = self._completed_network(make_forked_trees)
        literal, digest = result.SectionData, result.SectionHash
        files = self._owned_files(data)
        observed = data["frames"][0]["native_actions"]
        self.assertEqual(len(observed["sources"]), 6)
        self.assertEqual(len(observed["supports"]), 3)
        self.assertEqual([len(row["ends"]) for row in observed["springs"]], [1, 2, 2])
        guide_helper = next(
            row["node"] for row in observed["supports"][0]["spcs"] if row["role"] == "ANGLE"
        )

        def altered_actions(payload):
            return payload["frames"][0]["native_actions"]

        changes = (
            ("missing_sixth_source", lambda a: a["sources"].pop()),
            ("extra_source", lambda a: a["sources"].append(copy.deepcopy(a["sources"][0]))),
            (
                "duplicate_source_owner",
                lambda a: a["sources"][0].update(owner=a["sources"][1]["owner"]),
            ),
            ("missing_guide", lambda a: a["supports"].pop()),
            ("missing_actual_spring_end", lambda a: a["springs"][1]["ends"].pop()),
            (
                "rotation_aliases_physical_node",
                lambda a: a["knot_algebraic_spcs"][0].update(rotation_node=model.root_nodes[0]),
            ),
            (
                "receiving_aliases_support_helper",
                lambda a: a["knot_algebraic_spcs"][0].update(receiving_node=guide_helper),
            ),
            (
                "expansion_aliases_rotation",
                lambda a: a["knot_algebraic_spcs"][0].update(
                    expansion_node=a["knot_algebraic_spcs"][0]["rotation_node"]
                ),
            ),
            (
                "one_knot_changes_signature",
                lambda a: a["knot_algebraic_spcs"][1].update(
                    rotation_node=max(row["node"] for row in a["knot_algebraic_spcs"]) + 1000
                ),
            ),
            ("incomplete_r_directions", lambda a: a["knot_algebraic_spcs"].pop(0)),
            (
                "algebraic_row_claims_physical_axis",
                lambda a: a["knot_algebraic_spcs"][0].update(axis=[1, 0, 0]),
            ),
        )
        try:
            for name, change in changes:
                with self.subTest(alteration=name):
                    payload = copy.deepcopy(data)
                    change(altered_actions(payload))
                    forged = json.dumps(payload, sort_keys=True, allow_nan=False)
                    result.SectionData = forged
                    result.SectionHash = hashlib.sha256(forged.encode()).hexdigest()
                    self.assertEqual(
                        hashlib.sha256(result.SectionData.encode()).hexdigest(), result.SectionHash
                    )
                    (self.directory / (name + ".json")).write_text(forged)
                    # Rehashing storage must not turn invalid physical/native
                    # identities into a valid self-consistent historical record.
                    with self.assertRaises(ValueError):
                        result.Proxy.getSectionForces(result, historical=True)
                    self.assertEqual(result.SectionData, forged)
        finally:
            result.SectionData, result.SectionHash = literal, digest
        self._unchanged_history(result, data, literal, digest, files)

    @staticmethod
    def _unsupported_authored_change(model, kind):
        if kind == "rotational_spring":
            model.springs[1].Kind = "Rotational"
        elif kind == "nonzero_guide":
            model.guides[1].yDisplacement = "0.01 mm"
        elif kind == "redundant_parallel_cycle":
            extra = ObjectsFem.makeConstraintElasticConnector(model.doc, "RedundantInternalSpring")
            extra.Attachment = "Vertices"
            extra.Kind = "Translational"
            extra.Mode = "Two points"
            extra.Axis = "X"
            extra.End1 = (model.upper, ["Vertex2"])
            extra.End2 = (model.right_stem, ["Vertex1"])
            extra.Orientation = App.Rotation()
            extra.Stiffness = "1000 N/mm"
            model.analysis.addObject(extra)
        elif kind == "beam_receiving_rbe":
            rbe = ObjectsFem.makeConstraintRigidBody(model.doc, "UnsupportedBeamReceiver")
            rbe.References = [(model.upper, ["Vertex2"])]
            rbe.ReferenceNode = App.Vector(100, 57, -23)
            for axis in "XYZ":
                setattr(rbe, "TranslationalMode" + axis, "Free")
                setattr(rbe, "RotationalMode" + axis, "Free")
            model.analysis.addObject(rbe)
        elif kind == "contact":
            # Real adjacent CAD faces author an actual Contact request. They
            # are not added as padding to the qualified beam mesh or solved.
            left = model.doc.addObject("Part::Box", "UnsupportedContactLeft")
            right = model.doc.addObject("Part::Box", "UnsupportedContactRight")
            for box in (left, right):
                box.Length = box.Width = box.Height = "1 mm"
            right.Placement.Base = App.Vector(1, 0, 0)
            model.doc.recompute()
            faces = [
                next(
                    "Face" + str(index)
                    for index, face in enumerate(box.Shape.Faces, 1)
                    if abs(face.CenterOfMass.x - 1) < 1e-10
                )
                for box in (left, right)
            ]
            contact = ObjectsFem.makeConstraintContact(model.doc, "UnsupportedNetworkContact")
            contact.References = [(box, [face]) for box, face in zip((left, right), faces)]
            model.analysis.addObject(contact)
        elif kind == "overlapping_sections":
            model.sections[1].References = model.sections[0].References
        elif kind == "missing_native_owner_history":
            model.mesh.ElementGroupReferences = []
        else:
            raise AssertionError("Unknown public authoring control")
        model.doc.recompute()

    def test_unsupported_native_network_requests_are_refused_without_export_or_silent_changes(self):
        for kind in (
            "rotational_spring",
            "nonzero_guide",
            "redundant_parallel_cycle",
            "beam_receiving_rbe",
            "contact",
            "overlapping_sections",
            "missing_native_owner_history",
        ):
            with self.subTest(request=kind):
                doc = App.newDocument("NativeNetworkRefusal")
                self.document_names.append(doc.Name)
                model = make_connected_trees(doc)
                self._unsupported_authored_change(model, kind)
                members = {obj.Name for obj in model.analysis.Group}
                directory = self.directory / kind
                directory.mkdir()
                fea = FemToolsCcx(analysis=model.analysis, solver=model.solver)
                fea.update_objects()
                fea.setup_working_dir(str(directory))
                with self.assertRaises(ValueError):
                    fea.write_inp_file()
                self.assertEqual({obj.Name for obj in model.analysis.Group}, members)
                self.assertTrue(model.solver.BeamSectionForces)
                self.assertFalse(list(directory.glob("*.beam-section*")))
                self.assertFalse(list(directory.glob("*.dat")))
                self.assertFalse(list(directory.glob("*.sta")))

    def test_bare_network_frd_cannot_be_imported_as_mechanical_stress(self):
        from feminout import importCcxFrdResults

        model, result, data, _ = self._completed_network()
        bare_directory = self.directory / "bare"
        bare_directory.mkdir()
        bare = bare_directory / "unbound-network.frd"
        bare.write_bytes(Path(data["provenance"]["frd"]["path"]).read_bytes())
        before = {obj.Name for obj in model.doc.Objects}
        with self.assertRaisesRegex(ValueError, "Bare original-beam FRD"):
            importCcxFrdResults.importFrd(str(bare), model.analysis)
        self.assertEqual({obj.Name for obj in model.doc.Objects}, before)
        self.assertEqual(result.Proxy.getSectionForces(result), data)
