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

import Arch
import Draft
import FreeCAD
import Part
from bimtests import TestArchBase


class TestArchPipe(TestArchBase.TestArchBase):

    def test_invalid_path_is_failed_and_can_be_repaired(self):
        arc = Draft.make_circle(20, startangle=0, endangle=90, face=False)
        self.document.recompute()
        self.assertEqual(len(arc.Shape.Wires), 0)
        pipe = Arch.makePipe(arc, diameter=5)
        self.document.recompute()
        self.assertIn("Invalid", pipe.State)
        self.assertTrue(pipe.Shape.isNull())
        self.assertIn("base path", pipe.getStatusString())
        wire = self.document.addObject("Part::Feature", "ValidPath")
        wire.Shape = Part.Wire([Part.makeLine(FreeCAD.Vector(), FreeCAD.Vector(0, 0, 100))])
        pipe.Base = wire
        self.document.recompute()
        self.assertNotIn("Invalid", pipe.State)
        self.assertTrue(pipe.Shape.isValid())
        self.assertGreater(pipe.Shape.Volume, 0)
        self.assertAlmostEqual(pipe.Length.Value, 100)
        pipe.Base = arc
        self.document.recompute()
        self.assertIn("Invalid", pipe.State)
        self.assertTrue(pipe.Shape.isNull(), "Failed pipe must not retain stale geometry")
        self.assertAlmostEqual(pipe.Length.Value, 0)

    def test_makePipe(self):
        """Test the makePipe function."""
        operation = "Testing makePipe function"
        self.printTestMessage(operation)

        pipe = Arch.makePipe(diameter=200, length=1000, name="TestPipe")
        self.assertIsNotNone(pipe, "makePipe failed to create a pipe object.")
        self.assertEqual(pipe.Label, "TestPipe", "Pipe label is incorrect.")

    def test_makePipeConnector(self):
        """Test the makePipeConnector function."""
        operation = "Testing makePipeConnector function"
        self.printTestMessage(operation)

        pipe1 = Arch.makePipe(diameter=200, length=1000, name="Pipe1")
        pipe2 = Arch.makePipe(diameter=200, length=1000, name="Pipe2")
        connector = Arch.makePipeConnector([pipe1, pipe2], radius=100, name="TestConnector")
        self.assertIsNotNone(
            connector, "makePipeConnector failed to create a pipe connector object."
        )
        self.assertEqual(connector.Label, "TestConnector", "Pipe connector label is incorrect.")
