# SPDX-License-Identifier: LGPL-2.1-or-later
"""Stock-authored gravity/contact history; analytical software qualification only.

Each current endpoint is a fresh one-step native solve from time zero, with
the same absolute-time Q history. No multi-frame accounting API is implied.
No Oomakhi project, edited deck, recovered force or fitted reference is used.
"""

import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
from types import SimpleNamespace
import unittest

import FreeCAD as App
import ObjectsFem
import Part
from BOPTools.SplitAPI import booleanFragments
from femmesh.gmshtools import GmshTools
from femtools.ccxtools import FemToolsCcx

HISTORY = ["0, 0, 0.2, 0", "0.4, 1, 0.6, 0, 0.8, -1, 1, 0"]
GRAVITY = 9.80665
DENSITIES = (7900, 7800, 8000)
WEIGHTS = tuple(density * 0.001 * GRAVITY for density in DENSITIES)
CENTRE = (17.0, -23.0)


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def vertical_wrench(force):
    return [0.0, 0.0, force, CENTRE[1] * force, -CENTRE[0] * force, 0.0]


@unittest.skipUnless(shutil.which("gmsh"), "Native Gmsh executable required")
class TestStagedSelfweightNative(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("StagedSelfweightNative")
        parent = os.environ.get("E4K_RUN")
        self.root = Path(tempfile.mkdtemp(prefix="staged-selfweight-", dir=parent))

    def tearDown(self):
        if self.doc.Name in App.listDocuments():
            App.closeDocument(self.doc.Name)

    def make_case(self, source="pressure"):
        analysis = ObjectsFem.makeAnalysis(self.doc)
        solver = ObjectsFem.makeSolverCalculiXCcxTools(self.doc)
        solver.AnalysisType = "static"
        solver.StaticStepAmplitude = "Step"
        solver.NativeForceAccounting = True
        solver.AutomaticIncrementation = False
        solver.TimeInitialIncrement = "0.1 s"
        solver.TimeMaximumIncrement = "0.1 s"
        solver.OutputFrequency = 1
        analysis.addObject(solver)
        geometry = self.doc.addObject("Part::Feature", "ThreeMaterials")
        blocks = [Part.makeBox(100, 100, 100, App.Vector(-33, -73, z)) for z in (0, 100, 200)]
        geometry.Shape = Part.makeCompound([blocks[0], booleanFragments(blocks[1:], "CompSolid")])
        self.doc.recompute()
        self.assertTrue(geometry.Shape.isValid())
        self.assertEqual(len(geometry.Shape.Solids), 3)

        def solid_at(z):
            found = [
                f"Solid{i}"
                for i, solid in enumerate(geometry.Shape.Solids, 1)
                if abs(solid.CenterOfMass.z - z) < 1e-7
            ]
            self.assertEqual(len(found), 1)
            return found[0]

        def face_at(owner, z, normal):
            found = [
                f"Face{i}"
                for i, face in enumerate(owner.Shape.Faces, 1)
                if abs(face.CenterOfMass.z - z) < 1e-7 and face.normalAt(0, 0).z * normal > 0.99
            ]
            self.assertEqual(len(found), 1, (z, normal, found))
            return found[0]

        solids = [solid_at(z) for z in (50, 150, 250)]
        materials = []
        for name, solid, density in zip(
            ("BaseMaterial", "LowerMaterial", "UpperMaterial"), solids, DENSITIES
        ):
            material = ObjectsFem.makeMaterialSolid(self.doc, name)
            material.References = [(geometry, [solid])]
            material.Material = {
                "Name": name,
                "YoungsModulus": "200000 MPa",
                "PoissonRatio": "0",
                "Density": f"{density} kg/m^3",
            }
            analysis.addObject(material)
            materials.append(material)
        fixed = ObjectsFem.makeConstraintFixed(self.doc, "BaseSupport")
        fixed.References = [(geometry, [face_at(geometry, 0, -1)])]
        analysis.addObject(fixed)
        solver.NativeAccountingSupports = [fixed]
        contact = ObjectsFem.makeConstraintContact(self.doc, "GravityContact")
        contact.References = [
            (geometry, [face_at(geometry, 100, -1)]),
            (geometry, [face_at(geometry, 100, 1)]),
        ]
        contact.SurfaceBehavior = "Linear"
        contact.Slope = "100000 MPa/mm"
        contact.Friction = True
        contact.FrictionCoefficient = 0.3
        contact.StickSlope = "10000 MPa/mm"
        contact.Adjust = "0 mm"
        analysis.addObject(contact)
        solver.NativeContactOutputs = [contact]
        gravity = ObjectsFem.makeConstraintSelfWeight(self.doc, "VolumetricGravity")
        gravity.GravityAcceleration = f"{GRAVITY} m/s^2"
        gravity.GravityDirection = (0, 0, -1)
        analysis.addObject(gravity)
        if source == "pressure":
            load = ObjectsFem.makeConstraintPressure(self.doc, "VariableQPressure")
            load.Pressure = "0.001 MPa"
        else:
            load = ObjectsFem.makeConstraintForce(self.doc, "VariableQForce")
            direction = self.doc.addObject("Part::Feature", "QDirection")
            direction.Shape = Part.makeLine(App.Vector(), App.Vector(0, 0, -1))
            load.Force = "10 N"
            load.Direction = (direction, ["Edge1"])
            load.Reversed = False
        load.References = [(geometry, [face_at(geometry, 300, 1)])]
        load.EnableAmplitude = True
        load.AmplitudeValues = HISTORY
        analysis.addObject(load)
        lower = ObjectsFem.makeConstraintSectionPrint(self.doc, "LowerCut")
        lower.References = [(geometry, [face_at(geometry, 200, 1)])]
        lower.NativeEquilibriumCut = True
        lower.AccountingBody = [(geometry, [solids[1]])]
        analysis.addObject(lower)
        reverse = self.doc.addObject("Part::Reverse", "UpperCutOrientation")
        reverse.Source = geometry
        self.doc.recompute()
        upper = ObjectsFem.makeConstraintSectionPrint(self.doc, "UpperCut")
        upper.References = [(reverse, [face_at(reverse, 200, -1)])]
        upper.NativeEquilibriumCut = True
        upper.AccountingBody = [(geometry, [solids[2]])]
        analysis.addObject(upper)
        mesh = ObjectsFem.makeMeshGmsh(self.doc, "Mesh")
        mesh.Shape = geometry
        mesh.ElementOrder = "2nd"
        mesh.SecondOrderLinear = True
        mesh.CoherenceMesh = False
        mesh.CharacteristicLengthMax = 40
        mesh.CharacteristicLengthMin = 40
        mesh.WorkingDirectory = str(self.root)
        analysis.addObject(mesh)
        self.doc.recompute()
        mesher = GmshTools(mesh)
        mesher.create_mesh()
        self.assertEqual(mesher.process.exitCode(), 0)
        self.assertGreater(mesh.FemMesh.VolumeCount, 0)
        # The contact owners are distinct; the upper cut remains conformal.
        volume_nodes = []
        for solid in solids:
            group = next(g for g in mesh.FemMesh.Groups if mesh.FemMesh.getGroupName(g) == solid)
            elements = set(mesh.FemMesh.getGroupElements(group))
            self.assertTrue(elements)
            volume_nodes.append(
                {node for element in elements for node in mesh.FemMesh.getElementNodes(element)}
            )
        self.assertFalse(volume_nodes[0] & volume_nodes[1])
        self.assertTrue(volume_nodes[1] & volume_nodes[2])
        return SimpleNamespace(
            analysis=analysis,
            solver=solver,
            geometry=geometry,
            materials=materials,
            mesh=mesh,
            load=load,
            gravity=gravity,
            fixed=fixed,
            contact=contact,
            lower=lower,
            upper=upper,
            native_lower_role="slave",
        )

    def solve(self, model, time):
        folder = self.root / f"run-{len(list(self.root.glob('run-*')))}-time-{time}"
        folder.mkdir()
        model.solver.TimePeriod = f"{time} s"
        self.doc.recompute()
        fea = FemToolsCcx(analysis=model.analysis, solver=model.solver)
        fea.update_objects()
        fea.setup_working_dir(str(folder))
        self.assertFalse(fea.write_inp_file())
        deck = Path(fea.inp_file_name)
        text = deck.read_text()
        self.assertEqual(text.count("*STEP,"), 1)
        if model.solver.StaticStepAmplitude == "Step":
            self.assertIn("AMPLITUDE=STEP", text)
        else:
            self.assertNotIn("AMPLITUDE=STEP", text)
        self.assertIn("Eall,GRAV,9806.65,0,0,-1", text)
        self.assertIn("\n".join(HISTORY), text)
        self.assertIn(f"AMPLITUDE={model.load.Name}", text)
        before = file_hash(deck)
        self.assertEqual(fea.ccx_run(), 0, fea.ccx_stdout + fea.ccx_stderr)
        self.assertEqual(file_hash(deck), before)
        (folder / "solver.stdout").write_text(fea.ccx_stdout)
        (folder / "solver.stderr").write_text(fea.ccx_stderr)
        current = [
            obj
            for obj in model.analysis.Group
            if getattr(getattr(obj, "Proxy", None), "Type", "")
            == "Fem::NativeForceAccountingResult"
            and obj.Status.startswith("Current")
        ]
        self.assertEqual(len(current), 1)
        accounting = current[0]
        self.assertTrue(accounting.Status.startswith("Current"), accounting.Status)
        data = json.loads(accounting.AccountingData)
        current_contact = [
            obj
            for obj in model.analysis.Group
            if getattr(getattr(obj, "Proxy", None), "Type", "") == "Fem::ContactStateResult"
            and obj.Status.startswith("Current")
        ]
        self.assertEqual(len(current_contact), 1)
        observation = current_contact[0]
        contact = observation.Proxy.getContactStates(observation)
        state = deck.with_suffix(".accounting.out").read_text().splitlines()[1].split()
        frame = contact["frames"][-1]
        self.assertEqual(state[0], "STATE")
        self.assertEqual((int(state[1]), int(state[2])), (frame["step"], frame["increment"]))
        self.assertAlmostEqual(float(state[3]), time, delta=1e-10)
        self.assertAlmostEqual(frame["time"], time, delta=1e-10)
        active = [sample for sample in frame["samples"] if sample["availability"] == "ACTIVE"]
        self.assertTrue(active)
        self.assertTrue(
            all(sample["state"] == "STICK" and sample["pressure"] > 0 for sample in active)
        )
        self.assertEqual(data["model_digest"], contact["provenance"]["model_digest"])
        self.assertEqual(data["deck_sha256"], contact["provenance"]["deck_sha256"])
        physical = contact["provenance"]["contacts"]
        self.assertEqual(len(physical), 1)
        self.assertEqual(
            physical[0]["references_slave_then_master"],
            [[owner.Name, list(names)] for owner, names in model.contact.References],
        )
        solid = model.lower.AccountingBody[0][1][0]
        native = model.mesh.FemMesh
        group = next(group for group in native.Groups if native.getGroupName(group) == solid)
        lower_elements = set(native.getGroupElements(group))
        role = model.native_lower_role
        other = "master" if role == "slave" else "slave"
        self.assertTrue(
            {element for element, _face in physical[0][role + "_faces"]} <= lower_elements
        )
        self.assertFalse(
            {element for element, _face in physical[0][other + "_faces"]} & lower_elements
        )
        for row in active:
            self.assertIn(row[role + "_element"], lower_elements)
            self.assertNotIn(row[other + "_element"], lower_elements)
        fea.load_results()
        return SimpleNamespace(
            fea=fea,
            accounting=accounting,
            data=data,
            observation=observation,
            contact=contact,
            folder=folder,
        )

    def assert_wrench(self, actual, expected, label):
        # Independent per-component 1% limits, with separately fixed zero
        # budgets. Never infer a tolerance from computed actions or residuals.
        for index, (value, reference) in enumerate(zip(actual, expected)):
            self.assertTrue(math.isfinite(value))
            budget = 0.01 * abs(reference) if reference else (1e-6 if index < 3 else 1e-4)
            self.assertLessEqual(abs(value - reference), budget, (label, index, value, reference))

    def check_endpoint(self, model, run, factor):
        w = run.data["wrenches"]
        q = 10 * factor
        references = {
            ("SUPPORT", model.fixed.Name): vertical_wrench(sum(WEIGHTS) + q),
            ("LOAD", model.upper.Name): vertical_wrench(-WEIGHTS[2] - q),
            ("LOAD", model.lower.Name): vertical_wrench(-WEIGHTS[1]),
            ("CONTACT", model.lower.Name): vertical_wrench(WEIGHTS[1] + WEIGHTS[2] + q),
            ("CONTACT", model.upper.Name): [0.0] * 6,
            ("MPC", model.lower.Name): [0.0] * 6,
            ("MPC", model.upper.Name): [0.0] * 6,
            ("CUT", model.upper.Name): vertical_wrench(WEIGHTS[2] + q),
            ("CUT", model.lower.Name): vertical_wrench(-WEIGHTS[2] - q),
        }
        for (kind, owner), reference in references.items():
            self.assert_wrench(w[kind][owner], reference, (kind, owner))
        # The independently frozen closure budget uses the largest physical
        # action on each active axis. A cancellation residual on active Z is
        # not an independently zero physical load component.
        closure_scale = vertical_wrench(sum(WEIGHTS) + q)

        def closure(actual, label):
            for index, (value, scale) in enumerate(zip(actual, closure_scale)):
                budget = 0.01 * abs(scale) if scale else (1e-6 if index < 3 else 1e-4)
                self.assertLessEqual(abs(value), budget, (label, index, value, budget))

        global_external = [
            a + b
            for a, b in zip(w["SUPPORT"][model.fixed.Name], vertical_wrench(-sum(WEIGHTS) - q))
        ]
        closure(global_external, "global external balance")
        cut_pair = [a + b for a, b in zip(w["CUT"][model.lower.Name], w["CUT"][model.upper.Name])]
        closure(cut_pair, "opposite material cut sides")
        material_closures = {}
        for owner in (model.lower.Name, model.upper.Name):
            values = [
                math.fsum(w[channel][owner][index] for channel in ("LOAD", "CONTACT", "MPC", "CUT"))
                for index in range(6)
            ]
            closure(values, ("material balance", owner))
            material_closures[owner] = values
        result = {
            "time": run.data["end_time"],
            "factor": factor,
            "weights_N": WEIGHTS,
            "references": {f"{kind}/{owner}": value for (kind, owner), value in references.items()},
            "actual": w,
            "native_state": run.contact["frames"][-1]["increment"],
            "deck_sha256": run.data["deck_sha256"],
            "binary_sha256": run.data["binary_sha256"],
            "fixed_component_relative_tolerance": 0.01,
            "fixed_closure_axis_scales": closure_scale,
            "global_external_closure": global_external,
            "cut_pair_closure": cut_pair,
            "material_closures": material_closures,
            "lower_native_contact_role": model.native_lower_role,
        }
        (run.folder / "equilibrium.json").write_text(json.dumps(result, indent=2) + "\n")

    def test_pressure_reversal_after_gravity_equilibrium_keeps_all_native_channels_current(self):
        model = self.make_case()
        for time, factor in ((0.2, 0), (0.4, 1), (0.6, 0), (0.8, -1), (1.0, 0)):
            with self.subTest(time=time):
                run = self.solve(model, time)
                self.check_endpoint(model, run, factor)
        self.check_early_gravity(run)
        self.assertEqual(run.contact["inventory_scope"], "PER_RETAINED_FRAME")
        catalogues = [
            json.dumps([frame["face_inventory"], frame["sample_inventory"]], sort_keys=True)
            for frame in run.contact["frames"]
        ]
        self.assertGreater(len(set(catalogues)), 1, "Fixture must exercise native resampling")
        self.doc.saveAs(str(self.root / "staged-gravity.FCStd"))
        (self.root / "saved-literals.json").write_text(
            json.dumps(
                {
                    "accounting_name": run.accounting.Name,
                    "accounting": run.accounting.AccountingData,
                    "contact_name": run.observation.Name,
                    "contact": run.observation.ContactData,
                },
                indent=2,
            )
        )

    def check_early_gravity(self, run, ramp=False):
        # Native pair totals are already integrated in CalculiX. Their force
        # magnitude establishes held G in the early increments of this full
        # history, independently of final-only accounting and deck keywords.
        pattern = (
            r"statistics for slave set DEPGRAVITYCONTACT, master set INDGRAVITYCONTACT "
            r"and time\s+(\S+)\s+total surface force \(fx,fy,fz\) "
            r"and moment about the origin \(mx,my,mz\)\s+([^\n]+)"
        )
        totals = [
            (float(time), list(map(float, values.split())))
            for time, values in re.findall(
                pattern, Path(run.fea.inp_file_name).with_suffix(".dat").read_text()
            )
        ]
        early = []
        for time in (0.1, 0.2):
            rows = [values for actual, values in totals if abs(actual - time) < 1e-10]
            self.assertEqual(len(rows), 1, totals)
            self.assertEqual(len(rows[0]), 6)
            native_force = math.hypot(*rows[0][:3])
            reference = (WEIGHTS[1] + WEIGHTS[2]) * (time if ramp else 1)
            self.assertAlmostEqual(native_force, reference, delta=0.01 * reference)
            frames = [frame for frame in run.contact["frames"] if abs(frame["time"] - time) < 1e-10]
            self.assertEqual(len(frames), 1)
            active = [row for row in frames[0]["samples"] if row["availability"] == "ACTIVE"]
            self.assertTrue(active)
            self.assertTrue(all(row["state"] == "STICK" and row["pressure"] > 0 for row in active))
            early.append(
                {
                    "time": time,
                    "native_CF": rows[0],
                    "force_magnitude_N": native_force,
                    "reference_N": reference,
                    "contact_increment": frames[0]["increment"],
                }
            )
        (self.root / "early-gravity-history.json").write_text(json.dumps(early, indent=2) + "\n")

    def test_default_ramp_preserves_its_distinct_native_gravity_history(self):
        model = self.make_case()
        model.solver.StaticStepAmplitude = "Ramp"
        run = self.solve(model, 1.0)
        self.check_endpoint(model, run, 0)
        self.check_early_gravity(run, ramp=True)

    def test_force_reversal_uses_its_independent_explicit_history(self):
        model = self.make_case(source="force")
        for time, factor in ((0.4, 1), (0.8, -1)):
            with self.subTest(time=time):
                self.check_endpoint(model, self.solve(model, time), factor)

    def test_native_master_side_attribution_preserves_the_same_physical_history(self):
        model = self.make_case()
        model.contact.References = list(reversed(model.contact.References))
        model.native_lower_role = "master"
        self.doc.recompute()
        self.check_endpoint(model, self.solve(model, 0.8), -1)

    def test_physical_history_edits_withdraw_current_and_preserve_literals(self):
        from femtools import force_accounting

        model = self.make_case()
        material = model.materials[2]
        original_material = dict(material.Material)
        edits = (
            (model.solver, "StaticStepAmplitude", "Ramp", "Step"),
            (model.solver, "TimePeriod", "0.8 s", "0.4 s"),
            (model.gravity, "GravityAcceleration", "9.81 m/s^2", f"{GRAVITY} m/s^2"),
            (model.load, "AmplitudeValues", [], HISTORY),
            (model.load, "EnableAmplitude", False, True),
            (
                material,
                "Material",
                {**original_material, "Density": "8100 kg/m^3"},
                original_material,
            ),
        )
        for obj, prop, changed, original in edits:
            with self.subTest(property=prop):
                run = self.solve(model, 0.4)
                self.check_endpoint(model, run, 1)
                saved_accounting = run.accounting.AccountingData
                saved_contact = run.observation.ContactData
                setattr(obj, prop, changed)
                self.assertFalse(run.accounting.Status.startswith("Current"))
                with self.assertRaises(ValueError):
                    run.observation.Proxy.getContactStates(run.observation)
                with self.assertRaisesRegex(ValueError, "changed"):
                    force_accounting.run_context(run.fea, run.fea.ccx_binary)
                self.assertEqual(run.accounting.AccountingData, saved_accounting)
                self.assertEqual(run.observation.ContactData, saved_contact)
                setattr(obj, prop, original)
                self.assertFalse(run.accounting.Status.startswith("Current"))
                with self.assertRaises(ValueError):
                    run.observation.Proxy.getContactStates(run.observation)
