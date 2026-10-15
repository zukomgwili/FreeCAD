# SPDX-License-Identifier: LGPL-2.1-or-later

"""Run the retained probe with native FreeCAD, not FreeCADCmd.

Use the environment documented in RetainedDimensionReferences, plus
FREECAD_6G7_RESULT for a JSON result path. Optionally set
FREECAD_6G7_EXPECTED_COMMIT to require a specific compiled runtime identity.
This result file is useful because native test-runner output can go to the GUI.
"""

import json
import os
from pathlib import Path

import FreeCAD as App
import FreeCADGui as Gui
import Part
import RetainedDimensionReferences as Retained


class NativeRetainedDimensionReferences(Retained.RetainedDimensionReferences):
    @classmethod
    def setUpClass(cls):
        if not App.GuiUp or Gui.getMainWindow() is None:
            raise AssertionError("Requires the native FreeCAD application")
        expected = os.environ.get("FREECAD_6G7_EXPECTED_COMMIT")
        if expected and App.Version()[-1] != expected:
            raise AssertionError(f"Unexpected compiled runtime: {App.Version()}")

    def test_physical_points_survive_recompute_and_save(self):
        result_path = Path(os.environ["FREECAD_6G7_RESULT"])
        result = {
            "version": App.Version(),
            "home": App.getHomePath(),
            "part_module": Part.__file__,
            "gui_up": App.GuiUp,
            "input": os.environ["FREECAD_6G7_INPUT"],
            "output": os.environ["FREECAD_6G7_OUTPUT"],
        }
        try:
            super().test_physical_points_survive_recompute_and_save()
            result["passed"] = True
        except BaseException as error:
            result.update(passed=False, error=repr(error))
            raise
        finally:
            result_path.write_text(json.dumps(result, indent=2))
