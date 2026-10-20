"""Public stock-export refusal for ambiguous unselected physical restraints."""
import os
from pathlib import Path
import unittest
import FreeCAD as App
import ObjectsFem
from femtools.ccxtools import FemToolsCcx
from YwuMovingPortWitness import sha, write_json


class SupportOverlap(unittest.TestCase):
    def test_unselected_fixed_boundary_cannot_share_selected_rbe_receiving_dofs(self):
        source = Path(__file__).resolve().parent / "source-endload-r03/witness/moving-face-ports-native-v3.FCStd"
        before = sha(source)
        doc = App.openDocument(str(source))
        receipt = {"passed": False, "saved_fixture": str(source), "saved_fixture_sha256": before,
                   "native_solve_performed": False, "model_altered_or_saved_on_disk": False}
        try:
            analysis = doc.getObject("Analysis")
            solver = doc.getObject("SolverCcxTools")
            support = doc.getObject("ExternalSupport")
            self.assertEqual(list(solver.NativeAccountingSupports), [support])
            duplicate = ObjectsFem.makeConstraintFixed(doc, "UnselectedFixedDuplicate")
            duplicate.References = support.References
            analysis.addObject(duplicate)
            doc.recompute()
            fea = FemToolsCcx(analysis=analysis, solver=solver)
            fea.update_objects()
            directory = Path(os.environ["YWU_OUTPUT"]) / "export"
            directory.mkdir()
            fea.setup_working_dir(str(directory))
            with self.assertRaisesRegex(ValueError, "overlap") as caught:
                fea.write_inp_file()
            receipt.update(passed=True, refusal=str(caught.exception))
        finally:
            App.closeDocument(doc.Name)
            self.assertEqual(sha(source), before)
            write_json(Path(os.environ["YWU_OUTPUT"]) / "overlap-receipt.json", receipt)
