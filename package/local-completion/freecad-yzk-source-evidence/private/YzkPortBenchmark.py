# SPDX-License-Identifier: LGPL-2.1-or-later
"""One public connector-resolution timing pass on an immutable saved model.

Root alone runs this module inside serial FreeCAD with fresh isolated profiles.
No writer, solver, mesher, save, recompute, model edit, private API, cache
injection or native-accounting force calculation is performed. Results are
performance/correctness observations, not a fresh physical solve.
"""
import sys
sys.dont_write_bytecode = True

import hashlib
import json
import math
import os
from pathlib import Path
import time
import traceback
import unittest

import FreeCAD as App
from femtools import elastic_connector


ROOT = Path(__file__).resolve().parent
MODEL_ROOT = ROOT / 'repro-v2/physical-red-2/witness'
PINS = {
    '65-moving-ports.FCStd': '9932139f779a3a6cd929c4e26772f43d9e1c3c9896bf106acb83862337cdeb16',
    'port-membership.json': '197fc173b907e815209b32313af523f5996e18ea6deeeb917ebcdae31011d8e4',
    'probe.json': '683a0636ead7126ced591afd479f66752b1e82da886e4ed3baeeccc467422bfe',
    'native/Mesh.inp': '07f0858349d83a4cfb0915947aa443b06e99e2864ea74c82f7d2d171b0896387',
    'native/Mesh.accounting': '78e5c5a2b0387ba1a229a5497860d1842477a4f9af60f1f0b8c7c7872262c905',
}
EXPECTED_NAMES = [f'Spring{arm:02d}{kind}{axis}'
    for arm in (1, 2) for kind in ('T', 'R') for axis in 'XYZ']
EXPECTED_NATIVE_IDS = {'Hub': [18497, 18498], 'ArmPort01': [18499, 18500],
                       'ArmPort02': [18501, 18502]}


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def plain(value):
    if isinstance(value, (str, bool, int, float)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted(plain(item) for item in value)
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    if isinstance(value, App.Vector):
        return [value.x, value.y, value.z]
    if isinstance(value, App.Rotation):
        return list(value.Q)
    if isinstance(value, App.Placement):
        return {'base': plain(value.Base), 'rotation': plain(value.Rotation)}
    if hasattr(value, 'Name') and hasattr(value, 'Document'):
        return {'object': value.Name, 'document': value.Document.Name}
    if hasattr(value, 'Value') and hasattr(value, 'Unit'):
        return {'value': value.Value, 'unit': str(value.Unit)}
    raise TypeError('Unrecorded public result value: ' + type(value).__name__)


def input_pins():
    return {str(MODEL_ROOT / name): sha(MODEL_ROOT / name) for name in PINS}


def snapshot(doc, mesh):
    """Selected persistent inputs, read without materializing FemMesh.Nodes."""
    names = ('References', 'ReferenceNode', 'Displacement', 'Rotation', 'Placement',
        *('TranslationalMode' + axis for axis in 'XYZ'),
        *('RotationalMode' + axis for axis in 'XYZ'),
        'Attachment', 'Mode', 'Kind', 'Axis', 'Orientation', 'OrientationReference',
        'RigidBody1', 'RigidBody2', 'Stiffness', 'RotationalStiffness',
        'NativeForceAccounting', 'NativeAccountingSolver', 'NativeAccountingSupports',
        'Material', 'Force', 'Direction', 'Reversed', 'Shape')
    objects = {}
    for obj in doc.Objects:
        values = {}
        for name in names:
            if name not in obj.PropertiesList:
                continue
            value = getattr(obj, name)
            if name == 'Shape' and hasattr(value, 'Solids') and hasattr(value, 'BoundBox'):
                values[name] = {'solids': len(value.Solids), 'volume': value.Volume,
                    'area': value.Area, 'bound_box': [value.BoundBox.XMin, value.BoundBox.YMin,
                        value.BoundBox.ZMin, value.BoundBox.XMax, value.BoundBox.YMax, value.BoundBox.ZMax]}
            else:
                values[name] = plain(value)
        objects[obj.Name] = {'type': obj.TypeId, 'properties': values}
    return {'objects': objects, 'mesh_node_count': mesh.FemMesh.NodeCount,
            'mesh_volume_count': mesh.FemMesh.VolumeCount}


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                                   separators=(',', ':')).encode()).hexdigest()


class PublicPortResolutionBenchmark(unittest.TestCase):
    def test_twelve_real_scalar_connectors_resolve_without_changing_the_model(self):
        output = Path(os.environ['YZK_OUTPUT']) / 'port-benchmark.json'
        self.assertFalse(output.exists())
        module = Path(elastic_connector.__file__).resolve()
        home = Path(App.getHomePath()).resolve()
        self.assertTrue(module.is_relative_to(home), 'Connector module is not the actual application/build module')
        before = input_pins()
        for name, wanted in PINS.items():
            self.assertEqual(before[str(MODEL_ROOT / name)], wanted)
        historical = json.loads((MODEL_ROOT / 'probe.json').read_text())
        self.assertEqual(historical['solver_returncode'], 201)
        self.assertEqual(historical['stage'], 'native_run')
        original_ids = {row[1]: [int(row[2]), int(row[3])] for row in historical['actual_PORT_declarations']}
        for name, expected in EXPECTED_NATIVE_IDS.items():
            self.assertEqual(original_ids[name], expected)
        regions = json.loads((MODEL_ROOT / 'port-membership.json').read_text())
        receipt = {'schema': 'FreeCAD-yzk-public-port-resolution-benchmark-v1', 'passed': False,
            'runtime': App.Version(), 'application_home': str(home),
            'public_module': {'path': str(module), 'sha256': sha(module)},
            'benchmark_module': {'path': str(Path(__file__).resolve()), 'sha256': sha(__file__)},
            'inputs_before': before, 'selected_connectors': EXPECTED_NAMES,
            'timings': [], 'no_resolve_warmup_or_repeated_connector_call': True,
            'native_ID_query_excluded_from_resolution_timing': True,
            'no_solve_writer_mesher_recompute_save_or_model_edit': True,
            'scope': 'Public API performance/correctness only, not fresh native physics or engineering acceptance',
            'Oomakhi_accessed_or_solved': False, 'engineering_or_BIM_accepted': False}
        doc = None
        try:
            started = time.perf_counter()
            doc = App.openDocument(str(MODEL_ROOT / '65-moving-ports.FCStd'))
            receipt['cold_document_load_seconds'] = time.perf_counter() - started
            analysis, mesh = doc.getObject('Analysis'), doc.getObject('Mesh')
            self.assertIsNotNone(analysis)
            self.assertIsNotNone(mesh)
            self.assertEqual(mesh.FemMesh.NodeCount, historical['physical_mesh_nodes'])
            self.assertEqual(mesh.FemMesh.VolumeCount, historical['physical_volume_elements'])
            connectors = [item for item in analysis.Group if item.Name.startswith('Spring')
                and {'RigidBody1', 'RigidBody2', 'Attachment', 'Kind', 'Axis'} <= set(item.PropertiesList)]
            self.assertEqual(len(connectors), 384)
            selected = connectors[:12]
            self.assertEqual([obj.Name for obj in selected], EXPECTED_NAMES)
            model_before = snapshot(doc, mesh)
            receipt['model_before_sha256'] = canonical_sha(model_before)
            records = []
            for obj in selected:
                # Only this public call is timed, once per connector. Results
                # are retained and checked afterwards, not used as an oracle.
                tick = time.perf_counter()
                data = elastic_connector.resolve_connector(obj, mesh, analysis)
                elapsed = time.perf_counter() - tick
                receipt['timings'].append({'connector': obj.Name, 'seconds': elapsed})
                records.append((obj, data))
            receipt['resolve_total_seconds'] = sum(row['seconds'] for row in receipt['timings'])
            receipt['resolve_each_seconds'] = [row['seconds'] for row in receipt['timings']]
            results = {}
            for obj, data in records:
                arm = 'ArmPort' + obj.Name[6:8]
                expected_bodies = [doc.getObject('Hub'), doc.getObject(arm)]
                self.assertEqual(data['bodies'], expected_bodies)
                self.assertEqual(data['regions'], [set(regions['Hub']), set(regions[arm])])
                self.assertEqual(data['nodes'], [])
                self.assertEqual(obj.Attachment, 'Rigid body ports')
                self.assertEqual(obj.Mode, 'Two points')
                self.assertEqual(obj.Axis, obj.Name[-1])
                rotational = obj.Name[-2] == 'R'
                self.assertEqual(data['rotational'], rotational)
                self.assertEqual(data['stiffness'], 6000 if rotational else 1200)
                self.assertEqual(obj.Kind, 'Rotational' if rotational else 'Translational')
                for axis, vector in zip('XYZ', (App.Vector(1, 0, 0), App.Vector(0, 1, 0), App.Vector(0, 0, 1))):
                    self.assertLess((data['rotation'].multVec(vector) - vector).Length, 1e-12, axis)
                results[obj.Name] = plain(data)
            receipt['queried_result_dictionaries'] = results
            tick = time.perf_counter()
            native_ids = {name: list(elastic_connector.rigid_body_node_ids(analysis, mesh, doc.getObject(name)))
                          for name in EXPECTED_NATIVE_IDS}
            receipt['public_native_ID_query_seconds'] = time.perf_counter() - tick
            self.assertEqual(native_ids, EXPECTED_NATIVE_IDS)
            receipt['public_native_ID_outputs'] = native_ids
            receipt['model_after_sha256'] = canonical_sha(snapshot(doc, mesh))
            self.assertEqual(receipt['model_after_sha256'], receipt['model_before_sha256'])
            self.assertEqual(sha(module), receipt['public_module']['sha256'])
            self.assertTrue(all(math.isfinite(row['seconds']) and row['seconds'] >= 0 for row in receipt['timings']))
            receipt.update(passed=True, result_dictionary_sha256=canonical_sha(results))
        except BaseException as error:
            receipt['error'] = {'type': type(error).__name__, 'message': str(error), 'traceback': traceback.format_exc()}
            raise
        finally:
            receipt['inputs_after'] = input_pins()
            receipt['frozen_model_and_original_evidence_unchanged'] = receipt['inputs_before'] == receipt['inputs_after']
            receipt['passed'] &= receipt['frozen_model_and_original_evidence_unchanged']
            if doc is not None and doc.Name in App.listDocuments():
                App.closeDocument(doc.Name)
            with output.open('x') as stream:
                json.dump(receipt, stream, indent=2, sort_keys=True, allow_nan=False)
                stream.write('\n')
        self.assertTrue(receipt['passed'])
