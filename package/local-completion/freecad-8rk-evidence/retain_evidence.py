"""Retain exact FreeCAD-8rk gate receipts and compressed logs; never run native code."""
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess

PRIVATE = Path(__file__).resolve().parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
COMMIT = '7136d8188e779b6fb2c4decbd1509f26a1e68f70'
DEST = REPO / 'package/local-completion/freecad-8rk-evidence'
LABELS = (
    'red-r01', 'red-r02', 'dot-free-control', 'build-red-tests',
    'new-base-red', 'new-backup-red', 'build-green-tests', 'new-base-green',
    'new-backup-green', 'original-repro-green', 'committed-release-build',
    'committed-base-all', 'committed-backup-all', 'committed-ctest',
)
RED = {'red-r01', 'red-r02', 'new-base-red', 'new-backup-red'}
SUMMARY = REPO / 'package/local-completion/freecad-8rk-validation.json'
assert not DEST.exists() and not SUMMARY.exists()
assert not (PRIVATE / 'build-identity-after.json').exists()
captured = {}


def capture(relative):
    data = (PRIVATE / relative).read_bytes()
    captured[relative] = data
    return data


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO,
                               text=True).strip() == COMMIT
identity = json.loads(capture('build-identity-before.json'))
assert identity['source_commit'] == COMMIT
assert identity['compiled_revision'] == '49261 +231 (Git)'
after = {name: sha((REPO / name).read_bytes()) for name in identity['sha256']}
assert after == identity['sha256'], 'Selected build/input bytes changed'
header = (REPO / 'build/release/src/Build/Version.h').read_bytes()
assert sha(header) == after['build/release/src/Build/Version.h']
assert re.search(rb'#define FCRepositoryHash\s+"' + COMMIT.encode() + rb'"', header)
assert re.search(rb'#define FCRevision\s+"49261 \+231 \(Git\)"', header)
review = json.loads(capture('static-review.json'))
assert review['passed'] is True and review['commit'] == COMMIT
assert review['findings'] == []
for name, digest in review['files'].items():
    assert after[name] == digest

receipts = {}
for label in LABELS:
    receipt = json.loads(capture(label + '/execution.json'))
    raw = capture(label + '/run.log')
    assert sha(raw) == receipt['log_sha256']
    assert receipt['returncode'] == (1 if label in RED else 0)
    assert receipt['timed_out'] is False and receipt['child_reaped'] is True
    assert receipt['app_and_three_profiles_unchanged'] is True
    assert receipt.get('inputs_unchanged', receipt.get('source_and_supervisor_unchanged'))
    assert receipt.get('process_group_gone', True)
    if label.startswith('committed-'):
        assert receipt['source_commit'] == COMMIT and receipt['passed'] is True
        assert receipt['dot_free_substitution'] is False
    receipts[label] = receipt

commands = {
    'committed-release-build': ['cmake', '--build', 'build/release', '--parallel', '8'],
    'committed-base-all': ['build/release/tests/Base_tests_run'],
    'committed-backup-all': ['build/release/tests/App_tests_run', '--gtest_filter=BackupPolicyTest.*'],
    'committed-ctest': ['ctest', '--test-dir', 'build/release', '--output-on-failure',
                        '--parallel', '1', '--timeout', '60'],
}
for label, command in commands.items():
    assert receipts[label]['command'] == ['pixi', 'run', '--frozen'] + command
base_log = captured['committed-base-all/run.log'].decode()
backup_log = captured['committed-backup-all/run.log'].decode()
for text, count in ((base_log, 661), (backup_log, 23)):
    assert re.findall(r'^\[  PASSED  \] (\d+) tests\.$', text, re.MULTILINE) == [str(count)]
assert '661 tests from 60 test suites ran.' in base_log
assert 'YOU HAVE 1 DISABLED TEST' in base_log and '[  SKIPPED ]' not in base_log
assert '25 tests from 1 test suite ran.' in backup_log
assert 'YOU HAVE 2 DISABLED TESTS' in backup_log
assert '[  SKIPPED ] 2 tests, listed below:' in backup_log
for name in ('FileInfoExtensionTest.PreservesBasenameExtensionConventions',
             'FileInfoExtensionTest.IgnoresDotsInParentDirectories'):
    assert '[       OK ] ' + name + ' ' in base_log
for name in ('BackupPolicyTest.TimestampTargetHasNoExtension',
             'BackupPolicyTest.TimestampExtensionlessTargetStaysInDottedDirectory'):
    assert '[       OK ] ' + name + ' ' in backup_log
log = captured['committed-ctest/run.log'].decode()
rows = re.findall(r'^\s*(\d+)/(\d+) Test\s+#(\d+):\s+(\S+)\s+\.{2,}\s*(.*)$',
                  log, re.MULTILINE)
assert len(rows) == 2277 and {int(row[1]) for row in rows} == {2277}
assert {int(row[0]) for row in rows} == set(range(1, 2278))
assert {int(row[2]) for row in rows} == set(range(1, 2278))
assert len({row[3] for row in rows}) == 2277
passed = [row[3] for row in rows if row[4].startswith('Passed')]
skipped = [row[3] for row in rows if row[4].startswith('***Skipped')]
disabled = [row[3] for row in rows if row[4].startswith('***Not Run (Disabled)')]
assert len(passed) == 2267 and len(skipped) == 2 and len(disabled) == 8
assert set(skipped) == {'BackupPolicyTest.StandardWithZeroFilesDeletesExisting',
                        'BackupPolicyTest.TimestampWithZeroFilesDeletesExisting'}
for name in ('BackupPolicyTest.TimestampTargetHasNoExtension',
             'BackupPolicyTest.TimestampExtensionlessTargetStaysInDottedDirectory',
             'FileInfoExtensionTest.PreservesBasenameExtensionConventions',
             'FileInfoExtensionTest.IgnoresDotsInParentDirectories'):
    assert name in passed
assert '100% tests passed out of 2269' in log

for name in ('run_backup_probe.py', 'run_backup_probe_v2.py', 'run_gate.py',
             'retain_evidence.py'):
    capture(name)
assert all((PRIVATE / name).read_bytes() == data for name, data in captured.items())
assert all(sha((REPO / name).read_bytes()) == digest for name, digest in after.items())
write_json(PRIVATE / 'build-identity-after.json', {
    'schema': 'FreeCAD-8rk-build-identity-endcheck-v1',
    'observed': 'after complete committed CTest', 'source_commit': COMMIT,
    'sha256': after, 'matches_recorded_during_ctest': True,
})
capture('build-identity-after.json')
DEST.mkdir()
entries = {}


def retain(relative, data, original=None):
    target = DEST / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as stream:
        stream.write(data)
    entries[relative] = {'bytes': len(data), 'sha256': sha(data)}
    if original is not None:
        entries[relative]['uncompressed_sha256'] = sha(original)


for label in LABELS:
    retain(label + '/execution.json', captured[label + '/execution.json'])
    raw = captured[label + '/run.log']
    retain(label + '/run.log.gz', gzip.compress(raw, mtime=0), original=raw)
for name in ('run_backup_probe.py', 'run_backup_probe_v2.py', 'run_gate.py',
             'retain_evidence.py', 'static-review.json', 'build-identity-before.json',
             'build-identity-after.json'):
    retain(name, captured[name])
retain('Version.h', header)
write_json(DEST / 'index.json', {
    'schema': 'FreeCAD-8rk-retained-evidence-v1', 'source_commit': COMMIT,
    'meaning': 'Exact gate receipts/logs; gzip logs preserve uncompressed byte hashes.',
    'files': entries,
})
write_json(SUMMARY, {
    'bead': 'FreeCAD-8rk', 'date': '2026-10-21',
    'status': 'source_fixed_built_and_verified_not_installed',
    'source_commit': COMMIT, 'compiled_revision': '49261 +231 (Git)',
    'reproduced_before_implementation_read': True,
    'cause': 'Both FileInfo suffix accessors searched the full path, treating a parent-directory dot as part of the filename suffix and truncating an extensionless timestamp-backup path.',
    'fix': 'Search the existing normalized fileName() basename, retaining established first/last-dot, hidden-file, trailing-dot and case conventions. BackupPolicy itself is unchanged.',
    'regressions': 'Ten baseline names, forty dotted-parent/normalized-separator/UNC variants, and an isolated timestamp-backup placement/content/collision regression; both bug regressions failed before the fix.',
    'original_reproduction': {
        'dotted_parent_red_runs': 2, 'dot_free_diagnostic_control_passed': True,
        'dotted_parent_green_passed': True,
        'red_stray_backups': 'Nine-byte Test data, outside requested TMPDIR but inside private task quarantine; no user data affected.',
        'red_and_precommit_green_are_not_committed_qualification': True,
    },
    'committed_gates': {
        'release_build': receipts['committed-release-build']['passed'],
        'base': {'passed': 661, 'disabled': 1, 'failed': 0},
        'backup_policy': {'passed': 23, 'existing_skipped': 2, 'disabled': 2, 'failed': 0},
        'ctest': {'catalogue': len(rows), 'passed': len(passed), 'failed': 0,
                  'existing_skipped': skipped, 'existing_disabled': disabled,
                  'elapsed_seconds': receipts['committed-ctest']['elapsed_seconds'],
                  'complete_unique_catalogue_verified': True, 'excluded': []},
        'temporary_directory': 'Genuinely dotted private TMPDIR for every qualification gate; no dot-free substitution.',
        'incremental_release_build_not_clean_from_scratch': True,
        'nonfatal_build_warning': 'Pivy .pyi generation reported missing output; retained verbatim and tracked separately as FreeCAD-szc, with no causal or runtime-failure claim.',
        'selected_build_identity_unchanged_after_ctest': True,
        'independent_static_review_findings': [],
        'whitespace': 'CRLF-aware committed-diff check passes; existing FileInfo.cpp CRLF retained.',
        'rails_pre_push_checks': 'Not applicable: no Rails application, Gemfile, gemspec, wrappers, importmap or root JS lint configuration. Only a vendored Coin documentation package.json exists.',
    },
    'evidence': {'directory': 'package/local-completion/freecad-8rk-evidence',
                 'index_sha256': sha((DEST / 'index.json').read_bytes()),
                 'retained_files': len(entries), 'private_directory': str(PRIVATE)},
    'collector_history': 'Initial collector aborted before any writes because its summary-line assertion expected a different CTest wording. Corrected to the actual 100% tests passed out of 2269 line; unique result-row/count validation and native results were unchanged.',
    'installation': {'performed': False, 'installed_app_and_three_profiles_unchanged': True,
                     'installed_revision_remains': '49261 +229 (Git)',
                     'dependency_environment': '/Users/zukomgwili/src/FreeCAD/.pixi/envs/default'},
    'limits': ['No installation or upstream PR requested or performed.',
               'Runtime qualification is macOS only, not a direct Windows/Linux run.',
               'No Oomakhi solve, fixture change, engineering acceptance or new public API.'],
})
print(json.dumps({'retained_files': len(entries), 'ctest_passed': len(passed),
                  'selected_build_identity_unchanged': True}))
