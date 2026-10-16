# SPDX-License-Identifier: LGPL-2.1-or-later

"""Native operations must not interpret a foreign hasher's numeric identities locally."""

from collections import Counter, defaultdict
import gc
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest

import FreeCAD as App
import Part


_IDENTITY = re.compile(r"#([0-9a-fA-F]+)")


class TestMixedShapeHashers(unittest.TestCase):
    def setUp(self):
        self.documents = []

    def tearDown(self):
        for name in self.documents:
            if name in App.listDocuments():
                App.closeDocument(name)

    @staticmethod
    def make_source(hasher, seed, offset=0, native_ids=True):
        shape = Part.makeBox(2, 3, 4)
        shape.Tag = 1
        shape = shape.copy(seed, hasher)
        if native_ids:
            shape = shape.fuse(shape.translated(App.Vector(1, 0, 0)))
        if offset:
            shape.translate(App.Vector(offset, 0, 0))
        return shape

    def make_pair(self, shared=False, native_ids=True, reverse_creation=False):
        first = App.StringHasher()
        second = first if shared else App.StringHasher()
        if reverse_creation:
            right = self.make_source(second, "SeedB", 1, native_ids)
            left = self.make_source(first, "SeedA", native_ids=native_ids)
        else:
            left = self.make_source(first, "SeedA", native_ids=native_ids)
            right = self.make_source(second, "SeedB", 1, native_ids)
        return left, right

    def identity_records(self, shape, require_ids=True):
        """Check both declared dependencies and IDs embedded in native string data."""
        roots = {int(value, 16) for raw in shape.ElementMap
                 for value in _IDENTITY.findall(raw)}
        if require_ids:
            self.assertTrue(roots, "Fixture must exercise genuine native hashed names")
        if roots:
            self.assertIsNotNone(shape.Hasher)
        records = {}

        def visit(value, active):
            self.assertNotIn(value, active, "Cyclic native hashed identity")
            if value in records:
                return
            sid = shape.Hasher.getID(value)
            self.assertIsNotNone(sid, "Native mapped identity #%x is missing" % value)
            related = tuple(sid.Related)
            record = (sid.Data, sid.IsBinary, sid.IsHashed, related)
            descendants = set(related)
            if not sid.IsBinary and not sid.IsHashed:
                descendants.update(int(raw, 16) for raw in _IDENTITY.findall(sid.Data))
            for child in descendants:
                visit(child, active | {value})
            records[value] = record

        for value in roots:
            visit(value, set())
        return roots, records

    @staticmethod
    def fingerprint(element):
        """Pair identity meaning with actual geometry, including vertex-only names."""
        bounds = element.BoundBox
        extent = tuple(round(getattr(bounds, name), 9)
                       for name in ("XMin", "YMin", "ZMin", "XMax", "YMax", "ZMax"))
        if element.ShapeType == "Vertex":
            measure = 0
        elif element.ShapeType == "Edge":
            measure = element.Length
        elif element.ShapeType == "Face":
            measure = element.Area
        else:
            measure = element.Volume
        return element.ShapeType, extent, round(measure, 9)

    def semantic_records(self, shape):
        self.assertTrue(shape.ElementMap, "Need native mapped names, not bare BRep")
        records = Counter()
        for raw, indexed in shape.ElementMap.items():
            history = shape.getElementHistory(raw)
            # Intermediate history retains local IDs and generated disambiguation hashes.
            # The expanded source name and its physical target are the stable semantics.
            origin = None if history is None else tuple(history[:2])
            records[self.fingerprint(shape.getElement(indexed)), origin] += 1
        return records

    @staticmethod
    def geometry_only(shape):
        # Geometry comparisons must not introduce another naming operation or
        # change the identity tables being qualified by this test.
        result = Part.Shape()
        result.importBrepFromString(shape.exportBrepToString())
        return result

    def origin_geometry(self, shapes):
        origins = defaultdict(list)
        for shape in shapes:
            self.assertTrue(shape.ElementMap)
            for raw, indexed in shape.ElementMap.items():
                history = shape.getElementHistory(raw)
                origin = tuple(history[:2]) if history else (shape.Tag, raw)
                origins[origin].append(self.geometry_only(shape.getElement(indexed)))
        return origins

    def provenance_records(self, shape, origins):
        """Check that each reported source can physically contain its mapped target."""
        self.assertTrue(shape.ElementMap)
        records = Counter()
        for raw, indexed in shape.ElementMap.items():
            history = shape.getElementHistory(raw)
            origin = tuple(history[:2]) if history else (shape.Tag, raw)
            element = self.geometry_only(shape.getElement(indexed))
            supported = False
            for candidate in origins.get(origin, []):
                if element.ShapeType == "Vertex":
                    supported = element.distToShape(candidate)[0] < 1e-8
                else:
                    overlap = element.common(candidate)
                    measure = "Length" if element.ShapeType == "Edge" else "Area"
                    supported = abs(getattr(overlap, measure) - getattr(element, measure)) < 1e-8
                if supported:
                    break
            records[self.fingerprint(element), supported] += 1
        return records

    def assert_supported_provenance(self, records):
        self.assertTrue(records)
        unsupported = {geometry: count for (geometry, supported), count in records.items()
                       if not supported}
        self.assertFalse(unsupported, "Mapped targets are outside their reported source primitives")

    def assert_rightmost_origin(self, shape, x, seed="SeedB"):
        meanings = [shape.getElementHistory(raw)[1]
                    for raw, indexed in shape.ElementMap.items()
                    if indexed.startswith("Face")
                    and abs(shape.getElement(indexed).CenterOfMass.x - x) < 1e-9]
        self.assertTrue(meanings)
        self.assertTrue(all(seed in meaning for meaning in meanings))

    def snapshot(self, shape):
        return (shape.Hasher, shape.exportBrepToString(), dict(shape.ElementMap),
                self.identity_records(shape, require_ids=False))

    def assert_unchanged(self, shape, before, check_brep=True):
        owner, brep, names, identities = before
        self.assertTrue(shape.Hasher.isSame(owner))
        if check_brep:
            self.assertEqual(shape.exportBrepToString(), brep)
        self.assertEqual(shape.ElementMap, names)
        self.assertEqual(self.identity_records(shape, require_ids=False), identities)

    @staticmethod
    def operate(operation, first, second):
        if operation == "compound":
            return Part.makeCompound([first, second])
        if operation == "nested compound":
            return Part.makeCompound([Part.makeCompound([first]), Part.makeCompound([second])])
        if operation == "generalFuse":
            return first.generalFuse([second])[0]
        return getattr(first, operation)(second)

    def native_fuse(self):
        doc = App.newDocument("MixedShapeHashers")
        self.documents.append(doc.Name)
        first, second = self.make_pair()
        inputs = [doc.addObject("Part::Feature", name) for name in ("A", "B")]
        inputs[0].Shape, inputs[1].Shape = first, second
        result = doc.addObject("Part::Fuse", "Union")
        result.Base, result.Tool = inputs
        result.Refine = False
        doc.recompute()
        return doc, inputs, result

    def test_minimal_native_copy_boolean_ids(self):
        for operation in ("fuse", "cut", "common", "generalFuse"):
            with self.subTest(operation=operation):
                first, second = self.make_pair(native_ids=False)
                self.assertTrue(first.ElementMap and second.ElementMap)
                before = [self.snapshot(shape) for shape in (first, second)]
                output = self.operate(operation, first, second)
                self.assertTrue(output.isValid())
                self.assert_unchanged(first, before[0])
                self.assert_unchanged(second, before[1])
                self.identity_records(output)

    def test_native_primitive_provenance_has_physical_support(self):
        for operation in ("fuse", "cut", "common", "generalFuse", "compound", "nested compound"):
            for reverse in (False, True):
                with self.subTest(operation=operation, reverse=reverse):
                    inputs = self.make_pair(native_ids=False)
                    if reverse:
                        inputs = inputs[::-1]
                    origins = self.origin_geometry(inputs)
                    output = self.operate(operation, *inputs)
                    self.assertTrue(output.isValid())
                    self.assert_supported_provenance(self.provenance_records(output, origins))
                    if operation in ("fuse", "generalFuse") or (operation == "cut" and reverse):
                        self.assert_rightmost_origin(output, 3)
                    self.identity_records(output, require_ids="compound" not in operation)

    def test_native_boolean_semantics_match_shared_owner(self):
        for operation in ("fuse", "cut", "common", "generalFuse"):
            for reverse in (False, True):
                with self.subTest(operation=operation, reverse=reverse):
                    mixed = self.make_pair()
                    # The native mapper can choose either provenance on shared
                    # geometry by numeric ID order. Seed the control's selected
                    # output domain in the same operand order as the mixed run.
                    shared = self.make_pair(shared=True, reverse_creation=reverse)
                    if reverse:
                        mixed, shared = mixed[::-1], shared[::-1]
                    before = [self.snapshot(shape) for shape in mixed]
                    origins = self.origin_geometry(mixed)
                    control_origins = self.origin_geometry(shared)
                    actual = self.operate(operation, *mixed)
                    control = self.operate(operation, *shared)
                    self.assertTrue(actual.isValid())
                    self.assertAlmostEqual(actual.Volume, control.Volume)
                    for shape, old in zip(mixed, before):
                        self.assert_unchanged(shape, old)
                    if operation in ("fuse", "generalFuse") or (operation == "cut" and reverse):
                        self.assert_rightmost_origin(actual, 4)
                    # Equal geometry can legitimately choose different origins
                    # by local SID allocation order. Compare actual physical
                    # support, not one control's local choice of provenance.
                    expected = self.provenance_records(control, control_origins)
                    self.assert_supported_provenance(expected)
                    self.assertEqual(self.provenance_records(actual, origins), expected)
                    self.identity_records(actual)

    def test_recursive_indexed_history_uses_existing_seed_elements(self):
        source = Part.makeBox(2, 3, 4)
        source.Tag = 1
        source = source.copy("SeedA", App.StringHasher())
        result = source.fuse(source.translated(App.Vector(1, 0, 0)))
        checked = 0
        for raw in result.ElementMap:
            history = result.getElementHistory(raw)
            if history:
                match = re.match(r"(Vertex|Edge|Face)([0-9]+);SeedA", history[1])
                if match:
                    checked += 1
                    self.assertLessEqual(int(match[2]), source.countElement(match[1]))
        self.assertGreater(checked, 0)

    def test_compound_semantics_match_shared_owner(self):
        for operation in ("compound", "nested compound"):
            with self.subTest(operation=operation):
                mixed = self.make_pair()
                shared = self.make_pair(shared=True)
                before = [self.snapshot(shape) for shape in mixed]
                origins = self.origin_geometry(mixed)
                control_origins = self.origin_geometry(shared)
                actual = self.operate(operation, *mixed)
                control = self.operate(operation, *shared)
                for shape, old, shared_shape in zip(mixed, before, shared):
                    # BRep_Builder marks members non-Free in both native runs.
                    # Keep exact geometry parity with that shared-owner control,
                    # while maps and all existing identity records stay unchanged.
                    self.assert_unchanged(shape, old, check_brep=False)
                    self.assertEqual(shape.exportBrepToString(), shared_shape.exportBrepToString())
                # Nested child-map history can expose an unexpanded local ID
                # in either domain; simple native copies above check every
                # primitive strictly, while this fixture covers recursive SIDs.
                self.assertEqual(self.provenance_records(actual, origins),
                                 self.provenance_records(control, control_origins))
                self.identity_records(actual)

    def test_general_fuse_history_fragments_preserve_semantics(self):
        # Bare copied boxes are solids: Boolean-generated compounds can return
        # empty history groups, which would make fragment qualification vacuous.
        mixed = self.make_pair(native_ids=False)
        shared = self.make_pair(shared=True, native_ids=False)
        before = [self.snapshot(shape) for shape in mixed]
        origins = self.origin_geometry(mixed)
        actual, fragments = mixed[0].generalFuse([mixed[1]])
        control, expected = shared[0].generalFuse([shared[1]])
        self.assertEqual(len(fragments), 2)
        self.assertEqual([len(group) for group in fragments],
                         [len(group) for group in expected])
        self.assertTrue(all(fragments))
        for shape, old in zip(mixed, before):
            self.assert_unchanged(shape, old)
        # The history map contains exported fragment shapes, not just identifiers
        # into the aggregate. Each returned shape needs its own coherent owner.
        for index, (group, controls) in enumerate(zip(fragments, expected)):
            for part, (fragment, reference) in enumerate(zip(group, controls)):
                with self.subTest(source=index, fragment=part):
                    self.assertTrue(fragment.isValid())
                    self.assertAlmostEqual(fragment.Volume, reference.Volume)
                    self.assert_supported_provenance(self.provenance_records(fragment, origins))
                    self.identity_records(fragment, require_ids=False)
        self.assertAlmostEqual(actual.Volume, control.Volume)
        self.assert_supported_provenance(self.provenance_records(actual, origins))
        self.identity_records(actual)

    def test_explicit_foreign_copy_preserves_semantics(self):
        for collisions in (False, True):
            with self.subTest(collisions=collisions):
                source = self.make_source(App.StringHasher(), "SeedA")
                before = self.snapshot(source)
                destination = App.StringHasher()
                noise = ([destination.getID("Unrelated identity %d" % i) for i in range(32)]
                         if collisions else [])
                actual = source.copy("ForeignCopy", destination)
                control = source.copy("ForeignCopy", source.Hasher)
                self.assert_unchanged(source, before)
                self.assertTrue(actual.Hasher.isSame(destination))
                self.assertEqual(self.semantic_records(actual), self.semantic_records(control))
                self.identity_records(actual)
                self.assertEqual(len(noise), 32 if collisions else 0)

    def test_literal_hash_in_operation_names_is_not_translated(self):
        for seed in ("Seed#1", "Seed#3", "Seed(#1)", "Seed,#1"):
            with self.subTest(seed=seed):
                source = self.make_source(App.StringHasher(), seed)
                names = dict(source.ElementMap)
                brep = source.exportBrepToString()
                destination = App.StringHasher()
                noise = [destination.getID("Unrelated identity %d" % i) for i in range(32)]
                actual = source.copy("ForeignCopy", destination)
                control = source.copy("ForeignCopy", source.Hasher)
                self.assertEqual(self.semantic_records(actual), self.semantic_records(control))
                self.assertEqual(dict(source.ElementMap), names)
                self.assertEqual(source.exportBrepToString(), brep)
                self.assertTrue(noise)

    def test_native_feature_fuse_retains_recursive_ids(self):
        doc, inputs, result = self.native_fuse()
        before = [self.snapshot(obj.Shape) for obj in inputs]
        for obj in inputs:
            roots, records = self.identity_records(obj.Shape)
            self.assertEqual(len(roots), 5)
            self.assertEqual(len(records), 13)
            self.assertTrue(any(record[3] for record in records.values()))
        self.assertFalse(inputs[0].Shape.Hasher.isSame(inputs[1].Shape.Hasher))
        self.assertAlmostEqual(result.Shape.Volume, 48)
        self.assertTrue(result.Shape.isValid())
        doc.recompute(None, True)
        for obj, old in zip(inputs, before):
            self.assert_unchanged(obj.Shape, old)
        self.identity_records(result.Shape)

    def test_regeneration_and_save_reopen_keep_linked_face(self):
        doc, inputs, result = self.native_fuse()
        selected = next("Face%d" % (index + 1) for index, face in enumerate(result.Shape.Faces)
                        if abs(face.CenterOfMass.x - 4) < 1e-9)
        reference = doc.addObject("App::FeaturePython", "Reference")
        reference.addProperty("App::PropertyLinkSubList", "References")
        reference.References = [(result, [selected])]
        inputs[1].Shape = self.make_source(inputs[1].Shape.Hasher, "SeedB", 1.5)
        doc.recompute()

        def verify():
            owner, names = doc.Reference.References[0]
            self.assertEqual(len(names), 1)
            face = owner.Shape.getElement(names[0])
            self.assertEqual(face.ShapeType, "Face")
            self.assertAlmostEqual(face.CenterOfMass.x, 4.5)
            self.assertAlmostEqual(face.Area, 12)
            for name in ("A", "B", "Union"):
                shape = doc.getObject(name).Shape
                self.assertFalse(shape.Hasher.SaveAll)
                self.identity_records(shape)

        verify()
        with TemporaryDirectory() as directory:
            filename = str(Path(directory) / "mixed-hashers.FCStd")
            for unused in range(2):
                doc.saveAs(filename)
                App.closeDocument(doc.Name)
                doc = App.openDocument(filename)
                self.documents.append(doc.Name)
                verify()  # Inspect persisted IDs and the linked physical face before recompute.
                doc.recompute(None, True)
                verify()

    def test_native_opaque_identity_payloads_survive_save(self):
        # Use the document primary throughout, isolating persistence from foreign
        # assignment/import. Read opaque leaf data only: composite textual
        # introspection at low thresholds is the separate FreeCAD-3ir issue.
        for threshold in (0, 1, 40):
            with self.subTest(threshold=threshold):
                doc = App.newDocument("OpaqueShapeHashers")
                self.documents.append(doc.Name)
                box = doc.addObject("Part::Box", "Seed")
                doc.recompute()
                target = doc.addObject("Part::Feature", "Target")
                target.Shape = box.Shape
                hasher = target.Shape.Hasher
                hasher.Threshold = threshold
                target.Shape = self.make_source(hasher, "OpaqueSeed")
                doc.recompute()

                def snapshot(shape):
                    records = {}

                    def visit(value):
                        if value in records:
                            return
                        sid = shape.Hasher.getID(value)
                        self.assertIsNotNone(sid)
                        opaque = sid.IsHashed or sid.IsBinary
                        records[value] = (sid.Data if opaque else None,
                                          sid.IsHashed, sid.IsBinary, tuple(sid.Related))
                        for child in sid.Related:
                            visit(child)

                    for name in shape.ElementMap:
                        for value in _IDENTITY.findall(name):
                            visit(int(value, 16))
                    self.assertTrue(records)
                    return records

                expected = snapshot(target.Shape)
                if threshold == 1:
                    self.assertTrue(any(record[1] for record in expected.values()))
                names = dict(target.Shape.ElementMap)
                with TemporaryDirectory() as directory:
                    filename = str(Path(directory) / "opaque-hasher.FCStd")
                    doc.saveAs(filename)
                    App.closeDocument(doc.Name)
                    del target, hasher, box
                    doc = App.openDocument(filename)
                    self.documents.append(doc.Name)
                    self.assertFalse(doc.Target.Shape.Hasher.SaveAll)
                    self.assertEqual(dict(doc.Target.Shape.ElementMap), names)
                    self.assertEqual(snapshot(doc.Target.Shape), expected)
                    self.assertAlmostEqual(doc.Target.Shape.Volume, 36)

    def test_saved_child_names_survive_boolean_without_source_documents(self):
        with TemporaryDirectory() as directory:
            filename = str(Path(directory) / "child-map-inputs.FCStd")
            doc = App.newDocument("MixedChildMapSources")
            self.documents.append(doc.Name)
            for name, seed, offset in (("A", "SeedA", 0), ("B", "SeedB", 1)):
                shape = self.make_source(App.StringHasher(), seed, offset)
                feature = doc.addObject("Part::Feature", name)
                feature.Shape = shape.copy("LongNativeChildOperationForCopy", shape.Hasher)
            doc.recompute()
            doc.saveAs(filename)  # Materialize the native hashed child postfixes.
            App.closeDocument(doc.Name)
            del shape, feature
            gc.collect()
            doc = App.openDocument(filename)
            self.documents.append(doc.Name)
            for name in ("A", "B"):
                self.identity_records(doc.getObject(name).Shape)
            output = doc.A.Shape.fuse(doc.B.Shape)
            expected_meanings = self.semantic_records(output)
            destination = App.newDocument("MixedChildMapOutput")
            self.documents.append(destination.Name)
            target = destination.addObject("Part::Feature", "Target")
            target.Shape = output
            self.assertEqual(self.semantic_records(target.Shape), expected_meanings)
            App.closeDocument(doc.Name)
            del output, doc
            gc.collect()
            self.identity_records(target.Shape)
            self.assertEqual(self.semantic_records(target.Shape), expected_meanings)
            filename = str(Path(directory) / "child-map-output.FCStd")
            destination.saveAs(filename)
            App.closeDocument(destination.Name)
            del target, destination
            gc.collect()
            restored = App.openDocument(filename)
            self.documents.append(restored.Name)
            self.assertFalse(restored.Target.Shape.Hasher.SaveAll)
            self.identity_records(restored.Target.Shape)
            self.assertEqual(self.semantic_records(restored.Target.Shape), expected_meanings)
            self.assertAlmostEqual(restored.Target.Shape.Volume, 48)
