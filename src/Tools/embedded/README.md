# Embedding FreeCAD

An importing Python host must use the same initialized Python runtime as
FreeCAD's libraries. Matching the Python major/minor version alone is not
sufficient. In particular, a macOS Python executable may statically embed
Python while `FreeCAD.so` links a separate `libpython` dylib. Adding the FreeCAD
library directory to that executable's `PYTHONPATH` does not make those two
runtime instances compatible. FreeCAD rejects this combination with
`ImportError`, before initializing the application.

For Python automation without an external embedding host, use the existing
`FreeCADCmd` executable with a script file:

```sh
build/release/bin/FreeCADCmd automation.py
```

This executable initializes FreeCAD and its configured Python runtime before
running the script. Use the `FreeCADCmd` that belongs to the installation you
intend to automate; it is not necessary to import the installed module using
an unrelated Python executable.

For a custom embedding application, link the host to the same shared Python
library used by FreeCAD, initialize that runtime, and add the corresponding
FreeCAD library directory to Python's module search path. Use the matching
Python standard library and dependencies as well. Do not initialize a second
Python runtime to work around a failed import.

The test-only `FreeCAD_EmbeddingHost` and `FreeCAD_EmbeddingRuntime` CTest
exercise direct shared-runtime import, safe rejection of incompatible hosts,
and the existing `FreeCADCmd` script path. The test host is not an installed
Python launcher.
