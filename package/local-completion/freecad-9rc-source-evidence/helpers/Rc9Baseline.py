"""Fresh installed GUI characterization of the intentional coupled-contact refusal."""
import hashlib
import json
import os
from pathlib import Path
import unittest
import FreeCAD as App
import FreeCADGui as Gui
import FemGui
from Rc9Fixture import make_case
from femtools.ccxtools import FemToolsCcx

class TestInstalledRefusal(unittest.TestCase):
 def test_real_two_solid_contact_is_refused_without_creating_current_results(self):
  self.assertTrue(App.GuiUp)
  self.assertEqual(App.Version()[-1],'2f6ed5df7bd9786449230ad01366a7d8e10ae0e2')
  self.assertEqual(Path(App.getHomePath()).resolve(),Path('/Applications/FreeCAD-27.1.0.app/Contents/Resources'))
  directory=Path(os.environ['R9_CASE_ROOT']);directory.mkdir()
  previous=App.activeDocument();previous_name=previous.Name if previous else None
  doc=App.newDocument('CoupledContactInstalledBaseline')
  try:
   model=make_case(doc)
   for body in (model.solid,model.backing):
    self.assertTrue(body.Shape.isValid());self.assertAlmostEqual(body.Shape.Volume,1500.,delta=1e-9)
   self.assertEqual(model.mesh.FemMesh.NodeCount,17)
   self.assertEqual(model.mesh.FemMesh.VolumeCount,6)
   self.assertEqual(model.rbe.TranslationalModeX,'Free')
   FemGui.setActiveAnalysis(model.analysis)
   for obj in doc.Objects:
    if hasattr(obj,'ViewObject'):obj.ViewObject.Visibility=False
   for obj in (model.geometry,model.solid,model.backing):obj.ViewObject.Visibility=True
   Gui.activeDocument().activeView().viewAxonometric();Gui.activeDocument().activeView().fitAll();Gui.updateGui()
   doc.saveAs(str(directory/'coupled-contact.FCStd'))
   Gui.getMainWindow().grab().save(str(directory/'native-geometry.png'))
   observed=[]
   for selected in (True,False):
    model.solver.NativeContactOutputs=[model.contact] if selected else []
    doc.recompute()
    work=directory/('selected' if selected else 'contact-only');work.mkdir()
    fea=FemToolsCcx(analysis=model.analysis,solver=model.solver)
    fea.update_objects();fea.setup_working_dir(str(work))
    with self.assertRaises(ValueError) as caught:fea.write_inp_file()
    message=str(caught.exception)
    self.assertIn('contact',message.lower())
    self.assertFalse(list(work.glob('*.beam-section*')))
    observed.append({'native_contact_outputs_selected':selected,'exception':type(caught.exception).__name__,'message':message})
    print('INSTALLED_CONTACT_REFUSAL '+json.dumps(observed[-1]))
   self.assertFalse(any(getattr(getattr(o,'Proxy',None),'Type','') in ('Fem::BeamSectionForceResult','Fem::ContactStateResult') for o in doc.Objects))
   record={'runtime':App.Version(),'gui':True,'home':App.getHomePath(),'observations':observed,'native_solver_override':model.solver.NativeAccountingSolver,'physical_guide':{k:getattr(model.rbe,k) for k in ('TranslationalModeX','TranslationalModeY','TranslationalModeZ','RotationalModeX','RotationalModeY','RotationalModeZ')},'original_beam_nodes':list(model.beam_nodes),'loaded_solid_nodes':list(model.solid_nodes),'backing_nodes':list(range(301,307)),'all_solid_nodes_disjoint_from_beam':True,'project_model_opened':False,'solver_executed':False}
   (directory/'observation.json').write_text(json.dumps(record,indent=2)+'\n')
  finally:
   FemGui.setActiveAnalysis();App.closeDocument(doc.Name)
   if previous_name in App.listDocuments():App.setActiveDocument(previous_name)
