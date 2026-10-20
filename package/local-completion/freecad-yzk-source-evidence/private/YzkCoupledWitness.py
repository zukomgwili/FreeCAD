# SPDX-License-Identifier: LGPL-2.1-or-later
"""Public stock export/solve/import/save qualification of one frozen graph.

Root's serial bounded supervisor selects YZK_CASE=tracer or capacity. The
fixture, oracle and assertions are identical parameterized physical contracts;
no target writer/accounting implementation or private maths is imported here.
"""
import json
import math
import os
from pathlib import Path
import re
import traceback
import unittest

import FreeCAD as App
from feminout.importCcxFrdResults import read_frd_result
from femtools.ccxtools import FemToolsCcx

from YzkCoupledFixture import FROZEN, make_fixture, model_properties, plain, sha, write_json
from YzkNativeAudit import audit_export, parse_port_motion


ROOT = Path(__file__).resolve().parent


def input_pins():
    names = ('YzkCoupledFixture.py', 'YzkCoupledWitness.py', 'YzkNativeAudit.py',
             'YzkColdRestore.py', *('oracle/' + name for name in FROZEN))
    return {str(ROOT / name): sha(ROOT / name) for name in names}


def vector_check(checks, name, actual, reference, zero_scale, limit):
    actual, reference = list(actual), list(reference)
    if len(actual) != 3 or len(reference) != 3 or not all(math.isfinite(v) for v in actual + reference):
        raise AssertionError('Nonfinite or non-vector comparison: ' + name)
    norm, error = math.hypot(*reference), math.dist(actual, reference)
    scale = norm if norm else zero_scale
    if not math.isfinite(scale) or scale <= 0:
        raise AssertionError('Undeclared/nonpositive comparison scale: ' + name)
    row = {'name': name, 'actual': actual, 'reference': reference, 'reference_norm': norm,
        'error_norm': error, 'scale': scale, 'relative_error': error/scale,
        'limit': limit, 'passed': error <= limit*scale}
    checks.append(row)
    if not row['passed']:
        raise AssertionError(row)


def wrench_checks(checks, name, actual, reference, force_scale, moment_scale):
    if len(actual) != 6 or len(reference) != 6:
        raise AssertionError('Not a six-component original-origin wrench: ' + name)
    vector_check(checks, name + '/force', actual[:3], reference[:3], force_scale, 0.01)
    vector_check(checks, name + '/original-origin-moment', actual[3:], reference[3:], moment_scale, 0.01)


class CoupledFiniteFaceWitness(unittest.TestCase):
    def test_independent_head_ports_keep_the_complete_coupled_physical_graph(self):
        case = os.environ.get('YZK_CASE', 'tracer')
        self.assertIn(case, ('tracer', 'capacity'))
        rows_y, columns_z = (1, 1) if case == 'tracer' else (11, 12)
        output = Path(os.environ['YZK_OUTPUT']) / 'witness'
        checks = []
        receipt = {'schema': 'FreeCAD-yzk-coupled-native-witness-v1', 'passed': False,
            'case': case, 'rows_y': rows_y, 'columns_z': columns_z,
            'only_public_native_interfaces': True, 'no_deck_patches_or_mocks': True,
            'Oomakhi_accessed_or_solved': False, 'engineering_or_BIM_accepted': False,
            'frozen_oracle_sha256': FROZEN, 'inputs_before': input_pins(), 'checks': checks,
            'force_and_original_origin_moment_limit': 0.01, 'scalar_response_limit': 0.05,
            'local_generalized_force_and_couple_limit': 0.01, 'phase': 'before-fixture'}
        doc, fixture = App.newDocument('YzkCoupledFiniteFaceWitness'), None
        try:
            fixture = make_fixture(doc, output, rows_y=rows_y, columns_z=columns_z)
            receipt['phase'] = 'fixture-and-physical-mesh-proved'
            candidate = os.environ.get('YZK_CANDIDATE')
            if candidate:
                fixture.solver.NativeAccountingSolver = candidate
            receipt['explicit_candidate_override'] = candidate
            properties = model_properties(fixture.analysis, fixture.mesh)
            write_json(output / 'export-properties.json', properties)
            doc.recompute()
            before_document = output / 'coupled-before-export.FCStd'
            doc.saveAs(str(before_document))
            receipt['before_export_document_sha256'] = sha(before_document)

            fea = FemToolsCcx(analysis=fixture.analysis, solver=fixture.solver)
            fea.update_objects()
            fea.setup_working_dir(str(output / 'native'))
            receipt['phase'] = 'stock-writer-started'
            fea.write_inp_file()
            deck = Path(fea.inp_file_name)
            request = deck.with_suffix('.accounting')
            original_hashes = {'deck': sha(deck), 'request': sha(request)}
            receipt['deck'], receipt['request'] = str(deck), str(request)
            receipt['original_native_input_sha256'] = original_hashes
            receipt['phase'] = 'stock-writer-finished'
            export = audit_export(fixture, deck, request, deck.with_suffix('.accounting.out'))
            self.assertTrue(export['passed'])
            write_json(output / 'independent-export-audit.json', export)
            receipt['export_audit_sha256'] = sha(output / 'independent-export-audit.json')
            receipt['phase'] = 'complete-native-input-graph-proved'
            code = fea.ccx_run()
            (output / 'native.stdout').write_text(fea.ccx_stdout)
            (output / 'native.stderr').write_text(fea.ccx_stderr)
            receipt.update(solver_returncode=code, actual_binary=str(fea.ccx_binary),
                actual_binary_sha256=sha(fea.ccx_binary), phase='native-process-returned')
            self.assertEqual(code, 0, fea.ccx_stdout + fea.ccx_stderr)
            self.assertEqual({'deck': sha(deck), 'request': sha(request)}, original_hashes)
            wire = deck.with_suffix('.accounting.out')
            lines = wire.read_text().splitlines()
            self.assertEqual(lines[0], 'CCX_FORCE_ACCOUNTING_V3')
            self.assertEqual(lines[-1], 'END')
            reports = [item for item in fixture.analysis.Group
                if getattr(getattr(item, 'Proxy', None), 'Type', None) == 'Fem::NativeForceAccountingResult']
            self.assertEqual(len(reports), 1)
            report = reports[0]
            self.assertTrue(report.Status.startswith('Current'), report.Status)
            literal = report.AccountingData
            data = json.loads(literal)
            self.assertEqual(data['schema'], 'CCX_FORCE_ACCOUNTING_V3')
            self.assertEqual(data['movement_source']['status'], 'BOUND')
            self.assertEqual(data['binary'], str(fea.ccx_binary))
            self.assertEqual(data['binary_sha256'], sha(fea.ccx_binary))
            self.assertEqual(data['analysis'], fixture.analysis.Name)
            self.assertEqual(data['mesh'], fixture.mesh.Name)
            self.assertEqual(data['deck_sha256'], original_hashes['deck'])
            self.assertEqual(data['request_sha256'], original_hashes['request'])
            self.assertEqual(data['output_sha256'], sha(wire))
            self.assertEqual(data['end_time'], 1.0)
            self.assertRegex(data['model_digest'], r'^[0-9a-f]{64}$')
            self.assertEqual(len(data['expected']), len(fixture.cuts) + 1)
            self.assertEqual({tuple(item) for item in data['expected']},
                {('SUPPORT', fixture.fixed.Name), *(('CUT', cut.Name) for cut in fixture.cuts)})
            source = data['movement_source']
            self.assertEqual(source['schema'], 'FREECAD_MOVEMENT_SOURCE_V1')
            self.assertEqual(source['path'], str(deck.with_suffix('.frd')))
            self.assertEqual(source['sha256'], sha(deck.with_suffix('.frd')))
            self.assertEqual(source['deck'], str(deck))
            self.assertEqual(source['request'], str(request))
            self.assertEqual(source['binary'], str(fea.ccx_binary))
            self.assertEqual(source['deck_sha256'], original_hashes['deck'])
            self.assertEqual(source['request_sha256'], original_hashes['request'])
            self.assertEqual(source['binary_sha256'], sha(fea.ccx_binary))
            self.assertEqual(source['model_digest'], data['model_digest'])
            self.assertEqual(source['requested_end_time'], 1.0)
            (output / 'native-accounting-data.json').write_text(literal)
            channels = data['wrenches']
            self.assertEqual(set(channels), {'SUPPORT', 'CUT', 'LOAD', 'CONTACT', 'MPC'})
            self.assertEqual(set(channels['SUPPORT']), {fixture.fixed.Name})
            body_names = {cut.Name for cut in fixture.cuts}
            for kind in ('CUT', 'LOAD', 'CONTACT', 'MPC'):
                self.assertEqual(set(channels[kind]), body_names)
            oracle = json.loads((ROOT / 'oracle/physical-oracle.json').read_text())
            expected_case = oracle['tracer_1_by_1' if case == 'tracer' else 'capacity_11_by_12']
            total = expected_case['whole_applied_wrench']
            support = expected_case['physical_external_SUPPORT']
            force_scale, moment_scale = math.hypot(*total[:3]), math.hypot(*total[3:])
            wrench_checks(checks, 'SUPPORT/' + fixture.fixed.Name, channels['SUPPORT'][fixture.fixed.Name],
                          support, force_scale, moment_scale)
            for branch in fixture.branches:
                # Independently frozen load statics, not a calculation from
                # accounting output or any target writer/solver force helper.
                w = [12, 0, 0, 6, 12*branch['z'], -12*branch['y']]
                scale_m = math.hypot(*w[3:])
                expected = {
                    'Left': {'CUT': w, 'LOAD': [0]*6, 'CONTACT': [0]*6, 'MPC': [-v for v in w]},
                    'Right': {'CUT': [-v for v in w], 'LOAD': w, 'CONTACT': [0]*6, 'MPC': [0]*6},
                }
                for side in ('Left', 'Right'):
                    name = branch['cuts'][side].Name
                    for kind in ('CUT', 'LOAD', 'CONTACT', 'MPC'):
                        wrench_checks(checks, kind + '/' + name, channels[kind][name], expected[side][kind], 12, scale_m)
                    balance = [sum(channels[kind][name][axis] for kind in ('CUT', 'LOAD', 'CONTACT', 'MPC')) for axis in range(6)]
                    wrench_checks(checks, name + '/body-equilibrium', balance, [0]*6, 12, scale_m)
                paired = [sum(channels['CUT'][branch['cuts'][side].Name][axis] for side in ('Left', 'Right')) for axis in range(6)]
                wrench_checks(checks, branch['name'] + '/paired-cut-sum', paired, [0]*6, 12, scale_m)

            motion = parse_port_motion(deck.with_suffix('.dat'), export['rbe_ids'])
            self.assertTrue(motion['passed'])
            write_json(output / 'motion-from-original-dat.json', motion)
            # Verify the original FRD's actual displacement state independently
            # of the requested-time provenance claim before using its field.
            frd_state, displacement_times = None, []
            for line in deck.with_suffix('.frd').read_text().splitlines():
                if re.match(r'^\s*100CL\s', line):
                    fields = line.split()
                    self.assertGreaterEqual(len(fields), 3)
                    frd_state = float(fields[2])
                    self.assertTrue(math.isfinite(frd_state))
                elif re.match(r'^\s*-4\s+DISP\b', line):
                    self.assertIsNotNone(frd_state)
                    displacement_times.append(frd_state)
            self.assertTrue(displacement_times)
            self.assertTrue(all(0 <= value <= 1 for value in displacement_times))
            self.assertEqual(displacement_times[-1], 1.0)
            receipt['observed_FRD_displacement_times'] = displacement_times
            displacement = read_frd_result(str(deck.with_suffix('.frd')))['Results'][-1]['disp']
            coordinates = fixture.mesh.FemMesh.Nodes
            physical_proof, host_work = {}, 0.0
            for port in fixture.ports:
                port_motion = motion['ports'][port.Name]
                translation, rotation = App.Vector(*port_motion['translation_mm']), App.Vector(*port_motion['rotation_rad'])
                errors, nonzero = [], False
                for node in fixture.membership['moving_face_nodes'][port.Name]:
                    actual = App.Vector(*displacement[node])
                    predicted = translation + rotation.cross(coordinates[node] - port.ReferenceNode)
                    denominator = predicted.Length if predicted.Length else 0.01
                    error = (actual - predicted).Length/denominator
                    self.assertTrue(math.isfinite(error))
                    self.assertLessEqual(error, 0.05, (port.Name, node, actual, predicted))
                    errors.append(error)
                    nonzero |= actual.Length > 0
                physical_proof[port.Name] = {'nodes': len(errors), 'maximum_relative_kinematic_error': max(errors),
                    'finite_physical_face_has_nonzero_motion': bool(nonzero)}
            for branch in fixture.branches:
                a, b = (motion['ports'][branch['ports'][side].Name] for side in ('A', 'B'))
                du = [y-x for x, y in zip(a['translation_mm'], b['translation_mm'])]
                dr = [y-x for x, y in zip(a['rotation_rad'], b['rotation_rad'])]
                vector_check(checks, branch['name'] + '/differential-translation', du, [0.01, 0, 0], 0.01, 0.05)
                vector_check(checks, branch['name'] + '/differential-rotation', dr, [0.001, 0, 0], 0.001, 0.05)
                vector_check(checks, branch['name'] + '/local-generalized-force', [1200*v for v in du], [12, 0, 0], 12, 0.01)
                vector_check(checks, branch['name'] + '/local-generalized-couple', [6000*v for v in dr], [6, 0, 0], 6, 0.01)
                vector_check(checks, branch['name'] + '/explicit-local-X-torque', [6000*dr[0], 0, 0], [6, 0, 0], 6, 0.01)
                host_work += 12*a['translation_mm'][0] + 6*a['rotation_rad'][0]
            self.assertTrue(math.isfinite(host_work) and host_work > 0,
                'Finite backbone under nonzero port loads has no positive observable elastic work')
            self.assertTrue(any(physical_proof[branch['ports']['A'].Name]['finite_physical_face_has_nonzero_motion'] for branch in fixture.branches))
            self.assertTrue(all(physical_proof[branch['ports']['B'].Name]['finite_physical_face_has_nonzero_motion'] for branch in fixture.branches))
            write_json(output / 'physical-face-motion-proof.json', physical_proof)
            receipt['host_positive_generalized_load_work_N_mm'] = host_work
            receipt['phase'] = 'independent-physical-equilibrium-and-response-proved'

            fea.load_results()
            self.assertTrue(fea.results_present)
            fem_results = [item for item in fixture.analysis.Group if item.isDerivedFrom('Fem::FemResultObject')]
            self.assertTrue(fem_results)
            receipt['fem_result_objects'] = [item.Name for item in fem_results]
            self.assertTrue(report.Status.startswith('Current'), report.Status)
            self.assertEqual(report.AccountingData, literal)
            resultants = plain(list(report.Resultants))
            doc.recompute()
            self.assertTrue(report.Status.startswith('Current'), report.Status)
            saved = output / 'coupled-native-current.FCStd'
            doc.saveAs(str(saved))
            self.assertEqual(report.AccountingData, literal)
            self.assertTrue(report.Status.startswith('Current'), report.Status)
            self.assertEqual({'deck': sha(deck), 'request': sha(request)}, original_hashes)
            self.assertEqual(sha(wire), data['output_sha256'])
            self.assertEqual(sha(deck.with_suffix('.frd')), source['sha256'])
            self.assertEqual(sha(fea.ccx_binary), data['binary_sha256'])
            source_files = {'deck': deck, 'request': request, 'native_output': wire,
                'dat': deck.with_suffix('.dat'), 'frd': deck.with_suffix('.frd')}
            cold = {'schema': 'FreeCAD-yzk-coupled-cold-case-v1', 'case': case,
                'document': str(saved), 'document_sha256': sha(saved),
                'report_name': report.Name, 'analysis_name': fixture.analysis.Name,
                'solver_name': fixture.solver.Name, 'mesh_name': fixture.mesh.Name,
                'accounting_data_literal': literal, 'resultants_literal': resultants,
                'saved_status_literal': report.Status, 'movement_source_literal': data['movement_source'],
                'binary': str(fea.ccx_binary), 'binary_sha256': sha(fea.ccx_binary),
                'source_files': {name: {'path': str(path), 'sha256': sha(path)} for name, path in source_files.items()},
                'explicit_supports': [obj.Name for obj in fixture.solver.NativeAccountingSupports],
                'saved_references': {obj.Name: plain(obj.References) for obj in [*fixture.ports, *fixture.cuts, fixture.fixed]},
                'saved_native_properties': properties, 'frozen_oracle_sha256': FROZEN,
                'no_cold_restore_performed_yet': True, 'no_history_or_provenance_repair': True}
            write_json(output / 'cold-case.json', cold)
            receipt.update(passed=True, phase='normal-import-save-complete', cold_manifest=str(output / 'cold-case.json'),
                cold_manifest_sha256=sha(output / 'cold-case.json'), physical_check_count=len(checks),
                current_native_report={'name': report.Name, 'status': report.Status, 'schema': data['schema'],
                    'movement_status': data['movement_source']['status']})
        except BaseException as error:
            receipt['witness_error'] = {'type': type(error).__name__, 'message': str(error), 'traceback': traceback.format_exc()}
            raise
        finally:
            output.mkdir(parents=True, exist_ok=True)
            receipt['inputs_after'] = input_pins()
            receipt['protected_inputs_unchanged'] = receipt['inputs_before'] == receipt['inputs_after']
            receipt['passed'] &= receipt['protected_inputs_unchanged']
            receipt['retained_files'] = {str(path.relative_to(output)): {'sha256': sha(path), 'bytes': path.stat().st_size}
                for path in sorted(output.rglob('*')) if path.is_file()}
            write_json(output / 'witness-receipt.json', receipt)
            if doc.Name in App.listDocuments():
                App.closeDocument(doc.Name)
        self.assertTrue(receipt['passed'])
