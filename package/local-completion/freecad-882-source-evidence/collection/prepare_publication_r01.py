"""Root's explicit profiling-only review and evidence-plan preparation.

No product imports, native jobs, publication, Git writes or receipt repair.
The separately reviewed collector still checks every proposed input and link.
"""
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
TASK = Path('/private/tmp/freecad-882-VGfnpo')
REPO = Path('/Users/zukomgwili/src/FreeCAD')
RUN = TASK / 'installed-profile-baseline-r02'
PLAN_DIR = TASK / 'planning/collection'
REVIEW = TASK / 'planning/completed-profile-review-r01.json'
PLAN = PLAN_DIR / 'approved-plan-r01.json'
ATTR = TASK / 'planning/measured-source-cost-opportunities-r02.json'
FINAL = TASK / 'planning/final-profiling-review-r01.json'
captured = {}


def need(value, message):
    if not value:
        raise RuntimeError(message)


def data(path):
    path = Path(path)
    if path not in captured:
        need(path.is_file() and not path.is_symlink(), 'Regular file required: ' + str(path))
        captured[path] = path.read_bytes()
    return captured[path]


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


def ref(path):
    return {'path': str(path), 'sha256': sha(data(path))}


def parsed(path):
    return json.loads(data(path))


def write_new(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')


def main():
    need(not REVIEW.exists() and not PLAN.exists(), 'New review and plan paths required')
    execution, profile, attribution, final = map(parsed, (RUN / 'execution.json', RUN / 'export-profile.json', ATTR, FINAL))
    need(execution['passed'] and profile['passed'] and attribution['passed'], 'Completed measured inputs required')
    need(final['schema'] == 'FreeCAD-882-independent-final-profiling-review-v1'
         and final['passed'] is True and final['outstanding_findings'] == []
         and final['attribution_report'] == ref(ATTR), 'Final independent attribution review required')
    need(attribution['baseline_execution'] == ref(RUN / 'execution.json')
         and attribution['baseline_profile'] == ref(RUN / 'export-profile.json'), 'Attribution must bind this exact run')
    roles = {
        'setup_failure_execution': TASK / 'installed-profile-baseline-r01/execution.json',
        'setup_failure_classification': TASK / 'planning/baseline-setup-halt-review-r01.json',
        'restore_execution': TASK / 'restore-observation-r01/execution.json',
        'restore_probe': TASK / 'restore-observation-r01/restore-probe.json',
        'restore_bijection_amendment': TASK / 'planning/restore-bijection-benchmark-amendment-r01.json',
        'fixture_retention_custody': TASK / 'retained-synthetic-fixture-r01/retention-custody.json',
        'baseline_execution': RUN / 'execution.json', 'baseline_profile': RUN / 'export-profile.json',
        'attribution_opportunity_report': ATTR,
        'scope_clarification': TASK / 'planning/profiling-vs-implementation-scope-r01.json',
    }
    qualified = {
        'schema': 'FreeCAD-882-completed-profile-review-v1', 'passed': True,
        'scope': {'profiling_only': True, 'installation_performed': False,
            'implementation_performed': False, 'candidate_speedup_claimed': False,
            'new_build_or_physical_qualification_claimed': False,
            'Oomakhi_accessed_or_solved': False, 'engineering_or_BIM_accepted': False,
            'force_original_origin_moment_limit': .01, 'scalar_response_limit': .05},
        'roles': {name: ref(path) for name, path in roles.items()},
        'independent_final_review': ref(FINAL),
        'root_review': 'Root read the frozen profiling harness, actual completed receipts/caller data, relevant byte-matched implementation, full attribution and independent reviews. This PASS is the profiling deliverable only; publication still requires its own exact-byte audit.',
        'measurements': attribution['measurements'],
        'measured_source_HEAD': execution['source_HEAD'],
        'actual_installed_commit': execution['installed_commit'],
        'actual_installed_revision': execution['installed_revision'],
        'default_native_sha256': execution['candidate_sha256'],
        'observation': 'Repeated owned-reference geometry/mesh/group validation is the dominant profiled work. Cumulative descendants overlap, instrumentation overhead is included, and no achievable speedup is inferred.',
        'implementation_follow_up': {'id': 'FreeCAD-3q7', 'status': 'open',
            'title': 'FEM: amortize exact ownership validation within coupled export batches',
            'implemented_or_accepted': False},
        'quality_gates': {'actual_profile_tests_including_identity': 2,
            'skips': 0, 'completed_whole_public_write_calls': 1,
            'root_fixture_check_only': {'passed': True, 'input_files': 12, 'writes': 0},
            'root_fixture_retention': {'passed': True, 'input_files': 12, 'writes': 13},
            'product_functional_suites_or_build_rerun': False,
            'reason': 'No product source or application change; this is profiling/evidence only, not a product candidate.'},
        'replay': 'Exact synthetic saved fixture and historical/restored mesh bytes are retained. Frozen historical helper paths remain literal; replay needs a new explicit configuration and matching external FreeCAD/Pixi/native runtime.',
        'skill_influence': 'Measured before implementation inspection. Design review keeps recommended reuse behind a small private interface with explicit batch lifetime; it does not extend public configuration or retain writer state across request preparation.',
    }
    files = []

    def add(path, destination, classification, kind=None):
        path = Path(path)
        payload = data(path)
        if kind is None:
            kind = 'json' if path.suffix == '.json' else 'source' if path.suffix == '.py' else 'text'
        files.append({'path': str(path), 'destination': destination,
            'sha256': sha(payload), 'bytes': len(payload), 'kind': kind,
            'classification': classification})

    for folder, names, label in (
        ('installed-profile-baseline-r01', ('execution.json', 'manifest.json', 'identity.json', 'export-profile.json', 'run.log'), 'Failed pre-write QA setup; not product failure or export timing'),
        ('restore-observation-r01', ('execution.json', 'manifest.json', 'identity.json', 'restore-probe.json', 'run.log', 'restored-volume-connectivity.json'), 'Read-only restore observation; no export or physical qualification'),
        ('installed-profile-baseline-r02', ('execution.json', 'manifest.json', 'identity.json', 'export-profile.json', 'run.log', 'whole-public-write.prof', 'profile-cumulative.txt', 'native/Mesh.inp', 'native/Mesh.accounting', 'native/Mesh.accounting.json'), 'Completed exact whole-export profiling baseline; not a solve or speedup'),
    ):
        for name in names:
            add(TASK / folder / name, 'runs/' + folder + '/' + name, label,
                'profile-binary' if name.endswith('.prof') else None)
    common = ('AppYzkIdentity.py', 'B882Identity.py', 'B882Profile.py', 'critical_pins.py', 'harness_config.py', 'preservation.py', 'process_control.py')
    for folder, drivers in (('proposals', ('run_export_profile.py', 'run_export_profile_v2.py')),
                            ('restore-probe-r01', ('run_restore_probe.py',)),
                            ('profile-v4', ('run_export_profile_v2.py',))):
        for name in common + drivers:
            add(TASK / folder / name, 'qa/' + folder + '/' + name,
                'Exact run-pinned QA input; proposals/run_export_profile.py is a pinned unexecuted superseded driver')
    custody = parsed(roles['fixture_retention_custody'])
    need(len(custody['files']) == 12, 'Complete explicit capsule expected')
    for row in custody['files']:
        path = TASK / 'retained-synthetic-fixture-r01' / row['path']
        need(sha(data(path)) == row['sha256'] and len(data(path)) == row['bytes'], 'Capsule bytes differ')
        add(path, 'synthetic-fixture/' + row['path'], 'Exact narrowly approved generic software-QA replay input; historical physics is not transferred',
            'synthetic-fixture' if path.suffix == '.FCStd' else None)
    add(roles['fixture_retention_custody'], 'synthetic-fixture/retention-custody.json', 'Actual root retention after zero-write preflight')
    planning = ('accounting-provenance-coverage-map.json', 'active-baseline-identity-review-r01.json',
        'baseline-setup-halt-review-r01.json', 'existing-elastic-tie-behavior-coverage.json',
        'profile-v4-static-review-r01.json', 'profiling-vs-implementation-scope-r01.json',
        'restore-bijection-benchmark-amendment-r01.json', 'restore-probe-static-review-r01.json',
        'measured-source-cost-opportunities-r01.json', 'measured-source-cost-opportunities-r02.json',
        'profile-numeric-caller-review-r01.json', 'completed-profile-attribution-review-r01.json',
        'final-profiling-review-r01.json')
    for name in planning:
        add(TASK / 'planning' / name, 'reviews/' + name,
            'Exact scoped review; measured r01 is superseded only by explicit raw/canonical labeling in r02')
    for folder, name in (('proposals', 'evidence-acceptance-plan-r01.json'),
                         ('profile-v4', 'profile-plan-review.json'),
                         ('restore-probe-r01', 'restore-probe-review.json')):
        add(TASK / folder / name, 'reviews/' + folder + '/' + name,
            'Preserved method/static review; prospective implementation obligations clarified separately')
    for name in ('retain_fixture.py', 'collect_882.py', 'collect_882_v2.py',
                 'artifact-selection-proposal.json', 'collector-v2-binding-amendment.json',
                 'collector-static-review-v2.json', 'retention-requirements-review.json',
                 'prepare_publication_r01.py'):
        add(PLAN_DIR / name, 'collection/' + name,
            'Exact collection proposal/source/review; collect_882.py is superseded and unexecuted')
    app_fem = Path('/Applications/FreeCAD-27.1.0.app/Contents/Resources/Mod/Fem')
    need(len(attribution['source_bindings']) == 9, 'Nine inspected source bindings expected')
    for row in attribution['source_bindings']:
        path = Path(row['runtime_path'])
        need(path.is_relative_to(app_fem) and sha(data(path)) == row['sha256']
             and data(path) == data(Path(row['path'])), 'Measured source/runtime bytes differ')
        add(path, 'measured-source/' + str(path.relative_to(app_fem)),
            'Measured installed implementation, byte-equal to recorded source HEAD; read only after baseline')
    installer = REPO / 'package/local-completion/freecad-ywu-installation-evidence/private/stage_install.py'
    need(sha(data(installer)) == 'cca627502a56b6c9b4aefa4a970172c51e42e2dde834000decca65fd44ab46d9', 'Known preservation dependency differs')
    add(installer, 'qa/preservation-dependency/stage_install.py', 'Existing exact custody helper definitions only; no installation executed')
    write_new(REVIEW, qualified)
    add(REVIEW, 'completed-profile-review.json', 'Root completed profiling-only review; not product acceptance')
    need(len(files) == len({row['path'] for row in files}) == len({row['destination'] for row in files}), 'Unique explicit paths required')
    for path, payload in captured.items():
        need(path.read_bytes() == payload, 'Prepared input changed: ' + str(path))
    plan = {'schema': 'FreeCAD-882-approved-evidence-plan-v1', 'root_approved': True,
        'qualification_receipt': ref(REVIEW), 'files': files}
    write_new(PLAN, plan)
    print(json.dumps({'passed': True, 'files': len(files), 'qualification': ref(REVIEW),
        'plan': ref(PLAN), 'publication_performed': False}))


if __name__ == '__main__':
    main()
