"""Retain immutable qualification bytes without migrating their provenance."""
import hashlib
import json
from pathlib import Path
import shutil
import stat
import subprocess
import tarfile

from run_gate import protected, serial, sha

WORK = Path(__file__).resolve().parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
OUT = REPO / 'package/local-completion/freecad-9ii-source-evidence'
VALIDATION = REPO / 'package/local-completion/freecad-9ii-validation.json'
FINAL = {'native-build-r03': None, 'application-build-r03': None, 'gui-r05': 4,
         'final-native-r02': 14, 'final-interfaces-r02': 1, 'final-fingerprint-r02': 5,
         'final-regressions-r02': 110, 'cold-r03': 1}
FAILURES = {
    'stock-baseline': 'Harness App.__file__ assumption, not a product result',
    'native-state-red': 'Actual installed missing NativeContactOutputs RED',
    'native-build-r01': 'Extension patch context mismatch before compilation',
    'fingerprint-probe-r01': 'Diagnostic harness accessed a closed object',
    'restore-r01': 'Overoptimistic restore promotion exposed fingerprint/session and raw-label differences',
    'restore-r02': 'Raw mesh labels changed on restore; guard correctly refused promotion',
    'interfaces-r01': 'Independent test oracle used wrong public-to-ABAQUS connectivity convention',
    'safety-red-r01': 'Actual incomplete-final-frame parser RED plus nondeterministic multithread exact-comparison harness assumption',
    'latest-attempt-red-r01': 'Actual superseded native child republished Current before latest-attempt fence',
    'absolute-selection-red-r01': 'Actual mutable PATH-based selection admitted before absolute-path boundary',
    'gui-r01': 'Harness required visible controls without showing the native Tasks pane',
    'gui-r02': 'Native camera action timer encountered deferred view teardown between tests; harness DeferredDelete drain fixed lifecycle',
    'fingerprint-r01': 'Harness attempted immutable mesh mutation and assumed no native cache creation on link retarget',
}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')


def retain(source, relative):
    source = Path(source)
    assert stat.S_ISREG(source.lstat().st_mode), source
    target = OUT / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    assert not target.exists()
    before = sha(source)
    shutil.copy2(source, target)
    assert before == sha(source) == sha(target)
    return str(target.relative_to(OUT))


def blob(source):
    digest = sha(source)
    target = OUT / 'as-run/blobs' / digest
    if not target.exists():
        retain(source, target.relative_to(OUT))
    assert sha(target) == digest
    return {'sha256': digest, 'evidence': str(target.relative_to(OUT)),
            'size': source.stat().st_size}


serial()
protection = protected()
assert not VALIDATION.exists()
OUT.mkdir(exist_ok=False)
records = {}
for run in sorted(WORK.iterdir()):
    receipt = run / 'execution.json'
    if not receipt.is_file():
        continue
    data = json.loads(receipt.read_text())
    assert sha(run / 'run.log') == data['log_sha256']
    retain(receipt, Path('execution') / run.name / receipt.name)
    retain(run / 'run.log', Path('execution') / run.name / 'run.log')
    if run.name in FINAL:
        assert data['passed'] and data['returncode'] == 0 and not data['timed_out']
        assert data['child_reaped'] and data['group_gone']
        assert data['inputs_before'] == data['inputs_after']
        assert data['protected_before'] == data['protected_after'] == protection
        if FINAL[run.name] is not None:
            assert data['test_counts'] == [str(FINAL[run.name])]
    snapshots = {}
    if (run / 'inputs').exists():
        for path in sorted((run / 'inputs').rglob('*')):
            if path.is_file() and not path.is_symlink():
                snapshots[str(path.relative_to(run / 'inputs'))] = blob(path)
    records[run.name] = {'passed': data['passed'], 'returncode': data['returncode'],
        'tests': data.get('test_counts', []), 'execution': f'execution/{run.name}/execution.json',
        'classification': ('Final exact-source gate' if run.name in FINAL else
            FAILURES.get(run.name, 'Intermediate or diagnostic gate; not final acceptance')),
        'source_snapshots': snapshots}
assert set(FINAL) <= set(records)
assert all(records[label]['passed'] is False for label in FAILURES if label in records)
write_json(OUT / 'execution-index.json', records)

for path in sorted(WORK.glob('*.py')):
    retain(path, Path('harness') / path.name)
for name in ('PrepareBundle.receipt.json', 'ColdContactWitness.witness.json',
             'LinkFingerprintProbe.states.json', 'fingerprint-states.json',
             'code-review-safety-final.json'):
    retain(WORK / name, Path('receipts') / name)
retain(WORK / 'stock-baseline-r02/baseline.json', 'receipts/stock-baseline.json')
native = WORK / 'native-build-r03/native'
for path in [*sorted(native.glob('*.log')), native / 'build-receipt.json',
             native / 'pixi.toml', native / 'pixi.lock']:
    retain(path, Path('native-build') / path.name)
for name in ('recipe-pins.json', 'pixi.toml', 'pixi.lock', 'build_probe.py'):
    retain(REPO / 'package/local-completion/calculix-9zt-probe' / name,
           Path('native-build/driver') / name)
for path in sorted((native / 'functional-tests').iterdir()):
    if path.suffix in ('.inp', '.ref') or path.name == 'run_test.py':
        retain(path, Path('native-build/functional-tests') / path.name)
for name in ('contactstate.c', 'forceaccounting.c', 'hooks.patch', 'contract.json', 'COPYING'):
    retain(REPO / 'package/calculix/force-accounting' / name, Path('native-source') / name)

cold_fixture = WORK / 'safety-green-r01/tmp/freecad-contact-state-native-lr4amy1_'
roots = [(label, WORK / label / 'tmp') for label in
         ('final-native-r02', 'final-interfaces-r02', 'gui-r05')]
roots.append(('exact-cold-source', cold_fixture))
artifacts = []
with tarfile.open(OUT / 'native-fixtures.tar.gz', 'x:gz', compresslevel=6) as archive:
    for label, root in roots:
        for path in sorted(root.rglob('*')):
            if path.is_symlink() or not path.is_file():
                continue
            if not (path.suffix in ('.inp', '.dat', '.frd', '.sta', '.cvg', '.FCStd')
                    or '.contact-state' in path.name or '.accounting' in path.name
                    or '.frd.' in path.name):
                continue
            name = str(Path(label) / path.relative_to(root))
            before = sha(path)
            archive.add(path, arcname=name, recursive=False)
            assert sha(path) == before
            artifacts.append({'original': str(path), 'archive_member': name,
                              'sha256': before, 'size': path.stat().st_size})
write_json(OUT / 'native-fixture-index.json', artifacts)

review = json.loads((WORK / 'code-review-safety-final.json').read_text())
source_hashes = review['reviewed_source_files_sha256']
for name, expected in source_hashes.items():
    assert sha(REPO / name) == expected, name
manifest = [{'path': str(path.relative_to(OUT)), 'sha256': sha(path),
             'size': path.stat().st_size}
            for path in sorted(OUT.rglob('*')) if path.is_file()]
write_json(OUT / 'manifest.json', manifest)
assert protected() == protection
serial()
write_json(VALIDATION, {
    'schema': 'FREECAD_9II_SOURCE_QUALIFICATION_V1', 'issue': 'FreeCAD-9ii',
    'source_verification_passed': True, 'independent_evidence_audit': 'pending',
    'meaning': 'Software request/native-output/import/inspection qualification only; not contact-law accuracy or building design acceptance',
    'build_base_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip(),
    'source_files_sha256': source_hashes, 'final_gates': FINAL,
    'final_test_count': sum(value for value in FINAL.values() if value is not None),
    'evidence_root': str(OUT.relative_to(REPO)), 'manifest_sha256': sha(OUT / 'manifest.json'),
    'native_schema': 'CCX_CONTACT_STATE_V1', 'preserved_accounting_schema': 'CCX_FORCE_ACCOUNTING_V3',
    'qualified_native_sha256': '0c2a86318df9c7cc9d921e5068ae52f1d53e27b7b16747e00a74ccc8fe37c6cc',
    'native_binary_committed': False, 'native_build_receipt_physical_duty_qualified': False,
    'analytical_software_qualification': '14 final native tests include exact deterministic diagnostics-on/off FRD (excluding creation timestamps), CF/CFN/CFS and V3 parity; native state/identity, Tet4/Tet10, rotated frame and fail-closed custody checks. Separate two-contact ownership/selection test and four real GUI cases passed.',
    'cold_restore': 'Literal original raw labels/provenance preserved as Historical; changed native mesh labels refuse explicit refresh and require a fresh stock writer/owned run. No cold Current promotion is asserted.',
    'relocation': 'Archive members preserve original bytes and absolute provenance paths. This index records relocation only; relocated historical files are not relabelled Current. Vendor source/build tree and platform binary are not retained in git; rebuild from pinned archive/recipe/toolchain and the committed custom sources.',
    'limitations': ['Same-document physical dependencies; absolute executable path or default bundle',
        'One small-displacement mechanical static step; Tet4/Tet10 and documented native contact domain',
        'Frame-local native sample catalogue, not persistent material points',
        'Inactive/unpaired constitutive channels remain unavailable; no invented zero state',
        'No changed geometry, loads or 1%/5% engineering limits; no Oomakhi opening, solve or acceptance'],
    'installation_performed': False, 'installed_application_unchanged': True,
    'protected_inventory_sha256': protection,
    'pre_push_rails_skill': {'status': 'not applicable',
        'discovery': 'No Gemfile, Rails wrappers, config/importmap.rb or package.json; no Rails/JS/RSpec checks configured. Native FreeCAD gates used.',
        'checks': dict.fromkeys(('bundler-audit', 'pending migrations', 'Zeitwerk', 'RuboCop',
            'Brakeman', 'importmap audit', 'ERB lint', 'JS lint', 'RSpec'), 'SKIPPED: not applicable')},
})
print(json.dumps({'evidence_files': len(manifest), 'gates': len(records),
                  'native_artifacts': len(artifacts), 'final_tests': 135,
                  'archive_bytes': (OUT / 'native-fixtures.tar.gz').stat().st_size,
                  'validation': str(VALIDATION)}, indent=2))
