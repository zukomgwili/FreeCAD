"""Cold literal V1--V5 history from seven real bundled-app cases; no rerun/rebinding."""

import sys

sys.dont_write_bytecode = True

import hashlib
import json
import os
from pathlib import Path
import unittest

import FreeCAD as App
from AppBeamBjh import APP, IDENTITY, IDENTITY_PATH, NATIVE_SHA, check_identity
from AppBeamBjh import sha, source_origins, write_report


def check_contact_case(test, doc, beam, data, case):
    contacts = [
        obj
        for obj in doc.Objects
        if getattr(getattr(obj, "Proxy", None), "Type", "") == "Fem::ContactStateResult"
    ]
    test.assertEqual(len(contacts), 1)
    contact = contacts[0]
    contact_path = Path(case["contact_literal"])
    test.assertTrue(contact_path.is_absolute())
    test.assertFalse(contact_path.is_symlink())
    contact_bytes = contact_path.read_bytes()
    test.assertEqual(sha(contact_path), case["contact_literal_sha256"])
    literal = contact_bytes.decode()
    local = json.loads(literal)
    test.assertEqual(contact.ContactData, literal)
    test.assertEqual(contact.ContactHash, hashlib.sha256(contact_bytes).hexdigest())
    test.assertFalse(contact.CompletedRun)
    test.assertTrue(contact.Status.startswith("Historical"), contact.Status)
    test.assertEqual(json.loads(contact.ContactData), local)
    test.assertEqual(local["schema"], "CCX_CONTACT_STATE_V1")
    test.assertEqual(local["units"], {"length": "mm", "force": "N", "stress": "MPa"})
    test.assertEqual(
        [(f["step"], f["increment"], f["time"]) for f in local["frames"]],
        [(f["step"], f["increment"], f["time"]) for f in data["frames"]],
    )
    for key in ("deck_sha256", "binary_sha256", "stdout_sha256"):
        test.assertEqual(local["provenance"][key], data["provenance"][key])
    test.assertEqual(local["provenance"]["model_digest"], data["provenance"]["model_hash"])
    for name in ("analysis", "solver", "mesh"):
        test.assertEqual(getattr(contact, name.capitalize()), getattr(beam, name.capitalize()))
        test.assertEqual(local["provenance"][name], data["provenance"]["case"][name])
    with test.assertRaises(ValueError):
        contact.Proxy.getContactStates(contact)
    test.assertFalse(contact.Status.startswith("Current"))
    test.assertFalse(contact.CompletedRun)
    test.assertEqual(contact.ContactData, literal)
    test.assertEqual(json.loads(contact.ContactData), local)
    coupling = data["provenance"]["coupling"]
    mechanical = [obj for obj in beam.Analysis.Group if obj.isDerivedFrom("Fem::FemResultObject")]
    solids = [obj for obj in mechanical if hasattr(obj, "NativeSolidOwner")]
    mixed = [obj for obj in mechanical if not hasattr(obj, "NativeSolidOwner")]
    test.assertEqual((len(mechanical), len(solids), len(mixed)), (3, 2, 1))
    test.assertEqual(
        {obj.NativeSolidOwner.Name for obj in solids},
        {coupling["loaded_solid_owner"], coupling["anchored_solid_owner"]},
    )
    for obj in mechanical:
        test.assertEqual(obj.NativeBeamSource, beam)
        test.assertEqual(obj.NativeSourceFileHash, data["provenance"]["frd"]["sha256"])
        test.assertEqual(json.loads(obj.NativeSourceFrame)["case"], data["provenance"]["case"])
    for obj in solids:
        test.assertEqual(obj.Mesh.FemMesh.NodeCount, 6)
        test.assertEqual(obj.Mesh.FemMesh.VolumeCount, 3)
        test.assertEqual(obj.Mesh.FemMesh.EdgeCount, 0)
        test.assertTrue(obj.NativeSolidOwner.Shape.isValid())
        test.assertEqual(len(obj.NodeStressXX), 6)
    test.assertEqual(mixed[0].Mesh.FemMesh.NodeCount, 17)
    test.assertEqual(mixed[0].Mesh.FemMesh.VolumeCount, 6)
    test.assertEqual(mixed[0].Mesh.FemMesh.EdgeCount, 2)
    test.assertFalse(mixed[0].NodeStressXX)
    test.assertEqual(contact_path.read_bytes(), contact_bytes)
    return {
        "paired_contact_literal_sha256": sha(contact_path),
        "contact_frames": len(local["frames"]),
        "solid_owners": sorted(obj.NativeSolidOwner.Name for obj in solids),
        "mechanical_partition_preserved": True,
        "paired_history_promoted_current": False,
    }


def check_network_case(test, doc, result, data, case):
    coupling = data["provenance"]["coupling"]
    frame = data["frames"][-1]
    actions = frame["native_actions"]
    components = case["components"]
    test.assertEqual(len(coupling["components"]), components)
    test.assertEqual(len(coupling["materials"]), case["materials"])
    test.assertEqual(len(coupling["sections"]), case["materials"])
    test.assertEqual(len(actions["sources"]), case["sources"])
    test.assertEqual(len(actions["supports"]), case["supports"])
    test.assertEqual(len(actions["springs"]), components)
    test.assertEqual(sum(s["mode"] == "GROUND" for s in actions["springs"]), 1)
    test.assertEqual(sum(len(s["ends"]) for s in actions["springs"]), case["spring_ends"])
    test.assertEqual(result.Mesh.FemMesh.NodeCount, 19 * components)
    test.assertEqual(result.Mesh.FemMesh.EdgeCount, 9 * components)
    test.assertEqual(len(coupling["nodes"]), 19 * components)
    test.assertFalse(result.Mesh.FemMesh.FaceCount or result.Mesh.FemMesh.VolumeCount)
    for key in ("analysis", "solver", "mesh"):
        test.assertEqual(getattr(result, key.capitalize()).Name, data["provenance"]["case"][key])
    test.assertFalse(result.Solver.NativeForceAccounting)
    test.assertFalse(result.Solver.NativeContactOutputs)
    test.assertFalse(result.Solver.NativeAccountingSupports)
    for spring in coupling["springs"]:
        obj = doc.getObject(spring["owner"])
        test.assertIsNotNone(obj)
        test.assertEqual(obj.Attachment, "Vertices")
        test.assertEqual(obj.Kind, "Translational")
        test.assertEqual(obj.Mode, "Ground" if spring["mode"] == "GROUND" else "Two points")
        test.assertEqual(obj.Axis, "XYZ"[spring["direction"] - 1])
        test.assertEqual(
            obj.Stiffness.getValueAs("N/mm").Value, spring["authored_stiffness_N_per_mm"]
        )
        test.assertTrue(obj.End1[0])
        test.assertEqual(len(obj.End1[1]), 1)
        if spring["mode"] == "TWO_POINTS":
            test.assertTrue(obj.End2[0])
            test.assertEqual(len(obj.End2[1]), 1)
    for guide in coupling["supports"]:
        obj = doc.getObject(guide["owner"])
        test.assertIsNotNone(obj)
        test.assertTrue(obj.xFree)
        test.assertFalse(
            any(getattr(obj, p) for p in ("yFree", "zFree", "rotxFree", "rotyFree", "rotzFree"))
        )
        for prop in ("yDisplacement", "zDisplacement"):
            test.assertEqual(getattr(obj, prop).getValueAs("mm").Value, 0)
        for prop in ("xRotation", "yRotation", "zRotation"):
            test.assertEqual(getattr(obj, prop).getValueAs("rad").Value, 0)
    for name, material in coupling["materials"].items():
        obj = doc.getObject(name)
        test.assertEqual(
            App.Units.Quantity(obj.Material["YoungsModulus"]).getValueAs("MPa").Value,
            material["youngs_modulus_MPa"],
        )
        test.assertEqual(float(obj.Material["PoissonRatio"]), material["poisson_ratio"])
    for name, section in coupling["sections"].items():
        obj = doc.getObject(name)
        test.assertEqual(
            [obj.RectWidth.getValueAs("mm").Value, obj.RectHeight.getValueAs("mm").Value],
            section["dimensions_mm"],
        )
    for source in coupling["sources"]:
        obj = doc.getObject(source["owner"])
        vector = App.Vector(obj.DirectionVector) * obj.Force.getValueAs("N").Value
        for actual, expected in zip(vector, source["force_global"]):
            test.assertAlmostEqual(actual, expected, delta=1e-12)
    for owner in coupling["members"]:
        test.assertIsNotNone(doc.getObject(owner["geometry_owner"]))
    mechanical = [obj for obj in result.Analysis.Group if obj.isDerivedFrom("Fem::FemResultObject")]
    test.assertEqual(len(mechanical), 1)
    test.assertEqual(len(mechanical[0].NodeNumbers), 19 * components)
    test.assertEqual(len(mechanical[0].DisplacementVectors), 19 * components)
    for field in (
        "NodeStressXX",
        "NodeStressYY",
        "NodeStressZZ",
        "NodeStressXY",
        "NodeStressXZ",
        "NodeStressYZ",
    ):
        test.assertFalse(getattr(mechanical[0], field))
    test.assertGreater(len(actions["knot_algebraic_spcs"]), 0)
    for row in actions["knot_algebraic_spcs"]:
        test.assertEqual(row["role"], "ALGEBRAIC")
        for field in ("value_unit", "prescription_unit", "displacement_unit"):
            test.assertEqual(row[field], "NATIVE_EQUATION_VALUE")
    return {
        "components": components,
        "source_owners": [s["owner"] for s in actions["sources"]],
        "support_owners": [s["owner"] for s in actions["supports"]],
        "spring_ends": case["spring_ends"],
        "native_knot_algebraic_rows": len(actions["knot_algebraic_spcs"]),
        "saved_physical_parameters_preserved": True,
        "mechanical_displacement_only_preserved": True,
    }


class ColdBeamBjh(unittest.TestCase):
    def test_saved_literal_axes_case_and_output_request_survive_cold_restore(self):
        self.assertEqual(os.environ["IBJH_MODE"], "cold")
        self.assertFalse(App.GuiUp)
        identity = check_identity(self)
        cases = json.loads(os.environ["IBJH_COLD_CASES"])
        self.assertEqual(
            [case["schema"] for case in cases],
            [
                "CCX_BEAM_SECTION_V1",
                "CCX_BEAM_SECTION_V2",
                "CCX_BEAM_SECTION_V3",
                "CCX_BEAM_SECTION_V4",
                "CCX_BEAM_SECTION_V5",
                "CCX_BEAM_SECTION_V5",
                "CCX_BEAM_SECTION_V5",
            ],
        )
        self.assertEqual(
            [case["name"] for case in cases],
            ["v1", "v2", "v3", "v4", "v5-ground", "v5-connected", "v5-fork"],
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
                    if case["schema"] != "CCX_BEAM_SECTION_V4":
                        self.assertEqual(len(historical["frames"]), 1)
                    self.assertTrue(historical["frames"])
                    frame = historical["frames"][-1]
                    if case["schema"] == "CCX_BEAM_SECTION_V4":
                        self.assertEqual((frame["step"], frame["time"]), (1, 1.0))
                        self.assertGreaterEqual(frame["increment"], 1)
                    else:
                        self.assertEqual(
                            (frame["step"], frame["increment"], frame["time"]), (1, 1, 1.0)
                        )
                    self.assertEqual(len(frame["samples"]), case["samples"])
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
                    elif case["schema"] == "CCX_BEAM_SECTION_V4":
                        mechanical_observation = check_contact_case(self, doc, result, data, case)
                    elif case["schema"] == "CCX_BEAM_SECTION_V5":
                        mechanical_observation = check_network_case(self, doc, result, data, case)
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
                            "name": case["name"],
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
        self.assertEqual(len(observations), 7)
        write_report(
            "cold-observation.json",
            {
                "schema": "FreeCAD-bjh-cold-beam-history-v1",
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
                "schema": "FreeCAD-bjh-installation-regression-v1",
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
                    "ColdBeamBjh.ColdBeamBjh.test_saved_literal_axes_case_and_output_request_survive_cold_restore"
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
    return ColdSuite(loader.loadTestsFromTestCase(ColdBeamBjh))
