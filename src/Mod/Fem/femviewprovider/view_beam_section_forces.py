# SPDX-License-Identifier: LGPL-2.1-or-later
"""Inspect literal native beam-end actions without force or stress recovery."""

import json

from PySide import QtCore
from PySide import QtWidgets

import FreeCADGui as Gui
from femviewprovider.view_base_femobject import VPBaseFemObject


class VPBeamSectionForces(VPBaseFemObject):
    def getIcon(self):
        return ":/icons/FEM_PostFilterDataAtPoint.svg"

    def doubleClicked(self, vobj):
        self.inspect(vobj)
        return True

    def setupContextMenu(self, vobj, menu):
        action = menu.addAction("Inspect native beam-end actions")
        action.triggered.connect(lambda _checked=False: self.inspect(vobj))

    def updateData(self, obj, prop):
        for withdraw in tuple(getattr(self, "_inspectors", ())):
            withdraw("The result changed; close and reopen the inspector")

    def onDelete(self, vobj, subelements):
        self.updateData(vobj.Object, "deleted")
        return True

    def inspect(self, vobj):
        obj = vobj.Object
        historical = not obj.Status.startswith("Current")
        try:
            data = obj.Proxy.getSectionForces(obj, historical=historical)
        except ValueError as error:
            QtWidgets.QMessageBox.warning(None, "Native beam-end actions unavailable", str(error))
            return

        dialog = QtWidgets.QDialog(Gui.getMainWindow())
        dialog.setObjectName("NativeBeamSectionInspector")
        dialog.setWindowTitle("Native beam-end forces and moments — " + obj.Label)
        dialog.resize(1200, 650)
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.addWidget(
            QtWidgets.QLabel(
                "Historical saved output; rerun for Current data"
                if historical
                else "Current native output — last validated snapshot"
            )
        )
        layout.addWidget(
            QtWidgets.QLabel(
                "Units: forces N; moments N*mm; positions mm. "
                "Outward element-end actions about the current section centroid."
            )
        )
        source = data["provenance"]
        layout.addWidget(QtWidgets.QLabel("Case: " + json.dumps(source["case"], sort_keys=True)))
        layout.addWidget(
            QtWidgets.QLabel(
                "Literal native face axes e1, e2, normal; the first end basis may be left-handed. "
                "Expanded-node stress averaging remains native."
            )
        )
        frames = QtWidgets.QComboBox()
        frames.setObjectName("NativeBeamSectionFrames")
        layout.addWidget(frames)
        table = QtWidgets.QTableWidget()
        table.setObjectName("NativeBeamSectionSamples")
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        layout.addWidget(table)
        status = QtWidgets.QLabel("Saved solver observations; not design acceptance")
        status.setObjectName("NativeBeamSectionAvailability")
        layout.addWidget(status)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        withdrawn = False

        def withdraw(reason):
            nonlocal withdrawn
            if not withdrawn:
                withdrawn = True
                table.clearContents()
                table.setRowCount(0)
                frames.setEnabled(False)
                status.setText("Unavailable: " + reason)

        def validate():
            if withdrawn:
                return
            try:
                current = obj.Proxy.getSectionForces(obj, historical=historical)
                if current != data:
                    withdraw("The saved output changed; reopen the inspector")
            except (ValueError, RuntimeError, ReferenceError) as error:
                withdraw(str(error))

        owners = {row["element"]: row for row in source["elements"]}
        columns = ["Element", "Node", "End", "Section", "Material"]
        columns += [f"F{axis} (N)" for axis in "xyz"]
        columns += [f"M{axis} (N*mm)" for axis in "xyz"]
        channels = ("shear1", "shear2", "axial", "torque", "bend2", "bend1")
        columns += [name + (" (N)" if i < 3 else " (N*mm)") for i, name in enumerate(channels)]
        columns += ["e1", "e2", "normal", "Centroid (mm)"]

        def show_frame(index):
            validate()
            if withdrawn or index < 0:
                return
            table.clear()
            table.setColumnCount(len(columns))
            table.setHorizontalHeaderLabels(columns)
            samples = data["frames"][index]["samples"]
            table.setRowCount(len(samples))
            for i, row in enumerate(samples):
                owner = owners[row["element"]]
                values = [
                    row["element"],
                    row["node"],
                    row["end"],
                    owner["section"],
                    owner["material"],
                ]
                values += row["force_global"] + row["moment_global"]
                values += [row["native_channels"][name] for name in channels]
                values += [row["basis"][name] for name in ("e1", "e2", "normal")]
                values += [row["position"]]
                for j, value in enumerate(values):
                    text = format(value, ".10g") if isinstance(value, float) else str(value)
                    table.setItem(i, j, QtWidgets.QTableWidgetItem(text))
            table.resizeColumnsToContents()

        for frame in data["frames"]:
            frames.addItem(
                f"Step {frame['step']}, increment {frame['increment']}, "
                f"FRD dataset {frame['frame']}, time {frame['time']}"
            )
        frames.currentIndexChanged.connect(show_frame)
        timer = QtCore.QTimer(dialog)
        timer.timeout.connect(validate)
        timer.start(500)
        if not hasattr(self, "_inspectors"):
            self._inspectors = []
        self._inspectors.append(withdraw)
        try:
            frames.setCurrentIndex(len(data["frames"]) - 1)
            show_frame(frames.currentIndex())
            dialog.exec()
        finally:
            timer.stop()
            self._inspectors.remove(withdraw)
            dialog.deleteLater()
