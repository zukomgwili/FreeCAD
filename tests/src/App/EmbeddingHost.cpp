// SPDX-License-Identifier: LGPL-2.1-or-later

#include <Python.h>

// Test-only host: unlike a statically linked Python executable, this shares
// the configured Python runtime with the FreeCAD import module.
int main(int argc, char** argv)
{
    return Py_BytesMain(argc, argv);
}
