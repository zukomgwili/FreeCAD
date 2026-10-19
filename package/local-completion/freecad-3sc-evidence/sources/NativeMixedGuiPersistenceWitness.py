"""Private real-GUI material persistence qualification; no unsaved embedding claim.

The mixed nonzero row is authored by the stock GUI delegates. A separately
labelled null fixture uses only documented native Array2D dimension setters;
native GUI row insertion itself authors zeros rather than invalid QVariant nulls.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil

import FreeCAD as App
import Materials
import Part

import NativeMixedGuiGreenWitness as G


# These are values passed to real native QuantitySpinBox delegates by the base
# witness, not values substituted into the material or array implementation.
G.VALUES.update({0: 301.1234567890123, 1: 1000.1234567890123,
                 3: 2000.2345678901234, 4: 3000.3456789012345})


def material_identity(material):
    from femtools.native_properties import property_value

    canonical = property_value(material)
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return {"canonical": canonical, "sha256": hashlib.sha256(encoded.encode()).hexdigest()}


def scope(manager):
    output = G.OUT.resolve()
    user_data = Path(App.getUserAppDataDir()).resolve()
    libraries = [{"name": name, "path": str(Path(path).resolve())}
                 for name, path, _icon in manager.MaterialLibraries if path]
    user = [entry for entry in libraries if entry["name"] == "User"]
    if len(user) != 1:
        raise AssertionError(f"Expected one native User library: {libraries}")
    actual = Path(user[0]["path"])
    if actual == output or not actual.is_relative_to(output):
        raise AssertionError(f"Native User library outside this owned profile: {actual}")
    if user_data == output or not user_data.is_relative_to(output):
        raise AssertionError(f"Actual native user data outside this owned profile: {user_data}")
    return {
        "output": str(output), "user_app_data_dir": str(user_data),
        "user_library": str(actual), "material_libraries": libraries,
        "native_config": {key: App.ConfigGet(key) for key in
                          ("UserAppData", "UserHomePath", "UserParameter", "SystemParameter",
                           "AppHomePath", "ExeName", "BinPath")},
        "private_environment": {key: os.environ.get(key) for key in
                                ("FREECAD_USER_HOME", "FREECAD_USER_DATA", "FREECAD_USER_TEMP",
                                 "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME")},
    }


class NativeMixedGuiPersistenceWitness(G.NativeMixedGuiGreenWitness):
    def check_private_persistence(self, docs):
        from femmesh import quality
        from femtools import force_accounting

        manager = Materials.MaterialManager()
        actual_scope = scope(manager)
        producer_paths = [Path(__file__).resolve(), Path(G.__file__).resolve(),
                          G.ROOT / "NativeMixedGuiWitness.py", G.ROOT / "GuiMaterialReadBridge.cpp",
                          G.ROOT / "GuiMaterialReadBridge.so",
                          Path(os.environ["FREECAD_3SC_BRIDGE"]),
                          Path(Materials.__file__).resolve(),
                          G.ROOT / "NativeMixedGuiColdRestore.py",
                          G.ROOT / "run_gui_persistence.py", G.ROOT / "run_cold_restore.py",
                          G.ROOT / "compile_green_bridge.py"]
        producer_paths.extend(Path(image["path"]).resolve()
                              for image in self.record["loaded_material_images_after_bridge_gui"])
        producer_paths = list(dict.fromkeys(producer_paths))
        producers_before = {str(path): G.sha(path) for path in producer_paths}
        for path in producer_paths:
            if path.parent == G.ROOT:
                shutil.copy2(path, G.OUT / path.name)
        self.record["persistence"] = {
            "assessed": True, "verdict": "PENDING", "actual_scope": actual_scope,
            "producer_sha256_before": producers_before,
            "gui_precision_fixture": dict(G.VALUES),
            "fcstd_semantics": "UUID lookup into saved available private User library; not embedded unsaved material",
            "null_fixture_origin": "Separate documented public Array2D.Columns/Rows setters; not GUI-authored nulls",
        }
        expected = {"scope": actual_scope, "producer_sha256": producers_before,
                    "runtime": App.Version(), "materials_module": self.record["Materials_module"],
                    "gui_material": {}, "public_api_null_material": {}}

        gui_material = self.latest_material
        gui_expected_array = G.array_snapshot(gui_material.getPhysicalValue("ElasticProperties"))
        before_save_identity = material_identity(gui_material)
        # Native Manager/Library legitimately assigns saved card Name/Directory.
        # Capture this explicitly; do not omit these metadata fields from hashes.
        scope(manager)
        manager.save("User", gui_material, "/GuiCreated.FCMat", saveInherited=True)
        gui_uuid = gui_material.UUID
        cached = manager.getMaterial(gui_uuid)
        self.assertEqual(G.array_snapshot(cached.getPhysicalValue("ElasticProperties")), gui_expected_array)
        saved_identity = material_identity(cached)
        manager.refresh()
        scope(manager)
        loaded = manager.getMaterial(gui_uuid)
        self.assertEqual(material_identity(loaded), saved_identity)
        self.assertEqual(G.array_snapshot(loaded.getPhysicalValue("ElasticProperties")), gui_expected_array)
        expected["gui_material"] = {
            "uuid": gui_uuid, "typed_array": gui_expected_array,
            "identity": saved_identity, "card": str(Path(actual_scope["user_library"]) / "GuiCreated.FCMat"),
        }
        doc = self.geometry_doc
        doc.Geometry.ShapeMaterial = loaded
        doc.recompute()
        baseline_hashes = {"model_digest": force_accounting._model_digest(doc.Analysis, doc.MeshGmsh),
                           "quality_input_fingerprint": quality.input_fingerprint(doc.MeshGmsh)}
        doc_path = G.OUT / f"{doc.Name}.FCStd"
        doc.saveAs(str(doc_path))
        old_name = doc.Name
        docs.remove(doc)
        App.closeDocument(old_name)
        restored = App.openDocument(str(doc_path))
        docs.append(restored)
        self.assertEqual(restored.Name, old_name)
        self.assertEqual(restored.Geometry.ShapeMaterial.UUID, gui_uuid)
        self.assertEqual(material_identity(restored.Geometry.ShapeMaterial), saved_identity)
        restored_hashes = {"model_digest": force_accounting._model_digest(restored.Analysis, restored.MeshGmsh),
                           "quality_input_fingerprint": quality.input_fingerprint(restored.MeshGmsh)}
        self.assertEqual(restored_hashes, baseline_hashes,
                         "FCStd restore must not bypass or omit material metadata in FEM identities")
        expected["gui_material"].update(document=str(doc_path), document_name=old_name,
                                         fem_hashes=baseline_hashes)

        null_material = Materials.Material()
        null_material.addPhysicalModel(G.MODEL)
        null_array = Materials.Array2D()
        null_array.Columns = 5
        null_array.Rows = 2
        null_material.setValue("ElasticProperties", null_array)
        self.assertEqual(null_material.getPhysicalValue("ElasticProperties").TypedArray,
                         [[None] * 5, [None] * 5])
        null_expected_array = G.array_snapshot(null_material.getPhysicalValue("ElasticProperties"))
        scope(manager)
        manager.save("User", null_material, "/PublicApiNullSeed.FCMat", saveInherited=True)
        null_uuid = null_material.UUID
        cached_null = manager.getMaterial(null_uuid)
        null_saved_identity = material_identity(cached_null)
        self.assertEqual(G.array_snapshot(cached_null.getPhysicalValue("ElasticProperties")), null_expected_array)
        manager.refresh()
        scope(manager)
        loaded_null = manager.getMaterial(null_uuid)
        self.assertEqual(material_identity(loaded_null), null_saved_identity)
        self.assertEqual(G.array_snapshot(loaded_null.getPhysicalValue("ElasticProperties")), null_expected_array)
        null_doc = App.newDocument("NativeNullArray")
        docs.append(null_doc)
        null_shape = null_doc.addObject("Part::Feature", "Geometry")
        null_shape.Shape = Part.makeBox(1, 1, 1)
        null_shape.ShapeMaterial = loaded_null
        null_doc.recompute()
        null_doc_path = G.OUT / "NativeNullArray.FCStd"
        null_doc.saveAs(str(null_doc_path))
        docs.remove(null_doc)
        App.closeDocument(null_doc.Name)
        restored_null = App.openDocument(str(null_doc_path))
        docs.append(restored_null)
        self.assertEqual(restored_null.Geometry.ShapeMaterial.UUID, null_uuid)
        self.assertEqual(material_identity(restored_null.Geometry.ShapeMaterial), null_saved_identity)
        expected["public_api_null_material"] = {
            "uuid": null_uuid, "typed_array": null_expected_array,
            "identity": null_saved_identity,
            "card": str(Path(actual_scope["user_library"]) / "PublicApiNullSeed.FCMat"),
            "document": str(null_doc_path), "document_name": "NativeNullArray",
            "origin": "Native public dimension setters, not GUI row insertion",
        }
        for name in ("gui_material", "public_api_null_material"):
            case = expected[name]
            case["card_sha256"] = G.sha(case["card"])
            case["document_sha256"] = G.sha(case["document"])
        producers_after = {str(path): G.sha(path) for path in producer_paths}
        self.assertEqual(producers_after, producers_before)
        self.record["persistence"].update(
            verdict="PASS", public_manager_save_refresh_exact=True,
            same_process_fcstd_uuid_library_restore_exact=True,
            same_process_fem_hashes_exact=True,
            source_material_before_card_save=before_save_identity,
            saved_material_identity=saved_identity,
            producer_sha256_after=producers_after,
            cases=expected,
            cold_process_restore_assessed=False,
        )
        (G.OUT / "cold-restore-expected.json").write_text(json.dumps(expected, indent=2) + "\n")
