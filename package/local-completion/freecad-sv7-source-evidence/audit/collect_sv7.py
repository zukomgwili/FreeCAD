"""Retain immutable source qualification records, excluding binaries and profiles."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
DEST = REPO/'package/local-completion/freecad-sv7-source-evidence'
RED = {'coupled-old-capability-r01', 'coupled-red', 'gui-red-r01', 'hybrid-red-r01', 'solid-gui-red-r01'}
PROTOTYPES = {
 'stock-spring-baseline': 'Private fixture authoring: adding a float to a dimensional Quantity failed before solve.',
 'stock-spring-baseline-v2': 'Private fixture authoring: addEdge required a list rather than a tuple.',
 'native-build-r01': 'Observer hook passed nload pointer instead of its integer value; compile-time rejection, corrected before execution.',
 'hybrid-green-r01': 'Written-deck catalogue compared SMESH Tet storage order with native CalculiX order; corrected catalogue interpretation.',
 'hybrid-green-r02': 'Fixture authored Tet connectivity in CalculiX order instead of SMESH order; stock export then had negative Jacobians. Corrected fixture connectivity without altering CAD geometry, loads or limits.',
 'hybrid-green-r03': 'Native forces, moments, spring motion and solid patch passed. Extra ideal-rod PL/EA tip criterion failed; native corner-mean point loading is not uniform traction. Original failure retained, no ideal-rod displacement qualification claimed. Independently prescribed pure native beam and inactive old/new controls establish component equivalence.',
 'native-causality-r01': 'Private control helper used an obsolete section property and attempted to JSON-encode a Vector; no mechanics conclusion from this attempt.',
}

def sha(p):
 return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def copy(p, target):
 target.parent.mkdir(parents=True, exist_ok=True)
 if target.exists():
  assert target.read_bytes()==p.read_bytes(),target
 else:
  shutil.copyfile(p,target)
 assert sha(p)==sha(target)

def text_file(p):
 try:
  data=p.read_bytes()
  if b'\x00' in data: return False
  data.decode('utf-8')
  return True
 except UnicodeDecodeError:
  return False

def artifact(p):
 return not p.is_symlink() and p.is_file() and (
  p.suffix.lower() in ('.json','.inp','.frd','.dat','.out','.png','.log','.sta','.cvg') or
  any(marker in p.name for marker in ('.beam-section','.contact-state','.accounting'))
 ) and (p.suffix.lower()=='.png' or text_file(p))

assert not DEST.exists(), 'Publish exact records once'
cases=[]
for execution in sorted(ROOT.glob('*/execution.json')):
 run=execution.parent; label=run.name; d=json.loads(execution.read_text())
 assert d['source_inputs_before']==d['source_inputs_after'],label
 assert d['source_and_supervisor_unchanged'] and d['app_and_three_profiles_unchanged'],label
 assert not d['timed_out'] and d['child_reaped'] and d['process_group_gone'],label
 assert sha(run/'run.log')==d['log_sha256'],label
 classification='PASS' if d['passed'] else 'EXPECTED_RED' if label in RED else 'NONQUALIFYING_PROTOTYPE'
 if not d['passed']: assert label in RED or label in PROTOTYPES,label
 manifest={'execution_sha256':sha(execution),'inputs':{}}
 for name,digest in d['source_inputs_before'].items():
  blob=ROOT/'code-blobs'/digest; original=Path(name)
  source=blob if blob.exists() else original if original.exists() and sha(original)==digest else None
  record={'sha256':digest}
  if source is not None and text_file(source):
   target=DEST/'code-blobs'/digest
   copy(source,target)
   record['snapshot']=str(target.relative_to(REPO))
  elif source is not None:
   record['withheld']='Binary executable, CAD document, archive or native dependency; hash retained.'
  else:
   raise AssertionError('Missing exact input snapshot: '+name+' '+digest)
  manifest['inputs'][name]=record
 for name in ('execution.json','run.log'): copy(run/name,DEST/label/name)
 (DEST/label/'input-snapshots.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
 output_roots=[run/'cases']
 if d['mode'] not in ('native-build','configure','build','ctest','scripts','stage'):
  output_roots.append(run/'dotted.parent')
 if label=='installed-baseline':
  output_roots.extend(p for p in sorted(run.glob('test_*')) if p.is_dir())
 if label.startswith('stock-spring-baseline'):
  output_roots.append(run/'series')
 for output_root in output_roots:
  for p in sorted(output_root.rglob('*')):
   if artifact(p):copy(p,DEST/label/p.relative_to(run))
 cases.append({'case':label,'classification':classification,'explanation':PROTOTYPES.get(label),
  'receipt':str((DEST/label/'execution.json').relative_to(REPO)),'execution_sha256':sha(execution)})
for p in sorted((ROOT/'code-blobs').iterdir()):
 if text_file(p): copy(p,DEST/'code-blobs'/p.name)
for label in ('native-build-r02','native-build-r03','native-build-r04'):
 for name in ('build-receipt.json','functional-tests.log'):
  p=ROOT/label/'build'/name
  if p.exists():copy(p,DEST/label/'build'/name)
copy(Path(__file__),DEST/'audit'/Path(__file__).name)
copy(ROOT/'final-quality.json',DEST/'audit/final-quality.json')
current=set(subprocess.check_output(['git','diff','--name-only','HEAD'],cwd=REPO,text=True).splitlines())
current.update(subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=REPO,text=True).splitlines())
sources={name:sha(REPO/name) for name in sorted(current) if (REPO/name).is_file() and
 (name.startswith(('src/Mod/Fem/','package/calculix/force-accounting/')) or name in (
 'package/local-completion/freecad-sv7-research.md','package/local-completion/freecad-sv7-oracles.md',
 'package/local-completion/freecad-sv7-usage.md','package/local-completion/freecad-sv7-independent-audit.json'))}
summary={
 'schema':'FreeCAD-sv7-source-validation-v1','bead':'FreeCAD-sv7',
 'source_base_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
 'source_inputs':sources,'cases':cases,
 'quality':str((DEST/'audit/final-quality.json').relative_to(REPO)),
 'V2_frozen_limits':'See freecad-sv7-oracles.md and test_beam_coupling_native.py; the separate axial and scaled transverse budgets remain unchanged.',
 'native_solver_sha256':'1f6281e8d779deeeb0f6a587d2cdcb5a7fc935e95f90b394cb28e761b22a603e',
 'native_build_receipt':str((DEST/'native-build-r04/build/build-receipt.json').relative_to(REPO)),
 'application_installation_performed':False,'application_and_three_real_profiles_unchanged_in_every_gate':True,
 'executed_stock_solver_decks_edited':False,'python_force_or_stress_recovery_used':False,
 'original_Oomakhi_opened_changed_solved_or_accepted':False,
 'scope':{
  'V1':'Existing pure B32R rectangular linear small-displacement static 3D qualification retained.',
  'V2':'One straight uniform rectangular B32R chain, global-axis grounded scalar translational SPRING1, five zero guided beam endpoint DOFs and opposite endpoint Force.',
  'V3':'One straight uniform rectangular B32R chain and one connected C3D4 CAD solid; scalar translational SPRING2 from beam vertex to detached fully free solid RBE reference, separate beam guide and solid Fixed support, one opposite beam Force. Axial analytical composition qualified; no generic joint stiffness law.',
  'contact':'Refused in the coupled beam workflow; future domain qualification tracked by FreeCAD-9rc.',
 },
 'frozen_V3_limits':{'action_force_N':0.01,'action_origin_moment_Nmm':1,'beam_end_force_N':0.1,'beam_end_moment_Nmm':0.4,'solid_stress_MPa':0.0001,'spring_relative_displacement_mm':0.000001,'solid_port_displacement_mm':0.0000001,'native_pure_beam_component_equivalence_mm':0.0000002},
 'geometry_semantics':'V2/V3 use native map co+vold argument, not an assumed solved-current deformed centroid. V1 legacy labels remain readable; geometry_source is explicit.',
 'unqualified_ideal_rod_displacement':'Failed original PL/EA tip comparison retained in hybrid-green-r03 and comparison.json. Component equivalence does not claim continuum end-compliance accuracy.',
 'independent_audit':'package/local-completion/freecad-sv7-independent-audit.json',
 'reviews':'Independent Standards and Spec reviews plus stable GUI review found no remaining actionable findings after corrections. Offline arithmetic reviewer authored native observer but not the fixtures or Python result/import assertions; report discloses this relationship.',
 'retained_history':'Receipts and logs copied unchanged, including every failed prototype and expected RED. Exact text input snapshots retained by SHA; executables, CAD documents, pinned archive/dependency binaries and private profiles withheld. Small native analytical outputs and GUI screenshots retained.',
}
(REPO/'package/local-completion/freecad-sv7-validation.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
print(json.dumps({'cases':len(cases),'sources':len(sources),'destination':str(DEST)},indent=2))
