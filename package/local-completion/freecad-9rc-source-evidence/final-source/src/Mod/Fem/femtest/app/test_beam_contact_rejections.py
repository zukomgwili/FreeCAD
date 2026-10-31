# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native admission rejects altered diagnostic declarations on an unchanged deck."""

import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import subprocess

import FreeCAD as App

from femtest.app.beam_contact_fixtures import make_contact_series
from femtest.app.test_beam_contact_native import BeamContactNativeCase


class TestBeamContactRejections(BeamContactNativeCase):
    def _alter_declaration(self, literal, declaration, replace):
        """Change one actual request row, preserving all unrelated declarations."""
        lines = literal.splitlines(keepends=True)
        matching = [
            index
            for index, line in enumerate(lines)
            if line.split()[: len(declaration)] == list(declaration)
        ]
        self.assertEqual(len(matching), 1)
        index = matching[0]
        changed = replace(lines[index].split())
        lines[index] = " ".join(changed) + "\n" if changed is not None else ""
        result = "".join(lines)
        self.assertNotEqual(result, literal)
        return result

    def _complete_output(self, request):
        path = Path(str(request) + ".out")
        if not path.exists():
            return False
        data = json.loads(path.read_text())
        self.assertIsInstance(data, dict)
        return data.get("complete") is True

    def test_native_request_mismatches_cannot_authorize_beam_contact_composition(self):
        base = self.directory
        self.directory = base / "accepted"
        self.directory.mkdir()
        doc = App.newDocument("NativeBeamContactRequestRefusals")
        self.documents.append(doc)
        model = make_contact_series(doc)
        beam, contact, data, local, deck = self._solve(model)
        joint = data["provenance"]["joint"]
        original_deck = Path(joint["deck"]["path"])
        original_beam = Path(joint["beam"]["path"])
        original_contact = Path(joint["contact"]["path"])
        original_paths = {
            original_deck,
            original_beam,
            original_contact,
            Path(joint["beam"]["output"]),
            Path(joint["contact"]["output"]),
            Path(joint["frd"]["path"]),
        }
        originals = {path: path.read_bytes() for path in original_paths}
        self.assertEqual(originals[original_deck], deck)

        def different_nonce(fields):
            fields[1] = "0" * 32 if fields[1] != "0" * 32 else "1" * 32
            return fields

        def unknown_slave_surface(fields):
            fields[2] = "MissingNativeSlave"
            return fields

        def beam_as_contact_face(fields):
            fields[2] = str(model.beam_elements[0])
            return fields

        def alias_solid_owner(fields):
            fields[3] = fields[2]
            return fields

        # These messages come from the native declaration and cross-observer
        # admission guards, before any constitutive iteration or result frame.
        cases = (
            (
                "contact_child_nonce",
                "contact",
                ("REQUEST",),
                different_nonce,
                "*ERROR CCX beam section V4: contact child identity, pair, law or time "
                "differs from the validated mixed request",
            ),
            (
                "contact_surface_identity",
                "contact",
                ("PAIR",),
                unknown_slave_surface,
                "*ERROR CCX contact state V1: requested pair must identify exactly one "
                "native slave/master declaration",
            ),
            (
                "beam_element_as_contact_face",
                "beam",
                ("CONTACT_FACE", "SLAVE"),
                beam_as_contact_face,
                "*ERROR CCX beam section V4: selected contact face is not an exterior "
                "face of its declared true solid owner",
            ),
            (
                "aliased_contact_solid_owner",
                "beam",
                ("CONTACT",),
                alias_solid_owner,
                "*ERROR CCX beam section V4: contact composition requires a complete "
                "physical guide and authenticated native pair",
            ),
            (
                "omitted_physical_port_guide",
                "beam",
                ("PORT_GUIDE",),
                lambda _fields: None,
                "*ERROR CCX beam section V4: contact composition requires a complete "
                "physical guide and authenticated native pair",
            ),
        )
        observer_variables = {
            "CCX_FORCE_ACCOUNTING_REQUEST",
            "CCX_CONTACT_STATE_REQUEST",
            "CCX_BEAM_SECTION_REQUEST",
            "CCX_9ZT_DIAGNOSTIC",
        }
        ordinary_environment = {
            key: value for key, value in os.environ.items() if key not in observer_variables
        }
        preference = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/Ccx").GetInt(
            "AnalysisNumCPUs", 1
        )
        ordinary_environment["OMP_NUM_THREADS"] = str(
            preference if preference > 1 else multiprocessing.cpu_count()
        )
        receipts = {}
        for name, channel, declaration, replace, diagnostic in cases:
            with self.subTest(declaration=name):
                directory = base / name
                directory.mkdir()
                copied_deck = directory / original_deck.name
                requests = {
                    "beam": directory / original_beam.name,
                    "contact": directory / original_contact.name,
                }
                shutil.copyfile(original_deck, copied_deck)
                shutil.copyfile(original_beam, requests["beam"])
                shutil.copyfile(original_contact, requests["contact"])
                selected = requests[channel]
                selected.write_text(
                    self._alter_declaration(selected.read_text(), declaration, replace)
                )
                self.assertEqual(copied_deck.read_bytes(), deck)
                self.assertFalse(self._complete_output(requests["beam"]))
                self.assertFalse(self._complete_output(requests["contact"]))
                environment = dict(ordinary_environment)
                environment["CCX_BEAM_SECTION_REQUEST"] = str(requests["beam"].resolve())
                environment["CCX_CONTACT_STATE_REQUEST"] = str(requests["contact"].resolve())
                child = subprocess.run(
                    [self.binary, "-i", copied_deck.stem],
                    cwd=directory,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    timeout=120,
                    check=False,
                )
                (directory / "stdout.txt").write_bytes(child.stdout)
                (directory / "stderr.txt").write_bytes(child.stderr)
                output = (child.stdout + child.stderr).decode(errors="replace")
                self.assertNotEqual(child.returncode, 0, output)
                self.assertIn(diagnostic, output)
                self.assertEqual(copied_deck.read_bytes(), deck)
                complete = {
                    key: self._complete_output(request) for key, request in requests.items()
                }
                self.assertFalse(all(complete.values()), "Rejected child published a complete pair")
                for path, literal in originals.items():
                    self.assertEqual(path.read_bytes(), literal)
                self.assertEqual(beam.Proxy.getSectionForces(beam), data)
                self.assertEqual(contact.Proxy.getContactStates(contact), local)
                receipts[name] = {
                    "returncode": child.returncode,
                    "expected_native_diagnostic": diagnostic,
                    "deck_sha256": hashlib.sha256(copied_deck.read_bytes()).hexdigest(),
                    "binary_sha256": joint["binary"]["sha256"],
                    "beam_request_sha256": hashlib.sha256(
                        requests["beam"].read_bytes()
                    ).hexdigest(),
                    "contact_request_sha256": hashlib.sha256(
                        requests["contact"].read_bytes()
                    ).hexdigest(),
                    "complete_observations": complete,
                    "accepted_sources_and_results_unchanged": True,
                }
        (base / "native-request-refusals.json").write_text(json.dumps(receipts, indent=2))
