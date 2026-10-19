"""Private native GUI TypedArray/FEM witness, prepared after preserved native red.

Parent-confirmed boundaries: real Qt material/array delegates; public TypedArray;
existing FEM input_fingerprint/_model_digest integration; optional public
MaterialManager save/refresh and UUID-based FCStd restore. No mechanics/solver.
"""
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import traceback
import unittest

import FreeCAD as App
import FreeCADGui as Gui
import Fem
import Materials
import ObjectsFem
import Part
from PySide import QtCore, QtGui, QtWidgets
import shiboken6

from NativeMixedGuiWitness import find_index


ROOT = Path(__file__).resolve().parent
OUT = Path(os.environ["FREECAD_3SC_OUTPUT"])
MODEL = "2afbba4b-55c0-4c4a-a6dc-4f5716cc5571"
VALUES = {0: 301.25, 1: 1000.125, 2: 0.314159, 3: 2000.25, 4: 3000.5}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def scalar(value):
    if isinstance(value, App.Units.Quantity):
        return {"type": "Quantity", "value_hex": value.Value.hex(),
                "unit_signature": list(value.Unit.Signature)}
    if isinstance(value, float):
        return {"type": "float", "value_hex": value.hex()}
    if isinstance(value, (str, int, bool)) or value is None:
        return {"type": type(value).__name__, "value": value}
    raise TypeError(type(value))


def array_snapshot(array):
    return [[scalar(cell) for cell in row] for row in array.TypedArray]


def loaded_material_images():
    process = ctypes.CDLL(None)
    count = process._dyld_image_count
    count.restype = ctypes.c_uint32
    name = process._dyld_get_image_name
    name.argtypes = [ctypes.c_uint32]
    name.restype = ctypes.c_char_p
    paths = [name(i).decode() for i in range(count())]
    return [{"path": path, "sha256": sha(path)} for path in paths
            if Path(path).name in ("Materials.so", "MatGui.so")]


class NativeMixedGuiGreenWitness(unittest.TestCase):
    def test_gui_typed_material_and_real_fem_input_identities(self):
        from femmesh import quality
        from femtools import force_accounting

        errors = []
        docs = []
        bridge_path = Path(os.environ.get("FREECAD_3SC_BRIDGE", ROOT / "GuiMaterialReadBridge.so"))
        protected = [ROOT / "NativeMixedGuiWitness.py", ROOT / "GuiMaterialReadBridge.cpp",
                     ROOT / "GuiMaterialReadBridge.so", Path(__file__).resolve(), bridge_path,
                     Path("/Applications/FreeCAD-27.1.0.app/Contents/Resources/lib/Materials.so"),
                     Path("/Applications/FreeCAD-27.1.0.app/Contents/Resources/lib/MatGui.so")]
        custody_before = {str(path): sha(path) for path in protected}
        for path in protected:
            if path.parent == ROOT:
                shutil.copy2(path, OUT / path.name)
        self.record = {
            "runtime": App.Version(), "stock_model_uuid": MODEL,
            "property": "ElasticProperties", "loaded_material_images": loaded_material_images(),
            "Materials_module": {"path": Materials.__file__, "sha256": sha(Materials.__file__)},
            "protected_sha256_before": custody_before,
            "bridge": "readonly copy of existing native GUI-owned Material; no cell replacement",
            "persistence": {"assessed": False},
            "engineering_acceptance": False, "solver_launched": False,
        }
        self.assertTrue(hasattr(Materials.Array2D(), "TypedArray"))
        bridge = ctypes.PyDLL(str(bridge_path))
        bridge.copy_editor_item_material.argtypes = [ctypes.c_void_p]
        bridge.copy_editor_item_material.restype = ctypes.py_object
        Gui.activateWorkbench("MaterialWorkbench")
        Gui.runCommand("Material_Edit", 0)
        Gui.updateGui()
        self.record["loaded_material_images_after_bridge_gui"] = loaded_material_images()
        material_images = [image["path"] for image in self.record["loaded_material_images_after_bridge_gui"]
                           if Path(image["path"]).name == "Materials.so"]
        self.assertEqual([Path(path).resolve() for path in material_images],
                         [Path(Materials.__file__).resolve()],
                         "readonly bridge must not load a second installed Materials module")
        editor = next(w for w in QtWidgets.QApplication.topLevelWidgets()
                      if w.metaObject().className() == "MatGui::MaterialsEditor" and w.isVisible())
        editor.resize(1200, 750)
        try:
            def guarded(callback):
                def invoke():
                    try:
                        callback()
                    except Exception:
                        errors.append(traceback.format_exc())
                        active = QtWidgets.QApplication.activeModalWidget()
                        if active:
                            active.reject()
                return invoke

            def choose_model():
                dialog = QtWidgets.QApplication.activeModalWidget()
                self.assertEqual(dialog.metaObject().className(), "MatGui::ModelSelect")
                tree = dialog.findChild(QtWidgets.QTreeView, "treeModels")
                index = find_index(tree.model(), MODEL, QtCore.Qt.UserRole)
                self.assertTrue(index.isValid())
                tree.setCurrentIndex(index)
                tree.selectionModel().select(index, QtCore.QItemSelectionModel.ClearAndSelect)
                buttons = dialog.findChild(QtWidgets.QDialogButtonBox, "standardButtons")
                self.assertTrue(buttons.button(QtWidgets.QDialogButtonBox.Ok).isEnabled())
                buttons.button(QtWidgets.QDialogButtonBox.Ok).click()

            QtCore.QTimer.singleShot(0, guarded(choose_model))
            editor.findChild(QtWidgets.QPushButton, "buttonPhysicalAdd").click()
            self.assertFalse(errors, "\n".join(errors))
            physical = editor.findChild(QtWidgets.QTreeView, "treePhysicalProperties")
            tabs = editor.findChild(QtWidgets.QTabWidget, "tabWidget")
            tabs.setCurrentWidget(physical.parentWidget())
            property_index = find_index(physical.model(), "ElasticProperties", QtCore.Qt.UserRole + 1)
            self.assertTrue(property_index.isValid())
            value_index = property_index.sibling(property_index.row(), 1)
            item = physical.model().itemFromIndex(value_index)
            material_pointer = shiboken6.getCppPointer(item)[0]

            def copy_material():
                return bridge.copy_editor_item_material(material_pointer)

            def edit_array():
                dialog = QtWidgets.QApplication.activeModalWidget()
                self.assertEqual(dialog.metaObject().className(), "MatGui::Array2D")
                dialog.resize(1120, 480)
                table = dialog.findChild(QtWidgets.QTableView, "tableView")
                model = table.model()
                self.assertEqual(model.columnCount(), 5)
                self.record["headers"] = [model.headerData(c, QtCore.Qt.Horizontal) for c in range(5)]
                self.record["delegates"] = []

                def edit_cell(column, number):
                    cell = model.index(0, column)
                    table.setCurrentIndex(cell)
                    table.edit(cell)
                    Gui.updateGui()
                    candidates = [w for w in table.findChildren(QtWidgets.QAbstractSpinBox)
                                  if w.isVisible()]
                    self.assertEqual(len(candidates), 1, repr(candidates))
                    spinner = candidates[0]
                    native_class = spinner.metaObject().className()
                    if column == 2:
                        self.assertEqual(native_class, "Gui::DoubleSpinBox")
                        spinner.setValue(number)
                        self.assertEqual(spinner.value(), number)
                    else:
                        self.assertEqual(native_class, "Gui::QuantitySpinBox")
                        self.assertTrue(spinner.setProperty("rawValue", number))
                        self.assertEqual(spinner.property("rawValue"), number)
                    delegate = table.itemDelegateForColumn(column)
                    delegate.setModelData(spinner, model, cell)
                    delegate.closeEditor.emit(spinner, QtWidgets.QAbstractItemDelegate.NoHint)
                    Gui.updateGui()
                    self.record["delegates"].append({"column": column, "class": native_class,
                                                      "authored_value": number})

                # The Float first creates one native row; every Quantity then gets
                # authored through its real native delegate, eliminating unset NaNs.
                for column in (2, 0, 1, 3, 4):
                    edit_cell(column, VALUES[column])
                native_float = model.data(model.index(0, 2), QtCore.Qt.DisplayRole)
                native_material = copy_material()
                array = native_material.getPhysicalValue("ElasticProperties")
                self.assertEqual(array.Rows, 1)
                self.assertEqual(array.Columns, 5)
                self.assertIsInstance(array.TypedArray[0][2], float)
                self.assertEqual(array.TypedArray[0][2], native_float)
                self.assertEqual(native_float, VALUES[2])
                for column in (0, 1, 3, 4):
                    cell = array.TypedArray[0][column]
                    self.assertIsInstance(cell, App.Units.Quantity)
                    self.assertTrue(math.isfinite(cell.Value))
                    self.assertEqual(cell.Value, VALUES[column])
                legacy = [array.getValue(0, 2), array.getRow(0)[2], array.Array[0][2]]
                self.assertTrue(all(isinstance(cell, App.Units.Quantity) for cell in legacy))
                self.assertEqual([cell.Value for cell in legacy], [0.0, 0.0, 0.0])
                self.record["native_raw_float"] = native_float
                self.record["legacy_quantity_zero_compatibility"] = [scalar(cell) for cell in legacy]
                self.record["initial_typed_array"] = array_snapshot(array)

                doc = App.newDocument("NativeGuiArrayFEM")
                docs.append(doc)
                shape = doc.addObject("Part::Feature", "Geometry")
                shape.Shape = Part.makeBox(1, 1, 1)
                shape.ShapeMaterial = native_material
                analysis = ObjectsFem.makeAnalysis(doc)
                material = ObjectsFem.makeMaterialSolid(doc)
                material.References = [(shape, ["Solid1"])]
                analysis.addObject(material)
                mesh = ObjectsFem.makeMeshGmsh(doc)
                mesh.Shape = shape
                tetra = Fem.FemMesh()
                for point in ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)):
                    tetra.addNode(*point)
                tetra.addVolume([1, 2, 3, 4])
                mesh.FemMesh = tetra
                analysis.addObject(mesh)
                doc.recompute()

                def hashes():
                    return {"model_digest": force_accounting._model_digest(analysis, mesh),
                            "quality_input_fingerprint": quality.input_fingerprint(mesh)}

                baseline = hashes()
                retained = [copy_material() for _ in range(32)]
                retained.extend(shape.ShapeMaterial for _ in range(32))
                self.assertEqual(hashes(), baseline)
                for copied in retained:
                    self.assertEqual(array_snapshot(copied.getPhysicalValue("ElasticProperties")),
                                     self.record["initial_typed_array"])
                self.record["readonly_copies"] = len(retained)
                self.record["initial_fem_hashes"] = baseline
                self.record["mutations"] = []
                previous = baseline
                for number in (0.271828, 0.161803):
                    edit_cell(2, number)
                    authored = copy_material()
                    self.assertEqual(authored.getPhysicalValue("ElasticProperties").TypedArray[0][2],
                                     model.data(model.index(0, 2), QtCore.Qt.DisplayRole))
                    shape.ShapeMaterial = authored
                    doc.recompute()
                    current = hashes()
                    self.assertNotEqual(current["model_digest"], previous["model_digest"])
                    self.assertNotEqual(current["quality_input_fingerprint"],
                                        previous["quality_input_fingerprint"])
                    retained.extend(shape.ShapeMaterial for _ in range(16))
                    self.assertEqual(hashes(), current)
                    self.record["mutations"].append({"authored_float": number, "hashes": current})
                    previous = current
                self.record["final_typed_array"] = array_snapshot(shape.ShapeMaterial.getPhysicalValue("ElasticProperties"))
                self.record["fem_hash_read_repeatability"] = True
                self.latest_material = copy_material()
                self.geometry_doc = doc
                dialog.grab().save(str(OUT / "native-array-green.png"))
                dialog.accept()

            QtCore.QTimer.singleShot(0, guarded(edit_array))
            option = QtWidgets.QStyleOptionViewItem()
            event = QtGui.QMouseEvent(QtCore.QEvent.MouseButtonDblClick,
                                     QtCore.QPointF(5, 5), QtCore.Qt.LeftButton,
                                     QtCore.Qt.LeftButton, QtCore.Qt.NoModifier)
            physical.itemDelegateForColumn(1).editorEvent(event, physical.model(), option, value_index)
            self.assertFalse(errors, "\n".join(errors))
            editor.grab().save(str(OUT / "native-material-editor-green.png"))

            if os.environ.get("FREECAD_3SC_CHECK_PERSISTENCE") == "1":
                self.check_private_persistence(docs)
            custody_after = {str(path): sha(path) for path in protected}
            self.record["protected_sha256_after"] = custody_after
            self.assertEqual(custody_after, custody_before)
            self.record["verdict"] = "PASS"
        except Exception:
            self.record["verdict"] = "FAIL"
            self.record["error"] = traceback.format_exc()
            raise
        finally:
            (OUT / "green-witness.json").write_text(json.dumps(self.record, indent=2) + "\n")
            print("NATIVE_MIXED_GREEN " + json.dumps(self.record, sort_keys=True))
            editor.reject()
            for doc in docs:
                if doc.Name in App.listDocuments():
                    App.closeDocument(doc.Name)
            Gui.updateGui()

    def check_private_persistence(self, docs):
        private_library = OUT / "private-material-library"
        private_library.mkdir()
        params = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Material/Resources")
        params.SetBool("UseMaterialsFromCustomDir", True)
        params.SetASCII("CustomMaterialsDir", str(private_library))
        manager = Materials.MaterialManager()
        manager.refresh()
        self.assertTrue(any(name == "Custom" and Path(path).resolve() == private_library.resolve()
                            for name, path, _icon in manager.MaterialLibraries))
        material = self.latest_material
        expected = array_snapshot(material.getPhysicalValue("ElasticProperties"))
        uuid = material.UUID
        manager.save("Custom", material, "/GuiCreated.FCMat", saveInherited=True)
        manager.refresh()
        loaded = manager.getMaterial(uuid)
        self.assertEqual(array_snapshot(loaded.getPhysicalValue("ElasticProperties")), expected)
        doc = self.geometry_doc
        doc.Geometry.ShapeMaterial = loaded
        doc.recompute()
        path = OUT / "GuiCreated.FCStd"
        doc.saveAs(str(path))
        App.closeDocument(doc.Name)
        restored = App.openDocument(str(path))
        docs.append(restored)
        self.assertEqual(restored.Geometry.ShapeMaterial.UUID, uuid)
        self.assertEqual(array_snapshot(restored.Geometry.ShapeMaterial.getPhysicalValue("ElasticProperties")), expected)
        self.record["persistence"] = {
            "assessed": True, "public_manager_save_refresh_exact": True,
            "fcstd_uuid_library_restore_exact": True,
            "cold_process_restore_assessed": False,
            "fcmat_sha256": sha(private_library / "GuiCreated.FCMat"),
            "fcstd_sha256": sha(path), "expected_typed_array": expected,
        }
