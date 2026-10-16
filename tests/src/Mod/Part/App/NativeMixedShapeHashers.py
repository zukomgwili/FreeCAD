# SPDX-License-Identifier: LGPL-2.1-or-later

"""Opt-in native GUI/cold-process mixed-hasher probe for FreeCAD-b9r.

Run FreeCAD -P tests/src/Mod/Part/App -t NativeMixedShapeHashers with
FREECAD_B9R_DIRECTORY set to a disposable evidence directory and
FREECAD_B9R_STAGE=create. Run again in a fresh process with stage=reopen.
The latter reads mixed-hashers.FCStd and saves mixed-hashers-successor.FCStd.
Optional FREECAD_B9R_INPUT/OUTPUT select other paths for additional cold cycles.
FREECAD_B9R_EXPECTED_COMMIT optionally checks the compiled source identity.

Only synthetic native copy/fuse shapes are used. No handwritten mapped names,
SaveAll workaround, historical project, or installed application is required.
"""

import gc
import hashlib
import json
import os
from pathlib import Path
import unittest
from zipfile import ZipFile

import FreeCAD as App
import FreeCADGui as Gui
import Part
from parttests import TestMixedShapeHashers as mixed_tests
from PySide import QtCore


@unittest.skipUnless(os.environ.get("FREECAD_B9R_DIRECTORY"),
                     "Requires a disposable mixed-hasher evidence directory")
class NativeMixedShapeHashers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not App.GuiUp or Gui.getMainWindow() is None:
            raise AssertionError("Requires the native FreeCAD application")
        expected = os.environ.get("FREECAD_B9R_EXPECTED_COMMIT")
        if expected and App.Version()[-1] != expected:
            raise AssertionError(f"Unexpected compiled runtime: {App.Version()}")

    def setUp(self):
        # Keep the helper module namespaced: importing its TestCase directly would
        # make the opt-in GUI test loader run the complete regular test suite too.
        self.oracle = mixed_tests.TestMixedShapeHashers()

    def records(self, shape):
        roots, records = self.oracle.identity_records(shape)
        return {"roots": sorted(roots), "records": json.loads(json.dumps(records))}

    def shape_snapshot(self, shape):
        self.assertFalse(shape.Hasher.SaveAll)
        self.assertTrue(shape.isValid())
        return {"identities": self.records(shape),
                "element_map": sorted([raw, indexed] for raw, indexed in shape.ElementMap.items()),
                "volume": round(shape.Volume, 9)}

    def direct_semantic_control(self, report):
        mixed = self.oracle.make_pair()
        shared = self.oracle.make_pair(shared=True)
        before = [self.oracle.snapshot(shape) for shape in mixed]
        origins = self.oracle.origin_geometry(mixed)
        control_origins = self.oracle.origin_geometry(shared)
        actual = mixed[0].fuse(mixed[1])
        control = shared[0].fuse(shared[1])
        support = self.oracle.provenance_records(actual, origins)
        self.assertEqual(support, self.oracle.provenance_records(control, control_origins))
        self.oracle.assert_rightmost_origin(actual, 4)
        roots, records = self.oracle.identity_records(actual)
        for shape, old in zip(mixed, before):
            self.oracle.assert_unchanged(shape, old)
        report["direct_semantic_control"] = {
            "root_count": len(roots), "identity_count": len(records),
            "mapped_name_count": len(actual.ElementMap), "volume": actual.Volume,
            "physical_provenance_matches_shared_owner": True,
            "supported_history_count": sum(count for (_, valid), count in support.items() if valid),
            "control_history_limit_count": sum(count for (_, valid), count in support.items()
                                               if not valid),
        }
        # A single native copy has no recursive-history ambiguity. Independently
        # require every mapped vertex/edge/face to lie on its reported source.
        inputs = self.oracle.make_pair(native_ids=False)
        origins = self.oracle.origin_geometry(inputs)
        primitive = inputs[0].fuse(inputs[1])
        support = self.oracle.provenance_records(primitive, origins)
        self.oracle.assert_supported_provenance(support)
        self.oracle.assert_rightmost_origin(primitive, 3)
        self.oracle.identity_records(primitive)
        report["direct_semantic_control"]["strict_primitive_history_count"] = sum(support.values())
        # Only primitive report data survive; no native shape/SID/hasher wrapper
        # from this independent control is retained by the document fixture.

    def add_source(self, doc, name, seed, offset):
        source = self.oracle.make_source(App.StringHasher(), seed, offset)
        roots, records = self.oracle.identity_records(source)
        self.assertEqual(len(roots), 5)
        self.assertEqual(len(records), 13)
        self.assertTrue(any(record[3] for record in records.values()))
        before = self.oracle.snapshot(source)
        geometry = sorted(self.oracle.fingerprint(source.getElement(indexed))
                          for indexed in source.ElementMap.values())
        target = doc.addObject("Part::Feature", name)
        target.Shape = source
        self.assertTrue(target.Shape.Hasher.isSame(source.Hasher))
        # The GUI clears OCCT's Checked flag on assignment with either a
        # primary or foreign owner. Verify geometry, not that mutable BRep flag.
        self.oracle.assert_unchanged(source, before, check_brep=False)
        self.assertEqual(sorted(self.oracle.fingerprint(source.getElement(indexed))
                                for indexed in source.ElementMap.values()), geometry)
        self.assertTrue(source.isValid())
        self.assertAlmostEqual(source.Volume, 36)

    def linked_face(self, doc):
        obj, names = doc.Reference.References[0]
        self.assertEqual(len(names), 1)
        face = obj.Shape.getElement(names[0])
        self.assertEqual(face.ShapeType, "Face")
        self.assertAlmostEqual(face.CenterOfMass.x, 4.5)
        self.assertAlmostEqual(face.CenterOfMass.y, 1.5)
        self.assertAlmostEqual(face.CenterOfMass.z, 2)
        self.assertAlmostEqual(face.Area, 12)
        return {"indexed_name": names[0], "area": round(face.Area, 9),
                "center": [round(value, 9) for value in
                           (face.CenterOfMass.x, face.CenterOfMass.y, face.CenterOfMass.z)]}

    def snapshot(self, doc):
        self.assertFalse(doc.A.Shape.Hasher.isSame(doc.B.Shape.Hasher))
        shapes = {name: self.shape_snapshot(doc.getObject(name).Shape)
                  for name in ("A", "B", "Union")}
        self.assertAlmostEqual(shapes["A"]["volume"], 36)
        self.assertAlmostEqual(shapes["B"]["volume"], 36)
        self.assertAlmostEqual(shapes["Union"]["volume"], 54)
        return {"shapes": shapes, "linked_face": self.linked_face(doc)}

    def check_snapshot(self, doc, expected, label, report):
        actual = self.snapshot(doc)
        self.assertEqual(actual, expected)
        report.setdefault("snapshots", []).append({
            "label": label, "linked_face": actual["linked_face"],
            "shapes": {name: {"root_count": len(shape["identities"]["roots"]),
                              "identity_count": len(shape["identities"]["records"]),
                              "mapped_name_count": len(shape["element_map"]),
                              "volume": shape["volume"], "save_all": False}
                       for name, shape in actual["shapes"].items()},
        })

    def show_fixture(self, doc, path):
        App.setActiveDocument(doc.Name)
        doc.A.ViewObject.Visibility = False
        doc.B.ViewObject.Visibility = False
        doc.Union.ViewObject.Visibility = True
        doc.Union.ViewObject.ShapeColor = (0.25, 0.65, 0.9)
        Gui.activeDocument().activeView().viewAxonometric()
        Gui.activeDocument().activeView().fitAll()
        Gui.updateGui()
        loop = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(250, loop.quit)
        loop.exec()
        Gui.activeDocument().activeView().saveImage(str(path), 1000, 700, "White")

    def create_fixture(self, directory, report):
        doc = App.newDocument("NativeMixedShapeHashers")
        self.add_source(doc, "A", "SeedA", 0)
        self.add_source(doc, "B", "SeedB", 1)
        result = doc.addObject("Part::Fuse", "Union")
        result.Base, result.Tool = doc.A, doc.B
        result.Refine = False
        # Helpers have returned and no external source wrappers remain.
        gc.collect()
        self.assertFalse(doc.A.Shape.Hasher.isSame(doc.B.Shape.Hasher))
        doc.recompute()
        self.assertAlmostEqual(result.Shape.Volume, 48)
        original = self.shape_snapshot(result.Shape)
        report["original_native_fuse"] = {
            "volume": original["volume"],
            "identity_count": len(original["identities"]["records"]),
            "root_count": len(original["identities"]["roots"]),
        }
        selected = next("Face%d" % (index + 1) for index, face in enumerate(result.Shape.Faces)
                        if abs(face.CenterOfMass.x - 4) < 1e-9)
        reference = doc.addObject("App::FeaturePython", "Reference")
        reference.addProperty("App::PropertyLinkSubList", "References")
        reference.References = [(result, [selected])]
        self.replace_tool(doc)
        del result, reference, original
        gc.collect()
        doc.recompute()
        expected = self.snapshot(doc)
        self.check_snapshot(doc, expected, "regenerated-after-source-wrapper-gc", report)
        doc.recompute()
        self.check_snapshot(doc, expected, "ordinary-recompute", report)
        doc.recompute(None, True)
        self.check_snapshot(doc, expected, "forced-recompute", report)
        self.show_fixture(doc, directory / "create.png")
        fixture = directory / "mixed-hashers.FCStd"
        doc.saveAs(str(fixture))
        with ZipFile(fixture) as archive:
            self.assertIn("GuiDocument.xml", archive.namelist())
        self.check_snapshot(doc, expected, "native-save", report)
        (directory / "expected.json").write_text(json.dumps(expected, indent=2))
        report["output"] = str(fixture)

    def replace_tool(self, doc):
        source = self.oracle.make_source(doc.B.Shape.Hasher, "SeedB", 1.5)
        doc.B.Shape = source

    def reopen_fixture(self, directory, report):
        source = Path(os.environ.get("FREECAD_B9R_INPUT",
                                     directory / "mixed-hashers.FCStd")).resolve()
        output = Path(os.environ.get("FREECAD_B9R_OUTPUT",
                                     directory / "mixed-hashers-successor.FCStd")).resolve()
        self.assertNotEqual(source, output, "Never overwrite the cold-process input")
        original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        expected = json.loads((directory / "expected.json").read_text())
        doc = App.openDocument(str(source))
        gc.collect()
        self.check_snapshot(doc, expected, "cold-reopen-before-recompute", report)
        doc.recompute()
        self.check_snapshot(doc, expected, "cold-ordinary-recompute", report)
        doc.recompute(None, True)
        self.check_snapshot(doc, expected, "cold-forced-recompute", report)
        self.show_fixture(doc, directory / "reopen.png")
        doc.saveAs(str(output))
        with ZipFile(output) as archive:
            self.assertIn("GuiDocument.xml", archive.namelist())
        self.check_snapshot(doc, expected, "successor-save", report)
        App.closeDocument(doc.Name)
        del doc
        gc.collect()
        doc = App.openDocument(str(output))
        self.check_snapshot(doc, expected, "successor-reopen-before-recompute", report)
        doc.recompute(None, True)
        self.check_snapshot(doc, expected, "successor-forced-recompute", report)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original_hash)
        report.update(input=str(source), output=str(output), input_sha256=original_hash)

    def test_native_mixed_operation_and_cold_restore(self):
        directory = Path(os.environ["FREECAD_B9R_DIRECTORY"]).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        stage = os.environ.get("FREECAD_B9R_STAGE", "create")
        report = {"version": App.Version(), "home": App.getHomePath(),
                  "part_module": Part.__file__, "helper_module": mixed_tests.__file__,
                  "gui_module": getattr(Gui, "__file__", "<built-in>"),
                  "gui_up": App.GuiUp, "stage": stage}
        try:
            self.assertIn(stage, ("create", "reopen"))
            self.direct_semantic_control(report)
            gc.collect()
            if stage == "create":
                self.create_fixture(directory, report)
            else:
                self.reopen_fixture(directory, report)
            report["passed"] = True
        except BaseException as error:
            report.update(passed=False, error=repr(error))
            raise
        finally:
            (directory / f"{stage}-result.json").write_text(json.dumps(report, indent=2))
