"""Publish exact h88 deployment metadata; private CAD and inventory bodies stay private.

Root executes this only after the sealed bundle swap and installed checks. This
collector never launches FreeCAD or a solver, and never rewrites historical
stage receipts or module/solver provenance to the installed path.
"""
import datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from zoneinfo import ZoneInfo

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import critical_pins
import run_gate
import stage_install as install

DEST = install.REPO / 'package/local-completion/freecad-h88-installation-evidence'
SUMMARY = install.REPO / 'package/local-completion/freecad-h88-installation.json'
PHASES = {'build-latest': 'build', 'ctest-latest': 'ctest', **{
    'step-' + name: name for name in ('admission-self-test', 'capture', 'payload',
        'audit-payload', 'stage', 'audit-stage', 'audit-custody', 'swap')}, **{
    location + '-' + mode: mode for location in ('stage', 'installed')
    for mode in ('cmd', 'gui', 'save', 'cold')}}
CAPTURED, RELOCATIONS, PRIVATE_PINS = {}, {}, {}
CAD_SUFFIXES = {'.fcstd', '.fcstd1', '.brp', '.brep', '.step', '.stp', '.iges', '.igs'}
NATIVE_MAGIC = {b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xfe\xed\xfa\xce',
                b'\xce\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca',
                b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca', b'\x7fELF'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def inode_identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def regular_bytes(path):
    path = Path(path)
    before = path.lstat()
    assert stat.S_ISREG(before.st_mode) and not path.is_symlink(), path
    with os.fdopen(os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)), 'rb') as stream:
        assert inode_identity(os.fstat(stream.fileno())) == inode_identity(before), path
        data = stream.read()
        assert inode_identity(os.fstat(stream.fileno())) == inode_identity(before), path
    assert inode_identity(path.lstat()) == inode_identity(before), path
    return data


def capture(relative):
    relative = str(relative)
    path = ROOT / relative
    assert path.resolve(strict=True) == path and path.is_relative_to(ROOT), path
    assert path.suffix.lower() not in CAD_SUFFIXES, 'Private CAD is never published'
    assert not relative.endswith(('baseline-inventory.json', 'stage-inventory.json',
                                   'profile-inventories.json'))
    data = regular_bytes(path)
    assert data[:4] not in NATIVE_MAGIC and data[:2] != b'MZ', 'Native binary excluded'
    assert CAPTURED.get(relative, data) == data, relative
    CAPTURED[relative] = data
    return data


def pairs(rows):
    result = {}
    for key, value in rows:
        assert key not in result, 'Duplicate JSON member: ' + key
        result[key] = value
    return result


def reject_nonfinite(value):
    raise ValueError('Nonfinite JSON member: ' + value)


def parsed(relative):
    return json.loads(capture(relative), object_pairs_hook=pairs, parse_constant=reject_nonfinite)


def same_input(name, wanted, manifest=None):
    """Only a declared exact-byte staged native input can relocate after swap."""
    path = Path(name)
    assert path.is_absolute()
    if path.is_relative_to(install.STAGE):
        assert manifest is not None and manifest['expected_native_files'].get(name) == wanted, name
        relative = str(path.relative_to(install.STAGE))
        assert SEALED[relative]['kind'] == 'file' and SEALED[relative]['sha256'] == wanted
        current = install.APP / relative
        data = regular_bytes(current)
        assert sha(data) == wanted and data[:4] in NATIVE_MAGIC, current
        RELOCATIONS[name] = {'historical_path': name, 'current_exact_byte_location': str(current),
                             'sha256': wanted, 'reason': 'Exact sealed bundle rename',
                             'original_receipt_or_provenance_rewritten': False}
    else:
        assert install.digest(path) == wanted, name
    if path.suffix.lower() in CAD_SUFFIXES:
        PRIVATE_PINS[name] = {'sha256': wanted, 'bytes_published': False}


def common_phase(label, mode):
    proof = parsed(label + '/execution.json')
    log = capture(label + '/run.log')
    assert proof['mode'] == mode and proof['source_commit'] == install.COMMIT
    assert proof['passed'] is True and type(proof['returncode']) is int and proof['returncode'] == 0
    for key in ('timed_out',):
        assert proof[key] is False
    for key in ('child_reaped', 'process_group_gone'):
        assert proof[key] is True
    assert proof['log_sha256'] == sha(log)
    if label in ('build-latest', 'ctest-latest'):
        assert proof['schema'] == 'FreeCAD-8rk-isolated-native-gate-v1'
        assert proof['source_and_supervisor_unchanged'] is True
        assert proof['app_and_three_profiles_unchanged'] is True
        assert proof['source_inputs_before'] == proof['source_inputs_after']
        assert proof['protected_before'] == proof['protected_after']
        for name, wanted in proof['source_inputs_after'].items():
            same_input(name, wanted)
    elif label.startswith('step-'):
        assert proof['schema'] == 'FreeCAD-8rk-install-step-v1'
        assert proof['inputs_unchanged'] is True and proof['protected_unchanged'] is True
        assert proof['inputs_before'] == proof['inputs_after']
        for name, wanted in proof['inputs_after'].items():
            same_input(name, wanted)
        if mode == 'swap':
            assert proof['expected_sealed_install_and_exact_backup'] is True
            for path in install.PROFILES:
                assert proof['protected_before'][str(path)] == proof['protected_after'][str(path)]
            assert proof['protected_before'][str(install.APP)] == install.canonical_sha(BASELINE)
            assert proof['protected_after'][str(install.APP)] == install.canonical_sha(SEALED)
        else:
            assert proof['protected_before'] == proof['protected_after']
    else:
        assert proof['schema'] == 'FreeCAD-h88-literal-application-gate-v1'
    return proof


def sealed_claim(path, wanted, application):
    path = Path(path)
    assert path.is_relative_to(application / 'Contents/Resources'), path
    row = SEALED[str(path.relative_to(application))]
    assert row['kind'] == 'file' and row['sha256'] == wanted, path


def application_history(location, mode, proof):
    """Recheck receipts as their original location, never relabel staged tests."""
    label, count = location + '-' + mode, install.COUNTS[mode]
    manifest = parsed(label + '/manifest.json')
    regression = parsed(label + '/regression.json')
    application = install.STAGE if location == 'stage' else install.APP
    assert manifest['schema'] == 'FreeCAD-h88-literal-application-manifest-v1'
    assert regression['schema'] == 'FreeCAD-h88-installation-regression-v1'
    assert proof['location'] == manifest['location'] == regression['location'] == location
    assert proof['application'] == manifest['application'] == regression['application'] == str(application)
    assert manifest['mode'] == regression['mode'] == proof['mode'] == mode
    assert proof['revision'] == manifest['revision'] == regression['revision'] == install.REVISION
    assert manifest['commit'] == regression['commit'] == install.COMMIT
    assert proof['native_sha256'] == manifest['native_sha256'] == regression['native_sha256'] == install.NATIVE_SHA
    assert proof['expected_tests'] == proof['executed_tests'] == manifest['expected_tests'] == regression['test_count'] == count
    for key in ('application_unchanged', 'profiles_and_dependencies_unchanged', 'inputs_unchanged',
                'strict_signature_verified', 'original_app_unchanged', 'semantic_tests_passed'):
        assert proof[key] is True, (label, key)
    assert proof['source_or_build_import_override'] is False and proof['native_solver_override'] is False
    assert regression['passed'] is True and regression['source_or_build_import_override'] is False
    assert regression['only_public_native_interfaces'] is True and regression['no_mesh_or_solve'] is True
    assert regression['original_project_mutated'] is False and regression['gui'] is (mode == 'gui')
    assert proof['inputs_before'] == proof['inputs_after']
    for name, wanted in proof['inputs_after'].items():
        same_input(name, wanted, manifest)
    assert proof['application_inventory_sha256'] == install.canonical_sha(SEALED)
    assert proof['regression_sha256'] == sha(CAPTURED[label + '/regression.json'])
    assert regression['manifest_sha256'] == sha(CAPTURED[label + '/manifest.json'])
    assert regression['module_sha256'] == sha(capture('AppH88Identity.py'))
    ids = regression['selected_test_ids']
    assert len(ids) == len(set(ids)) == count
    public = sorted(ids0 for ids0 in ids if ids0.startswith('bimtests.TestArchShapeCleanup.TestArchShapeCleanup.'))
    assert public == regression['public_test_ids'] and len(public) == (7 if mode in ('cmd', 'gui') else 0)
    assert set(public) == (install.PUBLIC_IDS if mode in ('cmd', 'gui') else set())
    identity_id = 'AppH88Identity.AppH88Identity.test_exact_application_identity_and_loaded_native_origins'
    original_id = 'H88OriginalCheckpoint.H88OriginalCheckpoint.test_valid_native_base_survives_stock_structure_recompute'
    cold_id = 'H88ColdCheckpoint.H88ColdCheckpoint.test_valid_wrapper_and_material_survive_private_save_or_cold_reopen'
    assert set(ids) == ({identity_id} | install.PUBLIC_IDS if mode in ('cmd', 'gui') else
                        {identity_id, original_id, cold_id} if mode == 'save' else {identity_id, cold_id})
    text = CAPTURED[label + '/run.log'].decode(errors='replace')
    assert re.findall(r'^Ran (\d+) tests? in [0-9.]+s$', text, re.M) == [str(count)]
    assert len(re.findall(r'^OK$', text, re.M)) == 1
    assert not re.search(r'^(?:FAILED|FAIL:|ERROR:|UNEXPECTED SUCCESS)|\.\.\. skipped', text, re.M)
    assert proof['command'] == [str(application / 'Contents/MacOS' / ('FreeCAD' if mode == 'gui' else 'FreeCADCmd')),
        '-u', str(ROOT / label / 'user.cfg'), '-s', str(ROOT / label / 'system.cfg'),
        '-P', str(ROOT), '-t', 'AppH88Identity']
    for name, wanted in manifest['expected_native_files'].items():
        sealed_claim(name, wanted, application)
    sources = {target: install.digest(install.REPO / name) for name, target in install.SOURCES.items()}
    assert manifest['expected_source_files'] == sources
    for name, wanted in sources.items():
        sealed_claim(application / 'Contents/Resources' / name, wanted, application)
    identity = regression['identity']
    assert identity['runtime'][3] == install.REVISION and identity['runtime'][-1] == install.COMMIT
    assert identity['GuiUp'] is (mode == 'gui') and identity['source_or_build_import_override'] is False
    candidate = identity['candidate']
    assert candidate['override'] is False and candidate['sha256'] == install.NATIVE_SHA
    assert candidate['path'] == str(application / 'Contents/Resources/data/NativeSolvers/ccx-force-accounting')
    assert candidate['capabilities'] == {'--freecad-force-accounting-version': 'CCX_FORCE_ACCOUNTING_V3',
                                         '--freecad-contact-state-version': 'CCX_CONTACT_STATE_V1'}
    origins = [identity['process_executable'], *identity['BIM_origins'].values(),
               *identity['initial_module_origins'].values(), *regression['final_module_origins'].values()]
    origins += [row for row in identity['native_origins'].values() if 'path' in row]
    for origin in origins:
        sealed_claim(origin['path'], origin['sha256'], application)
    if mode in ('save', 'cold'):
        saved = regression['private_checkpoint']
        same_input(saved['path'], saved['sha256'])
        assert regression['original_sha256'] == manifest['original_sha256'] == '570e7ffd62c4dfb95c7b0bcbb1eafab69f11c5d54152bf9fd840ad0464402a33'
        cold = regression['cold_report']
        assert cold['path'] == str(ROOT / label / 'cold-observation.json')
        observation = parsed(label + '/cold-observation.json')
        assert sha(CAPTURED[label + '/cold-observation.json']) == cold['sha256']
        assert observation == cold['observation']
        assert observation['passed'] is True and observation['input_unchanged'] is True
        assert observation['no_mesh_or_solve'] is True and observation['original_project_mutated'] is False
        assert observation['controls_before'] == observation['controls_after']
        assert observation['wrapper_after']['valid'] is True and observation['wrapper_after']['closed'] is True
        if mode == 'save':
            assert observation['phase'] == 'save' and observation['saved_sha256'] == saved['sha256']
            original = regression['original_report']
            assert original['path'] == str(ROOT / label / 'observation.json')
            data = parsed(label + '/observation.json')
            assert original['sha256'] == sha(CAPTURED[label + '/observation.json'])
            assert data['passed'] is True and data['source_unchanged'] is True
            assert data['controls_before'] == data['controls_after']
        else:
            assert observation['phase'] == 'cold-reopen' and observation['input_sha256'] == saved['sha256']
            prior = parsed(location + '-save/regression.json')
            assert saved == prior['private_checkpoint']
            assert observation['controls_before'] == prior['cold_report']['observation']['controls_after']
    return regression


def ctest_summary():
    text = CAPTURED['ctest-latest/run.log'].decode()
    rows = re.findall(r'^\s*(\d+)/(\d+) Test\s+#(\d+):\s+(\S+)\s+\.{2,}\s*(.*)$', text, re.M)
    assert len(rows) == 2277 and {int(row[1]) for row in rows} == {2277}
    assert {int(row[0]) for row in rows} == {int(row[2]) for row in rows} == set(range(1, 2278))
    assert len({row[3] for row in rows}) == 2277
    passed = [row[3] for row in rows if row[4].startswith('Passed')]
    skipped = [row[3] for row in rows if row[4].startswith('***Skipped')]
    disabled = [row[3] for row in rows if row[4].startswith('***Not Run (Disabled)')]
    assert (len(passed), len(skipped), len(disabled)) == (2267, 2, 8)
    assert '100% tests passed out of 2269' in text
    return {'catalogue': 2277, 'passed': 2267, 'failed': 0, 'existing_skipped': skipped,
            'existing_disabled': disabled, 'excluded': [], 'genuinely_dotted_TMPDIR': True,
            'elapsed_seconds': PHASE_PROOFS['ctest-latest']['elapsed_seconds']}


def final_custody():
    run_gate.serial()
    install.compiled_identity()
    critical = critical_pins.verify()
    assert len(critical['files']) == 17 and len(install.PROFILES) == 3
    assert install.inventory(install.APP) == SEALED and install.inventory(install.BACKUP) == BASELINE
    assert not install.STAGE.exists() and not install.STAGE.is_symlink()
    profiles = install.read(ROOT / 'profile-inventories.json')
    assert set(profiles) == {str(path) for path in install.PROFILES} and len(profiles) == 3
    for name, wanted in profiles.items():
        assert install.inventory(Path(name)) == wanted, name
    namespace = install.read(ROOT / 'namespace-plan.json')
    assert len(namespace) == 11
    install.check_namespace(namespace)
    for application in (install.APP, install.BACKUP):
        install.verify(application)
        for name in install.EXTENSIONS:
            expected = install.plistlib.loads(regular_bytes(ROOT / (name + '.plist')))
            assert install.entitlements(application / 'Contents/Resources/PlugIns' / name) == expected
    resources = install.APP / 'Contents/Resources'
    assert not list(resources.rglob('*.pyc')) and not list(resources.rglob('__pycache__'))
    assert all(row['kind'] == 'link' or not row['mode'] & 0o222 for row in install.inventory(resources).values())
    return critical


def audits():
    result = {}
    for mode, name in (('payload', 'independent-payload-audit.json'),
                       ('stage', 'independent-stage-audit.json'), ('custody', 'independent-stage-custody.json')):
        result[mode] = install.admit_audit(parsed(name), mode)
    payload, stage, custody = (result[mode] for mode in ('payload', 'stage', 'custody'))
    assert stage['payload_audit_sha256'] == custody['payload_audit_sha256'] == sha(CAPTURED['independent-payload-audit.json'])
    assert custody['stage_audit_sha256'] == sha(CAPTURED['independent-stage-audit.json'])
    assert custody['profiles_inventory_receipt_sha256'] == install.digest(ROOT / 'profile-inventories.json')
    assert custody['critical_receipt_sha256'] == sha(capture('critical-before-DESTDIR.json'))
    assert stage['sealed_stage_inventory_sha256'] == install.canonical_sha(SEALED)
    assert payload['baseline_inventory_sha256'] == stage['baseline_inventory_sha256'] == install.canonical_sha(BASELINE)
    assert payload['payload_inventory_sha256'] == install.canonical_sha(install.inventory(ROOT / 'payload'))
    manifest_path = install.BUILD / 'install_manifest.txt'
    manifest_bytes = regular_bytes(manifest_path)
    manifest_proof = payload['install_manifest']
    assert manifest_proof['path'] == str(manifest_path)
    assert manifest_proof['sha256'] == sha(manifest_bytes)
    manifest_leaves = set()
    allowed_namespace = {install.PREFIX / name for name in install.NAMESPACE_FILES}
    for line in manifest_bytes.decode().splitlines():
        path = Path(line)
        assert path.is_absolute() and '..' not in path.parts, line
        assert path.is_relative_to(install.APP / 'Contents/Resources') or path in allowed_namespace, line
        manifest_leaves.add(str(path.relative_to('/')))
    payload_leaves = {name for name, row in install.inventory(ROOT / 'payload').items()
                      if row['kind'] != 'dir'}
    assert manifest_leaves == payload_leaves
    assert manifest_proof['unique_leaf_count'] == len(manifest_leaves)
    assert payload['payload_native_count'] == stage['native_payload_parity_count'] == custody['native_payload_count'] == 61
    native = {row['relative'] for row in payload['native']}
    assert len(native) == len(payload['native']) == len(stage['native']) == 61
    assert native == {row['relative'] for row in stage['native']}
    assert payload['native_complete_relative_set_sha256'] == stage['native_complete_relative_set_sha256'] == custody['native_complete_relative_set_sha256'] == install.canonical_sha(sorted(native))
    for row in stage['native']:
        sealed_claim(install.APP / 'Contents/Resources' / row['relative'], row['stage_sha256'], install.APP)
    assert stage['selected_source_matches'] == len(install.SOURCES)
    payload_root = ROOT / 'payload' / install.APP.relative_to('/') / 'Contents/Resources'
    nonnative = 0
    for relative, row in install.inventory(payload_root).items():
        parts = Path(relative).parts
        if row['kind'] == 'dir' or relative in native or '__pycache__' in parts or relative.endswith('.pyc') or '_CodeSignature' in parts:
            continue
        actual = SEALED[str(Path('Contents/Resources') / relative)]
        assert actual['kind'] == row['kind']
        assert actual['mode'] == (row['mode'] if row['kind'] == 'link' else row['mode'] & ~0o222)
        key = 'target' if row['kind'] == 'link' else 'sha256'
        assert actual[key] == row[key], relative
        nonnative += 1
    assert nonnative == stage['non_native_payload_matches']
    return result


def main():
    global SEALED, BASELINE, PHASE_PROOFS
    assert __debug__ and not sys.flags.optimize and not sys.argv[1:]
    assert not DEST.exists() and not SUMMARY.exists()
    SEALED = install.read(ROOT / 'stage-inventory.json')
    BASELINE = install.read(ROOT / 'baseline-inventory.json')
    critical = final_custody()
    PHASE_PROOFS = {label: common_phase(label, mode) for label, mode in PHASES.items()}
    assert len(PHASE_PROOFS) == 18
    for mode, count in install.COUNTS.items():
        for location in ('stage', 'installed'):
            application_history(location, mode, PHASE_PROOFS[location + '-' + mode])
        install.application_gate(install.APP, 'installed-' + mode, count)
    ctest = ctest_summary()
    audit = audits()
    admission = json.loads(CAPTURED['step-admission-self-test/run.log'])
    assert admission['schema'] == 'FreeCAD.LOCAL_INSTALL_PRODUCER_ADMISSION_SELF_TEST_V1'
    assert admission['passed'] is True and admission['helper_sha256'] == install.AUDITOR_SHA
    assert admission['accepted_count'] == len(admission['accepted']) == 3
    assert admission['rejected_count'] == len(admission['rejected']) == 64
    for path in sorted(ROOT.glob('*.py')):
        capture(path.name)
    for name in ('identity.json', 'build-identity.json', 'namespace-plan.json', 'LOCAL-INSTALL.txt'):
        capture(name)
    for name in install.EXTENSIONS:
        capture(name + '.plist')
    for path in sorted(ROOT.glob('*review*.json')):
        capture(path.name)
    capture(Path(__file__).relative_to(ROOT))
    manifest = regular_bytes(install.BUILD / 'install_manifest.txt')
    assert sha(manifest) == audit['payload']['install_manifest']['sha256']
    for relative, data in CAPTURED.items():
        assert regular_bytes(ROOT / relative) == data, relative
    final_custody()
    DEST.mkdir()
    index = {}

    def publish(name, data, original=None):
        path = DEST / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(data)
        index[name] = {'bytes': len(data), 'sha256': sha(data)}
        if original is not None:
            index[name]['uncompressed_sha256'] = sha(original)

    for relative, data in sorted(CAPTURED.items()):
        compressed = relative.endswith('run.log')
        publish(relative + '.gz' if compressed else relative,
                gzip.compress(data, mtime=0) if compressed else data, data if compressed else None)
    publish('install_manifest.txt.gz', gzip.compress(manifest, mtime=0), manifest)
    publish('historical-stage-native-input-relocations.json', (json.dumps({
        'schema': 'FreeCAD-h88-historical-stage-rename-proof-v1', 'entries': RELOCATIONS,
        'original_receipts_and_absolute_provenance_unchanged': True,
        'history_requalified_as_Current': False}, indent=2) + '\n').encode())
    publish('private-artifact-pins.json', (json.dumps({
        'schema': 'FreeCAD-h88-private-artifact-pins-v1', 'files': PRIVATE_PINS,
        'private_CAD_or_BREP_bytes_retained': False}, indent=2) + '\n').encode())
    install.write_json(DEST / 'index.json', {
        'schema': 'FreeCAD-h88-installation-evidence-index-v1', 'source_commit': install.COMMIT,
        'files': index, 'raw_app_or_profile_inventory_bodies_retained': False,
        'native_executables_retained': False, 'private_CAD_or_BREP_bytes_retained': False})
    final_custody()
    london = ZoneInfo('Europe/London')
    installed_time = datetime.datetime.fromtimestamp(install.APP.stat().st_mtime, london)
    summary = {
        'schema': 'FreeCAD-h88-installation-validation-v1', 'passed': True,
        'date': datetime.datetime.now(london).date().isoformat(), 'timezone': 'Europe/London',
        'deployment_bead': 'FreeCAD-m9x', 'fix_bead': 'FreeCAD-h88',
        'application': str(install.APP), 'rollback_backup': str(install.BACKUP),
        'source_commit': install.COMMIT, 'revision': install.REVISION,
        'native_sha256': install.NATIVE_SHA, 'modified_local_time': installed_time.isoformat(),
        'build': {'full_incremental_Release': True, 'clean_from_scratch_claimed': False,
                  'nonfatal_Pivy_stub_warning_tracked_separately': 'FreeCAD-szc'},
        'ctest': ctest, 'admission_self_test': {'valid_accepted': 3, 'invalid_rejected': 64},
        'application_tests': {'stage': dict(install.COUNTS), 'installed': dict(install.COUNTS),
            'stage_total': sum(install.COUNTS.values()), 'installed_total': sum(install.COUNTS.values()),
            'total_executed': 2 * sum(install.COUNTS.values()),
            'identity_checks_included_in_counts': True,
            'separate_process_cold_restore_per_location': True,
            'private_original_checkpoint_and_material_preservation_verified': True},
        'payload': {'complete_native_images': audit['payload']['payload_native_count'],
            'non_native_payload_matches': audit['stage']['non_native_payload_matches'],
            'selected_source_matches': audit['stage']['selected_source_matches'],
            'full_DESTDIR_manifest_leaf_set_verified': True,
            'stage_and_installed_exact_sealed_inventory_sha256': install.canonical_sha(SEALED),
            'old_backup_exact_inventory_sha256': install.canonical_sha(BASELINE),
            'strict_signatures_and_QuickLook_entitlements_verified': True,
            'resources_readonly_and_cachefree': True},
        'preservation': {'profiles_unchanged': 3, 'external_namespace_files_unchanged': 11,
            'selected_critical_dependency_files_unchanged': len(critical['files']),
            'whole_dependency_environment_inventory_claimed': False},
        'phases': {'qualifying_passed': len(PHASES)},
        'privacy': {'private_CAD_or_BREP_bytes_retained': False,
                    'original_absolute_provenance_preserved': True,
                    'stage_histories_rebound_or_relabelled_Current': False},
        'runtime_dependency': str(install.PREFIX), 'self_contained': False, 'notarized': False,
        'scope': 'Current fork software deployment only; private checkpoint copies recomputed/saved/reopened. No original project mutation, remeshing, solving or engineering acceptance.',
        'evidence': {'directory': str(DEST.relative_to(install.REPO)), 'files': len(index),
            'index_sha256': install.digest(DEST / 'index.json'), 'private_directory': str(ROOT)},
        'final_independent_audit': 'Published separately after collection; not claimed by collector.',
        'metadata_note': 'Later evidence/tracking commits do not change the exact compiled 1e3/+238 identity.'}
    install.write_json(SUMMARY, summary)
    print(json.dumps({'passed': True, 'application': str(install.APP), 'revision': install.REVISION,
        'evidence_files': len(index), 'total_deployment_tests': 2 * sum(install.COUNTS.values()),
        'summary': str(SUMMARY)}, indent=2))


if __name__ == '__main__':
    main()
