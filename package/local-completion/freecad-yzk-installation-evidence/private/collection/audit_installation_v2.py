"""Filesystem-only final installation audit; root alone executes after all gates.

No application, solver, test, build, signing, installation or Git command is
invoked. Signature status is inherited from successful sealed-image audits and
unchanged bytes, not from a new signature verification. Raw inventories remain
private. Missing or incomplete receipts fail before any final audit is written.
"""
import sys
sys.dont_write_bytecode = True

import argparse
import ast
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat

from evidence_packet import PRIVATE, REPOSITORY, json_bytes, privacy_check, require


APP = Path('/Applications/FreeCAD-27.1.0.app')
BACKUP = Path('/Users/zukomgwili/Applications/FreeCAD Backups/FreeCAD-27.1.0-before-yzk-6cdc1affda.app')
STAGE = PRIVATE / APP.name
BUILD = REPOSITORY / 'build/release'
CAPSULE = PRIVATE / 'installed-retained-r01'
SOURCE_QA = REPOSITORY / 'package/local-completion/freecad-yzk-validation.json'
NATIVE = {'forceaccounting.c': '8c51e06abecf4c2b1537b1e6f4ef4606ea8481a4a180d465cbff00d63329f2a4',
          'hooks.patch': 'e500c46cc9cd26fc4e63508a51375bd09ebdc0973638375df14cffd036c9bfa7',
          'contract.json': '8086e668ed9383a324fbfff7cbe8621d919c46da844924d507252a24f85a77eb'}
COUNTS = {'supports': 1, 'bodies': 264, 'ports': 264, 'angles': 792, 'springs': 792}
STEPS = ('payload', 'audit-payload', 'stage', 'audit-stage', 'audit-custody', 'swap')
GATES = (
    ('stage-fem', 'TestFemApp', 406), ('stage-gui', 'TestFemGui', 9),
    ('stage-native', 'femtest.app.test_moving_port_accounting_native', 6),
    ('installed-fem', 'TestFemApp', 406), ('installed-gui', 'TestFemGui', 9),
    ('installed-native', 'femtest.app.test_moving_port_accounting_native', 6),
    ('installed-capacity', 'femtest.app.test_moving_port_capacity_native', 2),
    ('installed-cold', 'YzkPortableColdRestore', 2),
)
ROOT_HELPERS = ('AppYzkIdentity.py', 'YzkPortableColdRestore.py', 'audit_payload_stage.py',
    'critical_pins.py', 'harness_config.py', 'preservation.py', 'process_control.py',
    'process_control_devnull.py', 'run_app.py', 'run_build_gate.py', 'run_step.py', 'stage_install.py')
COLLECTION_HELPERS = ('audit_installation.py', 'audit_installation_v2.py',
                      'collect_installation.py', 'collect_installation_v2.py',
                      'copy_installed_selection.py', 'copy_installed_selection_v2.py',
                      'history/copy_installed_selection_v2-before-receipt-collision-guard.py',
                      'copy_installed_selection_v3.py', 'evidence_packet.py',
                      'prepare_plan.py', 'verify_publication.py')
SELECTED = ('witness-receipt.json', 'independent-export-audit.json',
    'physical-face-motion-proof.json', 'motion-from-original-dat.json', 'cold-case.json',
    'geometry-contract.json', 'export-properties.json', 'native-properties.json',
    'native-accounting-data.json', 'native.stdout', 'native.stderr',
    'native/Mesh.inp', 'native/Mesh.accounting', 'native/Mesh.accounting.json',
    'native/Mesh.accounting.out', 'native/Mesh.dat')
SELECTED_FEM_SOURCES = (
    'ObjectsFem.py', 'TestFemApp.py', 'TestFemGui.py', 'femcommands/commands.py',
    'femobjects/solver_ccxtools.py', 'femobjects/result_contact_observation.py',
    'femresult/contact_observation.py', 'femresult/contact_observation_source.py',
    'femresult/owned_probe.py', 'femtools/force_accounting.py', 'femtools/ccxtools.py',
    'femmesh/meshtools.py', 'femmesh/meshsetsgetter.py', 'femmesh/ownership_context.py',
    'femsolver/calculix/write_constraint_elastic_connector.py',
    'femsolver/calculix/write_constraint_tie.py', 'femsolver/calculix/write_constraint_contact.py',
    'femtest/app/test_moving_port_accounting_native.py', 'femtest/app/test_tie_accounting_native.py',
    'femtest/app/test_force_accounting.py', 'femtest/app/test_movement_provenance.py',
    'femtest/app/test_tie_ownership.py', 'femtest/gui/test_contact_observation.py',
    'femtools/elastic_connector.py', 'femsolver/calculix/writer.py',
    'femsolver/calculix/write_constraint_rigidbody.py',
    'femsolver/calculix/write_constraint_rigidbody_step.py',
    'femtest/app/test_elastic_connector.py', 'femtest/app/coupled_port_fixture.py',
    'femtest/app/coupled_port_audit.py', 'femtest/app/test_moving_port_capacity_native.py',
    'femtest/data/calculix/coupled_port_capacity_fixture.json',
    'femtest/data/calculix/coupled_port_capacity_oracle.json',
)
ORIGINAL_INSTALLER = (REPOSITORY /
    'package/local-completion/freecad-ywu-installation-evidence/private/stage_install.py')


def sha(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'Not a regular file: ' + str(path))
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def stamp(path):
    path = Path(path)
    return {'path': str(path), 'sha256': sha(path), 'bytes': path.stat().st_size}


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def inventory(root):
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), 'Invalid inventory root: ' + str(root))
    result = {'.': {'kind': 'dir', 'mode': stat.S_IMODE(root.lstat().st_mode)}}
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in sorted(dirs + files):
            path = Path(directory) / name
            mode = path.lstat().st_mode
            row = {'mode': stat.S_IMODE(mode)}
            if stat.S_ISLNK(mode):
                row.update(kind='link', target=os.readlink(path))
            elif stat.S_ISDIR(mode):
                row.update(kind='dir')
            else:
                require(stat.S_ISREG(mode), 'Special filesystem entry: ' + str(path))
                row.update(kind='file', sha256=sha(path))
            result[str(path.relative_to(root))] = row
    return result


class Audit:
    def __init__(self):
        self.publishable = {}
        self.hash_only = {}
        self.captured = {}
        self.expected = {}
        self.config = {}
        config_path = PRIVATE / 'harness_config.py'
        config_bytes = config_path.read_bytes()
        self.captured[str(config_path)] = hashlib.sha256(config_bytes).hexdigest()
        for node in ast.parse(config_bytes).body:
            require(isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name), 'Nonliteral harness config')
            self.config[node.targets[0].id] = ast.literal_eval(node.value)
        require(self.config['COMMIT'] == '7667033a14654a9b229bf59b94cb3012ce989170'
                and self.config['REVISION'] == '49261 +224 (Git)'
                and self.config['NATIVE_SHA'] == '6c02452a896727af6cb4578fd3fb6bbfbdd48e3fb887c1c04fa2d8b171976c66',
                'Unexpected frozen deployment identity')

    def add(self, path, kind='receipt', classification='Exact completed installation evidence'):
        path = Path(path)
        scope = 'private' if path.is_relative_to(PRIVATE) else 'repository'
        root = PRIVATE if scope == 'private' else REPOSITORY
        require(path.is_relative_to(root), 'Publication input escaped known roots')
        relative = str(path.relative_to(root))
        row = {'scope': scope, 'path': relative, 'destination': scope + '/' + relative,
               'sha256': sha(path), 'kind': kind, 'classification': classification}
        if kind == 'generic-fixture':
            row['fixture_scope'] = 'generic software QA; not a retained engineering model'
        if str(path) in self.publishable:
            require(self.publishable[str(path)]['sha256'] == row['sha256'], 'Input changed during audit')
        else:
            self.publishable[str(path)] = row
        return path

    def read(self, path, public=True, kind='receipt'):
        path = Path(path)
        require(path.is_file() and not path.is_symlink(), 'Not a regular JSON input')
        payload = path.read_bytes()
        captured_sha = hashlib.sha256(payload).hexdigest()
        require(str(path) not in self.captured or self.captured[str(path)] == captured_sha,
                'JSON input changed between reads')
        self.captured[str(path)] = captured_sha
        if public:
            self.add(path, kind)
            require(self.publishable[str(path)]['sha256'] == captured_sha, 'Parsed/publication JSON bytes differ')
        else:
            self.hash_only[str(path)] = {'path': str(path), 'sha256': captured_sha, 'bytes': len(payload)}
        return json.loads(payload)

    def ref(self, path, wanted):
        path = str(Path(path))
        require(path not in self.expected or self.expected[path] == wanted,
                'Conflicting fixed reference SHA: ' + path)
        require(sha(path) == wanted, 'Referenced original changed: ' + str(path))
        self.expected[path] = wanted

    def critical_files(self, critical):
        require(critical['passed'] is True and len(critical['files']) == 16, 'Selected critical scope differs')
        for path, wanted in critical['files'].items():
            info = Path(path).lstat()
            actual = {'dev': info.st_dev, 'inode': info.st_ino, 'mode': info.st_mode,
                'size': info.st_size, 'mtime_ns': info.st_mtime_ns, 'ctime_ns': info.st_ctime_ns}
            if stat.S_ISLNK(info.st_mode):
                actual.update(kind='link', target=os.readlink(path), resolved=str(Path(path).resolve(strict=True)),
                              resolved_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest())
            else:
                actual.update(kind='file', sha256=sha(path))
            require(actual == wanted, 'Selected critical dependency changed')

    def namespace_files(self, namespace):
        require(len(namespace) == 11, 'Unexpected external canonical namespace scope')
        for relative, proof in namespace.items():
            require(proof['before'] == proof['after'], 'External canonical namespace baseline differs')
            self.ref(REPOSITORY / '.pixi/envs/default' / relative, proof['before'])

    def text(self, path, kind='text'):
        path = Path(path)
        require(path.is_file() and not path.is_symlink(), 'Not a regular text input')
        payload = path.read_bytes()
        captured_sha = hashlib.sha256(payload).hexdigest()
        require(str(path) not in self.captured or self.captured[str(path)] == captured_sha,
                'Text input changed between reads')
        self.captured[str(path)] = captured_sha
        self.add(path, kind)
        require(self.publishable[str(path)]['sha256'] == captured_sha, 'Parsed/publication text differs')
        return payload.decode('utf-8')

    def private(self, name):
        return self.read(PRIVATE / name, public=False)

    def native_image(self, path, application, sealed):
        path = Path(path)
        require(path.is_relative_to(application), 'Historical/installed origin escaped its app')
        row = sealed[str(path.relative_to(application))]
        require(row['kind'] == 'file', 'Expected regular sealed app origin')
        return row['sha256']

    def app_gate(self, label, module, total, sealed):
        directory = PRIVATE / label
        application = STAGE if label.startswith('stage-') else APP
        row = self.read(directory / 'execution.json')
        identity = self.read(directory / 'identity.json')
        manifest = self.read(directory / 'manifest.json')
        self.ref(directory / 'identity.json', row['identity_sha256'])
        self.ref(directory / 'manifest.json', row['manifest_sha256'])
        text = self.text(directory / 'run.log')
        self.ref(directory / 'run.log', row['log_sha256'])
        require(all(row[key] is True for key in ('passed', 'child_reaped', 'process_group_gone',
                    'application_unchanged', 'app_and_profiles_unchanged', 'critical_dependency_pins_unchanged',
                    'source_build_harness_unchanged', 'manifest_unchanged', 'post_run_serial_guard_passed'))
                and row['returncode'] == 0 and row['timed_out'] is False
                and row['application'] == str(application) and row['module'] == module
                and row['inputs_before'] == row['inputs_after'], 'Incomplete application gate: ' + label)
        for path, wanted in row['inputs_after'].items():
            self.ref(path, wanted)
        require(identity['passed'] is True and identity['application'] == str(application)
                and identity['runtime'][3] == self.config['REVISION']
                and identity['runtime'][-1] == self.config['COMMIT']
                and identity['source_or_build_import_override'] is False
                and identity['manifest_sha256'] == row['manifest_sha256']
                and identity['TestFemApp_count'] == 405
                and identity['candidate'] == {'path': str(application / 'Contents/Resources/data/NativeSolvers/ccx-force-accounting'),
                    'sha256': self.config['NATIVE_SHA'], 'capability': 'CCX_FORCE_ACCOUNTING_V3', 'override': False},
                'Literal app/native identity differs: ' + label)
        suite = identity['selected_suite']
        require(suite['name'] == module and suite['count'] == total - 1
                and len(suite['ids']) == len(set(suite['ids'])) == total - 1
                and manifest['module'] == module and manifest['expected_count'] == total
                and manifest['application'] == str(application)
                and manifest['commit'] == self.config['COMMIT'] and manifest['revision'] == self.config['REVISION']
                and row['skipped_lines'] == [] and len(row['unittest_counts']) == 1
                and int(row['unittest_counts'][0][0]) == total
                and len(re.findall(r'^Ran ' + str(total) + r' tests? in [0-9.]+s$', text, re.M)) == 1
                and len(re.findall(r'^OK$', text, re.M)) == 1
                and not re.search(r'^(FAILED|FAIL:|ERROR:|UNEXPECTED SUCCESS)', text, re.M),
                'Executed suite differs: ' + label)
        for test_id in suite['ids']:
            pattern = '^' + re.escape(test_id.rsplit('.', 1)[-1]) + r' \(' + re.escape(test_id) + r'\)([^\n]*)$'
            hits = re.findall(pattern, text, re.M)
            require(len(hits) == 1 and 'skipped' not in hits[0], 'Absent/repeated/skipped actual method')
        for when in ('before', 'after'):
            app_path = directory / ('private-application-' + when + '.json')
            state_path = directory / ('private-custody-' + when + '.json')
            self.ref(app_path, row['application_inventory_' + when + '_sha256'])
            self.ref(state_path, row['custody_' + when + '_sha256'])
            require(self.read(app_path, public=False) == sealed, 'Gate did not use the sealed image')
        require(self.read(directory / 'private-custody-before.json', public=False) ==
                self.read(directory / 'private-custody-after.json', public=False), 'Gate custody changed')
        require(row['critical_before_DESTDIR_sha256'] == sha(PRIVATE / 'critical-before-DESTDIR.json'),
                'Wrong selected dependency baseline')
        for proof in list(identity['copied_modules'].values()) + list(identity['loaded_fem_python'].values()):
            require(self.native_image(proof['origin'], application, sealed) == proof['sha256'],
                    'Loaded/copy module does not match sealed image')
            self.ref(proof['source'], proof['sha256'])
        for proof in identity['capacity_json_copies'].values():
            require(self.native_image(proof['path'], application, sealed) == proof['sha256'],
                    'Copied capacity JSON does not match sealed image')
            self.ref(proof['source'], proof['sha256'])
        for proof in list(identity['native_modules'].values()) + [identity['app_library'], identity['process_executable']]:
            require(self.native_image(proof['path'], application, sealed) == proof['sha256'],
                    'Native module/library/process differs from the sealed image')
        require(self.native_image(identity['candidate']['path'], application, sealed) == self.config['NATIVE_SHA'],
                'Native candidate differs from the sealed image')
        policy = identity['capacity_policy_query']
        require(policy['supported']['allocation'] == 'dynamic' and policy['supported']['total_records'] == 2113
                and policy['supported']['limits'] == dict.fromkeys(COUNTS, 2113)
                and policy['required'] == dict.fromkeys(COUNTS, 0) and policy['total'] == 0
                and policy['binary_sha256'] == self.config['NATIVE_SHA']
                and identity['capacity_policy_query_is_not_physical_qualification'] is True,
                'Resource-policy query differs or was mislabelled as physical proof')
        return {'receipt': stamp(directory / 'execution.json'), 'total_tests': total,
                'registered_tests': total - 1, 'identity_tests': 1, 'skipped': 0,
                'application_at_execution': str(application), 'runtime': identity['runtime']}

    def build_gate(self, name):
        directory = PRIVATE / (name + '-latest')
        row = self.read(directory / 'execution.json')
        self.ref(self.add(directory / 'run.log', 'text'), row['log_sha256'])
        require(row['passed'] is True and row['exit_code'] == 0 and row['timed_out'] is False
                and row['process_reaped'] is True and row['owned_group_gone'] is True
                and row['source_and_supervisor_unchanged'] is True
                and row['app_profiles_selected_dependencies_unchanged'] is True
                and row['source_before'] == row['source_after']
                and row['source_after']['git_head'] == self.config['COMMIT']
                and row['build_after']['version_header']['FCRepositoryHash'] == self.config['COMMIT']
                and row['build_after']['version_header']['FCRevision'] == self.config['REVISION'],
                'Fresh build/CTest receipt differs')
        for group in ('source_after', 'build_after'):
            for path, wanted in row[group]['files'].items():
                self.ref(path, wanted)
        if name == 'ctest':
            ct = row['ctest']
            require(ct['complete_catalogue_verified'] is True and ct['failed'] == 0
                    and (ct['catalogue'], ct['executed_passing'], ct['skipped'], ct['disabled']) == (2274, 2264, 2, 8),
                    'Complete CTest catalogue differs')
            for log, proof in row['ctest_logs_after'].items():
                if proof['fresh_for_this_run']:
                    self.ref(self.add(directory / log, 'text'), proof['sha256'])
                elif log == 'LastTestsFailed.log':
                    require(not (directory / log).exists(), 'Stale failure log retained as current evidence')
            return {'receipt': stamp(directory / 'execution.json'), 'counts': ct}
        return {'receipt': stamp(directory / 'execution.json'), 'elapsed_seconds': row['elapsed_seconds']}

    def physical(self):
        custody = self.read(CAPSULE / 'copy-custody.json')
        require(custody['passed'] is True and custody['all_originals_unchanged'] is True
                and custody['all_copies_exact'] is True and len(custody['files']) == 16
                and {row['path'] for row in custody['files']} == set(SELECTED)
                and custody['FCStd_FRD_or_other_large_geometry_artifacts_copied'] is False
                and custody['generic_native_input_geometry_in_Mesh_inp_copied'] is True,
                'Incomplete generic proof selection')
        require(custody['copy_helper'] == stamp(PRIVATE / 'collection/copy_installed_selection_v3.py'),
                'Selection was not produced by the exact frozen v3 helper')
        for key in ('source_run_execution', 'source_run_manifest', 'source_run_identity'):
            self.ref(custody[key]['path'], custody[key]['sha256'])
        require(custody['source_run_execution']['path'] == str(PRIVATE / 'installed-capacity/execution.json')
                and custody['source_run_manifest']['path'] == str(PRIVATE / 'installed-capacity/manifest.json')
                and custody['source_run_identity']['path'] == str(PRIVATE / 'installed-capacity/identity.json'),
                'Selection is not bound to the actual installed-capacity gate')
        original = Path(custody['source_witness_directory'])
        execution = self.read(PRIVATE / 'installed-capacity/execution.json')
        require(str(original) == execution['capacity_witness']['directory'], 'Selected witness directory rebound')
        for row in custody['files']:
            copied = CAPSULE / row['path']
            require(Path(row['source']) == original / row['path']
                    and '..' not in Path(row['path']).parts, 'Rebound selected original')
            self.ref(row['source'], row['sha256'])
            self.ref(self.add(copied, 'generic-fixture'), row['sha256'])
            require(copied.stat().st_size == row['bytes'] <= 32 * 1024 * 1024, 'Selected byte size differs')
        for row in custody['hash_only_originals_not_copied']:
            self.ref(row['path'], row['sha256'])
            require(Path(row['path']).stat().st_size == row['bytes'], 'Omitted original size differs')
        witness = self.read(CAPSULE / 'witness-receipt.json', kind='generic-fixture')
        frozen = {
            'coupled_port_capacity_fixture.json': '9142f5aa4d149aa1f0d518a592a78638f9489fb3e245af67ea4fd463e5b8ae22',
            'coupled_port_capacity_oracle.json': '42fa6289fd9e1f80efa56db27c02c06a5454ed9880f7ca61bfd80992dfb251b8',
        }
        for name, wanted in frozen.items():
            self.ref(REPOSITORY / 'src/Mod/Fem/femtest/data/calculix' / name, wanted)
        require(witness['passed'] is True and witness['physical_check_count'] == len(witness['checks']) == 3566
                and witness['frozen_oracle_sha256'] == frozen
                and len({row['name'] for row in witness['checks']}) == 3566
                and witness['actual_binary'] == str(APP / 'Contents/Resources/data/NativeSolvers/ccx-force-accounting')
                and witness['actual_binary_sha256'] == self.config['NATIVE_SHA']
                and sha(CAPSULE / 'witness-receipt.json') == execution['capacity_witness']['witness_receipt_sha256']
                and witness['force_and_original_origin_moment_limit'] == .01
                and witness['local_generalized_force_and_couple_limit'] == .01
                and witness['scalar_response_limit'] == .05
                and witness['engineering_project_accessed_or_solved'] is False
                and witness['engineering_or_BIM_accepted'] is False,
                'Actual installed132 qualification differs')
        for row in witness['checks']:
            require(row['passed'] is True and row['limit'] in (.01, .05)
                    and math.isfinite(row['relative_error']) and 0 <= row['relative_error'] <= row['limit'],
                    'Frozen installed acceptance check failed')
            require(len(row['actual']) == len(row['reference']) == 3
                    and all(math.isfinite(value) for value in row['actual'] + row['reference'])
                    and math.isfinite(row['scale']) and row['scale'] > 0,
                    'Nonfinite physical check or missing declared scale')
            norm, error = math.hypot(*row['reference']), math.dist(row['actual'], row['reference'])
            require((norm == 0 or row['scale'] == norm) and error <= row['limit'] * row['scale']
                    and math.isclose(error / row['scale'], row['relative_error'], rel_tol=1e-12, abs_tol=1e-15),
                    'Independent recorded-vector norm arithmetic differs')
        require(sum(row['limit'] == .01 for row in witness['checks']) == 3302
                and sum(row['limit'] == .05 for row in witness['checks']) == 264,
                'Frozen per-limit physical check membership differs')
        data = self.read(CAPSULE / 'native-accounting-data.json', kind='generic-fixture')
        applied = {'budget': 2113, 'counts': COUNTS, 'total': 2113}
        require(data['capacity_applied'] == applied and data['capacity']['required'] == COUNTS
                and data['capacity']['total'] == 2113 and data['capacity']['supported']['total_records'] == 2113
                and data['deck_sha256'] == sha(CAPSULE / 'native/Mesh.inp')
                and data['request_sha256'] == sha(CAPSULE / 'native/Mesh.accounting')
                and data['output_sha256'] == sha(CAPSULE / 'native/Mesh.accounting.out'),
                'Installed imported declaration provenance differs')
        stdout = self.text(CAPSULE / 'native.stdout', 'generic-fixture')
        echoes = re.findall(r'^CCX_FORCE_ACCOUNTING_CAPACITY_APPLIED_V1 (.+)$', stdout, re.M)
        require(len(echoes) == 1 and json.loads(echoes[0]) == applied, 'Installed owned-child echo differs')
        cold_manifest = self.read(CAPSULE / 'cold-case.json', kind='generic-fixture')
        require(set(cold_manifest['source_files']) == {'deck', 'request', 'native_output', 'dat', 'frd'}
                and json.loads(cold_manifest['accounting_data_literal']) == data,
                'Cold source corpus or literal native data differs')
        require(sha(witness['cold_manifest']) == witness['cold_manifest_sha256'] == sha(CAPSULE / 'cold-case.json'),
                'Selected cold manifest is not the actual installed original')
        for proof in cold_manifest['source_files'].values():
            self.ref(proof['path'], proof['sha256'])
        self.ref(cold_manifest['document'], cold_manifest['document_sha256'])
        cold = self.read(PRIVATE / 'installed-cold/cold-receipt.json')
        require(cold['passed'] is True and cold['manifest'] == witness['cold_manifest']
                and cold['manifest_sha256'] == witness['cold_manifest_sha256']
                and cold['status'].startswith('Stale') and cold['no_native_solve'] is True
                and cold['no_save'] is True and cold['no_history_or_provenance_repair'] is True
                and cold['accounting_data_sha256'] == hashlib.sha256(cold_manifest['accounting_data_literal'].encode()).hexdigest(),
                'Separate installed cold result changed literal history or source binding')
        return {'physical_checks': 3566, 'declarations': applied,
                'witness_receipt': stamp(CAPSULE / 'witness-receipt.json'),
                'cold_receipt': stamp(PRIVATE / 'installed-cold/cold-receipt.json'),
                'large_saved_model_and_FRD_are_hash_only_originals': True,
                'hash_only_originals': custody['hash_only_originals_not_copied']}

    def run(self, review_files=()):
        sealed, baseline = self.private('stage-inventory.json'), self.private('baseline-inventory.json')
        require(inventory(APP) == sealed and inventory(BACKUP) == baseline
                and not STAGE.exists() and not STAGE.is_symlink(), 'Installed/rollback transition not exact')
        require(self.private('private-baseline-app.json') == baseline, 'Baseline aliases disagree')
        profiles = self.private('profile-inventories.json')
        require(profiles == self.private('private-baseline-profiles.json') and len(profiles) == 3,
                'Protected profile scope differs')
        for path, wanted in profiles.items():
            require(inventory(path) == wanted, 'Protected user profile changed')
        critical = self.private('critical-before-DESTDIR.json')
        self.critical_files(critical)
        namespace = self.read(PRIVATE / 'namespace-plan.json')
        self.namespace_files(namespace)
        audits = {name: self.read(PRIVATE / ('independent-' + name + '-audit.json'))
                  for name in ('payload', 'stage')}
        custody = self.read(PRIVATE / 'independent-stage-custody.json')
        payload, stage = audits['payload'], audits['stage']
        native_set = {row['relative'] for row in payload['native']}
        require(payload['passed'] is stage['passed'] is custody['passed'] is True
                and payload['commit'] == stage['source_commit'] == custody['compiled_commit'] == self.config['COMMIT']
                and custody['compiled_revision'] == self.config['REVISION']
                and native_set == {row['relative'] for row in stage['native']}
                and len(native_set) == payload['payload_native_count'] == stage['native_payload_parity_count'] == custody['native_payload_count'] == 61
                and stage['selected_source_matches'] == len(SELECTED_FEM_SOURCES) + 5 == 38
                and canonical(sorted(native_set)) == payload['native_complete_relative_set_sha256']
                == stage['native_complete_relative_set_sha256'] == custody['native_complete_relative_set_sha256']
                and stage['sealed_stage_inventory_sha256'] == canonical(sealed)
                and stage['baseline_inventory_sha256'] == canonical(baseline)
                and stage['payload_audit_sha256'] == sha(PRIVATE / 'independent-payload-audit.json')
                and custody['stage_audit_sha256'] == sha(PRIVATE / 'independent-stage-audit.json')
                and custody['critical_receipt_sha256'] == sha(PRIVATE / 'critical-before-DESTDIR.json')
                and custody['baseline_and_stage_exact'] is True
                and custody['strict_signatures_quicklook_readonly_cachefree'] is True,
                'Payload/stage/custody receipts do not describe the same complete image')
        for action in STEPS:
            directory = PRIVATE / ('step-' + action)
            row = self.read(directory / 'execution.json')
            self.ref(self.add(directory / 'run.log', 'text'), row['log_sha256'])
            require(row['passed'] is True and row['action'] == action and row['returncode'] == 0
                    and row['child_reaped'] is True and row['process_group_gone'] is True
                    and row['timed_out'] is False and row['protected_profiles_and_selected_inputs_unchanged'] is True
                    and row['source_commit'] == self.config['COMMIT'] and row['compiled_revision'] == self.config['REVISION']
                    and row['installation_replacement'] == (action == 'swap'), 'Deployment step not complete')
        results = {name: self.build_gate(name) for name in ('build', 'ctest')}
        results['applications'] = {label: self.app_gate(label, module, total, sealed) for label, module, total in GATES}
        results['installed_capacity_and_cold'] = self.physical()
        self.ref(SOURCE_QA, 'dbe58b84d047dff45cab813f6aa1fc3f694a951eb840b4f55a36e995febab58b')
        source = self.read(SOURCE_QA)
        require(source['schema'] == 'FreeCAD-yzk-source-validation-v1'
                and source['implementation_commit'] == 'cf23c61504c9a25699899a87b68571b86de37438'
                and source['revision'] == '49261 +223 (Git)'
                and source['passed'] is True and source['scope']['source_only'] is True
                and source['native']['candidate_sha256'] == self.config['NATIVE_SHA']
                and source['native']['sources_sha256'] == NATIVE, 'Inherited source qualification differs')
        results['inherited_SOURCE_legacy_not_fresh_installed_runs'] = source['qualification']['legacy']
        for name, wanted in NATIVE.items():
            path = REPOSITORY / 'package/calculix/force-accounting' / name
            self.ref(self.add(path, 'source'), wanted)
            self.ref(APP / 'Contents/Resources/data/NativeSolvers/source' / name, wanted)
        self.add(REPOSITORY / 'package/calculix/force-accounting/COPYING', 'source')
        self.ref(APP / 'Contents/Resources/data/NativeSolvers/source/COPYING',
                 sha(REPOSITORY / 'package/calculix/force-accounting/COPYING'))
        self.ref(APP / 'Contents/Resources/data/NativeSolvers/ccx-force-accounting', self.config['NATIVE_SHA'])
        for relative in SELECTED_FEM_SOURCES:
            source_path = self.add(REPOSITORY / 'src/Mod/Fem' / relative, 'source')
            self.ref(APP / 'Contents/Resources/Mod/Fem' / relative, sha(source_path))
        ext_source = self.add(REPOSITORY / 'src/Ext/freecad/utils.py', 'source')
        self.ref(APP / 'Contents/Resources/Ext/freecad/utils.py', sha(ext_source))
        self.add(BUILD / 'src/Build/Version.h', 'source')
        self.ref(self.add(ORIGINAL_INSTALLER, 'source'),
                 'cca627502a56b6c9b4aefa4a970172c51e42e2dde834000decca65fd44ab46d9')
        for name in ROOT_HELPERS:
            self.add(PRIVATE / name, 'source')
        for name in COLLECTION_HELPERS:
            if name in ('audit_installation.py', 'collect_installation.py'):
                classification = 'Unexecuted initial audit/collector draft; superseded by v2'
            elif name in ('copy_installed_selection.py', 'copy_installed_selection_v2.py') or name.startswith('history/'):
                classification = 'Unexecuted prior selection proposal; superseded by v3'
            else:
                classification = 'Exact reviewed collection helper source'
            self.add(PRIVATE / 'collection' / name, 'source', classification)
        self.add(PRIVATE / 'LOCAL-INSTALL.txt', 'text')
        self.ref(APP / 'Contents/Resources/LOCAL-INSTALL.txt', sha(PRIVATE / 'LOCAL-INSTALL.txt'))
        for path in review_files:
            review = self.read(path)
            require(review['passed'] is True and review.get('outstanding_findings', []) == [], 'Outstanding code review')
        require(inventory(APP) == sealed and inventory(BACKUP) == baseline, 'App/backup changed during audit')
        for path, wanted in profiles.items():
            require(inventory(path) == wanted, 'Protected user profile changed during audit')
        self.critical_files(critical)
        self.namespace_files(namespace)
        for path, wanted in self.captured.items():
            self.ref(path, wanted)
        for row in self.publishable.values():
            root = PRIVATE if row['scope'] == 'private' else REPOSITORY
            self.ref(root / row['path'], row['sha256'])
        for path, wanted in self.expected.items():
            require(sha(path) == wanted, 'Fixed referenced original changed during audit: ' + path)
        result = {'schema': 'FreeCAD-yzk-final-installation-filesystem-audit-v1', 'passed': True,
            'source_commit': self.config['COMMIT'], 'compiled_revision': self.config['REVISION'],
            'application': str(APP), 'backup': str(BACKUP), 'native_sha256': self.config['NATIVE_SHA'],
            'sealed_application_inventory_sha256': canonical(sealed), 'baseline_backup_inventory_sha256': canonical(baseline),
            'application_inventory_entries': len(sealed), 'backup_inventory_entries': len(baseline),
            'protected_user_profile_count': len(profiles), 'selected_critical_dependency_count': 16,
            'external_namespace_file_count': 11, 'native_payload_complete_set_count': len(native_set),
            'signature_status': 'Inherited successful stage/swap strict verification plus exact unchanged sealed bytes; not a new codesign invocation',
            'historical_stage_scope': 'Original pre-swap literal-stage runs, hash-bound to the sealed currentAPP; never rerun/rebound to an absent stage path',
            'results': results, 'private_inventory_receipts_hash_only': sorted(self.hash_only.values(), key=lambda row: row['path']),
            'review_files': [str(path) for path in review_files],
            'publishable_inputs': sorted(self.publishable.values(), key=lambda row: (row['scope'], row['path'])),
            'deployment_limits': {'external_Pixi_prefix_required': str(REPOSITORY / '.pixi/envs/default'),
                'self_contained': False, 'notarized': False, 'FreeCAD_882_remains_open': True,
                'engineering_or_BIM_accepted': False, 'Oomakhi_accessed_or_solved': False,
                'R49_11_123267892_percent_remains_FAIL_against_5_percent': True,
                'R51_5_240441298_percent_remains_FAIL_against_5_percent': True,
                'force_original_origin_moment_limit': .01, 'scalar_response_limit': .05,
                'FCStd_FRD_or_other_large_geometry_artifacts_published': False,
                'generic_native_input_geometry_in_Mesh_inp_published': True}}
        privacy_check(result, 'final filesystem audit')
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review-file', type=Path, action='append', default=[])
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    require(not sys.flags.optimize, 'Use an unoptimized interpreter')
    result = Audit().run(args.review_file)
    output = PRIVATE / 'final-audit.json'
    if not args.check_only:
        with output.open('xb') as stream:
            stream.write(json_bytes(result))
    print(json_bytes({'passed': True, 'writes': 0 if args.check_only else 1,
                      'final_audit_sha256': hashlib.sha256(json_bytes(result)).hexdigest(),
                      'publishable_input_count': len(result['publishable_inputs'])}).decode(), end='')


if __name__ == '__main__':
    main()
