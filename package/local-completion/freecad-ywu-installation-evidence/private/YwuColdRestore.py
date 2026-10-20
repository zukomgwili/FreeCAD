"""Independent-process historical restore; no rerun or provenance repair."""
import json
import os
from pathlib import Path
import unittest

import FreeCAD as App
from YwuMovingPortWitness import plain, sha, write_json


class ColdRestore(unittest.TestCase):
    def test_saved_support_roles_and_literal_history_restore(self):
        source = Path(os.environ.get("YWU_COLD_MANIFEST") or (
            Path(__file__).resolve().parent / "source-endload-r03/witness/cold-case.json"))
        expected = json.loads(source.read_text())
        output = Path(os.environ["YWU_OUTPUT"]) / "cold-receipt.json"
        receipt = {"passed": False, "manifest": str(source), "manifest_sha256": sha(source),
                   "no_native_solve": True, "no_history_or_provenance_repair": True}
        doc = None
        try:
            saved = Path(expected["document"])
            self.assertEqual(sha(saved), expected["document_sha256"])
            for row in expected["source_files"].values():
                self.assertEqual(sha(row["path"]), row["sha256"])
            doc = App.openDocument(str(saved))
            report = doc.getObject(expected["report_name"])
            self.assertTrue(report.Status.startswith("Stale after restore"), report.Status)
            self.assertEqual(report.AccountingData, expected["accounting_data_literal"])
            self.assertEqual(plain(list(report.Resultants)), expected["resultants_literal"])
            self.assertEqual(json.loads(report.AccountingData)["movement_source"],
                             expected["movement_source_literal"])
            solver = doc.getObject(expected["solver_name"])
            self.assertEqual([obj.Name for obj in solver.NativeAccountingSupports],
                             expected["explicit_supports"])
            # Native document names are session identifiers and change to the
            # saved filename on cold open. Compare actual local object links,
            # never rewrite the saved accounting/provenance payload.
            prior_document_names = set()
            def local_links(value, *, restored):
                if isinstance(value, dict):
                    if set(value) == {"object", "document"}:
                        if restored:
                            self.assertEqual(value["document"], doc.Name)
                            self.assertIsNotNone(doc.getObject(value["object"]))
                        else:
                            prior_document_names.add(value["document"])
                        return {"object": value["object"], "document": "<owning document>"}
                    return {key: local_links(item, restored=restored) for key, item in value.items()}
                if isinstance(value, list):
                    return [local_links(item, restored=restored) for item in value]
                return value
            for name, references in expected["saved_references"].items():
                self.assertEqual(local_links(plain(doc.getObject(name).References), restored=True),
                                 local_links(references, restored=False))
            for name, item in expected["saved_native_properties"].items():
                obj = doc.getObject(name)
                self.assertEqual(obj.TypeId, item["type"])
                for prop, row in item["properties"].items():
                    self.assertEqual(obj.getTypeIdOfProperty(prop), row["type"])
                    self.assertEqual(local_links(plain(getattr(obj, prop)), restored=True),
                                     local_links(row["value"], restored=False), (name, prop))
            self.assertEqual(len(prior_document_names), 1)
            receipt["session_document_name_mapping"] = {
                "saved_session": next(iter(prior_document_names)), "cold_session": doc.Name}
            doc.recompute()
            self.assertTrue(report.Status.startswith("Stale"), report.Status)
            self.assertEqual(report.AccountingData, expected["accounting_data_literal"])
            self.assertEqual(sha(saved), expected["document_sha256"])
            for row in expected["source_files"].values():
                self.assertEqual(sha(row["path"]), row["sha256"])
            receipt.update(passed=True, status=report.Status,
                           supports=[obj.Name for obj in solver.NativeAccountingSupports],
                           accounting_data_sha256=sha_text(report.AccountingData))
        finally:
            if doc is not None and doc.Name in App.listDocuments():
                App.closeDocument(doc.Name)
            write_json(output, receipt)


def sha_text(value):
    import hashlib
    return hashlib.sha256(value.encode()).hexdigest()
