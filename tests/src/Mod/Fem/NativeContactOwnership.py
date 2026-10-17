# SPDX-License-Identifier: LGPL-2.1-or-later

"""Opt-in exact R27 native contact-ownership witness for FreeCAD-bt9.

Run native FreeCAD -P tests/src/Mod/Fem -t NativeContactOwnership with
FREECAD_BT9_INPUT pointing to the immutable qualified owned.FCStd and
FREECAD_BT9_DIRECTORY naming disposable evidence. Run FREECAD_BT9_STAGE=create,
then stage=reopen in a separate process with the same input and directory.
Optional FREECAD_BT9_EXPECTED_COMMIT and FREECAD_BT9_EXPECTED_RESOURCES guard
the runtime and loaded module origins. No mesher, solver or preferences change.

The oracle independently matches each complete six-node native face element to
its unique ten-node volume and checks the original solid groups. Frozen side
labels below were observed in the retained stock fragment AFTER independent UNV
owner classification; they are not a claim of independently deriving CalculiX's
side convention. Cold restore maps these labels by complete connectivity, never
by assuming serialized, UNV and VTK element numbers are interchangeable.
Only assertions use the frozen expectations: no mesh or solver sets are repaired.
"""

import hashlib
import io
import json
import os
from pathlib import Path
import traceback
from types import SimpleNamespace
import unittest
from zipfile import ZipFile

import FreeCAD as App
import Fem
import ObjectsFem
import Part
from femmesh import meshsetsgetter, meshtools
from femsolver.calculix import calculixutils, write_constraint_contact
from femtools import elastic_connector


WITNESS_SHA256 = "fcc5b43e2d0663f0b5222c98d81ffeeec669bad93d8b78d9321951489d377387"
RETAINED_FACETS = {
    "Face2": [(412, 1), (524, 2), (525, 3), (531, 1), (532, 1), (557, 4),
              (558, 4), (561, 1), (563, 4), (572, 1), (580, 1), (581, 4),
              (584, 4), (586, 3), (588, 2), (590, 4), (592, 3), (595, 4)],
    "Face7": [(659, 1), (693, 1), (704, 1), (705, 2), (709, 2), (710, 4),
              (717, 1), (722, 3), (741, 4), (742, 4), (766, 1), (769, 3),
              (772, 1), (773, 4), (775, 1), (776, 4), (779, 4), (780, 3)],
}


@unittest.skipUnless(os.environ.get("FREECAD_BT9_INPUT")
                     and os.environ.get("FREECAD_BT9_DIRECTORY"),
                     "Requires an immutable R27 input and disposable evidence directory")
class NativeContactOwnership(unittest.TestCase):
    @staticmethod
    def digest(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    @staticmethod
    def json_digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    def objects(self):
        names = ("TouchingFootprints", "RBERC", "RBELedger", "PortRegionAnalysis",
                 "PortRegionMesh", "RegionConnector")
        values = [self.doc.getObject(name) for name in names]
        self.assertTrue(all(value is not None for value in values))
        self.assertTrue(all(value.ViewObject is not None for value in values))
        return values

    @staticmethod
    def link_graph(part):
        graph = {}

        def encode(value):
            if hasattr(value, "Document") and hasattr(value, "Name"):
                key = ("local" if value.Document == part.Document
                       else value.Document.FileName, value.Name)
                text = json.dumps(key)
                if text not in graph:
                    graph[text] = {}
                    graph[text].update({name: encode(value.getPropertyByName(name))
                                        for name in sorted(value.PropertiesList)
                                        if "Link" in value.getTypeIdOfProperty(name)})
                return list(key)
            if isinstance(value, (list, tuple)):
                return [encode(item) for item in value]
            return value

        encode(part)
        return graph

    def geometry(self):
        # Preserve the observation order of the original qualified observer.
        compound = self.doc.getObject("TouchingFootprints")
        rc = self.doc.getObject("RCFootprint")
        ledger = self.doc.getObject("LedgerFootprint")
        self.assertEqual(compound.Links, [rc, ledger])
        self.assertEqual([rc.Length.Value, rc.Width.Value, rc.Height.Value], [180, 100, 80])
        self.assertEqual([ledger.Length.Value, ledger.Width.Value, ledger.Height.Value],
                         [95, 100, 80])
        center = App.Vector(62.5, 2843, 5835)
        faces = [rc.getSubObject("Face2"), ledger.getSubObject("Face1")]
        self.assertFalse(faces[0].isSame(faces[1]))
        for face in faces:
            self.assertLess((face.CenterOfMass - center).Length, 1e-8)
            self.assertAlmostEqual(face.Area, 8000, places=8)
        return {"source_geometry": meshtools.get_mesh_geometry_signature(compound),
                "face_areas_mm2": [face.Area for face in faces],
                "face_centers_mm": [list(face.CenterOfMass) for face in faces],
                "independent_native_faces": True}

    def settings(self):
        compound, first, second, analysis, mesh, connector = self.objects()
        self.assertEqual(mesh.Shape, compound)
        self.assertEqual(mesh.ElementOrder, "2nd")
        self.assertEqual(mesh.CharacteristicLengthMax.Value, 40)
        self.assertEqual(mesh.CharacteristicLengthMin.Value, 20)
        self.assertFalse(mesh.CoherenceMesh)
        self.assertEqual(connector.Attachment, "Rigid body ports")
        self.assertEqual(connector.Kind, "Translational")
        self.assertEqual(connector.Mode, "Two points")
        self.assertEqual(connector.Axis, "Y")
        self.assertEqual(connector.Stiffness.getValueAs("N/mm").Value, 1000)
        self.assertEqual([connector.RigidBody1, connector.RigidBody2], [first, second])
        members = [first, second, mesh, connector]
        contact = self.doc.getObject("OwnedFaceContact")
        self.assertEqual(analysis.Group, members + ([contact] if contact else []))
        for body, owner, name, entity in ((first, "RCFootprint", "Face2", "Face2"),
                                          (second, "LedgerFootprint", "Face1", "Face7")):
            self.assertEqual(body.References, [(self.doc.getObject(owner), (name,))])
            self.assertEqual(list(body.ReferenceNode), [62.5, 2843, 5835])
            self.assertEqual(meshtools.get_reference_group_elements(body, compound)[1], [entity])
        general = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/General")
        return {"Shape": mesh.Shape.Name, "ElementOrder": mesh.ElementOrder,
                "ElementDimension": mesh.ElementDimension,
                "CharacteristicLengthMax_mm": mesh.CharacteristicLengthMax.Value,
                "CharacteristicLengthMin_mm": mesh.CharacteristicLengthMin.Value,
                "CoherenceMesh": mesh.CoherenceMesh,
                "GeometryTolerance": mesh.GeometryTolerance,
                "AnalysisGroupMeshing": general.GetBool("AnalysisGroupMeshing"),
                "RBE_references": [[[owner.Name, list(names)] for owner, names in body.References]
                                   for body in (first, second)],
                "RBE_reference_positions_mm": [list(body.ReferenceNode)
                                               for body in (first, second)],
                "connector": {"Attachment": connector.Attachment, "Kind": connector.Kind,
                              "Mode": connector.Mode, "Axis": connector.Axis,
                              "stiffness_N_per_mm": 1000},
                "provenance": {"names": list(mesh.ElementGroupNames),
                               "references": [[owner.Name, list(names)]
                                              for owner, names in mesh.ElementGroupReferences],
                               "geometry": mesh.ElementGroupGeometry}}

    def group(self, name):
        fm = self.doc.getObject("PortRegionMesh").FemMesh
        groups = [g for g in fm.Groups if fm.getGroupName(g) == name]
        self.assertEqual(len(groups), 1, name)
        return set(fm.getGroupElements(groups[0]))

    def topology_digest(self):
        fm = self.doc.getObject("PortRegionMesh").FemMesh
        # Serialization can renumber elements, so exclude element IDs.
        nodes = [(node, list(point)) for node, point in sorted(fm.Nodes.items())]
        elements = {kind: sorted(sorted(fm.getElementNodes(element))
                                 for element in getattr(fm, kind))
                    for kind in ("Edges", "Faces", "Volumes")}
        return self.json_digest({"nodes": nodes, "elements": elements})

    def mesh_snapshot(self):
        fm = self.doc.getObject("PortRegionMesh").FemMesh
        groups = sorted((fm.getGroupName(group), fm.getGroupElementType(group),
                         sorted(fm.getGroupElements(group))) for group in fm.Groups)
        return {"topology_sha256": self.topology_digest(),
                "groups_sha256": self.json_digest(groups)}

    def incidence_oracle(self, previous=None):
        fm = self.doc.getObject("PortRegionMesh").FemMesh
        ordered = {element: list(fm.getElementNodes(element)) for element in fm.Volumes}
        volumes = {element: set(nodes) for element, nodes in ordered.items()}
        self.assertTrue(all(len(nodes) == 10 for nodes in volumes.values()))
        solids = {name: self.group(name) for name in ("Solid1", "Solid2")}
        self.assertFalse(solids["Solid1"] & solids["Solid2"])
        self.assertEqual(solids["Solid1"] | solids["Solid2"], set(volumes))
        result = {}
        for face, solid in (("Face2", "Solid1"), ("Face7", "Solid2")):
            face_elements = self.group(face)
            self.assertEqual(len(face_elements), 18)
            self.assertTrue(face_elements <= set(fm.Faces))
            old = previous["regions"][face] if previous else None
            labels = ({(tuple(item["volume_nodes"]), tuple(item["face_nodes"])): item["side"]
                       for item in old["connectivity"]} if old else None)
            retained = dict(RETAINED_FACETS[face])
            facets, connectivity, nodes = [], [], set()
            for element in sorted(face_elements):
                face_nodes = set(fm.getElementNodes(element))
                self.assertEqual(len(face_nodes), 6)
                matches = [volume for volume, values in volumes.items() if face_nodes <= values]
                self.assertEqual(len(matches), 1, "Full quadratic face must have one native owner")
                volume = matches[0]
                self.assertIn(volume, solids[solid])
                fingerprint = (tuple(sorted(volumes[volume])), tuple(sorted(face_nodes)))
                side = labels[fingerprint] if labels is not None else retained[volume]
                facets.append([volume, side])
                connectivity.append({"volume_nodes": list(fingerprint[0]),
                                     "volume_node_order": ordered[volume],
                                     "face_nodes": list(fingerprint[1]), "side": side})
                nodes.update(face_nodes)
            self.assertEqual(len(nodes), 47)
            if old is None:
                self.assertEqual(sorted(facets), [list(pair) for pair in RETAINED_FACETS[face]])
            result[face] = {"solid": solid, "facets": sorted(facets),
                            "nodes": sorted(nodes),
                            "connectivity": sorted(connectivity,
                                                   key=lambda item: item["face_nodes"])}
            if old is not None:
                self.assertEqual(result[face]["connectivity"], old["connectivity"])
                self.assertEqual(result[face]["nodes"], old["nodes"])
        a, b = [set(result[face]["nodes"]) for face in ("Face2", "Face7")]
        self.assertFalse(a & b)
        self.assertEqual({tuple(fm.Nodes[node]) for node in a},
                         {tuple(fm.Nodes[node]) for node in b})
        return {"method": "complete six-node face to unique ten-node volume incidence",
                "side_label_origin": "frozen retained stock labels after independent UNV owners",
                "regions": result, "owner_intersection": [],
                "counts": {"nodes": fm.NodeCount, "volumes": fm.VolumeCount,
                           "faces": fm.FaceCount, "groups": fm.GroupCount},
                "topology_sha256": self.topology_digest()}

    def rbe_precheck(self, oracle):
        mesh = self.doc.getObject("PortRegionMesh")
        result = []
        for name, face in (("RBERC", "Face2"), ("RBELedger", "Face7")):
            body = self.doc.getObject(name)
            expected = set(oracle["regions"][face]["nodes"])
            public = set(meshtools.get_femnodes_by_femobj_with_references(
                mesh.FemMesh, {"Object": body}))
            explicit = set(meshtools.get_femnodes_by_femobj_with_references(
                mesh.FemMesh, {"Object": body}, mesh))
            self.assertEqual(public, expected)
            self.assertEqual(explicit, expected)
            port = set(elastic_connector.rigid_body_nodes(body, mesh))
            self.assertEqual(port, expected)
            result.append({"body": name, "public_node_ids": sorted(public),
                           "explicit_node_ids": sorted(explicit), "port_node_ids": sorted(port)})
        return {"regions": result, "owned_node_counts": [47, 47], "intersection": []}

    def contact(self, create=False):
        contact = self.doc.getObject("OwnedFaceContact")
        references = [(self.doc.getObject("RCFootprint"), ("Face2",)),
                      (self.doc.getObject("LedgerFootprint"), ("Face1",))]
        if contact is None and create:
            contact = ObjectsFem.makeConstraintContact(self.doc, "OwnedFaceContact")
            contact.References = references
            contact.Adjust = "0 mm"
            self.doc.getObject("PortRegionAnalysis").addObject(contact)
            self.doc.recompute()
        self.assertIsNotNone(contact, "Cold restore must retain the saved contact")
        self.assertIsNotNone(contact.ViewObject)
        self.assertEqual(contact.References, references)
        self.assertEqual(contact.Adjust.Value, 0)
        self.assertIn(contact, self.doc.getObject("PortRegionAnalysis").Group)
        return contact

    @staticmethod
    def parse_surfaces(text):
        result, current = {}, None
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("**"):
                continue
            if line.startswith("*"):
                if not line.upper().startswith("*SURFACE,"):
                    raise AssertionError("Expected only the stock surface fragment")
                fields = [item.strip() for item in line.split(",")]
                current = next(item.split("=", 1)[1] for item in fields
                               if item.upper().startswith("NAME="))
                if current in result:
                    raise AssertionError("Duplicate native surface")
                result[current] = []
            else:
                element, side = [item.strip() for item in line.split(",")]
                if current is None or not side.startswith("S"):
                    raise AssertionError("Malformed native surface fragment")
                result[current].append([int(element), int(side[1:])])
        return result

    def check_contact(self, oracle, report, key):
        contact = self.contact()
        before = self.mesh_snapshot()
        analysis, mesh = [self.doc.getObject(name)
                          for name in ("PortRegionAnalysis", "PortRegionMesh")]
        row = {"Object": contact}
        getter = meshsetsgetter.MeshSetsGetter(
            analysis, SimpleNamespace(AnalysisType="static", ModelSpace="3D"), mesh,
            SimpleNamespace(cons_contact=[row]))
        # This is the actual production call path, not the incidence oracle.
        for name, mask in calculixutils.define_masks(SimpleNamespace(ModelSpace="3D")).items():
            setattr(getter, "mask_" + name, mask)
        getter.get_constraints_contact_faces()
        solids = {name: self.group(name) for name in ("Solid1", "Solid2")}
        sides = {}
        for name in ("ContactSlaveFaces", "ContactMasterFaces"):
            self.assertEqual(len(row[name]), 1)
            reference, facets, sub = row[name][0]
            facets = [list(pair) for pair in facets]
            sides[name] = {"reference": [reference[0].Name, list(reference[1])],
                           "is_sub_element": sub, "facets": sorted(facets),
                           "facet_count": len(facets),
                           "solid_owner_counts": {solid: sum(e in ids for e, _ in facets)
                                                  for solid, ids in solids.items()}}
        stream = io.StringIO()
        write_constraint_contact.write_meshdata_constraint(stream, row, contact, None)
        text = stream.getvalue()
        output = self.work / f"{key}-surfaces.inc"
        with output.open("x") as handle:
            handle.write(text)
        written = self.parse_surfaces(text)
        actual = {"getter": sides, "writer_surfaces": written,
                  "fragment": str(output), "fragment_sha256": self.digest(output),
                  "mesh_before": before,
                  "references": [[owner.Name, list(names)] for owner, names in contact.References]}
        report[key] = actual  # Retain wrong-owner observations before assertions go red.
        actual["rbe_after_contact"] = self.rbe_precheck(oracle)
        actual["mesh_after"] = self.mesh_snapshot()
        self.assertEqual(actual["mesh_after"], before,
                         "Contact lookup/writer must not repair mesh groups or connectivity")
        pairs = (("ContactSlaveFaces", "Face2", "Solid1", "RCFootprint", "Face2", "DEP"),
                 ("ContactMasterFaces", "Face7", "Solid2", "LedgerFootprint", "Face1", "IND"))
        for name, face, solid, owner, subelement, prefix in pairs:
            expected = oracle["regions"][face]["facets"]
            observed = sides[name]
            self.assertEqual(observed["reference"], [owner, [subelement]])
            self.assertTrue(observed["is_sub_element"])
            self.assertEqual(observed["facet_count"], 18)
            self.assertEqual(len({tuple(pair) for pair in observed["facets"]}), 18)
            self.assertEqual(observed["facets"], expected)
            self.assertEqual(observed["solid_owner_counts"],
                             {name: 18 if name == solid else 0 for name in solids})
            self.assertEqual(sorted(written[prefix + contact.Name]), expected)
        self.assertEqual(set(written), {"DEP" + contact.Name, "IND" + contact.Name})
        self.assertFalse({tuple(pair) for pair in sides["ContactSlaveFaces"]["facets"]}
                         & {tuple(pair) for pair in sides["ContactMasterFaces"]["facets"]})
        return actual

    def observe(self, report, previous=None):
        compound = self.doc.getObject("TouchingFootprints")
        mesh = self.doc.getObject("PortRegionMesh")
        report["stored_geometry_signature"] = mesh.ElementGroupGeometry
        report["native_input_link_graph"] = self.link_graph(compound)
        report["signature_observations"] = {
            "before_geometry": meshtools.get_mesh_geometry_signature(compound)}
        report["geometry"] = self.geometry()
        report["signature_observations"]["after_geometry"] = (
            meshtools.get_mesh_geometry_signature(compound))
        report["settings"] = self.settings()
        report["signature_observations"]["after_settings"] = (
            meshtools.get_mesh_geometry_signature(compound))
        report["oracle"] = self.incidence_oracle(previous)
        report["rbe_precheck"] = self.rbe_precheck(report["oracle"])
        self.assertEqual(report["stored_geometry_signature"],
                         report["signature_observations"]["before_geometry"])
        return report["oracle"]

    def test_exact_native_contact_and_cold_restore(self):
        self.doc = None
        self.directory = Path(os.environ["FREECAD_BT9_DIRECTORY"]).resolve()
        self.source = Path(os.environ["FREECAD_BT9_INPUT"]).resolve()
        self.stage = os.environ.get("FREECAD_BT9_STAGE", "create")
        self.work = self.directory / self.stage
        report_path = self.directory / f"{self.stage}-result.json"
        output = self.directory / "owned.FCStd" if self.stage == "create" else (
            self.work / "successor.FCStd")
        copied, copied_hash, cold_source, cold_hash = None, None, None, None
        primary, cleanup = None, None
        report = {"runtime": App.Version(), "home": App.getHomePath(), "gui_up": App.GuiUp,
                  "stage": self.stage, "harness": str(Path(__file__).resolve()),
                  "source": str(self.source), "source_sha256": WITNESS_SHA256,
                  "passed": False, "semantic_contact_pass": False, "mesher_or_solver_run": False,
                  "material_load_or_hand_deck_created": False,
                  "engineering_design_accepted": False, "cleanup_errors": []}
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            self.assertFalse(report_path.exists(), "Retain earlier reports; use fresh evidence")
            self.assertIn(self.stage, ("create", "reopen"))
            self.work.mkdir(exist_ok=False)
            self.assertFalse(output.exists(), "Never overwrite a native predecessor")
            self.assertTrue(App.GuiUp, "Use the native GUI runtime")
            self.assertFalse(self.source.is_relative_to(self.directory))
            self.assertEqual(self.digest(self.source), WITNESS_SHA256)
            expected = os.environ.get("FREECAD_BT9_EXPECTED_COMMIT")
            if expected:
                self.assertEqual(App.Version()[-1], expected)
            modules = (Fem, Part, ObjectsFem, meshsetsgetter, meshtools, elastic_connector,
                       calculixutils, write_constraint_contact)
            paths = {module.__name__: str(Path(module.__file__).resolve()) for module in modules}
            report["loaded_modules"] = paths
            report["module_sha256"] = {name: self.digest(path) for name, path in paths.items()}
            resources = os.environ.get("FREECAD_BT9_EXPECTED_RESOURCES")
            if resources:
                resources = Path(resources).resolve()
                self.assertEqual(Path(App.getHomePath()).resolve(), resources)
                self.assertTrue(all(Path(path).is_relative_to(resources)
                                    for path in paths.values()))
            created = None
            if self.stage == "reopen":
                created = json.loads((self.directory / "create-result.json").read_text())
                self.assertTrue(created["passed"])
                self.assertEqual(created["runtime"][-1], App.Version()[-1])
                cold_source = self.directory / "owned.FCStd"
                cold_hash = created["owned_sha256"]
                self.assertEqual(self.digest(cold_source), cold_hash)
            source = cold_source if cold_source is not None else self.source
            copied = self.work / "input.FCStd"
            with copied.open("xb") as handle:
                handle.write(source.read_bytes())
            copied_hash = self.digest(source)
            report["copied_input"] = str(copied)
            report["copied_input_sha256_before_open"] = copied_hash
            self.assertEqual(self.digest(copied), copied_hash)
            self.doc = App.openDocument(str(copied))
            self.assertEqual(Path(self.doc.FileName).resolve(), copied)
            # No manual recompute or contact/provenance assignment precedes cold checks.
            oracle = self.observe(report, created["oracle"] if created else None)
            if created:
                self.assertEqual(report["geometry"], created["geometry"])
                self.assertEqual(report["settings"], created["settings"])
                self.assertEqual(oracle["topology_sha256"], created["oracle"]["topology_sha256"])
                self.contact()  # Validate existing contact; never recreate or rebind it.
                self.check_contact(oracle, report, "cold_before_manual_recompute")
                self.doc.recompute(None, True)
                self.check_contact(oracle, report, "after_forced_recompute")
                self.assertEqual(report["cold_before_manual_recompute"]["getter"],
                                 report["after_forced_recompute"]["getter"])
            else:
                self.contact(create=True)
                self.check_contact(oracle, report, "before_save")
            self.assertEqual(self.topology_digest(), oracle["topology_sha256"])
            self.assertEqual(self.incidence_oracle(oracle), oracle)
            self.assertEqual(self.settings(), report["settings"])
            report["semantic_contact_pass"] = True
        except BaseException as error:
            primary = (error, error.__traceback__)
            report["error"] = repr(error)
            report["error_traceback"] = traceback.format_exc()
        finally:
            if self.doc is not None:
                try:
                    self.doc.saveAs(str(output))
                    with ZipFile(output) as archive:
                        self.assertIn("GuiDocument.xml", archive.namelist())
                    report["owned_native"] = str(output)
                    report["owned_sha256"] = self.digest(output)
                except BaseException as error:
                    cleanup = (error, error.__traceback__)
                    report["cleanup_errors"].append({"operation": "saveAs", "error": repr(error),
                                                     "traceback": traceback.format_exc()})
                try:
                    App.closeDocument(self.doc.Name)
                except BaseException as error:
                    if cleanup is None:
                        cleanup = (error, error.__traceback__)
                    report["cleanup_errors"].append({"operation": "closeDocument",
                                                     "error": repr(error)})
            try:
                report["source_sha256_after"] = self.digest(self.source)
                report["source_unchanged"] = report["source_sha256_after"] == WITNESS_SHA256
                report["copied_input_sha256_after"] = (
                    self.digest(copied) if copied is not None and copied.exists() else None)
                report["copied_input_unchanged"] = (
                    copied is not None and report["copied_input_sha256_after"] == copied_hash)
                report["cold_input_unchanged"] = (
                    cold_source is None or self.digest(cold_source) == cold_hash)
                self.assertTrue(report["source_unchanged"])
                self.assertTrue(report["copied_input_unchanged"])
                self.assertTrue(report["cold_input_unchanged"])
            except BaseException as error:
                if cleanup is None:
                    cleanup = (error, error.__traceback__)
                report["cleanup_errors"].append({"operation": "preservation_hashes",
                                                 "error": repr(error)})
            report["passed"] = primary is None and cleanup is None
            try:
                with report_path.open("x") as handle:
                    handle.write(json.dumps(report, indent=2) + "\n")
            except BaseException as error:
                report["passed"] = False
                report["report_write_error"] = repr(error)
                print("NATIVE_CONTACT_REPORT_JSON=" + json.dumps(report))
                if cleanup is None:
                    cleanup = (error, error.__traceback__)
        if primary is not None:
            raise primary[0].with_traceback(primary[1])
        if cleanup is not None:
            raise cleanup[0].with_traceback(cleanup[1])
        self.assertTrue(report["passed"])
