"""Cold literal V1/V2/V3 beam history; no analysis rerun or provenance rebinding."""

import sys

sys.dont_write_bytecode = True

import hashlib
import json
import os
from pathlib import Path
import unittest

import FreeCAD as App
from AppBeamSv7 import APP, IDENTITY, IDENTITY_PATH, NATIVE_SHA, check_identity
from AppBeamSv7 import sha, source_origins, write_report


class ColdBeamSv7(unittest.TestCase):
    def test_saved_literal_axes_case_and_output_request_survive_cold_restore(self):
        self.assertEqual(os.environ["ISV7_MODE"], "cold")
        self.assertFalse(App.GuiUp)
        identity = check_identity(self)
        cases = json.loads(os.environ["ISV7_COLD_CASES"])
        self.assertEqual(
            [case["schema"] for case in cases],
            ["CCX_BEAM_SECTION_V1", "CCX_BEAM_SECTION_V2", "CCX_BEAM_SECTION_V3"],
        )
        observations = []
        previous = App.activeDocument()
        previous_name = previous.Name if previous is not None else None
        for case in cases:
            with self.subTest(schema=case["schema"]):
                path, literal_path = Path(case["document"]), Path(case["literal"])
                self.assertTrue(path.is_absolute() and literal_path.is_absolute())
                self.assertFalse(path.is_symlink() or literal_path.is_symlink())
                document_sha, literal_sha = sha(path), sha(literal_path)
                self.assertEqual(document_sha, case["document_sha256"])
                self.assertEqual(literal_sha, case["literal_sha256"])
                literal = literal_path.read_text()
                data = json.loads(literal)
                self.assertEqual(data["schema"], case["schema"])
                self.assertEqual(hashlib.sha256(literal.encode()).hexdigest(), literal_sha)
                doc = App.openDocument(str(path))
                try:
                    results = [
                        obj
                        for obj in doc.Objects
                        if getattr(getattr(obj, "Proxy", None), "Type", "")
                        == "Fem::BeamSectionForceResult"
                    ]
                    self.assertEqual(len(results), 1)
                    result = results[0]
                    self.assertTrue(result.Solver.BeamSectionForces)
                    self.assertFalse(result.Solver.Output3d)
                    self.assertFalse(result.CompletedRun)
                    self.assertTrue(result.Status.startswith("Historical"), result.Status)
                    stored_literal, stored_hash = result.SectionData, result.SectionHash
                    self.assertEqual(
                        hashlib.sha256(stored_literal.encode()).hexdigest(), stored_hash
                    )
                    if case["literal_bytes_match"]:
                        self.assertEqual(stored_literal, literal)
                        self.assertEqual(stored_hash, literal_sha)
                    else:
                        # Shipped V2/V3 tests write pretty observed.json, while
                        # the native result saves its own canonical JSON text.
                        self.assertEqual(json.loads(stored_literal), data)
                    historical = result.Proxy.getSectionForces(result, historical=True)
                    self.assertEqual(historical, data)
                    self.assertEqual(
                        historical["units"], {"length": "mm", "force": "N", "moment": "N*mm"}
                    )
                    self.assertEqual(len(historical["frames"]), 1)
                    frame = historical["frames"][0]
                    self.assertEqual(
                        (frame["step"], frame["increment"], frame["time"]), (1, 1, 1.0)
                    )
                    self.assertEqual(
                        len(frame["samples"]), 4 if case["schema"].endswith("V3") else 10
                    )
                    for row in frame["samples"]:
                        self.assertEqual(set(row["basis"]), {"e1", "e2", "normal"})
                    mechanical_observation = None
                    if case["schema"] == "CCX_BEAM_SECTION_V2":
                        self.assertEqual(doc.GroundSpring.Attachment, "Vertices")
                        self.assertEqual(doc.GroundSpring.Mode, "Ground")
                        self.assertEqual(doc.GroundSpring.Stiffness.getValueAs("N/mm").Value, 2000)
                        self.assertTrue(doc.Stabilizer.xFree)
                        self.assertFalse(doc.Stabilizer.rotxFree)
                        self.assertEqual(len(frame["native_actions"]["support"]["spcs"]), 8)
                    elif case["schema"] == "CCX_BEAM_SECTION_V3":
                        self.assertEqual(doc.HybridSpring.Attachment, "Vertex to rigid body port")
                        self.assertEqual(doc.HybridSpring.RigidBody2, doc.HybridPort)
                        self.assertEqual(doc.HybridSpring.End1[0], doc.HybridBeam)
                        self.assertEqual(doc.HybridSpring.Mode, "Two points")
                        self.assertEqual(doc.HybridSpring.Stiffness.getValueAs("N/mm").Value, 10000)
                        mechanical = [
                            obj
                            for obj in doc.HybridAnalysis.Group
                            if obj.isDerivedFrom("Fem::FemResultObject")
                        ]
                        solid = [
                            obj
                            for obj in mechanical
                            if set(obj.NativeSourceNodeNumbers) == set(range(101, 107))
                        ]
                        mixed = [
                            obj
                            for obj in mechanical
                            if set(obj.NativeSourceNodeNumbers)
                            == set(range(1, 6)) | set(range(101, 107))
                        ]
                        self.assertEqual((len(mechanical), len(solid), len(mixed)), (2, 1, 1))
                        solid, mixed = solid[0], mixed[0]
                        for mechanical_result in (solid, mixed):
                            self.assertEqual(mechanical_result.NativeBeamSource, result)
                            self.assertEqual(
                                mechanical_result.NativeSourceFileHash,
                                data["provenance"]["frd"]["sha256"],
                            )
                            self.assertEqual(
                                json.loads(mechanical_result.NativeSourceFrame)["case"],
                                data["provenance"]["case"],
                            )
                        self.assertEqual(solid.NativeSolidOwner, doc.HybridPrism)
                        self.assertEqual(solid.Mesh.FemMesh.NodeCount, 6)
                        self.assertEqual(solid.Mesh.FemMesh.VolumeCount, 3)
                        self.assertEqual(solid.Mesh.FemMesh.EdgeCount, 0)
                        self.assertEqual(mixed.Mesh.FemMesh.NodeCount, 11)
                        self.assertEqual(mixed.Mesh.FemMesh.VolumeCount, 3)
                        self.assertEqual(mixed.Mesh.FemMesh.EdgeCount, 2)
                        self.assertEqual(len(solid.NodeStressXX), 6)
                        for value in solid.NodeStressXX:
                            self.assertAlmostEqual(value, 4 / 3, delta=0.0001)
                        self.assertFalse(mixed.NodeStressXX)
                        self.assertTrue(doc.HybridPrism.Shape.isValid())
                        mechanical_observation = {
                            "solid_original_nodes": list(solid.NativeSourceNodeNumbers),
                            "mixed_original_nodes": list(mixed.NativeSourceNodeNumbers),
                            "solid_owner": solid.NativeSolidOwner.Name,
                            "solid_stress_xx_MPa": list(solid.NodeStressXX),
                            "mixed_stress_xx_empty": not mixed.NodeStressXX,
                            "source_file_sha256": solid.NativeSourceFileHash,
                        }
                    with self.assertRaises(ValueError):
                        result.Proxy.getSectionForces(result)
                    self.assertFalse(result.Status.startswith("Current"))
                    self.assertEqual(
                        result.Proxy.getSectionForces(result, historical=True), historical
                    )
                    self.assertEqual(result.SectionData, stored_literal)
                    self.assertEqual(result.SectionHash, stored_hash)
                    self.assertFalse(result.CompletedRun)
                    observations.append(
                        {
                            "schema": historical["schema"],
                            "document": {"path": str(path), "sha256": document_sha},
                            "reference": {"path": str(literal_path), "sha256": literal_sha},
                            "reference_is_exact_stored_text": case["literal_bytes_match"],
                            "stored_section_data_sha256": stored_hash,
                            "case": historical["provenance"]["case"],
                            "frames": len(historical["frames"]),
                            "samples": len(frame["samples"]),
                            "status": result.Status,
                            "completed_run": result.CompletedRun,
                            "mechanical_results": mechanical_observation,
                        }
                    )
                finally:
                    App.closeDocument(doc.Name)
                    if previous_name in App.listDocuments():
                        App.setActiveDocument(previous_name)
                self.assertEqual(sha(path), document_sha)
                self.assertEqual(sha(literal_path), literal_sha)
        self.assertEqual(len(observations), 3)
        write_report(
            "cold-observation.json",
            {
                "schema": "FreeCAD-sv7-cold-beam-history-v1",
                "passed": True,
                "application": str(APP),
                "commit": IDENTITY["commit"],
                "revision": IDENTITY["revision"],
                "native_sha256": NATIVE_SHA,
                "cases": observations,
                "source_inputs_rebound_or_history_promoted_current": False,
                "analysis_solver_rerun": False,
                "input_unchanged": True,
                "source_or_build_import_override": False,
                "identity": identity,
            },
        )


class ColdSuite(unittest.TestSuite):
    def run(self, result, debug=False):
        super().run(result, debug=debug)
        passed = bool(result.wasSuccessful() and not result.skipped and result.testsRun == 1)
        write_report(
            "regression.json",
            {
                "schema": "FreeCAD-sv7-installation-regression-v1",
                "passed": passed,
                "mode": "cold",
                "application": str(APP),
                "gui": False,
                "commit": IDENTITY["commit"],
                "revision": IDENTITY["revision"],
                "native_sha256": NATIVE_SHA,
                "identity_sha256": sha(IDENTITY_PATH),
                "expected_tests": 1,
                "executed_tests": result.testsRun,
                "selected_test_ids": [
                    "ColdBeamSv7.ColdBeamSv7.test_saved_literal_axes_case_and_output_request_survive_cold_restore"
                ],
                "skipped": [test.id() for test, _reason in result.skipped],
                "failures": [test.id() for test, _traceback in result.failures],
                "errors": [test.id() for test, _traceback in result.errors],
                "source_or_build_import_override": False,
                "native_solver_override": False,
                "only_public_native_interfaces": True,
                "analysis_solver_rerun": False,
                "original_project_opened_changed_or_solved": False,
                "module_sha256": sha(__file__),
                "final_module_origins": source_origins(),
            },
        )
        return result


def load_tests(loader, _tests, _pattern):
    return ColdSuite(loader.loadTestsFromTestCase(ColdBeamSv7))
