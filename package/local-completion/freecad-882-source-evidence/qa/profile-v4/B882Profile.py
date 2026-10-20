"""One whole public stock export of the immutable installed132-bay fixture.

Root alone executes inside bounded serial FreeCAD with fresh profiles. No
solver, mesher, save, recompute, deck/request edit or physical model edit is
performed by this harness. setup_working_dir only routes new export outputs.
The measured call is exactly FemToolsCcx.write_inp_file, not a private phase.
"""
import sys
sys.dont_write_bytecode = True

import cProfile
from collections import Counter
import hashlib
import io
import json
import os
from pathlib import Path
import pstats
import re
import time
import traceback
import unittest

import FreeCAD as App
from femtest.app.coupled_port_fixture import model_properties
from femtools.ccxtools import FemToolsCcx
from harness_config import COMMIT, REVISION, NATIVE_SHA, SOURCE_HEAD, WITNESS, FIXTURE_PINS
from harness_config import RESTORED_CONNECTIVITY, RESTORED_CONNECTIVITY_SHA, RESTORED_CONNECTIVITY_CANONICAL_SHA

MODEL = Path(WITNESS)
EXPECTED_COUNTS = {'PORT': 264, 'BODY': 264, 'ANGLE': 792, 'SPRING': 792,
                   'SPC_SUPPORT': 1, 'CCX_FORCE_ACCOUNTING_V3': 1, 'END': 1}
WRITTEN_ON = re.compile(r'^\*\*   written on    --> [^\r\n]+$', re.M)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                                    separators=(',', ':')).encode()).hexdigest()


def pins():
    result = {str(MODEL / name): sha(MODEL / name) for name in FIXTURE_PINS}
    result[RESTORED_CONNECTIVITY] = sha(RESTORED_CONNECTIVITY)
    return result


def mesh_snapshot(mesh):
    native = mesh.FemMesh
    return {'nodes': {str(node): [point.x, point.y, point.z]
                      for node, point in native.Nodes.items()},
            'volume_connectivity': {str(element): list(native.getElementNodes(element))
                                    for element in native.Volumes},
            'groups': [{'id': group, 'name': native.getGroupName(group),
                        'element_type': native.getGroupElementType(group),
                        'elements': list(native.getGroupElements(group))}
                       for group in native.Groups]}


def request_graph(payload):
    rows = [line.split() for line in payload.decode().splitlines() if line.strip()]
    declarations = Counter(row[0] for row in rows if row[0][0].isalpha())
    ports = [row for row in rows if row[0] == 'PORT']
    if any(len(row) != 4 for row in ports) or len({row[1] for row in ports}) != len(ports):
        raise AssertionError('Repeated or malformed actual PORT declaration')
    return dict(declarations), {row[1]: [int(row[2]), int(row[3])] for row in ports}


def first_difference(before, after):
    a, b = before.decode().splitlines(), after.decode().splitlines()
    for number in range(max(len(a), len(b))):
        left = a[number] if number < len(a) else '<EOF>'
        right = b[number] if number < len(b) else '<EOF>'
        if left != right:
            return {'one_based_line': number + 1, 'original_prefix': left[:240],
                    'new_prefix': right[:240], 'line_prefixes_may_be_truncated': True}
    return None


class WholePublicExportProfile(unittest.TestCase):
    def test_original_installed132_graph_whole_stock_export_profile(self):
        run = Path(os.environ['B882_OUTPUT'])
        output, directory = run / 'export-profile.json', run / 'native'
        self.assertFalse(output.exists())
        self.assertFalse(directory.exists())
        before = pins()
        for name, wanted in FIXTURE_PINS.items():
            self.assertEqual(before[str(MODEL / name)], wanted)
        self.assertTrue(before[RESTORED_CONNECTIVITY] == RESTORED_CONNECTIVITY_SHA,
                        'Pinned restored connectivity observation changed')
        self.assertEqual(os.environ['CCX_FORCE_ACCOUNTING_MAX_DECLARATIONS'], '2113')
        self.assertEqual(App.Version()[3], REVISION)
        self.assertEqual(App.Version()[-1], COMMIT)
        historical = json.loads((MODEL / 'witness-receipt.json').read_bytes())
        self.assertTrue(historical['passed'])
        self.assertEqual(historical['before_export_document_sha256'], FIXTURE_PINS['coupled-before-export.FCStd'])
        expected_mesh = json.loads((MODEL / 'mesh-membership.json').read_bytes())
        restored_connectivity = json.loads(Path(RESTORED_CONNECTIVITY).read_bytes())
        self.assertTrue(canonical(restored_connectivity) == RESTORED_CONNECTIVITY_CANONICAL_SHA,
                        'Pinned restored connectivity canonical form changed')
        old_deck = (MODEL / 'native/Mesh.inp').read_bytes()
        old_request = (MODEL / 'native/Mesh.accounting').read_bytes()
        original_counts, original_ports = request_graph(old_request)
        self.assertEqual(original_counts, EXPECTED_COUNTS)
        receipt = {'schema': 'FreeCAD-882-whole-public-export-profile-v3', 'passed': False,
            'scope': 'Export-only performance/custody; not a new physical solve or engineering acceptance',
            'source_HEAD': SOURCE_HEAD, 'actual_runtime': App.Version(), 'inputs_before': before,
            'physical_fixture': 'Exact installed132-bay saved FCStd3128ea; post-restore element relabeling is pinned separately, no different source223 mesh',
            'restored_connectivity_observation': {'path': RESTORED_CONNECTIVITY,
                'sha256': RESTORED_CONNECTIVITY_SHA, 'canonical_sha256': RESTORED_CONNECTIVITY_CANONICAL_SHA},
            'historical_deck_request_PORT_comparisons_are_diagnostic_only': True,
            'old_physical_qualification_inherited_by_this_export': False,
            'candidate_must_match_this_new_baseline_deck_except_timestamp_and_exact_request_PORT_IDs': True,
            'fresh_full132_physics_cold_and_refusal_qualification_required_separately': True,
            'original_unprofiled_stock_write_seconds': historical['stock_write_inp_file_seconds'],
            'original_unprofiled_measurement_is_not_paired_with_profiled_wall_time': True,
            'one_whole_public_write_inp_file_call_intended': True,
            'actual_write_inp_file_calls': 0, 'no_timing_SLA_asserted': True,
            'CPU_scope': 'time.process_time for this FreeCAD process only, including profiling overhead; not native-child CPU or the profiler timer',
            'cumulative_profile_times_overlap_and_are_not_additive_partitions': True,
            'no_solver_mesher_save_recompute_or_physical_model_edit_by_harness': True,
            'only_export_operational_WorkingDir_is_routed_to_new_output': True,
            'originals_are_hash_only_and_never_overwritten': True,
            'only_allowed_deck_comparison_normalization': 'The one exact **   written on    --> timestamp comment; comparison only, never output modification',
            'Oomakhi_accessed_or_solved': False, 'engineering_or_BIM_accepted': False,
            'phase': 'before-document-open'}
        document = None
        profiler = cProfile.Profile()
        try:
            def phase(value):
                receipt['phase'] = value
                print('[DEBUG-882] whole-profile ' + value, flush=True)

            phase('open-pinned-document')
            started = time.perf_counter()
            document = App.openDocument(str(MODEL / 'coupled-before-export.FCStd'))
            receipt['document_load_seconds'] = time.perf_counter() - started
            analysis, solver, mesh = (document.getObject(name) for name in ('Analysis', 'SolverCcxTools', 'Mesh'))
            phase('verify-analysis-solver-and-geometry')
            self.assertTrue(all(obj is not None for obj in (analysis, solver, mesh)))
            self.assertTrue(solver.NativeForceAccounting)
            self.assertEqual(solver.NativeAccountingSolver, '')
            self.assertFalse(solver.SplitInputWriter)
            self.assertEqual([obj.Name for obj in solver.NativeAccountingSupports], ['BackboneFixed'])
            geometry = document.getObject('CoupledCells')
            self.assertEqual(len(geometry.Shape.Solids), 397)
            contract = json.loads((MODEL / 'geometry-contract.json').read_bytes())
            self.assertLess(abs(geometry.Shape.Volume - contract['physical_volume_mm3']), 1e-8)
            physical_before = model_properties(analysis, mesh)
            previous_names = set()

            def local(value, restored):
                # Comparison only: the established cold-session own-document
                # normalization. No native property or literal file is changed.
                if isinstance(value, dict):
                    if set(value) == {'object', 'document'}:
                        if restored:
                            self.assertEqual(value['document'], document.Name)
                            self.assertIsNotNone(document.getObject(value['object']))
                        else:
                            previous_names.add(value['document'])
                        return {'object': value['object'], 'document': '<owning document>'}
                    return {key: local(item, restored) for key, item in value.items()}
                if isinstance(value, list):
                    return [local(item, restored) for item in value]
                return value

            original_properties = json.loads((MODEL / 'export-properties.json').read_bytes())
            phase('compare-properties-by-boolean-own-document-normalization')
            self.assertTrue(local(physical_before, True) == local(original_properties, False),
                            'Original selected physical properties differ after restore')
            self.assertEqual(len(previous_names), 1)
            receipt['session_document_name_mapping'] = {
                'saved_session': next(iter(previous_names)), 'opened_session': document.Name,
                'comparison_only_no_native_references_or_history_rebound': True}
            phase('read-public-physical-mesh-and-groups')
            mesh_before = mesh_snapshot(mesh)
            phase('verify-pinned-restored-mesh-by-short-booleans')
            self.assertTrue(mesh_before['nodes'] == expected_mesh['nodes'], 'Restored node coordinates differ')
            self.assertTrue(mesh_before['volume_connectivity'] == restored_connectivity,
                            'Restored connectivity differs from the separately verified/pinned observation')
            receipt['model_before_sha256'] = canonical(physical_before)
            receipt['mesh_before_sha256'] = canonical(mesh_before)
            receipt['physical_mesh_nodes'] = len(mesh_before['nodes'])
            receipt['physical_volume_elements'] = len(mesh_before['volume_connectivity'])
            receipt['solver_working_dir_before_setup'] = solver.WorkingDir
            fea = FemToolsCcx(analysis=analysis, solver=solver)
            phase('prepare-public-tool-and-new-output-directory')
            fea.update_objects()
            directory.mkdir()
            fea.setup_working_dir(str(directory))
            self.assertTrue(model_properties(analysis, mesh) == physical_before,
                            'Selected physical properties changed during public setup')
            receipt['solver_working_dir_after_setup'] = solver.WorkingDir
            module = Path(sys.modules[FemToolsCcx.__module__].__file__).resolve()
            self.assertTrue(module.is_relative_to(Path(App.getHomePath()).resolve()))
            receipt['public_entrypoint_module'] = {'path': str(module), 'sha256': sha(module)}
            phase('whole-stock-write-inp-file-started')
            started = time.perf_counter()
            cpu_started = time.process_time()
            profiler.enable()
            try:
                receipt['actual_write_inp_file_calls'] += 1
                fea.write_inp_file()
            finally:
                profiler.disable()
                receipt['profiled_stock_write_wall_seconds'] = time.perf_counter() - started
                receipt['profiled_stock_write_FreeCAD_process_CPU_seconds'] = time.process_time() - cpu_started
                profiler.dump_stats(str(run / 'whole-public-write.prof'))
                view = io.StringIO()
                stats = pstats.Stats(profiler, stream=view)
                stats.sort_stats('cumulative').print_stats(100)
                with (run / 'profile-cumulative.txt').open('x') as handle:
                    handle.write(view.getvalue())
                rows = [{'filename': key[0], 'line': key[1], 'function': key[2],
                         'primitive_calls': row[0], 'total_calls': row[1],
                         'self_seconds': row[2], 'cumulative_seconds': row[3]}
                        for key, row in stats.stats.items()]
                receipt['profile_operation_rows'] = sorted(rows, key=lambda row: (-row['cumulative_seconds'], row['filename'], row['line']))
            phase('stock-export-returned-capture-diagnostic-historical-comparisons')
            deck = Path(fea.inp_file_name)
            request = deck.with_suffix('.accounting')
            self.assertEqual(deck.parent, directory)
            new_deck, new_request = deck.read_bytes(), request.read_bytes()
            counts, ports = request_graph(new_request)
            receipt['output_deck'] = {'path': str(deck), 'sha256': hashlib.sha256(new_deck).hexdigest(), 'bytes': len(new_deck)}
            receipt['output_request'] = {'path': str(request), 'sha256': hashlib.sha256(new_request).hexdigest(), 'bytes': len(new_request)}
            metadata_path = deck.with_suffix('.accounting.json')
            metadata_bytes = metadata_path.read_bytes()
            metadata = json.loads(metadata_bytes)
            effective = metadata['capacity']
            required = {'supports': 1, 'bodies': 264, 'ports': 264, 'angles': 792, 'springs': 792}
            native = Path(App.getHomePath()).resolve() / 'data/NativeSolvers/ccx-force-accounting'
            phase('verify-written-effective-capacity2113-and-default-native6c')
            self.assertTrue(metadata['schema'] == 'CCX_FORCE_ACCOUNTING_V3'
                            and metadata['deck_sha256'] == receipt['output_deck']['sha256']
                            and metadata['request_sha256'] == receipt['output_request']['sha256']
                            and effective['required'] == required and effective['total'] == 2113
                            and effective['supported']['total_records'] == 2113
                            and effective['supported']['limits'] == dict.fromkeys(required, 2113)
                            and effective['binary'] == str(native)
                            and effective['binary_sha256'] == sha(native) == NATIVE_SHA,
                            'Actual stock export metadata did not bind default6c and complete2113 budget')
            receipt['output_request_metadata'] = {'path': str(metadata_path),
                'sha256': hashlib.sha256(metadata_bytes).hexdigest(), 'bytes': len(metadata_bytes)}
            receipt['actual_export_capacity'] = {'required': effective['required'], 'total': effective['total'],
                'supported': effective['supported'], 'binary': effective['binary'], 'binary_sha256': effective['binary_sha256']}
            receipt['request_declarations'] = counts
            receipt['native_PORT_IDs'] = ports
            receipt['original_native_PORT_IDs'] = original_ports
            receipt['raw_deck_identical'] = old_deck == new_deck
            receipt['raw_request_identical'] = old_request == new_request
            receipt['raw_deck_first_difference'] = first_difference(old_deck, new_deck)
            receipt['raw_request_first_difference'] = first_difference(old_request, new_request)
            written_old, written_new = WRITTEN_ON.findall(old_deck.decode()), WRITTEN_ON.findall(new_deck.decode())
            receipt['declared_written_on_comments'] = {'original': written_old, 'new': written_new}
            self.assertEqual(len(written_old), 1)
            self.assertEqual(len(written_new), 1)
            normalized_old = WRITTEN_ON.sub('**   written on    --> <timestamp>', old_deck.decode())
            normalized_new = WRITTEN_ON.sub('**   written on    --> <timestamp>', new_deck.decode())
            receipt['deck_equal_except_single_declared_timestamp_comment'] = normalized_old == normalized_new
            self.assertEqual(counts, EXPECTED_COUNTS)
            self.assertTrue(receipt['actual_write_inp_file_calls'] == 1, 'Expected exactly one actual public write call')
            receipt['historical_PORT_IDs_equal'] = ports == original_ports
            phase('verify-post-export-raw-properties-and-physical-mesh-groups')
            receipt['model_after_sha256'] = canonical(model_properties(analysis, mesh))
            receipt['mesh_after_sha256'] = canonical(mesh_snapshot(mesh))
            self.assertEqual(receipt['model_before_sha256'], receipt['model_after_sha256'])
            self.assertEqual(receipt['mesh_before_sha256'], receipt['mesh_after_sha256'])
            self.assertEqual(sha(module), receipt['public_entrypoint_module']['sha256'])
            self.assertFalse(any(path.suffix.lower() in ('.frd', '.dat', '.fcstd') for path in directory.iterdir()))
            receipt.update(passed=True, phase='new-baseline-profile-graph-counts-and-input-custody-complete')
        except BaseException as error:
            receipt['error'] = {'type': type(error).__name__, 'message': str(error), 'traceback': traceback.format_exc()}
            raise
        finally:
            profiler.disable()
            receipt['inputs_after'] = pins()
            receipt['original_fixture_and_native_evidence_unchanged'] = before == receipt['inputs_after']
            receipt['passed'] &= receipt['original_fixture_and_native_evidence_unchanged']
            if document is not None and document.Name in App.listDocuments():
                App.closeDocument(document.Name)
            with output.open('x') as handle:
                json.dump(receipt, handle, indent=2, sort_keys=True, allow_nan=False)
                handle.write('\n')
        self.assertTrue(receipt['passed'])
