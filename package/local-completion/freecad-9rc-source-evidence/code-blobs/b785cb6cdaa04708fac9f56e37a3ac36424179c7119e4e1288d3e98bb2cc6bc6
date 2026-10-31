# SPDX-License-Identifier: LGPL-2.1-or-later
"""Inspect coupled native actions and withdraw both live observation windows."""

from collections import Counter
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import FreeCAD as App

from femtest.app.beam_contact_fixtures import make_contact_series
from femtest.gui import test_beam_coupling as coupling_gui
from femtools.beam_section_forces import require_capability
from femtools.ccxtools import FemToolsCcx
from femtools.force_accounting import solver_binary

if App.GuiUp:
    from PySide import QtCore
    from PySide import QtWidgets

    import FreeCADGui as Gui
    import FemGui


@unittest.skipUnless(App.GuiUp, "A native FreeCAD GUI is required")
class TestBeamContactCouplingGui(unittest.TestCase):
    # Import helpers through the module so unittest does not rediscover V2.
    _drain_deferred_deletes = staticmethod(coupling_gui.TestBeamCouplingGui._drain_deferred_deletes)
    _headers = staticmethod(coupling_gui.TestBeamCouplingGui._headers)
    _text = staticmethod(coupling_gui.TestBeamCouplingGui._text)

    def setUp(self):
        previous = App.activeDocument()
        self.previous_document = previous.Name if previous is not None else None
        self.previous_analysis = FemGui.getActiveAnalysis()
        workbench = Gui.activeWorkbench()
        self.previous_workbench = workbench.name() if workbench is not None else None
        window = Gui.getMainWindow()
        self.previous_window_visible = window.isVisible()
        self.previous_window_state = window.windowState()
        self.mdi = window.findChild(QtWidgets.QMdiArea)
        self.previous_mdi_window = self.mdi.activeSubWindow() if self.mdi is not None else None
        self.previous_mdi_state = (
            self.previous_mdi_window.windowState() if self.previous_mdi_window is not None else None
        )
        self.general = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/General")
        self.overwrite_key = "OverwriteSolverWorkingDirectory"
        self.overwrite_value = self.general.GetBool(self.overwrite_key, True)
        self.overwrite_present = self.general.GetBool(
            self.overwrite_key, True
        ) == self.general.GetBool(self.overwrite_key, False)
        self.keep_key = "KeepResultsOnReRun"
        self.keep_value = self.general.GetBool(self.keep_key, False)
        self.keep_present = self.general.GetBool(self.keep_key, True) == self.general.GetBool(
            self.keep_key, False
        )
        self.ccx_preferences = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/Ccx")
        self.cpu_key = "AnalysisNumCPUs"
        self.cpu_value = self.ccx_preferences.GetInt(self.cpu_key, 1)
        self.cpu_present = self.ccx_preferences.GetInt(
            self.cpu_key, 1
        ) == self.ccx_preferences.GetInt(self.cpu_key, 2)
        self.doc = None
        self.temporary = None
        self.addCleanup(self._restore_session)
        self._drain_deferred_deletes()
        Gui.showMainWindow()
        window.showNormal()
        Gui.activateWorkbench("FemWorkbench")
        self.general.SetBool(self.overwrite_key, False)
        self.general.SetBool(self.keep_key, False)
        self.ccx_preferences.SetInt(self.cpu_key, 2)
        explicit = os.environ.get("R9_TEST_SOLVER")
        selected = explicit or solver_binary(SimpleNamespace(NativeAccountingSolver=""))
        try:
            require_capability(selected, schema="CCX_BEAM_SECTION_V4")
        except (OSError, ValueError) as error:
            if explicit:
                raise
            self.skipTest("Qualified native beam/contact observer required: " + str(error))
        retained = os.environ.get("R9_WITNESS_ROOT")
        if retained:
            self.directory = Path(retained) / self._testMethodName
            self.directory.mkdir(parents=True)
        else:
            self.temporary = tempfile.TemporaryDirectory(prefix="freecad-beam-contact-gui-")
            self.directory = Path(self.temporary.name)
        self.doc = App.newDocument("BeamContactCouplingGui")
        self.model = make_contact_series(self.doc, friction=False)
        self.model.solver.NativeAccountingSolver = selected
        self.model.solver.WorkingDir = str(self.directory)
        FemGui.setActiveAnalysis(self.model.analysis)
        self.doc.recompute()
        view = Gui.getDocument(self.doc.Name).activeView()
        view.viewAxonometric()
        view.fitAll()
        Gui.updateGui()

    def _restore_session(self):
        try:
            coupling_gui.TestBeamCouplingGui._restore_session(self)
        finally:
            if self.keep_present:
                self.general.SetBool(self.keep_key, self.keep_value)
            else:
                self.general.RemBool(self.keep_key)

    def _mechanical_roles(self, beam, data):
        mechanical = [
            obj for obj in self.model.analysis.Group if obj.isDerivedFrom("Fem::FemResultObject")
        ]
        self.assertEqual(len(mechanical), 3)
        solids = {
            obj.NativeSolidOwner.Name: obj for obj in mechanical if hasattr(obj, "NativeSolidOwner")
        }
        self.assertEqual(set(solids), {self.model.solid.Name, self.model.backing.Name})
        mixed = next(obj for obj in mechanical if not hasattr(obj, "NativeSolidOwner"))
        self.assertEqual(
            set(mixed.NativeSourceNodeNumbers),
            set(self.model.beam_nodes + self.model.all_solid_nodes),
        )
        self.assertEqual(
            set(mixed.NativeSourceElementNumbers),
            set(self.model.beam_elements + self.model.all_solid_elements),
        )
        self.assertEqual((mixed.Mesh.FemMesh.NodeCount, mixed.Mesh.FemMesh.EdgeCount), (17, 2))
        self.assertEqual((mixed.Mesh.FemMesh.VolumeCount, mixed.Mesh.FemMesh.FaceCount), (6, 0))
        stress_properties = (
            "NodeStressXX",
            "NodeStressYY",
            "NodeStressZZ",
            "NodeStressXY",
            "NodeStressXZ",
            "NodeStressYZ",
        )
        for name in (
            *stress_properties,
            "vonMises",
            "PrincipalMax",
            "PrincipalMed",
            "PrincipalMin",
        ):
            self.assertFalse(getattr(mixed, name), name)
        for owner, nodes, elements in (
            (self.model.solid, self.model.solid_nodes, self.model.solid_elements),
            (self.model.backing, self.model.backing_nodes, self.model.backing_elements),
        ):
            result = solids[owner.Name]
            self.assertEqual(result.NativeSolidOwner, owner)
            self.assertEqual(set(result.NativeSourceNodeNumbers), set(nodes))
            self.assertEqual(set(result.NativeSourceElementNumbers), set(elements))
            self.assertEqual((result.Mesh.FemMesh.NodeCount, result.Mesh.FemMesh.EdgeCount), (6, 0))
            self.assertEqual(
                (result.Mesh.FemMesh.VolumeCount, result.Mesh.FemMesh.FaceCount), (3, 0)
            )
            for name in stress_properties:
                self.assertEqual(len(getattr(result, name)), 6)
                # Mechanical result components use MPa, independently of
                # the N and N*mm beam-end action channels.
                for value in getattr(result, name):
                    self.assertAlmostEqual(
                        value, -4 / 3 if name == "NodeStressXX" else 0, delta=0.0001
                    )
        self.assertTrue(
            set(solids[self.model.solid.Name].NativeSourceNodeNumbers).isdisjoint(
                solids[self.model.backing.Name].NativeSourceNodeNumbers
            )
        )
        self.assertEqual(len({result.Mesh.Name for result in mechanical}), 3)
        for result in mechanical:
            self.assertEqual(result.NativeBeamSource, beam)
            self.assertEqual(result.NativeSourceFileHash, data["provenance"]["frd"]["sha256"])
            self.assertEqual(
                json.loads(result.NativeSourceFrame)["case"], data["provenance"]["case"]
            )
            self.assertEqual(len(result.DisplacementVectors), len(result.NativeSourceNodeNumbers))
        return {"mixed": mixed, **solids}

    def _pipeline_roles(self, mechanical):
        if "BUILD_FEM_VTK" not in App.__cmake__:
            return {}
        pipelines = self.model.analysis.getObjectsOfType("Fem::FemPostPipeline")
        self.assertEqual(
            len(pipelines), 3, "Mixed and both solid owners require distinct pipelines"
        )
        by_name = {pipeline.Name: pipeline for pipeline in pipelines}
        expected = {role: "Pipeline_" + result.Name for role, result in mechanical.items()}
        self.assertEqual(set(by_name), set(expected.values()))
        datasets = []
        stress_names = (
            "Stress xx component",
            "Stress yy component",
            "Stress zz component",
            "Stress xy component",
            "Stress xz component",
            "Stress yz component",
            "von Mises Stress",
            "Major Principal Stress",
            "Intermediate Principal Stress",
            "Minor Principal Stress",
        )
        bounds = {
            "mixed": (-50, 40, 12, 22, -28, -13),
            self.model.solid.Name: (-30, -10, 12, 22, -28, -13),
            self.model.backing.Name: (-50, -30, 12, 22, -28, -13),
        }
        for role, name in expected.items():
            pipeline = by_name[name]
            native = pipeline.Data
            datasets.append(native.GetAddressAsString(""))
            count = 17 if role == "mixed" else 6
            self.assertEqual(native.GetNumberOfPoints(), count)
            self.assertEqual(tuple(native.GetBounds()), bounds[role])
            # The stock native VTK exporter shows the highest element
            # dimension; the mixed mechanical mesh retains its two beams.
            self.assertEqual(native.GetNumberOfCells(), 6 if role == "mixed" else 3)
            self.assertTrue(
                all(native.GetCellType(i) == 10 for i in range(native.GetNumberOfCells()))
            )
            points = native.GetPointData()
            vector = points.GetArray("Displacement")
            self.assertIsNotNone(vector)
            self.assertEqual(vector.GetNumberOfComponents(), 3)
            self.assertEqual(vector.GetNumberOfTuples(), count)
            if role == "mixed":
                for field in stress_names:
                    self.assertIsNone(points.GetArray(field), field)
                continue
            for field in stress_names[:6]:
                values = points.GetArray(field)
                self.assertIsNotNone(values, field)
                self.assertEqual(values.GetNumberOfComponents(), 1)
                self.assertEqual(values.GetNumberOfTuples(), 6)
                # The native post pipeline converts mechanical MPa to Pa.
                for index in range(6):
                    self.assertAlmostEqual(
                        values.GetTuple1(index),
                        -1e6 * 4 / 3 if field == "Stress xx component" else 0,
                        delta=100,
                    )
        self.assertEqual(len(set(datasets)), 3, "Each result role needs its own actual VTK source")
        return expected

    def _assert_actions(self, dialog, data):
        samples = dialog.findChild(QtWidgets.QTableWidget, "NativeBeamSectionSamples")
        actions = dialog.findChild(QtWidgets.QTableWidget, "NativeCoupledBeamActions")
        supports = dialog.findChild(QtWidgets.QTableWidget, "NativeCoupledBeamSupportDofs")
        self.assertIsNotNone(actions, "Native beam/contact action table is missing")
        self.assertIsNotNone(supports, "Native physical/algebraic DOF table is missing")
        self.assertEqual((samples.rowCount(), actions.rowCount(), supports.rowCount()), (4, 10, 31))
        for table in (samples, actions, supports):
            self.assertEqual(table.editTriggers(), QtWidgets.QAbstractItemView.NoEditTriggers)
        labels = " ".join(label.text() for label in dialog.findChildren(QtWidgets.QLabel))
        for text in ("global origin", "physical supports", "internal", "excluded", "separate"):
            self.assertIn(text, labels.lower())
        self.assertIn("N*mm", labels)
        pair = dialog.findChild(QtWidgets.QLabel, "NativeBeamContactPair")
        self.assertIsNotNone(pair)
        self.assertIn("step, increment and time", pair.text())
        self.assertIn("FRD stress dataset identity", pair.text())
        headers = self._headers(actions)
        for header in ("Solid owner", "Contact side", "Fx (N)", "Mx about origin (N*mm)"):
            self.assertIn(header, headers)
        rows = {
            self._text(actions, index, headers.index("Action")): index
            for index in range(actions.rowCount())
        }
        expected = (
            ("source", self.model.force.Name, "—", "—", -100),
            ("beam guide", self.model.stabilizer.Name, "—", "—", 0),
            ("solid fixed", self.model.fixed.Name, self.model.backing.Name, "—", 100),
            ("spring on beam", self.model.connector.Name, "—", "—", 100),
            ("spring on reference", self.model.connector.Name, "—", "—", -100),
            ("RBE receiving", self.model.rbe.Name, self.model.solid.Name, "—", -100),
            ("RBE reference", self.model.rbe.Name, self.model.solid.Name, "—", 100),
            ("RBE physical guide", self.model.rbe.Name, self.model.solid.Name, "—", 0),
            ("contact on SLAVE", self.model.contact.Name, self.model.solid.Name, "SLAVE", 100),
            ("contact on MASTER", self.model.contact.Name, self.model.backing.Name, "MASTER", -100),
        )
        self.assertEqual(set(rows), {row[0] for row in expected})
        for name, owner, solid_owner, side, force in expected:
            row = rows[name]
            for header, value in (
                ("Owner", owner),
                ("Solid owner", solid_owner),
                ("Contact side", side),
            ):
                self.assertEqual(self._text(actions, row, headers.index(header)), value)
            # These independent frozen statics also check the displayed signs.
            for axis, value in zip("xyz", (force, 0, 0)):
                self.assertAlmostEqual(
                    float(self._text(actions, row, headers.index(f"F{axis} (N)"))),
                    value,
                    delta=0.01,
                )
            for axis, value in zip("xyz", (0, -23 * force, -17 * force)):
                self.assertAlmostEqual(
                    float(self._text(actions, row, headers.index(f"M{axis} about origin (N*mm)"))),
                    value,
                    delta=1,
                )
        guide = data["frames"][-1]["native_actions"]["port_guide"]
        region = self._text(actions, rows["RBE physical guide"], headers.index("Node / region"))
        for node in (guide["reference_node"], guide["rotation_node"]):
            self.assertIn(str(node), region)
        headers = self._headers(supports)
        roles, owners, port_roles = Counter(), Counter(), Counter()
        for row in range(supports.rowCount()):
            role = self._text(supports, row, headers.index("Role"))
            owner = self._text(supports, row, headers.index("Owner"))
            roles[role] += 1
            owners[owner] += 1
            if owner == self.model.rbe.Name:
                port_roles[role] += 1
            units = self._text(supports, row, headers.index("Units"))
            contribution = self._text(supports, row, headers.index("Physical contribution"))
            if role == "ALGEBRAIC":
                self.assertEqual(contribution, "Excluded")
                self.assertNotIn(units, ("N", "N*mm"))
            else:
                self.assertEqual(units, "N" if role == "TRANSLATION" else "N*mm")
                self.assertEqual(contribution, "Force" if role == "TRANSLATION" else "Couple")
        self.assertEqual(roles, {"TRANSLATION": 13, "ANGLE": 6, "ALGEBRAIC": 12})
        self.assertEqual(
            owners,
            {self.model.stabilizer.Name: 8, self.model.fixed.Name: 9, self.model.rbe.Name: 14},
        )
        self.assertEqual(port_roles, {"TRANSLATION": 2, "ANGLE": 3, "ALGEBRAIC": 9})
        return samples, actions, supports

    def test_contact_sides_and_physical_guide_withdraw_with_the_paired_observation(self):
        fea = FemToolsCcx(analysis=self.model.analysis, solver=self.model.solver)
        fea.update_objects()
        fea.setup_working_dir(str(self.directory))
        self.assertFalse(fea.check_prerequisites())
        self.assertFalse(fea.write_inp_file())
        self.assertEqual(fea.ccx_run(), 0, fea.ccx_stdout + fea.ccx_stderr)
        fea.load_results()
        results = {
            obj.Proxy.Type: obj
            for obj in self.model.analysis.Group
            if getattr(getattr(obj, "Proxy", None), "Type", "")
            in ("Fem::BeamSectionForceResult", "Fem::ContactStateResult")
        }
        beam = results["Fem::BeamSectionForceResult"]
        contact = results["Fem::ContactStateResult"]
        data = beam.Proxy.getSectionForces(beam)
        local = contact.Proxy.getContactStates(contact)
        self.assertEqual(data["schema"], "CCX_BEAM_SECTION_V4")
        self.assertEqual(
            [(row["step"], row["increment"], row["time"]) for row in data["frames"]],
            [(row["step"], row["increment"], row["time"]) for row in local["frames"]],
        )
        mechanical = self._mechanical_roles(beam, data)
        roles = self._pipeline_roles(mechanical)
        self.assertFalse(self.general.GetBool(self.keep_key, True))
        fea.load_results()
        self.assertEqual(self._pipeline_roles(mechanical), roles)
        self.assertEqual(beam.Proxy.getSectionForces(beam), data)
        self.assertEqual(contact.Proxy.getContactStates(contact), local)
        literals = beam.SectionData, contact.ContactData
        existing = {id(dialog) for dialog in QtWidgets.QApplication.topLevelWidgets()}
        inspected, timers = {}, []

        def own_dialogs(name=None):
            return [
                dialog
                for dialog in QtWidgets.QApplication.topLevelWidgets()
                if isinstance(dialog, QtWidgets.QDialog)
                and id(dialog) not in existing
                and dialog.objectName()
                in ("NativeBeamSectionInspector", "NativeContactStateInspector")
                and (name is None or dialog.objectName() == name)
            ]

        def fail_callback(error):
            inspected.setdefault("error", error)
            for dialog in own_dialogs():
                dialog.reject()

        def check_withdrawal():
            try:
                for table in inspected["tables"]:
                    self.assertEqual(table.rowCount(), 0, table.objectName())
                for name, prefix in (
                    ("NativeBeamSectionInspector", "NativeBeamSection"),
                    ("NativeContactStateInspector", "NativeContactState"),
                ):
                    dialog = own_dialogs(name)[0]
                    frames = dialog.findChild(QtWidgets.QComboBox, prefix + "Frames")
                    availability = dialog.findChild(QtWidgets.QLabel, prefix + "Availability")
                    self.assertFalse(frames.isEnabled())
                    self.assertEqual(frames.currentIndex(), inspected[prefix + "Frame"])
                    self.assertTrue(
                        availability.text().startswith("Unavailable:"), availability.text()
                    )
                    if os.environ.get("R9_WITNESS_ROOT"):
                        self.assertTrue(
                            dialog.grab().save(str(self.directory / (name + "-withdrawn.png")))
                        )
                for result in (beam, contact):
                    self.assertFalse(result.CompletedRun)
                    self.assertFalse(result.Status.startswith("Current"), result.Status)
                self.assertEqual((beam.SectionData, contact.ContactData), literals)
                inspected["withdrawn"] = True
                for dialog in reversed(own_dialogs()):
                    dialog.accept()
            except Exception as error:
                fail_callback(error)

        def inspect_contact():
            try:
                dialogs = own_dialogs("NativeContactStateInspector")
                self.assertEqual(len(dialogs), 1)
                dialog = dialogs[0]
                table = dialog.findChild(QtWidgets.QTableWidget, "NativeContactStateSamples")
                inspected["NativeContactStateFrame"] = dialog.findChild(
                    QtWidgets.QComboBox, "NativeContactStateFrames"
                ).currentIndex()
                self.assertGreater(table.rowCount(), 0)
                self.assertEqual(table.rowCount(), len(local["frames"][-1]["samples"]))
                headers = self._headers(table)
                for header in ("contact", "availability", "state", "native_point", "pressure"):
                    self.assertIn(header, headers)
                self.assertEqual(
                    self._text(table, 0, headers.index("contact")), self.model.contact.Name
                )
                self.assertGreater(float(self._text(table, 0, headers.index("pressure"))), 0)
                inspected["tables"] += (table,)
                if os.environ.get("R9_WITNESS_ROOT"):
                    self.assertTrue(
                        dialog.grab().save(str(self.directory / "contact-inspector.png"))
                    )
                # A companion-result failure must withdraw the open beam
                # inspector too, without changing either frame selector or
                # calling either getter from this test after the mutation.
                contact.ContactHash = "0" * 64
                withdrawal_timer.start(1000)
            except Exception as error:
                fail_callback(error)

        def inspect_beam():
            try:
                dialogs = own_dialogs("NativeBeamSectionInspector")
                self.assertEqual(len(dialogs), 1)
                dialog = dialogs[0]
                inspected["tables"] = self._assert_actions(dialog, data)
                inspected["NativeBeamSectionFrame"] = dialog.findChild(
                    QtWidgets.QComboBox, "NativeBeamSectionFrames"
                ).currentIndex()
                if os.environ.get("R9_WITNESS_ROOT"):
                    self.assertTrue(dialog.grab().save(str(self.directory / "beam-inspector.png")))
                contact_timer.start(100)
                self.assertTrue(contact.ViewObject.Proxy.doubleClicked(contact.ViewObject))
            except Exception as error:
                fail_callback(error)

        beam_timer = QtCore.QTimer()
        beam_timer.setSingleShot(True)
        beam_timer.timeout.connect(inspect_beam)
        contact_timer = QtCore.QTimer()
        contact_timer.setSingleShot(True)
        contact_timer.timeout.connect(inspect_contact)
        withdrawal_timer = QtCore.QTimer()
        withdrawal_timer.setSingleShot(True)
        withdrawal_timer.timeout.connect(check_withdrawal)
        watchdog = QtCore.QTimer()
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(
            lambda: fail_callback(AssertionError("Native paired beam/contact inspectors timed out"))
        )
        timers.extend((beam_timer, contact_timer, withdrawal_timer, watchdog))
        beam_timer.start(100)
        watchdog.start(15000)
        try:
            self.assertTrue(beam.ViewObject.Proxy.doubleClicked(beam.ViewObject))
        finally:
            for timer in timers:
                timer.stop()
            for dialog in own_dialogs():
                dialog.reject()
        if "error" in inspected:
            raise inspected["error"]
        self.assertTrue(inspected.get("withdrawn"))
