"""One native capacity tracer: 65 genuine free finite-face RBE ports.

Separate generic support-only fixture. Not an edit/replay of ywu or Oomakhi;
no BODY/cut/contact or production-engineering acceptance is claimed here.
"""
import sys
sys.dont_write_bytecode = True
import hashlib
import json
import os
from pathlib import Path
import re
import traceback
import unittest

import FreeCAD as App
import ObjectsFem
import Part
from femmesh import gmshtools
from femtools.ccxtools import FemToolsCcx

NATIVE_SHA = '2d59adb06736801f730de077a5f3dbfcfba8c0a430636e5814e5582606b5c89b'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    with Path(path).open('x') as stream:
        stream.write(json.dumps(value, indent=2) + '\n')


class PortCapacityWitness(unittest.TestCase):
    def test_stock_native_model_can_account_for_65_moving_ports(self):
        output = Path(os.environ['YZK_OUTPUT']) / 'witness'
        output.mkdir()
        for name in ('mesh', 'native'):
            (output / name).mkdir()
        definition = Path(__file__).with_name('fixture.json')
        receipt = {'passed': False, 'stage': 'construct', 'definition_sha256': sha(definition),
                   'scope': 'One installed stock-writer/native capacity tracer, support-only',
                   'expected_moving_ports': 65, 'expected_physical_solids': 65,
                   'no_deck_or_request_patching': True, 'Oomakhi_opened_or_solved': False,
                   'full_physical_or_engineering_qualification_claimed': False}
        doc = App.newDocument('Yzk65NativePorts')
        try:
            analysis = ObjectsFem.makeAnalysis(doc, 'Analysis')
            solver = ObjectsFem.makeSolverCalculiXCcxTools(doc, 'SolverCcxTools')
            solver.AnalysisType = 'static'
            solver.NativeForceAccounting = True
            solver.SplitInputWriter = False
            self.assertEqual(solver.NativeAccountingSolver, '')
            analysis.addObject(solver)
            shape = doc.addObject('Part::Feature', 'PhysicalSolids')
            # One ordinary-supported anchor, one loaded long arm and63 small
            # unloaded satellites. Every receiving region is a distinct face.
            anchor = Part.makeBox(10, 2, 2, App.Vector(0, 1, 2))
            arms = [Part.makeBox(10 if index == 0 else 2, 2, 2,
                                 App.Vector(20, 1 + 4 * index, 2)) for index in range(64)]
            shape.Shape = Part.makeCompound([anchor, *arms])
            doc.recompute()
            self.assertEqual(len(shape.Shape.Solids), 65)
            self.assertAlmostEqual(shape.Shape.Volume, 584, places=8)

            def face_at(x, y, direction):
                names = [f'Face{number}' for number, face in enumerate(shape.Shape.Faces, 1)
                         if (face.CenterOfMass - App.Vector(x, y, 3)).Length < 1e-8
                         and face.normalAt(0, 0).x * direction > 0.99]
                self.assertEqual(len(names), 1, (x, y, direction, names))
                self.assertAlmostEqual(shape.getSubObject(names[0]).Area, 4, places=8)
                return names[0]

            fixed = ObjectsFem.makeConstraintFixed(doc, 'ExternalFixedSupport')
            fixed.References = [(shape, [face_at(0, 2, -1)])]
            analysis.addObject(fixed)
            solver.NativeAccountingSupports = [fixed]
            material = ObjectsFem.makeMaterialSolid(doc, 'SyntheticMaterial')
            material.Material = {'Name': 'Yzk generic linear material', 'YoungsModulus': '20000 MPa',
                                 'PoissonRatio': '0.3', 'Density': '1 kg/m^3'}
            analysis.addObject(material)
            ports = []
            port_faces = {}
            for name, x, y, normal in [('Hub', 10, 2, 1)] + [
                    (f'ArmPort{index + 1:02d}', 20, 2 + 4 * index, -1) for index in range(64)]:
                port = ObjectsFem.makeConstraintRigidBody(doc, name)
                face = face_at(x, y, normal)
                port.References = [(shape, [face])]
                port.ReferenceNode = App.Vector(x, y, 3)
                port.Displacement, port.Rotation = App.Vector(), App.Rotation()
                for axis in 'XYZ':
                    setattr(port, 'TranslationalMode' + axis, 'Free')
                    setattr(port, 'RotationalMode' + axis, 'Free')
                analysis.addObject(port)
                ports.append(port)
                port_faces[name] = face
            for index, arm in enumerate(ports[1:], 1):
                for kind, prefix in (('Translational', 'T'), ('Rotational', 'R')):
                    for axis in 'XYZ':
                        item = ObjectsFem.makeConstraintElasticConnector(doc, f'Spring{index:02d}{prefix}{axis}')
                        item.Attachment, item.Mode = 'Rigid body ports', 'Two points'
                        item.Kind, item.Axis, item.Orientation = kind, axis, App.Rotation()
                        item.RigidBody1, item.RigidBody2 = ports[0], arm
                        if kind == 'Translational':
                            item.Stiffness = '1200 N/mm'
                        else:
                            item.RotationalStiffness = App.Units.Quantity('6000 N*mm/rad')
                        analysis.addObject(item)
            direction = doc.addObject('Part::Feature', 'AxialDirection')
            direction.Shape = Part.makeLine(App.Vector(), App.Vector(1, 0, 0))
            force = ObjectsFem.makeConstraintForce(doc, 'EndForce')
            force.References = [(shape, [face_at(30, 2, 1)])]
            force.Force, force.Direction, force.Reversed = '12 N', (direction, ['Edge1']), False
            analysis.addObject(force)
            receipt['stage'] = 'native_mesh'
            print('YZK_PROGRESS native mesh:65 solids,65 real moving face ports,384 scalar connectors', flush=True)
            mesh = ObjectsFem.makeMeshGmsh(doc, 'Mesh')
            mesh.Shape = shape
            mesh.ElementOrder, mesh.SecondOrderLinear, mesh.CoherenceMesh = '2nd', False, False
            mesh.CharacteristicLengthMax, mesh.CharacteristicLengthMin = 1.5, 0.75
            mesh.WorkingDirectory = str(output / 'mesh')
            analysis.addObject(mesh)
            doc.recompute()
            mesher = gmshtools.GmshTools(mesh)
            mesher.create_mesh()
            self.assertEqual(mesher.process.exitCode(), 0)
            self.assertEqual(mesher.process.exitStatus(), mesher.process.ExitStatus.NormalExit)
            self.assertGreater(mesh.FemMesh.VolumeCount, 0)
            owners = {name: set(mesh.FemMesh.getNodesByFace(shape.getSubObject(face)))
                      for name, face in port_faces.items()}
            seen = set()
            for name, nodes in owners.items():
                self.assertGreaterEqual(len(nodes), 3, name)
                self.assertFalse(seen.intersection(nodes), name)
                seen.update(nodes)
            write(output / 'port-membership.json', {name: sorted(nodes) for name, nodes in owners.items()})
            doc.saveAs(str(output / '65-moving-ports.FCStd'))
            receipt['stage'] = 'stock_export'
            fea = FemToolsCcx(analysis=analysis, solver=solver)
            fea.update_objects()
            fea.setup_working_dir(str(output / 'native'))
            fea.write_inp_file()
            deck, request = Path(fea.inp_file_name), Path(fea.inp_file_name).with_suffix('.accounting')
            deck_before, request_before = sha(deck), sha(request)
            declarations = [line.split() for line in request.read_text().splitlines() if line.startswith('PORT ')]
            self.assertEqual(request.read_text().splitlines()[0], 'CCX_FORCE_ACCOUNTING_V3')
            self.assertEqual(len(declarations), 65)
            self.assertEqual({row[1] for row in declarations}, {item.Name for item in ports})
            self.assertEqual(len({int(value) for row in declarations for value in row[2:]}), 130)
            stock_rbes = re.findall(r'^\*RIGID BODY, NSET=([^,]+), REF NODE=(\d+), ROT NODE=(\d+)\s*$',
                                   deck.read_text(), re.M | re.I)
            self.assertEqual({(name, ref, rot) for name, ref, rot in stock_rbes},
                             {(row[1], row[2], row[3]) for row in declarations})
            self.assertEqual(sum(line.startswith('SPRING ') for line in request.read_text().splitlines()), 384)
            receipt.update(stage='native_run', deck=str(deck), deck_sha256=deck_before,
                           request=str(request), request_sha256=request_before, actual_PORT_declarations=declarations,
                           physical_volume_elements=mesh.FemMesh.VolumeCount, physical_mesh_nodes=len(mesh.FemMesh.Nodes))
            print('YZK_PROGRESS stock export complete:65 uniquePORT declarations; running bundled solver', flush=True)
            code = fea.ccx_run()
            (output / 'native.stdout').write_text(fea.ccx_stdout)
            (output / 'native.stderr').write_text(fea.ccx_stderr)
            receipt.update(solver_returncode=code, actual_binary=str(fea.ccx_binary),
                           actual_binary_sha256=sha(fea.ccx_binary),
                           native_diagnostic=fea.ccx_stdout + '\n' + fea.ccx_stderr,
                           stock_deck_unchanged=sha(deck) == deck_before,
                           stock_request_unchanged=sha(request) == request_before)
            self.assertEqual(sha(fea.ccx_binary), NATIVE_SHA)
            self.assertTrue(receipt['stock_deck_unchanged'] and receipt['stock_request_unchanged'])
            self.assertEqual(code, 0, receipt['native_diagnostic'])
            # On the installed RED this is not reached. It is a minimal
            # support-only check, not full ywu/production qualification.
            results = [item for item in analysis.Group if getattr(getattr(item, 'Proxy', None), 'Type', None)
                       == 'Fem::NativeForceAccountingResult']
            self.assertEqual(len(results), 1)
            self.assertTrue(results[0].Status.startswith('Current'))
            receipt.update(stage='completed', passed=True, current_report_status=results[0].Status)
        except BaseException as error:
            receipt.update(error=repr(error), traceback=traceback.format_exc())
            raise
        finally:
            write(output / 'probe.json', receipt)
            if doc.Name in App.listDocuments():
                App.closeDocument(doc.Name)
