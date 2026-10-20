"""Private native retained-selector/writer witness; never solve or repair a mesh.

The copied Oomakhi fixture supplies geometry and mesh only.  The separate test
analysis is NOT a proposed engineering replacement for its physical analysis.
"""
import sys
sys.dont_write_bytecode = True

import ctypes
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import struct
import time
import traceback
import unittest
import xml.etree.ElementTree as ET
import zipfile

import FreeCAD as App
import Fem
import ObjectsFem
from femtools import femutils
from femtools.ccxtools import FemToolsCcx

REPOSITORY = Path("/Users/zukomgwili/src/FreeCAD")
BUILD = REPOSITORY / "build/release"
MATERIALS = ("CollectorConcreteMaterial", "CollectorTimberMaterial", "CollectorSteelMaterial")
ANALYSIS = "RO1TieWriter"
SOLVER = "RO1TieSolver"
TIES = tuple("RO1RearTie%02d" % number for number in range(1, 25))
# Official CalculiX2.23 tetrahedron S1..S4, zero-based node positions
# (manual printedp394 and *SURFACE printedp612). Native SMESH C3D4 order is
# exported to ABAQUS/CCX as native positions (1,0,2,3), not (0,1,2,3).
# R06 deliberately remains a failed observer record: its prior oracle applied
# the CCX table directly to native order and incorrectly exchanged S3/S4.
CCX_SIDES = ((0, 1, 2), (0, 3, 1), (1, 3, 2), (2, 3, 0))
NATIVE_TO_CCX_TETRA4_ORDER = (1, 0, 2, 3)
SIDES = tuple(tuple(NATIVE_TO_CCX_TETRA4_ORDER[index] for index in side) for side in CCX_SIDES)


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def encoded_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def refs(values):
    return [[owner.Name, list(names)] for owner, names in values]


def encode(value):
    if hasattr(value, "Document") and hasattr(value, "Name"):
        return {"native_object": value.Name}
    if hasattr(value, "Value"):
        return {"quantity": str(value), "value": float(value.Value)}
    if isinstance(value, (tuple, list)):
        return [encode(item) for item in value]
    if isinstance(value, dict):
        return {str(key): encode(item) for key, item in value.items()}
    if isinstance(value, (str, bool, int, float)) or value is None:
        return value
    if hasattr(value, "Q"):
        return {"rotation": list(value.Q)}
    if hasattr(value, "Base") and hasattr(value, "Rotation"):
        return {"base": list(value.Base), "rotation": list(value.Rotation.Q)}
    if hasattr(value, "x") and hasattr(value, "y") and hasattr(value, "z"):
        return list(value)
    raise TypeError("Unhandled native material value: " + type(value).__name__)


def box(shape):
    bounds = shape.BoundBox
    return [bounds.XMin, bounds.YMin, bounds.ZMin, bounds.XMax, bounds.YMax, bounds.ZMax]


def geometry_and_properties(doc):
    """No output feature values, saved response, or solver result is accessed."""
    assembly = doc.CollectorAssembly
    owners = list(assembly.Links)
    geometry = {}
    for owner in owners:
        shape = owner.Shape
        geometry[owner.Name] = {
            "type": owner.TypeId, "bounds": box(shape), "volume": shape.Volume,
            # A native Bolt MultiFuse can retain two solids as Part.Compound;
            # Compound intentionally has no CenterOfMass API.  The actual
            # per-solid and per-face native centers below bind its geometry
            # without inventing an aggregate or changing any native input.
            "placement": encode(owner.Placement),
            "solids": [{"volume": solid.Volume, "center": list(solid.CenterOfMass),
                        "bounds": box(solid)} for solid in shape.Solids],
            "faces": [{"area": face.Area, "center": list(face.CenterOfMass),
                       "bounds": box(face), "surface": type(face.Surface).__name__}
                      for face in shape.Faces],
        }
    excluded = {"Proxy", "Shape", "ExpressionEngine", "Visibility", "Label2"}
    materials = {}
    for name in MATERIALS:
        material = doc.getObject(name)
        materials[name] = {prop: encode(material.getPropertyByName(prop))
                           for prop in sorted(material.PropertiesList) if prop not in excluded}
    # All 267 preexisting native constraints include all 193 Contacts, every
    # support, load, section and gravity definition.  None is a response object;
    # accounting result features are not Fem::Constraint* and are not read.
    constraints = {}
    for obj in doc.CollectorAnalysis.Group:
        if obj.TypeId.startswith("Fem::Constraint"):
            constraints[obj.Name] = {prop: encode(obj.getPropertyByName(prop))
                                     for prop in sorted(obj.PropertiesList)
                                     if prop not in {"Proxy", "ExpressionEngine", "Visibility", "Label2"}}
    other_groups = {obj.Name: [member.Name for member in obj.Group]
                    for obj in doc.Objects
                    if "Group" in obj.PropertiesList and obj.Name not in {"CollectorAnalysis", ANALYSIS}}
    mesh = doc.CollectorMesh
    return {
        "assembly_links": [owner.Name for owner in owners],
        "geometry_sha256": encoded_sha(geometry), "material_properties": materials,
        "original_native_constraint_properties": constraints,
        "original_analysis_members": [member.Name for member in doc.CollectorAnalysis.Group],
        "other_native_group_members": other_groups,
        "original_rear_references": {"Bolt%02dRearSeat" % number:
            refs(doc.getObject("Bolt%02dRearSeat" % number).References)
            for number in range(1, 25)},
        "mesh_shape": mesh.Shape.Name, "mesh_order": str(mesh.ElementOrder),
        "mesh_coherence": bool(mesh.CoherenceMesh),
        "group_geometry": mesh.ElementGroupGeometry,
        "group_names": list(mesh.ElementGroupNames),
        "group_references_sha256": encoded_sha(refs(mesh.ElementGroupReferences)),
    }


def native_groups(fm):
    return {fm.getGroupName(group): tuple(sorted(int(item) for item in fm.getGroupElements(group)))
            for group in fm.Groups}


def saved_face_bindings(path, doc, test):
    """Observe saved native topological history, never infer ownership by position.

    Independently serialized owner/compound BReps need not share OCC identity.
    Native LinkSub shadows retain the owner history followed by the compound
    history extension.  Only an exact unique extension is admitted here.  This
    observer's mapping is never passed to a production getter or writer.
    """
    with zipfile.ZipFile(path) as archive:
        xml_bytes = archive.read("Document.xml")
    document = ET.fromstring(xml_bytes)
    objects = {obj.attrib["name"]: obj for obj in document.findall("./ObjectData/Object")}
    mesh = objects["CollectorMesh"]
    mesh_rows = mesh.findall("./Properties/Property[@name='ElementGroupReferences']/LinkSubList/Link")
    test.assertTrue(mesh_rows)
    saved_mesh_refs = [(row.attrib["obj"], row.attrib["sub"]) for row in mesh_rows]
    live_mesh_refs = [(owner.Name, name) for owner, names in doc.CollectorMesh.ElementGroupReferences
                      for name in names]
    test.assertEqual(live_mesh_refs, saved_mesh_refs,
                     "Actual native mesh reference metadata must equal this phase's byte-copied XML")
    bindings = {}
    for number in range(1, 25):
        name = "Bolt%02dRearSeat" % number
        rows = objects[name].findall("./Properties/Property[@name='References']/LinkSubList/Link")
        expected = [("Bolt%02d" % number, "Face5"), ("CollectorConcrete", "Face3")]
        test.assertEqual([(row.attrib["obj"], row.attrib["sub"]) for row in rows], expected)
        test.assertEqual(refs(doc.getObject(name).References),
                         [[owner, [face]] for owner, face in expected])
        for row in rows:
            owner_name, local = row.attrib["obj"], row.attrib["sub"]
            shadow = row.attrib["shadow"]
            test.assertTrue(shadow.endswith("." + local), name)
            owner_history = shadow[:-(len(local) + 1)]
            test.assertTrue(owner_history.startswith(";"))
            matches = [candidate for candidate in mesh_rows
                       if candidate.attrib["obj"] == "CollectorAssembly"
                       and re.fullmatch(r"Face[1-9][0-9]*", candidate.attrib["sub"])
                       and candidate.attrib.get("shadow", "").startswith(owner_history + ";")]
            test.assertEqual(len(matches), 1, owner_name + "." + local)
            matched = matches[0]
            binding = {"assembly_face": matched.attrib["sub"],
                       "owner_native_history": owner_history,
                       "assembly_native_history": matched.attrib["shadow"]}
            key = owner_name + "." + local
            if key in bindings:
                test.assertEqual(bindings[key], binding, key)
            bindings[key] = binding
    test.assertEqual(len(bindings), 25)
    return {"phase_input": str(path), "phase_input_sha256": sha(path),
            "document_xml_sha256": hashlib.sha256(xml_bytes).hexdigest(),
            "binding_basis": "exact_unique_saved_native_topological_history_extension",
            "bindings": bindings}


def mesh_fingerprint(fm, groups, wanted_face_keys=None):
    """Identity observer, including ID-independent physical cohort hashes.

    Native node/element numbers are checked within each process, not imposed on a
    separately restored mesh.  Physical hashes use exact native coordinate bits.
    """
    node_bytes = {int(key): struct.pack("<3d", vector.x, vector.y, vector.z)
                  for key, vector in fm.Nodes.items()}
    coordinate_hash = hashlib.sha256()
    for node in sorted(node_bytes):
        coordinate_hash.update(struct.pack("<Q", node) + node_bytes[node])
    volume_owner = {}
    cohort_cells = {}
    for number in range(1, 51):
        name = "Solid%d" % number
        if name not in groups or not groups[name]:
            raise AssertionError("Missing native owner group " + name)
        cohort_cells[name] = []
        for volume in groups[name]:
            if volume in volume_owner:
                raise AssertionError("Overlapping native owner volume groups")
            volume_owner[volume] = name
    connectivity_hash = hashlib.sha256()
    incidence = {key: [] for key in (wanted_face_keys or ())}
    volume_count = 0
    for volume in fm.Volumes:
        volume = int(volume)
        nodes = tuple(int(node) for node in fm.getElementNodes(volume))
        if len(nodes) != 4:
            raise AssertionError("Retained oracle supports its recorded C3D4 mesh only")
        if volume not in volume_owner:
            raise AssertionError("Native owner partition does not cover a volume")
        connectivity_hash.update(struct.pack("<5Q", volume, *nodes))
        cell = b"".join(sorted(node_bytes[node] for node in nodes))
        cohort_cells[volume_owner[volume]].append(hashlib.sha256(cell).digest())
        if wanted_face_keys is not None:
            for side, indices in enumerate(SIDES, 1):
                key = tuple(sorted(nodes[index] for index in indices))
                if key in incidence:
                    incidence[key].append((volume, side))
        volume_count += 1
    if volume_count != len(volume_owner):
        raise AssertionError("Owner groups contain non-volume or absent IDs")
    physical = {name: hashlib.sha256(b"".join(sorted(cells))).hexdigest()
                for name, cells in cohort_cells.items()}
    signature = {
        "nodes": len(node_bytes), "volumes": volume_count,
        "node_ids_and_coordinates_sha256": coordinate_hash.hexdigest(),
        "element_ids_and_connectivity_sha256": connectivity_hash.hexdigest(),
        "all_native_group_ids_sha256": encoded_sha(groups),
        "all_native_group_counts": {name: len(ids) for name, ids in groups.items()},
        "native_owner_counts": {"Solid%d" % number: len(groups["Solid%d" % number])
                                for number in range(1, 51)},
        "native_owner_physical_sha256": physical,
    }
    return signature, incidence


def oracle(doc, test, groups, saved_history):
    """Saved native face history -> actual face group -> fresh tet incidence.

    This observer never supplies sets to the production getter or writer.
    """
    fm, assembly = doc.CollectorMesh.FemMesh, doc.CollectorAssembly
    selections = [("CollectorConcrete", "Face3", "Solid1")]
    selections += [("Bolt%02d" % number, "Face5", "Solid%d" % (2 * number + 1))
                   for number in range(1, 25)]
    faces, wanted = {}, set()
    owner_sets = {"Solid%d" % number: set(groups["Solid%d" % number])
                  for number in range(1, 51)}
    for owner_name, face_name, cohort in selections:
        owner = doc.getObject(owner_name)
        face = owner.getSubObject(face_name)
        coincidence = None
        if owner_name != "CollectorConcrete":
            master = doc.CollectorConcrete.getSubObject("Face3")
            test.assertFalse(face.isSame(master), owner_name + " must retain independent native face identity")
            overlap_area = face.common(master).Area
            # Same bounded CAD face-observation allowance already used by the
            # retained R29 catalogue guard: 1e-6 mm² absolute or 1e-10 relative.
            # This does not enter native selection, Tie tolerance, or solver data.
            area_tolerance = max(1e-6, abs(face.Area) * 1e-10)
            test.assertAlmostEqual(overlap_area, face.Area, delta=area_tolerance,
                                   msg=owner_name + ".Face5 must lie on its unchanged bounded master face")
            coincidence = {"independent_native_face_identity": True,
                           "slave_area_mm2": face.Area, "native_common_area_mm2": overlap_area,
                           "CAD_area_observation_tolerance_mm2": area_tolerance}
        local = [index for index, solid in enumerate(owner.Shape.Solids, 1)
                 if any(candidate.isSame(face) for candidate in solid.Faces)]
        test.assertEqual(local, [1], owner_name + "." + face_name)
        # No cross-BRep isSame requirement: independent serialized copies lose
        # that kernel identity. Select solely by the exact saved native history;
        # then verify the chosen native CAD face, without a geometric search.
        key = owner_name + "." + face_name
        group_name = saved_history["bindings"][key]["assembly_face"]
        ordinal = int(group_name[4:])
        test.assertLessEqual(ordinal, len(assembly.Shape.Faces))
        chosen = assembly.Shape.Faces[ordinal - 1]
        test.assertEqual(type(chosen.Surface).__name__, type(face.Surface).__name__)
        common_area = chosen.common(face).Area
        area_tolerance = max(1e-6, abs(face.Area) * 1e-10)
        test.assertAlmostEqual(chosen.Area, face.Area, delta=area_tolerance, msg=key)
        test.assertAlmostEqual(common_area, face.Area, delta=area_tolerance, msg=key)
        test.assertIn(group_name, groups)
        triangles = []
        for element in groups[group_name]:
            nodes = tuple(sorted(int(node) for node in fm.getElementNodes(element)))
            test.assertEqual(len(nodes), 3, group_name)
            triangles.append(nodes)
            wanted.add(nodes)
        test.assertTrue(triangles, group_name)
        test.assertEqual(len(triangles), len(set(triangles)), group_name)
        faces[owner_name + "." + face_name] = {
            "assembly_face": group_name, "cohort": cohort, "triangles": triangles,
            "history_selected_native_CAD_common_area_mm2": common_area,
            "CAD_area_observation_tolerance_mm2": area_tolerance}
        if coincidence is not None:
            faces[owner_name + "." + face_name]["native_coincidence"] = coincidence
    signature, incidence = mesh_fingerprint(fm, groups, wanted)
    for key, face in faces.items():
        pairs = []
        triangles = face.pop("triangles")
        for triangle in triangles:
            candidates = incidence[triangle]
            test.assertEqual(len(candidates), 1, key)
            pair = candidates[0]
            test.assertIn(pair[0], owner_sets[face["cohort"]], key)
            pairs.append(pair)
        face["pairs"] = sorted(pairs)
        face["native_face_triangle_node_patches"] = sorted(triangles)
        face["facet_count"] = len(pairs)
        test.assertEqual(len(pairs), len(set(pairs)), key)
    return signature, faces


def parse_deck(path, fm, wanted_volumes):
    """Read the actual unmodified C3D4 wire records; verify all native orders.

    Selected wire elements are retained to independently expand each written
    CCX surface side into node patches. No parsed data returns to FreeCAD.
    """
    surfaces, ties, current = {}, [], None
    wire_cells, seen = {}, set()
    wire_hash = hashlib.sha256()
    with Path(path).open() as source:
        for raw in source:
            line = raw.strip()
            if not line or line.startswith("**"):
                continue
            if line.startswith("*"):
                current = None
                keyword = line.split(",", 1)[0].upper()
                attributes = {item.split("=", 1)[0].strip().upper(): item.split("=", 1)[1].strip()
                              for item in line.split(",")[1:] if "=" in item}
                if keyword == "*ELEMENT":
                    if attributes.get("TYPE", "").upper() != "C3D4":
                        raise AssertionError("Retained wire oracle admits only its actual C3D4 records")
                    current = "__ELEMENTS__"
                elif keyword == "*SURFACE":
                    if attributes.get("TYPE", "ELEMENT").upper() != "ELEMENT":
                        raise AssertionError("Unexpected non-element surface")
                    current = attributes["NAME"]
                    if current in surfaces:
                        raise AssertionError("Duplicate surface name")
                    surfaces[current] = []
                elif keyword == "*TIE":
                    ties.append({"card": line, "attributes": attributes, "references": None})
                    current = "__TIE__"
            elif current == "__ELEMENTS__":
                values = tuple(int(item.strip()) for item in line.split(","))
                if len(values) != 5:
                    raise AssertionError("Invalid actual C3D4 wire connectivity")
                element, nodes = values[0], values[1:]
                if element in seen:
                    raise AssertionError("Duplicate actual wire element")
                native = tuple(int(node) for node in fm.getElementNodes(element))
                if len(native) != 4 or nodes != tuple(native[index] for index in NATIVE_TO_CCX_TETRA4_ORDER):
                    raise AssertionError("Actual native-to-wire tetrahedron permutation mismatch")
                seen.add(element)
                wire_hash.update(struct.pack("<5Q", element, *nodes))
                if element in wanted_volumes:
                    wire_cells[element] = nodes
            elif current == "__TIE__":
                if ties[-1]["references"] is not None:
                    raise AssertionError("Extra Tie data line")
                ties[-1]["references"] = [item.strip() for item in line.split(",")]
            elif current:
                element, side = [item.strip() for item in line.split(",")]
                if not re.fullmatch(r"S[1-4]", side.upper()):
                    raise AssertionError("Invalid retained tetra face")
                surfaces[current].append((int(element), int(side[1:])))
    if seen != {int(element) for element in fm.Volumes} or set(wire_cells) != wanted_volumes:
        raise AssertionError("Actual wire volume domain differs from the native mesh/oracle")
    wire_proof = {"actual_wire_type": "C3D4", "actual_wire_volume_count": len(seen),
                  "actual_wire_connectivity_sha256": wire_hash.hexdigest(),
                  "native_to_wire_node_positions_0based": list(NATIVE_TO_CCX_TETRA4_ORDER),
                  "permutation_verified_for_every_actual_wire_volume": True,
                  "CCX_S1_to_S4_node_positions_0based": [list(side) for side in CCX_SIDES],
                  "selected_wire_volume_count": len(wire_cells)}
    return surfaces, ties, wire_cells, wire_proof


class RetainedRearTieWitness(unittest.TestCase):
    def test_retained_ordinary_tie_owner_selection_and_full_writer(self):
        root = Path(os.environ["RO1_RETAINED_RUN"]).resolve()
        phase = os.environ["RO1_RETAINED_PHASE"]
        source = Path(os.environ["RO1_RETAINED_INPUT"]).resolve()
        expected = os.environ["RO1_RETAINED_INPUT_SHA256"]
        input_copy = root / "input.FCStd"
        saved = root / "witness.FCStd"
        report = {"passed": False, "phase": phase, "runtime": App.Version(),
                  "source": str(source), "source_sha256": expected,
                  "source_override": False, "manual_mesh_or_provenance_repair": False,
                  "remeshes": 0, "solves": 0, "response_accesses": 0,
                  "engineering_method_or_design_accepted": False, "checkpoints": []}
        doc = None
        started = time.monotonic()

        def checkpoint(name, **extra):
            row = {"name": name, "seconds": round(time.monotonic() - started, 3), **extra}
            report["checkpoints"].append(row)
            with (root / ("checkpoint-%02d.json" % len(report["checkpoints"]))).open("x") as output:
                output.write(json.dumps(row, indent=2) + "\n")
            print("RO1_RETAINED " + json.dumps(row), flush=True)

        try:
            self.assertFalse(App.GuiUp)
            self.assertEqual(Path(App.getHomePath()).resolve(), BUILD.resolve())
            self.assertTrue(sys.dont_write_bytecode)
            self.assertEqual(sha(source), expected)
            self.assertEqual(sha(input_copy), expected)
            self.assertNotEqual(source, input_copy)
            report["modules"] = {}
            for name, relative in (("ObjectsFem", "ObjectsFem.py"),
                    ("femmesh.meshsetsgetter", "femmesh/meshsetsgetter.py"),
                    ("femmesh.meshtools", "femmesh/meshtools.py"),
                    ("femmesh.ownership_context", "femmesh/ownership_context.py"),
                    ("femsolver.calculix.write_constraint_tie", "femsolver/calculix/write_constraint_tie.py"),
                    ("femsolver.calculix.writer", "femsolver/calculix/writer.py"),
                    ("femsolver.writerbase", "femsolver/writerbase.py"),
                    ("femsolver.calculix.calculixutils", "femsolver/calculix/calculixutils.py"),
                    ("femtools.femutils", "femtools/femutils.py"),
                    ("femtools.membertools", "femtools/membertools.py"),
                    ("femtools.ccxtools", "femtools/ccxtools.py")):
                module = importlib.import_module(name)
                actual = Path(module.__file__).resolve()
                self.assertEqual(actual, (BUILD / "Mod/Fem" / relative).resolve())
                self.assertEqual(sha(actual), sha(REPOSITORY / "src/Mod/Fem" / relative))
                report["modules"][name] = {"path": str(actual), "sha256": sha(actual)}
            self.assertEqual(Path(Fem.__file__).resolve(), (BUILD / "Mod/Fem/Fem.so").resolve())
            dyld = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
            dyld._NSGetExecutablePath.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
            dyld._NSGetExecutablePath.restype = ctypes.c_int
            size = ctypes.c_uint32(4096)
            buffer = ctypes.create_string_buffer(size.value)
            self.assertEqual(dyld._NSGetExecutablePath(buffer, ctypes.byref(size)), 0)
            executable = Path(os.fsdecode(buffer.value)).resolve()
            self.assertEqual(executable, (BUILD / "bin/FreeCADCmd").resolve())
            report["process_executable"] = {"path": str(executable), "sha256": sha(executable)}
            dyld._dyld_image_count.restype = ctypes.c_uint32
            dyld._dyld_get_image_name.argtypes = [ctypes.c_uint32]
            dyld._dyld_get_image_name.restype = ctypes.c_char_p
            fem_images = [Path(os.fsdecode(dyld._dyld_get_image_name(index))).resolve()
                          for index in range(dyld._dyld_image_count())
                          if Path(os.fsdecode(dyld._dyld_get_image_name(index))).name in ("Fem.so", "FemGui.so")]
            self.assertEqual(fem_images, [(BUILD / "Mod/Fem/Fem.so").resolve()])
            report["loaded_fem_images"] = [{"path": str(path), "sha256": sha(path)} for path in fem_images]
            header = (BUILD / "src/Build/Version.h").read_text()
            for macro, value in (("FCRevision", App.Version()[3]), ("FCRepositoryHash", App.Version()[-1])):
                match = re.search(r'^#define\s+' + macro + r'\s+"([^"]+)"', header, re.M)
                self.assertIsNotNone(match)
                self.assertEqual(value, match.group(1))
            doc = App.openDocument(str(input_copy))
            self.assertEqual(Path(doc.FileName).resolve(), input_copy)
            # No manual recompute or output access precedes these native checks.
            initial = geometry_and_properties(doc)
            self.assertEqual(len(initial["original_native_constraint_properties"]), 267)
            self.assertEqual(sum(member.TypeId == "Fem::ConstraintContact"
                                 for member in doc.CollectorAnalysis.Group), 193)
            self.assertEqual(initial["assembly_links"],
                ["CollectorConcrete", "CollectorLedger"] + ["Bolt%02d" % i for i in range(1, 25)])
            self.assertEqual(initial["mesh_shape"], "CollectorAssembly")
            self.assertEqual(initial["mesh_order"], "1st")
            self.assertFalse(initial["mesh_coherence"])
            for number in range(1, 25):
                self.assertEqual(initial["original_rear_references"]["Bolt%02dRearSeat" % number],
                    [["Bolt%02d" % number, ["Face5"]], ["CollectorConcrete", ["Face3"]]])
            groups = native_groups(doc.CollectorMesh.FemMesh)
            owner_sets = {"Solid%d" % number: set(groups["Solid%d" % number])
                          for number in range(1, 51)}
            checkpoint("cold_native_inputs_observed_before_manual_recompute", group_count=len(groups))
            saved_history = saved_face_bindings(input_copy, doc, self)
            report["independent_saved_native_history_bindings"] = saved_history
            checkpoint("phase_bytecopy_XML_unique_native_history_bindings_verified", selected_faces=25)
            initial_mesh, expected_faces = oracle(doc, self, groups, saved_history)
            self.assertEqual([initial_mesh["nodes"], initial_mesh["volumes"]], [257444, 784939])
            self.assertEqual(initial_mesh["native_owner_counts"]["Solid1"], 90573)
            self.assertEqual(initial_mesh["native_owner_counts"]["Solid2"], 221065)
            report["initial_properties"] = initial
            report["initial_mesh"] = initial_mesh
            report["oracle"] = expected_faces
            checkpoint("independent_native_tetra_incidence_oracle_complete", selected_faces=len(expected_faces))
            if phase == "create":
                self.assertIsNone(doc.getObject(ANALYSIS))
                transferred = [*MATERIALS, "CollectorMesh"]
                before_members = initial["original_analysis_members"]
                for name in transferred:
                    self.assertEqual(before_members.count(name), 1, name)
                isolated = dict(initial)
                isolated["original_analysis_members"] = [name for name in before_members
                                                          if name not in transferred]
                report["private_analysis_membership_partition"] = {
                    "native_addObject_transfer_performed_this_phase": True,
                    "transferred_existing_objects": transferred,
                    "original_private_group_before_transfer": before_members,
                    "expected_original_private_group_after_transfer": isolated["original_analysis_members"],
                    "original_private_analysis_not_intended_or_qualified_for_solving": True,
                    "physical_method_adopted": False}
                analysis = ObjectsFem.makeAnalysis(doc, ANALYSIS)
                solver = ObjectsFem.makeSolverCalculiXCcxTools(doc, SOLVER)
                solver.NativeForceAccounting = False
                analysis.addObject(solver)
                for name in MATERIALS:
                    analysis.addObject(doc.getObject(name))
                analysis.addObject(doc.CollectorMesh)
                for number, name in enumerate(TIES, 1):
                    tie = ObjectsFem.makeConstraintTie(doc, name)
                    tie.References = [(doc.getObject("Bolt%02d" % number), ["Face5"]),
                                      (doc.CollectorConcrete, ["Face3"])]
                    tie.Tolerance = 0
                    analysis.addObject(tie)
                # Only newly authored native constraints, never the old model,
                # mesh, Boolean history, reverse cuts or ownership properties.
                doc.recompute([doc.getObject(name) for name in TIES], True)
                report["selective_new_tie_recompute_calls"] = 1
            else:
                self.assertEqual(phase, "cold")
                prior = json.loads(Path(os.environ["RO1_RETAINED_PREVIOUS_REPORT"]).read_text())
                self.assertTrue(prior["passed"])
                self.assertEqual(initial, prior["isolated_properties"])
                self.assertEqual(initial_mesh["all_native_group_counts"], prior["initial_mesh"]["all_native_group_counts"])
                self.assertEqual(initial_mesh["native_owner_physical_sha256"], prior["initial_mesh"]["native_owner_physical_sha256"])
                isolated = initial
                prior_partition = prior["private_analysis_membership_partition"]
                transferred = [*MATERIALS, "CollectorMesh"]
                self.assertEqual(prior_partition["transferred_existing_objects"], transferred)
                original_members = prior_partition["original_private_group_before_transfer"]
                for name in transferred:
                    self.assertEqual(original_members.count(name), 1, name)
                self.assertEqual(initial["original_analysis_members"],
                                 [name for name in original_members if name not in transferred])
                report["private_analysis_membership_partition"] = dict(prior_partition)
                report["private_analysis_membership_partition"]["native_addObject_transfer_performed_this_phase"] = False
                analysis, solver = doc.getObject(ANALYSIS), doc.getObject(SOLVER)
                self.assertIsNotNone(analysis)
                self.assertIsNotNone(solver)
                report["selective_new_tie_recompute_calls"] = 0
            self.assertFalse(solver.NativeForceAccounting)
            self.assertEqual([member.Name for member in analysis.Group],
                             [SOLVER, *MATERIALS, "CollectorMesh", *TIES])
            for number, name in enumerate(TIES, 1):
                tie = doc.getObject(name)
                # Ordinary Tie is a native ConstraintPython-backed object;
                # use FreeCAD's supported FEM semantic type observer rather
                # than assuming a C++ inheritance relation that does not exist.
                self.assertTrue(femutils.is_derived_from(tie, "Fem::ConstraintTie"))
                self.assertEqual(refs(tie.References),
                    [["Bolt%02d" % number, ["Face5"]], ["CollectorConcrete", ["Face3"]]])
                self.assertEqual(float(tie.Tolerance), 0)
            self.assertEqual(geometry_and_properties(doc), isolated)
            report["isolated_properties"] = isolated
            checkpoint("isolated_ordinary_writer_analysis_verified", member_count=len(analysis.Group))
            deck_dir = root / "writer"
            deck_dir.mkdir(exist_ok=False)
            solver.WorkingDir = str(deck_dir)
            tool = FemToolsCcx(analysis=analysis, solver=solver)
            tool.update_objects()
            tool.setup_working_dir(str(deck_dir))
            prerequisites = tool.check_prerequisites()
            report["prerequisites"] = prerequisites
            self.assertEqual(prerequisites,
                             "Static analysis: No mechanical boundary conditions defined.\n")
            report["solver_prerequisites_passed"] = False
            report["writer_only_missing_boundary_diagnostic_expected"] = True
            checkpoint("writer_only_prerequisites_observed_no_supports_or_loads_added")
            tool.write_inp_file()  # No ccx_run, run, task pipeline or result import.
            deck = Path(tool.inp_file_name).resolve()
            self.assertTrue(deck.is_relative_to(deck_dir))
            self.assertTrue(deck.is_file())
            self.assertFalse(list(deck_dir.glob("*.accounting*")))
            wanted_volumes = {volume for face in expected_faces.values() for volume, _side in face["pairs"]}
            surfaces, cards, actual_wire_cells, wire_proof = parse_deck(
                deck, doc.CollectorMesh.FemMesh, wanted_volumes)
            report["actual_C3D4_wire_convention_proof"] = wire_proof
            self.assertEqual(len(cards), 24)
            report["deck"] = {"path": str(deck), "sha256": sha(deck), "bytes": deck.stat().st_size}
            report["written_sides"] = {}
            report["tie_cards"] = cards
            for number, name in enumerate(TIES, 1):
                dependent, independent = "TIE_DEP" + name, "TIE_IND" + name
                matched = [card for card in cards if card["references"] == [dependent, independent]]
                self.assertEqual(len(matched), 1)
                self.assertEqual(matched[0]["attributes"],
                                 {"POSITION TOLERANCE": "0", "ADJUST": "NO", "NAME": "TIE" + name})
                for surface, face_key in ((dependent, "Bolt%02d.Face5" % number),
                                          (independent, "CollectorConcrete.Face3")):
                    self.assertIn(surface, surfaces)
                    actual = sorted(surfaces[surface])
                    wanted = expected_faces[face_key]["pairs"]
                    self.assertEqual(len(actual), len(set(actual)), surface)
                    self.assertEqual(actual, wanted, surface)
                    # This is separate from the corrected native side-number
                    # oracle: expand the actual emitted side using the actual
                    # wire connectivity and the primary CCX table, then compare
                    # with the native face-group triangle patch itself.
                    expanded = sorted(tuple(sorted(actual_wire_cells[volume][index]
                                                   for index in CCX_SIDES[side - 1]))
                                      for volume, side in actual)
                    native_patches = expected_faces[face_key]["native_face_triangle_node_patches"]
                    self.assertEqual(len(expanded), len(set(expanded)), surface)
                    self.assertEqual(expanded, native_patches, surface)
                    cohort = expected_faces[face_key]["cohort"]
                    self.assertTrue(all(volume in owner_sets[cohort] for volume, _side in actual), surface)
                    report["written_sides"][surface] = {
                        "face": face_key, "cohort": cohort, "facet_count": len(actual),
                        "pairs_sha256": encoded_sha(actual), "exact_native_incidence_match": True,
                        "actual_wire_expanded_node_patches_sha256": encoded_sha(expanded),
                        "native_face_group_node_patches_sha256": encoded_sha(native_patches),
                        "actual_wire_CCX_side_patch_equals_native_owned_face_patch": True}
            checkpoint("all_48_stock_written_surfaces_match_independent_native_oracle")
            final_groups = native_groups(doc.CollectorMesh.FemMesh)
            final_mesh, _unused = mesh_fingerprint(doc.CollectorMesh.FemMesh, final_groups)
            self.assertEqual(final_mesh, initial_mesh)
            self.assertEqual(geometry_and_properties(doc), isolated)
            report["final_mesh"] = final_mesh
            self.assertFalse(saved.exists())
            doc.saveAs(str(saved))
            self.assertEqual(sha(source), expected)
            self.assertEqual(sha(input_copy), expected)
            self.assertEqual(geometry_and_properties(doc), isolated)
            report["saved_witness"] = {"path": str(saved), "sha256": sha(saved)}
            report["source_and_private_input_unchanged"] = True
            checkpoint("private_witness_saved_physical_inputs_unchanged_expected_private_group_partition_retained")
            report["passed"] = True
        except BaseException as error:
            report["error"] = repr(error)
            report["traceback"] = traceback.format_exc()
            raise
        finally:
            if doc is not None:
                App.closeDocument(doc.Name)
            report["seconds"] = round(time.monotonic() - started, 3)
            with (root / "report.json").open("x") as output:
                output.write(json.dumps(report, indent=2) + "\n")
