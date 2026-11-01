"""Cold process checks only: never solve, save, repair or promote observations."""

import sys

sys.dont_write_bytecode = True
import hashlib
import json
import os
from pathlib import Path
import unittest
import FreeCAD as App
import AppStagedE4k as app_checks

ROOT = Path(__file__).resolve().parent
HISTORY = ["0, 0, 0.2, 0", "0.4, 1, 0.6, 0, 0.8, -1, 1, 0"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class TestColdE4k(unittest.TestCase):
    def test_exact_saved_controls_owners_units_and_history_remain_historical(self):
        app_checks.check_identity(self)
        plan = json.loads(os.environ["IE4K_COLD_CASE"])
        document = Path(plan["document"])
        literal_path = Path(plan["literal"])
        self.assertEqual(sha(document), plan["document_sha256"])
        self.assertEqual(sha(literal_path), plan["literal_sha256"])
        literals = json.loads(literal_path.read_text())
        doc = App.openDocument(str(document))
        try:
            solver = doc.SolverCcxTools
            self.assertEqual(solver.StaticStepAmplitude, "Step")
            self.assertAlmostEqual(solver.TimePeriod.getValueAs("s").Value, 1)
            self.assertEqual(list(solver.NativeAccountingSupports), [doc.BaseSupport])
            self.assertEqual(list(solver.NativeContactOutputs), [doc.GravityContact])
            self.assertEqual(solver.NativeAccountingSolver, "")
            self.assertTrue(solver.NativeForceAccounting)
            self.assertTrue(doc.VariableQPressure.EnableAmplitude)
            self.assertEqual(list(doc.VariableQPressure.AmplitudeValues), HISTORY)
            self.assertAlmostEqual(doc.VariableQPressure.Pressure.getValueAs("MPa").Value, 0.001)
            self.assertAlmostEqual(
                doc.VolumetricGravity.GravityAcceleration.getValueAs("m/s^2").Value, 9.80665
            )
            self.assertEqual(tuple(doc.VolumetricGravity.GravityDirection), (0, 0, -1))
            geometry = doc.ThreeMaterials
            for name, density, z in (
                ("BaseMaterial", 7900, 50),
                ("LowerMaterial", 7800, 150),
                ("UpperMaterial", 8000, 250),
            ):
                material = doc.getObject(name)
                self.assertEqual(material.Material["Density"], f"{density} kg/m^3")
                self.assertEqual(len(material.References), 1)
                owner, parts = material.References[0]
                self.assertEqual(owner, geometry)
                self.assertEqual(len(parts), 1)
                self.assertAlmostEqual(owner.getSubObject(parts[0]).CenterOfMass.z, z)
            self.assertTrue(doc.LowerCut.NativeEquilibriumCut)
            self.assertTrue(doc.UpperCut.NativeEquilibriumCut)
            for obj, z in ((doc.LowerCut, 150), (doc.UpperCut, 250)):
                self.assertEqual(len(obj.AccountingBody), 1)
                owner, parts = obj.AccountingBody[0]
                self.assertEqual(owner, geometry)
                self.assertAlmostEqual(owner.getSubObject(parts[0]).CenterOfMass.z, z)
            accounting = doc.getObject(literals["accounting_name"])
            contact = doc.getObject(literals["contact_name"])
            self.assertEqual(accounting.AccountingData, literals["accounting"])
            self.assertTrue(accounting.Status.startswith("Stale"), accounting.Status)
            self.assertEqual(contact.ContactData, literals["contact"])
            self.assertTrue(contact.Status.startswith("Historical"), contact.Status)
            # Standalone contact keeps the saved last-run completion marker.
            # Cold availability is Historical; that marker does not grant
            # Current access and is not a newly owned solver child.
            completed_before = contact.CompletedRun
            before_status = [accounting.Status, contact.Status]
            saved_hash = hashlib.sha256(contact.ContactData.encode()).hexdigest()
            self.assertEqual(contact.ContactHash, saved_hash)
            with self.assertRaises(ValueError):
                contact.Proxy.getContactStates(contact)
            self.assertFalse(contact.Status.startswith("Current"))
            self.assertEqual(accounting.AccountingData, literals["accounting"])
            self.assertEqual(contact.ContactData, literals["contact"])
            self.assertEqual(sha(document), plan["document_sha256"])
            self.assertEqual(sha(literal_path), plan["literal_sha256"])
            report = {
                "passed": True,
                "document": str(document),
                "document_sha256": sha(document),
                "accounting_sha256": hashlib.sha256(accounting.AccountingData.encode()).hexdigest(),
                "contact_sha256": saved_hash,
                "solver_controls_preserved": True,
                "material_and_cut_ownership_preserved": True,
                "units_and_full_history_preserved": True,
                "availability_before": before_status,
                "availability_after": [accounting.Status, contact.Status],
                "CompletedRun": contact.CompletedRun,
                "completed_run_before": completed_before,
                "solve_performed": False,
                "save_performed": False,
                "repair_or_rebind_performed": False,
            }
            (Path(os.environ["E4K_RUN"]) / "cold.json").write_text(
                json.dumps(report, indent=2) + "\n"
            )
        finally:
            App.closeDocument(doc.Name)


def load_tests(_loader, _tests, _pattern):
    return app_checks.VerifiedSuite([TestColdE4k('test_exact_saved_controls_owners_units_and_history_remain_historical')])
