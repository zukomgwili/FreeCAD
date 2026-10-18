# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native accounting interface tests, independent of a particular solver binary."""

from types import SimpleNamespace
import unittest

import FreeCAD
import ObjectsFem


class TestForceAccounting(unittest.TestCase):
    def setUp(self):
        self.doc = FreeCAD.newDocument("NativeAccountingTest")

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def test_properties_are_opt_in_and_restore(self):
        solver = ObjectsFem.makeSolverCalculiXCcxTools(self.doc)
        section = ObjectsFem.makeConstraintSectionPrint(self.doc)
        self.assertFalse(solver.NativeForceAccounting)
        self.assertFalse(section.NativeEquilibriumCut)
        self.assertEqual(section.AccountingBody, [])
        solver.Proxy.onDocumentRestored(solver)
        section.Proxy.onDocumentRestored(section)
        self.assertFalse(solver.NativeForceAccounting)

    def test_output_parser_is_strict(self):
        from femtools import force_accounting

        valid = "CCX_FORCE_ACCOUNTING_V1\nSTATE 1 1 1\nSUPPORT R 0 0 2 4 -6 0\nEND\n"
        result = force_accounting.parse_output(valid, {("SUPPORT", "R")}, 1)
        self.assertEqual(result["SUPPORT"]["R"], [0, 0, 2, 4, -6, 0])
        for text in (
            valid.replace(" 2 ", " NaN "),
            valid.replace("END", ""),
            valid.replace("STATE 1 1 1", "STATE 1 1 .5"),
            valid.replace("SUPPORT R", "SUPPORT Wrong"),
            valid.replace("END", "SUPPORT R 0 0 2 4 -6 0\nEND"),
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                force_accounting.parse_output(text, {("SUPPORT", "R")}, 1)

    def test_result_restore_and_model_changes_invalidate(self):
        from femtools import force_accounting

        analysis = ObjectsFem.makeAnalysis(self.doc)
        box = self.doc.addObject("Part::Box", "Box")
        result = force_accounting.make_result(analysis)
        result.Status = "Current native accounting; not design acceptance"
        box.Length = 20
        self.assertTrue(result.Status.startswith("Stale"))
        result.Status = "Current native accounting; not design acceptance"
        result.Proxy.onDocumentRestored(result)
        self.assertTrue(result.Status.startswith("Stale"))

    def test_unknown_solver_capability_is_rejected(self):
        from femtools import force_accounting

        with self.assertRaises(ValueError):
            force_accounting.require_capability("/usr/bin/false")

    def test_cut_request_cannot_silently_fall_back_to_stress_output(self):
        from femtools import force_accounting

        solver = ObjectsFem.makeSolverCalculiXCcxTools(self.doc)
        section = ObjectsFem.makeConstraintSectionPrint(self.doc)
        section.NativeEquilibriumCut = True
        writer = SimpleNamespace(
            solver_obj=solver,
            mesh_object=None,
            analysis=None,
            member=SimpleNamespace(cons_sectionprint=[{"Object": section}]),
        )
        with self.assertRaisesRegex(ValueError, "Enable NativeForceAccounting"):
            force_accounting.prepare_request(writer)
