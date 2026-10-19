# SPDX-License-Identifier: LGPL-2.1-or-later
"""Saved contact-side observations qualify through their document interface."""

import unittest
import json

import FreeCAD as App
import ObjectsFem


class TestContactObservation(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("ContactObservationTest")

    def tearDown(self):
        if self.doc.Name in App.listDocuments():
            App.closeDocument(self.doc.Name)

    def test_unconfigured_result_is_explicitly_unavailable_not_zero(self):
        result = ObjectsFem.makeResultContactObservation(self.doc)
        self.assertEqual(result.Proxy.Type, "Fem::ContactSideObservation")
        result.Proxy.refresh(result)
        self.assertTrue(result.Status.startswith("Unavailable"), result.Status)
        with self.assertRaisesRegex(ValueError, "Unavailable"):
            result.Proxy.getObservations(result)
        self.assertEqual(result.ObservationData, "")

    def test_legacy_accounting_is_preserved_but_not_used_as_movement(self):
        from femtools import force_accounting

        analysis = ObjectsFem.makeAnalysis(self.doc)
        mesh = ObjectsFem.makeMeshGmsh(self.doc)
        analysis.addObject(mesh)
        contact = ObjectsFem.makeConstraintContact(self.doc)
        analysis.addObject(contact)
        accounting = force_accounting.make_result(analysis)
        historical = json.dumps({"schema": force_accounting.SCHEMA, "legacy": True})
        accounting.AccountingData = historical
        accounting.Status = "Stale after restore; rerun to establish current native accounting"
        result = ObjectsFem.makeResultContactObservation(self.doc, analysis, accounting, [contact])
        result.Proxy.refresh(result)
        self.assertIn("bound native movement source", result.Status)
        self.assertEqual(accounting.AccountingData, historical)
        with self.assertRaisesRegex(ValueError, "bound native movement source"):
            result.Proxy.getObservations(result)

    def test_analysis_backlink_does_not_create_a_recompute_dependency_cycle(self):
        analysis = ObjectsFem.makeAnalysis(self.doc)
        result = ObjectsFem.makeResultContactObservation(self.doc, analysis)
        self.assertIn(result, analysis.Group)
        self.assertEqual(result.Analysis, analysis)
        self.assertNotIn(analysis, result.OutList)
        self.doc.recompute()
        self.assertNotIn("Touched", result.State)

    def test_recompute_does_not_implicitly_refresh_an_editable_observation(self):
        result = ObjectsFem.makeResultContactObservation(self.doc)
        result.SlaveVertex = 2
        status = result.Status
        self.doc.recompute()
        self.assertEqual(result.Status, status)
