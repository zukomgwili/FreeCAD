"""Root-only report producer from completed immutable e4k evidence."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parent
REPO=Path('/Users/zukomgwili/src/FreeCAD')
def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(name):
    return json.loads((ROOT/name).read_text())
phases=('native-build-r03','configure-r03','build-r05-frozen','guard-compile-r01','guard-test-r01','unit-r02','native-r04','cold-r03','mechanical-r01','gui-r01','fem-all-r01','ctest-r01')
gates={}
for phase in phases:
    p=ROOT/phase/'execution.json'
    record=json.loads(p.read_text())
    assert record['passed'] is True,(phase,record)
    gates[phase]={'execution':str(p),'execution_sha256':sha(p),'log_sha256':sha(p.with_name('run.log')),'elapsed_seconds':record['elapsed_seconds'],'passed':True,'test_counts':record.get('test_counts')}
assert read('unit-r02/execution.json')['test_counts']==['16']
assert read('native-r04/execution.json')['test_counts']==['5']
assert read('fem-all-r01/execution.json')['test_counts']==['481']
assert '100% tests passed out of 2269' in (ROOT/'ctest-r01/run.log').read_text()
assert (ROOT/'ctest-r01/run.log').read_text().count('***Skipped')==2
review=read('equilibrium-review-native-r04.json')
mechanical=read('mechanical-r01/mechanical-preservation.json')
assert mechanical['passed'] and mechanical['parsed_U_S_E_exactly_equal']
assert read('gui-r01/gui-receipt.json')['passed']
assert read('cold-r03/cold.json')['passed']
spec=importlib.util.spec_from_file_location('collector_spec',ROOT/'collect.py')
collector=importlib.util.module_from_spec(spec);spec.loader.exec_module(collector)
source={name:sha(REPO/name) for name in collector.SOURCE_NAMES}
assert sha(REPO/'package/calculix/force-accounting/forceaccounting.c')=='85690f1744ec4a2e9d0ff8483618373e3c85d7a49487c9f7a10f2265ffc6e728'
assert read('candidate-binary.json')['sha256']==sha(REPO/'build/release/data/NativeSolvers/ccx-force-accounting')
assert sha(ROOT/'oracles.json')=='ba8e0b883a501d9306c4bdab77936dc4c5827c1b061d97ccb03859ebf9ff9548'
report={
'schema':'FreeCAD-e4k-source-qualification-v1','issue':'FreeCAD-e4k','passed':True,
'scope':'Source/application-build software qualification; not application installation or Oomakhi design acceptance.',
'source_base_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
'source_files_sha256':source,
'feature':{'control':'Saved solver StaticStepAmplitude = Ramp or Step, TimeIncrement property group','default':'Ramp preserves the existing stock STEP/DLOAD behavior, excluding only independently generated footer wall-clock metadata in comparisons.','route':'Native density-based volumetric GRAV is full from first converged increment and held; explicit existing force/pressure amplitudes independently delay and reverse Q in one supported static step.','validation':'Finite strictly increasing authored amplitude pairs; valid signed factors, negative prehistory, D exponents and trailing padding preserved; missing/malformed/nonfinite and duplicate/decreasing times refused before definitions.','legacy_restore':'Missing saved control gains Ramp; saved Step, units, materials, references and full Q history preserved.'},
'native_integration':{'binary':read('candidate-binary.json'),'build_receipt':str(ROOT/'native-build-r03/build/build-receipt.json'),'build_receipt_sha256':sha(ROOT/'native-build-r03/build/build-receipt.json'),'zero_support':'Only captured, untainted, exact native-generated STEP table on an original finite zero structural SPC is additionally admitted; explicit user amplitudes, helper type, altered table or nonzero value still refuse.','contact_catalogues':'PER_RETAINED_FRAME inventories retain actual current native labels/counts with fixed pair/slave-face ownership; complete coverage and exact final aliases validated. Unmarked legacy V1 retains its shared-inventory invariant. No cross-frame material-point trajectories invented.','endpoint_representation':'Native and importer match at most four nextafter neighbours on each side of requested end, without rewriting actual times. Observed full1s native time is exactly one binary64 predecessor below1. Five neighbours, incomplete flags and5e-13 shortfall refuse. Successful owned-child and complete input/file custody still mandatory.','mechanics':'Diagnostic-only changes; no mechanical solver arrays or equations changed.'},
'qualification':{'fixture':'Three actual100mm cubes, three material density owners, translated XY centroid17,-23mm, genuine frictional contact and conformal cut; ordinary Fixed external support; same physical lower owner observed as native slave and master in separate runs.','directly_observed_channels':['SUPPORT/BaseSupport','LOAD/LowerCut','LOAD/UpperCut','CONTACT/LowerCut','CONTACT/UpperCut','MPC/LowerCut','MPC/UpperCut','CUT/LowerCut','CUT/UpperCut'],'base_contact_observation':'No new simultaneous independent base-side BODY/CONTACT measurement is claimed.','current_state_scope':'15 completed stock one-step native runs. Each requested current endpoint replays the same full physical-time Q history from time zero; accounting remains final-only.','individual_nonzero_component_relative_limit':0.01,'zero_force_absolute_N':1e-6,'zero_moment_absolute_Nmm':1e-4,'closure_limits':'Independently frozen1% physical-axis support/action scales on active axes, with the same fixed zero-axis budgets.','frozen_oracles':str(ROOT/'oracles.json'),'frozen_oracles_sha256':sha(ROOT/'oracles.json'),'independent_equilibrium_review':str(ROOT/'equilibrium-review-native-r04.json'),'independent_equilibrium_review_sha256':sha(ROOT/'equilibrium-review-native-r04.json'),'independent_review':review,'ordinary_mechanics_control':{'parsed_all_frame_U_S_E_exactly_equal':True,'baseline_native_sha256':'b6a356e8635a35cef2621db7bd80145566dc1f671683edb405ab927cb415b353','same_one_authored_mesh':True,'both_diagnostics_off':True,'backend_selection':'Existing ordinary Ccx preference in isolated profile; separate native and GUI gates exercise actual default bundled selection.','deck_exclusion':'Only exact stock written-on footer comment; executed raw decks remain untouched.','report':str(ROOT/'mechanical-r01/mechanical-preservation.json'),'report_sha256':sha(ROOT/'mechanical-r01/mechanical-preservation.json')},'cold':read('cold-r03/cold.json'),'gui':{'report':str(ROOT/'gui-r01/gui-receipt.json'),'report_sha256':sha(ROOT/'gui-r01/gui-receipt.json'),'native_property_editor':'Visible Ramp/Step editor and native stock Write/Run buttons; actual ordinary result import and current account/contact state.','root_visual_inspection':'Root inspected solver-property-editor-step.png; Static Step Amplitude is visibly Step.'}},
'quality_gates':gates,
'counts':{'registered_FEM_passed':481,'registered_FEM_skipped':0,'dedicated_control_and_wire_tests':16,'dedicated_native_test_methods':5,'dedicated_native_solve_endpoints':15,'dedicated_GUI':1,'dedicated_cold_latest':1,'ordinary_mechanical_preservation':1,'dedicated_tests_overlap_registered_suite':True,'ctest_catalogue':2277,'ctest_passed':2267,'ctest_existing_skipped':2,'ctest_existing_disabled':8,'ctest_failed':0,'SPC_exact_product_predicate_C_checks':40},
'static_checks':{'black_26_5_1_line100':{'passed':True,'log_sha256':sha(ROOT/'black-check.log')},'ruff_F401_F841_E9':{'passed':True,'log_sha256':sha(ROOT/'ruff-check.log')},'git_diff_check':{'passed':True}},
'failed_attempts':{'classification_record':str(ROOT/'attempt-classifications.json'),'cold_harness_record':str(ROOT/'cold-harness-classification.json'),'rule':'Original failed/nonqualifying receipts and verdicts retained verbatim, never relabelled as passing; current helpers are distinct snapshots and unresolved historical bodies are explicitly reported.'},
'custody':'Root-only serial FreeCAD/Gmsh/CalculiX/compiler/GUI execution; static subagent reviews only. Every final application gate protects the actual installed app and three real profiles; all are unchanged across each gate.',
'limitations':['One small-displacement static step; no multistep accounting or intermediate-frame accounting selector added.','Normal-source compression with actual native STICK; no new sliding/separation/general tangential-law qualification.','Software output qualification does not establish stress accuracy, generic mesh convergence, anchorage, strength or building acceptance.','Original Oomakhi not opened, edited, remeshed or solved; original1% equilibrium and separate5% sensitivity duties remain unchanged.','The application in /Applications is not replaced by this source task; deployment requires its own build/install step.'],
'installation_performed':False,
'primary_manual':{'url':'https://www.dhondt.de/ccx_2.23.pdf','printed_page':607,'sha256':'a0bf3fc03f374912ff2bf28da3f7dfb6a61428dd7f41b281a2e7e1fdb318f330','pdf_body_published':False}
}
(ROOT/'validation.json').write_text(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+'\n')
print(json.dumps({'passed':True,'source_files':len(source),'quality_gates':len(gates),'validation_sha256':sha(ROOT/'validation.json')}))
