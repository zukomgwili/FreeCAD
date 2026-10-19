"""Stage, sign and reversibly install the pinned FreeCAD 927 build.

Private, host-local installer. All dependency links are preserved literally.
The external namespace is verified unchanged; no prefix file/cache is written.
"""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import runpy
import shutil
import stat
import subprocess
import sys
from harness_config import (COMMIT, REVISION, OLD_COMMIT, OLD_REVISION,
                            OLD_NATIVE_SHA256, NATIVE_CODE_ID,
                            ORDINARY_CCX_SHA256)

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
APP = Path('/Applications/FreeCAD-27.1.0.app')
STAGE = ROOT / APP.name
BACKUP = Path('/Users/zukomgwili/Applications/FreeCAD Backups/'
              'FreeCAD-27.1.0-before-927-5591e8e388.app')
PREFIX = REPO / '.pixi/envs/default'
OLD_MESH = '099344a469be5990bf0240169e6235c1c4be5ee63c909e3a80c50d05fb81768c'
EXIT_DRIVER = REPO / 'tests/src/App/TestRunnerExitStatus.py'
EXIT_FIXTURE = REPO / 'tests/src/App/TestRunnerExitStatusFixture.py'
PROFILES = (Path('/Users/zukomgwili/Library/Application Support/FreeCAD Local'),
            Path('/Users/zukomgwili/Library/Application Support/FreeCAD'))
HELPER = runpy.run_path(str(REPO / 'package/qt-cocoa/install_overlay.py'))
EXTENSIONS = ('FreeCADPreviewExtension.appex', 'FreeCADThumbnailExtension.appex')
KEYS = {'com.apple.security.app-sandbox',
        'com.apple.security.files.bookmarks.app-scope',
        'com.apple.security.files.downloads.read-only',
        'com.apple.security.files.user-selected.read-only'}
GATES = ('create', 'reopen', 'cli', 'features', 'gui', 'equilibrium',
         'mixed-create', 'mixed-reopen', 'area-create', 'area-reopen')
NAMESPACE_FILES = {
    'lib/python3.13/site-packages/freecad/' + name
    for name in ('UiTools.py', '__init__.py', 'deprecation.py', 'freecad_doc.py',
                 'module_io.py', 'part.py', 'partdesign.py', 'project_utility.py',
                 'sketcher.py', 'utils.py', 'utils_zip.py')}
SOURCES = {
    'src/Mod/Fem/femtools/native_properties.py': 'Mod/Fem/femtools/native_properties.py',
    'src/Mod/Fem/femmesh/quality.py': 'Mod/Fem/femmesh/quality.py',
    'src/Mod/Fem/femtools/force_accounting.py': 'Mod/Fem/femtools/force_accounting.py',
    'src/Mod/Fem/femtools/ccxtools.py': 'Mod/Fem/femtools/ccxtools.py',
    'src/Mod/Fem/femobjects/solver_ccxtools.py': 'Mod/Fem/femobjects/solver_ccxtools.py',
    'src/Mod/Fem/femobjects/constraint_sectionprint.py': 'Mod/Fem/femobjects/constraint_sectionprint.py',
    'src/Mod/Fem/femtest/app/test_force_accounting.py': 'Mod/Fem/femtest/app/test_force_accounting.py',
    'package/calculix/force-accounting/forceaccounting.c': 'data/NativeSolvers/source/forceaccounting.c',
    'package/calculix/force-accounting/hooks.patch': 'data/NativeSolvers/source/hooks.patch',
    'package/calculix/force-accounting/contract.json': 'data/NativeSolvers/source/contract.json',
    'src/Mod/Fem/femmesh/meshtools.py': 'Mod/Fem/femmesh/meshtools.py',
    'src/Mod/Fem/femmesh/meshsetsgetter.py': 'Mod/Fem/femmesh/meshsetsgetter.py',
    'src/Mod/Fem/femmesh/ownership_context.py': 'Mod/Fem/femmesh/ownership_context.py',
    'src/Mod/Fem/TestFemApp.py': 'Mod/Fem/TestFemApp.py',
    'src/Mod/Fem/femtest/app/test_contact_ownership.py':
        'Mod/Fem/femtest/app/test_contact_ownership.py',
    'src/Mod/Fem/femtest/app/test_material_groups.py':
        'Mod/Fem/femtest/app/test_material_groups.py',
    'src/Mod/Draft/draftfunctions/svgshapes.py': 'Mod/Draft/draftfunctions/svgshapes.py',
    'src/Mod/Draft/drafttests/test_svg.py': 'Mod/Draft/drafttests/test_svg.py',
    'src/Mod/Spreadsheet/TestSpreadsheet.py': 'Mod/Spreadsheet/TestSpreadsheet.py',
    'src/Mod/TechDraw/TestTechDrawApp.py': 'Mod/TechDraw/TestTechDrawApp.py',
    'src/Ext/freecad/utils.py': 'Ext/freecad/utils.py',
}
SOURCES.update({
    'src/Mod/Fem/' + relative: 'Mod/Fem/' + relative
    for relative in [
        "ObjectsFem.py",
        "TestFemApp.py",
        "TestFemGui.py",
        "femcommands/commands.py",
        "femobjects/result_contact_observation.py",
        "femresult/contact_observation.py",
        "femresult/contact_observation_source.py",
        "femresult/owned_probe.py",
        "femtools/force_accounting.py",
        "femtools/ccxtools.py",
        "femviewprovider/view_contact_observation.py",
        "femtest/app/test_contact_observation.py",
        "femtest/app/test_contact_observation_native.py",
        "femtest/app/test_contact_observation_source.py",
        "femtest/app/test_mesh_vtk_identity.py",
        "femtest/app/test_movement_provenance.py",
        "femtest/app/test_object.py",
        "femtest/app/test_owned_probe.py",
        "femtest/gui/test_contact_observation.py"
    ]
})


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(root):
    result = {'.': {'kind': 'dir', 'mode': stat.S_IMODE(root.lstat().st_mode)}}
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in sorted(dirs + files):
            path = Path(directory) / name
            mode = path.lstat().st_mode
            record = {'mode': stat.S_IMODE(mode)}
            if stat.S_ISLNK(mode):
                record.update(kind='link', target=os.readlink(path))
            elif stat.S_ISDIR(mode):
                record.update(kind='dir')
            else:
                assert stat.S_ISREG(mode), path
                record.update(kind='file', sha256=digest(path))
            result[str(path.relative_to(root))] = record
    return result


def compiled_identity():
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO,
                                   text=True).strip() == COMMIT
    subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--', 'src'], cwd=REPO, check=True)
    header = (REPO / 'build/release/src/Build/Version.h').read_text()
    values = dict(re.findall(r'^#define\s+(\w+)\s+"([^"]*)"', header, re.MULTILINE))
    assert values['FCRepositoryHash'] == COMMIT
    assert re.fullmatch(r'\d+ \+\d+ \(Git\)', values['FCRevision'])
    assert values['FCRevision'] == REVISION
    version = (values['FCVersionMajor'] + '.' + values['FCVersionMinor'] + '.'
               + values['FCVersionPoint'] + values['FCVersionSuffix']
               + values['FCRevision'].replace(' +', '+'))
    closure = json.loads((ROOT / 'compiled-inputs.json').read_text())
    assert closure['compiled_commit'] == COMMIT and closure['compiled_revision'] == REVISION
    for relative, required in closure['files'].items():
        assert digest(REPO / relative) == required, relative
    return values['FCRevision'], version


def verify(path):
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(path)], check=True)


def entitlements(path):
    result = subprocess.run(['codesign', '-d', '--entitlements', ':-', str(path)],
                            capture_output=True, check=True)
    values = plistlib.loads(result.stdout)
    assert set(values) == KEYS and all(values.values()), (path, values)
    return values


def modes(resources, writable):
    # pathlib.rglob does not recurse directory symlinks; do not chmod links.
    paths = list(resources.rglob('*')) + [resources]
    for path in sorted(paths, key=lambda p: len(p.parts), reverse=not writable):
        if not path.is_symlink():
            previous = stat.S_IMODE(path.stat().st_mode)
            path.chmod(previous | 0o200 if writable else previous & ~0o222)


def source_equal(resources):
    compiled_identity()
    for source, target in SOURCES.items():
        actual = resources / target
        assert not actual.is_symlink() and actual.is_file(), target
        assert (REPO / source).read_bytes() == actual.read_bytes(), target
    native = resources / 'data/NativeSolvers/ccx-force-accounting'
    assert native.is_file() and not native.is_symlink()
    assert native_code_id(native) == NATIVE_CODE_ID
    material_native_parity(resources)
    fem_native_parity(resources)
    assert digest(PREFIX / 'bin/ccx') == ORDINARY_CCX_SHA256
    assert subprocess.check_output([str(native), '--freecad-force-accounting-version'], text=True).strip() == 'CCX_FORCE_ACCOUNTING_V1'


def native_code_id(path):
    # Exclude only code-signature data and the two size fields it changes.
    # All instructions, constants, imports and remaining load commands must match.
    import struct
    data = bytearray(path.read_bytes())
    assert struct.unpack_from('<I', data)[0] == 0xfeedfacf
    count = struct.unpack_from('<I', data, 16)[0]
    offset, signature = 32, None
    for _ in range(count):
        command, size = struct.unpack_from('<II', data, offset)
        if command == 0x1d:
            signature, length = struct.unpack_from('<II', data, offset + 8)
            data[offset + 8:offset + 16] = bytes(8)
        if command == 0x19 and data[offset+8:offset+24].rstrip(b'\0') == b'__LINKEDIT':
            data[offset+32:offset+40] = bytes(8)
            data[offset+48:offset+56] = bytes(8)
        offset += size
    assert signature is not None
    return hashlib.sha256(data[:signature]).hexdigest()



def macho_identity(path):
    """Ignore only signature bookkeeping and install-time RPATH relocation.

    Keep all other load commands, code/data sections and the complete native
    body before the signature. This is software payload custody, not a claim
    that independently rerunning codesign produces identical file bytes.
    """
    import struct
    data = path.read_bytes()
    assert data[:4] == b'\xcf\xfa\xed\xfe', path
    header = struct.unpack_from('<IiiIIIII', data)
    _, _, _, _, count, command_bytes, _, _ = header
    commands, rpaths, sections = [], [], {}
    offset, signature = 32, None
    for _ in range(count):
        command, length = struct.unpack_from('<II', data, offset)
        payload = bytearray(data[offset:offset + length])
        assert length >= 8 and len(payload) == length, path
        if command == 0x8000001c:  # LC_RPATH: legitimate install relocation
            start = struct.unpack_from('<I', payload, 8)[0]
            rpaths.append(bytes(payload[start:]).split(b'\0', 1)[0].decode())
        elif command == 0x1d:  # LC_CODE_SIGNATURE
            signature, signature_length = struct.unpack_from('<II', payload, 8)
            assert signature + signature_length == len(data), path
        else:
            if command == 0x19:
                segment = bytes(payload[8:24]).rstrip(b'\0')
                if segment == b'__LINKEDIT':
                    # The signature changes only its trailing segment sizes.
                    payload[32:40] = bytes(8)
                    payload[48:56] = bytes(8)
                nsects = struct.unpack_from('<I', payload, 64)[0]
                for number in range(nsects):
                    start = 72 + number * 80
                    section = payload[start:start + 80]
                    name = bytes(section[:16]).split(b'\0', 1)[0].decode()
                    segment_name = bytes(section[16:32]).split(b'\0', 1)[0].decode()
                    size = struct.unpack_from('<Q', section, 40)[0]
                    location, _, _, _, section_flags = struct.unpack_from('<IIIII', section, 48)
                    if location and section_flags & 0xff not in (1, 0xc, 0x12):
                        sections[segment_name + ',' + name] = {
                            'offset': location, 'size': size,
                            'sha256': hashlib.sha256(data[location:location + size]).hexdigest()}
            commands.append(bytes(payload))
        offset += length
    assert offset == 32 + command_bytes and sections, path
    first = min(section['offset'] for section in sections.values())
    end = signature if signature is not None else len(data)
    assert end >= first, path
    normalized = {
        'header_without_command_counts': [header[i] for i in (0, 1, 2, 3, 6, 7)],
        'non_rpath_signature_commands_sha256': hashlib.sha256(b''.join(commands)).hexdigest(),
        'sections': sections,
        'post_load_command_body_sha256': hashlib.sha256(data[first:end]).hexdigest(),
    }
    return {'path': str(path), 'sha256': digest(path), 'rpaths': rpaths,
            'normalized': normalized,
            'normalized_sha256': hashlib.sha256(
                json.dumps(normalized, sort_keys=True).encode()).hexdigest()}


def material_native_parity(resources):
    """Bind both staged C++ material modules to the final build and payload."""
    payload = ROOT / 'payload' / APP.relative_to('/') / 'Contents/Resources'
    proof = {}
    for name in ('Materials.so', 'MatGui.so'):
        paths = {
            'build': REPO / 'build/release/Mod/Material' / name,
            'payload': payload / 'lib' / name,
            'application': resources / 'lib' / name,
        }
        for path in paths.values():
            assert path.is_file() and not path.is_symlink(), path
        records = {key: macho_identity(path) for key, path in paths.items()}
        assert records['build']['normalized'] == records['payload']['normalized'], name
        assert records['payload']['normalized'] == records['application']['normalized'], name
        assert records['payload']['rpaths'] == records['application']['rpaths'], name
        proof[name] = records
    return {'passed': True, 'compiled_commit': COMMIT, 'compiled_revision': REVISION,
            'resources': str(resources), 'modules': proof,
            'normalization_limits': [
                'Build-to-payload comparison ignores only LC_RPATH relocation and signature bookkeeping.',
                'Payload-to-application comparison also requires exact RPATH lists.',
                'All other load commands and native code/data body remain exact.']}


def fem_native_parity(resources):
    """Bind both staged C++ FEM modules to the final build and payload."""
    payload = ROOT / 'payload' / APP.relative_to('/') / 'Contents/Resources'
    proof = {}
    for name in ('Fem.so', 'FemGui.so'):
        paths = {
            'build': REPO / 'build/release/Mod/Fem' / name,
            'payload': payload / 'lib' / name,
            'application': resources / 'lib' / name,
        }
        for path in paths.values():
            assert path.is_file() and not path.is_symlink(), path
        records = {key: macho_identity(path) for key, path in paths.items()}
        assert records['build']['normalized'] == records['payload']['normalized'], name
        assert records['payload']['normalized'] == records['application']['normalized'], name
        assert records['payload']['rpaths'] == records['application']['rpaths'], name
        proof[name] = records
    return {'passed': True, 'compiled_commit': COMMIT, 'compiled_revision': REVISION,
            'resources': str(resources), 'modules': proof,
            'normalization_limits': [
                'Build-to-payload comparison ignores only LC_RPATH relocation and signature bookkeeping.',
                'Payload-to-application comparison also requires exact RPATH lists.',
                'All other load commands and native code/data body remain exact.']}


def check_3sc(label, application):
    """Require actual typed GUI/card/cold proof before application replacement."""
    assert label in ('stage', 'installed')
    gui = ROOT / 'typed' / f'{label}-3sc-gui'
    cold = ROOT / 'typed' / f'{label}-3sc-cold'
    reports = {}
    for name, directory, native_name in (
        ('gui', gui, 'green-witness.json'),
        ('cold', cold, 'cold-restore-report.json'),
    ):
        execution = json.loads((directory / 'execution.json').read_text())
        native_path = directory / native_name
        native = json.loads(native_path.read_text())
        assert execution['verdict'] == native['verdict'] == 'PASS'
        assert execution['exit_code'] == 0 and execution['process_reaped']
        assert not execution['timed_out']
        assert execution['native_witness_sha256'] == digest(native_path)
        assert native['runtime'][-1] == COMMIT and native['runtime'][3] == REVISION
        module = native['Materials_module']
        expected_module = application / 'Contents/Resources/lib/Materials.so'
        assert Path(module['path']).resolve() == expected_module.resolve()
        assert module['sha256'] == digest(expected_module)
        images = native.get('loaded_material_images_after_bridge_gui',
                            native.get('loaded_material_images'))
        assert [Path(row['path']).resolve() for row in images
                if Path(row['path']).name == 'Materials.so'] == [expected_module.resolve()]
        for row in images:
            assert row['sha256'] == digest(Path(row['path']))
        assert execution['protected_sha256_before'] == execution['protected_sha256_after']
        assert execution['supervisor_sha256_before'] == execution['supervisor_sha256_after']
        reports[name] = {'execution': execution, 'native': native}
    native = reports['gui']['native']
    persistence = native['persistence']
    assert persistence['verdict'] == 'PASS'
    assert persistence['public_manager_save_refresh_exact']
    assert persistence['same_process_fcstd_uuid_library_restore_exact']
    assert persistence['same_process_fem_hashes_exact']
    assert persistence['producer_sha256_before'] == persistence['producer_sha256_after']
    assert native['readonly_copies'] >= 64 and native['fem_hash_read_repeatability']
    assert len(native['mutations']) == 2
    previous = native['initial_fem_hashes']
    for change in native['mutations']:
        current = change['hashes']
        for key in ('model_digest', 'quality_input_fingerprint'):
            assert current[key] != previous[key]
        previous = current
    scope = persistence['actual_scope']
    assert Path(scope['output']).resolve() == gui.resolve()
    for key in ('user_library', 'user_app_data_dir'):
        actual = Path(scope[key]).resolve()
        assert actual != gui.resolve() and actual.is_relative_to(gui.resolve())
    expected = gui / 'cold-restore-expected.json'
    assert reports['cold']['native']['expected_receipt_sha256'] == digest(expected)
    assert set(reports['cold']['native']['cases']) == {'gui_material', 'public_api_null_material'}
    assert all(row['exact_material_identity'] for row in reports['cold']['native']['cases'].values())
    return {'passed': True, 'application': str(application), 'label': label,
            'gui_report': str(gui / 'execution.json'),
            'cold_report': str(cold / 'execution.json')}


def merge_payload(source, target):
    # Reject writes through a baseline dependency link, including at recursion.
    assert source.is_dir() and not source.is_symlink(), source
    assert not target.is_symlink(), target
    target.mkdir(exist_ok=True)
    for child in source.iterdir():
        destination = target / child.name
        if child.is_symlink():
            if destination.is_symlink():
                assert os.readlink(child) == os.readlink(destination), child
            else:
                assert not destination.exists(), destination
                destination.symlink_to(os.readlink(child))
        elif child.is_dir():
            merge_payload(child, destination)
        else:
            assert child.is_file() and not destination.is_symlink(), destination
            shutil.copy2(child, destination)


def check_namespace(plan):
    assert set(plan) == NAMESPACE_FILES
    assert PREFIX.is_dir() and not PREFIX.is_symlink(), PREFIX
    for relative, proof in plan.items():
        assert proof['before'] == proof['after'], relative
        target = PREFIX / relative
        assert target.is_file() and not target.is_symlink(), target
        parent = target.parent
        while parent != PREFIX:
            assert parent.is_dir() and not parent.is_symlink(), parent
            parent = parent.parent
        assert stat.S_IMODE(target.stat().st_mode) == proof['mode'], target
        assert digest(target) == proof['before'], relative


def check_exit_status(label, application):
    report_path = ROOT / f'{label}-exit-status/summary.json'
    report = json.loads(report_path.read_text())
    assert report['passed'] and report['expected_commit'] == COMMIT
    assert report['expected_revision'] == REVISION
    assert report['application'] == str(application)
    for name, path in (('driver', EXIT_DRIVER), ('fixture', EXIT_FIXTURE)):
        assert report[f'{name}_sha256_before'] == report[f'{name}_sha256_after'] == digest(path)
    assert len(report['gates']) == 2
    assert {gate['mode'] for gate in report['gates']} == {'gui', 'cmd'}
    for gate in report['gates']:
        assert gate['passed'] and gate['exit_code'] == 0 and gate['tests_run'] == 15
        assert gate['skipped'] == (4 if gate['mode'] == 'cmd' else 0)
        assert gate['timeout_seconds'] == 510
        assert not gate['timed_out'] and gate['process_reaped']
    return report_path


def sign(path):
    assert path == STAGE and path.is_dir() and not path.is_symlink()
    resources = path / 'Contents/Resources'
    native = resources / 'data/NativeSolvers/ccx-force-accounting'
    # This 927/FEM fix must retain the unchanged qualified signed solver literally.
    # Do not assume that repeating codesign reproduces its exact file bytes.
    baseline_native = APP / 'Contents/Resources/data/NativeSolvers/ccx-force-accounting'
    assert native.is_file() and not native.is_symlink()
    assert baseline_native.is_file() and not baseline_native.is_symlink()
    assert not os.path.samefile(native, baseline_native)
    preserved_native = baseline_native.read_bytes()
    assert hashlib.sha256(preserved_native).hexdigest() == OLD_NATIVE_SHA256
    assert native_code_id(native) == native_code_id(baseline_native) == NATIVE_CODE_ID
    modes(resources, True)
    subprocess.run(['codesign', '--force', '--deep', '--sign', '-', str(path)], check=True)
    # Restore only this verified code-identical already-signed native leaf,
    # before the final outer bundle seal. Baseline APP is read-only here.
    native.write_bytes(preserved_native)
    assert digest(native) == OLD_NATIVE_SHA256
    for name in EXTENSIONS:
        extension = resources / 'PlugIns' / name
        subprocess.run(['codesign', '--force', '--sign', '-', '--entitlements',
                        str(ROOT / (name + '.plist')), str(extension)], check=True)
    subprocess.run(['codesign', '--force', '--sign', '-', str(path)], check=True)
    assert digest(native) == OLD_NATIVE_SHA256
    modes(resources, False)
    verify(path)
    for name in EXTENSIONS:
        assert entitlements(resources / 'PlugIns' / name) == plistlib.loads(
            (ROOT / (name + '.plist')).read_bytes())
    assert not list(resources.rglob('*.pyc'))
    assert not list(resources.rglob('__pycache__'))
    for proof in inventory(resources).values():
        assert proof['kind'] == 'link' or not proof['mode'] & 0o222
    source_equal(resources)


def stage():
    assert not STAGE.exists() and not STAGE.is_symlink()
    revision, version = compiled_identity()
    HELPER['no_live_app'](APP)
    verify(APP)
    old_install = (APP / 'Contents/Resources/LOCAL-INSTALL.txt').read_text()
    assert OLD_COMMIT in old_install
    assert OLD_REVISION.replace(' +', '+') in old_install
    assert digest(APP / 'Contents/Resources/data/NativeSolvers/ccx-force-accounting') == OLD_NATIVE_SHA256
    assert digest(PREFIX / 'bin/ccx') == ORDINARY_CCX_SHA256
    profiles = {}
    for profile in PROFILES:
        assert profile.is_dir() and not profile.is_symlink()
        profiles[str(profile)] = inventory(profile)
    (ROOT / 'profile-inventories.json').write_text(json.dumps(profiles, indent=2) + '\n')
    assert digest(APP / 'Contents/Resources/Mod/Fem/femmesh/meshtools.py') == OLD_MESH
    before = inventory(APP)
    (ROOT / 'baseline-inventory.json').write_text(json.dumps(before, indent=2) + '\n')
    for name in EXTENSIONS:
        values = entitlements(APP / 'Contents/Resources/PlugIns' / name)
        (ROOT / (name + '.plist')).write_bytes(plistlib.dumps(values))
    shutil.copytree(APP, STAGE, symlinks=True)
    assert inventory(STAGE) == before, 'Baseline copy differs'
    verify(STAGE)
    namespace = ROOT / 'payload' / PREFIX.relative_to('/')
    assert namespace.is_dir() and not namespace.is_symlink()
    files = sorted(p for p in namespace.rglob('*') if p.is_file())
    assert {str(p.relative_to(namespace)) for p in files} == NAMESPACE_FILES
    plan = {}
    for path in files:
        assert not path.is_symlink(), path
        parent = path.parent
        while parent != namespace:
            assert parent.is_dir() and not parent.is_symlink(), parent
            parent = parent.parent
        relative = path.relative_to(namespace)
        live = PREFIX / relative
        plan[str(relative)] = {'before': digest(live), 'after': digest(path),
                               'mode': stat.S_IMODE(live.stat().st_mode)}
    check_namespace(plan)
    (ROOT / 'namespace-plan.json').write_text(json.dumps(plan, indent=2) + '\n')
    payload = ROOT / 'payload' / APP.relative_to('/') / 'Contents/Resources'
    assert payload.is_dir() and not payload.is_symlink()
    resources = STAGE / 'Contents/Resources'
    modes(resources, True)
    merge_payload(payload, resources)
    # Retain normal app-local namespace precedence and its existing gui subtree.
    namespace_package = namespace / 'lib/python3.13/site-packages/freecad'
    canonical = resources / 'Ext/freecad'
    assert canonical.is_dir() and not canonical.is_symlink()
    for incoming in namespace_package.iterdir():
        destination = canonical / incoming.name
        assert destination.is_file() and not destination.is_symlink(), destination
        assert destination.read_bytes() == incoming.read_bytes(), destination
    merge_payload(namespace_package, canonical)
    source_equal(resources)
    cache = ROOT / 'staged-cache'
    for path in list(resources.rglob('__pycache__')):
        assert not path.is_symlink(), path
        target = cache / path.relative_to(resources)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(target))
    for path in list(resources.rglob('*.pyc')):
        assert not path.is_symlink(), path
        target = cache / path.relative_to(resources)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(target))
    (resources / 'LOCAL-INSTALL.txt').write_text(
        f'FreeCAD Local Release built from {COMMIT}.\n'
        f'19 October 2026, version {version}.\n'
        'Includes FreeCAD-927 and FreeCAD-89o: saved editable contact-side\n'
        'observations, strict source-run bindings, exact native mesh IDs and\n'
        'bounded owner-side native VTK sampling; no gap/slip acceptance computed.\n'
        'PointSide selects an existing Slave or Master vertex while original\n'
        'slave/master owners and the slave reference frame remain unchanged.\n'
        'Historical observations are not current results; refresh is explicit.\n'
        'Moving the app changes the exact solver-path binding. Staged saved\n'
        'results remain historical; installed checks create fresh native runs.\n'
        'No staged AccountingData or ObservationData paths are rewritten.\n'
        'Includes FreeCAD-3sc: lossless native Array2D TypedArray, material-card\n'
        'persistence and exact FEM input provenance for native GUI cell edits.\n'
        'New typed Array2D cards require this version or newer compatible readers;\n'
        'older FreeCAD versions cannot read the new typed card representation.\n'
        'ShapeMaterial in FCStd remains a UUID reference, not embedded unsaved\n'
        'material data: retain the saved material library with the project.\n'
        'Array3D/scalar persistence is unchanged and separately tracked.\n'
        'Includes FreeCAD-4jb: native accounting provenance stability correction.\n'
        'Software import/lifecycle qualification is not engineering acceptance.\n'
        'Includes FreeCAD-9zt: separately versioned native support and explicit\n'
        'equilibrium-cut accounting, owned contact/load terms and provenance.\n'
        'Enable NativeForceAccounting on the CalculiX solver; for a native cut,\n'
        'enable NativeEquilibriumCut and select AccountingBody on SectionPrint.\n'
        'The qualified solver is data/NativeSolvers/ccx-force-accounting.\n'
        'Its source, precise domain and contract are in data/NativeSolvers/source.\n'
        'Standard RF/SOF/SOM/CF and ordinary solver preferences are unchanged.\n'
        'All earlier fixes, including native GUI colourbar/export improvements,\n'
        'mesh ownership, Tet4 volume and typing/build fixes, remain included.\n'
        'Updated main and all earlier recent fixes remain included.\n'
        'Affected older independently meshed coincident regions require remeshing\n'
        'to generate persistent native ownership metadata. Genuine overlap is rejected.\n'
        'Native program and workbenches are installed in Contents/Resources.\n'
        'External Python, Qt, OCCT and other dependencies remain required at:\n'
        f'{PREFIX}\n'
        'Qt 6.11.2 Cocoa accessibility package: pl5321h12ef06d_2.\n'
        'Preserved native launchers select this external patched plugin directly;\n'
        'no historical app-local qt-cocoa overlay is installed.\n'
        'This host-local app is not a self-contained, notarized distribution.\n'
        'User profiles remain under Library/Application Support/FreeCAD Local.\n'
        'Native startup uses the canonical namespace in this app Ext/freecad.\n'
        'All 11 external namespace files are unchanged; no helper/cache swap is needed.\n'
        f'To reverse this install, quit FreeCAD and restore {BACKUP}.\n'
        'The earlier combined-main namespace backup remains historical and is not\n'
        'needed to reverse only this 927 application replacement.\n'
        'This software fix is not physical joint, house/BIM or Oomakhi design acceptance.\n')
    assert not (resources / 'qt-cocoa').exists()
    sign(STAGE)
    with (ROOT / 'stage-material-native-parity.json').open('x') as stream:
        json.dump(material_native_parity(resources), stream, indent=2)
        stream.write('\n')
    with (ROOT / 'stage-fem-native-parity.json').open('x') as stream:
        json.dump(fem_native_parity(resources), stream, indent=2)
        stream.write('\n')
    assert digest(resources / 'data/NativeSolvers/ccx-force-accounting') == OLD_NATIVE_SHA256
    # The GUI wrapper signature may change; its executable instructions must not.
    assert (APP / 'Contents/MacOS/FreeCAD').read_bytes()[:34240] == (
        STAGE / 'Contents/MacOS/FreeCAD').read_bytes()[:34240]
    assert (APP / 'Contents/MacOS/FreeCADCmd').read_bytes() == (
        STAGE / 'Contents/MacOS/FreeCADCmd').read_bytes()
    check_namespace(plan)
    (ROOT / 'stage-inventory.json').write_text(json.dumps(inventory(STAGE), indent=2) + '\n')
    print('STAGE VERIFIED', STAGE, version, 'namespace:11 unchanged,0 writes', flush=True)


def swap():
    for path in (APP, STAGE):
        assert path.is_dir() and not path.is_symlink()
        HELPER['no_live_app'](path)
        verify(path)
    baseline = json.loads((ROOT / 'baseline-inventory.json').read_text())
    staged = json.loads((ROOT / 'stage-inventory.json').read_text())
    assert inventory(APP) == baseline
    assert inventory(STAGE) == staged
    assert BACKUP.parent.is_dir() and not BACKUP.parent.is_symlink()
    assert not BACKUP.exists() and not BACKUP.is_symlink()
    assert APP.stat().st_dev == STAGE.stat().st_dev == BACKUP.parent.stat().st_dev
    source_equal(STAGE / 'Contents/Resources')
    sequence = json.loads((ROOT / 'stage-sequence-result.json').read_text())
    assert sequence['passed'] and len(sequence['gates']) == len(GATES)
    assert {gate['mode'] for gate in sequence['gates']} == set(GATES)
    for mode in GATES:
        report = json.loads((ROOT / f'stage-{mode}/summary.json').read_text())
        assert report['passed'] and report['expected_commit'] == COMMIT, mode
    for mode in ('cmd', 'gui'):
        report = json.loads((ROOT / f'stage-native-{mode}/summary.json').read_text())
        assert report['passed'] and report['expected_commit'] == COMMIT
        focused = json.loads((ROOT / f'stage-4jb-{mode}/summary.json').read_text())
        assert focused['passed'] and focused['expected_commit'] == COMMIT
        assert focused['expected_revision'] == REVISION
        assert focused['application'] == str(STAGE)
    native_report = json.loads((ROOT / 'stage-native-analytic/qualification.json').read_text())
    assert native_report['passed'] and len(native_report['analytic_cases']) >= 48
    assert native_report['binary_sha256'] == digest(STAGE / 'Contents/Resources/data/NativeSolvers/ccx-force-accounting')
    assert native_report['binary_sha256'] == OLD_NATIVE_SHA256
    fem = json.loads((ROOT / 'stage-fem/summary.json').read_text())
    assert fem['passed'] and fem['application'] == str(STAGE)
    assert fem['expected_commit'] == COMMIT and fem['expected_revision'] == REVISION
    assert fem['configured_suite_counts']['TestFemApp'] == 373
    assert sequence['fem_927_report'] == str(ROOT / 'stage-fem/summary.json')
    status_path = check_exit_status('stage', STAGE)
    check_3sc('stage', STAGE)
    assert sequence['exit_status_report'] == str(status_path)
    for path, expected in json.loads((ROOT / 'profile-inventories.json').read_text()).items():
        assert inventory(Path(path)) == expected, path
    plan = json.loads((ROOT / 'namespace-plan.json').read_text())
    check_namespace(plan)
    HELPER['no_live_app'](APP)
    HELPER['no_live_app'](STAGE)
    payload_audit = json.loads((ROOT / 'independent-payload-audit.json').read_text())
    stage_audit = json.loads((ROOT / 'independent-stage-audit.json').read_text())
    custody_audit = json.loads((ROOT / 'independent-stage-custody.json').read_text())
    assert payload_audit['passed'] and payload_audit['commit'] == COMMIT
    assert stage_audit['passed'] and stage_audit['source_commit'] == COMMIT
    assert custody_audit['passed'] and custody_audit['compiled_commit'] == COMMIT
    assert stage_audit['native_payload_parity_count'] == payload_audit['payload_native_count'] == 61
    moved_new = False
    APP.rename(BACKUP)
    try:
        STAGE.rename(APP)
        moved_new = True
        APP.touch()
        verify(APP)
        verify(BACKUP)
        assert inventory(APP) == staged
        assert inventory(BACKUP) == baseline
        check_namespace(plan)
    except BaseException as failure:
        rollback_errors = []
        if moved_new:
            try:
                APP.rename(STAGE)
            except BaseException as error:
                rollback_errors.append(f'new app to stage: {error!r}')
        try:
            BACKUP.rename(APP)
        except BaseException as error:
            rollback_errors.append(f'original app restore: {error!r}')
        if rollback_errors:
            raise RuntimeError(f'Rollback requires attention: {rollback_errors}; '
                               f'app backup={BACKUP}; new app={STAGE}; current app={APP}') from failure
        assert inventory(APP) == baseline
        check_namespace(plan)
        raise
    print('INSTALLED', APP, '\nBACKUP', BACKUP, '\nNAMESPACE:11 unchanged,0 writes', flush=True)


if __name__ == '__main__':
    assert len(sys.argv) == 2 and sys.argv[1] in ('stage', 'sign', 'swap')
    {'stage': stage, 'sign': lambda: sign(STAGE), 'swap': swap}[sys.argv[1]]()
