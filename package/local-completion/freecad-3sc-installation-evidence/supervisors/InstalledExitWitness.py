"""Preserved one-case process witness for the private FreeCAD-3sc gates.

The historical FREECAD59D marker/environment protocol remains unchanged.
"""

import json
import os
import sys
import unittest

sys.dont_write_bytecode = True

import FreeCAD as App


class TestExitWitness(unittest.TestCase):
    def test_outcome(self):
        print(
            "FREECAD59D_IDENTITY="
            + json.dumps({"version": App.Version(), "home": App.getHomePath(), "gui": App.GuiUp}),
            flush=True,
        )
        outcome = os.environ["FREECAD_59D_CASE"]
        if outcome == "failure":
            self.fail("FreeCAD-3sc deliberate assertion witness")
        if outcome == "error":
            raise RuntimeError("FreeCAD-3sc deliberate error witness")
        self.assertEqual(outcome, "pass")
