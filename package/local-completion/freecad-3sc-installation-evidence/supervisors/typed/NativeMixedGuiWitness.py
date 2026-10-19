"""Unchanged native tree lookup, extracted without any historical bridge/test."""
from PySide import QtCore


def find_index(model, target, role=QtCore.Qt.DisplayRole, parent=QtCore.QModelIndex()):
    for row in range(model.rowCount(parent)):
        index = model.index(row, 0, parent)
        if index.data(role) == target:
            return index
        result = find_index(model, target, role, index)
        if result.isValid():
            return result
    return QtCore.QModelIndex()
