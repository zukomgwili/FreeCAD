# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *   Copyright (c) 2023 Mario Passaglia <mpassaglia[at]cbc.uba.ar>         *
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# *                                                                         *
# **************************************************************************/

import FreeCAD
import unittest


class TestStringHasher(unittest.TestCase):
    def setUp(self):
        self.strHash = FreeCAD.StringHasher()
        self.strID = self.strHash.getID("A")

    def testInit(self):
        with self.assertRaises(TypeError):
            FreeCAD.StringHasher(0)

    def testGetID(self):
        with self.assertRaises(ValueError):
            self.strHash.getID(0)

    def testStringHasherIsSame(self):
        with self.assertRaises(TypeError):
            self.strHash.isSame(0)

    def testStringIDIsSame(self):
        with self.assertRaises(TypeError):
            self.strID.isSame(0)

    def test_native_hashed_postfix_text(self):
        import base64
        import re
        import Part

        for threshold in (0, 1, 40, 100):
            with self.subTest(threshold=threshold):
                hasher = FreeCAD.StringHasher()
                hasher.Threshold = threshold
                shape = Part.makeBox(2, 3, 4)
                shape.Tag = 1
                shape = shape.copy("Seed", hasher)
                shape = shape.fuse(shape.translated(FreeCAD.Vector(1, 0, 0)))
                names = dict(shape.ElementMap)
                table = hasher.Table
                self.assertTrue(table)
                opaque_postfixes = 0
                for value, text in table.items():
                    sid = hasher.getID(value)
                    self.assertIsInstance(text, str)
                    self.assertEqual(text, sid.Data)
                    if "<base64:" in text:
                        opaque_postfixes += 1
                        self.assertFalse(sid.IsHashed or sid.IsBinary)
                        encoded = re.search(r"<base64:([^>]*)>", text).group(1)
                        self.assertEqual(base64.b64decode(encoded, validate=True),
                                         base64.b64decode(hasher.getID(sid.Related[0]).Data))
                self.assertEqual(opaque_postfixes > 0, threshold == 1)
                self.assertEqual(shape.ElementMap, names)
                self.assertAlmostEqual(shape.Volume, 36)
