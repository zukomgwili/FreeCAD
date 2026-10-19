# SPDX-License-Identifier: LGPL-2.1-or-later

"""Saved contact observations through real CAD/Gmsh/CalculiX native output.

These software checks do not assess contact gap/slip engineering limits.
Generated native solver evidence is retained in a private temporary directory.
"""

import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import FreeCAD as App
import Fem
import ObjectsFem

from feminout.importCcxFrdResults import read_frd_result
from femmesh import gmshtools
from femmesh import meshtools
from femtools import force_accounting
from femtools.ccxtools import FemToolsCcx


def native_mesh_identity(mesh):
    """Public native IDs and coordinates, without any numeric remapping."""
    native = mesh.FemMesh
    state = {
        "nodes": [(node, tuple(native.getNodeById(node))) for node in sorted(native.Nodes)],
        "elements": [
            (element, tuple(native.getElementNodes(element)))
            for element in sorted(set(native.Edges) | set(native.Faces) | set(native.Volumes))
        ],
    }
    return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()


@unittest.skipUnless(shutil.which("gmsh"), "Native Gmsh executable required")
class TestContactObservationNative(unittest.TestCase):
    def setUp(self):
        try:
            Fem.FemMesh().toVTK()
        except NotImplementedError:
            self.skipTest("Native VTK Python wrappers are unavailable in this build")
        self.doc = App.newDocument("ContactObservationNative")
        self.output = Path(tempfile.mkdtemp(prefix="freecad-contact-observation-native-"))

    def tearDown(self):
        if self.doc is not None and self.doc.Name in App.listDocuments():
            App.closeDocument(self.doc.Name)

    @staticmethod
    def file_hash(path):
        with Path(path).open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()

    def make_native_nonconformal_source(self, conformal=False):
        slave = self.doc.addObject("Part::Box", "Slave")
        slave.Length = 2
        slave.Width, slave.Height = (5, 5) if conformal else (1.1, 0.9)
        slave.Placement.Base = App.Vector() if conformal else App.Vector(0, 1.3, 1.7)
        master = self.doc.addObject("Part::Box", "Master")
        master.Length, master.Width, master.Height = 2, 5, 5
        master.Placement.Base = App.Vector(2, 0, 0)
        compound = self.doc.addObject("Part::Compound", "Geometry")
        compound.Links = [slave, master]
        analysis = ObjectsFem.makeAnalysis(self.doc)
        solver = ObjectsFem.makeSolverCalculiXCcxTools(self.doc)
        solver.NativeForceAccounting = True
        candidate = os.environ.get("FREECAD_9ZT_PRODUCTION_CCX")
        if candidate:
            solver.NativeAccountingSolver = candidate
        binary = Path(force_accounting.solver_binary(solver))
        if not binary.is_file() or not os.access(binary, os.X_OK):
            self.skipTest("Qualified native force-accounting solver is unavailable")
        force_accounting.require_capability(binary)
        analysis.addObject(solver)
        material = ObjectsFem.makeMaterialSolid(self.doc)
        material.Material = {
            "Name": "Steel",
            "YoungsModulus": "200000 MPa",
            "PoissonRatio": "0.3",
            "Density": "7900 kg/m^3",
        }
        analysis.addObject(material)
        for body, face, name, anchor in (
            (slave, "Face1", "SlaveSupport", App.Vector(-1, 1.3, 1.7)),
            (master, "Face2", "MasterSupport", App.Vector(5, 0, 0)),
        ):
            support = ObjectsFem.makeConstraintRigidBody(self.doc, name)
            support.References = [(body, [face])]
            support.ReferenceNode = anchor
            for kind in ("Translational", "Rotational"):
                for axis in "XYZ":
                    setattr(support, kind + "Mode" + axis, "Constraint")
            analysis.addObject(support)
        contact = ObjectsFem.makeConstraintContact(self.doc, "NonconformalContact")
        contact.References = [(slave, ["Face2"]), (master, ["Face1"])]
        contact.SurfaceBehavior = "Tied"
        contact.Slope = "1000000 MPa/mm"
        contact.Friction = True
        contact.FrictionCoefficient = 0.3
        contact.StickSlope = "100000 MPa/mm"
        contact.Adjust = "0 mm"
        analysis.addObject(contact)
        gravity = ObjectsFem.makeConstraintSelfWeight(self.doc)
        analysis.addObject(gravity)
        mesh = ObjectsFem.makeMeshGmsh(self.doc, "Mesh")
        mesh.Shape = compound
        mesh.ElementOrder = "2nd"
        mesh.SecondOrderLinear = True
        mesh.CoherenceMesh = False
        mesh.CharacteristicLengthMax = 1.4
        mesh.CharacteristicLengthMin = 0.4
        mesh.WorkingDirectory = str(self.output)
        analysis.addObject(mesh)
        self.doc.recompute()
        mesher = gmshtools.GmshTools(mesh)
        mesher.create_mesh()
        self.assertEqual(mesher.process.exitCode(), 0)
        self.assertEqual(mesher.process.exitStatus(), mesher.process.ExitStatus.NormalExit)
        self.assertGreater(mesh.FemMesh.VolumeCount, 0)
        slave_node, master_node = self.assert_owner_node_availability(mesh, slave, conformal)
        fea = FemToolsCcx(analysis=analysis, solver=solver)
        fea.update_objects()
        fea.setup_working_dir(str(self.output))
        fea.write_inp_file()
        self.assertEqual(fea.ccx_run(), 0, fea.ccx_stdout + fea.ccx_stderr)
        accounting = next(
            item
            for item in analysis.Group
            if isinstance(getattr(item, "Proxy", None), force_accounting.AccountingResult)
        )
        self.assertTrue(accounting.Status.startswith("Current"), accounting.Status)
        return SimpleNamespace(
            analysis=analysis,
            solver=solver,
            mesh=mesh,
            slave=slave,
            master=master,
            contact=contact,
            material=material,
            accounting=accounting,
            fea=fea,
            slave_node=slave_node,
            master_node=master_node,
        )

    def assert_owner_node_availability(self, mesh, slave, conformal):
        """Independent native solid groups establish the missing-master test premise."""
        native = mesh.FemMesh
        point = meshtools.sub_shape_at_global_placement(slave, "Face2").Vertexes[0].Point
        matching = []
        for owner in ("Solid1", "Solid2"):
            groups = [group for group in native.Groups if native.getGroupName(group) == owner]
            self.assertEqual(len(groups), 1, owner)
            volumes = set(native.getGroupElements(groups[0]))
            self.assertTrue(volumes)
            self.assertTrue(volumes <= set(native.Volumes))
            nodes = {node for element in volumes for node in native.getElementNodes(element)}
            matching.append(
                [node for node in nodes if (native.getNodeById(node) - point).Length < 1e-10]
            )
        self.assertEqual(tuple(map(len, matching)), (1, 1 if conformal else 0), matching)
        return matching[0][0], matching[1][0] if matching[1] else None

    def make_available_observation(self, model):
        result = ObjectsFem.makeResultContactObservation(
            self.doc, model.analysis, model.accounting, [model.contact]
        )
        result.Proxy.refresh(result)
        self.assertTrue(result.Status.startswith("Available"), result.Status)
        result.Proxy.getObservations(result)
        return result

    def test_nonconformal_source_exposes_both_native_owner_displacements(self):
        model = self.make_native_nonconformal_source()
        result = ObjectsFem.makeResultContactObservation(
            self.doc, model.analysis, model.accounting, [model.contact]
        )
        self.assertEqual(result.Mesh, model.mesh)
        result.Proxy.refresh(result)
        self.assertTrue(result.Status.startswith("Available"), result.Status)
        data = result.Proxy.getObservations(result)
        self.assertEqual(data["schema"], "FreeCAD.CONTACT_SIDE_OBSERVATION_V1")
        self.assertEqual(data["units"], "mm")
        self.assertEqual(len(data["contacts"]), 1)
        row = data["contacts"][0]
        self.assertEqual(row["contact"], model.contact.Name)
        self.assertEqual(
            row["references_slave_then_master"],
            [[model.slave.Name, ["Face2"]], [model.master.Name, ["Face1"]]],
        )
        point = meshtools.sub_shape_at_global_placement(model.slave, "Face2").Vertexes[0].Point
        self.assertEqual(row["point_mm"], list(point))
        for side, method in (("slave", "ORIGINAL_NODE"), ("master", "NATIVE_VTK_SURFACE")):
            with self.subTest(side=side):
                observed = row[side]
                self.assertEqual(observed["status"], "AVAILABLE")
                self.assertEqual(observed["method"], method)
                self.assertEqual(len(observed["value_mm"]), 3)
                self.assertTrue(all(math.isfinite(value) for value in observed["value_mm"]))
                self.assertTrue(observed["source_element_ids"])
                self.assertTrue(observed["source_node_ids"])
        frd = Path(model.fea.inp_file_name).with_suffix(".frd")
        raw_result = read_frd_result(str(frd))
        final_field = raw_result["Results"][-1]["disp"]
        self.assertIn(model.slave_node, row["slave"]["source_node_ids"])
        self.assertEqual(row["slave"]["value_mm"], list(final_field[model.slave_node]))
        self.assertEqual(Path(data["source"]["frd"]["path"]).resolve(), frd.resolve())
        self.assertEqual(data["source"]["frd"]["sha256"], self.file_hash(frd))
        self.assertEqual(data["source"]["accounting"]["name"], model.accounting.Name)
        self.assertTrue(data["source"]["model_digest"])
        self.assertEqual(data["source"]["observed_time"], data["source"]["requested_end_time"])
        frame = row["reference_frame"]
        self.assertEqual(len(frame["native_uv"]), 2)
        self.assertEqual(len(frame["tangents"]), 2)
        normal = App.Vector(*frame["normal"])
        tangents = [App.Vector(*value) for value in frame["tangents"]]
        for vector in (normal, *tangents):
            self.assertAlmostEqual(vector.Length, 1, places=12)
        self.assertAlmostEqual(normal.dot(tangents[0]), 0, places=12)
        self.assertAlmostEqual(normal.dot(tangents[1]), 0, places=12)
        self.assertAlmostEqual(tangents[0].dot(tangents[1]), 0, places=12)

    def test_saved_observation_is_historical_in_a_separate_cold_process(self):
        model = self.make_native_nonconformal_source()
        result = ObjectsFem.makeResultContactObservation(
            self.doc, model.analysis, model.accounting, [model.contact]
        )
        result.Proxy.refresh(result)
        self.assertTrue(result.Status.startswith("Available"), result.Status)
        result.Proxy.getObservations(result)
        raw = result.ObservationData
        document_path = self.output / "native-observation.FCStd"
        self.doc.recompute()
        self.doc.saveAs(str(document_path))
        case_path = self.output / "cold-case.json"
        report_path = self.output / "cold-report.json"
        case_path.write_text(
            json.dumps(
                {
                    "document": str(document_path),
                    "result": result.Name,
                    "analysis": model.analysis.Name,
                    "solver": model.solver.Name,
                    "accounting": model.accounting.Name,
                    "mesh": model.mesh.Name,
                    "raw_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                    "native_mesh_identity": native_mesh_identity(model.mesh),
                    "report": str(report_path),
                    "version": App.Version(),
                }
            )
        )
        App.closeDocument(self.doc.Name)
        self.doc = None
        executable = Path(App.ConfigGet("BinPath")) / (
            "FreeCADCmd.exe" if os.name == "nt" else "FreeCADCmd"
        )
        self.assertTrue(executable.is_file(), str(executable))
        child = self.output / "cold-process"
        child.mkdir()
        environment = dict(os.environ)
        for key, subdirectory in (
            ("FREECAD_USER_HOME", "user"),
            ("FREECAD_USER_DATA", "data"),
            ("FREECAD_USER_TEMP", "temp"),
            ("XDG_CONFIG_HOME", "xdg-config"),
            ("XDG_DATA_HOME", "xdg-data"),
            ("XDG_CACHE_HOME", "xdg-cache"),
        ):
            path = child / subdirectory
            path.mkdir()
            environment[key] = str(path)
        environment.update(
            FREECAD_CONTACT_OBSERVATION_COLD_CASE=str(case_path),
            PYTHONDONTWRITEBYTECODE="1",
            PYTHONNOUSERSITE="1",
            TMPDIR=str(child / "temp"),
        )
        command = [
            str(executable),
            "-u",
            str(child / "user.cfg"),
            "-s",
            str(child / "system.cfg"),
            "-P",
            str(Path(__file__).parent),
            "--run-test",
            "test_contact_observation_native._ColdObservationWitness",
        ]
        completed = subprocess.run(
            command,
            env=environment,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        log = completed.stdout + completed.stderr
        (child / "run.log").write_text(log)
        self.assertEqual(completed.returncode, 0, log)
        report = json.loads(report_path.read_text())
        self.assertTrue(report["historical_until_explicit_refresh"])
        self.assertEqual(report["raw_sha256"], hashlib.sha256(raw.encode()).hexdigest())
        self.assertTrue(report["fresh_native_run_available"])

    def test_conformal_independent_owned_nodes_keep_original_id_controls(self):
        model = self.make_native_nonconformal_source(conformal=True)
        self.assertNotEqual(model.slave_node, model.master_node)
        result = self.make_available_observation(model)
        row = result.Proxy.getObservations(result)["contacts"][0]
        frd = Path(model.fea.inp_file_name).with_suffix(".frd")
        field = read_frd_result(str(frd))["Results"][-1]["disp"]
        for side, node in (("slave", model.slave_node), ("master", model.master_node)):
            with self.subTest(side=side):
                self.assertEqual(row[side]["status"], "AVAILABLE")
                self.assertEqual(row[side]["method"], "ORIGINAL_NODE")
                self.assertIn(node, row[side]["source_node_ids"])
                self.assertEqual(row[side]["value_mm"], list(field[node]))

    def test_changed_model_contact_and_source_bytes_reject_cached_values(self):
        model = self.make_native_nonconformal_source()
        result = self.make_available_observation(model)
        raw = result.ObservationData
        material = dict(model.material.Material)
        changed = dict(material, YoungsModulus="210000 MPa")
        model.material.Material = changed
        with self.assertRaises(ValueError):
            result.Proxy.getObservations(result)
        self.assertEqual(result.ObservationData, raw)
        model.material.Material = material
        result.Proxy.refresh(result)
        self.assertTrue(result.Status.startswith("Available"), result.Status)
        references = list(model.contact.References)
        model.contact.References = list(reversed(references))
        with self.assertRaises(ValueError):
            result.Proxy.getObservations(result)
        self.assertEqual(result.ObservationData, raw)
        model.contact.References = references
        result.Proxy.refresh(result)
        self.assertTrue(result.Status.startswith("Available"), result.Status)
        frd = Path(model.fea.inp_file_name).with_suffix(".frd")
        original = frd.read_bytes()
        try:
            frd.write_bytes(original + b"\n")
            with self.assertRaises(ValueError):
                result.Proxy.getObservations(result)
            self.assertEqual(result.ObservationData, raw)
        finally:
            frd.write_bytes(original)
        result.Proxy.refresh(result)
        self.assertTrue(result.Status.startswith("Available"), result.Status)
        result.Proxy.getObservations(result)

    def test_foreign_document_inputs_are_rejected_without_creating_a_result(self):
        model = self.make_native_nonconformal_source()
        foreign = App.newDocument("ForeignObservationInputs")
        try:
            before = [obj.Name for obj in foreign.Objects]
            for analysis, accounting, contacts in (
                (model.analysis, None, []),
                (None, model.accounting, []),
                (None, None, [model.contact]),
            ):
                with self.subTest(analysis=analysis, accounting=accounting, contacts=contacts):
                    with self.assertRaises(ValueError):
                        ObjectsFem.makeResultContactObservation(
                            foreign, analysis, accounting, contacts
                        )
                    self.assertEqual([obj.Name for obj in foreign.Objects], before)
        finally:
            App.closeDocument(foreign.Name)

    def test_native_sampler_failure_withdraws_availability_and_preserves_history(self):
        model = self.make_native_nonconformal_source()
        result = self.make_available_observation(model)
        raw = result.ObservationData
        # This is an external native algorithm boundary, not an ownership,
        # source-reader or interpolation implementation double.
        with patch(
            "femresult.owned_probe.vtkPointData",
            side_effect=RuntimeError("Native VTK factory unavailable"),
        ):
            result.Proxy.refresh(result)
        self.assertTrue(result.Status.startswith("Unavailable"), result.Status)
        self.assertEqual(result.ObservationData, raw)
        with self.assertRaises(ValueError):
            result.Proxy.getObservations(result)


# This witness exists only in the explicitly launched child. Normal parent
# discovery does not add a hidden skipped test or recursively run the solver.
if os.environ.get("FREECAD_CONTACT_OBSERVATION_COLD_CASE"):

    class _ColdObservationWitness(unittest.TestCase):
        def test_historical_literal_and_explicit_revalidation(self):
            case = json.loads(Path(os.environ["FREECAD_CONTACT_OBSERVATION_COLD_CASE"]).read_text())
            self.assertEqual(App.Version(), case["version"])
            document = App.openDocument(case["document"])
            try:
                result = document.getObject(case["result"])
                raw = result.ObservationData
                digest = hashlib.sha256(raw.encode()).hexdigest()
                self.assertEqual(digest, case["raw_sha256"])
                self.assertTrue(result.Status.startswith("Historical"), result.Status)
                with self.assertRaises(ValueError):
                    result.Proxy.getObservations(result)
                document.recompute()
                self.assertTrue(result.Status.startswith("Historical"), result.Status)
                self.assertEqual(result.ObservationData, raw)
                with self.assertRaises(ValueError):
                    result.Proxy.getObservations(result)
                identity = native_mesh_identity(document.getObject(case["mesh"]))
                result.Proxy.refresh(result)
                if identity == case["native_mesh_identity"]:
                    self.assertTrue(result.Status.startswith("Available"), result.Status)
                    data = result.Proxy.getObservations(result)
                    self.assertEqual(data["schema"], "FreeCAD.CONTACT_SIDE_OBSERVATION_V1")
                    revalidated = True
                else:
                    self.assertTrue(result.Status.startswith("Unavailable"), result.Status)
                    self.assertEqual(result.ObservationData, raw)
                    with self.assertRaises(ValueError):
                        result.Proxy.getObservations(result)
                    revalidated = False
                # Native FCStd persistence may assign different original mesh
                # IDs. Only a fresh ordinary writer/solver run can bind those
                # current IDs; never repair or remap the historical field.
                before_run = native_mesh_identity(document.getObject(case["mesh"]))
                analysis = document.getObject(case["analysis"])
                solver = document.getObject(case["solver"])
                fresh = Path(case["report"]).parent / "cold-fresh-native-run"
                fresh.mkdir()
                fea = FemToolsCcx(analysis=analysis, solver=solver)
                fea.update_objects()
                fea.setup_working_dir(str(fresh))
                fea.write_inp_file()
                self.assertEqual(fea.ccx_run(), 0, fea.ccx_stdout + fea.ccx_stderr)
                created = [
                    obj
                    for obj in analysis.Group
                    if isinstance(getattr(obj, "Proxy", None), force_accounting.AccountingResult)
                    and obj.Name != case["accounting"]
                ]
                self.assertEqual(len(created), 1)
                self.assertEqual(result.AccountingResult.Name, case["accounting"])
                self.assertEqual(native_mesh_identity(document.getObject(case["mesh"])), before_run)
                result.AccountingResult = created[0]
                result.Proxy.refresh(result)
                self.assertTrue(result.Status.startswith("Available"), result.Status)
                refreshed = result.Proxy.getObservations(result)
                self.assertEqual(refreshed["source"]["accounting"]["name"], created[0].Name)
                self.assertEqual(
                    Path(refreshed["source"]["frd"]["path"]).parent.resolve(), fresh.resolve()
                )
                Path(case["report"]).write_text(
                    json.dumps(
                        {
                            "historical_until_explicit_refresh": True,
                            "raw_sha256": digest,
                            "native_ids_unchanged": identity == case["native_mesh_identity"],
                            "explicit_refresh_available": revalidated,
                            "fresh_native_run_available": True,
                        }
                    )
                )
            finally:
                App.closeDocument(document.Name)
