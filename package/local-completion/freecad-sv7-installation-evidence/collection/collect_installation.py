"""Publish exact sv7 deployment receipts after the installed-bundle checks."""
import sys
sys.dont_write_bytecode = True
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
DEST = REPO/'package/local-completion/freecad-sv7-installation-evidence'
SUMMARY = REPO/'package/local-completion/freecad-sv7-installation.json'
COMMIT = '2f6ed5df7bd9786449230ad01366a7d8e10ae0e2'
REVISION = '49261 +242 (Git)'
NATIVE_SHA = '1f6281e8d779deeeb0f6a587d2cdcb5a7fc935e95f90b394cb28e761b22a603e'
COUNTS = {'cmd':31, 'gui':6, 'cold':1}

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def canonical(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def read(path):
    return json.loads(Path(path).read_text())

def copy(source,target):
    assert source.is_file() and not source.is_symlink(), source
    target.parent.mkdir(parents=True,exist_ok=True)
    assert not target.exists(),target
    shutil.copyfile(source,target)
    assert sha(source)==sha(target),target

def write(path,value):
    with path.open('x') as stream:
        json.dump(value,stream,indent=2,sort_keys=True,allow_nan=False)
        stream.write('\n')

assert not DEST.exists() and not SUMMARY.exists()
sys.path.insert(0,str(ROOT))
import stage_install as install
import critical_pins
import audit_payload_stage as audit
install.no_live_app(); install.compiled_identity()
assert (install.COMMIT,install.REVISION,install.NATIVE_SHA)==(COMMIT,REVISION,NATIVE_SHA)
sealed,baseline=read(ROOT/'stage-inventory.json'),read(ROOT/'baseline-inventory.json')
assert install.inventory(install.APP)==sealed and install.inventory(install.BACKUP)==baseline
assert not install.STAGE.exists()
for path,expected in read(ROOT/'profile-inventories.json').items():
    assert install.inventory(Path(path))==expected,path
critical=critical_pins.verify()
install.check_namespace(read(ROOT/'namespace-plan.json'))
install.verify(install.APP); install.verify(install.BACKUP)
install.source_equal(install.APP/'Contents/Resources')
for label,mode in (('build-latest','build'),('ctest-latest','ctest')):
    install.source_gate(label,mode)
for mode in COUNTS: install.application_gate(install.APP,mode)
reviews={}
for name in ('stage-independent-review.json','final-independent-review.json'):
    proof=read(ROOT/name); assert proof['passed'] is True,name
    stage = name.startswith('stage-')
    helper=ROOT/'review'/('independent_stage_review.py' if stage else 'independent_final_review.py')
    assert proof['schema']==('FreeCAD-sv7-independent-stage-review-v1' if stage else 'FreeCAD-sv7-independent-installed-review-v1')
    assert proof['compiled_commit']==COMMIT and proof['revision']==REVISION and proof['native_sha256']==NATIVE_SHA
    assert proof['helper_sha256']==sha(helper) and proof['findings']==[]
    if stage:
        assert proof['stage_inventory_sha256']==canonical(sealed)
        assert proof['baseline_inventory_sha256']==canonical(baseline)
    else:
        assert proof['installed_inventory_sha256']==canonical(sealed)
        assert proof['backup_inventory_sha256']==canonical(baseline)
        assert proof['stage_review_sha256']==sha(ROOT/'stage-independent-review.json')
    inputs=proof.pop('inputs')
    assert isinstance(inputs,dict)
    reviews[name]={'schema':'FreeCAD-sv7-public-independent-review-derivative-v1',
      'original_schema':proof.pop('schema'),'original_private_path':str(ROOT/name),
      'original_sha256':sha(ROOT/name),'input_record_count':len(inputs),
      'inputs_canonical_sha256':canonical(inputs),'private_original_retained_unchanged':True,
      'bulk_inputs_omitted':True,'publication_is_new_review_or_reexecution':False,**proof}
reports={}
for mode,name in (('payload','independent-payload-audit.json'),('stage','independent-stage-audit.json'),('custody','independent-stage-custody.json')):
    proof=read(ROOT/name)
    audit.admit_producer(proof,mode,commit=COMMIT,revision=REVISION)
    reports[mode]=proof
assert reports['stage']['sealed_stage_inventory_sha256']==canonical(sealed)
ct=(ROOT/'ctest-latest/run.log').read_text()
assert len(re.findall(r'^\s*\d+/\d+ Test\s+#.*\bPassed\s+[0-9.]+ sec',ct,re.M))==2267
assert '100% tests passed' in ct
assert len(re.findall(r'^\s*\d+ - \S+ \(Skipped\)$',ct,re.M))==2
assert len(re.findall(r'^\s*\d+ - \S+ \(Disabled\)$',ct,re.M))==8
phases=[]
for path in sorted(ROOT.glob('*/execution.json')):
    proof=read(path); run=path.parent
    assert proof['passed'] is True and proof['returncode']==0 and proof['timed_out'] is False,run
    assert proof['child_reaped'] is True and proof['process_group_gone'] is True,run
    assert sha(run/'run.log')==proof['log_sha256'],run
    assert proof['source_commit']==COMMIT,run
    for prefix in ('source_inputs','inputs'):
        if prefix+'_before' in proof:
            assert proof[prefix+'_before']==proof[prefix+'_after'],run
    if run.name.startswith(('stage-','installed-')):
        reg=read(run/'regression.json'); mode=proof['mode']
        assert reg['passed'] and reg['expected_tests']==reg['executed_tests']==COUNTS[mode]
        assert set(reg['selected_test_ids'])==install.expected_ids(mode)
        assert reg['skipped']==reg['failures']==reg['errors']==[]
        assert sha(run/'regression.json')==proof['regression_sha256']
        assert proof['application_inventory_sha256']==canonical(sealed)
        assert reg['source_or_build_import_override'] is False and reg['native_solver_override'] is False
        identity=read(run/'identity-observation.json')
        assert identity['runtime'][-1]==COMMIT and identity['runtime'][3]==REVISION
        assert identity['candidate']['sha256']==NATIVE_SHA and identity['candidate']['override'] is False
        assert set(identity['candidate']['capabilities'].values())=={'CCX_FORCE_ACCOUNTING_V3','CCX_CONTACT_STATE_V1','CCX_BEAM_SECTION_V1','CCX_BEAM_SECTION_V2','CCX_BEAM_SECTION_V3'}
        if mode=='cold':
            cold=read(run/'cold-observation.json')
            assert cold['analysis_solver_rerun'] is False
            assert cold['source_inputs_rebound_or_history_promoted_current'] is False
            assert {row['schema'] for row in cold['cases']}=={'CCX_BEAM_SECTION_V1','CCX_BEAM_SECTION_V2','CCX_BEAM_SECTION_V3'}
            assert all(row['completed_run'] is False and (row['status'].startswith('Historical') or row['status']=='Stale: Native beam output is historical or withdrawn; rerun required') for row in cold['cases'])
    phases.append({'label':run.name,'classification':'QUALIFYING_PASS','execution_sha256':sha(path),'log_sha256':proof['log_sha256']})
assert len(phases)==15,len(phases)
DEST.mkdir()
(DEST/'.gitattributes').write_text('# Preserve exact executed receipts, logs and helpers.\n* -whitespace\n')
for path in sorted(ROOT.glob('*.py')): copy(path,DEST/'helpers'/path.name)
copy(Path(__file__),DEST/'collection'/Path(__file__).name)
for path in sorted((ROOT/'review').glob('*.py')): copy(path,DEST/'review'/path.name)
for path in sorted((ROOT/'review-history').rglob('*')):
    if path.is_file(): copy(path,DEST/'review-history'/path.relative_to(ROOT/'review-history'))
for location in ('stage','installed'):
    for case in read(ROOT/(location+'-cold')/'cold-observation.json')['cases']:
        reference=Path(case['reference']['path'])
        assert reference.is_relative_to(ROOT) and reference.suffix=='.json'
        assert sha(reference)==case['reference']['sha256']
        copy(reference,DEST/reference.relative_to(ROOT))
for name in ('identity.json','build-identity.json','namespace-plan.json','LOCAL-INSTALL.txt',
             'independent-payload-audit.json','independent-stage-audit.json','independent-stage-custody.json'):
    copy(ROOT/name,DEST/name)
for name,proof in reviews.items(): write(DEST/name.replace('.json','-public.json'),proof)
for name in install.EXTENSIONS: copy(ROOT/(name+'.plist'),DEST/(name+'.plist'))
for phase in phases:
    directory=ROOT/phase['label']
    for name in ('execution.json','run.log','regression.json','identity-observation.json','cold-observation.json'):
        source=directory/name
        if source.exists(): copy(source,DEST/directory.name/name)
    for source in sorted(directory.rglob('*.png')):
        copy(source,DEST/directory.name/source.relative_to(directory))
copy(install.BUILD/'install_manifest.txt',DEST/'install_manifest.txt')
index={str(p.relative_to(DEST)):{'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(DEST.rglob('*')) if p.is_file()}
write(DEST/'index.json',index)
summary={'schema':'FreeCAD-sv7-installation-validation-v1','passed':True,
 'application':str(install.APP),'source_commit':COMMIT,'revision':REVISION,
 'native_sha256':NATIVE_SHA,'fix_bead':'FreeCAD-sv7','deployment_bead':'FreeCAD-nta',
 'date':datetime.now(ZoneInfo('Europe/London')).isoformat(),'timezone':'Europe/London',
 'modified_local_time':datetime.fromtimestamp(install.APP.stat().st_mtime,ZoneInfo('Europe/London')).isoformat(),
 'rollback_backup':str(install.BACKUP),'runtime_dependency':str(install.PREFIX),
 'self_contained':False,'notarized':False,'ad_hoc_signed':True,
 'build':{'full_incremental_Release':True,'clean_from_scratch_claimed':False},
 'application_tests':{'stage':COUNTS,'installed':COUNTS,'total_executed':76,'skipped':[],
   'cold_schemas_per_location':['CCX_BEAM_SECTION_V1','CCX_BEAM_SECTION_V2','CCX_BEAM_SECTION_V3'],
   'source_or_build_import_override':False,'native_solver_override':False},
 'ctest':{'catalogue':2277,'passed':2267,'skipped':2,'disabled':8,'failed':0},
 'payload':{'native_images':reports['payload']['payload_native_count'],
   'sealed_stage_and_installed_inventory_sha256':canonical(sealed),
   'exact_backup_inventory_sha256':canonical(baseline),
   'full_DESTDIR_leaf_set_audited':True,'strict_signatures_QuickLook_entitlements_readonly_cachefree':True},
 'preservation':{'profiles_unchanged':3,'selected_critical_files_unchanged':len(critical['files']),
   'external_namespace_files_unchanged':11,'whole_dependency_environment_inventory_claimed':False},
 'scope':'Current fork deployment only; source-qualified bounded coupling domains unchanged. No original project or building design opened, changed, solved or accepted. Coupled contact remains FreeCAD-9rc.',
 'source_qualification':'package/local-completion/freecad-sv7-validation.json',
 'nonqualifying_review_harness_attempts':2,
 'review_history':'Two rejected review-script assumptions are preserved under review-history; successful application gates and frozen installation helpers were unchanged.',
 'metadata_note':'Later deployment-tracking commits do not change the exact compiled2f6ed5df7b/+242 application identity.',
 'privacy':{'bulk_app_and_profile_inventories_published':False,'native_executables_or_CAD_published':False,
   'independent_review_publications_are_labelled_derivatives':True,'original_absolute_provenance_preserved':True},
 'evidence':{'directory':str(DEST.relative_to(REPO)),'private_directory':str(ROOT),'files':len(index),
   'index_sha256':sha(DEST/'index.json')},'phases':phases}
write(SUMMARY,summary)
assert install.inventory(install.APP)==sealed and install.inventory(install.BACKUP)==baseline
critical_pins.verify();install.no_live_app()
print(json.dumps({'passed':True,'summary':str(SUMMARY),'files':len(index),'revision':REVISION},indent=2))
