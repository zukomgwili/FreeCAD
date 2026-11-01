"""Native GUI characterization of an authored branching spring composition."""
import hashlib
import json
import os
from pathlib import Path
import unittest

import FreeCAD as App
import FreeCADGui as Gui
import FemGui
import ObjectsFem
from PySide import QtWidgets

from femtest.app.test_beam_section_forces_native import make_torsion_case
from femtools.ccxtools import FemToolsCcx


class TestBranchingSpringBaseline(unittest.TestCase):
    def test_stock_gui_writer_characterizes_two_source_t_on_ground_spring(self):
        self.assertTrue(App.GuiUp)
        directory=Path(os.environ['BJH_CASE_ROOT']);directory.mkdir()
        doc=App.newDocument('BranchingNativeBaseline')
        try:
            model=make_torsion_case(doc)
            doc.removeObject('Fixed')
            direction=doc.LoadDirection
            direction.X2,direction.Y2,direction.Z2=1.,0.,0.
            for force,value in ((model.force,1.),(model.negative_force,2.)):
                force.Force=f'{value:.17g} N'
                force.Direction=(direction,['Edge1'])
                force.Reversed=False
            guide=ObjectsFem.makeConstraintDisplacement(doc,'PhysicalRootGuide')
            guide.References=[(model.stem,['Vertex1'])]
            guide.xFree=True
            guide.yFree=guide.zFree=False
            guide.rotxFree=guide.rotyFree=guide.rotzFree=False
            guide.yDisplacement=guide.zDisplacement='0 mm'
            guide.xRotation=guide.yRotation=guide.zRotation='0 rad'
            model.analysis.addObject(guide)
            spring=ObjectsFem.makeConstraintElasticConnector(doc,'RootSpring')
            spring.Attachment='Vertices'
            spring.Kind='Translational'
            spring.Mode='Ground'
            spring.End1=(model.stem,['Vertex1'])
            spring.Axis='X'
            spring.Stiffness='10000 N/mm'
            model.analysis.addObject(spring)
            doc.recompute()
            FemGui.setActiveAnalysis(model.analysis)
            Gui.activeDocument().activeView().viewAxonometric()
            Gui.activeDocument().activeView().fitAll()
            Gui.updateGui()
            fea=FemToolsCcx(analysis=model.analysis,solver=model.solver)
            fea.update_objects();fea.setup_working_dir(str(directory))
            prerequisite=fea.check_prerequisites()
            refusal=None
            try:
                fea.write_inp_file()
            except ValueError as error:
                refusal=str(error)
            report={'freecad_version':App.Version(),'gui_up':bool(App.GuiUp),
                    'app_home':App.ConfigGet('AppHomePath'),
                    'fixture':'Existing genuine shared-node V1 T frame, two positive axial tip forces, nonzero root SPRING1 path and five explicit physical zero guides',
                    'mesh_nodes':model.mesh.FemMesh.NodeCount,
                    'mesh_edges':model.mesh.FemMesh.EdgeCount,
                    'mesh_volumes':model.mesh.FemMesh.VolumeCount,
                    'force_owners':[model.force.Name,model.negative_force.Name],
                    'root_spring_stiffness_N_per_mm':spring.Stiffness.getValueAs('N/mm').Value,
                    'prerequisites':prerequisite,'writer_value_error':refusal,
                    'solver_executed':False,'project_model_opened':False,
                    'has_current_native_result':any(getattr(o,'CompletedRun',False) for o in model.analysis.Group)}
            (directory/'observation.json').write_text(json.dumps(report,indent=2))
            self.assertTrue(refusal,'Stock export succeeded; characterize support rather than assume refusal')
            self.assertFalse(report['has_current_native_result'])
            App.Console.PrintError('Branching spring export: '+refusal+'\n')
            window=Gui.getMainWindow()
            for dock in window.findChildren(QtWidgets.QDockWidget):
                if 'report' in dock.windowTitle().lower():dock.show()
            Gui.updateGui()
            self.assertTrue(window.grab().save(str(directory/'stock-refusal.png')))
            doc.saveAs(str(directory/'branching-baseline.FCStd'))
        finally:
            FemGui.setActiveAnalysis()
            App.closeDocument(doc.Name)
