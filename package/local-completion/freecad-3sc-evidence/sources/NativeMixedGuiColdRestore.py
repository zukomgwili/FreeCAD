"""Read-only second-process private card/FCStd restore qualification."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import unittest

import FreeCAD as App
import Materials


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def material_identity(material):
    from femtools.native_properties import property_value

    canonical = property_value(material)
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return {"canonical": canonical, "sha256": hashlib.sha256(encoded.encode()).hexdigest()}


def material_images():
    process = ctypes.CDLL(None)
    process._dyld_image_count.restype = ctypes.c_uint32
    process._dyld_get_image_name.argtypes = [ctypes.c_uint32]
    process._dyld_get_image_name.restype = ctypes.c_char_p
    paths = [process._dyld_get_image_name(i).decode()
             for i in range(process._dyld_image_count())]
    return [{"path": path, "sha256": sha(path)} for path in paths
            if Path(path).name in ("Materials.so", "MatGui.so")]


class NativeMixedGuiColdRestore(unittest.TestCase):
    def test_saved_gui_and_public_null_cards_restore_exactly(self):
        from femmesh import quality
        from femtools import force_accounting

        expected_path = Path(os.environ["FREECAD_3SC_EXPECTED"]).resolve()
        expected = json.loads(expected_path.read_text())
        self.assertEqual(App.Version(), expected["runtime"])
        self.assertEqual(sha(Materials.__file__), expected["materials_module"]["sha256"])
        self.assertEqual({path: sha(path) for path in expected["producer_sha256"]},
                         expected["producer_sha256"])
        images = material_images()
        self.assertEqual([Path(image["path"]).resolve() for image in images
                          if Path(image["path"]).name == "Materials.so"],
                         [Path(Materials.__file__).resolve()])
        owned = expected_path.parent.resolve()
        self.assertTrue(owned.is_relative_to(Path(__file__).resolve().parent))
        manager = Materials.MaterialManager()
        user_libraries = [Path(path).resolve() for name, path, _icon in manager.MaterialLibraries
                          if name == "User"]
        self.assertEqual(user_libraries, [Path(expected["scope"]["user_library"]).resolve()])
        self.assertTrue(user_libraries[0].is_relative_to(owned))
        self.assertNotEqual(user_libraries[0], owned)
        self.assertEqual(Path(App.getUserAppDataDir()).resolve(),
                         Path(expected["scope"]["user_app_data_dir"]).resolve())
        protected = [Path(__file__).resolve(), expected_path]
        protected.extend(Path(expected[name][key]) for name in ("gui_material", "public_api_null_material")
                         for key in ("card", "document"))
        before = {str(path): sha(path) for path in protected}
        report = {"verdict": "PENDING", "runtime": App.Version(),
                  "Materials_module": {"path": Materials.__file__, "sha256": sha(Materials.__file__)},
                  "loaded_material_images": images,
                  "supervisor": {"path": os.environ["FREECAD_3SC_SUPERVISOR"],
                                 "sha256": sha(os.environ["FREECAD_3SC_SUPERVISOR"])},
                  "expected_receipt_sha256": sha(expected_path),
                  "actual_user_app_data_dir": App.getUserAppDataDir(),
                  "actual_user_library": str(user_libraries[0]), "cases": {},
                  "protected_sha256_before": before,
                  "semantics": "Cold UUID lookup against saved private library, not embedded unsaved materials"}
        try:
            for name in ("gui_material", "public_api_null_material"):
                case = expected[name]
                self.assertEqual(sha(case["card"]), case["card_sha256"])
                self.assertEqual(sha(case["document"]), case["document_sha256"])
                loaded = manager.getMaterial(case["uuid"])
                self.assertEqual(material_identity(loaded), case["identity"])
                doc = App.openDocument(case["document"])
                try:
                    self.assertEqual(doc.Name, case["document_name"])
                    self.assertEqual(doc.Geometry.ShapeMaterial.UUID, case["uuid"])
                    self.assertEqual(material_identity(doc.Geometry.ShapeMaterial), case["identity"])
                    if name == "gui_material":
                        hashes = {"model_digest": force_accounting._model_digest(doc.Analysis, doc.MeshGmsh),
                                  "quality_input_fingerprint": quality.input_fingerprint(doc.MeshGmsh)}
                        self.assertEqual(hashes, case["fem_hashes"])
                    report["cases"][name] = {"exact_material_identity": True, "uuid": case["uuid"]}
                finally:
                    App.closeDocument(doc.Name)
            after = {str(path): sha(path) for path in protected}
            self.assertEqual(after, before)
            report.update(verdict="PASS", protected_sha256_after=after)
        finally:
            output = Path(os.environ["FREECAD_3SC_OUTPUT"])
            (output / "cold-restore-report.json").write_text(json.dumps(report, indent=2) + "\n")
            print("NATIVE_MIXED_COLD_RESTORE " + json.dumps(report, sort_keys=True))
