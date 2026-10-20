"""Installed +221 identity only; no source/build import or current-HEAD claim."""
import sys
sys.dont_write_bytecode = True
import ctypes
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import unittest

import FreeCAD as App
import Fem
import Materials
import Part

APP = Path('/Applications/FreeCAD-27.1.0.app')
RESOURCES = APP / 'Contents/Resources'
BASELINE = Path('/Users/zukomgwili/src/FreeCAD/package/local-completion/freecad-ywu-installation-evidence/private/installed-endload/identity.json')
NATIVE_SHA = '2d59adb06736801f730de077a5f3dbfcfba8c0a430636e5814e5582606b5c89b'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class InstalledIdentity(unittest.TestCase):
    def test_exact_installed_application_and_bundled_native_solver(self):
        report = {'passed': False, 'runtime': App.Version(), 'application': str(APP)}
        try:
            baseline = json.loads(BASELINE.read_text())
            self.assertEqual(App.Version()[3], '49261 +221 (Git)')
            self.assertEqual(App.Version()[-1], '6cdc1affda07ac4e3b45a98097b7ae11039c80c6')
            self.assertFalse(App.GuiUp)
            self.assertEqual(Path(App.getHomePath()).resolve(), RESOURCES)
            for value in sys.path:
                if value:
                    actual = Path(value).resolve()
                    self.assertFalse(actual.is_relative_to(Path('/Users/zukomgwili/src/FreeCAD/src')))
                    self.assertFalse(actual.is_relative_to(Path('/Users/zukomgwili/src/FreeCAD/build')))
            dyld = ctypes.CDLL('/usr/lib/libSystem.B.dylib')
            dyld._NSGetExecutablePath.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
            size = ctypes.c_uint32(4096)
            buffer = ctypes.create_string_buffer(size.value)
            self.assertEqual(dyld._NSGetExecutablePath(buffer, ctypes.byref(size)), 0)
            executable = Path(os.fsdecode(buffer.value)).resolve()
            self.assertEqual(executable, RESOURCES / 'bin/FreeCADCmd')
            self.assertEqual(sha(executable), baseline['process_executable']['sha256'])
            dyld._dyld_image_count.restype = ctypes.c_uint32
            dyld._dyld_get_image_name.argtypes = [ctypes.c_uint32]
            dyld._dyld_get_image_name.restype = ctypes.c_char_p
            images = [Path(os.fsdecode(dyld._dyld_get_image_name(index))).resolve()
                      for index in range(dyld._dyld_image_count())]
            library = RESOURCES / 'lib/libFreeCADApp.dylib'
            self.assertEqual([path for path in images if path.name == library.name], [library])
            self.assertEqual(sha(library), baseline['app_library']['sha256'])
            for name, module in (('Fem', Fem), ('Materials', Materials), ('Part', Part)):
                actual = Path(module.__file__).resolve()
                self.assertEqual(actual, RESOURCES / 'lib' / (name + '.so'))
                self.assertEqual(sha(actual), baseline['native_modules'][name]['sha256'])
            for name in ('ObjectsFem', 'femtools.ccxtools', 'femmesh.gmshtools'):
                actual = Path(importlib.import_module(name).__file__).resolve()
                pin = baseline['copied_modules'][name]
                self.assertEqual(str(actual), pin['origin'])
                self.assertEqual(sha(actual), pin['sha256'])
            binary = RESOURCES / 'data/NativeSolvers/ccx-force-accounting'
            self.assertEqual(sha(binary), NATIVE_SHA)
            capability = subprocess.run([str(binary), '--freecad-force-accounting-version'],
                                        check=True, capture_output=True, text=True, timeout=10).stdout.strip()
            self.assertEqual(capability, 'CCX_FORCE_ACCOUNTING_V3')
            report.update(passed=True, executable=str(executable), native_binary=str(binary),
                          native_sha256=sha(binary), capability=capability,
                          prior_installed_identity=str(BASELINE), prior_identity_sha256=sha(BASELINE))
        finally:
            with (Path(os.environ['YZK_OUTPUT']) / 'identity.json').open('x') as stream:
                stream.write(json.dumps(report, indent=2) + '\n')
