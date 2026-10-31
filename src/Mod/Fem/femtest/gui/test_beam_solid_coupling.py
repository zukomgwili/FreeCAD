# SPDX-License-Identifier: LGPL-2.1-or-later
"""Inspect the native mixed load path and its separate solid result in the GUI."""

from collections import Counter
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import FreeCAD as App

from femtest.app.beam_coupling_fixtures import make_hybrid_series
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
class TestBeamSolidCouplingGui(unittest.TestCase):
    # Import the helper module, not its TestCase class into this module's
    # namespace: unittest must not rediscover or inherit the V2 tracer here.
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
        explicit = os.environ.get("SV7_TEST_SOLVER")
        selected = explicit or solver_binary(SimpleNamespace(NativeAccountingSolver=""))
        try:
            require_capability(selected, schema="CCX_BEAM_SECTION_V3")
        except (OSError, ValueError) as error:
            if explicit:
                raise
            self.skipTest("Qualified native mixed beam/solid observer required: " + str(error))
        retained = os.environ.get("SV7_WITNESS_ROOT")
        if retained:
            self.directory = Path(retained) / self._testMethodName
            self.directory.mkdir(parents=True)
        else:
            self.temporary = tempfile.TemporaryDirectory(prefix="freecad-beam-solid-gui-")
            self.directory = Path(self.temporary.name)
        self.doc = App.newDocument("BeamSolidCouplingGui")
        self.model = make_hybrid_series(self.doc)
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

    def _pipeline_roles(self):
        if "BUILD_FEM_VTK" not in App.__cmake__:
            return {}
        pipelines = self.model.analysis.getObjectsOfType("Fem::FemPostPipeline")
        self.assertEqual(
            len(pipelines), 2, "Mixed displacement and solid stress need distinct pipelines"
        )
        by_points = {pipeline.Data.GetNumberOfPoints(): pipeline for pipeline in pipelines}
        self.assertEqual(set(by_points), {6, 11})
        mixed, solid = by_points[11], by_points[6]
        self.assertNotEqual(mixed.Name, solid.Name)
        for pipeline in (mixed, solid):
            vector = pipeline.Data.GetPointData().GetArray("Displacement")
            self.assertIsNotNone(vector)
            self.assertEqual(vector.GetNumberOfComponents(), 3)
            self.assertEqual(vector.GetNumberOfTuples(), pipeline.Data.GetNumberOfPoints())
        self.assertIsNone(mixed.Data.GetPointData().GetArray("Stress xx component"))
        stress = solid.Data.GetPointData().GetArray("Stress xx component")
        self.assertIsNotNone(stress)
        self.assertEqual(stress.GetNumberOfTuples(), 6)
        # The native VTK pipeline uses Pa; the mechanical solid result uses MPa.
        for index in range(6):
            self.assertAlmostEqual(stress.GetTuple1(index), 1e6 * 4 / 3, delta=100)
        return {points: pipeline.Name for points, pipeline in by_points.items()}

    def test_hybrid_inspector_keeps_internal_actions_and_solid_pipeline_separate(self):
        fea = FemToolsCcx(analysis=self.model.analysis, solver=self.model.solver)
        fea.update_objects()
        fea.setup_working_dir(str(self.directory))
        self.assertFalse(fea.check_prerequisites())
        self.assertFalse(fea.write_inp_file())
        self.assertEqual(fea.ccx_run(), 0, fea.ccx_stdout + fea.ccx_stderr)
        fea.load_results()
        result = next(
            obj
            for obj in self.model.analysis.Group
            if getattr(getattr(obj, "Proxy", None), "Type", "") == "Fem::BeamSectionForceResult"
        )
        data = result.Proxy.getSectionForces(result)
        self.assertEqual(data["schema"], "CCX_BEAM_SECTION_V3")
        mechanical = [
            obj for obj in self.model.analysis.Group if obj.isDerivedFrom("Fem::FemResultObject")
        ]
        self.assertEqual(len(mechanical), 2)
        solid = next(obj for obj in mechanical if hasattr(obj, "NativeSolidOwner"))
        mixed = next(obj for obj in mechanical if not hasattr(obj, "NativeSolidOwner"))
        self.assertEqual(list(solid.NativeSourceNodeNumbers), [101, 102, 103, 104, 105, 106])
        self.assertEqual(
            list(mixed.NativeSourceNodeNumbers), [1, 2, 3, 4, 5, 101, 102, 103, 104, 105, 106]
        )
        self.assertEqual(solid.NativeSolidOwner, self.model.solid)
        self.assertFalse(mixed.NodeStressXX)
        self.assertEqual(len(solid.NodeStressXX), 6)
        for value in solid.NodeStressXX:
            self.assertAlmostEqual(value, 4 / 3, delta=0.0001)
        roles = self._pipeline_roles()
        self.assertFalse(self.general.GetBool(self.keep_key, True))
        # A second normal import must update the same two pipeline roles,
        # including when old mechanical result objects remain in the document.
        fea.load_results()
        self.assertEqual(self._pipeline_roles(), roles)
        self.assertEqual(result.Proxy.getSectionForces(result), data)
        existing = {
            id(dialog)
            for dialog in Gui.getMainWindow().findChildren(
                QtWidgets.QDialog, "NativeBeamSectionInspector"
            )
        }
        inspected, timers = {}, []

        def own_dialogs():
            return [
                dialog
                for dialog in Gui.getMainWindow().findChildren(
                    QtWidgets.QDialog, "NativeBeamSectionInspector"
                )
                if id(dialog) not in existing
            ]

        def fail_callback(error):
            inspected.setdefault("error", error)
            for dialog in own_dialogs():
                dialog.reject()

        def check_withdrawal():
            try:
                dialog = inspected["dialog"]
                for table in inspected["tables"]:
                    self.assertEqual(table.rowCount(), 0, table.objectName())
                availability = dialog.findChild(QtWidgets.QLabel, "NativeBeamSectionAvailability")
                self.assertIn("Unavailable", availability.text())
                frames = dialog.findChild(QtWidgets.QComboBox, "NativeBeamSectionFrames")
                self.assertFalse(frames.isEnabled())
                self.assertFalse(result.Status.startswith("Current"), result.Status)
                inspected["withdrawn"] = True
                if os.environ.get("SV7_WITNESS_ROOT"):
                    self.assertTrue(
                        dialog.grab().save(str(self.directory / "withdrawn-inspector.png"))
                    )
                dialog.accept()
            except Exception as error:
                fail_callback(error)

        def inspect_dialog():
            try:
                dialogs = own_dialogs()
                self.assertEqual(len(dialogs), 1)
                dialog = dialogs[0]
                inspected["dialog"] = dialog
                samples = dialog.findChild(QtWidgets.QTableWidget, "NativeBeamSectionSamples")
                actions = dialog.findChild(QtWidgets.QTableWidget, "NativeCoupledBeamActions")
                supports = dialog.findChild(QtWidgets.QTableWidget, "NativeCoupledBeamSupportDofs")
                self.assertIsNotNone(actions, "Native mixed load-path action table is missing")
                self.assertIsNotNone(
                    supports, "Native mixed physical/algebraic DOF table is missing"
                )
                self.assertEqual(samples.rowCount(), 4)
                self.assertEqual(actions.rowCount(), 7)
                self.assertEqual(supports.rowCount(), 26)
                labels = " ".join(label.text() for label in dialog.findChildren(QtWidgets.QLabel))
                self.assertIn("global origin", labels.lower())
                self.assertIn("physical support", labels.lower())
                self.assertIn("internal", labels.lower())
                self.assertIn("algebraic", labels.lower())
                self.assertIn("excluded", labels.lower())
                self.assertIn("N*mm", labels)
                headers = self._headers(actions)
                for header in (
                    "Action",
                    "Owner",
                    "Node / region",
                    "Fx (N)",
                    "Mx about origin (N*mm)",
                ):
                    self.assertIn(header, headers)
                rows = {
                    self._text(actions, row, headers.index("Action")).lower(): row
                    for row in range(actions.rowCount())
                }
                port = data["frames"][0]["native_actions"]["port"]
                expected = (
                    ("source", "HybridForce", (5,), (100, 0, 0), (0, -2300, -1700)),
                    ("beam guide", "HybridStabilizer", (1,), (0, 0, 0), (0, 0, 0)),
                    ("solid fixed", "HybridFixed", (101, 102, 103), (-100, 0, 0), (0, 2300, 1700)),
                    ("spring on beam", "HybridSpring", (1,), (-100, 0, 0), (0, 2300, 1700)),
                    (
                        "spring on reference",
                        "HybridSpring",
                        (port["reference_node"],),
                        (100, 0, 0),
                        (0, -2300, -1700),
                    ),
                    (
                        "rbe receiving",
                        "HybridPort",
                        (104, 105, 106),
                        (100, 0, 0),
                        (0, -2300, -1700),
                    ),
                    (
                        "rbe reference",
                        "HybridPort",
                        (port["reference_node"],),
                        (-100, 0, 0),
                        (0, 2300, 1700),
                    ),
                )
                self.assertEqual(set(rows), {row[0] for row in expected})
                for name, owner, nodes, force, moment in expected:
                    row = rows[name]
                    self.assertEqual(self._text(actions, row, headers.index("Owner")), owner)
                    region = self._text(actions, row, headers.index("Node / region"))
                    for node in nodes:
                        self.assertIn(str(node), region)
                    for axis, value in zip("xyz", force):
                        self.assertAlmostEqual(
                            float(self._text(actions, row, headers.index(f"F{axis} (N)"))),
                            value,
                            delta=0.01,
                        )
                    for axis, value in zip("xyz", moment):
                        self.assertAlmostEqual(
                            float(
                                self._text(
                                    actions, row, headers.index(f"M{axis} about origin (N*mm)")
                                )
                            ),
                            value,
                            delta=1,
                        )
                headers = self._headers(supports)
                for header in ("Role", "Owner", "Units", "Physical contribution"):
                    self.assertIn(header, headers)
                roles = Counter()
                owners = Counter()
                for row in range(supports.rowCount()):
                    role = self._text(supports, row, headers.index("Role"))
                    roles[role] += 1
                    owners[self._text(supports, row, headers.index("Owner"))] += 1
                    if role == "ALGEBRAIC":
                        self.assertIn(
                            "excluded",
                            self._text(
                                supports, row, headers.index("Physical contribution")
                            ).lower(),
                        )
                        self.assertNotIn(
                            self._text(supports, row, headers.index("Units")), ("N", "N*mm")
                        )
                self.assertEqual(roles, {"TRANSLATION": 11, "ANGLE": 3, "ALGEBRAIC": 12})
                self.assertEqual(owners, {"HybridStabilizer": 8, "HybridFixed": 9, "HybridPort": 9})
                inspected["tables"] = (samples, actions, supports)
                inspected["rows"] = (4, 7, 26)
                if os.environ.get("SV7_WITNESS_ROOT"):
                    self.assertTrue(dialog.grab().save(str(self.directory / "inspector.png")))
                self.model.connector.Stiffness = "10001 N/mm"
                self.doc.recompute()
                withdrawal_timer.start(1000)
            except Exception as error:
                fail_callback(error)

        inspection_timer = QtCore.QTimer()
        inspection_timer.setSingleShot(True)
        inspection_timer.timeout.connect(inspect_dialog)
        withdrawal_timer = QtCore.QTimer()
        withdrawal_timer.setSingleShot(True)
        withdrawal_timer.timeout.connect(check_withdrawal)
        watchdog = QtCore.QTimer()
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(
            lambda: fail_callback(AssertionError("Native mixed beam/solid inspector timed out"))
        )
        timers.extend((inspection_timer, withdrawal_timer, watchdog))
        inspection_timer.start(100)
        watchdog.start(15000)
        try:
            self.assertTrue(result.ViewObject.Proxy.doubleClicked(result.ViewObject))
        finally:
            for timer in timers:
                timer.stop()
            for dialog in own_dialogs():
                dialog.reject()
        if "error" in inspected:
            raise inspected["error"]
        self.assertEqual(inspected.get("rows"), (4, 7, 26))
        self.assertTrue(inspected.get("withdrawn"))
