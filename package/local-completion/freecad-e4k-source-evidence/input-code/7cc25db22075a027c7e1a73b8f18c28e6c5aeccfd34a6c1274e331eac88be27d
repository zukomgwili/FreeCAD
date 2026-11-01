# SPDX-License-Identifier: LGPL-2.1-or-later
"""Saved native static-step defaults and independently authored load histories."""

from pathlib import Path
from io import StringIO
import tempfile
from types import SimpleNamespace
import unittest

import FreeCAD as App
import ObjectsFem

from femexamples.constraint_selfweight_cantilever import setup
from femtools.ccxtools import FemToolsCcx


class TestStaticStepAmplitude(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("StaticStepAmplitudeTest")
        setup(self.doc, test_mode=True)
        self.solver = self.doc.CalculiXCcxTools
        self.directory = tempfile.TemporaryDirectory(prefix="freecad-static-step-amplitude-")

    def tearDown(self):
        if self.doc.Name in App.listDocuments():
            App.closeDocument(self.doc.Name)
        self.directory.cleanup()

    def write(self):
        self.doc.recompute()
        fea = FemToolsCcx(self.doc.Analysis, self.solver, test_mode=True)
        fea.update_objects()
        fea.setup_working_dir(self.directory.name)
        self.assertFalse(fea.write_inp_file())
        return Path(fea.inp_file_name).read_text()

    def make_loads(self):
        force = ObjectsFem.makeConstraintForce(self.doc, "VariableForce")
        force.References = [(self.doc.Box, ["Face2"])]
        force.Force = "12 N"
        pressure = ObjectsFem.makeConstraintPressure(self.doc, "VariablePressure")
        pressure.References = [(self.doc.Box, ["Face6"])]
        pressure.Pressure = "0.5 MPa"
        for obj in (force, pressure):
            obj.EnableAmplitude = True
            obj.AmplitudeValues = ["0, 0, 0.2, 0", "0.4, 1, 0.6, 0, 0.8, -1, 1, 0"]
            self.doc.Analysis.addObject(obj)
        return force, pressure

    def reopen(self, filename):
        path = str(Path(self.directory.name) / filename)
        self.doc.recompute()
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        self.solver = self.doc.CalculiXCcxTools

    def test_step_holds_volumetric_gravity_and_keeps_explicit_force_and_pressure_histories(self):
        force, pressure = self.make_loads()
        self.solver.StaticStepAmplitude = "Step"
        self.doc.Gravity.GravityAcceleration = "9.81 m/s^2"
        deck = self.write()
        self.assertIn("*STEP, INC=2000, AMPLITUDE=STEP\n", deck)
        self.assertIn("*DLOAD\nEall,GRAV,9810,0,0,-1\n", deck)
        self.assertIn(f"*CLOAD, AMPLITUDE={force.Name}\n", deck)
        self.assertIn(f"*DLOAD, AMPLITUDE={pressure.Name}\n", deck)
        for obj in (force, pressure):
            self.assertIn(
                f"*AMPLITUDE, NAME={obj.Name}\n" + "\n".join(obj.AmplitudeValues) + "\n\n",
                deck,
            )
        self.assertEqual(deck.count("*STEP,"), 1)

    def test_default_and_missing_legacy_control_preserve_exact_stock_writer_output(self):
        self.assertEqual(self.solver.StaticStepAmplitude, "Ramp")
        expected = self.write()
        self.assertIn("*STEP, INC=2000\n", expected)
        self.assertIn("*DLOAD\nEall,GRAV,9806.65,0,0,-1\n", expected)
        self.assertNotIn("AMPLITUDE", expected)
        self.solver.setPropertyStatus("StaticStepAmplitude", "-LockDynamic")
        self.solver.removeProperty("StaticStepAmplitude")

        # Separate stock writes may cross a wall-clock second. Compare all
        # other bytes; the executed decks themselves remain untouched.
        def without_timestamp(text):
            return "".join(
                line
                for line in text.splitlines(keepends=True)
                if not line.startswith("**   written on    --> ")
            )

        self.assertEqual(without_timestamp(self.write()), without_timestamp(expected))

    def test_saved_control_preserves_load_identity_units_material_ownership_and_history(self):
        force, pressure = self.make_loads()
        self.solver.StaticStepAmplitude = "Step"
        self.doc.Gravity.GravityAcceleration = "9.81 m/s^2"
        names = (force.Name, pressure.Name)
        histories = [list(obj.AmplitudeValues) for obj in (force, pressure)]
        material = dict(self.doc.FemMaterial.Material)
        self.reopen("staged-gravity.FCStd")
        self.assertEqual(self.solver.StaticStepAmplitude, "Step")
        self.assertEqual(self.doc.Gravity.GravityAcceleration.getValueAs("mm/s^2").Value, 9810)
        self.assertEqual(tuple(self.doc.Gravity.GravityDirection), (0, 0, -1))
        self.assertEqual(dict(self.doc.FemMaterial.Material), material)
        self.assertEqual(self.doc.FemMaterial.References, [(self.doc.Box, ("Solid1",))])
        for name, values in zip(names, histories):
            obj = self.doc.getObject(name)
            self.assertTrue(obj.EnableAmplitude)
            self.assertEqual(list(obj.AmplitudeValues), values)
        self.assertEqual(self.doc.getObject(names[0]).Force.getValueAs("N").Value, 12)
        self.assertEqual(self.doc.getObject(names[1]).Pressure.getValueAs("MPa").Value, 0.5)
        self.assertIn("*STEP, INC=2000, AMPLITUDE=STEP\n", self.write())

    def test_old_saved_solver_gains_ramp_default_without_changing_other_controls(self):
        self.solver.TimeInitialIncrement = "0.125 s"
        self.solver.setPropertyStatus("StaticStepAmplitude", "-LockDynamic")
        self.solver.removeProperty("StaticStepAmplitude")
        self.reopen("legacy-default.FCStd")
        self.assertEqual(self.solver.StaticStepAmplitude, "Ramp")
        self.assertEqual(self.solver.TimeInitialIncrement.getValueAs("s").Value, 0.125)
        self.assertIn("*STEP, INC=2000\n", self.write())

    def test_invalid_static_default_and_unsupported_analysis_are_refused(self):
        self.solver.StaticStepAmplitude = ["Unknown"]
        with self.assertRaisesRegex(ValueError, "StaticStepAmplitude"):
            self.write()
        self.solver.StaticStepAmplitude = ["Ramp", "Step"]
        self.solver.StaticStepAmplitude = "Step"
        self.solver.AnalysisType = "frequency"
        with self.assertRaisesRegex(ValueError, "static"):
            self.write()

    def test_enabled_missing_or_invalid_load_amplitudes_are_refused_without_repair(self):
        force, pressure = self.make_loads()
        cases = (
            [],
            [""],
            ["0"],
            ["0, 0, 1"],
            ["0, nan"],
            ["0, inf"],
            ["nan, 0"],
            ["0, 0", "0, 1"],
            ["1, 0", "0, 1"],
            ["0, 0\n*STEP"],
            ["0, 0", "** comment"],
            ["0, , 1, 1"],
            ["0, 0, 1, 1, 2, 0, 3, -1, 4, 0"],
        )
        for obj in (force, pressure):
            valid = list(obj.AmplitudeValues)
            for values in cases:
                with self.subTest(object=obj.Name, values=values):
                    obj.AmplitudeValues = values
                    with self.assertRaisesRegex(ValueError, obj.Name + ".*amplitude"):
                        self.write()
                    self.assertEqual(list(obj.AmplitudeValues), values)
            obj.AmplitudeValues = valid

    def test_signed_finite_fortran_histories_remain_literal_and_disabled_invalid_is_ignored(self):
        force, pressure = self.make_loads()
        force.AmplitudeValues = [" -1D0, 0, ", "0D0, 0, , ,", "2D-1, 0, 4d-1, -1, 1d0, 1,"]
        pressure.EnableAmplitude = False
        pressure.AmplitudeValues = ["invalid while disabled"]
        for mode in ("Ramp", "Step"):
            with self.subTest(mode=mode):
                self.solver.StaticStepAmplitude = mode
                deck = self.write()
                self.assertIn("\n".join(force.AmplitudeValues), deck)
                self.assertNotIn(f"*AMPLITUDE, NAME={pressure.Name}", deck)
                self.assertNotIn("invalid while disabled", deck)

    def test_all_enabled_histories_are_checked_before_emitting_any_definition(self):
        from femsolver.calculix import write_amplitude

        force, pressure = self.make_loads()
        pressure.AmplitudeValues = ["0, 0", "0, 1"]
        member = SimpleNamespace(
            cons_force=[{"Object": force}],
            cons_pressure=[{"Object": pressure}],
            cons_displacement=[],
            cons_heatflux=[],
            cons_temperature=[],
            cons_bodyheatsource=[],
            cons_rigidbody=[],
            cons_initialtemperature=[],
        )
        output = StringIO()
        with self.assertRaisesRegex(ValueError, pressure.Name + ".*amplitude"):
            write_amplitude.write_amplitude(output, SimpleNamespace(member=member))
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(list(pressure.AmplitudeValues), ["0, 0", "0, 1"])
