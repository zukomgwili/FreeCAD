"""Actual retained checkpoint through stock targeted BIM recompute only."""
import sys

sys.dont_write_bytecode = True

import hashlib
import json
import math
import os
from pathlib import Path
import unittest

import FreeCAD as App
import ArchComponent
import ArchStructure
import Part

SOURCE = Path(os.environ["H88_SOURCE"])
RUN = Path(os.environ["H88_RUN_DIR"])


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical(value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


def module_origins():
    result = {}
    for module in (ArchComponent, ArchStructure):
        path = Path(module.__file__).resolve()
        expected = Path(os.environ["H88_MODULE_ROOT"]) / path.name
        source = Path(os.environ["H88_CODE_ROOT"]) / path.name
        if path != expected.resolve() or sha(path) != sha(source):
            raise AssertionError("Wrong loaded BIM module: " + str(path))
        result[module.__name__] = {"path": str(path), "sha256": sha(path)}
    if App.Version()[-1] != os.environ["H88_EXPECT_COMMIT"]:
        raise AssertionError("Wrong compiled FreeCAD commit")
    return result


def material_differences(test, first, second):
    test.assertTrue(first.isValid())
    test.assertTrue(second.isValid())
    result = []
    for left, right in ((first, second), (second, first)):
        difference = left.cut(right)
        row = {"null": difference.isNull(), "vertices": len(difference.Vertexes),
               "valid": None if difference.isNull() else difference.isValid()}
        result.append(row)
        if not row["null"]:
            test.assertTrue(row["valid"], "Material difference Boolean is inconclusive")
        test.assertEqual(row["vertices"], 0, "Material changed")
    return result


def health(obj):
    shape = obj.Shape
    return {
        "name": obj.Name, "type": obj.TypeId,
        "valid": shape.isValid(), "null": shape.isNull(),
        "closed": shape.isClosed(), "solid_count": len(shape.Solids),
        "face_count": len(shape.Faces), "volume_mm3": shape.Volume,
        "area_mm2": shape.Area,
        "bounds_mm": [getattr(shape.BoundBox, key) for key in (
            "XMin", "YMin", "ZMin", "XMax", "YMax", "ZMax")],
        "solid_closed": [solid.isClosed() for solid in shape.Solids],
        "solid_volumes_mm3": [solid.Volume for solid in shape.Solids],
        "must_execute": bool(obj.MustExecute), "state": list(obj.State),
    }


def controls(doc):
    rail = doc.getObject("R67C16CompleteRail")
    cut = doc.getObject("R67C16BoredRail")
    tools = doc.getObject("R67C16CrownBores")
    wrapper = doc.getObject("Structure671")
    return {
        "rail_inputs": [obj.Name for obj in rail.Shapes],
        "tool_links": [obj.Name for obj in tools.Links],
        "rail_refine": bool(rail.Refine), "cut_refine": bool(cut.Refine),
        "cut_base": cut.Base.Name, "cut_tool": cut.Tool.Name,
        "wrapper_base": wrapper.Base.Name,
        "additions": [obj.Name for obj in wrapper.Additions],
        "subtractions": [obj.Name for obj in wrapper.Subtractions],
        "axis": str(wrapper.Axis), "clone_of": str(wrapper.CloneOf),
        "placement": str(wrapper.Placement),
        "wrapper_has_refine": "Refine" in wrapper.PropertiesList,
        "material": wrapper.Material.Name if wrapper.Material else None,
        "input_refines": {obj.Name: bool(obj.Refine) for obj in rail.Shapes
                          if "Refine" in obj.PropertiesList},
    }


class H88OriginalCheckpoint(unittest.TestCase):
    def test_valid_native_base_survives_stock_structure_recompute(self):
        self.assertEqual(sha(SOURCE), "570e7ffd62c4dfb95c7b0bcbb1eafab69f11c5d54152bf9fd840ad0464402a33")
        report = {"schema": "FreeCAD-h88-original-checkpoint-v1",
                  "source": str(SOURCE), "source_sha256": sha(SOURCE),
                  "runtime": App.Version(), "GuiUp": bool(App.GuiUp),
                  "no_shape_assignment": True, "no_mesh_or_solve": True,
                  "saved_output": False, "original_project_mutated": False}
        report["modules"] = module_origins()
        report["OCC_version"] = Part.OCC_VERSION
        doc = App.openDocument(str(SOURCE))
        try:
            names = ("R67C16CompleteRail", "R67C16BoredRail", "Structure671")
            report["controls_before"] = controls(doc)
            report["before"] = {name: health(doc.getObject(name)) for name in names}
            print("[H88-REPRO-BEFORE]", json.dumps(report["before"], sort_keys=True), flush=True)
            original = report["controls_before"]
            self.assertEqual(len(original["rail_inputs"]), 165)
            self.assertEqual(len(original["tool_links"]), 66)
            self.assertEqual(canonical(original["rail_inputs"]), "bc1912e0a674b370727a3c8f5914744132115a5fc6fad8ebe7551d49f32703c0")
            self.assertEqual(canonical(original["tool_links"]), "b0bec49185ec098c3fbd1384a276441136519f33b01424c5bb188557ac6925a6")
            self.assertFalse(original["rail_refine"])
            self.assertFalse(original["cut_refine"])
            self.assertEqual(original["wrapper_base"], "R67C16BoredRail")
            self.assertEqual(original["additions"], [])
            self.assertEqual(original["subtractions"], [])
            for name in names[:2]:
                self.assertTrue(report["before"][name]["valid"], name)
                self.assertEqual(report["before"][name]["solid_count"], 1)
            wrapper = doc.getObject("Structure671")
            wrapper.touch()
            returned = wrapper.recompute()
            report["recompute_returned"] = returned
            report["controls_after"] = controls(doc)
            report["after"] = {name: health(doc.getObject(name)) for name in names}
            self.assertEqual(report["controls_after"], original)
            self.assertIs(returned, True)
            self.assertTrue(report["after"]["R67C16BoredRail"]["valid"])
            observed = report["after"]["Structure671"]
            print("[H88-REPRO-AFTER]", json.dumps(report["after"], sort_keys=True), flush=True)
            self.assertTrue(observed["valid"], "Stock BIM wrapper made a valid native Base invalid")
            self.assertEqual(observed["solid_count"], 1)
            self.assertTrue(observed["closed"])
            self.assertTrue(math.isclose(observed["volume_mm3"],
                                        report["after"]["R67C16BoredRail"]["volume_mm3"],
                                        rel_tol=1e-12, abs_tol=1e-6))
            report["material_differences"] = material_differences(
                self, doc.getObject("R67C16BoredRail").Shape, wrapper.Shape)
            report["passed"] = True
        finally:
            App.closeDocument(doc.Name)
            report["source_unchanged"] = sha(SOURCE) == report["source_sha256"]
            with (RUN / "observation.json").open("x") as stream:
                json.dump(report, stream, indent=2)
                stream.write("\n")


def load_tests(loader, _tests, _pattern):
    return loader.loadTestsFromTestCase(H88OriginalCheckpoint)
