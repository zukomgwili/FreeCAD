"""Host-local V2 payload staging and reversible application replacement.

No dependency files, user profiles or engineering models are modified.
All mutations are explicitly selected main actions; imports only define helpers.
"""
import hashlib
import json
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
BACKUP = Path('/Users/zukomgwili/Applications/FreeCAD Backups/FreeCAD-27.1.0-before-5ar-f0c43f0a93.app')
PREFIX = REPO / '.pixi/envs/default'
COMMIT = 'b6b9e216c4ee2ca1bbc73db70076a6c99b2b1ab5'
REVISION = '49261 +218 (Git)'
NATIVE_SHA = '31fc5615d1753ccbb7b53d5a47175ac1122f18d5cb13060cec272462bb0bd03d'
PROFILES = tuple(Path('/Users/zukomgwili/Library/Application Support') / name
                 for name in ('FreeCAD Local', 'FreeCAD'))
EXTENSIONS = ('FreeCADPreviewExtension.appex', 'FreeCADThumbnailExtension.appex')
NAMESPACE_FILES = {'lib/python3.13/site-packages/freecad/' + name for name in (
    'UiTools.py', '__init__.py', 'deprecation.py', 'freecad_doc.py', 'module_io.py',
    'part.py', 'partdesign.py', 'project_utility.py', 'sketcher.py', 'utils.py', 'utils_zip.py')}
SOURCES = {'src/Mod/Fem/' + path: 'Mod/Fem/' + path for path in (
    'ObjectsFem.py', 'TestFemApp.py', 'TestFemGui.py', 'femcommands/commands.py',
    'femobjects/result_contact_observation.py', 'femresult/contact_observation.py',
    'femresult/contact_observation_source.py', 'femresult/owned_probe.py',
    'femtools/force_accounting.py', 'femtools/ccxtools.py', 'femmesh/meshtools.py',
    'femmesh/meshsetsgetter.py', 'femmesh/ownership_context.py',
    'femsolver/calculix/write_constraint_tie.py', 'femsolver/calculix/write_constraint_contact.py',
    'femtest/app/test_tie_accounting_native.py', 'femtest/app/test_force_accounting.py',
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
                                   text=True, timeout=10).strip() == 'CCX_FORCE_ACCOUNTING_V2'


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
    preserved_v2 = native.read_bytes()
    assert digest(native) == NATIVE_SHA
    subprocess.run(['codesign', '--force', '--deep', '--sign', '-', str(STAGE)],
                   check=True, timeout=120)
    # Restore the already-valid signed V2 build leaf, NOT the old installed V1.
    native.write_bytes(preserved_v2)
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
                      'native_V2_sha256': digest(native)}), flush=True)


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def check_stage_receipts(sealed):
    """Bind completed gates to this signed location; booleans alone are insufficient."""
    audit_path = ROOT / 'independent-stage-audit.json'
    audit = json.loads(audit_path.read_text())
    custody = json.loads((ROOT / 'independent-stage-custody.json').read_text())
    assert audit['passed'] and audit['source_commit'] == COMMIT
    assert audit['native_payload_parity_count'] == 61
    assert audit['sealed_stage_inventory_sha256'] == canonical_sha(sealed)
    assert custody['passed'] and custody['compiled_commit'] == COMMIT
    assert custody['compiled_revision'] == REVISION and custody['native_payload_count'] == 61
    assert custody['stage_audit_sha256'] == digest(audit_path)
    assert custody['profiles_exact_unchanged_count'] == len(PROFILES)
    assert custody['namespace_unchanged_count'] == 11
    assert custody['critical_receipt_sha256'] == digest(ROOT / 'critical-before-DESTDIR.json')
    assert custody['baseline_and_stage_exact'] and custody['strict_signatures_quicklook_readonly_cachefree']
    assert custody['native_complete_relative_set_sha256'] == audit['native_complete_relative_set_sha256']
    for label, suite_name, actual_count in (('stage-fem', 'TestFemApp', 390),
                                            ('stage-gui', 'TestFemGui', 8)):
        directory = ROOT / label
        report = json.loads((directory / 'execution.json').read_text())
        identity_path = directory / 'identity.json'
        identity = json.loads(identity_path.read_text())
        assert report['passed'] and report['application'] == str(STAGE)
        assert report['exit_code'] == 0 and not report['timed_out']
        assert report['process_reaped'] and report['owned_group_gone']
        assert report['source_and_harness_unchanged'] and report['application_unchanged']
        assert report['unittest']['count'] == actual_count + 1
        assert not report['unittest']['skipped_lines'] and report['unittest']['details'] == ''
        assert report['configured_suite_counts'] == {suite_name: actual_count}
        assert report['identity_sha256'] == digest(identity_path)
        assert report['log_sha256'] == digest(directory / 'run.log')
        assert identity['passed'] and identity['application'] == str(STAGE)
        assert identity['runtime'] == report['runtime']
        assert identity['runtime'][-1] == COMMIT and identity['runtime'][3] == REVISION
        assert identity['bundled_solver'] == {
            'path': str(STAGE / 'Contents/Resources/data/NativeSolvers/ccx-force-accounting'),
            'sha256': NATIVE_SHA, 'capability': 'CCX_FORCE_ACCOUNTING_V2',
            'preference_or_candidate_override': False}
        registered = identity['registered_native_tie_ids']
        assert len(registered) == len(set(registered)) == 4
        if suite_name == 'TestFemApp':
            assert set(registered).issubset(identity['configured_suites'][suite_name]['ids'])
            text = (directory / 'run.log').read_text()
            for test_id in registered:
                method = test_id.rsplit('.', 1)[-1]
                pattern = '^' + re.escape(method) + r' \(' + re.escape(test_id) + r'\) \.\.\.(.*)$'
                matches = re.findall(pattern, text, re.M)
                assert len(matches) == 1 and 'skipped' not in matches[0], test_id
    candidate = STAGE / 'Contents/Resources/data/NativeSolvers/ccx-force-accounting'
    v2 = json.loads((ROOT / 'stage-v2/summary.json').read_text())
    assert v2['all_selected_passed'] and v2['candidate'] == str(candidate)
    assert v2['candidate_sha256'] == digest(candidate) == NATIVE_SHA
    assert v2['manifest_sha256'] == digest(ROOT / 'stage-v2/manifest.json')
    assert len(v2['selected_cases']) == len(set(v2['selected_cases'])) == len(v2['reports']) == 10
    assert len([row for row in v2['reports'] if row.get('expected_domain_refusal')]) == 2
    checks = [check for row in v2['reports'] for check in row.get('checks', [])]
    assert len(checks) == 144 and all(row['passed'] and row['limit'] == 0.01 for row in checks)
    assert all(row['passed'] and row['protected_inputs_unchanged'] and row['child_reaped']
               and row['process_group_gone'] and not row['timed_out'] for row in v2['reports'])
    v1 = json.loads((ROOT / 'stage-v1/qualification.json').read_text())
    assert v1['passed'] and v1['binary'] == str(candidate) and v1['binary_sha256'] == NATIVE_SHA
    assert len(v1['analytic_cases']) == 48 and len(v1['rejections']) == 6
    coordinate = json.loads((ROOT / 'stage-coordinate/execution.json').read_text())
    assert coordinate['candidate'] == str(candidate) and coordinate['candidate_sha256'] == NATIVE_SHA
    assert coordinate['strict_coordinate_contract_passed'] and coordinate['returncode'] == 201
    assert coordinate['child_reaped'] and coordinate['process_group_gone']
    assert coordinate['protected_inputs_unchanged'] and not coordinate['timed_out']
    cold_dir = ROOT / 'stage-cold'
    cold = json.loads((cold_dir / 'execution.json').read_text())
    cold_identity = json.loads((cold_dir / 'identity.json').read_text())
    cold_probe = json.loads((cold_dir / 'probe.json').read_text())
    fresh_case = json.loads((ROOT / 'stage-fem/execution.json').read_text())['tie_cold_cases']
    assert len(fresh_case) == 1
    assert cold['passed'] and cold['application'] == str(STAGE)
    assert cold['exit_code'] == 0 and not cold['timed_out']
    assert cold['process_reaped'] and cold['owned_group_gone']
    assert cold['all_protected_inputs_unchanged']
    assert cold['manifest'] == fresh_case[0]['path']
    assert cold['manifest_sha256'] == fresh_case[0]['sha256'] == digest(Path(cold['manifest']))
    assert cold['unittest']['count'] == 2 and not cold['unittest']['skipped_lines']
    assert cold['identity_sha256'] == digest(cold_dir / 'identity.json')
    assert cold['probe_sha256'] == digest(cold_dir / 'probe.json')
    assert cold['log_sha256'] == digest(cold_dir / 'run.log')
    assert cold_identity['passed'] and cold_identity['application'] == str(STAGE)
    assert cold_identity['runtime'] == cold['runtime']
    assert cold['runtime'][-1] == COMMIT and cold['runtime'][3] == REVISION
    assert cold_probe == cold['probe'] and cold_probe['passed']
    assert cold_probe['application'] == str(STAGE) and cold_probe['protected_inputs_unchanged']
    assert cold_probe['historical_until_explicit_refresh']
    assert cold_probe['accounting_not_promoted_to_Current'] and cold_probe['opened_copy_unsaved']
    assert not cold_probe['writer_run'] and not cold_probe['solver_solve_run']
    assert not cold_probe['saved_document_written'] and not cold_probe['status_hash_or_fingerprint_repaired']


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
