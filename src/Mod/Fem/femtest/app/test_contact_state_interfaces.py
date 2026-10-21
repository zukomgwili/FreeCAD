# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native Contact selection and owner attribution through ordinary interfaces.

Software output qualification only; these small bars do not accept a building
model, contact constitutive accuracy, or mesh convergence.
"""

import shutil
import unittest
from pathlib import Path

import FreeCAD as App

import ObjectsFem

from femmesh.gmshtools import GmshTools
from femtest.app import test_contact_state_native as native_fixture
from femtools.ccxtools import FemToolsCcx
from femtools.femutils import is_of_type

_NATIVE_FACE_NODES = {
    4: ((0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3)),
    10: (
        (0, 1, 2, 4, 5, 6),
        (0, 1, 3, 4, 7, 8),
        (0, 2, 3, 6, 7, 9),
        (1, 2, 3, 5, 8, 9),
    ),
}
_NATIVE_TO_CCX = {
    "C3D4": (1, 0, 2, 3),
    "C3D10": (1, 0, 2, 3, 4, 6, 5, 8, 7, 9),
}


@unittest.skipUnless(shutil.which("gmsh"), "Native Gmsh executable required")
class TestContactStateInterfaces(unittest.TestCase):
    def setUp(self):
        # Composition reuses the ordinary native fixture without collecting its
        # tests again through unittest inheritance.
        self.fixture = native_fixture.TestContactStateNative(methodName="runTest")
        self.fixture.setUp()
        self.doc = self.fixture.doc
        self.directory = self.fixture.directory

    def tearDown(self):
        self.fixture.tearDown()

    def _add_second_pair(self, model):
        left = self.doc.addObject("Part::Box", "UpperLeft")
        right = self.doc.addObject("Part::Box", "UpperRight")
        for body in (left, right):
            body.Length = body.Width = body.Height = 1
        left.Placement.Base = App.Vector(0, 0, 3)
        right.Placement.Base = App.Vector(1, 0, 3)
        geometry = self.doc.getObject("Geometry")
        geometry.Links = list(geometry.Links) + [left, right]

        contact = ObjectsFem.makeConstraintContact(self.doc, "UpperInterface")
        contact.SurfaceBehavior = "Linear"
        contact.References = [(left, ["Face2"]), (right, ["Face1"])]
        contact.Slope = "100000 MPa/mm"
        contact.Friction = True
        contact.FrictionCoefficient = 0.3
        contact.StickSlope = "10000 MPa/mm"
        contact.Adjust = "0 mm"
        model.analysis.addObject(contact)

        fixed = ObjectsFem.makeConstraintFixed(self.doc)
        fixed.References = [(left, ["Face1"])]
        model.analysis.addObject(fixed)
        displacement = ObjectsFem.makeConstraintDisplacement(self.doc)
        displacement.References = [(right, ["Face2"])]
        displacement.xFree = displacement.yFree = displacement.zFree = False
        displacement.xDisplacement = "-0.004 mm"
        model.analysis.addObject(displacement)

        # The fixture's one whole-analysis material applies to all four bars.
        self.doc.recompute()
        mesher = GmshTools(model.mesh)
        mesher.create_mesh()
        self.assertEqual(mesher.process.exitCode(), 0)
        self.assertGreater(model.mesh.FemMesh.VolumeCount, 0)
        return contact

    def _owner_groups(self, native):
        # Literal original-coordinate extents independently identify the four
        # constructed bars; this does not use the diagnostic export manifest.
        bounds = {
            "Solid1": ((0, 1), (0, 1), (0, 1)),
            "Solid2": ((1, 2), (0, 1), (0, 1)),
            "Solid3": ((0, 1), (0, 1), (3, 4)),
            "Solid4": ((1, 2), (0, 1), (3, 4)),
        }
        owners = {}
        seen = set()
        for owner, extent in bounds.items():
            groups = [group for group in native.Groups if native.getGroupName(group) == owner]
            self.assertEqual(len(groups), 1, owner)
            elements = set(native.getGroupElements(groups[0]))
            self.assertTrue(elements, owner)
            self.assertTrue(elements <= set(native.Volumes), owner)
            self.assertFalse(seen.intersection(elements), owner)
            seen.update(elements)
            nodes = {node for element in elements for node in native.getElementNodes(element)}
            points = [tuple(native.getNodeById(node)) for node in nodes]
            for axis, (lower, upper) in enumerate(extent):
                self.assertAlmostEqual(min(point[axis] for point in points), lower, delta=1e-10)
                self.assertAlmostEqual(max(point[axis] for point in points), upper, delta=1e-10)
                self.assertTrue(
                    all(lower - 1e-10 <= point[axis] <= upper + 1e-10 for point in points),
                    owner,
                )
            owners[owner] = elements
        self.assertEqual(seen, set(native.Volumes))
        return owners

    def _assert_interface_face(self, native, element, face, owner):
        self.assertIn(element, owner)
        self.assertIn(face, (1, 2, 3, 4))
        nodes = native.getElementNodes(element)
        self.assertIn(len(nodes), (4, 10))
        # Public FemMesh tetrahedra swap corners 1/2 relative to CalculiX; see
        # FemMesh.cpp writeABAQUS. Check every original face node at literal x=1.
        # This is topology verification, not result
        # interpolation or a coordinate-based ownership recovery operation.
        for index in _NATIVE_FACE_NODES[len(nodes)][face - 1]:
            self.assertAlmostEqual(native.getNodeById(nodes[index]).x, 1.0, delta=1e-10)

    def _assert_written_connectivity(self, native, filename):
        # Independently verify the observed public-mesh -> actual native deck
        # convention, rather than reusing the production ownership resolver.
        # The literal maps are documented by FemMesh.cpp:1913-1918.
        elements = {}
        kind = None
        for line in Path(filename).read_text().splitlines():
            text = line.strip()
            if not text or text.startswith("**"):
                continue
            if text.startswith("*"):
                kind = None
                fields = text.upper().replace(" ", "").split(",")
                if fields[0] == "*ELEMENT":
                    kind = next((field[5:] for field in fields if field.startswith("TYPE=")), None)
                    self.assertIn(kind, _NATIVE_TO_CCX)
                continue
            if kind is not None:
                values = tuple(int(item.strip()) for item in text.split(","))
                self.assertEqual(len(values), len(_NATIVE_TO_CCX[kind]) + 1)
                self.assertNotIn(values[0], elements)
                elements[values[0]] = (kind, values[1:])
        self.assertEqual(set(elements), set(native.Volumes))
        for element, (kind, written) in elements.items():
            public = native.getElementNodes(element)
            self.assertEqual(len(public), len(_NATIVE_TO_CCX[kind]))
            self.assertEqual(written, tuple(public[index] for index in _NATIVE_TO_CCX[kind]))

    def _assert_attribution(self, data, native, owners, expected):
        self.assertEqual(data["schema"], "CCX_CONTACT_STATE_V1")
        self.assertEqual(data["sample_identity_scope"], "FRAME_LOCAL_NATIVE_CATALOGUE")
        self.assertTrue(data["complete"])
        self.assertTrue(data["frames"])
        self.assertEqual({row["contact"] for row in data["sample_inventory"]}, set(expected))
        self.assertEqual({row["contact"] for row in data["face_inventory"]}, set(expected))
        for frame in data["frames"]:
            self.assertEqual({row["contact"] for row in frame["samples"]}, set(expected))
            active = {name: [] for name in expected}
            points = set()
            for row in frame["samples"]:
                name = row["contact"]
                slave, master, lower, upper, pressure, native_pair = expected[name]
                self.assertEqual(row["native_pair"], native_pair)
                self.assertNotIn(row["native_point"], points)
                points.add(row["native_point"])
                self._assert_interface_face(
                    native, row["slave_element"], row["slave_face"], owners[slave]
                )
                self.assertTrue(lower - 1e-8 <= row["slave_position"][2] <= upper + 1e-8)
                if row["master_element"] is not None:
                    self._assert_interface_face(
                        native, row["master_element"], row["master_face"], owners[master]
                    )
                    self.assertTrue(lower - 1e-8 <= row["master_position"][2] <= upper + 1e-8)
                if row["availability"] == "ACTIVE":
                    active[name].append(row)
                    self.assertEqual(row["state"], "STICK")
                    self.assertAlmostEqual(row["pressure"], pressure, delta=0.01 * pressure)
            for name, rows in active.items():
                self.assertTrue(rows, name)

    def _rerun(self, model, contacts, label):
        model.solver.NativeContactOutputs = contacts
        self.assertFalse(model.solver.NativeForceAccounting)
        self.doc.recompute()
        self.doc.saveAs(str(self.directory / "native-contact-interfaces.FCStd"))
        directory = self.directory / label
        directory.mkdir()
        fea = FemToolsCcx(analysis=model.analysis, solver=model.solver)
        fea.update_objects()
        fea.setup_working_dir(str(directory))
        fea.write_inp_file()
        self._assert_written_connectivity(model.mesh.FemMesh, fea.inp_file_name)
        self.assertEqual(fea.ccx_run(), 0, fea.ccx_stdout + fea.ccx_stderr)
        fea.load_results()
        results = [
            item for item in model.analysis.Group if is_of_type(item, "Fem::ContactStateResult")
        ]
        self.assertEqual(len(results), 1)
        return results[0].Proxy.getContactStates(results[0])

    def test_two_native_pairs_keep_owner_identity_and_second_only_selection(self):
        model = self.fixture.make_case()
        second = self._add_second_pair(model)
        native = model.mesh.FemMesh
        owners = self._owner_groups(native)
        expected = {
            model.contact.Name: ("Solid1", "Solid2", 0, 1, 0.9950248756218906, 1),
            second.Name: ("Solid3", "Solid4", 3, 4, 1.9900497512437811, 2),
        }
        both = self._rerun(model, [model.contact, second], "both-selected")
        self._assert_attribution(both, native, owners, expected)
        second_ids = {
            row["native_point"]
            for row in both["frames"][-1]["samples"]
            if row["contact"] == second.Name
        }
        self.assertTrue(second_ids)
        self.assertGreater(min(second_ids), 1)

        selected = self._rerun(model, [second], "second-only")
        self.assertEqual(list(model.solver.NativeContactOutputs), [second])
        self._assert_attribution(selected, native, owners, {second.Name: expected[second.Name]})
        self.assertEqual(
            {row["native_point"] for row in selected["frames"][-1]["samples"]}, second_ids
        )
