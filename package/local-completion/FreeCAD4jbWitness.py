# SPDX-License-Identifier: LGPL-2.1-or-later
"""Ordinary native solve/import lifecycle while retaining read-only material copies.

The existing CAD/contact/cut witness runs the real writer and bundled solver.
Only the Python lifetime of native material getters changes across communicate;
solver arguments, input files and returned output are never replaced.
"""

import os
import subprocess
from unittest import mock

import FreeCAD as App

import FreeCAD9ztProductionWitness as production


class MaterialLifetimePipelineWitness(production.ProductionAccountingWitness):
    def test_native_contact_cut_pipeline(self):
        original = subprocess.Popen
        held_materials = []

        def launch(*args, **kwargs):
            process = original(*args, **kwargs)
            if "-i" in args[0]:
                communicate = process.communicate

                def finish(*call_args, **call_kwargs):
                    output = communicate(*call_args, **call_kwargs)
                    documents = [
                        doc
                        for doc in App.listDocuments().values()
                        if doc.getObject("Geometry") is not None
                        and doc.getObject("Analysis") is not None
                    ]
                    self.assertEqual(len(documents), 1)
                    document = documents[0]
                    held_materials.extend(
                        obj.ShapeMaterial
                        for obj in document.Objects
                        if "ShapeMaterial" in obj.PropertiesList
                    )
                    return output

                process.communicate = finish
            return process

        output = os.environ.get(
            "FREECAD_4JB_OUTPUT", os.environ.get("FREECAD_9ZT_OUTPUT", "/tmp")
        )
        with mock.patch.dict(os.environ, FREECAD_9ZT_OUTPUT=output):
            with mock.patch.object(subprocess, "Popen", side_effect=launch):
                super().test_native_contact_cut_pipeline()
        self.assertTrue(held_materials)
