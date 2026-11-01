"""Collect only completed FreeCAD-bjh evidence; never run FreeCAD or a solver.

The root agent reviews and runs this after every required gate completes.
Profiles, CAD bodies, binaries, dependency environments and archives are omitted.
Historical code inputs are preserved by their exact pre-run SHA256, not relabelled
as the final implementation. Failed prototypes remain explicitly nonqualifying.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile

ROOT = Path('/private/tmp/freecad-bjh-I0l3dCyo')
REPO = Path('/Users/zukomgwili/src/FreeCAD')
OUT = REPO/'package/local-completion/freecad-bjh-source-evidence'
SOURCE_BASE = 'd63cefd11f7d95d6b6ff12d836e820007c51b456'
NATIVE = 'b6a356e8635a35cef2621db7bd80145566dc1f671683edb405ab927cb415b353'
MAX_SMALL = 32 * 1024 * 1024
TEXT_SUFFIXES = {'.py', '.c', '.h', '.f', '.f90', '.cpp', '.hpp', '.patch', '.diff',
                 '.md', '.txt', '.json', '.toml', '.lock', '.yaml', '.yml', '.cmake'}
CASE_SUFFIXES = {'.json', '.frd', '.dat', '.inp', '.out', '.txt', '.log', '.csv',
                 '.png', '.sta', '.cvg', '.12d', '.request', '.xml', '.equ', '.nam'}
REQUEST_NAME = re.compile(r'.*\.(?:beam-section|contact-state|force-accounting)(?:\.run-[0-9a-f]{32})?(?:\.out)?$')
PROFILE_PARTS = {'freecad_user_home', 'freecad_user_data', 'xdg_data_home',
                 'xdg_config_home', 'xdg_cache_home', '__pycache__', '.pixi',
                 '.git', '.config', 'profiles', 'profile'}
FORBIDDEN_SUFFIXES = {'.fcstd', '.fcstd1', '.cfg', '.conf', '.ini', '.pyc', '.pyo',
                      '.so', '.dylib', '.dll', '.exe', '.o', '.a', '.zip', '.bz2',
                      '.gz', '.xz', '.7z', '.tar', '.step', '.stp', '.iges', '.igs', '.brep'}
SECRET_NAMES = {'.env', 'credentials', 'credentials.json', 'token', 'tokens.json',
                'user.cfg', 'system.cfg', 'config', 'config.json'}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def regular(path):
    path = Path(path)
    return path.is_file() and not path.is_symlink() and stat.S_ISREG(path.stat().st_mode)


def safe_name(path):
    path = Path(path)
    return (path.suffix.lower() not in FORBIDDEN_SUFFIXES
            and path.name.lower() not in SECRET_NAMES
            and not any(part.lower() in PROFILE_PARTS for part in path.parts)
            and 'Library' not in path.parts and 'Applications' not in path.parts)


def text_input(path):
    path = Path(path)
    return safe_name(path) and (path.suffix.lower() in TEXT_SUFFIXES
                                or path.name in {'CMakeLists.txt', 'COPYING', 'LICENSE', 'Makefile'})


def json_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def get_json(path):
    return json.loads(Path(path).read_text())


def resolve_input(original, expected):
    require(re.fullmatch('[0-9a-f]{64}', expected) is not None, f'Invalid input SHA: {original}')
    candidates = [ROOT / 'code-blobs' / expected, Path(original)]
    for candidate in candidates:
        if regular(candidate) and sha(candidate) == expected:
            return candidate
    raise RuntimeError(f'Missing exact historical text input {original} at SHA {expected}')


def walk_owned(base):
    """Never follow symlinks or enter any isolated profile/environment body."""
    if not base.is_dir() or base.is_symlink():
        return
    for current, directories, files in os.walk(base, followlinks=False):
        directories[:] = sorted(d for d in directories
                                if d.lower() not in PROFILE_PARTS
                                and not (Path(current) / d).is_symlink())
        for name in sorted(files):
            path = Path(current) / name
            if regular(path) and path.name.lower() not in SECRET_NAMES:
                yield path



REQUIRED = {
    'native-build-r05', 'component-control-r01', 'ordinary-mechanics-r01',
    'bounded-mechanics-r01', 'bounded-mechanics-r02', 'production-build-r02',
    'fem-all-r01', 'ctest-r01', 'gui-final-r01', 'cold-final-r01',
}
FAILED = {
    'grounded-branch-red-r01': ('EXPECTED_RED', 'Original single-source coupled admission refused the native branching tracer.'),
    'grounded-branch-green-r01': ('NONQUALIFYING_PROTOTYPE', 'Native generated blank equation not authenticated; no Current output qualified.'),
    'grounded-branch-green-r02': ('NONQUALIFYING_PROTOTYPE', 'Diagnostic identified the exact native two-term temperature equation.'),
    'grounded-branch-green-r03': ('NONQUALIFYING_PROTOTYPE', 'Native cascade changed the raw mean-translation equation representation; added authenticated raw graph bridge.'),
    'grounded-branch-green-r04': ('NONQUALIFYING_FORMAL_TEST', 'Owned native Current result existed, but test looked for section/material fields on each sample instead of joining the immutable element catalogue. Corrected test lookup only; fixed numeric budgets unchanged.'),
    'gui-red-r01': ('EXPECTED_RED', 'Actual native result inspector lacked the plural V5 action table before the provider implementation.'),
    'ordinary-mechanics-r02': ('NONQUALIFYING_EXACT_COMPARISON', 'Additional two-T exact comparison failed on near-null ordinary fields. Retained failure; separate pre-reviewed bounded comparison and inactive repeats used, never a bit-identity claim.'),
    'ordinary-mechanics-r03': ('NONQUALIFYING_EXACT_COMPARISON', 'Additional three-T exact comparison failed on near-null ordinary fields. Retained failure; separate pre-reviewed bounded comparison and inactive repeats used, never a bit-identity claim.'),
}


def verify_receipt(path):
    d=get_json(path); name=path.parent.name
    require(d['source_commit']==SOURCE_BASE, 'Wrong source base: '+name)
    require(d['source_inputs_before']==d['source_inputs_after'] and d['source_and_supervisor_unchanged'], 'Source custody: '+name)
    require(d['protected_before']==d['protected_after'] and d['app_and_three_profiles_unchanged'], 'Protected custody: '+name)
    require(d['installation_performed'] is False and d['timed_out'] is False and d['child_reaped'] and d['process_group_gone'], 'Child/scope: '+name)
    require(sha(path.parent/'run.log')==d['log_sha256'], 'Log identity: '+name)
    if name in FAILED:
        require(d['passed'] is False and d['returncode']!=0, 'Failed historical gate changed: '+name)
        classification, reason=FAILED[name]
    else:
        require(d['passed'] is True and d['returncode']==0, 'Unknown failed gate: '+name)
        classification='QUALIFYING_FINAL_PASS' if name in ('production-build-r02','fem-all-r01','gui-final-r01','cold-final-r01','ctest-r01','native-build-r05') else 'SUPPORTING_REQUIRED_PASS' if name in REQUIRED else 'SUPPORTING_PASS'
        reason='Required final gate with complete custody.' if name in REQUIRED else 'Supporting reproduction, build, or intermediate verification; not a claim about the final version by itself.'
    return d,classification,reason


def collect():
    receipts={p.parent.name:(p,*verify_receipt(p)) for p in sorted(ROOT.glob('*/execution.json'))}
    require(REQUIRED<=receipts.keys(), 'Required gates missing: '+str(REQUIRED-receipts.keys()))
    require(FAILED.keys()<=receipts.keys(), 'Historical failures missing')
    static=get_json(ROOT/'static-checks.json')
    require(static['black_returncode']==0 and static['ast_files']>0, 'Static checks failed')
    for name,digest in static['source_sha256'].items():
        require(sha(REPO/name)==digest, 'Stale static checks: '+name)
    native=get_json(ROOT/'native-stage.json')
    require(native['sha256']==NATIVE and native['installation_performed'] is False and native['previous_solver_replaced'] is False, 'Stage scope')
    require(sha(native['source'])==sha(native['target'])==NATIVE, 'Stage identity')
    native_build=get_json(ROOT/'native-build-r05/build/build-receipt.json')
    require(native_build['binary_sha256']==NATIVE and native_build['installed'] is False, 'Native receipt identity/scope')
    for key,name in [('beam_source_sha256','beamsection.c'),('beam_patch_sha256','beamsection.patch'),('contact_source_sha256','contactstate.c'),('extra_source_sha256','forceaccounting.c')]:
        require(sha(REPO/'package/calculix/force-accounting'/name)==native_build[key], 'Native compiled source differs: '+name)
    all_log=(ROOT/'fem-all-r01/run.log').read_text()
    require(re.search(r'^Ran 460 tests in ',all_log,re.M) is not None and re.search(r'^OK$',all_log,re.M) is not None and re.search(r'^OK \(skipped=',all_log,re.M) is None, 'Full FEM suite incomplete or skipped')
    ctest_log=(ROOT/'ctest-r01/run.log').read_text()
    require(re.search(r'^100% tests passed out of 2269$',ctest_log,re.M) is not None, 'CTest incomplete')
    for name,expected in [('oracles','5fa2860dbe013d119c9b471376e88ab77fa1e09af0140df5c2525a1a652cf43b'),('connected-oracles','c8c15042a8abb3fc7a27e5ed490c27be1b94ec8a4921d4e2c4aa3ff8be64f4dc'),('fork-oracles','53342c7585e80a3a324e6efd08727119eb0ea1ef9bb675dc305d0c1e2bc1f378')]:
        require(sha(REPO/('package/local-completion/freecad-bjh-'+name+'.md'))==expected, 'Frozen oracle changed: '+name)
    final_inputs=receipts['fem-all-r01'][1]['source_inputs_before']
    final_sources={Path(p):h for p,h in final_inputs.items() if Path(p).is_relative_to(REPO) and text_input(p) and (p.startswith(str(REPO/'src/Mod/Fem')+'/') or p.startswith(str(REPO/'package/calculix/force-accounting')+'/') or '/freecad-bjh-' in p)}
    for p,h in final_sources.items():require(sha(p)==h, 'Final source stale: '+str(p))
    final_gates=('production-build-r02','fem-all-r01','gui-final-r01','cold-final-r01')
    core_sources={p:h for p,h in final_sources.items() if str(p).startswith(str(REPO/'src/Mod/Fem')+'/') or str(p).startswith(str(REPO/'package/calculix/force-accounting')+'/')}
    for name in final_gates:
        pins=receipts[name][1]['source_inputs_before']
        for p,h in core_sources.items():
            require(pins.get(str(p))==h, 'Final gate core source differs/missing: '+name+' '+str(p))
    ctest_inputs=receipts['ctest-r01'][1]['source_inputs_before']
    for p,h in core_sources.items():
        if '/femtest/' not in str(p):
            require(ctest_inputs.get(str(p))==h, 'CTest product source differs: '+str(p))
    production={}
    for case in sorted((ROOT/'fem-all-r01/cases').iterdir()):
        if not case.is_dir() or not (case/'section-data.json').is_file():continue
        d=get_json(case/'section-data.json')
        if d.get('schema')!='CCX_BEAM_SECTION_V5':continue
        p=d['provenance']
        require(p['binary']==str(REPO/'build/release/data/NativeSolvers/ccx-force-accounting') and p['binary_sha256']==NATIVE, 'Production default not selected: '+case.name)
        production[case.name]={'binary':p['binary'],'binary_sha256':NATIVE,'samples':len(d['frames'][0]['samples'])}
    require({18,36,54}<={r['samples'] for r in production.values()}, 'Missing production multi-component positives')
    require(sha(REPO/'build/release/data/NativeSolvers/ccx-force-accounting')==NATIVE, 'Default binary changed')
    incomplete=get_json(ROOT/'scripts-r07/incomplete-gate.json')
    require(incomplete['classification']=='NONQUALIFYING_SUPERVISOR_FAILURE' and incomplete['execution_receipt_written'] is False and sha(ROOT/'scripts-r07/run.log')==incomplete['run_log_sha256'], 'Incomplete attempt identity')
    require(not OUT.exists(), 'Output already exists; inspect before replacement')
    artifacts=[];omissions=[];gates={}
    with tempfile.TemporaryDirectory(prefix='.freecad-bjh-collect-',dir=OUT.parent) as tmp:
        stage=Path(tmp)/'evidence';stage.mkdir()
        def copy(source,relative,expected=None):
            source=Path(source);relative=Path(relative)
            require(regular(source) and not relative.is_absolute() and '..' not in relative.parts, 'Unsafe copy')
            h=sha(source);require(expected is None or expected==h, 'Copy changed: '+str(source))
            dest=stage/relative;dest.parent.mkdir(parents=True,exist_ok=True)
            if dest.exists():require(sha(dest)==h,'Conflicting snapshot')
            else:shutil.copyfile(source,dest)
            artifacts.append({'path':relative.as_posix(),'sha256':h,'size':source.stat().st_size,'original':str(source)})
            return relative.as_posix()
        for name,(path,d,classification,reason) in receipts.items():
            copy(path,Path('runs')/name/'execution.json')
            copy(path.parent/'run.log',Path('runs')/name/'run.log',d['log_sha256'])
            inputs={}
            for original,h in d['source_inputs_before'].items():
                if text_input(original):
                    inputs[original]={'sha256':h,'snapshot':copy(resolve_input(original,h),Path('code-blobs')/h,h)}
                else:inputs[original]={'sha256':h,'snapshot':None,'reason':'Binary/archive/CAD/config/environment body excluded.'}
            json_write(stage/'runs'/name/'input-snapshots.json',inputs)
            gates[name]={'classification':classification,'reason':reason,'passed':d['passed'],'returncode':d['returncode'],'receipt':'runs/'+name+'/execution.json','log':'runs/'+name+'/run.log','custody_and_log_verified':True}
            for p in path.parent.glob('build/build-receipt.json'):copy(p,Path('runs')/name/'native-build-receipt.json')
            for tree in ('cases','legacy','legacy-coupled','dotted.parent'):
                for p in walk_owned(path.parent/tree):
                    allowed=safe_name(p) and (p.suffix.lower() in CASE_SUFFIXES or REQUEST_NAME.fullmatch(p.name))
                    # Dotted runtime and legacy bodies are represented by hashes.
                    allowed=allowed and tree=='cases'
                    if allowed and p.stat().st_size<=MAX_SMALL:
                        if p.suffix.lower()=='.png':require(p.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'),'Invalid screenshot')
                        else:
                            body=p.read_bytes();require(b'\x00' not in body,'Non-text case body');body.decode('utf-8')
                        copy(p,Path('runs')/name/p.relative_to(path.parent))
                    else:omissions.append({'original':str(p),'size':p.stat().st_size,'sha256':sha(p),'reason':'Excluded CAD/binary/config/runtime or oversized body; hash only.'})
        copy(ROOT/'scripts-r07/incomplete-gate.json','runs/scripts-r07/incomplete-gate.json')
        copy(ROOT/'scripts-r07/run.log','runs/scripts-r07/run.log',incomplete['run_log_sha256'])
        gates['scripts-r07']={'classification':incomplete['classification'],'passed':False,'audited_execution_receipt':False,'reason':incomplete['failure']}
        for p in sorted(ROOT.iterdir()):
            if p.is_file() and p.suffix in ('.py','.md','.json') and not p.name.endswith('.pending'):
                copy(p,Path('helpers')/p.name)
        for p,h in sorted(final_sources.items()):copy(p,Path('final-source')/p.relative_to(REPO),h)
        summary={'schema':'FreeCAD-bjh-validation-v1','bead':'FreeCAD-bjh','source_base':SOURCE_BASE,'required_gates':sorted(REQUIRED),'all_required_gates_passed':True,'native_binary_sha256':NATIVE,'gates':gates,'final_source_sha256':{str(p.relative_to(REPO)):h for p,h in final_sources.items()},'production_default_observations':production,'installation_performed':False,'scope':{'qualified':'V5 connected acyclic branching B32R component trees with one common global scalar axis, one grounded SPRING1, acyclic SPRING2 links, one physical five-zero guide per component, multiple point sources and per-component material/section ownership.','benchmarks':'One T, two connected Ts, three-component fork; frozen independently reviewed signed ends, physical supports, actual spring ends, geometry/axes/origin and case controls.','mechanics_comparison':'Original one-T exact comparison passed. Extra two-T/three-T exact controls failed and remain nonqualifying. Separate reviewed bounded comparisons including inactive candidate repeats and old binary passed without changing frozen equilibrium budgets.','excluded':['rotational/general joints','contact composition with V5','cycles','nonlinear modes','building design or Oomakhi acceptance','installation']},'evidence_directory':str(OUT.relative_to(REPO)),'excluded_bodies':'No application/profile/CAD/config/executable/archive/dependency bodies copied; analytical screenshots explicitly permitted.','collector_executed_native_commands':False}
        json_write(stage/'artifact-index.json',artifacts)
        json_write(stage/'hash-only-artifacts.json',omissions)
        json_write(stage/'validation.json',summary)
        json_write(stage/'manifest.json',{'schema':'FreeCAD-bjh-source-evidence-v1','source_base':SOURCE_BASE,'copied_artifact_records':len(artifacts),'omitted_body_hash_records':len(omissions),'validation':'validation.json'})
        stage.rename(OUT)
        json_write(REPO/'package/local-completion/freecad-bjh-validation.json',summary)
    print(json.dumps({'output':str(OUT),'required_gates':sorted(REQUIRED),'native_sha256':NATIVE},indent=2))


if __name__=='__main__':collect()
