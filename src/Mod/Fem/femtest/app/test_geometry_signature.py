# SPDX-License-Identifier: LGPL-2.1-or-later

"""Exact ownership fingerprints must survive native shape persistence."""

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import FreeCAD as App
from femmesh import meshtools


class TestGeometrySignature(unittest.TestCase):
    def test_coincident_input_owner_change_invalidates_signature(self):
        doc = App.newDocument("GeometrySignatureOwners")
        try:
            first = doc.addObject("Part::Box", "First")
            second = doc.addObject("Part::Box", "Second")
            aggregate = doc.addObject("Part::Compound", "Aggregate")
            aggregate.Links = [first]
            doc.recompute()
            signature = meshtools.get_mesh_geometry_signature(aggregate)
            aggregate.Links = [second]
            doc.recompute()
            self.assertNotEqual(signature, meshtools.get_mesh_geometry_signature(aggregate))
        finally:
            App.closeDocument(doc.Name)

    def test_legacy_signature_requires_exact_current_geometry(self):
        doc = App.newDocument("LegacyGeometrySignature")
        try:
            solid = doc.addObject("Part::Box", "Box")
            doc.recompute()
            mesh = SimpleNamespace(
                ElementGroupGeometry=meshtools.get_mesh_geometry_signature(solid, canonical=False)
            )
            self.assertTrue(meshtools.mesh_geometry_matches(mesh, solid))
            solid.Length = 11
            doc.recompute()
            self.assertFalse(meshtools.mesh_geometry_matches(mesh, solid))
        finally:
            App.closeDocument(doc.Name)

    def test_curved_signature_survives_native_reopen(self):
        doc = App.newDocument("GeometrySignature")
        try:
            solid = doc.addObject("Part::Cylinder", "Cylinder")
            solid.Radius = 3
            solid.Height = 5
            doc.recompute()
            signature = meshtools.get_mesh_geometry_signature(solid)
            with tempfile.TemporaryDirectory() as directory:
                path = str(Path(directory) / "cylinder.FCStd")
                doc.saveAs(path)
                App.closeDocument(doc.Name)
                doc = App.openDocument(path)
                solid = doc.Cylinder
                self.assertEqual(signature, meshtools.get_mesh_geometry_signature(solid))
                solid.Radius = 3.5
                doc.recompute()
                self.assertNotEqual(signature, meshtools.get_mesh_geometry_signature(solid))
                solid.Radius = 3
                solid.Placement.Base.x = 0.125
                doc.recompute()
                self.assertNotEqual(signature, meshtools.get_mesh_geometry_signature(solid))
        finally:
            App.closeDocument(doc.Name)
