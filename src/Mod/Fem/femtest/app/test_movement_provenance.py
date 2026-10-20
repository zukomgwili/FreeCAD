# SPDX-License-Identifier: LGPL-2.1-or-later
"""Fresh solver-output custody through the ordinary native accounting lifecycle.

The small executable is a subprocess-boundary fixture, not a CalculiX accuracy
witness. These tests do not interpret displacement or establish design acceptance.
"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import FreeCAD
import Fem
import ObjectsFem
import Part

from femtools import ccxtools, force_accounting


@unittest.skipUnless(os.name == "posix", "Executable subprocess fixture needs POSIX")
class TestMovementProvenance(unittest.TestCase):
    def setUp(self):
        self.doc = FreeCAD.newDocument("MovementProvenanceTest")
        self.scratch = tempfile.TemporaryDirectory()
        self.root = Path(self.scratch.name).resolve()
        geometry = self.doc.addObject("Part::Feature", "Geometry")
        geometry.Shape = Part.makeBox(1, 1, 1)
        analysis = ObjectsFem.makeAnalysis(self.doc)
        mesh = ObjectsFem.makeMeshGmsh(self.doc)
        mesh.Shape = geometry
        tetra = Fem.FemMesh()
        for point in ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)):
            tetra.addNode(*point)
        tetra.addVolume([1, 2, 3, 4])
        mesh.FemMesh = tetra
        solver = ObjectsFem.makeSolverCalculiXCcxTools(self.doc)
        solver.NativeForceAccounting = True
        for obj in (mesh, solver):
            analysis.addObject(obj)
        self.doc.recompute()
        self.fea = ccxtools.FemToolsCcx(analysis, solver, test_mode=True)
        self.fea.mesh = mesh
        self.fea.inp_file_name = str(self.root / "model.inp")
        self.frd = self.root / "model.frd"
        deck = Path(self.fea.inp_file_name)
        request = deck.with_suffix(".accounting")
        deck.write_text("*HEADING\nSynthetic subprocess custody fixture\n")
        request.write_text(force_accounting.SCHEMA + "\nSUPPORT R 1 2\nEND\n")
        metadata = {
            "schema": force_accounting.SCHEMA,
            "expected": [["SUPPORT", "R"]],
            "deck_sha256": hashlib.sha256(deck.read_bytes()).hexdigest(),
            "request_sha256": hashlib.sha256(request.read_bytes()).hexdigest(),
            "model_digest": force_accounting._model_digest(analysis, mesh),
            "analysis": analysis.Name,
            "mesh": mesh.Name,
            "end_time": 1.0,
        }
        Path(str(request) + ".json").write_text(json.dumps(metadata))

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)
        self.scratch.cleanup()

    def engine(self, body="", *, capacity=False, capacity_echo=None):
        """Use a real child process at the solver executable boundary."""
        executable = self.root / "synthetic-solver"
        python = shutil.which("python3") or shutil.which("python")
        if python is None:
            self.skipTest("Subprocess fixture needs a Python interpreter")
        capacity_code = ""
        if capacity:
            capacity_code = (
                "budget = int(os.environ.get('CCX_FORCE_ACCOUNTING_MAX_DECLARATIONS', '65536'))\n"
                "if sys.argv[1:] == ['--freecad-force-accounting-capacity']:\n"
                "    print(json.dumps({'schema': 'CCX_FORCE_ACCOUNTING_CAPACITY_V1',\n"
                f"        'request_schema': {force_accounting.SCHEMA!r}, 'allocation': 'dynamic',\n"
                "        'counting_policy': 'top-level-declarations-v1', 'total_records': budget,\n"
                "        'limits': dict.fromkeys("
                "('supports','bodies','ports','angles','springs'), budget)}))\n"
                "    sys.exit(0)\n"
            )
            capacity_code += (
                "print('CCX_FORCE_ACCOUNTING_CAPACITY_APPLIED_V1 ' + "
                "json.dumps({'budget': budget,\n"
                "    'counts': {'supports':1,'bodies':0,'ports':1,"
                "'angles':0,'springs':0}, 'total':2}))\n"
                if capacity_echo is None
                else f"sys.stdout.write({capacity_echo!r})\n"
            )
        else:
            capacity_code = (
                "if sys.argv[1:] == ['--freecad-force-accounting-capacity']:\n"
                "    print('*ERROR in readinput: cannot open file "
                "--freecad-force-accounting-capacity.inp')\n"
                "    sys.exit(201)\n"
            )
        executable.write_text(
            f"#!{python}\n"
            "import os, sys, json\n"
            "from pathlib import Path\n"
            "if sys.argv[1:] == ['--freecad-force-accounting-version']:\n"
            f"    print({force_accounting.SCHEMA!r})\n"
            "    sys.exit(0)\n"
            + capacity_code
            + "request = Path(os.environ['CCX_FORCE_ACCOUNTING_REQUEST'])\n"
            "Path(str(request) + '.out').write_text(\n"
            f"    '{force_accounting.SCHEMA}\\nSTATE 1 1 1\\n'\n"
            "    'SUPPORT R 0 0 2 4 -6 0\\nEND\\n')\n" + body
        )
        executable.chmod(0o700)
        self.fea.ccx_binary = str(executable)

    def capacity_request(self):
        """Literal subprocess-boundary request, not a structural solver fixture."""
        self.fea.solver.NativeAccountingSolver = self.fea.ccx_binary
        if self.doc.getObject("R") is None:
            support = ObjectsFem.makeConstraintRigidBody(self.doc, "R")
            support.References = [(self.doc.getObject("Geometry"), ["Face1"])]
            self.fea.analysis.addObject(support)
        request = Path(self.fea.inp_file_name).with_suffix(".accounting")
        request.write_text(force_accounting.SCHEMA + "\nPORT R 1 2\nSUPPORT R 1 2\nEND\n")
        metadata_path = Path(str(request) + ".json")
        metadata = json.loads(metadata_path.read_text())
        metadata["request_sha256"] = hashlib.sha256(request.read_bytes()).hexdigest()
        metadata["model_digest"] = force_accounting._model_digest(self.fea.analysis, self.fea.mesh)
        with mock.patch.dict(os.environ, {"CCX_FORCE_ACCOUNTING_MAX_DECLARATIONS": "2"}):
            metadata["capacity"] = force_accounting.capacity_preflight(
                self.fea.analysis, self.fea.solver, binary=self.fea.ccx_binary
            )
        self.assertEqual(metadata["capacity"]["total"], 2)
        metadata_path.write_text(json.dumps(metadata))
        return request

    def test_changed_capacity_requires_reexport_before_launch_or_output_quarantine(self):
        """A real child query changes; prior output must survive the refusal."""
        launched = self.root / "was-launched"
        self.engine(
            "request.with_name('was-launched').write_text('entered solver')\n", capacity=True
        )
        request = self.capacity_request()
        old_frd = b"Retained previous FRD\n"
        self.frd.write_bytes(old_frd)
        old_output = request.with_name(request.name + ".out")
        old_output.write_bytes(b"Retained previous accounting\n")
        with mock.patch.dict(os.environ, {"CCX_FORCE_ACCOUNTING_MAX_DECLARATIONS": "3"}):
            with self.assertRaisesRegex(ValueError, "capacity.*changed.*rewrite"):
                self.fea.start_ccx()
        self.assertFalse(launched.exists())
        self.assertEqual(self.frd.read_bytes(), old_frd)
        self.assertEqual(old_output.read_bytes(), b"Retained previous accounting\n")
        self.assertFalse(any(hasattr(obj, "AccountingData") for obj in self.fea.analysis.Group))

    def test_capacity_echo_must_match_owned_child_before_current_import(self):
        marker = "CCX_FORCE_ACCOUNTING_CAPACITY_APPLIED_V1 "
        valid = (
            marker
            + json.dumps(
                {
                    "budget": 2,
                    "counts": {"supports": 1, "bodies": 0, "ports": 1, "angles": 0, "springs": 0},
                    "total": 2,
                }
            )
            + "\n"
        )
        wrong = valid.replace('"ports": 1', '"ports": 0')
        malformed = (
            marker
            + json.dumps(
                {
                    "budget": 2,
                    "counts": ["supports", "bodies", "ports", "angles", "springs"],
                    "total": 2,
                }
            )
            + "\n"
        )
        for label, echo in (
            ("missing", ""),
            ("wrong", wrong),
            ("duplicate", valid + valid),
            ("malformed", malformed),
        ):
            with self.subTest(label=label):
                self.engine(
                    "request.with_suffix('.frd').write_bytes(b'fresh unit FRD\\n')\n",
                    capacity=True,
                    capacity_echo=echo,
                )
                self.capacity_request()
                with mock.patch.dict(os.environ, {"CCX_FORCE_ACCOUNTING_MAX_DECLARATIONS": "2"}):
                    with self.assertRaisesRegex(ValueError, "applied.*capacity"):
                        self.fea.start_ccx()
                self.assertFalse(
                    any(hasattr(obj, "AccountingData") for obj in self.fea.analysis.Group)
                )

    def test_legacy_export_still_refuses_current_budget_before_quarantine(self):
        self.engine(capacity=True)
        request = Path(self.fea.inp_file_name).with_suffix(".accounting")
        request.write_text(force_accounting.SCHEMA + "\nPORT R 1 2\nSUPPORT R 1 2\nEND\n")
        metadata_path = Path(str(request) + ".json")
        metadata = json.loads(metadata_path.read_text())
        metadata["request_sha256"] = hashlib.sha256(request.read_bytes()).hexdigest()
        self.assertNotIn("capacity", metadata)
        metadata_path.write_text(json.dumps(metadata))
        self.frd.write_bytes(b"Retained old FRD\n")
        output = Path(str(request) + ".out")
        output.write_bytes(b"Retained old accounting\n")
        with mock.patch.dict(os.environ, {"CCX_FORCE_ACCOUNTING_MAX_DECLARATIONS": "1"}):
            with self.assertRaisesRegex(ValueError, "capacity exceeded.*total required 2"):
                self.fea.start_ccx()
        self.assertEqual(self.frd.read_bytes(), b"Retained old FRD\n")
        self.assertEqual(output.read_bytes(), b"Retained old accounting\n")

    def accounting(self):
        return next(obj for obj in self.fea.analysis.Group if hasattr(obj, "AccountingData"))

    def test_success_without_new_frd_preserves_old_without_binding_movement(self):
        old_bytes = b"Previous run's displacement; never accepted as current\n"
        self.frd.write_bytes(old_bytes)
        self.engine()
        self.assertEqual(self.fea.start_ccx(), 0)
        result = self.accounting()
        self.assertTrue(result.Status.startswith("Current native accounting"))
        source = json.loads(result.AccountingData)["movement_source"]
        self.assertEqual(source["status"], "UNAVAILABLE")
        self.assertIn("no fresh", source["reason"].lower())
        self.assertFalse(self.frd.exists())
        self.assertEqual(Path(source["recovery_path"]).read_bytes(), old_bytes)

    def test_fresh_frd_binds_exact_bytes_and_requested_state_not_qualified_field(self):
        self.engine("request.with_suffix('.frd').write_bytes(b'fresh FRD fixture\\n')\n")
        self.assertEqual(self.fea.start_ccx(), 0)
        data = json.loads(self.accounting().AccountingData)
        source = data["movement_source"]
        self.assertEqual(source["schema"], "FREECAD_MOVEMENT_SOURCE_V1")
        self.assertEqual(source["status"], "BOUND")
        self.assertEqual(source["path"], str(self.frd))
        self.assertEqual(
            source["sha256"],
            "fc9996c8844eac50b646dd7743704a9b93980bf129c1e61bb555bc5d11704363",
        )
        self.assertEqual(source["requested_end_time"], 1.0)
        self.assertIn("must verify", source["time_basis"])
        self.assertIn("not qualified displacement", source["domain"])
        for name in ("deck_sha256", "request_sha256", "binary_sha256", "model_digest"):
            self.assertEqual(source[name], data[name])

    def test_output_replaced_after_child_completion_cannot_bind_movement(self):
        self.engine("request.with_suffix('.frd').write_bytes(b'fresh FRD fixture\\n')\n")
        context = force_accounting.run_context(self.fea, self.fea.ccx_binary)
        completed = subprocess.run(
            [self.fea.ccx_binary, "-i", "model"],
            env=context[0],
            cwd=self.root,
            check=False,
            timeout=10,
        )
        force_accounting.finish_run(context, completed.returncode)
        self.frd.write_bytes(b"Replacement after the solver has returned\n")
        # Repeated notification is not a second child process and cannot rebind
        # a replacement output to the completed run.
        force_accounting.finish_run(context, completed.returncode)
        result = force_accounting.import_result(self.fea, context)
        self.assertTrue(result.Status.startswith("Current native accounting"))
        source = json.loads(result.AccountingData)["movement_source"]
        self.assertEqual(source["status"], "UNAVAILABLE")
        self.assertIn("changed", source["reason"].lower())

    def test_failed_child_preserves_previous_frd_without_creating_current_result(self):
        self.frd.write_bytes(b"recoverable previous run\n")
        self.engine("sys.exit(7)\n")
        self.assertEqual(self.fea.start_ccx(), 7)
        self.assertFalse(self.frd.exists())
        recovered = list(self.root.glob(".model-previous-frd-*/model.frd"))
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].read_bytes(), b"recoverable previous run\n")
        self.assertFalse(any(hasattr(obj, "AccountingData") for obj in self.fea.analysis.Group))

    def test_failed_launch_preserves_previous_frd_without_restoring_it_as_current(self):
        self.frd.write_bytes(b"recoverable previous run\n")
        self.engine()
        original = subprocess.Popen

        def launch(command, *args, **kwargs):
            if "-i" in command:
                raise OSError("Synthetic solver launch failure")
            return original(command, *args, **kwargs)

        with mock.patch.object(subprocess, "Popen", side_effect=launch):
            with self.assertRaisesRegex(OSError, "Synthetic solver launch failure"):
                self.fea.start_ccx()
        self.assertFalse(self.frd.exists())
        recovered = list(self.root.glob(".model-previous-frd-*/model.frd"))
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].read_bytes(), b"recoverable previous run\n")

    def test_existing_symlink_output_is_refused_without_touching_its_target(self):
        other = self.root / "user-result.frd"
        other.write_bytes(b"user data must not change\n")
        self.frd.symlink_to(other)
        self.engine()
        with self.assertRaisesRegex(ValueError, "regular.*not a symlink"):
            self.fea.start_ccx()
        self.assertTrue(self.frd.is_symlink())
        self.assertEqual(other.read_bytes(), b"user data must not change\n")

    def test_unfinished_context_and_legacy_context_cannot_attest_existing_frd(self):
        self.engine()
        context = force_accounting.run_context(self.fea, self.fea.ccx_binary)
        subprocess.run(
            [self.fea.ccx_binary, "-i", "model"],
            env=context[0],
            cwd=self.root,
            check=True,
            timeout=10,
        )
        self.frd.write_bytes(b"not bound to a completed run\n")
        result = force_accounting.import_result(self.fea, context)
        source = json.loads(result.AccountingData)["movement_source"]
        self.assertEqual(source["status"], "UNAVAILABLE")
        self.assertIn("No successful completed", source["reason"])
        legacy = (context[0], dict(context[1]), context[2])
        historical = force_accounting.import_result(self.fea, legacy)
        source = json.loads(historical.AccountingData)["movement_source"]
        self.assertEqual(source["status"], "UNAVAILABLE")
        self.assertIn("Legacy accounting", source["reason"])
        self.assertTrue(historical.Status.startswith("Current native accounting"))

    def test_save_restore_keeps_exact_source_history_but_never_current_status(self):
        self.engine("request.with_suffix('.frd').write_bytes(b'fresh FRD fixture\\n')\n")
        self.assertEqual(self.fea.start_ccx(), 0)
        result = self.accounting()
        data, name = result.AccountingData, result.Name
        path = str(self.root / "accounting.FCStd")
        self.doc.saveAs(path)
        FreeCAD.closeDocument(self.doc.Name)
        self.doc = FreeCAD.openDocument(path)
        restored = self.doc.getObject(name)
        self.assertEqual(restored.AccountingData, data)
        self.assertTrue(restored.Status.startswith("Stale after restore"))

    def test_dotted_input_name_runs_exact_requested_deck_not_neighboring_deck(self):
        for suffix in (".inp", ".accounting", ".accounting.json"):
            (self.root / ("model" + suffix)).rename(self.root / ("model.v1" + suffix))
        self.fea.inp_file_name = str(self.root / "model.v1.inp")
        self.frd = self.root / "model.v1.frd"
        (self.root / "model.inp").write_text("Do not solve this neighboring deck\n")
        self.engine(
            "selected = Path(sys.argv[sys.argv.index('-i') + 1] + '.inp')\n"
            "if selected.read_bytes() != request.with_suffix('.inp').read_bytes():\n"
            "    sys.exit(19)\n"
            "request.with_suffix('.frd').write_bytes(b'fresh FRD fixture\\n')\n"
        )
        self.assertEqual(self.fea.start_ccx(), 0)
        source = json.loads(self.accounting().AccountingData)["movement_source"]
        self.assertEqual(source["status"], "BOUND")
        self.assertEqual(source["deck"], str(self.root / "model.v1.inp"))
        self.assertEqual(source["path"], str(self.frd))
