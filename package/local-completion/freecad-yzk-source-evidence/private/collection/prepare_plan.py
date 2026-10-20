"""Build an explicit source-evidence file plan; root alone invokes this tool.

No application, native solver, build, test, installation or repository write is
performed. The hash-bound config names every final role and every optional
input. Expansion is limited to fixed public QA namespaces and receipt-declared
generic legacy cases. The resulting exact file list requires root review.
"""
import sys
sys.dont_write_bytecode = True

import argparse
from pathlib import Path
import re

from evidence_packet import (
    PRIVATE, REPOSITORY, Packet, descriptor, digest, json_bytes, load,
    read_regular, relative_path, require, source_path,
)


SCHEMA = 'FreeCAD-yzk-source-collection-config-v1'
PRIMARY = 'qa-v2/coupled-capacity-at-limit-r01/witness'
GENERIC = 'generic software QA; not a retained engineering model'
COMMON = ('manifest.json', 'execution.json', 'identity.json', 'run.log')
PRIMARY_FILES = (
    'witness-receipt.json', 'exact-budget-proof.json', 'cold-case.json',
    'coupled-before-export.FCStd', 'coupled-native-current.FCStd',
    'export-properties.json', 'native-properties.json', 'geometry-contract.json',
    'independent-export-audit.json', 'mesh-membership.json',
    'motion-from-original-dat.json', 'native-accounting-data.json',
    'physical-face-motion-proof.json', 'native.stdout', 'native.stderr',
    'native/Mesh.inp', 'native/Mesh.accounting', 'native/Mesh.accounting.out',
    'native/Mesh.accounting.json', 'native/Mesh.dat', 'native/Mesh.frd',
)
PORTABLE_FILES = (
    'witness-receipt.json', 'independent-export-audit.json',
    'physical-face-motion-proof.json', 'motion-from-original-dat.json',
    'cold-case.json', 'geometry-contract.json', 'export-properties.json',
    'native-properties.json', 'native-accounting-data.json', 'native.stdout', 'native.stderr',
)
ORACLES = ('fixture-spec.json', 'physical-oracle.json', 'acceptance-amendment-v1.json')
NATIVE = ('forceaccounting.c', 'hooks.patch', 'contract.json', 'COPYING')
OWN = ('evidence_packet.py', 'prepare_plan.py', 'collect_source.py', 'verify_publication.py')


def safe_directory(value, prefixes):
    path = relative_path(value)
    require(any(str(path).startswith(prefix + '/') for prefix in prefixes),
            f'Role escaped its declared QA namespace: {value}')
    return str(path)


def assemble(config, config_path):
    require(config['schema'] == SCHEMA, 'Wrong explicit collection config schema')
    require(re.fullmatch(r'[0-9a-f]{40}', config['source_commit'])
            and isinstance(config['revision'], str), 'Final identity must be explicit')
    files = {}
    omissions = config.get('receipt_omissions', {})

    def add(scope, path, kind, classification):
        path = str(relative_path(path))
        target = source_path(scope, path)
        entry = {'scope': scope, 'path': path, 'destination': scope + '/' + path,
                 'sha256': descriptor(target)['sha256'], 'kind': kind,
                 'classification': classification}
        if kind == 'generic-fixture':
            entry['fixture_scope'] = GENERIC
        key = scope + '/' + path
        if key in omissions:
            entry['omit_top_level_fields'] = omissions[key]
        if key in files:
            previous = files[key]
            require(previous['sha256'] == entry['sha256']
                    and previous.get('omit_top_level_fields') == entry.get('omit_top_level_fields'),
                    f'Conflicting explicit input: {key}')
            if previous['kind'] == 'generic-fixture':
                entry['kind'], entry['fixture_scope'] = previous['kind'], GENERIC
            entry['classification'] = previous['classification'] + ' | ' + classification
        files[key] = entry

    def bundle(directory, classification, required=True):
        for name in COMMON:
            if required or (PRIVATE / directory / name).is_file():
                add('private', directory + '/' + name,
                    'receipt' if name.endswith('.json') else 'text', classification)

    proposal = load(PRIVATE / 'collection/proposal-v1.json')
    for row in proposal['initial_known_receipt_roles']:
        require(descriptor(source_path(row['scope'], row['path']))['sha256'] == row['sha256'],
                f'Frozen historical receipt changed: {row["role"]}')
        add(row['scope'], row['path'], 'receipt', row['classification'])
        # Preserve only these known companion names if they actually exist.
        # No recursive discovery and no private inventory capture.
        if Path(row['path']).name == 'execution.json':
            bundle(str(Path(row['path']).parent), row['classification'], required=False)
    for row in config.get('history', []):
        require(set(row) == {'directory', 'classification'}, 'Unexpected history declaration')
        directory = safe_directory(row['directory'], ('qa', 'qa-v2', 'qa-v3', 'native-qa'))
        bundle(directory, row['classification'], required=False)
        require((PRIVATE / directory / 'execution.json').is_file(), 'History needs an actual receipt')

    for name in ('65-moving-ports.FCStd', 'probe.json', 'port-membership.json',
                 'native.stdout', 'native.stderr', 'native/Mesh.inp',
                 'native/Mesh.accounting', 'native/Mesh.accounting.json'):
        add('private', 'repro-v2/physical-red-2/witness/' + name, 'generic-fixture',
            'Original stock65-port capacity RED inputs/logs; no repaired result or fitted physical acceptance')
    for base in ('native-capacity-unit-r01', 'native-capacity-unit-r02'):
        add('private', base + '/manifest.json', 'receipt',
            'Artificial native-C component plan; not FE physics')
    units = load(PRIVATE / 'native-capacity-unit-r02/summary.json')
    for row in units['cases']:
        folder = relative_path('native-capacity-unit-r02/' + row['label'])
        require(len(folder.parts) == 2, 'Artificial case escaped its declared directory')
        for name in ('execution.json', 'process.json', 'run.log',
                     'ARTIFICIAL_REQUEST_NOT_FE_INPUT', 'ARTIFICIAL_REQUEST_NOT_FE_INPUT.out'):
            if (PRIVATE / folder / name).is_file():
                add('private', str(folder / name), 'receipt' if name.endswith('.json') else 'text',
                    'Artificial native-C capacity/mask control, NOT a finite-element physical result')
    for folder in ('native-capacity-unit-r01/compile', 'native-capacity-unit-r02/compile',
                   'native-capacity-unit-r02/compile-sanitized'):
        for name in ('execution.json', 'process.json', 'run.log'):
            if (PRIVATE / folder / name).is_file():
                add('private', folder + '/' + name, 'receipt' if name.endswith('.json') else 'text',
                    'Artificial C component compiler receipt; firstattempt SDK setup failure retained')

    for name in ORACLES:
        add('private', 'oracle/' + name, 'source', 'Frozen independently declared software fixture/oracle; unchanged limits')
    for name in NATIVE:
        add('repository', 'package/calculix/force-accounting/' + name, 'source',
            'Final native extension source or observed contract/license; not a runtime binary')
    for scope, path in (
        ('private', 'native-qa/run_legacy_v1.py'), ('private', 'native-qa/process_control.py'),
        ('repository', 'package/local-completion/freecad-5ar-qa/qualify_native_v2_analytic.py'),
        ('repository', 'package/local-completion/freecad-5ar-qa/process_control.py'),
        ('repository', 'package/local-completion/FreeCAD9ztContactWitness.py'),
    ):
        add(scope, path, 'source', 'Unchanged predeclared legacy corpus generator/driver/process helper')
    for name in PRIMARY_FILES:
        add('private', PRIMARY + '/' + name, 'generic-fixture',
            'Primary actual132 coupled software fixture; original +222/a878 identity, not final-runtime rebinding')
    bundle(str(Path(PRIMARY).parent), 'Primary actual132 software qualification at its original +222 identity')
    for directory in ('qa-v2/coupled-capacity-cold-r02', 'qa-v2/coupled-capacity-refusal-r01'):
        bundle(directory, 'Actual primary-fixture cold/refusal control; original +222 identity')
    add('private', 'qa-v2/coupled-capacity-cold-r02/cold-receipt.json', 'receipt',
        'Separate cold process; historical Stale data, no solve/save/repair')
    add('private', 'qa-v2/coupled-capacity-refusal-r01/capacity-refusal-proof.json', 'receipt',
        'Same complete2113 graph refuses2112 before mesh export or solve')

    build = safe_directory(config['build_directory'], ('qa-v3',))
    add('private', build + '/execution.json', 'receipt', 'Final clean committed source build')
    add('private', build + '/run.log', 'text', 'Final clean committed source build raw log')
    for role, spec in config['applications'].items():
        require(set(spec) == {'directory', 'module', 'expected_count', 'critical_ids'},
                f'Unexpected application role fields: {role}')
        directory = safe_directory(spec['directory'], ('qa-v3',))
        require(isinstance(spec['expected_count'], int) and spec['expected_count'] > 0,
                'Expected test count must be declared independently')
        bundle(directory, 'Final committed source application gate: ' + role)

    retained = config['portable_retained']
    require(set(retained) == {'directory', 'copy_custody'}, 'Wrong portable capsule declaration')
    portable = relative_path(retained['directory'])
    require(len(portable.parts) == 1 and re.fullmatch(r'portable-retained-[A-Za-z0-9_-]+', str(portable)),
            'Portable capsule must be outside all profile/cache roots')
    for name in PORTABLE_FILES:
        add('private', str(portable / name), 'generic-fixture',
            'Exact retained copy of selected final portable generic witness JSON; original path preserved')
    add('private', retained['copy_custody'], 'receipt',
        'Explicit portable JSON original/copy path and SHA equality custody; no broad profile copy')
    add('private', 'collection/copy_portable.py', 'source', 'Unexecuted earlier portable-selection proposal; preserved history')
    add('private', 'collection/copy_portable_v2.py', 'source', 'Exact reviewed portable-selection copy producer')
    for path, classification in ((config['benchmark_report'], 'Final same public12-call diagnostic benchmark'),
                                 (config['portable_cold_receipt'], 'Actual separate-process final portable historical cold gate')):
        add('private', path, 'receipt', classification)
    attestation = load(PRIVATE / 'qa/native-capacity-r01-attestation-v2.json')
    for stamp in attestation['original_evidence'].values():
        path = Path(stamp['path'])
        require(path.is_relative_to(PRIVATE / 'native-capacity-r01'), 'Native original evidence escaped its known root')
        add('private', str(path.relative_to(PRIVATE)), 'receipt' if path.suffix == '.json' else 'text',
            'Original actual native compilation or functional checks; not132-graph physical acceptance')

    for version, directory in config['legacy'].items():
        require(version in ('V1', 'V2'), 'Unknown legacy protocol')
        directory = safe_directory(directory, ('native-qa',))
        bundle(directory, 'Final unchanged generic native ' + version + ' regression', required=False)
        add('private', directory + '/manifest.json', 'receipt', 'Legacy native control manifest')
        add('private', directory + '/preparation.json', 'receipt', 'Generic corpus preparation; no native execution')
        outer = load(PRIVATE / directory / 'manifest.json')
        corpus = Path(outer['corpus'])
        require(corpus == PRIVATE / (directory + '-corpus'), 'Legacy corpus not expected sibling')
        inner = load(corpus / 'manifest.json')
        require(len(outer['cases']) == (54 if version == 'V1' else 10), 'Incomplete generic corpus')
        add('private', str(corpus.relative_to(PRIVATE) / 'manifest.json'), 'receipt', 'Frozen complete generic corpus')
        add('private', str(corpus.relative_to(PRIVATE) / ('qualification.json' if version == 'V1' else 'summary.json')),
            'receipt', 'Actual complete generic native results, not FreeCAD writer/capacity proof')
        expected = {row['case'] if version == 'V1' else row['name'] for row in inner['cases']}
        require(expected == {row['name'] for row in outer['cases']}, 'Corpus/control case names differ')
        for row in outer['cases']:
            case = Path(row['directory'])
            require(case == corpus / relative_path(row['name']), 'Legacy case escaped corpus')
            names = ['contact.inp', 'contact.accounting', 'execution.json', 'solver.log']
            if version == 'V1':
                names.append('oracle.json')
            if (case / 'contact.accounting.out').is_file():
                names.append('contact.accounting.out')
            for name in names:
                add('private', str((case / name).relative_to(PRIVATE)),
                    'generic-fixture' if name not in ('execution.json', 'solver.log', 'oracle.json') else
                    ('receipt' if name.endswith('.json') else 'text'),
                    'Unchanged ' + version + ' generic case ' + row['name'])

    ctest = safe_directory(config['ctest_directory'], ('native-qa',))
    add('private', ctest + '/execution.json', 'receipt', 'Final serial CTest complete actual catalogue')
    add('private', ctest + '/run.log', 'text', 'Final serial CTest raw log')
    # Fresh retained CTest log names are explicitly supplied; never copy the
    # mutable build/Testing tree or a stale failure log based on its filename.
    for relative in config['ctest_retained_logs']:
        require(Path(relative).parent == Path(ctest), 'CTest retained log escaped gate')
        add('private', relative, 'text', 'Exact supervisor-retained fresh CTest diagnostic')
    static = safe_directory(config['static_directory'], ('native-qa',))
    add('private', static + '/execution.json', 'receipt', 'Final static authored-source quality gates')
    for number in range(5):
        add('private', static + f'/check-{number}.log', 'text', 'Actual static command raw log')
    add('private', config['review_receipt'], 'receipt',
        'Hash-bound source review with explicit independence/authorship caveats; no runtime proof')
    add('private', 'native-qa/primary-physical-independent-audit.json', 'receipt',
        'Completed primary-evidence arithmetic/custody review; retain author and runtime-scope disclosures')
    review = load(PRIVATE / config['review_receipt'])
    for path in review['reviewed_files']:
        require(path.startswith(('src/Mod/Fem/', 'package/calculix/force-accounting/')),
                'Reviewed source escaped approved product namespaces')
        add('repository', path, 'source', 'Exact final reviewed production/test/source-oracle bytes')
    add('repository', 'build/release/src/Build/Version.h', 'source', 'Actual final compiled source revision header')

    for row in config['additional_files']:
        require(set(row) == {'scope', 'path', 'kind', 'classification'}, 'Unexpected optional explicit file fields')
        add(**row)
    for name in OWN:
        add('private', 'collection/' + name, 'source', 'Reviewed source-only evidence producer; not product runtime')
    for name in ('prepare_plan-draft-v1.py', 'collect_source-draft-v1.py', 'verify_publication-draft-v1.py'):
        add('private', 'collection/history/' + name, 'source', 'Unexecuted earlier evidence-producer draft; not final publication code')
    add('private', str(config_path.relative_to(PRIVATE)), 'receipt', 'Exact root-approved final role config')
    add('private', 'collection/proposal-v1.json', 'receipt', 'Earlier proposal, not a final execution receipt')
    require(set(omissions).issubset(files), 'Omission names a file not explicitly selected')
    entries = sorted(files.values(), key=lambda row: (row['scope'], row['path']))
    packet = Packet()
    for entry in entries:
        packet.add(entry)
    packet.unchanged()
    return {'schema': 'FreeCAD-yzk-source-approved-file-plan-v1',
            'task_root': str(PRIVATE), 'repository': str(REPOSITORY),
            'config': config, 'config_descriptor': descriptor(config_path),
            'files': entries, 'planned_input_count': len(entries),
            'publication_requires_separately_reviewed_hash_bound_plan': True,
            'application_solver_build_test_or_installation_executed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--config-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(not sys.flags.optimize, 'Use an unoptimized interpreter')
    config_path = args.config.absolute()
    require(config_path.parent == PRIVATE / 'collection' and not config_path.is_symlink(),
            'Root-approved config must be in this private collection directory')
    require(digest(read_regular(config_path)) == args.config_sha256, 'Config SHA differs')
    require(args.output.absolute().parent == PRIVATE / 'collection'
            and not args.output.exists() and not args.output.is_symlink(), 'New private plan only')
    result = assemble(load(config_path), config_path)
    with args.output.open('xb') as stream:
        stream.write(json_bytes(result))
    print(json_bytes({'passed': True, 'plan': descriptor(args.output),
                      'explicit_inputs': result['planned_input_count'],
                      'native_or_repository_writes': 0}).decode(), end='')


if __name__ == '__main__':
    main()
