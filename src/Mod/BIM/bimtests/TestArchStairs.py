# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2025 Furgo
# SPDX-FileNotice: Part of the FreeCAD project.

################################################################################
#                                                                              #
#   FreeCAD is free software: you can redistribute it and/or modify            #
#   it under the terms of the GNU Lesser General Public License as             #
#   published by the Free Software Foundation, either version 2.1              #
#   of the License, or (at your option) any later version.                     #
#                                                                              #
#   FreeCAD is distributed in the hope that it will be useful,                 #
#   but WITHOUT ANY WARRANTY; without even the implied warranty                #
#   of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.                    #
#   See the GNU Lesser General Public License for more details.                #
#                                                                              #
#   You should have received a copy of the GNU Lesser General Public           #
#   License along with FreeCAD. If not, see https://www.gnu.org/licenses       #
#                                                                              #
################################################################################

import json
import os
import tempfile
import Arch
import ArchStairs
import FreeCAD as App
from bimtests import TestArchBase


class TestArchStairs(TestArchBase.TestArchBase):

    def test_proxy_state_round_trip(self):
        """Stairs auxiliary state survives both Python and JSON round trips."""
        stairs = Arch.makeStairs(length=5000, width=1000, height=3000, steps=10)
        for uuid, property_sets in (
            ("", []),
            ("e21ef894-7328-46ce-839b-1183a908db39", ["Default", "Wide stairs"]),
        ):
            stairs.Proxy.ArchSkPropSetPickedUuid = uuid
            stairs.Proxy.ArchSkPropSetListPrev = property_sets
            state = stairs.Proxy.dumps()
            for serialized in (state, json.loads(json.dumps(state))):
                with self.subTest(state=serialized):
                    restored = ArchStairs._Stairs.__new__(ArchStairs._Stairs)
                    restored.loads(serialized)
                    self.assertEqual(restored.Type, "Stairs")
                    self.assertEqual(restored.ArchSkPropSetPickedUuid, uuid)
                    self.assertEqual(restored.ArchSkPropSetListPrev, property_sets)
                    self.assertEqual(restored.dumps(), state)

    def test_proxy_state_legacy_formats(self):
        """Restore tagged triples and bare pairs, including IDs matching type markers."""
        property_sets = ["Default", "Wide stairs"]
        states = (
            ("Stairs", "e21ef894-7328-46ce-839b-1183a908db39", property_sets),
            ("e21ef894-7328-46ce-839b-1183a908db39", property_sets),
            ("", []),
            ("S", property_sets),
            ("Stairs", property_sets),
        )
        for state in states:
            for serialized in (state, json.loads(json.dumps(state))):
                with self.subTest(state=serialized):
                    restored = ArchStairs._Stairs.__new__(ArchStairs._Stairs)
                    restored.loads(serialized)
                    self.assertEqual(restored.Type, "Stairs")
                    self.assertEqual(restored.ArchSkPropSetPickedUuid, state[-2])
                    self.assertEqual(restored.ArchSkPropSetListPrev, state[-1])

    def test_proxy_state_without_archsketch_fields(self):
        """Old documents acquire default auxiliary fields during restoration."""
        stairs = Arch.makeStairs(length=5000, width=1000, height=3000, steps=10)
        for state in (None, "Stairs"):
            with self.subTest(state=state):
                restored = ArchStairs._Stairs.__new__(ArchStairs._Stairs)
                restored.loads(state)
                restored.setProperties(stairs)
                self.assertEqual(restored.Type, "Stairs")
                self.assertEqual(restored.ArchSkPropSetPickedUuid, "")
                self.assertEqual(restored.ArchSkPropSetListPrev, [])

    def test_proxy_state_document_round_trip(self):
        """Closing, reopening and saving again preserves default and populated state."""
        default = Arch.makeStairs(length=5000, width=1000, height=3000, steps=10)
        populated = Arch.makeStairs(length=5000, width=1200, height=3000, steps=10)
        populated.Proxy.ArchSkPropSetPickedUuid = "e21ef894-7328-46ce-839b-1183a908db39"
        populated.Proxy.ArchSkPropSetListPrev = ["Default", "Wide stairs"]
        self.document.recompute()
        expected_states = {obj.Name: obj.Proxy.dumps() for obj in (default, populated)}

        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "stairs_proxy_state.FCStd")
            for _ in range(2):
                self.document.saveAs(path)
                App.closeDocument(self.document.Name)
                self.document = App.openDocument(path)
                for name, expected in expected_states.items():
                    stairs = self.document.getObject(name)
                    self.assertEqual(stairs.Proxy.dumps(), expected)
                self.document.recompute(None, True, True)
                for name, expected in expected_states.items():
                    stairs = self.document.getObject(name)
                    self.assertEqual(stairs.Proxy.dumps(), expected)
                    self.assertFalse(stairs.Shape.isNull())
                    self.assertTrue(stairs.Shape.isValid())

    def test_center_landing_with_enforced_tread_depth(self):
        """Centered landings support automatic and explicitly enforced tread depths."""
        expected_bounds = {
            "HalfTurnLeft": (0.0, -1000.0, 0.0, 2750.0, 1000.0, 2812.5),
            "HalfTurnRight": (0.0, -2000.0, 0.0, 2750.0, 0.0, 2812.5),
            "Straight": (0.0, -1000.0, 0.0, 4500.0, 0.0, 2812.5),
        }

        def assert_stairs(stairs):
            self.assertNotIn("Invalid", stairs.State)
            self.assertFalse(stairs.Shape.isNull())
            self.assertTrue(stairs.Shape.isValid())
            self.assertAlmostEqual(stairs.Length.Value, 4500.0)
            self.assertAlmostEqual(stairs.Width.Value, 1000.0)
            self.assertAlmostEqual(stairs.Height.Value, 3000.0)
            self.assertEqual(stairs.NumberOfSteps, 16)
            self.assertAlmostEqual(stairs.LandingDepth.Value, 1000.0)
            self.assertAlmostEqual(stairs.TreadDepth.Value, 250.0)
            self.assertAlmostEqual(stairs.RiserHeight.Value, 187.5)
            self.assertEqual(len(stairs.Shape.Solids), 3)
            self.assertEqual(len(stairs.Shape.Faces), 44)
            self.assertEqual(len(stairs.OutlineLeft), 2)
            self.assertEqual(len(stairs.OutlineRight), 2)

            bounds = stairs.Shape.BoundBox
            actual_bounds = (
                bounds.XMin,
                bounds.YMin,
                bounds.ZMin,
                bounds.XMax,
                bounds.YMax,
                bounds.ZMax,
            )
            for actual, expected in zip(actual_bounds, expected_bounds[stairs.Flight]):
                self.assertAlmostEqual(actual, expected)

        stairs_names = []
        for flight in expected_bounds:
            for tread_depth in (0.0, 250.0):
                with self.subTest(flight=flight, tread_depth=tread_depth):
                    stairs = Arch.makeStairs(length=4500, width=1000, height=3000, steps=16)
                    stairs.Flight = flight
                    stairs.Landings = "At center"
                    stairs.LandingDepth = 1000
                    stairs.TreadDepthEnforce = tread_depth
                    stairs_names.append(stairs.Name)

        self.document.recompute(None, True, True)
        for name in stairs_names:
            stairs = self.document.getObject(name)
            with self.subTest(stage="created", stairs=name):
                assert_stairs(stairs)

        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "centered_landing_stairs.FCStd")
            self.document.saveAs(path)
            App.closeDocument(self.document.Name)
            self.document = App.openDocument(path)
            self.document.recompute(None, True, True)

            for name in stairs_names:
                stairs = self.document.getObject(name)
                with self.subTest(stage="restored", stairs=name):
                    assert_stairs(stairs)

    def test_makeStairs(self):
        """Test the makeStairs function."""
        operation = "Testing makeStairs function"
        self.printTestMessage(operation)

        stairs = Arch.makeStairs(length=5000, width=1000, height=3000, steps=10, name="TestStairs")
        self.assertIsNotNone(stairs, "makeStairs failed to create a stairs object.")
        self.assertEqual(stairs.Label, "TestStairs", "Stairs label is incorrect.")

    def test_makeRailing(self):
        """Test the makeRailing function."""
        operation = "Testing makeRailing..."
        self.printTestMessage(operation)

        stairs = Arch.makeStairs(length=5000, width=1000, height=3000, steps=10, name="TestStairs")
        self.assertIsNotNone(stairs, "makeStairs failed to create a stairs object.")

        # Pass stairs as a list to makeRailing
        obj = Arch.makeRailing([stairs])
        self.assertIsNotNone(obj, "makeRailing failed to create an object")
        self.assertEqual(obj.Label, "Railing", "Incorrect default label for Railing")

    def test_makeRailing(self):
        """Test the makeRailing function."""
        operation = "Testing makeRailing..."
        self.printTestMessage(operation)

        # Create stairs
        stairs = Arch.makeStairs(width=800, height=2500, length=3500, steps=14)
        self.document.recompute()

        # Get object names before creation
        pre_creation_names = {obj.Name for obj in self.document.Objects}

        # Create railings
        Arch.makeRailing([stairs])
        self.document.recompute()

        # Find new railings by name comparison and type checking
        new_railings = [
            obj
            for obj in self.document.Objects
            if obj.Name not in pre_creation_names
            and hasattr(obj, "Proxy")
            and getattr(obj.Proxy, "Type", "") == "Pipe"
        ]

        # Should create exactly 2 new railing objects
        self.assertEqual(len(new_railings), 2)

        # Verify properties exist
        for railing in new_railings:
            self.assertTrue(hasattr(railing, "Height"))
            self.assertTrue(hasattr(railing, "Diameter"))
            self.assertTrue(hasattr(railing, "Placement"))
