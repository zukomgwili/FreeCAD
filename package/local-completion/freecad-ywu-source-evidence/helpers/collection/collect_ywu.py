"""Collect already-executed, source-only FreeCAD-ywu evidence; never run QA.

PREPARATION ONLY until the root agent has read this file and supplies final IDs.
Example (labels/commit/revision below are deliberately placeholders):
  python -B collection/collect_ywu.py --commit <40-hex> --revision '<revision>' \
    --final build=<label> --final ctest=<label> --final fem=<label> \
    --final gui=<label> --final native=<label> --final endload=<label> \
    --final ordinary=<label> --final cold-endload=<label> \
    --final cold-ordinary=<label> --final legacy-v1=<label> \
    --final legacy-v2=<label> --fixture-manifest collection/fixtures.json

The separate, root-approved fixture manifest is an explicit file allowlist:
  {"schema":"FreeCAD-ywu-approved-fixture-files-v1", "files":[
    {"path":"<label>/witness/native/Mesh.inp", "sha256":"<64-hex>",
     "fixture":"end-only-beams", "role":"unaltered native solver input"}]}
Paths are relative to the private root, not inferred from arbitrary JSON links.
Only named historical/final runs and the four declared generic fixture families
are eligible. Private inventories, profiles, caches, environment files, runtime
binaries and vendor build trees are never copied. Receipt excerpts are labelled
as derived; historical failures and pre-final identities are never repaired.

This producer writes ONLY the two NEW repository destinations below, on explicit
main invocation. Original evidence, application and dependency files are read
only. It imports no gate or product module and starts no subprocess of any kind.
"""

import argparse
import ast
import datetime
import gzip
import hashlib
import itertools
import json
import math
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
BUILD = REPO / 'build/release'
DEST = REPO / 'package/local-completion/freecad-ywu-source-evidence'
VALIDATION = REPO / 'package/local-completion/freecad-ywu-validation.json'
GZIP_THRESHOLD = 64 * 1024
NATIVE_SHA = '2d59adb06736801f730de077a5f3dbfcfba8c0a430636e5814e5582606b5c89b'
NATIVE_C_SHA = 'fb35ca4fe0ccd6f1ed1e88439c20926092a06ca32f5c21eb6c9739e52fd0dc5a'
HOOKS_SHA = '28bcdb6d042b45db26c817dbb39bc04bb298c0f9a0d717fc9c1a639d0bba15ea'
DEPENDENCY_MANIFEST_SHA = {
    'pixi.toml': '119ea10b858e6926f16a014b3245b3f301a3624500bf6b5b8c6c98010c55352b',
    'pixi.lock': '730693309df0ef3afd2c35ea7becf1dc4cd097bfd4b287a459449ca1a1b81ad7',
}
FROZEN = {
    'oracle.json': 'c31fe65e7b8e1d5d742a380e746a7da97dedffdebc80749f59dd3e3d9bbe38ad',
    'endload-oracle.json': 'd1e436011bbd452ec39453a1c61b7466b6ec7a1bef657d7c8bc1da819114660b',
    'ordinary-oracle.json': 'c8fa248d41273d3d829222c9f57cdcbc6cdf384f7077b34010eab94fd48a77c7',
    'oracle-spec-proposal.json': '8c7ecc8e52dba80b223b94b5b19af9dfb19f4b5a0e33b73aceb117e12fe69dd7',
    'posthoc-oracle-audit.json': 'b49ed0c7bdcd9e410b68351599d30014b1c16ca17a890ee023400e220d11d390',
    'endload-posthoc-audit.json': '32b2cac268fa34726f4d03a35c412f836c539931b1e5ab389566590137963957',
    'ordinary-posthoc-audit.json': 'f4c34debfa277203eeb0f6cadb41e694d13d97cc759613552b96765fe1a845d8',
}
HISTORY = (
    'installed-red-r01', 'installed-legacy-control-r01',
    'native-v3-r01', 'native-v3-r02',
    'configure-v3-r01', 'configure-v3-r02', 'configure-v3-r03',
    'source-build-v3-r01', 'source-lifecycle-build-r02',
    'source-support-build-r03', 'source-registered-build-r04',
    'source-overlap-build-r05', 'source-negative-observer-build-r06',
    'source-review-build-r07', 'source-moving-r01', 'source-endload-r01',
    'source-endload-diagnostic-r02', 'source-endload-r03',
    'source-endload-cold-r01', 'source-endload-cold-r02',
    'source-endload-cold-r03', 'source-ordinary-cold-r01', 'ctest-r01',
    'source-ordinary-red-r01', 'source-ordinary-red-r02',
    'source-ordinary-green-r01', 'source-rbe-ordinary-overlap-red-r01',
    'source-rbe-ordinary-overlap-green-r01',
    'source-registered-native-r01', 'source-registered-native-r02',
    'full-fem-app-r01', 'full-fem-gui-r01', 'legacy-v1-r01', 'legacy-v2-r01',
)
HELPERS = (
    'AppNativeIdentity.py', 'SourceYwuIdentity.py', 'YwuColdRestore.py',
    'YwuEndLoadGreen.py', 'YwuLegacyFixedPorts.py', 'YwuMovingPortGreen.py',
    'YwuMovingPortWitness.py', 'YwuOrdinaryGreen.py', 'YwuOrdinarySupports.py',
    'YwuSupportOverlap.py', 'harness_config.py', 'process_control.py',
    'run_builds.py', 'run_full_build.py', 'run_legacy_installed.py',
    'run_legacy_v1.py', 'run_source.py', 'run_ywu.py',
)
RUN_FILES = (
    'execution.json', 'run.log', 'identity.json', 'cold-receipt.json',
    'overlap-receipt.json', 'ordinary-receipt.json',
    'qualification.json', 'summary.json', 'manifest.json',
    'witness/witness-receipt.json', 'witness/cold-case.json',
    'witness/native-properties.json', 'witness/native-properties-off.json',
    'witness/native-properties-on.json', 'witness/mesh-membership.json',
    'witness/native-accounting-data.json', 'witness/motion-from-stock-dat.json',
    'witness/stock-boundary-request-binding.json',
    'witness/stock-imported-results.json', 'witness/accounting-on-exception.json',
)
NATIVE_BUILD_FILES = (
    'execution.json', 'run.log', 'native/build-receipt.json',
    'native/build.log', 'native/functional-tests.log', 'native/accounting-patch.log',
)
SOURCE_FILES = (
    'package/calculix/force-accounting/forceaccounting.c',
    'package/calculix/force-accounting/hooks.patch',
    'package/calculix/force-accounting/contract.json',
    'package/calculix/force-accounting/COPYING',
    'src/Mod/Fem/CMakeLists.txt', 'src/Mod/Fem/TestFemApp.py',
    'src/Mod/Fem/femobjects/solver_ccxtools.py',
    'src/Mod/Fem/femresult/contact_observation_source.py',
    'src/Mod/Fem/femsolver/calculix/write_constraint_elastic_connector.py',
    'src/Mod/Fem/femtest/app/test_moving_port_accounting_native.py',
    'src/Mod/Fem/femtest/app/test_tie_accounting_native.py',
    'src/Mod/Fem/femtools/force_accounting.py',
)
V2_CASES = (
    'tie-tet4', 'tie-tet10', 'equation-unit-tet4',
    'equation-negative-scale-reverse-tet4', 'equation-quarter-scale-tet10',
    'equation-chain-reverse-tet4', 'tie-dependent-point-tet4',
    'equation-chain-dependent-point-tet10',
    'reject-shared-cut-mpc-tet4', 'reject-body-spc-tet4',
)
V1_REJECTIONS = ('nlgeom', 'missing-cut-node', 'duplicate-support',
                 'oversized-integer', 'cut-point-load', 'cut-mpc')
FIXTURES = {'original-sideface-beams', 'end-only-beams',
            'ordinary-support-beams', 'overlap-export-negative'}
FIXTURE_SUFFIXES = {'.FCStd', '.frd', '.inp', '.accounting', '.out', '.dat',
                    '.json', '.stdout', '.stderr'}
FORBIDDEN_NAMES = {'private-custody-before.json', 'private-baseline.json',
                   'environment.log', '.env', 'user.cfg', 'system.cfg'}
FORBIDDEN_PARTS = {'__pycache__', 'CalculiX', '.pixi', '.git', 'profiles',
                   'freecad_user_home', 'freecad_user_data', 'freecad_user_temp',
                   'xdg_config_home', 'xdg_data_home', 'xdg_cache_home'}
INVENTORY_KEYS = {'app_before', 'app_after', 'critical_before', 'critical_after',
                  'private_custody_before', 'private_baseline', 'inventory',
                  'app_inventory', 'application_inventory', 'profile_inventory',
                  'profile_inventories', 'profiles', 'prior_ctest_logs',
                  'ctest_logs_after'}
SECRET_KEYS = {'password', 'api_key', 'apikey', 'secret', 'authorization',
               'cookie', 'access_token', 'refresh_token', 'environment', 'environ'}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def raw(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), f'Not a regular file: {path}')
    return path.read_bytes()


def file_sha(path):
    return sha(raw(path))


def load(path):
    return json.loads(raw(path))


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()


def safe_relative(value):
    path = Path(value)
    require(not path.is_absolute() and path.parts and
            all(part not in ('', '.', '..') for part in path.parts), f'Unsafe path: {value}')
    require(not any(part in FORBIDDEN_PARTS for part in path.parts), f'Private path: {value}')
    require(path.name not in FORBIDDEN_NAMES and path.suffix.lower() not in
            {'.cfg', '.pyc', '.pyo', '.so', '.dylib', '.exe', '.o', '.a'},
            f'Excluded file: {value}')
    return path


def root_file(relative):
    rel = safe_relative(relative)
    path = ROOT / rel
    require(not path.is_symlink(), f'Input is a link: {relative}')
    require(path.resolve().is_relative_to(ROOT.resolve()), f'Escaped private root: {relative}')
    parent = path.parent
    while parent != ROOT:
        require(not parent.is_symlink(), f'Parent is a link: {path}')
        parent = parent.parent
    return path


def private_json(value, location):
    if isinstance(value, dict):
        require(not SECRET_KEYS.intersection(str(k).lower() for k in value),
                f'Environment/secret dictionary in {location}')
        require(not INVENTORY_KEYS.intersection(value), f'Nested inventory in {location}')
        for item in value.values():
            private_json(item, location)
    elif isinstance(value, list):
        for item in value:
            private_json(item, location)


class Archive:
    def __init__(self):
        self.pending = {}
        self.sources = {}
        self.records = []

    def add(self, path, destination, classification, *, receipt=False):
        path = Path(path)
        if path.is_relative_to(ROOT):
            require(root_file(path.relative_to(ROOT)) == path, 'Unsafe private input')
        original = raw(path)
        require(original[:4] not in (b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf',
                b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xce', b'\x7fELF',
                b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca', b'\xca\xfe\xba\xbf',
                b'\xbf\xba\xfe\xca') and not original.startswith(b'MZ'),
                f'Runtime binary: {path}')
        require(len(original) <= 32 * 1024 * 1024, f'Oversized evidence file: {path}')
        if path.suffix != '.FCStd':
            text = original.decode('utf-8')
            require(b'\x00' not in original, f'Non-text runtime payload: {path}')
            require(not re.search(r'(?im)^(?:OPENAI_API_KEY|AWS_SECRET_ACCESS_KEY|'
                r'GITHUB_TOKEN|GH_TOKEN|ACCESS_TOKEN|REFRESH_TOKEN|PASSWORD)\s*=\s*\S+', text),
                f'Secret-bearing environment dump: {path}')
        else:
            require(original.startswith(b'PK\x03\x04'), f'Invalid generic FCStd archive: {path}')
        omitted = []
        data = original
        if path.suffix == '.json':
            obj = json.loads(original)
            if receipt and isinstance(obj, dict):
                omitted = sorted(INVENTORY_KEYS.intersection(obj))
                if omitted:
                    facts = {k: v for k, v in obj.items() if k not in omitted}
                    private_json(facts, path)
                    data = encoded({'schema': 'FreeCAD-ywu-curated-receipt-excerpt-v1',
                        'transformation': 'Inventory bodies omitted; retained facts are copied, not a new independent audit.',
                        'original_private_receipt': {'path': str(path),
                            'sha256': sha(original), 'bytes': len(original)},
                        'omitted_top_level_fields': omitted, 'facts': facts})
                else:
                    private_json(obj, path)
            else:
                private_json(obj, path)
        if path.suffix == '.py':
            ast.parse(original)
        rel = safe_relative(destination)
        compression = 'identity'
        stored = data
        if len(data) >= GZIP_THRESHOLD and path.suffix != '.FCStd':
            compression = 'gzip'
            stored = gzip.compress(data, mtime=0)
            rel = Path(str(rel) + '.gz')
        key = str(rel)
        require(key not in self.pending, f'Duplicate archive path: {key}')
        self.pending[key] = stored
        self.sources[str(path)] = sha(original)
        self.records.append({'file': key, 'classification': classification,
            'original_path': str(path), 'original_sha256': sha(original),
            'original_bytes': len(original), 'stored_sha256': sha(stored),
            'stored_bytes': len(stored), 'encoding': compression,
            'uncompressed_sha256': sha(data), 'uncompressed_bytes': len(data),
            'transformation': 'explicit curated JSON excerpt' if omitted else 'exact bytes',
            'omitted_top_level_fields': omitted})

    def check_unchanged(self):
        for path, wanted in self.sources.items():
            require(file_sha(path) == wanted, f'Original changed during collection: {path}')


def passed_execution(label):
    directory = root_file(label)
    receipt = load(directory / 'execution.json')
    require(receipt.get('passed') is True, f'Final gate did not pass: {label}')
    require(not receipt.get('timed_out'), f'Timed-out final gate: {label}')
    code = receipt.get('returncode', receipt.get('exit_code'))
    require(code == 0, f'Nonzero final gate: {label}')
    require(receipt.get('child_reaped', receipt.get('process_reaped')) is True and
            receipt.get('process_group_gone', receipt.get('owned_group_gone')) is True,
            f'Unreaped final gate: {label}')
    require(file_sha(directory / 'run.log') == receipt['log_sha256'], f'Changed log: {label}')
    for flag in ('source_build_harness_unchanged', 'source_and_supervisor_unchanged',
                 'app_and_profiles_unchanged'):
        if flag in receipt:
            require(receipt[flag] is True, f'Final custody failed: {label}: {flag}')
    for before, after in (('inputs_before', 'inputs_after'), ('source_before', 'source_after')):
        if before in receipt:
            require(receipt[before] == receipt[after], f'Final input fence changed: {label}')
    return receipt


def current_files(mapping):
    for path, wanted in mapping.items():
        require(file_sha(path) == wanted, f'Final recorded input changed: {path}')


def final_identity(label, receipt, commit, revision):
    path = root_file(label) / 'identity.json'
    identity = load(path)
    require(identity.get('passed') is True and file_sha(path) == receipt['identity_sha256'],
            f'Invalid identity receipt: {label}')
    runtime = identity['runtime']
    require(runtime[-1] == commit and runtime[3] == revision, f'Pre-final runtime: {label}')
    candidate = identity['candidate']
    require(candidate == {'path': str(BUILD / 'data/NativeSolvers/ccx-force-accounting'),
            'sha256': NATIVE_SHA, 'capability': 'CCX_FORCE_ACCOUNTING_V3', 'override': False},
            f'Final native solver differs: {label}')
    current_files(receipt['inputs_after'])
    return identity


def unittest_count(receipt, label):
    counts = receipt['unittest_counts']
    require(len(counts) == 1 and not receipt['skipped_lines'], f'Missing/skipped tests: {label}')
    text = raw(root_file(label) / 'run.log').decode()
    require(re.search(r'^OK\s*$', text, re.M) and not re.search(
        r'^(FAILED\b|FAIL:|ERROR:|UNEXPECTED SUCCESS:)', text, re.M), f'Failed unittest: {label}')
    return int(counts[0][0]), float(counts[0][1])


def native_test_ids():
    path = REPO / 'src/Mod/Fem/femtest/app/test_moving_port_accounting_native.py'
    tree = ast.parse(raw(path))
    result = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for method in node.body:
                if isinstance(method, ast.FunctionDef) and method.name.startswith('test_'):
                    result.append('femtest.app.test_moving_port_accounting_native.' +
                                  node.name + '.' + method.name)
    require(result and len(result) == len(set(result)), 'No unique native test methods')
    return result


def log_native_ids(label, expected):
    text = raw(root_file(label) / 'run.log').decode()
    for test_id in expected:
        # unittest prints a method's docstring on the following line when it
        # exists. Bind the exact unique ID at line start; the surrounding gate
        # separately requires the complete normal OK/count and zero skips.
        pattern = '^' + re.escape(test_id.rsplit('.', 1)[-1]) + r' \(' + re.escape(test_id) + r'\)([^\n]*)$'
        hits = re.findall(pattern, text, re.M)
        require(len(hits) == 1 and 'skipped' not in hits[0], f'Native method not executed: {test_id}')


def validate_final(labels, commit, revision, fixture_files):
    results = {}
    header = raw(BUILD / 'src/Build/Version.h').decode()
    macros = dict(re.findall(r'^#define\s+(\w+)\s+"([^"]*)"', header, re.M))
    require(macros['FCRepositoryHash'] == commit and macros['FCRevision'] == revision,
            'Final compiled header differs from root-supplied identity')
    require(file_sha(BUILD / 'data/NativeSolvers/ccx-force-accounting') == NATIVE_SHA,
            'Final copied native binary differs')
    expected_ids = native_test_ids()
    witnesses = {}
    for role, label in labels.items():
        if role.startswith('legacy-'):
            continue
        receipt = passed_execution(label)
        if role in ('build', 'ctest'):
            require(receipt['mode'] == role, f'Incorrect gate mode: {role}')
            require(receipt['source_after']['git_head'] == commit and
                    receipt['build_after']['version_header']['FCRepositoryHash'] == commit and
                    receipt['build_after']['version_header']['FCRevision'] == revision,
                    f'Pre-final committed build: {role}')
            current_files(receipt['source_after']['files'])
            current_files(receipt['build_after']['files'])
            require(receipt.get('installation_performed') is False, 'Unexpected installation')
            if role == 'ctest':
                ct = receipt['ctest']
                require(ct['complete_catalogue_verified'] and ct['failed'] == 0 and
                        ct['catalogue'] == ct['executed_passing'] + ct['skipped'] + ct['disabled'],
                        'Incomplete CTest catalogue')
                results[role] = ct
            else:
                results[role] = {'passed': True, 'seconds': receipt['elapsed_seconds']}
            continue
        identity = final_identity(label, receipt, commit, revision)
        require(receipt.get('app_and_profiles_unchanged') is True and
                receipt.get('source_build_harness_unchanged') is True,
                'Final app/profile or source input custody not established')
        count, seconds = unittest_count(receipt, label)
        results[role] = {'passed': True, 'executed_including_identity': count,
                         'seconds': seconds, 'skipped': 0, 'runtime': identity['runtime']}
        if role in ('fem', 'gui'):
            field = 'TestFemApp_count' if role == 'fem' else 'TestFemGui_count'
            require(count == identity[field] + 1, f'Discovered/executed count mismatch: {role}')
            require(bool(identity['gui_up']) == (role == 'gui'), 'Incorrect GUI identity')
            results[role]['public_tests'] = identity[field]
        if role in ('fem', 'native'):
            log_native_ids(label, expected_ids)
            results[role]['native_methods_executed_without_skips'] = len(expected_ids)
            if role == 'native':
                require(count == len(expected_ids) + 1, 'Incomplete native-only suite')
        if role in ('endload', 'ordinary'):
            witness = load(root_file(label) / 'witness/witness-receipt.json')
            require(witness['passed'] and witness['actual_binary_sha256'] == NATIVE_SHA and
                    witness['solver_returncode'] == 0 and witness['no_deck_patches_or_mocks'] and
                    witness['only_public_native_interfaces'] and not witness['Oomakhi_opened_or_solved'],
                    f'Unqualified native witness: {role}')
            oracle_name = 'endload-oracle.json' if role == 'endload' else 'ordinary-oracle.json'
            oracle_hash = witness.get('frozen_independent_oracle_sha256', witness.get('oracle_sha256'))
            require(oracle_hash == FROZEN[oracle_name], 'Witness oracle changed')
            checks = witness['checks']
            require(checks and all(c['passed'] and c['limit'] == 0.01 and
                math.isfinite(c['relative_error']) and c['relative_error'] <= 0.01 for c in checks),
                'Frozen force/original-origin moment limit failed')
            results[role]['checks'] = len(checks)
            results[role]['maximum_normalized_error'] = max(c['relative_error'] for c in checks)
            manifest = Path(witness['cold_manifest'])
            require(manifest == root_file(label) / 'witness/cold-case.json' and
                    file_sha(manifest) == witness['cold_manifest_sha256'], 'Wrong fresh cold manifest')
            case = load(manifest)
            require(case['schema'] == 'FreeCAD-ywu-native-cold-case-v1' and
                    case['binary_sha256'] == NATIVE_SHA, 'Wrong cold fixture schema/candidate')
            required_files = [(Path(case['document']), case['document_sha256'])]
            required_files += [(Path(row['path']), row['sha256']) for row in case['source_files'].values()]
            for path, wanted in required_files:
                require(path.is_relative_to(ROOT / label) and file_sha(path) == wanted,
                        'Cold artifact is not this fresh generic witness')
                require(str(path.relative_to(ROOT)) in fixture_files and
                        fixture_files[str(path.relative_to(ROOT))]['sha256'] == wanted,
                        f'Required native fixture absent from explicit allowlist: {path}')
            witnesses[str(manifest)] = witness['cold_manifest_sha256']
        if role.startswith('cold'):
            cold = load(root_file(label) / 'cold-receipt.json')
            require(cold['passed'] and cold['no_native_solve'] and
                    cold['no_history_or_provenance_repair'] and cold['status'].startswith('Stale'),
                    'Cold restore promoted/repaired history or reran solver')
            results[role]['manifest'] = cold['manifest']
            results[role]['manifest_sha256'] = cold['manifest_sha256']
            results[role]['status'] = cold['status']
    for role, result in results.items():
        if role.startswith('cold'):
            require(witnesses.get(result['manifest']) == result['manifest_sha256'],
                    'Cold restore is not bound to a selected final native witness')
    results['native_method_ids'] = expected_ids
    return results


def validate_legacy(labels):
    result = {}
    for role in ('legacy-v1', 'legacy-v2'):
        directory = root_file(labels[role])
        name = 'qualification.json' if role == 'legacy-v1' else 'summary.json'
        summary = load(directory / name)
        require(summary.get('binary_sha256', summary.get('candidate_sha256')) == NATIVE_SHA,
                'Legacy native candidate differs')
        if role == 'legacy-v1':
            require(summary['passed'] and summary['schema'] == 'CCX_FORCE_ACCOUNTING_V1', 'Legacy V1 failed')
            cases = summary['analytic_cases']
            wanted = {f't{t}-q{q}-r{r}-s{s}/{side}-upper'
                for t, q, r, s, side in itertools.product((1, 2, 4), (0, 1), (0, 1), (0, 1), ('slave', 'master'))}
            require({row['case'] for row in cases} == wanted and len(cases) == len(wanted), 'V1 corpus incomplete')
            require(tuple(row['case'] for row in summary['rejections']) == V1_REJECTIONS,
                    'V1 refusal corpus incomplete')
            for row in cases + summary['rejections']:
                case = directory / row['case']
                require(load(case / 'execution.json') == row, 'V1 retained execution/summary mismatch')
                require(row['passed'] and row['child_reaped'] and row['reaped'] and
                        row['process_group_gone'] and not row['timed_out'] and
                        row['inputs_unchanged'] and row['protected_unchanged'] and row['manifest_unchanged'],
                        'V1 execution/custody did not pass')
                require(row['inputs_before'] == row['inputs_after'] and
                        row['protected_before'] == row['protected_after'], 'V1 input fences changed')
                require(row['protected_before'][str(REPO / SOURCE_FILES[0])] == NATIVE_C_SHA and
                        row['protected_before'][str(REPO / SOURCE_FILES[1])] == HOOKS_SHA and
                        row['protected_before'][str(BUILD / 'data/NativeSolvers/ccx-force-accounting')] == NATIVE_SHA,
                        'V1 standalone native C/hooks/candidate pins differ')
                for filename, wanted_sha in row['inputs_after'].items():
                    require(filename in {'contact.inp', 'contact.accounting', 'oracle.json'} and
                            file_sha(case / filename) == wanted_sha, 'V1 native input changed')
                require(file_sha(case / 'solver.log') == row['log_sha256'], 'V1 solver log changed')
                for filename, wanted_sha in row['outputs'].items():
                    require(filename in {'contact.dat', 'contact.frd', 'contact.accounting.out',
                        'contact.cvg', 'spooles.out', 'contact.12d', 'contact.sta', 'solver.log'} and
                        file_sha(case / filename) == wanted_sha, 'V1 native output changed')
            for row in cases:
                case = directory / row['case']
                require(row['positive'] and row['returncode'] == 0, 'V1 positive run did not succeed')
                require(row['physical_norm_checks'] == sum(len(pair)
                    for pair in row['relative_force_moment_errors'].values()),
                    'V1 force/moment check count differs from retained vectors')
                require(raw(case / 'contact.accounting.out').startswith(b'CCX_FORCE_ACCOUNTING_V1'),
                        'Literal legacy V1 output changed schema')
                require(all(math.isfinite(x) and 0 <= x <= .01
                    for pair in row['relative_force_moment_errors'].values() for x in pair), 'V1 fixed limit failed')
            for row in summary['rejections']:
                require(not row['positive'] and row['returncode'] == 201 and
                        not row['complete_accounting_envelope'], 'V1 explicit refusal failed')
                require(row['diagnostic'] in raw(directory / row['case'] / 'solver.log').decode(),
                        'V1 refusal diagnostic missing')
            result[role] = {'passed': True, 'positive_cases': len(cases),
                            'explicit_refusals': len(summary['rejections']),
                            'force_moment_checks': sum(row['physical_norm_checks'] for row in cases)}
        else:
            require(summary['all_selected_passed'] and tuple(summary['selected_cases']) == V2_CASES,
                    'V2 corpus incomplete')
            require(tuple(row['case'] for row in summary['reports']) == V2_CASES,
                    'V2 report corpus differs from selected cases')
            checks = []
            for row in summary['reports']:
                require(row['passed'] and row['candidate_sha256'] == NATIVE_SHA and
                        row['protected_inputs_unchanged'] and row['child_reaped'] and
                        row['process_group_gone'] and not row['timed_out'], 'V2 child failed/custody changed')
                require(load(directory / row['case'] / 'execution.json') == row, 'V2 summary/case mismatch')
                require(file_sha(directory / row['case'] / 'solver.log') == row['solver_log_sha256'], 'V2 log changed')
                require(row['custody_before'] == row['custody_after'], 'V2 recorded custody changed')
                require(file_sha(directory / row['case'] / 'contact.inp') == row['custody_before']['deck'] and
                        file_sha(directory / row['case'] / 'contact.accounting') == row['custody_before']['request'],
                        'V2 native input differs from child custody hashes')
                if row.get('checks'):
                    native_output = directory / row['case'] / 'contact.accounting.out'
                    require(row['returncode'] == 0 and file_sha(native_output) == row['native_output_sha256'] and
                        raw(native_output).startswith(b'CCX_FORCE_ACCOUNTING_V2'),
                        'Literal legacy V2 output changed schema or run failed')
                else:
                    require(row['returncode'] == 201 and row.get('expected_domain_refusal'),
                            'V2 explicit refusal not established')
                checks += row.get('checks', [])
            require(len(checks) == 144 and all(c['passed'] and c['limit'] == .01 and
                    math.isfinite(c['relative_error']) and c['relative_error'] <= .01 for c in checks), 'V2 fixed limit failed')
            result[role] = {'passed': True, 'positive_cases': sum(bool(r.get('checks')) for r in summary['reports']),
                            'explicit_refusals': sum(bool(r.get('expected_domain_refusal')) for r in summary['reports']),
                            'force_moment_checks': len(checks)}
    return result


def collect_run(archive, label, classification):
    directory = root_file(label)
    for filename in RUN_FILES:
        path = directory / filename
        if path.is_file():
            archive.add(path, f'runs/{label}/{filename}', classification, receipt=path.suffix == '.json')
    for name in HELPERS:
        path = directory / 'executed-scripts' / name
        if path.is_file():
            archive.add(path, f'helpers/retained/{label}/{name}',
                'Retained historical helper bytes; execution binding is recorded separately, not inferred from filename.')


def historical_helper_gaps(label):
    """Disclose recorded old helper hashes unavailable as exact retained bytes."""
    path = ROOT / label / 'execution.json'
    if not path.is_file():
        return []
    receipt = load(path)
    maps = []
    for key in ('inputs_before', 'source_before', 'protected_before'):
        value = receipt.get(key, {})
        if isinstance(value, dict):
            maps.append(value.get('files', value))
    gaps = []
    for mapping in maps:
        for recorded, wanted in mapping.items():
            original = Path(recorded)
            if original.parent != ROOT or original.suffix != '.py' or not isinstance(wanted, str):
                continue
            retained = ROOT / label / 'executed-scripts' / original.name
            if original.name in HELPERS and original.is_file() and file_sha(original) == wanted:
                continue
            if original.name in HELPERS and retained.is_file() and file_sha(retained) == wanted:
                continue
            gaps.append({'recorded_path': recorded, 'recorded_sha256': wanted,
                'status': 'Exact earlier helper bytes not retained; current snapshot is not represented as this execution.'})
    return gaps


def helper_input_hashes(labels):
    """Hashes show an input fence, not proof every helper was imported/run."""
    result = set()
    for label in labels:
        path = ROOT / label / 'execution.json'
        if not path.is_file():
            continue
        receipt = load(path)
        for key in ('inputs_before', 'source_before', 'protected_before'):
            value = receipt.get(key, {})
            if not isinstance(value, dict):
                continue
            mapping = value.get('files', value)
            for path, wanted in mapping.items():
                if isinstance(wanted, str):
                    result.add((path, wanted))
    return result


def collect_legacy(archive, role, label):
    directory = root_file(label)
    files = ('execution.json', 'solver.log', 'oracle.json', 'qualification.json',
             'contact.inp', 'contact.accounting', 'contact.accounting.out')
    if role == 'legacy-v1':
        cases = [f't{t}-q{q}-r{r}-s{s}/{side}-upper'
            for t, q, r, s, side in itertools.product((1, 2, 4), (0, 1), (0, 1), (0, 1), ('slave', 'master'))]
        cases += list(V1_REJECTIONS)
        tops = ('qualification.json',)
    else:
        cases, tops = list(V2_CASES), ('summary.json', 'manifest.json')
    for name in tops:
        archive.add(directory / name, f'legacy/{role}/{label}/{name}', 'Final native candidate legacy wire-contract regression.', receipt=True)
    for case in cases:
        for filename in files:
            path = directory / case / filename
            if path.is_file():
                archive.add(path, f'legacy/{role}/{label}/{case}/{filename}',
                            'Explicit synthetic legacy case; not a building/engineering result.', receipt=path.suffix == '.json')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--final', action='append', required=True, metavar='ROLE=LABEL')
    parser.add_argument('--fixture-manifest', type=Path, required=True)
    parser.add_argument('--native-build-label', default='native-v3-r02')
    parser.add_argument('--history-label', action='append', default=[], metavar='LABEL')
    parser.add_argument('--review', action='append', default=[], metavar='RELATIVE_JSON=SHA256',
                        help='Root-captured independent review JSON with an explicit immutable SHA')
    parser.add_argument('--check-only', action='store_true',
                        help='Validate all selected evidence and prepare the byte plan in memory; write nothing')
    args = parser.parse_args()
    require(re.fullmatch(r'[0-9a-f]{40}', args.commit), 'Full final commit required')
    require(re.fullmatch(r'\d+ \+\d+ \(Git\)', args.revision), 'Exact final compiled revision required')
    labels = {}
    allowed_roles = {'build', 'ctest', 'fem', 'gui', 'native', 'endload', 'ordinary',
                     'cold', 'cold-endload', 'cold-ordinary', 'legacy-v1', 'legacy-v2'}
    for item in args.final:
        role, separator, label = item.partition('=')
        require(separator and role in allowed_roles and role not in labels and
                re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', label), 'Invalid/duplicate final role or label')
        labels[role] = label
    require({'build', 'ctest', 'fem', 'gui', 'native', 'endload', 'ordinary',
             'legacy-v1', 'legacy-v2'}.issubset(labels) and
            any(role.startswith('cold') for role in labels), 'Incomplete final role set')
    require(len(set(labels.values())) == len(labels), 'Final roles must have distinct executions')
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', args.native_build_label), 'Unsafe native build label')
    require(not DEST.exists() and not DEST.is_symlink() and not VALIDATION.exists() and
            not VALIDATION.is_symlink(), 'New destinations already exist; never overwrite evidence')
    require(DEST.parent.is_dir() and not DEST.parent.is_symlink(), 'Unsafe evidence parent directory')
    fixture_manifest = args.fixture_manifest.resolve(strict=True)
    require(fixture_manifest.is_relative_to(ROOT / 'collection'), 'Fixture allowlist must be root-approved inside collection/')
    manifest = load(fixture_manifest)
    require(manifest['schema'] == 'FreeCAD-ywu-approved-fixture-files-v1', 'Wrong explicit fixture allowlist schema')
    require(all(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', label)
                for label in args.history_label), 'Unsafe additional history label')
    history_labels = tuple(dict.fromkeys(HISTORY + tuple(args.history_label)))
    selected = set(history_labels) | set(labels.values()) | {args.native_build_label}
    review_files = []
    for item in args.review:
        relative, separator, wanted = item.rpartition('=')
        require(separator and Path(relative).suffix == '.json' and
                re.fullmatch(r'[0-9a-f]{64}', wanted), 'Invalid captured review declaration')
        path = root_file(relative)
        require(file_sha(path) == wanted, 'Captured independent review changed')
        private_json(load(path), path)
        review_files.append({'path': path, 'relative': relative, 'sha256': wanted})
    fixture_files = {}
    for row in manifest['files']:
        require(set(row) == {'path', 'sha256', 'fixture', 'role'} and row['fixture'] in FIXTURES and
                isinstance(row['role'], str) and row['role'], 'Invalid explicit fixture entry')
        rel = safe_relative(row['path'])
        require(len(rel.parts) >= 3 and rel.parts[0] in selected and
                rel.parts[1] in {'witness', 'export', 'native', 'stock-off', 'accounting-on'} and
                rel.suffix in FIXTURE_SUFFIXES, 'Fixture path not in approved generic run namespace')
        require(row['path'] not in fixture_files and re.fullmatch(r'[0-9a-f]{64}', row['sha256']), 'Duplicate/invalid fixture SHA')
        require(file_sha(root_file(rel)) == row['sha256'], 'Approved fixture changed')
        fixture_files[row['path']] = row
    for name, wanted in FROZEN.items():
        require(file_sha(ROOT / name) == wanted, f'Frozen oracle/audit changed: {name}')
    for name, wanted in DEPENDENCY_MANIFEST_SHA.items():
        require(file_sha(REPO / name) == wanted, f'Protected dependency manifest changed: {name}')
    # The original side-loaded fixture was NOT rewritten when the separate
    # end-load and ordinary-support numerical benchmarks were introduced.
    original_inputs = load(ROOT / 'posthoc-oracle-audit.json')['inputs']
    for row in original_inputs:
        path = Path(row['path'])
        require(path.is_relative_to(ROOT) and file_sha(root_file(path.relative_to(ROOT))) == row['sha256'],
                'Original side-loaded fixture input was rewritten')
    require(file_sha(REPO / SOURCE_FILES[0]) == NATIVE_C_SHA and
            file_sha(REPO / SOURCE_FILES[1]) == HOOKS_SHA, 'Qualified native source changed')
    results = validate_final(labels, args.commit, args.revision, fixture_files)
    results.update(validate_legacy(labels))
    build_receipt = load(root_file(args.native_build_label) / 'native/build-receipt.json')
    require(build_receipt['channel'] == 'CCX_FORCE_ACCOUNTING_V3' and
            build_receipt['binary_sha256'] == NATIVE_SHA and
            build_receipt['extra_source_sha256'] == NATIVE_C_SHA and
            build_receipt['probe_patch_sha256'] == HOOKS_SHA and
            build_receipt['dependency_functional_tests_passed'] and not build_receipt['installed'],
            'Native build receipt differs from qualified source/candidate')
    archive = Archive()
    archive.add(Path(__file__), 'helpers/collection/collect_ywu.py', 'Collection producer, not a native/test execution helper.')
    archive.add(fixture_manifest, 'approved-fixture-files.json', 'Root-approved explicit generic fixture allowlist.')
    for name in FROZEN:
        archive.add(ROOT / name, 'oracles/' + name,
            'Immutable predeclared oracle/proposal or explicitly post-hoc independent audit; scope literal preserved.')
    for row in review_files:
        archive.add(row['path'], 'captured-reviews/' + row['relative'],
            'Root-captured independent source/spec review; not an engineering or native qualification.', receipt=True)
    helper_fences = helper_input_hashes(selected)
    omitted_helpers = []
    for name in HELPERS:
        path = ROOT / name
        if path.is_file() and (str(path), file_sha(path)) in helper_fences:
            archive.add(path, 'helpers/current/' + name,
                'Actual current helper bytes present in a recorded input fence; not proof of import/execution or byte identity to earlier runs.')
        else:
            omitted_helpers.append({'name': name,
                'reason': 'No existing current file with a matching selected-run input fence; no file invented or substituted.'})
    history = []
    for label in history_labels:
        if label in labels.values() or not (ROOT / label).is_dir():
            continue
        collect_run(archive, label, 'Historical/pre-final attempt only; not a final source qualification gate.')
        path = ROOT / label / 'execution.json'
        if path.is_file():
            receipt = load(path)
            identity = load(ROOT / label / 'identity.json') if (ROOT / label / 'identity.json').is_file() else {}
            history.append({'label': label, 'execution_passed_as_recorded': receipt.get('passed'),
                'runtime_as_recorded': identity.get('runtime'), 'error_as_recorded': receipt.get('error'),
                'source_identity_scope': ('Earlier +219 compiled header accompanied investigative working-tree edits; not the final clean implementation.'
                    if len(identity.get('runtime') or []) > 3 and identity['runtime'][3] == '49261 +219 (Git)' else
                    'Literal earlier identity; a runtime commit alone is not asserted to prove a clean source tree.'),
                'unavailable_exact_executed_helper_bytes': historical_helper_gaps(label),
                'interpretation': 'Historical attempt; setup failure versus product RED is not inferred or repaired by this collector.'})
    for role, label in labels.items():
        if role.startswith('legacy-'):
            collect_legacy(archive, role, label)
        else:
            collect_run(archive, label, 'Selected final clean committed source gate: ' + role)
        if role == 'ctest':
            for name in ('LastTest.log', 'LastTestsDisabled.log'):
                path = root_file(label) / name
                if path.is_file():
                    archive.add(path, f'runs/{label}/{name}', 'Fresh final CTest detail; not stale prior-run evidence.')
    for name in NATIVE_BUILD_FILES:
        path = root_file(args.native_build_label) / name
        destination = f'native-build/{args.native_build_label}/{name}'
        if path.is_file():
            archive.add(path, destination, 'Native candidate provenance/build log; vendor runtime/source tree excluded.', receipt=path.suffix == '.json')
    for relative in SOURCE_FILES:
        archive.add(REPO / relative, 'qualified-source/' + relative, 'Exact final qualified implementation source snapshot.')
    archive.add(BUILD / 'src/Build/Version.h', 'qualified-source/Version.h', 'Exact final compiled source identity; no runtime binary bytes.')
    for rel, row in fixture_files.items():
        # Metadata may already have been copied by the run allowlist. Avoid a
        # second copy while retaining the explicit fixture manifest authority.
        source = root_file(rel)
        if str(source) not in archive.sources:
            archive.add(source, 'fixtures/' + rel, row['fixture'] + ': ' + row['role'], receipt=source.suffix == '.json')
    archive.check_unchanged()
    index = {'schema': 'FreeCAD-ywu-source-evidence-index-v1',
        'source_private_root': str(ROOT), 'scope': 'Source-only generic software/output evidence; no installation or Oomakhi replay.',
        'compiled_commit': args.commit, 'compiled_revision': args.revision,
        'final_labels': labels, 'historical_attempts': history,
        'helper_snapshot_policy': 'Current and retained historical helper bytes are labelled separately. Recorded earlier helper SHA values without matching retained bytes are explicitly disclosed, not substituted by current code.',
        'unpublished_current_helpers': omitted_helpers,
        'privacy_policy': 'No private inventories, profile/config/cache/environment files, secrets, runtime binaries or vendor build tree. Explicit root-approved generic fixture files only.',
        'self_hash_policy': 'Index excludes itself; separate validation binds its SHA. No self-hash claim.',
        'files': sorted(archive.records, key=lambda row: row['file'])}
    index_bytes = encoded(index)
    summary = {'schema': 'FreeCAD-ywu-source-validation-v1', 'passed': True,
        'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'issue': 'FreeCAD-ywu', 'compiled_commit': args.commit, 'compiled_revision': args.revision,
        'scope': 'Source-only capability qualification, not installation, Oomakhi replay or engineering/design acceptance.',
        'native_binary_sha256': NATIVE_SHA, 'native_source_sha256': NATIVE_C_SHA,
        'native_hooks_sha256': HOOKS_SHA, 'final_labels': labels, 'qualification': results,
        'captured_review_json': [{'path': row['relative'], 'sha256': row['sha256']}
                                 for row in review_files],
        'frozen_oracle_and_audit_sha256': FROZEN, 'historical_attempts': history,
        'protected_dependency_manifest_sha256': DEPENDENCY_MANIFEST_SHA,
        'evidence': {'directory': str(DEST.relative_to(REPO)), 'index_sha256': sha(index_bytes),
                     'index_bytes': len(index_bytes), 'indexed_files': len(archive.records)},
        'holds': {'installation_performed': False, 'installed_application_changed': False,
            'protected_user_FreeCAD_profiles_unchanged_during_final_gates': True,
            'custody_scope': 'Protected application/profile inventories in selected app-gate receipts and pinned dependency manifest files; not a whole-environment inventory.',
            'dependency_manifest_files_modified': False,
            'whole_dependency_environment_inventoried_or_unchanged_claimed': False,
            'Oomakhi_opened_altered_or_solved': False, 'engineering_or_BIM_design_accepted': False,
            'original_side_loaded_witness_repaired_or_claimed_passing': False,
            'original_side_loaded_fixture_inputs_rewritten': False,
            'separate_predeclared_end_loading_and_support_cases': True,
            'unchanged_force_and_original_origin_moment_relative_ceiling': 0.01,
            'original_R49_displacement_percent_ceiling': 5,
            'ordinary_support_patch_reaction_magnitudes_fitted': False,
            'posthoc_audits_claimed_predeclared': False}}
    summary_bytes = encoded(summary)
    # All validation, explicit input checking and privacy filtering finish before
    # creating either repository artifact. Existing evidence is never replaced.
    archive.check_unchanged()
    if args.check_only:
        print(json.dumps({'collection_plan_passed': True, 'writes': 0,
            'files': len(archive.records), 'index_sha256': sha(index_bytes),
            'validation_sha256': sha(summary_bytes)}, indent=2))
        return
    DEST.mkdir()
    for relative, data in archive.pending.items():
        path = DEST / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(data)
    with (DEST / 'index.json').open('xb') as stream:
        stream.write(index_bytes)
    with VALIDATION.open('xb') as stream:
        stream.write(summary_bytes)
    actual = {str(p.relative_to(DEST)) for p in DEST.rglob('*')
              if p.is_file() and p != DEST / 'index.json'}
    require(actual == set(archive.pending), 'Published evidence coverage differs from explicit plan')
    for relative, data in archive.pending.items():
        require(raw(DEST / relative) == data, f'Published bytes differ: {relative}')
    archive.check_unchanged()
    print(json.dumps({'passed': True, 'files': len(archive.records),
        'index_sha256': sha(index_bytes), 'validation_sha256': sha(summary_bytes),
        'destination': str(DEST)}, indent=2))


if __name__ == '__main__':
    main()
