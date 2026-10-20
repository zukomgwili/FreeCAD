"""Host-local V3 payload staging and reversible application replacement.

No dependency files, user profiles or engineering models are modified.
All mutations are explicitly selected main actions; imports only define helpers.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import plistlib
import re
import shutil
import signal
import stat
import struct
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
BUILD = REPO / 'build/release'
APP = Path('/Applications/FreeCAD-27.1.0.app')
STAGE = ROOT / APP.name
BACKUP = Path('/Users/zukomgwili/Applications/FreeCAD Backups/FreeCAD-27.1.0-before-ywu-b6b9e216c4.app')
PREFIX = REPO / '.pixi/envs/default'
COMMIT = '6cdc1affda07ac4e3b45a98097b7ae11039c80c6'
REVISION = '49261 +221 (Git)'
NATIVE_SHA = '2d59adb06736801f730de077a5f3dbfcfba8c0a430636e5814e5582606b5c89b'
PROFILE_CANDIDATES = (
    Path('/Users/zukomgwili/Library/Application Support/FreeCAD Local'),
    Path('/Users/zukomgwili/Library/Application Support/FreeCAD'),
    Path('/Users/zukomgwili/Library/Preferences/FreeCAD'),
)
PROFILES = tuple(path for path in PROFILE_CANDIDATES if path.is_dir())
EXTENSIONS = ('FreeCADPreviewExtension.appex', 'FreeCADThumbnailExtension.appex')
NAMESPACE_FILES = {'lib/python3.13/site-packages/freecad/' + name for name in (
    'UiTools.py', '__init__.py', 'deprecation.py', 'freecad_doc.py', 'module_io.py',
    'part.py', 'partdesign.py', 'project_utility.py', 'sketcher.py', 'utils.py', 'utils_zip.py')}
SOURCES = {'src/Mod/Fem/' + path: 'Mod/Fem/' + path for path in (
    'ObjectsFem.py', 'TestFemApp.py', 'TestFemGui.py', 'femcommands/commands.py',
    'femobjects/solver_ccxtools.py', 'femobjects/result_contact_observation.py', 'femresult/contact_observation.py',
    'femresult/contact_observation_source.py', 'femresult/owned_probe.py',
    'femtools/force_accounting.py', 'femtools/ccxtools.py', 'femmesh/meshtools.py',
    'femmesh/meshsetsgetter.py', 'femmesh/ownership_context.py',
    'femsolver/calculix/write_constraint_elastic_connector.py', 'femsolver/calculix/write_constraint_tie.py', 'femsolver/calculix/write_constraint_contact.py',
    'femtest/app/test_moving_port_accounting_native.py', 'femtest/app/test_tie_accounting_native.py', 'femtest/app/test_force_accounting.py',
    'femtest/app/test_movement_provenance.py', 'femtest/app/test_tie_ownership.py',
    'femtest/gui/test_contact_observation.py')}
SOURCES.update({'package/calculix/force-accounting/' + name:
                'data/NativeSolvers/source/' + name
                for name in ('forceaccounting.c', 'hooks.patch', 'contract.json', 'COPYING')})
SOURCES['src/Ext/freecad/utils.py'] = 'Ext/freecad/utils.py'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, data):
    with path.open('x') as stream:
        stream.write(json.dumps(data, indent=2) + '\n')


def inventory(root):
    assert root.is_dir() and not root.is_symlink(), root
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
                assert stat.S_ISREG(mode), path
                row.update(kind='file', sha256=digest(path))
            result[str(path.relative_to(root))] = row
    return result


def no_live_app(_application=None):
    from process_control import assert_serial
    assert_serial(('ninja', 'make', 'gmake'))


HELPER = {'no_live_app': no_live_app}


def compiled_identity():
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO,
                                   text=True, timeout=10).strip()
    assert head == COMMIT
    subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--', 'src', 'package/calculix'],
                   cwd=REPO, check=True, timeout=10)
    values = dict(re.findall(r'^#define\s+(\w+)\s+"([^"]*)"',
                            (BUILD / 'src/Build/Version.h').read_text(), re.M))
    assert values['FCRepositoryHash'] == COMMIT and values['FCRevision'] == REVISION
    receipt = json.loads((ROOT / 'build-latest/execution.json').read_text())
    assert receipt['passed'] and receipt['source_and_supervisor_unchanged']
    for path, wanted in receipt['source_after']['files'].items():
        assert digest(Path(path)) == wanted, path
    for path, wanted in receipt['build_after']['files'].items():
        assert digest(Path(path)) == wanted, path
    assert digest(BUILD / 'data/NativeSolvers/ccx-force-accounting') == NATIVE_SHA
    return values


def verify(path):
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(path)],
                   check=True, timeout=60)


def entitlements(path):
    output = subprocess.run(['codesign', '-d', '--entitlements', ':-', str(path)],
                            check=True, capture_output=True, timeout=20)
    return plistlib.loads(output.stdout)


def macho_identity(path):
    """Allow only signature bookkeeping and install-time LC_RPATH relocation."""
    data = path.read_bytes()
    assert data[:4] == b'\xcf\xfa\xed\xfe', path
    header = struct.unpack_from('<IiiIIIII', data)
    count, command_bytes = header[4:6]
    commands, rpaths, sections = [], [], {}
    offset, signature = 32, None
    for _ in range(count):
        command, length = struct.unpack_from('<II', data, offset)
        payload = bytearray(data[offset:offset + length])
        assert length >= 8 and len(payload) == length, path
        if command == 0x8000001c:
            start = struct.unpack_from('<I', payload, 8)[0]
            rpaths.append(bytes(payload[start:]).split(b'\0', 1)[0].decode())
        elif command == 0x1d:
            signature, size = struct.unpack_from('<II', payload, 8)
            assert signature + size == len(data), path
        else:
            if command == 0x19:
                segment = bytes(payload[8:24]).rstrip(b'\0')
                if segment == b'__LINKEDIT':
                    payload[32:40] = bytes(8)
                    payload[48:56] = bytes(8)
                for number in range(struct.unpack_from('<I', payload, 64)[0]):
                    section = payload[72 + number * 80:152 + number * 80]
                    name = bytes(section[:16]).split(b'\0', 1)[0].decode()
                    segment_name = bytes(section[16:32]).split(b'\0', 1)[0].decode()
                    size = struct.unpack_from('<Q', section, 40)[0]
                    location, _, _, _, flags = struct.unpack_from('<IIIII', section, 48)
                    if location and flags & 0xff not in (1, 0xc, 0x12):
                        sections[segment_name + ',' + name] = {
                            'offset': location, 'size': size,
                            'sha256': hashlib.sha256(data[location:location + size]).hexdigest()}
            commands.append(bytes(payload))
        offset += length
    assert offset == 32 + command_bytes and sections, path
    first = min(section['offset'] for section in sections.values())
    end = signature if signature is not None else len(data)
    assert end >= first
    normalized = {
        'header_without_command_counts': [header[i] for i in (0, 1, 2, 3, 6, 7)],
        'non_rpath_signature_commands_sha256': hashlib.sha256(b''.join(commands)).hexdigest(),
        'sections': sections,
        'post_load_command_body_sha256': hashlib.sha256(data[first:end]).hexdigest()}
    return {'path': str(path), 'sha256': digest(path), 'rpaths': rpaths,
            'normalized': normalized, 'normalized_sha256': hashlib.sha256(
                json.dumps(normalized, sort_keys=True).encode()).hexdigest()}


def modes(resources, writable):
    for path in sorted(list(resources.rglob('*')) + [resources],
                       key=lambda item: len(item.parts), reverse=not writable):
        if not path.is_symlink():
            previous = stat.S_IMODE(path.stat().st_mode)
            path.chmod(previous | 0o200 if writable else previous & ~0o222)


def merge_payload(source, target):
    assert source.is_dir() and not source.is_symlink(), source
    assert not target.is_symlink(), target
    target.mkdir(exist_ok=True)
    for child in source.iterdir():
        destination = target / child.name
        if child.is_symlink():
            if destination.is_symlink():
                assert os.readlink(child) == os.readlink(destination)
            else:
                assert not destination.exists()
                destination.symlink_to(os.readlink(child))
        elif child.is_dir():
            merge_payload(child, destination)
        else:
            assert child.is_file() and not destination.is_symlink(), destination
            shutil.copy2(child, destination)


def check_namespace(plan):
    assert set(plan) == NAMESPACE_FILES
    for relative, proof in plan.items():
        path = PREFIX / relative
        assert path.is_file() and not path.is_symlink()
        parent = path.parent
        while parent != PREFIX:
            assert parent.is_dir() and not parent.is_symlink()
            parent = parent.parent
        assert proof['before'] == proof['after'] == digest(path)
        assert stat.S_IMODE(path.stat().st_mode) == proof['mode']


def source_equal(resources):
    compiled_identity()
    for source, target in SOURCES.items():
        path = resources / target
        assert path.is_file() and not path.is_symlink(), path
        assert digest(REPO / source) == digest(path), target
    native = resources / 'data/NativeSolvers/ccx-force-accounting'
    assert native.is_file() and not native.is_symlink() and digest(native) == NATIVE_SHA
    subprocess.run(['codesign', '--verify', '--strict', str(native)], check=True, timeout=20)
    assert subprocess.check_output([str(native), '--freecad-force-accounting-version'],
                                   text=True, timeout=10).strip() == 'CCX_FORCE_ACCOUNTING_V3'


def unchanged_original():
    assert inventory(APP) == json.loads((ROOT / 'baseline-inventory.json').read_text())
    for path, wanted in json.loads((ROOT / 'profile-inventories.json').read_text()).items():
        assert inventory(Path(path)) == wanted, path


def stage():
    no_live_app()
    compiled_identity()
    unchanged_original()
    verify(APP)
    assert not STAGE.exists() and not STAGE.is_symlink()
    assert json.loads((ROOT / 'independent-payload-audit.json').read_text())['passed']
    before = inventory(APP)
    for name in EXTENSIONS:
        values = entitlements(APP / 'Contents/Resources/PlugIns' / name)
        assert values and all(values.values())
        (ROOT / (name + '.plist')).write_bytes(plistlib.dumps(values))
    shutil.copytree(APP, STAGE, symlinks=True)
    assert inventory(STAGE) == before
    verify(STAGE)
    namespace = ROOT / 'payload' / PREFIX.relative_to('/')
    assert {str(path.relative_to(namespace)) for path in namespace.rglob('*')
            if path.is_file()} == NAMESPACE_FILES
    plan = {relative: {'before': digest(PREFIX / relative),
                       'after': digest(namespace / relative),
                       'mode': stat.S_IMODE((PREFIX / relative).stat().st_mode)}
            for relative in NAMESPACE_FILES}
    check_namespace(plan)
    write_json(ROOT / 'namespace-plan.json', plan)
    resources = STAGE / 'Contents/Resources'
    modes(resources, True)
    merge_payload(ROOT / 'payload' / APP.relative_to('/') / 'Contents/Resources', resources)
    canonical = resources / 'Ext/freecad'
    incoming = namespace / 'lib/python3.13/site-packages/freecad'
    for path in incoming.iterdir():
        assert (canonical / path.name).read_bytes() == path.read_bytes(), path
    merge_payload(incoming, canonical)
    source_equal(resources)
    for path in list(resources.rglob('__pycache__')) + list(resources.rglob('*.pyc')):
        if not path.exists():
            continue
        assert not path.is_symlink()
        target = ROOT / 'stage-cache' / path.relative_to(resources)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(target))
    shutil.copy2(ROOT / 'LOCAL-INSTALL.txt', resources / 'LOCAL-INSTALL.txt')
    native = resources / 'data/NativeSolvers/ccx-force-accounting'
    preserved_v3 = native.read_bytes()
    assert digest(native) == NATIVE_SHA
    subprocess.run(['codesign', '--force', '--deep', '--sign', '-', str(STAGE)],
                   check=True, timeout=120)
    # Restore the already-valid signed V3 build leaf, NOT the old installed V2.
    native.write_bytes(preserved_v3)
    assert digest(native) == NATIVE_SHA
    for name in EXTENSIONS:
        subprocess.run(['codesign', '--force', '--sign', '-', '--entitlements',
                        str(ROOT / (name + '.plist')),
                        str(resources / 'PlugIns' / name)], check=True, timeout=30)
    subprocess.run(['codesign', '--force', '--sign', '-', str(STAGE)], check=True, timeout=60)
    modes(resources, False)
    verify(STAGE)
    source_equal(resources)
    for name in EXTENSIONS:
        assert entitlements(resources / 'PlugIns' / name) == plistlib.loads(
            (ROOT / (name + '.plist')).read_bytes())
    assert not list(resources.rglob('*.pyc')) and not list(resources.rglob('__pycache__'))
    assert all(row['kind'] == 'link' or not row['mode'] & 0o222
               for row in inventory(resources).values())
    unchanged_original()
    check_namespace(plan)
    write_json(ROOT / 'stage-inventory.json', inventory(STAGE))
    print(json.dumps({'passed': True, 'stage': str(STAGE), 'revision': REVISION,
                      'native_V3_sha256': digest(native)}), flush=True)


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def check_app_receipts(location, sealed):
    """Bind fresh gates to one actual location; never rebind saved records."""
    assert location in ('stage', 'installed'), location
    application = STAGE if location == 'stage' else APP
    def read(path):
        return json.loads(Path(path).read_text())

    candidate = application / 'Contents/Resources/data/NativeSolvers/ccx-force-accounting'
    assert digest(candidate) == NATIVE_SHA
    assert inventory(application) == sealed
    audit_path = ROOT / 'independent-stage-audit.json'
    audit, payload = read(audit_path), read(ROOT / 'independent-payload-audit.json')
    custody = read(ROOT / 'independent-stage-custody.json')
    native_set = {row['relative'] for row in payload['native']}
    assert native_set and payload['payload_native_count'] == len(native_set)
    assert payload['passed'] and payload['commit'] == COMMIT
    assert payload['native_complete_relative_set_sha256'] == canonical_sha(sorted(native_set))
    assert audit['passed'] and audit['source_commit'] == COMMIT
    assert audit['payload_audit_sha256'] == digest(ROOT / 'independent-payload-audit.json')
    assert {row['relative'] for row in audit['native']} == native_set
    assert audit['native_payload_parity_count'] == len(native_set)
    assert audit['sealed_stage_inventory_sha256'] == canonical_sha(sealed)
    assert custody['passed'] and custody['compiled_commit'] == COMMIT
    assert custody['compiled_revision'] == REVISION and custody['native_payload_count'] == len(native_set)
    assert custody['stage_audit_sha256'] == digest(audit_path)
    assert custody['profiles_exact_unchanged_count'] == len(PROFILES)
    assert custody['namespace_unchanged_count'] == len(NAMESPACE_FILES)
    assert custody['critical_receipt_sha256'] == digest(ROOT / 'critical-before-DESTDIR.json')
    assert custody['baseline_and_stage_exact'] and custody['strict_signatures_quicklook_readonly_cachefree']
    assert custody['native_complete_relative_set_sha256'] == audit['native_complete_relative_set_sha256']

    tie_ids = {
        'femtest.app.test_tie_accounting_native.TestTieAccountingNative.' + name
        for name in (
            'test_mixed_native_interfaces_keep_independent_nonzero_original_displacements',
            'test_mixed_tie_contact_bodies_preserve_paired_physical_cut_equilibrium',
            'test_nonconformal_tie_uses_native_master_surface_without_an_original_query_node',
            'test_tie_edits_fail_closed_and_saved_native_observation_remains_historical',
        )}
    moving_ids = {
        'femtest.app.test_moving_port_accounting_native.TestMovingPortAccountingNative.' + name
        for name in (
            'test_moving_finite_rbe_ports_keep_elastic_transfer_separate_from_physical_support',
            'test_ordinary_fixed_and_partial_supports_preserve_aggregate_physical_equilibrium',
            'test_invalid_physical_support_selections_fail_at_stock_export_without_solving',
            'test_longitudinal_side_load_on_shared_cut_is_refused_without_current_accounting',
            'test_unselected_ordinary_boundary_cannot_overlap_a_selected_fixed_rbe',
        )}

    def app_gate(label, selected, count):
        directory = ROOT / label
        report, identity = read(directory / 'execution.json'), read(directory / 'identity.json')
        assert report['passed'] and report['application'] == str(application)
        assert report['returncode'] == 0 and not report['timed_out']
        assert report['child_reaped'] and report['process_group_gone']
        assert report['source_build_harness_unchanged'] and report['app_and_profiles_unchanged']
        assert report['application_unchanged']
        assert report['inputs_before'] == report['inputs_after']
        for path, expected in report['inputs_after'].items():
            assert digest(Path(path)) == expected, path
        assert report['skipped_lines'] == []
        assert len(report['unittest_counts']) == 1 and int(report['unittest_counts'][0][0]) == count + 1
        assert report['identity_sha256'] == digest(directory / 'identity.json')
        assert report['log_sha256'] == digest(directory / 'run.log')
        assert identity['passed'] and identity['application'] == str(application)
        assert identity['runtime'][-1] == COMMIT and identity['runtime'][3] == REVISION
        assert identity['source_or_build_import_override'] is False
        assert identity['candidate'] == {'path': str(candidate), 'sha256': NATIVE_SHA,
                                         'capability': 'CCX_FORCE_ACCOUNTING_V3', 'override': False}
        assert identity['TestFemApp_count'] == 395
        assert identity['gui_up'] == (selected == 'TestFemGui')
        if selected == 'TestFemGui':
            assert identity['TestFemGui_count'] == 8
        assert set(identity['registered_native_ids']) == tie_ids | moving_ids
        assert len(identity['registered_native_ids']) == 9
        suite = identity['selected_suite']
        assert suite['name'] == selected and suite['count'] == count
        assert len(suite['ids']) == len(set(suite['ids'])) == count
        # Raw before/after custody stays private. Its exact digests are bound by
        # the supervisor receipt, and both app inventories equal the sealed app.
        for when in ('before', 'after'):
            path = directory / f'private-custody-{when}.json'
            assert report[f'custody_{when}_sha256'] == digest(path)
            path = directory / f'private-application-{when}.json'
            assert report[f'application_inventory_{when}_sha256'] == digest(path)
            assert read(path) == sealed
        assert read(directory / 'private-custody-before.json') == read(directory / 'private-custody-after.json')
        assert report['critical_dependency_pins_unchanged']
        assert report['critical_before_DESTDIR_sha256'] == digest(ROOT / 'critical-before-DESTDIR.json')
        assert report['rebound_or_reused_stage_outputs'] is False
        text = (directory / 'run.log').read_text()
        assert re.search(r'^OK\s*$', text, re.M)
        assert not re.search(r'^(FAILED\b|FAIL:|ERROR:|UNEXPECTED SUCCESS:)', text, re.M)
        expected_ids = tie_ids | moving_ids if selected == 'TestFemApp' else (
            moving_ids if selected == 'femtest.app.test_moving_port_accounting_native' else set())
        assert expected_ids.issubset(suite['ids'])
        if selected == 'femtest.app.test_moving_port_accounting_native':
            assert set(suite['ids']) == moving_ids
        for test_id in expected_ids:
            method = test_id.rsplit('.', 1)[-1]
            # unittest may print a method docstring on the following line;
            # match its exact ID independently of the trailing progress text.
            pattern = '^' + re.escape(method) + r' \(' + re.escape(test_id) + r'\)([^\n]*)$'
            matches = re.findall(pattern, text, re.M)
            assert len(matches) == 1 and 'skipped' not in matches[0], test_id
        assert inventory(application) == sealed
        return report

    app_gate(location + '-fem', 'TestFemApp', 395)
    app_gate(location + '-gui', 'TestFemGui', 8)
    app_gate(location + '-native', 'femtest.app.test_moving_port_accounting_native', 5)
    for kind, module, checks, support_names, oracle_sha in (
        ('endload', 'YwuEndLoadGreen', 24, ['ExternalSupport'],
         'd1e436011bbd452ec39453a1c61b7466b6ec7a1bef657d7c8bc1da819114660b'),
        ('ordinary', 'YwuOrdinaryGreen', 26, ['FixedPatch', 'PartialAxialPatch'],
         'c8fa248d41273d3d829222c9f57cdcbc6cdf384f7077b34010eab94fd48a77c7'),
    ):
        app_gate(location + '-' + kind, module, 1)
        witness_dir = ROOT / (location + '-' + kind) / 'witness'
        witness = read(witness_dir / 'witness-receipt.json')
        assert witness['passed'] and witness['actual_binary'] == str(candidate)
        assert witness['actual_binary_sha256'] == NATIVE_SHA and witness['solver_returncode'] == 0
        assert witness['only_public_native_interfaces'] and witness['no_deck_patches_or_mocks']
        assert witness['Oomakhi_opened_or_solved'] is False
        assert len(witness['checks']) == checks
        assert all(row['passed'] and row['limit'] == 0.01 and math.isfinite(row['relative_error'])
                   and 0 <= row['relative_error'] <= 0.01 for row in witness['checks'])
        assert witness['current_native_report']['status'].startswith('Current')
        assert witness['current_native_report']['schema'] == 'CCX_FORCE_ACCOUNTING_V3'
        assert witness['current_native_report']['movement_status'] == 'BOUND'
        oracle = Path(witness['frozen_independent_oracle'])
        assert oracle == ROOT / (kind + '-oracle.json') and digest(oracle) == oracle_sha
        assert witness.get('frozen_independent_oracle_sha256', witness.get('oracle_sha256')) == oracle_sha
        for relative, expected in witness['retained_files'].items():
            path = witness_dir / relative
            assert not Path(relative).is_absolute() and '..' not in Path(relative).parts
            assert path.stat().st_size == expected['bytes'] and digest(path) == expected['sha256']
        manifest_path = Path(witness['cold_manifest'])
        assert manifest_path == witness_dir / 'cold-case.json'
        assert digest(manifest_path) == witness['cold_manifest_sha256']
        manifest = read(manifest_path)
        assert manifest['schema'] == 'FreeCAD-ywu-native-cold-case-v1'
        assert manifest['binary'] == str(candidate) and manifest['binary_sha256'] == NATIVE_SHA
        assert manifest['explicit_supports'] == support_names
        assert manifest['no_history_or_provenance_repair']
        saved = Path(manifest['document'])
        assert saved.parent == witness_dir and digest(saved) == manifest['document_sha256']
        assert manifest['saved_status_literal'].startswith('Current')
        assert json.loads(manifest['accounting_data_literal'])['schema'] == 'CCX_FORCE_ACCOUNTING_V3'
        for row in manifest['source_files'].values():
            path = Path(row['path'])
            assert path.is_relative_to(witness_dir) and digest(path) == row['sha256']
        app_gate(location + '-' + kind + '-cold', 'YwuColdRestore', 1)
        cold = read(ROOT / (location + '-' + kind + '-cold') / 'cold-receipt.json')
        assert cold['passed'] and cold['status'].startswith('Stale after restore')
        assert cold['manifest'] == str(manifest_path) and cold['manifest_sha256'] == digest(manifest_path)
        assert cold['supports'] == support_names
        assert cold['no_native_solve'] and cold['no_history_or_provenance_repair']
        assert cold['accounting_data_sha256'] == hashlib.sha256(manifest['accounting_data_literal'].encode()).hexdigest()

    # Legacy requests stay V2/V1: this is deliberate compatibility coverage,
    # distinct from the currently bundled executable's V3 capability.
    v2 = read(ROOT / (location + '-v2/summary.json'))
    v2_manifest = read(ROOT / (location + '-v2/manifest.json'))
    assert v2['all_selected_passed'] and v2['candidate'] == str(candidate)
    assert v2['candidate_sha256'] == NATIVE_SHA
    assert v2['manifest_sha256'] == digest(ROOT / (location + '-v2/manifest.json'))
    assert len(v2['selected_cases']) == len(set(v2['selected_cases'])) == len(v2['reports']) == 10
    assert len([row for row in v2['reports'] if row.get('expected_domain_refusal')]) == 2
    checks = [check for row in v2['reports'] for check in row.get('checks', [])]
    assert len(checks) == 144 and all(row['passed'] and row['limit'] == 0.01
                                    and math.isfinite(row['relative_error'])
                                    and 0 <= row['relative_error'] <= 0.01 for row in checks)
    assert all(row['passed'] and row['protected_inputs_unchanged'] and row['child_reaped']
               and row['process_group_gone'] and not row['timed_out'] for row in v2['reports'])
    for row in v2['reports']:
        assert row['candidate'] == str(candidate) and row['candidate_sha256'] == NATIVE_SHA
        assert row['returncode'] == (201 if row.get('expected_domain_refusal') else 0)
        directory = ROOT / (location + '-v2') / row['case']
        assert read(directory / 'execution.json') == row
        assert digest(directory / 'solver.log') == row['solver_log_sha256']
        cases = [case for case in v2_manifest['cases'] if case['name'] == row['case']]
        assert len(cases) == 1
        case = cases[0]
        assert case['directory'] == str(directory)
        assert row['custody_before'] == row['custody_after']
        custody_paths = {'candidate': candidate,
                         'script': Path(v2_manifest['script']),
                         'generator': Path(v2_manifest['generator']),
                         'process_control': Path(v2_manifest['process_control']),
                         'deck': directory / 'contact.inp', 'request': directory / 'contact.accounting'}
        assert row['custody_after'] == {name: digest(path) for name, path in custody_paths.items()}
        for name in ('deck', 'request'):
            assert case[name] == str(custody_paths[name])
            assert case[name + '_sha256'] == row['custody_after'][name]
        if not row.get('expected_domain_refusal'):
            output = directory / 'contact.accounting.out'
            assert row['native_output_sha256'] == digest(output)
            lines = output.read_text().splitlines()
            assert lines[0] == 'CCX_FORCE_ACCOUNTING_V2' and lines[-1] == 'END'
    v1 = read(ROOT / (location + '-v1/qualification.json'))
    assert v1['passed'] and v1['binary'] == str(candidate) and v1['binary_sha256'] == NATIVE_SHA
    assert v1['schema'] == 'CCX_FORCE_ACCOUNTING_V1'
    assert v1['manifest_sha256'] == digest(ROOT / (location + '-v1/manifest.json'))
    assert v1['all_children_reaped'] and v1['all_inputs_unchanged']
    assert v1['positive_cases'] == 48 and v1['expected_refusals'] == 6 and v1['physical_norm_checks'] == 288
    for path, expected in v1['protected'].items():
        assert digest(Path(path)) == expected, path
    assert len(v1['analytic_cases']) == 48 and len(v1['rejections']) == 6
    assert len({row['case'] for row in v1['analytic_cases']}) == 48
    for row in v1['analytic_cases']:
        assert len(row['relative_force_moment_errors']) == 3
        assert all(len(pair) == 2 and all(math.isfinite(error) and 0 <= error <= 0.01 for error in pair)
                   for pair in row['relative_force_moment_errors'].values())
    assert all(row['returncode'] == 201 and row['complete_accounting_envelope'] is False
               for row in v1['rejections'])
    for row in v1['analytic_cases'] + v1['rejections']:
        assert row['passed'] and row['inputs_unchanged'] and row['protected_unchanged'] and row['manifest_unchanged']
        assert row['child_reaped'] and row['process_group_gone'] and not row['timed_out']
        directory = ROOT / (location + '-v1') / row['case']
        assert read(directory / 'execution.json') == row
        assert digest(directory / 'solver.log') == row['log_sha256']
        assert row['inputs_before'] == row['inputs_after']
        assert set(row['inputs_after']) == {'contact.inp', 'contact.accounting', 'oracle.json'}
        for name, expected in row['inputs_after'].items():
            assert digest(directory / name) == expected, name
        assert row['protected_before'] == row['protected_after'] == v1['protected']
        for name, expected in row['outputs'].items():
            assert Path(name).name == name and digest(directory / name) == expected, name
        if row['positive']:
            assert row['returncode'] == 0
    assert inventory(application) == sealed


def check_stage_receipts(sealed):
    return check_app_receipts('stage', sealed)


def interrupted(signum, _frame):
    raise InterruptedError('Installation interrupted by signal ' + str(signum))


def swap():
    no_live_app()
    compiled_identity()
    unchanged_original()
    sealed = json.loads((ROOT / 'stage-inventory.json').read_text())
    assert inventory(STAGE) == sealed
    check_stage_receipts(sealed)
    for application in (APP, STAGE):
        verify(application)
    assert BACKUP.parent.is_dir() and not BACKUP.parent.is_symlink()
    assert not BACKUP.exists() and not BACKUP.is_symlink()
    assert APP.stat().st_dev == STAGE.stat().st_dev == BACKUP.parent.stat().st_dev
    source_equal(STAGE / 'Contents/Resources')
    moved_old = moved_new = False
    try:
        APP.rename(BACKUP)
        moved_old = True
        STAGE.rename(APP)
        moved_new = True
        APP.touch()
        verify(APP)
        verify(BACKUP)
        assert inventory(APP) == sealed
        assert inventory(BACKUP) == json.loads((ROOT / 'baseline-inventory.json').read_text())
        check_namespace(json.loads((ROOT / 'namespace-plan.json').read_text()))
    except BaseException as failure:
        # Repeated interrupts must not abandon either independent restoration attempt.
        watched = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
        handlers = {number: signal.getsignal(number) for number in watched}
        for number in watched:
            signal.signal(number, signal.SIG_IGN)
        errors = []
        # A signal may arrive after rename(2) succeeds but before its Python
        # completion flag is assigned. Resolve that narrow window from these
        # three previously validated, unique paths as well as the flags.
        backup_present = BACKUP.is_dir() and not BACKUP.is_symlink()
        new_at_app = backup_present and APP.is_dir() and not STAGE.exists()
        if moved_new or new_at_app:
            try:
                APP.rename(STAGE)
            except BaseException as error:
                errors.append('new app to stage: ' + repr(error))
        if moved_old or backup_present:
            try:
                BACKUP.rename(APP)
            except BaseException as error:
                errors.append('original app restoration: ' + repr(error))
        for number, handler in handlers.items():
            signal.signal(number, handler)
        if errors:
            raise RuntimeError(f'Rollback needs attention: {errors}; '
                               f'APP={APP}, BACKUP={BACKUP}, STAGE={STAGE}') from failure
        assert inventory(APP) == json.loads((ROOT / 'baseline-inventory.json').read_text())
        raise
    print(json.dumps({'installed': str(APP), 'backup': str(BACKUP)}), flush=True)


if __name__ == '__main__':
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, interrupted)
    assert len(sys.argv) == 2 and sys.argv[1] in ('stage', 'swap')
    {'stage': stage, 'swap': swap}[sys.argv[1]]()
