# SPDX-License-Identifier: LGPL-2.1-or-later
"""Public stock preflight at one below the unchanged full-graph budget.

Read a literal task-private analytical fixture only. No remesh, solve, save,
input/output alteration or engineering-model access is performed.
"""
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import FreeCAD as App
from femtools.ccxtools import FemToolsCcx
from YzkCoupledFixture import model_properties
from YzkCoupledFixture import sha
from YzkCoupledFixture import write_json


class CapacityRefusal(unittest.TestCase):
    def test_complete_graph_is_refused_before_any_stock_mesh_export(self):
        task = Path(__file__).resolve().parent
        source = task / "qa-v2/coupled-capacity-at-limit-r01/witness/coupled-before-export.FCStd"
        manifest = json.loads(Path(os.environ["YZK_QA_MANIFEST"]).read_text())
        expected_sha = manifest["inputs"]["files"][str(source)]
        self.assertEqual(sha(source), expected_sha)
        output = Path(os.environ["YZK_OUTPUT"])
        directory = output / "refused-export"
        directory.mkdir()
        doc = None
        try:
            doc = App.openDocument(str(source))
            analysis, solver, mesh = (doc.getObject(name) for name in ("Analysis", "SolverCcxTools", "Mesh"))
            before = model_properties(analysis, mesh)
            self.assertEqual(solver.NativeAccountingSolver, "")
            self.assertEqual([obj.Name for obj in solver.NativeAccountingSupports], ["BackboneFixed"])
            fea = FemToolsCcx(analysis=analysis, solver=solver)
            fea.update_objects()
            fea.setup_working_dir(str(directory))
            with patch.dict(os.environ, {"CCX_FORCE_ACCOUNTING_MAX_DECLARATIONS": "2112"}):
                with self.assertRaisesRegex(ValueError, "capacity exceeded") as caught:
                    fea.write_inp_file()
            diagnostic = str(caught.exception)
            required = {"supports": 1, "bodies": 264, "ports": 264, "angles": 792, "springs": 792}
            for kind, count in required.items():
                self.assertIn(f"{kind} required {count}; supported 2112", diagnostic)
            self.assertIn("total required 2113; supported 2112", diagnostic)
            self.assertEqual(list(directory.iterdir()), [])
            self.assertEqual(model_properties(analysis, mesh), before)
            self.assertFalse(any(hasattr(obj, "AccountingData") for obj in analysis.Group))
            self.assertEqual(sha(source), expected_sha)
            write_json(output / "capacity-refusal-proof.json", {
                "passed": True, "budget": 2112, "total_required": 2113,
                "required": required, "diagnostic": diagnostic,
                "stock_export_directory_untouched": True, "no_mesh_export_or_FE_solve": True,
                "source_document_sha256": expected_sha, "source_document_unchanged": True,
                "selected_persistent_properties_unchanged": True,
                "literal_source_document_unchanged": True,
                "separate_in_memory_shape_mesh_digest_claimed": False,
                "engineering_or_BIM_accepted": False,
            })
        finally:
            if doc is not None and doc.Name in App.listDocuments():
                App.closeDocument(doc.Name)
