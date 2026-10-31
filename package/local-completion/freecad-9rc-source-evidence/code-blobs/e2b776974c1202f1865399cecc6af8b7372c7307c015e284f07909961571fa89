"""Separate-process public restore, retaining exact paired historical literals."""

import hashlib
import json
import os
from pathlib import Path
import unittest

import FreeCAD as App


class TestPairedColdHistory(unittest.TestCase):
    def test_both_contact_states_reopen_without_minting_a_current_run(self):
        root = Path(os.environ["R9_COLD_SOURCE_ROOT"])
        reports = []
        for name in (
            "test_frictionless_compression_keeps_beam_contact_and_solid_owners_in_one_case",
            "test_zero_tangential_compression_reports_actual_native_stick",
        ):
            with self.subTest(case=name):
                case = root / name
                path = case / "coupled-contact.FCStd"
                original = path.read_bytes()
                expected = (case / "section-data.json").read_text(), (
                    case / "contact-data.json"
                ).read_text()
                doc = App.openDocument(str(path))
                try:
                    beam = next(
                        o
                        for o in doc.Objects
                        if getattr(getattr(o, "Proxy", None), "Type", "")
                        == "Fem::BeamSectionForceResult"
                    )
                    contact = next(
                        o
                        for o in doc.Objects
                        if getattr(getattr(o, "Proxy", None), "Type", "")
                        == "Fem::ContactStateResult"
                    )
                    self.assertEqual((beam.SectionData, contact.ContactData), expected)
                    self.assertEqual(
                        (beam.SectionHash, contact.ContactHash),
                        tuple(hashlib.sha256(x.encode()).hexdigest() for x in expected),
                    )
                    for obj in (beam, contact):
                        self.assertFalse(obj.CompletedRun)
                        self.assertTrue(obj.Status.startswith("Historical"), obj.Status)
                    historical = beam.Proxy.getSectionForces(beam, historical=True)
                    local = json.loads(contact.ContactData)
                    self.assertEqual(
                        historical["provenance"]["joint"], local["provenance"]["joint"]
                    )
                    self.assertEqual(historical["provenance"]["joint"]["frames"], [[1, 1, 1]])
                    self.assertEqual(
                        (beam.Mesh.FemMesh.NodeCount, beam.Mesh.FemMesh.VolumeCount), (17, 6)
                    )
                    coupling = historical["provenance"]["coupling"]
                    solid_results = {
                        o.NativeSolidOwner.Name: o
                        for o in doc.Objects
                        if hasattr(o, "NativeSolidOwner")
                    }
                    self.assertEqual(set(solid_results), {g["owner"] for g in coupling["solids"]})
                    for group in coupling["solids"]:
                        result = solid_results[group["owner"]]
                        self.assertEqual(set(result.NativeSourceNodeNumbers), set(group["nodes"]))
                        self.assertEqual(
                            set(result.NativeSourceElementNumbers),
                            {r["element"] for r in group["elements"]},
                        )
                        self.assertEqual(result.NativeBeamSource, beam)
                        self.assertEqual(
                            result.NativeSourceFileHash, historical["provenance"]["frd"]["sha256"]
                        )
                        self.assertEqual(
                            (result.Mesh.FemMesh.NodeCount, result.Mesh.FemMesh.VolumeCount), (6, 3)
                        )
                        for field in ('NodeStressXX','NodeStressYY','NodeStressZZ',
                                      'NodeStressXY','NodeStressXZ','NodeStressYZ'):
                            values=getattr(result,field)
                            self.assertEqual(len(values),6)
                            for value in values:
                                self.assertAlmostEqual(value,-4/3 if field=='NodeStressXX' else 0,
                                                       delta=.0001)
                    physical = [o for o in doc.Objects if o.isDerivedFrom("Fem::FemResultObject")]
                    mixed = next(o for o in physical if not hasattr(o, "NativeSolidOwner"))
                    self.assertEqual(len(physical), 3)
                    self.assertFalse(mixed.NodeStressXX)
                    self.assertEqual(
                        set(mixed.NativeSourceNodeNumbers),
                        set(coupling["beam_nodes"]) | set(coupling["solid_nodes"]),
                    )
                    selected = doc.getObject(coupling["contact"]["owner"])
                    self.assertEqual(beam.Solver.NativeContactOutputs, [selected])
                    self.assertTrue(beam.Solver.BeamSectionForces)
                    self.assertFalse(beam.Solver.NativeForceAccounting)
                    self.assertFalse(beam.Solver.NativeAccountingSupports)
                    port = doc.getObject(coupling["port"]["name"])
                    connector = doc.getObject(coupling["spring"]["owner"])
                    self.assertEqual(connector.Attachment, "Vertex to rigid body port")
                    self.assertEqual(connector.Mode, "Two points")
                    self.assertEqual(connector.Kind, "Translational")
                    self.assertEqual(connector.Axis, "X")
                    self.assertEqual(connector.RigidBody2, port)
                    self.assertEqual(connector.Stiffness.getValueAs("N/mm").Value, 10000)
                    self.assertEqual(port.TranslationalModeX, "Free")
                    for axis in "YZ":
                        self.assertEqual(getattr(port, "TranslationalMode" + axis), "Constraint")
                    for axis in "XYZ":
                        self.assertEqual(getattr(port, "RotationalMode" + axis), "Constraint")
                    self.assertEqual(tuple(port.Displacement), (0, 0, 0))
                    self.assertEqual(tuple(port.Rotation.Q), (0, 0, 0, 1))
                    fixed = doc.getObject(coupling["solid_support"]["owner"])
                    self.assertEqual(fixed.References[0][0].Name, coupling["anchored_solid_owner"])
                    guide = doc.getObject(coupling["support"]["owner"])
                    self.assertTrue(guide.xFree)
                    self.assertFalse(
                        any(
                            getattr(guide, p)
                            for p in ("yFree", "zFree", "rotxFree", "rotyFree", "rotzFree")
                        )
                    )
                    for getter, obj in (
                        (beam.Proxy.getSectionForces, beam),
                        (contact.Proxy.getContactStates, contact),
                    ):
                        with self.assertRaises(ValueError):
                            getter(obj)
                    contact.Proxy.refresh(contact)
                    self.assertEqual((beam.SectionData, contact.ContactData), expected)
                    self.assertFalse(beam.CompletedRun or contact.CompletedRun)
                    self.assertFalse(
                        beam.Status.startswith("Current") or contact.Status.startswith("Current")
                    )
                    self.assertEqual(path.read_bytes(), original)
                    reports.append(
                        {
                            "case": name,
                            "document_sha256": hashlib.sha256(original).hexdigest(),
                            "literal_hashes": [beam.SectionHash, contact.ContactHash],
                            "states": sorted({r["state"] for r in local["frames"][0]["samples"]}),
                            "statuses": [beam.Status, contact.Status],
                            "solid_owner_source_maps_preserved": True,
                            "connector_support_requests_preserved": True,
                            "current_available": False,
                            "solver_executed": False,
                        }
                    )
                finally:
                    App.closeDocument(doc.Name)
        target = Path(os.environ["R9_CASE_ROOT"])
        target.mkdir()
        (target / "cold-observation.json").write_text(json.dumps(reports, indent=2))
