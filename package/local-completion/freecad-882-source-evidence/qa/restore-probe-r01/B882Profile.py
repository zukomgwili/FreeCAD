"""Read-only restore representation probe; no writer or solver call.

PASS means observations completed with unchanged input bytes/properties, not
that differing tetrahedral connectivity orders are physically equivalent.
"""
import sys
sys.dont_write_bytecode = True

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import time
import traceback
import unittest

import FreeCAD as App
from femtest.app.coupled_port_fixture import model_properties
from harness_config import COMMIT, REVISION, SOURCE_HEAD, WITNESS, FIXTURE_PINS

MODEL = Path(WITNESS)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                                    separators=(',', ':')).encode()).hexdigest()


def pins():
    return {str(MODEL / name): sha(MODEL / name) for name in FIXTURE_PINS}


class RestoreRepresentationProbe(unittest.TestCase):
    def test_original_installed132_restore_representation_without_export(self):
        run = Path(os.environ['B882_OUTPUT'])
        output = run / 'restore-probe.json'
        before = pins()
        self.assertTrue(all(before[str(MODEL / name)] == wanted for name, wanted in FIXTURE_PINS.items()),
                        'A pinned original input changed')
        receipt = {'schema': 'FreeCAD-882-restore-representation-probe-v1', 'passed': False,
            'scope': 'Read-only diagnostic observations, not orientation/topology equivalence or physical/export qualification',
            'source_HEAD': SOURCE_HEAD, 'actual_runtime': App.Version(), 'inputs_before': before,
            'no_write_inp_file_native_directory_profile_solve_save_recompute_or_mesher': True,
            'original_files_edited_or_rebound': False, 'Oomakhi_accessed_or_solved': False,
            'actual_write_inp_file_calls': 0, 'phase': 'initial-pins-verified',
            'geometry_or_orientation_equivalence_qualification_claimed': False,
            'engineering_or_BIM_accepted': False}
        document = None
        try:
            def phase(value):
                receipt['phase'] = value
                print('[DEBUG-882] restore-probe ' + value, flush=True)

            phase('verify-installed-runtime')
            self.assertTrue(App.Version()[3] == REVISION and App.Version()[-1] == COMMIT,
                            'Unexpected installed runtime')
            expected = json.loads((MODEL / 'mesh-membership.json').read_bytes())
            phase('open-pinned-document')
            started = time.perf_counter()
            document = App.openDocument(str(MODEL / 'coupled-before-export.FCStd'))
            receipt['document_load_seconds'] = time.perf_counter() - started
            analysis, mesh = (document.getObject(name) for name in ('Analysis', 'Mesh'))
            phase('verify-analysis-and-mesh-presence')
            self.assertTrue(analysis is not None and mesh is not None, 'Missing native Analysis/Mesh')
            properties_before = model_properties(analysis, mesh)
            old_properties = json.loads((MODEL / 'export-properties.json').read_bytes())
            previous_names = set()

            def local(value, restored):
                if isinstance(value, dict):
                    if set(value) == {'object', 'document'}:
                        if restored:
                            self.assertTrue(value['document'] == document.Name
                                            and document.getObject(value['object']) is not None,
                                            'Restored reference is not an existing own-document object')
                        else:
                            previous_names.add(value['document'])
                        return {'object': value['object'], 'document': '<owning document>'}
                    return {key: local(item, restored) for key, item in value.items()}
                if isinstance(value, list):
                    return [local(item, restored) for item in value]
                return value

            phase('compare-selected-own-document-properties-boolean-only')
            receipt['selected_properties_equal_except_session_name'] = local(properties_before, True) == local(old_properties, False)
            receipt['saved_reference_session_count'] = len(previous_names)
            receipt['session_document_name_mapping'] = {
                'saved_sessions': sorted(previous_names), 'opened_session': document.Name,
                'comparison_only_no_native_references_rewritten': True}
            native = mesh.FemMesh
            phase('read-public-node-coordinates-and-volume-connectivity')
            nodes = {str(node): [point.x, point.y, point.z] for node, point in native.Nodes.items()}
            live = {str(element): list(native.getElementNodes(element)) for element in native.Volumes}
            old = expected['volume_connectivity']
            old_keys, live_keys = set(old), set(live)
            shared = sorted(old_keys & live_keys, key=int)
            mismatches = [key for key in shared if old[key] != live[key]]
            same_node_sets = sum(set(old[key]) == set(live[key]) for key in shared)
            samples = []
            for key in mismatches[:10]:
                a, b = old[key], live[key]
                same = len(a) == len(b) and set(a) == set(b)
                samples.append({'element': int(key), 'original_node_sequence': a,
                    'restored_node_sequence': b, 'same_node_set': same,
                    'original_node_count': len(a), 'restored_node_count': len(b),
                    'restored_positions_in_original_sequence': [a.index(node) for node in b] if same else None,
                    'orientation_equivalence_not_inferred': True})
            phase('summarize-connectivity-differences-without-container-assert-diffs')
            receipt.update(
                original_node_count=len(expected['nodes']), restored_node_count=len(nodes),
                node_coordinates_exactly_equal=nodes == expected['nodes'],
                original_nodes_sha256=canonical(expected['nodes']), restored_nodes_sha256=canonical(nodes),
                original_volume_count=len(old), restored_volume_count=len(live),
                element_ID_sets_equal=old_keys == live_keys,
                original_only_element_count=len(old_keys - live_keys), restored_only_element_count=len(live_keys - old_keys),
                original_only_ID_sample=sorted(old_keys - live_keys, key=int)[:10],
                restored_only_ID_sample=sorted(live_keys - old_keys, key=int)[:10],
                exact_sequence_comparison=old == live, shared_element_count=len(shared),
                differing_sequence_count=len(mismatches), same_node_set_shared_element_count=same_node_sets,
                original_element_node_count_histogram=dict(sorted(Counter(map(len, old.values())).items())),
                restored_element_node_count_histogram=dict(sorted(Counter(map(len, live.values())).items())),
                original_connectivity_canonical_sha256=canonical(old), restored_connectivity_canonical_sha256=canonical(live),
                first_at_most_ten_order_differences=samples,
                public_type_information='Only public FemMesh.Volumes and getElementNodes; node-count histograms are not an element-orientation/type proof')
            full = run / 'restored-volume-connectivity.json'
            phase('write-private-connectivity-observation-only')
            with full.open('x') as handle:
                json.dump(live, handle, sort_keys=True, separators=(',', ':'))
                handle.write('\n')
            receipt['restored_connectivity_file'] = {'path': str(full), 'sha256': sha(full), 'bytes': full.stat().st_size}
            receipt['selected_properties_before_sha256'] = canonical(properties_before)
            receipt['selected_properties_after_sha256'] = canonical(model_properties(analysis, mesh))
            phase('verify-read-only-property-stability-boolean-only')
            self.assertTrue(receipt['selected_properties_before_sha256'] == receipt['selected_properties_after_sha256'],
                            'Selected properties changed during the read-only probe')
            receipt.update(passed=True, phase='read-only-observations-complete')
        except BaseException as error:
            receipt['error'] = {'type': type(error).__name__, 'message': str(error), 'traceback': traceback.format_exc()}
            raise
        finally:
            receipt['inputs_after'] = pins()
            receipt['original_fixture_and_native_evidence_unchanged'] = before == receipt['inputs_after']
            receipt['passed'] &= receipt['original_fixture_and_native_evidence_unchanged']
            if document is not None and document.Name in App.listDocuments():
                App.closeDocument(document.Name)
            with output.open('x') as handle:
                json.dump(receipt, handle, indent=2, sort_keys=True, allow_nan=False)
                handle.write('\n')
        self.assertTrue(receipt['passed'], 'Read-only probe or source custody failed')
