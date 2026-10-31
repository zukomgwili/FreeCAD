"""Fresh 960 admission adapter; immutable staging, signing and rollback core."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import signal
import subprocess
import sys

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
import run_gate
REPO=Path('/Users/zukomgwili/src/FreeCAD')
ORIGINAL=REPO/'package/local-completion/freecad-ywu-installation-evidence/private/stage_install.py'
CORE_SHA='cca627502a56b6c9b4aefa4a970172c51e42e2dde834000decca65fd44ab46d9'
assert __debug__ and hashlib.sha256(ORIGINAL.read_bytes()).hexdigest()==CORE_SHA
spec=importlib.util.spec_from_file_location('_960_stage_core',ORIGINAL)
core=importlib.util.module_from_spec(spec);spec.loader.exec_module(core)
identity=json.loads((ROOT/'identity.json').read_text())
assert identity['schema']=='FreeCAD-960-install-identity-v1'
assert identity['commit']=='64e6da94ac9e5d693f7dafb8495679983a68bb46'
assert identity['native_sha256']=='3fdd2b7f7cc3198e7fd1a5dc89a71e0cfacbd1f6ee3e21b106e2171ed6b52d7a'
core.ROOT=ROOT;core.STAGE=ROOT/core.APP.name
core.BACKUP=Path('/Users/zukomgwili/Applications/FreeCAD Backups/FreeCAD-27.1.0-before-960-1e3e53ed1f.app')
core.COMMIT=identity['commit'];core.REVISION=identity['revision'];core.NATIVE_SHA=identity['native_sha256']
IDENTITY_SHA=core.digest(ROOT/'identity.json')
assert len(core.PROFILES)==3
for relative in (
 'femtools/elastic_connector.py','femsolver/calculix/writer.py','femtools/rigid_body.py',
 'femtest/app/support_utils.py','femtest/app/test_rigid_region_ownership.py',
 'femsolver/calculix/write_constraint_rigidbody.py','femsolver/calculix/write_constraint_rigidbody_step.py',
 'femtest/app/test_elastic_connector.py','femtest/app/coupled_port_fixture.py','femtest/app/coupled_port_audit.py',
 'femtest/app/test_moving_port_capacity_native.py','femtest/data/calculix/coupled_port_capacity_fixture.json',
 'femtest/data/calculix/coupled_port_capacity_oracle.json','femmesh/quality.py',
 'femsolver/calculix/write_step_output.py','femtaskpanels/task_solver_ccxtools.py',
 'femtest/app/test_contact_state_interfaces.py','femtest/app/test_contact_state_native.py',
 'femtest/app/test_input_fingerprint.py','femtest/gui/test_contact_state.py','femtools/contact_state.py',
 'femtools/native_properties.py','femviewprovider/view_contact_state.py'):
 core.SOURCES['src/Mod/Fem/'+relative]='Mod/Fem/'+relative
for relative in ('ArchComponent.py','ArchStructure.py','TestArch.py','bimtests/TestArchShapeCleanup.py'):
 core.SOURCES['src/Mod/BIM/'+relative]='Mod/BIM/'+relative
for name in json.loads((REPO/'package/local-completion/freecad-960-validation.json').read_text())['source_inputs']:
 if name.startswith('src/Mod/Fem/') and name.endswith('.py'):
  core.SOURCES[name]=name.removeprefix('src/')
for name in ('contactstate.c','beamsection.c','beamsection.patch'):
 core.SOURCES['package/calculix/force-accounting/'+name]='data/NativeSolvers/source/'+name

def read(path): return json.loads(Path(path).read_text())

def source_gate(label,mode):
 directory=ROOT/label; proof=read(directory/'execution.json')
 assert proof['schema']=='FreeCAD-8rk-isolated-native-gate-v1'
 assert proof['mode']==mode and proof['source_commit']==core.COMMIT
 assert proof['passed'] is True and proof['returncode']==0 and not proof['timed_out']
 for name in ('child_reaped','process_group_gone','source_and_supervisor_unchanged','app_and_three_profiles_unchanged'):
  assert proof[name] is True,(label,name)
 assert proof['source_inputs_before']==proof['source_inputs_after']
 for path,wanted in proof['source_inputs_after'].items(): assert core.digest(path)==wanted,path
 assert core.digest(directory/'run.log')==proof['log_sha256']
 return proof

def compiled_identity():
 assert core.digest(ROOT/'identity.json')==IDENTITY_SHA
 assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()==core.COMMIT
 subprocess.run(['git','diff','--quiet','HEAD','--','src','tests/src','package/calculix'],cwd=REPO,check=True)
 values=dict(re.findall(r'^#define\s+(\w+)\s+"([^"]*)"',(core.BUILD/'src/Build/Version.h').read_text(),re.M))
 assert values['FCRepositoryHash']==core.COMMIT and values['FCRevision']==core.REVISION,values
 source_gate('build-latest','build')
 assert core.digest(core.BUILD/'data/NativeSolvers/ccx-force-accounting')==core.NATIVE_SHA
 if (ROOT/'build-identity.json').exists():
  for path,wanted in read(ROOT/'build-identity.json').items(): assert core.digest(path)==wanted,path
 return values

original_source_equal=core.source_equal
def source_equal(resources):
 original_source_equal(resources)
 binary=resources/'data/NativeSolvers/ccx-force-accounting'
 for option,wanted in (('--freecad-contact-state-version','CCX_CONTACT_STATE_V1'),
                       ('--freecad-beam-section-version','CCX_BEAM_SECTION_V1')):
  assert subprocess.check_output([str(binary),option],text=True,timeout=10).strip()==wanted

def application_gate(application,mode):
 location='stage' if application==core.STAGE else 'installed'
 assert application in (core.STAGE,core.APP)
 directory=ROOT/(location+'-'+mode)
 proof=read(directory/'execution.json');reg=read(directory/'regression.json')
 assert proof['schema']=='FreeCAD-960-literal-application-gate-v1'
 assert proof['passed'] is True and proof['application']==str(application)
 assert proof['mode']==mode and proof['location']==location and proof['source_commit']==core.COMMIT
 assert proof['revision']==core.REVISION and proof['native_sha256']==core.NATIVE_SHA
 for key in ('child_reaped','process_group_gone','application_unchanged','profiles_and_dependencies_unchanged','inputs_unchanged','strict_signature_verified','semantic_tests_passed'):
  assert proof[key] is True,key
 assert proof['returncode']==0 and proof['timed_out'] is False
 assert proof['inputs_before']==proof['inputs_after']
 for path,wanted in proof['inputs_after'].items(): assert core.digest(path)==wanted,path
 assert core.digest(directory/'run.log')==proof['log_sha256']
 assert core.digest(directory/'regression.json')==proof['regression_sha256']
 assert reg['passed'] is True and reg['application']==str(application)
 assert reg['schema']=='FreeCAD-960-installation-regression-v1'
 assert reg['commit']==core.COMMIT and reg['revision']==core.REVISION
 assert reg['native_sha256']==core.NATIVE_SHA
 count={'cmd':20,'gui':4,'cold':1}[mode]
 assert reg['mode']==mode and reg['expected_tests']==reg['executed_tests']==count
 assert proof['executed_tests']==count and proof['skipped_lines']==[]
 assert len(reg['selected_test_ids'])==len(set(reg['selected_test_ids']))==count
 assert reg['source_or_build_import_override'] is False
 assert reg['native_solver_override'] is False
 assert proof['source_or_build_import_override'] is False
 assert proof['native_solver_override'] is False
 assert reg['only_public_native_interfaces'] is True
 assert reg['original_project_opened_changed_or_solved'] is False
 assert core.inventory(application)==read(ROOT/'stage-inventory.json')
 return proof

def check_stage_receipts(sealed):
 import critical_pins
 compiled_identity();source_gate('ctest-latest','ctest');critical_pins.verify()
 assert core.inventory(core.STAGE)==sealed
 import audit_payload_stage as audit
 for mode in ('payload','stage','custody'):
  path=ROOT/('independent-'+{'payload':'payload-audit','stage':'stage-audit','custody':'stage-custody'}[mode]+'.json')
  audit.admit_producer(read(path),mode,commit=core.COMMIT,revision=core.REVISION)
 assert read(ROOT/'independent-stage-audit.json')['sealed_stage_inventory_sha256']==core.canonical_sha(sealed)
 for mode in ('cmd','gui','cold'): application_gate(core.STAGE,mode)

original_stage=core.stage
def stage():
 import audit_payload_stage as audit
 audit.admit_producer(read(ROOT/'independent-payload-audit.json'),'payload',commit=core.COMMIT,revision=core.REVISION)
 return original_stage()

core.compiled_identity=compiled_identity;core.source_equal=source_equal
core.no_live_app=run_gate.serial;core.HELPER={'no_live_app':lambda *_:run_gate.serial()}
core.check_stage_receipts=check_stage_receipts;core.stage=stage
globals().update({key:value for key,value in vars(core).items() if not key.startswith('__')})
if __name__=='__main__':
 for number in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(number,core.interrupted)
 assert sys.argv[1:] in (['stage'],['swap'])
 {'stage':core.stage,'swap':core.swap}[sys.argv[1]]()
