"""Publish exact serial qualification records, withholding private runtime state."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
DEST = REPO/'package/local-completion/freecad-960-source-evidence'
EXPECTED_RED = {
    'installed-stock-baseline-r01','request-red-r01','native-capability-red-r01',
    'native-axial-red-r01','gui-red-r01','inspector-red-r01','safety-red-r01',
    'relative-red-r01','projection-red-r01','frame-red-r01','comment-red-r01',
    'metadata-red-r01','gui-invalid-red-r01',
}
PROTOTYPE = {
    'combined-axial-r01':'Overstrict prototype preflight rejected the default nonlinear-material toggle without an active nonlinear law; corrected to inspect the actual assigned law.',
    'combined-axial-r02':'Product/native axial checks passed; the test used obsolete StressValues instead of actual NodeStress fields.',
    'transverse-y-r01':'Fixture assigned a bare force magnitude in internal mN instead of explicit N; corrected native property units without changing the declared 0.1 N load or 1% limits.',
    'legacy-native-equivalence-r01':'Comparison included differing compiler timestamps; raw differences were inspected, then only build/creation metadata was excluded while preserving every numerical byte.',
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def copy(source, target):
    source, target = Path(source), Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        assert target.read_bytes() == source.read_bytes(), target
    else:
        shutil.copyfile(source,target)
    assert sha(source) == sha(target)


assert not DEST.exists(), 'Publish once; do not rewrite executed evidence'
cases = []
for execution in sorted(ROOT.glob('*/execution.json')):
    directory = execution.parent
    label = directory.name
    report = json.loads(execution.read_text())
    assert report['source_inputs_before'] == report['source_inputs_after'], label
    assert report['source_and_supervisor_unchanged'] is True, label
    assert report['app_and_three_profiles_unchanged'] is True, label
    assert not report['timed_out'] and report['child_reaped'] and report['process_group_gone'], label
    assert sha(directory/'run.log') == report['log_sha256'], label
    if report['passed']:
        classification = 'PASS'
        assert label not in EXPECTED_RED and label not in PROTOTYPE
    else:
        assert report['returncode'] != 0, label
        assert label in EXPECTED_RED or label in PROTOTYPE, label
        classification = 'EXPECTED_RED' if label in EXPECTED_RED else 'NONQUALIFYING_PROTOTYPE'
    manifest = directory/'input-snapshots-complete.json'
    snapshots = json.loads(manifest.read_text())
    assert snapshots['execution_sha256'] == sha(execution), label
    for name, record in snapshots['inputs'].items():
        assert record['sha256'] == report['source_inputs_before'][name]
        if 'snapshot' in record:
            assert sha(ROOT/record['snapshot']) == record['sha256']
    for name in ('execution.json','run.log','input-snapshots-complete.json'):
        copy(directory/name, DEST/label/name)
    cases.append({'case':label,'classification':classification,
                  'receipt':str((DEST/label/'execution.json').relative_to(REPO)),
                  'execution_sha256':sha(execution),
                  'prototype_explanation':PROTOTYPE.get(label)})

assert EXPECTED_RED == {item['case'] for item in cases if item['classification']=='EXPECTED_RED'}
assert set(PROTOTYPE) == {item['case'] for item in cases if item['classification']=='NONQUALIFYING_PROTOTYPE'}
for source in sorted((ROOT/'code-blobs').iterdir()):
    copy(source,DEST/'code-blobs'/source.name)
for name in ('Beam960IndependentAudit.py','independent-equilibrium-audit.json',
             'capture_complete_inputs.py','collect_beam960.py','final-review-and-quality.json',
             'independent_second_review.py','independent-second-review.json',
             'Beam960IndependentAudit-r01-label-error.py','independent-equilibrium-audit-r01-label-error.json'):
    copy(ROOT/name,DEST/'audit'/name)
for name in ('build-receipt.json','functional-tests.log'):
    source=ROOT/'native-build-r01/build'/name
    if source.exists():
        copy(source,DEST/'native-build'/name)
for name in ('inspector.png','saved-output.json'):
    copy(ROOT/'production-gui-r01/test_visible_solver_write_and_run_saves_current_native_beam_end_actions'/name,
         DEST/'inspection'/name)
copy(ROOT/'final-cold-gui-r01/historical-inspector.png',DEST/'inspection/historical-inspector.png')
copy(ROOT/'legacy-observer-equivalence-r01/legacy-equivalence.json',DEST/'audit/legacy-equivalence.json')

# Publish only the small analytical solver artifacts used by the arithmetic
# audit. No application, personal profile, native executable or CAD document.
audit=json.loads((ROOT/'independent-equilibrium-audit.json').read_text())
for case in audit['cases']:
    for name, identity in case['files'].items():
        source=Path(name)
        assert sha(source)==identity['sha256'],source
        copy(source,DEST/'analytical'/source.relative_to(ROOT/'rotated-matrix-r01'))

current = set(subprocess.check_output(['git','diff','--name-only'],cwd=REPO,text=True).splitlines())
current.update(subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=REPO,text=True).splitlines())
selected = [name for name in sorted(current) if name.startswith(('src/Mod/Fem/','package/calculix/force-accounting/'))
            or name in ('package/local-completion/calculix-9zt-probe/build_probe.py',
                        'package/local-completion/freecad-960-research.md')]
sources={name:sha(REPO/name) for name in selected if (REPO/name).is_file()}
summary={
    'schema':'FreeCAD-960-source-validation-v1','bead':'FreeCAD-960',
    'source_base_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
    'source_inputs':sources,
    'native_candidate':json.loads((ROOT/'native-candidate.json').read_text()),
    'application_installation_performed':False,
    'application_and_three_real_profiles_unchanged_in_every_gate':True,
    'executed_stock_solver_decks_edited':False,
    'classification_unit_text_never_executed':True,
    'python_force_or_stress_recovery_used':False,
    'original_Oomakhi_opened_changed_solved_or_accepted':False,
    'supported_domain':'Straight quadratic B32R, rectangular section, pure 1D mesh, unsplit linear small-displacement static 3D; other requests are explicitly refused.',
    'engineering_limit_force_and_moment':0.01,
    'arithmetic_audit':str((DEST/'audit/independent-equilibrium-audit.json').relative_to(REPO)),
    'nonqualifying_audit_draft':'The retained r01-label-error helper/report used a shadowed case-label variable. Its calculations and inputs were unchanged, but its labels are invalid and it is not a qualification record. The corrected six-case report is the arithmetic_audit named above.',
    'independent_second_arithmetic_review':str((DEST/'audit/independent-second-review.json').relative_to(REPO)),
    'auditor_authorship_disclosure':'Fixture author performed the first offline arithmetic audit and reviewed production code not authored by that agent. A separate lifecycle reviewer found and rechecked metadata custody and GUI invalid-write fixes, then independently derived six free bodies directly from stock input coordinates/loads/supports using Decimal arithmetic. That second reviewer authored neither the analytical fixtures, production/native implementation nor first audit. Native observer also received separate standards/spec reviewers. The first report retains its historical note that a newly spawned arithmetic reviewer was unavailable; this was resolved by reusing a different existing agent.',
    'native_mechanics_equivalence':'Three unchanged stock decks: old 0c2a86318df9, new 3fdd2b7f7cc3 Off and On have identical DAT bytes and all FRD bytes except native creation/build timestamp records.',
    'retained_history':'Original execution receipts/logs and their referenced content-addressed text snapshots are copied without alteration. Other inputs remain hash-bound in the original manifests and are withheld, including executables, pinned upstream archive/recipe binaries, generated CAD documents, personal profiles and private environment state. Failed prototypes and expected RED runs are not numerical qualifications.',
    'cases':cases,
}
target=REPO/'package/local-completion/freecad-960-validation.json'
assert not target.exists()
target.write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
print(json.dumps({'cases':len(cases),'source_files':len(sources),'destination':str(DEST),
                  'validation_sha256':sha(target)},indent=2))
