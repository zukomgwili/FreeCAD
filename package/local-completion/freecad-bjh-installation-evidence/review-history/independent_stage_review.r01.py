"""Independent read-only full deployment inventory/parser audit; no native calls."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
from types import SimpleNamespace

ROOT = Path('/private/tmp/freecad-bjh-install-4X8KjpF5')
REPO = Path('/Users/zukomgwili/src/FreeCAD')
APP = Path('/Applications/FreeCAD-27.1.0.app')
STAGE = ROOT / APP.name
BACKUP = Path('/Users/zukomgwili/Applications/FreeCAD Backups/FreeCAD-27.1.0-before-bjh-4X8KjpF5.app')
PREFIX = REPO / '.pixi/envs/default'
RES = Path('Contents/Resources')
CORE = REPO / 'package/local-completion/freecad-ywu-installation-evidence/private/stage_install.py'
CORE_SHA = 'cca627502a56b6c9b4aefa4a970172c51e42e2dde834000decca65fd44ab46d9'
NATIVE_SHA = 'b6a356e8635a35cef2621db7bd80145566dc1f671683edb405ab927cb415b353'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            assert key not in result
            result[key] = value
        return result
    return json.loads(Path(path).read_text(), object_pairs_hook=unique)


def functions():
    # Compile only four hash/inventory/byte-parser definitions from the
    # independently pinned immutable core; no adapter imports or subprocesses.
    assert sha(CORE) == CORE_SHA
    tree = ast.parse(CORE.read_text())
    wanted = {'digest', 'inventory', 'canonical_sha', 'macho_identity'}
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    assert {n.name for n in nodes} == wanted
    assert not any(isinstance(n, ast.Name) and n.id in {'subprocess', 'runpy', 'importlib'}
                   for item in nodes for n in ast.walk(item))
    scope = {'hashlib': hashlib, 'os': os, 'stat': stat, 'struct': struct,
             'Path': Path, 'json': json}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(CORE), 'exec'), scope)
    return scope


def source_map():
    # Evaluate only source-map dictionary/loop statements; never load the
    # staging adapter, its native checks, runpy or imported helpers.
    tree = ast.parse(CORE.read_text())
    body = []
    for item in tree.body:
        if isinstance(item, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == 'SOURCES' or
            isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name)
            and target.value.id == 'SOURCES' for target in item.targets
        ):
            body.append(item)
        elif isinstance(item, ast.Expr) and isinstance(item.value, ast.Call) and isinstance(
            item.value.func, ast.Attribute
        ) and isinstance(item.value.func.value, ast.Name) and item.value.func.value.id == 'SOURCES':
            body.append(item)
    scope = {}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(CORE), 'exec'), scope)
    proxy = SimpleNamespace(SOURCES=scope['SOURCES'])
    tree = ast.parse((ROOT / 'stage_install.py').read_text())
    body = [n for n in tree.body if isinstance(n, ast.For) and any(
        isinstance(item, ast.Attribute) and item.attr == 'SOURCES'
        and isinstance(item.value, ast.Name) and item.value.id == 'core'
        for item in ast.walk(n)
    )]
    exec(compile(ast.Module(body=body, type_ignores=[]), 'source-map-only', 'exec'),
         {'core': proxy, 'json': json, 'REPO': REPO})
    return proxy.SOURCES


def native_set(root):
    found = set()
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [name for name in dirs if not (Path(current) / name).is_symlink()]
        for name in files:
            path = Path(current) / name
            if path.is_symlink():
                continue
            assert stat.S_ISREG(path.lstat().st_mode)
            with path.open('rb') as stream:
                magic = stream.read(4)
            if magic == b'\xcf\xfa\xed\xfe':
                found.add(path.relative_to(root).as_posix())
    return found


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('location', choices=('stage', 'installed'))
    args = parser.parse_args()
    fixed = [ROOT/name for name in (
        'identity.json', 'test-plan.json', 'LOCAL-INSTALL.txt', 'baseline-inventory.json',
        'stage-inventory.json', 'profile-inventories.json', 'critical-before-DESTDIR.json',
        'namespace-plan.json', 'independent-payload-audit.json', 'independent-stage-audit.json',
        'independent-stage-custody.json', 'stage_install.py', 'run_application.py', 'run_step.py',
        'audit_payload_stage.py', 'critical_pins.py', 'AppBeamBjh.py', 'ColdBeamBjh.py')]
    fixed += [CORE, REPO/'build/release/install_manifest.txt', Path(__file__)]
    before = {str(path):sha(path) for path in fixed}
    f = functions()
    inventory, canonical, macho = (f[k] for k in ('inventory', 'canonical_sha', 'macho_identity'))
    application = STAGE if args.location == 'stage' else APP
    old_app = APP if args.location == 'stage' else BACKUP
    baseline, sealed = load(ROOT / 'baseline-inventory.json'), load(ROOT / 'stage-inventory.json')
    assert inventory(old_app) == baseline
    actual = inventory(application)
    assert actual == sealed
    for path, expected in load(ROOT / 'profile-inventories.json').items():
        assert inventory(Path(path)) == expected
    critical = load(ROOT / 'critical-before-DESTDIR.json')
    for original, expected in critical['files'].items():
        path = Path(original); info = path.lstat()
        row = dict(dev=info.st_dev, inode=info.st_ino, mode=info.st_mode, size=info.st_size,
                   mtime_ns=info.st_mtime_ns, ctime_ns=info.st_ctime_ns)
        if stat.S_ISLNK(info.st_mode):
            row.update(kind='link', target=os.readlink(path), resolved=str(path.resolve(strict=True)),
                       resolved_sha256=sha(path))
        else:
            assert stat.S_ISREG(info.st_mode);row.update(kind='file', sha256=sha(path))
        assert row == expected, original
    payload_root = ROOT / 'payload'
    payload = payload_root / APP.relative_to('/') / RES
    payload_inventory = inventory(payload)
    manifest = REPO / 'build/release/install_manifest.txt'
    namespace = load(ROOT / 'namespace-plan.json')
    expected_namespace = {'lib/python3.13/site-packages/freecad/'+name for name in (
        'UiTools.py', '__init__.py', 'deprecation.py', 'freecad_doc.py', 'module_io.py',
        'part.py', 'partdesign.py', 'project_utility.py', 'sketcher.py', 'utils.py', 'utils_zip.py')}
    assert set(namespace) == expected_namespace
    for relative, proof in namespace.items():
        live = PREFIX / relative
        incoming_leaf = payload_root / PREFIX.relative_to('/') / relative
        assert not live.is_symlink() and not incoming_leaf.is_symlink()
        assert proof['before'] == proof['after'] == sha(live) == sha(incoming_leaf)
        assert stat.S_IMODE(live.stat().st_mode) == proof['mode']
    for line in manifest.read_text().splitlines():
        path = Path(line)
        assert path.is_absolute() and '..' not in path.parts
        assert path.is_relative_to(APP / RES) or path in {PREFIX/name for name in expected_namespace}
    manifest_leaves = {str(Path(line).relative_to('/')) for line in manifest.read_text().splitlines()}
    incoming = inventory(payload_root)
    assert manifest_leaves == {key for key,row in incoming.items() if row['kind'] != 'dir'}
    payload_audit = load(ROOT / 'independent-payload-audit.json')
    stage_audit = load(ROOT / 'independent-stage-audit.json')
    custody = load(ROOT / 'independent-stage-custody.json')
    assert payload_audit['passed'] is True and stage_audit['passed'] is True
    for proof in (payload_audit, stage_audit, custody):
        assert proof['schema'] == 'FreeCAD.LOCAL_INSTALL_INDEPENDENT_AUDIT_V2'
        assert proof['passed'] is True and proof['helper_sha256'] == sha(ROOT/'audit_payload_stage.py')
    assert custody['stage_audit_sha256'] == sha(ROOT/'independent-stage-audit.json')
    assert custody['critical_receipt_sha256'] == sha(ROOT/'critical-before-DESTDIR.json')
    assert custody['strict_signatures_quicklook_readonly_cachefree'] is True
    assert canonical(incoming) == payload_audit['payload_inventory_sha256']
    assert canonical(baseline) == payload_audit['baseline_inventory_sha256']
    assert stage_audit['payload_audit_sha256'] == sha(ROOT / 'independent-payload-audit.json')
    assert canonical(actual) == stage_audit['sealed_stage_inventory_sha256']
    payload_native, old_native, actual_native = native_set(payload), native_set(old_app), native_set(application)
    assert payload_native == {row['relative'] for row in payload_audit['native']}
    mapped = {(RES / item).as_posix() for item in payload_native}
    assert actual_native == mapped | (old_native - mapped)
    for row in payload_audit['native']:
        relative = row['relative'];before = macho(payload / relative)
        assert before['sha256'] == row['payload_sha256']
        assert before['normalized_sha256'] == row['normalized_sha256']
        assert before['rpaths'] == row['payload_rpaths']
        assert row['build_matches']
        for match in row['build_matches']:
            compiled = macho(REPO / 'build/release' / match['path'])
            assert compiled['sha256'] == match['sha256']
            assert compiled['normalized'] == before['normalized']
        after = macho(application / RES / relative)
        assert before['normalized'] == after['normalized'] and before['rpaths'] == after['rpaths']
    for relative in actual_native - mapped:
        before, after = macho(old_app / relative), macho(application / relative)
        assert before['normalized'] == after['normalized'] and before['rpaths'] == after['rpaths']
    # Complete leaf accounting, including inherited non-native resources.
    # Exempt only signing records, removed resource bytecode caches, and the
    # explicitly replaced local installation note. Other leaves must match
    # the payload overlay or baseline exactly, with documented read-only modes.
    overlay = {(RES / key).as_posix():row for key,row in payload_inventory.items() if row['kind'] != 'dir'}
    inherited = {key:row for key,row in baseline.items() if row['kind'] != 'dir'}
    expected = {**inherited, **overlay}
    def signature(key):return '_CodeSignature' in Path(key).parts
    def removed_cache(key):
        return key.startswith(str(RES)+'/') and ('__pycache__' in Path(key).parts or key.endswith('.pyc'))
    expected = {key:row for key,row in expected.items() if not signature(key) and not removed_cache(key)}
    leaves = {key:row for key,row in actual.items() if row['kind'] != 'dir' and not signature(key)}
    assert set(leaves) == set(expected), {'missing':sorted(set(expected)-set(leaves)), 'extra':sorted(set(leaves)-set(expected))}
    for key,row in leaves.items():
        prior = expected[key]
        assert row['kind'] == prior['kind'], key
        mode = prior['mode'] if row['kind'] == 'link' or not key.startswith(str(RES)+'/') else prior['mode'] & ~0o222
        assert row['mode'] == mode, key
        if key in actual_native:
            continue
        if key == str(RES / 'LOCAL-INSTALL.txt'):
            assert row['sha256'] == sha(ROOT / 'LOCAL-INSTALL.txt')
        else:
            field = 'target' if row['kind'] == 'link' else 'sha256'
            assert row[field] == prior[field], key
    resources = inventory(application / RES)
    assert not any('__pycache__' in Path(key).parts or key.endswith('.pyc') for key in resources)
    assert all(row['kind'] == 'link' or not row['mode'] & 0o222 for row in resources.values())
    sources = source_map()
    for source,target in sources.items():
        path = application / RES / target
        assert path.is_file() and not path.is_symlink() and sha(path) == sha(REPO/source), target
    native = application / RES / 'data/NativeSolvers/ccx-force-accounting'
    assert sha(native) == NATIVE_SHA
    result = {'passed':True, 'location':args.location,
                     'sealed_inventory_sha256':canonical(actual),
                     'baseline_inventory_sha256':canonical(baseline),
                     'total_inventory_entries':len(actual), 'complete_leaf_count':len(leaves),
                     'payload_native_count':len(payload_native), 'inherited_native_count':len(actual_native-mapped),
                     'all_native_count':len(actual_native), 'selected_source_matches':len(sources),
                     'selected_critical_files_unchanged':len(critical['files']),
                     'manifest_leaf_count':len(manifest_leaves),
                     'native_sha256':NATIVE_SHA,
                     'only_filesystem_hash_and_MachO_parser_operations':True,
                     'native_code_signature_or_app_execution':False}
    identity = load(ROOT/'identity.json')
    result.update(schema='FreeCAD-bjh-independent-stage-review-v1' if args.location=='stage'
                  else 'FreeCAD-bjh-independent-installed-review-v1',
                  compiled_commit=identity['commit'], revision=identity['revision'],
                  helper_sha256=sha(__file__), findings=[], inputs=before,
                  review_scope='Complete sealed software payload, source, inventory and custody; root native signature/app gates remain separate.')
    result['stage_inventory_sha256' if args.location=='stage' else 'installed_inventory_sha256'] = canonical(actual)
    if args.location=='installed':
        result.update(backup_inventory_sha256=canonical(baseline),
                      stage_review_sha256=sha(ROOT/'stage-independent-review.json'))
    assert before == {str(path):sha(path) for path in fixed}
    output = ROOT / ('stage-independent-review.json' if args.location=='stage' else 'final-independent-review.json')
    with output.open('x') as stream:
        json.dump(result,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')
    print(json.dumps({key:value for key,value in result.items() if key!='inputs'},indent=2))


if __name__ == '__main__':main()
