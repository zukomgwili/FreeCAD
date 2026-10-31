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
        hybrid = data["schema"] == "CCX_BEAM_SECTION_V3"
        coupled = hybrid or data["schema"] == "CCX_BEAM_SECTION_V2"
        dialog.resize(1200, 900 if coupled else 650)
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
                "Outward element-end actions about the native section-map centroid."
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
        if hybrid:
            table.verticalHeader().setDefaultSectionSize(24)
        layout.addWidget(table, 2 if hybrid else 3)
        tables = [table]
        if coupled:
            explanation = QtWidgets.QLabel(
                "Actions use original global axes and moments about the global origin. "
                "Beam guide and solid fixed are physical supports; spring ends and moving "
                "RBE sides are internal transfer, not additional external ground supports."
                if hybrid
                else "Source, spring and support actions act on the structural model in original "
                "global axes. Their moments are about the global origin."
            )
            explanation.setWordWrap(True)
            layout.addWidget(explanation)
            actions_table = QtWidgets.QTableWidget()
            actions_table.setObjectName("NativeCoupledBeamActions")
            actions_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
            actions_table.setAlternatingRowColors(True)
            if hybrid:
                actions_table.verticalHeader().setDefaultSectionSize(24)
            layout.addWidget(actions_table, 3 if hybrid else 2)
            explanation = QtWidgets.QLabel(
                "Support DOFs: TRANSLATION is force (N); ANGLE is a physical couple (N*mm). "
                "ALGEBRAIC is a native equation value excluded from the physical wrench; "
                "it may be nonzero. Equation-node coordinates are not physical force locations."
            )
            explanation.setWordWrap(True)
            layout.addWidget(explanation)
            support_table = QtWidgets.QTableWidget()
            support_table.setObjectName("NativeCoupledBeamSupportDofs")
            support_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
            support_table.setAlternatingRowColors(True)
            if hybrid:
                support_table.verticalHeader().setDefaultSectionSize(24)
            layout.addWidget(support_table, 3)
            tables.extend((actions_table, support_table))
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
                for displayed in tables:
                    displayed.clearContents()
                    displayed.setRowCount(0)
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

        def fill_table(displayed, headers, rows):
            displayed.clear()
            displayed.setColumnCount(len(headers))
            displayed.setHorizontalHeaderLabels(headers)
            displayed.setRowCount(len(rows))
            for i, values in enumerate(rows):
                for j, value in enumerate(values):
                    text = format(value, ".10g") if isinstance(value, float) else str(value)
                    displayed.setItem(i, j, QtWidgets.QTableWidgetItem(text))
            displayed.resizeColumnsToContents()

        def show_coupled_actions(frame):
            actions = frame["native_actions"]
            headers = [
                "Action",
                "Owner",
                "Node / region" if hybrid else "Node",
                "Spring element",
                "Original position (mm)",
            ]
            headers += [f"F{axis} (N)" for axis in "xyz"]
            headers += [f"M{axis} about origin (N*mm)" for axis in "xyz"]
            rows = []
            if hybrid:
                spring = actions["spring"]
                first, second = spring["ends"]
                port = actions["port"]
                catalogue = (
                    (
                        "source",
                        actions["source"]["owner"],
                        actions["source"]["node"],
                        "—",
                        actions["source"]["position"],
                        actions["source"],
                    ),
                    (
                        "beam guide",
                        actions["support"]["owner"],
                        actions["support"]["node"],
                        "—",
                        actions["support"]["position"],
                        actions["support"],
                    ),
                    (
                        "solid fixed",
                        actions["solid_support"]["owner"],
                        actions["solid_support"]["nodes"],
                        "—",
                        "—",
                        actions["solid_support"],
                    ),
                    (
                        "spring on beam",
                        spring["owner"],
                        first["node"],
                        spring["element"],
                        first["position"],
                        first,
                    ),
                    (
                        "spring on reference",
                        spring["owner"],
                        second["node"],
                        spring["element"],
                        second["position"],
                        second,
                    ),
                    (
                        "RBE receiving",
                        port["owner"],
                        port["receiving_nodes"],
                        "—",
                        "—",
                        port["receiving_action"],
                    ),
                    (
                        "RBE reference",
                        port["owner"],
                        port["reference_node"],
                        "—",
                        source["coupling"]["port"]["position"],
                        port["reference_action"],
                    ),
                )
                for name, owner, nodes, element, position, row in catalogue:
                    rows.append(
                        [name, owner, nodes, element, position]
                        + row["force_global"]
                        + row["moment_origin"]
                    )
            else:
                for name in ("source", "spring", "support"):
                    row = actions[name]
                    rows.append(
                        [name, row["owner"], row["node"], row.get("element", "—"), row["position"]]
                        + row["force_global"]
                        + row["moment_origin"]
                    )
            fill_table(actions_table, headers, rows)
            headers = [
                "Role",
                "Owner",
                "Node",
                "DOF",
                "Original node",
                "Original DOF",
                "Native value",
                "Units",
                "Axis",
                "Physical contribution",
            ]
            roles = {
                "TRANSLATION": ("N", "Force"),
                "ANGLE": ("N*mm", "Couple"),
                "ALGEBRAIC": ("Native equation value", "Excluded"),
            }
            terms = [(actions["support"]["owner"], row) for row in actions["support"]["spcs"]]
            if hybrid:
                terms.extend(
                    (actions["solid_support"]["owner"], row)
                    for row in actions["solid_support"]["spcs"]
                )
                terms.extend((port["owner"], row) for row in port["algebraic_spcs"])
            rows = []
            for owner, row in terms:
                units, contribution = roles[row["role"]]
                rows.append(
                    [
                        row["role"],
                        owner,
                        row["node"],
                        row["direction"],
                        row.get("original_node", row.get("receiving_node", row["node"])),
                        row.get("original_direction", row["direction"]),
                        row["value"],
                        units,
                        row.get("axis", "—"),
                        contribution,
                    ]
                )
            fill_table(support_table, headers, rows)

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
            if coupled:
                show_coupled_actions(data["frames"][index])

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
