"""First public compression tracer; independent controls live in frozen oracles."""
from pathlib import Path
import json
import os
import unittest
import FreeCAD as App
from Rc9Fixture import make_case
from femtools.ccxtools import FemToolsCcx

class TestCoupledCompression(unittest.TestCase):
 def test_native_beam_solid_contact_and_local_state_share_one_completed_case(self):
  doc=App.newDocument('CoupledContactCompression')
  try:
   model=make_case(doc)
   directory=Path(os.environ['R9_CASE_ROOT']);directory.mkdir()
   if os.environ.get('R9_TEST_SOLVER'):model.solver.NativeAccountingSolver=os.environ['R9_TEST_SOLVER']
   fea=FemToolsCcx(analysis=model.analysis,solver=model.solver)
   fea.update_objects();fea.setup_working_dir(str(directory))
   self.assertFalse(fea.write_inp_file())
   original=Path(fea.inp_file_name).read_bytes()
   self.assertEqual(fea.ccx_run(),0,fea.ccx_stdout+fea.ccx_stderr)
   self.assertEqual(Path(fea.inp_file_name).read_bytes(),original)
   fea.load_results()
   beam=next(o for o in model.analysis.Group if getattr(getattr(o,'Proxy',None),'Type','')=='Fem::BeamSectionForceResult')
   contact=next(o for o in model.analysis.Group if getattr(getattr(o,'Proxy',None),'Type','')=='Fem::ContactStateResult')
   data=beam.Proxy.getSectionForces(beam)
   local=contact.Proxy.getContactStates(contact)
   self.assertEqual(data['schema'],'CCX_BEAM_SECTION_V4')
   self.assertEqual(local['schema'],'CCX_CONTACT_STATE_V1')
   self.assertTrue(beam.Status.startswith('Current'),beam.Status)
   self.assertTrue(contact.Status.startswith('Current'),contact.Status)
   for frame in data['frames']:
    self.assertEqual((frame['step'],frame['time']),(1,1.))
    for row in frame['samples']:
     expected=100. if row['end']==1 else -100.
     self.assertAlmostEqual(row['force_global'][0],expected,delta=.1)
   (directory/'observed-beam.json').write_text(json.dumps(data,indent=2))
   (directory/'observed-contact.json').write_text(json.dumps(local,indent=2))
   doc.saveAs(str(directory/'coupled-contact.FCStd'))
  finally:App.closeDocument(doc.Name)
