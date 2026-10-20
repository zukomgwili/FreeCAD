"""Prepare an explicit root-reviewable allowlist, never publish evidence or QA.

Only fixed software-gate namespaces, the two declared generic witness kinds,
and manifest-declared V1/V2 cases may contribute files. No recursive discovery
or copy is performed. Root must inspect the resulting complete file list and
approve its printed SHA before separately invoking collect_installation.py.
Only the selected new collection/install-plan.json may be written.
"""
import sys
sys.dont_write_bytecode = True

import argparse
import json
from pathlib import Path

from evidence_packet import (PRIVATE, REPOSITORY, descriptor, digest, json_bytes,
    load, require)
from collect_installation import (COMMIT, REVISION, HELPERS, NATIVE_SOURCE, ORACLES,
    SOURCE_QUALIFICATION)


GENERIC_SCOPE = 'generic software QA; not a retained engineering model'
OUTPUT = PRIVATE / 'collection/install-plan.json'
WITNESS_ALLOWED = {
    'cold-case.json', 'mesh-membership.json', 'motion-from-stock-dat.json',
    'native-accounting-data.json', 'native-properties.json',
    'stock-boundary-request-binding.json', 'native.stdout', 'native.stderr',
    'mesh/BeamCells_Geometry.brep', 'mesh/BeamCells_Mesh.vtk', 'mesh/shape2mesh.geo',
    'moving-face-ports-before-solve.FCStd', 'moving-face-ports-native-v3.FCStd',
    'ordinary-supports-before-solve.FCStd', 'ordinary-supports-native-v3.FCStd',
    'native/Mesh.12d', 'native/Mesh.accounting', 'native/Mesh.accounting.json',
    'native/Mesh.accounting.out', 'native/Mesh.cvg', 'native/Mesh.dat',
    'native/Mesh.frd', 'native/Mesh.inp', 'native/Mesh.sta', 'native/spooles.out',
}
V1_OUTPUTS = {'contact.12d', 'contact.accounting.out', 'contact.cvg',
    'contact.dat', 'contact.frd', 'contact.sta', 'spooles.out', 'solver.log'}
CORPUS_RETAINED = {'contact.inp', 'contact.accounting', 'contact.accounting.out',
    'oracle.json', 'solver.log'}
V2_CASE_FILES = ('contact.inp', 'contact.accounting', 'contact.accounting.out', 'oracle.json')
WITNESS_METADATA = {'cold-case.json', 'mesh-membership.json', 'motion-from-stock-dat.json',
    'native-accounting-data.json', 'native-properties.json', 'stock-boundary-request-binding.json',
    'native.stdout', 'native.stderr', 'native/Mesh.accounting.json'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    require(not OUTPUT.exists() and not OUTPUT.is_symlink(), 'Explicit plan already exists')
    final = load(PRIVATE / 'final-audit.json')
    independent_path = PRIVATE / 'independent-installed-audit.json'
    independent = load(independent_path)
    require(final['passed'] and final['source_commit'] == COMMIT and final['compiled_revision'] == REVISION
            and independent['passed'] and independent['source_commit'] == COMMIT
            and independent['revision'] == REVISION, 'Final installation audits not ready')
    entries = {}

    def add(relative, kind='receipt', classification='Retained final installation receipt', scope='private'):
        root = PRIVATE if scope == 'private' else REPOSITORY
        path = root / relative
        require(not Path(relative).is_absolute() and '..' not in Path(relative).parts, 'Unsafe explicit path')
        require(str(path) not in entries, 'Repeated explicit source')
        row = {'scope': scope, 'path': str(relative),
            'destination': ('repository/' if scope == 'repository' else 'private/') + str(relative),
            'sha256': descriptor(path)['sha256'], 'kind': kind, 'classification': classification}
        if kind == 'generic-fixture':
            row['fixture_scope'] = GENERIC_SCOPE
        entries[str(path)] = row

    for name in (*HELPERS, 'collection/prepare_plan.py'):
        add(name, 'source' if name.endswith('.py') else 'text',
            'Reviewed executed workflow or collection helper; collection code itself is not product QA')
    for name in ('namespace-plan.json', 'independent-payload-audit.json',
            'independent-stage-audit.json', 'independent-stage-custody.json',
            'final-audit.json', 'independent-installed-audit.json'):
        add(name)
    for mode in ('build', 'ctest'):
        # These small log-freshness descriptors are retained byte-exact, not
        # dropped alongside raw inventory bodies (which are never added).
        add(mode + '-latest/execution.json', classification='Exact final build/CTest receipt including literal fresh/stale log classifications')
        add(mode + '-latest/run.log', 'text', 'Exact final bounded build/CTest process output')
    for step in ('payload', 'audit-payload', 'stage', 'audit-stage', 'audit-custody', 'swap', 'audit-installed'):
        add('step-' + step + '.json')
        add('step-' + step + '.log', 'text', 'Exact installer supervisor output; new collection hash is not a missing original log-hash field')
    for name in ('oracle.json', 'oracle-spec-proposal.json', 'endload-oracle.json', 'ordinary-oracle.json'):
        add(name, classification='Unchanged predeclared generic software benchmark oracle; not engineering acceptance')
    for location in ('stage', 'installed'):
        for suffix in ('fem', 'gui', 'native', 'endload', 'ordinary', 'endload-cold', 'ordinary-cold'):
            label = location + '-' + suffix
            for name in ('execution.json', 'identity.json'):
                add(label + '/' + name, classification='Literal ' + location + ' application gate receipt; no historical path rebinding')
            add(label + '/run.log', 'text', 'Exact ' + location + ' application verbose unittest output')
        for kind in ORACLES:
            base = location + '-' + kind + '/witness'
            witness = load(PRIVATE / base / 'witness-receipt.json')
            require(witness['passed'], 'Generic native witness not passed')
            add(base + '/witness-receipt.json')
            require(set(witness['retained_files']) <= WITNESS_ALLOWED,
                    'Unknown generic witness filename requires root approval')
            cold = load(PRIVATE / base / 'cold-case.json')
            document = 'moving-face-ports-native-v3.FCStd' if kind == 'endload' else 'ordinary-supports-native-v3.FCStd'
            cold_files = {document, 'native/Mesh.inp', 'native/Mesh.accounting',
                'native/Mesh.accounting.out', 'native/Mesh.frd', 'native/Mesh.dat'}
            require(cold['document'] == str(PRIVATE / base / document)
                    and set(cold['source_files']) == {'deck', 'request', 'native_output', 'frd', 'dat'},
                    'Unknown generic cold file layout')
            require(cold_files <= set(witness['retained_files']), 'Required six cold artifacts missing')
            for name, proof in sorted(witness['retained_files'].items()):
                require(descriptor(PRIVATE / base / name)['sha256'] == proof['sha256'], 'Retained witness bytes changed')
                if name in WITNESS_METADATA | cold_files:
                    add(base + '/' + name, 'generic-fixture',
                        'Explicit declared generic ' + kind + ' analytical fixture/result; literal ' + location + ' provenance')
            add(location + '-' + kind + '-cold/cold-receipt.json')
        v1base = location + '-v1'
        v1 = load(PRIVATE / v1base / 'qualification.json')
        require(v1['passed'] and len(v1['analytic_cases']) == 48 and len(v1['rejections']) == 6,
                'V1 complete qualifier unavailable')
        for name in ('qualification.json', 'manifest.json'):
            add(v1base + '/' + name)
        for row in v1['analytic_cases'] + v1['rejections']:
            case = row['case']
            require(not Path(case).is_absolute() and '..' not in Path(case).parts
                    and set(row['inputs_after']) == {'contact.inp', 'contact.accounting', 'oracle.json'}
                    and set(row['outputs']) <= V1_OUTPUTS, 'Unknown V1 corpus filename')
            base = v1base + '/' + case
            add(base + '/execution.json')
            for name, sha in sorted(row['inputs_after'].items()):
                require(descriptor(PRIVATE / base / name)['sha256'] == sha, 'V1 declared input changed')
                add(base + '/' + name, 'generic-fixture', 'Exact predeclared generic legacy V1 input')
            for name, sha in sorted(row['outputs'].items()):
                require(descriptor(PRIVATE / base / name)['sha256'] == sha, 'V1 recorded output changed')
                if name in CORPUS_RETAINED:
                    add(base + '/' + name, 'text' if name == 'solver.log' else 'generic-fixture',
                        'Exact generic legacy V1 native output/log bound by its original case receipt')
        v2base = location + '-v2'
        v2 = load(PRIVATE / v2base / 'summary.json')
        require(v2['all_selected_passed'] and len(v2['reports']) == 10, 'V2 complete qualifier unavailable')
        for name in ('summary.json', 'manifest.json'):
            add(v2base + '/' + name)
        for row in v2['reports']:
            case = row['case']
            require(not Path(case).is_absolute() and '..' not in Path(case).parts, 'Unsafe V2 case')
            base = v2base + '/' + case
            add(base + '/execution.json')
            add(base + '/solver.log', 'text', 'Exact generic legacy V2 bounded native process log')
            for name in V2_CASE_FILES:
                if (PRIVATE / base / name).exists():
                    add(base + '/' + name, 'generic-fixture',
                        'Explicit known generic legacy V2 corpus file; only request/deck/accounting-output/log have original per-case SHA fields')
    for name in NATIVE_SOURCE:
        add('package/calculix/force-accounting/' + name,
            'receipt' if name.endswith('.json') else 'source',
            'Matching deployed native implementation/contract, not an executable payload', 'repository')
    add('package/calculix/force-accounting/COPYING', 'text',
        'Native solver source license; no executable bytes', 'repository')
    add('build/release/src/Build/Version.h', 'source',
        'Actual +221 compiled source identity header; not an executable payload', 'repository')
    add(str(SOURCE_QUALIFICATION.relative_to(REPOSITORY)), 'receipt',
        'Existing immutable +220 source qualification; not relabelled as installed +221 results', 'repository')
    # Bind the untouched shared V2 driver/generator/process helper explicitly.
    v2_manifest = load(PRIVATE / 'installed-v2/manifest.json')
    for key in ('script', 'generator', 'process_control'):
        path = Path(v2_manifest[key])
        if str(path) in entries:
            continue
        scope = 'private' if path.is_relative_to(PRIVATE) else 'repository'
        root = PRIVATE if scope == 'private' else REPOSITORY
        require(path.is_relative_to(root), 'Legacy helper is outside approved roots')
        add(str(path.relative_to(root)), 'source', 'Unchanged reviewed generic legacy V2 qualifier source', scope)
    v1 = load(PRIVATE / 'installed-v1/qualification.json')
    for name in v1['protected']:
        path = Path(name)
        if path.name == 'FreeCAD9ztContactWitness.py' and str(path) not in entries:
            require(path.is_relative_to(REPOSITORY), 'Untouched generic generator escaped repository')
            add(str(path.relative_to(REPOSITORY)), 'source', 'Untouched generic legacy V1 fixture generator', 'repository')
    plan = {'schema': 'FreeCAD-ywu-installation-publication-plan-v1',
        'source_commit': COMMIT, 'compiled_revision': REVISION,
        'independent_audit': {'path': 'independent-installed-audit.json', 'sha256': descriptor(independent_path)['sha256']},
        'files': sorted(entries.values(), key=lambda row: (row['scope'], row['path'])),
        'notes': ['Root must inspect and approve this full file list and SHA before publication.',
            'No recursive collection. Fixed gate names, two declared generic witnesses and manifest-declared legacy case names only.',
            'No private profiles, raw custody inventories, environment dumps, runtime binary bytes or native vendor tree.',
            'Stage paths remain historical pre-swap paths. Installed generic outputs were generated afresh at literal APP.',
            'Build/CTest freshness metadata is retained exactly, including explicitly stale historical failure-log classifications.',
            'Source/output software qualification only; engineering/Oomakhi holds remain unchanged.']}
    data = json_bytes(plan)
    if not args.check_only:
        with OUTPUT.open('xb') as stream:
            stream.write(data)
    print(json.dumps({'prepared': True, 'check_only': args.check_only,
        'writes': 0 if args.check_only else 1, 'explicit_file_count': len(entries),
        'plan': str(OUTPUT), 'sha256': digest(data), 'bytes': len(data)}, indent=2))


if __name__ == '__main__':
    main()
