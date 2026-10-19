"""Reuse the real native CAD/Gmsh/solver/import lifetime regression unchanged."""
import os
from pathlib import Path
import sys

sys.path.insert(0, "/Users/zukomgwili/src/FreeCAD/package/local-completion")
os.environ["FREECAD_4JB_OUTPUT"] = os.environ["FREECAD_3SC_OUTPUT"]
from FreeCAD4jbWitness import MaterialLifetimePipelineWitness
