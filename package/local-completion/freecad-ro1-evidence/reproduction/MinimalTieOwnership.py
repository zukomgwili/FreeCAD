"""Minimal two-solid ordinary Tie export, using only native authoring/writing."""
import sys
sys.dont_write_bytecode = True
import hashlib
import json
import os
from pathlib import Path
import unittest
import FreeCAD as App
import ObjectsFem
from femmesh import gmshtools
from femtools.ccxtools import FemToolsCcx


class MinimalTieOwnership(unittest.TestCase):
    def test_stock_tie_writer_preserves_two_independent_coincident_faces(self):
        root = Path(os.environ["FREECAD_RO1_OUTPUT"])
        doc = App.newDocument("IndependentTie")
        report = {"passed": False, "runtime": App.Version(), "home": App.getHomePath(),
                  "solver_run": False, "manual_mesh_or_group_repair": False}
        try:
            first = doc.addObject("Part::Box", "First")
            second = doc.addObject("Part::Box", "Second")
            second.Placement.Base = App.Vector(10, 0, 0)
            shape = doc.addObject("Part::Compound", "Compound")
            shape.Links = [first, second]
            analysis = ObjectsFem.makeAnalysis(doc)
            solver = ObjectsFem.makeSolverCalculiXCcxTools(doc)
            analysis.addObject(solver)
            material = ObjectsFem.makeMaterialSolid(doc)
            material.Material = {"Name": "Steel", "YoungsModulus": "200000 MPa",
                                 "PoissonRatio": "0.3", "Density": "7900 kg/m^3"}
            analysis.addObject(material)
            tie = ObjectsFem.makeConstraintTie(doc, "Tie")
            tie.References = [(first, ["Face2"]), (second, ["Face1"])]
            tie.Tolerance = 0
            analysis.addObject(tie)
            mesh = ObjectsFem.makeMeshGmsh(doc, "Mesh")
            mesh.Shape = shape
            mesh.ElementOrder = "2nd"
            mesh.SecondOrderLinear = False
            mesh.CoherenceMesh = False
            mesh.CharacteristicLengthMax = 5
            mesh.CharacteristicLengthMin = 3
            mesh.WorkingDirectory = str(root)
            analysis.addObject(mesh)
            doc.recompute()
            a, b = first.Shape.Faces[1], second.Shape.Faces[0]
            self.assertFalse(a.isSame(b))
            self.assertLess((a.CenterOfMass - b.CenterOfMass).Length, 1e-10)
            self.assertAlmostEqual(a.Area, 100, places=10)
            mesher = gmshtools.GmshTools(mesh)
            mesher.create_mesh()
            self.assertEqual(mesher.process.exitCode(), 0)
            fm = mesh.FemMesh
            groups = {fm.getGroupName(g): sorted(fm.getGroupElements(g)) for g in fm.Groups}
            solid = {name: set(groups[name]) for name in ("Solid1", "Solid2")}
            expected = []
            for face, owner in (("Face2", "Solid1"), ("Face7", "Solid2")):
                volumes = set()
                for face_id in groups[face]:
                    nodes = set(fm.getElementNodes(face_id))
                    owning = [v for v in fm.Volumes if nodes <= set(fm.getElementNodes(v))]
                    self.assertEqual(len(owning), 1)
                    self.assertIn(owning[0], solid[owner])
                    volumes.add(owning[0])
                self.assertTrue(volumes)
                expected.append(volumes)
            fea = FemToolsCcx(analysis=analysis, solver=solver)
            fea.update_objects()
            fea.setup_working_dir(str(root))
            fea.write_inp_file()
            deck = Path(fea.inp_file_name)
            surfaces, current = {}, None
            for line in deck.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("**"):
                    continue
                if line.startswith("*"):
                    current = None
                    if line.upper().startswith("*SURFACE,"):
                        current = next(p.split("=", 1)[1].strip() for p in line.split(",")
                                       if p.strip().upper().startswith("NAME="))
                        surfaces[current] = []
                elif current:
                    volume, side = [p.strip() for p in line.split(",")]
                    surfaces[current].append([int(volume), int(side[1:])])
            names = ("TIE_DEP" + tie.Name, "TIE_IND" + tie.Name)
            report.update(deck=str(deck), deck_sha256=hashlib.sha256(deck.read_bytes()).hexdigest(),
                          mesh_volumes=fm.VolumeCount,
                          expected_faces=[len(groups[n]) for n in ("Face2", "Face7")],
                          sides={name: {"facets": surfaces[name], "count": len(surfaces[name]),
                                        "owners": {n: sum(v in ids for v, _ in surfaces[name])
                                                   for n, ids in solid.items()}}
                                 for name in names})
            self.assertEqual(groups, {fm.getGroupName(g): sorted(fm.getGroupElements(g)) for g in fm.Groups})
            for name, face, wanted in zip(names, ("Face2", "Face7"), expected):
                self.assertEqual(len(surfaces[name]), len(groups[face]), report["sides"])
                self.assertEqual({v for v, _ in surfaces[name]}, wanted)
            report["passed"] = True
        finally:
            (root / "report.json").write_text(json.dumps(report, indent=2) + "\n")
            App.closeDocument(doc.Name)
