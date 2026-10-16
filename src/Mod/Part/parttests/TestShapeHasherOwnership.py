# SPDX-License-Identifier: LGPL-2.1-or-later

"""Genuine native mapped identities must retain a coherent owning hasher."""

import gc
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest

import FreeCAD as App
import Part


class TestShapeHasherOwnership(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("ShapeHasherOwnership")

    def tearDown(self):
        if self.doc.Name in App.listDocuments():
            App.closeDocument(self.doc.Name)

    @staticmethod
    def make_source(offset=0, seed="Seed"):
        hasher = App.StringHasher()
        shape = Part.makeBox(2, 3, 4)
        shape.Tag = 1
        shape = shape.copy(seed, hasher)
        shape = shape.fuse(shape.translated(App.Vector(1, 0, 0)))
        if offset:
            shape.translate(App.Vector(offset, 0, 0))
        return shape

    def identity_records(self, shape):
        self.assertIsNotNone(shape.Hasher)
        roots = {int(raw, 16) for name in shape.ElementMap
                 for raw in re.findall(r"#([0-9a-fA-F]+)", name)}
        self.assertTrue(roots, "Test requires native SID-backed names, not empty/raw maps")
        records = {}

        def visit(sid):
            self.assertIsNotNone(sid, "Mapped identity is absent from the owning hasher")
            if sid.Value in records:
                return
            related = list(sid.Related)
            records[sid.Value] = (sid.Data, sid.IsBinary, sid.IsHashed, related)
            for child in sid.Related:
                owner = shape.Hasher.getID(child)
                self.assertIsNotNone(owner, "Related identity is absent from the owning hasher")
                visit(owner)

        for identity in roots:
            visit(shape.Hasher.getID(identity))
        return records

    def primary_hasher(self):
        box = self.doc.addObject("Part::Box", "PrimarySeed")
        self.doc.recompute()
        holder = self.doc.addObject("Part::Feature", "PrimaryHolder")
        holder.Shape = box.Shape
        self.assertIsNotNone(holder.Shape.Hasher)
        return holder.Shape.Hasher

    def check_records(self, shape, expected):
        records = self.identity_records(shape)
        for identity, record in expected.items():
            sid = shape.Hasher.getID(identity)
            self.assertIsNotNone(sid, identity)
            self.assertEqual((sid.Data, sid.IsBinary, sid.IsHashed,
                              list(sid.Related)), record)
        return records

    def assert_reference_points(self, doc, expected):
        reference = doc.getObject("Reference")
        actual = []
        for obj, names in reference.References:
            for name in names:
                point = obj.Shape.getElement(name).Point
                actual.append((point.x, point.y, point.z))
        self.assertEqual(actual, expected)

    def test_assignment_preserves_native_owner_and_recursive_ids(self):
        source = self.make_source()
        before = self.identity_records(source)
        self.assertTrue(any(record[3] for record in before.values()), "Need recursive IDs")
        self.assertFalse(source.Hasher.SaveAll)
        original_brep = source.exportBrepToString()
        target = self.doc.addObject("Part::Feature", "Target")
        target.Shape = source
        self.assertTrue(target.Shape.Hasher.isSame(source.Hasher))
        self.check_records(target.Shape, before)
        self.assertEqual(self.identity_records(source), before)
        self.assertEqual(source.exportBrepToString(), original_brep)
        self.assertEqual(target.Shape.Volume, source.Volume)

    def test_destination_numeric_collisions_do_not_alias(self):
        primary = self.primary_hasher()
        source = self.make_source()
        before = self.identity_records(source)
        noise = [primary.getID("Unrelated primary identity %d" % i)
                 for i in range(max(before) + 2)]
        self.assertFalse(primary.isSame(source.Hasher))
        self.assertTrue(all(primary.getID(i) is not None for i in before))
        self.assertTrue(any(primary.getID(i).Data != record[0] for i, record in before.items()))
        target = self.doc.addObject("Part::Feature", "Target")
        target.Shape = source
        self.assertFalse(target.Shape.Hasher.isSame(primary))
        self.check_records(target.Shape, before)
        self.assertTrue(noise)  # Keep the unrelated collision controls alive.

    def test_unmapped_assignment_does_not_clear_shared_source(self):
        source = self.make_source()
        before = self.identity_records(source)
        untagged = Part.makeBox(1, 1, 1)
        untagged.Hasher = source.Hasher
        self.assertEqual(untagged.Tag, 0)
        self.assertEqual(untagged.ElementMapSize, 0)
        target = self.doc.addObject("Part::Feature", "Unmapped")
        target.Shape = untagged
        self.assertEqual(self.identity_records(source), before)
        self.assertAlmostEqual(target.Shape.Volume, 1)

    def test_source_document_close_preserves_foreign_ids(self):
        source_doc = App.newDocument("ShapeHasherOwnershipSource")
        source_name = source_doc.Name
        try:
            source = source_doc.addObject("Part::Feature", "Source")
            source.Shape = self.make_source()
            before = self.identity_records(source.Shape)
            point = source.Shape.Vertexes[0].Point
            target = self.doc.addObject("Part::Feature", "Target")
            target.Shape = source.Shape
            self.assertTrue(target.Shape.Hasher.isSame(source.Shape.Hasher))
            App.closeDocument(source_name)
            del source, source_doc
            gc.collect()
            self.check_records(target.Shape, before)
            self.assertLess((target.Shape.Vertexes[0].Point - point).Length, 1e-9)
        finally:
            if source_name in App.listDocuments():
                App.closeDocument(source_name)

    def test_two_hasher_save_reopen_and_source_gc(self):
        expected_records = {}
        points = []
        owners = []
        for index, offset in enumerate((0, 50)):
            source = self.make_source(offset, "Seed%d" % index)
            before = self.identity_records(source)
            target = self.doc.addObject("Part::Feature", "Target%d" % index)
            target.Shape = source
            self.check_records(target.Shape, before)
            expected_records[target.Name] = self.identity_records(target.Shape)
            owners.append(target)
            point = source.Vertexes[0].Point
            points.append((point.x, point.y, point.z))
        self.assertFalse(owners[0].Shape.Hasher.isSame(owners[1].Shape.Hasher))
        self.assertEqual(set(expected_records[owners[0].Name]),
                         set(expected_records[owners[1].Name]))
        self.assertNotEqual(expected_records[owners[0].Name], expected_records[owners[1].Name])
        reference = self.doc.addObject("App::FeaturePython", "Reference")
        reference.addProperty("App::PropertyLinkSubList", "References")
        reference.References = [(target, ["Vertex1"]) for target in owners]
        del source, before
        gc.collect()
        self.doc.recompute()
        self.assert_reference_points(self.doc, points)
        with TemporaryDirectory() as directory:
            filename = str(Path(directory) / "foreign-hashers.FCStd")
            for unused in range(2):
                for target in owners:
                    self.assertFalse(target.Shape.Hasher.SaveAll)
                self.doc.saveAs(filename)
                App.closeDocument(self.doc.Name)
                del owners
                gc.collect()
                self.doc = App.openDocument(filename)
                owners = [self.doc.getObject("Target%d" % i) for i in range(2)]
                # Inspect stored identity data and actual linked points before recompute.
                for target in owners:
                    self.check_records(target.Shape, expected_records[target.Name])
                    self.assertFalse(target.Shape.Hasher.SaveAll)
                self.assertFalse(owners[0].Shape.Hasher.isSame(owners[1].Shape.Hasher))
                self.assert_reference_points(self.doc, points)
                self.doc.recompute(None, True)
                self.assert_reference_points(self.doc, points)

    def test_assignment_undo_redo_preserves_identity(self):
        first = self.make_source()
        second = self.make_source(50, "SecondSeed")
        target = self.doc.addObject("Part::Feature", "Target")
        target.Shape = first
        self.assertTrue(target.Shape.Hasher.isSame(first.Hasher))
        first_records = self.identity_records(target.Shape)
        self.doc.openTransaction("Replace foreign-owned shape")
        target.Shape = second
        self.assertTrue(target.Shape.Hasher.isSame(second.Hasher))
        self.doc.commitTransaction()
        second_records = self.identity_records(target.Shape)
        self.doc.undo()
        self.assertTrue(target.Shape.Hasher.isSame(first.Hasher))
        self.check_records(target.Shape, first_records)
        self.assertLess((target.Shape.Vertexes[0].Point - first.Vertexes[0].Point).Length, 1e-9)
        self.doc.redo()
        self.assertTrue(target.Shape.Hasher.isSame(second.Hasher))
        self.check_records(target.Shape, second_records)
        self.assertLess((target.Shape.Vertexes[0].Point - second.Vertexes[0].Point).Length, 1e-9)
