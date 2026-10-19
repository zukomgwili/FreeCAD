"""Actual stock native material Array2D dialog; no material save/reload."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import traceback
import unittest

import FreeCAD as App
import FreeCADGui as Gui
import Materials
from PySide import QtCore, QtGui, QtWidgets
from PySide6 import QtTest
import shiboken6


ROOT = Path(__file__).resolve().parent
OUT = Path(os.environ["FREECAD_3SC_OUTPUT"])
MODEL = "2afbba4b-55c0-4c4a-a6dc-4f5716cc5571"


def find_index(model, target, role=QtCore.Qt.DisplayRole, parent=QtCore.QModelIndex()):
    for row in range(model.rowCount(parent)):
        index = model.index(row, 0, parent)
        if index.data(role) == target:
            return index
        result = find_index(model, target, role, index)
        if result.isValid():
            return result
    return QtCore.QModelIndex()


class NativeMixedGuiWitness(unittest.TestCase):
    def test_stock_native_float_is_not_lost_by_python_read(self):
        self.errors = []
        self.record = {
            "runtime": App.Version(),
            "stock_model_uuid": MODEL,
            "property": "ElasticProperties",
            "persistence_used": False,
            "bridge": "readonly QStandardItem native Material copy; no values replaced",
            "bridge_sha256": hashlib.sha256((ROOT / "GuiMaterialReadBridge.so").read_bytes()).hexdigest(),
        }
        bridge = ctypes.PyDLL(str(ROOT / "GuiMaterialReadBridge.so"))
        bridge.copy_editor_item_material.argtypes = [ctypes.c_void_p]
        bridge.copy_editor_item_material.restype = ctypes.py_object
        Gui.activateWorkbench("MaterialWorkbench")
        Gui.runCommand("Material_Edit", 0)
        Gui.updateGui()
        editor = next(w for w in QtWidgets.QApplication.topLevelWidgets()
                      if w.objectName() == "MatGui::MaterialsEditor" and w.isVisible())
        editor.resize(1100, 750)
        try:
            def guarded(callback):
                def invoke():
                    try:
                        callback()
                    except Exception:
                        self.errors.append(traceback.format_exc())
                        active = QtWidgets.QApplication.activeModalWidget()
                        if active:
                            active.reject()
                return invoke

            def choose_model():
                select = QtWidgets.QApplication.activeModalWidget()
                self.assertEqual(select.objectName(), "MatGui::ModelSelect")
                tree = select.findChild(QtWidgets.QTreeView, "treeModels")
                index = find_index(tree.model(), MODEL, QtCore.Qt.UserRole)
                self.assertTrue(index.isValid(), "stock model absent from native selector")
                tree.setCurrentIndex(index)
                tree.selectionModel().select(index, QtCore.QItemSelectionModel.ClearAndSelect)
                buttons = select.findChild(QtWidgets.QDialogButtonBox, "standardButtons")
                self.assertTrue(buttons.button(QtWidgets.QDialogButtonBox.Ok).isEnabled())
                buttons.button(QtWidgets.QDialogButtonBox.Ok).click()

            QtCore.QTimer.singleShot(0, guarded(choose_model))
            editor.findChild(QtWidgets.QPushButton, "buttonPhysicalAdd").click()
            self.assertFalse(self.errors, "\n".join(self.errors))
            tabs = editor.findChild(QtWidgets.QTabWidget, "tabWidget")
            physical = editor.findChild(QtWidgets.QTreeView, "treePhysicalProperties")
            tabs.setCurrentWidget(physical.parentWidget())
            index = find_index(physical.model(), "ElasticProperties", QtCore.Qt.UserRole + 1)
            self.assertTrue(index.isValid(), "native physical property absent")
            value_index = index.sibling(index.row(), 1)
            item = physical.model().itemFromIndex(value_index)
            material_pointer = shiboken6.getCppPointer(item)[0]
            self.record["property_model_class"] = physical.model().metaObject().className()
            editor.grab().save(str(OUT / "native-material-editor.png"))

            def edit_array():
                array_dialog = QtWidgets.QApplication.activeModalWidget()
                self.assertEqual(array_dialog.objectName(), "MatGui::Array2D")
                table = array_dialog.findChild(QtWidgets.QTableView, "tableView")
                model = table.model()
                self.record["table_model_class"] = model.metaObject().className()
                self.record["headers"] = [model.headerData(c, QtCore.Qt.Horizontal)
                                           for c in range(model.columnCount())]
                self.assertEqual(model.columnCount(), 5)
                cell = model.index(0, 2)
                table.setCurrentIndex(cell)
                table.edit(cell)
                Gui.updateGui()
                inputs = [w for w in table.findChildren(QtWidgets.QDoubleSpinBox) if w.isVisible()]
                self.assertEqual(len(inputs), 1, repr(inputs))
                spinner = inputs[0]
                spinner.setValue(0.314159)
                self.record["float_editor_class"] = spinner.metaObject().className()
                self.record["float_editor_value"] = spinner.value()
                delegate = table.itemDelegateForColumn(2)
                delegate.setModelData(spinner, model, cell)
                self.record["native_gui_raw_float"] = model.data(cell, QtCore.Qt.DisplayRole)
                self.record["native_gui_raw_type"] = type(self.record["native_gui_raw_float"]).__name__
                self.record["table_rows_including_new_row"] = model.rowCount()
                # A native MaterialPy copy preserves the exact GUI-owned array in memory.
                copied_material = bridge.copy_editor_item_material(material_pointer)
                value = copied_material.getPhysicalValue("ElasticProperties")
                self.record["python_value_class"] = type(value).__name__
                self.record["rows"] = value.Rows
                self.record["columns"] = value.Columns
                self.record["python_getValue_float"] = value.getValue(0, 2).Value
                self.record["python_getRow_float"] = value.getRow(0)[2].Value
                self.record["python_Array_float"] = value.Array[0][2].Value
                self.record["material_models"] = copied_material.PhysicalModels
                array_dialog.grab().save(str(OUT / "native-array-edited.png"))
                (OUT / "witness.json").write_text(json.dumps(self.record, indent=2) + "\n")
                print("NATIVE_MIXED_WITNESS " + json.dumps(self.record, sort_keys=True))
                array_dialog.accept()

            QtCore.QTimer.singleShot(0, guarded(edit_array))
            # Native delegate dispatches the real double-click to its stock modal editor.
            option = QtWidgets.QStyleOptionViewItem()
            event = QtGui.QMouseEvent(QtCore.QEvent.MouseButtonDblClick,
                                     QtCore.QPointF(5, 5), QtCore.Qt.LeftButton,
                                     QtCore.Qt.LeftButton, QtCore.Qt.NoModifier)
            physical.itemDelegateForColumn(1).editorEvent(event, physical.model(), option, value_index)
            self.assertFalse(self.errors, "\n".join(self.errors))
            self.assertEqual(self.record["native_gui_raw_float"], 0.314159)
            self.assertEqual(self.record["python_getValue_float"],
                             self.record["native_gui_raw_float"],
                             "native GUI Float cell is silently read as zero by Python")
        finally:
            editor.reject()
            Gui.updateGui()
