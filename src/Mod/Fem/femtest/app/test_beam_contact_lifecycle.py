# SPDX-License-Identifier: LGPL-2.1-or-later
"""Authenticate both native observations as one live, owned completion."""

import hashlib
import json
import multiprocessing
import os
from copy import deepcopy
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import FreeCAD as App

from femtest.app.beam_contact_fixtures import make_contact_series
from femtest.app.test_beam_contact_native import BeamContactNativeCase
from femtools import beam_section_forces as bs
from femtools.ccxtools import FemToolsCcx


class TestBeamContactLifecycle(BeamContactNativeCase):
    def _fresh(self, label):
        if not hasattr(self, "base_directory"):
            self.base_directory = self.directory
        self.directory = self.base_directory / label
        self.directory.mkdir()
        doc = App.newDocument("PairedContactLifecycle")
        self.documents.append(doc)
        model = make_contact_series(doc, friction=False)
        return doc, model

    def _withdrawn(self, beam, contact, literals):
        self.assertFalse(beam.CompletedRun)
        self.assertFalse(contact.CompletedRun)
        self.assertFalse(beam.Status.startswith("Current"), beam.Status)
        self.assertFalse(contact.Status.startswith("Current"), contact.Status)
        self.assertEqual((beam.SectionData, contact.ContactData), literals)
        with self.assertRaises(ValueError):
            beam.Proxy.getSectionForces(beam)
        with self.assertRaises(ValueError):
            contact.Proxy.getContactStates(contact)
        self.assertEqual(
            beam.Proxy.getSectionForces(beam, historical=True)["schema"], "CCX_BEAM_SECTION_V4"
        )

    def test_each_owned_source_withdraws_both_without_rewriting_history(self):
        for channel in (
            "beam_request",
            "contact_request",
            "beam_output",
            "contact_output",
            "deck",
            "frd",
        ):
            with self.subTest(source=channel):
                doc, model = self._fresh(channel)
                beam, contact, data, local, deck = self._solve(model)
                joint = data["provenance"]["joint"]
                literals = beam.SectionData, contact.ContactData
                if channel in ("deck", "frd"):
                    source = joint[channel]["path"]
                else:
                    owner, kind = channel.split("_")
                    source = joint[owner]["path" if kind == "request" else "output"]
                path = Path(source)
                original = path.read_bytes()
                try:
                    path.write_bytes(original + b"\n")
                    # Either getter must detect corruption in either channel.
                    if channel.startswith("contact"):
                        with self.assertRaises(ValueError):
                            beam.Proxy.getSectionForces(beam)
                    else:
                        with self.assertRaises(ValueError):
                            contact.Proxy.getContactStates(contact)
                    self._withdrawn(beam, contact, literals)
                finally:
                    path.write_bytes(original)
                self._withdrawn(beam, contact, literals)

    def test_physical_edits_and_detached_links_withdraw_both(self):
        for mutation in (
            "force",
            "contact_law",
            "analysis_link",
            "mesh_link",
            "solver_link",
            "membership",
        ):
            with self.subTest(mutation=mutation):
                doc, model = self._fresh(mutation)
                beam, contact, data, local, deck = self._solve(model)
                literals = beam.SectionData, contact.ContactData
                if mutation == "force":
                    model.force.Force = "101 N"
                elif mutation == "contact_law":
                    model.contact.Slope = "90000 MPa/mm"
                elif mutation == "analysis_link":
                    beam.Analysis = None
                elif mutation == "mesh_link":
                    contact.Mesh = None
                elif mutation == "solver_link":
                    beam.Solver = None
                else:
                    model.analysis.removeObject(contact)
                self._withdrawn(beam, contact, literals)

    def test_invalid_literal_or_hash_withdraws_its_companion(self):
        for channel in ("beam", "contact"):
            with self.subTest(channel=channel):
                doc, model = self._fresh(channel)
                beam, contact, data, local, deck = self._solve(model)
                literal, digest = (
                    ("SectionData", "SectionHash")
                    if channel == "beam"
                    else ("ContactData", "ContactHash")
                )
                result = beam if channel == "beam" else contact
                # Rehashing an edited literal must not mint a fresh solver run.
                changed = json.loads(getattr(result, literal))
                changed["provenance"]["stdout_sha256"] = "0" * 64
                encoded = json.dumps(changed, sort_keys=True, allow_nan=False)
                setattr(result, literal, encoded)
                setattr(result, digest, hashlib.sha256(encoded.encode()).hexdigest())
                self._withdrawn(beam, contact, (beam.SectionData, contact.ContactData))

    def test_deleting_either_companion_withdraws_the_surviving_literal(self):
        for channel in ("beam", "contact"):
            with self.subTest(deleted=channel):
                doc, model = self._fresh(channel)
                beam, contact, data, local, deck = self._solve(model)
                removed, survivor = (beam, contact) if channel == "beam" else (contact, beam)
                attribute = "ContactData" if channel == "beam" else "SectionData"
                literal = getattr(survivor, attribute)
                doc.removeObject(removed.Name)
                self.assertFalse(survivor.CompletedRun)
                self.assertFalse(survivor.Status.startswith("Current"))
                self.assertEqual(getattr(survivor, attribute), literal)
                with self.assertRaises(ValueError):
                    if channel == "beam":
                        survivor.Proxy.getContactStates(survivor)
                    else:
                        survivor.Proxy.getSectionForces(survivor)

    def test_late_child_completion_cannot_withdraw_a_newer_owned_pair(self):
        from femtools import beam_contact_results as joint
        from femtools import contact_state as cs

        doc, model = self._fresh("first")
        captured = {}
        beam_context, contact_context = bs.run_context, cs.run_context

        def remember_beam(fea, *args, **kwargs):
            captured["fea"] = fea
            captured["beam"] = beam_context(fea, *args, **kwargs)
            return captured["beam"]

        def remember_contact(fea, *args, **kwargs):
            captured["contact"] = contact_context(fea, *args, **kwargs)
            return captured["contact"]

        with patch.object(bs, "run_context", side_effect=remember_beam), patch.object(
            cs, "run_context", side_effect=remember_contact
        ):
            self._solve(model)
        self.directory = self.base_directory / "newer"
        self.directory.mkdir()
        beam, contact, data, local, deck = self._solve(model)
        self.assertNotEqual(data["request"], captured["beam"]["metadata"]["run"]["token"])
        self.assertTrue(
            joint.finish_run(
                captured["fea"], captured["beam"], captured["contact"], 0, "late completion"
            )
        )
        self.assertEqual(beam.Proxy.getSectionForces(beam), data)
        self.assertEqual(contact.Proxy.getContactStates(contact), local)

    def test_getting_withdrawn_data_during_repeat_run_cannot_cancel_new_child(self):
        doc, model = self._fresh("repeat")
        beam, contact, data, local, deck = self._solve(model)
        fea = FemToolsCcx(analysis=model.analysis, solver=model.solver)
        fea.update_objects()
        fea.setup_working_dir(str(self.directory))
        fea.inp_file_name = data["provenance"]["deck"]
        original_popen = subprocess.Popen
        probed = []

        def start_and_query_old(*args, **kwargs):
            child = original_popen(*args, **kwargs)
            if "-i" in args[0]:
                probed.append(True)
                with self.assertRaises(ValueError):
                    beam.Proxy.getSectionForces(beam)
                with self.assertRaises(ValueError):
                    contact.Proxy.getContactStates(contact)
            return child

        with patch("femtools.ccxtools.subprocess.Popen", side_effect=start_and_query_old):
            self.assertEqual(fea.ccx_run(), 0, fea.ccx_stdout + fea.ccx_stderr)
        self.assertEqual(probed, [True])
        self.assertEqual(Path(fea.inp_file_name).read_bytes(), deck)
        newest = beam.Proxy.getSectionForces(beam)
        self.assertNotEqual(newest["request"], data["request"])
        self.assertEqual(newest["provenance"]["model_hash"], data["provenance"]["model_hash"])
        self.assertTrue(contact.Proxy.getContactStates(contact))

    def test_new_export_withdraws_both_before_a_failed_input_capture(self):
        doc, model = self._fresh("export")
        beam, contact, data, local, deck = self._solve(model)
        literals = beam.SectionData, contact.ContactData
        fea = FemToolsCcx(analysis=model.analysis, solver=model.solver)
        fea.update_objects()
        fea.setup_working_dir(str(self.directory))
        from femtools import contact_state

        with patch.object(contact_state, "begin_export", side_effect=ValueError("capture failed")):
            with self.assertRaisesRegex(ValueError, "capture failed"):
                fea.write_inp_file()
        self._withdrawn(beam, contact, literals)

    def test_native_prescriptions_and_child_frame_bindings_cannot_be_relabelled(self):
        doc, model = self._fresh("wire")
        beam, contact, data, local, deck = self._solve(model)
        native = {key: value for key, value in data.items() if key != "provenance"}
        actions = native["frames"][0]["native_actions"]
        for rows in (
            actions["support"]["spcs"],
            actions["solid_support"]["spcs"],
            actions["port_guide"]["spcs"],
            actions["port"]["algebraic_spcs"],
        ):
            for row in rows:
                self.assertIn("native_prescribed_value", row)
                self.assertIn("native_displacement", row)
                if row["role"] != "ALGEBRAIC":
                    self.assertEqual(row["native_prescribed_value"], 0)
        for mutation in ("physical_prescription", "missing_displacement", "child", "frame_child"):
            with self.subTest(mutation=mutation):
                changed = deepcopy(native)
                if mutation == "physical_prescription":
                    changed["frames"][0]["native_actions"]["port_guide"]["spcs"][0][
                        "native_prescribed_value"
                    ] = 1
                elif mutation == "missing_displacement":
                    del changed["frames"][0]["native_actions"]["solid_support"]["spcs"][0][
                        "native_displacement"
                    ]
                elif mutation == "child":
                    changed["contact_request"] = "0" * 32
                else:
                    changed["frames"][0]["contact_request"] = "0" * 32
                with self.assertRaises(ValueError):
                    bs._validate_output(changed, data["provenance"])
        from femtools import beam_contact_results as joint

        fea = SimpleNamespace(
            analysis=model.analysis,
            solver=model.solver,
            mesh=model.mesh,
            inp_file_name=data["provenance"]["deck"],
        )
        contexts = (
            {"metadata": data["provenance"], "output": data["provenance"]["output"]},
            {"metadata": local["provenance"], "output": local["provenance"]["output"]},
        )
        joint._prevalidate(fea, *contexts)
        path = Path(local["provenance"]["output"])
        original = path.read_bytes()
        try:
            changed = json.loads(original)
            changed["frames"][0]["increment"] += 1
            path.write_text(json.dumps(changed, allow_nan=False))
            with self.assertRaisesRegex(ValueError, "completion frames"):
                joint._prevalidate(fea, *contexts)
        finally:
            path.write_bytes(original)
        self.assertEqual(beam.Proxy.getSectionForces(beam), data)
        self.assertEqual(contact.Proxy.getContactStates(contact), local)

    def test_partial_publication_keeps_no_single_current_observation(self):
        doc, model = self._fresh("partial")
        if self.explicit_binary:
            model.solver.NativeAccountingSolver = self.explicit_binary
        fea = FemToolsCcx(analysis=model.analysis, solver=model.solver)
        fea.update_objects()
        fea.setup_working_dir(str(self.directory))
        self.assertFalse(fea.check_prerequisites())
        self.assertFalse(fea.write_inp_file())
        deck = Path(fea.inp_file_name).read_bytes()
        with patch.object(bs, "finish_run", side_effect=ValueError("beam publication failed")):
            with self.assertRaisesRegex(ValueError, "beam publication failed"):
                fea.ccx_run()
        self.assertEqual(Path(fea.inp_file_name).read_bytes(), deck)
        contacts = [
            o
            for o in model.analysis.Group
            if getattr(getattr(o, "Proxy", None), "Type", "") == "Fem::ContactStateResult"
        ]
        self.assertEqual(len(contacts), 1)
        result = contacts[0]
        self.assertTrue(result.ContactData)
        self.assertFalse(result.CompletedRun)
        self.assertFalse(result.Status.startswith("Current"))
        with self.assertRaises(ValueError):
            result.Proxy.getContactStates(result)

    def test_save_reopen_preserves_both_literals_as_historical(self):
        doc, model = self._fresh("reopen")
        beam, contact, data, local, deck = self._solve(model)
        literals = beam.SectionData, contact.ContactData
        hashes = beam.SectionHash, contact.ContactHash
        names = beam.Name, contact.Name
        path = self.directory / "paired-history.FCStd"
        doc.recompute()
        doc.saveAs(str(path))
        self.documents.remove(doc)
        App.closeDocument(doc.Name)
        reopened = App.openDocument(str(path))
        self.documents.append(reopened)
        beam, contact = (reopened.getObject(name) for name in names)
        self.assertEqual((beam.SectionHash, contact.ContactHash), hashes)
        self._withdrawn(beam, contact, literals)
        self.assertTrue(beam.Status.startswith(("Historical", "Stale")))
        self.assertTrue(contact.Status.startswith(("Historical", "Stale")))

    def test_observers_preserve_the_ordinary_native_fields_on_the_same_stock_deck(self):
        doc, model = self._fresh("observed")
        beam, contact, data, local, deck = self._solve(model)

        def literal_fields(path):
            # The generic reader includes NaN eigenmode placeholders in a
            # static result, which cannot be compared with dict equality.
            # Compare the literal mesh and fields exactly, excluding only
            # nonphysical wall-clock date/time headers. No numeric tolerance.
            return [
                line
                for line in Path(path).read_bytes().splitlines()
                if line[4:10] not in (b"1UDATE", b"1UTIME")
                and not line.startswith(b"    1UCOMPILETIME")
            ]

        original = literal_fields(data["provenance"]["frd"]["path"])
        environment = {
            key: value
            for key, value in os.environ.items()
            if key
            not in {
                "CCX_FORCE_ACCOUNTING_REQUEST",
                "CCX_CONTACT_STATE_REQUEST",
                "CCX_BEAM_SECTION_REQUEST",
                "CCX_9ZT_DIAGNOSTIC",
            }
        }
        preference = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/Ccx").GetInt(
            "AnalysisNumCPUs", 1
        )
        environment["OMP_NUM_THREADS"] = str(
            preference if preference > 1 else multiprocessing.cpu_count()
        )
        binaries = {"candidate_inactive": self.binary}
        if os.environ.get("R9_BASELINE_SOLVER"):
            binaries["previous_inactive"] = os.environ["R9_BASELINE_SOLVER"]
        receipts = {}
        for label, binary in binaries.items():
            directory = self.base_directory / label
            directory.mkdir()
            path = directory / Path(data["provenance"]["deck"]).name
            path.write_bytes(deck)
            completed = subprocess.run(
                [binary, "-i", path.stem],
                cwd=directory,
                env=environment,
                capture_output=True,
                timeout=120,
            )
            (directory / "stdout.txt").write_bytes(completed.stdout)
            (directory / "stderr.txt").write_bytes(completed.stderr)
            self.assertEqual(completed.returncode, 0, completed.stdout.decode(errors="replace"))
            self.assertEqual(path.read_bytes(), deck)
            self.assertEqual(literal_fields(path.with_suffix(".frd")), original)
            receipts[label] = {
                "binary": str(Path(binary).resolve()),
                "binary_sha256": bs._sha(binary),
                "deck_sha256": bs._sha(path),
                "literal_native_mesh_and_fields_equal": True,
            }
        (self.base_directory / "mechanics-equivalence.json").write_text(
            json.dumps(receipts, indent=2)
        )
