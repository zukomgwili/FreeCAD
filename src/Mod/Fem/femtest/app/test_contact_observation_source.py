# SPDX-License-Identifier: LGPL-2.1-or-later
"""Qualification of synthetic serialized upstream source contracts.

Run-owned output custody is separately tested through the actual runner in
test_movement_provenance. These small FRD inputs are not engineering evidence.
"""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import FreeCAD
import Fem
import ObjectsFem
import Part

from femtools import force_accounting


class TestContactObservationSource(unittest.TestCase):
    def setUp(self):
        self.doc = FreeCAD.newDocument("ContactSourceTest")
        self.scratch = tempfile.TemporaryDirectory()
        self.root = Path(self.scratch.name).resolve()
        geometry = self.doc.addObject("Part::Feature", "Geometry")
        geometry.Shape = Part.makeBox(1, 1, 1)
        self.analysis = ObjectsFem.makeAnalysis(self.doc)
        self.mesh = ObjectsFem.makeMeshGmsh(self.doc)
        self.mesh.Shape = geometry
        mesh = Fem.FemMesh()
        for node, point in zip((11, 23, 37, 41), ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1))):
            mesh.addNode(*point, node)
        mesh.addVolume([11, 23, 37, 41], 101)
        self.mesh.FemMesh = mesh
        self.analysis.addObject(self.mesh)
        self.solver = ObjectsFem.makeSolverCalculiXCcxTools(self.doc)
        self.solver.NativeForceAccounting = True
        self.analysis.addObject(self.solver)
        self.doc.recompute()
        self.result = force_accounting.make_result(self.analysis)
        for suffix in ("inp", "accounting", "solver"):
            (self.root / ("model." + suffix)).write_text("Synthetic source identity\n")
        self.deck = (
            "*HEADING\nSynthetic static source\n*STEP\n*STATIC\n1,1\n" "*NODE FILE\nU\n*END STEP\n"
        )
        (self.root / "model.inp").write_text(self.deck)
        self.frd = self.root / "model.frd"
        self.text = self.frd_text()
        self.bind(self.text)

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)
        self.scratch.cleanup()

    def frd_text(self, *, time="1.000000000", extra_node=False):
        nodes = list(self.mesh.FemMesh.Nodes.items())
        if extra_node:
            nodes.append((999, (9, 8, 7)))
        lines = ["    1C", f"    2C                  {len(nodes):12d}{'':37s}1"]
        for node, point in nodes:
            lines.append(f" -1{node:10d}" + "".join(f"{value:12.5E}" for value in point))
        quadratic = len(self.mesh.FemMesh.getElementNodes(101)) == 10
        kind = 6 if quadratic else 3
        connectivity = (23, 11, 37, 41, 53, 61, 59, 71, 67, 73) if quadratic else (23, 11, 37, 41)
        lines += [
            " -3",
            f"    3C                  {1:12d}{'':37s}1",
            f" -1       101{kind:5d}    0    1",
            " -2" + "".join(f"{node:10d}" for node in connectivity),
            " -3",
            "    1PSTEP                         1           1           1          ",
        ]
        lines.append(f"  100CL  101{time:>12s}{len(nodes):12d}{'':21s}0    1           1")
        lines += [
            " -4  DISP        4    1",
            " -5  D1          1    2    1    0",
            " -5  D2          1    2    2    0",
            " -5  D3          1    2    3    0",
            " -5  ALL         1    2    0    0    1ALL",
        ]
        for node, point in nodes:
            vector = (0.125, -0.25, 0.5) if node == 37 else (0.0, 0.0, 0.0)
            lines.append(f" -1{node:10d}" + "".join(f"{value:12.5E}" for value in vector))
        return "\n".join(lines + [" -3", " 9999", ""])

    def bind(self, text):
        self.frd.write_text(text)

        def identity(path):
            return hashlib.sha256(path.read_bytes()).hexdigest()

        data = {
            "schema": force_accounting.SCHEMA,
            "analysis": self.analysis.Name,
            "mesh": self.mesh.Name,
            "model_digest": force_accounting._model_digest(self.analysis, self.mesh),
            "deck_sha256": identity(self.root / "model.inp"),
            "request_sha256": identity(self.root / "model.accounting"),
            "binary_sha256": identity(self.root / "model.solver"),
            "binary": str(self.root / "model.solver"),
            "end_time": self.solver.TimePeriod.getValueAs("s").Value,
        }
        data["movement_source"] = {
            "schema": "FREECAD_MOVEMENT_SOURCE_V1",
            "status": "BOUND",
            "path": str(self.frd),
            "sha256": identity(self.frd),
            "deck": str(self.root / "model.inp"),
            "request": str(self.root / "model.accounting"),
            "requested_end_time": data["end_time"],
            **{
                key: data[key]
                for key in (
                    "deck_sha256",
                    "request_sha256",
                    "binary_sha256",
                    "model_digest",
                    "binary",
                )
            },
        }
        self.result.AccountingData = json.dumps(data, sort_keys=True)
        self.result.Status = "Current native accounting; not design acceptance"

    def test_original_sparse_node_ids_and_native_vectors_are_preserved(self):
        from femresult.contact_observation_source import load_source

        values, source = load_source(self.analysis, self.mesh, self.result)
        self.assertEqual(set(values), {11, 23, 37, 41})
        self.assertEqual(values[37], (0.125, -0.25, 0.5))
        self.assertEqual(source["observed_time"], 1.0)
        self.assertEqual(source["frd"]["path"], str(self.frd))

    def test_duplicate_geometry_or_displacement_ids_are_not_silently_overwritten(self):
        from femresult.contact_observation_source import load_source

        lines = self.text.splitlines()
        node = next(line for line in lines if line.startswith(" -1        11"))
        element = " -1       101    3    0    1\n -2        23        11        37        41"
        displacement = next(line for line in reversed(lines) if line.startswith(" -1        37"))
        for name, record in (("node", node), ("element", element), ("displacement", displacement)):
            with self.subTest(record=name):
                self.bind(self.text.replace(record, record + "\n" + record, 1))
                with self.assertRaisesRegex(ValueError, "[Dd]uplicate"):
                    load_source(self.analysis, self.mesh, self.result)

    def test_local_output_and_unbound_deck_includes_are_not_global_displacement(self):
        from femresult.contact_observation_source import load_source

        for deck in (
            self.deck.replace("*NODE FILE", "*NODE FILE, GLOBAL=NO"),
            "*INCLUDE, INPUT=unbound.inc\n" + self.deck,
            self.deck.replace("*STATIC", "*DYNAMIC"),
            self.deck + "*STEP\n*STATIC\n1,1\n*END STEP\n",
        ):
            with self.subTest(deck=deck):
                (self.root / "model.inp").write_text(deck)
                self.bind(self.text)
                with self.assertRaisesRegex(ValueError, "[Gg]lobal|[Ii]nclude|[Ss]tatic|[Ss]tep"):
                    load_source(self.analysis, self.mesh, self.result)

    def test_wrong_coordinates_or_original_volume_topology_cannot_qualify(self):
        from femresult.contact_observation_source import load_source

        extra = self.frd_text(extra_node=True)
        node_line = next(
            line for line in self.text.splitlines() if line.startswith(" -1        23")
        )
        changed = node_line[:13] + f"{1.01:12.5E}" + node_line[25:]
        for name, text in (
            ("coordinate", self.text.replace(node_line, changed, 1)),
            ("volume ID", self.text.replace(" -1       101    3", " -1       102    3")),
            (
                "connectivity",
                extra.replace(
                    " -2        23        11        37        41",
                    " -2        23        11        37       999",
                ),
            ),
        ):
            with self.subTest(change=name):
                self.bind(text)
                with self.assertRaisesRegex(ValueError, "[Cc]oordinate|[Tt]opology|[Vv]olume"):
                    load_source(self.analysis, self.mesh, self.result)

    def test_ambiguous_or_nonstatic_final_displacement_frames_are_rejected(self):
        from femresult.contact_observation_source import load_source

        start = self.text.index("    1PSTEP")
        block = self.text[start : self.text.index(" 9999")]
        header = next(line for line in self.text.splitlines() if line[2:7] == "100CL")
        dynamic = header[:57] + "1" + header[58:]
        for name, text in (
            ("duplicate final", self.text.replace(" 9999", block + " 9999")),
            (
                "second step",
                self.text.replace(
                    "1           1           1          ", "1           1           2          "
                ),
            ),
            ("dynamic", self.text.replace(header, dynamic)),
            ("imaginary displacement", self.text.replace("DISP ", "DISPI")),
            ("unknown component", self.text.replace(" -5  D1 ", " -5  DX ")),
        ):
            with self.subTest(frame=name):
                self.bind(text)
                with self.assertRaisesRegex(
                    ValueError, "[Ff]rame|[Ss]tatic|[Cc]omponent|[Dd]isplacement"
                ):
                    load_source(self.analysis, self.mesh, self.result)

    def test_native_reader_sidecar_is_not_an_unbound_input(self):
        from femresult.contact_observation_source import load_source

        (self.root / "model_inout_nodes.txt").write_text("1,11,23\n")
        with self.assertRaisesRegex(ValueError, "[Uu]nbound.*sidecar"):
            load_source(self.analysis, self.mesh, self.result)

    def test_tet10_corner_and_midside_reassignment_is_not_the_same_topology(self):
        from femresult.contact_observation_source import load_source

        mesh = Fem.FemMesh()
        nodes = [
            (11, (0, 0, 0)),
            (23, (1, 0, 0)),
            (37, (0, 1, 0)),
            (41, (0, 0, 1)),
            (53, (0.5, 0, 0)),
            (59, (0.5, 0.5, 0)),
            (61, (0, 0.5, 0)),
            (67, (0, 0, 0.5)),
            (71, (0.5, 0, 0.5)),
            (73, (0, 0.5, 0.5)),
        ]
        for node, point in nodes:
            mesh.addNode(*point, node)
        mesh.addVolume([node for node, point in nodes], 101)
        self.mesh.FemMesh = mesh
        text = self.frd_text()
        self.bind(text)
        values, source = load_source(self.analysis, self.mesh, self.result)
        self.assertEqual(len(values), 10)
        connectivity = next(line for line in text.splitlines() if line.startswith(" -2"))
        # Swap the first corner and first midside in the literal record, without
        # changing its node set, to expose a higher-order association error.
        entries = [23, 11, 37, 41, 53, 61, 59, 71, 67, 73]
        entries[0], entries[4] = entries[4], entries[0]
        malformed = " -2" + "".join(f"{node:10d}" for node in entries)
        self.bind(text.replace(connectivity, malformed))
        with self.assertRaisesRegex(ValueError, "[Tt]opology|[Oo]rder"):
            load_source(self.analysis, self.mesh, self.result)

    def test_initial_adjustment_is_rejected_even_below_frd_print_precision(self):
        from femresult.contact_observation_source import load_source

        for card in (
            "*CONTACT PAIR, INTERACTION=Tiny, ADJUST=1E-12\nSlave,Master\n",
            "*TIE, NAME=MovingByDefault\nSlave,Master\n",
            "*IMPERFECTION, FILE=unbound\n1,1E-12\n",
        ):
            with self.subTest(card=card):
                (self.root / "model.inp").write_text(card + self.deck)
                self.bind(self.text)
                with self.assertRaisesRegex(ValueError, "[Aa]djust|[Rr]eference|[Gg]eometry"):
                    load_source(self.analysis, self.mesh, self.result)
        (self.root / "model.inp").write_text(self.deck)
        contact = ObjectsFem.makeConstraintContact(self.doc)
        contact.Adjust = "0.000000000001 mm"
        self.analysis.addObject(contact)
        self.bind(self.text)
        with self.assertRaisesRegex(ValueError, "[Aa]djust|[Rr]eference"):
            load_source(self.analysis, self.mesh, self.result)

    def test_final_time_must_match_exactly_not_with_a_solver_tolerance(self):
        from femresult.contact_observation_source import load_source

        self.solver.TimePeriod = "1.0000000001 s"
        self.bind(self.text)
        with self.assertRaisesRegex(ValueError, "exact final|rounded|frame"):
            load_source(self.analysis, self.mesh, self.result)
        self.solver.TimePeriod = "0.1 s"
        self.bind(self.frd_text(time="1.00000E-01"))
        values, source = load_source(self.analysis, self.mesh, self.result)
        self.assertEqual(source["observed_time"], 0.1)

    def test_missing_or_nonfinite_physical_u_does_not_become_a_zero_vector(self):
        from femresult.contact_observation_source import load_source, validate_source

        lines = self.text.splitlines()
        row = next(line for line in reversed(lines) if line.startswith(" -1        41"))
        header = next(line for line in lines if line[2:7] == "100CL")
        incomplete = self.text.replace(header, header[:24] + f"{3:12d}" + header[36:])
        # Only remove the field row; the node-coordinate row remains complete.
        index = incomplete.rindex(row)
        incomplete = incomplete[:index] + incomplete[index + len(row) :]
        invalid = (
            self.text[: self.text.rindex(row)]
            + row[:13]
            + f"{'NAN':>12s}"
            + row[25:]
            + self.text[self.text.rindex(row) + len(row) :]
        )
        for text in (incomplete, invalid):
            with self.subTest(case=text[-200:]):
                self.bind(text)
                # The public cheap seam verifies source custody, not U values.
                self.assertEqual(
                    validate_source(self.analysis, self.mesh, self.result)["requested_end_time"],
                    1.0,
                )
                with self.assertRaisesRegex(ValueError, "physical|nonfinite|displacement"):
                    load_source(self.analysis, self.mesh, self.result)

    def test_file_or_model_changes_reject_without_rewriting_accounting_history(self):
        from femresult.contact_observation_source import validate_source

        for path in (
            self.root / "model.inp",
            self.root / "model.accounting",
            self.root / "model.solver",
            self.frd,
        ):
            with self.subTest(file=path.name):
                original = path.read_bytes()
                data = self.result.AccountingData
                path.write_bytes(original + b"changed\n")
                try:
                    with self.assertRaisesRegex(ValueError, "file changed"):
                        validate_source(self.analysis, self.mesh, self.result)
                    self.assertEqual(self.result.AccountingData, data)
                finally:
                    path.write_bytes(original)
        self.solver.GeometricalNonlinearity = True
        with self.assertRaisesRegex(ValueError, "stale|physical"):
            validate_source(self.analysis, self.mesh, self.result)

    def test_legacy_or_mismatched_bindings_are_explicitly_unavailable(self):
        from femresult.contact_observation_source import validate_source

        original = json.loads(self.result.AccountingData)
        variants = []
        missing = dict(original)
        missing.pop("movement_source")
        variants.append(missing)
        unavailable = json.loads(json.dumps(original))
        unavailable["movement_source"]["status"] = "UNAVAILABLE"
        variants.append(unavailable)
        wrong = json.loads(json.dumps(original))
        wrong["movement_source"]["model_digest"] = "0" * 64
        variants.append(wrong)
        for data in variants:
            with self.subTest(source=data.get("movement_source", {}).get("status")):
                self.result.AccountingData = json.dumps(data, sort_keys=True)
                with self.assertRaisesRegex(ValueError, "unavailable|binding"):
                    validate_source(self.analysis, self.mesh, self.result)
                self.assertTrue(self.result.Status.startswith("Current native accounting"))

    def test_source_changed_during_native_file_read_is_not_returned(self):
        from femresult.contact_observation_source import load_source
        from feminout import importCcxFrdResults

        original_open = importCcxFrdResults.pyopen
        target = self.frd

        class ExternalWriterOnClose:
            def __init__(self, stream):
                self.stream = stream

            def __iter__(self):
                return iter(self.stream)

            def close(self):
                self.stream.close()
                target.write_bytes(target.read_bytes() + b"\n")

        def opening(path, *args, **kwargs):
            stream = original_open(path, *args, **kwargs)
            return ExternalWriterOnClose(stream) if Path(path) == target else stream

        # This is a filesystem-boundary change; the real native reader still
        # decodes the actual file, and no result/decode function is substituted.
        with mock.patch.object(importCcxFrdResults, "pyopen", side_effect=opening):
            with self.assertRaisesRegex(ValueError, "changed"):
                load_source(self.analysis, self.mesh, self.result)

    def test_changed_and_restored_source_during_native_read_is_not_returned(self):
        from femresult.contact_observation_source import load_source
        from feminout import importCcxFrdResults

        target = self.frd
        original_bytes = target.read_bytes()
        row = next(
            line for line in reversed(self.text.splitlines()) if line.startswith(" -1        37")
        )
        altered = row[:13] + f"{0.875:12.5E}" + row[25:]
        changed_bytes = original_bytes.replace(row.encode(), altered.encode())
        original_open = importCcxFrdResults.pyopen

        class ExternalWriterRestoresOnClose:
            def __init__(self, stream):
                self.stream = stream

            def __iter__(self):
                return iter(self.stream)

            def close(self):
                self.stream.close()
                target.write_bytes(original_bytes)

        def opening(path, *args, **kwargs):
            if Path(path) != target:
                return original_open(path, *args, **kwargs)
            # A real external filesystem change supplies different U during
            # decoding, then restores the byte-exact input before the posthash.
            # The actual native decoder is never replaced or mocked.
            target.write_bytes(changed_bytes)
            return ExternalWriterRestoresOnClose(original_open(path, *args, **kwargs))

        with mock.patch.object(importCcxFrdResults, "pyopen", side_effect=opening):
            with self.assertRaisesRegex(ValueError, "changed"):
                load_source(self.analysis, self.mesh, self.result)
        self.assertEqual(target.read_bytes(), original_bytes)
