# SPDX-License-Identifier: LGPL-2.1-or-later

"""Opt-in native GUI/cold-process ownership probe for FreeCAD-ute.

Run FreeCAD -P tests/src/Mod/Part/App -t NativeShapeHasherOwnership with
FREECAD_UTE_DIRECTORY set to a disposable evidence directory and
FREECAD_UTE_STAGE=create, then run again in a fresh process with stage=reopen.
The latter reads ownership.FCStd and writes ownership-successor.FCStd. Optional
FREECAD_UTE_INPUT and FREECAD_UTE_OUTPUT select distinct input/output paths for
additional cold-process cycles; expected.json remains in the evidence directory.
FREECAD_UTE_EXPECTED_COMMIT optionally checks the compiled source identity.

Only synthetic native copy/fuse shapes are used. No handwritten mapped names,
SaveAll workaround, retained project, or installed application is required.
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
from parttests import TestShapeHasherOwnership as ownership_tests
from PySide import QtCore


@unittest.skipUnless(os.environ.get("FREECAD_UTE_DIRECTORY"),
                     "Requires a disposable ownership evidence directory")
class NativeShapeHasherOwnership(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not App.GuiUp or Gui.getMainWindow() is None:
            raise AssertionError("Requires the native FreeCAD application")
        expected = os.environ.get("FREECAD_UTE_EXPECTED_COMMIT")
        if expected and App.Version()[-1] != expected:
            raise AssertionError(f"Unexpected compiled runtime: {App.Version()}")

    def records(self, shape):
        records = ownership_tests.TestShapeHasherOwnership.identity_records(self, shape)
        # Canonical JSON primitives also avoid retaining a source SID/hasher wrapper.
        return json.loads(json.dumps(records))

    def reference_points(self, doc):
        points = []
        for obj, names in doc.Reference.References:
            for name in names:
                point = obj.Shape.getElement(name).Point
                points.append([point.x, point.y, point.z])
        return points

    def show_fixture(self, doc):
        App.setActiveDocument(doc.Name)
        for name in ("PrimarySeed", "PrimaryHolder"):
            doc.getObject(name).ViewObject.Visibility = False
        for index, color in enumerate(((0.25, 0.65, 0.9), (0.9, 0.65, 0.25))):
            target = doc.getObject(f"Target{index}")
            target.ViewObject.Visibility = True
            target.ViewObject.ShapeColor = color
        Gui.activeDocument().activeView().viewAxonometric()
        Gui.activeDocument().activeView().fitAll()
        Gui.updateGui()
        loop = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(250, loop.quit)
        loop.exec()

    def check_snapshot(self, doc, expected, label, report):
        owners = [doc.getObject(f"Target{i}") for i in range(2)]
        self.assertFalse(owners[0].Shape.Hasher.isSame(owners[1].Shape.Hasher))
        primary = doc.PrimaryHolder.Shape.Hasher
        self.assertIsNotNone(primary)
        snapshot = {"label": label, "targets": {}}
        for target in owners:
            shape = target.Shape
            self.assertFalse(shape.Hasher.isSame(primary))
            self.assertFalse(shape.Hasher.SaveAll)
            actual = self.records(shape)
            self.assertEqual(actual, expected["targets"][target.Name]["records"])
            self.assertEqual(sorted(shape.ElementMap),
                             expected["targets"][target.Name]["mapped_names"])
            self.assertAlmostEqual(shape.Volume, 36)
            snapshot["targets"][target.Name] = {
                "identity_count": len(actual),
                "save_all": shape.Hasher.SaveAll,
                "volume": shape.Volume,
            }
        points = self.reference_points(doc)
        self.assertEqual(points, expected["reference_points"])
        snapshot["reference_points"] = points
        report.setdefault("snapshots", []).append(snapshot)

    def make_origin_and_target(self, index, destination, primary):
        source_doc = App.newDocument(f"OwnershipOrigin{index}")
        source = ownership_tests.TestShapeHasherOwnership.make_source(index * 8, f"Seed{index}")
        before = self.records(source)
        self.assertTrue(any(record[3] for record in before.values()), "Need recursive SIDs")
        origin = source_doc.addObject("Part::Feature", "Origin")
        origin.Shape = source
        source_doc.recompute()
        self.assertTrue(origin.Shape.Hasher.isSame(source.Hasher))
        self.assertEqual(self.records(origin.Shape), before)
        # Populate the destination domain before assignment: numeric lookup alone
        # would succeed here while resolving foreign names to unrelated identities.
        maximum = max(int(identity) for identity in before)
        noise = [primary.getID(f"Unrelated destination identity {i}")
                 for i in range(maximum + 8)]
        for identity, record in before.items():
            collision = primary.getID(int(identity))
            self.assertIsNotNone(collision)
            self.assertNotEqual(collision.Data, record[0])
        target = destination.addObject("Part::Feature", f"Target{index}")
        target.Shape = origin.Shape
        self.assertTrue(target.Shape.Hasher.isSame(origin.Shape.Hasher))
        self.assertEqual(self.records(target.Shape), before)
        point = source.Vertexes[0].Point
        expected = {
            "records": before,
            "mapped_names": sorted(target.Shape.ElementMap),
        }
        return source_doc.Name, expected, [point.x, point.y, point.z], noise

    def create_fixture(self, directory, report):
        self.doc = App.newDocument("NativeShapeHasherOwnership")
        primary = ownership_tests.TestShapeHasherOwnership.primary_hasher(self)
        expected = {"targets": {}, "reference_points": []}
        source_names = []
        noise = []
        for index in range(2):
            name, records, point, controls = self.make_origin_and_target(index, self.doc, primary)
            source_names.append(name)
            expected["targets"][f"Target{index}"] = records
            expected["reference_points"].append(point)
            noise.extend(controls)
        first = expected["targets"]["Target0"]["records"]
        second = expected["targets"]["Target1"]["records"]
        self.assertEqual(set(first), set(second))
        self.assertTrue(any(first[key][0] != second[key][0] for key in first),
                        "Independent tables must differ so swapped owners cannot pass")
        self.assertTrue(noise)
        for name, target in expected["targets"].items():
            self.assertFalse(self.doc.getObject(name).Shape.Hasher.isSame(primary))
            for identity, record in target["records"].items():
                collision = primary.getID(int(identity))
                self.assertIsNotNone(collision)
                self.assertNotEqual(collision.Data, record[0])
        reference = self.doc.addObject("App::FeaturePython", "Reference")
        reference.addProperty("App::PropertyLinkSubList", "References")
        reference.References = [(self.doc.getObject(f"Target{i}"), ["Vertex1"])
                                for i in range(2)]
        # The helper has returned: no Python shape/hasher/SID wrappers from either
        # source remain. Closing both source documents must not invalidate targets.
        for name in source_names:
            App.closeDocument(name)
        gc.collect()
        self.assertTrue(all(name not in App.listDocuments() for name in source_names))
        report["closed_source_documents"] = source_names
        self.check_snapshot(self.doc, expected, "source-documents-closed-before-recompute", report)
        for cycle in range(2):
            self.doc.recompute(None, True)
            self.check_snapshot(self.doc, expected, f"create-recompute-{cycle + 1}", report)
        self.show_fixture(self.doc)
        Gui.activeDocument().activeView().saveImage(
            str(directory / "create.png"), 1000, 700, "White")
        fixture = directory / "ownership.FCStd"
        self.doc.saveAs(str(fixture))
        with ZipFile(fixture) as archive:
            self.assertIn("GuiDocument.xml", archive.namelist())
        self.check_snapshot(self.doc, expected, "native-save", report)
        (directory / "expected.json").write_text(json.dumps(expected, indent=2))
        report["output"] = str(fixture)

    def reopen_fixture(self, directory, report):
        source = Path(os.environ.get("FREECAD_UTE_INPUT", directory / "ownership.FCStd")).resolve()
        output = Path(os.environ.get("FREECAD_UTE_OUTPUT",
                                     directory / "ownership-successor.FCStd")).resolve()
        self.assertNotEqual(source, output, "Never overwrite the cold-process input")
        original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        expected = json.loads((directory / "expected.json").read_text())
        self.doc = App.openDocument(str(source))
        self.check_snapshot(self.doc, expected, "cold-reopen-before-recompute", report)
        for cycle in range(2):
            self.doc.recompute(None, True)
            self.check_snapshot(self.doc, expected, f"cold-recompute-{cycle + 1}", report)
        self.show_fixture(self.doc)
        self.doc.saveAs(str(output))
        with ZipFile(output) as archive:
            self.assertIn("GuiDocument.xml", archive.namelist())
        self.check_snapshot(self.doc, expected, "successor-save", report)
        App.closeDocument(self.doc.Name)
        del self.doc
        gc.collect()
        self.doc = App.openDocument(str(output))
        self.check_snapshot(self.doc, expected, "successor-reopen-before-recompute", report)
        self.doc.recompute(None, True)
        self.check_snapshot(self.doc, expected, "successor-recompute", report)
        self.show_fixture(self.doc)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original_hash)
        Gui.activeDocument().activeView().saveImage(
            str(directory / "reopen.png"), 1000, 700, "White")
        report.update(input=str(source), output=str(output), input_sha256=original_hash)

    def test_native_assignment_and_cold_restore(self):
        directory = Path(os.environ["FREECAD_UTE_DIRECTORY"]).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        stage = os.environ.get("FREECAD_UTE_STAGE", "create")
        report = {
            "version": App.Version(),
            "home": App.getHomePath(),
            "part_module": Part.__file__,
            "gui_up": App.GuiUp,
            "stage": stage,
        }
        try:
            self.assertIn(stage, ("create", "reopen"))
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
