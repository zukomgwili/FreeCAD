"""Common source-build identity, not a solve or candidate acceptance.

Authored by the private QA evidence agent; root alone reviews and executes it.
The stock export sidecar, not this metadata test, proves default selection.
"""
import hashlib
import ctypes
import importlib
import json
import os
from pathlib import Path
import sys
import unittest

import FreeCAD as App
import Fem
import Part
import Materials
from large_config import BUILD, COMMIT, REVISION, NATIVE_SHA

sys.dont_write_bytecode = True


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


class TestQ37LargeIdentity(unittest.TestCase):
    def test_common_build_runtime_manifest_and_selected_suite(self):
        run = Path(os.environ['Q37L_OUTPUT'])
        report = {'schema': 'FreeCAD-3q7-large-build-identity-v1', 'passed': False,
                  'authorship': 'Private QA evidence agent; root-only execution',
                  'metadata_identity_only_not_default_selection_or_physical_acceptance': True}
        try:
            manifest_path = Path(os.environ['Q37L_MANIFEST'])
            self.assertEqual(manifest_path.parent.resolve(), run.resolve())
            manifest_bytes = manifest_path.read_bytes()
            self.assertEqual(digest(manifest_bytes), os.environ['Q37L_MANIFEST_SHA'])
            manifest = json.loads(manifest_bytes)
            inputs, pins = manifest['inputs'], manifest['compiled_native_pins']
            build = Path(BUILD).resolve()
            version = list(App.Version())
            self.assertEqual(version[3], REVISION)
            self.assertEqual(version[-1], COMMIT)
            self.assertEqual(Path(App.getHomePath()).resolve(), build)
            dyld = ctypes.CDLL('/usr/lib/libSystem.B.dylib')
            dyld._NSGetExecutablePath.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
            size, buffer = ctypes.c_uint32(4096), ctypes.create_string_buffer(4096)
            self.assertEqual(dyld._NSGetExecutablePath(buffer, ctypes.byref(size)), 0)
            process = Path(os.fsdecode(buffer.value)).resolve()
            self.assertEqual(process, build / 'bin/FreeCADCmd')
            self.assertEqual(digest(process.read_bytes()), pins[str(process)])
            dyld._dyld_image_count.restype = ctypes.c_uint32
            dyld._dyld_get_image_name.argtypes = [ctypes.c_uint32]
            dyld._dyld_get_image_name.restype = ctypes.c_char_p
            images = [Path(os.fsdecode(dyld._dyld_get_image_name(index))).resolve()
                      for index in range(dyld._dyld_image_count())]
            library = build / 'lib/libFreeCADApp.dylib'
            self.assertEqual([path for path in images if path.name == library.name], [library])
            self.assertEqual(digest(library.read_bytes()), pins[str(library)])
            native_modules = {}
            for name, module, relative in (('Fem', Fem, 'Mod/Fem/Fem.so'),
                    ('Part', Part, 'Mod/Part/Part.so'),
                    ('Materials', Materials, 'Mod/Material/Materials.so')):
                actual = Path(module.__file__).resolve()
                self.assertEqual(actual, build / relative)
                self.assertEqual(digest(actual.read_bytes()), pins[str(actual)])
                native_modules[name] = {'path': str(actual), 'sha256': pins[str(actual)]}
            sources = {}
            for name in ('femtools.ccxtools', 'femtest.app.coupled_port_fixture'):
                path = Path(importlib.import_module(name).__file__).resolve()
                self.assertTrue(path.is_relative_to(build / 'Mod/Fem'), str(path))
                actual = digest(path.read_bytes())
                self.assertEqual(actual, inputs[str(path)], str(path))
                sources[name] = {'path': str(path), 'sha256': actual}
            native = build / 'data/NativeSolvers/ccx-force-accounting'
            self.assertEqual(digest(native.read_bytes()), NATIVE_SHA)
            self.assertEqual(pins[str(native)], NATIVE_SHA)
            self.assertIn(str(build / 'bin/FreeCADCmd'), pins)
            for literal, wanted in pins.items():
                path = Path(literal)
                self.assertTrue(path.is_absolute() and path.resolve().is_relative_to(build))
                self.assertEqual(digest(path.read_bytes()), wanted, literal)
            selected = importlib.import_module('Q37LargeProfile')
            origin = Path(selected.__file__).resolve()
            self.assertEqual(origin.parent, Path(__file__).resolve().parent)
            self.assertEqual(digest(origin.read_bytes()), inputs[str(origin)])
            suite = unittest.defaultTestLoader.loadTestsFromModule(selected)
            self.assertEqual(suite.countTestCases(), 1, 'Exactly one profile test, no inherited tests')
            report.update(passed=True, runtime=version, getHomePath=App.getHomePath(),
                build=str(build), manifest={'path': str(manifest_path), 'sha256': digest(manifest_bytes)},
                process={'path': str(process), 'sha256': pins[str(process)]},
                app_library={'path': str(library), 'sha256': pins[str(library)]},
                loaded_native_modules=native_modules,
                sources=sources, native={'path': str(native), 'sha256': NATIVE_SHA},
                compiled_native_pins=pins,
                selected_module={'path': str(origin), 'sha256': inputs[str(origin)], 'tests': 1})
        finally:
            with (run / 'identity.json').open('x') as stream:
                json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
                stream.write('\n')
