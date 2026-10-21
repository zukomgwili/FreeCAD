"""Final live custody/signature checks and compact exact-byte evidence retention."""
import gzip
import hashlib
import json
from pathlib import Path
import re
import time

import critical_pins
import run_gate
import stage_install as install

ROOT = Path(__file__).resolve().parent
DEST = install.REPO / 'package/local-completion/freecad-8rk-installation-evidence'
SUMMARY = install.REPO / 'package/local-completion/freecad-8rk-installation.json'
LABELS = ('build-latest', 'ctest-latest', 'step-capture', 'step-payload',
          'step-capture-r02', 'step-payload-r02', 'step-audit-payload', 'step-stage',
          'step-audit-stage', 'step-audit-custody', 'stage-cmd', 'stage-gui',
          'step-swap', 'installed-cmd', 'installed-gui')
assert __debug__ and not DEST.exists() and not SUMMARY.exists()
run_gate.serial()
install.compiled_identity()
critical = critical_pins.verify()
sealed = json.loads((ROOT / 'stage-inventory.json').read_text())
baseline = json.loads((ROOT / 'baseline-inventory.json').read_text())
assert install.inventory(install.APP) == sealed
assert install.inventory(install.BACKUP) == baseline
for name, proof in json.loads((ROOT / 'profile-inventories.json').read_text()).items():
    assert install.inventory(Path(name)) == proof
install.check_namespace(json.loads((ROOT / 'namespace-plan.json').read_text()))
install.verify(install.APP)
install.verify(install.BACKUP)
for mode, count in (('cmd', 2), ('gui', 10)):
    install.application_gate(install.APP, 'installed-' + mode, count)

captured = {}


def read(relative):
    data = (ROOT / relative).read_bytes()
    captured[relative] = data
    return data


def sha(data):
    return hashlib.sha256(data).hexdigest()


receipts = {}
for label in LABELS:
    row = json.loads(read(label + '/execution.json'))
    log = read(label + '/run.log')
    assert sha(log) == row['log_sha256']
    assert row['returncode'] == (1 if label == 'step-capture' else 0)
    assert row['passed'] is (label != 'step-capture')
    assert not row['timed_out'] and row['child_reaped'] and row['process_group_gone']
    assert row['source_commit'] == install.COMMIT
    receipts[label] = row
ctest = captured['ctest-latest/run.log'].decode()
rows = re.findall(r'^\s*(\d+)/(\d+) Test\s+#(\d+):\s+(\S+)\s+\.{2,}\s*(.*)$', ctest, re.M)
assert len(rows) == 2277 and {int(row[1]) for row in rows} == {2277}
assert {int(row[0]) for row in rows} == {int(row[2]) for row in rows} == set(range(1, 2278))
assert len({row[3] for row in rows}) == 2277
passed = [row[3] for row in rows if row[4].startswith('Passed')]
skipped = [row[3] for row in rows if row[4].startswith('***Skipped')]
disabled = [row[3] for row in rows if row[4].startswith('***Not Run (Disabled)')]
assert (len(passed), len(skipped), len(disabled)) == (2267, 2, 8)
assert '100% tests passed out of 2269' in ctest
for name in ('BackupPolicyTest.TimestampTargetHasNoExtension',
             'BackupPolicyTest.TimestampExtensionlessTargetStaysInDottedDirectory',
             'FileInfoExtensionTest.PreservesBasenameExtensionConventions',
             'FileInfoExtensionTest.IgnoresDotsInParentDirectories'):
    assert name in passed
for label in ('stage-cmd', 'stage-gui', 'installed-cmd', 'installed-gui'):
    read(label + '/manifest.json')
    proof = json.loads(read(label + '/regression.json'))
    assert proof['passed'] and proof['commit'] == install.COMMIT
    for filename, expected in proof['backup_regression']['final_file_sha256'].items():
        path = Path(filename)
        assert path.is_relative_to(ROOT / label / 'witness')
        assert sha(read(str(path.relative_to(ROOT)))) == expected
for name in ('independent-payload-audit.json', 'independent-stage-audit.json',
             'independent-stage-custody.json', 'critical-before-DESTDIR.json',
             'namespace-plan.json', 'build-identity.json', 'LOCAL-INSTALL.txt'):
    read(name)
for path in sorted(ROOT.glob('*.py')):
    read(path.name)
payload = json.loads(captured['independent-payload-audit.json'])
stage = json.loads(captured['independent-stage-audit.json'])
assert payload['passed'] and stage['passed'] and stage['stage_signature_verified']
assert all((ROOT / name).read_bytes() == data for name, data in captured.items())
assert install.inventory(install.APP) == sealed and install.inventory(install.BACKUP) == baseline
critical_pins.verify()
DEST.mkdir()
index = {}
for name, original in captured.items():
    compressed = name.endswith('run.log')
    relative = name + '.gz' if compressed else name
    data = gzip.compress(original, mtime=0) if compressed else original
    path = DEST / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(data)
    index[relative] = {'bytes': len(data), 'sha256': sha(data)}
    if compressed:
        index[relative]['uncompressed_sha256'] = sha(original)
manifest = install.BUILD / 'install_manifest.txt'
data = gzip.compress(manifest.read_bytes(), mtime=0)
(DEST / 'install_manifest.txt.gz').write_bytes(data)
index['install_manifest.txt.gz'] = {'bytes': len(data), 'sha256': sha(data),
                                     'uncompressed_sha256': install.digest(manifest)}
install.write_json(DEST / 'index.json', {'source_commit': install.COMMIT, 'files': index,
    'raw_user_or_app_inventory_bodies_retained': False})
install.write_json(SUMMARY, {
    'schema': 'FreeCAD-8rk-installation-validation-v1', 'passed': True,
    'date': '2026-10-21', 'deployment_bead': 'FreeCAD-soh', 'fix_bead': 'FreeCAD-8rk',
    'application': str(install.APP), 'rollback_backup': str(install.BACKUP),
    'source_commit': install.COMMIT, 'revision': install.REVISION,
    'modified_local_time': time.strftime('%Y-%m-%d %H:%M:%S %Z', time.localtime(install.APP.stat().st_mtime)),
    'build': {'full_incremental_Release': True, 'clean_from_scratch_claimed': False,
              'nonfatal_Pivy_stub_warning_tracked_separately': 'FreeCAD-szc'},
    'ctest': {'catalogue': 2277, 'passed': 2267, 'failed': 0, 'existing_skipped': skipped,
              'existing_disabled': disabled, 'excluded': [], 'genuinely_dotted_TMPDIR': True,
              'elapsed_seconds': receipts['ctest-latest']['elapsed_seconds']},
    'application_tests': {'stage_cmd': 2, 'stage_gui': 10, 'installed_cmd': 2, 'installed_gui': 10,
        'GUI_controls': 'Eight unchanged TestFemGui tests plus two new native identity/save tests.',
        'regression': 'Extensionless native document under dotted parent; two backups contain exact previous file bytes, no escaped/temp files, values third/first/second survive native same-process reopen.',
        'separate_cold_process_claimed': False},
    'payload': {'complete_native_images': payload['payload_native_count'],
                'non_native_payload_matches': stage['non_native_payload_matches'],
                'full_DESTDIR_manifest_leaf_set_verified': True,
                'stage_and_installed_exact_sealed_inventory_sha256': install.canonical_sha(sealed),
                'old_backup_exact_inventory_sha256': install.canonical_sha(baseline),
                'strict_signatures_and_extension_entitlements_verified': True,
                'resources_readonly_and_cachefree': True},
    'preservation': {'profiles_unchanged': len(install.PROFILES), 'external_namespace_files_unchanged': 11,
                     'selected_critical_dependency_files_unchanged': len(critical['files']),
                     'whole_dependency_environment_inventory_claimed': False},
    'preparation_history': 'Initial capture child failed to import the private helper. A first DESTDIR-only payload was accidentally created before baseline capture; it was preserved as payload-before-capture and is not qualifying evidence. The import was corrected, successful capture-r02 preceded a freshly regenerated qualifying payload-r02 and all stage/installed gates. Both earlier receipts/logs remain honest historical setup outputs; finalized helpers are not a full historical checkout of initial setup.',
    'runtime_dependency': str(install.PREFIX), 'self_contained': False, 'notarized': False,
    'scope': 'Current fork software deployment only; no engineering/Oomakhi acceptance, project solve, dependency upgrade, source fix or upstream PR.',
    'evidence': {'directory': str(DEST.relative_to(install.REPO)), 'files': len(index),
                 'index_sha256': install.digest(DEST / 'index.json'), 'private_directory': str(ROOT)},
    'metadata_note': 'Installation was tested against this compiled source commit; later tracking/evidence commits do not change its binary identity.'})
print(json.dumps({'passed': True, 'retained_files': len(index), 'application': str(install.APP),
                  'backup': str(install.BACKUP), 'revision': install.REVISION}))
