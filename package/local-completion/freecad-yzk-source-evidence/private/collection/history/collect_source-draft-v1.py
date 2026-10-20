"""Validate/publish the explicit yzk source packet; root alone executes.

No FreeCAD, solver, test, build or installation is launched. Check-only writes
nothing. Every semantic input must be in the root-approved byte plan, except
hash-only runtime references and explicitly retained portable-copy originals.
Historical failing evidence is never reclassified as a current green gate.
"""
import sys
sys.dont_write_bytecode = True

import argparse
import json
import math
from pathlib import Path
import re
import subprocess

from evidence_packet import (
    PRIVATE, REPOSITORY, Packet, descriptor, digest, json_bytes, load,
    privacy_check, read_regular, require, source_path,
)


BUILD = REPOSITORY / 'build/release'
CANDIDATE = '6c02452a896727af6cb4578fd3fb6bbfbdd48e3fb887c1c04fa2d8b171976c66'
NATIVE = {
    'forceaccounting.c': '8c51e06abecf4c2b1537b1e6f4ef4606ea8481a4a180d465cbff00d63329f2a4',
    'hooks.patch': 'e500c46cc9cd26fc4e63508a51375bd09ebdc0973638375df14cffd036c9bfa7',
    'contract.json': '8086e668ed9383a324fbfff7cbe8621d919c46da844924d507252a24f85a77eb',
}
ORACLES = {
    'fixture-spec.json': 'ab19711657222245daadade4037d2d1cf2ce6f0deef49a05e5465fe77a36a822',
    'physical-oracle.json': '68f6663e3ff526356236473c11934069c38c5b2a50e264a7641e3382cc6cb3ac',
    'acceptance-amendment-v1.json': '2e4014ec78adaff7bc9daf4acfbb0ea2a63c15d1f2ac7d66c63afc13798b2584',
}
COUNTS = {'angles': 792, 'bodies': 264, 'ports': 264, 'springs': 792, 'supports': 1}
PRIMARY = PRIVATE / 'qa-v2/coupled-capacity-at-limit-r01/witness'
DESTINATION = REPOSITORY / 'package/local-completion/freecad-yzk-source-evidence'
SUMMARY = REPOSITORY / 'package/local-completion/freecad-yzk-validation.json'


def parse_ctest(text):
    """Independently require one complete actual catalogue and terminal result."""
    rows = []
    for match in re.finditer(r'^\s*(\d+)/(\d+)\s+Test\s+#(\d+):[^\r\n]*$', text, re.M):
        line = match.group(0).strip()
        status = ('disabled' if '***Not Run (Disabled)' in line else
                  'skipped' if '***Skipped' in line else
                  'passed' if re.search(r'\bPassed\s+[\d.]+\s+sec\s*$', line) else 'failed_or_unknown')
        rows.append({'ordinal': int(match[1]), 'catalogue': int(match[2]),
                     'test_number': int(match[3]), 'status': status, 'line': line})
    require(rows and len({row['catalogue'] for row in rows}) == 1, 'CTest catalogue absent/inconsistent')
    count = rows[0]['catalogue']
    require(len(rows) == count and {row['ordinal'] for row in rows} == set(range(1, count + 1))
            and {row['test_number'] for row in rows} == set(range(1, count + 1)),
            'CTest catalogue incomplete/duplicated')
    ends = re.findall(r'^(\d+)% tests passed(?:, (\d+) tests failed)? out of (\d+)\s*$', text, re.M)
    elapsed = re.findall(r'^Total Test time \(real\) =\s*([\d.]+) sec\s*$', text, re.M)
    require(len(ends) == len(elapsed) == 1, 'CTest terminal summary absent/repeated')
    totals = {status: sum(row['status'] == status for row in rows)
              for status in ('passed', 'skipped', 'disabled', 'failed_or_unknown')}
    percent, failures, enabled = (int(value or 0) for value in ends[0])
    require(percent == 100 and failures == 0 and totals['failed_or_unknown'] == 0
            and enabled == count - totals['disabled']
            and totals['passed'] + totals['skipped'] == enabled, 'CTest terminal/catalogue results disagree')
    return {'catalogue': count, 'enabled': enabled, 'executed_passing': totals['passed'],
            'skipped': totals['skipped'], 'disabled': totals['disabled'], 'failed': failures,
            'real_seconds': float(elapsed[0]), 'complete_catalogue_verified': True,
            'skipped_rows': [row for row in rows if row['status'] == 'skipped'],
            'disabled_rows': [row for row in rows if row['status'] == 'disabled']}


class Audit:
    def __init__(self, plan):
        self.plan = plan
        self.config = plan['config']
        self.packet = Packet()
        self.files = {}
        for entry in plan['files']:
            path = source_path(entry['scope'], entry['path'])
            require(str(path) not in self.files, 'Duplicate explicit source input')
            self.files[str(path)] = entry
            self.packet.add(entry)
        require(len(self.files) == plan['planned_input_count'], 'Plan count differs')

    def bound(self, path, wanted=None):
        path = Path(path)
        require(str(path) in self.files, f'Semantic input not approved for publication: {path}')
        observed = descriptor(path)
        require(observed['sha256'] == self.files[str(path)]['sha256'], 'Planned bytes changed')
        if wanted is not None:
            require(observed['sha256'] == wanted, f'Receipt-bound bytes differ: {path}')
        return path

    def obj(self, path, wanted=None):
        return load(self.bound(path, wanted))

    def reference(self, path, wanted):
        """Hash-only references may include binaries; never add them to packet."""
        require(descriptor(path)['sha256'] == wanted, f'Hash-only reference differs: {path}')

    def file_map(self, mapping):
        require(isinstance(mapping, dict) and mapping, 'Empty source/file custody map')
        for path, wanted in mapping.items():
            require(isinstance(path, str) and Path(path).is_absolute()
                    and re.fullmatch('[0-9a-f]{64}', wanted), 'Invalid file SHA map')
            self.reference(path, wanted)

    def process(self, row):
        require(row['passed'] is True and row['returncode'] == 0
                and row['child_reaped'] is True and row['process_group_gone'] is True
                and row['timed_out'] is False, 'Gate failed, timed out or left owned children')

    def protected(self, row):
        require(row['app_and_profiles_unchanged'] is True
                and row['selected_critical_dependencies_unchanged'] is True,
                'Protected application/profiles/selected dependencies changed')
        for kind in ('custody', 'critical'):
            before, after = f'private_{kind}_before_sha256', f'private_{kind}_after_sha256'
            if before in row and after in row:
                require(row[before] == row[after], 'Private scoped custody digests differ')

    def log(self, directory, row):
        return read_regular(self.bound(Path(directory) / 'run.log', row['log_sha256'])).decode()

    def build(self):
        directory = PRIVATE / self.config['build_directory']
        row = self.obj(directory / 'execution.json')
        self.process(row)
        self.protected(row)
        self.log(directory, row)
        require(row['mode'] == 'build' and row['installation_performed'] is False
                and row['source_and_supervisor_unchanged'] is True
                and row['source_before'] == row['source_after']
                and row['source_after']['git_head'] == self.config['source_commit']
                and row['Fem_python_source_build_parity'] is True
                and row['Fem_capacity_json_source_build_parity'] is True
                and row['native_source_sha256'] == NATIVE, 'Final source build identity/parity differs')
        self.file_map(row['source_after']['files'])
        built = row['build_after']
        require(built['version_header']['FCRepositoryHash'] == self.config['source_commit']
                and built['version_header']['FCRevision'] == self.config['revision']
                and built['fem_python_copy_parity']['passed'] is True
                and built['fem_capacity_json_copy_parity']['passed'] is True,
                'Final compiled header or complete FEM copy parity differs')
        self.file_map(built['files'])
        return {'receipt': descriptor(directory / 'execution.json'),
                'elapsed_seconds': row['elapsed_seconds'], 'version_header': built['version_header']}

    def native_compilation(self):
        attestation = self.obj(PRIVATE / 'qa/native-capacity-r01-attestation-v2.json')
        require(attestation['passed'] is True and attestation['derived_receipt'] is True
                and attestation['new_execution_performed'] is False
                and attestation['contract_compilation_claimed'] is False
                and attestation['native_source_sha256'] == NATIVE
                and attestation['compiled_sources_sha256'] == {key: NATIVE[key] for key in ('forceaccounting.c', 'hooks.patch')}
                and attestation['candidate']['sha256'] == CANDIDATE,
                'Derived current-contract attestation misstates existing compilation')
        self.reference(attestation['candidate']['path'], CANDIDATE)
        for stamp in attestation['original_evidence'].values():
            self.bound(stamp['path'], stamp['sha256'])
        receipt = self.obj(PRIVATE / 'native-capacity-r01/native/build-receipt.json')
        require(receipt['binary_sha256'] == CANDIDATE
                and receipt['extra_source_sha256'] == NATIVE['forceaccounting.c']
                and receipt['probe_patch_sha256'] == NATIVE['hooks.patch']
                and receipt['channel'] == 'CCX_FORCE_ACCOUNTING_V3'
                and receipt['dependency_functional_tests_passed'] is True
                and receipt['physical_duty_qualified'] is False and receipt['installed'] is False,
                'Original native compilation pins differ')
        return {'receipt': descriptor(PRIVATE / 'native-capacity-r01/native/build-receipt.json'),
                'observed_contract_attestation': descriptor(PRIVATE / 'qa/native-capacity-r01-attestation-v2.json'),
                'new_compilation_claimed_by_derived_attestation': False}

    def app(self, name, spec):
        directory = PRIVATE / spec['directory']
        row = self.obj(directory / 'execution.json')
        manifest = self.obj(directory / 'manifest.json', row['manifest_sha256'])
        identity = self.obj(directory / 'identity.json', row['identity_sha256'])
        text = self.log(directory, row)
        self.process(row)
        self.protected(row)
        require(row['inputs_unchanged'] is True
                and row['inputs_before']['files'] == row['inputs_after']
                and row['inputs_before']['git_head'] == self.config['source_commit']
                and row['installation_performed'] is False
                and row['skipped_lines'] == []
                and row['missing_repeated_or_skipped_ids'] == [], 'App custody/skip status differs')
        self.file_map(row['inputs_after'])
        require(manifest['module'] == spec['module']
                and manifest['expected_count'] == spec['expected_count']
                and manifest['discovery_only'] is False
                and manifest['inputs']['git_head'] == self.config['source_commit']
                and manifest['version_header']['FCRepositoryHash'] == self.config['source_commit']
                and manifest['version_header']['FCRevision'] == self.config['revision'],
                'Application manifest differs from explicit final role/identity')
        require(identity['passed'] is True
                and identity['runtime'][7] == self.config['source_commit']
                and identity['runtime'][3] == self.config['revision']
                and identity['runtime'] == row['runtime']
                and identity['selected_suite']['name'] == spec['module']
                and identity['selected_suite']['count'] == spec['expected_count'] - 1
                and len(identity['selected_suite']['ids']) == spec['expected_count'] - 1
                and len(set(identity['selected_suite']['ids'])) == spec['expected_count'] - 1,
                'Loaded app runtime/suite identity differs')
        candidate = manifest['candidate']
        require(candidate == identity['candidate']
                and candidate['path'] == str(BUILD / 'data/NativeSolvers/ccx-force-accounting')
                and candidate['sha256'] == CANDIDATE
                and candidate['schema'] == 'CCX_FORCE_ACCOUNTING_V3'
                and candidate['override'] is False, 'Wrong or overridden native candidate')
        self.reference(candidate['path'], CANDIDATE)
        for field in ('process', 'app_library'):
            stamp = identity[field]
            require(Path(stamp['path']).is_relative_to(BUILD), 'Runtime identity escaped source build')
            self.reference(stamp['path'], stamp['sha256'])
        for stamp in identity['loaded_FEM_python'].values():
            require(Path(stamp['path']).is_relative_to(BUILD / 'Mod/Fem'), 'Loaded FEM module escaped build')
            self.reference(stamp['path'], stamp['sha256'])
            self.reference(stamp['source'], stamp['sha256'])
        counts = re.findall(r'^Ran (\d+) tests? in ([0-9.]+)s$', text, re.M)
        require(len(row['unittest_counts']) == 1
                and counts == [(str(spec['expected_count']), row['unittest_counts'][0][1])]
                and row['unittest_counts'] == [list(counts[0])]
                and len(re.findall(r'^OK$', text, re.M)) == 1
                and not re.search(r'^(?:FAILED|FAIL:|ERROR:|UNEXPECTED SUCCESS)', text, re.M)
                and not re.search(r'^.*\.\.\. skipped .*$', text, re.M), 'App raw unittest log/count status differs')
        ids = identity['selected_suite']['ids']
        require(set(spec['critical_ids']).issubset(ids), 'Critical native methods absent from suite')
        for test_id in ids:
            pattern = '^' + re.escape(test_id.rsplit('.', 1)[-1]) + r' \(' + re.escape(test_id) + r'\)([^\n]*)$'
            matches = re.findall(pattern, text, re.M)
            require(len(matches) == 1 and 'skipped' not in matches[0],
                    'Missing/repeated/skipped actual method: ' + test_id)
        return {'role': name, 'receipt': descriptor(directory / 'execution.json'),
                'module': spec['module'], 'registered_tests': spec['expected_count'] - 1,
                'identity_tests': 1, 'skipped': 0, 'runtime': identity['runtime'],
                'critical_ids': spec['critical_ids'], 'elapsed_seconds': row['elapsed_seconds']}

    def primary_generation(self):
        directory = PRIMARY.parent
        row = self.obj(directory / 'execution.json')
        manifest = self.obj(directory / 'manifest.json', row['manifest_sha256'])
        identity = self.obj(directory / 'identity.json', row['identity_sha256'])
        self.process(row)
        self.protected(row)
        text = self.log(directory, row)
        require(identity['passed'] is True and row['runtime'] == identity['runtime']
                and identity['runtime'][3] == '49261 +222 (Git)'
                and identity['runtime'][7] == 'a878b8ae8e0536a70b016b80b4b92ff7c8f75dff'
                and manifest['module'] == 'YzkCapacityAtLimit' and manifest['expected_count'] == 2
                and identity['candidate']['sha256'] == CANDIDATE
                and identity['candidate']['override'] is False
                and row['inputs_unchanged'] is True
                and row['inputs_before']['files'] == row['inputs_after']
                and row['skipped_lines'] == [] and row['missing_repeated_or_skipped_ids'] == []
                and len(re.findall(r'^Ran 2 tests in [0-9.]+s$', text, re.M)) == 1
                and len(re.findall(r'^OK$', text, re.M)) == 1,
                'Original primary132 runtime/process custody differs')
        return {'runtime': identity['runtime'], 'receipt': descriptor(directory / 'execution.json'),
                'dirty_source_file_pins_retained_in_original_receipts': True,
                'rebound_to_final_committed_source': False}

    def physical(self, directory, portable=False):
        directory = Path(directory)
        row = self.obj(directory / 'witness-receipt.json')
        audit = self.obj(directory / 'independent-export-audit.json', row['export_audit_sha256'])
        require(row['passed'] is True and row['rows_y'] == 11 and row['columns_z'] == 12
                and row['solver_returncode'] == 0 and row['physical_check_count'] == 3566
                and len(row['checks']) == 3566
                and row['force_and_original_origin_moment_limit'] == 0.01
                and row['local_generalized_force_and_couple_limit'] == 0.01
                and row['scalar_response_limit'] == 0.05
                and row['actual_binary_sha256'] == CANDIDATE
                and row['explicit_candidate_override'] is None
                and row['only_public_native_interfaces'] is True
                and row['no_deck_patches_or_mocks'] is True
                and row['protected_inputs_unchanged'] is True
                and row['inputs_before'] == row['inputs_after']
                and row['engineering_or_BIM_accepted'] is False
                and row['Oomakhi_accessed_or_solved'] is False, 'Full physical qualification scope differs')
        require(audit['passed'] is True and audit['counts'] == {
                'ANGLE': 792, 'BODY': 264, 'PORT': 264, 'SPC_SUPPORT': 1, 'SPRING': 792}
                and audit['all_declarations_and_actual_elements_once_only'] is True
                and audit['all_reference_modes_unprescribed'] is True
                and audit['whole_applied_reference'] == [1584, 0, 0, 792, 39600, -34848]
                and audit['whole_applied_wrench'] == [1584, 0, 0, 792, 39600, -34848]
                and len(audit['body_ownership']) == 264
                and len(audit['scalar_incidence']) == 792,
                'Independent complete graph/load/incidence proof differs')
        for check in row['checks']:
            require(check['passed'] is True and check['limit'] in (0.01, 0.05)
                    and math.isfinite(check['relative_error'])
                    and 0 <= check['relative_error'] <= check['limit'], 'Physical frozen check failed')
        cold = self.obj(directory / 'cold-case.json', row['cold_manifest_sha256'])
        accounting = self.obj(directory / 'native-accounting-data.json')
        require(accounting['capacity_applied'] == {'budget': 2113, 'counts': COUNTS, 'total': 2113}
                and accounting['capacity']['required'] == COUNTS
                and accounting['capacity']['total'] == 2113
                and accounting['capacity']['supported']['total_records'] == 2113
                and accounting['capacity']['binary_sha256'] == CANDIDATE
                and accounting['binary_sha256'] == CANDIDATE, 'Actual imported capacity provenance differs')
        stdout = read_regular(self.bound(directory / 'native.stdout')).decode()
        echoes = re.findall(r'^CCX_FORCE_ACCOUNTING_CAPACITY_APPLIED_V1 (.+)$', stdout, re.M)
        require(len(echoes) == 1 and json.loads(echoes[0]) == accounting['capacity_applied'],
                'Owned native stdout lacks one exact applied-budget echo')
        require(cold['binary_sha256'] == CANDIDATE and set(cold['source_files']) ==
                {'deck', 'request', 'native_output', 'dat', 'frd'}, 'Incomplete saved cold source corpus')
        # Retained portable JSON copies point to original private generic
        # witness files. Their immutable originals are checked, never copied
        # through the profile namespace or relabelled to the retained paths.
        original_directory = Path(row['cold_manifest']).parent
        for name, stamp in row['retained_files'].items():
            path = original_directory / name
            require(not Path(name).is_absolute() and '..' not in Path(name).parts,
                    'Unsafe physical retained name')
            self.reference(path, stamp['sha256'])
            require(path.stat().st_size == stamp['bytes'], 'Physical retained byte size differs')
        for key in ('deck', 'request'):
            self.reference(row[key], row['original_native_input_sha256'][key])
        for stamp in cold['source_files'].values():
            self.reference(stamp['path'], stamp['sha256'])
            if not portable:
                self.bound(stamp['path'], stamp['sha256'])
        self.reference(cold['document'], cold['document_sha256'])
        if not portable:
            self.bound(cold['document'], cold['document_sha256'])
            require(row['frozen_oracle_sha256'] == ORACLES, 'Primary frozen oracle changed')
            proof = self.obj(directory / 'exact-budget-proof.json')
            require(proof['passed'] is True and proof['budget'] == 2113
                    and proof['required'] == COUNTS
                    and proof['actual_owned_child_receipt'] ==
                    {'budget': 2113, 'counts': COUNTS, 'total': 2113}
                    and proof['same_frozen_geometry_loads_supports_and_oracles'] is True,
                    'Primary exact owned-child budget proof differs')
        else:
            require(row['in_process_historical_reopen']['passed'] is True
                    and row['in_process_historical_reopen']['separate_process_cold_claimed'] is False,
                    'Portable in-process historical restore was mislabelled as cold proof')
        return {'receipt': descriptor(directory / 'witness-receipt.json'),
                'physical_checks': len(row['checks']), 'counts': COUNTS, 'budget': 2113,
                'max_relative_error': max(item['relative_error'] for item in row['checks']),
                'saved_document_sha256': cold['document_sha256'],
                'cold_manifest_sha256': row['cold_manifest_sha256'],
                'original_witness_directory': str(original_directory),
                'separate_process_cold_claimed_by_this_physical_receipt': False}

    def portable_copy(self):
        spec = self.config['portable_retained']
        retained = PRIVATE / spec['directory']
        custody = self.obj(PRIVATE / spec['copy_custody'])
        # Root supplies the actual custody schema after the portable run. Its
        # explicit rows must name all and only the11 approved generic files.
        names = {'witness-receipt.json', 'independent-export-audit.json',
                 'physical-face-motion-proof.json', 'motion-from-original-dat.json',
                 'cold-case.json', 'geometry-contract.json', 'export-properties.json',
                 'native-properties.json', 'native-accounting-data.json', 'native.stdout', 'native.stderr'}
        require(custody['schema'] == 'FreeCAD-yzk-exact-portable-selection-v1'
                and custody['passed'] is True and len(custody['files']) == len(names)
                and custody['all_originals_unchanged'] is True and custody['all_copies_exact'] is True
                and custody['profile_cache_or_environment_payloads_copied'] is False
                and custody['large_FCStd_FRD_payloads_copied'] is False,
                'Incomplete explicit portable-copy custody')
        for name in ('source_run_manifest', 'source_run_execution'):
            self.bound(custody[name]['path'], custody[name]['sha256'])
        self.bound(custody['copy_helper']['path'], custody['copy_helper']['sha256'])
        actual = set()
        for row in custody['files']:
            original, copied = Path(row['source']), retained / row['path']
            require(copied.parent == retained and copied.name in names
                    and original.name == copied.name
                    and original.parent == Path(custody['source_witness_directory'])
                    and original.is_relative_to(PRIVATE / self.config['applications']['portable']['directory'])
                    and original.parent.name == 'witness'
                    and original.parent.parent.name.startswith('freecad-moving-port-capacity-native-'),
                    'Portable copy escaped its single declared generic witness')
            self.bound(copied, row['sha256'])
            self.reference(original, row['sha256'])
            require(read_regular(original) == read_regular(copied)
                    and copied.stat().st_size == row['bytes'], 'Portable copy is not byte-identical')
            actual.add(copied.name)
        require(actual == names, 'Missing/duplicate selected portable JSON')
        return retained

    def cold(self, path, expected_manifest):
        row = self.obj(path)
        require(row['passed'] is True and row['manifest_sha256'] == expected_manifest
                and row['status'].startswith('Stale')
                and row['no_history_or_provenance_repair'] is True
                and row['no_native_solve'] is True and row['no_save'] is True,
                'Cold control promoted Current, rewrote history or lost source binding')
        return {'receipt': descriptor(path), 'status': row['status'],
                'manifest_sha256': expected_manifest, 'no_solve_save_or_repair': True}

    def legacy(self, version, relative):
        directory = PRIVATE / relative
        outer = self.obj(directory / 'execution.json')
        manifest = self.obj(directory / 'manifest.json', outer['manifest_sha256'])
        self.process(outer)
        self.protected(outer)
        self.log(directory, outer)
        require(outer['candidate_sha256'] == CANDIDATE
                and outer['protected_inputs_unchanged'] is True
                and outer['corpus_inputs_unchanged'] is True
                and outer['manifest_unchanged'] is True
                and outer['post_run_serial_guard_passed'] is True
                and outer['installation_performed'] is False
                and manifest['version'] == version, 'Legacy outer custody differs')
        qualification = outer['qualification']
        summary = self.obj(qualification['summary'], qualification['summary_sha256'])
        corpus = Path(manifest['corpus'])
        inner = self.obj(corpus / 'manifest.json', manifest['corpus_manifest_sha256'])
        require(corpus == PRIVATE / (relative + '-corpus'), 'Legacy corpus namespace differs')
        rows = summary['analytic_cases'] + summary['rejections'] if version == 'V1' else summary['reports']
        expected = (48, 6, 288) if version == 'V1' else (8, 2, 144)
        require(len(rows) == expected[0] + expected[1]
                and len({row['case'] for row in rows}) == len(rows)
                and {row['case'] for row in rows} == {row['name'] for row in manifest['cases']}
                and summary['binary_sha256' if version == 'V1' else 'candidate_sha256'] == CANDIDATE,
                'Legacy cases/candidate incomplete')
        by_name = {row['name']: row for row in manifest['cases']}
        positives = refusals = checks = 0
        for row in rows:
            case = by_name[row['case']]
            folder = Path(case['directory'])
            require(folder == corpus / case['name'] and row == self.obj(folder / 'execution.json'),
                    'Legacy case receipt differs from aggregate')
            require(row['passed'] is True and row['timed_out'] is False
                    and row['process_group_gone'] is True
                    and row['reaped' if version == 'V1' else 'child_reaped'] is True,
                    'Legacy native child failed or was not reaped')
            for path, wanted in case['input_files'].items():
                self.bound(path, wanted)
            self.bound(folder / 'solver.log', row['log_sha256' if version == 'V1' else 'solver_log_sha256'])
            output = folder / 'contact.accounting.out'
            if version == 'V1':
                require(row['inputs_before'] == row['inputs_after']
                        and row['protected_before'] == row['protected_after']
                        and row['inputs_unchanged'] and row['protected_unchanged']
                        and row['manifest_unchanged'], 'Legacy V1 input custody differs')
                for name, wanted in row['outputs'].items():
                    self.reference(folder / name, wanted)
            else:
                require(row['custody_before'] == row['custody_after']
                        and row['protected_inputs_unchanged'] is True,
                        'Legacy V2 input custody differs')
                require(row['native_output_sha256'] ==
                        (descriptor(output)['sha256'] if output.is_file() else None),
                        'Legacy V2 output hash differs')
            if output.is_file():
                self.bound(output)
            if case['positive']:
                require(row['returncode'] == 0, 'Positive legacy native case refused')
                values = ([value for pair in row['relative_force_moment_errors'].values() for value in pair]
                          if version == 'V1' else [check['relative_error'] for check in row['checks']])
                require(len(values) == (6 if version == 'V1' else 18)
                        and all(math.isfinite(value) and 0 <= value <= .01 for value in values),
                        'Legacy frozen1% independent checks failed')
                if version == 'V2':
                    require(all(check['passed'] is True and check['limit'] == .01 for check in row['checks']),
                            'Legacy V2 fixed limits changed')
                positives += 1
                checks += len(values)
            else:
                require(row['returncode'] == 201 and
                        (not output.exists() or 'END' not in read_regular(output).decode().splitlines()),
                        'Legacy refusal not exact201 or left completed accounting')
                refusals += 1
        require((positives, refusals, checks) == expected
                and tuple(qualification[k] for k in ('positive_cases', 'expected_refusals', 'physical_norm_checks')) == expected,
                'Legacy final total differs')
        require(inner['schema'] == 'FreeCAD-ywu.LEGACY_V1_PREDECLARED.1' if version == 'V1' else
                inner['accounting_schema'] == 'CCX_FORCE_ACCOUNTING_V2', 'Unexpected legacy schema')
        return {'receipt': descriptor(directory / 'execution.json'), 'positive_cases': positives,
                'expected_refusals': refusals, 'physical_norm_checks': checks,
                'FreeCAD_writer_or_capacity_graph_coverage': False}

    def ctest(self):
        directory = PRIVATE / self.config['ctest_directory']
        row = self.obj(directory / 'execution.json')
        self.process(row)
        self.protected(row)
        text = self.log(directory, row)
        require(row['mode'] == 'ctest' and row['ctest_parallel'] == 1
                and row['source_build_supervisor_candidate_unchanged'] is True
                and row['post_run_serial_guard_passed'] is True
                and row['installation_performed'] is False, 'CTest protected status differs')
        parsed = row['ctest']
        # The supervisor's parser records the complete catalogue and terminal
        # actual statuses; do not infer counts from the historical old run.
        require(parsed['complete_catalogue_verified'] is True and parsed['failed'] == 0,
                'Complete CTest parser did not pass')
        require(parsed == parse_ctest(text), 'Independent complete CTest parse differs')
        require(row['protected_inputs_before'] == row['protected_inputs_after'], 'CTest protected input maps differ')
        self.file_map(row['protected_inputs_after']['source']['files'])
        self.file_map(row['protected_inputs_after']['build']['files'])
        require(row['protected_inputs_after']['source']['git_head'] == self.config['source_commit'],
                'CTest source identity differs')
        retained = set(self.config['ctest_retained_logs'])
        for name, stamp in row['ctest_logs_after'].items():
            relative = str(Path(self.config['ctest_directory']) / name)
            if stamp['fresh_for_this_run']:
                require(relative in retained, 'Fresh CTest log not explicitly retained')
                self.bound(PRIVATE / relative, stamp['sha256'])
            else:
                require(relative not in retained, 'Stale CTest diagnostic mislabelled as fresh evidence')
        for relative in self.config['ctest_retained_logs']:
            self.bound(PRIVATE / relative)
        return {'receipt': descriptor(directory / 'execution.json'), 'actual_complete_catalogue': parsed,
                'parallel': 1, 'default_timeout_seconds': row['ctest_default_test_timeout_seconds'],
                'existing_test_TIMEOUT_properties_overridden': False}

    def static_review(self):
        directory = PRIVATE / self.config['static_directory']
        row = self.obj(directory / 'execution.json')
        require(row['passed'] is True and row['inputs_before'] == row['inputs_after'], 'Static input custody differs')
        self.file_map(row['inputs_after'])
        for number, check in enumerate(row['commands']):
            require(check['returncode'] == 0 and check['child_reaped'] is True
                    and check['process_group_gone'] is True and check['timed_out'] is False,
                    'Static command failed or was not reaped')
            self.bound(directory / f'check-{number}.log', check['log_sha256'])
        review = self.obj(PRIVATE / self.config['review_receipt'])
        require(review['passed'] is True and review['standards']['outstanding_findings'] == []
                and review['spec']['outstanding_findings'] == []
                and review['subsequent_committed_binding']['commit'] == self.config['source_commit']
                and review['subsequent_committed_binding']['reviewed_file_hashes_still_apply'] is True,
                'Final review has unresolved findings or wrong source binding')
        for path, wanted in review['reviewed_files'].items():
            self.bound(REPOSITORY / path, wanted)
        return {'static_receipt': descriptor(directory / 'execution.json'),
                'review_receipt': descriptor(PRIVATE / self.config['review_receipt']),
                'independence_disclosure': review['independence_disclosure']}

    def validate(self):
        require(self.plan['task_root'] == str(PRIVATE) and self.plan['repository'] == str(REPOSITORY),
                'Plan roots differ')
        # Only bounded read-only Git metadata commands; no checkout or writes.
        def git(*args):
            return subprocess.check_output(['git', *args], cwd=REPOSITORY, timeout=30,
                                           stdin=subprocess.DEVNULL).decode().strip()
        require(git('rev-parse', 'HEAD') == self.config['source_commit'], 'Final implementation HEAD differs')
        require(not git('diff', '--name-only', 'HEAD', '--', 'src/Mod/Fem', 'package/calculix/force-accounting'),
                'Product source changed after final implementation commit')
        for name, wanted in NATIVE.items():
            self.bound(REPOSITORY / 'package/calculix/force-accounting' / name, wanted)
        for name, wanted in ORACLES.items():
            self.bound(PRIVATE / 'oracle' / name, wanted)
        result = {'build': self.build(), 'native_compilation': self.native_compilation()}
        require({'fem', 'gui', 'portable'}.issubset(self.config['applications']), 'Missing final source app roles')
        result['applications'] = {name: self.app(name, spec)
                                  for name, spec in self.config['applications'].items()}
        result['primary_132'] = self.physical(PRIMARY)
        result['primary_132']['generation'] = self.primary_generation()
        result['primary_132']['runtime_scope'] = 'Original +222/a878 dirty file-pinned source execution; NOT relabelled final commit'
        primary_audit = self.obj(PRIVATE / 'native-qa/primary-physical-independent-audit.json')
        require(primary_audit['passed'] is True and primary_audit['findings'] == []
                and primary_audit['acceptance']['named_checks_independently_recomputed'] == 3566
                and primary_audit['acceptance']['five_percent_differential_response_unchanged'] == .05
                and primary_audit['acceptance']['one_percent_wrench_and_original_origin_moment_unchanged'] == .01,
                'Independent completed-primary audit differs')
        result['primary_132']['independent_evidence_review'] = {
            'receipt': descriptor(PRIVATE / 'native-qa/primary-physical-independent-audit.json'),
            'auditor_disclosure': primary_audit['auditor_disclosure']}
        result['primary_cold'] = self.cold(PRIVATE / 'qa-v2/coupled-capacity-cold-r02/cold-receipt.json',
                                            result['primary_132']['cold_manifest_sha256'])
        refusal = self.obj(PRIVATE / 'qa-v2/coupled-capacity-refusal-r01/capacity-refusal-proof.json')
        require(refusal['passed'] is True and refusal['budget'] == 2112
                and refusal['total_required'] == 2113 and refusal['required'] == COUNTS
                and refusal['stock_export_directory_untouched'] is True
                and refusal['no_mesh_export_or_FE_solve'] is True, 'One-below graph refusal differs')
        result['primary_one_below'] = {'budget': 2112, 'required': 2113, 'passed': True}
        result['portable_132'] = self.physical(self.portable_copy(), portable=True)
        result['portable_cold'] = self.cold(PRIVATE / self.config['portable_cold_receipt'],
                                             result['portable_132']['cold_manifest_sha256'])
        require(set(self.config['legacy']) == {'V1', 'V2'}, 'Missing legacy protocol')
        result['legacy'] = {version: self.legacy(version, relative)
                            for version, relative in self.config['legacy'].items()}
        result['ctest'] = self.ctest()
        result['quality'] = self.static_review()
        before = self.obj(PRIVATE / 'port-benchmark-before-r02/port-benchmark.json')
        after = self.obj(PRIVATE / self.config['benchmark_report'])
        require(before['passed'] is True and after['passed'] is True
                and before['queried_result_dictionaries'] == after['queried_result_dictionaries']
                and before['public_native_ID_outputs'] == after['public_native_ID_outputs']
                and before['result_dictionary_sha256'] == after['result_dictionary_sha256']
                and after['no_solve_writer_mesher_recompute_save_or_model_edit'] is True
                and after['frozen_model_and_original_evidence_unchanged'] is True
                and after['inputs_before'] == after['inputs_after'], 'Public benchmark output/custody changed')
        result['public_benchmark'] = {
            'before_receipt': descriptor(PRIVATE / 'port-benchmark-before-r02/port-benchmark.json'),
            'after_receipt': descriptor(PRIVATE / self.config['benchmark_report']),
            'before_seconds': before['resolve_total_seconds'], 'after_seconds': after['resolve_total_seconds'],
            'exact_returned_values_and_native_IDs_unchanged': True,
            'timing_is_diagnostic_only_not_a_fitted_threshold_or_SLA': True}
        unit = self.obj(PRIVATE / 'native-capacity-unit-r02/summary.json')
        require(unit['passed'] is True and len(unit['cases']) == 46
                and all(case['passed'] is True and case['child_reaped'] is True
                        and case['process_group_gone'] is True and case['timed_out'] is False
                        for case in unit['cases'])
                and unit['physical_or_engineering_qualification'] is False,
                'Artificial native unit evidence differs')
        result['artificial_component_cases'] = {'cases': 46, 'includes_sanitizers': True,
            'finite_element_or_engineering_qualification': False}
        self.packet.unchanged()
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    require(not sys.flags.optimize, 'Use an unoptimized interpreter')
    plan_path = args.plan.absolute()
    require(plan_path.parent == PRIVATE / 'collection'
            and digest(read_regular(plan_path)) == args.plan_sha256, 'Exact reviewed private plan required')
    plan = load(plan_path)
    require(plan['schema'] == 'FreeCAD-yzk-source-approved-file-plan-v1', 'Wrong plan schema')
    audit = Audit(plan)
    results = audit.validate()
    audit.packet.add({'scope': 'private', 'path': str(plan_path.relative_to(PRIVATE)),
        'destination': 'approved-plan.json', 'sha256': args.plan_sha256, 'kind': 'receipt',
        'classification': 'Exact root-reviewed explicit publication plan; producer did not execute product gates'})
    index = {'schema': 'FreeCAD-yzk-source-evidence-index-v1',
             'files': sorted(audit.packet.records, key=lambda row: row['file']),
             'explicit_plan': descriptor(plan_path), 'input_count': len(plan['files']),
             'indexed_file_count': len(audit.packet.records),
             'privacy': 'No raw profile/application inventories, secrets, runtime binaries or vendor tree payloads',
             'source_only': True}
    summary = {'schema': 'FreeCAD-yzk-source-validation-v1', 'passed': True,
        'implementation_commit': plan['config']['source_commit'], 'revision': plan['config']['revision'],
        'native': {'candidate_sha256': CANDIDATE, 'sources_sha256': NATIVE,
                   'contract_observed_not_compiled': True}, 'qualification': results,
        'evidence': {'directory': str(DESTINATION.relative_to(REPOSITORY)),
                     'index_sha256': digest(json_bytes(index)), 'indexed_files': len(index['files']),
                     'approved_plan_sha256': args.plan_sha256},
        'scope': {'source_only': True, 'installation_performed': False,
                  'protected_application_and_user_profiles_unchanged_according_to_scoped_receipts': True,
                  'selected_critical_dependency_pins_unchanged_according_to_scoped_receipts': True,
                  'entire_dependency_environment_filesystem_unchanged_claimed': False,
                  'engineering_or_BIM_accepted': False, 'Oomakhi_accessed_or_solved': False,
                  'original_side_loaded_fixture_inputs_rewritten': False,
                  'separate_predeclared_generic_coupled_fixture': True,
                  'R49_11_123267892_percent_remains_FAIL_against_5_percent': True,
                  'R51_5_240441298_percent_remains_FAIL_against_5_percent': True,
                  'force_original_origin_moment_limit': .01, 'scalar_response_limit': .05},
        'history': 'Exact failed/setup/timed-out/intermediate receipts retain their explicit individual classifications; no historical runtime rebinding.'}
    privacy_check(summary, 'validation summary')
    audit.packet.unchanged()
    if not args.check_only:
        audit.packet.publish_new(DESTINATION, SUMMARY, index, summary)
    print(json_bytes({'passed': True, 'check_only': args.check_only,
        'writes': 0 if args.check_only else len(index['files']) + 2,
        'index_sha256': digest(json_bytes(index)), 'summary_sha256': digest(json_bytes(summary)),
        'indexed_files': len(index['files']), 'source_only': True}).decode(), end='')


if __name__ == '__main__':
    main()
