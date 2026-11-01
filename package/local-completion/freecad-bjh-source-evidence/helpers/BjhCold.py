"""Separate-process historical restore of literal native network observations."""
import hashlib
import json
import os
from pathlib import Path
import unittest

import FreeCAD as App


class TestNativeNetworkCold(unittest.TestCase):
    def test_network_history_and_physical_authoring_restore_without_current_promotion(self):
        root=Path(os.environ['BJH_COLD_SOURCE'])
        reports=[]
        for case in sorted(root.iterdir()):
            documents=list(case.glob('*.FCStd')) if case.is_dir() else []
            if not documents:continue
            self.assertEqual(len(documents),1)
            path=documents[0]
            original=path.read_bytes()
            expected=(case/'section-data.json').read_text()
            data=json.loads(expected)
            doc=App.openDocument(str(path))
            try:
                results=[o for o in doc.Objects if getattr(getattr(o,'Proxy',None),'Type','')=='Fem::BeamSectionForceResult']
                self.assertEqual(len(results),1)
                result=results[0]
                self.assertEqual(result.SectionData,expected)
                self.assertEqual(result.SectionHash,hashlib.sha256(expected.encode()).hexdigest())
                self.assertFalse(result.CompletedRun)
                self.assertTrue(result.Status.startswith('Historical'),result.Status)
                self.assertEqual(result.Proxy.getSectionForces(result,historical=True),data)
                coupling=data['provenance']['coupling']
                self.assertEqual(result.Mesh.FemMesh.NodeCount,len(coupling['nodes']))
                self.assertEqual(result.Mesh.FemMesh.EdgeCount,len(data['provenance']['elements']))
                self.assertFalse(result.Mesh.FemMesh.FaceCount or result.Mesh.FemMesh.VolumeCount)
                for key in ('analysis','solver','mesh'):
                    source=getattr(result,key.capitalize())
                    self.assertEqual(source.Name,data['provenance']['case'][key])
                self.assertTrue(result.Solver.BeamSectionForces)
                self.assertFalse(result.Solver.NativeForceAccounting)
                self.assertFalse(result.Solver.NativeContactOutputs)
                self.assertFalse(result.Solver.NativeAccountingSupports)
                for spring in coupling['springs']:
                    obj=doc.getObject(spring['owner'])
                    self.assertEqual(obj.Attachment,'Vertices')
                    self.assertEqual(obj.Kind,'Translational')
                    self.assertEqual(obj.Mode,'Ground' if spring['mode']=='GROUND' else 'Two points')
                    self.assertEqual(obj.Axis,'XYZ'[spring['direction']-1])
                    self.assertEqual(obj.Stiffness.getValueAs('N/mm').Value,spring['authored_stiffness_N_per_mm'])
                    self.assertTrue(obj.End1[0])
                    if spring['mode']=='TWO_POINTS':self.assertTrue(obj.End2[0])
                for guide in coupling['supports']:
                    obj=doc.getObject(guide['owner'])
                    self.assertTrue(obj.xFree)
                    self.assertFalse(any(getattr(obj,p) for p in ('yFree','zFree','rotxFree','rotyFree','rotzFree')))
                    for p in ('yDisplacement','zDisplacement'):
                        self.assertEqual(getattr(obj,p).getValueAs('mm').Value,0)
                    for p in ('xRotation','yRotation','zRotation'):
                        self.assertEqual(getattr(obj,p).getValueAs('rad').Value,0)
                for name,material in coupling['materials'].items():
                    obj=doc.getObject(name)
                    self.assertEqual(App.Units.Quantity(obj.Material['YoungsModulus']).getValueAs('MPa').Value,material['youngs_modulus_MPa'])
                    self.assertEqual(float(obj.Material['PoissonRatio']),material['poisson_ratio'])
                for name,section in coupling['sections'].items():
                    obj=doc.getObject(name)
                    self.assertEqual([obj.RectWidth.getValueAs('mm').Value,obj.RectHeight.getValueAs('mm').Value],section['dimensions_mm'])
                for source in coupling['sources']:
                    obj=doc.getObject(source['owner'])
                    vector=App.Vector(obj.DirectionVector)*obj.Force.getValueAs('N').Value
                    for a,b in zip(vector,source['force_global']):self.assertAlmostEqual(a,b,delta=1e-12)
                mechanical=[o for o in doc.Objects if o.isDerivedFrom('Fem::FemResultObject')]
                self.assertEqual(len(mechanical),1)
                self.assertEqual(len(mechanical[0].NodeNumbers),len(coupling['nodes']))
                self.assertEqual(len(mechanical[0].DisplacementVectors),len(coupling['nodes']))
                for p in ('NodeStressXX','NodeStressYY','NodeStressZZ','NodeStressXY','NodeStressXZ','NodeStressYZ'):
                    self.assertFalse(getattr(mechanical[0],p))
                with self.assertRaises(ValueError):result.Proxy.getSectionForces(result)
                self.assertFalse(result.CompletedRun)
                self.assertFalse(result.Status.startswith('Current'))
                self.assertEqual(result.SectionData,expected)
                self.assertEqual(path.read_bytes(),original)
                reports.append({'case':case.name,'document_sha256':hashlib.sha256(original).hexdigest(),
                                'section_hash':result.SectionHash,'components':len(coupling['components']),
                                'native_knots':len(data['frames'][0]['native_actions']['knot_algebraic_spcs']),
                                'saved_physical_parameters_preserved':True,'mechanical_displacement_only_preserved':True,
                                'solver_executed':False,'current_available':False})
            finally:App.closeDocument(doc.Name)
        self.assertGreaterEqual(len(reports),2)
        directory=Path(os.environ['BJH_CASE_ROOT']);directory.mkdir()
        (directory/'cold-observation.json').write_text(json.dumps(reports,indent=2))
